"""Co-creation phase: user input → Q&A loop → story setup generation."""
import re
from dataclasses import dataclass, field
from string import Template

from storyloom.io.api_client import ApiClient
from storyloom.i18n import _, get_current_lang
from storyloom.config import (
    MAX_RETRIES,
    STORY_LABEL_MIN_CHARS,
    STORY_LABEL_MAX_CHARS,
    VARIABLE_CAP,
    VARIABLE_NUMERIC_CAP,
    VARIABLE_LABEL_CAP,
    OUTLINE_NODE_RANGES,
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
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
        r"^([^:]+):\s*(\S+),\s*(.+)$"
    )

    @staticmethod
    def parse_variables(text: str) -> list[dict]:
        """Parse variables block into list of {name, type, initial} dicts.

        Format: ``<name>: <type>, <value>`` (var names in story language).

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
                    f"Expected format: <name>: <type>, <value>"
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
                    if route_text:
                        # Single route on same line: → target
                        # (empty routes = ending node, detected by validate_outline)
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


# ── Language metadata for LLM instructions (English — not user-visible) ──

_LANG_META = {
    "zh-CN": {
        "instruction": (
            "The user's language is Chinese (zh-CN). "
            "Conduct the Q&A conversation in Chinese. "
            "All questions, example answers, and the story title (label) must be in Chinese."
        ),
        "label_hint": "{a short Chinese title, 5-15 characters, used for save files}",
    },
    "en": {
        "instruction": (
            "The user's language is English (en). "
            "Conduct the Q&A conversation in English. "
            "All questions, example answers, and the story title (label) must be in English."
        ),
        "label_hint": "{unique story identifier for save files}",
    },
}

# ── Prompt Templates ────────────────────────────────────────────────

CO_CREATE_SYSTEM_PROMPT = Template("""You are a warm and perceptive story co-creation partner. Your goal is to help the user discover the story they truly want to experience — by asking thoughtful questions, listening carefully, and guiding gently.

$language_instruction

# Questioning Phase

Ask one question at a time. Here are some dimensions to explore — use them as a guide, not a checklist. Do NOT reveal specific plot events or spoil story content:
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
$own_answer_hint
```

Show genuine curiosity about the user's choices. Acknowledge their previous answer before asking the next question — this makes the conversation feel natural, not like a form.""")


CO_CREATE_GENERATION_PROMPT = Template("""Based on our conversation above, generate the complete story setup.

Output ALL THREE sections below in order. Use EXACTLY the format shown.

## Section 1: story_config

```
=== story_config ===
genre: {free text, e.g. "cyberpunk adventure", "historical mystery"}
tier: {short / medium / long}
label: $label_hint
language: $language
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
- Fewer is better. Only create variables that will drive branching or gate choices.

Genre seed reference (adopt or adapt based on the story; replace if unsuitable):
  Romance → affection
  Mystery → clues_progress
  Cyberpunk → implant_integrity
  Wuxia → inner_power
  Horror → sanity

```
=== variables ===
体力: number, 80
信任度: number, 10
所属势力: string, 自由佣兵
```

## Section 3: outline

