"""Tests for StreamingXmlParser and LineBuffer."""

import pytest
from storyloom.parser.xml_parser import ParsedOutput, XmlParser
from storyloom.parser.streaming_parser import (
    EventType,
    LineBuffer,
    ParseEvent,
    StreamingXmlParser,
)


# ── Shared fixtures ──────────────────────────────────────────────

VALID_XML = """<story>
<seg>雨水敲击着头顶的金属雨棚。</seg>
<seg>耗子抬起眼，义眼红光微微闪烁。</seg>
<choice id="approach">
<opt key="1" branch="direct">直视对方，直截了当</opt>
<opt key="2" branch="cautious">先环顾四周，压低声音</opt>
</choice>
<set var="信任度" op="+" val="5" if="approach==1"/>
<checkpoint node="ch2" summary="在霓虹深渊与耗子接头。"/>
<bridge/>
<seg>你直视耗子的义眼。</seg>
<branch name="direct">
<seg>林焰：芯片在哪儿？</seg>
</branch>
<branch name="cautious">
<seg>你的目光扫过昏暗的酒吧。</seg>
</branch>
</story>"""

VALID_XML_WITH_LINE_NUMBERS = """001| <story>
002| <seg>雨水敲击着头顶的金属雨棚。</seg>
003| <seg>耗子抬起眼，义眼红光微微闪烁。</seg>
004| <choice id="approach">
005| <opt key="1" branch="direct">直视对方，直截了当</opt>
006| <opt key="2" branch="cautious">先环顾四周，压低声音</opt>
007| </choice>
008| <set var="信任度" op="+" val="5" if="approach==1"/>
009| <checkpoint node="ch2" summary="在霓虹深渊与耗子接头。"/>
010| <bridge/>
011| <seg>你直视耗子的义眼。</seg>
012| <branch name="direct">
013| <seg>林焰：芯片在哪儿？</seg>
014| </branch>
015| <branch name="cautious">
016| <seg>你的目光扫过昏暗的酒吧。</seg>
017| </branch>
018| </story>"""


# ── LineBuffer tests ────────────────────────────────────────────

class TestLineBuffer:
    def test_feed_single_line(self):
        lb = LineBuffer()
        assert lb.feed("hello world\n") == ["hello world"]

    def test_feed_partial_then_complete(self):
        lb = LineBuffer()
        assert lb.feed("hel") == []
        assert lb.feed("lo w") == []
        assert lb.feed("orld\n") == ["hello world"]

    def test_feed_multiple_lines_in_one_chunk(self):
        lb = LineBuffer()
        assert lb.feed("line one\nline two\n") == ["line one", "line two"]

    def test_feed_multiple_chunks_with_newlines(self):
        lb = LineBuffer()
        assert lb.feed("a\nb\nc") == ["a", "b"]
        assert lb.feed("d\ne\n") == ["cd", "e"]

    def test_feed_empty_string(self):
        lb = LineBuffer()
        assert lb.feed("") == []

    def test_feed_whitespace_only_lines_are_skipped(self):
        lb = LineBuffer()
        assert lb.feed("  \nreal\n\t\n") == ["real"]

    def test_flush_returns_remaining(self):
        lb = LineBuffer()
        lb.feed("partial line")
        assert lb.flush() == "partial line"

    def test_flush_empty_buffer_returns_none(self):
        lb = LineBuffer()
        assert lb.flush() is None

    def test_multiple_feeds_and_flush(self):
        lb = LineBuffer()
        lb.feed("first\nsec")
        assert lb.feed("ond\nthird\nfo") == ["second", "third"]
        assert lb.flush() == "fo"


# ── StreamingXmlParser tests ────────────────────────────────────

