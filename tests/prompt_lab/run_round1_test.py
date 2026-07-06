#!/usr/bin/env python3
"""Test Round 1 prompt in conversation (sliding window) architecture.

Two modes:
  1. Auto (default): uses PromptBuilder + fixture to generate prompt
  2. Manual: reads prompt from a text file via --prompt

Usage:
  python3 tests/run_round1_test.py                          # auto mode, 3 runs
  python3 tests/run_round1_test.py --runs 5                 # auto, 5 runs
  python3 tests/run_round1_test.py --prompt round1-v2.txt   # manual mode, 1 run
  python3 tests/run_round1_test.py --prompt round1-v2.txt --runs 3
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.storyloom.api_client import ApiClient, ApiError
from src.storyloom.prompt_builder import PromptBuilder
from src.storyloom.xml_parser import XmlParser, ParseError

# ── Test fixture (auto mode) ────────────────────────────────────────────

SAMPLE_STORY = {
    "genre": "赛博朋克冒险",
    "tier": "medium",
    "label": "霓虹深渊",
    "setting": "2087年新东京地下城，企业控制数据流，芯片即权力",
    "protagonist_name": "林焰",
    "protagonist_identity": "前荒坂安全顾问，现自由佣兵",
    "protagonist_traits": "冷静、道德灰色，有过载神经接口",
    "tone": "黑暗冷峻",
    "conflict": "一枚从企业R&D部门流出的神秘芯片正在寻找宿主",
    "characters": "耗子（地下情报贩子，亦敌亦友）、美智子（荒坂安全主管，前上司）",
    "variables": [
        {"name": "体力", "type": "number", "initial": 80},
        {"name": "理智值", "type": "number", "initial": 55},
        {"name": "信任度", "type": "number", "initial": 10},
        {"name": "芯片完整度", "type": "number", "initial": 100},
        {"name": "线索", "type": "list", "initial": []},
        {"name": "所属势力", "type": "string", "initial": "自由佣兵"},
    ],
}

SAMPLE_OUTLINE = """ch1_bar [completed] — 霓虹深渊：在酒吧获取情报
  → ch2_confrontation [active]
ch2_confrontation [active] — 地下交易：与耗子会面
  ├→ ch3_ally [pending]
  └→ ch3_betrayal [pending]
