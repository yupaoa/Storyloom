# API Audit & Interface Design for UI Integration

> **Status:** Design approved, ready for implementation plan.
> **Date:** 2026-07-07

## §1 Background

Storyloom is a single Python application with a layered architecture:
**core engine** (game loop, state management, LLM interaction) + **UI protocol**
(terminal CLI on `main`, web interface under active parallel development).

The engine asserts UI-agnosticism via the `UiInterface` protocol, but an audit
found 5 critical gaps that would force the Web UI to reimplement business logic.
This design closes those gaps under the principle of **minimal intrusion** —
no changes to core flow logic, only new public API surface.

### Design Principles

1. **Engine internals stay private** — `_prefix` attributes remain private;
   only necessary public accessors added.
2. **UI doesn't reimplement logic** — all business rules live in engine,
   exposed via clean interfaces.
3. **UI freedom maximized** — provide capabilities; don't constrain how UI
   composes them.
4. **No core flow changes** — `game_loop.py` and `co_create.py` core logic
   untouched; only new methods/properties added alongside existing ones.

## §2 Audit Findings

### Current `UiInterface` (only 3 methods)

```python
class UiInterface(Protocol):
    def write(self, text: str) -> None: ...
    def show_error(self, text: str) -> None: ...
    def ask(self, prompt: str) -> str: ...
```

### Five Gaps Identified

| # | Gap | Severity | Root Cause |
|---|-----|----------|------------|
| 1 | UiInterface too minimal | 🔴 Critical | No semantic methods for wait/separator states |
| 2 | CoCreateFlow unreusable by web UI | 🔴 Critical | Synchronous `run()` with embedded UI calls |
| 3 | No top-level session orchestrator | 🔴 Critical | `main.py` hardcodes the lifecycle flow |
| 4 | Missing public accessors on GameLoop | 🟡 Medium | `_checkpoint_history` and `_outline_nodes` are private |
| 5 | SaveManager not unified | 🟡 Medium | Separate lifecycle from GameLoop; UI must wire manually |

### Full Flow Coverage Map

```
[Menu] → [Co-Create] → [Init GameState] → [Narrative Loop] → [Ending] → [Menu]

Phase              Engine Provides               UI Can Use Directly?
─────              ───────────────               ────────────────────
Menu               SaveManager.list_saves()      ✅
                   SaveManager.delete()          ✅
New Game           CoCreateFlow.run()            ❌ (synchronous, embedded UI)
                   GameState(story_config)       ✅
                   GameLoop(...)                 ⚠️ (7 constructor params)
Gameplay           start_round1_stream()         ✅
                   continue_round_stream(key)    ✅
                   get_available_options()       ✅
                   to_save_dict()                ✅
                   round_count, current_node     ✅
                   checkpoint_history            ❌ (private _attribute)
                   outline_nodes                 ❌ (private _attribute)
Ending             type: "ending" event          ✅ (built into stream)
                   adventure_log                 ✅ (in ending event)
Return to Menu     —                             ❌ (no transition mechanism)
```

## §3 Design

### 3.1 UiInterface Extension

**File:** `src/storyloom/core/ui_interface.py`

Add two semantic methods. No changes to existing methods.

```python
class UiInterface(Protocol):
    # ── Existing (unchanged) ──
    def write(self, text: str) -> None: ...
    def show_error(self, text: str) -> None: ...
    def ask(self, prompt: str) -> str: ...

    # ── New ──
    def show_wait(self, message: str) -> None:
        """Display a transient wait/progress message.
        
        Semantically distinct from write(): the UI may show a spinner,
        loading indicator, or inline text. The engine uses this for
        "Weaving your story world..." and similar progress states.
        """
        ...

    def show_separator(self) -> None:
        """Display a visual section break between UI phases.
        
        UI determines the visual rendering (horizontal rule, spacing,
        or transition animation). Engine uses this at phase boundaries.
        """
        ...
```

**Rationale:** `co_create.py:698` currently calls `ui.write(_("Weaving your story world..."))`.
A Web UI receiving `write()` can't discriminate between narrative content and progress
messages. `show_wait()` gives semantic intent; the UI chooses rendering.

### 3.2 GameLoop Public Accessors

**File:** `src/storyloom/core/game_loop.py`

Two new read-only properties. The underlying data is already public in save files
(`data-model.md` §3.1 outlines); this provides live access without requiring file I/O.

```python
class GameLoop:
    # ── New properties ──

    @property
    def checkpoint_history(self) -> list[dict]:
        """Return checkpoint history for UI progress display.
        
        Returns a copy. Each entry: {node, title, summary, round}.
        """

    @property
    def outline_nodes(self) -> list[dict]:
        """Current outline with computed node statuses.
        
        Returns a copy. Each entry: {id, title, goal, status, routes}.
        Status is computed: 'active' | 'completed' | 'pending'.
        """
```

**Not exposed** (kept private):
- `_checkpoint_summaries` — internal compression use only
- `_checkpoint_snapshots` — reserved for Phase 2 rewind feature
- `_rejected_changes` — transient per-round state

### 3.3 CoCreateFlow Step-by-Step API

**File:** `src/storyloom/core/co_create.py`

A state machine API alongside the existing synchronous `run()`. `run()` is preserved
unchanged for CLI and backward compatibility.

