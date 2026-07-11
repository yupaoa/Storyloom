#!/usr/bin/env python3
"""Storyloom — AI-powered interactive text fiction game engine.

CLI test harness. Runs the game loop non-interactively; all output goes
through observers (filesystem when --debug, else discarded). No game
interaction — this is a developer tool for testing and data collection.
"""

import argparse
import os
import sys

from storyloom.io.api_client import ApiClient
from storyloom.core.game_loop import GameLoop, GameState
from storyloom.config import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE
from storyloom.i18n import init_i18n
from storyloom.cli_utils import make_debug_observer, make_print_observer

# ── Default story config (used with --quick) ────────────────────────

DEFAULT_STORY_CONFIG: dict = {
    "genre": "赛博朋克冒险",
    "tier": "medium",
    "label": "霓虹深渊",
    "setting": "2087年新东京地下城",
    "protagonist_name": "林焰",
    "protagonist_identity": "前荒坂公司安全顾问",
    "protagonist_traits": "冷静、理性、道德灰色地带",
    "tone": "黑暗冷峻",
    "conflict": "一枚神秘生物芯片正在寻找宿主，各方势力暗中角逐",
    "characters": "耗子（情报贩子）、美智子（安全主管）、老陈（地下医生）",
    "variables": [
        {"name": "体力", "type": "number", "initial": 80},
        {"name": "信任度", "type": "number", "initial": 10},
        {"name": "线索", "type": "number", "initial": 0},
        {"name": "所属势力", "type": "string", "initial": "自由佣兵"},
        {"name": "物品", "type": "list", "initial": []},
    ],
}

SAMPLE_OUTLINE = """ch1_intro [active] — 霓虹深渊：深夜的地下城酒吧
  → ch2_meeting [pending]
ch2_meeting [pending] — 接头：与神秘线人耗子会面
ch3_chase [pending] — 追逐：逃避荒坂的追捕
ch4_revelation [pending] — 真相：芯片的秘密逐渐揭开
ch5_ending [pending] — 结局：最终抉择"""


# ── CLI ──────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Storyloom — test harness for the narrative engine"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save per-round prompt/response/metrics to disk",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use default story config (skip co-creation)",
    )
    parser.add_argument(
        "--lang",
        choices=sorted(SUPPORTED_LANGUAGES),
        default=None,
        help="Language for UI strings (zh-CN / en)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=1,
        metavar="N",
        help="Number of rounds to run (default: 1). Auto-picks first option.",
    )
    parser.add_argument(
        "--choices",
        type=str,
        default=None,
        metavar="1,2,1",
        help="Comma-separated choice sequence (1-indexed). Overrides auto-pick.",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print per-round summary to stderr (one line per round).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output: include segment counts and token info in --print lines.",
    )
    return parser.parse_args(argv)


# ── Helpers ──────────────────────────────────────────────────────────

def _extract_first_node(outline_text: str) -> str:
    """Extract first node ID from outline text."""
    for line in outline_text.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("├") and not line.startswith("└") and not line.startswith("→"):
            parts = line.split()
            if parts:
                return parts[0]
    return ""


def _extract_first_goal(outline_text: str) -> str:
    """Extract first node goal from outline text."""
    for line in outline_text.strip().split("\n"):
        line = line.strip()
        if "：" in line:
            return line.split("：", 1)[1].strip()
    return ""


# ── Main ─────────────────────────────────────────────────────────────

def main(output=None, argv: list[str] | None = None) -> None:
    """Test harness entry point.

    Runs the game loop non-interactively for N rounds. All output goes
    through observers — the terminal shows nothing except errors.

    Args:
        output: Output stream (defaults to sys.stdout; StringIO for tests).
        argv: Argument list (defaults to sys.argv[1:]).
    """
    if output is None:
        args = parse_args()
    else:
        args = parse_args(argv if argv is not None else [])

    # Resolve language
    language = args.lang or os.environ.get("STORYLOOM_LANG") or DEFAULT_LANGUAGE
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE
    init_i18n(language)

    # Parse choice sequence
    choice_sequence: list[str] = []
    if args.choices:
        choice_sequence = [c.strip() for c in args.choices.split(",") if c.strip()]

    # Load API client
    try:
        api_client = ApiClient()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Copy .env.example to .env and fill in API configuration.", file=sys.stderr)
        sys.exit(1)

    if not args.quick:
        print("Error: --quick is required (co-creation not available in test harness).",
              file=sys.stderr)
        print("Use the web UI for interactive co-creation.", file=sys.stderr)
        sys.exit(1)

    # Build observers
    observers = []
    if args.debug:
        import time
        ts = time.strftime("%Y%m%d-%H%M%S")
        observers.append(make_debug_observer(f"tests/data/output/debug-{ts}"))
    if args.print:
        observers.append(make_print_observer(verbose=args.verbose))

    # Setup game
    story_config = DEFAULT_STORY_CONFIG
    outline_text = SAMPLE_OUTLINE

    game_state = GameState(story_config)
    first_node = _extract_first_node(outline_text)
    first_goal = _extract_first_goal(outline_text)

    game_loop = GameLoop(
        story_config=story_config,
        outline_text=outline_text,
        api_client=api_client,
        game_state=game_state,
        current_node=first_node,
        goal=first_goal,
        observers=observers,
    )

    # Run rounds
    n_rounds = max(1, args.rounds)
    failed = 0

    def _run_round(choice_key: str | None = None) -> None:
        """Drive one round via stream_round(), feeding choice at options."""
        gen = game_loop.stream_round()
        choice_fed = False
        try:
            event = next(gen)
            while True:
                if (event["type"] == "options"
                        and choice_key is not None
                        and not choice_fed):
                    event = gen.send(choice_key)
                    choice_fed = True
                elif event["type"] == "error":
                    raise RuntimeError(event["message"])
                event = next(gen)
        except StopIteration:
            pass

    # Round 1
    game_loop.start_game()
    try:
        _run_round()
    except Exception as e:
        print(f"Round 1 failed: {e}", file=sys.stderr)
        sys.exit(1)

    for r in range(1, n_rounds):
        options = game_loop.get_available_options()
        if not options:
            choice_key = None
        else:
            idx = r - 1
            if idx < len(choice_sequence):
                choice_key = choice_sequence[idx]
            else:
                choice_key = "1"
        try:
            _run_round(choice_key=choice_key)
        except Exception as e:
            failed += 1
            print(f"Round {r + 1} failed: {e}", file=sys.stderr)
            if not args.debug:
                sys.exit(1)

    if failed:
        print(f"Completed {n_rounds} round(s) — {failed} failed.",
              file=output or sys.stdout)
    else:
        print(f"Completed {n_rounds} round(s).", file=output or sys.stdout)


if __name__ == "__main__":
    main()
