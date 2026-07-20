"""Save file management for Storyloom.

Per-game directory structure with append-only checkpoint saves.
Per data-model.md §3.1-3.4.

Directory layout::

    saves/{label}_{compact_ts}/
        _init.json              # created at game start
        {cp_title}_{ts}.json    # per-checkpoint saves, appended
"""

import json
import os
import re
import shutil
import time
from pathlib import Path

from storyloom.config import SAVE_VERSION


class SaveManager:
    """Manage save files for a single game directory.

    Each game lives in its own subdirectory under ``saves/``.
    ``_init.json`` is the initial save; checkpoint
    saves are named ``{checkpoint_title}_{timestamp}.json`` and are
    never overwritten.
    """

    REQUIRED_FIELDS = [
        "story_config",
        "state_vars",
        "outline",
        "progress",
    ]

    ILLEGAL_CHARS_RE = re.compile(r'[/\\:*?"<>|]')
    LAST_PLAYED_FILE = ".last_played.json"

    # ── Instance — operate on a single game directory ──────────────

    def __init__(self, game_dir: str):
        """*game_dir* is a per-game path, e.g. ``saves/my_story_20260711T.../``."""
        self._dir = Path(game_dir)

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _sanitize(cls, label: str) -> str:
        """Replace filesystem-illegal characters with ``_``."""
        return cls.ILLEGAL_CHARS_RE.sub("_", label)

    @staticmethod
    def _compact_ts() -> str:
        """Compact UTC timestamp for filenames: ``20260711T142115Z``."""
        return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())

    # ── Save / Load / Delete / List (instance) ─────────────────────

    def save(self, save_data: dict, cp_title: str | None = None) -> str:
        """Save game state to a file.  Atomic write via temp + os.replace.

        Args:
            save_data: Complete save dict per data-model.md §3.1.
            cp_title: Checkpoint title for the filename.
                      ``None`` writes ``_init.json`` (once per game).

        Returns:
            The filename that was written.
        """
        self._ensure_dir()

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_data["metadata"]["updated_at"] = now_iso
        if (
            "created_at" not in save_data["metadata"]
            or not save_data["metadata"]["created_at"]
        ):
            save_data["metadata"]["created_at"] = now_iso

        if cp_title is None:
            filename = "_init.json"
        else:
            safe_title = self._sanitize(cp_title)
            filename = f"{safe_title}_{self._compact_ts()}.json"

        tmp_path = self._dir / f"{filename}.tmp"
        target_path = self._dir / filename

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

        os.replace(tmp_path, target_path)

        # Update last-played tracking so "Continue" picks up this save.
        label = save_data.get("metadata", {}).get(
            "label", save_data.get("story_config", {}).get("label", "")
        )
        SaveManager.write_last_played(
            str(self._dir.parent), self._dir.name, label, filename,
        )
        return filename

    def load(self, filename: str) -> dict:
        """Load and validate a save file.

        Args:
            filename: Exact filename (e.g. ``_init.json`` or
                      ``萌芽之春_20260713T133038Z.json``).

        Returns:
            Validated save data dict.

        Raises:
            FileNotFoundError: Save does not exist.
            ValueError: Save is corrupt (file is deleted automatically).
        """
        path = self._dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Save '{filename}' not found")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            self._remove_corrupt(path)
            raise ValueError(f"Save '{filename}' is corrupt: invalid JSON")

        # Validate version
        version = data.get("version")
        if version != SAVE_VERSION:
            self._remove_corrupt(path)
            raise ValueError(
                f"Save '{filename}' version {version} unsupported "
                f"(expected {SAVE_VERSION})"
            )

        # Validate required top-level fields
        missing = [f for f in self.REQUIRED_FIELDS if f not in data]
        if missing:
            self._remove_corrupt(path)
            raise ValueError(
                f"Save '{filename}' is corrupt: Missing required fields: "
                f"{', '.join(missing)}"
            )

        # Validate story_config has variables
        if "variables" not in data["story_config"]:
            self._remove_corrupt(path)
            raise ValueError(
                f"Save '{filename}' is corrupt: story_config missing variables"
            )

        # Validate current_node exists in outline
        current_node = data["progress"].get("current_node")
        if current_node:
            node_ids = {
                n.get("node_id", n.get("id", "")) for n in data["outline"]
            }
            if current_node not in node_ids and node_ids:
                self._remove_corrupt(path)
                raise ValueError(
                    f"Save '{filename}' is corrupt: current_node "
                    f"'{current_node}' not in outline"
                )

        return data

    @staticmethod
    def _remove_corrupt(path: Path) -> None:
        """Delete a corrupt save file.  Errors are silently ignored —
        the caller will raise the validation error regardless."""
        try:
            path.unlink()
        except OSError:
            pass

    def delete(self, filename: str) -> bool:
        """Delete a save file. Returns True if deleted, False if not found.
        Clears ``.last_played.json`` if it pointed to this save."""
        path = self._dir / filename
        if not path.exists():
            return False
        path.unlink()
        # Clear tracking file if it pointed to this save.
        root = str(self._dir.parent)
        tracked = SaveManager.read_last_played(root)
        if (
            tracked
            and tracked.get("game_id") == self._dir.name
            and tracked.get("save_file") == filename
        ):
            try:
                (Path(root) / SaveManager.LAST_PLAYED_FILE).unlink()
            except OSError:
                pass
        return True

    def list_saves(self) -> list[dict]:
        """List all saves in this game directory.

        Returns:
            List of ``{filename, checkpoint_title, checkpoint_node,
            round, saved_at, current_node}`` dicts.
        """
        self._ensure_dir()
        result = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            meta = data.get("metadata", {})
            progress = data.get("progress", {})

            # Read checkpoint info from completed outline nodes with summaries.
            # Falls back to legacy checkpoint_history for old saves.
            cp_title = ""
            cp_node = ""
            outline_nodes = data.get("outline", [])
            for node in reversed(outline_nodes):
                if node.get("status") == "completed" and node.get("summary"):
                    nid = node.get("node_id", node.get("id", ""))
                    cp_title = node.get("title", "")
                    cp_node = nid
                    break
            if not cp_node:
                cp_history = progress.get("checkpoint_history", [])
                if cp_history:
                    last_cp = cp_history[-1]
                    cp_title = last_cp.get("title", "")
                    cp_node = last_cp.get("node", "")

            result.append({
                "filename": path.name,
                "checkpoint_title": cp_title,
                "checkpoint_node": cp_node,
                "saved_at": meta.get("updated_at", ""),
                "current_node": progress.get("current_node", ""),
            })
        return result

    # ── Static — cross-game operations on saves/ root ─────────────

    @staticmethod
    def write_last_played(
        root: str, game_id: str, game_label: str, save_file: str
    ) -> None:
        """Write ``.last_played.json`` in *root*.  Atomic write.

        Called by ``GameSession.load_game()`` and ``SaveManager.save()``
        so that "Continue" can find the last-played save in O(1).

        Errors are silently ignored — this file is a cache, not game data.
        """
        data = {
            "game_id": game_id,
            "game_label": game_label,
            "save_file": save_file,
            "played_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        root_path = Path(root)
        try:
            root_path.mkdir(parents=True, exist_ok=True)
            tmp_path = root_path / f"{SaveManager.LAST_PLAYED_FILE}.tmp"
            target_path = root_path / SaveManager.LAST_PLAYED_FILE
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, target_path)
        except OSError:
            pass

    @staticmethod
    def read_last_played(root: str) -> dict | None:
        """Read and validate ``.last_played.json``.  Returns ``None`` on
        any failure (missing, corrupt JSON, stale reference).

        Validation:
        1. File exists and is valid JSON.
        2. ``game_id`` directory exists under *root*.
        3. ``save_file`` exists inside that directory.

        Any failure deletes the tracking file so the next write starts
        fresh.  Callers fall back to ``list_games()`` when ``None``.
        """
        root_path = Path(root)
        path = root_path / SaveManager.LAST_PLAYED_FILE
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            SaveManager._remove_corrupt(path)
            return None
        game_id = data.get("game_id", "")
        save_file = data.get("save_file", "")
        game_dir = root_path / game_id
        if not game_dir.is_dir() or not (game_dir / save_file).exists():
            SaveManager._remove_corrupt(path)
            return None
        return data

    @staticmethod
    def create_game(root: str, label: str) -> tuple[str, str, str]:
        """Create a new game directory under *root*.

        Args:
            root: Root saves directory, e.g. ``"saves"``.
            label: Story label (used in directory name).

        Returns:
            ``(game_dir, game_id, created_at)`` where *game_dir* is the
            absolute path, *game_id* is the directory name (uses compact
            timestamp for cross-platform filesystem safety), and
            *created_at* is the ISO 8601 UTC timestamp.
        """
        root_path = Path(root)
        root_path.mkdir(parents=True, exist_ok=True)
        created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        safe_label = SaveManager.ILLEGAL_CHARS_RE.sub("_", label)
        # Compact timestamp for directory name — colons in ISO 8601
        # extended format (HH:MM:SS) are invalid on Windows filesystems.
        game_id = f"{safe_label}_{SaveManager._compact_ts()}"
        game_dir = root_path / game_id
        game_dir.mkdir(exist_ok=False)
        return str(game_dir), game_id, created_at

    @staticmethod
    def list_games(root: str = "saves", enrich: bool = False) -> list[dict]:
        """List all games under *root* by reading each ``_init.json``.

        Args:
            root: Root saves directory.
            enrich: When True, adds ``last_played_at`` — the
                    ``updated_at`` of the most recently modified
                    save file in each game directory (one file-open
                    per game, no full iteration).

        Returns:
            List of ``{game_id, label, language, genre, tier,
            created_at, save_count[, last_played_at]}`` dicts.
        """
        root_path = Path(root)
        if not root_path.exists():
            return []
        result = []
        for game_dir in sorted(root_path.iterdir()):
            if not game_dir.is_dir():
                continue
            init_path = game_dir / "_init.json"
            if not init_path.exists():
                continue
            try:
                with open(init_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            meta = data.get("metadata", {})
            sc = data.get("story_config", {})
            save_files = list(game_dir.glob("*.json"))
            save_count = len(save_files)
            game_data = {
                "game_id": game_dir.name,
                "label": meta.get("label", game_dir.name),
                "language": sc.get("language", ""),
                "genre": sc.get("genre", ""),
                "tier": sc.get("tier", ""),
                "created_at": meta.get("created_at", ""),
                "save_count": save_count,
            }
            if enrich and save_files:
                try:
                    newest = max(save_files, key=lambda p: p.stat().st_mtime)
                except OSError:
                    game_data["last_played_at"] = ""
                else:
                    try:
                        with open(newest, "r", encoding="utf-8") as f:
                            d = json.load(f)
                        game_data["last_played_at"] = (
                            d.get("metadata", {}).get("updated_at", "")
                        )
                    except (json.JSONDecodeError, OSError):
                        game_data["last_played_at"] = ""
            result.append(game_data)
        return result

    @staticmethod
    def list_saves_for_game(root: str, game_id: str) -> list[dict]:
        """List saves in a game directory without creating a persistent
        ``SaveManager`` instance."""
        game_dir = os.path.join(root, game_id)
        if not os.path.isdir(game_dir):
            return []
        return SaveManager(game_dir).list_saves()

    @staticmethod
    def delete_game(root: str, game_id: str) -> bool:
        """Delete an entire game directory. Returns True if deleted.
        Clears ``.last_played.json`` if it pointed to the deleted game."""
        game_dir = Path(root) / game_id
        if not game_dir.exists():
            return False
        shutil.rmtree(game_dir)
        # Clear tracking file if it pointed to this game.
        tracked = SaveManager.read_last_played(root)
        if tracked and tracked.get("game_id") == game_id:
            try:
                (Path(root) / SaveManager.LAST_PLAYED_FILE).unlink()
            except OSError:
                pass
        return True
