"""Co-creation phase: user input → Q&A loop → story setup generation."""
import re
from dataclasses import dataclass, field
from string import Template

from storyloom.io.api_client import ApiClient, ApiError
from storyloom.i18n import _, get_current_lang
from storyloom.config import (
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

            if var_type not in ("number", "string"):
                raise ValueError(
                    f"Unknown type '{var_type}' for variable '{name}'. "
                    f"Must be number or string."
                )

            if var_type == "number":
                try:
                    initial = int(raw_initial)
                except ValueError:
                    raise ValueError(
                        f"Number variable '{name}' initial value "
                        f"'{raw_initial}' is not an integer."
                    )
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
        string_count = sum(1 for v in variables if v["type"] == "string")

        if num_count > VARIABLE_NUMERIC_CAP:
            errors.append(
                f"Numeric variables ({num_count}) exceed maximum "
                f"{VARIABLE_NUMERIC_CAP}"
            )
        if string_count > VARIABLE_LABEL_CAP:
            errors.append(
                f"String variables ({string_count}) exceed maximum "
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
        "example_variables": (
            "体力: number, 80\n"
            "信任度: number, 10\n"
            "所属势力: string, 自由佣兵"
        ),
        "example_branch_var": "信任度",
        "example_goal": (
            "在霓虹深渊酒吧，情报贩子向主角透露了一枚神秘芯片的存在。"
            "通过隐藏终端查询，发现芯片来自企业研发部门的绝密项目，"
            "多个势力正在逼近。"
            "主角必须决定是深入调查还是暂避锋芒——时间不多了。"
        ),
    },
    "en": {
        "instruction": (
            "The user's language is English (en). "
            "Conduct the Q&A conversation in English. "
            "All questions, example answers, and the story title (label) must be in English."
        ),
        "label_hint": "{unique story identifier for save files}",
        "example_variables": (
            "Stamina: number, 80\n"
            "Trust: number, 10\n"
            "Faction: string, Freelancer"
        ),
        "example_branch_var": "Trust",
        "example_goal": (
            "At the Neon Abyss bar, a fixer tips off the protagonist about a mysterious "
            "data chip. A search through a hidden terminal reveals the chip is from a "
            "top-secret corporate R&D project, and multiple factions are already closing "
            "in. The protagonist must decide whether to dig deeper or lie low — time is "
            "running out."
        ),
    },
}

# ── Prompt Templates ────────────────────────────────────────────────

CO_CREATE_SYSTEM_PROMPT = Template("""You are a warm and perceptive story co-creation partner. Your task is purely information gathering through conversation — NOT story generation. After our conversation, a separate step will use our discussion as source material to generate the story setup.

$language_instruction

# Questioning Phase

Ask one question at a time. Here are some dimensions to explore — use them as a guide, not a checklist. Do NOT reveal specific plot events or spoil story content:
- Story length — ask whether the user wants $story_length_hint key chapters.
- World setting (era, location, tech/magic level, society)
- Protagonist (name, gender, identity, personality traits, background)
- Story tone (dark/light, epic/personal, serious/humorous)
- Conflict direction (core tension — describe it as a question the story explores)

**After each question, offer 2-3 example answers as numbered suggestions** — these help the user express themselves, but they are free to write their own answer. Format:
[1] example answer one
[2] example answer two
[3] example answer three
$own_answer_hint

# Important Rules

- Do NOT generate story content, narrative, or outlines during this phase. Your only job is to ask questions and understand the player's preferences.
- There is no fixed number of questions — continue the conversation naturally. The player decides when to move to generation.
- Do NOT summarize or conclude the conversation on your own. Keep asking until the player signals they are ready.

Show genuine curiosity about the user's choices. Acknowledge their previous answer before asking the next question — this makes the conversation feel natural, not like a form.""")


