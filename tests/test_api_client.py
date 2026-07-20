"""Tests for api_client module."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from storyloom.io.api_client import ApiClient, ApiError
from storyloom.user_config import UserConfig


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def cfg():
    """Headless UserConfig with test API key."""
    c = UserConfig()
    c.api_key = "sk-test-key"
    c.api_base_url = "https://api.test.com"
    c.api_model = "test-model"
    return c


@pytest.fixture
def mock_http():
    """Mock httpx.Client — inject via api._client."""
    return MagicMock(spec=httpx.Client)


@pytest.fixture
def client(cfg, mock_http):
    """ApiClient with mocked httpx.Client (injected after construction
    since the real client is now created lazily on first API call)."""
    c = ApiClient(cfg)
    c._client = mock_http
    return c


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Build a MagicMock simulating httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = json.dumps(json_data, ensure_ascii=False)
    return resp


# ── Init ─────────────────────────────────────────────────────────────

class TestApiClientInit:
    def test_loads_config_from_user_config(self, cfg):
        with patch("storyloom.io.api_client.httpx.Client"):
            client = ApiClient(cfg)
        assert client.api_key == "sk-test-key"
        assert client.base_url == "https://api.test.com"
        assert client.model == "test-model"

    def test_env_var_overrides_config(self, cfg, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-from-env")
        with patch("storyloom.io.api_client.httpx.Client"):
            client = ApiClient(cfg)
        assert client.api_key == "sk-from-env"

    def test_raises_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        c = UserConfig()
        c.api_key = ""
        client = ApiClient(c)
        with pytest.raises(RuntimeError, match="API Key not found"):
            client.chat([{"role": "user", "content": "hi"}])


# ── Non-streaming chat ───────────────────────────────────────────────

class TestNonStreamingChat:
    def test_returns_content(self, client, mock_http):
        mock_http.post.return_value = _mock_response({
            "choices": [{"message": {"content": "hello world"}}]
        })
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "hello world"

    def test_handles_null_content(self, client, mock_http):
        """Reasoning model returns content: null → return ''."""
        mock_http.post.return_value = _mock_response({
            "choices": [{"message": {"content": None}}]
        })
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result == ""

    def test_raises_on_api_error(self, client, mock_http):
        mock_http.post.return_value = _mock_response({
            "error": {"message": "Rate limit exceeded"}
        })
        with pytest.raises(ApiError, match="Rate limit"):
            client.chat([{"role": "user", "content": "hi"}])

    def test_raises_on_http_error(self, client, mock_http):
        resp = _mock_response({}, status_code=400)
        resp.text = '<html>Bad Request</html>'
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=resp
        )
        mock_http.post.return_value = resp
        with pytest.raises(ApiError, match=r"HTTP 400"):
            client.chat([{"role": "user", "content": "hi"}])

    def test_shows_raw_body_on_non_json_error(self, client, mock_http):
        """Non-JSON error body (e.g. proxy HTML) shown in message."""
        resp = _mock_response({}, status_code=400)
        resp.text = '<html>Proxy Error</html>'
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=resp
        )
        mock_http.post.return_value = resp
        with pytest.raises(ApiError, match="Proxy Error"):
            client.chat([{"role": "user", "content": "hi"}])

    def test_raises_on_connection_error(self, client, mock_http):
        mock_http.post.side_effect = httpx.RequestError("Connection refused")
        with pytest.raises(ApiError, match="Connection"):
            client.chat([{"role": "user", "content": "hi"}])

    def test_passes_max_tokens(self, client, mock_http):
        mock_http.post.return_value = _mock_response({
            "choices": [{"message": {"content": "ok"}}]
        })
        client.chat([{"role": "user", "content": "hi"}], max_tokens=100)
        payload = mock_http.post.call_args[1]["json"]
        assert payload["max_tokens"] == 100

    def test_omits_max_tokens_when_none(self, client, mock_http):
        mock_http.post.return_value = _mock_response({
            "choices": [{"message": {"content": "ok"}}]
        })
        client.chat([{"role": "user", "content": "hi"}])
        payload = mock_http.post.call_args[1]["json"]
        assert "max_tokens" not in payload

    def test_sends_correct_payload(self, client, mock_http):
        mock_http.post.return_value = _mock_response({
            "choices": [{"message": {"content": "ok"}}]
        })
        messages = [{"role": "user", "content": "hello"}]
        client.chat(messages)
        call_args = mock_http.post.call_args
        assert call_args[0][0] == "https://api.test.com/chat/completions"
        assert call_args[1]["json"]["messages"] == messages
        assert call_args[1]["json"]["stream"] is False


# ── Streaming ────────────────────────────────────────────────────────

def _mock_stream(lines: list[str], status_code: int = 200) -> MagicMock:
    """Build a MagicMock simulating httpx streaming context manager.

    httpx.iter_lines() returns str, not bytes.
    """
    stream = MagicMock()
    stream.__enter__.return_value = stream
    stream.status_code = status_code
    stream.iter_lines.return_value = lines
    return stream


class TestStreamChat:
    def test_collects_sse_chunks(self, client, mock_http):
        mock_http.stream.return_value = _mock_stream([
            'data: {"choices":[{"delta":{"content":"hello"}}]}\n',
            'data: {"choices":[{"delta":{"content":" world"}}]}\n',
            'data: [DONE]\n',
        ])
        result = client.stream_chat([{"role": "user", "content": "hi"}])
        assert result.content == "hello world"
        assert isinstance(result.ttft, float)

    def test_handles_empty_delta(self, client, mock_http):
        mock_http.stream.return_value = _mock_stream([
            'data: {"choices":[{"delta":{}}]}\n',
            'data: [DONE]\n',
        ])
        result = client.stream_chat([{"role": "user", "content": "hi"}])
        assert result.content == ""

    def test_raises_on_http_error_during_stream(self, client, mock_http):
        mock_http.stream.return_value = _mock_stream([], status_code=401)
        with pytest.raises(ApiError, match=r"401|HTTP"):
            client.stream_chat([{"role": "user", "content": "hi"}])

    def test_raises_on_connection_error(self, client, mock_http):
        mock_http.stream.side_effect = httpx.RequestError("Connection refused")
        with pytest.raises(ApiError, match="Connection"):
            client.stream_chat([{"role": "user", "content": "hi"}])

    def test_sends_correct_json_payload(self, client, mock_http):
        mock_http.stream.return_value = _mock_stream([
            'data: [DONE]\n',
        ])
        messages = [{"role": "user", "content": "hello"}]
        client.stream_chat(messages)
        payload = mock_http.stream.call_args[1]["json"]
        assert payload["messages"] == messages
        assert payload["stream"] is True

    def test_stream_iter_yields_usage_and_done(self, client, mock_http):
        mock_http.stream.return_value = _mock_stream([
            'data: {"choices":[{"delta":{"content":"x"}}],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}\n',
            'data: [DONE]\n',
        ])
        chunks = list(client.stream_chat_iter([{"role": "user", "content": "hi"}]))
        assert any(c.get("done") for c in chunks)
        usages = [c for c in chunks if c.get("done")]
        assert usages[0]["usage"]["total"] == 15
