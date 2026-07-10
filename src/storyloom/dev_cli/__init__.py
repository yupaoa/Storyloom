"""Storyloom dev CLI — minimal game UI + developer inspection.

Independent package. Delete this directory to remove the dev CLI
from a release build. Zero engine modifications needed.

Usage:
    python -m storyloom.dev_cli [--mode dev|normal] [--story FILE] [--no-save] [--lang zh-CN|en]
"""

from storyloom.dev_cli.ui import dev_main, TerminalUi
from storyloom.dev_cli.observer import DevObserver
from storyloom.dev_cli.args import parse_args, DevCliArgs

__all__ = ["dev_main", "TerminalUi", "DevObserver", "parse_args", "DevCliArgs"]
