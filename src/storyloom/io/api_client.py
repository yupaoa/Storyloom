"""OpenAI-compatible API client using urllib (standard library only).

Reads API configuration from UserConfig, with os.environ as override.
Supports streaming (SSE) and non-streaming chat completions.
"""

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass

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

    def _build_request(
        self, messages: list[dict], stream: bool = True
    ) -> urllib.request.Request:
        """Build a POST Request to the chat completions endpoint."""
        url = f"{self.base_url}/v1/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        return urllib.request.Request(
            url, data=body, headers=headers, method="POST"
        )

    @staticmethod
    def _handle_http_error(e: urllib.error.HTTPError) -> None:
        """Convert HTTPError to ApiError with readable message."""
        try:
            detail = json.loads(e.read())
            msg = detail.get("error", {}).get("message", str(e))
        except Exception:
            msg = str(e)
        raise ApiError(f"HTTP {e.code}: {msg}") from e

    def stream_chat_iter(self, messages: list[dict]) -> Iterator[dict]:
        """Yield streaming chat tokens one by one.

        Each yielded dict has:
          {"delta": str}           — content token (first token also has "ttft": float)
          {"usage": dict, "done": True}  — final chunk with token counts

        Args:
            messages: List of message dicts with role and content keys.

        Yields:
            Token dicts as described above.

        Raises:
            ApiError: On network errors, HTTP errors, or malformed responses.
        """
        request = self._build_request(messages, stream=True)
        t_start = time.perf_counter()
        ttft: float | None = None

        try:
            with urllib.request.urlopen(request, timeout=STREAM_STALL_TIMEOUT_SEC) as response:
                status = response.status
                if status >= 400:
                    raise ApiError(
                        f"HTTP {status}: API returned error during streaming"
                    )

                while True:
                    line = response.readline()
                    if not line:
                        break

                    raw = line.decode("utf-8", errors="replace").strip()
                    if not raw:
                        continue

                    if raw == "data: [DONE]":
                        break

                    if raw.startswith("data: "):
                        payload = raw[6:]
                        try:
                            data = json.loads(payload)
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

                        # Capture usage from final chunk (if API provides it)
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

        except urllib.error.HTTPError as e:
            self._handle_http_error(e)
        except urllib.error.URLError as e:
            raise ApiError(f"Connection error: {e.reason}") from e
        except OSError as e:
            raise ApiError(f"Network error: {e}") from e

    def stream_chat(self, messages: list[dict]) -> ApiResult:
        """Send messages via streaming API, collect and return the full response.

        Convenience wrapper around stream_chat_iter() for callers that want
        the full result at once.

        Args:
            messages: List of message dicts with role and content keys.

        Returns:
            ApiResult with content, TTFT (time to first token), and token usage.

        Raises:
            ApiError: On network errors, HTTP errors, or malformed responses.
        """
        collected: list[str] = []
        ttft: float | None = None
        tokens: dict | None = None

        for chunk in self.stream_chat_iter(messages):
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

    def chat(self, messages: list[dict]) -> str:
        """Non-streaming chat for one-shot calls.

        Args:
            messages: List of message dicts with role and content keys.

        Returns:
            Content string from the assistant response.

        Raises:
            ApiError: On network errors, HTTP errors, or malformed responses.
        """
        request = self._build_request(messages, stream=False)

        try:
            with urllib.request.urlopen(request, timeout=STREAM_STALL_TIMEOUT_SEC) as response:
                status = response.status
                if status >= 400:
                    raise ApiError(
                        f"HTTP {status}: API returned error"
                    )

                body = response.read()
                data = json.loads(body)

                # Check for API-level error in response body
                if "error" in data:
                    msg = data["error"].get("message", "Unknown API error")
                    raise ApiError(f"API error: {msg}")

                choices = data.get("choices", [])
                if not choices:
                    raise ApiError("No choices in API response")

                content = choices[0].get("message", {}).get("content", "")
                return content

        except urllib.error.HTTPError as e:
            self._handle_http_error(e)
        except urllib.error.URLError as e:
            raise ApiError(f"Connection error: {e.reason}") from e
        except OSError as e:
            raise ApiError(f"Network error: {e}") from e
