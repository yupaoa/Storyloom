"""Game flow driver — co-creation + narrative loop with deque buffer.

Architecture (per exec-flow.md §4.5 "UI queue buffer")::

    Receiver (fast)              Deque buffer           Display (paced)
    ─────────────────────       ──────────────         ──────────────────
    gen = gl.stream_round()     collections.deque      _display_loop()
    for event in gen:           event_queue.append()   pops at mode pace
      if options → inline                              instant: no delay
                                                       auto:    _AUTO_DELAY_SEC/seg
                                                       manual:  Enter/seg

Display pacing (auto / manual) is the pause mechanism — toggling auto→manual
naturally pauses display.  ``instant`` is a CLI-only mode with no pacing.
Ctrl+C raises KeyboardInterrupt naturally (caught by dev_main).
"""

import argparse
import collections
import sys
import time
from pathlib import Path

from storyloom.core.session import GameSession
from storyloom.core.co_create import CoCreateError, CoCreationResult
from storyloom.core.game_loop import GameLoop
from storyloom.i18n import init_i18n
from storyloom.io.api_client import ApiClient
from storyloom.user_config import UserConfig

from storyloom.dev_cli._terminal import TerminalInput
from storyloom.dev_cli.observer import DevObserver


# ── Display pacing ──────────────────────────────────────────────────

_AUTO_DELAY_SEC = 1.0  # delay between segments in auto display mode


# ═══════════════════════════════════════════════════════════════════
# Display controller — mutable pacing mode, Tab to toggle
# ═══════════════════════════════════════════════════════════════════

class DisplayController:
    """Display pacing controller with runtime mode switching.

    Pattern for UI implementations::

        - Maintain a mutable ``mode`` state (auto / manual / instant).
        - User input events toggle the mode at any time.
        - Display pacing logic reads ``mode`` at each segment boundary.
        - auto ↔ manual switching IS pause — no separate pause mechanism.

    CLI binding: Tab key toggles auto ↔ manual during auto-mode sleep.
    Web UI equivalent: button or gesture sets ``controller.mode``.

    ``instant`` mode is CLI-only; it has no pacing and ignores toggles.
    """

    def __init__(self, initial_mode: str = "auto"):
        self.mode = initial_mode
        self._term = TerminalInput()
        self._enter_hint_shown = False

    # ── Toggle detection ────────────────────────────────────────

    def poll_toggle(self) -> bool:
        """Non-blocking check for Tab key.  Returns True if mode changed.

        Call during auto-mode sleep loop only.  Must be inside a
        ``raw_mode()`` context on POSIX for single-key detection.
        """
        ch = self._term.get_char(0)
        if ch == "\t":
            self.mode = "manual"
            return True
        return False


# ═══════════════════════════════════════════════════════════════════
# Terminal I/O helpers
# ═══════════════════════════════════════════════════════════════════


def _ask(prompt: str) -> str:
    """Read a line from stdin.  Returns stripped input."""
    if prompt:
        print(prompt)
    try:
        return input("> ").strip()
    except EOFError:
        return ""


def _error(text: str) -> None:
    """Print an error message to stderr."""
    print(f"[Error] {text}", file=sys.stderr)


# ═══════════════════════════════════════════════════════════════════
# Co-creation driver
# ═══════════════════════════════════════════════════════════════════

