# Co-Creation Phase Implementation Design

> 2026-07-05 | Design — implement the co-creation (共创) phase to stable level
> Status: Approved | Next: writing-plans → implementation

## Motivation

The narrative loop (叙事循环) has undergone 6+ rounds of iteration with XML output format,
conversation-based architecture, and comprehensive testing. Meanwhile, the co-creation
phase — the story setup flow that feeds story_config + variables + outline into GameLoop —
has zero implementation. `main.py` bypasses it entirely with hardcoded `DEFAULT_STORY_CONFIG`
and `SAMPLE_OUTLINE`.

This design covers the full co-creation pipeline: user input → Q&A loop → single-turn
generation of story_config + variables + outline → validated output → GameLoop.

## Design Decisions

### 1. Single LLM Call for Generation (Steps 3/3.5/4 Merged)

Instead of three separate API calls (story_config → variables → outline), the LLM
outputs all three blocks in a single response:

```
=== story_config ===
...INI-style key: value pairs...

=== variables ===
...one variable per line...

=== outline ===
...[node] blocks with routes...
```

**Rationale**: 1 API call instead of 3 reduces latency; LLM designs variables and
outline with full knowledge of story_config in a single generation context.

### 2. Static Full-Context Window

The co-creation phase uses a simple static messages array — no sliding window, no
compression. The entire conversation (Q&A loop + generation request + generation
response) fits comfortably within token limits (~6-12 messages).

```
messages = [
  {role: "system",  content: CO_CREATE_SYSTEM_PROMPT},
  {role: "user",    content: raw_idea},
  {role: "assistant", content: LLM question},
  {role: "user",    content: user answer},
  ...  // Q&A loop
  {role: "user",    content: "Information is sufficient. Generate the full setup."},
  {role: "assistant", content: "=== story_config ===\n...\n=== variables ===\n...\n=== outline ===\n..."},
]
```

### 3. INI-Style Block Format

Block delimiters (`=== xxx ===`) are proven stable from narrative prompt testing.
Block internals use `key: value` format — simpler to parse than free text, less
error-prone than YAML/JSON for LLM generation.

### 4. Variable Cap: ≤3 (per 2026-07-05 spec)

Updated from the original 5-8 variable design. Hard constraints:
- ≤3 total variables
- ≤2 numeric (number)
- ≤1 label (string/list)
- Seed reference table in-prompt for genre guidance

### 5. Hybrid Quick-Start Mode

`python -m src.storyloom.main --quick` skips co-creation and uses hardcoded defaults.
Normal flow runs the full co-creation pipeline. Existing tests remain unchanged.

## Architecture

### New Module: `src/storyloom/co_create.py`

```
CoCreateFlow
  ├── run()                    # orchestrates full 5-step flow
  ├── _step1_get_idea()        # terminal input → raw_idea
  ├── _step2_questioning()     # multi-turn LLM Q&A loop
  └── _step3_generate_all()    # single LLM call → parse 3 blocks
       ├── _split_blocks()     # split by === xxx ===
       ├── _parse_story_config()
       ├── _parse_variables()
       ├── _validate_variables()
       ├── _parse_outline()
       └── _validate_outline()

CoCreateParser (stateless helpers)
  ├── parse_story_config(text) → dict
  ├── parse_variables(text)    → list[{name, type, initial}]
  ├── parse_outline(text)      → str (formatted for GameLoop)
  └── split_blocks(text)       → {story_config, variables, outline}
```

### Modified Files

| File | Change |
|------|--------|
| `src/storyloom/co_create.py` | **New** — full co-creation module |
| `src/storyloom/config.py` | Add `MAX_RETRIES`, `VARIABLE_CAP`, `VARIABLE_NUMERIC_CAP`, `VARIABLE_LABEL_CAP`, outline node ranges |
| `src/storyloom/main.py` | Wire co-creation into menu [1]; add `--quick` flag |
| `tests/test_co_create.py` | **New** — parser, validator, and flow tests |

### Unchanged Files

| File | Reason |
|------|--------|
| `src/storyloom/prompt_builder.py` | Narrative prompts — separate domain |
| `src/storyloom/context_manager.py` | Narrative sliding window — separate domain |
| `src/storyloom/xml_parser.py` | XML parsing — separate domain |
| `src/storyloom/game_loop.py` | Consumes story_config + outline_text — interface unchanged |
| `src/storyloom/api_client.py` | Generic — no changes needed |
| `src/storyloom/display.py` | Generic — no changes needed |
| All existing tests | Test narrative loop — unaffected |

## Data Flow

