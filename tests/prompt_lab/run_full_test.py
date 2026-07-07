#!/usr/bin/env python3
"""Multi-round narrative flow test — GameLoop-driven with observer.

Drives GameLoop (production code) through multiple rounds. Observer
saves per-round prompt/response/metrics. No business logic duplicated.

Usage:
  python3 tests/run_full_test.py              # 3 rounds (default)
  python3 tests/run_full_test.py --rounds 5   # 5 rounds
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Env ───────────────────────────────────────────────────────────
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
from storyloom.io.api_client import ApiClient
from storyloom.core.game_loop import GameLoop, GameState
from storyloom.cli_utils import make_debug_observer

# ── Config ────────────────────────────────────────────────────────
STORY_CONFIG = {
    "language": "zh-CN",
    "genre": "赛博朋克冒险",
    "setting": "2087年，新东京。超级企业掌控着从数据流到呼吸权的每一寸生存空间",
    "protagonist_name": "林焰",
    "protagonist_identity": "前荒坂安全顾问，现自由佣兵",
    "protagonist_traits": "冷静、果断、道德模糊，颈部植入军用级神经接口",
    "tone": "黑暗冷峻，高压、不信任、每个人都在隐藏秘密",
    "conflict": "一枚从荒坂R&D流出的神秘生物芯片，多方势力在暗中角逐",
    "characters": (
        "- 耗子 — 地下情报贩子，与林焰有旧账，亦敌亦友\n"
        "- 美智子 — 荒坂安全部门主管，林焰的前上司和曾经的导师"
    ),
    "variables": [
        {"name": "芯片同步率", "type": "number", "initial": 0},
        {"name": "所属势力", "type": "string", "initial": "自由佣兵"},
    ],
}

OUTLINE = """ch1_bar [active] — 霓虹深渊：在酒吧获取情报
  → ch2_confrontation [pending]
ch2_confrontation [pending] — 地下交易：与耗子会面
  ├→ ch3_ally [pending]
  └→ ch3_betrayal [pending]
ch3_ally [pending] — 盟友之路：通过地下网络逃离
ch3_betrayal [pending] — 背叛之路：杀出重围
ch4_safehouse [pending] — 安全屋：揭开芯片秘密（结局）"""

OUT_DIR = PROJECT_ROOT / "tests/prompt_lab/data/output/full-test"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ── Observer ──────────────────────────────────────────────────────
save_round = make_debug_observer(str(OUT_DIR))


# ── Choice simulation strategy ────────────────────────────────────
def pick_choice(options: list[dict], round_num: int) -> str:
    """Pick the 2nd option when available, otherwise the 1st."""
    if len(options) >= 2:
        return "2"
    return "1"


# ── Main ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    max_rounds = max(1, min(args.rounds, 6))

    print("=" * 60)
    print(f"Storyloom Full Test — {max_rounds} rounds  |  {MODEL}")
    print("=" * 60)

    # ── Production modules ────────────────────────────────────
    api_client = ApiClient()
    gs = GameState(STORY_CONFIG)

    goal_map = {
        "ch1_bar": "在酒吧获取情报，引出故事",
        "ch2_confrontation": "与耗子会面，完成交易谈判",
        "ch3_ally": "与耗子联手，通过地下网络逃离",
        "ch3_betrayal": "杀出重围，摆脱追捕",
        "ch4_safehouse": "揭开芯片秘密，面对最终结局",
    }

    game_loop = GameLoop(
        story_config=STORY_CONFIG,
        outline_text=OUTLINE,
        api_client=api_client,
        game_state=gs,
        current_node="ch1_bar",
        goal=goal_map["ch1_bar"],
        observer=save_round,
    )

    # ── Round 1 ───────────────────────────────────────────────
    print(f"\n{'─'*60}\nROUND 1  (ch1_bar)")
    print(f"  ⚠️  Calling API...")
    t0 = time.perf_counter()
    result = game_loop.start_round1()
    print(f"  ✓  {result.parsed.total_segments} segs  "
          f"({result.parsed.pre_segments} pre / {result.parsed.post_segments} post)  "
          f"bridge={'✓' if result.parsed.bridge_found else '✗'}")
    print(f"  Checkpoint: {result.parsed.checkpoint_node}")
    if result.parsed.choices:
        c = result.parsed.choices[-1]
        print(f"  Choice: {c['id']} → {c['branches']}")
    print(f"  State: {gs.state_vars}")

    # ── Rounds 2..N ───────────────────────────────────────────
    for rn in range(2, max_rounds + 1):
        print(f"\n{'─'*60}\nROUND {rn}")
        options = game_loop.get_available_options()

        if options:
            choice_key = pick_choice(options, rn)
            branch_name = options[int(choice_key) - 1]["branch"] if options else None
            print(f"  Options: {len(options)}  →  pick [{choice_key}] {branch_name}")
        else:
            choice_key = None
            branch_name = None
            print(f"  No options → auto-advance")

        print(f"  ⚠️  Calling API...")
        t0 = time.perf_counter()
        result = game_loop.continue_round(choice_key=choice_key)
        elapsed = time.perf_counter() - t0

        print(f"  ✓  {result.parsed.total_segments} segs  "
              f"({result.parsed.pre_segments} pre / {result.parsed.post_segments} post)  "
              f"bridge={'✓' if result.parsed.bridge_found else '✗'}")
        if result.parsed.checkpoint_node:
            routes = " → " + ", ".join(
                r.target for r in result.parsed.routes
            ) if result.parsed.routes else " (ending)"
            print(f"  Checkpoint: {result.parsed.checkpoint_node}{routes}")
        if result.parsed.choices:
            c = result.parsed.choices[-1]
            print(f"  Choice: {c['id']} → {c['branches']}")
        print(f"  State: {gs.state_vars}")

        if not result.parsed.routes and not result.parsed.choices:
            print("  ✓ No routes or choices — outline complete.")
            break

    print(f"\n{'='*60}")
    print(f"Test complete. Output: {OUT_DIR}")
    print(f"Final state: {gs.state_vars}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
