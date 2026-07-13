"""Server-side session stores for co-creation and game flows.

Single-user, in-memory storage.  Restarting the server loses all state.
"""

from dataclasses import dataclass, field
from queue import Queue

from storyloom.core.co_create import CoCreateFlow
from storyloom.core.game_loop import GameLoop
from storyloom.core.session import GameSession


# ── Co-Create sessions ────────────────────────────────────────────

_co_create_flows: dict[str, CoCreateFlow] = {}


def store_co_create(session_id: str, flow: CoCreateFlow) -> None:
    _co_create_flows[session_id] = flow


def get_co_create(session_id: str) -> CoCreateFlow:
    if session_id not in _co_create_flows:
        raise KeyError(f"Unknown co-create session: {session_id}")
    return _co_create_flows[session_id]


def remove_co_create(session_id: str) -> None:
    _co_create_flows.pop(session_id, None)


# ── Game sessions ──────────────────────────────────────────────────


@dataclass
class GameSessionState:
    """Per-game state for the SSE + choice bridge mechanism."""
    game_loop: GameLoop
    session: GameSession
    event_queue: Queue = field(default_factory=Queue)
    choice_queue: Queue = field(default_factory=Queue)
    round_active: bool = False


_game_sessions: dict[str, GameSessionState] = {}


def store_game(game_id: str, state: GameSessionState) -> None:
    _game_sessions[game_id] = state


def get_game(game_id: str) -> GameSessionState:
    if game_id not in _game_sessions:
        raise KeyError(f"Unknown game session: {game_id}")
    return _game_sessions[game_id]


def remove_game(game_id: str) -> None:
    _game_sessions.pop(game_id, None)


def drain_queue(q: Queue) -> None:
    """Remove all pending items from a queue without blocking."""
    while not q.empty():
        try:
            q.get_nowait()
        except Exception:
            break
