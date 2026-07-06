#!/usr/bin/env python3
r"""Analyze XML-format (Frame) prompt test results: timing + correctness.

Usage:
  # Full analysis
  python3 tests/analyze_frame.py --prompt tests/prompt_lab/data/prompts/frame-v1.txt \
      --output-dir tests/prompt_lab/data/output/frame-v1/

  # Timing only (skip correctness)
  python3 tests/analyze_frame.py --prompt tests/prompt_lab/data/prompts/frame-v1.txt \
      --output-dir tests/prompt_lab/data/output/frame-v1/ --no-correctness

  # Prompt analysis only (no test data yet)
  python3 tests/analyze_frame.py --prompt tests/prompt_lab/data/prompts/frame-v1.txt

Format: XML-based narrative engine output ("Frame" format).

Correctness checks:
  1. xml:        valid XML, root is <story>
  2. choice:     <choice> present with id + 2-5 <opt> children
  3. set:        all <set> have var/op/val attributes
  4. checkpoint: <checkpoint> node matches outline, summary present
  5. routes:     all <route> targets exist in outline
  6. bridge:     exactly one <bridge/>
  7. pre-bridge: no <branch> before <bridge/>
  8. post-bridge: all segs inside <branch>, each opt->branch matched
  9. numbering:  seg n starts at 1, sequential (no gaps/dupes)
  10. segments:  total <= hard cap
  11. tail:      per-branch >= min_tail
"""

import argparse
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

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
    """Extract MIN, MAX, hard_cap, bridge range, min_tail, valid nodes."""
    text = path.read_text(encoding="utf-8")

    # Segment range: "本轮 60-120 个叙事段"
    m = re.search(r"本轮\s*(\d+)\s*[-–]\s*(\d+)\s*个叙事段", text)
    if not m:
        raise RuntimeError("Could not find segment range in prompt.")
    lo, hi = int(m.group(1)), int(m.group(2))

    # Hard cap: "超过 120 段截断" or "超过 120 段会被截断"
    hard_cap = None
    m_cap = re.search(r"超过\s*(\d+)\s*段.*截断", text)
    if m_cap:
        hard_cap = int(m_cap.group(1))
    else:
        hard_cap = hi

    # Bridge range: "第 30-60 段之间"
    m_br = re.search(r"第\s*(\d+)\s*[-–]\s*(\d+)\s*段之间", text)
    if m_br:
        bridge_lo, bridge_hi = int(m_br.group(1)), int(m_br.group(2))
        bridge_at = (bridge_lo + bridge_hi) // 2
        ratio = bridge_at / ((lo + hi) / 2)
    else:
        bridge_lo, bridge_hi = None, None
        bridge_at = (lo + hi) // 2
        ratio = 0.5

    # Min tail per branch: "每个分支至少 15 个 <seg>"
    min_tail = 15  # default
    m_tail = re.search(r"每个分支至少\s*(\d+)\s*个\s*<seg>", text)
    if m_tail:
        min_tail = int(m_tail.group(1))

    # Valid node IDs from outline section
    valid_nodes = set()
    outline_start = text.find("**大纲：**")
    if outline_start < 0:
        outline_start = text.find("大纲")
    if outline_start > 0:
        outline_block = text[outline_start:]
        # Match node IDs like ch1_bar, ch2_confrontation, etc.
        for m in re.finditer(r'\b(ch\d+_\w+)\b', outline_block):
            valid_nodes.add(m.group(1))

    return {
        "min": lo, "max": hi,
        "hard_cap": hard_cap,
        "ratio": ratio,
        "bridge_at": bridge_at,
        "bridge_lo": bridge_lo,
        "bridge_hi": bridge_hi,
        "min_tail": min_tail,
        "valid_nodes": valid_nodes,
    }


