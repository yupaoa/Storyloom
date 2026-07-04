#!/usr/bin/env python3
"""Quick test: send a prompt to DeepSeek N times in parallel, save results.

Usage:
  # Test a single prompt version (5 runs, parallel, streaming by default)
  python3 tests/run_prompt_test.py --prompt tests/data/prompts/default.txt

  # Specify output directory and run count
  python3 tests/run_prompt_test.py --prompt my-prompt.txt --output results/ --runs 3

  # Non-streaming mode (for comparison)
  python3 tests/run_prompt_test.py --prompt tests/data/prompts/default.txt --no-stream

  # Test multiple prompt versions
  python3 tests/run_prompt_test.py --prompt tests/data/prompts/v1.txt
  python3 tests/run_prompt_test.py --prompt tests/data/prompts/v2.txt

Setup:
  1. Copy .env.example to .env and fill in your DEEPSEEK_API_KEY
  2. Put prompt files in tests/data/prompts/ (or anywhere)
  3. Results auto-saved to tests/data/output/<prompt_name>/

Prompt file format:
  A plain text file containing the full LLM prompt (system + user combined).
  Split point: the first occurrence of '当前节点目标：'.
  Everything before  → system message
  Everything from there → user message

Metrics (streaming mode):
  - TTFT:        time from request to first token
  - FirstSegment: time from request to first numbered narrative segment
                 (i.e., when the program has enough content to start display)
  - Total:       total generation time
  These are the metrics that matter for bridge timing analysis.
"""

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

# ── Defaults ─────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "tests" / "data" / "output"


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


# ── Prompt loading ───────────────────────────────────────────────────
def load_prompt(path: Path) -> tuple[str, str]:
    """Return (system_prompt, user_message) from a prompt text file.

    The file contains the full LLM prompt (system + user combined).
    Split point: first occurrence of '当前节点目标：'.
    Everything before → system, from there → user.
    """
    text = path.read_text(encoding="utf-8").strip()
    split_marker = "当前节点目标："
    split_pos = text.find(split_marker)
    if split_pos == -1:
        raise RuntimeError(
            f"Split marker '{split_marker}' not found in {path}. "
            f"Make sure the prompt file contains both system prompt "
            f"and user message sections."
        )
    system_prompt = text[:split_pos].rstrip()
    user_message = text[split_pos:].strip()
    return system_prompt, user_message


# ── Single run ───────────────────────────────────────────────────────
def run_one(args: dict) -> dict:
    """Execute one API call, write result file. Returns summary dict."""
    index = args["index"]
    out_path = args["output_dir"] / f"prompt-test-{index:02d}.md"
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    use_stream = args.get("stream", True)

    t0 = time.perf_counter()
    ttft = None        # Time To First Token
    first_seg = None   # Time to first numbered segment
    finish_reason = None
    usage = None
    content_parts = []

    try:
        if use_stream:
            # ── Streaming mode: measure TTFT + FirstSegment ──────────
            stream = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": args["system_prompt"]},
                    {"role": "user", "content": args["user_message"]},
                ],
                temperature=0.8,
                max_tokens=8192,
                stream=True,
                stream_options={"include_usage": True},
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token_text = chunk.choices[0].delta.content
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    content_parts.append(token_text)
                    # Detect first complete numbered segment: "N. text\n"
                    if first_seg is None:
                        full_so_far = "".join(content_parts)
                        import re
                        if re.search(r'(?:^|\n)\d+\.\s+', full_so_far, re.MULTILINE):
                            first_seg = time.perf_counter() - t0
                if chunk.choices and chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason
                if hasattr(chunk, 'usage') and chunk.usage:
                    usage = chunk.usage
            content = "".join(content_parts)
        else:
            # ── Non-streaming mode ────────────────────────────────────
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": args["system_prompt"]},
                    {"role": "user", "content": args["user_message"]},
                ],
                temperature=0.8,
                max_tokens=8192,
                stream=False,
            )
            content = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason
            usage = response.usage

    except Exception as e:
        elapsed = time.perf_counter() - t0
        out_path.write_text(
            f"# Test {index:02d} — ERROR\n\n"
            f"- **Time**: {elapsed:.1f}s\n"
            f"- **Model**: {MODEL}\n"
            f"- **Error**: {e}\n",
            encoding="utf-8",
        )
        return {"index": index, "time": elapsed, "error": str(e)}

    elapsed = time.perf_counter() - t0

    # Build header
    header_lines = [
        f"# Test {index:02d}",
        "",
        f"- **Time**: {elapsed:.1f}s",
        f"- **Model**: {MODEL}",
        f"- **Finish**: {finish_reason}",
    ]
    if use_stream:
        header_lines.append(
            f"- **TTFT**: {ttft:.1f}s" if ttft else "- **TTFT**: N/A"
        )
        header_lines.append(
            f"- **FirstSegment**: {first_seg:.1f}s" if first_seg else "- **FirstSegment**: N/A"
        )
    if usage:
        header_lines.append(
            f"- **Tokens**: prompt={usage.prompt_tokens}, "
            f"completion={usage.completion_tokens}, "
            f"total={usage.total_tokens}"
        )
    header_lines.append(
        f"- **Timestamp**: {datetime.now(timezone.utc).isoformat()}"
    )
    header_lines.extend(["", "---", ""])
    header = "\n".join(header_lines)

    out_path.write_text(header + content, encoding="utf-8")
    return {
        "index": index,
        "time": elapsed,
        "ttft": ttft,
        "first_seg": first_seg,
        "tokens": usage.total_tokens if usage else None,
        "finish": finish_reason,
    }


