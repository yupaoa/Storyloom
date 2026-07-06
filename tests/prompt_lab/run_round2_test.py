#!/usr/bin/env python3
"""Manual Round 1 → Round 2 nested test: package as conversation, send to API.

Usage:
  python3 tests/run_round2_test.py
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

# ── Load Round 1 data ────────────────────────────────────────────
r1_prompt_file = PROJECT_ROOT / "tests/prompt_lab/data/prompts/round1-linenum.txt"
r1_output_file = PROJECT_ROOT / "tests/prompt_lab/data/output/round1-linenum/prompt-test-01.md"

r1_prompt = r1_prompt_file.read_text(encoding="utf-8").strip()

# Extract Round 1 LLM output (after --- separator)
r1_md = r1_output_file.read_text(encoding="utf-8")
parts = r1_md.split("---\n", 1)
r1_output = parts[1] if len(parts) > 1 else r1_md

print("=" * 60)
print("Round 1 → Round 2 Nested Test")
print("=" * 60)

# ── Parse Round 1 output ─────────────────────────────────────────
r1_parsed = XmlParser.parse(r1_output)
print(f"\nRound 1 parsed: {r1_parsed.total_segments} segs, "
      f"checkpoint={r1_parsed.checkpoint_node}, "
      f"choice={r1_parsed.choice_id}")
print(f"Bridge text: {r1_parsed.bridge_text[:80]}...")

# ── Build Round 2 prompt (simulate player chose option 2) ────────
pb = PromptBuilder()

# Simulate state after Round 1: player chose key "2" (sync_refuse),
# so approach==2 — no 芯片同步率 change, stay at 0
current_state = {"芯片同步率": 0, "所属势力": "自由佣兵"}

r2_user = pb.build_round_n(
    current_node="ch2_confrontation",
    goal="与耗子会面，完成交易谈判",
    completed_nodes=["ch1_bar"],
    state_vars=current_state,
    bridge_text=r1_parsed.bridge_text,
)

print(f"\nRound 2 prompt ({len(r2_user)} chars):")
print("-" * 40)
print(r2_user[:500] + "..." if len(r2_user) > 500 else r2_user)
print("-" * 40)

# ── Build messages array (ContextManager style) ──────────────────
messages = [
    {"role": "user", "content": r1_prompt},
    {"role": "assistant", "content": r1_output},
    {"role": "user", "content": r2_user},
]

print(f"\nMessages: {len(messages)} entries")
print(f"  [0] user: {len(r1_prompt)} chars (Round 1 prompt)")
print(f"  [1] assistant: {len(r1_output)} chars (Round 1 output)")
print(f"  [2] user: {len(r2_user)} chars (Round 2 context)")

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
output_dir = PROJECT_ROOT / "tests/prompt_lab/data/output/round2-nested"
output_dir.mkdir(parents=True, exist_ok=True)

out_path = output_dir / "prompt-test-01.md"
out_path.write_text(
    f"# Test 01 — Round 2 (nested)\n\n"
    f"- **Time**: {elapsed:.1f}s\n"
    f"- **Model**: {MODEL}\n"
    f"- **Finish**: {finish_reason}\n"
    f"- **TTFT**: {ttft:.1f}s\n"
    f"- **Tokens**: prompt={usage.prompt_tokens if usage else 'N/A'}, "
    f"completion={usage.completion_tokens if usage else 'N/A'}\n"
    f"- **Timestamp**: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n\n"
    f"---\n"
    f"{content}",
    encoding="utf-8",
)
print(f"\nSaved to {out_path}")

# ── Parse & analyze Round 2 output ───────────────────────────────
print("\n" + "=" * 60)
print("Round 2 Analysis")
print("=" * 60)

r2_parsed = XmlParser.parse(content)

print(f"\nSegments: {r2_parsed.total_segments} (pre={r2_parsed.pre_segments}, "
      f"post={r2_parsed.post_segments})")
print(f"Bridge found: {r2_parsed.bridge_found}")

if r2_parsed.checkpoint_node:
    print(f"Checkpoint: {r2_parsed.checkpoint_node} — {r2_parsed.checkpoint_summary}")
    print(f"Routes: {[(r.target, r.condition) for r in r2_parsed.routes]}")
else:
    print("Checkpoint: NONE")

if r2_parsed.choices:
    for c in r2_parsed.choices:
        print(f"Choice: id={c['id']}, branches={c['branches']}")
else:
    print("Choice: NONE")

if r2_parsed.sets:
    for s in r2_parsed.sets:
        print(f"Set: {s.var} {s.op} {s.val}" + (f" if {s.condition}" if s.condition else ""))
else:
    print("Sets: NONE")

print(f"Post branches: {r2_parsed.post_branches}")
print(f"Numbering issues: {r2_parsed.numbering_issues}")

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
        # Find first break
        for i, (a, b) in enumerate(zip(nums, expected)):
            if a != b:
                print(f"  First break at index {i}: expected {b}, got {a}")
                break

# ── Bridge position ──────────────────────────────────────────────
bridge_idx = content.find("<bridge/>")
if bridge_idx == -1:
    bridge_idx = content.find("<bridge />")
total_chars = len(content)
if bridge_idx > 0:
    bridge_pct = bridge_idx / total_chars * 100
    print(f"Bridge position: ~{bridge_pct:.0f}% through output (char-based)")

# ── Show first & last few lines ──────────────────────────────────
lines = content.strip().split("\n")
print(f"\nFirst 5 lines:")
for line in lines[:5]:
    print(f"  {line}")
print(f"...")
print(f"Last 3 lines:")
for line in lines[-3:]:
    print(f"  {line}")
