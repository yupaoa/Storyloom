# Core Engine Completion Design — Save, Ending, Decoupling

> **术语说明**：本文撰写时使用了"前端/后端"术语。在 Storyloom 架构中，这对应"界面层/核心引擎"——Storyloom 是单体应用，非 client-server 架构。
>
> **Date**: 2026-07-06
> **Status**: Approved (revised after self-review)
> **Authority**: `docs/spec/exec-flow.md`, `docs/spec/block-spec.md`, `docs/spec/data-model.md`, `docs/spec/prompt-design.md`
>
> **Principle**: Spec documents are authoritative. Code adapts to match specs.

## §1 Scope

Four areas, all minimal-change:

1. **Save System** — new `SaveManager` module (save/load/delete/list)
2. **Ending Detection + Adventure Log** — `ending_flag` mechanism + independent LLM call per spec
3. **CoCreateFlow Decoupling** — `UiInterface` protocol so UI layer can implement its own UI
4. **Serialization** — `GameState.to_dict()` / `GameLoop.to_save_dict()` / `GameLoop.from_save_dict()`

Plus one prerequisite fix: add `label` to `story_config` (required for save file naming per spec).

Out of scope: main menu implementation (UI concern), Q-key ending (UI concern), option graying display (UI concern — `conditions` already exposed in events).

---

## §2 Save System

### 2.1 Prerequisite: `story_config.label`

Per `data-model.md` §3.1, save files are named after `story_config.label`. But `CoCreateParser.REQUIRED_CONFIG_FIELDS` does not include `label`. Fix:

1. Add `label` to `REQUIRED_CONFIG_FIELDS` in `CoCreateParser`
2. Add `label: {5-15 chars, Chinese, unique story identifier}` to the co-creation system prompt's `story_config` section
3. Validate: `STORY_LABEL_MIN_CHARS ≤ len(label) ≤ STORY_LABEL_MAX_CHARS` (5-15 chars per `config.py`)
4. Sanitize for filesystem: replace `/ \ : * ? " < > |` with `_`

### 2.2 New Module: `src/storyloom/core/save_manager.py`

```python
class SaveManager:
    def __init__(self, saves_dir: str = "saves") -> None

    def save(self, save_data: dict) -> None
        # Writes to saves/{label}.json (atomic: .tmp → os.replace)
        # save_data = GameLoop.to_save_dict()

    def load(self, label: str) -> dict
        # Reads saves/{label}.json, validates, returns save_data dict
        # Caller uses GameLoop.from_save_dict(data, api_client) to restore
        # Raises: FileNotFoundError, ValueError (corrupt save)

    def delete(self, label: str) -> bool
        # Deletes saves/{label}.json. Returns True if deleted.

    def list_saves(self) -> list[dict]
        # Scans saves/*.json, reads metadata from each
        # Returns [{ "label": str, "round_count": int, "created_at": str,
        #            "updated_at": str, "current_node": str }]
```

No LLM involvement. Pure file I/O. No Display dependency.

### 2.3 Save File Format

Per `data-model.md` §3.1 (authoritative):

```json
{
  "version": 1,
  "metadata": {
    "label": "...",
    "created_at": "...",
    "updated_at": "...",
    "round_count": 0
  },
  "config": {
    "temperature": null
  },
  "story_config": {
    "...": "...",
    "variables": [
      {"name": "体力", "type": "number", "initial": 80}
    ]
  },
  "state_vars": {
    "体力": 30
  },
  "outline": [
    {
      "node_id": "ch1_intro",
      "title": "序章",
      "goal": "主角抵达边陲小镇",
      "status": "completed",
      "branches": ["ch2_next"]
    }
  ],
  "progress": {
    "current_node": "ch2_next",
    "round_count": 5,
    "checkpoint_history": [
      {"node": "ch1_intro", "title": "序章", "summary": "...", "round": 3}
    ],
    "checkpoint_summaries": [
      "主角抵达边陲小镇，获得了第一条线索"
    ],
    "checkpoint_snapshots": {
      "ch1_intro": {"体力": 75, "线索": ["旧地图"]}
    }
  },
  "bridge_text": "..."
}
```

