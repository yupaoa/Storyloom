"""TerminalUi — minimal CLI implementing UiInterface + game flow driver."""
import json
import sys
import time
from pathlib import Path

from storyloom.core.session import GameSession
from storyloom.core.co_create import CoCreationResult
from storyloom.core.game_loop import GameLoop
from storyloom.i18n import init_i18n
from storyloom.config import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE

from storyloom.dev_cli.args import parse_args

_DELAYS = {"instant": 0, "fast": 0.1, "normal": 0.5, "slow": 1.0}


class TerminalUi:
    """Minimal CLI UI implementing the UiInterface protocol."""

    def write(self, text: str) -> None:
        print(text)

    def write_raw(self, text: str) -> None:
        """Write without trailing newline (streaming tokens)."""
        sys.stdout.write(text)
        sys.stdout.flush()

    def show_error(self, text: str) -> None:
        print(f"[Error] {text}", file=sys.stderr)

    def ask(self, prompt: str) -> str:
        print(prompt)
        try:
            return input("> ").strip()
        except EOFError:
            return ""


# ── Co-creation driver ──────────────────────────────────────────

def run_co_create(
    ui: TerminalUi, session: GameSession, observer=None
) -> CoCreationResult | None:
    """Drive the co-creation Q&A loop. Returns None if user quits."""
    flow = session.new_co_create()

    try:
        event = flow.start()
    except RuntimeError as e:
        ui.show_error(f"Co-creation failed to start: {e}")
        return None
    ui.write(event["prompt"])

    while True:
        user_input = ui.ask("")
        if user_input == "":
            continue

        ui.write("[Waiting for LLM...]")
        sys.stdout.flush()
        try:
            event = flow.send(user_input)
        except KeyboardInterrupt:
            ui.write("\n[Interrupted]")
            return None
        except RuntimeError as e:
            ui.show_error(f"Co-creation error: {e}")
            return None

        phase = event["phase"]

        if observer is not None:
            observer.record_co_create_messages(phase, flow.messages)

        if phase == "awaiting_idea":
            ui.write(event["prompt"])

        elif phase == "awaiting_answer":
            ui.write(event["question"])
            if observer is not None:
                observer.record_co_create_response(event["question"])

        elif phase == "complete":
            result = event["result"]
            if observer is not None:
                observer.record_co_create_result(
                    result.story_config, result.outline_text
                )
            ui.write(f"\n[Story created: {result.story_config.get('label', '?')}]")
            ui.write(f"[Genre: {result.story_config.get('genre', '?')}]")
            ui.write(f"[Outline: {len(result.outline_nodes)} nodes]\n")
            return result

        elif phase == "aborted":
            ui.write("[Co-creation aborted]")
            return None

        elif phase == "error":
            ui.show_error(event["message"])
            if not event.get("recoverable", False):
                return None

        else:
            ui.show_error(f"Unknown co-create phase: {phase}")
            return None


# ── Game driver ──────────────────────────────────────────────────

def run_game(
    ui: TerminalUi,
    game_loop: GameLoop,
    observer=None,
    speed: str = "normal",
) -> None:
    """Drive the game loop — stream events, show narrative, handle choices."""
    if observer is not None:
        game_loop._observers.append(observer.record_round)

    # Round 1
    ui.write("[Generating round 1...]")
    sys.stdout.flush()
    try:
        for event in game_loop.start_round1_stream():
            _handle_event(ui, event, speed)
    except Exception as e:
        ui.show_error(f"Round 1 failed: {e}")
        return

    if game_loop.ending_flag or game_loop.last_parsed is None:
        return

    # Continue rounds
    while True:
        options = game_loop.get_available_options()
        if options:
            for opt in options:
                ui.write(f"  [{opt['index']}] {opt['branch']}")
            ui.write("  [p] Pause  [q] Quit")

        if options:
            choice = _get_choice(ui, len(options))
            if choice is None:
                _handle_quit(ui)
                return
            if choice == "pause":
                _handle_pause(ui)
                continue
        else:
            choice = None

        try:
            for event in game_loop.continue_round_stream(choice_key=choice):
                _handle_event(ui, event, speed)
        except Exception as e:
            ui.show_error(f"Round failed: {e}")
            return

        if game_loop.ending_flag:
            return


