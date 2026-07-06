"""Tests for SaveManager."""
import json
import os
import tempfile

import pytest

from storyloom.core.save_manager import SaveManager


class TestSaveManager:
    @pytest.fixture
    def tmp_dir(self):
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
                "checkpoint_history": [],
                "checkpoint_summaries": [],
                "checkpoint_snapshots": {},
            },
            "bridge_text": "",
        }

    def test_save_and_load_roundtrip(self, tmp_dir, save_data):
        sm = SaveManager(tmp_dir)
        sm.save(save_data)
        loaded = sm.load("test-story")
        assert loaded == save_data

    def test_list_saves_returns_metadata(self, tmp_dir, save_data):
        sm = SaveManager(tmp_dir)
        sm.save(save_data)
        saves = sm.list_saves()
        assert len(saves) == 1
        assert saves[0]["label"] == "test-story"
        assert saves[0]["round_count"] == 3

    def test_delete_removes_file(self, tmp_dir, save_data):
        sm = SaveManager(tmp_dir)
        sm.save(save_data)
        assert sm.delete("test-story") is True
        assert sm.list_saves() == []

    def test_delete_nonexistent_returns_false(self, tmp_dir):
        sm = SaveManager(tmp_dir)
        assert sm.delete("nonexistent") is False

    def test_load_nonexistent_raises(self, tmp_dir):
        sm = SaveManager(tmp_dir)
        with pytest.raises(FileNotFoundError):
            sm.load("nonexistent")

    def test_load_corrupt_json_raises(self, tmp_dir):
        sm = SaveManager(tmp_dir)
        path = os.path.join(tmp_dir, "bad.json")
        with open(path, "w") as f:
            f.write("not json")
        with pytest.raises(ValueError, match="corrupt"):
            sm.load("bad")

    def test_load_wrong_version_raises(self, tmp_dir, save_data):
        sm = SaveManager(tmp_dir)
        save_data["version"] = 99
        sm.save(save_data)
        with pytest.raises(ValueError, match="version"):
            sm.load("test-story")

    def test_load_missing_fields_raises(self, tmp_dir):
        sm = SaveManager(tmp_dir)
        save_data = {"version": 1, "metadata": {"label": "bad"}}
        sm.save(save_data)
        with pytest.raises(ValueError, match="Missing required"):
            sm.load("bad")

    def test_save_atomic_write(self, tmp_dir, save_data):
        sm = SaveManager(tmp_dir)
        sm.save(save_data)
        assert not os.path.exists(os.path.join(tmp_dir, "test-story.tmp"))
        assert os.path.exists(os.path.join(tmp_dir, "test-story.json"))

    def test_label_sanitization(self, tmp_dir, save_data):
        sm = SaveManager(tmp_dir)
        save_data["metadata"]["label"] = "bad:file/name"
        sm.save(save_data)
        saves = sm.list_saves()
        assert saves  # file exists despite illegal chars in label
