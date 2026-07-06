# Backend Completion Design — Core Loop Closure

> **Date**: 2026-07-06
> **Status**: Approved
> **Goal**: Fill backend gaps so frontend + backend can independently develop and merge into a complete game loop (new game → co-create → narrative → ending → save → continue).

## §1 Scope

Four areas, all minimal-change:

1. **Save System** — new `SaveManager` module (save/load/delete/list)
2. **Ending Detection + Adventure Log** — `ending_flag` mechanism + independent LLM call per spec
3. **CoCreateFlow Decoupling** — `UiInterface` protocol so frontend can implement its own UI
4. **Serialization** — `GameState.to_dict()` / `GameLoop.to_save_dict()` / `GameLoop.from_save_dict()`

Out of scope: main menu implementation (CLI/frontend concern), Q-key ending (frontend concern), option graying display (frontend concern after `conditions` already exposed in events).

### Current State (post-refactor)

```
src/storyloom/
  __init__.py           — public API re-exports
  config.py             — constants
  i18n.py               — gettext
  core/
    game_loop.py        — GameState, GameLoop, RoundResult, RoundRecord
    co_create.py         — CoCreateFlow (depends on Display)
    context_manager.py   — ContextManager (messages array, sliding window)
    prompt_builder.py    — PromptBuilder (round 1 / round N prompts)
  io/
    api_client.py        — ApiClient (streaming + non-streaming)
    display.py           — Display (terminal, implements informal UI methods)
  parser/
    xml_parser.py        — XmlParser (batch), ParsedOutput, Segment, SetOperation
    streaming_parser.py  — StreamingXmlParser (parse events)
```

Key data distribution:
- **GameState**: `_state_vars`, `_var_types`, apply_set(), evaluate_condition()
- **GameLoop**: `story_config`, `outline_text`, `current_node`, `_completed_nodes`, `_node_goals`, `_last_bridge_text`, `_rejected_changes`, `round_count` (via ContextManager), `last_parsed`

---

## §2 Save System

### 2.1 New Module: `src/storyloom/core/save_manager.py`

```python
class SaveManager:
    def __init__(self, saves_dir: str = "saves") -> None

    def save(self, save_data: dict) -> None
        # Writes save dict to saves/{label}.json (atomic: .tmp → os.replace)
        # save_data = GameLoop.to_save_dict()

    def load(self, label: str) -> dict
        # Reads saves/{label}.json, validates, returns save_data dict
        # Caller uses GameLoop.from_save_dict(data, api_client) to restore
        # Raises: FileNotFoundError, ValueError (corrupt save)

    def delete(self, label: str) -> bool
        # Deletes saves/{label}.json. Returns True if deleted.

    def list_saves(self) -> list[dict]
        # Returns [{ "label": str, "round_count": int, "created_at": str,
        #            "updated_at": str, "current_node": str }]
```

No LLM involvement. Pure file I/O. No Display dependency.

### 2.2 Save File Format

Per `data-model.md` §3.1:

```json
{
  "version": 1,
  "metadata": { "label": "...", "created_at": "...", "updated_at": "...", "round_count": 0 },
  "config": { "temperature": null },
  "story_config": { "...": "...", "variables": [...] },
  "state_vars": { "...": "..." },
  "outline": [{ "node_id": "...", "title": "...", "goal": "...", "status": "...", "branches": [...] }],
  "progress": {
    "current_node": "...",
    "round_count": 0,
    "completed_nodes": [],
    "checkpoint_summaries": [],
    "checkpoint_history": [],
    "checkpoint_snapshots": {}
  },
  "bridge_text": ""
}
```

**Naming**: Based on `story_config.label` (not UUID). Illegal chars (`/ \ : * ? " < > |`) replaced with `_`. Duplicates get `_2`, `_3` suffix.

**Auto-save timing**: Only at checkpoint processing (per spec). Not every round.

### 2.3 Load Validation

Per `data-model.md` §3.4:
1. JSON parseable → else corrupt
2. `version == 1` → else corrupt
3. Required fields present: `story_config` (with `variables`), `state_vars`, `outline`, `progress` → else corrupt
4. `progress.current_node` exists in `outline` → else corrupt
5. If any validation fails → raise `ValueError`, caller deletes file and returns to menu

