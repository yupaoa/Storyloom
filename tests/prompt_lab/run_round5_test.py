#!/usr/bin/env python3
"""Round 5 nested test — validates ContextManager compression trigger.

Compression rule: FIRST_COMPRESSION_AT=5, WINDOW_SIZE=3.
- R5 API call: 9 messages (no compression yet — all 4 prior rounds in full)
- After R5 response: add_round triggers compression of R2 → checkpoint summary
- get_messages() for R6 would show compressed array

Usage:
  python3 tests/run_round5_test.py
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
from storyloom.prompt_builder import PromptBuilder
from storyloom.xml_parser import XmlParser
from storyloom.context_manager import ContextManager

# ── Helpers ──────────────────────────────────────────────────────
def load_output(path):
    md = Path(path).read_text(encoding="utf-8")
    parts = md.split("---\n", 1)
    return parts[1] if len(parts) > 1 else md

def extract_branch_bridge_text(raw_xml, branch_name):
    pattern = rf'<branch name="{branch_name}">(.*?)</branch>'
    m = re.search(pattern, raw_xml, re.DOTALL)
    if not m: return ""
    segs = re.findall(r'<seg>(.*?)</seg>', m.group(1), re.DOTALL)
    return "\n".join(s.strip() for s in segs)

def count_segs_in_branch(text, branch_name):
    pattern = rf'<branch name="{branch_name}">(.*?)</branch>'
    m = re.search(pattern, text, re.DOTALL)
    return len(re.findall(r'<seg>(.*?)</seg>', m.group(1), re.DOTALL)) if m else 0

# ── Load all prior data ──────────────────────────────────────────
r1_prompt = (PROJECT_ROOT / "tests/prompt_lab/data/prompts/round1-linenum.txt").read_text(encoding="utf-8")
r1_out = load_output(PROJECT_ROOT / "tests/prompt_lab/data/output/round1-linenum/prompt-test-01.md")
r2_out = load_output(PROJECT_ROOT / "tests/prompt_lab/data/output/round2-nested/prompt-test-01.md")
r3_out = load_output(PROJECT_ROOT / "tests/prompt_lab/data/output/round3-nested/prompt-test-01.md")
r4_out = load_output(PROJECT_ROOT / "tests/prompt_lab/data/output/round4-nested/prompt-test-01.md")

r1_parsed = XmlParser.parse(r1_out)
r2_parsed = XmlParser.parse(r2_out)
r3_parsed = XmlParser.parse(r3_out)
r4_parsed = XmlParser.parse(r4_out)

# Branch-specific bridge texts
bridge_r1 = r1_parsed.bridge_text
bridge_r2 = extract_branch_bridge_text(r2_out, "betrayal_path")
bridge_r3 = extract_branch_bridge_text(r3_out, "industrial_route")
bridge_r4 = extract_branch_bridge_text(r4_out, "dive")  # Player chooses neural dive

print("=" * 60)
print("Round 5 Nested Test (compression boundary)")
print("=" * 60)

# ── Build ContextManager from scratch ────────────────────────────
pb = PromptBuilder()
cm = ContextManager()

# Round 1
r1_user = r1_prompt
cm.set_round1(r1_user, r1_out)
print(f"R1 set: round_count={cm.round_count}")

# Round 2
r2_user = pb.build_round_n(
    current_node="ch2_confrontation", goal="与耗子会面，完成交易谈判",
    completed_nodes=["ch1_bar"], state_vars={"芯片同步率": 0, "所属势力": "自由佣兵"},
    bridge_text=bridge_r1)
cm.add_round(r2_user, r2_out)
print(f"R2 added: round_count={cm.round_count}, compressed={cm.get_compressed_rounds()}, window={cm.get_window_rounds()}")

# Round 3
r3_user = pb.build_round_n(
    current_node="ch3_betrayal", goal="杀出重围：在美智子的追捕下逃脱",
    completed_nodes=["ch1_bar", "ch2_confrontation"],
    state_vars={"芯片同步率": -5, "所属势力": "自由佣兵"},
    bridge_text=bridge_r2)
cm.add_round(r3_user, r3_out)
print(f"R3 added: round_count={cm.round_count}, compressed={cm.get_compressed_rounds()}, window={cm.get_window_rounds()}")

# Round 4
r4_user = pb.build_round_n(
    current_node="ch4_safehouse", goal="揭开芯片秘密：抵达安全屋，面对最终结局",
    completed_nodes=["ch1_bar", "ch2_confrontation", "ch3_betrayal"],
    state_vars={"芯片同步率": -3, "所属势力": "自由佣兵"},
    bridge_text=bridge_r3)
cm.add_round(r4_user, r4_out)
print(f"R4 added: round_count={cm.round_count}, compressed={cm.get_compressed_rounds()}, window={cm.get_window_rounds()}")

# ── Pre-R5: check messages array (should have NO compression yet) ─
msgs_before_r5 = cm.get_messages()
print(f"\nPre-R5 messages: {len(msgs_before_r5)} entries")
for i, m in enumerate(msgs_before_r5):
    role = m['role']
    preview = m['content'][:60].replace('\n', ' ')
    print(f"  [{i}] {role}: {len(m['content'])} chars — {preview}...")

# ── Build R5 context ─────────────────────────────────────────────
# R4 state after choosing "dive" (key=2): 芯片同步率 = 45
r5_state = {"芯片同步率": 45, "所属势力": "自由佣兵"}

r5_user = pb.build_round_n(
    current_node="ch4_safehouse",
    goal="最终结局：芯片的秘密已经揭开，做出最后的决定",
    completed_nodes=["ch1_bar", "ch2_confrontation", "ch3_betrayal", "ch4_safehouse"],
    state_vars=r5_state,
    bridge_text=bridge_r4,
)

print(f"\nR5 prompt ({len(r5_user)} chars):")
print("-" * 40)
print(r5_user)
print("-" * 40)

# Append R5 user to messages
api_messages = msgs_before_r5 + [{"role": "user", "content": r5_user}]
print(f"API messages: {len(api_messages)} entries ({'NO compression' if 'Key events' not in str(api_messages) else 'compression ACTIVE'})")
for i, m in enumerate(api_messages):
    preview = m['content'][:50].replace('\n', ' ')
    print(f"  [{i}] {m['role']}: {len(m['content'])} chars — {preview}...")

# ⚠️ About to call the LLM API
print(f"\n⚠️  Preparing to send R5 request to {MODEL}...")
print(f"   Messages: {len(api_messages)} entries")

# ── Send to API ──────────────────────────────────────────────────
print(f"Sending...")
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

t0 = time.perf_counter()
ttft = None; finish_reason = None; usage = None; content_parts = []

try:
    stream = client.chat.completions.create(
        model=MODEL, messages=api_messages, max_tokens=12288,
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
    print(f"\nDone: {elapsed:.1f}s  TTFT: {ttft:.1f}s  finish: {finish_reason}")
    if usage:
        print(f"Tokens: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}, total={usage.total_tokens}")
except Exception as e:
    print(f"ERROR: {e}"); sys.exit(1)

# ── Save ─────────────────────────────────────────────────────────
output_dir = PROJECT_ROOT / "tests/prompt_lab/data/output/round5-nested"
output_dir.mkdir(parents=True, exist_ok=True)
out_path = output_dir / "prompt-test-01.md"
out_path.write_text(
    f"# Round 5 (nested, branch=dive)\n\n"
    f"- **Time**: {elapsed:.1f}s\n- **Model**: {MODEL}\n- **Finish**: {finish_reason}\n"
    f"- **TTFT**: {ttft:.1f}s\n"
    f"- **Tokens**: prompt={usage.prompt_tokens if usage else 'N/A'}, "
    f"completion={usage.completion_tokens if usage else 'N/A'}\n"
    f"- **Messages**: {len(api_messages)} entries (pre-compression)\n"
    f"- **Choices**: R2=betrayal, R3=industrial, R4=dive\n"
    f"- **Timestamp**: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n\n---\n{content}",
    encoding="utf-8")
print(f"Saved to {out_path}")

# ── Now trigger compression by adding R5 ─────────────────────────
cm.add_round(r5_user, content)
compressed = cm.get_compressed_rounds()
window = cm.get_window_rounds()
print(f"\nAfter R5 add_round: compressed_rounds={compressed}, window={window}")
print(f"Compression triggered! {'YES (FIRST_COMPRESSION_AT=5)' if compressed else 'NO'}")

# Show post-compression messages array (for R6)
msgs_post = cm.get_messages()
print(f"Post-R5 messages (ready for R6): {len(msgs_post)} entries")
for i, m in enumerate(msgs_post):
    preview = m['content'][:80].replace('\n', ' ')
    print(f"  [{i}] {m['role']}: {len(m['content'])} chars — {preview}...")

# ── Analyze R5 output ────────────────────────────────────────────
print("\n" + "=" * 60)
print("Round 5 Analysis")
print("=" * 60)

r5_parsed = XmlParser.parse(content)
print(f"Segments: {r5_parsed.total_segments} (pre={r5_parsed.pre_segments}, post={r5_parsed.post_segments})")
print(f"Bridge: {r5_parsed.bridge_found}")
print(f"Numbering issues: {r5_parsed.numbering_issues}")

if r5_parsed.checkpoint_node:
    print(f"Checkpoint: {r5_parsed.checkpoint_node} — {r5_parsed.checkpoint_summary}")
else: print("Checkpoint: NONE (epilogue/final)")

if r5_parsed.choices:
    for c in r5_parsed.choices: print(f"Choice: id={c['id']}, branches={c['branches']}")
else: print("Choice: NONE (epilogue)")

if r5_parsed.sets:
    for s in r5_parsed.sets:
        print(f"Set: {s.var} {s.op} {s.val}" + (f" if {s.condition}" if s.condition else ""))

print(f"Post branches: {r5_parsed.post_branches}")

# Line check
line_nums = re.findall(r'^(\d{3})\| ', content, flags=re.MULTILINE)
if line_nums:
    nums = [int(n) for n in line_nums]
    continuous = nums == list(range(1, nums[-1] + 1))
    dupes = len(nums) != len(set(nums))
    print(f"Lines: {len(nums)}, continuous={continuous}, dupes={dupes}")

# Time seamlessness vs R4 dive branch
dive_segs = count_segs_in_branch(r4_out, "dive")
rt = dive_segs * 0.5
ok = ttft < rt
print(f"\nTime seamlessness: R5 TTFT={ttft:.1f}s vs R4.dive reading={dive_segs}×0.5={rt:.1f}s → {'PASS' if ok else 'FAIL'}")

# Show excerpt
lines = content.strip().split("\n")
print(f"\nFirst 5 lines:")
for l in lines[:5]: print(f"  {l}")
print(f"Last 3 lines:")
for l in lines[-3:]: print(f"  {l}")