def run_co_create(
    session: GameSession,
    observer: DevObserver | None = None,
) -> CoCreationResult | None:
    """Drive the co-creation Q&A loop.  Returns None if user quits.

    UI-level commands (engine does not parse user intent):
      /go    — trigger story generation
      /quit  — abort and return to menu
    """
    flow = session.new_co_create()

    try:
        event = flow.start()
    except RuntimeError as e:
        _error(f"Co-creation failed to start: {e}")
        return None
    print(event["prompt"])
    print("[/go to generate  /quit to exit]")

    while True:
        user_input = _ask("").strip()
        if user_input == "":
            continue

        if user_input == "/quit":
            flow.abort()
            print("[Co-creation aborted]")
            return None

        if user_input == "/go":
            break

        # ── Forward to LLM ──
        if observer is not None:
            observer.record_co_create_prompt(flow.messages, user_input)

        print("[Waiting for LLM...]")
        sys.stdout.flush()
        send_retry = False
        while True:
            try:
                reply = flow.retry_send() if send_retry else flow.send(user_input)
                break  # success
            except KeyboardInterrupt:
                print("\n[Interrupted]")
                return None
            except CoCreateError as e:
                _error(e.message)
                ans = _ask("Retry? (y/n)").strip().lower()
                if ans not in ("y", "yes"):
                    return None
                send_retry = True
            except (RuntimeError, ValueError) as e:
                _error(f"Co-creation error: {e}")
                return None

        if observer is not None:
            observer.record_co_create_response(flow.messages)

        print(reply)

    # ── Generate ──
    print("[Generating story setup...]")
    sys.stdout.flush()
    gen_retry = False
    while True:
        try:
            result = flow.retry_generate() if gen_retry else flow.generate()
            break  # success
        except KeyboardInterrupt:
            print("\n[Interrupted]")
            return None
        except CoCreateError as e:
            _error(e.message)
            ans = _ask("Retry? (y/n)").strip().lower()
            if ans not in ("y", "yes"):
                return None
            gen_retry = True
        except Exception as e:
            _error(f"Generation failed: {e}")
            return None

    if observer is not None:
        # Record generation prompt + response (generate() appends both to messages)
        gen_input = flow.messages[-2]["content"]
        observer.record_co_create_prompt(flow.messages[:-2], gen_input)
        observer.record_co_create_response(flow.messages)
        observer.record_co_create_result(
            result.story_config, result.outline_text)
    print(f"\n[Story: {result.story_config.get('label', '?')}]")
    print(f"[Genre: {result.story_config.get('genre', '?')}]")
    print(f"[Outline: {len(result.outline_nodes)} nodes]\n")
    return result


# ═══════════════════════════════════════════════════════════════════
# Game driver
# ═══════════════════════════════════════════════════════════════════

def run_game(
    game_loop: GameLoop,
    ctrl: DisplayController,
    observer: DevObserver | None = None,
) -> None:
    """Drive the narrative loop with deque-buffered display.

    Receiver (``for event in gen``) pushes events into a deque as fast
    as the API delivers them.  The display loop drains the deque at
    the pace set by ``ctrl.mode`` — instant, auto, or manual.

    ``options`` events are handled inline because they require
    ``gen.send(key)`` from the same thread.

    Observer two-phase recording (when observer is not None):

    * Phase 1 — prompt submit: ``write_prompt_at_send()`` immediately
      after the engine launches the background API call.
    * Phase 2 — response complete: ``record_round()`` callback fires
      inside ``stream_round()`` when the full LLM response has been
      received and parsed.  Only responses.txt + checks.txt are
      written here; prompts.txt was already written in Phase 1.
    """
    if observer is not None:
        game_loop._observers.append(observer.record_round)

    game_loop.start_game()
    # Phase 1: Round 1 prompt was just sent — write it immediately
    if observer is not None:
        observer.write_prompt_at_send(game_loop._pending_messages, 1)

    while True:
        # Snapshot before stream_round() consumes them (for retry on error)
        retry_msgs = list(game_loop._pending_messages) if game_loop._pending_messages else []
        retry_content = game_loop._pending_user_content

        gen = game_loop.stream_round()
        event_queue: collections.deque = collections.deque()

        for event in gen:
            # ── Receiver: push to queue ──────────────────────────
            event_queue.append(event)

            # ── Display: drain queue at configured pace ───────────
            while event_queue:
                evt = event_queue[0]  # peek

                # Options must be handled inline — needs gen.send()
                if evt["type"] == "options":
                    # Drain non-option events ahead of options first
                    _drain_non_options(event_queue)
                    # Now handle the choice
                    key = _show_choices(evt)
                    if key is None:
                        return
                    # Pop options event, resume generator
                    if event_queue and event_queue[0]["type"] == "options":
                        event_queue.popleft()
                    gen.send(key)
                    break  # exit display loop, continue receiver

                # Regular event — display one
                event_queue.popleft()

                if evt["type"] == "error":
                    _error(evt.get("message", ""))
                    ans = _ask("Retry? (y/n)").strip().lower()
                    if ans in ("y", "yes") and retry_msgs:
                        game_loop._launch_api(retry_msgs, retry_content)
                        break  # exit for loop, while loop re-calls stream_round()
                    return

                _display_one(evt)

                # Pacing after segment display (mode may change mid-sleep)
                if ctrl.mode == "auto" and evt["type"] == "segment":
                    _sleep(_AUTO_DELAY_SEC, ctrl)
                elif ctrl.mode == "manual" and evt["type"] == "segment":
                    _wait_enter(ctrl)

        if game_loop.ending_flag:
            adv = game_loop.get_adventure_log(timeout=30.0)
            if adv:
                print(adv)
                if observer is not None:
                    _record_adv(observer, game_loop, adv)
            else:
                err = game_loop.adventure_log_error
                if err:
                    # ── API error — offer manual retry ────────────
                    _error(f"Adventure log failed: {err}")
                    ans = _ask("Retry? (y/n)").strip().lower()
                    if ans in ("y", "yes"):
                        game_loop.retry_adventure_log()
                        adv = game_loop.get_adventure_log(timeout=60.0)
                        if adv:
                            print(adv)
                            if observer is not None:
                                _record_adv(observer, game_loop, adv)
                        else:
                            _error("Adventure log retry failed")
                    return
                else:
                    print("[Adventure log still generating...]")
                    adv = game_loop.get_adventure_log(timeout=60.0)
                    if adv:
                        print(adv)
                        if observer is not None:
                            _record_adv(observer, game_loop, adv)
                    else:
                        print("[Adventure log unavailable]")
            return

        # Phase 1: Next round's prompt was just sent by stream_round()
        if observer is not None:
            observer.write_prompt_at_send(
                game_loop._pending_messages,
                game_loop.round_count + 1,
            )