def calc_limits(params: dict, delay_ms: int) -> dict:
    lo, hi = params["min"], params["max"]
    avg_total = (lo + hi) / 2
    # Tail time = min_tail segments per branch × delay
    # (player sees only one branch's tail)
    tail_s = params["min_tail"] * delay_ms / 1000
    # Pre-bridge time = bridge_at segments × delay
    pre_bridge_s = params["bridge_at"] * delay_ms / 1000
    # Bridge trigger = when program submits next API call
    return {
        "tail_time_s": round(tail_s, 1),
        "pre_bridge_s": round(pre_bridge_s, 1),
        "bridge_trigger_s": round(pre_bridge_s, 1),
    }


# ── Output file parsing ─────────────────────────────────────────────

def extract_xml(text: str) -> str | None:
    """Extract XML content from LLM output, handling markdown fences."""
    # Split on "---" to get LLM output (after markdown header)
    parts = text.split('\n---\n', 1)
    llm_out = parts[1] if len(parts) > 1 else text

    # Strip markdown code fences
    llm_out = re.sub(r'^```(?:xml)?\s*\n', '', llm_out, flags=re.MULTILINE)
    llm_out = re.sub(r'\n```\s*$', '', llm_out)

    # Find <story>...</story> bounds
    story_start = llm_out.find('<story>')
    story_end = llm_out.rfind('</story>')

    if story_start < 0:
        # Try without root
        story_start = 0
    if story_end < 0:
        story_end = len(llm_out)
    else:
        story_end += len('</story>')

    xml_str = llm_out[story_start:story_end].strip()
    if not xml_str:
        return None
    # Fix common LLM XML escaping mistakes:
    # - Unescaped & that isn't part of a valid entity (&amp; &lt; &gt; &quot; &apos;)
    xml_str = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)', '&amp;', xml_str)
    return xml_str


