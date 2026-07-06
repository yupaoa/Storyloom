"""Tests for xml_parser module."""

import pytest
from storyloom.parser.xml_parser import XmlParser, ParsedOutput, ParseError


VALID_XML = """<story>
<seg>炉火在石砌的壁炉里噼啪作响。</seg>
<seg>旅店老板: 这么晚了还赶路？</seg>
<choice id="approach">
  <opt key="A" branch="take_lead">先开口</opt>
  <opt key="B" branch="wait">保持沉默</opt>
</choice>
<set var="声望" op="+" val="5" if="approach==1"/>
<checkpoint node="ch2_meeting" summary="在旅店接头。">
  <route if="approach==1" target="ch3_lead"/>
</checkpoint>
<bridge/>
<branch name="take_lead">
<seg>你在他对面坐下。</seg>
</branch>
<branch name="wait">
<seg>你站着没动。</seg>
</branch>
</story>"""


class TestXmlParser:
    def test_parse_valid_xml_returns_parsed_output(self):
        result = XmlParser.parse(VALID_XML)
        assert isinstance(result, ParsedOutput)

    def test_parse_extracts_choice_id(self):
        result = XmlParser.parse(VALID_XML)
        assert result.choices[-1]["id"] == "approach"

    def test_parse_extracts_opt_branches(self):
        result = XmlParser.parse(VALID_XML)
        assert result.choices[-1]["branches"] == ["take_lead", "wait"]

    def test_parse_extracts_set_operations(self):
        result = XmlParser.parse(VALID_XML)
        assert len(result.sets) == 1
        assert result.sets[0].var == "声望"
        assert result.sets[0].op == "+"
        assert result.sets[0].val == "5"
        assert result.sets[0].condition == "approach==1"

    def test_parse_extracts_checkpoint_node(self):
        result = XmlParser.parse(VALID_XML)
        assert result.checkpoint_node == "ch2_meeting"
        assert result.checkpoint_summary == "在旅店接头。"

    def test_parse_extracts_route_targets(self):
        result = XmlParser.parse(VALID_XML)
        assert len(result.routes) == 1
        assert result.routes[0].target == "ch3_lead"

    def test_parse_finds_exactly_one_bridge(self):
        result = XmlParser.parse(VALID_XML)
        assert result.bridge_found is True

    def test_parse_counts_segments(self):
        result = XmlParser.parse(VALID_XML)
        assert result.total_segments == 4

    def test_parse_extracts_bridge_text(self):
        result = XmlParser.parse(VALID_XML)
        assert "你在他对面坐下" in result.bridge_text
        assert "你站着没动" in result.bridge_text

    def test_parse_preserves_segment_order(self):
        result = XmlParser.parse(VALID_XML)
        texts = [s.text for s in result.segments]
        assert texts[0] == "炉火在石砌的壁炉里噼啪作响。"
        assert texts[1] == "旅店老板: 这么晚了还赶路？"

    def test_parse_rejects_missing_story_tag(self):
        with pytest.raises(ParseError, match="Missing <story>"):
            XmlParser.parse("<seg n='1'>text</seg>")

    def test_parse_rejects_multiple_bridges(self):
        xml = VALID_XML.replace("<bridge/>", "<bridge/><bridge/>", 1)
        with pytest.raises(ParseError, match="Multiple <bridge/>"):
            XmlParser.parse(xml)

    def test_parse_rejects_missing_bridge(self):
        xml = VALID_XML.replace("<bridge/>", "")
        with pytest.raises(ParseError, match="No <bridge/>"):
            XmlParser.parse(xml)

    def test_parse_rejects_post_bridge_prohibited_elements(self):
        xml = VALID_XML.replace(
            "</branch>",
            "</branch><choice id='x'><opt key='A' branch='b'>o</opt></choice>",
            1
        )
        with pytest.raises(ParseError, match="Prohibited"):
            XmlParser.parse(xml)

    def test_extract_bridge_text_strips_xml_tags(self):
        result = XmlParser.parse(VALID_XML)
        assert "<seg" not in result.bridge_text
        assert "<branch" not in result.bridge_text

    def test_parse_handles_no_choice(self):
        xml = VALID_XML.replace(
            "<choice id=\"approach\">\n  <opt key=\"A\" branch=\"take_lead\">先开口</opt>\n  <opt key=\"B\" branch=\"wait\">保持沉默</opt>\n</choice>\n",
            ""
        )
        result = XmlParser.parse(xml)
        assert result.choices == []

    def test_parse_extracts_pre_bridge_segments(self):
        result = XmlParser.parse(VALID_XML)
        pre_segs = [s for s in result.segments if s.position == "pre"]
        assert len(pre_segs) == 2

    def test_parse_handles_missing_seg_number(self):
        xml = '<story><seg>text</seg><bridge/><seg>ok</seg></story>'
        result = XmlParser.parse(xml)
        assert result.total_segments == 2
        # n defaults to 0 when attribute is missing
        assert result.segments[0].n == 0

    def test_parse_handles_ampersand_escaping(self):
        xml = '<story><seg>R&amp;D department</seg><bridge/><seg>ok</seg></story>'
        result = XmlParser.parse(xml)
        assert result.total_segments == 2

    def test_parse_strips_line_number_prefixes(self):
        xml = """001| <story>
002| <seg>first segment</seg>
003| <seg>second segment</seg>
004| <bridge/>
005| <seg>tail segment</seg>
006| </story>"""
        result = XmlParser.parse(xml)
        assert result.total_segments == 3
        assert result.segments[0].text == "first segment"
        assert result.bridge_found is True
        xml = '<story><seg n="1">R&amp;D department</seg><bridge/><seg n="2">ok</seg></story>'
        result = XmlParser.parse(xml)
        assert result.total_segments == 2

    def test_parse_handles_already_escaped_ampersand(self):
        xml = '<story><seg n="1">R&amp;amp;D</seg><bridge/><seg n="2">ok</seg></story>'
        result = XmlParser.parse(xml)
        assert result.total_segments == 2

    def test_parse_handles_non_integer_seg_number_gracefully(self):
        xml = '<story><seg n="abc">text</seg><bridge/><seg n="2">ok</seg></story>'
        result = XmlParser.parse(xml)
        # Non-integer n falls back to 0 instead of raising
        assert result.total_segments == 2
        assert result.segments[0].n == 0
        assert result.segments[1].n == 2

    def test_parse_handles_markdown_xml_fence(self):
        xml = '```xml\n<story><seg n="1">text</seg><bridge/><seg n="2">ok</seg></story>\n```'
        result = XmlParser.parse(xml)
        assert result.total_segments == 2
