#!/usr/bin/env python3
r"""Analyze prompt time limits and compare against actual test results.

Usage:
  # Prompt only (no test data yet — just print the time budget)
  python3 tests/analyze_results.py --prompt tests/data/prompts/default.txt

  # Prompt + test output directory (compare actual vs expected)
  python3 tests/analyze_results.py --prompt tests/data/prompts/default.txt \
      --output-dir tests/data/output/default/

─── Time limit formulas (from prompt-design.md §4.3) ─────────────────

Two limits are calculated from the prompt's segment parameters:

  guaranteed (保证时限)
    = MIN × (1 − RATIO) × AUTO_ADVANCE_DELAY_MS / 1000
    The absolute minimum time the next round's LLM has to generate,
    assuming the player skips through the shortest possible pre-bridge
    content at maximum auto-advance speed.

  expected (当前时限)
    = BRIDGE_AT × AUTO_ADVANCE_DELAY_MS / 1000
    where BRIDGE_AT = floor((MIN + MAX) / 2 × RATIO)
    The typical time before the player reaches the bridge marker,
    assuming auto-advance at the configured delay per segment.
    This is the LLM's generation deadline for seamless playback.

Parameters are extracted from the prompt text:
  - MIN, MAX  → "本轮生成 30-50 个叙事段"
  - RATIO      → "约 75% 处" or "× 0.75"
  - AUTO_ADVANCE_DELAY_MS → from data-model.md §A.5 (default 500)

The bridge_text (User Message content) is NOT a time parameter — it is
the previous round's tail text fed as input to the LLM.  Only MIN, MAX,
and RATIO affect the time budget.

─── Output columns ──────────────────────────────────────────────────

  File      → test output filename
  Time      → actual LLM generation time (from file header)
  Segments  → count of numbered narrative segments in the output
  vs Limit  → actual_time − expected_limit (negative = within budget)
  Status    → ✓ within limit  /  ✗ OVER limit

─── Reference ───────────────────────────────────────────────────────

  docs/spec/prompt-design.md  §4.3  (formulas, worked example)
  docs/spec/data-model.md     §A.4  (SEGMENTS_PER_ROUND_*)
  docs/spec/data-model.md     §A.5  (AUTO_ADVANCE_DELAY_MS)
"""

import argparse
import re
import sys
from math import floor
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUTO_ADVANCE_DELAY_MS = 500  # from data-model.md §A.5


def load_config() -> int:
    """Try to read AUTO_ADVANCE_DELAY_MS from data-model.md, fallback to 500."""
    data_model = PROJECT_ROOT / "docs" / "spec" / "data-model.md"
    if data_model.exists():
        text = data_model.read_text(encoding="utf-8")
        m = re.search(r"AUTO_ADVANCE_DELAY_MS\s*\|\s*(\d+)", text)
        if m:
            return int(m.group(1))
    return 500


# ── Prompt parsing ──────────────────────────────────────────────────
def parse_prompt(path: Path) -> dict:
    """Extract MIN, MAX, RATIO from a prompt file."""
    text = path.read_text(encoding="utf-8")

    # Pattern: "本轮生成 30-50 个叙事段。bridge 放在总段数的约 75% 处"
    # Also match: "bridge 放在约第 30 段之后（约 75% 位置）"
    m = re.search(r"本轮生成\s*(\d+)\s*-\s*(\d+)\s*个叙事段", text)
    if not m:
        # Fallback: try placeholder format {MIN}-{MAX}
        m = re.search(r"生成\s*\{MIN\}\s*-\s*\{MAX\}\s*个叙事段", text)
        if m:
            raise RuntimeError(
                "Prompt contains placeholders ({MIN}-{MAX}), not concrete values. "
                "Use a concrete prompt file (e.g. from §4.3)."
            )
        raise RuntimeError("Could not find '本轮生成 N-M 个叙事段' in prompt.")

    lo = int(m.group(1))
    hi = int(m.group(2))

    # Extract RATIO: "约 75%", "约 75% 处", "× 0.75"
    m = re.search(r"[约×]\s*(\d+)%", text)
    if not m:
        m = re.search(r"×\s*(0\.\d+)", text)
    if m:
        ratio_pct = float(m.group(1))
        ratio = ratio_pct / 100.0 if ratio_pct > 1 else ratio_pct
    else:
        ratio = 0.75  # default

    bridge_at = floor((lo + hi) / 2 * ratio)

    return {
        "min": lo,
        "max": hi,
        "ratio": ratio,
        "bridge_at": bridge_at,
    }


