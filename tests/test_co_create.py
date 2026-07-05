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


class TestParseStoryConfig:
    """Tests for parse_story_config — INI-style key: value parsing."""

    VALID_CONFIG = """genre: 赛博朋克冒险
tier: medium
setting: 2087年新东京地下城
protagonist_name: 林焰
protagonist_identity: 前荒坂安全顾问，现自由佣兵
protagonist_traits: 冷静、道德灰色
tone: 黑暗冷峻
conflict: 一枚神秘芯片正在寻找宿主
characters:
  耗子 | 地下情报贩子 | 亦敌亦友
  美智子 | 荒坂安全主管 | 前上司"""

    def test_parse_complete_valid_config(self):
        result = CoCreateParser.parse_story_config(self.VALID_CONFIG)
        assert result["genre"] == "赛博朋克冒险"
        assert result["tier"] == "medium"
        assert result["setting"] == "2087年新东京地下城"
        assert result["protagonist_name"] == "林焰"
        assert result["protagonist_identity"] == "前荒坂安全顾问，现自由佣兵"
        assert result["protagonist_traits"] == "冷静、道德灰色"
        assert result["tone"] == "黑暗冷峻"
        assert result["conflict"] == "一枚神秘芯片正在寻找宿主"
        assert "耗子" in result["characters"]
        assert "美智子" in result["characters"]

    def test_parse_without_setting_still_works(self):
        text = """genre: fantasy
tier: short
setting:
protagonist_name: Kael
protagonist_identity: mercenary
protagonist_traits: brave
tone: dark
conflict: a war
characters:
  Mouse | spy | friend"""
        result = CoCreateParser.parse_story_config(text)
        assert result["setting"] == ""
        assert result["genre"] == "fantasy"

    def test_missing_required_field_raises_parse_error(self):
        text = """genre: fantasy
tier: short
protagonist_name: Kael
protagonist_identity: mercenary
protagonist_traits: brave
tone: dark
conflict: a war"""
        with pytest.raises(ValueError, match="Missing required fields"):
            CoCreateParser.parse_story_config(text)

    def test_invalid_tier_raises_parse_error(self):
        text = """genre: fantasy
tier: epic
setting: somewhere
protagonist_name: Kael
protagonist_identity: mercenary
protagonist_traits: brave
tone: dark
conflict: a war
characters:
  Mouse | spy | friend"""
        with pytest.raises(ValueError, match="Unknown tier"):
            CoCreateParser.parse_story_config(text)

    def test_empty_text_raises_parse_error(self):
        with pytest.raises(ValueError, match="Empty"):
            CoCreateParser.parse_story_config("")

    def test_characters_single_entry(self):
        text = """genre: fantasy
tier: short
setting: somewhere
protagonist_name: Kael
protagonist_identity: mercenary
protagonist_traits: brave
tone: dark
conflict: a war
characters:
  Mouse | spy | friend"""
        result = CoCreateParser.parse_story_config(text)
        assert "Mouse" in result["characters"]

    def test_language_field_defaults(self):
        """language field defaults to zh-CN if not provided."""
        result = CoCreateParser.parse_story_config(self.VALID_CONFIG)
        assert result.get("language", "zh-CN") == "zh-CN"


class TestParseVariables:
    """Tests for parse_variables."""

    VALID_VARS = """体力: number, 初始 80
信任度: number, 初始 10
所属势力: string, 初始 自由佣兵"""

    def test_parse_three_valid_variables(self):
        result = CoCreateParser.parse_variables(self.VALID_VARS)
        assert len(result) == 3
        assert result[0] == {"name": "体力", "type": "number", "initial": 80}
        assert result[1] == {"name": "信任度", "type": "number", "initial": 10}
        assert result[2] == {"name": "所属势力", "type": "string", "initial": "自由佣兵"}

    def test_parse_list_type_empty(self):
        text = "物品: list, 初始 []"
        result = CoCreateParser.parse_variables(text)
        assert result[0]["type"] == "list"
        assert result[0]["initial"] == []

    def test_parse_list_type_with_elements(self):
        text = "线索: list, 初始 芯片, 密钥"
        result = CoCreateParser.parse_variables(text)
        assert result[0]["initial"] == ["芯片", "密钥"]

    def test_parse_single_variable(self):
        text = "理智值: number, 初始 50"
        result = CoCreateParser.parse_variables(text)
        assert len(result) == 1
        assert result[0]["name"] == "理智值"

    def test_empty_text_returns_empty_list(self):
        result = CoCreateParser.parse_variables("")
        assert result == []

    def test_malformed_line_raises_parse_error(self):
        text = "bad line without proper format"
        with pytest.raises(ValueError, match="Cannot parse variable"):
            CoCreateParser.parse_variables(text)

    def test_unknown_type_raises_parse_error(self):
        text = "体力: boolean, 初始 true"
        with pytest.raises(ValueError, match="Unknown type"):
            CoCreateParser.parse_variables(text)

    def test_number_initial_not_integer_raises_parse_error(self):
        text = "体力: number, 初始 high"
        with pytest.raises(ValueError, match="integer"):
            CoCreateParser.parse_variables(text)

    def test_name_with_illegal_colon_raises_parse_error(self):
        text = "体:力: number, 初始 80"
        with pytest.raises(ValueError, match="Cannot parse variable"):
            CoCreateParser.parse_variables(text)


