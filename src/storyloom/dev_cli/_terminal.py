"""Platform-adaptive terminal input for the dev CLI.

Provides a unified interface for single-key input detection across
POSIX (termios + tty + select) and Windows (msvcrt).

This is a dev-CLI utility — not part of the engine.
"""

import sys
import time


class TerminalInput:
    """Non-blocking single-character input, platform-adapted.

    Usage::

        ti = TerminalInput()
        with ti.raw_mode():
            while True:
                ch = ti.get_char(0.1)
                if ch == '\\t':
                    break
    """

    def __init__(self) -> None:
        self._fd = sys.stdin.fileno()
        self._old_settings: list | None = None
        self._is_windows = sys.platform == 'win32'

        if self._is_windows:
            import msvcrt as _m
            self._msvcrt = _m
        else:
            import select as _sel
            import termios as _t
            import tty as _tt
            self._select = _sel
            self._termios = _t
            self._tty = _tt

    # ── Raw mode context manager ──────────────────────────────────

    def raw_mode(self) -> '_RawModeGuard':
        """Context manager that enables single-key input mode.

        On POSIX: cbreak mode (no Enter required to read keys).
        On Windows: no-op (console already supports single-key reads).
        """
        return _RawModeGuard(self)

    def _enter_raw(self) -> None:
        if not self._is_windows:
            self._old_settings = self._termios.tcgetattr(self._fd)
            self._tty.setcbreak(self._fd)

    def _exit_raw(self) -> None:
        if not self._is_windows and self._old_settings is not None:
            self._termios.tcsetattr(
                self._fd, self._termios.TCSADRAIN, self._old_settings
            )
            self._old_settings = None

    # ── Single-key input ──────────────────────────────────────────

    def get_char(self, timeout_sec: float = 0.0) -> str | None:
        """Read a single character, non-blocking.

        Args:
            timeout_sec: Max seconds to wait.  0 = poll only (no wait).

        Returns:
            A single-character string, or None if no key is available.
        """
        if self._is_windows:
            return self._get_char_windows(timeout_sec)
        else:
            return self._get_char_posix(timeout_sec)

    def _get_char_windows(self, timeout_sec: float) -> str | None:
        if self._msvcrt.kbhit():
            ch = self._msvcrt.getch()
            try:
                return ch.decode('utf-8')
            except UnicodeDecodeError:
                return ch.decode('latin-1')
        elif timeout_sec > 0:
            time.sleep(min(timeout_sec, 0.05))
        return None

    def _get_char_posix(self, timeout_sec: float) -> str | None:
        r, _, _ = self._select.select(
            [sys.stdin], [], [], timeout_sec if timeout_sec > 0 else 0
        )
        if r:
            return sys.stdin.read(1)
        return None


class _RawModeGuard:
    """Context manager: enter raw mode on __enter__, restore on __exit__."""

    def __init__(self, terminal: TerminalInput) -> None:
        self._terminal = terminal

    def __enter__(self) -> '_RawModeGuard':
        self._terminal._enter_raw()
        return self

    def __exit__(self, *args: object) -> bool:
        self._terminal._exit_raw()
        return False
