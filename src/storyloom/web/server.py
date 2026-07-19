"""Storyloom Web UI — FastAPI application server.

Usage: python -m storyloom.web

Endpoint groups:
  Pages:         GET  /                                   — index page
                 GET  /health                             — health check
  Config:        GET  /api/config                         — read UserConfig properties
                 POST /api/config                         — update + cfg.save()
  Co-Create:     POST /api/co-create/start                — start Q&A session
                 POST /api/co-create/send                 — send message in Q&A
                 POST /api/co-create/retry-send           — retry failed send()
                 POST /api/co-create/generate             — generate story setup
                 POST /api/co-create/retry-generate       — retry failed generate()
                 POST /api/co-create/abort                — abort co-creation
  Game:          POST /api/game/new                       — create game from result
                 GET  /api/game/{id}/stream               — SSE narrative stream
                 POST /api/game/{id}/choice               — inject player choice
                 POST /api/game/{id}/retry                — retry failed API call
                 GET  /api/game/{id}/state                — sidebar state
                 GET  /api/game/{id}/adventure-log        — post-ending log (Phase 2)
  Saves:         GET    /api/saves/games                  — list all games
                 GET    /api/saves/{game_id}              — list saves in a game
                 POST   /api/saves/{game_id}/load/{filename} — load a save
                 DELETE /api/saves/{game_id}              — delete a game
                 DELETE /api/saves/{game_id}/{filename}   — delete a save
  System:        POST   /api/exit                         — graceful shutdown

SSE architecture:
    Daemon thread runs stream_round() → pushes events into Queue.
    Async endpoint drains Queue → StreamingResponse (SSE).

GameSession construction:
    UserConfig → ApiClient(config) → GameSession(api_client, saves_dir)
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from storyloom.config import SUPPORTED_LANGUAGES
from storyloom.core.co_create import CoCreateError
from storyloom.core.session import GameSession
from storyloom.io.api_client import ApiClient
from storyloom.user_config import UserConfig
from storyloom.web import sessions

# ── App setup ──────────────────────────────────────────────────────

_STATIC = Path(__file__).resolve().parent / "static"
# Default to the repository root, not cwd, so config.json is always
# at <repo>/config.json regardless of where the server is started.
# server.py → web → storyloom → src → repo root  (4 levels up)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_APP_DIR = os.environ.get("STORYLOOM_APP_DIR", str(_PROJECT_ROOT))

app = FastAPI(title="Storyloom", docs_url=None, redoc_url=None)
cfg = UserConfig(_APP_DIR)

# ── Engine wiring (mirrors dev_cli/dev_main.py) ──────────────────
# One ApiClient + one GameSession for the lifetime of the server.
# dev_cli creates these once at startup and reuses them across
# co-creation → game transitions.  We follow the same pattern.
_api_client = ApiClient(cfg)
_game_session = GameSession(_api_client, saves_dir=os.path.join(_APP_DIR, "saves"))

app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(_STATIC / "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════
# Config — thin pass-through to UserConfig
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/config")
async def get_config():
    """Return current config.  api_key is masked — only first 4 and
       last 4 characters are shown."""
    key = cfg.api_key
    if len(key) > 8:
        masked = key[:4] + "****" + key[-4:]
    elif key:
        masked = "****"
    else:
        masked = ""
    return {
        "language": cfg.language,
        "api_key": masked,
        "api_base_url": cfg.api_base_url,
        "api_model": cfg.api_model,
    }


class ConfigUpdate(BaseModel):
    language: str | None = None
    api_key: str | None = None
    api_base_url: str | None = None
    api_model: str | None = None


@app.post("/api/config")
async def update_config(body: ConfigUpdate):
    """Update fields and persist to config.json via UserConfig.save()."""
    if body.language is not None:
        if body.language not in SUPPORTED_LANGUAGES:
            raise HTTPException(
                400,
                f"Unsupported language: {body.language}. "
                f"Supported: {', '.join(sorted(SUPPORTED_LANGUAGES))}",
            )
        cfg.language = body.language
    if body.api_key is not None:
        cfg.api_key = body.api_key
    if body.api_base_url is not None:
        cfg.api_base_url = body.api_base_url
    if body.api_model is not None:
        cfg.api_model = body.api_model
    cfg.save()
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════
# Co-Create — Q&A phase before story generation
# ═══════════════════════════════════════════════════════════════════


class CoCreateStartReply(BaseModel):
    phase: str
    prompt: str


@app.post("/api/co-create/start", response_model=CoCreateStartReply)
async def co_create_start():
    """Start a new co-creation Q&A session.

    Creates a CoCreateFlow, calls start(), and stores it server-side.
    The returned *prompt* is the LLM's opening question — display it
    as the first assistant message in the chat UI.
    """
    flow = _game_session.new_co_create()
    result = flow.start()
    sessions.store_co_create(flow)
    return CoCreateStartReply(**result)


class CoCreateSendBody(BaseModel):
    text: str


class CoCreateSendReply(BaseModel):
    reply: str


@app.post("/api/co-create/send", response_model=CoCreateSendReply)
async def co_create_send(body: CoCreateSendBody):
    """Send a user message in the co-creation Q&A.

    Returns the LLM's reply text.  On API failure, returns HTTP 502
    so the UI can offer a retry.
    """
    flow = sessions.get_co_create()
    if flow is None:
        raise HTTPException(400, "No active co-creation session.  Call start first.")
    try:
        reply = flow.send(body.text)
    except CoCreateError as e:
        raise HTTPException(502, e.message)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    return CoCreateSendReply(reply=reply)


@app.post("/api/co-create/retry-send", response_model=CoCreateSendReply)
async def co_create_retry_send():
    """Retry the last failed send() call."""
    flow = sessions.get_co_create()
    if flow is None:
        raise HTTPException(400, "No active co-creation session.")
    try:
        reply = flow.retry_send()
    except CoCreateError as e:
        raise HTTPException(502, e.message)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return CoCreateSendReply(reply=reply)


@app.post("/api/co-create/generate")
async def co_create_generate():
    """Generate the story setup from the Q&A conversation.

    On success, caches the CoCreationResult server-side so that
    POST /api/game/new can consume it.  Returns the parsed story
    config and outline.
    """
    flow = sessions.get_co_create()
    if flow is None:
        raise HTTPException(400, "No active co-creation session.")
    try:
        result = flow.generate()
    except CoCreateError as e:
        raise HTTPException(502, e.message)
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    sessions.store_co_create_result(result)
    return {
        "status": "ok",
        "story_config": result.story_config,
        "outline_text": result.outline_text,
    }


@app.post("/api/co-create/retry-generate")
async def co_create_retry_generate():
    """Retry the last failed generate() call."""
    flow = sessions.get_co_create()
    if flow is None:
        raise HTTPException(400, "No active co-creation session.")
    try:
        result = flow.retry_generate()
    except CoCreateError as e:
        raise HTTPException(502, e.message)
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    sessions.store_co_create_result(result)
    return {
        "status": "ok",
        "story_config": result.story_config,
        "outline_text": result.outline_text,
    }


@app.post("/api/co-create/abort")
async def co_create_abort():
    """Abort the co-creation session and discard all state."""
    flow = sessions.get_co_create()
    if flow is not None:
        flow.abort()
    sessions.remove_co_create()
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════
# Game — create from co-creation result
# ═══════════════════════════════════════════════════════════════════


@app.post("/api/game/new")
async def game_new():
    """Create a new game from the cached co-creation result.

    Requires a prior successful POST /api/co-create/generate.
    Returns the game_id for subsequent navigation to #game/{id}.
    """
    result = sessions.get_co_create_result()
    if result is None:
        raise HTTPException(
            400,
            "No co-creation result found.  Call /api/co-create/generate first.",
        )

    gl, game_id = _game_session.start_game(result)
    sessions.store_game(game_id, gl)
    sessions.remove_co_create()  # clean up — game is now live

    return {
        "game_id": game_id,
        "label": result.story_config.get("label", ""),
        "round_count": gl.round_count,
        "current_node": gl.current_node,
    }


# ═══════════════════════════════════════════════════════════════════
# System
# ═══════════════════════════════════════════════════════════════════

@app.post("/api/exit")
async def exit_app():
    import signal
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "shutting_down"}


def main():
    import uvicorn
    uvicorn.run("storyloom.web.server:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