CO_CREATE_GENERATION_PROMPT = Template("""Based on our conversation above, generate the complete story setup.

# Rules

## Variables
- ≤3 variables total. ≤2 numeric (number), ≤1 string.
- Numeric: range [0, 100]. Use for health, trust, sanity, etc.
- String: for status markers, faction affiliation, etc.
- Fewer is better. Only create variables that will drive branching or gate choices.

Genre seed reference (adopt or adapt based on the story; replace if unsuitable):
  Romance → affection
  Mystery → clues_progress
  Cyberpunk → implant_integrity
  Wuxia → inner_power
  Horror → sanity

## Outline
- Node count by tier: $node_count_hint. Your outline must match your declared tier.
- Each node's goal is a chapter arc, not a scene. It unfolds over several rounds. 2-4 sentences.
- Branches use `if {condition} → {target_node}`. Conditions may only reference declared variables.
- Final node is the ending — leave its `routes:` empty (no text after the colon). The system detects endings by empty routes, not by any special keyword.
- node_id format: ch{number}_{english_abbreviation}

# Output Format

Your response must contain exactly three blocks separated by `===` markers.
Output ONLY the blocks — no markdown headings, no commentary before or after.

=== story_config ===
genre: {free text, e.g. "cyberpunk adventure", "historical mystery"}
tier: {short / medium / long}
label: $label_hint
language: $language
setting: {a story blurb that hooks the reader — introduce the world, protagonist, and what's at stake}
protagonist_name: {name}
protagonist_identity: {one sentence}
protagonist_traits: {2-3 key traits}
tone: {e.g. "dark and gritty", "light and humorous"}
conflict: {one sentence, core tension}
characters:
  {name} | {role} | {relationship to protagonist}
  (at least 1)

=== variables ===
$example_variables

=== outline ===
[node]
id: ch1_intro
title: {node title}
goal: $example_goal
routes: → ch2_next

[node]
id: ch2_next
title: {node title}
goal: {narrative goal}
routes:
  if $example_branch_var >= 30 → ch3_path_a
  if $example_branch_var < 30 → ch3_path_b

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
""")


# ── Exceptions ──────────────────────────────────────────────────────

