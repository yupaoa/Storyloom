# GameSession API

> **Audience:** UI developers integrating the Storyloom engine.
> **Authoritative spec:** `docs/spec/exec-flow.md`

`GameSession` is the sole entry point for UI layers to interact with the engine.
It coordinates co-creation, game lifecycle, save/load, and session management.

## Quick Start

```python
from storyloom.core import GameSession, CoCreateError

session = GameSession()

# ── Co-creation ──────────────────────────────────────────
flow = session.new_co_create()
event = flow.start()                     # → {"phase": "awaiting_idea", "prompt": "..."}
reply = flow.send("a cyberpunk story")   # → LLM follow-up question
# ... more Q&A turns ...
result = flow.generate()                 # → CoCreationResult
gl, game_id = session.start_game(result) # → (GameLoop, game_id)

# ── Narrative loop ───────────────────────────────────────
gen = gl.stream_round()                  # returns generator immediately
for event in gen:                        # yields events as they arrive
    ...  # handle token / segment / options / state / error / done
    if event["type"] == "options":
        gen.send("1")                    # resume with chosen option

# ── Save & load ──────────────────────────────────────────
saves = session.list_saves(game_id)
gl = session.load_game(game_id, "_init.json")

# ── Co-creation retry ────────────────────────────────────
try:
    reply = flow.send(user_input)
except CoCreateError as e:
    if e.phase == "send":
        reply = flow.retry_send()        # re-calls API with same messages
```

## Co-Creation Flow

`CoCreateFlow` exposes a state machine: `init → awaiting_idea → awaiting_answer → complete` (or `aborted`).

| Method | Description |
|--------|-------------|
| `flow.start() → dict` | Begin co-creation. Returns `{"phase": "awaiting_idea", "prompt": "..."}` |
| `flow.send(user_input) → str` | Forward message to LLM, return reply. Pure forward — no keyword detection. |
| `flow.generate() → CoCreationResult` | Inject generation prompt, call LLM, parse story_config + variables + outline |
| `flow.abort()` | Abort co-creation immediately |
| `flow.retry_send() → str` | Re-attempt failed `send()` with same messages |
| `flow.retry_generate() → CoCreationResult` | Re-attempt failed `generate()` (adds correction for parse failures) |

See `docs/api/co-create.md` for the full co-creation API reference.

## Narrative Loop

`GameLoop.stream_round()` returns a generator. Each yielded event has a `type` field:

| Event type | Description |
|------------|-------------|
| `token` | Raw text chunk from LLM (for streaming display) |
| `segment` | Parsed narrative segment ready for display |
| `options` | Player choice point — send choice number via `gen.send("1")` |
| `state` | State variable update |
| `error` | Recoverable error — UI decides retry/return |
| `done` | Round complete |
| `ending` | Story has ended — adventure log available |

## Save Management

| Method | Description |
|--------|-------------|
| `session.list_games() → list` | List all saved games |
| `session.list_saves(game_id) → list` | List save files in a game |
| `session.load_game(game_id, filename) → GameLoop` | Restore game from save |
| `session.delete_game(game_id)` | Delete game and all its saves |
| `session.delete_save(game_id, filename)` | Delete a single save file |

## Reference

| Resource | Content |
|----------|---------|
| `src/storyloom/core/session.py` | `GameSession` implementation |
| `src/storyloom/core/co_create.py` | `CoCreateFlow` implementation |
| `src/storyloom/core/game_loop.py` | `GameLoop` implementation |
| `docs/api/co-create.md` | Co-creation API reference |
| `docs/spec/exec-flow.md` | Execution pipeline spec |
