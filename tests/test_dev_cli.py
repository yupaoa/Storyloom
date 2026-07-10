"""Tests for dev_cli package."""
import pytest
from storyloom.dev_cli.args import parse_args, DevCliArgs


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