### 2.4 Serialization Methods

**On GameState** — serializes just the variable state:

```python
# GameState
def to_dict(self) -> dict:
    return {
        "state_vars": dict(self._state_vars),
        "var_types": dict(self._var_types),
    }

@classmethod
def from_dict(cls, data: dict) -> "GameState":
    """Restore from dict. story_config is reconstructed with variables list."""
    story_config = {
        "variables": [
            {"name": name, "type": vtype, "initial": data["state_vars"].get(name)}
            for name, vtype in data.get("var_types", {}).items()
        ]
    }
    gs = cls(story_config)
    gs._state_vars = dict(data["state_vars"])
    gs._var_types = dict(data.get("var_types", {}))
    return gs
```

**On GameLoop** — assembles the full save dict:

```python
# GameLoop
def to_save_dict(self) -> dict:
    """Produce complete save dict (format per data-model §3.1)."""
    ...

@classmethod
def from_save_dict(cls, data: dict, api_client: ApiClient, display: Display | None = None) -> "GameLoop":
    """Restore GameLoop from save dict. Validates structure first."""
    ...
```

### 2.5 `__init__.py` Exports

```python
from storyloom.core.save_manager import SaveManager
```

---

## §3 Ending Detection + Adventure Log

### 3.1 ending_flag

New field on GameLoop (or GameState, see §5 Implementation Notes):

```python
ending_flag: bool = False  # Set when checkpoint node == "end"
```

### 3.2 Detection Flow

In `continue_round_stream()`, during checkpoint processing (after XML parse):

```
parsed.checkpoint_node == "end"?
  → self.ending_flag = True
  → Mark last outline node completed
  → Store checkpoint_summaries entry
  → Store checkpoint_snapshots[current_node] = deep_copy(state_vars)
  → Trigger auto-save (via SaveManager)
  → Yield {"type": "state", "vars": ..., "changes": [...]} (existing)
  → Continue to bridge handling
```

### 3.3 Bridge Handling (Modified)

At bridge point in `continue_round_stream()`:

```
if self.ending_flag:
    # Don't assemble normal next-round prompt
    # Instead: call adventure log LLM (non-streaming)
    adventure_log = self._run_adventure_log()
    # Continue displaying bridge_text (buffer)
    # When bridge_text done + adventure_log ready:
    yield {
        "type": "ending",
        "adventure_log": adventure_log,
        "final_state": self.game_state.state_vars,
        "summary": parsed.checkpoint_summary,
    }
    yield {"type": "done", "round": ..., "node": "end", "state": ...}
    return  # Game over
else:
    # Normal next-round preparation (existing logic)
```

### 3.4 adventure_log Prompt

Replace existing simplified `run_adventure_log()` prompt with the structured template from `prompt-design.md` §5.2:

New method: `PromptBuilder.build_adventure_log_prompt(story_config, state_vars, checkpoint_summaries, checkpoint_history) → str`

Template per spec:
- `## 冒险回顾：{story_label}`
- `### 第X章：{node_title}` — per checkpoint, 2-3 sentences expanded from summary
- `### 结局：{ending_title}` — story conclusion
- `### 最终状态` — bullet list of each variable's final value with commentary
- 500-1000 chars, player-facing tone ("你选择了……"), Markdown format

### 3.5 New Event Type

```python
{
    "type": "ending",
    "adventure_log": str,     # LLM-generated markdown text
    "final_state": dict,      # Final state_vars snapshot
    "summary": str | None,    # Ending checkpoint summary
}
```

---

## §4 CoCreateFlow Decoupling

### 4.1 New Protocol: `src/storyloom/core/ui_interface.py`

```python
from typing import Protocol

class UiInterface(Protocol):
    """UI abstraction for headless (frontend) use.

    Display implements this; frontends provide their own implementation.
    """

    def show(self, text: str) -> None:
        """Display informational text (wait messages, status)."""
        ...

    def show_error(self, text: str) -> None:
        """Display error message."""
        ...

    def ask(self, prompt: str) -> str:
        """Ask user for free-text input. Returns user's response."""
        ...

    def ask_choice(self, prompt: str, options: list[str]) -> str:
        """Present options, return user's choice."""
        ...
```

