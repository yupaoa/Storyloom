"""Tests for co-create parser and flow."""
import pytest
from storyloom.core.co_create import CoCreateParser
from storyloom.io.api_client import ApiError
from storyloom.i18n import init_i18n
init_i18n("en")  # Use English for deterministic test output


class TestSplitBlocks:
    """Tests for _split_blocks — splitting LLM response into 3 sections."""

    def test_split_three_blocks(self):
        text = """=== story_config ===
genre: fantasy
tier: short

=== variables ===
hp: number, 80

=== outline ===
[node]
id: ch1
title: start
goal: begin
routes:"""
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
hp: number, 80

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
label: test-story
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
label: test-story
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
label: test-story
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
label: test-story
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
label: test-story
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

    VALID_VARS = """体力: number, 80
信任度: number, 10
所属势力: string, 自由佣兵"""

    def test_parse_three_valid_variables(self):
        result = CoCreateParser.parse_variables(self.VALID_VARS)
        assert len(result) == 3
        assert result[0] == {"name": "体力", "type": "number", "initial": 80}
        assert result[1] == {"name": "信任度", "type": "number", "initial": 10}
        assert result[2] == {"name": "所属势力", "type": "string", "initial": "自由佣兵"}

    def test_parse_single_variable(self):
        text = "理智值: number, 50"
        result = CoCreateParser.parse_variables(text)
        assert len(result) == 1
        assert result[0]["name"] == "理智值"

    def test_empty_text_returns_empty_variables(self):
        result = CoCreateParser.parse_variables("")
        assert result == []

    def test_malformed_line_raises_parse_error(self):
        text = "bad line without proper format"
        with pytest.raises(ValueError, match="Cannot parse variable"):
            CoCreateParser.parse_variables(text)

    def test_unknown_type_raises_parse_error(self):
        text = "体力: boolean, true"
        with pytest.raises(ValueError, match="Unknown type"):
            CoCreateParser.parse_variables(text)

    def test_number_initial_not_integer_raises_parse_error(self):
        text = "体力: number, high"
        with pytest.raises(ValueError, match="integer"):
            CoCreateParser.parse_variables(text)

    def test_name_with_illegal_colon_raises_parse_error(self):
        text = "体:力: number, 80"
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

    def test_too_many_strings(self):
        vars_list = [
            {"name": "a", "type": "string", "initial": "x"},
            {"name": "b", "type": "string", "initial": "y"},
            {"name": "c", "type": "number", "initial": 50},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("string" in e.lower() for e in errors)

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
goal: 揭开芯片秘密
routes:"""

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
routes:"""
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


# ── Integration Tests ────────────────────────────────────────────────

class MockApiClient:
    """Mock API client that returns predefined responses."""

    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_count = 0
        self.messages_history = []

    def chat(self, messages):
        self.messages_history.append(messages)
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        if self.responses:
            return self.responses[-1]
        return ""

    def stream_chat(self, messages):
        return self.chat(messages)


def make_mock_api_client():
    """Create a bare MockApiClient for send() error tests."""
    return MockApiClient()


class TestCoCreateFlowStateMachineProperties:
    """Tests for phase, result properties."""

    def test_initial_phase_is_init(self):
        """phase returns 'init' before start() is called."""
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        flow = CoCreateFlow(api)
        assert flow.phase == "init"

    def test_result_is_none_initially(self):
        """result is None before co-creation completes."""
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        flow = CoCreateFlow(api)
        assert flow.result is None

    def test_phase_transitions_after_start(self):
        """phase changes to 'awaiting_idea' after start()."""
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        flow = CoCreateFlow(api)
        flow.start()
        assert flow.phase == "awaiting_idea"

    def test_abort_changes_phase(self):
        """abort() sets phase to 'aborted'."""
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        flow = CoCreateFlow(api)
        flow.abort()
        assert flow.phase == "aborted"


class TestCoCreateFlowStart:
    """Tests for start() method."""

    def test_start_returns_awaiting_idea_event(self):
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        flow = CoCreateFlow(api)
        event = flow.start()
        assert event["phase"] == "awaiting_idea"
        assert "prompt" in event
        assert isinstance(event["prompt"], str)
        assert len(event["prompt"]) > 0

    def test_start_sets_phase(self):
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        flow = CoCreateFlow(api)
        assert flow.phase == "init"
        flow.start()
        assert flow.phase == "awaiting_idea"

    def test_start_raises_if_already_started(self):
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        flow = CoCreateFlow(api)
        flow.start()
        with pytest.raises(RuntimeError, match="already started"):
            flow.start()


FULL_GENERATION_RESPONSE = """=== story_config ===
genre: 赛博朋克冒险
tier: medium
label: test-story
setting: 2087年新东京地下城
protagonist_name: 林焰
protagonist_identity: 前荒坂安全顾问，现自由佣兵
protagonist_traits: 冷静、道德灰色
tone: 黑暗冷峻
conflict: 一枚神秘芯片正在寻找宿主
characters:
  耗子 | 地下情报贩子 | 亦敌亦友
  美智子 | 荒坂安全主管 | 前上司

=== variables ===
体力: number, 80
信任度: number, 10
所属势力: string, 自由佣兵

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
goal: 揭开芯片秘密
routes:"""


class TestCoCreateFlowSend:
    """Tests for send() method — pure message forward, returns str."""

    def test_send_before_start_raises(self):
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        flow = CoCreateFlow(api)
        with pytest.raises(RuntimeError, match="call start\\(\\) first"):
            flow.send("anything")

    def test_send_after_abort_raises(self):
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        flow = CoCreateFlow(api)
        flow._phase = "aborted"
        with pytest.raises(RuntimeError, match="was aborted"):
            flow.send("anything")

    def test_send_empty_input_raises_value_error(self):
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        flow = CoCreateFlow(api)
        flow.start()
        with pytest.raises(ValueError, match="cannot be empty"):
            flow.send("")

    def test_send_returns_str_not_dict(self):
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        api.chat = lambda msgs: "What era would you like?"
        flow = CoCreateFlow(api)
        flow.start()

        reply = flow.send("A cyberpunk romance in Neo Tokyo")

        assert isinstance(reply, str)
        assert reply == "What era would you like?"
        assert flow.phase == "awaiting_answer"

    def test_send_from_awaiting_idea_transitions_to_awaiting_answer(self):
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        api.chat = lambda msgs: "First question?"
        flow = CoCreateFlow(api)
        assert flow.phase == "init"
        flow.start()
        assert flow.phase == "awaiting_idea"
        flow.send("my idea")
        assert flow.phase == "awaiting_answer"

    def test_send_no_keyword_detection(self):
        """send() does NOT parse user input for start/quit keywords."""
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        api.chat = lambda msgs: "Interesting, tell me more."
        flow = CoCreateFlow(api)
        flow._phase = "awaiting_answer"
        flow._messages = [
            {"role": "system", "content": "test"},
            {"role": "user", "content": "idea"},
            {"role": "assistant", "content": "q"},
        ]

        # "开始" is just forwarded as text — no generation triggered
        reply = flow.send("开始")
        assert isinstance(reply, str)
        assert reply == "Interesting, tell me more."
        assert flow.phase == "awaiting_answer"

    def test_send_appends_to_messages(self):
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        api.chat = lambda msgs: "reply"
        flow = CoCreateFlow(api)
        flow._phase = "awaiting_answer"
        flow._messages = [
            {"role": "system", "content": "test"},
        ]

        flow.send("hello")

        user_msgs = [m for m in flow._messages if m["role"] == "user"]
        assert any("hello" in m["content"] for m in user_msgs)
        assistant_msgs = [m for m in flow._messages if m["role"] == "assistant"]
        assert any("reply" in m["content"] for m in assistant_msgs)


class TestCoCreateFlowSendEndToEnd:
    """End-to-end tests — start → send → generate → complete."""

    def test_full_flow_success(self):
        """Idea → Q&A → generate → complete."""
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient(responses=[
            "你想玩什么题材的故事？",
            FULL_GENERATION_RESPONSE,
        ])
        flow = CoCreateFlow(api)
        flow.start()
        reply = flow.send("赛博朋克冒险")
        assert reply == "你想玩什么题材的故事？"

        result = flow.generate()
        assert result.story_config["genre"] == "赛博朋克冒险"
        assert result.story_config["tier"] == "medium"
        assert len(result.story_config["variables"]) == 3
        assert "ch1_intro [active]" in result.outline_text
        assert flow.phase == "complete"
        assert flow.result is result

    def test_multi_turn_qa_before_generate(self):
        """Multiple Q&A rounds, then generate."""
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient(responses=[
            "Q1: What genre?",
            "Q2: What era?",
            FULL_GENERATION_RESPONSE,
        ])
        flow = CoCreateFlow(api)
        flow.start()

        r1 = flow.send("idea")
        assert r1 == "Q1: What genre?"

        r2 = flow.send("cyberpunk")
        assert r2 == "Q2: What era?"

        result = flow.generate()
        assert result.story_config["genre"] == "赛博朋克冒险"

    def test_user_aborts_during_qa(self):
        """abort() changes phase, independent of send()."""
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient(responses=["What genre?"])
        flow = CoCreateFlow(api)
        flow.start()
        flow.send("科幻")

        flow.abort()
        assert flow.phase == "aborted"

    def test_generate_validation_fails_raises_cocreate_error(self):
        """Parse validation failure → CoCreateError with phase='generate_parse'."""
        from storyloom.core.co_create import CoCreateFlow, CoCreateError
        api = make_mock_api_client()
        api.chat = lambda msgs: (
            "=== story_config ===\n"
            "genre: test\ntier: short\nlabel: 测试故事书\n"
            "setting: Test\nprotagonist_name: T\n"
            "protagonist_identity: Tester\nprotagonist_traits: Brave\n"
            "tone: Dark\nconflict: Test\ncharacters:\n  Foo | ally\n"
            "=== variables ===\n"
            "a: number, 80\n"
            "b: number, 50\n"
            "c: number, 30\n"
            "d: string, foo\n"
            "=== outline ===\n"
            "[node]\nid: ch1\ntitle: Start\ngoal: Begin\nroutes: → ch2\n"
            "[node]\nid: ch2\ntitle: End\ngoal: Finish\nroutes:\n"
        )
        flow = CoCreateFlow(api)
        flow._messages = [
            {"role": "system", "content": "test"},
            {"role": "user", "content": "idea"},
            {"role": "assistant", "content": "q"},
        ]
        flow._phase = "awaiting_answer"

        with pytest.raises(CoCreateError) as exc_info:
            flow.generate()
        assert exc_info.value.phase == "generate_parse"
        assert flow._retry_state is not None
        assert flow._retry_state[0] == "generate_parse"

    def test_retry_generate_after_parse_failure(self):
        """After parse failure, retry_generate() adds correction, re-calls API."""
        from storyloom.core.co_create import CoCreateFlow, CoCreateError
        BAD = """=== story_config ===
genre: fantasy
tier: epic
label: test-story
setting: somewhere
protagonist_name: Kael
protagonist_identity: warrior
protagonist_traits: brave
tone: dark
conflict: a war
characters:
  Mouse | spy | friend

=== variables ===
hp: number, 80

=== outline ===
[node]
id: ch1
title: start
goal: begin
routes:"""
        api = MockApiClient(responses=[BAD, FULL_GENERATION_RESPONSE])
        flow = CoCreateFlow(api)
        flow._messages = [
            {"role": "system", "content": "test"},
            {"role": "user", "content": "idea"},
            {"role": "assistant", "content": "q"},
        ]
        flow._phase = "awaiting_answer"

        # First generate() fails on parse → CoCreateError
        try:
            flow.generate()
        except CoCreateError:
            pass

        # retry_generate() adds correction, calls API, succeeds
        result = flow.retry_generate()
        assert result.story_config["tier"] == "medium"
        assert flow.phase == "complete"
        assert flow._retry_state is None

    def test_retry_generate_raises_when_no_failure(self):
        """retry_generate() raises RuntimeError when no previous failure."""
        from storyloom.core.co_create import CoCreateFlow
        api = make_mock_api_client()
        flow = CoCreateFlow(api)
        flow._phase = "awaiting_answer"

        with pytest.raises(RuntimeError, match="No failed generate"):
            flow.retry_generate()

    def test_generate_before_first_send_raises(self):
        """generate() before any Q&A raises RuntimeError."""
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient()
        flow = CoCreateFlow(api)
        flow.start()

        with pytest.raises(RuntimeError, match="Cannot generate"):
            flow.generate()


class TestCoCreateFlowSendErrors:
    """Tests for send() error handling — raises CoCreateError, manual retry."""

    def test_send_raises_cocreate_error_on_api_failure(self):
        """API fails → CoCreateError raised with phase='send'."""
        from storyloom.core.co_create import CoCreateFlow, CoCreateError
        api = make_mock_api_client()
        api.chat = lambda msgs: (_ for _ in ()).throw(ApiError("fail"))
        flow = CoCreateFlow(api)
        flow.start()

        with pytest.raises(CoCreateError) as exc_info:
            flow.send("idea")
        assert exc_info.value.phase == "send"
        assert "fail" in exc_info.value.message
        # Phase unchanged — user can retry
        assert flow.phase == "awaiting_idea"

    def test_send_preserves_message_on_failure(self):
        """API failure keeps user message in _messages for retry."""
        from storyloom.core.co_create import CoCreateFlow, CoCreateError
        api = make_mock_api_client()
        api.chat = lambda msgs: (_ for _ in ()).throw(ApiError("fail"))
        flow = CoCreateFlow(api)
        flow.start()

        try:
            flow.send("retry me")
        except CoCreateError:
            pass

        # User message must remain for manual retry
        user_msgs = [m for m in flow._messages if m["role"] == "user"]
        assert any("retry me" in m.get("content", "") for m in user_msgs)

    def test_send_sets_retry_state_on_failure(self):
        """API failure sets _retry_state to ('send', user_input)."""
        from storyloom.core.co_create import CoCreateFlow, CoCreateError
        api = make_mock_api_client()
        api.chat = lambda msgs: (_ for _ in ()).throw(ApiError("fail"))
        flow = CoCreateFlow(api)
        flow.start()

        try:
            flow.send("my idea")
        except CoCreateError:
            pass

        assert flow._retry_state is not None
        assert flow._retry_state[0] == "send"
        assert flow._retry_state[1] == "my idea"

    def test_retry_send_raises_when_no_failure(self):
        """retry_send() raises RuntimeError when no previous failure."""
        from storyloom.core.co_create import CoCreateFlow
        api = make_mock_api_client()
        flow = CoCreateFlow(api)
        flow.start()

        with pytest.raises(RuntimeError, match="No failed send"):
            flow.retry_send()

    def test_retry_send_reattempts_api(self):
        """After send fails, retry_send() re-calls API and returns reply."""
        from storyloom.core.co_create import CoCreateFlow, CoCreateError
        api = make_mock_api_client()
        api.chat = lambda msgs: "Hello from retry!"
        flow = CoCreateFlow(api)
        flow.start()

        # Simulate a failed send
        flow._retry_state = ("send", "idea")
        flow._messages.append({"role": "user", "content": "idea"})

        reply = flow.retry_send()
        assert reply == "Hello from retry!"
        assert flow.phase == "awaiting_answer"
        assert flow._retry_state is None  # cleared

    def test_retry_send_clears_state_on_success(self):
        """retry_send() clears _retry_state after success."""
        from storyloom.core.co_create import CoCreateFlow
        api = make_mock_api_client()
        api.chat = lambda msgs: "ok"
        flow = CoCreateFlow(api)
        flow.start()
        flow._retry_state = ("send", "idea")
        flow._messages.append({"role": "user", "content": "idea"})

        flow.retry_send()
        assert flow._retry_state is None

    def test_retry_send_reraises_api_error(self):
        """retry_send() raises CoCreateError again if API still fails."""
        from storyloom.core.co_create import CoCreateFlow, CoCreateError
        api = make_mock_api_client()
        api.chat = lambda msgs: (_ for _ in ()).throw(ApiError("still broken"))
        flow = CoCreateFlow(api)
        flow.start()
        flow._retry_state = ("send", "idea")
        flow._messages.append({"role": "user", "content": "idea"})

        with pytest.raises(CoCreateError) as exc_info:
            flow.retry_send()
        assert "still broken" in exc_info.value.message
        # _retry_state preserved for another attempt
        assert flow._retry_state is not None


class TestGenerate:
    """Tests for generate() — inject format prompt, parse, validate."""

    def test_generate_success(self):
        from storyloom.core.co_create import CoCreateFlow
        api = MockApiClient(responses=[FULL_GENERATION_RESPONSE])
        flow = CoCreateFlow(api)
        flow._messages = [
            {"role": "system", "content": "test"},
            {"role": "user", "content": "idea"},
            {"role": "assistant", "content": "q"},
        ]
        flow._phase = "awaiting_answer"

        result = flow.generate()
        assert result.story_config["genre"] == "赛博朋克冒险"
        assert len(result.outline_nodes) == 5
        assert flow.phase == "complete"
