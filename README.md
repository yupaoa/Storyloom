# Storyloom

> AI-powered interactive text fiction game engine — LLM narrates, program orchestrates.

**Current phase:** Design & specification. Phase 1 (terminal CLI MVP) fully specced; implementation pending.

## Documentation

| Document | Purpose |
|----------|---------|
| [`docs/design.md`](./docs/design.md) | Design vision, architecture, phased roadmap |
| [`docs/spec/exec-flow.md`](./docs/spec/exec-flow.md) | Phase 1 execution pipeline (authoritative) |
| [`docs/spec/block-spec.md`](./docs/spec/block-spec.md) | Block separator syntax & prompt format |
| [`docs/spec/data-model.md`](./docs/spec/data-model.md) | State, save system, constants, conventions |
| [`docs/spec/walkthrough.md`](./docs/spec/walkthrough.md) | 4-round narrative loop walkthrough |
| [`docs/README.md`](./docs/README.md) | Full documentation index |

## Quick Summary

1. **Co-creation phase** — User and LLM collaboratively define world, protagonist, and story direction. LLM outputs structured `story_config` and `outline` (a directed graph of story milestones).
2. **Narrative loop** — Each round, the program assembles a prompt from outline progress + state snapshot + bridge text, the LLM generates a story segment with structured blocks, the program parses/validates/displays, and the player chooses from options.
3. **Bridge preloading** — A `--- bridge ---` marker triggers the next API request while the current segment's tail text is still being displayed, making segment boundaries invisible to the player.
4. **Local source of truth** — LLM only *suggests* state changes; the program validates and applies them. All game data lives in a local `GameState`.

## Tech Stack

- **Language:** Python 3
- **Interface:** Terminal CLI (Phase 1), Web (Phase 2+)
- **LLM:** OpenAI-compatible API

## Development Status

- [x] Design documents & Phase 1 specification
- [ ] Phase 1 CLI implementation
- [ ] Phase 2 Web + dynamic systems
- [ ] Phase 3 Multimedia & cloud
