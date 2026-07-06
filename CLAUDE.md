# CLAUDE.md — Storyloom

> AI context file. Loaded automatically by Claude Code on entering the project.

## Project

Storyloom is an AI-powered interactive text fiction game engine. The LLM is the narrative brain; the program is the flow manager + context steward + dual-end interface. Currently in design/specification phase — no production code yet.

**Implementing (2026-07-04):** Both major migrations are now complete.
1. **XML output format** (`<seg>`, `<choice>`, `<bridge/>`, `<branch>`) replaced `--- block ---` delimiters — see `src/storyloom/xml_parser.py`.
2. **Conversation-based architecture** (sliding window + Round 1 anchoring + checkpoint compression) replaced stateless per-round prompts — see `src/storyloom/context_manager.py` and `src/storyloom/prompt_builder.py`.

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
LLM output is an XML document (`<story>...</story>`) containing `<seg>`, `<choice>`, `<set>`, `<checkpoint>`, `<bridge/>`, and `<branch>` elements. Parsed by `XmlParser` via `xml.etree.ElementTree`. Full spec: `docs/spec/block-spec.md`.

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
| `docs/design.md` | Vision, architecture, phased roadmap | Advisory |
| `docs/spec/exec-flow.md` | Phase 1 execution pipeline | **Authoritative** |
| `docs/spec/block-spec.md` | XML element syntax, branch routing, state validation | **Authoritative** |
| `docs/spec/prompt-design.md` | All Prompt templates, conversation architecture, constraints | **Authoritative** |
| `docs/spec/data-model.md` | State, save system, constants | **Authoritative** |
| `docs/spec/walkthrough.md` | 4-round narrative loop example (may be outdated) | Reference |
| `docs/README.md` | Documentation index | — |
| `docs/superpowers/specs/2026-07-04-conversation-prompt-design.md` | Conversation architecture spec | Reference |
| `src/storyloom/prompt_builder.py` | Round 1 / Round N prompt content builder | Implementation |
| `src/storyloom/xml_parser.py` | LLM XML output parser | Implementation |
| `src/storyloom/context_manager.py` | Messages array, sliding window, compression | Implementation |
| `src/storyloom/config.py` | Configurable constants (window size, segments, etc.) | Implementation |
| `tests/test_prompt_builder.py` | PromptBuilder unit tests | Test |
| `tests/test_xml_parser.py` | XmlParser unit tests | Test |
| `tests/test_context_manager.py` | ContextManager unit tests | Test |
| `tests/test_integration.py` | Multi-round conversation flow integration tests | Test |
| `tests/prompt_lab/` | Prompt design tools and LLM test harnesses (real API) | Tool |
| `tests/prompt_lab/data/prompts/round1-linenum.txt` | Authoritative prompt format standard | **Standard** |

**Test structure:** `tests/test_*.py` = pytest unit tests (mock, no API). `tests/prompt_lab/` = ad-hoc prompt design tools (require API key).

## Tech Stack

- **Language:** Python 3 (standard library preferred)
- **Interface:** Terminal CLI (Phase 1), FastAPI + SSE (Phase 2+)
- **LLM:** OpenAI-compatible API (abstracted behind common interface)
- **Storage:** Local JSON files in `saves/` directory

## Conventions

- **Conversation:** Chinese (对话用中文)
- **Code comments & git commits:** English
- **Git commits:** Conventional Commits (feat/fix/docs/refactor)
- **Prompt language:** Chinese (all LLM prompts)
- **XML element names:** English (`<seg>`, `<checkpoint>`, `<bridge/>`, etc.)
- **Variable names in prompts:** Chinese (state variable names, choice names)
- **Config constants:** Defined in `config.py`, referenced by name — no hardcoded values in business logic
