"""Tests for api_client module."""

import json
from pathlib import Path

import pytest
from src.storyloom.api_client import ApiClient, ApiError


# ── Helpers ────────────────────────────────────────────────────────

class MockStreamResponse:
    """Simulate urllib response object for streaming SSE tests."""

    def __init__(self, chunks: list[str], status: int = 200):
        self._chunks = [c.encode() for c in chunks]
        self.status = status

    def readline(self):
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return b"".join(self._chunks)


class MockJsonResponse:
    """Simulate urllib response returning a JSON body."""

    def __init__(self, data: dict, status: int = 200):
        self.body = json.dumps(data).encode()
        self.status = status

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# ── Tests ──────────────────────────────────────────────────────────

class TestApiClientInit:
    def test_loads_from_env(self):
        """Client should load API key, base URL and model from environment."""
        client = ApiClient()
        assert client.api_key is not None
        assert len(client.api_key) > 0
        assert client.base_url is not None
        assert client.model is not None

    def test_raises_without_api_key(self, monkeypatch):
        """Client should raise RuntimeError when DEEPSEEK_API_KEY is missing
        and no .env file is present."""
        monkeypatch.setattr(
            "src.storyloom.api_client.ApiClient._load_env",
            lambda self: None,  # simulate no env loaded
        )
        with pytest.raises(RuntimeError, match="API Key"):
            ApiClient()

    def test_raises_without_base_url(self, monkeypatch):
        """Client should raise RuntimeError when DEEPSEEK_BASE_URL is missing."""
        monkeypatch.setattr(
            "src.storyloom.api_client._find_project_root",
            # Return a dir with no .env so env vars are fallback-only
            lambda: Path("/tmp/nonexistent_storyloom"),
        )
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="Base URL"):
            ApiClient()


class TestApiClientStreamChat:
    def test_stream_collects_chunks(self, monkeypatch):
        """Streaming should concatenate all content delta chunks."""
        chunks = [
            'data: {"choices":[{"delta":{"content":"hello "}}]}\n',
            'data: {"choices":[{"delta":{"content":"world"}}]}\n',
            'data: {"choices":[{"delta":{"content":""}}]}\n',
            'data: [DONE]\n',
        ]

        def mock_open(*args, **kwargs):
            return MockStreamResponse(chunks)

        monkeypatch.setattr("urllib.request.urlopen", mock_open)

        client = ApiClient()
        result = client.stream_chat([{"role": "user", "content": "hi"}])
        assert result == "hello world"

    def test_stream_handles_empty_response(self, monkeypatch):
        """Streaming should return empty string for no content chunks."""
        chunks = ['data: {"choices":[{"delta":{}}]}\n', 'data: [DONE]\n']

        def mock_open(*args, **kwargs):
            return MockStreamResponse(chunks)

        monkeypatch.setattr("urllib.request.urlopen", mock_open)

        client = ApiClient()
        result = client.stream_chat([{"role": "user", "content": "hi"}])
        assert result == ""

    def test_stream_raises_on_http_error(self, monkeypatch):
        """Streaming should raise ApiError on non-200 status codes."""

        def mock_open(*args, **kwargs):
            return MockStreamResponse([], status=401)

        monkeypatch.setattr("urllib.request.urlopen", mock_open)

        client = ApiClient()
        with pytest.raises(ApiError, match="401"):
            client.stream_chat([{"role": "user", "content": "hi"}])

    def test_stream_raises_on_connection_error(self, monkeypatch):
        """Streaming should raise ApiError on connection failures."""

        def mock_open(*args, **kwargs):
            raise ConnectionError("Connection refused")

        monkeypatch.setattr("urllib.request.urlopen", mock_open)

        client = ApiClient()
        with pytest.raises(ApiError):
            client.stream_chat([{"role": "user", "content": "hi"}])

    def test_stream_skips_non_content_lines(self, monkeypatch):
        """Streaming should skip lines without content."""
        chunks = [
            'data: {"choices":[{"delta":{"role":"assistant"}}]}\n',
            'data: {"choices":[{"delta":{"content":"hello"}}]}\n',
            'data: [DONE]\n',
        ]

        def mock_open(*args, **kwargs):
            return MockStreamResponse(chunks)

        monkeypatch.setattr("urllib.request.urlopen", mock_open)

        client = ApiClient()
        result = client.stream_chat([{"role": "user", "content": "hi"}])
        assert result == "hello"

    def test_stream_handles_multiline_data(self, monkeypatch):
        """Streaming should handle lines that span multiple SSE lines."""
        chunks = [
            'data: {"choices":[{"delta":{"content":"line1\\nline2"}}]}\n',
            'data: [DONE]\n',
        ]

        def mock_open(*args, **kwargs):
            return MockStreamResponse(chunks)

        monkeypatch.setattr("urllib.request.urlopen", mock_open)

        client = ApiClient()
        result = client.stream_chat([{"role": "user", "content": "hi"}])
        assert "line1" in result
        assert "line2" in result


