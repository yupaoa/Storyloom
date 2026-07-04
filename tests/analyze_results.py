#!/usr/bin/env python3
r"""Analyze prompt test results: timing + correctness in one pass.

Usage:
  # Full analysis (timing + correctness)
  python3 tests/analyze_results.py --prompt tests/data/prompts/default.txt \
      --output-dir tests/data/output/default/

  # Timing only (skip correctness checks)
  python3 tests/analyze_results.py --prompt tests/data/prompts/default.txt \
      --output-dir tests/data/output/default/ --no-correctness

  # Prompt analysis only (no test data yet)
  python3 tests/analyze_results.py --prompt tests/data/prompts/default.txt

─── Timing metrics ──────────────────────────────────────────────────

  TTFT / FirstSegment: bridge deadline (from streaming-mode file headers).
  The key check: FirstSegment ≤ tail_time → seamless transition.

  guaranteed (保证时限) = MIN × (1−RATIO) × delay
  expected   (当前时限) = ((MIN+MAX)/2 − BRIDGE_AT) × delay

─── Correctness checks ──────────────────────────────────────────────

  1. choice:       options block has `choice: 变量名` on first line
  2. pre-branch:   pre-bridge options/state use only `:main` branch
  3. first-block:  output starts with `--- narrative:main ---`
  4. numbering:    first segment is numbered 1
  5. node:         checkpoint `node {id}` exists in outline
  6. routes:       all `route {target}` targets exist in outline
  7. segments:     total ≤ hard cap (MAX + 20)
  8. tail:         tail segments ≥ minimum (MIN × (1−RATIO))

  Valid nodes and the hard segment cap are parsed from the prompt file's
  outline section and rules respectively.

─── Reference ───────────────────────────────────────────────────────

  docs/spec/prompt-design.md  §4.3  (formulas, example)
  docs/spec/data-model.md     §A.4  (segment constants)
"""

import argparse
import re
import sys
from math import floor
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUTO_ADVANCE_DELAY_MS = 500


def load_delay_ms() -> int:
    data_model = PROJECT_ROOT / "docs" / "spec" / "data-model.md"
    if data_model.exists():
        m = re.search(r"AUTO_ADVANCE_DELAY_MS\s*\|\s*(\d+)", data_model.read_text(encoding="utf-8"))
        if m:
            return int(m.group(1))
    return 500


# ── Prompt parsing ──────────────────────────────────────────────────

def parse_prompt_params(path: Path) -> dict:
    """Extract MIN, MAX, RATIO, hard cap, valid nodes from a prompt file."""
    text = path.read_text(encoding="utf-8")

    # Segment range
    m = re.search(r"本轮\S*\s*(\d+)\s*[-–]\s*(\d+)\s*个叙事段", text)
    if not m:
        m = re.search(r"生成\s*\{MIN\}\s*-\s*\{MAX\}\s*个叙事段", text)
        if m:
            raise RuntimeError(
                "Prompt contains placeholders ({MIN}-{MAX}). "
                "Use a concrete prompt file."
            )
        raise RuntimeError("Could not find segment range in prompt.")

    lo = int(m.group(1))
    hi = int(m.group(2))

    # Hard cap
    hard_cap = None
    m_cap = re.search(r"超过\s*(\d+)\s*段.*截断", text)
    if m_cap:
        hard_cap = int(m_cap.group(1))
    else:
        hard_cap = hi + 20  # default

    # Bridge ratio / position
    m_window = re.search(r"放在第\s*(\d+)\s*[-–]\s*(\d+)\s*段之后", text)
    if m_window:
        # v5 format: absolute window → infer ratio + bridge_at
        bridge_lo = int(m_window.group(1))
        bridge_hi = int(m_window.group(2))
        bridge_at = (bridge_lo + bridge_hi) // 2
        ratio = bridge_at / ((lo + hi) / 2)
    else:
        m = re.search(r"[约×]\s*(\d+)%", text)
        if not m:
            m = re.search(r"×\s*(0\.\d+)", text)
        if m:
            ratio_pct = float(m.group(1))
            ratio = ratio_pct / 100.0 if ratio_pct > 1 else ratio_pct
        else:
            ratio = 0.75
        bridge_at = floor((lo + hi) / 2 * ratio)

    # Min tail
    min_tail = None
    m_tail = re.search(r"尾部不足\s*(\d+)\s*段", text)
    if m_tail:
        min_tail = int(m_tail.group(1))
    else:
        min_tail = floor(lo * (1 - ratio))

    # Valid node IDs from outline section
    valid_nodes = set()
    story_start = text.find("# 故事")
    if story_start < 0:
        story_start = text.find("**背景")
    if story_start > 0:
        story_text = text[story_start:]
        for m in re.finditer(r'\b(ch\d+_\w+)\b', story_text):
            # Only nodes listed as outline entries (with [status] or —)
            pass
        # Simpler: find all node_id patterns in the outline block
        outline_start = story_text.find("大纲")
        if outline_start < 0:
            outline_start = 0
        outline_block = story_text[outline_start:]
        # Match lines like: ch1_bar [completed] — title
        for m in re.finditer(r'\b(ch\d+_\w+)\b', outline_block):
            valid_nodes.add(m.group(1))

    return {
        "min": lo,
        "max": hi,
        "hard_cap": hard_cap,
        "ratio": ratio,
        "bridge_at": bridge_at,
        "min_tail": min_tail,
        "valid_nodes": valid_nodes,
    }


