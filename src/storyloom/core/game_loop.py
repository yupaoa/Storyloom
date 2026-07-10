"""Main narrative game loop, GameState, and result types.

Coordinates all modules: PromptBuilder, ContextManager, ApiClient, XmlParser.
Validates all LLM-suggested state changes (local source of truth).
"""

import copy
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Callable

from storyloom.io.api_client import ApiClient
from storyloom.core.context_manager import ContextManager
from storyloom.core.prompt_builder import PromptBuilder
from storyloom.parser.xml_parser import (
    ParsedOutput,
    SetOperation,
    XmlParser,
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

        Raises:
            ValueError: If variable doesn't exist or operation is incompatible.
        """
        var_name = set_op.var

        # Step 1: Check variable exists
        if var_name not in self._state_vars:
            raise ValueError(f"unknown variable: {var_name}")

        var_type = self._var_types[var_name]

        # Step 2: Check operation is valid for type
        if var_type == "number" and set_op.op not in self.VALID_NUMBER_OPS:
            raise ValueError(
                f"Invalid number operation: {set_op.op} for {var_name}"
            )
        if var_type == "string" and set_op.op not in self.VALID_STRING_OPS:
            raise ValueError(
                f"Invalid string operation: {set_op.op} for {var_name}"
            )
        if var_type == "list" and set_op.op not in self.VALID_LIST_OPS:
            raise ValueError(
                f"Invalid list operation: {set_op.op} for {var_name}"
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
        self._outline_nodes = outline_nodes or []
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

        # Checkpoint and save accumulators
        self._temperature = getattr(api_client, "temperature", None)
        self._checkpoint_summaries: list[str] = []
        self._checkpoint_history: list[dict] = []
        self._checkpoint_snapshots: dict[str, dict] = {}
        self.ending_flag: bool = False
        self._save_manager = None
        self._created_at: str | None = None

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

        # Stream API response token by token
        collected: list[str] = []
        ttft: float | None = None
        tokens: dict | None = None

        for chunk in self.api_client.stream_chat_iter(messages):
            if chunk.get("done"):
                tokens = chunk.get("usage")
            else:
                if chunk.get("ttft") is not None:
                    ttft = chunk["ttft"]
                collected.append(chunk["delta"])
                yield {"type": "token", "text": chunk["delta"]}

        response = "".join(collected)

        # Parse response
        try:
            parsed = XmlParser.parse(response)
        except Exception as e:
            self._format_error = str(e)
            self._notify(RoundRecord(
                round_number=1,
                messages_sent=messages,
                raw_response=response,
                parsed=None,
                ttft=ttft,
                tokens=tokens,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                node=self.current_node,
                selected_branch=None,
            ))
            yield {"type": "error", "message": str(e)}
            return

        # Store in context manager
        self._context_mgr.set_round1(r1_prompt, response)

        # Clear previous format error on successful parse
        self._format_error = None

        # Store parsed output
        self.last_parsed = parsed
        self._last_bridge_text = parsed.bridge_text

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

        if state_changes:
            yield {
                "type": "state",
                "vars": self.game_state.state_vars,
                "changes": state_changes,
            }

        # Yield structured events from parsed output
        yield from self._emit_parsed(parsed)

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
                from storyloom.parser.xml_parser import ParseError
                raise ParseError(
                    f"Round 1 parse failed: {event['message']}"
                )

        if self.last_parsed is None:
            from storyloom.parser.xml_parser import ParseError
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

        # ── Step 2: Apply last round's sets (with choice_dict) ──────
        step2_changes: list[dict] = []
        new_rejected: list[str] = []
        for set_op in self.last_parsed.sets:
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

        if step2_changes:
            yield {
                "type": "state",
                "vars": self.game_state.state_vars,
                "changes": step2_changes,
            }

        # ── Step 3: Evaluate routes → advance node ──────────────────
        if choice_dict:
            old_node = self.current_node
            route = self._evaluate_routes(choice_dict)
            if route:
                if old_node and old_node not in self._completed_nodes:
                    self._completed_nodes.append(old_node)
                self.current_node = route
                self.goal = self._node_goals.get(route, self.goal or "")
            elif not self.last_parsed.routes:
                if old_node and old_node not in self._completed_nodes:
                    self._completed_nodes.append(old_node)
        elif not self.last_parsed.routes:
            # No player choice and no routes — LLM auto-advanced node
            cp = self.last_parsed.checkpoint_node
            if cp and cp != self.current_node:
                if self.current_node and self.current_node not in self._completed_nodes:
                    self._completed_nodes.append(self.current_node)
                self.current_node = cp
                self.goal = self._node_goals.get(cp, self.goal or "")

        # ── Step 3.5: Accumulate checkpoint data ────────────────────
        if self.last_parsed.checkpoint_node:
            cp_node = self.last_parsed.checkpoint_node
            cp_summary = self.last_parsed.checkpoint_summary or ""

            if cp_summary:
                self._checkpoint_summaries.append(cp_summary)

            # Resolve title from _outline_nodes. For the "end" sentinel,
            # fall back to the last outline node's title.
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

            # Trigger auto-save if SaveManager is configured
            if self._save_manager is not None:
                try:
                    self._save_manager.save(self.to_save_dict())
                except Exception:
                    pass

        # ── Step 3.6: Ending detection ──────────────────────────────
        if self.last_parsed.checkpoint_node == "end":
            self.ending_flag = True
            if "end" not in self._completed_nodes:
                self._completed_nodes.append("end")

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

        # ── Step 6: Stream API response ─────────────────────────────
        collected: list[str] = []
        ttft: float | None = None
        tokens: dict | None = None

        for chunk in self.api_client.stream_chat_iter(messages):
            if chunk.get("done"):
                tokens = chunk.get("usage")
            else:
                if chunk.get("ttft") is not None:
                    ttft = chunk["ttft"]
                collected.append(chunk["delta"])
                yield {"type": "token", "text": chunk["delta"]}

        response = "".join(collected)

        # ── Step 7: Parse response ──────────────────────────────────
        self._format_error = None  # clear previous error
        try:
            parsed = XmlParser.parse(response)
        except Exception as e:
            self._format_error = str(e)
            self._notify(RoundRecord(
                round_number=self._context_mgr.round_count + 1,
                messages_sent=messages,
                raw_response=response,
                parsed=None,
                ttft=ttft,
                tokens=tokens,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                node=self.current_node,
                selected_branch=selected_branch,
            ))
            yield {"type": "error", "message": str(e)}
            return

        # ── Step 8: Store round in context manager ──────────────────
        self._context_mgr.add_round(rn_context, response, selected_branch)

        # ── Step 9: Apply this round's unconditional sets ───────────
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

        # Update stored state
        self.last_parsed = parsed
        self._last_bridge_text = parsed.bridge_text

        # ── Yield structured events ─────────────────────────────────
        yield from self._emit_parsed(parsed)

        # ── Check for ending after emitting parsed content ──
        if self.ending_flag:
            try:
                adventure_log = self.run_adventure_log()
            except Exception:
                adventure_log = None

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

            # Notify observers for ending round (same data as normal rounds)
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
            "round": self._context_mgr.round_count,
            "node": self.current_node,
            "state": self.game_state.state_vars,
        }

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
                from storyloom.parser.xml_parser import ParseError
                raise ParseError(
                    f"Round {self._context_mgr.round_count + 1} parse "
                    f"failed: {event['message']}"
                )

        if self.last_parsed is None:
            from storyloom.parser.xml_parser import ParseError
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
    def _emit_parsed(parsed: ParsedOutput) -> Iterator[dict]:
        """Yield structured events from parsed LLM output.

        Args:
            parsed: ParsedOutput from XmlParser.parse().

        Yields:
            segment and options events.
        """
        for seg in parsed.segments:
            yield {
                "type": "segment",
                "text": seg.text,
                "n": seg.n,
                "position": seg.position,
                "branch": seg.branch,
            }

        if parsed.choices:
            yield {
                "type": "options",
                "choices": parsed.choices,
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
                "branches": [r.get("target", "") for r in node.get("routes", [])],
            })

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        label = self.story_config.get("label", "untitled")

        # Preserve original created_at; set on first save only.
        if self._created_at is None:
            self._created_at = now

        return {
            "version": 1,
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
        messages = self._context_mgr.get_messages()
        messages.append({"role": "user", "content": prompt})
        return self.api_client.chat(messages)
