"""GameSession — lightweight lifecycle coordinator for the Storyloom engine.

Owns ApiClient. Wires CoCreateFlow → GameLoop transitions so the UI
doesn't need to know internal dependency order.

New game and load-game converge on the same code path::

    start_game(result) → _init.json → load_game(game_id, "_init.json")
    load_game(game_id, filename) → from_save_dict() → GameLoop

UI retains full control over rendering and interaction flow.
"""

import copy
import os
import time

from storyloom.config import SAVE_VERSION
from storyloom.io.api_client import ApiClient
from storyloom.core.save_manager import SaveManager
from storyloom.core.co_create import CoCreateFlow, CoCreationResult
from storyloom.core.game_loop import GameLoop, GameState


class GameSession:
    """Lightweight lifecycle coordinator.

    Does NOT control UI flow. UI calls methods at its own pace.

    Usage::

        session = GameSession()
        flow = session.new_co_create()
        # ... drive flow ...
        gl, game_id = session.start_game(flow.result)
        # ... drive gl.start_game() / gl.stream_round() ...
        # Or load:
        gl = session.load_game("game_id", "_init.json")
    """

    def __init__(self, api_client: ApiClient | None = None,
                 saves_dir: str = "saves"):
        self._api_client = api_client if api_client is not None else ApiClient()
        self._saves_root = saves_dir
        self._game_loop: GameLoop | None = None

    # ── Lifecycle ──────────────────────────────────────────────────

    def new_co_create(self) -> CoCreateFlow:
        return CoCreateFlow(self._api_client)

    def start_game(self, result: CoCreationResult) -> tuple[GameLoop, str]:
        """Create a new game from co-creation result.

        1. Create per-game directory under ``saves/``.
        2. Write ``_init.json`` directly from ``CoCreationResult``.
        3. Load via the unified ``load_game()`` path.

        Returns:
            ``(GameLoop, game_id)`` — UI uses *game_id* for subsequent
            save operations (list, delete, etc.).
        """
        label = result.story_config.get("label", "untitled")
        game_dir, game_id, created_at = SaveManager.create_game(
            self._saves_root, label
        )

        init_data = self._build_init_dict(result, created_at)
        SaveManager(game_dir).save(init_data)  # cp_title=None → _init.json

        return self.load_game(game_id, "_init.json"), game_id

    def load_game(self, game_id: str, filename: str) -> GameLoop:
        """Load a save file and return a ready-to-play ``GameLoop``.

        Args:
            game_id: Game directory name under ``saves/``.
            filename: Save file name (e.g. ``_init.json`` or
                      ``萌芽之春_20260713T133038Z.json``).
        """
        sm = SaveManager(os.path.join(self._saves_root, game_id))
        data = sm.load(filename)
        gl = GameLoop.from_save_dict(data, self._api_client)
        gl.set_save_manager(sm)
        self._game_loop = gl
        return gl

    # ── Save management ───────────────────────────────────────────

    def list_games(self) -> list[dict]:
        """List all games under ``saves/``.

        Returns:
            List of ``{game_id, label, language, genre, tier,
            created_at, save_count}`` dicts.
        """
        return SaveManager.list_games(self._saves_root)

    def list_saves(self, game_id: str) -> list[dict]:
        """List all saves in a game directory.

        Returns:
            List of ``{filename, checkpoint_title, checkpoint_node,
            round, saved_at, current_node}`` dicts.
        """
        return SaveManager.list_saves_for_game(self._saves_root, game_id)

    def delete_game(self, game_id: str) -> bool:
        """Delete an entire game directory. Returns True if deleted."""
        return SaveManager.delete_game(self._saves_root, game_id)

    def delete_save(self, game_id: str, filename: str) -> bool:
        """Delete a single save file. Returns True if deleted."""
        sm = SaveManager(os.path.join(self._saves_root, game_id))
        return sm.delete(filename)

    # ── State ─────────────────────────────────────────────────────

    @property
    def game_loop(self) -> GameLoop | None:
        return self._game_loop

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _build_init_dict(result: CoCreationResult, created_at: str) -> dict:
        """Build ``_init.json`` save dict directly from co-creation result.

        No ``GameLoop`` involvement — pure data assembly.
        Format matches ``GameLoop.to_save_dict()`` so that
        ``from_save_dict()`` can consume it identically.
        """
        sc = copy.deepcopy(result.story_config)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        label = sc.get("label", "untitled")

        # Initialize state_vars from variable definitions
        state_vars: dict[str, int | str] = {}
        for v in sc.get("variables", []):
            state_vars[v["name"]] = v["initial"]

        # Convert outline nodes to save format
        first_node_id = ""
        outline_for_save = []
        for i, node in enumerate(result.outline_nodes):
            nid = node.get("id", "")
            if i == 0:
                first_node_id = nid
            outline_for_save.append({
                "node_id": nid,
                "title": node.get("title", ""),
                "goal": node.get("goal", ""),
                "status": "active" if i == 0 else "pending",
                "summary": "",
                "branches": [
                    {"condition": r.get("condition"),
                     "target": r.get("target", "")}
                    for r in node.get("routes", [])
                ],
            })

        return {
            "version": SAVE_VERSION,
            "metadata": {
                "label": label,
                "created_at": created_at,
                "updated_at": now,
            },
            "config": {
                "temperature": None,
            },
            "story_config": sc,
            "state_vars": state_vars,
            "outline": outline_for_save,
            "progress": {
                "current_node": first_node_id,
                "checkpoint_snapshots": {},
            },
        }
