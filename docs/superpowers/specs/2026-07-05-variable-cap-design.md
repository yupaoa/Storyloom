# Variable Cap: ≤3 State Variables per Story

> 2026-07-05 | Design — simplify state model to reduce LLM cognitive load

## Motivation

Current prompt suggests 5-8 variables. Multiple dimensions create unnecessary LLM overhead — more `<set>` operations, more conditional routing, higher error rates. A lean per-story state model improves output quality and efficiency.

## Design

### Constraint

- **Hard cap**: ≤3 state variables per story
- **Type ratio**: ≤2 numeric (`number`), ≤1 label (`string`/`list`)
- **Principle**: If a variable never triggers a branch or gates a choice, it is noise. Prefer a single core numeric variable.

### Seed Reference

A minimal genre → variable mapping provided in-prompt as a starting point. The LLM may adopt, adapt, or replace:

```
Genre seed reference (adopt or adapt based on the story; replace if unsuitable):
  Romance      → affection
  Mystery      → clues_progress
  Cyberpunk    → implant_integrity
  Wuxia        → inner_power
  Horror       → sanity
```

These are **references, not requirements**.

### Changes

**1. `docs/spec/exec-flow.md` §3.5 Step 2** — Replace variable generation constraints:

| Before | After |
|--------|-------|
| 建议 5–8 个变量 | ≤3 total (≤2 numeric, ≤1 label) |
| No genre guidance | Seed reference table |
| No philosophy | "Fewer is better" principle |

**2. `docs/spec/exec-flow.md` §3.5 Step 4** — Add validation rules:

```
f. Variable count ≤ 3
g. Type count: number ≤ 2, string/list ≤ 1
```

**3. `docs/spec/prompt-design.md` §3.3** — Update variable generation prompt template (English, consistent with `round1-en.txt`).

### Non-Goals

- No genre-detection logic in code (LLM infers genre in-prompt)
- No hardcoded variable names in Python
- No changes to runtime state engine

### Impact

- Fewer variables → fewer `<set>` ops → fewer validation rejections → lower error rate
- Seed table: ~200 chars, negligible prompt budget
- Existing `story_config.variables` format unchanged
