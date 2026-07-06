#!/usr/bin/env python3
"""Storyloom — AI-powered interactive text fiction game engine.

CLI entry point. Loads .env, shows main menu, routes to game loop.
"""

import argparse
import os
import sys

from storyloom.io.api_client import ApiClient, ApiError
from storyloom.io.display import Display
from storyloom.core.co_create import CoCreateFlow, CoCreationAborted
from storyloom.core.game_loop import GameLoop, GameState
from storyloom.config import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE
from storyloom.i18n import init_i18n, _

# ── Default story config (used until co-creation UI is built) ─────

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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="Storyloom — AI-powered interactive text fiction"
    )
    parser.add_argument(
        "--menu",
        action="store_true",
        help="Show main menu immediately",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save per-round prompt/response/metrics for debugging",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Skip co-creation, use default story",
    )
    parser.add_argument(
        "--lang",
        choices=sorted(SUPPORTED_LANGUAGES),
        default=None,
        help="Language for UI and story (zh-CN / en)",
    )
    return parser.parse_args(argv)


def main(output=None) -> None:
    """Main entry point.

    Args:
        output: Output stream for testing (defaults to sys.stdout).
    """
    # Resolve language early (needed for Display init)
    if output is None:
        args = parse_args()
    else:
        args = parse_args([])
    language = args.lang or os.environ.get("STORYLOOM_LANG") or DEFAULT_LANGUAGE
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE

    init_i18n(language)

    display = Display(output=output)

    display.output.write("\n")
    display.output.write(_("Storyloom — Interactive Fiction") + "\n")
    display.output.write("=" * 40 + "\n\n")

    # Load API client
    try:
        api_client = ApiClient()
    except RuntimeError as e:
        display.show_error(str(e))
        display.show_error(
            "请复制 .env.example 为 .env 并填入 API 配置。"
        )
        return

    if args.quick:
        run_game(display, api_client, debug=args.debug)
    else:
        show_main_menu(display, api_client, debug=args.debug)


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


def show_main_menu(display: Display, api_client: ApiClient,
                   debug: bool = False) -> None:
    """Show main menu and route user choices.

    Args:
        display: Display instance for output.
        api_client: API client for game calls.
        debug: If True, save per-round data to disk.
    """
    while True:
        display.show_main_menu(save_count=0)
        choice = display.get_input(_("Choose: "))

        if choice == "1":
            try:
                flow = CoCreateFlow(api_client, display)
                result = flow.run()
                run_game(display, api_client,
                         story_config=result.story_config,
                         outline_text=result.outline_text,
                         debug=debug)
            except CoCreationAborted:
                display.output.write(_("Returning to menu.") + "\n")
            except ApiError as e:
                display.show_error(_("API error: {msg}").format(msg=e))
        elif choice == "2":
            display.show_wait_message(
                _("Loading: {feature}").format(feature="继续游戏（加载存档）"))
        elif choice == "3":
            display.show_wait_message(
                _("Loading: {feature}").format(feature="管理存档"))
        elif choice == "4":
            display.output.write(_("Goodbye.") + "\n")
            break
        else:
            display.output.write(_("Invalid choice, try again.") + "\n")


def _make_debug_observer(output_dir: str):
    """Create an observer that saves per-round data to disk.

    Args:
        output_dir: Base directory for round data output.

    Returns:
        Callable suitable as GameLoop observer.
    """
    import json
    from pathlib import Path

    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)

    def observer(record):
        rd = base / f"round-{record.round_number}"
        rd.mkdir(parents=True, exist_ok=True)

        # Full messages array
        (rd / "messages.json").write_text(
            json.dumps(record.messages_sent, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Raw LLM response
        (rd / "response.txt").write_text(record.raw_response, encoding="utf-8")

        # Metrics
        metrics = {
            "round": record.round_number,
            "ttft": record.ttft,
            "tokens": record.tokens,
            "node": record.node,
            "branch": record.selected_branch,
            "timestamp": record.timestamp,
        }
        (rd / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Parsed summary
        if record.parsed:
            parsed_summary = {
                "total_segs": record.parsed.total_segments,
                "pre_segs": record.parsed.pre_segments,
                "post_segs": record.parsed.post_segments,
                "bridge": record.parsed.bridge_found,
                "checkpoint": record.parsed.checkpoint_node,
                "checkpoint_summary": record.parsed.checkpoint_summary,
                "choices": record.parsed.choices,
                "sets": [
                    {"var": s.var, "op": s.op, "val": s.val, "if": s.condition}
                    for s in record.parsed.sets
                ],
                "routes": [
                    {"target": r.target, "condition": r.condition}
                    for r in record.parsed.routes
                ],
            }
            (rd / "parsed.json").write_text(
                json.dumps(parsed_summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    return observer


def run_game(
    display: Display,
    api_client: ApiClient,
    story_config: dict | None = None,
    outline_text: str | None = None,
    debug: bool = False,
) -> None:
    """Run the narrative game loop.

    Args:
        display: Display instance for output.
        api_client: API client for LLM calls.
        story_config: Story config (from co-creation or default).
        outline_text: Outline text (from co-creation or default).
        debug: If True, save per-round prompt/response/metrics to disk
               under tests/data/output/debug-{timestamp}/.
    """
    if story_config is None:
        story_config = DEFAULT_STORY_CONFIG
    if outline_text is None:
        outline_text = SAMPLE_OUTLINE

    game_state = GameState(story_config)

    first_node = _extract_first_node(outline_text)
    first_goal = _extract_first_goal(outline_text)

    # Debug observer
    observer = None
    if debug:
        import time
        ts = time.strftime("%Y%m%d-%H%M%S")
        observer = _make_debug_observer(
            f"tests/data/output/debug-{ts}"
        )

    game_loop = GameLoop(
        story_config=story_config,
        outline_text=outline_text,
        api_client=api_client,
        display=display,
        game_state=game_state,
        current_node=first_node,
        goal=first_goal,
        observer=observer,
    )

    try:
        result = game_loop.start_round1()
    except ApiError as e:
        display.show_error(_("API error: {msg}").format(msg=e))
        return

    n_opts = 0  # will be updated when options are available

    # Main narrative loop
    while True:
        options = game_loop.get_available_options()

        if not options:
            try:
                result = game_loop.continue_round(choice_key=None)
            except ApiError as e:
                display.show_error(_("API error: {msg}").format(msg=e))
                break
            continue

        n_opts = len(options)
        choice = display.get_input("\n" + _("Choose an option (type quit to return to menu): ") + " ")

        if choice and choice.strip().lower() in ("quit", "exit", "q"):
            display.output.write(_("Returning to menu.") + "\n")
            return

        if choice and choice.strip().isdigit():
            idx = int(choice.strip())
            if 1 <= idx <= n_opts:
                try:
                    result = game_loop.continue_round(choice_key=choice.strip())
                except ApiError as e:
                    display.show_error(_("API error: {msg}").format(msg=e)) 
                    break
            else:
                display.output.write(
                    _("Invalid choice, please enter 1-{n}.").format(n=n_opts) + "\n")
        elif choice == "0":
            display.show_state(game_loop.game_state.state_vars)
        else:
            display.output.write(_("Enter a number or quit.") + "\n")


if __name__ == "__main__":
    main()
