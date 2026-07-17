"""Tests for GameSession orchestrator."""
import os
import tempfile

import pytest
from unittest.mock import Mock, patch

from storyloom.core.session import GameSession
from storyloom.core.co_create import CoCreateFlow, CoCreationResult
from storyloom.core.game_loop import GameLoop


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
    @patch("storyloom.core.session.ApiClient")
    def test_creates_api_client_on_init(self, mock_api):
        session = GameSession()
        mock_api.assert_called_once()

    def test_game_loop_is_none_initially(self):
        with patch("storyloom.core.session.ApiClient"):
            session = GameSession()
            assert session.game_loop is None


class TestGameSessionSaveManagement:
    @pytest.fixture
    def root(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    def test_list_games_delegates(self, root):
        with patch("storyloom.core.session.ApiClient"):
            session = GameSession(root)
            result = session.list_games()
            assert result == []  # empty saves root

    def test_list_saves_requires_game_id(self, root):
        with patch("storyloom.core.session.ApiClient"):
            session = GameSession(root)
            result = session.list_saves("nonexistent_game")
            assert result == []

    def test_delete_game_returns_false_for_nonexistent(self, root):
        with patch("storyloom.core.session.ApiClient"):
            session = GameSession(root)
            assert session.delete_game("nonexistent") is False

    def test_delete_save_returns_false_for_nonexistent(self, root):
        with patch("storyloom.core.session.ApiClient"):
            session = GameSession(root)
            assert session.delete_save("nonexistent", "_init.json") is False


class TestGameSessionLifecycle:
    def test_new_co_create_returns_flow(self):
        with patch("storyloom.core.session.ApiClient"):
            session = GameSession()
            session._api_client = Mock()
            flow = session.new_co_create()
            assert isinstance(flow, CoCreateFlow)
            assert flow._api is session._api_client

    def test_start_game_returns_game_loop_and_game_id(self):
        with patch("storyloom.core.session.ApiClient"):
            with tempfile.TemporaryDirectory() as root:
                session = GameSession(root)
                session._api_client = Mock()

                gl, game_id = session.start_game(SAMPLE_RESULT)

                assert isinstance(gl, GameLoop)
                assert game_id.startswith("test-story_")
                assert session.game_loop is gl
                # _init.json should be created
                init_path = os.path.join(root, game_id, "_init.json")
                assert os.path.exists(init_path)

    def test_load_game_restores_game_loop(self):
        with patch("storyloom.core.session.ApiClient"):
            with tempfile.TemporaryDirectory() as root:
                session = GameSession(root)
                session._api_client = Mock()

                # Create a game first (writes _init.json)
                _, game_id = session.start_game(SAMPLE_RESULT)

                # Load it back
                gl = session.load_game(game_id, "_init.json")
                assert isinstance(gl, GameLoop)

    def test_load_game_nonexistent_raises(self):
        with patch("storyloom.core.session.ApiClient"):
            with tempfile.TemporaryDirectory() as root:
                session = GameSession(root)
                with pytest.raises(FileNotFoundError):
                    session.load_game("no_such_game", "_init.json")