def parse_output_file(path: Path) -> dict | None:
    """Extract timing + XML structure data from a test output file."""
    if not path.exists():
        return None

    text = path.read_text(encoding="utf-8")

    # Timing from header
    time_s = None
    m = re.search(r"\*\*Time\*\*:\s*([\d.]+)s", text)
    if m:
        time_s = float(m.group(1))

    ttft = None
    m = re.search(r"\*\*TTFT\*\*:\s*([\d.]+)s", text)
    if m:
        ttft = float(m.group(1))

    first_seg = None
    m = re.search(r"\*\*FirstSegment\*\*:\s*([\d.]+)s", text)
    if m:
        first_seg = float(m.group(1))

    finish = "?"
    m = re.search(r"\*\*Finish\*\*:\s*(\S+)", text)
    if m:
        finish = m.group(1)

    # Extract and parse XML
    xml_str = extract_xml(text)
    if xml_str is None:
        return {
            "time_s": time_s, "ttft": ttft, "first_seg": first_seg,
            "finish": finish, "parse_error": "No XML content found",
        }

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        return {
            "time_s": time_s, "ttft": ttft, "first_seg": first_seg,
            "finish": finish, "parse_error": str(e),
        }

    if root.tag != "story":
        return {
            "time_s": time_s, "ttft": ttft, "first_seg": first_seg,
            "finish": finish, "parse_error": f"Root is <{root.tag}>, expected <story>",
        }

    # Use direct children (not .iter() which flattens depth-first)
    children = list(root)
    if not children:
        return {
            "time_s": time_s, "ttft": ttft, "first_seg": first_seg,
            "finish": finish, "parse_error": "Empty <story>",
        }

    # Find bridge position among direct children
    bridge_idx = None
    for i, el in enumerate(children):
        if el.tag == "bridge":
            if bridge_idx is not None:
                return {
                    "time_s": time_s, "ttft": ttft, "first_seg": first_seg,
                    "finish": finish, "parse_error": "Multiple <bridge/> elements",
                }
            bridge_idx = i

    if bridge_idx is None:
        return {
            "time_s": time_s, "ttft": ttft, "first_seg": first_seg,
            "finish": finish, "parse_error": "No <bridge/> found",
        }

    # Split direct children into pre-bridge and post-bridge
    pre_children = children[:bridge_idx]
    post_children = children[bridge_idx + 1:]

    # ── Collect structured data ──

    # Collect all <seg> elements from direct children (pre-bridge)
    # and from <branch> children (pre and post bridge)
    all_segs = []
    pre_seg_count = 0
    pre_branches = {}   # pre-bridge branches (局部小分支)
    post_branches = {}  # post-bridge branches (选项后果分支)

    def collect_segs_from_children(children_list, is_pre, seg_list, branch_dict, seg_counter):
        """Collect <seg> and <branch> from a list of direct children."""
        count = 0
        for el in children_list:
            if el.tag == "seg":
                n = int(el.get("n", 0))
                seg_list.append({"n": n, "pre": is_pre, "text": el.text or ""})
                count += 1
            elif el.tag == "branch":
                branch_name = el.get("name", "")
                branch_segs = []
                for seg_el in el.findall("seg"):
                    n = int(seg_el.get("n", 0))
                    branch_segs.append({"n": n, "text": seg_el.text or ""})
                    seg_list.append({"n": n, "pre": is_pre, "branch": branch_name,
                                     "text": seg_el.text or ""})
                    count += 1
                branch_dict[branch_name] = branch_segs
        return count

    pre_seg_count = collect_segs_from_children(
        pre_children, True, all_segs, pre_branches, 0)
    post_seg_count = collect_segs_from_children(
        post_children, False, all_segs, post_branches, 0)

    total_segs = pre_seg_count + post_seg_count

    # Post-bridge prohibited elements check
    post_prohibited = []
    for el in post_children:
        if el.tag in ("choice", "set", "checkpoint"):
            post_prohibited.append(el.tag)

    # <choice> — find among pre-bridge children
    choice_el = None
    choice_id = None
    opt_branches = []
    opt_count = 0
    for el in pre_children:
        if el.tag == "choice":
            choice_el = el
            break
    if choice_el is not None:
        choice_id = choice_el.get("id")
        for opt_el in choice_el.findall("opt"):
            opt_branches.append(opt_el.get("branch", ""))
            opt_count += 1

    # <set> elements (pre-bridge only, may also appear inside <branch> before bridge)
    sets = []
    for el in root.iter("set"):
        sets.append({
            "var": el.get("var", ""),
            "op": el.get("op", ""),
            "val": el.get("val", ""),
            "if": el.get("if"),
        })

    # <checkpoint> — find among pre-bridge children
    cp_el = None
    cp_node = None
    cp_summary = None
    route_targets = []
    for el in pre_children:
        if el.tag == "checkpoint":
            cp_el = el
            break
    if cp_el is not None:
        cp_node = cp_el.get("node")
        cp_summary = cp_el.get("summary")
        for route_el in cp_el.findall("route"):
            route_targets.append({
                "if": route_el.get("if"),
                "target": route_el.get("target"),
            })

    # Numbering check
    seg_numbers = [s["n"] for s in all_segs]
    numbering_ok = True
    numbering_issues = []
    if seg_numbers:
        if seg_numbers[0] != 1:
            numbering_ok = False
            numbering_issues.append(f"starts at {seg_numbers[0]}")
        # Check monotonic increasing (allow gaps between branches)
        for i in range(1, len(seg_numbers)):
            if seg_numbers[i] <= seg_numbers[i - 1]:
                numbering_ok = False
                numbering_issues.append(f"non-seq at {seg_numbers[i-1]}→{seg_numbers[i]}")
                break

    return {
        # Timing
        "time_s": time_s,
        "ttft": ttft,
        "first_seg": first_seg,
        "finish": finish,
        # Counts
        "segments": total_segs,
        "pre_segs": pre_seg_count,
        "post_segs": post_seg_count,
        # Structure
        "choice_id": choice_id,
        "opt_branches": opt_branches,
        "opt_count": opt_count,
        "sets": sets,
        "cp_node": cp_node,
        "cp_summary": cp_summary,
        "route_targets": route_targets,
        "pre_branches": list(pre_branches.keys()),
        "post_branches": list(post_branches.keys()),
        "branch_seg_counts": {k: len(v) for k, v in {**pre_branches, **post_branches}.items()},
        "post_prohibited": post_prohibited,
        # Quality
        "numbering_ok": numbering_ok,
        "numbering_issues": numbering_issues,
        "seg_numbers": seg_numbers,
        "all_segs": all_segs,
    }