class TestApiClientChat:
    def test_non_streaming_returns_content(self, monkeypatch):
        """Non-streaming chat should return content from JSON response."""

        def mock_open(*args, **kwargs):
            return MockJsonResponse({
                "choices": [{"message": {"content": "Hello world"}}]
            })

        monkeypatch.setattr("urllib.request.urlopen", mock_open)

        client = ApiClient()
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "Hello world"

    def test_raises_on_http_error(self, monkeypatch):
        """Non-streaming chat should raise ApiError on HTTP error."""

        def mock_open(*args, **kwargs):
            return MockJsonResponse({"error": "Unauthorized"}, status=401)

        monkeypatch.setattr("urllib.request.urlopen", mock_open)

        client = ApiClient()
        with pytest.raises(ApiError, match="401"):
            client.chat([{"role": "user", "content": "hi"}])

    def test_raises_on_connection_error(self, monkeypatch):
        """Non-streaming chat should raise ApiError on connection failure."""

        def mock_open(*args, **kwargs):
            raise ConnectionError("Connection refused")

        monkeypatch.setattr("urllib.request.urlopen", mock_open)

        client = ApiClient()
        with pytest.raises(ApiError):
            client.chat([{"role": "user", "content": "hi"}])

    def test_raises_on_missing_choices(self, monkeypatch):
        """Non-streaming chat should raise ApiError when response has no choices."""

        def mock_open(*args, **kwargs):
            return MockJsonResponse({})

        monkeypatch.setattr("urllib.request.urlopen", mock_open)

        client = ApiClient()
        with pytest.raises(ApiError, match="No choices"):
            client.chat([{"role": "user", "content": "hi"}])


class TestApiClientBuildRequest:
    def test_request_contains_expected_headers(self, monkeypatch):
        """The HTTP request should have correct headers."""
        captured_headers = {}

        def mock_open(request, **kwargs):
            # Access internal headers dict (keys may be lower/title-cased)
            for key, val in request.headers.items():
                captured_headers[key] = val
            return MockStreamResponse(['data: [DONE]\n'])

        monkeypatch.setattr("urllib.request.urlopen", mock_open)

        client = ApiClient()
        client.stream_chat([{"role": "user", "content": "hi"}])

        # Check case-insensitively
        header_keys_lower = {k.lower(): v for k, v in captured_headers.items()}
        assert header_keys_lower.get("content-type") == "application/json"
        assert "bearer" in header_keys_lower.get("authorization", "").lower()

    def test_request_has_correct_method_and_url(self, monkeypatch):
        """The HTTP request should use POST to the chat completions endpoint."""
        captured = {}

        def mock_open(request, **kwargs):
            captured["method"] = request.method
            captured["url"] = request.full_url
            return MockStreamResponse(['data: [DONE]\n'])

        monkeypatch.setattr("urllib.request.urlopen", mock_open)

        client = ApiClient()
        client.stream_chat([{"role": "user", "content": "hi"}])

        assert captured["method"] == "POST"
        assert "chat/completions" in captured["url"]
