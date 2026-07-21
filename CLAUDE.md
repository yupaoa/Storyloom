# CLAUDE.md — Storyloom

> AI context file. Loaded automatically by Claude Code on entering the project.

## Project

Storyloom is an AI-powered interactive text fiction game engine. The LLM is the narrative brain; the program is the flow manager + context steward. It is a **single Python application** (not client-server) — the core engine is UI-agnostic via generator-based event streaming, with a terminal CLI on `main` and a web interface under active parallel development.

**Status (2026-07-21):** Phase 1 core engine implemented (game loop, co-creation, save system, ending detection, i18n). Per-game directory save system with append-only checkpoint files. Dev CLI (`src/storyloom/dev_cli/`) as CLI test harness. Web interface (FastAPI + SSE) fully functional — main menu, co-create chat, game view, adventure log, settings — single-page app with hash router. Packaging: `scripts/build.sh` produces standalone binary (PyInstaller) + pip wheel. Version 1.0.0.

**Key architectural decisions** (see `docs/engineering-journal.md` for the full timeline):

- **XML output format** — `<story>` document with `<seg>`, `<choice>`, `<bridge/>`, `<set>`, `<checkpoint>`, `<branch>` elements. `NNN|` line-number prefix. Parsed line-by-line by `StreamingXmlParser`. Spec: `docs/spec/block-spec.md`.
- **Conversation-based context** — Messages array with permanent Round 1 anchor (format spec + story context) + sliding window (last 3 rounds) + checkpoint compression for earlier rounds. Spec: `docs/spec/prompt-design.md`.
- **Bridge pre-fetch** — Background daemon thread + queue auto-advances rounds while current text displays. Hides LLM latency behind post-bridge narration.
- **UserConfig** — Centralized `config.json` management via `src/storyloom/user_config.py`.
- **Web UI** — FastAPI + SSE single-page app (main menu, co-create, game view, adventure log). See `src/storyloom/web/`.
- **Packaging** — `scripts/build.sh` produces standalone binary (PyInstaller) + pip wheel.

## Core Design Concepts

These are the foundational ideas. The authoritative spec is `docs/spec/exec-flow.md`.

### Bridge Mechanism
Each story segment contains a `<bridge/>` marker. When the program reaches it during parsing, it immediately submits the next round's prompt to the LLM — while continuing to display the tail text after the bridge. The player perceives continuous narration with no segment boundary pauses.

### Two-Layer Branching
- **Intra-segment branching** (`<branch>` containers): Narrative variants within one segment. Player choices route to different `<branch name="...">` blocks via `<opt branch="...">`. Does NOT affect the outline.
- **Outline branching** (`<route>` elements): Story-direction forks at checkpoint nodes. The program evaluates conditions against local state and routes to different outline nodes. Irreversible.

### Local Source of Truth
All game data lives in a local `GameState` object. The LLM can only *suggest* changes via `<set>` elements. The program validates each suggestion — type checks, range checks, variable existence — before applying. Rejected changes are fed back to the LLM in the next round.

### XML Output Format (current, replacing `--- block ---`)
LLM output is an XML document (`<story>...</story>`) containing `<seg>`, `<choice>`, `<set>`, `<checkpoint>`, `<bridge/>`, and `<branch>` elements. Parsed line-by-line by `StreamingXmlParser` (streaming). Full spec: `docs/spec/block-spec.md`.

Key advantages over old `--- block ---` format: node IDs as attributes prevent suffix appending; `<branch>` as container prevents missing post-choice narratives; `<bridge/>` as unique tag prevents double-bridge misuse.

### Conversation-Based Architecture (current)
Messages array with sliding window + Round 1 anchoring, managed by `ContextManager`:
- **Round 1**: Permanent anchor — full format spec + story context + XML example. NEVER compressed or removed.
- **Sliding window**: Last 3 full rounds kept as complete conversation history (user + assistant).
- **Compression**: Earlier rounds compressed into checkpoint summaries (from `<checkpoint summary="...">`).
- **Round N context**: Lightweight user message (progress, state, bridge_text, errors) — no format spec repetition.
- **Target**: ~50K token context ceiling.

## Documentation

Full documentation index with reading order and authority hierarchy: [`docs/README.md`](./docs/README.md).

| Document | Role |
|----------|------|
| `docs/spec/exec-flow.md` | Execution pipeline — **authoritative** |
| `docs/spec/block-spec.md` | XML element syntax — **authoritative** |
| `docs/spec/prompt-design.md` | Prompt templates — **authoritative** |
| `docs/spec/data-model.md` | Data model & constants — **authoritative** |
| `docs/engineering-journal.md` | Design decision log |
| `docs/api/co-create.md` | Co-creation API reference |
| `docs/api/session.md` | GameSession integration API |
| `docs/superpowers/specs/` | Feature design specs (archived) |
| `docs/superpowers/plans/` | Implementation plans (archived) |
| `src/storyloom/core/game_loop.py` | Game loop, GameState, ending detection, serialization | Implementation |
| `src/storyloom/core/context_manager.py` | Messages array, sliding window, compression | Implementation |
| `src/storyloom/core/prompt_builder.py` | Round 1 / Round N prompt content builder | Implementation |
| `src/storyloom/core/co_create.py` | Co-creation flow (Q&A → story_config → outline) | Implementation |
| `src/storyloom/core/save_manager.py` | Atomic JSON save/load/delete/list | Implementation |
| `src/storyloom/core/session.py` | `GameSession` lifecycle coordinator (UI integration API) | Implementation |

