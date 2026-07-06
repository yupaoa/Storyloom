#!/usr/bin/env python3
"""Manual Round 1→2→3→4 nested test with branch selection at each round.

Usage:
  python3 tests/run_round4_test.py
"""

import os, re, sys, time
from pathlib import Path

from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
env = os.environ.copy()
env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

API_KEY = env.get("DEEPSEEK_API_KEY", "")
BASE_URL = env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = env.get("DEEPSEEK_MODEL", "deepseek-chat")
if "your-api-key" in API_KEY or not API_KEY:
    print("ERROR: DEEPSEEK_API_KEY not set"); sys.exit(1)

sys.path.insert(0, str(PROJECT_ROOT))
from src.storyloom.prompt_builder import PromptBuilder
from src.storyloom.xml_parser import XmlParser

# ── Helpers ──────────────────────────────────────────────────────
def load_output(path):
    md = Path(path).read_text(encoding="utf-8")
    parts = md.split("---\n", 1)
    return parts[1] if len(parts) > 1 else md

def count_segs_in_branch(text, branch_name):
    pattern = rf'<branch name="{branch_name}">(.*?)</branch>'
    m = re.search(pattern, text, re.DOTALL)
    if not m: return 0
    return len(re.findall(r'<seg>(.*?)</seg>', m.group(1), re.DOTALL))

def extract_branch_bridge_text(raw_xml, branch_name):
    # Use regex approach to avoid XML parse issues with fragments
    pattern = rf'<branch name="{branch_name}">(.*?)</branch>'
    m = re.search(pattern, raw_xml, re.DOTALL)
    if not m: return ""
    segs = re.findall(r'<seg>(.*?)</seg>', m.group(1), re.DOTALL)
    return "\n".join(s.strip() for s in segs)

# ── Load all prior rounds ────────────────────────────────────────
r1_prompt = (PROJECT_ROOT / "tests/prompt_lab/data/prompts/round1-linenum.txt").read_text(encoding="utf-8")
r1_out = load_output(PROJECT_ROOT / "tests/prompt_lab/data/output/round1-linenum/prompt-test-01.md")
r2_out = load_output(PROJECT_ROOT / "tests/prompt_lab/data/output/round2-nested/prompt-test-01.md")
r3_out = load_output(PROJECT_ROOT / "tests/prompt_lab/data/output/round3-nested/prompt-test-01.md")

r1_parsed = XmlParser.parse(r1_out)
r2_parsed = XmlParser.parse(r2_out)
r3_parsed = XmlParser.parse(r3_out)

print("=" * 60)
print("Round 4 Nested Test")
print("=" * 60)

# ── Simulate player choices ──────────────────────────────────────
# R2 choice: key=2, branch=betrayal_path
# R3 choice: key=2, branch=industrial_route
R3_CHOICE_BRANCH = "industrial_route"

bridge_r1 = r1_parsed.bridge_text  # full bridge (for R2 context)
bridge_r2 = extract_branch_bridge_text(r2_out, "betrayal_path")
bridge_r3 = extract_branch_bridge_text(r3_out, R3_CHOICE_BRANCH)

print(f"R3 choice: {R3_CHOICE_BRANCH}")
print(f"R3 bridge text ({len(bridge_r3)} chars)")
print(f"R3 bridge segs: {count_segs_in_branch(r3_out, R3_CHOICE_BRANCH)}")

# ── State after Round 3 choice ────────────────────────────────────
# R2 set: 芯片同步率 -5 (choice 2)
# R3 set: 芯片同步率 = -3 (choice 2 = industrial_route)
current_state = {"芯片同步率": -3, "所属势力": "自由佣兵"}
print(f"State: {current_state}")

# ── Build Round 4 context ────────────────────────────────────────
pb = PromptBuilder()

r4_user = pb.build_round_n(
    current_node="ch4_safehouse",
    goal="揭开芯片秘密：抵达安全屋，面对最终结局",
    completed_nodes=["ch1_bar", "ch2_confrontation", "ch3_betrayal"],
    state_vars=current_state,
    bridge_text=bridge_r3,
)
print(f"\nR4 prompt ({len(r4_user)} chars)")
print("-" * 40)
print(r4_user)
print("-" * 40)

# ── Build full conversation ──────────────────────────────────────
# Reconstruct R2 & R3 user messages (same as prior tests)
r2_user = pb.build_round_n(
    current_node="ch2_confrontation", goal="与耗子会面，完成交易谈判",
    completed_nodes=["ch1_bar"], state_vars={"芯片同步率": 0, "所属势力": "自由佣兵"},
    bridge_text=bridge_r1)

r3_user = pb.build_round_n(
    current_node="ch3_betrayal", goal="杀出重围：在美智子的追捕下逃脱",
    completed_nodes=["ch1_bar", "ch2_confrontation"],
    state_vars={"芯片同步率": -5, "所属势力": "自由佣兵"},
    bridge_text=bridge_r2)

