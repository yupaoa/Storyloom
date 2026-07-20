# Storyloom

> AI-powered interactive text fiction engine — the LLM narrates, the engine orchestrates.
>
> [中文版本](./README.zh-CN.md)

Storyloom turns a large language model into a game master. You and the AI collaboratively build a story world, define characters and game mechanics, then play through a branching narrative where your choices shape the outcome. The engine handles state management, context window stewardship, and real-time streaming — the LLM focuses on telling a great story.

**Status (2026-07-19):** Phase 1 core engine complete. Playable via dev CLI or web UI.

## Highlights

- **Seamless narration** — The bridge pre-fetch mechanism fires the next API call mid-paragraph, hiding LLM latency behind the current text. No "waiting for response" pauses between segments.
- **Local source of truth** — All game state lives in the engine. The LLM *suggests* changes; the engine validates (type checks, range checks) before applying. Rejected suggestions feed back as corrections.
- **Two-layer branching** — Intra-segment narrative branches (player choices within a scene) and outline-level route forks (story-direction changes at checkpoints). One is reversible, the other isn't.
- **Conversation-based context** — Sliding window of recent rounds + permanent Round 1 anchor + checkpoint compression. Fits a long-running game in ~50K tokens without losing coherence.
- **Streaming XML output** — The LLM emits `<seg>`, `<choice>`, `<bridge/>`, `<set>`, `<checkpoint>` elements in a `<story>` document. Parsed line-by-line — no buffering, no waiting for the full response.
- **Co-creation flow** — Not just "pick a genre." The AI interviews you about your story idea, then generates a tailored world, protagonist, game variables, and plot outline before play begins.

## Quick Start

```bash
# Install
pip install -e .

# Configure — edit config.json with your API credentials
# (created automatically on first run, or create it manually)
cat > config.json << 'EOF'
{
  "api_key": "sk-your-key-here",
  "api_base_url": "https://api.deepseek.com",
  "api_model": "deepseek-v4-pro",
  "language": "zh-CN"
}
EOF

# Play (CLI)
python -m storyloom.dev_cli

# Play (Web UI)
python -m storyloom.web          # → http://127.0.0.1:8000
```

Any OpenAI-compatible API works — DeepSeek, OpenAI, local llama.cpp, etc. Set `api_base_url` and `api_model` to match your provider.

See [`src/storyloom/dev_cli/README.md`](./src/storyloom/dev_cli/README.md) for CLI controls and observer mode.

### Packaging (Web UI)

Build a standalone executable + pip wheel for distribution:

```bash
./scripts/build.sh
```

Output in `dist/storyloom-web-v{VERSION}/`:

| File | Use |
|------|-----|
| `storyloom-web` | Standalone binary — download and run (no Python needed) |
| `locale/` | i18n files — keep next to the binary |
| `*.whl` | pip package — `pip install storyloom-*.whl` → `storyloom-web` command |

Requires `build` + `pyinstaller` (installed automatically by the script).

## Architecture

Storyloom is a **single Python application** — not a client-server system. The core engine is UI-agnostic, exposing a generator-based event stream consumed by any presentation layer through `GameSession`.

```
┌─────────────────────────────────────────────────┐
│              Storyloom Core Engine              │
│  ┌──────────┐  ┌───────────┐  ┌──────────────┐  │
│  │GameLoop  │  │ContextMgr │  │StreamXmlPrs  │  │
│  └──────────┘  └───────────┘  └──────────────┘  │
│  ┌──────────┐  ┌───────────┐  ┌──────────────┐  │
│  │PromptBldr│  │CoCreate   │  │SaveManager   │  │
│  └──────────┘  └───────────┘  └──────────────┘  │
└─────────────────────┬───────────────────────────┘
                      │ GameSession (public API)
              ┌───────┴────────┐
              ▼                ▼
       ┌──────────┐    ┌──────────────┐
       │ Dev CLI  │    │  Web UI      │
       └──────────┘    └──────────────┘
```

### How a round works

