# CLAUDE.md — Storyloom

> AI context file. Loaded automatically by Claude Code on entering the project.

## Project

Storyloom is an AI-powered interactive text fiction game engine. The LLM is the narrative brain; the program is the flow manager + context steward. It is a **single Python application** (not client-server) — the core engine is UI-agnostic via generator-based event streaming, with a terminal CLI on `main` and a web interface under active parallel development.

**Status (2026-07-10):** Phase 1 core engine implemented (game loop, co-creation, save system, ending detection, i18n). Bridge pre-fetch implemented for auto-advance rounds. Dev CLI (`src/storyloom/dev_cli/`) replaces old `main.py` as the CLI test harness — zero engine changes. Web interface (FastAPI + SSE) under active development on parallel branch.

**Key migrations:**
1. **XML output format** (`<seg>`, `<choice>`, `<bridge/>`, `<branch>`) replaced `--- block ---` delimiters (2026-07-04) — see `src/storyloom/parser/streaming_parser.py`.
2. **Conversation-based architecture** (sliding window + Round 1 anchoring + checkpoint compression) replaced stateless per-round prompts (2026-07-04) — see `src/storyloom/core/context_manager.py` and `src/storyloom/core/prompt_builder.py`.
3. **Line-number format** (`NNN| ` prefix) replaced `<seg n="N">` attribute numbering (2026-07-05) — see `tests/prompt_lab/data/prompts/round1-linenum.txt`.
4. **Bridge pre-fetch** — daemon thread + `queue.Queue` for auto-advance rounds (2026-07-10) — see `src/storyloom/core/game_loop.py` `_launch_api()`.
5. **StreamingXmlParser restored** (2026-07-11) — streaming parse restored and integrated into all API call paths; bridge pre-fetch depends on it for correct timing. See `docs/engineering-journal.md`.

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

Key advantages over old `--- block ---` format: node IDs as attributes prevent suffix appending; `<branch>` as container prevents missing post-choice narratives; `<bridge/>` as unique tag prevents double-bridge misuse. Achieved 100% correctness vs ~20-74% for text blocks in comparative tests.

### Conversation-Based Architecture (current)
Messages array with sliding window + Round 1 anchoring, managed by `ContextManager`:
- **Round 1**: Permanent anchor — full format spec + story context + XML example. NEVER compressed or removed.
- **Sliding window**: Last 3 full rounds kept as complete conversation history (user + assistant).
- **Compression**: Earlier rounds compressed into checkpoint summaries (from `<checkpoint summary="...">`).
- **Round N context**: Lightweight user message (progress, state, bridge_text, errors) — no format spec repetition.
- **Target**: ~50K token context ceiling.

## Document Map

| Document | Role | Authority |
|----------|------|-----------|
| `docs/spec/exec-flow.md` | Phase 1 execution pipeline | **Authoritative** |
| `docs/spec/block-spec.md` | XML element syntax, branch routing, state validation | **Authoritative** |
| `docs/spec/prompt-design.md` | All Prompt templates, conversation architecture, constraints | **Authoritative** |
| `docs/spec/data-model.md` | State, save system, constants | **Authoritative** |
| `docs/engineering-journal.md` | Chronological design decision log (2026-07-02 → present) | Reference |
| `docs/README.md` | Documentation index | — |
| `docs/superpowers/specs/` | Feature design specs (archived by date) | Reference |
| `docs/superpowers/plans/` | Implementation plans (archived by date) | Reference |
| `src/storyloom/core/game_loop.py` | Game loop, GameState, ending detection, serialization | Implementation |
| `src/storyloom/core/context_manager.py` | Messages array, sliding window, compression | Implementation |
| `src/storyloom/core/prompt_builder.py` | Round 1 / Round N prompt content builder | Implementation |
| `src/storyloom/core/co_create.py` | Co-creation flow (Q&A → story_config → outline) | Implementation |
| `src/storyloom/core/save_manager.py` | Atomic JSON save/load/delete/list | Implementation |
| `src/storyloom/core/session.py` | `GameSession` lifecycle coordinator (UI integration API) | Implementation |

| `src/storyloom/parser/streaming_parser.py` | Line-by-line XML parser, data types, LineBuffer | Implementation |
| `src/storyloom/io/api_client.py` | OpenAI-compatible API client | Implementation |
| `src/storyloom/dev_cli/` | Dev CLI — `DevObserver`, deque-buffered display | Reference |
| `src/storyloom/config.py` | Configurable constants (window size, segments, etc.) | Implementation |
| `src/storyloom/i18n.py` | gettext i18n (zh-CN, en) | Implementation |
| `tests/test_*.py` | Unit tests (mock, no API) | Test |
| `tests/prompt_lab/data/prompts/round1-linenum.txt` | Authoritative prompt format standard | **Standard** |

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
| `src/storyloom/web/` | **Web UI package** (FastAPI + SSE) — recommended location |

### 🧪 Tests

Each team owns their test files. UI adds `tests/test_web_*.py`; does not modify `tests/test_game_loop.py`, `tests/test_co_create.py`, `tests/test_session.py`, etc.

### 📦 Package Exports

- `from storyloom.core import GameSession` — preferred import path for UI
- `from storyloom import GameSession` — also available via top-level package

## Tech Stack

- **Language:** Python 3.10+ (standard library preferred)
- **Interface:** Terminal CLI (test/maintenance tool on `main`), FastAPI + SSE web (primary UI, active parallel development)
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
