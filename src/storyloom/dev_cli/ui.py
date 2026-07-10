"""TerminalUi — minimal CLI implementing UiInterface + game flow driver."""
import json
import sys
from pathlib import Path

from storyloom.core.session import GameSession
from storyloom.core.co_create import CoCreationResult
from storyloom.core.game_loop import GameLoop
from storyloom.i18n import init_i18n
from storyloom.config import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE

from storyloom.dev_cli.args import parse_args


class TerminalUi:
    """Minimal CLI UI implementing the UiInterface protocol."""

    def write(self, text: str) -> None:
        print(text)

    def show_error(self, text: str) -> None:
        print(f"[Error] {text}", file=sys.stderr)

    def ask(self, prompt: str) -> str:
        print(prompt)
        try:
            return input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""


# ── Game flow drivers ────────────────────────────────────────────


def run_co_create(ui: TerminalUi, session: GameSession) -> CoCreationResult | None:
    """Drive the co-creation Q&A loop. Returns None if user quits."""
    flow = session.new_co_create()

    # Step 1: start
    event = flow.start()
    ui.write(event["prompt"])

    # Step 2: Q&A loop
    while True:
        user_input = ui.ask("")
        if user_input == "":
            continue

        ui.write("[...]")
        event = flow.send(user_input)

        phase = event["phase"]

        if phase == "awaiting_idea":
            ui.write(event["prompt"])

        elif phase == "awaiting_answer":
            ui.write(event["question"])

        elif phase == "complete":
            result = event["result"]
            ui.write(f"\n[Story created: {result.story_config.get('label', '?')}]")
            ui.write(f"[Genre: {result.story_config.get('genre', '?')}]")
            ui.write(f"[Outline: {len(result.outline_nodes)} nodes]")
            ui.write("")
            return result

        elif phase == "aborted":
            ui.write("[Co-creation aborted]")
            return None

        elif phase == "error":
            ui.show_error(event["message"])
            if not event.get("recoverable", False):
                return None


def run_game(
    ui: TerminalUi,
    game_loop: GameLoop,
    dev_observer=None,
) -> None:
    """Drive the game loop. Consume stream events, display narrative + choices."""
    # Register observer (private attribute access — dev tool only)
    if dev_observer is not None:
        game_loop._observers.append(dev_observer.record_round)

    # Start round 1
    ui.write("[Generating...]")
    try:
        events = list(game_loop.start_round1_stream())
    except Exception as e:
        ui.show_error(f"Round 1 failed: {e}")
        return

    for event in events:
        _handle_event(ui, event)

    if game_loop.ending_flag:
        return

    # Continue rounds
    while True:
        options = game_loop.get_available_options()

        # Show options
        if options:
            for opt in options:
                idx = opt["index"]
                branch = opt["branch"]
                ui.write(f"  [{idx}] {branch}")
            ui.write("  [q] Quit")

        # Get player choice
        if options:
            choice = _get_choice(ui, len(options))
            if choice is None:
                # User quit
                _handle_quit(game_loop, ui)
                return
        else:
            choice = None

        # Continue round
        try:
            events = list(game_loop.continue_round_stream(choice_key=choice))
        except Exception as e:
            ui.show_error(f"Round failed: {e}")
            return

        for event in events:
            _handle_event(ui, event)

        if game_loop.ending_flag:
            return


def _handle_event(ui: TerminalUi, event: dict) -> None:
    """Handle a single stream event."""
    etype = event["type"]

    if etype == "token":
        pass  # minimal mode — skip per-token display

    elif etype == "segment":
        ui.write(event["text"])

    elif etype == "options":
        pass  # handled separately via get_available_options()

    elif etype == "state":
        pass  # state changes are recorded by observer, not displayed

    elif etype == "error":
        ui.show_error(event["message"])

    elif etype == "ending":
        # Game over — show adventure log
        log = event.get("adventure_log")
        if log:
            ui.write("\n" + "=" * 40)
            ui.write(log)
            ui.write("=" * 40 + "\n")

    elif etype == "done":
        pass  # round boundary — observer already notified by engine


def _get_choice(ui: TerminalUi, num_options: int) -> str | None:
    """Get player choice. Returns choice_key (1-indexed str) or None for quit."""
    while True:
        raw = ui.ask("> ").lower()

        if raw == "":
            continue

        if raw in ("q", "quit", "exit"):
            return None
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= num_options:
                return raw
        ui.write(f"  Enter 1-{num_options}, or q to quit")


def _handle_quit(game_loop: GameLoop, ui: TerminalUi) -> None:
    """Handle graceful quit."""
    ui.write("\n[Quit]")


def dev_main(argv: list[str] | None = None) -> None:
    """Entry point for the dev CLI."""
    args = parse_args(argv)

    # i18n
    lang = args.lang
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE
    init_i18n(lang)

    ui = TerminalUi()

    # Game session
    session = GameSession()

    # Co-creation (or skip)
    if args.story_file:
        # Load CoCreationResult from JSON
        story_path = Path(args.story_file)
        if not story_path.exists():
            ui.show_error(f"Story file not found: {args.story_file}")
            sys.exit(1)
        data = json.loads(story_path.read_text(encoding="utf-8"))
        result = CoCreationResult(
            story_config=data["story_config"],
            outline_text=data["outline_text"],
            outline_nodes=data.get("outline_nodes", []),
        )
    else:
        result = run_co_create(ui, session)
        if result is None:
            sys.exit(0)

    # Start game
    game_loop = session.start_game(result)

    if args.no_save:
        game_loop.set_save_manager(None)

    # Observer
    observer = None
    if args.mode == "dev":
        from storyloom.dev_cli.observer import DevObserver

        observer = DevObserver()

    # Run
    run_game(ui, game_loop, observer)

    ui.write("\n[Game over]")
