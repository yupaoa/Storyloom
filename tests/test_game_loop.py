"""Tests for game_loop module."""

from pathlib import Path

import pytest
from storyloom.game_loop import GameLoop, GameState, SetResult, RoundResult
from storyloom.xml_parser import SetOperation


# ── Fixtures ───────────────────────────────────────────────────────

SAMPLE_STORY_CONFIG = {
    "genre": "赛博朋克冒险",
    "tier": "medium",
    "label": "霓虹深渊",
    "setting": "2087年新东京地下城",
    "protagonist_name": "林焰",
    "protagonist_identity": "前荒坂安全顾问",
    "protagonist_traits": "冷静、道德灰色",
    "tone": "黑暗冷峻",
    "conflict": "一枚神秘芯片正在寻找宿主",
    "characters": "耗子（情报贩子）、美智子（安全主管）",
    "variables": [
        {"name": "体力", "type": "number", "initial": 80},
        {"name": "信任度", "type": "number", "initial": 10},
        {"name": "所属势力", "type": "string", "initial": "自由佣兵"},
        {"name": "物品", "type": "list", "initial": []},
    ],
}

SAMPLE_OUTLINE = """ch1_bar [completed] — 霓虹深渊：在酒吧获取情报
  → ch2_confrontation [active]
ch2_confrontation [active] — 地下交易：与耗子会面
  ├→ ch3_ally [pending]
  └→ ch3_betrayal [pending]
ch3_ally [pending] — 盟友之路：通过地下网络逃离
ch3_betrayal [pending] — 背叛之路：杀出重围
ch4_safehouse [pending] — 安全屋：揭开芯片秘密（结局）"""

SAMPLE_XML = """<story>
<seg n="1">炉火噼啪作响。</seg>
<seg n="2">旅店老板: 这么晚了还赶路？</seg>
<seg n="3">疤脸人摘下兜帽。</seg>
<seg n="4">疤脸人: 坐。听说你在找一样东西。</seg>
<choice id="approach">
  <opt key="A" branch="take_lead">先开口</opt>
  <opt key="B" branch="wait">保持沉默</opt>
</choice>
<set var="体力" op="-" val="10" if="approach==1"/>
<set var="信任度" op="+" val="5" if="approach==2"/>
<checkpoint node="ch2_meeting" summary="在旅店接头。">
  <route if="approach==1" target="ch3_lead"/>
</checkpoint>
<bridge/>
<branch name="take_lead">
<seg n="5">你在他对面坐下。</seg>
</branch>
<branch name="wait">
<seg n="6">你站着没动。</seg>
</branch>
</story>"""

SIMPLE_XML = """<story>
<seg n="1">开场叙事。</seg>
<bridge/>
</story>"""


class MockApiResult:
    """Minimal ApiResult-like object for testing."""
    def __init__(self, content: str, ttft: float | None = None,
                 tokens: dict | None = None):
        self.content = content
        self.ttft = ttft
        self.tokens = tokens


class MockApiClient:
    """Mock API client for testing."""

    def __init__(self, response: str = SAMPLE_XML):
        self.response = response
        self.last_messages = None

    def stream_chat_iter(self, messages: list[dict]):
        """Yield tokens from response, then done chunk (matches ApiClient)."""
        self.last_messages = messages
        # Yield one chunk per character (simulates per-token streaming)
        for char in self.response:
            yield {"delta": char}
        yield {
            "usage": {"prompt": 100, "completion": 50, "total": 150},
            "done": True,
        }

    def stream_chat(self, messages: list[dict]) -> MockApiResult:
        """Convenience wrapper around stream_chat_iter."""
        collected = []
        ttft = None
        tokens = None
        for chunk in self.stream_chat_iter(messages):
            if chunk.get("done"):
                tokens = chunk.get("usage")
            else:
                if chunk.get("ttft") is not None:
                    ttft = chunk["ttft"]
                collected.append(chunk["delta"])
        return MockApiResult("".join(collected), ttft=ttft or 0.5,
                            tokens=tokens or {"prompt": 100, "completion": 50, "total": 150})

    def chat(self, messages: list[dict]) -> str:
        self.last_messages = messages
        return self.response


# ── GameState Tests ───────────────────────────────────────────────

