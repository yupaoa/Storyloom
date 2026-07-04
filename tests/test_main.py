"""Tests for main module (CLI entry point)."""

import io
import sys

import pytest
from src.storyloom.main import main, parse_args, DEFAULT_STORY_CONFIG
from src.storyloom.display import Display


class TestDefaultStoryConfig:
    def test_has_required_keys(self):
        """DEFAULT_STORY_CONFIG should have all required keys."""
        required = [
            "genre", "tier", "label", "setting",
            "protagonist_name", "protagonist_identity",
            "protagonist_traits", "tone", "conflict",
            "characters", "variables",
        ]
        for key in required:
            assert key in DEFAULT_STORY_CONFIG

    def test_variables_have_types_and_initials(self):
        """Variables should have name, type, and initial values."""
        for var in DEFAULT_STORY_CONFIG["variables"]:
            assert "name" in var
            assert "type" in var
            assert "initial" in var


class TestParseArgs:
    def test_no_args_returns_defaults(self):
        """parse_args should return defaults with no arguments."""
        args = parse_args([])
        assert args.menu is False
        assert args.debug is False

    def test_menu_flag(self):
        """--menu flag should be detected."""
        args = parse_args(["--menu"])
        assert args.menu is True

    def test_debug_flag(self):
        """--debug flag should be detected."""
        args = parse_args(["--debug"])
        assert args.debug is True


class TestMainFunction:
    def test_main_prints_banner(self, monkeypatch):
        """main() should print the Storyloom banner."""
        monkeypatch.setattr("time.sleep", lambda x: None)
        buf = io.StringIO()
        monkeypatch.setattr("sys.stdin", io.StringIO("4\n"))
        monkeypatch.setattr(
            "src.storyloom.main.ApiClient",
            lambda: MockApiClient(),
        )
        main(output=buf)
        output = buf.getvalue()
        assert "Storyloom" in output

    def test_new_game_starts(self, monkeypatch):
        """New game should start (choose 1, then quit)."""
        monkeypatch.setattr("time.sleep", lambda x: None)
        buf = io.StringIO()
        monkeypatch.setattr("sys.stdin", io.StringIO("1\nquit\n"))
        monkeypatch.setattr(
            "src.storyloom.main.ApiClient",
            lambda: MockApiClient(),
        )
        main(output=buf)
        output = buf.getvalue()
        assert "故事生成中" in output or "生成中" in output

    def test_exit_option(self, monkeypatch):
        """Exit option should terminate cleanly."""
        monkeypatch.setattr("time.sleep", lambda x: None)
        buf = io.StringIO()
        monkeypatch.setattr("sys.stdin", io.StringIO("4\n"))
        monkeypatch.setattr(
            "src.storyloom.main.ApiClient",
            lambda: MockApiClient(),
        )
        main(output=buf)  # Should not raise

    def test_quit_during_gameplay(self, monkeypatch):
        """Typing 'quit' during gameplay should return to menu, then exit."""
        monkeypatch.setattr("time.sleep", lambda x: None)
        buf = io.StringIO()
        monkeypatch.setattr("sys.stdin", io.StringIO("1\nquit\n4\n"))
        monkeypatch.setattr(
            "src.storyloom.main.ApiClient",
            lambda: MockApiClient(),
        )
        main(output=buf)  # Should not raise

    def test_manage_save_shows_stub(self, monkeypatch):
        """Manage saves should show a stub message."""
        monkeypatch.setattr("time.sleep", lambda x: None)
        buf = io.StringIO()
        monkeypatch.setattr("sys.stdin", io.StringIO("3\n4\n"))
        monkeypatch.setattr(
            "src.storyloom.main.ApiClient",
            lambda: MockApiClient(),
        )
        main(output=buf)
        output = buf.getvalue()
        assert "存档" in output


class MockApiClient:
    """Mock API client for main module tests."""

    def __init__(self):
        self.last_messages = None

    def stream_chat(self, messages):
        self.last_messages = messages
        return SAMPLE_XML

    def chat(self, messages):
        self.last_messages = messages
        return "故事结束。感谢游玩。"


SAMPLE_XML = """<story>
<seg n="1">数字霓虹在雨幕中流淌。</seg>
<seg n="2">林焰: 这条街我走了十二年。</seg>
<choice id="first_choice">
  <opt key="A" branch="enter">走进酒吧</opt>
  <opt key="B" branch="wait">在街角观察</opt>
</choice>
<bridge/>
<branch name="enter">
<seg n="3">你推开了酒吧的门。</seg>
</branch>
<branch name="wait">
<seg n="4">你靠在墙边点燃一支烟。</seg>
</branch>
</story>"""