# ═══════════════════════════════════════════════════════════════════
# Display helpers
# ═══════════════════════════════════════════════════════════════════

def _drain_non_options(queue: collections.deque) -> None:
    """Display all events in queue that are NOT options events."""
    drained = []
    while queue and queue[0]["type"] != "options":
        drained.append(queue.popleft())
    for evt in drained:
        _display_one(evt)


def _display_one(evt: dict) -> None:
    """Render a single event to the terminal.

    Only parsed content (segments) is displayed.  Raw token deltas are
    not shown — they belong in ``responses.txt`` via the observer.
    """
    etype = evt.get("type", "")

    if etype == "segment":
        print(evt.get("text", ""))

    elif etype == "bridge":
        print("---")

    # token, story_begin, story_end, done, state, ending — silent
    # ending.adventure_log is always None from the engine; adventure
    # log is fetched separately via game_loop.get_adventure_log().


def _sleep(duration: float, ctrl: DisplayController) -> None:
    """Sleep with Tab-key detection for auto→manual switch.

    Enters raw (cbreak) mode so Tab is detected without Enter.
    Restores normal mode on exit or when mode switches to manual.
    """
    with ctrl._term.raw_mode():
        elapsed = 0.0
        while elapsed < duration and ctrl.mode == "auto":
            time.sleep(0.05)
            elapsed += 0.05
            ctrl.poll_toggle()


def _wait_enter(ctrl: DisplayController) -> None:
    """Wait for Enter (manual mode).  Tab to switch to auto.

    Uses raw (cbreak) mode so Tab is detected without Enter,
    same as ``_sleep()``.
    """
    if not ctrl._enter_hint_shown:
        print("[Enter to continue, Tab for auto]")
        ctrl._enter_hint_shown = True
    with ctrl._term.raw_mode():
        while True:
            ch = ctrl._term.get_char(0.1)
            if ch == "\t":          # Tab → switch to auto
                ctrl.mode = "auto"
                return
            if ch in ("\r", "\n"):  # Enter → advance
                return
            if ch == "\x03":        # Ctrl+C
                raise KeyboardInterrupt


# ═══════════════════════════════════════════════════════════════════
# Adventure log recording
# ═══════════════════════════════════════════════════════════════════

def _record_adv(observer: DevObserver, game_loop: GameLoop, response: str) -> None:
    """Rebuild adventure log prompt and record prompt + response."""
    from storyloom.core.prompt_builder import PromptBuilder
    prompt = PromptBuilder.build_adventure_log_prompt(
        story_config=game_loop.story_config,
        state_vars=game_loop.game_state.state_vars,
        outline_text=game_loop.outline_text,
    )
    observer.record_adventure_log(prompt, response)


# ═══════════════════════════════════════════════════════════════════
# Choice input
# ═══════════════════════════════════════════════════════════════════

def _show_choices(evt: dict) -> str | None:
    """Display choice options and get player selection.

    Reads the engine-evaluated ``enabled`` list to annotate locked
    options.  Disabled selections are rejected locally (never sent
    to the engine).  Returns choice key (1-indexed string) or None
    (quit).
    """
    choices = evt.get("choices", [])
    total = 0
    disabled_indices: set[int] = set()
    for choice in choices:
        labels = choice.get("labels", [])
        enabled = choice.get("enabled", [True] * len(labels))
        for i, label in enumerate(labels):
            idx = total + i + 1
            if i < len(enabled) and not enabled[i]:
                print(f"  [{idx}] {label} (locked)")
                disabled_indices.add(idx)
            else:
                print(f"  [{idx}] {label}")
        total += len(labels)

    while True:
        try:
            raw = _ask("").lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if raw in ("q", "quit", "exit"):
            return None
        if raw.isdigit() and 1 <= int(raw) <= total:
            if int(raw) in disabled_indices:
                print("  This option is currently unavailable.")
                continue
            return raw
        print(f"  Enter 1-{total}, or q to quit")


