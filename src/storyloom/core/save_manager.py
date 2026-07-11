"""Save file management for Storyloom.

Atomic JSON save/load/delete/list. No LLM involvement.
Per data-model.md 3.1-3.4.
"""

import json
import os
import re
import time
from pathlib import Path

from storyloom.config import SAVE_VERSION


class SaveManager:
    """Manage save files on local filesystem.

    Each save is a single JSON file in saves_dir, named after
    story_config.label (sanitized for filesystem).
    """

    REQUIRED_FIELDS = [
        "story_config",
        "state_vars",
        "outline",
        "progress",
    ]

    ILLEGAL_CHARS_RE = re.compile(r'[/\\:*?"<>|]')

    def __init__(self, saves_dir: str = "saves"):
        self._dir = Path(saves_dir)

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _sanitize(self, label: str) -> str:
        """Sanitize label for use as filename."""
        return self.ILLEGAL_CHARS_RE.sub("_", label)

    def _path(self, label: str) -> Path:
        return self._dir / f"{self._sanitize(label)}.json"

    def save(self, save_data: dict) -> None:
        """Save game state to file. Atomic write via temp + os.replace.

        Args:
            save_data: Complete save dict per data-model.md 3.1.
        """
        self._ensure_dir()
        label = save_data["metadata"]["label"]
        save_data["metadata"]["updated_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        if (
            "created_at" not in save_data["metadata"]
            or not save_data["metadata"]["created_at"]
        ):
            save_data["metadata"]["created_at"] = save_data["metadata"]["updated_at"]

        tmp_path = self._dir / f"{self._sanitize(label)}.tmp"
        target_path = self._path(label)

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

        os.replace(tmp_path, target_path)

    def load(self, label: str) -> dict:
        """Load and validate a save file.

        Args:
            label: Save label (matches story_config.label).

        Returns:
            Validated save data dict.

        Raises:
            FileNotFoundError: Save does not exist.
            ValueError: Save is corrupt.
        """
        path = self._path(label)
        if not path.exists():
            raise FileNotFoundError(f"Save '{label}' not found")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            raise ValueError(f"Save '{label}' is corrupt: invalid JSON")

        # Validate version
        version = data.get("version")
        if version != SAVE_VERSION:
            raise ValueError(
                f"Save '{label}' version {version} unsupported (expected 1)"
            )

        # Validate required top-level fields
        missing = [f for f in self.REQUIRED_FIELDS if f not in data]
        if missing:
            raise ValueError(
                f"Save '{label}' is corrupt: Missing required fields: "
                f"{', '.join(missing)}"
            )

        # Validate story_config has variables
        if "variables" not in data["story_config"]:
            raise ValueError(
                f"Save '{label}' is corrupt: story_config missing variables"
            )

        # Validate current_node exists in outline
        current_node = data["progress"].get("current_node")
        if current_node:
            node_ids = {
                n.get("node_id", n.get("id", "")) for n in data["outline"]
            }
            if current_node not in node_ids and node_ids:
                raise ValueError(
                    f"Save '{label}' is corrupt: current_node "
                    f"'{current_node}' not in outline"
                )

        return data

    def delete(self, label: str) -> bool:
        """Delete a save file. Returns True if deleted, False if not found."""
        path = self._path(label)
        if not path.exists():
            return False
        path.unlink()
        return True

    def list_saves(self) -> list[dict]:
        """List all saves with metadata.

        Returns:
            List of {label, round_count, created_at, updated_at, current_node}.
        """
        self._ensure_dir()
        result = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                meta = data.get("metadata", {})
                progress = data.get("progress", {})
                result.append(
                    {
                        "label": meta.get("label", path.stem),
                        "round_count": meta.get("round_count", 0),
                        "created_at": meta.get("created_at", ""),
                        "updated_at": meta.get("updated_at", ""),
                        "current_node": progress.get("current_node", ""),
                    }
                )
            except (json.JSONDecodeError, KeyError):
                continue
        return result