class TestGameStateInit:
    def test_initializes_from_story_config(self):
        """GameState should initialize with variables from story_config."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        assert gs.state_vars["体力"] == 80
        assert gs.state_vars["信任度"] == 10
        assert gs.state_vars["所属势力"] == "自由佣兵"
        assert gs.state_vars["物品"] == []

    def test_raises_on_unknown_variable_type(self):
        """GameState should raise on unsupported variable type."""
        config = {
            "variables": [
                {"name": "foo", "type": "unknown", "initial": 0},
            ]
        }
        with pytest.raises(ValueError, match="Unknown variable type"):
            GameState(config)

    def test_empty_variables_list(self):
        """GameState should handle empty variables list."""
        gs = GameState({"variables": []})
        assert gs.state_vars == {}

    def test_missing_variables_key(self):
        """GameState should handle missing variables key."""
        gs = GameState({})
        assert gs.state_vars == {}


class TestGameStateApplySet:
    def test_applies_decrement_operation(self):
        """Subtraction from a number variable should work."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="体力", op="-", val="10", condition=None)
        result = gs.apply_set(op, {})
        assert result.accepted
        assert gs.state_vars["体力"] == 70

    def test_applies_increment_operation(self):
        """Addition to a number variable should work."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="信任度", op="+", val="15", condition=None)
        result = gs.apply_set(op, {})
        assert result.accepted
        assert gs.state_vars["信任度"] == 25

    def test_applies_assignment_operation(self):
        """Assignment operation for numbers should work."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="体力", op="=", val="50", condition=None)
        result = gs.apply_set(op, {})
        assert result.accepted
        assert gs.state_vars["体力"] == 50

    def test_applies_set_to_zero(self):
        """Assignment with =N should set to N."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="体力", op="=", val="0", condition=None)
        result = gs.apply_set(op, {})
        assert result.accepted
        assert gs.state_vars["体力"] == 0

    def test_rejects_out_of_range_high(self):
        """Number variables should be clamped/rejected outside [0,100]."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="体力", op="+", val="50", condition=None)
        result = gs.apply_set(op, {})
        assert not result.accepted
        # Value should remain unchanged
        assert gs.state_vars["体力"] == 80

    def test_rejects_out_of_range_low(self):
        """Number variables below 0 should be rejected."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="体力", op="-", val="200", condition=None)
        result = gs.apply_set(op, {})
        assert not result.accepted
        assert gs.state_vars["体力"] == 80

    def test_evaluates_condition_true(self):
        """Condition should be evaluated against choice_dict."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="信任度", op="+", val="5", condition="approach==1")
        result = gs.apply_set(op, {"approach": 1})
        assert result.accepted
        assert gs.state_vars["信任度"] == 15

    def test_evaluates_condition_false(self):
        """Condition returning false should skip the operation."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="信任度", op="+", val="5", condition="approach==1")
        result = gs.apply_set(op, {"approach": 2})
        assert result.accepted  # Accepted but skipped
        assert gs.state_vars["信任度"] == 10  # Unchanged

    def test_raises_on_nonexistent_variable(self):
        """Setting a variable that doesn't exist should raise."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="不存在变量", op="+", val="10", condition=None)
        with pytest.raises(ValueError, match="unknown variable"):
            gs.apply_set(op, {})

    def test_applies_string_assignment(self):
        """String variable assignment should work."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="所属势力", op="=", val="荒坂重工", condition=None)
        result = gs.apply_set(op, {})
        assert result.accepted
        assert gs.state_vars["所属势力"] == "荒坂重工"

    def test_applies_list_add(self):
        """Adding to a list variable should work."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="物品", op="+", val="神秘芯片", condition=None)
        result = gs.apply_set(op, {})
        assert result.accepted
        assert "神秘芯片" in gs.state_vars["物品"]

    def test_applies_list_remove(self):
        """Removing from a list variable should work."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        # First add
        gs.apply_set(SetOperation(var="物品", op="+", val="神秘芯片", condition=None), {})
        assert "神秘芯片" in gs.state_vars["物品"]
        # Then remove
        result = gs.apply_set(SetOperation(var="物品", op="-", val="神秘芯片", condition=None), {})
        assert result.accepted
        assert "神秘芯片" not in gs.state_vars["物品"]

    def test_rejects_invalid_operation_for_type(self):
        """Invalid operation for a type should raise."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="体力", op="+", val="not_a_number", condition=None)
        result = gs.apply_set(op, {})
        assert not result.accepted

    def test_rejects_list_add_on_non_list(self):
        """String vars should raise on list operations."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="所属势力", op="+", val="新势力", condition=None)
        with pytest.raises(ValueError, match="Invalid string operation"):
            gs.apply_set(op, {})

    def test_condition_against_state_variable(self):
        """Condition can reference state variables."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        gs._state_vars["体力"] = 30  # Low stamina
        op = SetOperation(var="信任度", op="+", val="10", condition="体力<=50")
        result = gs.apply_set(op, {})
        assert result.accepted
        assert gs.state_vars["信任度"] == 20

    def test_condition_against_state_variable_false(self):
        """Condition against state variable returns false."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        gs._state_vars["体力"] = 80  # High stamina
        op = SetOperation(var="信任度", op="+", val="10", condition="体力<=50")
        result = gs.apply_set(op, {})
        assert result.accepted
        assert gs.state_vars["信任度"] == 10  # Unchanged


class TestGameStateConditionEval:
    def test_eq_operator(self):
        gs = GameState(SAMPLE_STORY_CONFIG)
        assert gs.evaluate_condition("approach==1", {"approach": 1})
        assert not gs.evaluate_condition("approach==1", {"approach": 2})

    def test_neq_operator(self):
        gs = GameState(SAMPLE_STORY_CONFIG)
        assert gs.evaluate_condition("approach!=1", {"approach": 2})
        assert not gs.evaluate_condition("approach!=1", {"approach": 1})

    def test_gt_operator(self):
        gs = GameState(SAMPLE_STORY_CONFIG)
        assert gs.evaluate_condition("体力>50", {})
        assert not gs.evaluate_condition("体力>90", {})

    def test_ge_operator(self):
        gs = GameState(SAMPLE_STORY_CONFIG)
        assert gs.evaluate_condition("体力>=80", {})
        assert not gs.evaluate_condition("体力>=90", {})

    def test_lt_operator(self):
        gs = GameState(SAMPLE_STORY_CONFIG)
        assert gs.evaluate_condition("信任度<50", {})
        assert not gs.evaluate_condition("信任度<5", {})

    def test_le_operator(self):
        gs = GameState(SAMPLE_STORY_CONFIG)
        assert gs.evaluate_condition("信任度<=10", {})
        assert not gs.evaluate_condition("信任度<=5", {})

    def test_unknown_variable_in_condition(self):
        gs = GameState(SAMPLE_STORY_CONFIG)
        assert not gs.evaluate_condition("未知变量==1", {})

    def test_condition_is_empty_string(self):
        gs = GameState(SAMPLE_STORY_CONFIG)
        assert gs.evaluate_condition("", {})

    def test_condition_is_none(self):
        gs = GameState(SAMPLE_STORY_CONFIG)
        assert gs.evaluate_condition(None, {})

    def test_value_is_string(self):
        gs = GameState(SAMPLE_STORY_CONFIG)
        assert gs.evaluate_condition("所属势力==自由佣兵", {})
        assert not gs.evaluate_condition("所属势力==荒坂", {})

    def test_and_combinator(self):
        gs = GameState(SAMPLE_STORY_CONFIG)
        assert gs.evaluate_condition("体力>50 and 信任度>5", {})
        assert not gs.evaluate_condition("体力>50 and 信任度>50", {})

    def test_or_combinator(self):
        gs = GameState(SAMPLE_STORY_CONFIG)
        assert gs.evaluate_condition("体力>100 or 信任度>5", {})
        assert not gs.evaluate_condition("体力>100 or 信任度>50", {})


# ── GameLoop Tests ────────────────────────────────────────────────

class TestGameLoopInit:
    def test_initializes_without_display(self):
        """GameLoop should initialize without a display."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        assert loop.round_count == 0
        assert loop.story_config is SAMPLE_STORY_CONFIG

    def test_initializes_with_display(self):
        """GameLoop should initialize with a display."""
        import io
        from storyloom.display import Display
        d = Display(output=io.StringIO())
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
            display=d,
        )
        assert loop.display is d

    def test_initial_node_is_none(self):
        """The current_node should start as None."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        assert loop.current_node is None

    def test_completed_nodes_starts_empty(self):
        """completed_nodes should start as empty list."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        assert loop.completed_nodes == []


