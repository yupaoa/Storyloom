"""Main narrative game loop, GameState, and result types.

Coordinates all modules: PromptBuilder, ContextManager, ApiClient, XmlParser, Display.
Validates all LLM-suggested state changes (local source of truth).
"""

import re
from dataclasses import dataclass, field

from src.storyloom.api_client import ApiClient
from src.storyloom.context_manager import ContextManager
from src.storyloom.display import Display
from src.storyloom.prompt_builder import PromptBuilder
from src.storyloom.xml_parser import (
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

        if new_val < self.NUMBER_MIN or new_val > self.NUMBER_MAX:
            return SetResult(
                accepted=False,
                reason=f"{var_name} {new_val} out of range [{self.NUMBER_MIN}, {self.NUMBER_MAX}]",
            )

        self._state_vars[var_name] = new_val
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

        # Try to get the variable value
        if var_name in self._state_vars:
            var_value = self._state_vars[var_name]
        elif var_name in choice_dict:
            var_value = choice_dict[var_name]
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
    1. start_round1() -> Prompter -> API -> Parser -> display
    2. Player makes choice
    3. continue_round() -> apply state changes -> update outline ->
       build context -> API -> Parser -> display
    4. Repeat from step 2 until ending.
    """

    def __init__(
        self,
        story_config: dict,
        outline_text: str,
        api_client: ApiClient,
        display: Display | None = None,
        game_state: GameState | None = None,
        current_node: str | None = None,
        goal: str | None = None,
    ):
        """Initialize game loop with story config and dependencies.

        Args:
            story_config: Story configuration dict.
            outline_text: Formatted outline text.
            api_client: API client for LLM calls.
            display: Optional display for UI output.
            game_state: Optional GameState (created from story_config if omitted).
            current_node: Starting node ID (optional).
            goal: Starting node goal description (optional).
        """
        self.story_config = story_config
        self.outline_text = outline_text
        self.api_client = api_client
        self.display = display or Display()

        # Internal modules
        self._prompter = PromptBuilder()
        self._context_mgr = ContextManager()

        # State
        self.game_state = game_state or GameState(story_config)
        self.current_node = current_node
        self.goal = goal
        self._completed_nodes: list[str] = []
        self.last_parsed: ParsedOutput | None = None
        self._last_bridge_text: str = ""
        self._rejected_changes: list[str] = []
        self._format_error: str | None = None
        self._round1_started = False

    # ── Properties ─────────────────────────────────────────────────

    @property
    def round_count(self) -> int:
        """Current round number (0 before start_round1)."""
        return self._context_mgr.round_count

    @property
    def completed_nodes(self) -> list[str]:
        """List of completed node IDs."""
        return list(self._completed_nodes)

    # ── Round 1 ───────────────────────────────────────────────────

    def start_round1(self) -> RoundResult:
        """Build Round 1 prompt, call API, parse response.

        Returns:
            RoundResult with parsed output.

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

        # Build messages array (Round 1 only has user message)
        messages = [{"role": "user", "content": r1_prompt}]

        # Display wait message
        self.display.show_wait_message("故事生成中...")

        # Call API
        response = self.api_client.stream_chat(messages)

        # Parse response
        parsed = XmlParser.parse(response)

        # Store in context manager (both user and assistant)
        self._context_mgr.set_round1(r1_prompt, response)

        # Store parsed output
        self.last_parsed = parsed
        self._last_bridge_text = parsed.bridge_text

        # Display segments
        self.display.show_segments(parsed.segments)

        # Display options if available
        if parsed.choice_id and parsed.opt_branches:
            # We still show it even though labels are not in ParsedOutput
            labels = [f"选项{branch}" for branch in parsed.opt_branches]
            self.display.show_options(parsed.choice_id, parsed.opt_branches, labels)

        return RoundResult(parsed=parsed, round_number=1)

    # ── Continue Round ────────────────────────────────────────────

    def continue_round(self, choice_key: str | None = None) -> RoundResult:
        """Process player choice, build context, call API, parse response.

        Args:
            choice_key: Player's choice (1-indexed string) or None if no choice.

        Returns:
            RoundResult with parsed output.

        Raises:
            RuntimeError: If start_round1 hasn't been called.
        """
        if self.last_parsed is None:
            raise RuntimeError("No last result - call start_round1 first")

        # Build choice_dict
        choice_dict: dict[str, int] = {}
        if choice_key is not None and self.last_parsed.choice_id is not None:
            try:
                choice_num = int(choice_key)
                choice_dict[self.last_parsed.choice_id] = choice_num
            except ValueError:
                pass

        # Apply state changes from last parsed output
        new_rejected: list[str] = []
        for set_op in self.last_parsed.sets:
            result = self.game_state.apply_set(set_op, choice_dict)
            if not result.accepted and result.reason:
                new_rejected.append(result.reason)
        self._rejected_changes = new_rejected

        # Evaluate routes
        if choice_dict:
            route = self._evaluate_routes(choice_dict)
            if route:
                self.current_node = route

        # Get compressed summaries info from context manager
        compressed_rounds = self._context_mgr.get_compressed_rounds()
        compressed_summaries = (
            [str(r) for r in compressed_rounds] if compressed_rounds else None
        )

        # Get bridge text from context manager
        bridge_text = self._context_mgr.get_last_bridge_text()

        # Build Round N context
        rn_context = self._prompter.build_round_n(
            current_node=self.current_node or "",
            goal=self.goal or "",
            completed_nodes=self._completed_nodes,
            state_vars=self.game_state.state_vars,
            bridge_text=bridge_text,
            compressed_summaries=compressed_summaries,
            rejected_changes=self._rejected_changes if self._rejected_changes else None,
            format_error=self._format_error,
        )

        # Get existing messages and append current context
        messages = self._context_mgr.get_messages()
        messages.append({"role": "user", "content": rn_context})

        # Display wait message
        self.display.show_wait_message("故事生成中...")

        # Call API
        response = self.api_client.stream_chat(messages)

        # Parse response
        parsed = XmlParser.parse(response)

        # Store round in context manager
        self._context_mgr.add_round(rn_context, response)

        # Update stored state
        self.last_parsed = parsed
        self._last_bridge_text = parsed.bridge_text

        # Apply state changes from new round (unconditional ones)
        new_rejected_current: list[str] = []
        for set_op in parsed.sets:
            # Unconditional sets in the current round are applied immediately
            if not set_op.condition:
                result = self.game_state.apply_set(set_op, {})
                if not result.accepted and result.reason:
                    new_rejected_current.append(result.reason)
            else:
                # Conditional sets evaluated later when player makes choice
                pass
        if new_rejected_current:
            self._rejected_changes.extend(new_rejected_current)

        # Display segments
        self.display.show_segments(parsed.segments)

        # Display options
        if parsed.choice_id and parsed.opt_branches:
            labels = [f"选项{branch}" for branch in parsed.opt_branches]
            self.display.show_options(parsed.choice_id, parsed.opt_branches, labels)

        return RoundResult(
            parsed=parsed,
            round_number=self._context_mgr.round_count,
        )

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
        """Evaluate route conditions from last parsed output."""
        if not self.last_parsed:
            return None
        for route in self.last_parsed.routes:
            if route.condition is None:
                return route.target
            if self.game_state.evaluate_condition(
                route.condition, choice_dict
            ):
                return route.target
        return None

    # ── Adventure Log ─────────────────────────────────────────────

    def run_adventure_log(self) -> str:
        """Generate adventure log / ending summary.

        Uses non-streaming chat to generate a summary of the adventure.

        Returns:
            Summary text.
        """
        messages = self._context_mgr.get_messages()
        messages.append({
            "role": "user",
            "content": (
                "请为这段冒险写一段结局总结（200-300字），"
                "概括主角的旅程、关键抉择和最终命运。"
            ),
        })
        self.display.show_wait_message("生成冒险日志...")
        return self.api_client.chat(messages)
