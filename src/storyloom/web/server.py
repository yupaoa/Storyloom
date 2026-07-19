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
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from storyloom.user_config import UserConfig

# ── App setup ──────────────────────────────────────────────────────

_STATIC = Path(__file__).resolve().parent / "static"
_APP_DIR = os.environ.get("STORYLOOM_APP_DIR", str(Path.cwd()))

app = FastAPI(title="Storyloom", docs_url=None, redoc_url=None)
cfg = UserConfig(_APP_DIR)

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
    """Return current config.  UserConfig properties are the source."""
    return {
        "language": cfg.language,
        "api_key": cfg.api_key,
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