# ═══════════════════════════════════════════════════════════════════
# Save management
# ═══════════════════════════════════════════════════════════════════

def run_load_save(session: GameSession, ctrl: DisplayController,
                  observer: DevObserver | None = None) -> None:
    """Browse saves — load or delete.

    Three-level nested menu:

    Level 1 — Game list:
        List all games.  Pick one to see its saves.

    Level 2 — Save list:
        List all saves in a game.  Pick one to see details, or [D]
        to delete the entire game.

    Level 3 — Save detail:
        Show metadata for a single save.  [L] to load and play,
        [D] to delete.

    Reuses ``session.list_games()``, ``session.list_saves()``,
    ``session.load_game()``, ``session.delete_game()``,
    ``session.delete_save()`` — no engine-layer changes.
    """
    # ── Level 1: Game list ──────────────────────────────────────
    while True:
        games = session.list_games()
        print("\nLoad Save")
        if not games:
            print("  No games found.")
            _ask("Press Enter to go back")
            return
        for i, g in enumerate(games):
            print(f"  [{i + 1}] {g.get('label', '?')} "
                  f"({g.get('genre', '?')}, "
                  f"{g.get('save_count', 0)} saves)")
        print("  [0] Back")

        pick = _ask("").strip()
        if pick in ("0", "b", "back"):
            return
        if not (pick.isdigit() and 1 <= int(pick) <= len(games)):
            continue
        game = games[int(pick) - 1]
        game_id = game["game_id"]
        game_label = game.get("label", game_id)

        # ── Level 2: Save list ───────────────────────────────────
        while True:
            saves = session.list_saves(game_id)
            print(f"\nGame: {game_label} "
                  f"({game.get('genre', '?')}, "
                  f"{len(saves)} saves)")
            if not saves:
                print("  No saves in this game.")
                _ask("Press Enter to go back")
                break
            for i, s in enumerate(saves):
                cp_title = s.get("checkpoint_title") or "_init"
                print(f"  [{i + 1}] {cp_title} "
                      f"({s.get('saved_at', '?')})")
            print("  [D] Delete this game")
            print("  [0] Back")

            pick = _ask("").strip()
            if pick in ("0", "b", "back"):
                break
            if pick.lower() == "d":
                ans = _ask(f"Delete game '{game_label}' and ALL its saves? "
                           f"This cannot be undone. (y/n)").strip().lower()
                if ans in ("y", "yes"):
                    if session.delete_game(game_id):
                        print(f"  Game '{game_label}' deleted.")
                        break  # return to Level 1
                    else:
                        _error(f"Failed to delete game '{game_id}'.")
                continue

            if not (pick.isdigit() and 1 <= int(pick) <= len(saves)):
                continue
            save = saves[int(pick) - 1]
            filename = save["filename"]

            # ── Level 3: Save detail ────────────────────────────
            cp_title = save.get("checkpoint_title") or "_init"
            print(f"\nSave: {cp_title}")
            print(f"  Checkpoint: {save.get('checkpoint_title') or '(initial)'}")
            print(f"  Checkpoint Node: {save.get('checkpoint_node') or '(none)'}")
            print(f"  Current Node: {save.get('current_node', '?')}")
            print(f"  Saved at: {save.get('saved_at', '?')}")
            print("  [L] Load this save")
            print("  [D] Delete this save")
            print("  [0] Back")

            pick = _ask("").strip()
            if pick in ("0", "b", "back"):
                continue  # back to Level 2
            if pick.lower() == "d":
                ans = _ask(f"Delete save '{filename}'? "
                           f"This cannot be undone. (y/n)").strip().lower()
                if ans in ("y", "yes"):
                    if session.delete_save(game_id, filename):
                        print(f"  Save '{filename}' deleted.")
                    else:
                        _error(f"Failed to delete save '{filename}'.")
            elif pick.lower() == "l":
                try:
                    game_loop = session.load_game(game_id, filename)
                except Exception as e:
                    _error(f"Load failed: {e}")
                    continue
                try:
                    run_game(game_loop, ctrl, observer)
                except KeyboardInterrupt:
                    pass
                print("\n[Game over]")
                return  # back to main menu after game ends


