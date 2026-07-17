"""Build Round 1 and Round N prompt content for conversation-based architecture."""

from storyloom.config import (
    LINES_PER_ROUND_MIN,
    LINES_PER_ROUND_MAX,
    BRIDGE_POSITION_RATIO,
    MIN_TAIL_LINES,
    LANGUAGE_SEG_LIMITS,
)


ROUND1_TEMPLATE = """You are the narrative engine for a text adventure game. Generate the next interactive story segment based on the outline and current state.

# Output Format

Prefix every line with a line number: `001| `, `002| `, `003| ` ... incrementing continuously.
The program strips these prefixes before parsing — they are NOT part of the XML.
Start at 001 for this round.

Your output MUST be an XML document. Start with `<story>`, end with `</story>`.
Do NOT output markdown code fences, XML declarations, or any text outside the XML.

## Structure

001| <story>
002| <seg>narration text</seg>
003| <seg>narration text</seg>
004| ...
005| <!-- pre-bridge local branch (merges back). opt with no branch stays on main path -->
006| <choice id="minor">
007|   <opt key="1" branch="path_a">takes a branch</opt>
008|   <opt key="2">stays on main</opt>
009| </choice>
010| <branch name="path_a">
011| <seg>local variant — merges back after</seg>
012| </branch>
013| <!-- main interaction -->
014| <choice id="variable_name">
015|   <opt key="1" branch="outcome_a">option text</opt>
016|   <opt key="2" branch="outcome_b">option text</opt>
017| </choice>
018| <set var="variable" op="operation" val="value" if="condition"/>
019| <checkpoint node="node_id" summary="summary text">
020|   <route if="condition" target="target_node"/>
021| </checkpoint>
022| <bridge/>
023| <!-- after bridge: narrative only, selected by current_branch -->
024| <branch name="outcome_a">
025| <seg>outcome narration</seg>
026| ...
027| </branch>
028| <branch name="outcome_b">
029| <seg>outcome narration</seg>
030| ...
031| </branch>
032| </story>

## Elements

**Line numbers** — `NNN| ` prefix on every line, zero-padded to 3 digits. Increment each line. Not part of the XML.

**<seg>** — A narrative segment. The basic unit of the story — a single beat of narration or dialogue. One thing per segment.

**<choice id="variable_name">** — Player choice. Contains 2-4 `<opt>` elements with `key` (number), `branch` (optional, assigned to `current_branch`), and `if` (optional, availability condition).

**<set>** — State change. Modifies a state variable. `var`, `op`, `val` required. `if` (optional): conditional execution.

**<checkpoint>** — Key story node and save point. Appears 0-1 times. Always a direct child of `<story>`. Records outline progress with a `summary`. May contain `<route>` elements for outline branching.

**<bridge/>** — Self-closing. Always a direct child of `<story>`. Exactly ONCE per output. The signal point where the program triggers the next API call. Divides output into interactive zone (before) and narrative zone (after).

**<branch name>** — Branch narrative container. Before bridge: local branches that merge back. After bridge: key branches selected by `current_branch`. `name` is matched against `current_branch`.

## Format Example

Below is a format example (content is a short fictional fantasy story in English):

001| <story>
002| <seg>Snow fell on the empty road.</seg>
003| <seg>Kael stamped the snow from his boots.</seg>
004| <seg>He pushed through the heavy oak door.</seg>
005| <seg>Innkeeper: Room for the night?</seg>
006| <choice id="inn_choice">
007|   <opt key="1" branch="take_room">Take a room</opt>
008|   <opt key="2">Just a drink</opt>
009| </choice>
010| <branch name="take_room">
011| <seg>A key slid across the counter.</seg>
012| </branch>
013| <seg>A stranger sat alone at the corner table.</seg>
014| <seg>Stranger: You're the one I've been waiting for.</seg>
015| <seg>Stranger: Word is you handle things quietly.</seg>
016| <choice id="approach">
017|   <opt key="1" branch="accept">I'm listening</opt>
018|   <opt key="2" branch="decline">Not interested</opt>
019| </choice>
020| <set var="reputation" op="+" val="5" if="approach==1"/>
021| <checkpoint node="ch2_meeting" summary="A stranger made contact at the inn.">
022|   <route if="approach==1" target="ch3_job"/>
023|   <route if="approach==2" target="ch3_alone"/>
024| </checkpoint>
025| <bridge/>
026| <branch name="accept">
027| <seg>The stranger leaned closer.</seg>
028| <seg>Stranger: There's a shipment. Tomorrow night. Old pass.</seg>
029| <seg>Stranger: Payment on delivery. Half up front.</seg>
030| </branch>
031| <branch name="decline">
032| <seg>The stranger shrugged.</seg>
033| <seg>Stranger: Suit yourself. But you'll be back.</seg>
034| </branch>
035| </story>
(This is a format example ONLY. Your output is an entirely new story segment.)

# Core Rules

**Segment Format**
- Each `<seg>` is EITHER narration OR dialogue.
- Narration: one scene per segment. Short — a single observation, action, or beat.
- Dialogue: `Name: text` format, no quotation marks. One line per segment.
- Put character actions, expressions, and tone in separate narration segments.
- Use actual character names in dialogue.

**Line Count & Bridge Position**
- **Output {MIN_LINES}-{MAX_LINES} total lines.** The format example is deliberately short (35 lines) to show structure only — your output MUST reach {MIN_LINES}-{MAX_LINES}.
- Place `<bridge/>` roughly {BRIDGE_PCT:.0f}% through — about 3/4 of lines before, 1/4 after.
- Each post-bridge `<branch>` must span at least {MIN_TAIL} lines.
- Post-bridge content is selected by `current_branch`: use `<branch>` containers for multiple possible paths, bare `<seg>` for a single path.

**Choice → current_branch**
- `<opt branch="X">` sets `current_branch = X`. Branch selection is based on `current_branch`: `<branch name="X">` will match.
- Reference the choice in conditions using its `id` with the `key` number: `variable_name==1`.
- Conditions support `and` / `or` (max one combinator) and reference variables from "Current State".

**Set — State Changes**
- `var` MUST use the exact names from "Current State" below. Do NOT invent, translate, or substitute them.
- number: `op="+"` / `op="-"` / `op="="` with `val` as the number; string: `op="="`.
- Condition syntax: same as Choice above.

**Checkpoint**
- Copy the `node` attribute verbatim from the outline — exact character-for-character match.
  Outline has `ch2_confrontation` → write `node="ch2_confrontation"`.
- Copy `<route>` `target` attributes verbatim from outline node IDs.

**XML Rules**
- Match every opening tag with a closing tag. Use `/>` for self-closing elements.
- Wrap attribute values in double quotes.
- Escape `<` `>` `&` in text as `&lt;` `&gt;` `&amp;`. Example: "R&D" → "R&amp;D".

**Prohibited**
- `<bridge/>` count not equal to 1.
- `<choice>`, `<set>`, or `<checkpoint>` after bridge.
- More than one `<checkpoint>`.
- Outputting anything outside the XML document (markdown fences, comments, explanatory text).
- `<checkpoint>` `node` or `<route>` `target` not matching an outline node ID exactly.
- `<set>` `var` referencing a variable not listed in "Current State".
- Dialogue with quotation marks, pronouns as character names, or inline action descriptions.
- Addressing the player directly ("You choose...", "What do you do?").

# Quality Requirements

One thing per segment. Alternate dialogue and narration. Make each branch narratively distinct. Create suspense after bridge.

Rough guide: ~lines 001-{REF_PRE} before bridge + ~{REF_SINGLE} after (single path) or ~{REF_HALF} per branch-tail.

# Story Context
**Language:** {LANGUAGE}
**Seg limits:** narration ≤{NARR_LIMIT} characters, dialogue ≤{DIAL_LIMIT} characters
**Background:** {background}
**Protagonist:** {protagonist}
**Tone:** {tone}
**Conflict:** {conflict}
**Characters:**
{characters}

**Outline:**
{outline_text}

**Active Node:** {active_node} — {node_goal}

**Current State:**
{state_vars_text}

Output {MIN_LINES}-{MAX_LINES} total lines. Exactly one `<bridge/>`. Less is fine — do not pad to hit the upper bound.
The active node indicates the current direction; decide whether to complete it this round.

(This is the start of the whole story.)"""


