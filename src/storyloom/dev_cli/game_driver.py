"""Game flow driver — co-creation + narrative loop with deque buffer.

Architecture (per exec-flow.md §4.5 "UI queue buffer")::

    Receiver (fast)              Deque buffer           Display (paced)
    ─────────────────────       ──────────────         ──────────────────
    gen = gl.stream_round()     collections.deque      _display_loop()
    for event in gen:           event_queue.append()   pops at mode pace
      if options → inline                              instant: no delay
                                                       auto:    0.5s/seg
                                                       manual:  Enter/seg

Pause (Space key): display side freezes; receiver keeps filling queue.
Ctrl+C: always quit immediately.
"""

import collections
import select
import sys
import termios
import time
import tty

from storyloom.core.session import GameSession
from storyloom.core.co_create import CoCreationResult
from storyloom.core.game_loop import GameLoop
from storyloom.i18n import init_i18n

from storyloom.dev_cli.cli_ui import TerminalUi
from storyloom.dev_cli.observer import DevObserver


# ═══════════════════════════════════════════════════════════════════
# Pause handler — Space to pause, Ctrl+C to quit
# ═══════════════════════════════════════════════════════════════════

class PauseHandler:
    """Terminal raw-mode key detection.

    Space → toggle pause.  Ctrl+C → quit.
    Call ``disable()`` before any ``input()`` call, ``enable()`` after.
    """

    def __init__(self):
        self.paused = False
        self.quit_requested = False
        self._fd = sys.stdin.fileno()
        self._old: list | None = None

    def enable(self) -> None:
        """Switch terminal to cbreak mode for instant key detection."""
        self._old = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)

    def disable(self) -> None:
        """Restore normal terminal mode (for ``input()`` calls)."""
        if self._old is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)

    def poll(self) -> None:
        """Check for pending keystrokes.  Non-blocking."""
        r, _, _ = select.select([sys.stdin], [], [], 0)
        if not r:
            return
        ch = sys.stdin.read(1)
        if ch == " ":
            self.paused = not self.paused
        elif ch == "\x03":                      # Ctrl+C
            self.quit_requested = True
        # Discard other keys

    def wait_while_paused(self) -> None:
        """Block until unpaused or quit."""
        while self.paused and not self.quit_requested:
            self.poll()
            time.sleep(0.05)


# ═══════════════════════════════════════════════════════════════════
# Co-creation driver
# ═══════════════════════════════════════════════════════════════════

