"""Tests for api_client module."""

import json
import pytest
from storyloom.io.api_client import ApiClient, ApiError


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
    def test_loads_config_from_env(self):
        client = ApiClient()
        assert client.api_key is not None
        assert client.base_url is not None
        assert client.model is not None
        assert "http" in client.base_url

    def test_api_key_not_empty(self):
        client = ApiClient()
        assert len(client.api_key) > 0
        assert client.api_key.startswith("sk-")


class TestStreamChat:
    def test_collects_sse_chunks(self, monkeypatch):
        def mock_urlopen(req, timeout=None):
            return MockHTTPResponse([
                'data: {"choices":[{"delta":{"content":"hello"}}]}\n',
                'data: {"choices":[{"delta":{"content":" world"}}]}\n',
                'data: [DONE]\n',
            ])
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient()
        result = client.stream_chat([{"role": "user", "content": "hi"}])
        assert result.content == "hello world"
        assert isinstance(result.ttft, float)

    def test_handles_empty_delta(self, monkeypatch):
        def mock_urlopen(req, timeout=None):
            return MockHTTPResponse([
                'data: {"choices":[{"delta":{}}]}\n',
                'data: [DONE]\n',
            ])
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient()
        result = client.stream_chat([{"role": "user", "content": "hi"}])
        assert result.content == ""

    def test_raises_on_connection_error(self, monkeypatch):
        def mock_urlopen(req, timeout=None):
            raise OSError("Connection refused")
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient()
        with pytest.raises(ApiError, match="Connection"):
            client.stream_chat([{"role": "user", "content": "hi"}])

    def test_raises_on_http_error(self, monkeypatch):
        from urllib.error import HTTPError
        def mock_urlopen(req, timeout=None):
            resp = MockHTTPResponse([], status=401)
            raise HTTPError("http://fake", 401, "Unauthorized", {}, resp)
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient()
        with pytest.raises(ApiError, match="401"):
            client.stream_chat([{"role": "user", "content": "hi"}])

    def test_sends_correct_json_payload(self, monkeypatch):
        captured_data = {}
        def mock_urlopen(req, timeout=None):
            captured_data["body"] = json.loads(req.data.decode())
            return MockHTTPResponse(['data: [DONE]\n'])
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient()
        messages = [{"role": "user", "content": "hello"}]
        client.stream_chat(messages)
        assert captured_data["body"]["messages"] == messages
        assert captured_data["body"]["stream"] is True


class TestNonStreamingChat:
    def test_returns_content(self, monkeypatch):
        response_json = json.dumps({
            "choices": [{"message": {"content": "hello world"}}]
        })
        def mock_urlopen(req, timeout=None):
            return MockHTTPResponse([response_json])
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient()
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "hello world"

    def test_raises_on_api_error(self, monkeypatch):
        response_json = json.dumps({
            "error": {"message": "Rate limit exceeded"}
        })
        def mock_urlopen(req, timeout=None):
            return MockHTTPResponse([response_json])
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        client = ApiClient()
        with pytest.raises(ApiError, match="Rate limit"):
            client.chat([{"role": "user", "content": "hi"}])
