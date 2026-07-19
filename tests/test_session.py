"""Tests for GameSession orchestrator."""
import os
import tempfile

import pytest
from unittest.mock import Mock

from storyloom.core.session import GameSession
from storyloom.core.co_create import CoCreateFlow, CoCreationResult
from storyloom.core.game_loop import GameLoop
from storyloom.user_config import UserConfig
from storyloom.io.api_client import ApiClient


def _test_api_client():
    """Return an ApiClient with test credentials (no disk I/O)."""
    cfg = UserConfig()
    cfg.api_key = "sk-test"
    cfg.api_base_url = "https://api.test.com"
    return ApiClient(cfg)


SAMPLE_STORY_CONFIG = {
    "genre": "test", "tier": "short", "label": "test-story",
    "language": "zh-CN",
    "setting": "", "protagonist_name": "T",
    "protagonist_identity": "Tester",
    "protagonist_traits": "Brave",
    "tone": "Dark", "conflict": "Test",
    "characters": "Foo | ally",
    "variables": [
        {"name": "hp", "type": "number", "initial": 80},
    ],
}

SAMPLE_RESULT = CoCreationResult(
    story_config=SAMPLE_STORY_CONFIG,
    outline_text="ch1 [active] — Start：Begin",
    outline_nodes=[
        {"id": "ch1", "title": "Start", "goal": "Begin", "routes": []},
    ],
)


class TestGameSessionInit:
    def test_accepts_explicit_api_client(self):
        api = _test_api_client()
        session = GameSession(api_client=api)
        assert session._api_client is api

    def test_game_loop_is_none_initially(self):
        session = GameSession(api_client=_test_api_client())
        assert session.game_loop is None


class TestGameSessionSaveManagement:
    @pytest.fixture
    def root(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    def test_list_games_delegates(self, root):
        session = GameSession(api_client=_test_api_client(), saves_dir=root)
        result = session.list_games()
        assert result == []  # empty saves root

    def test_list_saves_requires_game_id(self, root):
        session = GameSession(api_client=_test_api_client(), saves_dir=root)
        result = session.list_saves("nonexistent_game")
        assert result == []

    def test_delete_game_returns_false_for_nonexistent(self, root):
        session = GameSession(api_client=_test_api_client(), saves_dir=root)
        assert session.delete_game("nonexistent") is False

    def test_delete_save_returns_false_for_nonexistent(self, root):
        session = GameSession(api_client=_test_api_client(), saves_dir=root)
        assert session.delete_save("nonexistent", "_init.json") is False


class TestGameSessionLifecycle:
    def test_new_co_create_returns_flow(self):
        mock_api = Mock()
        session = GameSession(api_client=mock_api)
        flow = session.new_co_create()
        assert isinstance(flow, CoCreateFlow)
        assert flow._api is mock_api

    def test_start_game_returns_game_loop_and_game_id(self):
        with tempfile.TemporaryDirectory() as root:
            session = GameSession(api_client=Mock(), saves_dir=root)

            gl, game_id = session.start_game(SAMPLE_RESULT)

            assert isinstance(gl, GameLoop)
            assert game_id.startswith("test-story_")
            assert session.game_loop is gl
            # _init.json should be created
            init_path = os.path.join(root, game_id, "_init.json")
            assert os.path.exists(init_path)

    def test_load_game_restores_game_loop(self):
        with tempfile.TemporaryDirectory() as root:
            session = GameSession(api_client=Mock(), saves_dir=root)

            # Create a game first (writes _init.json)
            _, game_id = session.start_game(SAMPLE_RESULT)

            # Load it back
            gl = session.load_game(game_id, "_init.json")
            assert isinstance(gl, GameLoop)

    def test_load_game_nonexistent_raises(self):
        with tempfile.TemporaryDirectory() as root:
            session = GameSession(api_client=Mock(), saves_dir=root)
            with pytest.raises(FileNotFoundError):
                session.load_game("no_such_game", "_init.json")