class TestStreamingXmlParser:
    """Unit tests for StreamingXmlParser feed_line() and get_result()."""

    @staticmethod
    def _feed_lines(parser: StreamingXmlParser, text: str) -> list[ParseEvent]:
        """Helper: feed all lines and return collected events."""
        events: list[ParseEvent] = []
        for line in text.strip().split("\n"):
            events.extend(parser.feed_line(line))
        return events

    # ── Basic element recognition ─────────────────────────────

    def test_story_begin_end(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(sp, "<story>\n</story>")
        types = [e.type for e in events]
        assert EventType.STORY_BEGIN in types
        assert EventType.STORY_END in types

    def test_segment_event(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(sp, "<story>\n<seg>hello</seg>\n</story>")
        seg_events = [e for e in events if e.type == EventType.SEGMENT]
        assert len(seg_events) == 1
        assert seg_events[0].text == "hello"

    def test_segment_with_n_attribute(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(sp, '<story>\n<seg n="5">text</seg>\n</story>')
        seg_events = [e for e in events if e.type == EventType.SEGMENT]
        assert len(seg_events) == 1
        # n value is captured via get_result()
        result = sp.get_result()
        assert result.segments[0].n == 5

    def test_segment_without_n_uses_sequential_count(self):
        sp = StreamingXmlParser()
        self._feed_lines(sp, "<story>\n<seg>a</seg>\n<seg>b</seg>\n<seg>c</seg>\n</story>")
        result = sp.get_result()
        assert [s.n for s in result.segments] == [1, 2, 3]

    def test_choice_events(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(
            sp,
            '<story>\n<choice id="approach">\n'
            '<opt key="1" branch="direct">直视对方</opt>\n'
            '<opt key="2" branch="cautious">环顾四周</opt>\n'
            '</choice>\n</story>',
        )
        types = {e.type for e in events}
        assert EventType.CHOICE_BEGIN in types
        assert EventType.OPT in types
        assert EventType.CHOICE_END in types

    def test_opt_attributes(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(
            sp,
            '<story>\n<choice id="approach">\n'
            '<opt key="1" branch="direct" if="score>50">直视</opt>\n'
            '</choice>\n</story>',
        )
        opt_events = [e for e in events if e.type == EventType.OPT]
        assert len(opt_events) == 1
        assert opt_events[0].opt_key == "1"
        assert opt_events[0].opt_branch == "direct"
        assert opt_events[0].opt_if == "score>50"
        assert opt_events[0].text == "直视"

    def test_opt_without_if_condition(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(
            sp,
            '<story>\n<choice id="approach">\n'
            '<opt key="1" branch="direct">直视</opt>\n'
            '</choice>\n</story>',
        )
        opt_events = [e for e in events if e.type == EventType.OPT]
        assert opt_events[0].opt_if is None

    def test_bridge_event(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(sp, "<story>\n<bridge/>\n</story>")
        bridge_events = [e for e in events if e.type == EventType.BRIDGE]
        assert len(bridge_events) == 1
        assert sp.bridge_seen

    def test_set_event(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(
            sp, '<story>\n<set var="体力" op="+" val="10"/>\n</story>'
        )
        set_events = [e for e in events if e.type == EventType.SET]
        assert len(set_events) == 1
        assert set_events[0].set_var == "体力"
        assert set_events[0].set_op == "+"
        assert set_events[0].set_val == "10"

    def test_set_with_condition(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(
            sp, '<story>\n<set var="体力" op="-" val="5" if="受伤==1"/>\n</story>'
        )
        set_events = [e for e in events if e.type == EventType.SET]
        assert set_events[0].set_if == "受伤==1"

    def test_checkpoint_event(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(
            sp,
            '<story>\n<checkpoint node="ch2" summary="接头完成。">\n'
            '</checkpoint>\n</story>',
        )
        cp_events = [e for e in events if e.type == EventType.CHECKPOINT]
        assert len(cp_events) == 1
        assert cp_events[0].cp_node == "ch2"
        assert cp_events[0].cp_summary == "接头完成。"

    def test_route_event(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(
            sp,
            '<story>\n<checkpoint node="ch2" summary="x">\n'
            '<route if="score>50" target="ch3_good"/>\n'
            '<route target="ch3_bad"/>\n'
            '</checkpoint>\n</story>',
        )
        route_events = [e for e in events if e.type == EventType.ROUTE]
        assert len(route_events) == 2
        assert route_events[0].route_if == "score>50"
        assert route_events[0].route_target == "ch3_good"
        assert route_events[1].route_if is None
        assert route_events[1].route_target == "ch3_bad"

    def test_branch_enter_exit(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(
            sp,
            '<story>\n<branch name="direct">\n<seg>text</seg>\n</branch>\n</story>',
        )
        enter_events = [e for e in events if e.type == EventType.BRANCH_ENTER]
        exit_events = [e for e in events if e.type == EventType.BRANCH_EXIT]
        assert len(enter_events) == 1
        assert enter_events[0].branch_name == "direct"
        assert len(exit_events) == 1

    # ── Position tracking ────────────────────────────────────

    def test_position_pre_bridge(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(sp, "<story>\n<seg>before</seg>\n<bridge/>\n</story>")
        seg_events = [e for e in events if e.type == EventType.SEGMENT]
        assert seg_events[0].position == "pre"

    def test_position_post_bridge(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(sp, "<story>\n<bridge/>\n<seg>after</seg>\n</story>")
        seg_events = [e for e in events if e.type == EventType.SEGMENT]
        assert seg_events[0].position == "post"

    def test_segment_in_branch_has_branch_name(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(
            sp,
            '<story>\n<branch name="direct">\n<seg>text</seg>\n</branch>\n</story>',
        )
        seg_events = [e for e in events if e.type == EventType.SEGMENT]
        assert seg_events[0].branch_name == "direct"

    # ── Line-number prefix stripping ─────────────────────────

    def test_line_number_prefix_stripped(self):
        sp = StreamingXmlParser()
        events = []
        for line in VALID_XML_WITH_LINE_NUMBERS.strip().split("\n"):
            events.extend(sp.feed_line(line))
        seg_events = [e for e in events if e.type == EventType.SEGMENT]
        assert seg_events[0].text == "雨水敲击着头顶的金属雨棚。"

    # ── get_result() completeness ────────────────────────────

    def test_get_result_segments(self):
        sp = StreamingXmlParser()
        self._feed_lines(sp, VALID_XML)
        result = sp.get_result()
        assert result.total_segments == 5  # 2 pre + 1 post-bare + 2 branch
        assert result.pre_segments == 2
        assert result.post_segments == 3
        assert result.bridge_found

    def test_get_result_choices(self):
        sp = StreamingXmlParser()
        self._feed_lines(sp, VALID_XML)
        result = sp.get_result()
        assert len(result.choices) == 1
        assert result.choices[0]["id"] == "approach"
        assert result.choices[0]["branches"] == ["direct", "cautious"]
        assert result.choices[0]["labels"] == ["直视对方，直截了当", "先环顾四周，压低声音"]
        assert result.choice_id == "approach"

    def test_get_result_sets(self):
        sp = StreamingXmlParser()
        self._feed_lines(sp, VALID_XML)
        result = sp.get_result()
        assert len(result.sets) == 1
        assert result.sets[0].var == "信任度"
        assert result.sets[0].op == "+"
        assert result.sets[0].val == "5"
        assert result.sets[0].condition == "approach==1"

    def test_get_result_checkpoint(self):
        sp = StreamingXmlParser()
        self._feed_lines(sp, VALID_XML)
        result = sp.get_result()
        assert result.checkpoint_node == "ch2"
        assert "霓虹深渊" in result.checkpoint_summary

    def test_get_result_routes(self):
        sp = StreamingXmlParser()
        self._feed_lines(sp, VALID_XML)
        # VALID_XML has no <route> inside its checkpoint, so routes is empty
        result = sp.get_result()
        assert result.routes == []
        # Now test with routes
        sp2 = StreamingXmlParser()
        self._feed_lines(
            sp2,
            '<story>\n<checkpoint node="ch2" summary="x">\n'
            '<route target="ch3"/>\n</checkpoint>\n</story>',
        )
        result2 = sp2.get_result()
        assert len(result2.routes) == 1
        assert result2.routes[0].target == "ch3"

    def test_get_result_bridge_text(self):
        sp = StreamingXmlParser()
        self._feed_lines(sp, VALID_XML)
        result = sp.get_result()
        assert "你直视耗子的义眼" in result.bridge_text
        assert "林焰：芯片在哪儿？" in result.bridge_text
        assert "你的目光扫过昏暗的酒吧" in result.bridge_text

    # ── Format errors ────────────────────────────────────────

    def test_format_error_choice_after_bridge(self):
        sp = StreamingXmlParser()
        self._feed_lines(
            sp,
            "<story>\n<bridge/>\n<choice id=\"x\">\n</choice>\n</story>",
        )
        assert len(sp.format_errors) >= 1
        assert any("choice" in err.lower() for err in sp.format_errors)

    def test_format_error_set_after_bridge(self):
        sp = StreamingXmlParser()
        self._feed_lines(
            sp,
            '<story>\n<bridge/>\n<set var="x" op="=" val="1"/>\n</story>',
        )
        assert any("set" in err.lower() for err in sp.format_errors)

    def test_no_format_errors_with_valid_xml(self):
        sp = StreamingXmlParser()
        self._feed_lines(sp, VALID_XML)
        assert sp.format_errors == []

    # ── Edge cases ───────────────────────────────────────────

    def test_empty_input(self):
        sp = StreamingXmlParser()
        assert sp.feed_line("") == []
        assert sp.feed_line("   ") == []

    def test_xml_comment_skipped(self):
        sp = StreamingXmlParser()
        events = sp.feed_line("<!-- comment -->")
        assert events == []

    def test_content_before_story_ignored(self):
        sp = StreamingXmlParser()
        events = self._feed_lines(sp, "preamble\n<story>\n<seg>ok</seg>\n</story>")
        seg_events = [e for e in events if e.type == EventType.SEGMENT]
        assert len(seg_events) == 1
        assert seg_events[0].text == "ok"


# ── Consistency with XmlParser ──────────────────────────────────

class TestParserConsistency:
    """Verify StreamingXmlParser produces same results as XmlParser."""

    def test_same_segment_count(self):
        sp = StreamingXmlParser()
        for line in VALID_XML.strip().split("\n"):
            sp.feed_line(line)
        streaming_result = sp.get_result()

        full_result = XmlParser.parse(VALID_XML)

        assert streaming_result.total_segments == full_result.total_segments
        assert streaming_result.pre_segments == full_result.pre_segments
        assert streaming_result.post_segments == full_result.post_segments

    def test_same_choice_extraction(self):
        sp = StreamingXmlParser()
        for line in VALID_XML.strip().split("\n"):
            sp.feed_line(line)
        streaming_result = sp.get_result()

        full_result = XmlParser.parse(VALID_XML)

        assert streaming_result.choice_id == full_result.choice_id
        assert streaming_result.choices == full_result.choices

    def test_same_set_extraction(self):
        sp = StreamingXmlParser()
        for line in VALID_XML.strip().split("\n"):
            sp.feed_line(line)
        streaming_result = sp.get_result()

        full_result = XmlParser.parse(VALID_XML)

        assert len(streaming_result.sets) == len(full_result.sets)
        for ss, fs in zip(streaming_result.sets, full_result.sets):
            assert ss.var == fs.var
            assert ss.op == fs.op
            assert ss.val == fs.val
            assert ss.condition == fs.condition

    def test_same_checkpoint_extraction(self):
        sp = StreamingXmlParser()
        for line in VALID_XML.strip().split("\n"):
            sp.feed_line(line)
        streaming_result = sp.get_result()

        full_result = XmlParser.parse(VALID_XML)

        assert streaming_result.checkpoint_node == full_result.checkpoint_node
        assert streaming_result.checkpoint_summary == full_result.checkpoint_summary

    def test_same_bridge_text(self):
        sp = StreamingXmlParser()
        for line in VALID_XML.strip().split("\n"):
            sp.feed_line(line)
        streaming_result = sp.get_result()

        full_result = XmlParser.parse(VALID_XML)

        assert streaming_result.bridge_text == full_result.bridge_text

    def test_same_branches(self):
        sp = StreamingXmlParser()
        for line in VALID_XML.strip().split("\n"):
            sp.feed_line(line)
        streaming_result = sp.get_result()

        full_result = XmlParser.parse(VALID_XML)

        assert set(streaming_result.pre_branches) == set(full_result.pre_branches)
        assert set(streaming_result.post_branches) == set(full_result.post_branches)

    def test_roundtrip_with_line_numbers(self):
        """Line-numbered XML should parse identically."""
        sp = StreamingXmlParser()
        for line in VALID_XML_WITH_LINE_NUMBERS.strip().split("\n"):
            sp.feed_line(line)
        streaming_result = sp.get_result()

        full_result = XmlParser.parse(VALID_XML_WITH_LINE_NUMBERS)

        assert streaming_result.total_segments == full_result.total_segments
        assert streaming_result.choice_id == full_result.choice_id
        assert streaming_result.checkpoint_node == full_result.checkpoint_node