**Key clarifications** (from spec):
- `story_config.variables[].initial`: **original** initial value from co-creation, NOT current state. Restored GameState uses this for type definitions; actual state comes from `state_vars`.
- `outline[].status`: `"active"` | `"completed"` | `"pending"`. No separate `completed_nodes` list — derive from status field.
- `checkpoint_summaries`: `list[str]` — plain summary strings.
- `checkpoint_history`: `list[dict]` — structured records with `{node, title, summary, round}`.
- `checkpoint_snapshots`: `dict[str, dict]` — `{node_id: deep_copy(state_vars)}`. Phase 1 stores only, does not read back.

**Naming**: `story_config.label` → sanitize → `saves/{label}.json`. Duplicates get `_2`, `_3` suffix.

**Auto-save timing**: Only at checkpoint processing (`data-model.md` §3.2). Not every round.

**Atomic write**: Write to `{label}.tmp` → `os.replace(tmp, target)` (`data-model.md` §3.3).

### 2.4 Load Validation

Per `data-model.md` §3.4:

1. JSON parseable → else corrupt
2. `version` field exists and `== 1` → else corrupt
3. Required fields present: `story_config` (with `variables`), `state_vars`, `outline`, `progress` → else corrupt
4. `progress.current_node` exists in `outline[*].node_id` → else corrupt
5. Any validation fails → raise `ValueError` (caller deletes file, returns to menu)

### 2.5 Serialization Methods

**GameState.to_dict()** — serializes variable state only:

```python
def to_dict(self) -> dict:
    return {
        "state_vars": dict(self._state_vars),
    }
```

**GameState.from_dict()** — restores from save data with original story_config:

```python
@classmethod
def from_dict(cls, data: dict, story_config: dict) -> "GameState":
    """Restore GameState from save data.

    Args:
        data: The state_vars dict from save.
        story_config: The original story_config from save (preserves
                      variable definitions with original initial values).
    """
    gs = cls(story_config)         # Uses original variable definitions
    gs._state_vars = dict(data.get("state_vars", {}))
    return gs
```

**GameLoop.to_save_dict()** — assembles full save dict per §2.3 format:

```python
def to_save_dict(self) -> dict:
    """Produce complete save dict in data-model §3.1 format."""
    ...

@classmethod
def from_save_dict(
    cls, data: dict, api_client: ApiClient,
    display: Display | None = None,
) -> "GameLoop":
    """Restore GameLoop from save dict. Validates structure first."""
    ...
```

### 2.6 Outline Storage in GameLoop

**Problem**: GameLoop currently stores only `outline_text: str` (formatted). The formatted format (`ch1_intro [active] — title：goal`) is different from the `[node]` block format that `CoCreateParser.parse_outline()` can parse. So outline can't be round-tripped for save.

**Fix**: GameLoop stores structured outline alongside text:

```python
# GameLoop.__init__
self.outline_text = outline_text              # For PromptBuilder (existing)
self._outline_nodes: list[dict] = nodes       # For save serialization (new)
```

`nodes` comes from `CoCreateParser.parse_outline()` — which already runs during co-creation. Pass it through `CoCreationResult` → `GameLoop.__init__`.

Node dict format: `{id, title, goal, routes: [{condition, target}]}`. The `outline[].branches` in save format is derived from `routes[].target`.

### 2.7 `config.temperature`

Per spec, `config.temperature` is stored in save and restored. GameLoop stores the temperature from ApiClient:

```python
# GameLoop.__init__
self._temperature = getattr(api_client, 'temperature', None)
```

This goes into `to_save_dict()` → `config.temperature`. On restore, it's informational (spec says "模型以 .env 为准" — model comes from .env, not save).

### 2.8 `__init__.py` Exports

```python
from storyloom.core.save_manager import SaveManager
```

---

## §3 Ending Detection + Adventure Log

### 3.1 ending_flag

