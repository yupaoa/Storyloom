# Co-Creation

The co-creation phase is a guided Q&A flow between the player and the LLM.
It produces a `story_config` dict and `outline_text` string — pass these
directly to `GameLoop` to start the narrative.

The co-creation flow (`CoCreateFlow`) works with any UI implementation via
the `UiInterface` protocol. Both the CLI (`Display`) and the web interface
(`WebCoCreateDisplay`) use the same flow logic; only the I/O mechanism differs.

## Reference

- Flow logic: `src/storyloom/core/co_create.py` — `CoCreateFlow.run()`
- Prompt templates: `src/storyloom/core/co_create.py` — `CO_CREATE_SYSTEM_PROMPT`, `GENERATE_ALL_PROMPT`
- Variable caps: `src/storyloom/config.py` — `VARIABLE_CAP`, `VARIABLE_NUMERIC_CAP`, `VARIABLE_LABEL_CAP`
- Outline format: same as `SAMPLE_OUTLINE` in `src/storyloom/main.py`
- UI protocol: `src/storyloom/core/ui_interface.py` — `UiInterface`

## Output

Co-creation produces two artifacts:

| Artifact | Type | Description |
|----------|------|-------------|
| `story_config` | `dict` | Genre, setting, protagonist, variables (names, types, initial values) |
| `outline_text` | `str` | Directed graph of story milestone nodes with titles and goals |

Both are consumed directly by `GameLoop.__init__()` — no intermediate parsing needed.
