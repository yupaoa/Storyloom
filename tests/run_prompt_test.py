#!/usr/bin/env python3
"""Quick test: send §4.3 prompt to DeepSeek, save response + timing.

Usage:
  1. Fill in DEEPSEEK_API_KEY in .env
  2. python3 tests/run_prompt_test.py

Runs 5 times, writes docs/spec/tests/prompt-test-01.md .. 05.md.
"""

import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

# ── Config ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPT_SOURCE = PROJECT_ROOT / "docs" / "spec" / "prompt-design.md"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "spec" / "tests"
RUNS = 5

# ── Load .env ───────────────────────────────────────────────────────
def load_env(path: Path) -> dict[str, str]:
    env = {}
    if not path.exists():
        print(f"[ERROR] {path} not found. Create it from .env template.")
        sys.exit(1)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env

env = load_env(PROJECT_ROOT / ".env")

API_KEY = env.get("DEEPSEEK_API_KEY", "")
BASE_URL = env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = env.get("DEEPSEEK_MODEL", "deepseek-chat")

if "your-api-key" in API_KEY or not API_KEY:
    print("[ERROR] Fill in DEEPSEEK_API_KEY in .env first.")
    sys.exit(1)

# ── Extract §4.3 prompt ─────────────────────────────────────────────
def extract_prompt(path: Path) -> tuple[str, str]:
    """Return (system_prompt, user_message) from the §4.3 code block."""
    text = path.read_text(encoding="utf-8")

    # Find §4.3 section
    m_start = re.search(r"^### 4\.3 Prompt 示例", text, re.MULTILINE)
    if not m_start:
        raise RuntimeError("§4.3 header not found in prompt-design.md")

    # Find the first ``` after §4.3 header
    code_start = text.find("```", m_start.end())
    if code_start == -1:
        raise RuntimeError("Code block start not found after §4.3")

    # Find the matching closing ```
    code_end = text.find("```", code_start + 3)
    if code_end == -1:
        raise RuntimeError("Code block end not found")

    full_prompt = text[code_start + 3 : code_end].strip()

    # Split at "当前节点目标" — everything before is system, after is user
    split_marker = "当前节点目标："
    split_pos = full_prompt.find(split_marker)
    if split_pos == -1:
        raise RuntimeError(f"Split marker '{split_marker}' not found in prompt")

    system_prompt = full_prompt[:split_pos].rstrip()
    user_message = full_prompt[split_pos:].strip()

    return system_prompt, user_message


# ── Main ─────────────────────────────────────────────────────────────
def main():
    system_prompt, user_message = extract_prompt(PROMPT_SOURCE)

    print(f"System prompt: {len(system_prompt)} chars")
    print(f"User message:  {len(user_message)} chars")
    print(f"Model: {MODEL}")
    print(f"Base URL: {BASE_URL}")
    print(f"Runs: {RUNS}")
    print(f"Output: {OUTPUT_DIR}")
    print()

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for i in range(1, RUNS + 1):
        out_path = OUTPUT_DIR / f"prompt-test-{i:02d}.md"
        print(f"[{i}/{RUNS}] Sending to {MODEL}...", end=" ", flush=True)

        t0 = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.8,
                max_tokens=8192,
                stream=False,
            )
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"ERROR after {elapsed:.1f}s: {e}")
            out_path.write_text(
                f"# Test {i:02d} — ERROR\n\n"
                f"- **Time**: {elapsed:.1f}s\n"
                f"- **Model**: {MODEL}\n"
                f"- **Error**: {e}\n",
                encoding="utf-8",
            )
            continue

        elapsed = time.perf_counter() - t0
        content = response.choices[0].message.content
        finish_reason = response.choices[0].finish_reason
        usage = response.usage

        header = (
            f"# Test {i:02d}\n\n"
            f"- **Time**: {elapsed:.1f}s\n"
            f"- **Model**: {MODEL}\n"
            f"- **Finish**: {finish_reason}\n"
            f"- **Tokens**: prompt={usage.prompt_tokens}, "
            f"completion={usage.completion_tokens}, "
            f"total={usage.total_tokens}\n"
            f"- **Timestamp**: {datetime.now(timezone.utc).isoformat()}\n"
            f"\n---\n\n"
        )

        out_path.write_text(header + content, encoding="utf-8")
        print(
            f"{elapsed:.1f}s  "
            f"tokens: {usage.prompt_tokens}+{usage.completion_tokens}"
            f"={usage.total_tokens}"
            f"  finish: {finish_reason}"
        )

    print(f"\nDone. Results in {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