New field on GameLoop (not GameState — GameState manages variables only per current code structure):

```python
# GameLoop
ending_flag: bool = False
```

### 3.2 Detection Flow

In `continue_round_stream()`, during checkpoint processing (after XML parse, in Step 3 area):

```
parsed.checkpoint_node == "end"?
  → self.ending_flag = True
  → Mark node "end" as completed in _outline_nodes status
  → Store checkpoint_summaries entry
  → Store checkpoint_history entry (structured: {node, title, summary, round})
  → Store checkpoint_snapshots["end"] = deep_copy(state_vars)
  → Trigger auto-save (if SaveManager available)
  → Continue to bridge handling
```

### 3.3 Bridge Handling (Modified)

At bridge point in `continue_round_stream()` (after _emit_parsed yields segments):

```
if self.ending_flag:
    # Submit adventure log LLM call (non-streaming, kicks off in background)
    # Continue yielding bridge_text segments (buffer narrative)
    # When bridge_text done → await adventure log response → yield ending:
    yield {
        "type": "ending",
        "adventure_log": str,       # LLM-generated markdown
        "final_state": dict,        # state_vars snapshot
        "summary": str | None,      # ending checkpoint summary
    }
    yield {"type": "done", "round": ..., "node": "end", "state": ...}
    return  # Game over
else:
    # Normal next-round preparation (existing logic)
```

Per `exec-flow.md` §5.2: bridge_text display continues while adventure log is generated. The generator yields bridge_text segments first, then the ending event when both are ready.

### 3.4 Adventure Log Prompt

Replace existing simplified `run_adventure_log()` with the structured template from `prompt-design.md` §5.2:

New method: `PromptBuilder.build_adventure_log_prompt(story_config, state_vars, checkpoint_summaries, checkpoint_history) → str`

Template per spec:
- `## 冒险回顾：{story_label}`
- `### 第X章：{node_title}` — per checkpoint, 2-3 sentences expanded from summary
- `### 结局：{ending_title}` — story conclusion
- `### 最终状态` — bullet list of each variable's final value with commentary
- 500-1000 chars, player-facing tone ("你选择了……"), Markdown format
- Independent LLM call, non-streaming, does NOT go through narrative loop pipeline

### 3.5 New Event Type

```python
{
    "type": "ending",
    "adventure_log": str,     # LLM-generated markdown text
    "final_state": dict,      # Final state_vars snapshot
    "summary": str | None,    # Ending checkpoint summary
}
```

### 3.6 Checkpoint Accumulation

New fields on GameLoop (populated during checkpoint processing):

```python
_checkpoint_summaries: list[str] = []   # Plain summary strings
_checkpoint_history: list[dict] = []    # [{node, title, summary, round}]
_checkpoint_snapshots: dict[str, dict] = {}  # {node_id: state_vars snapshot}
```

Per spec: `checkpoint_history` is structured (used by adventure log prompt to get per-chapter node titles), while `checkpoint_summaries` is plain strings (used as input context). Both are stored in the save and passed to `build_adventure_log_prompt()`.

---

## §4 CoCreateFlow Decoupling

### 4.1 Actual Display Usage

CoCreateFlow uses Display in these ways (verified from source):

| Pattern | Count | Maps to |
|---------|-------|---------|
| `d.output.write(text)` | ~20 | `ui.write(text)` |
| `d.show_wait_message(msg)` | 4 | `ui.write(msg)` (same thing) |
| `d.show_error(msg)` | 2 | `ui.show_error(msg)` |
| `d.get_input(prompt)` | ~10 | `ui.ask(prompt) → str` |

No multi-choice selection is used in co-creation — only free-text input.

### 4.2 New Protocol: `src/storyloom/core/ui_interface.py`

```python
from typing import Protocol

class UiInterface(Protocol):
    """UI abstraction for headless (UI) use.

    Display implements this; UI implementations provide their own.
    """

    def write(self, text: str) -> None:
        """Display text to the user (info, prompts, wait messages, etc.)."""
        ...

    def show_error(self, text: str) -> None:
        """Display error message."""
        ...

    def ask(self, prompt: str) -> str:
        """Ask user for free-text input. Returns user's response."""
        ...
```

