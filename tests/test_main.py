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
        """New game should start (choose 1, provide co-creation inputs, then quit)."""
        monkeypatch.setattr("time.sleep", lambda x: None)
        buf = io.StringIO()
        monkeypatch.setattr("sys.stdin", io.StringIO(
            "1\n"         # menu → new game
            "科幻\n"      # step1: raw idea
            "开始\n"      # step2: trigger generation
            "quit\n"      # exit game
            "4\n"         # exit menu
        ))
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
        monkeypatch.setattr("sys.stdin", io.StringIO(
            "1\n"         # menu → new game
            "科幻\n"      # step1: raw idea
            "开始\n"      # step2: trigger generation
            "quit\n"      # exit during gameplay
            "4\n"         # exit menu
        ))
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
    """Mock API client for main module tests.

    Tracks call count to return appropriate responses for co-creation flow:
    - First chat() → Q&A response triggering "是否开始生成故事"
    - Subsequent chat() → full generation response with all three blocks
    - stream_chat() → narrative XML (used by GameLoop)
    """

    def __init__(self):
        self.last_messages = None
        self._chat_count = 0

    def stream_chat(self, messages):
        self.last_messages = messages
        return SAMPLE_XML

    def chat(self, messages):
        self.last_messages = messages
        self._chat_count += 1
        if self._chat_count == 1:
            return "这个想法很有趣。请问主角是男性还是女性？是否开始生成故事？"
        return CO_CREATE_GENERATION_RESPONSE


CO_CREATE_GENERATION_RESPONSE = """=== story_config ===
genre: 赛博朋克冒险
tier: medium
setting: 2087年新东京地下城
protagonist_name: 林焰
protagonist_identity: 自由佣兵
protagonist_traits: 冷静、道德灰色
tone: 黑暗冷峻
conflict: 一枚神秘芯片正在寻找宿主
characters:
  耗子 | 情报贩子 | 亦敌亦友

=== variables ===
体力: number, 初始 80
信任度: number, 初始 10

=== outline ===
[node]
id: ch1_intro
title: 霓虹深渊
goal: 在地下城酒吧感受氛围
routes: → ch2_meeting

[node]
id: ch2_meeting
title: 地下交易
goal: 与耗子会面
routes: （结局）"""


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
