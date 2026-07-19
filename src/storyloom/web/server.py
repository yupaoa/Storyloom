"""Storyloom Web UI — FastAPI application server.

Usage: python -m storyloom.web

Endpoint groups:
  Pages:         GET  /                                   — index page
                 GET  /health                             — health check
  Co-Create:     POST /api/co-create/start                — start Q&A session
                 POST /api/co-create/send                 — send message in Q&A
                 POST /api/co-create/generate             — generate story setup
                 POST /api/co-create/abort                — abort co-creation
  Game:          POST /api/game/new                       — create game from result
                 GET  /api/game/{id}/stream               — SSE narrative stream
                 POST /api/game/{id}/choice               — inject player choice
                 POST /api/game/{id}/retry                — retry failed API call
                 GET  /api/game/{id}/state                — sidebar state
                 GET  /api/game/{id}/adventure-log        — post-ending log
  Saves:         GET    /api/saves/games                  — list all games
                 GET    /api/saves/{game_id}              — list saves in a game
                 POST   /api/saves/{game_id}/load/{filename} — load a save
                 DELETE /api/saves/{game_id}              — delete a game
                 DELETE /api/saves/{game_id}/{filename}   — delete a save

SSE architecture:
    Daemon thread runs stream_round() → pushes events into Queue.
    Async endpoint drains Queue → StreamingResponse (SSE).
    On options: thread blocks on choice_queue, waits for POST /choice.
    On error:  stream ends, UI presents retry / quit.
    On done:   round_complete SSE sent, stream ends.

GameSession construction:
    UserConfig → ApiClient(config) → GameSession(api_client, saves_dir)

Authoritative sources:
    GameSession API — src/storyloom/core/session.py
    Event contract  — docs/spec/exec-flow.md §4.1
    Reference impl  — src/storyloom/dev_cli/game_driver.py
"""