def calc_limits(params: dict, delay_ms: int) -> dict:
    lo, hi, ratio, bridge_at = params["min"], params["max"], params["ratio"], params["bridge_at"]
    avg_total = (lo + hi) / 2
    expected_tail = avg_total - bridge_at
    return {
        "guaranteed_s": round(lo * (1 - ratio) * delay_ms / 1000, 1),
        "expected_s": round(expected_tail * delay_ms / 1000, 1),
        "pre_bridge_s": round(bridge_at * delay_ms / 1000, 1),
    }


# ── Output file parsing ─────────────────────────────────────────────

def parse_output_file(path: Path) -> dict | None:
    """Extract timing + correctness data from a test output file."""
    if not path.exists():
        return None

    text = path.read_text(encoding="utf-8")
    time_s = None
    m = re.search(r"\*\*Time\*\*:\s*([\d.]+)s", text)
    if m:
        time_s = float(m.group(1))
    if time_s is None:
        return None

    ttft = None
    m = re.search(r"\*\*TTFT\*\*:\s*([\d.]+)s", text)
    if m:
        ttft = float(m.group(1))

    first_seg = None
    m = re.search(r"\*\*FirstSegment\*\*:\s*([\d.]+)s", text)
    if m:
        first_seg = float(m.group(1))

    # Split header from LLM output
    parts = text.split('\n---\n', 1)
    llm_out = parts[1] if len(parts) > 1 else text

    # --- Pre-bridge section ---
    bridge_m = re.search(r'^--- bridge ---$', llm_out, re.MULTILINE)
    bridge_pos = bridge_m.start() if bridge_m else len(llm_out)
    pre_text = llm_out[:bridge_pos]
    post_text = llm_out[bridge_pos:] if bridge_m else ""

    # --- Timing ---
    pre_segs = len(re.findall(r'^\d+\.', pre_text, re.MULTILINE))
    post_segs = len(re.findall(r'^\d+\.', post_text, re.MULTILINE)) if bridge_m else 0
    total_segs = pre_segs + post_segs

    # --- Correctness ---
    # 1. choice declaration
    has_choice = bool(re.search(r'^choice:\s*\S+', pre_text, re.MULTILINE))

    # 2. pre-bridge branch names (options/state must be :main or unqualified)
    pre_blocks = re.findall(r'^--- (options|state)(:\w+)? ---', pre_text, re.MULTILINE)
    bad_branches = [
        f"{btype}{branch}"
        for btype, branch in pre_blocks
        if branch and branch != ":main"
    ]

    # 3. first narrative block
    first_block_m = re.search(r'^--- narrative:(\S+) ---', llm_out, re.MULTILINE)
    first_block = first_block_m.group(1) if first_block_m else None

    # 4. first segment number
    first_num_m = re.search(r'^(\d+)\.\s', llm_out, re.MULTILINE)
    first_num = int(first_num_m.group(1)) if first_num_m else None

    # 5. checkpoint node
    node_m = re.search(r'^node\s+(\S+)', pre_text, re.MULTILINE)
    checkpoint_node = node_m.group(1) if node_m else None

    # 6. route targets
    route_targets = re.findall(r'route\s+(\S+)', pre_text)

    return {
        # Timing
        "time_s": time_s,
        "ttft": ttft,
        "first_seg": first_seg,
        "segments": total_segs,
        "tail_segs": post_segs,
        # Correctness
        "has_choice": has_choice,
        "bad_branches": bad_branches,
        "first_block": first_block,
        "first_num": first_num,
        "checkpoint_node": checkpoint_node,
        "route_targets": route_targets,
        "finish": _parse_finish(text),
    }