ch3_ally [pending] — 盟友之路：通过地下网络逃离
ch3_betrayal [pending] — 背叛之路：杀出重围
ch4_safehouse [pending] — 安全屋：揭开芯片秘密（结局）"""

VALID_NODES = {"ch1_bar", "ch2_confrontation", "ch3_ally", "ch3_betrayal", "ch4_safehouse"}
VALID_VARS = {v["name"] for v in SAMPLE_STORY["variables"]}
OUTPUT_DIR = PROJECT_ROOT / "tests" / "data" / "output" / "round1"
PROMPT_DIR = PROJECT_ROOT / "tests" / "data" / "prompts"


# ── Correctness checks ──────────────────────────────────────────────────

def check_correctness(parsed: "ParsedOutput | None", parse_error: str | None) -> list[str]:
    """Return list of issue strings. Empty list = clean."""
    issues = []

    if parse_error:
        issues.append(f"PARSE: {parse_error[:80]}")
        return issues
    if parsed is None:
        issues.append("PARSE: returned None")
        return issues

    # 1. Bridge
    if not parsed.bridge_found:
        issues.append("no-bridge")

    # 2. Choices
    if not parsed.choices:
        issues.append("no-choice")
    else:
        for c in parsed.choices:
            if len(c["branches"]) < 2:
                issues.append(f"few-opts({c['id']}={len(c['branches'])})")

    # 3. Checkpoint node
    if not parsed.checkpoint_node:
        issues.append("no-checkpoint")
    elif parsed.checkpoint_node not in VALID_NODES:
        issues.append(f"bad-node({parsed.checkpoint_node})")

    # 4. Route targets
    for rt in parsed.routes:
        if rt.target and rt.target not in VALID_NODES:
            issues.append(f"bad-route({rt.target})")

    # 5. opt ↔ branch match (last choice maps to post-bridge; earlier choices → pre-bridge)
    pre_set = set(parsed.pre_branches)
    post_set = set(parsed.post_branches)
    for c in parsed.choices[:-1]:  # all but last: pre-bridge local branches
        for b in c["branches"]:
            if b and b not in pre_set:
                issues.append(f"miss-pre-branch({c['id']}:{b})")
    if parsed.choices:  # last choice: post-bridge key branches
        last = parsed.choices[-1]
        last_branches = {b for b in last["branches"] if b}
        if last_branches:
            missing = last_branches - post_set
            if missing:
                issues.append(f"miss-branch({','.join(sorted(missing))})")
        extra = post_set - last_branches
        if extra:
            issues.append(f"extra-branch({','.join(sorted(extra))})")

    # 6. Numbering
    if parsed.numbering_issues:
        issues.append(f"num({';'.join(parsed.numbering_issues)})")

    # 7. Segment count 60-120
    if parsed.total_segments < 60:
        issues.append(f"too-few-segs({parsed.total_segments})")
    elif parsed.total_segments > 120:
        issues.append(f"too-many-segs({parsed.total_segments})")

    # 8. Bridge position 20%-80%
    if parsed.total_segments > 0:
        ratio = parsed.pre_segments / parsed.total_segments
        if ratio < 0.2:
            issues.append(f"bridge-early({ratio:.0%})")
        elif ratio > 0.8:
            issues.append(f"bridge-late({ratio:.0%})")

    # 9. Set var validity — only reference declared variables
    for s in parsed.sets:
        if s.var and s.var not in VALID_VARS:
            issues.append(f"bad-var({s.var})")

    # 10. Choice condition syntax — should use numbers, not letters
    if parsed.choice_id:
        for s in parsed.sets:
            if s.condition and parsed.choice_id in s.condition:
                # Check for letter-based reference like "foo==A"
                import re
                m = re.search(r'==([A-E])', s.condition)
                if m:
                    issues.append(f"choice-letter({s.condition})")
        for rt in parsed.routes:
            if rt.condition:
                import re
                m = re.search(r'==([A-E])', rt.condition)
                if m:
                    issues.append(f"route-letter({rt.condition})")

    return issues


# ── Single run ──────────────────────────────────────────────────────────

def run_one(index: int, client: ApiClient, prompt: str) -> dict:
    """Execute one API call, parse, check correctness."""
    out_path = OUTPUT_DIR / f"round1-test-{index:02d}.md"

    t0 = time.perf_counter()
    error = None

    try:
        content = client.chat([{"role": "user", "content": prompt}])
    except ApiError as e:
        error = str(e)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    elapsed = time.perf_counter() - t0

    if error:
        out_path.write_text(
            f"# Round 1 Test {index:02d} — ERROR\n\n"
            f"- **Time**: {elapsed:.1f}s\n"
            f"- **Error**: {error}\n",
            encoding="utf-8",
        )
        return {"index": index, "time": elapsed, "error": error}

    # Parse
    parsed = None
    parse_error = None
    try:
        parsed = XmlParser.parse(content)
    except ParseError as e:
        parse_error = str(e)

    issues = check_correctness(parsed, parse_error)

    # Write output
    header = (
        f"# Round 1 Test {index:02d}\n\n"
        f"- **Time**: {elapsed:.1f}s\n"
        f"- **Model**: {client.model}\n"
        f"- **Timestamp**: {datetime.now(timezone.utc).isoformat()}\n"
    )
    if issues:
        header += f"- **Issues**: {'; '.join(issues)}\n"
    else:
        header += "- **Issues**: ✓ CLEAN\n"
    header += "\n---\n\n"
    out_path.write_text(header + content, encoding="utf-8")

    return {
        "index": index,
        "time": elapsed,
        "segments": parsed.total_segments if parsed else 0,
        "pre_segs": parsed.pre_segments if parsed else 0,
        "post_segs": parsed.post_segments if parsed else 0,
        "choice_id": parsed.choice_id if parsed else None,
        "cp_node": parsed.checkpoint_node if parsed else None,
        "bridge_ok": parsed.bridge_found if parsed else False,
        "numbering_ok": len(parsed.numbering_issues) == 0 if parsed else False,
        "issues": issues,
    }


# ── Main ────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Test Round 1 prompt in conversation architecture."
    )
    p.add_argument("--runs", type=int, default=1)
    p.add_argument(
        "--prompt", type=str, default=None,
        help="Path to prompt text file (relative to tests/prompt_lab/data/prompts/). "
             "If not set, uses PromptBuilder auto-generate.",
    )
    args = p.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Resolve prompt source
    if args.prompt:
        prompt_path = Path(args.prompt)
        if not prompt_path.is_absolute():
            prompt_path = PROMPT_DIR / args.prompt
        if not prompt_path.exists():
            print(f"[ERROR] Prompt file not found: {prompt_path}")
            sys.exit(1)
        prompt = prompt_path.read_text(encoding="utf-8")
    else:
        pb = PromptBuilder()
        prompt = pb.build_round1(
            SAMPLE_STORY, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易"
        )
        # Auto-save for inspection / manual editing
        prompt_path = PROMPT_DIR / "round1-current.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")

    client = ApiClient()

    print(f"Model:  {client.model}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Runs:   {args.runs}")
    print(f"Prompt: {prompt_path} ({len(prompt)} chars)")
    print()

    results = []
    for i in range(1, args.runs + 1):
        print(f"[{i}/{args.runs}]", end=" ", flush=True)
        r = run_one(i, client, prompt)
        results.append(r)

        if "error" in r:
            print(f"ERROR: {r['error']}")
        else:
            status = "✓ CLEAN" if not r["issues"] else f"✗ {len(r['issues'])} issues"
            print(
                f"{r['time']:.1f}s  "
                f"segs={r['segments']}  pre={r['pre_segs']}  post={r['post_segs']}  "
                f"choice={r['choice_id']}  cp={r['cp_node']}  "
                f"bridge={'✓' if r['bridge_ok'] else '✗'}  "
                f"num={'✓' if r['numbering_ok'] else '✗'}  "
                f"{status}"
            )

    # Summary
    print()
    clean = sum(1 for r in results if not r.get("issues"))
    errors = sum(1 for r in results if "error" in r)
    print(f"Correct: {clean}/{args.runs}  Errors: {errors}/{args.runs}")

    times = [r["time"] for r in results if "error" not in r]
    if times:
        print(f"Time: min {min(times):.1f}s  max {max(times):.1f}s  "
              f"avg {sum(times)/len(times):.1f}s")

    segs = [r["segments"] for r in results if r.get("segments")]
    if segs:
        print(f"Segments: min {min(segs)}  max {max(segs)}  "
              f"avg {sum(segs)/len(segs):.0f}")

    all_issues = {}
    for r in results:
        for issue in r.get("issues", []):
            all_issues[issue] = all_issues.get(issue, 0) + 1
    if all_issues:
        print("\nIssue frequency:")
        for issue, count in sorted(all_issues.items(), key=lambda x: -x[1]):
            print(f"  {count}x  {issue}")
    elif clean == args.runs:
        print("\nAll runs clean! ✓")

    print(f"\nResults: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
