"""Main narrative game loop, GameState, and result types.

Coordinates all modules: PromptBuilder, ContextManager, ApiClient,
StreamingXmlParser.  Validates all LLM-suggested state changes
(local source of truth).
"""

import copy
import queue
import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Callable

from storyloom.config import SAVE_VERSION, STREAM_STALL_TIMEOUT_SEC
from storyloom.io.api_client import ApiClient
from storyloom.core.context_manager import ContextManager
from storyloom.core.prompt_builder import PromptBuilder
from storyloom.parser import (
    ParsedOutput,
    SetOperation,
)
from storyloom.parser.streaming_parser import (
    EventType,
    LineBuffer,
    ParseEvent,
    StreamingXmlParser,
)


@dataclass
class SetResult:
    """Result of applying a state change suggestion."""

    accepted: bool
    reason: str | None = None


@dataclass
class RoundResult:
    """Result of processing one narrative round."""

    parsed: ParsedOutput
    round_number: int
    ending_triggered: bool = False


@dataclass
class RoundRecord:
    """Snapshot of a completed narrative round for observers.

    Contains everything needed for debugging, testing, and analytics:
    the full messages array sent to the API, the raw LLM response,
    timing data, and the parsed output.
    """

    round_number: int
    messages_sent: list[dict]           # full messages array sent to API
    raw_response: str                   # LLM raw output
    parsed: ParsedOutput | None         # parsed result (None if parse failed)
    ttft: float | None                  # seconds to first token
    tokens: dict | None                 # {"prompt": N, "completion": N, "total": N}
    timestamp: str                      # ISO 8601
    node: str | None                    # current_node this round
    selected_branch: str | None         # player's chosen branch name (None if no choice)


# ── GameState ─────────────────────────────────────────────────────


class GameState:
    """Manages in-memory game state variables.

    The LLM can only SUGGEST changes via <set> elements.
    The program validates each suggestion — type checks, range checks,
    variable existence — before applying.
    """

    VALID_NUMBER_OPS = {"+", "-", "="}
    VALID_STRING_OPS = {"="}
    VALID_LIST_OPS = {"+", "-"}
    NUMBER_MIN = 0
    NUMBER_MAX = 100

    def __init__(self, story_config: dict):
        """Initialize state from story_config.variables.

        Args:
            story_config: Dict with a 'variables' list.
                          Each variable has: name, type, initial.

        Raises:
            ValueError: On unsupported variable type.
        """
        self._state_vars: dict = {}
        self._var_types: dict[str, str] = {}

        variables = story_config.get("variables", [])
        for v in variables:
            name = v["name"]
            var_type = v["type"]
            initial = v["initial"]

            if var_type == "number":
                self._state_vars[name] = int(initial)
            elif var_type == "string":
                self._state_vars[name] = initial
            elif var_type == "list":
                self._state_vars[name] = list(initial) if initial else []
            else:
                raise ValueError(f"Unknown variable type: {var_type}")

            self._var_types[name] = var_type

    @property
    def state_vars(self) -> dict:
        """Return current state variables as a dict copy."""
        return dict(self._state_vars)

    def to_dict(self) -> dict:
        """Serialize state variables to a plain dict.

        Returns:
            Dict with 'state_vars' key containing current values.
        """
        return {
            "state_vars": dict(self._state_vars),
        }

    @classmethod
    def from_dict(cls, data: dict, story_config: dict) -> "GameState":
        """Restore GameState from save data.

        Uses the original story_config for variable type definitions;
        actual state values come from data['state_vars'].

        Args:
            data: Dict with 'state_vars' key from save file.
            story_config: Original story_config from save file
                          (preserves variable definitions with initial values).

        Returns:
            New GameState instance with restored values.
        """
        gs = cls(story_config)
        gs._state_vars = dict(data.get("state_vars", {}))
        return gs

    def apply_set(self, set_op: SetOperation, choice_dict: dict[str, int]) -> SetResult:
        """Validate and apply a state change from the LLM.

        Per block-spec.md §5, all validation failures are returned as
        ``SetResult(accepted=False, reason=...)`` — never raised.  This
        implements the "silent rejection" contract: single-set failure
        does not affect other valid sets in the same round.

        Steps:
        1. Verify variable exists.
        2. Verify operation is valid for the variable type.
        3. For numbers: try int conversion, verify range [0, 100].
        4. For lists: verify the value is not empty.
        5. Evaluate condition if present.
        6. Apply the change.

        Args:
            set_op: The SetOperation from parsed XML.
            choice_dict: Player choice mapping (choice_id -> selected_index).

        Returns:
            SetResult with accepted flag and optional rejection reason.
            Never raises — all failures are communicated via the return
            value so the caller can accumulate rejected_changes.
        """
        var_name = set_op.var

        # Step 1: Verify variable exists (per block-spec.md §5:
        # unknown variable → silently reject, record in rejected_changes).
        if var_name not in self._state_vars:
            return SetResult(
                accepted=False,
                reason=f"unknown variable: {var_name}",
            )

        var_type = self._var_types[var_name]

        # Step 2: Verify operation is valid for type (per block-spec.md §5:
        # type mismatch → silently reject).
        if var_type == "number" and set_op.op not in self.VALID_NUMBER_OPS:
            return SetResult(
                accepted=False,
                reason=f"Invalid number operation: {set_op.op} for {var_name}",
            )
        if var_type == "string" and set_op.op not in self.VALID_STRING_OPS:
            return SetResult(
                accepted=False,
                reason=f"Invalid string operation: {set_op.op} for {var_name}",
            )
        if var_type == "list" and set_op.op not in self.VALID_LIST_OPS:
            return SetResult(
                accepted=False,
                reason=f"Invalid list operation: {set_op.op} for {var_name}",
            )

        # Step 3: Parse/try value
        if var_type == "number":
            try:
                val = int(set_op.val)
            except ValueError:
                return SetResult(
                    accepted=False,
                    reason=f"Cannot parse '{set_op.val}' as integer for {var_name}",
                )
        elif var_type == "list":
            val = set_op.val
            if not val:
                return SetResult(
                    accepted=False,
                    reason=f"Empty value for list operation on {var_name}",
                )
        else:
            val = set_op.val

        # Step 4: Evaluate condition
        if set_op.condition:
            if not self.evaluate_condition(set_op.condition, choice_dict):
                return SetResult(accepted=True)  # Skipped, not rejected

        # Step 5: Apply
        if var_type == "number":
            return self._apply_number_op(var_name, set_op.op, val)
        elif var_type == "string":
            return self._apply_string_op(var_name, val)
        elif var_type == "list":
            return self._apply_list_op(var_name, set_op.op, val)

        return SetResult(accepted=False, reason="Unknown variable type")

    def _apply_number_op(self, var_name: str, op: str, val: int) -> SetResult:
        """Apply a numeric operation with range validation."""
        current = self._state_vars[var_name]

        if op == "=":
            new_val = val
        elif op == "+":
            new_val = current + val
        elif op == "-":
            new_val = current - val
        else:
            return SetResult(accepted=False, reason=f"Unknown op: {op}")

        # Per block-spec.md §5: out-of-range → clamp silently.
        clamped = False
        if new_val < self.NUMBER_MIN:
            new_val = self.NUMBER_MIN
            clamped = True
        elif new_val > self.NUMBER_MAX:
            new_val = self.NUMBER_MAX
            clamped = True

        self._state_vars[var_name] = new_val
        if clamped:
            return SetResult(
                accepted=True,
                reason=f"{var_name} clamped to {new_val} (range [{self.NUMBER_MIN}, {self.NUMBER_MAX}])",
            )
        return SetResult(accepted=True)

    def _apply_string_op(self, var_name: str, val: str) -> SetResult:
        """Apply a string assignment."""
        self._state_vars[var_name] = val
        return SetResult(accepted=True)

    def _apply_list_op(self, var_name: str, op: str, val: str) -> SetResult:
        """Apply a list add/remove operation."""
        current: list = self._state_vars[var_name]

        if op == "+":
            if val not in current:
                current.append(val)
        elif op == "-":
            if val in current:
                current.remove(val)

        return SetResult(accepted=True)

    def evaluate_condition(
        self, condition: str | None, choice_dict: dict[str, int]
    ) -> bool:
        """Evaluate a condition expression against state and choice dict.

        Supports:
        - Comparison: ==, !=, >, >=, <, <=
        - Combinators: and, or
        - Variables from state_vars (by name)
        - Choice variables (by name from choice_dict)

        Args:
            condition: Condition string (e.g., "approach==1", "体力>50").
            choice_dict: Player choice mapping.

        Returns:
            True if condition is met or no condition provided.
        """
        if not condition or not condition.strip():
            return True

        # Handle "and" / "or" combinators
        if " and " in condition:
            parts = condition.split(" and ")
            return all(
                self.evaluate_condition(p.strip(), choice_dict) for p in parts
            )
        if " or " in condition:
            parts = condition.split(" or ")
            return any(
                self.evaluate_condition(p.strip(), choice_dict) for p in parts
            )

        # Parse single condition: var_name operator value
        match = re.match(
            r"^\s*(\w+)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$", condition
        )
        if not match:
            return False

        var_name = match.group(1)
        operator = match.group(2)
        raw_value = match.group(3).strip()

        # Try to get the variable value.
        # Per block-spec.md §3: choice_dict > state_vars priority.
        if var_name in choice_dict:
            var_value = choice_dict[var_name]
        elif var_name in self._state_vars:
            var_value = self._state_vars[var_name]
        else:
            return False

        # Try numeric comparison first
        try:
            numeric_value = int(raw_value)
            var_numeric = int(var_value) if not isinstance(var_value, int) else var_value
            return self._compare_numbers(var_numeric, operator, numeric_value)
        except (ValueError, TypeError):
            pass

        # Fall back to string comparison
        return self._compare_strings(str(var_value), operator, raw_value)

    @staticmethod
    def _compare_numbers(a: int, op: str, b: int) -> bool:
        """Compare two numbers with the given operator."""
        if op == "==":
            return a == b
        elif op == "!=":
            return a != b
        elif op == ">":
            return a > b
        elif op == ">=":
            return a >= b
        elif op == "<":
            return a < b
        elif op == "<=":
            return a <= b
        return False

    @staticmethod
    def _compare_strings(a: str, op: str, b: str) -> bool:
        """Compare two strings with the given operator."""
        if op in ("==", "="):
            return a == b
        elif op == "!=":
            return a != b
        elif op == ">":
            return a > b
        elif op == ">=":
            return a >= b
        elif op == "<":
            return a < b
        elif op == "<=":
            return a <= b
        return False


