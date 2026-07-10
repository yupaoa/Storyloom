"""Tests for dev_cli package."""
from unittest.mock import MagicMock

import pytest
from storyloom.dev_cli.args import parse_args, DevCliArgs
from storyloom.dev_cli.observer import DevObserver


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.mode == "dev"
        assert args.story_file is None
        assert args.no_save is False
        assert args.lang == "zh-CN"

    def test_mode_normal(self):
        args = parse_args(["--mode", "normal"])
        assert args.mode == "normal"

    def test_story_file(self):
        args = parse_args(["--story", "my_story.json"])
        assert args.story_file == "my_story.json"

    def test_no_save(self):
        args = parse_args(["--no-save"])
        assert args.no_save is True

    def test_lang_en(self):
        args = parse_args(["--lang", "en"])
        assert args.lang == "en"

    def test_all_flags(self):
        args = parse_args([
            "--mode", "normal",
            "--story", "config.json",
            "--no-save",
            "--lang", "en",
        ])
        assert args.mode == "normal"
        assert args.story_file == "config.json"
        assert args.no_save is True
        assert args.lang == "en"

    def test_invalid_mode_rejected(self):
        with pytest.raises(SystemExit):
            parse_args(["--mode", "invalid"])

    def test_invalid_lang_rejected(self):
        with pytest.raises(SystemExit):
            parse_args(["--lang", "fr"])


class TestDevObserver:
    def test_creates_output_dir(self, tmp_path):
        out = tmp_path / "test_output"
        DevObserver(str(out))
        assert out.exists()
        assert out.is_dir()

    def test_record_round_writes_three_files(self, tmp_path):
        out = tmp_path / "test_output"
        obs = DevObserver(str(out))

        record = MagicMock()
        record.round_number = 1
        record.timestamp = "2026-07-10T12:00:00Z"
        record.messages_sent = [{"role": "user", "content": "test prompt"}]
        record.raw_response = "<story>test response</story>"
        record.ttft = 2.5
        record.tokens = {"prompt": 100, "completion": 200, "total": 300}
        record.node = "ch1"
        record.selected_branch = None

        parsed = MagicMock()
        parsed.total_segments = 10
        parsed.pre_segments = 7
        parsed.post_segments = 3
        parsed.bridge_found = True
        parsed.checkpoint_node = "ch2"
        parsed.checkpoint_summary = "test summary"
        parsed.routes = []
        parsed.sets = []
        parsed.choices = []
        record.parsed = parsed

        obs.record_round(record)

        assert (out / "prompts.txt").exists()
        assert (out / "responses.txt").exists()
        assert (out / "checks.txt").exists()

        prompts = (out / "prompts.txt").read_text()
        assert "Round 1" in prompts
        assert "test prompt" in prompts

        responses = (out / "responses.txt").read_text()
        assert "Round 1" in responses
        assert "ttft=2.5s" in responses
        assert "test response" in responses

        checks = (out / "checks.txt").read_text()
        assert "Round 1" in checks
        assert "Node: ch1" in checks
        assert "Segments: 10 total (pre=7, post=3)" in checks

    def test_append_mode_across_rounds(self, tmp_path):
        out = tmp_path / "test_output"
        obs = DevObserver(str(out))

        for i in range(3):
            record = MagicMock()
            record.round_number = i + 1
            record.timestamp = f"2026-07-10T12:00:0{i}Z"
            record.messages_sent = [{"role": "user", "content": f"prompt {i}"}]
            record.raw_response = f"response {i}"
            record.ttft = 1.0
            record.tokens = {}
            record.node = None
            record.selected_branch = None

            parsed = MagicMock()
            parsed.total_segments = 5
            parsed.pre_segments = 3
            parsed.post_segments = 2
            parsed.bridge_found = False
            parsed.checkpoint_node = None
            parsed.checkpoint_summary = None
            parsed.routes = []
            parsed.sets = []
            parsed.choices = []
            record.parsed = parsed

            obs.record_round(record)

        prompts = (out / "prompts.txt").read_text()
        assert prompts.count("── Round") == 3
        assert "prompt 0" in prompts
        assert "prompt 2" in prompts


class TestTerminalUi:
    def test_implements_ui_interface(self):
        """TerminalUi satisfies the UiInterface protocol."""
        from storyloom.dev_cli.ui import TerminalUi

        ui = TerminalUi()
        assert hasattr(ui, "write")
        assert hasattr(ui, "show_error")
        assert hasattr(ui, "ask")
        assert callable(ui.write)
        assert callable(ui.show_error)
        assert callable(ui.ask)

    def test_write_to_stdout(self, capsys):
        from storyloom.dev_cli.ui import TerminalUi

        ui = TerminalUi()
        ui.write("hello")
        captured = capsys.readouterr()
        assert "hello" in captured.out

    def test_show_error_to_stderr(self, capsys):
        from storyloom.dev_cli.ui import TerminalUi

        ui = TerminalUi()
        ui.show_error("fail")
        captured = capsys.readouterr()
        assert "fail" in captured.err
        assert "[Error]" in captured.err

    def test_ask_returns_input(self, monkeypatch):
        from storyloom.dev_cli.ui import TerminalUi

        ui = TerminalUi()
        monkeypatch.setattr("builtins.input", lambda _: "  answer  ")
        result = ui.ask("Question?")
        assert result == "answer"

    def test_ask_eof_returns_empty(self, monkeypatch):
        from storyloom.dev_cli.ui import TerminalUi

        ui = TerminalUi()
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError))
        result = ui.ask("Question?")
        assert result == ""

    def test_ask_keyboard_interrupt_returns_empty(self, monkeypatch):
        from storyloom.dev_cli.ui import TerminalUi

        ui = TerminalUi()
        monkeypatch.setattr(
            "builtins.input", lambda _: (_ for _ in ()).throw(KeyboardInterrupt)
        )
        result = ui.ask("Question?")
        assert result == ""
