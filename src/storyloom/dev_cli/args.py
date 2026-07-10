"""CLI argument parsing for dev_cli."""
import argparse
from dataclasses import dataclass


@dataclass
class DevCliArgs:
    mode: str          # "normal" | "dev"
    story_file: str | None
    no_save: bool
    lang: str          # "zh-CN" | "en"


def parse_args(argv: list[str] | None = None) -> DevCliArgs:
    parser = argparse.ArgumentParser(
        prog="python -m storyloom.dev_cli",
        description="Storyloom — minimal CLI game + developer inspection",
    )
    parser.add_argument(
        "--mode",
        choices=["normal", "dev"],
        default="dev",
        help="dev = record raw data; normal = pure game (default: dev)",
    )
    parser.add_argument(
        "--story",
        metavar="FILE",
        default=None,
        help="JSON file (CoCreationResult) — skip co-creation",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Disable auto-save on checkpoints",
    )
    parser.add_argument(
        "--lang",
        choices=["zh-CN", "en"],
        default="zh-CN",
        help="UI language (default: zh-CN)",
    )

    ns = parser.parse_args(argv)
    return DevCliArgs(
        mode=ns.mode,
        story_file=ns.story,
        no_save=ns.no_save,
        lang=ns.lang,
    )
