"""Tests for web server endpoints (co-create, game start, saves).

Uses FastAPI TestClient with mocked sessions + ApiClient.
CoCreateFlow / GameSession engine methods are NOT mocked — only
the ApiClient (to avoid real network calls) and sessions store.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from storyloom.core.co_create import CoCreateError, CoCreationResult
from storyloom.core.session import GameSession
from storyloom.io.api_client import ApiClient
from storyloom.user_config import UserConfig


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def app_dir():
    """Isolated app dir with minimal config.json so UserConfig doesn't fail."""
    with tempfile.TemporaryDirectory() as td:
        cfg = {"version": 1, "language": "zh-CN", "api_key": "sk-test",
               "api_base_url": "https://api.test.com", "api_model": "test"}
        with open(os.path.join(td, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        old = os.environ.get("STORYLOOM_APP_DIR")
        os.environ["STORYLOOM_APP_DIR"] = td
        yield Path(td)
        if old is not None:
            os.environ["STORYLOOM_APP_DIR"] = old
        else:
            del os.environ["STORYLOOM_APP_DIR"]


@pytest.fixture
def client(app_dir):
    """FastAPI TestClient with mocked ApiClient (dev_cli pattern)."""
    mock_api = MagicMock(spec=ApiClient)
    mock_api.chat.return_value = "Hello! Tell me about your story idea."

    # Patch the module-level _api_client before importing server
    with patch("storyloom.web.server._api_client", mock_api):
        from storyloom.web.server import app
        from storyloom.web import sessions
        sessions.remove_co_create()
        with TestClient(app) as tc:
            yield tc


@pytest.fixture
def client_with_session(client):
    """Client with an active co-creation session already started."""
    from storyloom.web import sessions
    from storyloom.core.co_create import CoCreateFlow
    from storyloom.web.server import _api_client

    flow = CoCreateFlow(_api_client)
    flow.start()
    sessions.store_co_create(flow)
    return client


# ═══════════════════════════════════════════════════════════════════
# Static / health
# ═══════════════════════════════════════════════════════════════════


class TestStaticEndpoints:
    def test_index_returns_html(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]

    def test_health_returns_ok(self, client):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════


class TestConfig:
    def test_get_config_returns_masked_key(self, client):
        res = client.get("/api/config")
        assert res.status_code == 200
        data = res.json()
        assert data["language"] == "zh-CN"
        assert "****" in data["api_key"] or data["api_key"] == ""

    def test_update_config_language(self, client):
        res = client.post("/api/config", json={"language": "en"})
        assert res.status_code == 200

    def test_reject_unsupported_language(self, client):
        res = client.post("/api/config", json={"language": "fr"})
        assert res.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# Co-create: start
# ═══════════════════════════════════════════════════════════════════


class TestCoCreateStart:
    def test_start_returns_phase_and_prompt(self, client):
        res = client.post("/api/co-create/start")
        assert res.status_code == 200
        data = res.json()
        assert data["phase"] == "awaiting_idea"
        assert isinstance(data["prompt"], str)
        assert len(data["prompt"]) > 0

    def test_start_stores_session(self, client):
        client.post("/api/co-create/start")
        from storyloom.web import sessions
        assert sessions.get_co_create() is not None


# ═══════════════════════════════════════════════════════════════════
# Co-create: send
# ═══════════════════════════════════════════════════════════════════


class TestCoCreateSend:
    def test_send_returns_reply(self, client_with_session):
        res = client_with_session.post(
            "/api/co-create/send", json={"text": "A cyberpunk story"}
        )
        assert res.status_code == 200
        data = res.json()
        assert "reply" in data
        assert len(data["reply"]) > 0

    def test_send_no_session_returns_400(self, client):
        res = client.post("/api/co-create/send", json={"text": "hello"})
        assert res.status_code == 400

    def test_send_empty_text_returns_400(self, client_with_session):
        res = client_with_session.post(
            "/api/co-create/send", json={"text": ""}
        )
        assert res.status_code == 400

    def test_send_api_error_returns_502(self, client):
        """Mock the sessions store to return a flow that raises."""
        from storyloom.web import sessions

        mock_flow = MagicMock()
        mock_flow.send.side_effect = CoCreateError(
            phase="send", message="API timeout"
        )
        sessions.store_co_create(mock_flow)

        res = client.post("/api/co-create/send", json={"text": "test"})
        assert res.status_code == 502
        assert "API timeout" in res.json()["detail"]


# ═══════════════════════════════════════════════════════════════════
# Co-create: retry-send
# ═══════════════════════════════════════════════════════════════════


class TestCoCreateRetrySend:
    def test_retry_send_returns_reply(self, client):
        from storyloom.web import sessions

        mock_flow = MagicMock()
        mock_flow.retry_send.return_value = "Retried reply"
        sessions.store_co_create(mock_flow)

        res = client.post("/api/co-create/retry-send")
        assert res.status_code == 200
        assert res.json()["reply"] == "Retried reply"

    def test_retry_send_no_session_returns_400(self, client):
        res = client.post("/api/co-create/retry-send")
        assert res.status_code == 400

    def test_retry_send_api_error_returns_502(self, client):
        from storyloom.web import sessions

        mock_flow = MagicMock()
        mock_flow.retry_send.side_effect = CoCreateError(
            phase="send", message="API timeout"
        )
        sessions.store_co_create(mock_flow)

        res = client.post("/api/co-create/retry-send")
        assert res.status_code == 502


# ═══════════════════════════════════════════════════════════════════
# Co-create: generate
# ═══════════════════════════════════════════════════════════════════


SAMPLE_STORY_CONFIG = {
    "genre": "cyberpunk", "tier": "short", "label": "Test",
    "language": "zh-CN", "setting": "Test world",
    "protagonist_name": "Tester",
    "protagonist_identity": "Hacker",
    "protagonist_traits": "Brave",
    "tone": "Dark", "conflict": "Survival", "characters": "NPC | ally",
    "variables": [{"name": "hp", "type": "number", "initial": 80}],
}

SAMPLE_RESULT = CoCreationResult(
    story_config=SAMPLE_STORY_CONFIG,
    outline_text="ch1 [active] — Start：Begin",
    outline_nodes=[
        {"id": "ch1", "title": "Start", "goal": "Begin", "routes": []},
    ],
)


class TestCoCreateGenerate:
    def test_generate_creates_save_and_returns_game_id(self, client):
        from storyloom.web import sessions
        from storyloom.web.server import _game_session

        mock_flow = MagicMock()
        mock_flow.generate.return_value = SAMPLE_RESULT
        sessions.store_co_create(mock_flow)

        # Mock start_game to avoid real filesystem writes
        mock_gl = MagicMock()
        mock_gl.round_count = 0
        mock_gl.current_node = "ch1"
        with patch.object(_game_session, "start_game",
                          return_value=(mock_gl, "test-game-123")):
            res = client.post("/api/co-create/generate")

        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["game_id"] == "test-game-123"
        assert data["story_config"]["label"] == "Test"
        # GameLoop stored for later start
        assert sessions.get_game("test-game-123") is mock_gl
        # Co-create session cleaned up — game is now live
        assert sessions.get_co_create() is None

    def test_generate_no_session_returns_400(self, client):
        res = client.post("/api/co-create/generate")
        assert res.status_code == 400

    def test_generate_api_error_returns_502(self, client):
        from storyloom.web import sessions

        mock_flow = MagicMock()
        mock_flow.generate.side_effect = CoCreateError(
            phase="generate_api", message="Generate API timeout"
        )
        sessions.store_co_create(mock_flow)

        res = client.post("/api/co-create/generate")
        assert res.status_code == 502


# ═══════════════════════════════════════════════════════════════════
# Co-create: retry-generate
# ═══════════════════════════════════════════════════════════════════


class TestCoCreateRetryGenerate:
    def test_retry_generate_returns_result(self, client):
        from storyloom.web import sessions
        from storyloom.web.server import _game_session

        mock_flow = MagicMock()
        mock_flow.retry_generate.return_value = SAMPLE_RESULT
        sessions.store_co_create(mock_flow)

        mock_gl = MagicMock()
        mock_gl.round_count = 0
        mock_gl.current_node = "ch1"
        with patch.object(_game_session, "start_game",
                          return_value=(mock_gl, "test-retry-456")):
            res = client.post("/api/co-create/retry-generate")

        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["game_id"] == "test-retry-456"

    def test_retry_generate_no_session_returns_400(self, client):
        res = client.post("/api/co-create/retry-generate")
        assert res.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# Co-create: abort
# ═══════════════════════════════════════════════════════════════════


class TestCoCreateAbort:
    def test_abort_clears_session(self, client):
        from storyloom.web import sessions

        mock_flow = MagicMock()
        sessions.store_co_create(mock_flow)

        res = client.post("/api/co-create/abort")
        assert res.status_code == 200
        assert sessions.get_co_create() is None

    def test_abort_without_session_succeeds(self, client):
        res = client.post("/api/co-create/abort")
        assert res.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# Game: start (Round 1)
# ═══════════════════════════════════════════════════════════════════


class TestGameStart:
    def test_game_start_requires_existing_game(self, client):
        """No stored game → 404."""
        res = client.post("/api/game/nonexistent/start")
        assert res.status_code == 404

    def test_game_start_calls_start_game(self, client):
        from storyloom.web import sessions

        mock_gl = MagicMock()
        mock_gl.round_count = 0
        mock_gl.current_node = "ch1"
        sessions.store_game("test-game-123", mock_gl)

        res = client.post("/api/game/test-game-123/start")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["game_id"] == "test-game-123"
        mock_gl.start_game.assert_called_once()

    def test_game_start_already_started_returns_400(self, client):
        from storyloom.web import sessions

        mock_gl = MagicMock()
        mock_gl.start_game.side_effect = RuntimeError("Round 1 already started")
        sessions.store_game("test-game-123", mock_gl)

        res = client.post("/api/game/test-game-123/start")
        assert res.status_code == 400
