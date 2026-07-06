#!/usr/bin/env python3
"""Manual Round 1 → Round 2 → Round 3 nested test with branch selection.

Simulates the full game loop: player choice → branch-specific bridge text →
state update → Round 3 context → API call.

Usage:
  python3 tests/run_round3_test.py
"""

import os
import re
import sys
import time
from pathlib import Path

from openai import OpenAI

# ── Setup ────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

env = os.environ.copy()
env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

API_KEY = env.get("DEEPSEEK_API_KEY", "")
BASE_URL = env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = env.get("DEEPSEEK_MODEL", "deepseek-chat")

if "your-api-key" in API_KEY or not API_KEY:
    print("ERROR: DEEPSEEK_API_KEY not set in .env")
    sys.exit(1)

sys.path.insert(0, str(PROJECT_ROOT))

from storyloom.prompt_builder import PromptBuilder
from storyloom.xml_parser import XmlParser
import xml.etree.ElementTree as ET

# ── Load previous round data ─────────────────────────────────────
r1_prompt = (PROJECT_ROOT / "tests/prompt_lab/data/prompts/round1-linenum.txt").read_text(encoding="utf-8")

def load_output(path: Path) -> str:
    md = path.read_text(encoding="utf-8")
    parts = md.split("---\n", 1)
    return parts[1] if len(parts) > 1 else md

r1_output = load_output(PROJECT_ROOT / "tests/prompt_lab/data/output/round1-linenum/prompt-test-01.md")
r2_output = load_output(PROJECT_ROOT / "tests/prompt_lab/data/output/round2-nested/prompt-test-01.md")

# ── Parse outputs ────────────────────────────────────────────────
r1_parsed = XmlParser.parse(r1_output)
r2_parsed = XmlParser.parse(r2_output)

print("=" * 60)
print("Round 3 Nested Test (with branch selection)")
print("=" * 60)

# ── Simulate player choice ───────────────────────────────────────
# Choose option 2: betrayal_path (betray 耗子)
PLAYER_CHOICE_KEY = "2"
PLAYER_CHOICE_BRANCH = "betrayal_path"
print(f"\nPlayer choice: key={PLAYER_CHOICE_KEY}, branch={PLAYER_CHOICE_BRANCH}")

# ── Extract branch-specific bridge text ──────────────────────────
def extract_branch_bridge_text(raw_xml: str, branch_name: str) -> str:
    """Extract bridge text for a specific branch, using XmlParser for safety."""
    # Must go through XmlParser to handle & escaping and line stripping
    parsed = XmlParser.parse(raw_xml)

    # Re-parse clean XML to navigate branches
    clean = re.sub(r'^\d{3}\| ', '', raw_xml, flags=re.MULTILINE)
    # Fix unescaped & (same as XmlParser._extract_xml)
    clean = re.sub(
        r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)",
        "&amp;",
        clean,
    )
    root = ET.fromstring(clean)

    children = list(root)
    bridge_idx = next(i for i, el in enumerate(children) if el.tag == "bridge")
    post_children = children[bridge_idx + 1:]

    texts = []
    for el in post_children:
        if el.tag == "branch" and el.get("name") == branch_name:
            for seg_el in el.findall("seg"):
                if seg_el.text:
                    texts.append(seg_el.text.strip())
            break
        elif el.tag == "seg" and not branch_name:
            if el.text:
                texts.append(el.text.strip())

    return "\n".join(texts)

bridge_text_betrayal = extract_branch_bridge_text(r2_output, PLAYER_CHOICE_BRANCH)
print(f"Branch bridge text ({len(bridge_text_betrayal)} chars):")
print(f"  {bridge_text_betrayal[:100]}...")

# ── Apply state changes from Round 2 choice ──────────────────────
# Round 2 sets: 芯片同步率 +15 if choice==1, -5 if choice==2
# Since player chose 2: 芯片同步率 -= 5
# (In real game loop, also apply unconditional sets from R2)
current_state = {
    "芯片同步率": -5,
    "所属势力": "自由佣兵",
}
print(f"\nState after Round 2 choice: {current_state}")

# ── Build Round 3 context ────────────────────────────────────────
pb = PromptBuilder()

r3_user = pb.build_round_n(
    current_node="ch3_betrayal",
    goal="杀出重围：在美智子的追捕下逃脱",
    completed_nodes=["ch1_bar", "ch2_confrontation"],
    state_vars=current_state,
    bridge_text=bridge_text_betrayal,
)
print(f"\nRound 3 prompt ({len(r3_user)} chars):")
print("-" * 40)
print(r3_user)
print("-" * 40)

# ── Build messages array (ContextManager style) ──────────────────
# Round 2 user context (from previous test)
pb2 = PromptBuilder()
r2_user = pb2.build_round_n(
    current_node="ch2_confrontation",
    goal="与耗子会面，完成交易谈判",
    completed_nodes=["ch1_bar"],
    state_vars={"芯片同步率": 0, "所属势力": "自由佣兵"},
    bridge_text=r1_parsed.bridge_text,
)

messages = [
    {"role": "user", "content": r1_prompt},
    {"role": "assistant", "content": r1_output},
    {"role": "user", "content": r2_user},
    {"role": "assistant", "content": r2_output},
    {"role": "user", "content": r3_user},
]

