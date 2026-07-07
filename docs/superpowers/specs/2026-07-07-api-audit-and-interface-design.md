# API Audit & Interface Design for UI Integration

> **Status:** Design approved, ready for implementation plan.
> **Date:** 2026-07-07
> **Revision:** v2 — self-review corrections applied (see §6).

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

### 2.1 Current `UiInterface` (only 3 methods)

```python
class UiInterface(Protocol):
    def write(self, text: str) -> None: ...
    def show_error(self, text: str) -> None: ...
    def ask(self, prompt: str) -> str: ...
```

### 2.2 Five Gaps Identified

| # | Gap | Severity | Root Cause |
|---|-----|----------|------------|
| 1 | UiInterface too minimal | 🔴 Critical | No semantic methods; web UI can't distinguish intent |
| 2 | CoCreateFlow unreusable by web UI | 🔴 Critical | Synchronous `run()` with embedded UI calls |
| 3 | No top-level session orchestrator | 🔴 Critical | `main.py` hardcodes the lifecycle flow |
| 4 | Missing public accessors on GameLoop | 🟡 Medium | `_checkpoint_history` and `_outline_nodes` are private |
| 5 | SaveManager not unified | 🟡 Medium | Separate lifecycle from GameLoop; UI must wire manually |

### 2.3 Full Flow Coverage Map

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

### 3.1 How Gaps 1-2 Are Addressed: State Machine API (Not Protocol Extension)

The initial design proposed extending `UiInterface` with `show_wait()` and
`show_separator()`. Self-review (see §6) found this unnecessary: the new
state machine API communicates via return dicts, not via `UiInterface`.
Adding protocol methods that only `run()` (CLI legacy) would call violates
YAGNI.

**Decision:** `UiInterface` stays unchanged (3 methods). Gap 1 (too minimal)
and Gap 2 (CoCreateFlow unreusable) are both solved by the state machine API
below — it replaces `run()` as the primary UI integration point.

### 3.2 GameLoop Public Accessors (Gap 4)

**File:** `src/storyloom/core/game_loop.py`

Two new read-only properties. The underlying data is already public in save
files (`data-model.md` §3.1); this provides live access without file I/O.

**Pre-existing bug discovered during design:** `_outline_nodes` has two
incompatible internal formats depending on creation path:

| Path | Format | Key names |
|------|--------|-----------|
| Fresh (`CoCreateParser.parse_outline()`) | `[{id, title, goal, routes: [{condition, target}]}]` |
| Loaded (`from_save_dict()` → `data["outline"]`) | `[{node_id, title, goal, status, branches: [str]}]` |

Consequence: on a loaded game, `to_save_dict()` (L941, L950) uses
`node.get("id", "")` and `node.get("routes", [])` — both return empty for
the loaded format — producing corrupted save data. `_next_outline_node()`
(L1184) has the same issue, breaking route fallback for loaded games.

The public property normalizes both formats, fixing this latent bug.

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
        
        Returns a copy. Each entry: {id, title, goal, status, branches}.
        Format matches the save file outline structure (data-model.md §3.1).
        
        Status is computed: 'active' | 'completed' | 'pending'.
        branches: list of target node ID strings (conditions excluded —
                  they are engine internals).
        
        Normalizes the two internal formats (fresh vs. loaded) into a
        single consistent public shape.
        """
```

**Not exposed** (kept private):
- `_checkpoint_summaries` — internal compression use only
- `_checkpoint_snapshots` — reserved for Phase 2 rewind feature
- `_rejected_changes` — transient per-round state

### 3.3 CoCreateFlow Step-by-Step API (Gap 2)

**File:** `src/storyloom/core/co_create.py`

A state machine API alongside the existing synchronous `run()`. `run()` is
preserved unchanged for CLI backward compatibility.

**Design note:** `ui` parameter made optional (`UiInterface | None`).
Required by `run()` (CLI path); unused by the state machine API (which
communicates via return dicts). `run()` raises `RuntimeError` if called
with `ui=None`.

```python
class CoCreateFlow:
    # ── Existing (unchanged) ──
    def run(self) -> CoCreationResult: ...
    @property
    def messages(self) -> list[dict]: ...

    # ── Constructor change ──
    # ui changed from required to optional
    def __init__(self, api_client: ApiClient, ui: UiInterface | None = None): ...

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
        Does NOT call ui methods — communicates solely via return dicts.
        """

    def abort(self) -> None:
        """Abort co-creation immediately."""
