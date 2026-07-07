# Co-Creation API

> **Audience:** UI developers integrating the co-creation phase.
> **Authoritative spec:** `docs/spec/exec-flow.md` §3

The co-creation phase is a guided Q&A flow between the player and the LLM.
It produces a `CoCreationResult` containing `story_config` and `outline_text`
— pass these to `GameSession.start_game()` to begin the narrative.

## Entry Point

Use `GameSession` as the entry point:

```python
from storyloom.core import GameSession

session = GameSession()
flow = session.new_co_create()  # → CoCreateFlow
```

## Two APIs

CoCreateFlow provides **two** integration paths. UI developers should use
the state machine API. The legacy `run()` is preserved for CLI backward
compatibility only.

### State Machine API (recommended for all UIs)

Communicates via return dicts. Does **not** require a `UiInterface` —
ideal for web UIs where each step is a separate HTTP request.

```python
flow = CoCreateFlow(api_client)  # ui=None — no UiInterface needed

# Step 1 — collect story idea
event = flow.start()
# → {"phase": "awaiting_idea", "prompt": "Describe the story you'd like to play..."}

# Step 2 — Q&A loop
event = flow.send(user_input)
# → {"phase": "awaiting_answer", "question": "...", "round": 1}
# ... repeat until user says "go" / "开始" ...

# Step 3 — generation
event = flow.send("开始")
# → {"phase": "complete", "result": CoCreationResult(...)}
```

#### Event Dict Contract

Every return dict has a `"phase"` key:

| phase | Additional Keys | Meaning |
|-------|----------------|---------|
| `awaiting_idea` | `prompt` | Show prompt, wait for story idea |
| `awaiting_answer` | `question`, `round` | Show LLM question, wait for answer |
| `generating` | — | LLM call in progress (transient) |
| `complete` | `result: CoCreationResult` | Done; use with `GameSession.start_game()` |
| `error` | `message`, `recoverable: bool` | API/parse failure; UI decides retry/abort |
| `aborted` | — | User quit or unrecoverable error |

#### Flow Control

- **Start keywords:** `"开始"`, `"go"`, `"start"`, `"begin"`, `"ready"`, `"yes"`, `"ok"`, etc.
- **Quit keywords:** `"quit"`, `"exit"`, `"q"`, `"不玩了"`, `"退出"`, etc.
- **Round limit:** 15 Q&A rounds, then auto-generates
- **Recovery:** On `{phase: "error", recoverable: True}`, call `send()` again with the same or corrected input

#### State Inspection

```python
flow.phase    # 'init' | 'awaiting_idea' | 'awaiting_answer'
              # | 'generating' | 'complete' | 'aborted'
flow.result   # CoCreationResult | None (only set when phase == 'complete')
flow.messages # list of conversation messages (for debug/prompt saving)
```

### Legacy `run()` (CLI backward compat)

Synchronous, blocking. Requires a `UiInterface` for all I/O. Preserved
unchanged for the CLI test harness.

```python
flow = CoCreateFlow(api_client, ui=my_ui_impl)
result = flow.run()  # blocks until co-creation completes
```

Raises `RuntimeError` if constructed without a `UiInterface`.

## Output

```python
@dataclass
class CoCreationResult:
    story_config: dict    # genre, tier, setting, protagonist, variables, ...
    outline_text: str     # formatted outline string for PromptBuilder
    outline_nodes: list   # structured node data for GameLoop / progress display
```

Pass `CoCreationResult` to `GameSession.start_game()` — it handles
`GameState` creation, `GameLoop` construction, and auto-save wiring.

## Validation

The engine validates all LLM output during generation:
- **story_config:** required fields (genre, tier, label, etc.), tier must be short/medium/long
- **variables:** count caps (≤3 total, ≤2 numeric, ≤1 label), name uniqueness, range [0,100], no illegal chars
- **outline:** all route targets exist, final node has no routes

Failures raise `CoCreationAborted` (state machine catches and returns
`{phase: "error"}`) or trigger auto-retry (legacy `run()` path).

## Reference

- Flow logic: `src/storyloom/core/co_create.py`
- Entry point: `src/storyloom/core/session.py` — `GameSession`
- Variable caps: `src/storyloom/config.py`
- Integration design: `docs/superpowers/specs/2026-07-07-api-audit-and-interface-design.md`
