#!/usr/bin/env python3
"""Storyloom — AI-powered interactive text fiction game engine.

CLI entry point. Loads .env, shows main menu, routes to game loop.
"""

import argparse
import sys

from src.storyloom.api_client import ApiClient, ApiError
from src.storyloom.display import Display
from src.storyloom.game_loop import GameLoop, GameState

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
        help="Enable debug output",
    )
    return parser.parse_args(argv)


def main(output=None) -> None:
    """Main entry point.

    Args:
        output: Output stream for testing (defaults to sys.stdout).
    """
    display = Display(output=output)

    display.output.write("\n")
    display.output.write("Storyloom — 文字冒险\n")
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

    # Check API availability
    show_main_menu(display, api_client)


def show_main_menu(display: Display, api_client: ApiClient) -> None:
    """Show main menu and route user choices.

    Args:
        display: Display instance for output.
        api_client: API client for game calls.
    """
    while True:
        display.show_main_menu(save_count=0)
        choice = display.get_input("请选择: ")

        if choice == "1":
            run_game(display, api_client)
        elif choice == "2":
            display.show_wait_message("继续游戏（加载存档）—— 功能开发中")
        elif choice == "3":
            display.show_wait_message("管理存档 —— 功能开发中")
        elif choice == "4":
            display.output.write("再会。\n")
            break
        else:
            display.output.write("无效选择，请重试。\n")


def run_game(display: Display, api_client: ApiClient) -> None:
    """Run the narrative game loop.

    Args:
        display: Display instance for output.
        api_client: API client for LLM calls.
    """
    game_state = GameState(DEFAULT_STORY_CONFIG)

    game_loop = GameLoop(
        story_config=DEFAULT_STORY_CONFIG,
        outline_text=SAMPLE_OUTLINE,
        api_client=api_client,
        display=display,
        game_state=game_state,
        current_node="ch1_intro",
        goal="开场：来到地下城酒吧，感受氛围",
    )

    try:
        result = game_loop.start_round1()
    except ApiError as e:
        display.show_error(f"API 错误: {e}")
        return

    # Main narrative loop
    while True:
        options = game_loop.get_available_options()

        if not options:
            # No choice - continue automatically
            try:
                result = game_loop.continue_round(choice_key=None)
            except ApiError as e:
                display.show_error(f"API 错误: {e}")
                break
            continue

        # Player choice
        choice = display.get_input("\n输入选择 (输入 quit 返回菜单): ")

        if choice and choice.strip().lower() in ("quit", "exit", "q"):
            display.output.write("返回主菜单。\n")
            return

        if choice and choice.strip().isdigit():
            idx = int(choice.strip())
            if 1 <= idx <= len(options):
                try:
                    result = game_loop.continue_round(choice_key=choice.strip())
                except ApiError as e:
                    display.show_error(f"API 错误: {e}")
                    break
            else:
                display.output.write(f"无效选择，请输入 1-{len(options)}。\n")
        elif choice == "0":
            # Show state
            display.show_state(game_loop.game_state.state_vars)
        else:
            display.output.write("请输入数字或 quit。\n")


if __name__ == "__main__":
    main()