```

**Event dict contract** (return values of `start()` and `send()`):

| phase | Additional Keys | Meaning |
|-------|----------------|---------|
| `awaiting_idea` | `prompt` | Show prompt, wait for user's story idea |
| `awaiting_answer` | `question`, `round` | Show LLM question, wait for user response |
| `generating` | — | LLM call in progress (transient; UI usually won't render this) |
| `complete` | `result: CoCreationResult` | Done; use result to start game |
| `error` | `message`, `recoverable: bool` | Something failed; UI decides next step |

**Usage pattern (web UI pseudocode):**

```python
flow = CoCreateFlow(api_client)  # no ui needed for state machine

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

### 3.4 GameSession Orchestrator (Gaps 3, 5)

**File:** `src/storyloom/core/session.py` (new)

A thin coordination layer. Owns `ApiClient` and `SaveManager`. Wires
`CoCreateFlow → GameLoop` transitions. UI retains full control over
rendering and interaction flow.

**Design note:** `phase` property removed during self-review (see §6).
GameSession cannot detect game ending — it happens inside
`continue_round_stream()`. The `game_loop` property (`None` when no
active game) plus `game_loop.ending_flag` give the UI sufficient state
to track lifecycle.

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
    def game_loop(self) -> GameLoop | None:
        """Current active game, or None if not in-game."""
```

**Explicit non-responsibilities** (UI owns these decisions):
- Menu rendering and navigation
- Narrative display pacing (auto/manual mode)
- User input routing (choice keys, quit requests)
- WebSocket/SSE connection management
- Ending display transition
- Phase/lifecycle tracking (UI uses `game_loop` + `ending_flag`)

## §4 What Does NOT Change

- **UiInterface** — unchanged (3 methods). No protocol extension needed.
- **Display** — unchanged. No new methods.
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
| 1 | `game_loop.py` | Add `checkpoint_history`, `outline_nodes` properties | Low |
| 2 | `co_create.py` | `ui` optional; add state machine API (`phase`, `result`, `start`, `send`, `abort`) | Medium |
| 3 | `session.py` | New file: `GameSession` class | Low |
| 4 | Tests | Add tests for new API surface | — |

## §6 Self-Review Corrections (v2)

During systematic self-review against spec docs, code, and memory files,
four issues were identified. Three confirmed; one rejected.

### Confirmed and Applied

1. **`outline_nodes` format normalization** — Internal `_outline_nodes` has
   two incompatible formats (fresh: `{id, routes}`, loaded: `{node_id,
   branches}`). The public property normalizes to save format, fixing a
   latent bug where `to_save_dict()` and `_next_outline_node()` fail on
   loaded games (both use `node.get("id", "")` which returns empty for
   loaded format).

2. **`GameSession.phase` removed** — Ending detection happens inside
   `continue_round_stream()` (L817-848), which GameSession doesn't
   consume. `phase` would permanently report `'playing'` after game end.
   Removed; UI tracks lifecycle via `game_loop` + `ending_flag`.

3. **`CoCreateFlow.__init__` ui made optional** — State machine methods
   communicate via return dicts, not UiInterface. Requiring `ui` for
   state-machine-only usage is misleading. `run()` asserts non-None.

### Rejected

4. **UiInterface extension (`show_wait`, `show_separator`)** — Rejected.
   These would only be called by `run()` (CLI legacy path). The state
   machine API communicates via return dicts; the streaming API
   communicates via yield events. Adding protocol methods with no
   caller in the primary UI path violates YAGNI. UiInterface stays
   at 3 methods.