class TestValidateVariables:
    """Tests for validate_variables."""

    def test_all_valid_passes(self):
        vars_list = [
            {"name": "体力", "type": "number", "initial": 80},
            {"name": "信任度", "type": "number", "initial": 10},
            {"name": "所属势力", "type": "string", "initial": "自由佣兵"},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert errors == []

    def test_count_exceeds_cap(self):
        vars_list = [
            {"name": f"var{i}", "type": "number", "initial": 50}
            for i in range(4)
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("exceeds maximum 3" in e for e in errors)

    def test_too_many_numeric(self):
        vars_list = [
            {"name": "a", "type": "number", "initial": 50},
            {"name": "b", "type": "number", "initial": 50},
            {"name": "c", "type": "number", "initial": 50},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("numeric" in e.lower() for e in errors)

    def test_too_many_labels(self):
        vars_list = [
            {"name": "a", "type": "string", "initial": "x"},
            {"name": "b", "type": "list", "initial": []},
            {"name": "c", "type": "number", "initial": 50},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("label" in e.lower() for e in errors)

    def test_number_out_of_bounds(self):
        vars_list = [
            {"name": "体力", "type": "number", "initial": 150},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("out of range" in e for e in errors)

    def test_number_below_zero(self):
        vars_list = [
            {"name": "体力", "type": "number", "initial": -10},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert len(errors) >= 1

    def test_string_empty_initial(self):
        vars_list = [
            {"name": "tag", "type": "string", "initial": ""},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("empty" in e.lower() or "非空" in e for e in errors)

    def test_duplicate_names(self):
        vars_list = [
            {"name": "体力", "type": "number", "initial": 80},
            {"name": "体力", "type": "number", "initial": 50},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("duplicate" in e.lower() or "重复" in e for e in errors)

    def test_list_element_not_string(self):
        vars_list = [
            {"name": "物品", "type": "list", "initial": ["a", 123]},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("string" in e.lower() for e in errors)


class TestParseOutline:
    """Tests for parse_outline — [node] block parsing."""

    VALID_OUTLINE = """[node]
id: ch1_intro
title: 霓虹深渊
goal: 在地下城酒吧感受氛围
routes: → ch2_meeting

[node]
id: ch2_meeting
title: 地下交易
goal: 与耗子会面
routes:
  if 信任度 >= 30 → ch3_ally
  if 信任度 < 30 → ch3_betrayal

[node]
id: ch3_ally
title: 盟友之路
goal: 通过地下网络逃离
routes: → ch4_safehouse

[node]
id: ch3_betrayal
title: 背叛之路
goal: 杀出重围
routes: → ch4_safehouse

[node]
id: ch4_safehouse
title: 安全屋
goal: 揭开芯片秘密（结局）
routes: （结局）"""

    def test_parse_valid_branching_outline(self):
        nodes = CoCreateParser.parse_outline(self.VALID_OUTLINE)
        assert len(nodes) == 5
        assert nodes[0]["id"] == "ch1_intro"
        assert nodes[0]["title"] == "霓虹深渊"
        assert nodes[0]["goal"] == "在地下城酒吧感受氛围"
        assert nodes[0]["routes"] == [{"condition": None, "target": "ch2_meeting"}]

    def test_parse_branching_node(self):
        nodes = CoCreateParser.parse_outline(self.VALID_OUTLINE)
        ch2 = nodes[1]
        assert ch2["id"] == "ch2_meeting"
        assert len(ch2["routes"]) == 2
        assert ch2["routes"][0] == {"condition": "信任度 >= 30", "target": "ch3_ally"}
        assert ch2["routes"][1] == {"condition": "信任度 < 30", "target": "ch3_betrayal"}

    def test_parse_ending_node(self):
        nodes = CoCreateParser.parse_outline(self.VALID_OUTLINE)
        ending = nodes[4]
        assert ending["id"] == "ch4_safehouse"
        assert ending["routes"] == []

    def test_parse_linear_outline(self):
        text = """[node]
id: ch1
title: start
goal: begin
routes: → ch2

[node]
id: ch2
title: end
goal: finish
routes: （结局）"""
        nodes = CoCreateParser.parse_outline(text)
        assert len(nodes) == 2

    def test_parse_no_routes_field(self):
        text = """[node]
id: ch1
title: only
goal: solo"""
        nodes = CoCreateParser.parse_outline(text)
        assert len(nodes) == 1
        assert nodes[0]["routes"] == []

    def test_empty_outline_raises_parse_error(self):
        with pytest.raises(ValueError, match="Empty|No nodes"):
            CoCreateParser.parse_outline("")

    def test_node_without_id_raises_parse_error(self):
        text = """[node]
title: missing id
goal: something"""
        with pytest.raises(ValueError, match="Missing 'id'"):
            CoCreateParser.parse_outline(text)

    def test_node_without_title_raises_parse_error(self):
        text = """[node]
id: ch1
goal: something"""
        with pytest.raises(ValueError, match="Missing 'title'"):
            CoCreateParser.parse_outline(text)


class TestValidateOutline:
    """Tests for validate_outline."""

    def _make_nodes(self, *ids_and_targets):
        nodes = []
        for node_id, routes in ids_and_targets:
            nodes.append({
                "id": node_id,
                "title": node_id,
                "goal": "test",
                "routes": [
                    {"condition": c, "target": t} for c, t in routes
                ],
            })
        return nodes

    def test_all_valid_passes(self):
        nodes = self._make_nodes(
            ("ch1", [(None, "ch2")]),
            ("ch2", [(None, "ch3")]),
            ("ch3", []),
        )
        errors = CoCreateParser.validate_outline(nodes, ["hp"])
        assert errors == []

    def test_route_target_missing_rejected(self):
        nodes = self._make_nodes(
            ("ch1", [(None, "ch2")]),
            ("ch2", [(None, "ch99")]),
        )
        errors = CoCreateParser.validate_outline(nodes, [])
        assert any("ch99" in e for e in errors)

    def test_final_node_has_branches_rejected(self):
        nodes = self._make_nodes(
            ("ch1", [(None, "ch2")]),
            ("ch2", [(None, "ch3")]),
            ("ch3", [(None, "ch1")]),
        )
        errors = CoCreateParser.validate_outline(nodes, [])
        assert any("final" in e.lower() or "最后" in e for e in errors)

    def test_zero_nodes_rejected(self):
        errors = CoCreateParser.validate_outline([], [])
        assert any("1" in e for e in errors)

    def test_unknown_variable_in_condition_warns_only(self):
        nodes = self._make_nodes(
            ("ch1", [("unknown_var > 10", "ch2")]),
            ("ch2", []),
        )
        errors = CoCreateParser.validate_outline(nodes, ["hp"])
        assert not errors


class TestFormatOutline:
    """Tests for format_outline — convert [node] blocks to GameLoop format."""

    def test_format_simple_linear_outline(self):
        nodes = [
            {"id": "ch1", "title": "开始", "goal": "开场",
             "routes": [{"condition": None, "target": "ch2"}]},
            {"id": "ch2", "title": "结局", "goal": "收尾",
             "routes": []},
        ]
        result = CoCreateParser.format_outline(nodes)
        assert "ch1 [active] — 开始：开场" in result
        assert "→ ch2 [pending]" in result
        assert "ch2 [pending] — 结局：收尾" in result

    def test_format_branching_outline(self):
        nodes = [
            {"id": "ch1", "title": "起点", "goal": "start",
             "routes": [
                 {"condition": "a > 5", "target": "ch2a"},
                 {"condition": "a <= 5", "target": "ch2b"},
             ]},
            {"id": "ch2a", "title": "A路", "goal": "path a",
             "routes": []},
            {"id": "ch2b", "title": "B路", "goal": "path b",
             "routes": []},
        ]
        result = CoCreateParser.format_outline(nodes)
        assert "├→ ch2a [pending]" in result
        assert "└→ ch2b [pending]" in result

    def test_format_ending_node_no_routes(self):
        nodes = [
            {"id": "ch1", "title": "终", "goal": "end", "routes": []},
        ]
        result = CoCreateParser.format_outline(nodes)
        assert "ch1 [active]" in result
        assert "→" not in result