```
Step 1: Terminal input
  raw_idea: str

Step 2: Q&A loop (user + LLM)
  self._messages grows with user/assistant pairs
  Exit: user types "开始" or equivalent

Step 3: Single LLM generation
  Input:  self._messages + final user prompt
  Output: raw text with 3 === delimited blocks
    ├── === story_config ===  → parse → story_config dict
    ├── === variables ===     → parse + validate → variables list
    └── === outline ===       → parse + validate → outline_text str

Step 4: Return to caller
  CoCreationResult(story_config={...variables}, outline_text="...")
  → main.py passes to GameLoop(...)
```

## Output Formats

### story_config Block

```
=== story_config ===
genre: 赛博朋克冒险
tier: medium
setting: 2087年，新东京地下城，企业控制数据流
protagonist_name: 林焰
protagonist_identity: 前荒坂安全顾问，现自由佣兵
protagonist_traits: 冷静、道德灰色
tone: 黑暗冷峻
conflict: 一枚从企业R&D流出的神秘芯片正在寻找宿主
characters:
  耗子 | 地下情报贩子 | 亦敌亦友
  美智子 | 荒坂安全主管 | 前上司
```

**Fields**: 9 total. All required except `setting` may be empty for abstract settings.
`characters` supports multiple lines with `  name | role | relationship` format.

### variables Block

```
=== variables ===
体力: number, 初始 80
信任度: number, 初始 10
所属势力: string, 初始 自由佣兵
```

**Format**: `name: type, 初始 value`. One per line. list initial: `[]` or `元素1, 元素2`.

### outline Block (LLM Output Format)

```
=== outline ===
[node]
id: ch1_intro
title: 霓虹深渊
goal: 在地下城酒吧感受氛围，接到第一个线索
routes: → ch2_meeting

[node]
id: ch2_meeting
title: 地下交易
goal: 与耗子会面，获取芯片情报
routes:
  if 信任度 >= 30 → ch3_ally
  if 信任度 < 30 → ch3_betrayal

[node]
id: ch3_ally
title: 盟友之路
goal: 通过地下网络逃离追捕
routes: → ch4_safehouse

[node]
id: ch3_betrayal
title: 背叛之路
goal: 杀出重围，独自寻找答案
routes: → ch4_safehouse

[node]
id: ch4_safehouse
title: 安全屋
goal: 揭开芯片秘密（结局）
routes: （结局）
```

**Format**: `[node]` blocks. Each has `id`, `title`, `goal`, `routes`.
- `routes: → target` for unconditional progression
- `routes:` followed by indented `if condition → target` for branching
- Final node: `routes: （结局）` or empty

### outline_text (GameLoop-Compatible Format)

The parser converts `[node]` blocks into the format expected by `GameLoop` /
`PromptBuilder.build_round1()` (consistent with current `SAMPLE_OUTLINE`):

```
ch1_intro [active] — 霓虹深渊：在地下城酒吧感受氛围，接到第一个线索
  → ch2_meeting [pending]
ch2_meeting [pending] — 地下交易：与耗子会面，获取芯片情报
  ├→ ch3_ally [pending]
  └→ ch3_betrayal [pending]
ch3_ally [pending] — 盟友之路：通过地下网络逃离追捕
  → ch4_safehouse [pending]
ch3_betrayal [pending] — 背叛之路：杀出重围，独自寻找答案
  → ch4_safehouse [pending]
ch4_safehouse [pending] — 安全屋：揭开芯片秘密（结局）
```

**Conversion rules**:
- First node marked `[active]`, all others `[pending]`
- Each node: `node_id [status] — title：goal`
- Single route: `  → target [pending]`
- Multiple routes: `  ├→ target1 [pending]` / `  └→ target2 [pending]`
- Final node (no routes or `（结局）`): no route lines

## Validation Rules

### story_config

| # | Rule | Action |
|---|------|--------|
| a | 9 required fields all present | Reject if missing |
| b | tier ∈ {short, medium, long} | Reject if unknown |
| c | characters has ≥1 entry | Reject if empty |

### variables

| # | Rule | Action |
|---|------|--------|
| a | Name unique, non-empty, no `\n` or `:` | Reject |
| b | Type ∈ {number, string, list} | Reject |
| c | number initial ∈ [0, 100] | Reject |
| d | string initial non-empty | Reject |
| e | list elements are strings (empty list OK) | Reject |
| f | Total count ≤ 3 | Reject |
| g | number count ≤ 2, string+list count ≤ 1 | Reject |

### outline

| # | Rule | Action |
|---|------|--------|
| a | All route targets exist as node IDs | **Reject** |
| b | Final node has no branches (routes empty or `（结局）`) | **Reject** |
| c | Node count ≥ 1 | **Reject** |
| d | Route condition variables exist in variables | **Warn** (log only) |
| e | Node count in tier range (short 3-5 / medium 5-8 / long 8-15) | **Warn** (log only) |