Design a directed graph of key story nodes. Rules:
- Node count by tier: short 3-5 / medium 5-8 / long 8-15
- Each node has a clear narrative goal
- Branches use `if {condition} → {target_node}`. Conditions may only reference declared variables.
- Final node is the ending — leave its `routes:` empty (no text after the colon). The system detects endings by empty routes, not by any special keyword.
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
goal: {narrative goal}
routes:
```

Output all three sections in a single response. Do not add commentary before or after.""")


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

    @staticmethod
    def _build_system_prompt() -> str:
        """Build the language-aware co-creation system prompt."""
        lang = get_current_lang()
        if lang not in SUPPORTED_LANGUAGES:
            lang = DEFAULT_LANGUAGE
        meta = _LANG_META[lang]
        return CO_CREATE_SYSTEM_PROMPT.substitute(
            language_instruction=meta["instruction"],
            own_answer_hint=_("(or write your own answer)"),
        )

    @staticmethod
    def _build_generation_prompt() -> str:
        """Build the language-aware generation prompt (user message)."""
        lang = get_current_lang()
        if lang not in SUPPORTED_LANGUAGES:
            lang = DEFAULT_LANGUAGE
        meta = _LANG_META[lang]
        return CO_CREATE_GENERATION_PROMPT.substitute(
            label_hint=meta["label_hint"],
            language=lang,
        )

    def __init__(self, api_client: ApiClient):
        self._api = api_client
        self._messages: list[dict] = [
            {"role": "system", "content": self._build_system_prompt()}
        ]
        self._phase: str = "init"
        self._result: CoCreationResult | None = None

    @property
    def messages(self) -> list[dict]:
        """Return the full co-creation conversation messages.

        Contains system prompt, Q&A turns, and (after generate() is
        called) the generation prompt and LLM response.
        """
        return list(self._messages)

    @property
    def phase(self) -> str:
        """Current phase: 'init' | 'awaiting_idea' | 'awaiting_answer'
           | 'complete' | 'aborted'."""
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

    def send(self, user_input: str) -> str:
        """Send user input to LLM, return reply text.

        Pure message forward — no keyword detection, no phase
        transitions.  The UI decides when to call generate() or abort().

        Args:
            user_input: The user's message text.  Must be non-empty.

        Returns:
            LLM reply text.

        Raises:
            RuntimeError: If called before start() or after abort.
            ValueError: If user_input is empty.
        """
        if self._phase == "init":
            raise RuntimeError("call start() first before send()")
        if self._phase == "aborted":
            raise RuntimeError("co-creation was aborted")

        stripped = user_input.strip()
        if not stripped:
            raise ValueError("user input cannot be empty")

        self._messages.append({"role": "user", "content": stripped})

        # API call with silent retry (up to 3 attempts)
        for attempt in range(3):
            try:
                response = self._api.chat(self._messages)
                break
            except Exception:
                if attempt == 2:
                    self._messages.pop()
                    raise RuntimeError(
                        f"API call failed after 3 retries"
                    )
                continue

        self._messages.append({"role": "assistant", "content": response})
        self._phase = "awaiting_answer"
        return response

    def generate(self) -> CoCreationResult:
        """Inject generation prompt, call LLM, parse and validate.

        Appends CO_CREATE_GENERATION_PROMPT as a user message, calls the
        API, then parses the response into story_config + variables +
        outline.  Auto-retries on API failure (3 attempts) and on
        parse/validation failure (MAX_RETRIES attempts).

        Returns:
            CoCreationResult with story_config, outline_text, outline_nodes.

        Raises:
            RuntimeError: If not in awaiting_answer phase.
            CoCreationAborted: If API or validation fails after all retries.
        """
        if self._phase != "awaiting_answer":
            raise RuntimeError(
                f"Cannot generate in phase: {self._phase}"
            )

        # Append generation prompt as user message
        gen_prompt = self._build_generation_prompt()
        self._messages.append({"role": "user", "content": gen_prompt})

        # API call with silent retry (up to 3 attempts)
        response = None
        for attempt in range(3):
            try:
                response = self._api.chat(self._messages)
                break
            except Exception:
                if attempt == 2:
                    raise CoCreationAborted()
                continue

        self._messages.append({"role": "assistant", "content": response})

        # Parse with auto-retry on validation failure
        for parse_attempt in range(MAX_RETRIES + 1):
            blocks = CoCreateParser.split_blocks(response)

            # story_config
            try:
                story_config = CoCreateParser.parse_story_config(
                    blocks["story_config"]
                )
            except ValueError as e:
                if parse_attempt < MAX_RETRIES:
                    response = self._retry_generation(
                        f"Previous story_config had errors: {e}"
                    )
                    continue
                raise CoCreationAborted()

            # variables
            variables = CoCreateParser.parse_variables(blocks["variables"])
            var_errors = CoCreateParser.validate_variables(variables)
            if var_errors:
                if parse_attempt < MAX_RETRIES:
                    response = self._retry_generation(
                        f"Previous variables had errors: "
                        f"{'; '.join(var_errors)}"
                    )
                    continue
                raise CoCreationAborted()

            # outline
            try:
                outline_nodes = CoCreateParser.parse_outline(blocks["outline"])
            except ValueError as e:
                if parse_attempt < MAX_RETRIES:
                    response = self._retry_generation(
                        f"Previous outline had errors: {e}"
                    )
                    continue
                raise CoCreationAborted()

            var_names_list = [v["name"] for v in variables]
            outline_errors = CoCreateParser.validate_outline(
                outline_nodes, var_names_list
            )
            if outline_errors:
                if parse_attempt < MAX_RETRIES:
                    response = self._retry_generation(
                        f"Outline has errors: "
                        f"{'; '.join(outline_errors)}"
                    )
                    continue
                raise CoCreationAborted()

            # All validations passed
            story_config["variables"] = variables
            outline_text = CoCreateParser.format_outline(outline_nodes)

            self._phase = "complete"
            self._result = CoCreationResult(
                story_config=story_config,
                outline_text=outline_text,
                outline_nodes=outline_nodes,
            )
            return self._result

        raise CoCreationAborted()

    def _retry_generation(self, error_desc: str) -> str:
        """Append a correction prompt and call the LLM again.

        Args:
            error_desc: Human-readable description of what was wrong.

        Returns:
            New LLM response string.

        Raises:
            CoCreationAborted: If the API call fails.
        """
        self._messages.append({
            "role": "user",
            "content": (
                f"{error_desc}\n"
                f"Please fix and regenerate all three sections."
            ),
        })
        try:
            response = self._api.chat(self._messages)
        except Exception:
            raise CoCreationAborted()
        self._messages.append({"role": "assistant", "content": response})
        return response
