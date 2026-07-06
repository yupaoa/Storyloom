# Co-Creation

The co-creation phase is handled entirely by the frontend via direct LLM calls.

## Reference

- Prompt templates: `src/storyloom/co_create.py` — `CO_CREATE_SYSTEM_PROMPT`, `GENERATE_ALL_PROMPT`
- Variable caps: `src/storyloom/config.py` — `VARIABLE_CAP`, `VARIABLE_NUMERIC_CAP`, `VARIABLE_LABEL_CAP`
- Outline format: same as `SAMPLE_OUTLINE` in `src/storyloom/main.py`

## Output

Co-creation produces a `story_config` dict and `outline_text` string — pass these directly to `GameLoop`.
