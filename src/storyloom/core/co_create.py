"""Co-creation phase: user input → Q&A loop → story setup generation."""
import re
from dataclasses import dataclass, field

from storyloom.io.api_client import ApiClient
from storyloom.core.ui_interface import UiInterface
from storyloom.i18n import _, get_current_lang
from storyloom.config import (
    MAX_RETRIES,
    STORY_LABEL_MIN_CHARS,
    STORY_LABEL_MAX_CHARS,
    VARIABLE_CAP,
    VARIABLE_NUMERIC_CAP,
    VARIABLE_LABEL_CAP,
    OUTLINE_NODE_RANGES,
)


class CoCreateParser:
    """Stateless helpers for parsing LLM co-creation output."""

    BLOCK_DELIMITER = re.compile(r"^=== (story_config|variables|outline) ===\s*$")

    @staticmethod
    def split_blocks(text: str) -> dict[str, str]:
        """Split LLM response into {story_config, variables, outline} blocks.

        Args:
            text: Raw LLM response text.

        Returns:
            Dict with keys 'story_config', 'variables', 'outline'.
            Missing blocks have empty string values.
        """
        result = {"story_config": "", "variables": "", "outline": ""}
        current_block: str | None = None
        lines: list[str] = []

        for line in text.split("\n"):
            m = CoCreateParser.BLOCK_DELIMITER.match(line.strip())
            if m:
                if current_block and current_block in result:
                    result[current_block] = "\n".join(lines).strip()
                current_block = m.group(1)
                lines = []
            elif current_block:
                lines.append(line)

        if current_block and current_block in result:
            result[current_block] = "\n".join(lines).strip()

        return result

    REQUIRED_CONFIG_FIELDS = [
        "genre", "tier", "label",
        "protagonist_name", "protagonist_identity",
        "protagonist_traits", "tone", "conflict", "characters",
    ]
    VALID_TIERS = {"short", "medium", "long"}

    @staticmethod
    def parse_story_config(text: str) -> dict:
        """Parse INI-style story config block into a dict.

        Args:
            text: Raw text of the story_config block.

        Returns:
            Dict with keys: genre, tier, setting, protagonist_name,
            protagonist_identity, protagonist_traits, tone, conflict,
            characters, language.

        Raises:
            ValueError: On missing required fields or invalid tier.
        """
        if not text or not text.strip():
            raise ValueError("Empty story_config block")

        result: dict[str, str] = {}
        result["language"] = "zh-CN"  # default
        current_field: str | None = None

        for line in text.strip().split("\n"):
            # Check for key: value line
            kv_match = re.match(r"^(\w+):\s*(.*)$", line)
            if kv_match:
                current_field = kv_match.group(1)
                value = kv_match.group(2).strip()
                result[current_field] = value
            elif current_field and line.startswith("  "):
                # Continuation line (e.g., characters sub-lines)
                result[current_field] += "\n" + line.strip()

        # Validate required fields
        missing = [f for f in CoCreateParser.REQUIRED_CONFIG_FIELDS
                   if f not in result or not result[f].strip()]
        if missing:
            raise ValueError(
                f"Missing required fields: {', '.join(missing)}"
            )

        # Validate tier
        tier = result.get("tier", "")
        if tier not in CoCreateParser.VALID_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}'. Must be one of: "
                f"{', '.join(sorted(CoCreateParser.VALID_TIERS))}"
            )

        # Validate label length
        label = result.get("label", "")
        if len(label) < STORY_LABEL_MIN_CHARS:
            raise ValueError(
                f"Label '{label}' too short (min {STORY_LABEL_MIN_CHARS} chars)"
            )
        if len(label) > STORY_LABEL_MAX_CHARS:
            raise ValueError(
                f"Label '{label}' too long (max {STORY_LABEL_MAX_CHARS} chars)"
            )

        # setting defaults to empty string
        if "setting" not in result:
            result["setting"] = ""

        return result

    VAR_LINE_RE = re.compile(
        r"^([^:]+):\s*(\S+),\s*初始\s+(.+)$"
    )

    @staticmethod
    def parse_variables(text: str) -> list[dict]:
        """Parse variables block into list of {name, type, initial} dicts.

        Format: 变量名: 类型, 初始 值

        Args:
            text: Raw text of the variables block.

        Returns:
            List of variable definition dicts.

        Raises:
            ValueError: On parse errors or invalid types/values.
        """
        if not text or not text.strip():
            return []

        result = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            m = CoCreateParser.VAR_LINE_RE.match(line)
            if not m:
                raise ValueError(
                    f"Cannot parse variable line: '{line}'. "
                    f"Expected format: 变量名: 类型, 初始 值"
                )

            name = m.group(1)
            var_type = m.group(2)
            raw_initial = m.group(3).strip()

            if var_type not in ("number", "string", "list"):
                raise ValueError(
                    f"Unknown type '{var_type}' for variable '{name}'. "
                    f"Must be number, string, or list."
                )

            if var_type == "number":
                try:
                    initial = int(raw_initial)
                except ValueError:
                    raise ValueError(
                        f"Number variable '{name}' initial value "
                        f"'{raw_initial}' is not an integer."
                    )
            elif var_type == "list":
                if raw_initial in ("[]", ""):
                    initial = []
                else:
                    initial = [s.strip() for s in raw_initial.split(",") if s.strip()]
            else:
                initial = raw_initial

            result.append({"name": name, "type": var_type, "initial": initial})

        return result

    @staticmethod
    def validate_variables(variables: list[dict]) -> list[str]:
        """Validate parsed variable definitions.

        Args:
            variables: List of {name, type, initial} dicts.

        Returns:
            List of error strings. Empty = valid.
        """
        errors = []

        # f: Total count ≤ 3
        if len(variables) > VARIABLE_CAP:
            errors.append(
                f"Variable count {len(variables)} exceeds maximum {VARIABLE_CAP}"
            )

        # a: Name uniqueness + valid chars
        seen_names = set()
        for v in variables:
            name = v["name"]
            if "\n" in name or ":" in name:
                errors.append(
                    f"Variable name '{name}' contains illegal characters"
                )
            if name in seen_names:
                errors.append(f"Duplicate variable name: '{name}'")
            seen_names.add(name)

        # g: Type counts
        num_count = sum(1 for v in variables if v["type"] == "number")
        label_count = sum(1 for v in variables if v["type"] in ("string", "list"))

        if num_count > VARIABLE_NUMERIC_CAP:
            errors.append(
                f"Numeric variables ({num_count}) exceed maximum "
                f"{VARIABLE_NUMERIC_CAP}"
            )
        if label_count > VARIABLE_LABEL_CAP:
            errors.append(
                f"Label variables ({label_count}) exceed maximum "
                f"{VARIABLE_LABEL_CAP}"
            )

        # c-f: Per-variable validation
        for v in variables:
            name = v["name"]
            var_type = v["type"]
            initial = v["initial"]

            if var_type == "number":
                if not isinstance(initial, int):
                    errors.append(
                        f"'{name}': initial value must be integer, got {type(initial).__name__}"
                    )
                elif initial < 0 or initial > 100:
                    errors.append(
                        f"'{name}': initial value {initial} out of range [0, 100]"
                    )
            elif var_type == "string":
                if not initial or not str(initial).strip():
                    errors.append(
                        f"'{name}': string initial value must be non-empty"
                    )
            elif var_type == "list":
                if not isinstance(initial, list):
                    errors.append(
                        f"'{name}': list initial must be a list"
                    )
                else:
                    for i, elem in enumerate(initial):
                        if not isinstance(elem, str):
                            errors.append(
                                f"'{name}': list element [{i}] must be string, "
                                f"got {type(elem).__name__}"
                            )

        return errors

    @staticmethod
    def parse_outline(text: str) -> list[dict]:
        """Parse outline block into list of node dicts.

        Args:
            text: Raw text of the outline block.

        Returns:
            List of node dicts, each with keys: id, title, goal, routes.
            routes: list of {condition: str|None, target: str} dicts.

        Raises:
            ValueError: On parse errors or missing required fields.
        """
        if not text or not text.strip():
            raise ValueError("Empty outline block")

        nodes = []
        current: dict | None = None

        for line in text.strip().split("\n"):
            line_stripped = line.strip()

            if line_stripped == "[node]":
                if current:
                    nodes.append(current)
                current = {"id": "", "title": "", "goal": "", "routes": []}
            elif current is not None:
                if line_stripped.startswith("id:"):
                    current["id"] = line_stripped[3:].strip()
                elif line_stripped.startswith("title:"):
                    current["title"] = line_stripped[6:].strip()
                elif line_stripped.startswith("goal:"):
                    current["goal"] = line_stripped[5:].strip()
                elif line_stripped.startswith("routes:"):
                    route_text = line_stripped[7:].strip()
                    if route_text and route_text not in ("（结局）", "(ending)"):
                        # Single route on same line: → target
                        target = route_text.lstrip("→ ").strip()
                        if target:
                            current["routes"].append(
                                {"condition": None, "target": target}
                            )
                elif line_stripped.startswith("if ") and "→" in line_stripped:
                    # Indented route: if condition → target
                    parts = line_stripped.split("→", 1)
                    condition = parts[0].strip()
                    if condition.startswith("if "):
                        condition = condition[3:]
                    target = parts[1].strip() if len(parts) > 1 else ""
                    if condition and target:
                        current["routes"].append(
                            {"condition": condition, "target": target}
                        )

        if current:
            nodes.append(current)

        if not nodes:
            raise ValueError("No nodes found in outline")

        # Validate each node has required fields
        for i, node in enumerate(nodes):
            if not node["id"]:
                raise ValueError(f"Node {i + 1}: Missing 'id' field")
            if not node["title"]:
                raise ValueError(f"Node {i + 1} ('{node['id']}'): Missing 'title' field")
            if not node["goal"]:
                raise ValueError(f"Node {i + 1} ('{node['id']}'): Missing 'goal' field")

        return nodes

    @staticmethod
    def validate_outline(
        nodes: list[dict], variable_names: list[str]
    ) -> list[str]:
        """Validate outline structure.

        Args:
            nodes: List of node dicts from parse_outline.
            variable_names: List of valid variable names.

        Returns:
            List of error strings. Empty = valid.
        """
        errors = []

        # c: Node count ≥ 1
        if len(nodes) == 0:
            errors.append("Outline must have at least 1 node")
            return errors

        node_ids = {n["id"] for n in nodes}

        # a: All route targets exist
        for node in nodes:
            for route in node["routes"]:
                target = route["target"]
                if target not in node_ids:
                    errors.append(
                        f"Node '{node['id']}': route target "
                        f"'{target}' does not exist in outline"
                    )

        # b: Final node has no routes (is ending)
        if len(nodes) > 0:
            final = nodes[-1]
            if final["routes"]:
                errors.append(
                    f"Final node '{final['id']}' has branches but should "
                    f"be the ending node with no routes"
                )

        return errors

    @staticmethod
    def format_outline(nodes: list[dict]) -> str:
        """Convert parsed [node] blocks into GameLoop-compatible outline text.

        Format matches the existing SAMPLE_OUTLINE in main.py:
            ch1_intro [active] — title：goal
              → ch2_meeting [pending]

        Args:
            nodes: List of node dicts from parse_outline.

        Returns:
            Formatted outline string ready for GameLoop / PromptBuilder.
        """
        lines = []
        for i, node in enumerate(nodes):
            status = "[active]" if i == 0 else "[pending]"
            lines.append(f"{node['id']} {status} — {node['title']}：{node['goal']}")

            routes = node["routes"]
            if not routes:
                continue

            for j, route in enumerate(routes):
                is_last = (j == len(routes) - 1)
                prefix = "  └→" if is_last else "  ├→"
                target = route["target"]
                lines.append(f"{prefix} {target} [pending]")

        return "\n".join(lines)


