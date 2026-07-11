"""TerminalUi — minimal CLI implementing the UiInterface protocol."""

import sys


class TerminalUi:
    """Minimal CLI UI. Implements UiInterface protocol."""

    def write(self, text: str) -> None:
        """Display text with trailing newline."""
        print(text)

    def write_raw(self, text: str) -> None:
        """Write without trailing newline (for streaming tokens)."""
        sys.stdout.write(text)
        sys.stdout.flush()

    def show_error(self, text: str) -> None:
        """Display error message to stderr."""
        print(f"[Error] {text}", file=sys.stderr)

    def ask(self, prompt: str) -> str:
        """Ask user for input. Returns stripped response."""
        if prompt:
            print(prompt)
        try:
            return input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""
