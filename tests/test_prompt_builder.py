"""Tests for prompt_builder module."""

import pytest
from storyloom.core.prompt_builder import PromptBuilder


SAMPLE_STORY_CONFIG = {
    "genre": "赛博朋克冒险",
    "tier": "medium",
    "label": "霓虹深渊",
    "setting": "2087年新东京地下城",
    "protagonist_name": "林焰",
    "protagonist_identity": "前荒坂安全顾问，现自由佣兵",
    "protagonist_traits": "冷静、道德灰色",
    "tone": "黑暗冷峻",
    "conflict": "一枚神秘芯片正在寻找宿主",
    "characters": "耗子（地下情报贩子）、美智子（荒坂安全主管）",
    "variables": [
        {"name": "体力", "type": "number", "initial": 80},
        {"name": "信任度", "type": "number", "initial": 10},
        {"name": "所属势力", "type": "string", "initial": "自由佣兵"},
    ],
}

SAMPLE_OUTLINE = """
ch1_bar [completed] — 霓虹深渊：在酒吧获取情报
  → ch2_confrontation [active]
ch2_confrontation [active] — 地下交易：与耗子会面
  ├→ ch3_ally [pending]
  └→ ch3_betrayal [pending]
ch3_ally [pending] — 盟友之路：通过地下网络逃离
ch3_betrayal [pending] — 背叛之路：杀出重围
ch4_safehouse [pending] — 安全屋：揭开芯片秘密（结局）
"""


class TestBuildRound1:
    def test_round1_contains_role_definition(self):
        pb = PromptBuilder()
        result = pb.build_round1(SAMPLE_STORY_CONFIG, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易")
        assert "narrative engine" in result

    def test_round1_contains_xml_format_spec(self):
        pb = PromptBuilder()
        result = pb.build_round1(SAMPLE_STORY_CONFIG, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易")
        assert "<story>" in result
        assert "<seg>" in result
        assert "<bridge/>" in result

    def test_round1_contains_format_example(self):
        pb = PromptBuilder()
        result = pb.build_round1(SAMPLE_STORY_CONFIG, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易")
        assert "Snow fell" in result
        assert "Innkeeper" in result

    def test_round1_contains_story_context(self):
        pb = PromptBuilder()
        result = pb.build_round1(SAMPLE_STORY_CONFIG, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易")
        assert "赛博朋克冒险" in result
        assert "林焰" in result
        assert "ch2_confrontation" in result

    def test_round1_contains_state_variables(self):
        pb = PromptBuilder()
        result = pb.build_round1(SAMPLE_STORY_CONFIG, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易")
        assert "体力" in result
        assert "信任度" in result

    def test_round1_ends_with_start_instruction(self):
        pb = PromptBuilder()
        result = pb.build_round1(SAMPLE_STORY_CONFIG, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易")
        assert "start of the whole story" in result


class TestBuildRoundN:
    def test_round_n_does_not_contain_format_spec(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3_ally",
            goal="通过地下网络逃离",
            completed_nodes=["ch1_bar", "ch2_confrontation"],
            state_vars={"体力": 60, "信任度": 25, "所属势力": "自由佣兵"},
            bridge_text="你对耗子点了点头。\n耗子: 跟我来。",
        )
        assert "<story>" not in result
        assert "<seg>" not in result

    def test_round_n_contains_progress(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3_ally",
            goal="通过地下网络逃离",
            completed_nodes=["ch1_bar", "ch2_confrontation"],
            state_vars={"体力": 60},
            bridge_text="tail...",
        )
        assert "ch3_ally" in result
        assert "通过地下网络逃离" in result
        assert "ch1_bar" in result

    def test_round_n_contains_state_snapshot(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3_ally",
            goal="逃",
            completed_nodes=[],
            state_vars={"体力": 60, "信任度": 25},
            bridge_text="tail...",
        )
        assert "体力" in result
        assert "60" in result
        assert "信任度" in result

    def test_round_n_contains_bridge_text(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3_ally",
            goal="逃",
            completed_nodes=[],
            state_vars={"体力": 60},
            bridge_text="你对耗子点了点头。",
        )
        assert "Last round ending" in result
        assert "你对耗子点了点头" in result

    def test_round_n_contains_compressed_summaries(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch4",
            goal="结局",
            completed_nodes=["ch1", "ch2", "ch3"],
            state_vars={"体力": 30},
            bridge_text="tail...",
            compressed_summaries=["在旅店接头", "完成芯片交易"],
        )
        assert "在旅店接头" in result
        assert "完成芯片交易" in result

    def test_round_n_contains_rejected_feedback_when_present(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3",
            goal="逃",
            completed_nodes=[],
            state_vars={"体力": 60},
            bridge_text="tail...",
            rejected_changes=["体力变更被拒：超出范围[0,100]"],
        )
        assert "Rejected" in result
        assert "体力变更被拒" in result

    def test_round_n_omits_rejected_section_when_empty(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3",
            goal="逃",
            completed_nodes=[],
            state_vars={"体力": 60},
            bridge_text="tail...",
            rejected_changes=[],
        )
        assert "Rejected" not in result

    def test_round_n_format_error_adds_correction_hint(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3",
            goal="逃",
            completed_nodes=[],
            state_vars={"体力": 60},
            bridge_text="tail...",
            format_error="checkpoint 的 node 值与大纲不匹配",
        )
        assert "Format reminder" in result or "checkpoint" in result


class TestAdventureLogPrompt:
    def test_build_adventure_log_prompt_contains_label(self):
        pb = PromptBuilder()
        config = {"label": "霓虹深渊", "genre": "cyberpunk"}
        state_vars = {"体力": 25}
        summaries = ["抵达了边陲小镇"]
        history = [{"node": "ch1", "title": "序章", "summary": "抵达边陲小镇", "round": 3}]

        prompt = pb.build_adventure_log_prompt(config, state_vars, summaries, history)
        assert "霓虹深渊" in prompt
        assert "Adventure Recap" in prompt

    def test_build_adventure_log_prompt_includes_chapter_sections(self):
        pb = PromptBuilder()
        config = {"label": "test", "genre": "fantasy"}
        state_vars = {"魔力": 50}
        summaries = ["first checkpoint"]
        history = [{"node": "ch1", "title": "开始", "summary": "first checkpoint", "round": 2}]

        prompt = pb.build_adventure_log_prompt(config, state_vars, summaries, history)
        assert "开始" in prompt
        assert "Final State" in prompt
        assert "魔力" in prompt

    def test_build_adventure_log_prompt_empty_history(self):
        pb = PromptBuilder()
        config = {"label": "test"}
        state_vars = {}
        prompt = pb.build_adventure_log_prompt(config, state_vars, [], [])
        assert "Adventure Recap" in prompt
        assert "Final State" in prompt
        assert "No chapter records" in prompt