### 4.3 CoCreateFlow Changes

```python
class CoCreateFlow:
    def __init__(self, api_client: ApiClient, ui: UiInterface, ...):
        self.ui = ui  # was: self._display = display
```

Replace all Display calls:
- `self._display.output.write(...)` / `d.output.write(...)` → `self.ui.write(...)`
- `self._display.show_wait_message(...)` / `d.show_wait_message(...)` → `self.ui.write(...)`
- `self._display.show_error(...)` / `d.show_error(...)` → `self.ui.show_error(...)`
- `self._display.get_input(...)` / `d.get_input(...)` → `self.ui.ask(...)`

### 4.4 Display Update

`Display` implements `UiInterface`:
- `write(text)` delegates to `self.output.write(text)`
- `show_error(text)` already exists
- `ask(prompt)` delegates to `self.get_input(prompt)` (or rename for consistency)

All other Display methods (`show_segment`, `show_options`, etc.) remain unchanged — they're not used by CoCreateFlow.

---

## §5 File Change Summary

| File | Change | Type |
|------|--------|------|
| `src/storyloom/core/save_manager.py` | New module | **New** |
| `src/storyloom/core/ui_interface.py` | UiInterface protocol | **New** |
| `src/storyloom/core/game_loop.py` | ending_flag, checkpoint accum, \_outline_nodes, \_temperature, to\_save\_dict/from\_save\_dict, ending flow in continue\_round\_stream | Modify |
| `src/storyloom/core/prompt_builder.py` | build_adventure_log_prompt() | Modify |
| `src/storyloom/core/co_create.py` | Display → UiInterface, add label to config | Modify |
| `src/storyloom/io/display.py` | Implement UiInterface.write(), add UiInterface methods | Modify |
| `src/storyloom/__init__.py` | Export SaveManager | Modify |
| `tests/test_save_manager.py` | Unit tests | **New** |
| `tests/test_game_loop.py` | Ending + serialization tests | Modify |
| `tests/test_co_create.py` | UiInterface mock instead of Display | Modify |
| `tests/test_prompt_builder.py` | adventure_log prompt tests | Modify |

---

## §6 UI Layer API Contract (Summary)

### Game Flow (existing, unchanged)
```python
game_loop.start_round1_stream()              # → Iterator[dict]
game_loop.continue_round_stream(choice_dict)  # → Iterator[dict] (+ ending)
```

### Save System (new)
```python
SaveManager("saves").list_saves()   # → list[dict]
SaveManager("saves").load(label)    # → dict (save data)
SaveManager("saves").save(data)     # → None
SaveManager("saves").delete(label)  # → bool
```

### Co-Creation (modified)
```python
class MyUi:                         # implements UiInterface
    def write(self, text): ...      # display text
    def show_error(self, text): ... # display error
    def ask(self, prompt) -> str: ...  # get user input

flow = CoCreateFlow(api_client, ui=MyUi())
flow.run()  # existing method, now headless-compatible
```

### Event Types
| type | When | Payload |
|------|------|---------|
| `token` | Per token during streaming | `{"type": "token", "text": str}` |
| `segment` | Per `<seg>` parsed | `{"type": "segment", "text": str, "n": int, "position": str, "branch": str\|None}` |
| `options` | `<choice>` parsed | `{"type": "options", "choices": [{"id": str, "branches": [str], "labels": [str], "conditions": {str: str}}]}` |
| `state` | After `<set>` applied | `{"type": "state", "vars": dict, "changes": [{"var": str, "op": str, "val": str, "accepted": bool, "reason": str\|None}]}` |
| `error` | Parse/API failure | `{"type": "error", "message": str}` |
| `done` | Round complete | `{"type": "done", "round": int, "node": str\|None, "state": dict}` |
| `ending` | **New** — game over | `{"type": "ending", "adventure_log": str, "final_state": dict, "summary": str\|None}` |