def calc_limits(params: dict, delay_ms: int) -> dict:
    """Calculate time limits from prompt parameters."""
    lo = params["min"]
    ratio = params["ratio"]
    bridge_at = params["bridge_at"]

    guaranteed = lo * (1 - ratio) * delay_ms / 1000
    expected = bridge_at * delay_ms / 1000

    return {
        "guaranteed_s": round(guaranteed, 1),
        "expected_s": round(expected, 1),
    }


# ── Output file parsing ─────────────────────────────────────────────
def parse_output_file(path: Path) -> dict | None:
    """Extract metadata from a test output file. Returns None on error."""
    if not path.exists():
        return None

    text = path.read_text(encoding="utf-8")

    # Parse header
    time_s = None
    m = re.search(r"\*\*Time\*\*:\s*([\d.]+)s", text)
    if m:
        time_s = float(m.group(1))

    if time_s is None:
        return None

    # Count narrative segments (numbered lines in narrative blocks)
    # Find all narrative blocks and count numbered lines
    segments = 0
    in_narrative = False
    seen_numbers = set()

    for line in text.splitlines():
        line = line.strip()
        # Track block boundaries
        if re.match(r"^---\s*narrative:", line):
            in_narrative = True
            continue
        elif re.match(r"^---\s*(options|state|checkpoint|bridge)\b", line):
            in_narrative = False
            continue

        if in_narrative:
            m = re.match(r"^(\d+)\.\s", line)
            if m:
                num = int(m.group(1))
                if num not in seen_numbers:
                    seen_numbers.add(num)
                    segments += 1

    return {
        "time_s": time_s,
        "segments": segments,
    }


# ── Main ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Analyze prompt time limits and compare against test results."
    )
    parser.add_argument(
        "--prompt", type=Path, required=True,
        help="Path to prompt file",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Directory containing prompt-test-*.md files (optional)",
    )
    args = parser.parse_args()

    if not args.prompt.exists():
        print(f"[ERROR] Prompt file not found: {args.prompt}")
        sys.exit(1)

    delay_ms = load_config()

    # ── Prompt analysis ──────────────────────────────────────────
    params = parse_prompt(args.prompt)
    limits = calc_limits(params, delay_ms)

    print("═" * 58)
    print(f"Prompt:  {args.prompt.name}")
    print(f"Params:  MIN={params['min']}  MAX={params['max']}  "
          f"RATIO={int(params['ratio']*100)}%  BRIDGE_AT={params['bridge_at']}")
    print(f"Delay:   {delay_ms}ms/segment")
    print(f"Limits:  guaranteed ≥ {limits['guaranteed_s']}s  "
          f"expected ≈ {limits['expected_s']}s")
    print()

    # ── No output files ──────────────────────────────────────────
    if args.output_dir is None:
        print("(No --output-dir specified. Run with --output-dir to compare "
              "against actual results.)")
        return

    if not args.output_dir.exists():
        print(f"[WARN] Output directory not found: {args.output_dir}")
        return

    # ── Compare against results ──────────────────────────────────
    files = sorted(args.output_dir.glob("prompt-test-*.md"))
    if not files:
        print(f"[WARN] No prompt-test-*.md files found in {args.output_dir}")
        return

    print(f"{'File':<20s} {'Time':>7s}  {'Segments':>8s}  {'vs Limit':>12s}  "
          f"{'Status':>6s}")
    print("-" * 58)

    times = []
    segs = []
    for f in files:
        result = parse_output_file(f)
        if result is None:
            print(f"{f.name:<20s}  {'(parse error)':>33s}")
            continue

        t = result["time_s"]
        s = result["segments"]
        times.append(t)
        segs.append(s)

        diff = t - limits["expected_s"]
        diff_str = f"{diff:+.1f}s" if diff >= 0 else f"{diff:.1f}s"
        status = "✓" if t <= limits["expected_s"] else "✗ OVER"

        print(f"{f.name:<20s}  {t:6.1f}s  {s:8d}  {diff_str:>12s}  {status:>6s}")

    print("-" * 58)
    if times:
        avg_t = sum(times) / len(times)
        avg_s = sum(segs) / len(segs)
        over_count = sum(1 for t in times if t > limits["expected_s"])
        print(f"{len(times)} files  "
              f"time: {min(times):.1f}s ~ {max(times):.1f}s (avg {avg_t:.1f}s)  "
              f"segments: {min(segs)} ~ {max(segs)} (avg {avg_s:.0f})")
        if over_count:
            print(f"{over_count}/{len(times)} exceeded expected limit "
                  f"({limits['expected_s']}s)")


if __name__ == "__main__":
    main()
