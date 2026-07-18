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
    RouteTarget,
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
        4. Evaluate condition if present.
        5. Apply the change.

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

        # Step 3: Parse/try value
        if var_type == "number":
            try:
                val = int(set_op.val)
            except ValueError:
                return SetResult(
                    accepted=False,
                    reason=f"Cannot parse '{set_op.val}' as integer for {var_name}",
                )
        else:
            val = set_op.val

        # Step 4: Evaluate condition (per block-spec.md §5: condition
        # not met → skip without rejection).
        if set_op.condition:
            if not self.evaluate_condition(set_op.condition, choice_dict):
                return SetResult(
                    accepted=True,
                    reason="skipped: condition not met",
                )

        # Step 5: Apply
        if var_type == "number":
            return self._apply_number_op(var_name, set_op.op, val)
        elif var_type == "string":
            return self._apply_string_op(var_name, val)

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

    Unified per-round flow (all rounds identical per exec-flow.md §4.1)::

        gl.start_game()              # Round 1: build prompt + launch API
        gen = gl.stream_round()      # Round 1 generator
        for event in gen:            # Phase 1-4: streaming parse
            if event["type"] == "options":
                gen.send(key)         # choice pause → resume
        # Phase 5: </story> → store, launch next API, yield done
        gen = gl.stream_round()      # Round 2 (API already running)
        ...
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
        self._game_started: bool = False
        self._current_branch: str = "main"  # active branch from player's last choice

        # Checkpoint and save accumulators
        self._temperature = getattr(api_client, "temperature", None)
        self._checkpoint_summaries: list[str] = []
        self._checkpoint_history: list[dict] = []
        self._checkpoint_snapshots: dict[str, dict] = {}
        self.ending_flag: bool = False
        self._save_manager = None
        self._created_at: str | None = None

        # Adventure log — launched in a daemon thread during Phase 5 of the
        # final round (same pattern as _launch_api for regular pre-fetch).
        # The UI calls get_adventure_log() to retrieve the result.
        self._adv_thread: threading.Thread | None = None
        self._adv_result: str | None = None
        self._adv_error: str | None = None
        self._adv_retry_prompt: str | None = None

        # Pending API state — every round's Phase 5 launches the *next*
        # round's API call in a daemon thread and stores the result queue
        # here.  stream_round() drains this queue.  All rounds are
        # identical — Round 1 is no exception (its Phase 5 also launches
        # the Round 2 API call).
        self._pending_queue: queue.Queue | None = None
        self._pending_user_content: str = ""
        self._pending_messages: list[dict] = []

        # Retry state — when stream_round() encounters a severe error
        # (API timeout / network failure), it stores the original messages
        # here so the UI can call retry() after user confirmation.
        # Cleared on successful round completion.
        self._retry_messages: list[dict] | None = None
        self._retry_user_content: str = ""

    # ── Properties ─────────────────────────────────────────────────

    @property
    def round_count(self) -> int:
        """Current round number (0 before first ``stream_round()``)."""
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

    # ── Game Start ──────────────────────────────────────────────────
    # Called once by the UI after construction.  Builds the Round 1
    # prompt and launches the background API call so that the very first
    # stream_round() can consume it just like any other round.

    def start_game(self) -> None:
        """Build Round 1 prompt and launch the background API call.

        Must be called once before the first ``stream_round()``.
        Each ``GameLoop`` instance supports exactly one game session.

        Raises:
            RuntimeError: If already started.
        """
        if self._game_started:
            raise RuntimeError("Round 1 already started")
        self._game_started = True

        r1_prompt = self._prompter.build_round1(
            story_config=self.story_config,
            outline_text=self.outline_text,
            current_node=self.current_node or "",
            goal=self.goal or "",
            state_vars=self.game_state.state_vars,
        )

        # If resuming from a save, append bridge_text per
        # data-model.md §3.5.
        if self._last_bridge_text:
            r1_prompt += (
                "\n\n---\n"
                "Continue from here:\n"
                + self._last_bridge_text
            )

        messages = [{"role": "user", "content": r1_prompt}]
        self._launch_api(messages, r1_prompt)

    # ── stream_round (unified) ─────────────────────────────────────

    def stream_round(self) -> Iterator[dict]:
        """Unified per-round generator.  All rounds (1…N) use the same flow.

        Per exec-flow.md §4.1, every round follows the identical 6-phase
        pipeline.  Phase 5 of round *k* launches the background API call
        for round *k+1*; ``stream_round()`` for round *k+1* drains the
        queue that was stored then.

        **Choice pause** — when the parser encounters ``</choice>`` the
        generator yields an ``options`` event and suspends.  The UI must
        call ``gen.send(key)`` with the player's selected key (1-indexed
        string).  The generator resumes with ``current_branch`` and
        ``choice_dict`` populated.

        Yields:
            ``{"type": "story_begin"}``
            ``{"type": "story_end"}``
            ``{"type": "token", "text": str}``
            ``{"type": "segment", "text": str, ...}``
            ``{"type": "bridge"}``
            ``{"type": "options", "choices": [dict]}``
            ``{"type": "state", "vars": dict, "changes": [dict]}``
            ``{"type": "error", "message": str}``
            ``{"type": "ending", ...}``
            ``{"type": "done", "node": str, "state": dict}``
        """
        # ── Guard: ending already triggered ─────────────────────────
        if self.ending_flag:
            yield {
                "type": "done",
                "node": "end",
                "state": self.game_state.state_vars,
            }
            return

        # ── Guard: API must be launched ─────────────────────────────
        if self._pending_queue is None:
            raise RuntimeError(
                "start_game() must be called before stream_round()"
            )

        # ── Consume pending API state (stored by last round's Phase 5
        #    or by start_game()) ──────────────────────────────────────
        result_queue = self._pending_queue
        user_content = self._pending_user_content
        messages_sent = self._pending_messages
        self._pending_queue = None
        self._pending_user_content = ""
        self._pending_messages = []

        # ── Per-round state (fresh each round per block-spec.md §3) ─
        current_branch = "main"
        choice_dict: dict[str, int] = {}
        new_rejected: list[str] = []
        pending_cp: dict[str, str | None] = {"node": None, "summary": None}
        self._format_error = None  # reset each round — errors are fed back
        # via build_round_n() in Phase 5; must not persist into later rounds.

        # ── Phase 1-4: Streaming parse ──────────────────────────────
        # Per exec-flow.md §4.4: token chunks → LineBuffer complete
        # lines → StreamingXmlParser events.  SET and CHECKPOINT are
        # handled *immediately* at parse time — no deferral.
        lb = LineBuffer()
        sp = StreamingXmlParser()
        collected: list[str] = []
        ttft: float | None = None
        tokens: dict | None = None

        while True:
            try:
                chunk = result_queue.get(timeout=STREAM_STALL_TIMEOUT_SEC)
            except queue.Empty:
                # ── Severe error: save messages for retry ─────────
                self._retry_messages = messages_sent
                self._retry_user_content = user_content
                yield {
                    "type": "error",
                    "message": (
                        f"API timeout after {STREAM_STALL_TIMEOUT_SEC}s"
                    ),
                }
                return

            if chunk.get("__api_error__"):
                # ── Severe error: save messages for retry ─────────
                self._retry_messages = messages_sent
                self._retry_user_content = user_content
                yield {
                    "type": "error",
                    "message": f"API error: {chunk['__api_error__']}",
                }
                return

            if chunk.get("done"):
                tokens = chunk.get("usage")
                break  # end of API stream → Phase 5

            if chunk.get("ttft") is not None:
                ttft = chunk["ttft"]

            delta = chunk["delta"]
            collected.append(delta)
            yield {"type": "token", "text": delta}

            for line in lb.feed(delta):
                for event in sp.feed_line(line):
                    etype = event.type

                    if etype == EventType.STORY_BEGIN:
                        yield {"type": "story_begin"}

                    elif etype == EventType.STORY_END:
                        yield {"type": "story_end"}

                    elif etype == EventType.BRIDGE:
                        yield {"type": "bridge"}

                    elif etype == EventType.SEGMENT:
                        # Branch filter: bare segs always pass;
                        # named-branch segs pass only when they
                        # match current_branch (both pre- and
                        # post-bridge per block-spec.md §3).
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

                    elif etype == EventType.SET:
                        change = self._handle_set_event(
                            event, self.game_state, choice_dict,
                            new_rejected,
                        )
                        if change is not None:
                            yield {
                                "type": "state",
                                "vars": self.game_state.state_vars,
                                "changes": [change],
                            }

                    elif etype == EventType.CHOICE_END:
                        if event.choice_data:
                            # ── Evaluate option conditions (engine
                            #    responsibility per exec-flow.md §4.6).
                            #    Uses the same evaluator as <set> and
                            #    <route>.  choice_dict is {} because no
                            #    choice has been made yet this round.
                            cd = event.choice_data
                            branches = cd.get("branches", [])
                            conditions = cd.get("conditions", {})
                            enabled = [
                                self.game_state.evaluate_condition(
                                    conditions.get(b), {}
                                )
                                for b in branches
                            ]
                            # Fallback: all disabled → all enabled
                            # (prevents game lockup).
                            if enabled and not any(enabled):
                                enabled = [True] * len(enabled)
                            cd["enabled"] = enabled

                            # ── Pause: yield options, await UI input ─
                            key = yield {
                                "type": "options",
                                "choices": [cd],
                            }
                            # ── Resume: apply player's choice ───────
                            if key is not None:
                                try:
                                    idx = int(key) - 1
                                except (ValueError, TypeError):
                                    continue
                                branches = event.choice_data.get(
                                    "branches", []
                                )
                                cid = event.choice_data.get("id", "")
                                if 0 <= idx < len(branches):
                                    branch = branches[idx]
                                    if branch:
                                        current_branch = branch
                                    choice_dict[cid] = int(key)

                    elif etype == EventType.CHECKPOINT:
                        pending_cp["node"] = event.cp_node
                        pending_cp["summary"] = event.cp_summary
                        # Self-closing <checkpoint/>: _in_checkpoint
                        # stays False → process immediately.
                        if not sp._in_checkpoint:
                            self._handle_checkpoint(
                                sp.routes,
                                pending_cp["node"] or "",
                                pending_cp["summary"] or "",
                                choice_dict,
                            )
                            pending_cp["node"] = None

                    elif etype == EventType.CHECKPOINT_END:
                        if pending_cp["node"]:
                            self._handle_checkpoint(
                                sp.routes,
                                pending_cp["node"],
                                pending_cp["summary"] or "",
                                choice_dict,
                            )
                            pending_cp["node"] = None

        # ── Flush any remaining partial line ────────────────────────
        # Feed through the parser so its internal accumulators
        # (_segments, _bridge_text_items) are complete for
        # get_result() in Phase 5.  Don't yield UI events — the
        # stream has ended and a partial line is almost certainly
        # truncated garbage.
        remaining = lb.flush()
        if remaining:
            sp.feed_line(remaining)

        # ═══════════════════════════════════════════════════════════
        # Phase 5: </story> — pack, store, next-round launch
        # ═══════════════════════════════════════════════════════════

        response = "".join(collected)
        parsed = sp.get_result()

        # ── Format errors ───────────────────────────────────────────
        # Merge errors from two independent sources:
        #   1. sp.format_errors — post-bridge violations detected by
        #      the streaming parser.
        #   2. self._format_error — errors set during Phase 3 by
        #      _handle_checkpoint (e.g. unknown node ID).
        # Both must be fed back to the LLM in the next round's prompt.
        format_errors: list[str] = list(sp.format_errors)
        if self._format_error:
            format_errors.append(self._format_error)
        self._format_error = (
            "; ".join(format_errors) if format_errors else None
        )

        # ── Persist per-round state ─────────────────────────────────
        self._current_branch = current_branch
        self._rejected_changes = new_rejected

        # ── Store round in context manager ──────────────────────────
        is_first_round = self._context_mgr.round_count == 0
        if is_first_round:
            self._context_mgr.set_round1(
                user_content, response,
                bridge_text=sp.get_bridge_text(current_branch),
            )
        else:
            self._context_mgr.add_round(
                user_content,
                response,
                bridge_text=sp.get_bridge_text(current_branch),
                selected_branch=(
                    current_branch if current_branch != "main" else None
                ),
            )

        self.last_parsed = parsed
        self._last_bridge_text = sp.get_bridge_text(current_branch)

        # ── Ending: launch adventure log (concurrent per §5.2) ──────
        # Same pattern as bridge pre-fetch: launch daemon thread, yield
        # immediately, let the UI retrieve the result at its own pace.
        if self.ending_flag:
            def _fetch_adv() -> None:
                try:
                    self._adv_result = self.run_adventure_log()
                except Exception as exc:
                    self._adv_error = str(exc)

            self._adv_thread = threading.Thread(target=_fetch_adv, daemon=True)
            self._adv_thread.start()

            # ── Ending reached — clear retry state ────────────────
            self._retry_messages = None
            self._retry_user_content = ""

            yield {
                "type": "ending",
                "adventure_log": None,  # UI calls get_adventure_log() to retrieve
                "final_state": self.game_state.state_vars,
                "summary": parsed.checkpoint_summary,
            }

            self._notify(RoundRecord(
                round_number=self._context_mgr.round_count,
                messages_sent=messages_sent,
                raw_response=response,
                parsed=parsed,
                ttft=ttft,
                tokens=tokens,
                timestamp=time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                ),
                node="end",
                selected_branch=(
                    current_branch if current_branch != "main" else None
                ),
            ))

            yield {
                "type": "done",
                "node": "end",
                "state": self.game_state.state_vars,
            }
            return

        # ── Build next-round prompt → launch background API ─────────
        # Per exec-flow.md §4.7: assemble prompt at </story> so the
        # next round's TTFT overlaps with UI displaying bridge_text.
        compressed_summaries = (
            self._context_mgr.get_compressed_summaries() or None
        )
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

        messages = self._context_mgr.get_messages()
        messages.append({"role": "user", "content": rn_context})

        self._launch_api(messages, rn_context)

        # ── Round succeeded — clear retry state ────────────────────
        self._retry_messages = None
        self._retry_user_content = ""

        # ── Notify observer ─────────────────────────────────────────
        self._notify(RoundRecord(
            round_number=self._context_mgr.round_count,
            messages_sent=messages_sent,
            raw_response=response,
            parsed=parsed,
            ttft=ttft,
            tokens=tokens,
            timestamp=time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            ),
            node=self.current_node,
            selected_branch=(
                current_branch if current_branch != "main" else None
            ),
        ))

        yield {
            "type": "done",
            "node": self.current_node,
            "state": self.game_state.state_vars,
        }

    # ── Background API ──────────────────────────────────────────────

    def _launch_api(self, messages: list[dict], user_content: str) -> None:
        """Start a background API call and store the result queue.

        Called by ``start_game()`` (Round 1) and by ``stream_round()``
        Phase 5 (every round).  The daemon thread streams API chunks
        into ``queue.Queue``; the next ``stream_round()`` call drains
        it.

        Args:
            messages: Full messages array to send.
            user_content: The user message content (stored for
                          ``add_round`` in the next round).
        """
        result_queue: queue.Queue = queue.Queue()

        def _fetch() -> None:
            try:
                for chunk in self.api_client.stream_chat_iter(messages):
                    result_queue.put(chunk)
            except Exception as exc:
                result_queue.put({"__api_error__": str(exc)})

        thread = threading.Thread(target=_fetch, daemon=True)
        thread.start()

        self._pending_queue = result_queue
        self._pending_user_content = user_content
        self._pending_messages = list(messages)

    def retry(self) -> None:
        """Re-launch the last failed round with the same messages.

        Call after receiving an ``{"type": "error", ...}`` event and
        the user has chosen to retry.  Must be followed by another
        ``stream_round()`` call to consume the new result queue.

        Raises:
            RuntimeError: If there is no failed round to retry
                          (i.e. the last round completed successfully).
        """
        if self._retry_messages is None:
            raise RuntimeError(
                "No failed round to retry — the last round completed "
                "successfully or retry() was already called."
            )
        self._launch_api(self._retry_messages, self._retry_user_content)

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
            },
            "config": {
                "temperature": getattr(self, "_temperature", None),
            },
            "story_config": copy.deepcopy(self.story_config),
            "state_vars": self.game_state.state_vars,
            "outline": outline_for_save,
            "progress": {
                "current_node": self.current_node or "",
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

        # Reconstruct outline text from nodes, including branch
        # connection lines (├→ / └→) that the original
        # CoCreateParser.format_outline() produces.
        outline_nodes = data["outline"]
        outline_lines = []
        # Build status lookup for branch targets
        node_status: dict[str, str] = {}
        for node in outline_nodes:
            nid = node.get("node_id", node.get("id", ""))
            node_status[nid] = node.get("status", "pending")

        for node in outline_nodes:
            nid = node.get("node_id", node.get("id", ""))
            status = node.get("status", "pending")
            title = node.get("title", "")
            goal = node.get("goal", "")
            outline_lines.append(f"{nid} [{status}] — {title}：{goal}")

            # Branch connection lines
            branches = node.get("branches", [])
            if branches:
                for j, branch in enumerate(branches):
                    is_last = (j == len(branches) - 1)
                    prefix = "  └→" if is_last else "  ├→"
                    if isinstance(branch, dict):
                        target = branch.get("target", "")
                    else:
                        target = branch  # old format: plain target string
                    target_status = node_status.get(target, "pending")
                    outline_lines.append(
                        f"{prefix} {target} [{target_status}]"
                    )
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
            for sep in ("—", "："):
                if sep in stripped:
                    goal_text = stripped.split(sep, 1)[1].strip()
                    # Remove status markers and route hints
                    goal_text = goal_text.split("（")[0].strip()
                    goal_text = goal_text.replace("[active]", "").replace("[pending]", "").replace("[completed]", "").strip()
                    if goal_text:
                        goals[node_id] = goal_text
                    break
        return goals

    # ── In-Round Handlers (stream_round helpers) ───────────────────

    @staticmethod
    def _handle_set_event(
        event: "ParseEvent",
        game_state: GameState,
        choice_dict: dict[str, int],
        rejected: list[str],
    ) -> dict | None:
        """Apply a SET event immediately during streaming parse.

        Constructs a ``SetOperation`` from the event fields, delegates to
        ``game_state.apply_set()`` for validation / condition evaluation /
        application, and records any rejection reason.

        Returns a state-change dict suitable for yielding as a
        ``{"type": "state", ...}`` event, or ``None`` if the set was
        skipped (condition not met).
        """
        set_op = SetOperation(
            var=event.set_var or "",
            op=event.set_op or "",
            val=event.set_val or "",
            condition=event.set_if,
        )
        result = game_state.apply_set(set_op, choice_dict)

        # Condition not met → skip silently, no event.
        if result.reason and result.reason.startswith("skipped:"):
            return None

        change = {
            "var": set_op.var,
            "op": set_op.op,
            "val": set_op.val,
            "accepted": result.accepted,
            "reason": result.reason,
        }
        # Report genuine rejections and silent corrections (clamp, etc.)
        # to the LLM in the next round, but NOT skipped conditions.
        if result.reason:
            rejected.append(result.reason)
        return change

    def _handle_checkpoint(
        self,
        routes: list,
        cp_node: str,
        cp_summary: str,
        choice_dict: dict[str, int],
    ) -> None:
        """Process a checkpoint during streaming parse (Phase 3).

        Called at ``</checkpoint>`` (or self-closing ``<checkpoint/>``).
        Performs: ending detection (empty routes), route evaluation,
        node advancement, checkpoint accumulation, and auto-save.

        Args:
            routes: Route list accumulated by the parser for this
                    checkpoint (empty list = ending node).
            cp_node: Node ID from the ``<checkpoint>`` element.
            cp_summary: Summary text from the element.
            choice_dict: Per-round player choice mapping.
        """
        # Validate node exists in outline
        if self._outline_nodes:
            valid_ids = {n.get("id", "") for n in self._outline_nodes}
            if cp_node not in valid_ids:
                if self._format_error:
                    self._format_error += "; "
                else:
                    self._format_error = ""
                self._format_error += f"Unknown checkpoint node: {cp_node}"
                return

        # ── Ending detection ─────────────────────────────────────
        # Consult the outline definition for this node.  An outline
        # node with empty routes IS the ending; a node with routes
        # is non-ending even if the LLM omitted <route> children
        # (self-closing checkpoint on a single-path node).
        outline_routes: list | None = None
        for n in self._outline_nodes:
            if n.get("id") == cp_node:
                outline_routes = n.get("routes", [])
                break

        is_ending = (
            outline_routes is not None and not outline_routes
        ) if self._outline_nodes else not routes

        if is_ending:
            self.ending_flag = True

        # ── Mark old node completed ──────────────────────────────
        old_node = self.current_node
        if old_node and old_node not in self._completed_nodes:
            self._completed_nodes.append(old_node)

        # ── Advance to target node ───────────────────────────────
        if self.ending_flag:
            if cp_node not in self._completed_nodes:
                self._completed_nodes.append(cp_node)
            self.current_node = cp_node
        elif routes:
            # LLM output contains <route> children — evaluate.
            target = self._evaluate_routes(choice_dict, routes=routes)
            if target:
                if cp_node not in self._completed_nodes:
                    self._completed_nodes.append(cp_node)
                self.current_node = target
                self.goal = self._node_goals.get(target, self.goal or "")
        elif outline_routes:
            # LLM output has no <route> children (self-closing
            # checkpoint), but the outline defines routes for this
            # node — single-path advancement.  Convert outline
            # dict routes to RouteTarget for _evaluate_routes.
            if cp_node not in self._completed_nodes:
                self._completed_nodes.append(cp_node)
            rt_routes = [
                RouteTarget(condition=r.get("condition"), target=r.get("target", ""))
                for r in outline_routes
            ]
            target = self._evaluate_routes(choice_dict, routes=rt_routes)
            if target:
                self.current_node = target
                self.goal = self._node_goals.get(target, self.goal or "")
        else:
            # No outline loaded — fall back to sequential advance.
            if cp_node not in self._completed_nodes:
                self._completed_nodes.append(cp_node)
            target = self._next_outline_node()
            if target:
                self.current_node = target
                self.goal = self._node_goals.get(target, self.goal or "")

        # ── Accumulate checkpoint data + auto-save ───────────────
        self._accumulate_checkpoint(cp_node, cp_summary)

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

    def _evaluate_routes(
        self,
        choice_dict: dict[str, int],
        routes: list | None = None,
    ) -> str | None:
        """Evaluate route conditions.

        Per data-model.md §2 step 4:
        - First matching condition wins.
        - All conditions fail → fall back to first route's target.
        - No routes → advance to next node in outline sequence.

        Args:
            choice_dict: Player choice mapping.
            routes: Route list to evaluate.  When ``None``, reads from
                    ``self.last_parsed.routes`` (legacy path).
        """
        if routes is None:
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

        Called by ``_handle_checkpoint`` during streaming parse
        (Phase 3) for every checkpoint — ending or non-ending.

        Side effects on: ``_checkpoint_summaries``,
        ``_checkpoint_history``, ``_checkpoint_snapshots``,
        ``_save_manager``.
        """
        if cp_summary:
            self._checkpoint_summaries.append(cp_summary)

        cp_title = cp_node
        if self._outline_nodes:
            for node in self._outline_nodes:
                if node.get("id") == cp_node:
                    cp_title = node.get("title", cp_node)
                    break

        self._checkpoint_history.append({
            "node": cp_node,
            "title": cp_title,
            "summary": cp_summary,
        })

        self._checkpoint_snapshots[cp_node] = copy.deepcopy(
            self.game_state.state_vars
        )

        if self._save_manager is not None:
            try:
                self._save_manager.save(self.to_save_dict(), cp_title)
            except Exception:
                pass

    # ── Adventure Log ─────────────────────────────────────────────

    def run_adventure_log(self) -> str:
        """Generate adventure log / ending summary.

        Uses non-streaming chat with structured prompt per prompt-design.md §5.2.

        Saves the prompt to ``_adv_retry_prompt`` and clears ``_adv_error``
        so ``retry_adventure_log()`` can re-launch with the same prompt
        after a failure.

        Returns:
            Adventure log markdown text.
        """
        prompt = PromptBuilder.build_adventure_log_prompt(
            story_config=self.story_config,
            state_vars=self.game_state.state_vars,
            checkpoint_summaries=self._checkpoint_summaries,
            checkpoint_history=self._checkpoint_history,
        )
        self._adv_retry_prompt = prompt
        self._adv_error = None
        # Per exec-flow.md §5.4: independent LLM call — not part of the
        # narrative loop.  Send only the adventure-log prompt, not the
        # full conversation context (~50K tokens).
        return self.api_client.chat([{"role": "user", "content": prompt}])

    def get_adventure_log(self, timeout: float = 30.0) -> str | None:
        """Wait for the background adventure log thread and return the text.

        Called by the UI after receiving the ``ending`` event.
        The adventure log is fetched in a daemon thread (same pattern as
        bridge pre-fetch) so the generator is never blocked.

        Args:
            timeout: Maximum seconds to wait for the API response.

        Returns:
            Adventure log markdown text, or ``None`` on timeout / error.
        """
        if self._adv_thread is None:
            return None
        self._adv_thread.join(timeout=timeout)
        return self._adv_result

    def retry_adventure_log(self) -> None:
        """Re-launch the adventure log daemon thread with the same prompt.

        Call after ``adventure_log_error`` is set and the user has
        chosen to retry.  Must be followed by another
        ``get_adventure_log()`` call to retrieve the new result.

        Raises:
            RuntimeError: If there is no prompt to retry with (i.e.
                          ``run_adventure_log()`` was never called, or
                          the last call succeeded without saving a prompt).
        """
        if self._adv_retry_prompt is None:
            raise RuntimeError(
                "No failed adventure log to retry — run_adventure_log() "
                "was never called or succeeded without error."
            )
        self._adv_error = None
        self._adv_result = None

        def _fetch() -> None:
            try:
                self._adv_result = self.api_client.chat(
                    [{"role": "user", "content": self._adv_retry_prompt}]
                )
            except Exception as exc:
                self._adv_error = str(exc)

        self._adv_thread = threading.Thread(target=_fetch, daemon=True)
        self._adv_thread.start()

    @property
    def adventure_log_error(self) -> str | None:
        """Error message if adventure log generation failed, ``None`` otherwise.

        Check this after ``get_adventure_log()`` returns ``None`` to
        distinguish "API error" (this property is set) from "still
        waiting / timeout" (this property is ``None``).
        """
        return self._adv_error
