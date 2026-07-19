"""Storyloom Web UI — FastAPI + SSE frontend.

Serves the interactive text fiction game through a browser interface.
Uses Server-Sent Events for streaming narrative content and a
thread-per-game architecture with Queue bridging to the async FastAPI layer.

File map:
    __init__.py   — package init
    __main__.py   — python -m storyloom.web entry point
    server.py     — FastAPI application (endpoints + SSE + main)
    sessions.py   — in-memory session store (co-create + game)
    static/       — frontend (HTML/CSS/JS)
"""