def run_co_create(
    ui: TerminalUi,
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
        ui.show_error(f"Co-creation failed to start: {e}")
        return None
    ui.write(event["prompt"])

    while True:
        user_input = ui.ask("").strip()
        if user_input == "":
            continue

        if user_input == "/quit":
            flow.abort()
            ui.write("[Co-creation aborted]")
            return None

        if user_input == "/go":
            break

        # ── Forward to LLM ──
        if observer is not None:
            observer.record_co_create_prompt(flow.messages, user_input)

        ui.write("[Waiting for LLM...]")
        sys.stdout.flush()
        try:
            reply = flow.send(user_input)
        except KeyboardInterrupt:
            ui.write("\n[Interrupted]")
            return None
        except (RuntimeError, ValueError) as e:
            ui.show_error(f"Co-creation error: {e}")
            return None

        if observer is not None:
            observer.record_co_create_response(flow.messages)

        ui.write(reply)

    # ── Generate ──
    ui.write("[Generating story setup...]")
    sys.stdout.flush()
    try:
        result = flow.generate()
    except Exception as e:
        ui.show_error(f"Generation failed: {e}")
        return None

    if observer is not None:
        observer.record_co_create_result(
            result.story_config, result.outline_text)
    ui.write(f"\n[Story: {result.story_config.get('label', '?')}]")
    ui.write(f"[Genre: {result.story_config.get('genre', '?')}]")
    ui.write(f"[Outline: {len(result.outline_nodes)} nodes]\n")
    return result


# ═══════════════════════════════════════════════════════════════════
# Game driver
# ═══════════════════════════════════════════════════════════════════

def run_game(
    ui: TerminalUi,
    game_loop: GameLoop,
    display_mode: str,
    pause: PauseHandler,
    observer: DevObserver | None = None,
) -> None:
    """Drive the narrative loop with deque-buffered display.

    Receiver (``for event in gen``) pushes events into a deque as fast
    as the API delivers them.  The display loop drains the deque at
    the configured pace — instant, auto (0.5 s), or manual (Enter).

    ``options`` events are handled inline because they require
    ``gen.send(key)`` from the same thread.
    """
    if observer is not None:
        game_loop._observers.append(observer.record_round)

    game_loop.start_game()
    # Round 1 prompt was just sent — write it immediately
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
                pause.poll()
                if pause.quit_requested:
                    return
                pause.wait_while_paused()

                evt = event_queue[0]  # peek

                # Options must be handled inline — needs gen.send()
                if evt["type"] == "options":
                    # Drain non-option events ahead of options first
                    _drain_non_options(ui, event_queue, display_mode, pause)
                    # Now handle the choice
                    key = _show_choices(ui, evt, pause)
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
                    ui.show_error(evt.get("message", ""))
                    pause.disable()
                    ans = ui.ask("Retry? (y/n)").strip().lower()
                    pause.enable()
                    if ans in ("y", "yes") and retry_msgs:
                        game_loop._launch_api(retry_msgs, retry_content)
                        break  # exit for loop, while loop re-calls stream_round()
                    return

                _display_one(ui, evt)

                # Pacing after segment display
                if display_mode == "auto" and evt["type"] == "segment":
                    _sleep(1.0, pause)
                elif display_mode == "manual" and evt["type"] == "segment":
                    _wait_enter(ui, pause)

        if game_loop.ending_flag:
            adv = game_loop.get_adventure_log(timeout=30.0)
            if adv:
                ui.write(adv)
                if observer is not None:
                    _record_adv(observer, game_loop, adv)
            else:
                err = game_loop.adventure_log_error
                if err:
                    ui.show_error(f"Adventure log failed: {err}")
                else:
                    ui.write("[Adventure log still generating...]")
                    adv = game_loop.get_adventure_log(timeout=60.0)
                    if adv:
                        ui.write(adv)
                        if observer is not None:
                            _record_adv(observer, game_loop, adv)
                    else:
                        ui.write("[Adventure log unavailable]")
            return

        # Next round's prompt was just sent by stream_round() Phase 5
        if observer is not None:
            observer.write_prompt_at_send(
                game_loop._pending_messages,
                game_loop.round_count + 1,
            )


# ═══════════════════════════════════════════════════════════════════
# Display helpers
# ═══════════════════════════════════════════════════════════════════

def _drain_non_options(
    ui: TerminalUi,
    queue: collections.deque,
    mode: str,
    pause: PauseHandler,
) -> None:
    """Display all events in queue that are NOT options events."""
    drained = []
    while queue and queue[0]["type"] != "options":
        drained.append(queue.popleft())
    for evt in drained:
        _display_one(ui, evt)


def _display_one(ui: TerminalUi, evt: dict) -> None:
    """Render a single event to the terminal.

    Only parsed content (segments) is displayed.  Raw token deltas are
    not shown — they belong in ``responses.txt`` via the observer.
    """
    etype = evt.get("type", "")

    if etype == "segment":
        ui.write(evt.get("text", ""))

    elif etype == "bridge":
        ui.write("---")

    # token, story_begin, story_end, done, state, ending — silent
    # ending.adventure_log is always None from the engine; adventure
    # log is fetched separately via game_loop.get_adventure_log().


def _sleep(duration: float, pause: PauseHandler) -> None:
    """Sleep in small increments, checking for pause/quit."""
    elapsed = 0.0
    while elapsed < duration:
        time.sleep(0.05)
        elapsed += 0.05
        pause.poll()
        if pause.quit_requested or pause.paused:
            return


def _wait_enter(ui: TerminalUi, pause: PauseHandler) -> None:
    """Wait for Enter keypress.  Ctrl+C propagates to top-level handler."""
    pause.disable()
    try:
        ui.ask("[Enter to continue]")
    except EOFError:
        pass
    finally:
        pause.enable()


# ═══════════════════════════════════════════════════════════════════
# Adventure log recording
# ═══════════════════════════════════════════════════════════════════

def _record_adv(observer: DevObserver, game_loop: GameLoop, response: str) -> None:
    """Rebuild adventure log prompt and record prompt + response."""
    from storyloom.core.prompt_builder import PromptBuilder
    prompt = PromptBuilder.build_adventure_log_prompt(
        story_config=game_loop.story_config,
        state_vars=game_loop.game_state.state_vars,
        checkpoint_summaries=game_loop._checkpoint_summaries,
        checkpoint_history=game_loop.checkpoint_history,
    )
    observer.record_adventure_log(prompt, response)


# ═══════════════════════════════════════════════════════════════════
# Choice input
# ═══════════════════════════════════════════════════════════════════

def _show_choices(
    ui: TerminalUi, evt: dict, pause: PauseHandler,
) -> str | None:
    """Display choice options and get player selection.

    Switches terminal to normal mode for ``input()``, then back to
    raw mode afterwards.

    Returns choice key (1-indexed string) or None (quit).
    """
    choices = evt.get("choices", [])
    total = 0
    for choice in choices:
        labels = choice.get("labels", [])
        branches = choice.get("branches", [])
        for i, (label, branch) in enumerate(zip(labels, branches)):
            branch_str = f" ({branch})" if branch else ""
            ui.write(f"  [{total + i + 1}] {label}{branch_str}")
        total += len(branches)

    pause.disable()
    try:
        while True:
            raw = ui.ask("").lower()
            if raw in ("q", "quit", "exit"):
                return None
            if raw.isdigit() and 1 <= int(raw) <= total:
                return raw
            ui.write(f"  Enter 1-{total}, or q to quit")
    except (EOFError, KeyboardInterrupt):
        return None
    finally:
        pause.enable()


# ═══════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════

def dev_main(argv: list[str] | None = None) -> None:
    """Entry point for the dev CLI.

    Usage::

        python -m storyloom.dev_cli              observer + instant
        python -m storyloom.dev_cli instant      observer + instant
        python -m storyloom.dev_cli auto         observer + auto (0.5s)
        python -m storyloom.dev_cli manual       observer + manual (Enter)
        python -m storyloom.dev_cli play          play    + auto
        python -m storyloom.dev_cli play instant  play    + instant
        python -m storyloom.dev_cli play manual   play    + manual

    All three display modes work with both observer and play.
    """
    init_i18n()

    if argv is None:
        argv = sys.argv[1:]

    MODES = ("instant", "auto", "manual")

    is_observer = True
    display_mode = "instant"   # default

    if argv:
        a0 = argv[0]
        if a0 == "play":
            is_observer = False
            display_mode = "auto"
        elif a0 in MODES:
            display_mode = a0
        # Second arg: only meaningful when first was "play"
        if len(argv) > 1 and argv[1] in MODES:
            display_mode = argv[1]

    # ── Setup ─────────────────────────────────────────────────────
    ui = TerminalUi()
    session = GameSession()
    observer = DevObserver() if is_observer else None
    pause = PauseHandler()

    # ── Main menu + game loop ─────────────────────────────────────
    while True:
        saves = session.list_saves()
        ui.write("\nStoryloom")
        ui.write("  [1] New Game")
        ui.write(f"  [2] Continue" + (f" ({len(saves)} saves)" if saves else ""))
        ui.write("  [3] Exit")

        choice = ui.ask("").strip()

        if choice == "1":
            # ── New game: co-creation → game ──────────────────────
            try:
                result = run_co_create(ui, session, observer)
            except KeyboardInterrupt:
                ui.write("\n[Interrupted]")
                continue
            if result is None:
                continue
            pause.enable()
            try:
                game_loop = session.start_game(result)
                run_game(ui, game_loop, display_mode, pause, observer)
            except KeyboardInterrupt:
                pass
            finally:
                pause.disable()
            ui.write("\n[Game over]")
            continue

        elif choice == "2":
            if not saves:
                ui.write("  No saves found.")
                continue
            for i, s in enumerate(saves):
                ui.write(f"  [{i + 1}] {s.get('label', '?')} "
                         f"(round {s.get('round_count', '?')})")
            pick = ui.ask("").strip()
            if not (pick.isdigit() and 1 <= int(pick) <= len(saves)):
                continue
            try:
                game_loop = session.load_game(saves[int(pick) - 1]["label"])
            except Exception as e:
                ui.show_error(f"Load failed: {e}")
                continue
            pause.enable()
            try:
                run_game(ui, game_loop, display_mode, pause, observer)
            except KeyboardInterrupt:
                pass
            finally:
                pause.disable()
            ui.write("\n[Game over]")
            continue

        elif choice == "3":
            sys.exit(0)
