"""Co-creation phase: user input → Q&A loop → story setup generation."""
import re
from dataclasses import dataclass

from src.storyloom.api_client import ApiClient
from src.storyloom.display import Display
from src.storyloom.config import (
    MAX_RETRIES,
    VARIABLE_CAP,
    VARIABLE_NUMERIC_CAP,
    VARIABLE_LABEL_CAP,
    OUTLINE_NODE_RANGES,
)


class CoCreateParser:
    """Stateless helpers for parsing LLM co-creation output."""

    BLOCK_DELIMITER = re.compile(r"^=== (story_config|variables|outline) ===\s*$")

    @staticmethod
    def split_blocks(text: str) -> dict[str, str]:
        """Split LLM response into {story_config, variables, outline} blocks.

        Args:
            text: Raw LLM response text.

        Returns:
            Dict with keys 'story_config', 'variables', 'outline'.
            Missing blocks have empty string values.
        """
        result = {"story_config": "", "variables": "", "outline": ""}
        current_block: str | None = None
        lines: list[str] = []

        for line in text.split("\n"):
            m = CoCreateParser.BLOCK_DELIMITER.match(line.strip())
            if m:
                if current_block and current_block in result:
                    result[current_block] = "\n".join(lines).strip()
                current_block = m.group(1)
                lines = []
            elif current_block:
                lines.append(line)

        if current_block and current_block in result:
            result[current_block] = "\n".join(lines).strip()

        return result