# ── Main ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Send a prompt to DeepSeek N times in parallel, save results."
    )
    parser.add_argument(
        "--prompt", type=Path, required=True,
        help="Path to prompt text file (required). "
             "See tests/data/prompts/ for examples.",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Base output directory (default: {DEFAULT_OUTPUT}). "
             "A subdirectory named after the prompt file is created automatically.",
    )
    parser.add_argument(
        "--runs", type=int, default=5,
        help="Number of test runs (default: 5)",
    )
    parser.add_argument(
        "--no-stream", action="store_true",
        help="Use non-streaming mode (default: streaming for TTFT measurement)",
    )
    args = parser.parse_args()

    if not args.prompt.exists():
        print(f"[ERROR] Prompt file not found: {args.prompt}")
        sys.exit(1)

    system_prompt, user_message = load_prompt(args.prompt)

    use_stream = not args.no_stream

    # Auto-subdir: prompt "v1.txt" → output "v1/"
    output_dir = args.output / args.prompt.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Prompt:  {args.prompt}  ({len(system_prompt)} + {len(user_message)} chars)")
    print(f"Output:  {output_dir}")
    print(f"Model:   {MODEL}")
    print(f"Mode:    {'streaming' if use_stream else 'non-streaming'}")
    print(f"Runs:    {args.runs} (parallel)")
    print()

    shared = {
        "system_prompt": system_prompt,
        "user_message": user_message,
        "output_dir": output_dir,
        "stream": use_stream,
    }

    t_start = time.perf_counter()
    results = []

    with ThreadPoolExecutor(max_workers=args.runs) as executor:
        futures = {
            executor.submit(run_one, {"index": i, **shared}): i
            for i in range(1, args.runs + 1)
        }
        for future in as_completed(futures):
            r = future.result()
            results.append(r)
            i = r["index"]
            if "error" in r:
                print(f"[{i}/{args.runs}] ERROR after {r['time']:.1f}s: {r['error']}")
            elif use_stream:
                ttft_str = f"{r['ttft']:.1f}s" if r.get('ttft') else "N/A"
                seg_str = f"{r.get('first_seg', 0):.1f}s" if r.get('first_seg') else "N/A"
                print(
                    f"[{i}/{args.runs}] {r['time']:.1f}s  "
                    f"TTFT: {ttft_str}  FirstSeg: {seg_str}  "
                    f"tokens: {r['tokens']}  finish: {r['finish']}"
                )
            else:
                print(
                    f"[{i}/{args.runs}] {r['time']:.1f}s  "
                    f"tokens: {r['tokens']}  finish: {r['finish']}"
                )

    total_elapsed = time.perf_counter() - t_start
    results.sort(key=lambda x: x["index"])
    times = [r["time"] for r in results]
    print(f"\nWall clock: {total_elapsed:.1f}s")
    if times:
        print(f"Per-run: min {min(times):.1f}s  max {max(times):.1f}s  "
              f"avg {sum(times)/len(times):.1f}s")
    if use_stream:
        ttfts = [r.get("ttft") for r in results if r.get("ttft")]
        first_segs = [r.get("first_seg") for r in results if r.get("first_seg")]
        if ttfts:
            print(f"TTFT: min {min(ttfts):.1f}s  max {max(ttfts):.1f}s  "
                  f"avg {sum(ttfts)/len(ttfts):.1f}s")
        if first_segs:
            print(f"FirstSegment: min {min(first_segs):.1f}s  "
                  f"max {max(first_segs):.1f}s  "
                  f"avg {sum(first_segs)/len(first_segs):.1f}s")
    print(f"Results in {output_dir}/")


if __name__ == "__main__":
    main()