class PromptBuilder:
    """Build prompt content for conversation-based architecture.

    Round 1: Full format spec + story context + format example.
    Round N: Lightweight context (progress, state, bridge_text, errors).
    """

    @staticmethod
    def build_round1(
        story_config: dict,
        outline_text: str,
        current_node: str,
        goal: str,
        state_vars: dict[str, int | str],
    ) -> str:
        """Build Round 1 prompt (permanent anchor).

        Args:
            story_config: Story configuration dict.
            outline_text: Formatted outline tree text.
            current_node: Current outline node ID.
            goal: Current node narrative goal.
            state_vars: Current state variable values (new game or loaded).

        Returns:
            Full Round 1 prompt string.
        """
        language = story_config.get("language", "zh-CN")
        limits = LANGUAGE_SEG_LIMITS.get(language, LANGUAGE_SEG_LIMITS["zh-CN"])
        narr_limit = limits["narration"]
        dial_limit = limits["dialogue"]

        state_vars_text = PromptBuilder._format_current_state(
            state_vars, story_config.get("variables", [])
        )

        # Build protagonist line
        name = story_config.get("protagonist_name", "")
        identity = story_config.get("protagonist_identity", "")
        traits = story_config.get("protagonist_traits", "")
        protagonist = name
        if identity:
            protagonist += f"，{identity}"
        if traits:
            protagonist += f"。{traits}"

        # Build background line
        genre = story_config.get("genre", "")
        setting = story_config.get("setting", "")
        background = f"{genre} · {setting}" if genre and setting else genre or setting

        # Reference guides for bridge position
        bridge_pct = BRIDGE_POSITION_RATIO * 100
        ref_pre = int(LINES_PER_ROUND_MAX * BRIDGE_POSITION_RATIO)
        ref_single = LINES_PER_ROUND_MAX - ref_pre
        ref_half = ref_single // 2

        return ROUND1_TEMPLATE.format(
            MIN_LINES=LINES_PER_ROUND_MIN,
            MAX_LINES=LINES_PER_ROUND_MAX,
            BRIDGE_PCT=bridge_pct,
            MIN_TAIL=MIN_TAIL_LINES,
            REF_PRE=ref_pre,
            REF_SINGLE=ref_single,
            REF_HALF=ref_half,
            LANGUAGE=language,
            NARR_LIMIT=narr_limit,
            DIAL_LIMIT=dial_limit,
            background=background,
            protagonist=protagonist,
            tone=story_config.get("tone", ""),
            conflict=story_config.get("conflict", ""),
            characters=story_config.get("characters", ""),
            outline_text=outline_text,
            state_vars_text=state_vars_text,
            active_node=current_node or "(start)",
            node_goal=goal or "Begin the story from the active node.",
        )

    @staticmethod
    def build_round_n(
        current_node: str,
        goal: str,
        completed_nodes: list[str],
        state_vars: dict[str, int | str],
        bridge_text: str,
        compressed_summaries: list[str] | None = None,
        rejected_changes: list[str] | None = None,
        format_error: str | None = None,
    ) -> str:
        """Build Round N context message (N >= 2).

        Args:
            current_node: Current outline node ID.
            goal: Current node narrative goal.
            completed_nodes: List of completed node IDs.
            state_vars: Current state variable values.
            bridge_text: Plain text from last round's bridge tail.
            compressed_summaries: Checkpoint summaries from compressed rounds.
            rejected_changes: Rejected state change descriptions.
            format_error: Format error hint from last round.

        Returns:
            Round N context string for user message.
        """
        parts = []

        # Progress
        parts.append(f"Current node: {current_node} — {goal}")
        if completed_nodes:
            parts.append(f"Completed nodes: {', '.join(completed_nodes)}")

        # Compressed summaries
        if compressed_summaries:
            parts.append("\nCompleted chapter summaries:")
            for s in compressed_summaries:
                parts.append(f"- {s}")

        # State snapshot
        parts.append("\nCurrent state:")
        for name, value in state_vars.items():
            parts.append(f"  {name}: {value}")

        # Rejected changes feedback
        if rejected_changes:
            parts.append("\nRejected state changes from last round:")
            for rc in rejected_changes:
                parts.append(f"  - {rc}")

        # Format error correction
        if format_error:
            parts.append(
                f"\nFormat reminder: last round had format issues — {format_error}. "
                f"Please strictly follow the XML format specification."
            )

        # Bridge text
        parts.append(f"\nLast round ending:\n{bridge_text}")

        return "\n".join(parts)

    @staticmethod
    def build_adventure_log_prompt(
        story_config: dict,
        state_vars: dict,
        checkpoint_summaries: list[str],
        checkpoint_history: list[dict],
    ) -> str:
        """Build adventure log prompt per prompt-design.md section 5.2.

        This is an independent LLM call -- not part of the narrative loop.

        Args:
            story_config: Story configuration dict.
            state_vars: Current state variables.
            checkpoint_summaries: Accumulated checkpoint summary strings.
            checkpoint_history: Structured checkpoint records
                                [{node, title, summary, round}].

        Returns:
            Prompt string for adventure log generation.
        """
        story_label = story_config.get("label", "Untitled Adventure")
        language = story_config.get("language", "zh-CN")

        # Build chapter sections from history
        chapter_sections = []
        for i, cp in enumerate(checkpoint_history, 1):
            title = cp.get("title", f"Chapter {i}")
            summary = cp.get("summary", "")
            chapter_sections.append(
                f"### Chapter {i}: {title}\n"
                f"(Expand based on this summary: {summary})"
            )
        chapters_text = "\n\n".join(chapter_sections) if chapter_sections else "(No chapter records)"

        # Format state vars
        state_lines = []
        for name, value in state_vars.items():
            state_lines.append(f"- {name}: {value}")
        state_text = "\n".join(state_lines) if state_lines else "(No state variables)"

        prompt = f"""You are an adventure log author. Write a player-facing recap for a completed text adventure game.

Use Markdown format. Write in the story's language ({language}).

## Adventure Recap: {story_label}

{chapters_text}

## Ending
(Write a warm, satisfying conclusion based on the chapter summaries above.)

## Final State
{state_text}
(For each variable, write a brief one-sentence reflection, e.g. "Health: 25 — battered and bruised, but still standing.")

Requirements:
- Address the player directly ("You chose...", "In the end you...")
- Plain text only, no XML or block separators
- 500-1000 words"""

        return prompt

    @staticmethod
    def _format_current_state(
        state_vars: dict[str, int | str],
        variables: list[dict],
    ) -> str:
        """Format current state values for prompt display.

        Uses *variables* only for type lookup (number → ``/ 100`` suffix).
        Values come from *state_vars* — always the actual runtime values.
        """
        var_types = {v["name"]: v.get("type", "") for v in variables}
        lines = []
        for name, value in state_vars.items():
            if var_types.get(name) == "number":
                lines.append(f"{name}: {value} / 100")
            else:
                lines.append(f"{name}: {value}")
        return "\n".join(lines)
