"""Tests for api_client module."""

import json
import pytest
from storyloom.io.api_client import ApiClient, ApiError
from storyloom.user_config import UserConfig


# ── Fixture ─────────────────────────────────────────────────────
@pytest.fixture
def cfg():
    """Headless UserConfig with test API key."""
    c = UserConfig()
    c.api_key = "sk-test-key"
    c.api_base_url = "https://api.test.com"
    c.api_model = "test-model"
    return c


class MockHTTPResponse:
    """Simulate urllib response for streaming tests."""
    def __init__(self, chunks, status=200):
        self._chunks = chunks
        self.status = status
        self._index = 0

    def readline(self):
        if self._index < len(self._chunks):
            line = self._chunks[self._index]
            self._index += 1
            return line.encode() if isinstance(line, str) else line
        return b""

    def read(self):
        return b"".join(
            c.encode() if isinstance(c, str) else c for c in self._chunks
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def close(self):
        pass


class TestApiClientInit:
    def test_loads_config_from_user_config(self, cfg):
        client = ApiClient(cfg)
        assert client.api_key == "sk-test-key"
        assert client.base_url == "https://api.test.com"
        assert client.model == "test-model"

    def test_env_var_overrides_config(self, cfg, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-from-env")
        client = ApiClient(cfg)
        assert client.api_key == "sk-from-env"

    def test_raises_when_no_api_key(self, monkeypatch):
        """If config has no key and env has no key, should raise."""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        c = UserConfig()
        c.api_key = ""
        with pytest.raises(RuntimeError, match="API Key not found"):
            ApiClient(c)


class TestStreamChat:
    def test_collects_sse_chunks(self, cfg, monkeypatch):
        def mock_urlopen(req, timeout=None):
            return MockHTTPResponse([
                'data: {"choices":[{"delta":{"content":"hello"}}]}\n',
                'data: {"choices":[{"delta":{"content":" world"}}]}\n',
                'data: [DONE]\n',
            ])
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient(cfg)
        result = client.stream_chat([{"role": "user", "content": "hi"}])
        assert result.content == "hello world"
        assert isinstance(result.ttft, float)

    def test_handles_empty_delta(self, cfg, monkeypatch):
        def mock_urlopen(req, timeout=None):
            return MockHTTPResponse([
                'data: {"choices":[{"delta":{}}]}\n',
                'data: [DONE]\n',
            ])
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient(cfg)
        result = client.stream_chat([{"role": "user", "content": "hi"}])
        assert result.content == ""

    def test_raises_on_connection_error(self, cfg, monkeypatch):
        def mock_urlopen(req, timeout=None):
            raise OSError("Connection refused")
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient(cfg)
        with pytest.raises(ApiError, match="Connection"):
            client.stream_chat([{"role": "user", "content": "hi"}])

    def test_raises_on_http_error(self, cfg, monkeypatch):
        from urllib.error import HTTPError
        def mock_urlopen(req, timeout=None):
            resp = MockHTTPResponse([], status=401)
            raise HTTPError("http://fake", 401, "Unauthorized", {}, resp)
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient(cfg)
        with pytest.raises(ApiError, match="401"):
            client.stream_chat([{"role": "user", "content": "hi"}])

    def test_sends_correct_json_payload(self, cfg, monkeypatch):
        captured_data = {}
        def mock_urlopen(req, timeout=None):
            captured_data["body"] = json.loads(req.data.decode())
            return MockHTTPResponse(['data: [DONE]\n'])
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient(cfg)
        messages = [{"role": "user", "content": "hello"}]
        client.stream_chat(messages)
        assert captured_data["body"]["messages"] == messages
        assert captured_data["body"]["stream"] is True


class TestNonStreamingChat:
    def test_returns_content(self, cfg, monkeypatch):
        response_json = json.dumps({
            "choices": [{"message": {"content": "hello world"}}]
        })
        def mock_urlopen(req, timeout=None):
            return MockHTTPResponse([response_json])
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient(cfg)
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "hello world"

    def test_raises_on_api_error(self, cfg, monkeypatch):
        response_json = json.dumps({
            "error": {"message": "Rate limit exceeded"}
        })
        def mock_urlopen(req, timeout=None):
            return MockHTTPResponse([response_json])
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient(cfg)
        with pytest.raises(ApiError, match="Rate limit"):
            client.chat([{"role": "user", "content": "hi"}])