## Retry Flow

```
_generate_with_retry(build_retry_prompt, parse_func, validate_func, block_name):
  for attempt in 0..MAX_RETRIES (2):
    response = api_client.chat(messages + retry_hint)
    try:
      parsed = parse_func(response)
      errors = validate_func(parsed)
      if not errors: return parsed
    except ParseError as e:
      errors = [str(e)]
    messages.append({role: "user", content: f"{block_name} errors: {'; '.join(errors)}"})
  
  # Exhausted → user decides
  choice = display.get_input(f"{block_name} failed. [R]etry / [M]enu: ")
  if choice.upper() == 'R':
    return _generate_with_retry(...)  # fresh retry cycle
  raise CoCreationAborted()
```

On retry, the LLM regenerates the full response (all three blocks) — it sees the
previous successful blocks in context and typically preserves them while fixing only
what was flagged. We re-parse all three blocks from the new response; previously-valid
blocks serve as in-context anchors for the retry.

If the same block fails repeatedly while others pass, we stop re-parsing the passing
blocks and only validate the failing one against the new response.

## Prompt Templates

### System Prompt (CO_CREATE_SYSTEM_PROMPT)

English, consistent with narrative prompts. Defines role, 5-dimension questioning
constraints, and output format specifications.

### Questioning Prompt

Per `prompt-design.md` §3.1. Focuses on 5 dimensions: setting, protagonist, tone,
conflict direction, story length. Prohibits plot spoilers.

### Generation Prompt

Single prompt requesting all three blocks. Includes:
- Conversation summary (full Q&A history in context)
- story_config format spec + field definitions
- variables format spec + ≤3 constraint + seed reference table
- outline format spec + `[node]` block structure + tier-specific node counts

## Config Constants (config.py additions)

```python
# ── Co-creation ──────────────────────────────────────────────────
MAX_RETRIES = 2

# Variable caps (per 2026-07-05 variable-cap spec)
VARIABLE_CAP = 3            # max total variables
VARIABLE_NUMERIC_CAP = 2    # max numeric (number) variables
VARIABLE_LABEL_CAP = 1      # max label (string/list) variables

# Outline node ranges by tier
OUTLINE_NODE_RANGES = {
    "short":  (3, 5),
    "medium": (5, 8),
    "long":   (8, 15),
}
```

## External Interface

```python
@dataclass
class CoCreationResult:
    story_config: dict   # includes 'variables' key
    outline_text: str    # formatted outline, ready for GameLoop

class CoCreateFlow:
    def __init__(self, api_client: ApiClient, display: Display):
        ...

    def run(self) -> CoCreationResult:
        """Run full co-creation flow. May raise CoCreationAborted."""
        ...
```

## Test Plan

### Unit Tests (`tests/test_co_create.py`) — No API calls

| Class | Tests |
|-------|-------|
| `TestParseStoryConfig` | valid complete, missing field→error, characters multi-line, empty text→error |
| `TestParseVariables` | valid 3 vars (2num+1str), list type (empty+filled), illegal name chars→error, unknown type→error |
| `TestValidateVariables` | all pass, count>3→reject, num>2→reject, label>1→reject, num OOB→reject, string empty→reject, duplicate names→reject |
| `TestParseOutline` | valid branching, linear, empty→error, missing id→error |
| `TestValidateOutline` | all pass, target missing→reject, final node has routes→reject, zero nodes→reject, unknown var→warn |
| `TestSplitBlocks` | three blocks, missing block, mixed order, spurious delimiters |

### Integration Tests — Mock API

| Class | Tests |
|-------|-------|
| `TestCoCreateFlow` | run() e2e success, Q&A loop "开始" exit, Q&A loop "不玩了" exit, parse fail→retry→success, retry exhausted→user retry→success, retry exhausted→user menu→abort |

### Out of Scope

- Real LLM endpoint tests (slow/expensive/non-deterministic — reserved for manual comprehensive testing)
- Prompt correctness validation (belongs to prompt iteration workflow, not unit/integration tests)
- Existing test modifications (narrative loop tests unaffected)

## Non-Goals

- Save/load system (separate feature)
- Archive management UI (separate feature)
- Genre auto-detection (LLM infers in-prompt, no Python logic)
- Hardcoded variable templates (removed in 2026-07-04 variable system redesign)

## Impact Summary

- **New code**: ~500 lines (`co_create.py` parser + flow + prompts), ~300 lines (tests)
- **Modified code**: ~30 lines (`config.py`), ~40 lines (`main.py`)
- **Existing behavior**: Fully preserved (`--quick` flag = current hardcoded path)
- **API calls added**: 1 (generation) + N (Q&A loop, ~3-6 rounds)
