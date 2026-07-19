"""Server-side session stores for co-creation and game flows.

Single-user, in-memory storage.  State is lost on server restart.

Co-create store:
    store_co_create / get_co_create / remove_co_create
    store_co_create_result / get_co_create_result

Game store (placeholder — Phase 2):
    store_game / get_game / remove_game
"""

from storyloom.core.co_create import CoCreateFlow, CoCreationResult
from storyloom.core.game_loop import GameLoop

# ── Co-creation store ──────────────────────────────────────────────

_co_create_flow: CoCreateFlow | None = None
_co_create_result: CoCreationResult | None = None


def store_co_create(flow: CoCreateFlow) -> None:
    """Store the active co-creation flow.  Replaces any previous one."""
    global _co_create_flow, _co_create_result
    _co_create_flow = flow
    _co_create_result = None


def get_co_create() -> CoCreateFlow | None:
    """Return the active co-creation flow, or None."""
    return _co_create_flow


def remove_co_create() -> None:
    """Discard the active co-creation flow and any cached result."""
    global _co_create_flow, _co_create_result
    _co_create_flow = None
    _co_create_result = None


def store_co_create_result(result: CoCreationResult) -> None:
    """Cache the co-creation result so game/new can consume it."""
    global _co_create_result
    _co_create_result = result


def get_co_create_result() -> CoCreationResult | None:
    """Return the cached co-creation result, or None."""
    return _co_create_result


# ── Game store (placeholder) ───────────────────────────────────────

_game_loops: dict[str, GameLoop] = {}


def store_game(game_id: str, gl: GameLoop) -> None:
    """Store a running GameLoop by game_id."""
    _game_loops[game_id] = gl


def get_game(game_id: str) -> GameLoop | None:
    """Return a running GameLoop by game_id, or None."""
    return _game_loops.get(game_id)


def remove_game(game_id: str) -> None:
    """Remove a game from the store."""
    _game_loops.pop(game_id, None)
