"""Manages conversation messages array with sliding window + compression."""

from src.storyloom.config import WINDOW_SIZE, FIRST_COMPRESSION_AT
from src.storyloom.xml_parser import XmlParser
import re


class ContextManager:
    """Manages the messages array for conversation-based LLM interaction.

    Architecture:
      [0] Round 1 user (permanent anchor - format + story)
      [1] Round 1 assistant (permanent anchor - story opening)
      [... compressed rounds as user/assistant pair ...]
      [... last WINDOW_SIZE full rounds (user + assistant each) ...]
      [last] Current round user message

    Round 1 messages are NEVER removed or compressed.
    Rounds 2..N-WINDOW_SIZE-1 are compressed into checkpoint summaries.
    Rounds N-WINDOW_SIZE..N-1 are kept as full conversation history.
    """

    def __init__(self):
        self._round1_user: str | None = None
        self._round1_assistant: str | None = None
        self._rounds: list[dict] = []
        self._compressed_summaries: list[str] = []
        self._round_count: int = 0
        self._last_bridge_text: str = ""

    @property
    def round_count(self) -> int:
        return self._round_count

    def set_round1(self, user_content: str, assistant_content: str) -> None:
        """Set Round 1 messages (permanent anchor). Can only be called once."""
        if self._round1_user is not None:
            raise RuntimeError("Round 1 already set")
        self._round1_user = user_content
        self._round1_assistant = assistant_content
        self._round_count = 1

        # Extract bridge_text for next round
        self._last_bridge_text = self._extract_bridge_from_xml(assistant_content)

    def add_round(self, user_content: str, assistant_content: str) -> None:
        """Add a new round's messages and trigger compression if needed."""
        if self._round1_user is None:
            raise RuntimeError("Round 1 not set - call set_round1 first")

        checkpoint_text = self._extract_checkpoint_summaries(assistant_content)

        self._rounds.append({
            "round_num": self._round_count + 1,
            "user_content": user_content,
            "assistant_content": assistant_content,
            "checkpoint": checkpoint_text,
        })
        self._round_count += 1

        # Extract bridge_text for next round
        self._last_bridge_text = self._extract_bridge_from_xml(assistant_content)

        self._maybe_compress()

    def get_messages(self) -> list[dict]:
        """Build the full messages array for the next API call."""
        messages = []

        # Round 1 is always first and never compressed
        if self._round1_user:
            messages.append({"role": "user", "content": self._round1_user})
        if self._round1_assistant:
            messages.append({"role": "assistant", "content": self._round1_assistant})

        # Insert compressed summaries as a user/assistant pair
        if self._compressed_summaries:
            user_msg, asst_msg = self._build_compression_messages(
                self._compressed_summaries
            )
            messages.append({"role": "user", "content": user_msg})
            messages.append({"role": "assistant", "content": asst_msg})

        # Append the sliding window rounds in full
        window_rounds = self._get_window_rounds()
        for r in window_rounds:
            messages.append({"role": "user", "content": r["user_content"]})
            messages.append({"role": "assistant", "content": r["assistant_content"]})

        return messages

    def get_compressed_rounds(self) -> list[int]:
        """Return list of round numbers that have been compressed."""
        num_rounds = len(self._rounds)
        total_rounds = num_rounds + 1  # includes Round 1
        if total_rounds < FIRST_COMPRESSION_AT:
            return []
        window_count = min(WINDOW_SIZE, num_rounds)
        compressed_count = num_rounds - window_count
        if compressed_count > 0:
            return list(range(2, 2 + compressed_count))
        return []

    def get_window_rounds(self) -> list[int]:
        """Return list of round numbers currently in the window."""
        num_rounds = len(self._rounds)
        if num_rounds == 0:
            return []
        window_count = min(WINDOW_SIZE, num_rounds)
        start = num_rounds - window_count
        return list(range(start + 2, num_rounds + 2))

    def get_last_bridge_text(self) -> str:
        """Return bridge_text from the most recent round."""
        return self._last_bridge_text

    def get_compressed_summaries(self) -> list[str]:
        """Return compressed checkpoint summary strings."""
        return list(self._compressed_summaries)

    def _maybe_compress(self) -> None:
        """Compress rounds that have fallen out of the window."""
        total_rounds = len(self._rounds) + 1
        if total_rounds < FIRST_COMPRESSION_AT:
            return

        window_count = min(WINDOW_SIZE, len(self._rounds))
        keep_start = len(self._rounds) - window_count
        if keep_start < 0:
            keep_start = 0

        for i in range(keep_start):
            cp = self._rounds[i].get("checkpoint", "")
            if cp and cp not in self._compressed_summaries:
                self._compressed_summaries.append(cp)

    def _get_window_rounds(self) -> list[dict]:
        """Get the round dicts currently in the sliding window."""
        window_count = min(WINDOW_SIZE, len(self._rounds))
        return self._rounds[-window_count:] if window_count > 0 else []

    @staticmethod
    def _extract_checkpoint_summaries(xml: str) -> str:
        """Extract checkpoint summary from XML output."""
        match = re.search(r'<checkpoint[^>]*summary="([^"]*)"', xml)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_bridge_from_xml(xml: str) -> str:
        """Extract bridge text from assistant XML output. Returns empty string on failure."""
        try:
            parsed = XmlParser.parse(xml)
            return parsed.bridge_text
        except Exception:
            return ""

    @staticmethod
    def _build_compression_messages(summaries: list[str]) -> tuple[str, str]:
        """Build user/assistant message pair for compressed rounds."""
        items = "\n".join(f"- {s}" for s in summaries)
        user_msg = f"Key events so far:\n\n{items}"
        asst_msg = "(Summary of previous events. The story continues.)"
        return user_msg, asst_msg