class TestGameLoopRound1:
    def test_start_round1_increments_round_count(self):
        """start_round1 should set round_count to 1."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        result = loop.start_round1()
        assert loop.round_count == 1
        assert result.round_number == 1

    def test_start_round1_returns_round_result(self):
        """start_round1 should return a RoundResult."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        result = loop.start_round1()
        assert isinstance(result, RoundResult)
        assert result.parsed is not None

    def test_start_round1_parses_xml(self):
        """start_round1 should parse the API response into ParsedOutput."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        result = loop.start_round1()
        assert len(result.parsed.segments) > 0

    def test_start_round1_cannot_be_called_twice(self):
        """start_round1 should raise if called again."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        loop.start_round1()
        with pytest.raises(RuntimeError, match="Round 1 already started"):
            loop.start_round1()

    def test_start_round1_sends_messages_to_api(self):
        """start_round1 should pass messages to the API client."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        loop.start_round1()
        assert mock.last_messages is not None
        assert len(mock.last_messages) > 0

    def test_start_round1_sets_current_node(self):
        """start_round1 should set current_node from config."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
            current_node="ch1_bar",
            goal="开场：进入酒吧",
        )
        result = loop.start_round1()
        assert loop.current_node is not None

    def test_available_options_after_round1(self):
        """After round 1, available options should be populated."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        loop.start_round1()
        options = loop.get_available_options()
        assert len(options) > 0
        assert options[0]["branch"] == "take_lead"


class TestGameLoopContinueRound:
    def test_continue_round_increments_count(self):
        """continue_round should increment round count."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        loop.start_round1()
        result = loop.continue_round(choice_key="1")
        assert loop.round_count == 2
        assert result.round_number == 2

    def test_continue_round_applies_state_changes(self):
        """continue_round should apply conditional state changes."""
        mock = MockApiClient()
        gs = GameState(SAMPLE_STORY_CONFIG)
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
            game_state=gs,
        )
        loop.start_round1()
        # Option 1 maps to approach==1 → 体力 -= 10
        loop.continue_round(choice_key="1")
        assert gs.state_vars["体力"] == 70  # 80 - 10

    def test_continue_round_without_start_round1_raises(self):
        """continue_round should raise if start_round1 wasn't called."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        with pytest.raises(RuntimeError, match="No last result"):
            loop.continue_round(choice_key="1")

    def test_continue_round_picks_different_branch(self):
        """Different choice should apply different state changes."""
        mock = MockApiClient()
        gs = GameState(SAMPLE_STORY_CONFIG)
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
            game_state=gs,
        )
        loop.start_round1()
        # Option 2 maps to approach==2 → 信任度 += 5
        loop.continue_round(choice_key="2")
        assert gs.state_vars["信任度"] == 15  # 10 + 5

    def test_continue_round_sends_context_to_api(self):
        """continue_round should send context messages to API."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        loop.start_round1()
        loop.continue_round(choice_key="1")
        assert mock.last_messages is not None