# ═══════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════

def dev_main(argv: list[str] | None = None) -> None:
    """Entry point for the dev CLI.

    Usage::

        python -m storyloom.dev_cli                  play mode (manual, no files)
        python -m storyloom.dev_cli --observer        observer + manual (toggle in-game)
        python -m storyloom.dev_cli --observer --instant  observer + instant (no toggle)

    Play mode needs no extra arguments — always manual pacing with
    Tab-to-auto toggle.  Observer mode defaults to the same manual
    behaviour; ``--instant`` disables all pacing and in-game toggle.
    """
    # ── Config ─────────────────────────────────────────────────
    app_dir = _get_app_dir()
    config = UserConfig(app_dir)
    locale_dir = str(app_dir / "locale")
    init_i18n(config.language, locale_dir=locale_dir)

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="storyloom",
        description="Storyloom — AI-powered interactive text fiction",
    )
    parser.add_argument(
        "-o", "--observer",
        action="store_true",
        help="Enable observer mode (writes prompts/responses/checks to dev_output/)",
    )
    parser.add_argument(
        "--instant",
        action="store_true",
        help="Instant display — no per-segment pacing, no in-game toggle (observer only)",
    )
    args = parser.parse_args(argv)

    # ── Mode resolution ─────────────────────────────────────────────
    is_observer = args.observer
    if is_observer and args.instant:
        display_mode = "instant"
    else:
        display_mode = "manual"

    # ── Setup ─────────────────────────────────────────────────────
    api_client = ApiClient(config)
    session = GameSession(api_client=api_client)
    observer = DevObserver() if is_observer else None
    ctrl = DisplayController(initial_mode=display_mode)

    # ── Main menu + game loop ─────────────────────────────────────
    while True:
        games = session.list_games()
        print("\nStoryloom")
        print("  [1] New Game")
        if games:
            # Show most recent game label as hint
            latest = max(games, key=lambda g: g.get("last_played_at", ""))
            hint = latest.get("label", "?")
            print(f"  [2] Continue ({hint})")
        else:
            print("  [2] Continue")
        print("  [3] Load Save")
        print("  [4] Credits")
        print("  [5] Exit")

        choice = _ask("").strip()

        if choice == "1":
            # ── New game: co-creation → game ──────────────────────
            try:
                result = run_co_create(session, observer)
            except KeyboardInterrupt:
                print("\n[Interrupted]")
                continue
            if result is None:
                continue
            try:
                game_loop, game_id = session.start_game(result)
                run_game(game_loop, ctrl, observer)
            except KeyboardInterrupt:
                pass
            print("\n[Game over]")
            continue

        elif choice == "2":
            # ── Continue: auto-resume last played save ────────────
            if not games:
                print("  No games found.")
                continue
            latest_game = max(games, key=lambda g: g.get("last_played_at", ""))
            game_id = latest_game["game_id"]
            saves = session.list_saves(game_id)
            if not saves:
                print(f"  No saves in '{latest_game.get('label', game_id)}'.")
                continue
            latest_save = max(saves, key=lambda s: s.get("saved_at", ""))
            try:
                game_loop = session.load_game(game_id, latest_save["filename"])
            except Exception as e:
                _error(f"Load failed: {e}")
                continue
            try:
                run_game(game_loop, ctrl, observer)
            except KeyboardInterrupt:
                pass
            print("\n[Game over]")
            continue

        elif choice == "3":
            # ── Load Save: browse, load, or delete saves ──────────
            run_load_save(session, ctrl, observer)
            continue

        elif choice == "4":
            print("\n┌─────────────────────────────────────────┐")
            print("│            Storyloom — 制作人员         │")
            print("├─────────────────────────────────────────┤")
            print("│                                         │")
            print("│  引擎 & 系统架构                        │")
            print("│  Slev                                  │")
            print("│                                         │")
            print("│  Web 界面                               │")
            print("│  Aiden                                  │")
            print("│                                         │")
            print("│  基于 Claude (Anthropic) 驱动           │")
            print("│                                         │")
            print("└─────────────────────────────────────────┘")
            _ask("Press Enter to go back")
            continue

        elif choice == "5":
            sys.exit(0)


# ── App directory helper ──────────────────────────────────────────


def _get_app_dir() -> Path:
    """Return the application data directory.

    When frozen (PyInstaller), returns the directory containing the executable.
    In development, returns the project root (two levels up from this file).
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).resolve().parents[3]
