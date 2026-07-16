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

import collections
import select
import sys
import termios
import time
import tty

from storyloom.core.session import GameSession
from storyloom.core.co_create import CoCreateError, CoCreationResult
from storyloom.core.game_loop import GameLoop
from storyloom.i18n import init_i18n

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
        self._fd = sys.stdin.fileno()
        self._old_settings: list | None = None

    # ── Raw mode (CLI only — for single-key Tab detection) ──────

    def _enter_raw(self) -> None:
        """Switch to cbreak mode.  Call before auto-mode sleep loop."""
        self._old_settings = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)

    def _exit_raw(self) -> None:
        """Restore normal terminal mode."""
        if self._old_settings is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)
            self._old_settings = None

    # ── Toggle detection ────────────────────────────────────────

    def poll_toggle(self) -> bool:
        """Non-blocking check for Tab key.  Returns True if mode changed.

        Call during auto-mode sleep loop only.  In cbreak mode, reads
        a single character without waiting for Enter.
        """
        r, _, _ = select.select([sys.stdin], [], [], 0)
        if r:
            ch = sys.stdin.read(1)
            if ch == "\t":
                self._exit_raw()
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

        # Next round's prompt was just sent by stream_round() Phase 5
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
    ctrl._enter_raw()
    try:
        elapsed = 0.0
        while elapsed < duration and ctrl.mode == "auto":
            time.sleep(0.05)
            elapsed += 0.05
            ctrl.poll_toggle()
    finally:
        ctrl._exit_raw()


def _wait_enter(ctrl: DisplayController) -> None:
    """Wait for Enter (manual mode).  Tab to switch to auto.

    Uses raw (cbreak) mode so Tab is detected without Enter,
    same as ``_sleep()``.
    """
    print("[Enter to continue, Tab for auto]")
    ctrl._enter_raw()
    try:
        while True:
            r, _, _ = select.select([sys.stdin], [], [], 0.1)
            if r:
                ch = sys.stdin.read(1)
                if ch == "\t":          # Tab → switch to auto
                    ctrl._exit_raw()
                    ctrl.mode = "auto"
                    return
                if ch in ("\r", "\n"):  # Enter → advance
                    return
                if ch == "\x03":        # Ctrl+C
                    raise KeyboardInterrupt
    finally:
        ctrl._exit_raw()


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

def _show_choices(evt: dict) -> str | None:
    """Display choice options and get player selection.

    Returns choice key (1-indexed string) or None (quit).
    """
    choices = evt.get("choices", [])
    total = 0
    for choice in choices:
        labels = choice.get("labels", [])
        branches = choice.get("branches", [])
        for i, label in enumerate(labels):
            print(f"  [{total + i + 1}] {label}")
        total += len(branches)

    while True:
        try:
            raw = _ask("").lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if raw in ("q", "quit", "exit"):
            return None
        if raw.isdigit() and 1 <= int(raw) <= total:
            return raw
        print(f"  Enter 1-{total}, or q to quit")


# ═══════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════

def dev_main(argv: list[str] | None = None) -> None:
    """Entry point for the dev CLI.

    Usage::

        python -m storyloom.dev_cli              observer + instant
        python -m storyloom.dev_cli instant      observer + instant
        python -m storyloom.dev_cli auto         observer + auto
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
            display_mode = "manual"
        elif a0 in MODES:
            display_mode = a0
        # Second arg: only meaningful when first was "play"
        if len(argv) > 1 and argv[1] in MODES:
            display_mode = argv[1]

    # ── Setup ─────────────────────────────────────────────────────
    session = GameSession()
    observer = DevObserver() if is_observer else None
    ctrl = DisplayController(initial_mode=display_mode)

    # ── Main menu + game loop ─────────────────────────────────────
    while True:
        saves = session.list_saves()
        print("\nStoryloom")
        print("  [1] New Game")
        print(f"  [2] Continue" + (f" ({len(saves)} saves)" if saves else ""))
        print("  [3] Exit")

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
                game_loop = session.start_game(result)
                run_game(game_loop, ctrl, observer)
            except KeyboardInterrupt:
                pass
            print("\n[Game over]")
            continue

        elif choice == "2":
            if not saves:
                print("  No saves found.")
                continue
            for i, s in enumerate(saves):
                print(f"  [{i + 1}] {s.get('label', '?')} "
                         f"(round {s.get('round_count', '?')})")
            pick = _ask("").strip()
            if not (pick.isdigit() and 1 <= int(pick) <= len(saves)):
                continue
            try:
                game_loop = session.load_game(saves[int(pick) - 1]["label"])
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
            sys.exit(0)
