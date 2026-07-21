# Storyloom

> AI-powered interactive text fiction engine — the LLM narrates, the engine orchestrates.
>
> [中文版本](./README.zh-CN.md)

Storyloom turns a large language model into a game master. You and the AI collaboratively build a story world, define characters and game mechanics, then play through a branching narrative where your choices shape the outcome. The engine handles state management, context window stewardship, and real-time streaming — the LLM focuses on telling a great story.

**Status (2026-07-21):** Phase 1 core engine complete. Version 1.0.0. Playable via dev CLI or web UI (FastAPI + SSE single-page app). Standalone binary + pip wheel packaging via `scripts/build.sh`.

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

# Configure — copy config.example.json to config.json and edit
cp config.example.json config.json
# Edit config.json with your API credentials

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
│  ┌──────────┐  ┌───────────┐                    │
│  │ApiClient │  │UserConfig │                    │
│  └──────────┘  └───────────┘                    │
└─────────────────────┬───────────────────────────┘
                      │ GameSession (public API)
              ┌───────┴────────┐
              ▼                ▼
       ┌──────────┐    ┌──────────────┐
       │ Dev CLI  │    │  Web UI      │
       │(terminal)│    │(FastAPI+SSE) │
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

The `<bridge/>` element triggers the next API call mid-paragraph, hiding LLM latency behind the current text display.

The engine is organized into `storyloom.core` (game loop, context management, prompt building, co-creation, save system), `storyloom.parser` (XML parsing), `storyloom.io` (API client), and `storyloom.user_config` (config management). The UI layer — `storyloom.web` (FastAPI + SSE + SPA) and `storyloom.dev_cli` (terminal) — imports from `storyloom.core` via `GameSession`. See `CLAUDE.md` for the complete file ownership map.

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

**Tech stack:** Python 3.10+ (standard library preferred), OpenAI-compatible API, local JSON storage, gettext i18n. Web: FastAPI + SSE + vanilla JS SPA. Packaging: PyInstaller + pip wheel.

**Conventions:** Conventional Commits, English code comments & git messages, Chinese prompt variables.

**Tests:** pytest tests (mock, no API key needed). `pytest --ignore=tests/test_api_client.py` for engine-only tests.

### Web API

The web server exposes REST + SSE endpoints for config, co-creation, game streaming, and save management. See `src/storyloom/web/server.py` for the complete endpoint reference.

### API for UI integration

UI developers interact with the engine through `GameSession` — the sole public API surface.
See [`docs/api/session.md`](./docs/api/session.md) for a complete usage guide with code examples,
and [`docs/api/co-create.md`](./docs/api/co-create.md) for the co-creation API reference.

## Roadmap

- [x] Phase 1 core engine — game loop, co-creation, saving, ending detection, i18n
- [x] Bridge pre-fetch for seamless narration
- [x] Conversation-based context with sliding window + compression
- [x] Streaming XML parser with line-by-line output
- [x] UserConfig — centralized config management
- [x] Web UI (FastAPI + SSE) — main menu, co-create chat, game view, adventure log, settings, credits
- [x] Packaging — standalone binary (PyInstaller) + pip wheel via `scripts/build.sh`
- [ ] Phase 2 — image mode support (static backgrounds + character sprites), co-creation presets + partial real-time generation, vector memory for characters/locations
- [ ] Phase 3 — full image mode, visual quality on par with mainstream visual novel games, cloud sync, TTS, script export

## License

MIT
