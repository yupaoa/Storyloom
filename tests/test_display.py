"""Tests for display module."""

import io
import sys

import pytest
from storyloom.io.display import Display
from storyloom.parser.xml_parser import Segment


class TestDisplayInit:
    def test_default_output_is_stdout(self):
        """Default display output should be sys.stdout."""
        d = Display()
        assert d.output is sys.stdout

    def test_custom_output_buffer(self):
        """A StringIO buffer should be usable as output."""
        buf = io.StringIO()
        d = Display(output=buf)
        assert d.output is buf

    def test_auto_advance_defaults_to_true(self):
        """auto_advance should default to True."""
        d = Display()
        assert d.auto_advance is True

    def test_auto_advance_can_be_set_to_false(self):
        """auto_advance should be settable to False."""
        d = Display(auto_advance=False)
        assert d.auto_advance is False


class TestDisplayNarrative:
    def test_shows_single_segment(self):
        """A single narrative segment should be displayed."""
        buf = io.StringIO()
        d = Display(output=buf, auto_advance=False)
        seg = Segment(n=1, text="炉火噼啪作响。", position="pre")
        d.show_segment(seg)
        output = buf.getvalue()
        assert "炉火噼啪作响" in output

    def test_shows_dialogue_segment(self):
        """Dialogue segments should show character name."""
        buf = io.StringIO()
        d = Display(output=buf, auto_advance=False)
        seg = Segment(n=2, text="旅店老板: 这么晚了还赶路？", position="pre")
        d.show_segment(seg)
        output = buf.getvalue()
        assert "旅店老板" in output

    def test_shows_multiple_segments(self):
        """Multiple segments should each be displayed."""
        buf = io.StringIO()
        d = Display(output=buf, auto_advance=False)
        seg1 = Segment(n=1, text="第一段。", position="pre")
        seg2 = Segment(n=2, text="第二段。", position="pre")
        d.show_segment(seg1)
        d.show_segment(seg2)
        output = buf.getvalue()
        assert "第一段" in output
        assert "第二段" in output

    def test_segment_text_is_shown(self):
        """Segment display should show the narrative text."""
        buf = io.StringIO()
        d = Display(output=buf, auto_advance=False)
        seg = Segment(n=5, text="第五段内容。", position="pre")
        d.show_segment(seg)
        output = buf.getvalue()
        assert "第五段内容" in output


class TestDisplayOptions:
    def test_renders_options(self):
        """Options should be rendered with numbered keys."""
        buf = io.StringIO()
        d = Display(output=buf, auto_advance=False)
        d.show_options("approach", ["direct", "careful"], ["直接问价", "先探口风"])
        output = buf.getvalue()
        assert "[1]" in output
        assert "直接问价" in output
        assert "先探口风" in output

    def test_renders_single_option(self):
        """Single option should still render numbered."""
        buf = io.StringIO()
        d = Display(output=buf, auto_advance=False)
        d.show_options("exit", ["leave"], ["离开"])
        output = buf.getvalue()
        assert "离开" in output

    def test_option_shows_title_and_labels(self):
        """Options panel should show title and option labels."""
        buf = io.StringIO()
        d = Display(output=buf, auto_advance=False)
        d.show_options("approach", ["direct", "careful"], ["直接问价", "先探口风"])
        output = buf.getvalue()
        assert "选择" in output
        assert "直接问价" in output
        assert "先探口风" in output
        assert "[1]" in output
        assert "[2]" in output


class TestDisplayState:
    def test_shows_state_display(self):
        """State variables should be displayed as key-value pairs."""
        buf = io.StringIO()
        d = Display(output=buf)
        d.show_state({"体力": 75, "信任度": 30})
        output = buf.getvalue()
        assert "体力" in output
        assert "75" in output

    def test_shows_state_for_string_vars(self):
        """String state variables should display their values."""
        buf = io.StringIO()
        d = Display(output=buf)
        d.show_state({"所属势力": "自由佣兵"})
        output = buf.getvalue()
        assert "自由佣兵" in output

    def test_shows_multiple_state_vars(self):
        """Multiple state variables should all be displayed."""
        buf = io.StringIO()
        d = Display(output=buf)
        d.show_state({"体力": 75, "信任度": 30, "所属势力": "自由佣兵"})
        output = buf.getvalue()
        assert "体力" in output
        assert "信任度" in output
        assert "所属势力" in output

    def test_empty_state_does_not_raise(self):
        """Empty state dict should not cause errors."""
        buf = io.StringIO()
        d = Display(output=buf)
        d.show_state({})
        # Should not raise


class TestDisplayMainMenu:
    def test_renders_menu(self):
        """Main menu should show new game and continue options."""
        buf = io.StringIO()
        d = Display(output=buf)
        d.show_main_menu(save_count=3)
        output = buf.getvalue()
        assert "New Game" in output
        assert "Continue" in output

    def test_shows_save_count(self):
        """Main menu should show number of saves available."""
        buf = io.StringIO()
        d = Display(output=buf)
        d.show_main_menu(save_count=3)
        output = buf.getvalue()
        assert "3" in output

    def test_zero_saves_still_renders(self):
        """Main menu with zero saves should render without errors."""
        buf = io.StringIO()
        d = Display(output=buf)
        d.show_main_menu(save_count=0)
        output = buf.getvalue()
        assert output


class TestDisplayWaitMessage:
    def test_shows_wait_message(self):
        """Wait/progress messages should be displayed."""
        buf = io.StringIO()
        d = Display(output=buf)
        d.show_wait_message("生成中...")
        output = buf.getvalue()
        assert "生成中" in output

    def test_shows_different_wait_messages(self):
        """Different wait messages should display correctly."""
        buf = io.StringIO()
        d = Display(output=buf)
        d.show_wait_message("加载存档...")
        output = buf.getvalue()
        assert "加载存档" in output


class TestDisplayInput:
    def test_get_input_returns_user_text(self, monkeypatch):
        """get_input should return the user's typed text."""
        monkeypatch.setattr("sys.stdin", io.StringIO("test input\n"))
        d = Display(output=io.StringIO())
        result = d.get_input("> ")
        assert result == "test input"

    def test_get_input_displays_prompt(self, monkeypatch):
        """get_input should display the prompt string."""
        buf = io.StringIO()
        monkeypatch.setattr("sys.stdin", io.StringIO("hello\n"))
        d = Display(output=buf)
        d.get_input("输入选择: ")
        output = buf.getvalue()
        assert "输入选择" in output


class TestDisplaySeparators:
    def test_show_separator(self):
        """Separator between segments should be displayed."""
        buf = io.StringIO()
        d = Display(output=buf, auto_advance=False)
        d.show_separator()
        output = buf.getvalue()
        assert output  # Some visual separator is printed

    def test_show_section_break(self):
        """Section breaks (e.g., between rounds) should display."""
        buf = io.StringIO()
        d = Display(output=buf, auto_advance=False)
        d.show_section_break()
        output = buf.getvalue()
        assert "─" in output