@dataclass
class CoCreateError(Exception):
    """Serious error during co-creation — UI can retry or quit.

    Mirrors the narrative phase's ``{"type": "error"}`` event pattern.
    ``phase`` tells the UI which retry method to call:
    ``"send"`` → ``CoCreateFlow.retry_send()``
    ``"generate_api"`` → ``CoCreateFlow.retry_generate()``
    ``"generate_parse"`` → ``CoCreateFlow.retry_generate()`` (adds correction)
    """
    phase: str
    message: str


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
        node_count_hint = " / ".join(
            f"{tier} {lo}-{hi}" for tier, (lo, hi) in OUTLINE_NODE_RANGES.items()
        )
        story_length_hint = " / ".join(
            f"{tier} ~{hi}" for tier, (lo, hi) in OUTLINE_NODE_RANGES.items()
        )
        return CO_CREATE_SYSTEM_PROMPT.substitute(
            language_instruction=meta["instruction"],
            own_answer_hint=_("(or write your own answer)"),
            node_count_hint=node_count_hint,
            story_length_hint=story_length_hint,
        )

    @staticmethod
    def _build_generation_prompt() -> str:
        """Build the language-aware generation prompt (user message)."""
        lang = get_current_lang()
        if lang not in SUPPORTED_LANGUAGES:
            lang = DEFAULT_LANGUAGE
        meta = _LANG_META.get(lang, _LANG_META[DEFAULT_LANGUAGE])
        node_count_hint = " / ".join(
            f"{tier} {lo}-{hi}" for tier, (lo, hi) in OUTLINE_NODE_RANGES.items()
        )
        return CO_CREATE_GENERATION_PROMPT.substitute(
            label_hint=meta["label_hint"],
            language=lang,
            node_count_hint=node_count_hint,
            example_variables=meta["example_variables"],
            example_goal=meta["example_goal"],
            example_branch_var=meta["example_branch_var"],
        )

    def __init__(self, api_client: ApiClient):
        self._api = api_client
        self._messages: list[dict] = [
            {"role": "system", "content": self._build_system_prompt()}
        ]
        self._phase: str = "init"
        self._result: CoCreationResult | None = None
        self._retry_state: tuple[str, str] | None = None
        # ("send", user_input) | ("generate_api", "") | ("generate_parse", error_desc)

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
        self._retry_state = None

    def send(self, user_input: str) -> str:
        """Send user input to LLM, return reply text.

        Pure message forward — no keyword detection, no phase
        transitions.  The UI decides when to call generate() or abort().

        On API failure, raises ``CoCreateError`` (phase="send") and
        saves ``_retry_state`` so the UI can call ``retry_send()``.

        Args:
            user_input: The user's message text.  Must be non-empty.

        Returns:
            LLM reply text.

        Raises:
            RuntimeError: If called before start() or after abort.
            ValueError: If user_input is empty.
            CoCreateError: On API failure (UI can retry with retry_send()).
        """
        if self._phase == "init":
            raise RuntimeError("call start() first before send()")
        if self._phase == "aborted":
            raise RuntimeError("co-creation was aborted")

        stripped = user_input.strip()
        if not stripped:
            raise ValueError("user input cannot be empty")

        self._messages.append({"role": "user", "content": stripped})

        try:
            response = self._api.chat(self._messages)
        except ApiError as e:
            # Save retry state — user message stays in _messages for retry
            self._retry_state = ("send", stripped)
            raise CoCreateError(
                phase="send",
                message=f"API call failed: {e}",
            ) from e

        self._messages.append({"role": "assistant", "content": response})
        self._phase = "awaiting_answer"
        return response

    def retry_send(self) -> str:
        """Re-attempt the last failed ``send()`` API call.

        The user message is still in ``_messages`` (not popped on failure),
        so we just re-call the API with the same messages array.

        Returns:
            LLM reply text.

        Raises:
            RuntimeError: If no failed send to retry.
            CoCreateError: If the API call fails again (keeps
                           ``_retry_state`` for another attempt).
        """
        if self._retry_state is None or self._retry_state[0] != "send":
            raise RuntimeError(
                "No failed send to retry — the last send() completed "
                "successfully or retry_send() was already called successfully."
            )
        try:
            response = self._api.chat(self._messages)
        except ApiError as e:
            raise CoCreateError(
                phase="send",
                message=f"API call failed: {e}",
            ) from e

        self._messages.append({"role": "assistant", "content": response})
        self._phase = "awaiting_answer"
        self._retry_state = None
        return response

    def generate(self) -> CoCreationResult:
        """Inject generation prompt, call LLM, parse and validate.

        Appends ``CO_CREATE_GENERATION_PROMPT`` as a user message, calls
        the API once, then parses the response.  On API failure or
        parse/validation failure, raises ``CoCreateError`` and saves
        ``_retry_state`` so the UI can call ``retry_generate()``.

        Returns:
            CoCreationResult with story_config, outline_text, outline_nodes.

        Raises:
            RuntimeError: If not in awaiting_answer phase.
            CoCreateError: On API or validation failure (UI can retry).
        """
        if self._phase != "awaiting_answer":
            raise RuntimeError(
                f"Cannot generate in phase: {self._phase}"
            )

        # Append generation prompt as user message
        gen_prompt = self._build_generation_prompt()
        self._messages.append({"role": "user", "content": gen_prompt})

        # API call (single attempt — no auto-retry)
        try:
            response = self._api.chat(self._messages)
        except ApiError as e:
            self._retry_state = ("generate_api", "")
            raise CoCreateError(
                phase="generate_api",
                message=f"Generation API call failed: {e}",
            ) from e

        self._messages.append({"role": "assistant", "content": response})

        # Parse once — on failure, save retry state for user to retry
        try:
            return self._parse_generation(response)
        except CoCreateError:
            raise  # re-raise (retry state already set by _parse_generation)
        except Exception as e:
            # Unexpected error during parsing — treat as parse failure
            self._retry_state = ("generate_parse", str(e))
            raise CoCreateError(
                phase="generate_parse",
                message=f"Parse failed: {e}",
            ) from e

    def _parse_generation(self, response: str) -> CoCreationResult:
        """Parse and validate a generation response.

        When validation fails, sets ``_retry_state`` and raises
        ``CoCreateError`` so the UI can call ``retry_generate()``.

        Returns:
            CoCreationResult on success.

        Raises:
            CoCreateError: On any parse or validation failure.
        """
        blocks = CoCreateParser.split_blocks(response)

        # story_config
        try:
            story_config = CoCreateParser.parse_story_config(
                blocks["story_config"]
            )
        except ValueError as e:
            self._retry_state = ("generate_parse", str(e))
            raise CoCreateError(
                phase="generate_parse",
                message=f"story_config error: {e}",
            ) from e

        # variables
        variables = CoCreateParser.parse_variables(blocks["variables"])
        var_errors = CoCreateParser.validate_variables(variables)
        if var_errors:
            err_text = "; ".join(var_errors)
            self._retry_state = ("generate_parse", err_text)
            raise CoCreateError(
                phase="generate_parse",
                message=f"Variables error: {err_text}",
            )

        # outline
        try:
            outline_nodes = CoCreateParser.parse_outline(blocks["outline"])
        except ValueError as e:
            self._retry_state = ("generate_parse", str(e))
            raise CoCreateError(
                phase="generate_parse",
                message=f"Outline parse error: {e}",
            ) from e

        var_names_list = [v["name"] for v in variables]
        outline_errors = CoCreateParser.validate_outline(
            outline_nodes, var_names_list
        )
        if outline_errors:
            err_text = "; ".join(outline_errors)
            self._retry_state = ("generate_parse", err_text)
            raise CoCreateError(
                phase="generate_parse",
                message=f"Outline validation error: {err_text}",
            )

        # All validations passed
        story_config["variables"] = variables
        outline_text = CoCreateParser.format_outline(outline_nodes)

        self._phase = "complete"
        self._retry_state = None
        self._result = CoCreationResult(
            story_config=story_config,
            outline_text=outline_text,
            outline_nodes=outline_nodes,
        )
        return self._result

    def retry_generate(self) -> CoCreationResult:
        """Re-attempt the last failed ``generate()``.

        For API failures (phase="generate_api"), re-sends the same
        messages array.  For parse/validation failures
        (phase="generate_parse"), appends a correction prompt before
        calling the API.

        Returns:
            CoCreationResult on success.

        Raises:
            RuntimeError: If no failed generation to retry.
            CoCreateError: If the API or parse fails again (keeps
                           ``_retry_state`` for another attempt).
        """
        if self._retry_state is None or self._retry_state[0] not in (
            "generate_api", "generate_parse"
        ):
            raise RuntimeError(
                "No failed generate to retry — the last generate() "
                "completed successfully, or retry_generate() was already "
                "called successfully."
            )

        phase, error_desc = self._retry_state

        # For parse failures, append correction prompt
        if phase == "generate_parse" and error_desc:
            self._messages.append({
                "role": "user",
                "content": (
                    f"Previous generation had errors: {error_desc}\n"
                    f"Please fix and regenerate all three sections."
                ),
            })

        # API call (single attempt)
        try:
            response = self._api.chat(self._messages)
        except ApiError as e:
            self._retry_state = ("generate_api", "")
            raise CoCreateError(
                phase="generate_api",
                message=f"Generation API call failed: {e}",
            ) from e

        self._messages.append({"role": "assistant", "content": response})

        # Parse — on failure, retry state is re-set by _parse_generation
        try:
            return self._parse_generation(response)
        except CoCreateError:
            raise
        except Exception as e:
            self._retry_state = ("generate_parse", str(e))
            raise CoCreateError(
                phase="generate_parse",
                message=f"Parse failed: {e}",
            ) from e
