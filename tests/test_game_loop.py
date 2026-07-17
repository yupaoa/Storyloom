"""Tests for game_loop module."""

from pathlib import Path

import pytest
from storyloom.core.game_loop import GameLoop, GameState, SetResult, RoundResult
from storyloom.parser import SetOperation


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
  <opt key="1" branch="take_lead">先开口</opt>
  <opt key="2" branch="wait">保持沉默</opt>
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

    def test_clamps_out_of_range_high(self):
        """Number variables out of range [0,100] should be clamped silently.

        Per block-spec.md §5: out-of-range → clamp to boundary, accepted=True.
        """
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="体力", op="+", val="50", condition=None)
        result = gs.apply_set(op, {})
        assert result.accepted
        assert "clamped" in (result.reason or "")
        assert gs.state_vars["体力"] == 100

    def test_clamps_out_of_range_low(self):
        """Number variables below 0 should be clamped to 0."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="体力", op="-", val="200", condition=None)
        result = gs.apply_set(op, {})
        assert result.accepted
        assert "clamped" in (result.reason or "")
        assert gs.state_vars["体力"] == 0

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
        assert result.accepted
        assert result.reason == "skipped: condition not met"
        assert gs.state_vars["信任度"] == 10  # Unchanged

    def test_rejects_nonexistent_variable(self):
        """Setting a variable that doesn't exist should be silently rejected."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="不存在变量", op="+", val="10", condition=None)
        result = gs.apply_set(op, {})
        assert not result.accepted
        assert "unknown variable" in result.reason

    def test_applies_string_assignment(self):
        """String variable assignment should work."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="所属势力", op="=", val="荒坂重工", condition=None)
        result = gs.apply_set(op, {})
        assert result.accepted
        assert gs.state_vars["所属势力"] == "荒坂重工"

    def test_rejects_invalid_operation_for_type(self):
        """Invalid operation for a type should raise."""
        gs = GameState(SAMPLE_STORY_CONFIG)
        op = SetOperation(var="体力", op="+", val="not_a_number", condition=None)
        result = gs.apply_set(op, {})
        assert not result.accepted

    def test_rejects_unknown_variable_type(self):
        """GameState should raise ValueError for unsupported variable types."""
        config = {
            "variables": [{"name": "test", "type": "list", "initial": []}]
        }
        with pytest.raises(ValueError, match="Unknown variable type"):
            GameState(config)

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


def _run_round(game_loop, choice_key=None):
    """Drive one round via stream_round(), feeding choice_key at options.

    Replaces the old ``start_round1()`` / ``continue_round(key)``
    convenience wrappers.
    """
    gen = game_loop.stream_round()
    choice_fed = False
    try:
        event = next(gen)
        while True:
            if (event["type"] == "options"
                    and choice_key is not None
                    and not choice_fed):
                event = gen.send(choice_key)
                choice_fed = True
            elif event["type"] == "error":
                raise RuntimeError(event["message"])
            event = next(gen)
    except StopIteration:
        pass


class TestGameLoopInit:
    def test_initializes_with_defaults(self):
        """GameLoop should initialize with minimal arguments."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        assert loop.round_count == 0
        assert loop.story_config is SAMPLE_STORY_CONFIG
        assert loop.current_node is None

    def test_initializes_with_observers(self):
        """GameLoop should accept observers list and deprecated observer."""
        calls = []

        def obs(record):
            calls.append(record)

        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
            observers=[obs],
        )
        assert len(loop._observers) == 1

        # Deprecated single observer also works
        loop2 = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
            observer=obs,
        )
        assert len(loop2._observers) == 1

        # Both merged
        loop3 = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
            observers=[obs],
            observer=obs,
        )
        assert len(loop3._observers) == 2

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
    """Round 1 tests — now use start_game() + _run_round()."""

    def test_round1_increments_count(self):
        """Round 1 should set round_count to 1."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        loop.start_game()
        _run_round(loop)
        assert loop.round_count == 1

    def test_round1_parses_xml(self):
        """Round 1 should parse the API response into ParsedOutput."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        loop.start_game()
        _run_round(loop)
        assert loop.last_parsed is not None
        assert len(loop.last_parsed.segments) > 0

    def test_start_game_cannot_be_called_twice(self):
        """start_game should raise if called again."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        loop.start_game()
        with pytest.raises(RuntimeError, match="Round 1 already started"):
            loop.start_game()

    def test_round1_sends_messages_to_api(self):
        """Round 1 should pass messages to the API client."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        loop.start_game()
        _run_round(loop)
        assert mock.last_messages is not None
        assert len(mock.last_messages) > 0

    def test_round1_sets_current_node(self):
        """Round 1 should set current_node from config."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
            current_node="ch1_bar",
            goal="开场：进入酒吧",
        )
        loop.start_game()
        _run_round(loop)
        assert loop.current_node is not None

    def test_available_options_after_round1(self):
        """After round 1, available options should be populated."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        loop.start_game()
        _run_round(loop)
        options = loop.get_available_options()
        assert len(options) > 0
        assert options[0]["branch"] == "take_lead"


