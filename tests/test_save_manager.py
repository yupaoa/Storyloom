"""Tests for SaveManager — per-game directory + append-only saves."""
import json
import os
import tempfile

import pytest

from storyloom.core.save_manager import SaveManager


class TestSaveManagerInstance:
    """Tests for instance methods (operate on a single game directory)."""

    @pytest.fixture
    def game_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    @pytest.fixture
    def save_data(self):
        return {
            "version": 1,
            "metadata": {
                "label": "test-story",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "round_count": 3,
            },
            "config": {"temperature": None},
            "story_config": {
                "label": "test-story",
                "genre": "fantasy",
                "tier": "short",
                "variables": [],
            },
            "state_vars": {},
            "outline": [
                {
                    "node_id": "ch1",
                    "title": "Start",
                    "goal": "begin",
                    "status": "active",
                    "branches": [],
                }
            ],
            "progress": {
                "current_node": "ch1",
                "round_count": 3,
                "checkpoint_history": [
                    {"node": "ch1", "title": "Start", "summary": "began", "round": 3}
                ],
                "checkpoint_summaries": [],
                "checkpoint_snapshots": {},
            },
            "bridge_text": "",
        }

    # ── save / load round-trip ─────────────────────────────────

    def test_save_and_load_roundtrip(self, game_dir, save_data):
        sm = SaveManager(game_dir)
        filename = sm.save(save_data, cp_title="开始")
        loaded = sm.load(filename)
        assert loaded == save_data

    def test_save_init_without_cp_title(self, game_dir, save_data):
        sm = SaveManager(game_dir)
        filename = sm.save(save_data)
        assert filename == "_init.json"
        assert os.path.exists(os.path.join(game_dir, "_init.json"))

    def test_save_checkpoint_filename(self, game_dir, save_data):
        sm = SaveManager(game_dir)
        filename = sm.save(save_data, cp_title="开始")
        assert filename.startswith("开始_")
        assert filename.endswith(".json")
        assert ":" not in filename  # Windows-safe

    # ── list ───────────────────────────────────────────────────

    def test_list_saves_returns_metadata(self, game_dir, save_data):
        sm = SaveManager(game_dir)
        sm.save(save_data, cp_title="开始")
        saves = sm.list_saves()
        assert len(saves) == 1
        assert saves[0]["checkpoint_title"] == "Start"
        assert saves[0]["checkpoint_node"] == "ch1"
        assert saves[0]["round"] == 3

    def test_list_init_has_empty_cp_fields(self, game_dir, save_data):
        sm = SaveManager(game_dir)
        sm.save(save_data)  # _init.json — no checkpoint_history
        data_copy = dict(save_data)
        data_copy["progress"] = dict(data_copy["progress"], checkpoint_history=[])
        sm.save(data_copy)  # _init.json with empty history
        saves = sm.list_saves()
        # _init.json saved twice overwrites (same filename)
        assert len(saves) == 1
        assert saves[0]["checkpoint_title"] == ""

    # ── delete ─────────────────────────────────────────────────

    def test_delete_removes_file(self, game_dir, save_data):
        sm = SaveManager(game_dir)
        filename = sm.save(save_data, cp_title="test")
        assert sm.delete(filename) is True
        assert sm.list_saves() == []

    def test_delete_nonexistent_returns_false(self, game_dir):
        sm = SaveManager(game_dir)
        assert sm.delete("nonexistent.json") is False

    # ── load errors ────────────────────────────────────────────

    def test_load_nonexistent_raises(self, game_dir):
        sm = SaveManager(game_dir)
        with pytest.raises(FileNotFoundError):
            sm.load("nonexistent.json")

    def test_load_corrupt_json_raises(self, game_dir):
        sm = SaveManager(game_dir)
        path = os.path.join(game_dir, "bad.json")
        with open(path, "w") as f:
            f.write("not json")
        with pytest.raises(ValueError, match="corrupt"):
            sm.load("bad.json")

    def test_load_wrong_version_raises(self, game_dir, save_data):
        sm = SaveManager(game_dir)
        save_data["version"] = 99
        filename = sm.save(save_data, cp_title="test")
        with pytest.raises(ValueError, match="version"):
            sm.load(filename)

    def test_load_missing_fields_raises(self, game_dir):
        sm = SaveManager(game_dir)
        save_data = {"version": 1, "metadata": {"label": "bad"}}
        filename = sm.save(save_data, cp_title="test")
        with pytest.raises(ValueError, match="Missing required"):
            sm.load(filename)

    # ── atomic write ───────────────────────────────────────────

    def test_save_atomic_write(self, game_dir, save_data):
        sm = SaveManager(game_dir)
        filename = sm.save(save_data, cp_title="test")
        assert not os.path.exists(os.path.join(game_dir, f"{filename}.tmp"))
        assert os.path.exists(os.path.join(game_dir, filename))

    # ── sanitization ───────────────────────────────────────────

    def test_cp_title_sanitization(self, game_dir, save_data):
        sm = SaveManager(game_dir)
        filename = sm.save(save_data, cp_title="bad:file/name")
        assert filename.startswith("bad_file_name_")
        assert os.path.exists(os.path.join(game_dir, filename))


