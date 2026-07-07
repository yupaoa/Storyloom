# Storyloom

> AI-powered interactive text fiction game engine — the LLM narrates, the engine orchestrates.

**Current status:** Phase 1 core implemented. Terminal CLI available on `main`. Web interface under active development on parallel branch — dual-developer collaboration; the UI layer was prioritized ahead of the original phased roadmap.

## Architecture

Storyloom is a **single Python application** — not a client-server system.
The core engine is UI-agnostic: it produces structured events consumed by
any presentation layer via the `UiInterface` protocol.

```
┌──────────────────────────────────────────────┐
│           Storyloom Core Engine               │
│  ┌──────────┐ ┌───────────┐ ┌─────────────┐  │
│  │GameLoop  │ │ContextMgr │ │XmlParser     │  │
│  └──────────┘ └───────────┘ └─────────────┘  │
│  ┌──────────┐ ┌───────────┐ ┌─────────────┐  │
│  │PromptBldr│ │CoCreate   │ │GameState     │  │
│  └──────────┘ └───────────┘ └─────────────┘  │
└──────────────────┬───────────────────────────┘
                   │ UiInterface (protocol)
           ┌───────┴───────┐
           ▼               ▼
    ┌────────────┐  ┌─────────────────┐
    │  CLI (main)│  │ Web (并行开发中) │
    │  测试/维护  │  │ 用户交互界面     │
    └────────────┘  └─────────────────┘
```

## Quick Start

```bash
# Install
pip install -e .
cp .env.example .env    # add your API key

# Run
storyloom
# or: python -m storyloom.main
```

## How It Works

### Co-Creation Phase
Player and LLM collaboratively define the story world, protagonist, game
variables, and outline (a directed graph of milestone nodes). The result is
a `story_config` dict and `outline_text` string — fed directly into `GameLoop`.

### Narrative Loop
Each round:
1. The engine assembles context — outline progress, conversation history,
   state snapshot, and bridge text from the previous round.
2. The LLM generates an XML story segment (`<story>...</story>`).
3. The engine parses and validates the XML, displays narrative segments,
   presents player choices, and applies state changes.
4. At the `<bridge/>` marker, the engine fires the next API request while the
   tail text is still being displayed — the player perceives seamless narration.

### Key Design Principles

| Principle | Description |
|-----------|-------------|
| **Conversation-based context** | Sliding window (last 3 rounds) + Round 1 anchor + checkpoint compression. Managed by `ContextManager`. |
| **XML output format** | `<seg>`, `<choice>`, `<set>`, `<checkpoint>`, `<bridge/>` elements in a `<story>` root. Parsed by `XmlParser`. |
| **Bridge preloading** | `<bridge/>` triggers the next API call mid-display, hiding segment boundaries from the player. |
| **Local source of truth** | All game state lives in `GameState`. The LLM only *suggests* changes via `<set>`; the engine validates before applying. |

## Module Map

| Module | Purpose |
|--------|---------|
| `storyloom.core.game_loop` | Main narrative loop, round orchestration, ending detection |
| `storyloom.core.context_manager` | Messages array, sliding window, checkpoint compression |
| `storyloom.core.prompt_builder` | Round 1 / Round N prompt assembly |
| `storyloom.core.co_create` | Co-creation flow (Q&A → story_config → outline) |
| `storyloom.core.save_manager` | Atomic JSON save/load/delete/list |
| `storyloom.core.ui_interface` | `UiInterface` protocol for UI-agnostic design |
| `storyloom.parser.xml_parser` | LLM XML output parsing (full document) |
| `storyloom.parser.streaming_parser` | Real-time streaming XML parse |
| `storyloom.io.api_client` | OpenAI-compatible API client (stream + non-stream) |
| `storyloom.io.display` | Terminal display (CLI) |
| `storyloom.i18n` | Internationalization via gettext (.po/.mo) |

## Documentation

| Document | Purpose |
|----------|---------|
| [`docs/spec/exec-flow.md`](./docs/spec/exec-flow.md) | Phase 1 execution pipeline (**authoritative**) |
| [`docs/spec/block-spec.md`](./docs/spec/block-spec.md) | XML element syntax, branch routing, state validation |
| [`docs/spec/prompt-design.md`](./docs/spec/prompt-design.md) | Prompt templates & conversation architecture |
| [`docs/spec/data-model.md`](./docs/spec/data-model.md) | GameState, save system, constants |
| [`docs/README.md`](./docs/README.md) | Full documentation index |

## Tech Stack

- **Language:** Python 3.10+
- **LLM API:** OpenAI-compatible (configurable via `.env`)
- **Interface:** Terminal CLI (test/maintenance tool on `main`); web UI (primary user interface, active development on parallel branch)
- **Storage:** Local JSON files in `saves/` directory
- **i18n:** gettext (.po/.mo files)

## Development

```bash
# Run tests (mock — no API key needed)
pytest

# CLI with per-round debug output
python -m storyloom.main --debug

# Run a specific test file
pytest tests/test_game_loop.py -v
```