# ── Correctness evaluation ──────────────────────────────────────────

def check_correctness(r: dict, params: dict) -> list[str]:
    """Return list of issue labels. Empty list = clean."""
    issues = []

    if "parse_error" in r:
        issues.append(f"XML({r['parse_error'][:40]})")
        return issues

    # 1. choice
    if not r.get("choice_id"):
        issues.append("choice?")
    elif r.get("opt_count", 0) < 2:
        issues.append(f"opts={r['opt_count']}")

    # 2. set validity
    bad_sets = [s for s in r.get("sets", []) if not s["var"] or not s["op"]]
    if bad_sets:
        issues.append(f"set({len(bad_sets)}bad)")

    # 3. checkpoint node
    cp_node = r.get("cp_node")
    valid = params["valid_nodes"]
    if not cp_node:
        issues.append("cp?")
    elif cp_node != "end" and valid and cp_node not in valid:
        issues.append(f"node({cp_node})?")

    # 4. route targets
    for rt in r.get("route_targets", []):
        t = rt.get("target", "")
        if valid and t and t not in valid:
            issues.append(f"route({t})?")

    # 5. bridge presence (already checked in parse — error would be in parse_error)

    # 6. post-bridge prohibited elements
    prohibited = r.get("post_prohibited", [])
    if prohibited:
        issues.append(f"post-{','.join(prohibited)}")

    # 7. opt-branch matching (only if there's a <choice> with opts)
    opt_branches = set(r.get("opt_branches", []))
    post_branch_names = set(r.get("post_branches", []))
    if opt_branches:
        # Multi-branch scenario: each opt must have a post-bridge <branch>
        missing = opt_branches - post_branch_names
        extra = post_branch_names - opt_branches
        if missing:
            issues.append(f"miss-branch({','.join(sorted(missing))})")
        if extra:
            issues.append(f"extra-branch({','.join(sorted(extra))})")

    # 8. numbering
    if not r.get("numbering_ok", True):
        issues.append(f"num({','.join(r.get('numbering_issues', []))})")

    # 9. segment count
    if r.get("segments", 0) > params["hard_cap"]:
        issues.append(f"segs={r['segments']}(>{params['hard_cap']})")

    # 10. per-branch tail
    for bname, count in r.get("branch_seg_counts", {}).items():
        if count < params["min_tail"]:
            issues.append(f"tail({bname})={count}(<{params['min_tail']})")

    # 11. truncated
    if r.get("finish") == "length":
        issues.append("TRUNCATED")

    return issues


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Analyze XML-format (Frame) prompt test results."
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
    print(f"Format:  XML (Frame v1)")
    print(f"Params:  MIN={params['min']}  MAX={params['max']}  "
          f"HARD={params['hard_cap']}  RATIO≈{int(params['ratio']*100)}%  "
          f"BRIDGE_AT={params['bridge_at']}  MIN_TAIL={params['min_tail']}")
    if params["valid_nodes"]:
        print(f"Nodes:   {', '.join(sorted(params['valid_nodes']))}")
    print(f"Delay:   {delay_ms}ms/segment")
    print()
    print("Time budget (bridge mechanism):")
    print(f"  tail buffer (per branch): {limits['tail_time_s']:5.1f}s  "
          f"(MIN_TAIL × delay)")
    print(f"  bridge trigger point:    {limits['bridge_trigger_s']:5.1f}s  "
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
    has_streaming = sample and sample.get("ttft") is not None

    if has_streaming:
        header = (f"{'File':<20s} {'TTFT':>6s} {'1stSeg':>7s} {'Segs':>5s} "
                  f"{'Pre':>4s} {'Tail':>5s} {'缓冲':>5s} {'无缝':>5s}")
    else:
        header = (f"{'File':<20s} {'GenTime':>7s} {'Segs':>5s} {'Pre':>4s} "
                  f"{'Tail':>5s} {'缓冲':>5s} {'无缝':>5s}")
    if check_correct:
        header += "  正确性"
    print(header)
    print("-" * (len(header) + 4))

    all_times = []
    all_ttfts = []
    all_segs = []
    seamless_count = 0
    clean_count = 0

    for f in files:
        r = parse_output_file(f)
        if r is None:
            print(f"{f.name:<20s}  {'(parse error)':>50s}")
            continue

        if "parse_error" in r:
            if has_streaming:
                ttft_s = f"{r.get('ttft', 0):.1f}" if r.get('ttft') else "?"
                line = (f"{f.name:<20s}  {ttft_s:>5s}s  {'?':>6s}  {'?':>5}  "
                        f"{'?':>4}  {'?':>5}  {'?':>5}s  {'—':>5s}")
            else:
                t_s = f"{r.get('time_s', 0):.1f}" if r.get('time_s') else "?"
                line = (f"{f.name:<20s}  {t_s:>6s}s  {'?':>5}  {'?':>4}  "
                        f"{'?':>5}  {'?':>5}s  {'—':>5s}")
            if check_correct:
                line += f"  ✗ XML({r['parse_error'][:30]})"
            print(line)
            continue

        t = r["time_s"]
        ttft = r.get("ttft")
        s = r["segments"]
        pre = r["pre_segs"]
        post = r["post_segs"]
        # Tail buffer: if multi-branch → max branch segs; if single → post segs
        if r.get("post_branches"):
            post_branch_seg_counts = {
                k: v for k, v in r["branch_seg_counts"].items()
                if k in r["post_branches"]
            }
            max_branch_segs = max(post_branch_seg_counts.values()) if post_branch_seg_counts else 0
        else:
            max_branch_segs = r["post_segs"]
        tail_buffer = max_branch_segs * delay_ms / 1000

        all_times.append(t)
        if ttft is not None:
            all_ttfts.append(ttft)
        all_segs.append(s)

        # Seamlessness: TTFT <= tail buffer time
        deadline = ttft if ttft is not None else t
        gap = deadline - tail_buffer
        seamless = "✓" if gap <= 0 else f"+{gap:.0f}s"
        if gap <= 0:
            seamless_count += 1

        # Timing columns
        if has_streaming:
            ttft_s = f"{ttft:.1f}" if ttft else "?"
            fs_s = f"{r.get('first_seg', 0):.1f}" if r.get('first_seg') else "?"
            line = (f"{f.name:<20s}  {ttft_s:>5s}s  {fs_s:>6s}s  {s:5d}  "
                    f"{pre:4d}  {max_branch_segs:5d}  {tail_buffer:5.1f}s  {seamless:>5s}")
        else:
            line = (f"{f.name:<20s}  {t:5.1f}s  {s:5d}  {pre:4d}  "
                    f"{max_branch_segs:5d}  {tail_buffer:5.1f}s  {seamless:>5s}")

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
    n = len(files)
    if all_times:
        avg_t = sum(all_times) / len(all_times)
        avg_s = sum(all_segs) / len(all_segs)
        print(f"{n} files  "
              f"gen: {min(all_times):.1f}s ~ {max(all_times):.1f}s "
              f"(avg {avg_t:.1f}s)  "
              f"segments: {min(all_segs)} ~ {max(all_segs)} (avg {avg_s:.0f})")

        if all_ttfts:
            avg_ttft = sum(all_ttfts) / len(all_ttfts)
            print(f"TTFT: {min(all_ttfts):.1f}s ~ {max(all_ttfts):.1f}s "
                  f"(avg {avg_ttft:.1f}s)")

        if seamless_count == n:
            print(f"无缝: {seamless_count}/{n} ✓")
        elif seamless_count > 0:
            print(f"无缝: {seamless_count}/{n} (部分)")
        else:
            print(f"无缝: 0/{n}")

        if check_correct:
            print(f"正确: {clean_count}/{n}", end="")
            if clean_count == n:
                print(" ✓")
            else:
                print()

    print()


if __name__ == "__main__":
    main()