class TestGameLoopContinueRound:
    """Continue-round tests — now use start_game() + _run_round()."""

    def test_round2_increments_count(self):
        """Round 2 should increment round count."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        loop.start_game()
        _run_round(loop)
        _run_round(loop, choice_key="1")
        assert loop.round_count == 2

    def test_round2_applies_state_changes(self):
        """Round 2 should apply state changes from parsed XML."""
        mock = MockApiClient()
        gs = GameState(SAMPLE_STORY_CONFIG)
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
            game_state=gs,
        )
        loop.start_game()
        _run_round(loop)
        _run_round(loop, choice_key="1")
        assert gs.state_vars["体力"] == 70  # 80 - 10

    def test_stream_round_without_start_game_raises(self):
        """stream_round should raise if start_game wasn't called."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        with pytest.raises(RuntimeError, match="start_game"):
            next(loop.stream_round())

    def test_round2_picks_different_branch(self):
        """Different choice should apply different state changes."""
        mock = MockApiClient()
        gs = GameState(SAMPLE_STORY_CONFIG)
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
            game_state=gs,
        )
        loop.start_game()
        _run_round(loop)
        _run_round(loop, choice_key="2")
        assert gs.state_vars["信任度"] == 15  # 10 + 5

    def test_round2_sends_context_to_api(self):
        """Round 2 should send context messages to API."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        loop.start_game()
        _run_round(loop)
        _run_round(loop, choice_key="1")
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
        loop.start_game()
        _run_round(loop)
        assert loop.last_parsed.choices == []
        assert loop.last_parsed.bridge_found

    def test_simple_xml_no_options(self):
        """A simple XML should return empty options list."""
        mock = MockApiClient(response=SIMPLE_XML)
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        loop.start_game()
        _run_round(loop)
        options = loop.get_available_options()
        assert options == []

    def test_continue_without_choice(self):
        """Round 2 should work without a choice (passing None)."""
        mock = MockApiClient(response=SIMPLE_XML)
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        loop.start_game()
        _run_round(loop)
        _run_round(loop, choice_key=None)
        assert loop.round_count == 2


class TestGameLoopAdventureLog:
    def test_without_game_state(self):
        """Adventure log should work without a game state."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        loop.start_game()
        _run_round(loop)
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
        loop.start_game()
        _run_round(loop)
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
        loop.start_game()
        _run_round(loop)
        route = loop.evaluate_routes({"approach": 1})
        assert route is not None


