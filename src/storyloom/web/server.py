"""Storyloom Web UI — FastAPI application server.

All API endpoints + SSE streaming for the narrative loop.
Usage::

    python -m storyloom.web
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from storyloom.core.session import GameSession
from storyloom.core.co_create import CoCreationResult
from storyloom.i18n import init_i18n

from storyloom.web.sessions import (
    GameSessionState,
    store_co_create,
    get_co_create,
    remove_co_create,
    store_game,
    get_game,
    drain_queue,
)

logger = logging.getLogger("storyloom.web")

# ── Init ───────────────────────────────────────────────────────────

init_i18n()

_WEB_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _WEB_DIR / "static"


# ── App ────────────────────────────────────────────────────────────

app = FastAPI(title="Storyloom Web", version="0.1.0")

# Allow cross-origin requests (needed when frontend is served separately)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ── Health ─────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Pages ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = _STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Storyloom</h1><p>static/index.html not found.</p>")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════
# Co-Create API
# ═══════════════════════════════════════════════════════════════════

@app.post("/api/co-create/start")
async def co_create_start():
    """Start a new co-creation session."""
    session = GameSession()
    flow = session.new_co_create()
    event = flow.start()

    session_id = uuid.uuid4().hex[:12]
    store_co_create(session_id, flow)

    return {
        "session_id": session_id,
        "phase": event["phase"],
        "prompt": event["prompt"],
    }


@app.post("/api/co-create/send")
async def co_create_send(req: Request):
    """Send a message in the Q&A loop.  Returns LLM reply text."""
    body = await req.json()
    session_id = (body.get("session_id") or "").strip()
    message = (body.get("message") or "").strip()

    if not session_id:
        raise HTTPException(400, "Missing session_id")
    if not message:
        raise HTTPException(400, "Message cannot be empty")

    try:
        flow = get_co_create(session_id)
    except KeyError:
        raise HTTPException(400, "Invalid session_id")

    try:
        reply = flow.send(message)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"reply": reply, "phase": flow.phase}


@app.post("/api/co-create/generate")
async def co_create_generate(req: Request):
    """Trigger story generation.  Returns story_config + outline."""
    body = await req.json()
    session_id = (body.get("session_id") or "").strip()

    if not session_id:
        raise HTTPException(400, "Missing session_id")

    try:
        flow = get_co_create(session_id)
    except KeyError:
        raise HTTPException(400, "Invalid session_id")

    try:
        result = flow.generate()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        # CoCreationAborted or API failures
        raise HTTPException(400, f"Generation failed: {e}")

    return {
        "story_config": result.story_config,
        "outline_text": result.outline_text,
        "outline_nodes": result.outline_nodes,
        "phase": flow.phase,
    }


@app.post("/api/co-create/abort")
async def co_create_abort(req: Request):
    """Abort co-creation and clean up."""
    body = await req.json()
    session_id = (body.get("session_id") or "").strip()

    if session_id:
        try:
            flow = get_co_create(session_id)
            flow.abort()
        except KeyError:
            pass
        remove_co_create(session_id)

    return {"status": "aborted"}


# ═══════════════════════════════════════════════════════════════════
# Game API
# ═══════════════════════════════════════════════════════════════════

@app.post("/api/game/new")
async def game_new(req: Request):
    """Create a new game from co-creation result and start Round 1.

    Request body::

        {"story_config": {...}, "outline_text": "...", "outline_nodes": [...]}
    """
    body = await req.json()
    story_config = body["story_config"]
    outline_text = body["outline_text"]
    outline_nodes = body.get("outline_nodes", [])

    # ── Issue #3: fix variable initial-value types after JSON round-trip ──
    # JSON.parse can't distinguish int from float; Python's json.loads may
    # return float for number fields.  Normalise aggressively.
    for v in story_config.get("variables", []):
        vtype = v.get("type", "")
        if vtype == "number":
            try:
                v["initial"] = int(v["initial"])
            except (ValueError, TypeError):
                v["initial"] = 0
        elif vtype == "list":
            if not isinstance(v.get("initial"), list):
                v["initial"] = []
        # string: no conversion needed

    result = CoCreationResult(
        story_config=story_config,
        outline_text=outline_text,
        outline_nodes=outline_nodes,
    )

    session = GameSession()
    gl = session.start_game(result)
    gl.start_game()  # ⚠️ MUST call before stream_round()

    game_id = uuid.uuid4().hex[:12]
    state = GameSessionState(game_loop=gl, session=session)
    store_game(game_id, state)

    return {
        "game_id": game_id,
        "status": "started",
        "round_count": gl.round_count,
        "current_node": gl.current_node,
    }


@app.get("/api/game/{game_id}/stream")
async def game_stream(game_id: str):
    """SSE endpoint — streams narrative events to the browser.

    Spawns a daemon thread that iterates ``stream_round()`` and pushes
    events into a queue.  The SSE response drains that queue asynchronously.

    When an ``options`` event is hit, the daemon thread blocks on
    ``choice_queue`` until ``POST /api/game/{id}/choice`` injects a key.
    """
    try:
        state = get_game(game_id)
    except KeyError:
        raise HTTPException(404, "Game not found")

    if state.round_active:
        raise HTTPException(400, "Round already in progress")

    return await _start_round_stream(game_id, state)


async def _start_round_stream(game_id: str, state: GameSessionState):
    """Launch a round in a daemon thread and return an SSE StreamingResponse."""

    def _run_round():
        try:
            gen = state.game_loop.stream_round()
            state.round_active = True

            for event in gen:
                etype = event.get("type", "?")
                # Log key events for debugging
                if etype in ("options", "done", "ending", "error"):
                    logger.info(f"[game={game_id}] event: {etype}")
                if etype == "options":
                    state.event_queue.put(event)
                    key = state.choice_queue.get()
                    logger.info(f"[game={game_id}] choice key received: {key}")
                    try:
                        gen.send(key)
                    except StopIteration:
                        break
                else:
                    state.event_queue.put(event)

            # Signal round completion to the SSE consumer
            state.event_queue.put({"type": "__round_done__"})

        except Exception as exc:
            logger.exception("Round thread error")
            state.event_queue.put({
                "type": "error",
                "message": str(exc),
            })
        finally:
            state.round_active = False

    # Clean stale events from any previous round
    drain_queue(state.event_queue)
    drain_queue(state.choice_queue)

    thread = threading.Thread(target=_run_round, daemon=True)
    thread.start()

    return _sse_response(state)


def _sse_response(state: GameSessionState) -> StreamingResponse:
    """Build a StreamingResponse that drains the event queue."""

    async def _event_stream():
        while True:
            try:
                event = state.event_queue.get_nowait()
            except Exception:
                await asyncio.sleep(0.05)
                continue

            etype = event.get("type", "")

            # Internal signal — round finished
            if etype == "__round_done__":
                yield "event: round_complete\ndata: {}\n\n"
                return

            data_json = json.dumps(event, ensure_ascii=False, default=str)
            yield f"event: {etype}\ndata: {data_json}\n\n"

            # Error events end the stream
            if etype == "error":
                return

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/game/{game_id}/choice")
async def game_choice(game_id: str, req: Request):
    """Inject a player choice key into the running round.

    Request: ``{"key": "1"}``  (⚠️  1-indexed string, NOT zero-indexed)
    """
    try:
        state = get_game(game_id)
    except KeyError:
        raise HTTPException(404, "Game not found")

    body = await req.json()
    key = str(body.get("key", "")).strip()

    if not key:
        raise HTTPException(400, "Missing choice key")
    if not key.isdigit():
        raise HTTPException(400, f"Invalid choice key: {key} (must be a number)")

    if not state.round_active:
        raise HTTPException(400, "No active round — cannot send choice")

    state.choice_queue.put(key)
    return {"status": "ok", "key": key}


@app.post("/api/game/{game_id}/retry")
async def game_retry(game_id: str):
    """Retry the last failed API call."""
    try:
        state = get_game(game_id)
    except KeyError:
        raise HTTPException(404, "Game not found")

    if state.round_active:
        raise HTTPException(400, "Round in progress — cannot retry")

    try:
        state.game_loop.retry()
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    return {"status": "retrying"}


@app.get("/api/game/{game_id}/state")
async def game_state(game_id: str):
    """Return current game state for the sidebar."""
    try:
        state = get_game(game_id)
    except KeyError:
        raise HTTPException(404, "Game not found")

    gl = state.game_loop
    return {
        "round_count": gl.round_count,
        "current_node": gl.current_node,
        "outline_nodes": gl.outline_nodes,
        "state_vars": gl.game_state.state_vars,
        "ending_flag": gl.ending_flag,
    }


@app.get("/api/game/{game_id}/adventure-log")
async def game_adventure_log(game_id: str):
    """Fetch the adventure log.  Only valid after ending."""
    try:
        state = get_game(game_id)
    except KeyError:
        raise HTTPException(404, "Game not found")

    gl = state.game_loop
    if not gl.ending_flag:
        raise HTTPException(400, "Game has not ended yet")

    adv = gl.get_adventure_log(timeout=30.0)
    if adv is None:
        err = gl.adventure_log_error
        if err:
            return {"text": f"[Adventure log failed: {err}]", "pending": False}
        return {"text": "", "pending": True}

    return {"text": adv, "pending": False}


@app.post("/api/game/{game_id}/save")
async def game_save(game_id: str):
    """Save the current game."""
    try:
        state = get_game(game_id)
    except KeyError:
        raise HTTPException(404, "Game not found")

    save_dict = state.game_loop.to_save_dict()
    state.session._save_manager.save(save_dict)

    return {
        "status": "saved",
        "label": save_dict["metadata"]["label"],
        "round_count": save_dict["metadata"]["round_count"],
    }


# ═══════════════════════════════════════════════════════════════════
# Save CRUD API
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/saves")
async def list_saves():
    """List all save files."""
    session = GameSession()
    return session.list_saves()


@app.post("/api/saves/{label}/load")
async def load_game(label: str):
    """Load a saved game.  Returns a new game_id."""
    session = GameSession()
    try:
        gl = session.load_game(label)
    except Exception as e:
        raise HTTPException(400, f"Load failed: {e}")

    gl.start_game()  # ⚠️ MUST call before stream_round()

    game_id = uuid.uuid4().hex[:12]
    state = GameSessionState(game_loop=gl, session=session)
    store_game(game_id, state)

    return {
        "game_id": game_id,
        "status": "loaded",
        "label": label,
        "round_count": gl.round_count,
        "current_node": gl.current_node,
        "state_vars": gl.game_state.state_vars,
    }


@app.delete("/api/saves/{label}")
async def delete_save(label: str):
    """Delete a save file."""
    session = GameSession()
    ok = session.delete_save(label)
    if not ok:
        raise HTTPException(404, f"Save '{label}' not found")
    return {"status": "deleted", "label": label}


# ── Entry point ────────────────────────────────────────────────────

def main():
    import uvicorn
    uvicorn.run(
        "storyloom.web.server:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
