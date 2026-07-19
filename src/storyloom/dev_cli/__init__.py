"""Storyloom dev CLI — minimal game UI + developer inspection.

Independent package. Delete this directory to remove the dev CLI
from a release build. Zero engine modifications needed.

Usage:
    python -m storyloom.dev_cli                  play mode (manual, no output files)
    python -m storyloom.dev_cli --observer        observer + manual (toggle in-game)
    python -m storyloom.dev_cli --observer --instant  observer + instant (no toggle)

Observer mode writes per-round raw data to dev_output/:
    prompts.txt   — messages array sent to LLM (written at submit time)
    responses.txt — raw LLM response text (written when fully received)
    checks.txt    — round inspection summary (appended each round)

Play mode needs no extra arguments — always manual pacing with
Tab-to-auto toggle.  Observer mode defaults to the same manual
behaviour; ``--instant`` disables all pacing and in-game toggle.
"""

from storyloom.dev_cli.observer import DevObserver
from storyloom.dev_cli.game_driver import dev_main

__all__ = ["dev_main", "DevObserver"]
