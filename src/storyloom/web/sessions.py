"""Server-side session stores for co-creation and game flows.

Single-user, in-memory storage.  State is lost on server restart.

Co-create store:
    store_co_create / get_co_create / remove_co_create
    store_co_create_result / get_co_create_result

Game store:
    store_game / get_game / remove_game
    store_game_stream / pop_game_stream / get_game_stream
    request_stop_game_stream / is_game_stream_stopped
    inject_choice / wait_for_choice
"""

import queue
import threading

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


# ── Game store ─────────────────────────────────────────────────────

_game_loops: dict[str, GameLoop] = {}


def store_game(game_id: str, gl: GameLoop) -> None:
    """Store a running GameLoop by game_id."""
    _game_loops[game_id] = gl


def get_game(game_id: str) -> GameLoop | None:
    """Return a running GameLoop by game_id, or None."""
    return _game_loops.get(game_id)


def remove_game(game_id: str) -> None:
    """Remove a game and all associated stream/choice/stop state."""
    _game_loops.pop(game_id, None)
    pop_game_stream(game_id)


# ── Game stream state ──────────────────────────────────────────────

# Per-game event queues for SSE streaming.
# Populated by the background thread; drained by the async SSE endpoint.
_game_streams: dict[str, queue.Queue] = {}

# Per-game choice injection state.
# The background thread blocks on _game_choice_events[game_id] after
# yielding an "options" event.  The POST /choice handler sets
# _game_choices[game_id] and signals the event to unblock the thread.
_game_choices: dict[str, str] = {}
_game_choice_events: dict[str, threading.Event] = {}

# Per-game stop signals — set when the client disconnects or the UI
# explicitly stops the game stream.  The background daemon thread
# checks this flag at key yield points and exits cleanly.
_game_stop_events: dict[str, threading.Event] = {}


def store_game_stream(game_id: str) -> queue.Queue:
    """Create and store an event queue and stop signal for a game SSE stream.

    Returns the queue so the caller can feed events into it.  A fresh
    ``threading.Event`` is created as the stop signal — the daemon
    thread polls ``is_game_stream_stopped()`` to know when to exit.
    """
    q: queue.Queue = queue.Queue()
    _game_streams[game_id] = q
    _game_stop_events[game_id] = threading.Event()
    return q


def request_stop_game_stream(game_id: str) -> None:
    """Signal the background daemon thread to stop.

    Sets the stop event and wakes up any ``wait_for_choice()`` call
    that may be blocking the thread (otherwise it would hang for up to
    300 s).  Safe to call multiple times and from any thread.
    """
    evt = _game_stop_events.get(game_id)
    if evt is not None:
        evt.set()
    # Wake up wait_for_choice so the thread can observe the stop signal
    # immediately rather than blocking for the full 300 s timeout.
    choice_evt = _game_choice_events.get(game_id)
    if choice_evt is not None:
        choice_evt.set()


def is_game_stream_stopped(game_id: str) -> bool:
    """Return True if the stop signal has been set for *game_id*.

    The background daemon thread calls this at key points (before each
    ``stream_round()`` call, after each yielded event, and after
    ``wait_for_choice()`` returns) to decide whether to exit.
    """
    evt = _game_stop_events.get(game_id)
    return evt.is_set() if evt is not None else True


def pop_game_stream(game_id: str, q: queue.Queue | None = None) -> queue.Queue | None:
    """Remove a game stream queue, stop signal, and choice state.

    If *q* is provided, the queue is only removed when the currently
    stored queue is the same object (identity check).  This prevents
    an old daemon thread from accidentally removing a new stream's
    queue — the old thread's ``finally`` block calls this with the old
    *q* reference, which no longer matches after a new
    ``store_game_stream()`` overwrites the entry.

    Always cleans up the stop event and choice state regardless of
    the identity check — those should not persist once *any* stream
    for this game has ended.
    """
    _game_stop_events.pop(game_id, None)
    _game_choices.pop(game_id, None)
    _game_choice_events.pop(game_id, None)

    if q is not None:
        current = _game_streams.get(game_id)
        if current is not q:
            return None  # not our queue — new stream already started
    return _game_streams.pop(game_id, None)


def get_game_stream(game_id: str) -> queue.Queue | None:
    """Return a game stream queue without removing it."""
    return _game_streams.get(game_id)


def inject_choice(game_id: str, key: str) -> None:
    """Inject a player choice, unblocking the background game thread.

    Called from the POST /choice handler (any thread).  The background
    game thread is blocked on wait_for_choice() after yielding an
    "options" event.
    """
    _game_choices[game_id] = key
    evt = _game_choice_events.get(game_id)
    if evt is not None:
        evt.set()


def wait_for_choice(game_id: str, timeout: float = 300.0) -> str:
    """Block until a choice is injected.  Returns the choice key.

    Called from the background game thread after yielding an "options"
    event.  Must be called from the same thread that iterates the
    stream_round() generator so gen.send() works correctly.

    Returns "1" as fallback if timeout is reached.
    """
    evt = threading.Event()
    _game_choice_events[game_id] = evt
    signaled = evt.wait(timeout=timeout)
    _game_choice_events.pop(game_id, None)
    if not signaled:
        return "1"
    return _game_choices.pop(game_id, "1")