# ── Prompt Templates ────────────────────────────────────────────────

CO_CREATE_SYSTEM_PROMPT = """You are a warm and perceptive story co-creation partner. Your goal is to help the user discover the story they truly want to experience — by asking thoughtful questions, listening carefully, and guiding gently.

# Questioning Phase

Ask one question at a time, focused on these five dimensions. Do NOT reveal specific plot events or spoil story content:
- World setting (era, location, tech/magic level, society)
- Protagonist (name, identity, personality traits, background)
- Story tone (dark/light, epic/personal, serious/humorous)
- Conflict direction (core tension — describe it as a question the story explores)
- Story length (short ~10 rounds / medium ~20 rounds / long ~40 rounds)

**After each question, offer 2-3 example answers as numbered suggestions** — these help the user express themselves, but they are free to write their own answer. Format:
```
[1] example answer one
[2] example answer two
[3] example answer three
（或输入你自己的答案）
```

Show genuine curiosity about the user's choices. Acknowledge their previous answer before asking the next question — this makes the conversation feel natural, not like a form.

When you have enough information (usually 3-5 questions), end your reply with:
"This should be enough — shall I start generating the story?"

When the user indicates they are ready, I will ask you to generate the full setup.

# Generation Phase

When asked to generate the full setup, output ALL THREE sections below in order. Use EXACTLY the format shown.

## Section 1: story_config

```
=== story_config ===
genre: {free text, e.g. "cyberpunk adventure", "historical mystery"}
tier: {short / medium / long}
label: {5-15 Chinese characters, unique story identifier for save files}
setting: {one sentence: era, location, key world facts}
protagonist_name: {name}
protagonist_identity: {one sentence}
protagonist_traits: {2-3 key traits}
tone: {e.g. "dark and gritty", "light and humorous"}
conflict: {one sentence, core tension}
characters:
  {name} | {role} | {relationship to protagonist}
  (at least 1)
```

## Section 2: variables

Design state variables for this story. Rules:
- ≤3 variables total. ≤2 numeric (number), ≤1 label (string/list).
- Numeric: range [0, 100]. Use for health, trust, sanity, etc.
- String: for status markers, faction affiliation, etc.
- List: elements are strings. For inventory, clues, skills, etc.
- Variable names in Chinese, 2-5 characters.
- Fewer is better. Only create variables that will drive branching or gate choices.

Genre seed reference (adopt or adapt based on the story; replace if unsuitable):
  Romance → affection
  Mystery → clues_progress
  Cyberpunk → implant_integrity
  Wuxia → inner_power
  Horror → sanity

```
=== variables ===
体力: number, 初始 80
信任度: number, 初始 10
所属势力: string, 初始 自由佣兵
```

## Section 3: outline

Design a directed graph of key story nodes. Rules:
- Node count by tier: short 3-5 / medium 5-8 / long 8-15
- Each node has a clear narrative goal
- Branches use `if {condition} → {target_node}`. Conditions may only reference declared variables.
- Final node is the ending (no branches).
- node_id format: ch{number}_{english_abbreviation}

```
=== outline ===
[node]
id: ch1_intro
title: {node title}
goal: {narrative goal of this node}
routes: → ch2_next

[node]
id: ch2_next
title: {node title}
goal: {narrative goal}
routes:
  if 信任度 >= 30 → ch3_path_a
  if 信任度 < 30 → ch3_path_b

[node]
id: ch3_path_a
title: {node title}
goal: {narrative goal}
routes: → ch4_ending

[node]
id: ch3_path_b
title: {node title}
goal: {narrative goal}
routes: → ch4_ending

[node]
id: ch4_ending
title: {node title}
goal: {narrative goal}（结局）
routes: （结局）
```

Output all three sections in a single response. Do not add commentary before or after."""