```python
class CoCreateFlow:
    # ── Existing (unchanged) ──
    def __init__(self, api_client, ui): ...
    def run(self) -> CoCreationResult: ...
    @property
    def messages(self) -> list[dict]: ...

    # ── New: explicit state machine ──

    @property
    def phase(self) -> str:
        """Current phase: 'init' | 'awaiting_idea' | 'awaiting_answer'
           | 'generating' | 'complete' | 'aborted'."""

    @property
    def result(self) -> CoCreationResult | None:
        """Result when phase == 'complete', None otherwise."""

    def start(self) -> dict:
        """Begin co-creation. Returns {phase: 'awaiting_idea', prompt: str}.
        
        Must be called once before any send().
        """

    def send(self, user_input: str) -> dict:
        """Send user input, advance one step, return next event dict.
        
        Handles 'go'/'quit' keyword detection. Blocking during
        generation (LLM API call).
        
        Return dict has always-present 'phase' key plus phase-specific data.
        """

    def abort(self) -> None:
        """Abort co-creation immediately."""
```

**Event dict contract** (return values of `start()` and `send()`):

| phase | Additional Keys | Meaning |
|-------|----------------|---------|
| `awaiting_idea` | `prompt` | Show prompt, wait for user's story idea |
| `awaiting_answer` | `question`, `round` | Show LLM question, wait for user response |
| `generating` | — | LLM call in progress (transient) |
| `complete` | `result: CoCreationResult` | Done; use result to start game |
| `error` | `message`, `recoverable: bool` | Something failed; UI decides next step |

**Usage pattern (web UI pseudocode):**

```python
flow = CoCreateFlow(api_client, ui)

# Step 1: get idea
event = flow.start()
# → {phase: "awaiting_idea", prompt: "Describe the story..."}
# UI renders prompt, waits for user input

# Step 2-N: Q&A loop
event = flow.send(user_input)
# → {phase: "awaiting_answer", question: "...", round: 1}
# ...repeat until user says "go"...

# Final: generation
event = flow.send("开始")
# → {phase: "complete", result: CoCreationResult(...)}
```

### 3.4 GameSession Orchestrator

**File:** `src/storyloom/core/session.py` (new)

A thin coordination layer. Owns `ApiClient` and `SaveManager`. Wires
`CoCreateFlow → GameLoop` transitions. UI retains full control over
rendering and interaction flow.

```python
class GameSession:
    """Lightweight lifecycle coordinator.
    
    Does NOT control UI flow. UI calls methods at its own pace.
    """

    def __init__(self, saves_dir: str = "saves"):
        """Initialize ApiClient (.env) and SaveManager."""

    # ── Save management ──
    def list_saves(self) -> list[dict]: ...
    def delete_save(self, label: str) -> bool: ...

    # ── Lifecycle ──
    def new_co_create(self) -> CoCreateFlow: ...
    def start_game(self, result: CoCreationResult) -> GameLoop: ...
    def load_game(self, label: str) -> GameLoop: ...

    # ── State ──
    @property
    def game_loop(self) -> GameLoop | None: ...
    
    @property
    def phase(self) -> str:
        """'menu' | 'co_create' | 'playing' | 'ended'"""
```

**Explicit non-responsibilities** (UI owns these decisions):
- Menu rendering and navigation
- Narrative display pacing (auto/manual mode)
- User input routing (choice keys, quit requests)
- WebSocket/SSE connection management
- Ending display transition

### 3.5 Display Implementation

**File:** `src/storyloom/io/display.py`

Add `show_wait()` and `show_separator()` methods to the existing `Display` class
(which already implements `UiInterface` via `write`/`ask`).

```python
class Display:
    # Existing methods unchanged...

    def show_wait(self, message: str) -> None:
        """Display a wait/progress message."""
        self.output.write(f"\n  {message}\n\n")
        self.output.flush()

    def show_separator(self) -> None:
        """Display a section separator."""
        self.output.write("─" * 50 + "\n\n")
        self.output.flush()
```

## §4 What Does NOT Change

- **GameLoop core logic** — `start_round1_stream()`, `continue_round_stream()`,
  state validation, route evaluation, ending detection: zero modifications.
- **CoCreateFlow.run()** — preserved as-is for CLI backward compatibility.
- **XmlParser / StreamingXmlParser** — no changes.
- **PromptBuilder / ContextManager** — no changes.
- **SaveManager** — no changes; `GameSession` wraps it without modifying it.
- **ApiClient** — no changes.
- **i18n / config** — no changes.

## §5 Implementation Order

| Step | File | Change | Risk |
|------|------|--------|------|
| 1 | `ui_interface.py` | Add `show_wait`, `show_separator` | None (protocol only) |
| 2 | `display.py` | Implement new methods | None |
| 3 | `game_loop.py` | Add 2 public properties | None (read-only) |
| 4 | `co_create.py` | Add state machine API | Low (new code, existing unchanged) |
| 5 | `session.py` | New file | Low (new code, no existing deps) |
| 6 | Tests | Add tests for new API surface | — |

## §6 Self-Check

- [x] No placeholders or TODOs
- [x] All sections consistent: §3.3 events match §3.1 protocol methods
- [x] Scoped to one implementation plan: focused API surface extension
- [x] No ambiguous requirements: every method has a return type and contract
- [x] Design principles (§1) respected: no core flow changes, UI freedom preserved