class TestSaveManagerStatic:
    """Tests for static cross-game operations."""

    @pytest.fixture
    def root(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    def test_create_game_returns_paths(self, root):
        game_dir, game_id, created_at = SaveManager.create_game(root, "测试故事")
        assert os.path.isdir(game_dir)
        assert game_id.startswith("测试故事_")
        assert game_id.endswith(created_at)

    def test_list_games_empty(self, root):
        assert SaveManager.list_games(root) == []

    def test_list_games_with_data(self, root):
        _, game_id, _ = SaveManager.create_game(root, "my_story")
        sm = SaveManager(os.path.join(root, game_id))
        sm.save({
            "version": 1,
            "metadata": {"label": "my_story", "created_at": "2026-01-01T00:00:00Z", "updated_at": "", "round_count": 0},
            "config": {"temperature": None},
            "story_config": {"label": "my_story", "language": "zh-CN", "genre": "fantasy", "tier": "short", "variables": []},
            "state_vars": {},
            "outline": [],
            "progress": {"current_node": "", "round_count": 0, "checkpoint_history": [], "checkpoint_summaries": [], "checkpoint_snapshots": {}},
            "bridge_text": "",
        })
        games = SaveManager.list_games(root)
        assert len(games) == 1
        assert games[0]["game_id"] == game_id
        assert games[0]["label"] == "my_story"
        assert games[0]["save_count"] == 1

    def test_list_saves_for_game(self, root):
        _, game_id, _ = SaveManager.create_game(root, "test")
        sm = SaveManager(os.path.join(root, game_id))
        sm.save({
            "version": 1,
            "metadata": {"label": "test", "created_at": "2026-01-01T00:00:00Z", "updated_at": "", "round_count": 0},
            "config": {"temperature": None},
            "story_config": {"label": "test", "variables": []},
            "state_vars": {},
            "outline": [],
            "progress": {"current_node": "", "round_count": 0, "checkpoint_history": [], "checkpoint_summaries": [], "checkpoint_snapshots": {}},
            "bridge_text": "",
        })
        saves = SaveManager.list_saves_for_game(root, game_id)
        assert len(saves) == 1
        assert saves[0]["filename"] == "_init.json"

    def test_delete_game(self, root):
        _, game_id, _ = SaveManager.create_game(root, "to_delete")
        assert SaveManager.delete_game(root, game_id) is True
        assert not os.path.exists(os.path.join(root, game_id))

    def test_delete_game_nonexistent(self, root):
        assert SaveManager.delete_game(root, "nonexistent") is False
