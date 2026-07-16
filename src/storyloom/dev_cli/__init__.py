"""Storyloom dev CLI — minimal game UI + developer inspection.

Independent package. Delete this directory to remove the dev CLI
from a release build. Zero engine modifications needed.

Usage:
    python -m storyloom.dev_cli              observer + instant (default)
    python -m storyloom.dev_cli instant      observer + instant
    python -m storyloom.dev_cli auto         observer + auto
    python -m storyloom.dev_cli manual       observer + manual (Enter/seg)
    python -m storyloom.dev_cli play         pure game + auto
    python -m storyloom.dev_cli play instant pure game + instant
    python -m storyloom.dev_cli play manual  pure game + manual
"""

from storyloom.dev_cli.observer import DevObserver
from storyloom.dev_cli.game_driver import dev_main

__all__ = ["dev_main", "DevObserver"]
