"""Tests for co-create parser and flow."""
import pytest
from src.storyloom.co_create import CoCreateParser


class TestSplitBlocks:
    """Tests for _split_blocks — splitting LLM response into 3 sections."""

    def test_split_three_blocks(self):
        text = """=== story_config ===
genre: fantasy
tier: short

=== variables ===
hp: number, 初始 80

=== outline ===
[node]
id: ch1
title: start
goal: begin
routes: （结局）"""
        result = CoCreateParser.split_blocks(text)
        assert "genre: fantasy" in result["story_config"]
        assert "hp: number" in result["variables"]
        assert "[node]" in result["outline"]

    def test_split_missing_block_sets_empty(self):
        text = """=== story_config ===
genre: fantasy
tier: short"""
        result = CoCreateParser.split_blocks(text)
        assert result["story_config"] != ""
        assert result["variables"] == ""
        assert result["outline"] == ""

    def test_split_empty_text_returns_all_empty(self):
        result = CoCreateParser.split_blocks("")
        assert result == {"story_config": "", "variables": "", "outline": ""}

    def test_split_handles_spurious_delimiters_in_content(self):
        """Lines containing === that are not block delimiters should be kept as content."""
        text = """=== story_config ===
genre: fantasy
note: use === sparingly
tier: short

=== variables ===
hp: number, 初始 80

=== outline ===
[node]
id: ch1"""
        result = CoCreateParser.split_blocks(text)
        assert "use === sparingly" in result["story_config"]
        assert "hp: number" in result["variables"]
