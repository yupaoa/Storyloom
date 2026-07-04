"""Tests for xml_parser module."""

import pytest
from src.storyloom.xml_parser import XmlParser, ParsedOutput, ParseError


VALID_XML = """<story>
<seg n="1">炉火在石砌的壁炉里噼啪作响。</seg>
<seg n="2">旅店老板: 这么晚了还赶路？</seg>
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
<seg n="3">你在他对面坐下。</seg>
</branch>
<branch name="wait">
<seg n="4">你站着没动。</seg>
</branch>
</story>"""


class TestXmlParser:
    def test_parse_valid_xml_returns_parsed_output(self):
        result = XmlParser.parse(VALID_XML)
        assert isinstance(result, ParsedOutput)

    def test_parse_extracts_choice_id(self):
        result = XmlParser.parse(VALID_XML)
        assert result.choice_id == "approach"

    def test_parse_extracts_opt_branches(self):
        result = XmlParser.parse(VALID_XML)
        assert result.opt_branches == ["take_lead", "wait"]

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
        numbers = [s.n for s in result.segments]
        assert numbers == [1, 2, 3, 4]

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
        assert result.choice_id is None
        assert result.opt_branches == []

    def test_parse_extracts_pre_bridge_segments(self):
        result = XmlParser.parse(VALID_XML)
        pre_segs = [s for s in result.segments if s.position == "pre"]
        assert len(pre_segs) == 2

    def test_parse_handles_unordered_seg_numbers(self):
        xml = VALID_XML.replace('n="3"', 'n="5"')
        result = XmlParser.parse(xml)
        assert result.numbering_issues
