"""Server-side session stores for co-creation and game flows.

Single-user, in-memory storage. State is lost on server restart.

Architecture (exec-flow.md §4.5 "UI queue buffer"):
    Daemon thread pushes stream_round() events into a Queue;
    async SSE endpoint drains the queue via StreamingResponse.
    On options events the thread blocks on a choice_queue until
    POST /choice injects the player's key.

Co-create store:
    Dict[session_id, CoCreateFlow]
    store_co_create / get_co_create / remove_co_create

Game store:
    GameSessionState dataclass (GameLoop, event_queue, choice_queue, round_active)
    Dict[game_id, GameSessionState]
    store_game / get_game / remove_game
    drain_queue — non-blocking clear of all pending items
"""