class TestGameLoopWithSimpleXml:
    def test_simple_xml_round1(self):
        """A simple XML without choice should work for round 1."""
        mock = MockApiClient(response=SIMPLE_XML)
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        result = loop.start_round1()
        assert result.parsed.choices == []
        assert result.parsed.bridge_found

    def test_simple_xml_no_options(self):
        """A simple XML should return empty options list."""
        mock = MockApiClient(response=SIMPLE_XML)
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        loop.start_round1()
        options = loop.get_available_options()
        assert options == []

    def test_continue_without_choice(self):
        """continue_round should work without a choice (passing None)."""
        mock = MockApiClient(response=SIMPLE_XML)
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        loop.start_round1()
        result = loop.continue_round(choice_key=None)
        assert result.round_number == 2


class TestGameLoopAdventureLog:
    def test_without_game_state(self):
        """Adventure log should work without a game state."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        result = loop.start_round1()
        log = loop.run_adventure_log()
        assert isinstance(log, str)
        assert len(log) > 0

    def test_with_mock_api(self):
        """Adventure log should call API."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        loop.start_round1()
        log = loop.run_adventure_log()
        assert mock.last_messages is not None


class TestGameLoopBranchRoute:
    def test_route_evaluation(self):
        """The game loop should evaluate route conditions."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        loop.start_round1()
        route = loop.evaluate_routes({"approach": 1})
        assert route is not None


class TestGameLoopLastParsed:
    def test_last_parsed_is_accessible(self):
        """The last parsed output should be accessible."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        result = loop.start_round1()
        assert loop.last_parsed is result.parsed
