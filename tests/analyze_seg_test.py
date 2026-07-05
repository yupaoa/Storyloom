#!/usr/bin/env python3
"""Analyze segment-length test results across multiple tiers.

Usage:
  python3 tests/analyze_seg_test.py [--output-dir DIR ...]
  python3 tests/analyze_seg_test.py --all   # auto-discover from manifest
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_header(file_path: Path) -> dict:
    """Extract metrics from a result file's header."""
    text = file_path.read_text(encoding="utf-8")
    data = {"file": str(file_path.resolve().relative_to(PROJECT_ROOT))}

    patterns = {
        "time": r"\*\*Time\*\*:\s*([\d.]+)s",
        "ttft": r"\*\*TTFT\*\*:\s*([\d.]+)s",
        "first_seg": r"\*\*FirstSegment\*\*:\s*([\d.]+)s",
        "finish": r"\*\*Finish\*\*:\s*(\w+)",
        "prompt_tokens": r"prompt=(\d+)",
        "completion_tokens": r"completion=(\d+)",
        "total_tokens": r"total=(\d+)",
    }

    string_keys = {"finish", "file"}
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            val = m.group(1)
            if key in string_keys:
                data[key] = val
            else:
                try:
                    data[key] = float(val) if "." in val else int(val)
                except ValueError:
                    data[key] = val

    return data


def count_segments(content: str) -> tuple:
    """Count total segs, pre-bridge segs, post-bridge segs."""
    segs = re.findall(r'<seg n="(\d+)"', content)
    if not segs:
        return 0, 0, 0

    total = len(segs)

    # Find bridge position
    bridge_pos = content.find("<bridge/>")
    if bridge_pos == -1:
        bridge_pos = content.find("<bridge />")
    before_bridge = content[:bridge_pos] if bridge_pos != -1 else content
    pre_segs = re.findall(r'<seg n="(\d+)"', before_bridge)
    pre_count = len(pre_segs)
    post_count = total - pre_count

    return total, pre_count, post_count


def check_correctness(content: str) -> dict:
    """Run all correctness checks. Returns dict of check_name -> bool."""
    checks = {}

    # XML validity
    try:
        ET.fromstring(content.strip())
        checks["xml_valid"] = True
    except ET.ParseError:
        checks["xml_valid"] = False

    # Bridge count
    bridge_count = content.count("<bridge/>") + content.count("<bridge />")
    checks["bridge_count_1"] = bridge_count == 1

    # Checkpoint count
    cp_count = len(re.findall(r"<checkpoint\b", content))
    checks["checkpoint_le_1"] = cp_count <= 1

    # No interactive elements after bridge
    bridge_idx = max(
        content.find("<bridge/>") if "<bridge/>" in content else -1,
        content.find("<bridge />") if "<bridge />" in content else -1,
    )
    if bridge_idx != -1:
        after = content[bridge_idx:]
        checks["no_interactive_after_bridge"] = (
            "<choice" not in after
            and "<set" not in after
            and "<checkpoint" not in after
        )

    # Seg numbering
    seg_nums = [int(n) for n in re.findall(r'<seg n="(\d+)"', content)]
    if seg_nums:
        checks["seg_starts_at_1"] = seg_nums[0] == 1
        checks["seg_continuous"] = seg_nums == list(
            range(seg_nums[0], seg_nums[-1] + 1)
        )
        checks["seg_no_duplicates"] = len(seg_nums) == len(set(seg_nums))
        checks["seg_count"] = len(seg_nums)
    else:
        checks["seg_starts_at_1"] = False
        checks["seg_continuous"] = False
        checks["seg_no_duplicates"] = False
        checks["seg_count"] = 0

    # Markdown fence / external text
    stripped = content.strip()
    checks["no_markdown_fence"] = not (
        stripped.startswith("```") or stripped.endswith("```")
    )

    # Prohibited dialogue: quotation marks in seg content
    dialogue_lines = re.findall(r"<seg n=\"\d+\">(.*?)</seg>", content)
    quote_count = sum(
        1 for d in dialogue_lines if '"' in d or "“" in d or "”" in d
    )
    checks["no_quoted_dialogue"] = quote_count == 0

    return checks


