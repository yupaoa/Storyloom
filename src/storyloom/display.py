"""Terminal display management for Storyloom.

Handles all user-facing output: narrative segments, options, state display,
main menu, and user input. All terminal output is in Chinese.
"""

import readline  # enables line editing, cursor movement, CJK-aware deletion
import sys
import time

from src.storyloom.xml_parser import Segment


class Display:
    """Manage terminal output for the interactive fiction engine.

    All output methods write to the configured output stream (default sys.stdout).
    """

    UI = {
        "zh-CN": {
            "banner": "Storyloom — 文字冒险",
            "menu_new": "[1] 新游戏",
            "menu_continue": "[2] 继续",
            "menu_manage": "[3] 管理存档",
            "menu_exit": "[4] 退出",
            "menu_prompt": "请选择: ",
            "menu_invalid": "无效选择，请重试。",
            "menu_goodbye": "再会。",
            "saves_count": "（{} 个存档）",
            "choose_option": "输入选择 (输入 quit 返回菜单): ",
            "invalid_choice": "无效选择，请输入 1-{}。",
            "enter_digit_or_quit": "请输入数字或 quit。",
            "return_to_menu": "返回主菜单。",
            "wait_game": "故事生成中...",
            "wait_loading": "功能开发中",
            "api_error": "API 错误: {}",
            "loading": "{} —— 功能开发中",
            # Co-creation
            "cc_header": "【共创阶段 — 故事设定】",
            "cc_idea_prompt": (
                "请描述你想玩的故事。\n"
                "例如：'赛博朋克背景下的爱情故事'、'古代仙侠世界的冒险'\n"
            ),
            "cc_idea_empty": "请输入一些想法来开始。",
            "cc_qna_header": "【追问阶段】",
            "cc_qna_desc": (
                "AI 会提出几个问题来了解你想玩的故事。\n"
                "回答完毕后输入 '开始' 即可生成故事设定。\n"
                "输入 '不玩了' 返回主菜单。\n"
            ),
            "cc_think": "思考中...",
            "cc_qna_prompt": "你的回答（或输入 '开始'/'不玩了'）> ",
            "cc_gen_wait": "正在编织故事世界...",
            "cc_fix_block": "修正{}中...（第{}次重试）",
            "cc_block_fail": "{} 解析失败（{}）。",
            "cc_retry_prompt": "[R]重试 / [M]返回主菜单: ",
            "cc_api_fail": "API 调用失败: {}",
            "cc_confirm_quit": "确定退出共创，返回主菜单？(y/n): ",
            "cc_gen_fail": "生成失败: {}",
            "cc_outline_fail": "大纲校验失败（{}）。",
        },
        "en": {
            "banner": "Storyloom — Interactive Fiction",
            "menu_new": "[1] New Game",
            "menu_continue": "[2] Continue",
            "menu_manage": "[3] Manage Saves",
            "menu_exit": "[4] Exit",
            "menu_prompt": "Choose: ",
            "menu_invalid": "Invalid choice, try again.",
            "menu_goodbye": "Goodbye.",
            "saves_count": "({} save(s))",
            "choose_option": "Choose (type quit to return to menu): ",
            "invalid_choice": "Invalid choice, please enter 1-{}.",
            "enter_digit_or_quit": "Enter a number or quit.",
            "return_to_menu": "Returning to menu.",
            "wait_game": "Generating story...",
            "wait_loading": "Under development",
            "api_error": "API error: {}",
            "loading": "{} — under development",
            # Co-creation
            "cc_header": "[Co-Creation — Story Setup]",
            "cc_idea_prompt": (
                "Describe the story you'd like to play.\n"
                "e.g. 'A cyberpunk love story', 'A wuxia adventure'\n"
            ),
            "cc_idea_empty": "Please share some thoughts to begin.",
            "cc_qna_header": "[Q&A Phase]",
            "cc_qna_desc": (
                "I'll ask a few questions to understand the story you want.\n"
                "When you're ready, type 'go' to generate the story setup.\n"
                "Type 'quit' to return to the main menu.\n"
            ),
            "cc_think": "Thinking...",
            "cc_qna_prompt": "Your answer (or type 'go'/'quit')> ",
            "cc_gen_wait": "Weaving your story world...",
            "cc_fix_block": "Fixing {}... (attempt {})",
            "cc_block_fail": "{} parsing failed ({}).",
            "cc_retry_prompt": "[R]etry / [M]enu: ",
            "cc_api_fail": "API call failed: {}",
            "cc_confirm_quit": "Abort co-creation and return to menu? (y/n): ",
            "cc_gen_fail": "Generation failed: {}",
            "cc_outline_fail": "Outline validation failed ({}).",
        },
    }

    def __init__(self, output=None, auto_advance: bool = True,
                 language: str = "zh-CN"):
        """Initialize display.

        Args:
            output: Output stream (defaults to sys.stdout).
            auto_advance: If True, auto-advance between segments with a short
                          delay instead of waiting for keypress.
            language: UI language code (zh-CN or en).
        """
        self.output = output or sys.stdout
        self.auto_advance = auto_advance
        self.language = language

    def t(self, key: str, *args) -> str:
        """Get translated UI string for current language.

        Args:
            key: String key in the UI dict.
            *args: Format arguments.

        Returns:
            Translated string, falling back to zh-CN if key is missing.
        """
        strings = self.UI.get(self.language, self.UI["zh-CN"])
        template = strings.get(key, self.UI["zh-CN"].get(key, key))
        if args:
            return template.format(*args)
        return template

    # ── Narrative ──────────────────────────────────────────────────

    def show_segment(self, seg: Segment, delay_ms: int = 300) -> None:
        """Display one narrative segment.

        Args:
            seg: The segment to display.
            delay_ms: Delay before showing when auto_advance is True.
        """
        text = seg.text

        if delay_ms > 0 and self.auto_advance:
            time.sleep(delay_ms / 1000.0)

        self.output.write(text)
        self.output.write("\n\n")
        self.output.flush()

    def show_segments(self, segments: list[Segment], delay_ms: int = 300) -> None:
        """Display multiple narrative segments in sequence.

        Args:
            segments: List of segments to display.
            delay_ms: Delay between segments when auto_advance is True.
        """
        for seg in segments:
            self.show_segment(seg, delay_ms=delay_ms)

    # ── Options ────────────────────────────────────────────────────

    def show_options(
        self, choice_id: str, branches: list[str], labels: list[str]
    ) -> None:
        """Render the option panel.

        Args:
            choice_id: The choice variable name (e.g., "approach").
            branches: List of branch names matching <opt> elements.
            labels: List of user-facing option text labels.
        """
        self.output.write("━" * 40 + "\n")
        self.output.write("【选择】\n\n")
        for i, (branch, label) in enumerate(zip(branches, labels)):
            self.output.write(f"  [{i + 1}] {label}\n")
        self.output.write("\n")
        self.output.write(f"(输入 1-{len(branches)} 选择，或输入 0 查看状态)\n")
        self.output.write("━" * 40 + "\n")
        self.output.flush()

    # ── State ──────────────────────────────────────────────────────

    def show_state(self, state_vars: dict) -> None:
        """Display current state variables.

        Args:
            state_vars: Dictionary of variable name to value.
        """
        self.output.write("═" * 40 + "\n")
        self.output.write("【状态】\n\n")
        if not state_vars:
            self.output.write("  （无状态变量）\n")
        else:
            for name, value in state_vars.items():
                self.output.write(f"  {name}: {value}\n")
        self.output.write("═" * 40 + "\n")
        self.output.flush()

    # ── Main Menu ──────────────────────────────────────────────────

    def show_main_menu(self, save_count: int) -> None:
        """Show the main menu with save count.

        Args:
            save_count: Number of existing save files.
        """
        self.output.write("\n")
        self.output.write("╔══════════════════════════════════╗\n")
        self.output.write("║        Storyloom 文字冒险         ║\n")
        self.output.write("╚══════════════════════════════════╝\n\n")
        self.output.write("  [1] 新游戏\n")
        self.output.write("  [2] 继续\n")
        if save_count > 0:
            self.output.write(f"      （{save_count} 个存档）\n")
        self.output.write("  [3] 管理存档\n")
        self.output.write("  [4] 退出\n\n")
        self.output.flush()

    # ── Status Messages ───────────────────────────────────────────

    def show_wait_message(self, msg: str) -> None:
        """Show a waiting/progress message.

        Args:
            msg: The message to display.
        """
        self.output.write(f"\n  {msg}\n\n")
        self.output.flush()

    # ── User Input ─────────────────────────────────────────────────

    def get_input(self, prompt: str = "") -> str:
        """Get user input.

        Args:
            prompt: Optional prompt string displayed before input.

        Returns:
            User's typed input string.
        """
        if prompt:
            self.output.write(prompt)
            self.output.flush()
        try:
            return input().strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    # ── Separators ─────────────────────────────────────────────────

    def show_separator(self) -> None:
        """Display a separator between segments within a round."""
        self.output.write("···\n\n")
        self.output.flush()

    def show_section_break(self) -> None:
        """Display a section break (e.g., between rounds or major transitions)."""
        self.output.write("\n" + "━" * 50 + "\n\n")
        self.output.flush()

    # ── Errors ─────────────────────────────────────────────────────

    def show_error(self, msg: str) -> None:
        """Display an error message.

        Args:
            msg: Error message to display.
        """
        self.output.write(f"\n! 错误: {msg}\n\n")
        self.output.flush()
