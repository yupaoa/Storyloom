# Segment Length TTFT Impact Test — Design

> 2026-07-05 | Phase 1 of 2 (RATE testing is Phase 2)

## Motivation

Current prompt recommends 60-120 segments with bridge at position 30-60. At 0.5s/segment read time and 50% RATE, bridge_text reading time is only 15-30s — far below the ~48-60s average TTFT. The seamless bridge constraint requires:

```
TTFT < N × RATE × t
```

We hypothesize that TTFT is dominated by thinking time (format planning, content structuring), not output length. If true, we can significantly increase N without proportionally increasing TTFT, yielding more narrative per round while maintaining seamless bridging.

## Success Criteria

Stable guarantee of `TTFT < N × RATE × t` (currently RATE=0.5, t=0.5s) while maintaining generation correctness and quality.

## Phase 1: Segment Count (N) Testing

Fixed RATE = 50%. Test 4 N tiers, 3 runs each, then narrow into the promising range.

### Test Tiers

| Tier | Label | MIN | MAX | Bridge Range | REF_TOTAL |
|------|-------|-----|-----|-------------|-----------|
| T1 (control) | t1-60-120 | 60 | 120 | 30–60 | 100 |
| T2 | t2-120-200 | 120 | 200 | 60–100 | 160 |
| T3 | t3-180-280 | 180 | 280 | 90–140 | 240 |
| T4 | t4-240-360 | 240 | 360 | 120–180 | 320 |

REF_TOTAL values are clean multiples of 20 near each tier center.

### File Structure

```
tests/data/prompts/
  round1-en.tmpl              ← template (from round1-en.txt, 4 placeholders)
  seg-t1-60-120.txt            ← generated
  seg-t2-120-200.txt           ← generated
  seg-t3-180-280.txt           ← generated
  seg-t4-240-360.txt           ← generated
  seg-test-config.yaml         ← parameter matrix
  seg-test-manifest.json       ← generated (used by analysis script)
tests/
  generate_prompt.py           ← template renderer (~40 lines)
  analyze_seg_test.py          ← results aggregator (~100 lines)
```

### Prompt Template

`round1-en.tmpl` is `round1-en.txt` with the following placeholders:

| Placeholder | Replaces |
|-------------|----------|
| `{{MIN_SEG}}` | Minimum total seg count |
| `{{MAX_SEG}}` | Maximum total seg count |
| `{{BRIDGE_MIN}}` | Minimum bridge position |
| `{{BRIDGE_MAX}}` | Maximum bridge position |
| `{{REF_TOTAL}}` | Reference total for seg count example |
| `{{REF_SINGLE}}` | single-branch interaction count (= REF_TOTAL/2) |
| `{{REF_HALF}}` | dual-branch per-branch count (= REF_TOTAL/4) |

### Scripts

**`generate_prompt.py`**: Reads template + YAML config, replaces placeholders, writes prompt files, generates manifest JSON.

**`analyze_seg_test.py`**: Scans output `.md` files, extracts metrics from headers, aggregates per tier:

- **Timing**: TTFT (avg/min/max), total time (avg)
- **Output**: actual segment count (avg), bridge position ratio (avg)
- **Correctness** (per file, binary): XML valid, bridge count=1, checkpoint≤1, no interactive elements after bridge, seg numbering continuous from 1, no markdown fences, no prohibited dialogue format
- **Aggregate**: per-tier Correct% (trend only — 3 samples per tier is not statistically significant)

### Experiment Workflow

```
1. Create round1-en.tmpl from round1-en.txt
2. python tests/generate_prompt.py  →  4 prompt files + manifest
3. For each prompt: python tests/run_prompt_test.py --prompt <file> --runs 3
4. python tests/analyze_seg_test.py  →  comparison report
5. Select N range for Phase 2 RATE testing based on results
```

### Key Judgment

If segment count increases 3× (T1→T4) while TTFT increases only ~20%, the hypothesis is confirmed — thinking time dominates, and N can be substantially increased.

## Phase 2 (Future): RATE Testing

After Phase 1 identifies the optimal N range, test RATE ∈ {40%, 50%, 60%} at that N to find the best (N, RATE) combination.

## Non-Goals

- Not modifying existing `round1-en.txt` (template is a separate file)
- Not touching production code (`config.py`, `prompt_builder.py`) — this is pure experimental infrastructure
- Not testing multi-round conversation flow (single-round prompt test only)
