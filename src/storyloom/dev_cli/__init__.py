"""Storyloom dev CLI — minimal game UI + developer inspection.

Independent package. Delete this directory to remove the dev CLI
from a release build. Zero engine modifications needed.

Usage:
    python -m storyloom.dev_cli          # observer mode (default)
    python -m storyloom.dev_cli play      # pure game (no file output)
"""

from storyloom.dev_cli.observer import DevObserver
from storyloom.dev_cli.game_driver import dev_main

__all__ = ["dev_main", "DevObserver"]
