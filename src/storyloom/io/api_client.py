"""OpenAI-compatible API client using httpx with connection pooling.

Reads API configuration from UserConfig, with os.environ as override.
Supports streaming (SSE) and non-streaming chat completions.
"""

import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

from storyloom.config import DEFAULT_MODEL, STREAM_STALL_TIMEOUT_SEC


class ApiError(Exception):
    """Raised on API call failures (network, HTTP, or response errors)."""
    pass


@dataclass
class ApiResult:
    """Result of a streaming API call."""
    content: str
    ttft: float | None        # seconds to first content token
    tokens: dict | None       # {"prompt": N, "completion": N, "total": N}


class ApiClient:
    """OpenAI-compatible chat completion API client.

    Reads credentials from UserConfig, with os.environ as override.
    Uses httpx.Client for connection pooling — TCP connections and
    CONNECT tunnels (through proxies) are reused across requests.

    Supports streaming (SSE) via stream_chat() and one-shot via chat().
    """

    def __init__(self, config: "UserConfig | None" = None):
        from storyloom.user_config import UserConfig
        cfg = config if config is not None else UserConfig()

        self.api_key = os.environ.get("LLM_API_KEY") or cfg.api_key
        self.base_url = (
            os.environ.get("LLM_BASE_URL") or cfg.api_base_url
        ).rstrip("/")
        self.model = (
            os.environ.get("LLM_MODEL") or cfg.api_model or DEFAULT_MODEL
        )

        self._validate_config()

        # Connection pool — reused across all calls.
        # httpx auto-reads HTTP_PROXY / HTTPS_PROXY / NO_PROXY from env.
        self._client = httpx.Client(
            timeout=httpx.Timeout(STREAM_STALL_TIMEOUT_SEC, connect=30.0),
            follow_redirects=True,
        )

    def _validate_config(self) -> None:
        """Validate that required config is present."""
        if not self.api_key:
            raise RuntimeError(
                "API Key not found. Set it in the application settings "
                "or via the LLM_API_KEY environment variable."
            )
        if not self.base_url:
            raise RuntimeError(
                "Base URL not found. Set it in the application settings "
                "or via the LLM_BASE_URL environment variable."
            )

    # ── request helpers ──────────────────────────────────────────────

    def _build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _build_payload(
        self,
        messages: list[dict],
        stream: bool = False,
        max_tokens: int | None = None,
    ) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    # ── error handling ────────────────────────────────────────────────

    @staticmethod
    def _handle_http_error(response: httpx.Response) -> None:
        """Convert HTTP error response to ApiError with readable message."""
        raw_body = response.text
        try:
            detail = json.loads(raw_body)
            msg = detail.get("error", {}).get("message", str(response.status_code))
        except (json.JSONDecodeError, ValueError):
            snippet = raw_body[:500] if raw_body else "(empty body)"
            msg = f"Non-JSON response: {snippet}"
        raise ApiError(f"HTTP {response.status_code}: {msg}")

    @staticmethod
    def _extract_content(data: dict) -> str:
        """Extract message content, handling reasoning model nulls.

        Also strips lone surrogates (``\\udcef`` etc.) that some LLMs
        emit in their output.  These would break ``json.dumps`` on the
        next request when the text is sent back in the messages array.
        """
        choices = data.get("choices", [])
        if not choices:
            raise ApiError("No choices in API response")
        content = choices[0].get("message", {}).get("content")
        if content is None:
            content = ""
        # Strip lone surrogates — encode then decode to replace them
        return content.encode("utf-8", errors="replace").decode("utf-8")

    # ── public API ────────────────────────────────────────────────────

    def chat(
        self, messages: list[dict], max_tokens: int | None = None
    ) -> str:
        """Non-streaming chat for one-shot calls.

        Args:
            messages: List of message dicts with role and content keys.
            max_tokens: Optional max completion tokens (None = API default).

        Returns:
            Content string from the assistant response.

        Raises:
            ApiError: On network errors, HTTP errors, or malformed responses.
        """
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(messages, stream=False, max_tokens=max_tokens)

        try:
            response = self._client.post(
                url, json=payload, headers=self._build_headers()
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            self._handle_http_error(e.response)
        except httpx.RequestError as e:
            raise ApiError(f"Connection error: {e}") from e
        except UnicodeError as e:
            raise ApiError(f"Encoding error: {e}") from e

        if "error" in data:
            msg = data["error"].get("message", "Unknown API error")
            raise ApiError(f"API error: {msg}")

        return self._extract_content(data)

    def stream_chat_iter(
        self, messages: list[dict], max_tokens: int | None = None
    ) -> Iterator[dict]:
        """Yield streaming chat tokens one by one.

        Each yielded dict has:
          {"delta": str}           — content token (first token also has "ttft": float)
          {"usage": dict, "done": True}  — final chunk with token counts

        Args:
            messages: List of message dicts with role and content keys.
            max_tokens: Optional max completion tokens (None = API default).

        Yields:
            Token dicts as described above.

        Raises:
            ApiError: On network errors, HTTP errors, or malformed responses.
        """
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(messages, stream=True, max_tokens=max_tokens)
        t_start = time.perf_counter()
        ttft: float | None = None

        try:
            with self._client.stream(
                "POST", url, json=payload, headers=self._build_headers()
            ) as response:
                if response.status_code >= 400:
                    raise ApiError(
                        f"HTTP {response.status_code}: "
                        f"API returned error during streaming"
                    )

                for line_bytes in response.iter_lines():
                    if not line_bytes:
                        continue

                    # httpx.iter_lines() returns str; decode if bytes (safety net)
                    if isinstance(line_bytes, bytes):
                        raw = line_bytes.decode("utf-8", errors="replace").strip()
                    else:
                        raw = line_bytes.strip()
                    if not raw:
                        continue

                    if raw == "data: [DONE]":
                        break

                    if raw.startswith("data: "):
                        payload_str = raw[6:]
                        try:
                            data = json.loads(payload_str)
                        except json.JSONDecodeError:
                            continue

                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            chunk = {"delta": content}
                            if ttft is None:
                                ttft = time.perf_counter() - t_start
                                chunk["ttft"] = ttft
                            yield chunk

                        # Capture usage from final chunk
                        if "usage" in data:
                            u = data["usage"]
                            yield {
                                "usage": {
                                    "prompt": u.get("prompt_tokens"),
                                    "completion": u.get("completion_tokens"),
                                    "total": u.get("total_tokens"),
                                },
                                "done": True,
                            }

        except httpx.HTTPStatusError as e:
            self._handle_http_error(e.response)
        except httpx.RequestError as e:
            raise ApiError(f"Connection error: {e}") from e
        except UnicodeError as e:
            raise ApiError(f"Encoding error: {e}") from e

    def stream_chat(
        self, messages: list[dict], max_tokens: int | None = None
    ) -> ApiResult:
        """Send messages via streaming API, collect and return the full response.

        Convenience wrapper around stream_chat_iter() for callers that want
        the full result at once.

        Args:
            messages: List of message dicts with role and content keys.
            max_tokens: Optional max completion tokens (None = API default).

        Returns:
            ApiResult with content, TTFT (time to first token), and token usage.

        Raises:
            ApiError: On network errors, HTTP errors, or malformed responses.
        """
        collected: list[str] = []
        ttft: float | None = None
        tokens: dict | None = None

        for chunk in self.stream_chat_iter(messages, max_tokens=max_tokens):
            if chunk.get("done"):
                tokens = chunk.get("usage")
            else:
                if chunk.get("ttft") is not None:
                    ttft = chunk["ttft"]
                collected.append(chunk["delta"])

        return ApiResult(
            content="".join(collected),
            ttft=ttft,
            tokens=tokens,
        )

    # ── lifecycle ────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the underlying HTTP client connection pool."""
        self._client.close()

    def __del__(self) -> None:
        if hasattr(self, "_client"):
            self._client.close()