def aggregate(tiers_data: dict) -> str:
    """Build summary table from per-tier results."""
    lines = []
    header = (
        f"{'Tier':<16} {'Runs':>4}  {'TTFT(avg)':>9}  {'TTFT(min/max)':>16}  "
        f"{'Segs(avg)':>9}  {'Bridge%':>7}  {'Valid':>5}  {'Correct%':>7}  "
        f"{'Time(avg)':>9}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    bool_checks = [
        "xml_valid",
        "bridge_count_1",
        "checkpoint_le_1",
        "no_interactive_after_bridge",
        "seg_starts_at_1",
        "seg_continuous",
        "seg_no_duplicates",
        "no_markdown_fence",
        "no_quoted_dialogue",
    ]

    for label in sorted(tiers_data.keys()):
        runs = tiers_data[label]
        n = len(runs)

        ttfts = [r.get("ttft") for r in runs if r.get("ttft")]
        times = [r.get("time") for r in runs if r.get("time")]
        segs = [r.get("checks", {}).get("seg_count", 0) for r in runs]

        ttft_avg = sum(ttfts) / len(ttfts) if ttfts else 0
        ttft_min = min(ttfts) if ttfts else 0
        ttft_max = max(ttfts) if ttfts else 0
        seg_avg = sum(segs) / len(segs) if segs else 0
        time_avg = sum(times) / len(times) if times else 0

        # Bridge %
        pre_counts = [r.get("pre_segs", 0) for r in runs]
        post_counts = [r.get("post_segs", 0) for r in runs]
        total_pre = sum(pre_counts)
        total_post = sum(post_counts)
        bridge_pct = (
            total_pre / (total_pre + total_post) * 100
            if total_pre + total_post > 0
            else 0
        )

        # Valid count (XML parseable)
        valid_count = sum(
            1 for r in runs if r.get("checks", {}).get("xml_valid", False)
        )

        # Correct%
        correctness_scores = []
        for r in runs:
            c = r.get("checks", {})
            passed = sum(1 for k in bool_checks if c.get(k, False))
            correctness_scores.append(passed / len(bool_checks) * 100)
        correct_avg = (
            sum(correctness_scores) / len(correctness_scores)
            if correctness_scores
            else 0
        )

        ttft_range = f"{ttft_min:.1f} / {ttft_max:.1f}"
        lines.append(
            f"{label:<16} {n:>4}  {ttft_avg:>7.1f}s  {ttft_range:>16}  "
            f"{seg_avg:>7.0f}  {bridge_pct:>5.0f}%  {valid_count:>3}/{n:<3}  "
            f"{correct_avg:>5.0f}%  {time_avg:>7.1f}s"
        )

    # Constraint check
    lines.append("")
    lines.append(
        "Constraint check (TTFT < N * RATE * t, RATE=0.5, t=0.5s):"
    )
    for label in sorted(tiers_data.keys()):
        runs = tiers_data[label]
        ttfts = [r.get("ttft") for r in runs if r.get("ttft")]
        segs = [r.get("checks", {}).get("seg_count", 0) for r in runs]
        if ttfts and segs:
            max_ttft = max(ttfts)
            avg_segs = sum(segs) / len(segs)
            bridge_segs = avg_segs * 0.5
            reading_time = bridge_segs * 0.5
            ratio = max_ttft / reading_time if reading_time > 0 else float("inf")
            status = "PASS" if ratio < 1 else "FAIL"
            lines.append(
                f"  {label:<16}: max_TTFT={max_ttft:.1f}s, "
                f"bridge_reading={reading_time:.1f}s, "
                f"ratio={ratio:.2f} -> {status}"
            )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze segment-length test results."
    )
    parser.add_argument(
        "dirs", type=Path, nargs="*", help="Output directories to analyze."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Auto-discover test output dirs from manifest.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT
        / "tests"
        / "data"
        / "prompts"
        / "seg-test-manifest.json",
        help="Path to manifest JSON.",
    )
    args = parser.parse_args()

    dirs = []

    if args.all:
        manifest_path = args.manifest
        if not manifest_path.exists():
            print(f"Manifest not found: {manifest_path}")
            sys.exit(1)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for tier in manifest["tiers"]:
            label = tier["label"]
            output_dir = (
                PROJECT_ROOT / "tests" / "data" / "output" / f"seg-{label}"
            )
            if output_dir.exists():
                dirs.append(output_dir)
            else:
                print(f"SKIP: no output dir for {label} ({output_dir})")
    else:
        dirs = args.dirs

    if not dirs:
        print(
            "No output directories specified. Use --all or pass dirs directly."
        )
        sys.exit(1)

    tiers_data = defaultdict(list)

    for d in dirs:
        label = d.name.replace("seg-", "")
        for md_file in sorted(d.glob("prompt-test-*.md")):
            result = parse_header(md_file)

            # Extract XML content (everything after --- separator)
            text = md_file.read_text(encoding="utf-8")
            parts = text.split("---\n", 1)
            content = parts[1] if len(parts) > 1 else ""

            if content.strip():
                total, pre, post = count_segments(content)
                result["total_segs"] = total
                result["pre_segs"] = pre
                result["post_segs"] = post
                result["checks"] = check_correctness(content)

            tiers_data[label].append(result)

    print(aggregate(tiers_data))

    # Detailed per-run breakdown
    print("\n" + "=" * 60)
    print("Per-run Detail")
    print("=" * 60)
    bool_keys = [
        "xml_valid",
        "bridge_count_1",
        "checkpoint_le_1",
        "no_interactive_after_bridge",
        "seg_starts_at_1",
        "seg_continuous",
        "seg_no_duplicates",
        "no_markdown_fence",
        "no_quoted_dialogue",
    ]
    for label in sorted(tiers_data.keys()):
        print(f"\n--- {label} ---")
        for r in tiers_data[label]:
            c = r.get("checks", {})
            passed = sum(1 for k in bool_keys if c.get(k, False))
            total_bool = len(bool_keys)
            print(
                f"  {Path(r['file']).name}: "
                f"TTFT={r.get('ttft', 'N/A')}, "
                f"Segs={c.get('seg_count', 'N/A')}, "
                f"Valid={c.get('xml_valid', 'N/A')}, "
                f"Passed={passed}/{total_bool}"
            )


if __name__ == "__main__":
    main()