def _parse_finish(text: str) -> str:
    m = re.search(r"\*\*Finish\*\*:\s*(\S+)", text)
    return m.group(1) if m else "?"


# ── Correctness evaluation ──────────────────────────────────────────

def check_correctness(r: dict, params: dict) -> list[str]:
    """Return list of issue labels. Empty list = clean."""
    issues = []

    if not r["has_choice"]:
        issues.append("choice?")

    if r["bad_branches"]:
        issues.append(f"branch({','.join(r['bad_branches'])})?")

    if r["first_block"] != "main":
        issues.append(f"first={r['first_block']}")

    if r["first_num"] != 1:
        issues.append(f"start={r['first_num']}")

    node = r["checkpoint_node"]
    valid = params["valid_nodes"]
    if node and valid and node not in valid:
        issues.append(f"node({node})?")

    for rt in r["route_targets"]:
        if valid and rt not in valid:
            issues.append(f"route({rt})?")

    if r["segments"] > params["hard_cap"]:
        issues.append(f"segs={r['segments']}(>{params['hard_cap']})")

    if r["tail_segs"] < params["min_tail"]:
        issues.append(f"tail={r['tail_segs']}(<{params['min_tail']})")

    if r["finish"] == "length":
        issues.append("TRUNCATED")

    return issues


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Analyze prompt test results: timing + correctness."
    )
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--no-correctness", action="store_true",
        help="Skip correctness checks (timing only)."
    )
    args = parser.parse_args()

    if not args.prompt.exists():
        print(f"[ERROR] Prompt file not found: {args.prompt}")
        sys.exit(1)

    delay_ms = load_delay_ms()
    params = parse_prompt_params(args.prompt)
    limits = calc_limits(params, delay_ms)
    check_correct = not args.no_correctness

    # ── Prompt summary ──────────────────────────────────────────────
    print("═" * 72)
    print(f"Prompt:  {args.prompt.name}")
    print(f"Params:  MIN={params['min']}  MAX={params['max']}  "
          f"HARD={params['hard_cap']}  RATIO={int(params['ratio']*100)}%  "
          f"BRIDGE_AT={params['bridge_at']}  MIN_TAIL={params['min_tail']}")
    if params["valid_nodes"]:
        print(f"Nodes:   {', '.join(sorted(params['valid_nodes']))}")
    print(f"Delay:   {delay_ms}ms/segment")
    print()
    print("Time budget (bridge mechanism):")
    print(f"  保证时限 (min tail):   {limits['guaranteed_s']:5.1f}s  "
          f"(MIN × (1−RATIO) × delay)")
    print(f"  当前时限 (expected):   {limits['expected_s']:5.1f}s  "
          f"((avg − BRIDGE_AT) × delay)")
    print(f"  bridge 触发点:         {limits['pre_bridge_s']:5.1f}s  "
          f"(BRIDGE_AT × delay)")
    print()

    if args.output_dir is None:
        print("(No --output-dir specified.)")
        return

    if not args.output_dir.exists():
        print(f"[WARN] Output directory not found: {args.output_dir}")
        return

    files = sorted(args.output_dir.glob("prompt-test-*.md"))
    if not files:
        print(f"[WARN] No prompt-test-*.md files found.")
        return

    # ── Results table ───────────────────────────────────────────────
    sample = parse_output_file(files[0])
    has_streaming = sample and sample.get("first_seg") is not None

    if has_streaming:
        header = (f"{'File':<20s} {'TTFT':>6s} {'1stSeg':>7s} {'Segs':>5s} "
                  f"{'Tail':>5s} {'尾时':>6s} {'到达-尾':>7s} {'无缝':>5s}")
        if check_correct:
            header += "  正确性"
    else:
        header = (f"{'File':<20s} {'GenTime':>7s} {'Segs':>5s} {'Tail':>5s} "
                  f"{'尾时':>6s} {'Gen-尾':>7s} {'无缝':>5s}")
    print(header)
    print("-" * (len(header) + 4))

    all_times = []
    all_first_segs = []
    all_segs = []
    all_tails = []
    seamless_count = 0
    clean_count = 0

    for f in files:
        r = parse_output_file(f)
        if r is None:
            print(f"{f.name:<20s}  {'(parse error)':>50s}")
            continue

        t = r["time_s"]
        fs = r.get("first_seg")
        s = r["segments"]
        tail = r["tail_segs"]
        tail_time = tail * delay_ms / 1000

        all_times.append(t)
        if fs is not None:
            all_first_segs.append(fs)
        all_segs.append(s)
        all_tails.append(tail)

        # Seamless
        deadline = fs if fs is not None else t
        gap = deadline - tail_time
        seamless = "✓" if gap <= 0 else f"+{gap:.0f}s"
        if gap <= 0:
            seamless_count += 1

        # Timing columns
        if has_streaming:
            ttft_s = f"{r.get('ttft', 0):.1f}" if r.get('ttft') else "?"
            fs_s = f"{fs:.1f}" if fs else "?"
            line = (f"{f.name:<20s}  {ttft_s:>5s}s  {fs_s:>6s}s  {s:5d}  "
                    f"{tail:5d}  {tail_time:5.1f}s  {gap:6.1f}s  {seamless:>5s}")
        else:
            line = (f"{f.name:<20s}  {t:5.1f}s  {s:5d}  {tail:5d}  "
                    f"{tail_time:5.1f}s  {gap:6.1f}s  {seamless:>5s}")

        # Correctness
        if check_correct:
            issues = check_correctness(r, params)
            if issues:
                line += f"  ✗ {' '.join(issues)}"
            else:
                line += "  ✓"
                clean_count += 1

        print(line)

    # ── Summary ─────────────────────────────────────────────────────
    print("-" * 72)
    if all_times:
        avg_t = sum(all_times) / len(all_times)
        avg_s = sum(all_segs) / len(all_segs)
        avg_tail = sum(all_tails) / len(all_tails)
        avg_tail_time = avg_tail * delay_ms / 1000
        short_count = sum(
            1 for tl in all_tails
            if tl * delay_ms / 1000 < limits["guaranteed_s"]
        )

        print(f"{len(files)} files  "
              f"gen: {min(all_times):.1f}s ~ {max(all_times):.1f}s "
              f"(avg {avg_t:.1f}s)  "
              f"segments: {min(all_segs)} ~ {max(all_segs)} (avg {avg_s:.0f})")

        if all_first_segs:
            avg_fs = sum(all_first_segs) / len(all_first_segs)
            print(f"FirstSegment: {min(all_first_segs):.1f}s ~ "
                  f"{max(all_first_segs):.1f}s (avg {avg_fs:.1f}s)")

        if short_count:
            print(f"⚠ {short_count}/{len(files)} tail below guaranteed "
                  f"({limits['guaranteed_s']}s)")

        # Seamless summary
        if seamless_count == len(files):
            print(f"无缝: {seamless_count}/{len(files)} ✓")
        elif seamless_count > 0:
            print(f"无缝: {seamless_count}/{len(files)} (部分)")
        else:
            deadline_label = "FirstSegment" if all_first_segs else "GenTime"
            avg_deadline = (sum(all_first_segs) / len(all_first_segs)
                            if all_first_segs else avg_t)
            print(f"无缝: 0/{len(files)} — {deadline_label}({avg_deadline:.1f}s) > "
                  f"尾部({avg_tail_time:.1f}s), gap {avg_deadline - avg_tail_time:.1f}s")

        # Correctness summary
        if check_correct:
            print(f"正确: {clean_count}/{len(files)}", end="")
            if clean_count == len(files):
                print(" ✓")
            else:
                print()

    print()


if __name__ == "__main__":
    main()