```
Player reads text ──→ makes choice ──→ engine sends prompt ──→ LLM streams XML
                                                                       │
                    ┌──────────────────────────────────────────────────┘
                    ▼
            StreamingXmlParser (line-by-line)
                    │
       ┌────────────┼────────────┬────────────┐
       ▼            ▼            ▼            ▼
    <seg>        <choice>    <bridge/>     <set>
    display      present     fire next     validate &
    narrative    options     API call      apply state
```

The `<bridge/>` element triggers the next API request while the remaining text is still being displayed — the player sees continuous narration with no segment-boundary pauses.

## Module Map

| Module | Purpose |
|--------|---------|
| `storyloom.core.game_loop` | Narrative loop, round orchestration, ending detection, state validation |
| `storyloom.core.context_manager` | Messages array, sliding window, checkpoint compression |
| `storyloom.core.prompt_builder` | Round 1 / Round N prompt assembly |
| `storyloom.core.co_create` | Co-creation flow (Q&A → story config → outline) |
| `storyloom.core.save_manager` | Atomic JSON save/load/delete per game directory |
| `storyloom.core.session` | `GameSession` lifecycle coordinator — UI integration API |
| `storyloom.parser.streaming_parser` | Line-by-line XML parser for LLM output |
| `storyloom.io.api_client` | OpenAI-compatible streaming/non-streaming client |
| `storyloom.i18n` | gettext internationalization (zh-CN, en) |
| `storyloom.user_config` | Centralized config via `config.json` (API keys, language, model) |
| `storyloom.dev_cli` | Terminal interface — play mode + dev observer |

## Documentation

| Document | What it covers |
|----------|---------------|
| [`docs/spec/exec-flow.md`](./docs/spec/exec-flow.md) | Phase 1 execution pipeline — **authoritative** |
| [`docs/spec/block-spec.md`](./docs/spec/block-spec.md) | XML element syntax, branch routing, state validation |
| [`docs/spec/prompt-design.md`](./docs/spec/prompt-design.md) | Prompt templates & conversation architecture |
| [`docs/spec/data-model.md`](./docs/spec/data-model.md) | GameState, save system, config constants |
| [`docs/engineering-journal.md`](./docs/engineering-journal.md) | Design decision log (2026-07-02 → present) |
| [`docs/README.md`](./docs/README.md) | Full documentation index |

## Development

```bash
# Run tests (mock — no API key needed)
pytest --ignore=tests/test_api_client.py

# Run all tests including API tests
pytest

# Run a specific test file
pytest tests/test_game_loop.py -v
```

**Tech stack:** Python 3.10+ (standard library preferred), OpenAI-compatible API, local JSON storage, gettext i18n.

**Conventions:** Conventional Commits, English code comments & git messages, Chinese prompt variables.

### API for UI integration

UI developers interact with the engine through `GameSession`:

```python
from storyloom.core import GameSession

session = GameSession()

# Co-creation
flow = session.new_co_create()
event = flow.start()                     # → {"phase": "awaiting_idea", "prompt": "..."}
reply = flow.send("a cyberpunk story")   # → "That sounds exciting! Tell me more..."
# ... continue Q&A, then generate when ready ...
result = flow.generate()                 # → CoCreationResult
gl, game_id = session.start_game(result) # → (GameLoop, game_id)

# Narrative loop
gl.start_game()                          # launches round 1 API call
gen = gl.stream_round()
for event in gen:
    ...  # handle token / segment / options / state / error / done
    if event["type"] == "options":
        gen.send("1")                    # resume with chosen option

# Save & load
saves = session.list_saves(game_id)
gl = session.load_game(game_id, "_init.json")
```

## Roadmap

- [x] Phase 1 core engine — game loop, co-creation, saving, ending detection, i18n
- [x] Bridge pre-fetch for seamless narration
- [x] Conversation-based context with sliding window + compression
- [x] Streaming XML parser with line-by-line output
- [x] UserConfig — centralized config management
- [ ] Web UI (FastAPI + SSE) — main menu, settings, credits; gameplay views in progress
- [ ] Phase 2 — image mode support (static backgrounds + character sprites), co-creation presets + partial real-time generation
- [ ] Phase 3 — full image mode support, visual quality on par with mainstream visual novel games

## License

MIT