### 4.2 CoCreateFlow Change

```python
class CoCreateFlow:
    def __init__(
        self,
        api_client: ApiClient,
        ui: UiInterface,          # was: display: Display
        ...
    ):
        self.ui = ui
```

Replace all `self.display.show(...)` → `self.ui.show(...)` etc.

### 4.3 Display Update

`Display` already has the required methods. Add explicit protocol compliance (no functional changes needed).

---

## §5 Implementation Notes

### 5.1 Where to Put ending_flag

Two reasonable options:

| Option | Location | Pros | Cons |
|--------|----------|------|------|
| A | `GameLoop.ending_flag` | Minimal change, GameLoop already holds all narrative state | Save serialization needs GameLoop-level method anyway |
| B | New `GameState.progress` dict per spec | Matches spec exactly | Requires moving current_node, round_count, etc. into GameState — bigger refactor |

**Recommend A** for now. The spec's `progress` dict structure is the ideal; we can refactor toward it later when the data model naturally consolidates.

### 5.2 Checkpoint Accumulation

Currently GameLoop has `_completed_nodes: list[str]` but no `checkpoint_summaries` or `checkpoint_history`. Add to GameLoop:

```python
_checkpoint_summaries: list[str] = []
_checkpoint_history: list[dict] = []    # [{"node": str, "summary": str, "round": int}]
_checkpoint_snapshots: dict[str, dict] = {}  # {node_id: state_vars snapshot}
```

These are populated during checkpoint processing in `continue_round_stream()`.

### 5.3 Auto-Save Integration

At checkpoint processing:
```python
if self._save_manager is not None:
    self._save_manager.save(self.to_save_dict())
```

SaveManager is optional (CLI can pass it; frontend can manage saves independently).

### 5.4 Outline Parsing for Save

Currently `outline_text` is stored as a raw string. For save format, we need parsed outline nodes. The parsing logic (`_parse_outline_goals`) extracts `{node_id: goal}`. Need to also extract title and status for the save format.

Minimal approach: add `_parse_outline_nodes()` that returns `list[dict]` with `{node_id, title, goal, status, branches}`.

---

## §6 File Change Summary

| File | Change | Type |
|------|--------|------|
| `src/storyloom/core/save_manager.py` | New module | **New** |
| `src/storyloom/core/ui_interface.py` | UiInterface protocol | **New** |
| `src/storyloom/core/game_loop.py` | ending_flag, checkpoint accum, to_save_dict/from_save_dict, ending flow in continue_round_stream | Modify |
| `src/storyloom/core/prompt_builder.py` | build_adventure_log_prompt() | Modify |
| `src/storyloom/core/co_create.py` | Display → UiInterface | Modify |
| `src/storyloom/__init__.py` | Export SaveManager | Modify |
| `tests/test_save_manager.py` | Unit tests | **New** |
| `tests/test_game_loop.py` | Ending + serialization tests | Modify |
| `tests/test_co_create.py` | UiInterface mock instead of Display | Modify |
| `tests/test_prompt_builder.py` | adventure_log prompt tests | Modify |

---

## §7 Frontend API Contract (Summary)

All interfaces the frontend depends on:

### Game Flow (existing, unchanged)
```python
game_loop.start_round1_stream()      # → Iterator[dict]  (token|segment|options|state|error|done)
game_loop.continue_round_stream(choice_dict)  # → Iterator[dict]  (+ ending)
```

### Save System (new)
```python
SaveManager("saves").list_saves()     # → list[dict]
SaveManager("saves").load(label)      # → dict (save data)
SaveManager("saves").save(data)       # → None
SaveManager("saves").delete(label)    # → bool
```

### Co-Creation (modified)
```python
class MyUi:                          # implements UiInterface
    def show(self, text): ...
    def show_error(self, text): ...
    def ask(self, prompt) -> str: ...
    def ask_choice(self, prompt, options) -> str: ...

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