| `src/storyloom/parser/streaming_parser.py` | Line-by-line XML parser, data types, LineBuffer | Implementation |
| `src/storyloom/io/api_client.py` | OpenAI-compatible API client | Implementation |
| `src/storyloom/web/` | Web UI (FastAPI + SSE + SPA) — server, sessions, static frontend | Implementation |
| `src/storyloom/dev_cli/` | Dev CLI — `DevObserver`, deque-buffered display | Reference |
| `src/storyloom/config.py` | Configurable constants (window size, segments, etc.) | Implementation |
| `src/storyloom/user_config.py` | UserConfig — centralized config management (API keys, language, model) | Implementation |
| `src/storyloom/i18n.py` | gettext i18n (zh-CN, zh-TW, en) | Implementation |
| `scripts/build.sh` | PyInstaller + wheel packaging script | Build |
| `pyproject.toml` | Project metadata, dependencies, entry points, package data | Config |
| `tests/test_*.py` | pytest unit tests (mock, no API) | Test |
| `tests/test_web_server.py` | Web server integration tests | Test |

**Test structure:** `tests/test_*.py` = pytest unit tests (mock, no API). `tests/prompt_lab/` = ad-hoc prompt design tools (require API key).

## File Ownership & Modification Rules

> **Rationale:** Dual-developer setup (engine + UI) requires clear boundaries to prevent merge conflicts and unintended coupling. Each layer has exclusive modification rights over its files.

### 🔒 Engine Core — UI MUST NOT modify

These files implement the narrative engine. UI imports them but never edits them:

| File | Contains |
|------|----------|
| `src/storyloom/core/game_loop.py` | `GameLoop`, `GameState`, `RoundRecord` |
| `src/storyloom/core/co_create.py` | `CoCreateFlow`, `CoCreationResult`, `CoCreateParser` |
| `src/storyloom/core/context_manager.py` | `ContextManager` — sliding window, compression |
| `src/storyloom/core/prompt_builder.py` | `PromptBuilder` — Round 1 / Round N prompts |
| `src/storyloom/core/save_manager.py` | `SaveManager` — atomic JSON save/load/delete |
| `src/storyloom/parser/streaming_parser.py` | `StreamingXmlParser`, `ParsedOutput`, data types |
| `src/storyloom/io/api_client.py` | `ApiClient` — OpenAI-compatible API |
| `src/storyloom/config.py` | Configurable constants |
| `src/storyloom/i18n.py` | gettext i18n |

### 📖 Engine API — UI can IMPORT, must NOT modify

These are the public API surface for UI integration:

| File | Contains |
|------|----------|
| `src/storyloom/core/session.py` | `GameSession` — lifecycle coordinator |

UI imports: `from storyloom.core import GameSession, CoCreationResult`

### 🎨 UI Territory — Engine MUST NOT depend on

Engine code must never import from these files:

| File | Contains |
|------|----------|
| `src/storyloom/dev_cli/` | **Dev CLI** — `DevObserver` + `game_driver` |
| `src/storyloom/web/` | **Web UI** — FastAPI server + SSE + SPA frontend (static HTML/CSS/JS) |
| `tests/test_web_server.py` | Web server integration tests |

### 🧪 Tests

Each team owns their test files. UI adds `tests/test_web_*.py`; does not modify `tests/test_game_loop.py`, `tests/test_co_create.py`, `tests/test_session.py`, etc.

### 📦 Package Exports

- `from storyloom.core import GameSession` — preferred import path for UI
- `from storyloom import GameSession` — also available via top-level package
- `from storyloom.core import CoCreateFlow, CoCreationResult, CoCreateError` — co-creation API
- `from storyloom import UserConfig` — centralized config management

## Tech Stack

- **Language:** Python 3.10+ (standard library preferred)
- **Interface:** Terminal CLI (test/maintenance tool), FastAPI + SSE web (primary UI, single-page app)
- **LLM:** OpenAI-compatible API (abstracted behind common interface)
- **Storage:** Local JSON files in `saves/` directory
- **i18n:** gettext (.po/.mo)

## Conventions

- **Conversation:** Chinese (对话用中文)
- **Code comments & git commits:** English
- **Git commits:** Conventional Commits (feat/fix/docs/refactor)
- **Prompt language:** English for all system/narrative prompts (per authoritative `tests/prompt_lab/data/prompts/round1-linenum.txt`). Output language determined by `story_config.language`.
- **XML element names:** English (`<seg>`, `<checkpoint>`, `<bridge/>`, etc.)
- **Variable names in prompts:** Chinese (state variable names, choice names)
- **Config constants:** Defined in `src/storyloom/config.py`, referenced by name — no hardcoded values in business logic
