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
    The absolute minimum tail display time.  Even if the LLM generates
    only MIN segments, the tail (the portion after bridge) provides at
    least this much reading time for the player.  This is the floor:
    the next round's LLM MUST deliver its first usable segment within
    this window for seamless playback.

  expected (当前时限)
    = ((MIN + MAX) / 2 − BRIDGE_AT) × AUTO_ADVANCE_DELAY_MS / 1000
    where BRIDGE_AT = floor((MIN + MAX) / 2 × RATIO)
    The expected tail display time at the design-segment count (avg of
    MIN and MAX).  This is the typical LLM generation deadline for the
    bridge mechanism to deliver seamless transitions.

  reference: bridge trigger point
    = BRIDGE_AT × AUTO_ADVANCE_DELAY_MS / 1000
    Time from round start until the bridge marker triggers the next
    prompt submission.  Informational only — not a deadline.

The bridge mechanism:
  1. Program reaches bridge marker during display → submits next prompt
  2. Continues displaying tail segments while LLM generates
  3. LLM must return first usable segment before tail display completes
  4. With streaming: only TTFT + first-segment matters, not total time

Parameters are extracted from the prompt text:
  - MIN, MAX  → "本轮生成 30-50 个叙事段"
  - RATIO      → "约 75% 处" or "× 0.75"
  - AUTO_ADVANCE_DELAY_MS → from data-model.md §A.5 (default 500)

─── Output columns ──────────────────────────────────────────────────

  File      → test output filename
  Time      → total LLM generation time (from file header)
  Segs      → total narrative segments in the output
  Tail      → segments after bridge marker (the display buffer)
  尾时       → tail × delay = actual time budget for next round
  时限       → expected time limit (当前时限) for comparison
  Status    → ✓ tail ≥ guaranteed  /  ⚠ tail < guaranteed

  Note: total generation time (Time column) is measured with
  stream=False.  With streaming, only TTFT + first-segment latency
  matters — total time is irrelevant to bridge timing.  Run streaming
  tests to measure the true deadline metric.

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

    m = re.search(r"本轮生成\s*(\d+)\s*-\s*(\d+)\s*个叙事段", text)
    if not m:
        m = re.search(r"生成\s*\{MIN\}\s*-\s*\{MAX\}\s*个叙事段", text)
        if m:
            raise RuntimeError(
                "Prompt contains placeholders ({MIN}-{MAX}), not concrete values. "
                "Use a concrete prompt file (e.g. from §4.3)."
            )
        raise RuntimeError("Could not find '本轮生成 N-M 个叙事段' in prompt.")

    lo = int(m.group(1))
    hi = int(m.group(2))

    m = re.search(r"[约×]\s*(\d+)%", text)
    if not m:
        m = re.search(r"×\s*(0\.\d+)", text)
    if m:
        ratio_pct = float(m.group(1))
        ratio = ratio_pct / 100.0 if ratio_pct > 1 else ratio_pct
    else:
        ratio = 0.75

    bridge_at = floor((lo + hi) / 2 * ratio)

    return {
        "min": lo,
        "max": hi,
        "ratio": ratio,
        "bridge_at": bridge_at,
    }


def calc_limits(params: dict, delay_ms: int) -> dict:
    """Calculate time limits from prompt parameters.

    guaranteed (保证时限): minimum tail display time (at MIN segments).
    expected (当前时限):   expected tail display time (at avg segments).
                           This is the LLM's generation deadline.
    pre_bridge:            time from round start to bridge trigger
                           (informational, not a deadline).
    """
    lo = params["min"]
    hi = params["max"]
    ratio = params["ratio"]
    bridge_at = params["bridge_at"]

    avg_total = (lo + hi) / 2
    expected_tail = avg_total - bridge_at

    guaranteed = lo * (1 - ratio) * delay_ms / 1000
    expected = expected_tail * delay_ms / 1000
    pre_bridge = bridge_at * delay_ms / 1000

    return {
        "guaranteed_s": round(guaranteed, 1),
        "expected_s": round(expected, 1),
        "pre_bridge_s": round(pre_bridge, 1),
    }


