"""Tests for user_config module."""
import json
import tempfile
from pathlib import Path

import pytest
from storyloom.user_config import UserConfig


class TestUserConfigDefaults:
    """Headless mode — no file on disk, all defaults."""

    def test_headless_uses_defaults(self):
        cfg = UserConfig()
        assert cfg.language == "zh-CN"
        assert cfg.api_key == ""
        assert cfg.api_base_url == "https://api.deepseek.com"
        assert cfg.api_model == "deepseek-v4-pro"

    def test_headless_set_and_read_properties(self):
        cfg = UserConfig()
        cfg.language = "en"
        cfg.api_key = "sk-test"
        assert cfg.language == "en"
        assert cfg.api_key == "sk-test"

    def test_headless_save_is_noop(self):
        """Headless mode should not raise on save — just skip disk I/O."""
        cfg = UserConfig()
        cfg.language = "en"
        cfg.save()  # must not raise


class TestUserConfigLoad:
    """Load from existing config.json on disk."""

    def test_loads_all_fields(self, tmp_path):
        data = {
            "version": 1,
            "language": "en",
            "api_key": "sk-abc123",
            "api_base_url": "https://api.openai.com",
            "api_model": "gpt-4",
        }
        _write_json(tmp_path / "config.json", data)
        cfg = UserConfig(tmp_path)
        assert cfg.language == "en"
        assert cfg.api_key == "sk-abc123"
        assert cfg.api_base_url == "https://api.openai.com"
        assert cfg.api_model == "gpt-4"

    def test_missing_file_creates_default(self, tmp_path):
        cfg = UserConfig(tmp_path)
        assert cfg.language == "zh-CN"
        assert (tmp_path / "config.json").exists()

    def test_partial_file_backfills_missing_fields(self, tmp_path):
        _write_json(tmp_path / "config.json", {"version": 1, "language": "en"})
        cfg = UserConfig(tmp_path)
        assert cfg.language == "en"
        # Missing fields get defaults
        assert cfg.api_key == ""
        assert cfg.api_base_url == "https://api.deepseek.com"
        # File should have been re-saved with all fields
        saved = json.loads((tmp_path / "config.json").read_text())
        assert "api_key" in saved

    def test_copies_example_json_if_present(self, tmp_path):
        _write_json(tmp_path / "config.example.json", {
            "version": 1,
            "language": "en",
            "api_key": "your-api-key-here",
            "api_base_url": "https://api.deepseek.com",
            "api_model": "deepseek-v4-pro",
        })
        cfg = UserConfig(tmp_path)
        assert cfg.language == "en"
        assert (tmp_path / "config.json").exists()

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path):
        (tmp_path / "config.json").write_text("not valid json {{{")
        cfg = UserConfig(tmp_path)
        # Should not raise; should use defaults
        assert cfg.language == "zh-CN"
        # Original corrupt file should NOT be deleted
        assert (tmp_path / "config.json").exists()


class TestUserConfigSave:
    """Atomic save to disk."""

    def test_save_writes_all_fields(self, tmp_path):
        cfg = UserConfig(tmp_path)
        cfg.language = "en"
        cfg.api_key = "sk-new"
        cfg.save()
        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved["language"] == "en"
        assert saved["api_key"] == "sk-new"

    def test_save_is_atomic_no_partial_write(self, tmp_path):
        """If save() succeeds, file must be complete and valid JSON."""
        cfg = UserConfig(tmp_path)
        cfg.api_key = "sk-atomic"
        cfg.save()
        data = json.loads((tmp_path / "config.json").read_text())
        assert "api_key" in data
        assert data["version"] == 1
        # No .tmp file should remain
        tmps = list(tmp_path.glob("*.tmp"))
        assert len(tmps) == 0

    def test_save_preserves_version(self, tmp_path):
        _write_json(tmp_path / "config.json", {"version": 1, "language": "en"})
        cfg = UserConfig(tmp_path)
        cfg.language = "zh-CN"
        cfg.save()
        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved["version"] == 1


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