class TestGameLoopLastParsed:
    def test_last_parsed_is_accessible(self):
        """The last parsed output should be accessible after round 1."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        loop.start_game()
        _run_round(loop)
        assert loop.last_parsed is not None


class TestGameStateSerialization:
    def test_to_dict_returns_state_vars(self):
        story_config = {
            "variables": [
                {"name": "体力", "type": "number", "initial": 80},
                {"name": "信任度", "type": "number", "initial": 10},
            ]
        }
        gs = GameState(story_config)
        data = gs.to_dict()
        assert data == {"state_vars": {"体力": 80, "信任度": 10}}

    def test_from_dict_preserves_original_initial_values(self):
        story_config = {
            "variables": [
                {"name": "体力", "type": "number", "initial": 80},
            ]
        }
        save_state = {"state_vars": {"体力": 30}}
        gs = GameState.from_dict(save_state, story_config)
        assert gs.state_vars == {"体力": 30}

    def test_from_dict_roundtrip(self):
        story_config = {
            "variables": [
                {"name": "体力", "type": "number", "initial": 100},
            ]
        }
        gs1 = GameState(story_config)
        gs1._state_vars["体力"] = 50
        data = gs1.to_dict()
        gs2 = GameState.from_dict(data, story_config)
        assert gs2.state_vars == gs1.state_vars


class TestGameLoopAdventureLogRetry:
    """Tests for adventure log manual retry (unified with narrative phase)."""

    def test_retry_adventure_log_raises_when_no_failure(self):
        """retry_adventure_log() raises RuntimeError when no previous failure."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        with pytest.raises(RuntimeError, match="No failed adventure log"):
            loop.retry_adventure_log()

    def test_retry_adventure_log_raises_before_any_call(self):
        """retry_adventure_log() raises before run_adventure_log() ever called."""
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        assert loop._adv_retry_prompt is None
        with pytest.raises(RuntimeError):
            loop.retry_adventure_log()

    def test_run_adventure_log_saves_prompt(self):
        """run_adventure_log() saves the prompt to _adv_retry_prompt."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        loop.run_adventure_log()
        assert loop._adv_retry_prompt is not None
        assert isinstance(loop._adv_retry_prompt, str)
        assert len(loop._adv_retry_prompt) > 0

    def test_run_adventure_log_resets_error(self):
        """run_adventure_log() clears _adv_error before calling API."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        # Simulate a previous error
        loop._adv_error = "Previous failure"
        loop.run_adventure_log()
        assert loop._adv_error is None

    def test_retry_adventure_log_resets_error(self):
        """retry_adventure_log() clears _adv_error and starts new thread."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        # Simulate a previous failed run
        loop._adv_retry_prompt = "test prompt"
        loop._adv_error = "Previous failure"
        loop._adv_result = "stale result"

        loop.retry_adventure_log()

        assert loop._adv_error is None
        assert loop._adv_thread is not None  # new thread started
        # Note: _adv_result may be set by the daemon thread before we
        # reach here (mock chat() is synchronous), so we don't assert
        # on its value.

    def test_retry_adventure_log_starts_new_thread(self):
        """retry_adventure_log() starts a new daemon thread."""
        mock = MockApiClient()
        loop = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=mock,
        )
        loop._adv_retry_prompt = "test prompt"
        old_thread = getattr(loop, '_adv_thread', None)

        loop.retry_adventure_log()

        assert loop._adv_thread is not None
        assert loop._adv_thread != old_thread
        assert loop._adv_thread.daemon is True


class TestCheckpointHistory:
    """Tests for GameLoop.checkpoint_history property."""

    def test_returns_empty_list_when_no_checkpoints(self):
        """checkpoint_history returns [] before any checkpoints occur."""
        gl = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        assert gl.checkpoint_history == []
        assert isinstance(gl.checkpoint_history, list)

    def test_returns_copy_not_internal_reference(self):
        """checkpoint_history returns a copy, not the internal list."""
        gl = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
        )
        history = gl.checkpoint_history
        history.append({"node": "fake", "title": "x", "summary": "x", "round": 99})
        assert gl.checkpoint_history == []  # internal list unchanged


class TestOutlineNodes:
    """Tests for GameLoop.outline_nodes property."""

    def test_returns_list_of_nodes_with_required_keys(self):
        """outline_nodes returns list of dicts with id, title, goal, status, branches."""
        outline_nodes = [
            {"id": "ch1_intro", "title": "Intro", "goal": "Start the story",
             "routes": [{"condition": None, "target": "ch2_next"}]},
        ]
        gl = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
            current_node="ch1_intro",
            outline_nodes=outline_nodes,
        )
        result = gl.outline_nodes
        assert len(result) == 1
        node = result[0]
        assert node["id"] == "ch1_intro"
        assert node["title"] == "Intro"
        assert node["goal"] == "Start the story"
        assert node["status"] == "active"
        assert node["branches"] == ["ch2_next"]

    def test_returns_copy_not_internal_reference(self):
        """outline_nodes returns a copy."""
        outline_nodes = [
            {"id": "ch1_intro", "title": "Intro", "goal": "Start",
             "routes": []},
        ]
        gl = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
            outline_nodes=outline_nodes,
        )
        result = gl.outline_nodes
        result[0]["id"] = "hacked"
        assert gl.outline_nodes[0]["id"] == "ch1_intro"  # internal unchanged

    def test_status_computed_correctly(self):
        """Status is active/completed/pending based on current_node and _completed_nodes."""
        outline_nodes = [
            {"id": "ch1", "title": "One", "goal": "First",
             "routes": [{"condition": None, "target": "ch2"}]},
            {"id": "ch2", "title": "Two", "goal": "Second",
             "routes": [{"condition": None, "target": "ch3"}]},
            {"id": "ch3", "title": "Three", "goal": "Third", "routes": []},
        ]
        gl = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
            current_node="ch2",
            outline_nodes=outline_nodes,
        )
        # Mark ch1 as completed
        gl._completed_nodes = ["ch1"]

        result = gl.outline_nodes
        assert result[0]["status"] == "completed"  # ch1
        assert result[1]["status"] == "active"      # ch2 (current)
        assert result[2]["status"] == "pending"     # ch3

    def test_normalizes_loaded_save_format(self):
        """Nodes from save format (node_id, branches keys) are normalized to id, branches."""
        # Simulate save-format nodes (from from_save_dict)
        save_format_nodes = [
            {"node_id": "ch1_intro", "title": "Intro", "goal": "Start",
             "status": "completed", "branches": ["ch2_next"]},
        ]
        gl = GameLoop(
            story_config=SAMPLE_STORY_CONFIG,
            outline_text=SAMPLE_OUTLINE,
            api_client=MockApiClient(),
            current_node="ch2_next",
            outline_nodes=save_format_nodes,
        )
        # Mark ch1 as completed (it is in save format, but status computed dynamically)
        gl._completed_nodes = ["ch1_intro"]

        result = gl.outline_nodes
        assert len(result) == 1
        node = result[0]
        assert node["id"] == "ch1_intro"       # normalized from node_id
        assert node["branches"] == ["ch2_next"]  # normalized from branches
        assert node["status"] == "completed"     # computed dynamically