# ── Output file parsing ─────────────────────────────────────────────
def parse_output_file(path: Path) -> dict | None:
    """Extract metadata and tail segments from a test output file."""
    if not path.exists():
        return None

    text = path.read_text(encoding="utf-8")

    time_s = None
    m = re.search(r"\*\*Time\*\*:\s*([\d.]+)s", text)
    if m:
        time_s = float(m.group(1))

    if time_s is None:
        return None

    # Split off the metadata header to isolate LLM output
    parts = text.split('\n---\n', 1)
    llm_out = parts[1] if len(parts) > 1 else text

    # Find bridge marker
    bridge_m = re.search(r'^--- bridge ---$', llm_out, re.MULTILINE)
    bridge_pos = bridge_m.start() if bridge_m else len(llm_out)

    # Count segments before and after bridge
    pre_text = llm_out[:bridge_pos]
    post_text = llm_out[bridge_pos:] if bridge_m else ""

    pre_segs = len(re.findall(r'^\d+\.', pre_text, re.MULTILINE))
    post_segs = len(re.findall(r'^\d+\.', post_text, re.MULTILINE)) if bridge_m else 0

    total_segs = pre_segs + post_segs

    return {
        "time_s": time_s,
        "segments": total_segs,
        "tail_segs": post_segs,
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

    print("═" * 72)
    print(f"Prompt:  {args.prompt.name}")
    print(f"Params:  MIN={params['min']}  MAX={params['max']}  "
          f"RATIO={int(params['ratio']*100)}%  BRIDGE_AT={params['bridge_at']}")
    print(f"Delay:   {delay_ms}ms/segment")
    print()
    print("Time budget (bridge mechanism):")
    print(f"  保证时限 (min tail time):   {limits['guaranteed_s']:5.1f}s  "
          f"(MIN × (1−RATIO) × delay)")
    print(f"  当前时限 (exp tail time):   {limits['expected_s']:5.1f}s  "
          f"((avg_total − BRIDGE_AT) × delay)")
    print(f"  bridge 触发点 (pre-bridge): {limits['pre_bridge_s']:5.1f}s  "
          f"(BRIDGE_AT × delay, informational)")
    print(f"  ↑ LLM 必须在当前时限内返回首个可用段落，bridge 机制才能无缝衔接。")
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

    print(f"{'File':<20s} {'GenTime':>7s}  {'Segs':>5s}  {'Tail':>5s}  "
          f"{'尾时':>6s}  {'Gen-尾':>7s}  {'无缝?':>6s}")
    print("-" * 72)

    times = []
    segs = []
    tail_segs_list = []
    seamless_count = 0
    for f in files:
        result = parse_output_file(f)
        if result is None:
            print(f"{f.name:<20s}  {'(parse error)':>40s}")
            continue

        t = result["time_s"]
        s = result["segments"]
        tail = result["tail_segs"]
        tail_time = tail * delay_ms / 1000

        times.append(t)
        segs.append(s)
        tail_segs_list.append(tail)

        # Seamless check: can the LLM finish generating before tail ends?
        gap = t - tail_time
        seamless = "✓" if gap <= 0 else f"gap {gap:.0f}s"
        if gap <= 0:
            seamless_count += 1

        print(f"{f.name:<20s}  {t:5.1f}s  {s:5d}  {tail:5d}  "
              f"{tail_time:5.1f}s  {gap:6.1f}s  {seamless:>6s}")

    print("-" * 72)
    if times:
        avg_t = sum(times) / len(times)
        avg_s = sum(segs) / len(segs)
        avg_tail = sum(tail_segs_list) / len(tail_segs_list)
        avg_tail_time = avg_tail * delay_ms / 1000
        short_count = sum(
            1 for tl in tail_segs_list
            if tl * delay_ms / 1000 < limits["guaranteed_s"]
        )
        print(f"{len(times)} files  "
              f"gen: {min(times):.1f}s ~ {max(times):.1f}s (avg {avg_t:.1f}s)  "
              f"tail: {min(tail_segs_list)*delay_ms/1000:.1f}s ~ "
              f"{max(tail_segs_list)*delay_ms/1000:.1f}s (avg {avg_tail_time:.1f}s)")
        if short_count:
            print(f"⚠ {short_count}/{len(times)} tests have tail time below "
                  f"guaranteed minimum ({limits['guaranteed_s']}s)")
        print()
        if seamless_count == 0:
            print(f"无缝: 0/{len(times)} — LLM 生成时间({avg_t:.0f}s)远超"
                  f"尾部播放时间({avg_tail_time:.0f}s)，无法在尾部播完前返回完整响应。")
            print(f"要达到无缝，需生成时间 ≤ 尾部时间。当前差距约 {avg_t - avg_tail_time:.0f}s。")
            needed_tail = avg_t / (delay_ms / 1000)
            print(f"若保持当前生成速度，需尾部 ≥ {needed_tail:.0f} 段（总段数 ≈ {needed_tail/(1-params['ratio']):.0f}），"
                  f"或模型提速 {avg_t/avg_tail_time:.0f}×。")
        else:
            print(f"无缝: {seamless_count}/{len(times)}")


if __name__ == "__main__":
    main()