print(f"\nMessages: {len(messages)} entries")
for i, m in enumerate(messages):
    print(f"  [{i}] {m['role']}: {len(m['content'])} chars")

# ── Send to API ──────────────────────────────────────────────────
print(f"\nSending to {MODEL}...")
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

t0 = time.perf_counter()
ttft = None
finish_reason = None
usage = None
content_parts = []

try:
    stream = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=12288,
        stream=True,
        stream_options={"include_usage": True},
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            token_text = chunk.choices[0].delta.content
            if ttft is None:
                ttft = time.perf_counter() - t0
            content_parts.append(token_text)
        if chunk.choices and chunk.choices[0].finish_reason:
            finish_reason = chunk.choices[0].finish_reason
        if hasattr(chunk, 'usage') and chunk.usage:
            usage = chunk.usage

    content = "".join(content_parts)
    elapsed = time.perf_counter() - t0

    print(f"\nDone: {elapsed:.1f}s  TTFT: {ttft:.1f}s  finish: {finish_reason}")
    if usage:
        print(f"Tokens: prompt={usage.prompt_tokens}, "
              f"completion={usage.completion_tokens}, "
              f"total={usage.total_tokens}")

except Exception as e:
    print(f"\nERROR: {e}")
    sys.exit(1)

# ── Save output ──────────────────────────────────────────────────
output_dir = PROJECT_ROOT / "tests/prompt_lab/data/output/round3-nested"
output_dir.mkdir(parents=True, exist_ok=True)

out_path = output_dir / "prompt-test-01.md"
out_path.write_text(
    f"# Test 01 — Round 3 (nested, branch={PLAYER_CHOICE_BRANCH})\n\n"
    f"- **Time**: {elapsed:.1f}s\n"
    f"- **Model**: {MODEL}\n"
    f"- **Finish**: {finish_reason}\n"
    f"- **TTFT**: {ttft:.1f}s\n"
    f"- **Tokens**: prompt={usage.prompt_tokens if usage else 'N/A'}, "
    f"completion={usage.completion_tokens if usage else 'N/A'}\n"
    f"- **Player choice**: key={PLAYER_CHOICE_KEY}, branch={PLAYER_CHOICE_BRANCH}\n"
    f"- **Timestamp**: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n\n"
    f"---\n"
    f"{content}",
    encoding="utf-8",
)
print(f"\nSaved to {out_path}")

# ── Parse & analyze Round 3 output ───────────────────────────────
print("\n" + "=" * 60)
print("Round 3 Analysis")
print("=" * 60)

r3_parsed = XmlParser.parse(content)

print(f"\nSegments: {r3_parsed.total_segments} (pre={r3_parsed.pre_segments}, "
      f"post={r3_parsed.post_segments})")
print(f"Bridge found: {r3_parsed.bridge_found}")
print(f"Numbering issues: {r3_parsed.numbering_issues}")

if r3_parsed.checkpoint_node:
    print(f"Checkpoint: {r3_parsed.checkpoint_node} — {r3_parsed.checkpoint_summary}")
    print(f"Routes: {[(r.target, r.condition) for r in r3_parsed.routes]}")
else:
    print("Checkpoint: NONE ⚠️")

if r3_parsed.choices:
    for c in r3_parsed.choices:
        print(f"Choice: id={c['id']}, branches={c['branches']}")
else:
    print("Choice: NONE ⚠️")

if r3_parsed.sets:
    for s in r3_parsed.sets:
        print(f"Set: {s.var} {s.op} {s.val}" +
              (f" if {s.condition}" if s.condition else ""))
else:
    print("Sets: NONE")

print(f"Pre branches: {r3_parsed.pre_branches}")
print(f"Post branches: {r3_parsed.post_branches}")

# ── Line number check ────────────────────────────────────────────
line_nums = re.findall(r'^(\d{3})\| ', content, flags=re.MULTILINE)
if line_nums:
    nums = [int(n) for n in line_nums]
    expected = list(range(1, nums[-1] + 1))
    continuous = nums == expected
    duplicates = len(nums) != len(set(nums))
    print(f"\nLine numbers: {len(nums)} lines, "
          f"continuous={continuous}, duplicates={duplicates}")
    if not continuous:
        for i, (a, b) in enumerate(zip(nums, expected)):
            if a != b:
                print(f"  First break at index {i}: expected {b}, got {a}")
                break

# ── Outline progression check ────────────────────────────────────
outline_nodes = ["ch1_bar", "ch2_confrontation", "ch3_ally", "ch3_betrayal", "ch4_safehouse"]
if r3_parsed.checkpoint_node:
    cp = r3_parsed.checkpoint_node
    print(f"\nOutline check: checkpoint='{cp}'")
    if cp == "ch3_betrayal":
        print("  ✅ Correct: advancing along betrayal path")
    elif cp == "ch3_ally":
        print("  ⚠️ Wrong path: ally instead of betrayal")
    elif cp == "ch2_confrontation":
        print("  ⚠️ Stuck: didn't advance from Round 2")
    else:
        print(f"  ⚠️ Unexpected node: {cp}")

# ── Show excerpt ─────────────────────────────────────────────────
lines = content.strip().split("\n")
print(f"\nFirst 6 lines:")
for line in lines[:6]:
    print(f"  {line}")
print(f"...")
print(f"Last 3 lines:")
for line in lines[-3:]:
    print(f"  {line}")
