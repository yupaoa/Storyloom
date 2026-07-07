"""Tests for main module (CLI test harness)."""

import io
import sys

import pytest
from storyloom.main import main, parse_args, DEFAULT_STORY_CONFIG, SAMPLE_OUTLINE
from storyloom.i18n import init_i18n
init_i18n("en")  # Use English for deterministic test output


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

    def test_sample_outline_is_non_empty(self):
        """SAMPLE_OUTLINE should contain nodes."""
        assert len(SAMPLE_OUTLINE) > 0
        assert "ch1_intro" in SAMPLE_OUTLINE


class TestParseArgs:
    def test_no_args_returns_defaults(self):
        """parse_args should return defaults with no arguments."""
        args = parse_args([])
        assert args.debug is False
        assert args.quick is False
        assert args.rounds == 1
        assert args.choices is None

    def test_debug_flag(self):
        """--debug flag should be detected."""
        args = parse_args(["--debug"])
        assert args.debug is True

    def test_quick_flag(self):
        """--quick flag should be detected."""
        args = parse_args(["--quick"])
        assert args.quick is True

    def test_rounds_default(self):
        """--rounds should default to 1."""
        args = parse_args([])
        assert args.rounds == 1

    def test_rounds_custom(self):
        """--rounds N should be detected."""
        args = parse_args(["--rounds", "5"])
        assert args.rounds == 5

    def test_choices(self):
        """--choices should be detected as a string."""
        args = parse_args(["--choices", "1,2,1"])
        assert args.choices == "1,2,1"


class TestMainFunction:
    def test_main_quick_runs_round1(self, monkeypatch):
        """main --quick should run 1 round and print completion."""
        monkeypatch.setattr("time.sleep", lambda x: None)
        monkeypatch.setattr(
            "storyloom.main.ApiClient",
            lambda: MockApiClient(),
        )
        buf = io.StringIO()
        main(output=buf, argv=["--quick"])
        output = buf.getvalue()
        assert "Completed 1 round" in output

    def test_main_quick_rounds_3(self, monkeypatch):
        """main --quick --rounds 3 should run 3 rounds."""
        monkeypatch.setattr("time.sleep", lambda x: None)
        monkeypatch.setattr(
            "storyloom.main.ApiClient",
            lambda: MockApiClient(),
        )
        buf = io.StringIO()
        main(output=buf, argv=["--quick", "--rounds", "3"])
        output = buf.getvalue()
        assert "Completed 3 round" in output

    def test_main_without_quick_fails(self, monkeypatch):
        """main without --quick should print error to stderr and exit."""
        buf = io.StringIO()
        err = io.StringIO()
        monkeypatch.setattr("sys.stderr", err)
        with pytest.raises(SystemExit) as excinfo:
            main(output=buf, argv=[])
        assert excinfo.value.code == 1

    def test_main_print_flag(self, monkeypatch):
        """main --quick --print should output round summary to stderr."""
        monkeypatch.setattr("time.sleep", lambda x: None)
        monkeypatch.setattr(
            "storyloom.main.ApiClient",
            lambda: MockApiClient(),
        )
        buf = io.StringIO()
        err = io.StringIO()
        monkeypatch.setattr("sys.stderr", err)
        main(output=buf, argv=["--quick", "--print"])
        assert "Completed 1 round" in buf.getvalue()
        assert "[Round 1]" in err.getvalue()

    def test_main_verbose_flag(self, monkeypatch):
        """main --quick --print --verbose should include segment counts."""
        monkeypatch.setattr("time.sleep", lambda x: None)
        monkeypatch.setattr(
            "storyloom.main.ApiClient",
            lambda: MockApiClient(),
        )
        buf = io.StringIO()
        err = io.StringIO()
        monkeypatch.setattr("sys.stderr", err)
        main(output=buf, argv=["--quick", "--print", "--verbose"])
        assert "segs=" in err.getvalue()

    def test_main_missing_api_key(self, monkeypatch):
        """main should exit with error if ApiClient raises RuntimeError."""
        monkeypatch.setattr(
            "storyloom.main.ApiClient",
            lambda: _raise_runtime_error,
        )
        buf = io.StringIO()
        err = io.StringIO()
        monkeypatch.setattr("sys.stderr", err)
        with pytest.raises(SystemExit) as excinfo:
            main(output=buf, argv=["--quick"])
        assert excinfo.value.code == 1


# ── Mock ─────────────────────────────────────────────────────────────

def _raise_runtime_error():
    raise RuntimeError("No API key configured")


class MockApiClient:
    """Mock API client for test harness tests.

    Returns minimal valid XML for stream_chat_iter (used by GameLoop).
    """

    def __init__(self):
        self.last_messages = None

    def stream_chat_iter(self, messages):
        """Yield tokens from SAMPLE_XML, then done chunk."""
        self.last_messages = messages
        for char in SAMPLE_XML:
            yield {"delta": char}
        yield {
            "usage": {"prompt": 100, "completion": 50, "total": 150},
            "done": True,
        }


SAMPLE_XML = """<story>
<seg n="1">数字霓虹在雨幕中流淌。</seg>
<seg n="2">你站在街角，雨水顺着大衣滑落。</seg>
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