GENERATE_ALL_PROMPT = """Based on our conversation above, generate the complete story setup.

Output ALL THREE sections: story_config, variables, and outline.
Follow the format exactly as specified in the system instructions.

Available variables for the outline: {variable_names}"""


# ── Exceptions ──────────────────────────────────────────────────────

class CoCreationAborted(Exception):
    """Raised when user chooses to abort co-creation and return to menu."""
    pass


# ── Result ───────────────────────────────────────────────────────────

@dataclass
class CoCreationResult:
    """Output of the co-creation phase, ready for GameLoop."""
    story_config: dict
    outline_text: str
    outline_nodes: list[dict] = field(default_factory=list)


# ── Flow ─────────────────────────────────────────────────────────────

class CoCreateFlow:
    """Orchestrates the full co-creation phase.

    Flow:
        Step 1: User inputs raw story idea.
        Step 2: Multi-turn Q&A loop with LLM.
        Step 3: Single LLM call generates story_config + variables + outline.
    """

    _START_KEYWORDS = {"开始", "开始吧", "可以", "好的", "行", "ok", "OK", "yes", "go", "start", "begin", "ready"}
    _QUIT_KEYWORDS = {"不玩了", "退出", "quit", "exit", "q", "stop", "abort"}

    def __init__(self, api_client: ApiClient, ui: UiInterface | None = None):
        self._api = api_client
        self._ui = ui
        self._messages: list[dict] = [
            {"role": "system", "content": CO_CREATE_SYSTEM_PROMPT}
        ]
        self._phase: str = "init"
        self._result: CoCreationResult | None = None
        self._qa_round = 0

    @property
    def messages(self) -> list[dict]:
        """Return the full co-creation conversation messages.

        Contains system prompt, Q&A turns, and the final generation
        prompt. Use with cli_utils.save_prompts() to dump to a file.
        """
        return list(self._messages)

    @property
    def phase(self) -> str:
        """Current phase: 'init' | 'awaiting_idea' | 'awaiting_answer'
           | 'generating' | 'complete' | 'aborted'."""
        return self._phase

    @property
    def result(self) -> CoCreationResult | None:
        """Result when phase == 'complete', None otherwise."""
        return self._result

    def start(self) -> dict:
        """Begin co-creation. Returns {phase: 'awaiting_idea', prompt: str}.

        Must be called once before any send().

        Raises:
            RuntimeError: If already started.
        """
        if self._phase != "init":
            raise RuntimeError(
                f"Co-creation already started (phase: {self._phase})"
            )
        self._phase = "awaiting_idea"
        return {
            "phase": "awaiting_idea",
            "prompt": _("Describe the story you'd like to play.\n"
                         "e.g. 'A cyberpunk love story' or 'A wuxia adventure'"),
        }

    def abort(self) -> None:
        """Abort co-creation immediately."""
        self._phase = "aborted"

    def send(self, user_input: str) -> dict:
        """Send user input, advance one step, return next event dict.

        Handles phase transitions: awaiting_idea → awaiting_answer →
        complete/aborted. Blocking during LLM generation.

        Returns event dict with 'phase' key and phase-specific data.
        Does NOT call ui methods — communicates solely via return dicts.

        Raises:
            RuntimeError: If called before start() or after completion.
        """
        if self._phase == "init":
            raise RuntimeError("call start() first before send()")
        if self._phase == "complete":
            raise RuntimeError("co-creation already complete")
        if self._phase == "aborted":
            raise RuntimeError("co-creation was aborted")

        # ── Phase: awaiting_idea ──
        if self._phase == "awaiting_idea":
            stripped_idea = user_input.strip()
            if not stripped_idea:
                return {"phase": "awaiting_idea",
                        "prompt": _("Please share some thoughts to begin.")}

            self._phase = "generating"
            self._messages.append({"role": "user", "content": stripped_idea})
            try:
                response = self._api.chat(self._messages)
            except Exception as e:
                self._messages.pop()  # Remove orphaned user message
                self._phase = "awaiting_idea"
                return {"phase": "error", "message": str(e), "recoverable": True}

            self._messages.append({"role": "assistant", "content": response})
            self._phase = "awaiting_answer"
            self._qa_round = 1
            return {"phase": "awaiting_answer", "question": response, "round": 1}

        # ── Phase: awaiting_answer ──
        if self._phase == "awaiting_answer":
            stripped = user_input.strip()

            # Check quit keywords
            if stripped in self._QUIT_KEYWORDS:
                self._phase = "aborted"
                return {"phase": "aborted"}

            # Check start/go keywords → trigger generation
            if stripped in self._START_KEYWORDS:
                self._phase = "generating"
                try:
                    result = self._generate_all()
                except CoCreationAborted:
                    self._phase = "aborted"
                    return {"phase": "aborted"}
                except Exception as e:
                    self._phase = "awaiting_answer"
                    return {"phase": "error", "message": str(e), "recoverable": True}

                self._phase = "complete"
                self._result = result
                return {"phase": "complete", "result": result}

            # Normal answer → next Q&A round
            self._phase = "generating"
            self._messages.append({"role": "user", "content": stripped})
            try:
                response = self._api.chat(self._messages)
            except Exception as e:
                self._messages.pop()  # Remove orphaned user message
                self._phase = "awaiting_answer"
                return {"phase": "error", "message": str(e), "recoverable": True}

            self._messages.append({"role": "assistant", "content": response})
            self._phase = "awaiting_answer"
            self._qa_round += 1

            # Round limit check (max 15 rounds, matching current _step2_questioning)
            if self._qa_round > 15:
                self._phase = "generating"
                try:
                    result = self._generate_all()
                except CoCreationAborted:
                    self._phase = "aborted"
                    return {"phase": "aborted"}
                except Exception as e:
                    self._phase = "awaiting_answer"
                    return {"phase": "error", "message": str(e), "recoverable": True}

                self._phase = "complete"
                self._result = result
                return {"phase": "complete", "result": result}

            return {"phase": "awaiting_answer", "question": response,
                    "round": self._qa_round}

        # Fallback
        return {"phase": self._phase}

    def _generate_all(self) -> CoCreationResult:
        """Generate full story setup without UI interaction.

        Used by send() for the state machine API.

        Raises:
            CoCreationAborted: If outline validation fails.
            ValueError: If parsing fails (caught by send()).
        """
        var_names = self._build_var_names_hint()
        gen_prompt = GENERATE_ALL_PROMPT.format(variable_names=var_names)
        self._messages.append({"role": "user", "content": gen_prompt})

        response = self._api.chat(self._messages)
        self._messages.append({"role": "assistant", "content": response})

        blocks = CoCreateParser.split_blocks(response)

        story_config = CoCreateParser.parse_story_config(blocks["story_config"])
        variables = CoCreateParser.parse_variables(blocks["variables"])
        var_errors = CoCreateParser.validate_variables(variables)
        if var_errors:
            raise CoCreationAborted()
        outline_nodes = CoCreateParser.parse_outline(blocks["outline"])

        var_names_list = [v["name"] for v in variables]
        outline_errors = CoCreateParser.validate_outline(outline_nodes, var_names_list)
        if outline_errors:
            raise CoCreationAborted()

        story_config["variables"] = variables
        outline_text = CoCreateParser.format_outline(outline_nodes)

        return CoCreationResult(
            story_config=story_config,
            outline_text=outline_text,
            outline_nodes=outline_nodes,
        )

    def run(self) -> CoCreationResult:
        """Run the full co-creation flow.

        Returns:
            CoCreationResult with story_config (including variables)
            and formatted outline_text.

        Raises:
            CoCreationAborted: If user chooses to abort.
            RuntimeError: If ui is None (not set during construction).
        """
        if self._ui is None:
            raise RuntimeError(
                "CoCreateFlow.run() requires a UiInterface. "
                "Pass ui= at construction, or use the state machine API "
                "(start()/send()) for UI-agnostic co-creation."
            )
        self._step1_get_idea()
        self._step2_questioning()
        return self._step3_generate_all()

    # ── Step 1 ──────────────────────────────────────────────────

    def _step1_get_idea(self) -> None:
        """Collect user's initial story idea."""
        d = self._ui
        d.write("\n")
        d.write("━" * 50 + "\n")
        d.write(_("[Co-Creation — Story Setup]") + "\n\n")
        d.write(_("Describe the story you'd like to play.\ne.g. 'A cyberpunk love story' or 'A wuxia adventure'\n") + "\n")

        for _attempt in range(20):
            raw_idea = d.ask("> ")
            if raw_idea and raw_idea.strip():
                break
            d.write(_("Please share some thoughts to begin.") + "\n")
        else:
            raise CoCreationAborted()

        self._messages.append({"role": "user", "content": raw_idea.strip()})

    # ── Step 2 ──────────────────────────────────────────────────

    def _step2_questioning(self) -> None:
        """Multi-turn Q&A loop with LLM.

        LLM asks questions about 5 dimensions. User responds.
        Loop exits when user types '开始'/'go' or equivalent.
        """
        d = self._ui
        d.write("\n")
        d.write("━" * 50 + "\n")
        d.write(_("[Q&A Phase]") + "\n")
        d.write(_("I'll ask a few questions to understand the story you want.\nWhen you're ready, type 'go' to generate the story setup.\nType 'quit' to return to the main menu.\n") + "\n")

        if get_current_lang() == "zh-CN":
            START_KEYWORDS = {"开始", "开始吧", "可以", "好的", "行", "ok", "OK", "yes"}
            QUIT_KEYWORDS = {"不玩了", "退出", "quit", "exit", "q"}
        else:
            START_KEYWORDS = {"go", "start", "begin", "yes", "ok", "OK", "ready", "开始"}
            QUIT_KEYWORDS = {"quit", "exit", "q", "stop", "abort", "不玩了", "退出"}
        MAX_QNA_ROUNDS = 15

        for _round in range(MAX_QNA_ROUNDS):
            d.write(_("Thinking..."))
            try:
                response = self._api.chat(self._messages)
            except Exception as e:
                d.show_error(_("API call failed: {error}").format(error=e))
                choice = d.ask(_("[R]etry / [M]enu: "))
                if choice.upper() == 'M':
                    raise CoCreationAborted()
                continue

            self._messages.append({"role": "assistant", "content": response})
            d.write(f"\n{response}\n\n")

            user_input = d.ask(
                _("Your answer (or type 'go'/'quit')> ")
            ).strip()

            if not user_input:
                continue

            if user_input in START_KEYWORDS:
                d.write("\n")
                break

            if user_input in QUIT_KEYWORDS:
                confirm = d.ask(_("Abort co-creation and return to menu? (y/n): "))
                if confirm.lower() in ("y", "yes", "是"):
                    raise CoCreationAborted()
                continue

            self._messages.append({"role": "user", "content": user_input})
        else:
            raise CoCreationAborted()

    # ── Step 3 ──────────────────────────────────────────────────

    def _step3_generate_all(self) -> CoCreationResult:
        """Single LLM call → parse all three blocks → validate.

        Returns:
            CoCreationResult ready for GameLoop.

        Raises:
            CoCreationAborted: If user aborts after retry exhaustion.
        """
        var_names = self._build_var_names_hint()
        gen_prompt = GENERATE_ALL_PROMPT.format(variable_names=var_names)
        self._messages.append({"role": "user", "content": gen_prompt})

        self._ui.write(_("Weaving your story world..."))
        response = self._generate_with_retry()
        self._messages.append({"role": "assistant", "content": response})

        blocks = CoCreateParser.split_blocks(response)

        story_config = self._parse_story_config_with_retry(blocks["story_config"])
        # Refresh blocks after potential retry — retry may have generated
        # a new full response with updated content for all three sections.
        blocks = CoCreateParser.split_blocks(self._messages[-1]["content"])
        variables = self._parse_variables_with_retry(blocks["variables"])
        blocks = CoCreateParser.split_blocks(self._messages[-1]["content"])
        outline_nodes = self._parse_outline_with_retry(blocks["outline"])

        var_names_list = [v["name"] for v in variables]
        outline_errors = CoCreateParser.validate_outline(
            outline_nodes, var_names_list
        )
        if outline_errors:
            outline_nodes = self._retry_outline_validation(
                outline_errors, var_names_list
            )

        story_config["variables"] = variables
        outline_text = CoCreateParser.format_outline(outline_nodes)

        return CoCreationResult(
            story_config=story_config,
            outline_text=outline_text,
            outline_nodes=outline_nodes,
        )

    def _build_var_names_hint(self) -> str:
        return "由你根据故事设计（≤3个，≤2 numeric + ≤1 string/list）"

    def _generate_with_retry(self) -> str:
        """Call LLM for generation. Handle API errors."""
        d = self._ui
        for _retry in range(10):
            try:
                return self._api.chat(self._messages)
            except Exception as e:
                d.show_error(_("Generation failed: {error}").format(error=e))
                choice = d.ask(_("[R]etry / [M]enu: "))
                if choice.upper() == 'M':
                    raise CoCreationAborted()
        raise CoCreationAborted()

    def _parse_story_config_with_retry(self, text: str) -> dict:
        return self._retry_block(
            text=text,
            block_name="story_config",
            parse_fn=CoCreateParser.parse_story_config,
            validate_fn=lambda d: (
                [] if d.get("tier") in {"short", "medium", "long"}
                else ["tier must be short/medium/long"]
            ),
        )

    def _parse_variables_with_retry(self, text: str) -> list[dict]:
        return self._retry_block(
            text=text,
            block_name="variables",
            parse_fn=CoCreateParser.parse_variables,
            validate_fn=CoCreateParser.validate_variables,
        )

    def _parse_outline_with_retry(self, text: str) -> list[dict]:
        return self._retry_block(
            text=text,
            block_name="outline",
            parse_fn=CoCreateParser.parse_outline,
            validate_fn=lambda nodes: (
                [] if nodes else ["No nodes found"]
            ),
        )

    def _retry_outline_validation(
        self, errors: list[str], var_names: list[str]
    ) -> list[dict]:
        """Handle outline validation errors with retry.

        Uses a 2-level loop: inner loop auto-retries (MAX_RETRIES times),
        outer loop handles user-requested retry cycles (max 3 cycles).
        No recursion.
        """
        for _cycle in range(3):
            for attempt in range(MAX_RETRIES + 1):
                error_msg = "Outline errors: " + "; ".join(errors)
                self._messages.append(
                    {"role": "user",
                     "content": f"Outline has errors. {error_msg}\n"
                               f"Please fix and regenerate the outline block."}
                )
                self._ui.write(
                    _("Fixing {block}... (attempt {n})").format(block="大纲", n=attempt + 1)
                )
                response = self._generate_with_retry()
                self._messages.append({"role": "assistant", "content": response})

                blocks = CoCreateParser.split_blocks(response)
                try:
                    nodes = CoCreateParser.parse_outline(blocks["outline"])
                except ValueError as e:
                    errors = [str(e)]
                    continue

                errors = CoCreateParser.validate_outline(nodes, var_names)
                if not errors:
                    return nodes

            choice = self._ui.ask(
                _("Outline validation failed ({errors}).").format(errors="; ".join(errors))
                + " " + _("[R]etry / [M]enu: ")
            )
            if choice.upper() != 'R':
                raise CoCreationAborted()
            self._messages = self._messages[:-2]
        raise CoCreationAborted()

    def _retry_block(self, text, block_name, parse_fn, validate_fn):
        """Parse a block with retry on failure.

        Uses a 2-level loop: inner loop auto-retries (MAX_RETRIES times),
        outer loop handles user-requested retry cycles (max 3 cycles).
        No recursion.

        Raises:
            CoCreationAborted: If user aborts after retries.
        """
        for _cycle in range(3):
            for attempt in range(MAX_RETRIES + 1):
                try:
                    parsed = parse_fn(text)
                    errors = validate_fn(parsed)
                    if not errors:
                        return parsed
                except ValueError as e:
                    errors = [str(e)]

                if attempt < MAX_RETRIES:
                    error_msg = f"{block_name} errors: {'; '.join(errors)}"
                    self._messages.append(
                        {"role": "user",
                         "content": f"Previous {block_name} had errors. "
                                   f"{error_msg}\n"
                                   f"Please fix and regenerate all three sections."}
                    )
                    self._ui.write(
                        _("Fixing {block}... (attempt {n})").format(block=block_name, n=attempt + 1)
                    )
                    response = self._generate_with_retry()
                    self._messages.append(
                        {"role": "assistant", "content": response}
                    )
                    blocks = CoCreateParser.split_blocks(response)
                    text = blocks.get(block_name, "")
                    continue

            choice = self._ui.ask(
                _("{block} parsing failed ({errors}).").format(block=block_name, errors="; ".join(errors))
                + " " + _("[R]etry / [M]enu: ")
            )
            if choice.upper() != 'R':
                raise CoCreationAborted()
            self._messages = self._messages[:-2]
        raise CoCreationAborted()
