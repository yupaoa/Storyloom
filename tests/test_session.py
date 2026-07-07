"""Tests for GameSession orchestrator."""
import pytest
from unittest.mock import Mock, patch

from storyloom.core.session import GameSession
from storyloom.core.co_create import CoCreateFlow, CoCreationResult
from storyloom.core.game_loop import GameLoop


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
    def test_list_saves_delegates(self):
        with patch("storyloom.core.session.ApiClient"):
            session = GameSession()
            session._save_manager = Mock()
            session._save_manager.list_saves.return_value = [
                {"label": "test", "round_count": 5}
            ]
            result = session.list_saves()
            assert len(result) == 1
            assert result[0]["label"] == "test"

    def test_delete_save_delegates(self):
        with patch("storyloom.core.session.ApiClient"):
            session = GameSession()
            session._save_manager = Mock()
            session._save_manager.delete.return_value = True
            assert session.delete_save("test") is True
            session._save_manager.delete.assert_called_once_with("test")


class TestGameSessionLifecycle:
    def test_new_co_create_returns_flow(self):
        with patch("storyloom.core.session.ApiClient"):
            session = GameSession()
            session._api_client = Mock()
            flow = session.new_co_create()
            assert isinstance(flow, CoCreateFlow)
            assert flow._api is session._api_client

    def test_start_game_creates_game_loop(self):
        with patch("storyloom.core.session.ApiClient"):
            session = GameSession()
            session._api_client = Mock()
            session._save_manager = Mock()

            result = CoCreationResult(
                story_config={
                    "genre": "test", "tier": "short", "label": "test",
                    "setting": "", "protagonist_name": "T",
                    "protagonist_identity": "Tester",
                    "protagonist_traits": "Brave",
                    "tone": "Dark", "conflict": "Test",
                    "characters": "Foo | ally",
                    "variables": [
                        {"name": "t", "type": "number", "initial": 80},
                    ],
                },
                outline_text="ch1 [active] — Start：Begin",
                outline_nodes=[
                    {"id": "ch1", "title": "Start", "goal": "Begin", "routes": []},
                ],
            )

            gl = session.start_game(result)
            assert isinstance(gl, GameLoop)
            assert session.game_loop is gl
            assert gl._save_manager is session._save_manager

    def test_load_game_restores_game_loop(self):
        with patch("storyloom.core.session.ApiClient"):
            session = GameSession()
            session._api_client = Mock()
            session._save_manager = Mock()

            save_data = {
                "version": 1,
                "metadata": {"label": "test", "created_at": "", "updated_at": "",
                             "round_count": 3},
                "config": {},
                "story_config": {
                    "genre": "test", "tier": "short", "label": "test",
                    "setting": "", "protagonist_name": "T",
                    "protagonist_identity": "Tester",
                    "protagonist_traits": "Brave",
                    "tone": "Dark", "conflict": "Test",
                    "characters": "Foo | ally",
                    "variables": [{"name": "t", "type": "number", "initial": 80}],
                },
                "state_vars": {"t": 80},
                "outline": [
                    {"node_id": "ch1", "title": "Start", "goal": "Begin",
                     "status": "active", "branches": []},
                ],
                "progress": {
                    "current_node": "ch1", "round_count": 3,
                    "checkpoint_history": [], "checkpoint_summaries": [],
                    "checkpoint_snapshots": {},
                },
                "bridge_text": "",
            }
            session._save_manager.load.return_value = save_data

            gl = session.load_game("test")
            assert isinstance(gl, GameLoop)
            assert session.game_loop is gl
            session._save_manager.load.assert_called_once_with("test")

    def test_load_game_propagates_errors(self):
        with patch("storyloom.core.session.ApiClient"):
            session = GameSession()
            session._save_manager = Mock()
            session._save_manager.load.side_effect = FileNotFoundError("gone")
            with pytest.raises(FileNotFoundError):
                session.load_game("gone")
