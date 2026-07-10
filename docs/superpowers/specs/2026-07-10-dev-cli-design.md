# Dev CLI — Minimal CLI Development Tool

> Design doc. 2026-07-10.

## Purpose

A minimal, self-contained CLI UI layer for Storyloom that serves dual purposes:

1. **Minimal game UI** — a complete, playable CLI that exercises the full `UiInterface` protocol and `GameSession` lifecycle, proving the engine works end-to-end with zero UI coupling.
2. **Developer inspection** — silently records raw prompts, LLM responses, and engine check data to files for debugging prompt design and parser behavior.

The entire package can be deleted without affecting the engine core.

## Scope

- Single independent package: `src/storyloom/dev_cli/`
- One-way dependency: `dev_cli` imports `storyloom.core`; engine never imports `dev_cli`
- No modification to any engine file
- Must support: full co-creation flow, full game loop (Round 1 → N → ending), save/load
- Output files append across sessions; `dev_output/` is gitignored

## Architecture

```
src/storyloom/dev_cli/
├── __init__.py      # dev_main() entry point
├── args.py          # CLI argument parsing
├── ui.py            # TerminalUi (implements UiInterface) + game flow driver
└── observer.py      # DevObserver — writes raw data to files
```

### Module: `args.py`

Parse `sys.argv` into a typed config object.

```
Usage: python -m storyloom.dev_cli [options]

  --mode normal|dev    Default: dev
                       normal = pure game, no data recording
                       dev    = record raw data to dev_output/

  --story <file>       JSON file (CoCreationResult serialized form).
                       Skips co-creation when provided.

  --no-save            Disable auto-save on checkpoints.

  --lang zh-CN|en      UI language. Default: zh-CN.
```

### Module: `ui.py`

**`TerminalUi`** — implements `UiInterface` protocol.

```python
class TerminalUi:
    def write(self, text: str) -> None:
        """Display narrative text to stdout."""
        print(text)

    def show_error(self, text: str) -> None:
        """Display error to stderr."""
        print(f"[Error] {text}", file=sys.stderr)

    def ask(self, prompt: str) -> str:
        """Ask user for input. Returns trimmed response."""
        print(prompt)
        return input("> ").strip()
```

**Game flow driver** — static/standalone functions that drive the full lifecycle:

```
run_co_create(ui, session) -> CoCreationResult | None
    Drives the Q&A loop. Returns None if user quits.

run_game(ui, game_loop, dev_observer=None) -> None
    Consumes stream events from start_round1_stream() / continue_round_stream().
    Displays narrative segments, choices. Handles user input.
    Passes RoundRecord to dev_observer when present.
    Exits on ending, Ctrl+C, or 'q' input.

dev_main() -> None
    Top-level entry point. Parses args, creates TerminalUi + GameSession,
    optionally loads --story JSON, runs co-create + game, handles cleanup.
```

**Stream event handling in `run_game()`:**

| Event type | Action |
|---|---|
| `token` | (ignored — no per-token display in minimal mode) |
| `segment` | `ui.write(segment["text"])` |
| `options` | Print `[1] branch_a  [2] branch_b  [q] quit` |
| `state` | (ignored in display; recorded by observer) |
| `error` | `ui.show_error(event["message"])` |
| `done` | Record round, check ending flag, loop |

**Choice input handling:**
- Display: `[1] Option text  [q] Quit`
- Accept: `1`, `2`, ... (digit) or `q` / `quit` / `exit`
- `Ctrl+C` → treat as quit, prompt save
- Invalid input → re-prompt

**Co-creation Q&A loop:**
- Uses `CoCreateFlow.start()` and `CoCreateFlow.send()` API
- Display LLM questions via `ui.write()`, collect answers via `ui.ask()`
- Detect start keywords ("开始", "ok", "yes", ...) to trigger final generation
- Detect quit keywords ("退出", "quit", ...) to abort

### Module: `observer.py`

**`DevObserver`** — writes structured data to files.

```python
class DevObserver:
    def __init__(self, output_dir: str = "dev_output"):
        self._dir = Path(output_dir)
        # Ensure directory exists

    def record_round(self, record: RoundRecord) -> None:
        """Called after each round completes. Appends to all three files."""
        self._append_prompt(record)
        self._append_response(record)
        self._append_check(record)
```

**Output files** (always these three, always append):

| File | Content |
|---|---|
| `dev_output/prompts.txt` | Full user messages sent to LLM each round (with round headers) |
| `dev_output/responses.txt` | Raw LLM response text each round (with round headers) |
| `dev_output/checks.txt` | Parsed summary: segments, bridge, checkpoint, sets, choices, routes, tokens, ttft |

File format — round-delimited sections, append-only:

```
prompts.txt:
── Round 1 ── 2026-07-10T14:32:01Z ──
[full prompt content]

── Round 2 ── 2026-07-10T14:32:45Z ──
[full prompt content]

responses.txt:
── Round 1 ── 2026-07-10T14:32:01Z ── ttft=2.3s tokens=prompt:1200,completion:800,total:2000 ──
[raw LLM response]

checks.txt:
── Round 1 ── 2026-07-10T14:32:01Z ──
Node: ch1_intro | Branch: (none)
Segments: 15 total (pre=10, post=5) | Bridge: ✓
Checkpoint: ch2_meeting → ['ch3_chase'] | Summary: ...
Sets: 体力 +5 ✓ | 信任度 =20 ✓
Choice: choice_1 → ['branch_a', 'branch_b']
TTFT: 2.3s | Tokens: prompt=1200 completion=800 total=2000
```

## Data Flow

```
User input ──▶ TerminalUi (UiInterface) ──▶ stdout/stderr
                    │
                    │ calls
                    ▼
           GameSession / GameLoop  (engine core — unchanged)
                    │
                    │ observer callback
                    ▼
           DevObserver ──▶ dev_output/*.txt  (append, flush)
           (dev mode only)
```

## Game Lifecycle in dev_cli

```
dev_main()
  ├─ parse_args()
  ├─ init_i18n(lang)
  ├─ TerminalUi()
  ├─ GameSession()
  ├─ if --story:
  │    load JSON → CoCreationResult
  │  else:
  │    run_co_create(ui, session) → CoCreationResult
  ├─ game_loop = session.start_game(result)
  ├─ if --no-save:
  │    game_loop.set_save_manager(None)  # disable auto-save
  ├─ if mode=dev:
  │    observer = DevObserver()
  │    game_loop._observers.append(observer.record_round)
  └─ run_game(ui, game_loop, observer)
```

## Gitignore

```
# Dev CLI output (generated at runtime)
dev_output/
```

## Non-Goals

- No per-token streaming display (minimal mode shows completed segments only)
- No syntax highlighting or rich terminal formatting
- No save/load UI commands during gameplay (use --no-save or auto-save)
- No modification to engine core files
- No dependency on test code or test data

## Engine Issues Found

None. The dev CLI accesses `GameLoop._observers` (private attribute, Python convention only) to register the `DevObserver` — zero engine modifications needed.
