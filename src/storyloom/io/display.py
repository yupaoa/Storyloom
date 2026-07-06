"""Terminal display management for Storyloom.

Handles all user-facing output: narrative segments, options, state display,
main menu, and user input. Uses gettext for i18n.
"""

import sys

try:
    import readline  # Unix: GNU readline for line editing & CJK-aware deletion
except ImportError:
    try:
        import pyreadline3 as readline  # Windows: pure-Python readline replacement
    except ImportError:
        pass  # Bare input() — Windows console natively handles CJK input correctly
import time

from storyloom.i18n import _
from storyloom.parser.xml_parser import Segment


class Display:
    """Manage terminal output for the interactive fiction engine.

    All output methods write to the configured output stream (default sys.stdout).
    """

    def __init__(self, output=None, auto_advance: bool = True):
        """Initialize display.

        Args:
            output: Output stream (defaults to sys.stdout).
            auto_advance: If True, auto-advance between segments with a short
                          delay instead of waiting for keypress.
        """
        self.output = output or sys.stdout
        self.auto_advance = auto_advance

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
        self.output.write(_("────────────────────────────────────\n"))
        self.output.write("【选择】\n\n")
        for i, (branch, label) in enumerate(zip(branches, labels)):
            self.output.write(f"  [{i + 1}] {label}\n")
        self.output.write("\n")
        self.output.write(
            _("[{min}-{max}] Choose an option (0 for status, Q to quit): ")
            .format(min=1, max=len(branches)) + "\n"
        )
        self.output.write(_("────────────────────────────────────\n"))
        self.output.flush()

    # ── State ──────────────────────────────────────────────────────

    def show_state(self, state_vars: dict) -> None:
        """Display current state variables.

        Args:
            state_vars: Dictionary of variable name to value.
        """
        self.output.write(_("────────────────────────────────────\n"))
        self.output.write(_("State\n\n"))
        if not state_vars:
            self.output.write(_("  (no state variables)\n"))
        else:
            for name, value in state_vars.items():
                self.output.write(f"  {name}: {value}\n")
        self.output.write(_("────────────────────────────────────\n"))
        self.output.flush()

    # ── Main Menu ──────────────────────────────────────────────────

    def show_main_menu(self, save_count: int) -> None:
        """Show the main menu with save count.

        Args:
            save_count: Number of existing save files.
        """
        self.output.write("\n")
        self.output.write(_("Storyloom — Interactive Fiction") + "\n")
        self.output.write("=" * 40 + "\n\n")
        self.output.write(_("  [1] New Game\n"))
        self.output.write(_("  [2] Continue\n"))
        if save_count > 0:
            self.output.write(f"      ({save_count} save(s))\n")
        self.output.write(_("  [3] Manage Saves\n"))
        self.output.write(_("  [4] Exit\n\n"))
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

    def write(self, text: str) -> None:
        """Display text. Part of UiInterface protocol."""
        self.output.write(text)
        self.output.flush()

    def ask(self, prompt: str) -> str:
        """Get user input. Part of UiInterface protocol."""
        return self.get_input(prompt)

    # ── Separators ─────────────────────────────────────────────────

    def show_separator(self) -> None:
        """Display a separator between segments within a round."""
        self.output.write(_("···") + "\n\n")
        self.output.flush()

    def show_section_break(self) -> None:
        """Display a section break (e.g., between rounds or major transitions)."""
        self.output.write(_("────────────────────────────────────\n\n"))
        self.output.flush()

    # ── Errors ─────────────────────────────────────────────────────

    def show_error(self, msg: str) -> None:
        """Display an error message.

        Args:
            msg: Error message to display.
        """
        self.output.write(_("Error: {msg}").format(msg=msg) + "\n\n")
        self.output.flush()