# ── GameLoop ──────────────────────────────────────────────────────


class GameLoop:
    """Main narrative game loop, coordinating all modules.

    Flow:
    1. start_round1() -> Prompter -> API -> Parser
    2. Player makes choice
    3. continue_round() -> apply state changes -> update outline ->
       build context -> API -> Parser
    4. Repeat from step 2 until ending.
    """

    def __init__(
        self,
        story_config: dict,
        outline_text: str,
        api_client: ApiClient,
        game_state: GameState | None = None,
        current_node: str | None = None,
        goal: str | None = None,
        observers: list[Callable[[RoundRecord], None]] | None = None,
        observer: Callable[[RoundRecord], None] | None = None,
        outline_nodes: list[dict] | None = None,
    ):
        """Initialize game loop with story config and dependencies.

        Args:
            story_config: Story configuration dict.
            outline_text: Formatted outline text.
            api_client: API client for LLM calls.
            game_state: Optional GameState (created from story_config if omitted).
            current_node: Starting node ID (optional).
            goal: Starting node goal description (optional).
            observers: Optional list of observer callbacks invoked after each
                       round completes. Each receives a RoundRecord.
            observer: Deprecated. Single observer (use observers=list instead).
            outline_nodes: Structured outline from co-creation (optional).

        Observer failures are silently ignored (must not break the game loop).
        """
        self.story_config = story_config
        self.outline_text = outline_text
        self._outline_nodes = self._normalize_outline_nodes(outline_nodes or [])
        self.api_client = api_client

        # Internal modules
        self._prompter = PromptBuilder()
        self._context_mgr = ContextManager()

        # Observers — merge deprecated `observer` into list
        obs_list = list(observers) if observers else []
        if observer is not None:
            obs_list.append(observer)
        self._observers: list[Callable[[RoundRecord], None]] = obs_list

        # State
        self.game_state = game_state or GameState(story_config)
        self.current_node = current_node
        self.goal = goal
        self._node_goals: dict[str, str] = self._parse_outline_goals(outline_text)
        self._completed_nodes: list[str] = []
        self.last_parsed: ParsedOutput | None = None
        self._last_bridge_text: str = ""
        self._rejected_changes: list[str] = []
        self._format_error: str | None = None
        self._round1_started = False
        self._current_branch: str = "main"  # active branch from player's last choice

        # Checkpoint and save accumulators
        self._temperature = getattr(api_client, "temperature", None)
        self._checkpoint_summaries: list[str] = []
        self._checkpoint_history: list[dict] = []
        self._checkpoint_snapshots: dict[str, dict] = {}
        self.ending_flag: bool = False
        self._save_manager = None
        self._created_at: str | None = None

        # Bridge pre-fetch state (background API call for auto-advance rounds).
        # Protects _prefetch_data — game loop runs on main thread, pre-fetch
        # API call runs on daemon thread.
        self._prefetch_lock = threading.Lock()
        self._prefetch_data: dict | None = None

    # ── Properties ─────────────────────────────────────────────────

    @property
    def round_count(self) -> int:
        """Current round number (0 before start_round1)."""
        return self._context_mgr.round_count

    @property
    def checkpoint_history(self) -> list[dict]:
        """Return checkpoint history for UI progress display.

        Returns a copy. Each entry: {node, title, summary, round}.
        """
        return list(self._checkpoint_history)

    @property
    def outline_nodes(self) -> list[dict]:
        """Current outline with computed node statuses.

        Returns a copy. Each entry: {id, title, goal, status, branches}.
        Format matches the save file outline structure (data-model.md §3.1).

        Status is computed dynamically: 'active' | 'completed' | 'pending'.
        branches: list of target node ID strings (conditions excluded).

        Normalizes the two internal formats:
          - Fresh: {id, routes: [{condition, target}]}
          - Loaded: {node_id, branches: [str]}
        into a single consistent public shape.
        """
        result = []
        for node in self._outline_nodes:
            nid = node.get("id") or node.get("node_id", "")
            result.append({
                "id": nid,
                "title": node.get("title", ""),
                "goal": node.get("goal", ""),
                "status": (
                    "active" if nid == self.current_node
                    else "completed" if nid in self._completed_nodes
                    else "pending"
                ),
                "branches": [
                    r.get("target", r) if isinstance(r, dict) else r
                    for r in node.get("routes", node.get("branches", []))
                ],
            })
        return result

    @property
    def completed_nodes(self) -> list[str]:
        """List of completed node IDs."""
        return list(self._completed_nodes)

    @property
    def current_branch(self) -> str:
        """Active branch name from the player's last choice.

        Defaults to ``"main"`` per block-spec.md §3.  UI layers use
        this to select which post-bridge ``<branch name="...">``
        content to display.
        """
        return self._current_branch

    # ── Round 1 ───────────────────────────────────────────────────

    def start_round1_stream(self) -> Iterator[dict]:
        """Build Round 1 prompt, stream API response, yield structured events.

        Yields:
            {"type": "token", "text": str}           — per-token LLM output
            {"type": "segment", "text": str, "n": int,
             "position": "pre"|"post", "branch": str|None}
            {"type": "options", "choices": [dict]}   — choice panel
            {"type": "state", "vars": dict}          — state after sets applied
            {"type": "error", "message": str}        — parse failure
            {"type": "done", "round": int, "node": str|None,
             "state": dict}                          — round complete

        Raises:
            RuntimeError: If round 1 was already started.
        """
        if self._round1_started:
            raise RuntimeError("Round 1 already started")

        self._round1_started = True

        # Build Round 1 prompt
        r1_prompt = self._prompter.build_round1(
            story_config=self.story_config,
            outline_text=self.outline_text,
            current_node=self.current_node or "",
            goal=self.goal or "",
        )

        # If resuming from a save, append bridge_text as the first
        # user message per data-model.md §3.5.
        if self._last_bridge_text:
            r1_prompt += (
                "\n\n---\n"
                "Continue from here:\n"
                + self._last_bridge_text
            )

        # Build messages array (Round 1 only has user message)
        messages = [{"role": "user", "content": r1_prompt}]

        # Stream API response token by token with streaming parse.
        # Per exec-flow.md §4.4: StreamingXmlParser produces segment
        # events as soon as a complete line arrives, eliminating the
        # full-generation latency of ElementTree full-parse.
        collected: list[str] = []
        ttft: float | None = None
        tokens: dict | None = None
        lb = LineBuffer()
        sp = StreamingXmlParser()

        for chunk in self.api_client.stream_chat_iter(messages):
            if chunk.get("done"):
                tokens = chunk.get("usage")
            else:
                if chunk.get("ttft") is not None:
                    ttft = chunk["ttft"]
                delta = chunk["delta"]
                collected.append(delta)
                yield {"type": "token", "text": delta}
                yield from self._stream_parse_chunk(
                    delta, lb, sp, self._current_branch
                )

        # Flush any remaining partial line at end-of-stream.
        remaining = lb.flush()
        if remaining:
            yield from self._stream_parse_chunk(
                remaining, lb, sp, self._current_branch
            )

        response = "".join(collected)
        parsed = sp.get_result()

        # Surface format errors detected by the streaming parser.
        format_errors = sp.format_errors
        if format_errors:
            self._format_error = "; ".join(format_errors)

        # Store in context manager with bridge_text filtered by the
        # current_branch that was active when <bridge/> was parsed.
        self._context_mgr.set_round1(
            r1_prompt, response,
            bridge_text=sp.get_bridge_text(self._current_branch),
        )

        # Clear previous format error on successful parse
        self._format_error = None

        # Store parsed output (bridge_text filtered by current_branch
        # per block-spec.md §4 — unselected branches must not leak).
        self.last_parsed = parsed
        self._last_bridge_text = sp.get_bridge_text(self._current_branch)

        # Apply unconditional sets from Round 1
        state_changes: list[dict] = []
        for set_op in parsed.sets:
            if not set_op.condition:
                result = self.game_state.apply_set(set_op, {})
                state_changes.append({
                    "var": set_op.var,
                    "op": set_op.op,
                    "val": set_op.val,
                    "accepted": result.accepted,
                    "reason": result.reason,
                })
                if result.reason:
                    self._rejected_changes.append(result.reason)

        # Yield options (segments were already streamed above).
        yield from self._emit_options(parsed)

        if state_changes:
            yield {
                "type": "state",
                "vars": self.game_state.state_vars,
                "changes": state_changes,
            }

        # Notify observer
        self._notify(RoundRecord(
            round_number=1,
            messages_sent=messages,
            raw_response=response,
            parsed=parsed,
            ttft=ttft,
            tokens=tokens,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            node=self.current_node,
            selected_branch=None,
        ))

        yield {
            "type": "done",
            "round": 1,
            "node": self.current_node,
            "state": self.game_state.state_vars,
        }

    def start_round1(self) -> RoundResult:
        """Build Round 1 prompt, call API, parse response.

        Convenience wrapper that consumes start_round1_stream().
        For streaming/UI use, call start_round1_stream() directly.

        Returns:
            RoundResult with parsed output.

        Raises:
            RuntimeError: If round 1 was already started.
            ParseError: If parsing fails.
        """
        for event in self.start_round1_stream():
            if event["type"] == "error":
                from storyloom.parser import ParseError
                raise ParseError(
                    f"Round 1 parse failed: {event['message']}"
                )

        if self.last_parsed is None:
            from storyloom.parser import ParseError
            raise ParseError("Round 1 parse failed: unknown error")

        return RoundResult(parsed=self.last_parsed, round_number=1)

    # ── Continue Round ────────────────────────────────────────────

    def continue_round_stream(
        self, choice_key: str | None = None
    ) -> Iterator[dict]:
        """Process player choice, stream API response, yield structured events.

        Same event types as start_round1_stream().

        Args:
            choice_key: Player's choice (1-indexed string) or None if
                        no choice was presented.

        Yields:
            Structured event dicts (same schema as start_round1_stream).

        Raises:
            RuntimeError: If start_round1 hasn't been called.
        """
        if self.last_parsed is None:
            raise RuntimeError("No last result - call start_round1 first")

        # ── Guard: ending already triggered ─────────────────────────
        # Per exec-flow.md §5.2 the adventure log is yielded as an
        # "ending" event and the game loop stops.  If the caller issues
        # another continue_round_stream() anyway (e.g. UI auto-advance),
        # short-circuit with a no-op done event.
        if self.ending_flag:
            yield {
                "type": "done",
                "round": self._context_mgr.round_count,
                "node": "end",
                "state": self.game_state.state_vars,
            }
            return

        # ── Fast path: consume pre-fetched API response ────────────
        # _launch_prefetch already applied Steps 2-3.6 and started a
        # background API call.  Drain the buffered response — the only
        # difference from the live path is the response source.
        prefetch = self._take_prefetch(choice_key)
        if prefetch is not None:
            yield from prefetch["state_events"]

            prefetch["thread"].join(timeout=STREAM_STALL_TIMEOUT_SEC)
            if prefetch["thread"].is_alive():
                yield {
                    "type": "error",
                    "message": (
                        "Pre-fetched API call timed out after "
                        f"{STREAM_STALL_TIMEOUT_SEC}s"
                    ),
                }
                return

            lb = LineBuffer()
            sp = StreamingXmlParser()
            collected: list[str] = []
            ttft: float | None = None
            tokens: dict | None = None
            current_branch = self._current_branch

            while True:
                try:
                    chunk = prefetch["queue"].get_nowait()
                except queue.Empty:
                    break
                if "__prefetch_error__" in chunk:
                    yield {
                        "type": "error",
                        "message": f"Pre-fetch API error: {chunk['__prefetch_error__']}",
                    }
                    return
                if chunk.get("done"):
                    tokens = chunk.get("usage")
                else:
                    if chunk.get("ttft") is not None:
                        ttft = chunk["ttft"]
                    delta = chunk["delta"]
                    collected.append(delta)
                    yield {"type": "token", "text": delta}
                    yield from self._stream_parse_chunk(delta, lb, sp, current_branch)

            remaining = lb.flush()
            if remaining:
                yield from self._stream_parse_chunk(remaining, lb, sp, current_branch)

            response = "".join(collected)
            yield from self._finalize_parsed_round(
                sp=sp,
                user_content=prefetch["user_content"],
                response=response,
                messages=prefetch["messages"],
                selected_branch=prefetch.get("selected_branch"),
                current_branch=current_branch,
                ttft=ttft,
                tokens=tokens,
            )

            # Chain pre-fetch for next auto-advance round
            if not self.last_parsed or not self.last_parsed.choices:
                if not self.ending_flag:
                    self._launch_prefetch(choice_key)
            return

        # ── Step 1: Build choice_dict ───────────────────────────────
        choice_dict: dict[str, int] = {}
        if choice_key is not None and self.last_parsed.choice_id is not None:
            try:
                choice_num = int(choice_key)
                choice_dict[self.last_parsed.choice_id] = choice_num
            except ValueError:
                pass

        # Determine selected branch from the player's choice
        selected_branch = self._get_selected_branch(choice_key)
        if selected_branch is not None:
            self._current_branch = selected_branch

        # ── Steps 2-3.6: deferred sets, routes, checkpoint, ending ──
        step2_changes, _ = self._apply_deferred_step(choice_dict)

        if step2_changes:
            yield {
                "type": "state",
                "vars": self.game_state.state_vars,
                "changes": step2_changes,
            }

        # ── Step 4: Build Round N context ───────────────────────────
        compressed_summaries = self._context_mgr.get_compressed_summaries() or None
        bridge_text = self._context_mgr.get_last_bridge_text()

        rn_context = self._prompter.build_round_n(
            current_node=self.current_node or "",
            goal=self.goal or "",
            completed_nodes=self._completed_nodes,
            state_vars=self.game_state.state_vars,
            bridge_text=bridge_text,
            compressed_summaries=compressed_summaries,
            rejected_changes=(
                self._rejected_changes if self._rejected_changes else None
            ),
            format_error=self._format_error,
        )

        # ── Step 5: Assemble messages ───────────────────────────────
        messages = self._context_mgr.get_messages()
        messages.append({"role": "user", "content": rn_context})

        # ── Step 6: Stream API response with streaming parse ────────
        # Per exec-flow.md §4.4: StreamingXmlParser eliminates the
        # full-generation latency of ElementTree full-parse.
        collected: list[str] = []
        ttft: float | None = None
        tokens: dict | None = None
        lb = LineBuffer()
        sp = StreamingXmlParser()

        for chunk in self.api_client.stream_chat_iter(messages):
            if chunk.get("done"):
                tokens = chunk.get("usage")
            else:
                if chunk.get("ttft") is not None:
                    ttft = chunk["ttft"]
                delta = chunk["delta"]
                collected.append(delta)
                yield {"type": "token", "text": delta}
                yield from self._stream_parse_chunk(
                    delta, lb, sp, self._current_branch
                )

        # Flush remaining partial line at end-of-stream.
        remaining = lb.flush()
        if remaining:
            yield from self._stream_parse_chunk(
                remaining, lb, sp, self._current_branch
            )

        response = "".join(collected)

        # ── Bridge pre-fetch: fire next API call for auto-advance ─
        # Per exec-flow.md §4.7 the next round's prompt is assembled at
        # <bridge/> time so the post-bridge segments (bridge_text) act as
        # a display buffer that hides the API latency.
        # MUST be called *before* _finalize_parsed_round — the background
        # API call runs concurrently with segment/adventure-log display.
        #
        # Capture state snapshot first: _launch_prefetch mutates
        # game_state, current_node, and current_branch for the next round
        # (applies deferred sets + evaluates routes).  The "done" event
        # must reflect the state as it was at the END of THIS round.
        done_node = self.current_node
        done_state = self.game_state.state_vars
        done_round = self._context_mgr.round_count
        if not self.ending_flag:
            parsed_pre = sp.get_result()
            if not parsed_pre.choices:
                self._launch_prefetch(choice_key)

        yield from self._finalize_parsed_round(
            sp=sp,
            user_content=rn_context,
            response=response,
            messages=messages,
            selected_branch=selected_branch,
            current_branch=self._current_branch,
            ttft=ttft,
            tokens=tokens,
            done_node=done_node,
            done_state=done_state,
            done_round=done_round,
        )

    def continue_round(self, choice_key: str | None = None) -> RoundResult:
        """Process player choice, build context, call API, parse response.

        Convenience wrapper that consumes continue_round_stream().
        For streaming/UI use, call continue_round_stream() directly.

        Args:
            choice_key: Player's choice (1-indexed string) or None if
                        no choice was presented.

        Returns:
            RoundResult with parsed output.

        Raises:
            RuntimeError: If start_round1 hasn't been called.
            ParseError: If parsing fails.
        """
        for event in self.continue_round_stream(choice_key):
            if event["type"] == "error":
                from storyloom.parser import ParseError
                raise ParseError(
                    f"Round {self._context_mgr.round_count + 1} parse "
                    f"failed: {event['message']}"
                )

        if self.last_parsed is None:
            from storyloom.parser import ParseError
            raise ParseError(
                f"Round {self._context_mgr.round_count + 1} parse "
                f"failed: unknown error"
            )

        return RoundResult(
            parsed=self.last_parsed,
            round_number=self._context_mgr.round_count,
        )

    # ── Event Emission ───────────────────────────────────────────

    @staticmethod
    def _emit_options(parsed: ParsedOutput) -> Iterator[dict]:
        """Yield options event if the parsed output contains choices."""
        if parsed.choices:
            yield {
                "type": "options",
                "choices": parsed.choices,
            }

    @staticmethod
    def _stream_parse_chunk(
        text: str,
        lb: LineBuffer,
        sp: StreamingXmlParser,
        current_branch: str,
    ) -> Iterator[dict]:
        """Feed a token chunk through the streaming parse pipeline.

        Token chunks are accumulated into complete lines by *lb*; each
        complete line is fed to *sp*.

        Branch filter (applies to *both* pre- and post-bridge): bare
        ``<seg>`` elements (no enclosing ``<branch>``) always pass;
        named-branch segs pass only when they match *current_branch*.

        Post-bridge ``<choice>`` / ``<set>`` / ``<checkpoint>`` are
        flagged as format errors by ``StreamingXmlParser`` but are never
        yielded to the UI — they are surfaced via ``sp.format_errors``
        after ``get_result()``.

        Yields ``{"type": "story_begin"}``, ``{"type": "story_end"}``,
        ``{"type": "segment", ...}``, and ``{"type": "bridge"}`` events
        as lines complete.
        """
        for line in lb.feed(text):
            for event in sp.feed_line(line):
                if event.type == EventType.STORY_BEGIN:
                    yield {"type": "story_begin"}
                elif event.type == EventType.STORY_END:
                    yield {"type": "story_end"}
                elif event.type == EventType.BRIDGE:
                    yield {"type": "bridge"}
                elif event.type == EventType.SEGMENT:
                    # Bare segs (branch_name is None) always pass.
                    # Named-branch segs pass only when they match
                    # current_branch.  Applies to both pre- and
                    # post-bridge per block-spec.md §3.
                    if (event.branch_name
                            and event.branch_name != current_branch):
                        continue
                    yield {
                        "type": "segment",
                        "text": event.text or "",
                        "n": sp._seg_count,
                        "position": event.position,
                        "branch": event.branch_name,
                    }

    # ── Round Finalization ─────────────────────────────────────────

    def _finalize_parsed_round(
        self,
        sp: StreamingXmlParser,
        user_content: str,
        response: str,
        messages: list[dict],
        selected_branch: str | None,
        current_branch: str,
        ttft: float | None = None,
        tokens: dict | None = None,
        done_node: str | None = None,
        done_state: dict | None = None,
        done_round: int | None = None,
    ) -> Iterator[dict]:
        """Shared post-parse processing for continue_round_stream
        (both live and pre-fetch paths).

        Handles: parsed extraction, format errors, end checkpoint,
        store in context, unconditional sets, adventure log launch,
        options yield, ending/done events, observer notification.

        Callers handle pre-fetch at their own timing (before or after
        this method), since the two paths differ in when state snapshots
        must be captured.

        *done_node*, *done_state*, and *done_round* are snapshots taken
        BEFORE pre-fetch mutation.  When omitted they default to the
        current live values (correct for the pre-fetch path).
        """
        # ── Get complete parsed output ──────────────────────────────
        self._format_error = None  # clear previous error
        parsed = sp.get_result()
        format_errors = sp.format_errors
        if format_errors:
            self._format_error = "; ".join(format_errors)

        # ── Post-parse: handle "end" checkpoint ─────────────────────
        if parsed.checkpoint_node == "end":
            self._accumulate_checkpoint("end", parsed.checkpoint_summary or "")
            self.ending_flag = True
            if "end" not in self._completed_nodes:
                self._completed_nodes.append("end")

        # ── Store round in context manager ──────────────────────────
        self._context_mgr.add_round(
            user_content, response,
            bridge_text=sp.get_bridge_text(current_branch),
            selected_branch=selected_branch,
        )

        # ── Apply unconditional sets ────────────────────────────────
        step9_changes: list[dict] = []
        for set_op in parsed.sets:
            if not set_op.condition:
                result = self.game_state.apply_set(set_op, {})
                step9_changes.append({
                    "var": set_op.var,
                    "op": set_op.op,
                    "val": set_op.val,
                    "accepted": result.accepted,
                    "reason": result.reason,
                })
                if result.reason:
                    self._rejected_changes.append(result.reason)

        if step9_changes:
            yield {
                "type": "state",
                "vars": self.game_state.state_vars,
                "changes": step9_changes,
            }

        # Update stored state (bridge_text filtered by current_branch
        # per block-spec.md §4).
        self.last_parsed = parsed
        self._last_bridge_text = sp.get_bridge_text(current_branch)

        # ── Launch adventure log in background if ending ────────────
        # Per exec-flow.md §5.2: submit adventure log at bridge time
        # so the API call runs concurrently with bridge_text display.
        _adventure_thread: threading.Thread | None = None
        _adventure_result: dict = {}
        if self.ending_flag:
            def _fetch_adventure() -> None:
                try:
                    _adventure_result["text"] = self.run_adventure_log()
                except Exception:
                    _adventure_result["text"] = None
            _adventure_thread = threading.Thread(
                target=_fetch_adventure, daemon=True
            )
            _adventure_thread.start()

        # ── Yield options (segments were already streamed above) ────
        yield from self._emit_options(parsed)

        # ── Ending detection ────────────────────────────────────────
        if self.ending_flag:
            if _adventure_thread is not None:
                _adventure_thread.join(timeout=30)
            adventure_log = _adventure_result.get("text")

            yield {
                "type": "ending",
                "adventure_log": adventure_log,
                "final_state": self.game_state.state_vars,
                "summary": self.last_parsed.checkpoint_summary,
            }
            yield {
                "type": "done",
                "round": self._context_mgr.round_count,
                "node": "end",
                "state": self.game_state.state_vars,
            }

            self._notify(RoundRecord(
                round_number=self._context_mgr.round_count,
                messages_sent=messages,
                raw_response=response,
                parsed=parsed,
                ttft=ttft,
                tokens=tokens,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                node="end",
                selected_branch=selected_branch,
            ))
            return  # Game over

        # ── Notify observer ─────────────────────────────────────────
        self._notify(RoundRecord(
            round_number=self._context_mgr.round_count,
            messages_sent=messages,
            raw_response=response,
            parsed=parsed,
            ttft=ttft,
            tokens=tokens,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            node=self.current_node,
            selected_branch=selected_branch,
        ))

        yield {
            "type": "done",
            "round": done_round if done_round is not None else self._context_mgr.round_count,
            "node": done_node if done_node is not None else self.current_node,
            "state": done_state if done_state is not None else self.game_state.state_vars,
        }

    # ── Bridge Pre-fetch ──────────────────────────────────────────

    def _apply_deferred_step(
        self, choice_dict: dict[str, int]
    ) -> tuple[list[dict], bool]:
        """Apply deferred state changes and evaluate routes.

        Shared by ``_launch_prefetch`` and ``continue_round_stream``.
        Handles Steps 2-3.6: conditional sets (deferred from last
        round), route evaluation, checkpoint accumulation, and ending
        detection.

        Args:
            choice_dict: Player choice mapping (``{}`` for auto-advance).

        Returns:
            ``(step2_changes, ending_detected)`` where *step2_changes*
            is a list of ``{var, op, val, accepted, reason}`` dicts and
            *ending_detected* is ``True`` when the checkpoint node is
            ``"end"`` (caller should abort further processing).
        """
        # ── Step 2: apply last round's conditional sets ─────────────
        step2_changes: list[dict] = []
        new_rejected: list[str] = []
        for set_op in self.last_parsed.sets:
            if not set_op.condition:
                continue  # unconditional — already applied in its own round
            result = self.game_state.apply_set(set_op, choice_dict)
            step2_changes.append({
                "var": set_op.var,
                "op": set_op.op,
                "val": set_op.val,
                "accepted": result.accepted,
                "reason": result.reason,
            })
            if result.reason:
                new_rejected.append(result.reason)
        self._rejected_changes = new_rejected

        # ── Step 3: evaluate routes → advance node ──────────────────
        old_node = self.current_node
        route = self._evaluate_routes(choice_dict)
        if route:
            if old_node and old_node not in self._completed_nodes:
                self._completed_nodes.append(old_node)
            self.current_node = route
            self.goal = self._node_goals.get(route, self.goal or "")
        elif not self.last_parsed.routes:
            # No routes declared: advance via checkpoint_node if the
            # LLM set one, otherwise just mark the old node completed.
            if choice_dict:
                if old_node and old_node not in self._completed_nodes:
                    self._completed_nodes.append(old_node)
            else:
                cp = self.last_parsed.checkpoint_node
                if cp and cp != self.current_node:
                    if self.current_node and self.current_node not in self._completed_nodes:
                        self._completed_nodes.append(self.current_node)
                    self.current_node = cp
                    self.goal = self._node_goals.get(cp, self.goal or "")

        # ── Step 3.5: accumulate checkpoint data ────────────────────
        if self.last_parsed.checkpoint_node:
            cp_node = self.last_parsed.checkpoint_node
            cp_summary = self.last_parsed.checkpoint_summary or ""
            cp_valid = (cp_node == "end")
            if not cp_valid and self._outline_nodes:
                valid_ids = {n.get("id", "") for n in self._outline_nodes}
                cp_valid = cp_node in valid_ids
            elif not cp_valid and not self._outline_nodes:
                cp_valid = True
            if cp_valid:
                self._accumulate_checkpoint(cp_node, cp_summary)

        # ── Step 3.6: ending detection ──────────────────────────────
        ending_detected = False
        if self.last_parsed.checkpoint_node == "end":
            self.ending_flag = True
            if "end" not in self._completed_nodes:
                self._completed_nodes.append("end")
            ending_detected = True

        return step2_changes, ending_detected

    def _take_prefetch(self, choice_key: str | None) -> dict | None:
        """Atomically check and clear pre-fetched data for the given choice_key.

        Returns the pre-fetch dict if one is available AND its choice_key
        matches, otherwise returns None.  The pre-fetch is cleared on
        match so it is consumed at most once.
        """
        with self._prefetch_lock:
            data = self._prefetch_data
            if data is None:
                return None
            if data.get("choice_key") != choice_key:
                # Mismatch — e.g. a choice round arrived when we
                # pre-fetched for auto-advance.  Discard.
                self._prefetch_data = None
                return None
            self._prefetch_data = None
            return data

    def _launch_prefetch(self, choice_key: str | None) -> None:
        """Start background pre-fetch of the next round's API response.

        Called after the current round has been fully processed (parsed,
        state applied, last_parsed updated).  Only safe when the current
        round has *no* player choices — the next call to
        ``continue_round_stream()`` is guaranteed to be an auto-advance
        with the same ``choice_key``.

        Side effects:
        - Applies the *current* round's deferred sets (Step 2 for the
          next call) and evaluates routes (Step 3) — this mutates
          ``game_state``, ``current_node``, ``goal``, and
          ``completed_nodes``.
        - Builds the next round's messages array and starts a daemon
          thread that streams API chunks into a ``queue.Queue``.
        - Stores everything in ``_prefetch_data`` behind the lock.
        """
        if self.last_parsed is None:
            return

        # ── Steps 2-3.6: deferred sets, routes, checkpoint, ending ──
        step2_changes, ending_detected = self._apply_deferred_step({})
        if ending_detected:
            return  # do not pre-fetch past the ending

        # ── Step 4: build Round N context ──────────────────────────
        compressed_summaries = (
            self._context_mgr.get_compressed_summaries() or None
        )
        selected_branch = self._get_selected_branch(choice_key)
        if selected_branch is not None:
            self._current_branch = selected_branch

        # Derive bridge_text for the *next* round from the current
        # round's parsed output, filtered by the branch the player
        # chose (or "main" for auto-advance).
        bridge_text = self._context_mgr.get_last_bridge_text()

        rn_context = self._prompter.build_round_n(
            current_node=self.current_node or "",
            goal=self.goal or "",
            completed_nodes=self._completed_nodes,
            state_vars=self.game_state.state_vars,
            bridge_text=bridge_text,
            compressed_summaries=compressed_summaries,
            rejected_changes=(
                self._rejected_changes if self._rejected_changes else None
            ),
            format_error=self._format_error,
        )

        # ── Step 5: assemble messages ──────────────────────────────
        messages = self._context_mgr.get_messages()
        messages.append({"role": "user", "content": rn_context})

        # ── Step 6: fire API call in background ────────────────────
        result_queue: queue.Queue = queue.Queue()

        def _fetch() -> None:
            try:
                for chunk in self.api_client.stream_chat_iter(messages):
                    result_queue.put(chunk)
            except Exception as exc:
                result_queue.put({"__prefetch_error__": str(exc)})

        thread = threading.Thread(target=_fetch, daemon=True)
        thread.start()

        with self._prefetch_lock:
            self._prefetch_data = {
                "choice_key": choice_key,
                "queue": result_queue,
                "thread": thread,
                "messages": messages,
                "user_content": rn_context,
                "state_events": [
                    {
                        "type": "state",
                        "vars": self.game_state.state_vars,
                        "changes": step2_changes,
                    }
                ] if step2_changes else [],
                "selected_branch": selected_branch,
            }

    # ── Save / Restore ─────────────────────────────────────────────

    def to_save_dict(self) -> dict:
        """Produce complete save dict per data-model.md §3.1 format."""
        # Convert outline nodes to save format
        outline_for_save = []
        for node in self._outline_nodes:
            nid = node.get("id", "")
            status = "active" if nid == self.current_node else (
                "completed" if nid in self._completed_nodes else "pending"
            )
            outline_for_save.append({
                "node_id": nid,
                "title": node.get("title", ""),
                "goal": node.get("goal", ""),
                "status": status,
                "branches": [
                    {"condition": r.get("condition"), "target": r.get("target", "")}
                    for r in node.get("routes", [])
                ],
            })

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        label = self.story_config.get("label", "untitled")

        # Preserve original created_at; set on first save only.
        if self._created_at is None:
            self._created_at = now

        return {
            "version": SAVE_VERSION,
            "metadata": {
                "label": label,
                "created_at": self._created_at,
                "updated_at": now,
                "round_count": self._context_mgr.round_count,
            },
            "config": {
                "temperature": getattr(self, "_temperature", None),
            },
            "story_config": copy.deepcopy(self.story_config),
            "state_vars": self.game_state.state_vars,
            "outline": outline_for_save,
            "progress": {
                "current_node": self.current_node or "",
                "round_count": self._context_mgr.round_count,
                "checkpoint_history": list(self._checkpoint_history),
                "checkpoint_summaries": list(self._checkpoint_summaries),
                "checkpoint_snapshots": copy.deepcopy(self._checkpoint_snapshots),
            },
            "bridge_text": self._last_bridge_text,
        }

    @classmethod
    def from_save_dict(
        cls,
        data: dict,
        api_client: "ApiClient",
    ) -> "GameLoop":
        """Restore GameLoop from save data."""
        story_config = data["story_config"]
        state_vars_data = {"state_vars": data["state_vars"]}

        # Reconstruct outline text from nodes
        outline_nodes = data["outline"]
        outline_lines = []
        for node in outline_nodes:
            nid = node.get("node_id", node.get("id", ""))
            status = node.get("status", "pending")
            title = node.get("title", "")
            goal = node.get("goal", "")
            outline_lines.append(f"{nid} [{status}] — {title}：{goal}")
        outline_text = "\n".join(outline_lines)

        # Restore GameState
        game_state = GameState.from_dict(state_vars_data, story_config)

        progress = data["progress"]
        current_node = progress.get("current_node", "")

        # Parse goal from outline
        goal = ""
        for node in outline_nodes:
            nid = node.get("node_id", node.get("id", ""))
            if nid == current_node:
                goal = node.get("goal", "")
                break

        gl = cls(
            story_config=story_config,
            outline_text=outline_text,
            api_client=api_client,
            game_state=game_state,
            current_node=current_node or None,
            goal=goal or None,
            outline_nodes=outline_nodes,
        )

        # Restore bridge text
        gl._last_bridge_text = data.get("bridge_text", "")

        # Restore checkpoint accumulations
        gl._checkpoint_summaries = list(progress.get("checkpoint_summaries", []))
        gl._checkpoint_history = list(progress.get("checkpoint_history", []))
        gl._checkpoint_snapshots = dict(progress.get("checkpoint_snapshots", {}))

        # Restore completed nodes from outline status
        for node in outline_nodes:
            nid = node.get("node_id", node.get("id", ""))
            if node.get("status") == "completed" and nid not in gl._completed_nodes:
                gl._completed_nodes.append(nid)

        # Restore temperature
        config = data.get("config", {})
        if "temperature" in config:
            gl._temperature = config["temperature"]

        # Restore created_at (preserve original creation timestamp)
        metadata = data.get("metadata", {})
        if metadata.get("created_at"):
            gl._created_at = metadata["created_at"]

        return gl

    def set_save_manager(self, save_manager) -> None:
        """Configure auto-save on checkpoint."""
        self._save_manager = save_manager

    # ── Observer ──────────────────────────────────────────────────

    def _notify(self, record: RoundRecord) -> None:
        """Notify all observers of a completed round.

        Observer failures are silently ignored — they must not break
        the game loop.
        """
        for obs in self._observers:
            try:
                obs(record)
            except Exception:
                pass

    def _get_selected_branch(self, choice_key: str | None) -> str | None:
        """Determine the branch name from a player's choice key.

        Maps choice_key (1-indexed string) to the branch name from
        the last parsed output's choice options.
        """
        if choice_key is None or self.last_parsed is None:
            return None
        if not self.last_parsed.choices:
            return None
        try:
            idx = int(choice_key) - 1
        except ValueError:
            return None
        last_choice = self.last_parsed.choices[-1]
        branches = last_choice.get("branches", [])
        if 0 <= idx < len(branches):
            return branches[idx]
        return None

    # ── Options ───────────────────────────────────────────────────

    def get_available_options(self) -> list[dict]:
        """Return available options from last parsed output.

        Returns:
            List of option dicts with 'branch' key.
            Empty list if no choice was presented.
        """
        if not self.last_parsed or not self.last_parsed.choice_id:
            return []
        return [
            {"branch": branch, "index": i + 1}
            for i, branch in enumerate(self.last_parsed.opt_branches)
        ]

    # ── Outline ───────────────────────────────────────────────────

    @staticmethod
    def _normalize_outline_nodes(nodes: list[dict]) -> list[dict]:
        """Normalize outline nodes to a single consistent internal format.

        The internal ``_outline_nodes`` can arrive in two shapes depending
        on creation path:

        * **Fresh** (``CoCreateParser.parse_outline``):
          ``{id, title, goal, routes: [{condition, target}]}``
        * **Loaded** (``from_save_dict`` → save-file ``outline``):
          ``{node_id, title, goal, status, branches: [str|dict]}``
          (old saves: list of target strings; new saves: list of
          ``{condition, target}`` dicts).

        This method normalises both into the fresh format so that every
        downstream access site (checkpoint validation, ``to_save_dict``,
        ``_next_outline_node``, ``_accumulate_checkpoint``) works with a
        single key layout.

        Returns a **new** list — does not mutate the input.
        """
        normalized = []
        for node in nodes:
            nid = node.get("id") or node.get("node_id", "")
            routes = node.get("routes")
            if routes is None:
                # Loaded format: branches is a list of target strings
                # (old saves) or {condition, target} dicts (new saves).
                branches = node.get("branches", [])
                routes = []
                for b in branches:
                    if isinstance(b, dict):
                        routes.append({
                            "condition": b.get("condition"),
                            "target": b.get("target", ""),
                        })
                    elif b:
                        routes.append({"condition": None, "target": b})
            normalized.append({
                "id": nid,
                "title": node.get("title", ""),
                "goal": node.get("goal", ""),
                "routes": routes,
            })
        return normalized

    @staticmethod
    def _parse_outline_goals(outline_text: str) -> dict[str, str]:
        """Extract {node_id: goal_description} from outline text."""
        goals: dict[str, str] = {}
        for line in outline_text.strip().split("\n"):
            stripped = line.strip()
            if not stripped or stripped[0] in ("├", "└", "→"):
                continue
            # Format: ch1_bar [active] — title：goal
            node_id = stripped.split()[0] if stripped else ""
            if not node_id:
                continue
            for sep in ("：", "—"):
                if sep in stripped:
                    goal_text = stripped.split(sep, 1)[1].strip()
                    # Remove status markers and route hints
                    goal_text = goal_text.split("（")[0].strip()
                    goal_text = goal_text.replace("[active]", "").replace("[pending]", "").replace("[completed]", "").strip()
                    if goal_text:
                        goals[node_id] = goal_text
                    break
        return goals

    # ── Routes ────────────────────────────────────────────────────

    def evaluate_routes(self, choice_dict: dict[str, int]) -> str | None:
        """Evaluate route conditions from last parsed output.

        Public convenience wrapper around _evaluate_routes.

        Args:
            choice_dict: Player choice mapping.

        Returns:
            Target node ID if a route matches, None otherwise.
        """
        return self._evaluate_routes(choice_dict)

    def _evaluate_routes(self, choice_dict: dict[str, int]) -> str | None:
        """Evaluate route conditions from last parsed output.

        Per data-model.md §2 step 4:
        - First matching condition wins.
        - All conditions fail → fall back to first route's target.
        - No routes → advance to next node in outline sequence.
        """
        if not self.last_parsed:
            return None

        routes = self.last_parsed.routes
        for route in routes:
            if route.condition is None:
                return route.target
            if self.game_state.evaluate_condition(
                route.condition, choice_dict
            ):
                return route.target

        # Fallback 1: conditions exist but none matched → first route.
        if routes:
            return routes[0].target

        # Fallback 2: no routes → next node in outline sequence.
        return self._next_outline_node()

    def _next_outline_node(self) -> str | None:
        """Return the next node in outline sequence after current_node.

        Returns None if current_node is the last node or not found.
        """
        if not self._outline_nodes or not self.current_node:
            return None
        for i, node in enumerate(self._outline_nodes):
            nid = node.get("id", "")
            if nid == self.current_node and i + 1 < len(self._outline_nodes):
                return self._outline_nodes[i + 1].get("id")
        return None

    def _accumulate_checkpoint(self, cp_node: str, cp_summary: str) -> None:
        """Accumulate checkpoint data and trigger auto-save.

        Centralised helper shared by the deferred checkpoint path
        (Step 3.5 in ``continue_round_stream`` / ``_launch_prefetch``)
        and the immediate post-parse path for the ``"end"`` sentinel.

        Side effects on: ``_checkpoint_summaries``,
        ``_checkpoint_history``, ``_checkpoint_snapshots``,
        ``_save_manager``.
        """
        if cp_summary:
            self._checkpoint_summaries.append(cp_summary)

        cp_title = cp_node
        if self._outline_nodes:
            if cp_node == "end":
                last = self._outline_nodes[-1]
                cp_title = last.get("title", "ending") or "ending"
            else:
                for node in self._outline_nodes:
                    if node.get("id") == cp_node:
                        cp_title = node.get("title", cp_node)
                        break

        self._checkpoint_history.append({
            "node": cp_node,
            "title": cp_title,
            "summary": cp_summary,
            "round": self._context_mgr.round_count,
        })

        self._checkpoint_snapshots[cp_node] = copy.deepcopy(
            self.game_state.state_vars
        )

        if self._save_manager is not None:
            try:
                self._save_manager.save(self.to_save_dict())
            except Exception:
                pass

    # ── Adventure Log ─────────────────────────────────────────────

    def run_adventure_log(self) -> str:
        """Generate adventure log / ending summary.

        Uses non-streaming chat with structured prompt per prompt-design.md §5.2.

        Returns:
            Adventure log markdown text.
        """
        prompt = PromptBuilder.build_adventure_log_prompt(
            story_config=self.story_config,
            state_vars=self.game_state.state_vars,
            checkpoint_summaries=self._checkpoint_summaries,
            checkpoint_history=self._checkpoint_history,
        )
        # Per exec-flow.md §5.4: independent LLM call — not part of the
        # narrative loop.  Send only the adventure-log prompt, not the
        # full conversation context (~50K tokens).
        return self.api_client.chat([{"role": "user", "content": prompt}])