# ── Event handler ────────────────────────────────────────────────

def _handle_event(ui: TerminalUi, event: dict, speed: str) -> None:
    etype = event.get("type", "")
    delay = _DELAYS.get(speed, 0.5)
    instant = speed == "instant"

    if etype == "token":
        if instant:
            ui.write_raw(event.get("text", ""))

    elif etype == "segment":
        if instant:
            ui.write_raw("\n")
        ui.write(event.get("text", ""))
        if delay:
            time.sleep(delay)

    elif etype in ("options", "state"):
        pass  # options handled via get_available_options(); state via observer

    elif etype == "error":
        ui.show_error(event.get("message", ""))

    elif etype == "ending":
        if instant:
            ui.write_raw("\n")
        log = event.get("adventure_log")
        if log:
            ui.write("\n" + "=" * 40)
            ui.write(log)
            ui.write("=" * 40 + "\n")

    elif etype == "done":
        if instant:
            ui.write_raw("\n")

    else:
        ui.write(f"[Unknown event: {etype}]")


# ── Input helpers ────────────────────────────────────────────────

def _get_choice(ui: TerminalUi, num_options: int) -> str | None:
    """Returns choice_key, "pause", or None (quit)."""
    while True:
        raw = ui.ask("> ").lower()
        if raw == "":
            continue
        if raw in ("q", "quit", "exit"):
            return None
        if raw == "p":
            return "pause"
        if raw.isdigit() and 1 <= int(raw) <= num_options:
            return raw
        ui.write(f"  Enter 1-{num_options}, p to pause, or q to quit")


def _handle_pause(ui: TerminalUi) -> None:
    """Block until Enter — dev_output/ files frozen at current round."""
    ui.write(
        "\n⏸  Paused — dev_output/ is at current round.\n"
        "   Safe to inspect prompts.txt / responses.txt / checks.txt.\n"
        "   Press Enter to continue."
    )
    try:
        ui.ask("")
    except KeyboardInterrupt:
        pass
    ui.write("▶  Resuming...\n")


def _handle_quit(ui: TerminalUi) -> None:
    ui.write("\n[Quit]")


# ── Entry point ──────────────────────────────────────────────────

def dev_main(argv: list[str] | None = None) -> None:
    """Entry point for the dev CLI."""
    args = parse_args(argv)

    lang = args.lang
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE
    init_i18n(lang)

    ui = TerminalUi()
    session = GameSession()

    try:
        observer = None
        if args.mode == "dev":
            from storyloom.dev_cli.observer import DevObserver
            observer = DevObserver()

        if args.story_file:
            story_path = Path(args.story_file)
            if not story_path.exists():
                ui.show_error(f"Story file not found: {args.story_file}")
                sys.exit(1)
            try:
                data = json.loads(story_path.read_text(encoding="utf-8"))
                result = CoCreationResult(
                    story_config=data["story_config"],
                    outline_text=data["outline_text"],
                    outline_nodes=data.get("outline_nodes", []),
                )
            except (json.JSONDecodeError, KeyError) as e:
                ui.show_error(f"Invalid story file: {e}")
                sys.exit(1)
        else:
            result = run_co_create(ui, session, observer)
            if result is None:
                sys.exit(0)

        game_loop = session.start_game(result)
        if args.no_save:
            game_loop.set_save_manager(None)

        run_game(ui, game_loop, observer, speed=args.speed)
        ui.write("\n[Game over]")

    except KeyboardInterrupt:
        ui.write("\n[Interrupted]")
        sys.exit(0)
