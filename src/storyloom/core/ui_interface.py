"""UI abstraction protocol for headless (frontend) use."""

from typing import Protocol


class UiInterface(Protocol):
    """UI abstraction. Display implements this; frontends provide their own."""

    def write(self, text: str) -> None:
        """Display text to the user (info, prompts, wait messages, etc.)."""
        ...

    def show_error(self, text: str) -> None:
        """Display error message."""
        ...

    def ask(self, prompt: str) -> str:
        """Ask user for free-text input. Returns user's response."""
        ...