messages = [
    {"role": "user", "content": r1_prompt},
    {"role": "assistant", "content": r1_out},
    {"role": "user", "content": r2_user},
    {"role": "assistant", "content": r2_out},
    {"role": "user", "content": r3_user},
    {"role": "assistant", "content": r3_out},
    {"role": "user", "content": r4_user},
]

print(f"\nMessages: {len(messages)} entries")
for i, m in enumerate(messages):
    print(f"  [{i}] {m['role']}: {len(m['content'])} chars")

prompt_tokens_est = sum(len(m['content']) // 3 for m in messages)
print(f"Est. prompt tokens: ~{prompt_tokens_est}")

# ── Send to API ──────────────────────────────────────────────────
print(f"\nSending to {MODEL}...")
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

t0 = time.perf_counter()
ttft = None; finish_reason = None; usage = None; content_parts = []

try:
    stream = client.chat.completions.create(
        model=MODEL, messages=messages, max_tokens=12288,
        stream=True, stream_options={"include_usage": True})
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            if ttft is None: ttft = time.perf_counter() - t0
            content_parts.append(chunk.choices[0].delta.content)
        if chunk.choices and chunk.choices[0].finish_reason:
            finish_reason = chunk.choices[0].finish_reason
        if hasattr(chunk, 'usage') and chunk.usage: usage = chunk.usage

    content = "".join(content_parts)
    elapsed = time.perf_counter() - t0
    print(f"Done: {elapsed:.1f}s  TTFT: {ttft:.1f}s  finish: {finish_reason}")
    if usage:
        print(f"Tokens: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}, total={usage.total_tokens}")
except Exception as e:
    print(f"ERROR: {e}"); sys.exit(1)

# ── Save ─────────────────────────────────────────────────────────
output_dir = PROJECT_ROOT / "tests/prompt_lab/data/output/round4-nested"
output_dir.mkdir(parents=True, exist_ok=True)
out_path = output_dir / "prompt-test-01.md"
out_path.write_text(
    f"# Round 4 (nested, branch={R3_CHOICE_BRANCH})\n\n"
    f"- **Time**: {elapsed:.1f}s\n- **Model**: {MODEL}\n- **Finish**: {finish_reason}\n"
    f"- **TTFT**: {ttft:.1f}s\n"
    f"- **Tokens**: prompt={usage.prompt_tokens if usage else 'N/A'}, "
    f"completion={usage.completion_tokens if usage else 'N/A'}\n"
    f"- **Choices**: R2=betrayal_path, R3={R3_CHOICE_BRANCH}\n"
    f"- **Timestamp**: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n\n---\n{content}",
    encoding="utf-8")
print(f"Saved to {out_path}")

# ── Analyze ──────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Round 4 Analysis")
print("=" * 60)

r4_parsed = XmlParser.parse(content)
print(f"Segments: {r4_parsed.total_segments} (pre={r4_parsed.pre_segments}, post={r4_parsed.post_segments})")
print(f"Bridge: {r4_parsed.bridge_found}")
print(f"Numbering issues: {r4_parsed.numbering_issues}")

if r4_parsed.checkpoint_node:
    print(f"Checkpoint: {r4_parsed.checkpoint_node} — {r4_parsed.checkpoint_summary}")
    print(f"Routes: {[(r.target, r.condition) for r in r4_parsed.routes]}")
else: print("Checkpoint: NONE")

if r4_parsed.choices:
    for c in r4_parsed.choices: print(f"Choice: id={c['id']}, branches={c['branches']}")
else: print("Choice: NONE")

if r4_parsed.sets:
    for s in r4_parsed.sets:
        print(f"Set: {s.var} {s.op} {s.val}" + (f" if {s.condition}" if s.condition else ""))
else: print("Sets: NONE")

print(f"Post branches: {r4_parsed.post_branches}")

# Line check
line_nums = re.findall(r'^(\d{3})\| ', content, flags=re.MULTILINE)
if line_nums:
    nums = [int(n) for n in line_nums]
    continuous = nums == list(range(1, nums[-1] + 1))
    dupes = len(nums) != len(set(nums))
    print(f"Lines: {len(nums)}, continuous={continuous}, dupes={dupes}")

# Outline check
cp = r4_parsed.checkpoint_node
print(f"\nOutline: cp='{cp}'")
if cp == "ch4_safehouse": print("  ✓ Reached final node")
elif cp and cp.startswith("ch4"): print("  ~ ch4 area")
else: print(f"  ? Unexpected: {cp}")

# Time seamlessness
print(f"\nTime seamlessness:")
r3_branch_segs = count_segs_in_branch(r3_out, R3_CHOICE_BRANCH)
rt = r3_branch_segs * 0.5
ok = ttft < rt
print(f"  R4 TTFT={ttft:.1f}s vs R3.{R3_CHOICE_BRANCH} reading={r3_branch_segs}×0.5={rt:.1f}s → {'PASS' if ok else 'FAIL'}")

# Show excerpt
lines = content.strip().split("\n")
print(f"\nFirst 5 lines:")
for l in lines[:5]: print(f"  {l}")
print(f"Last 3 lines:")
for l in lines[-3:]: print(f"  {l}")
