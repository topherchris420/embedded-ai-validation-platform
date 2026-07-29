"""Cooperative cancellation for validation runs.

Cancellation is cooperative and checked at stage boundaries plus inside
the long-running loops that can afford a poll (telemetry capture, suite
iteration). A token can additionally watch a sentinel file, which is how
the dashboard cancels a run that a *different* browser session — or a
different process — started: the request is durable on disk rather than
held in one web session's memory.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

#: Sentinel file written into a run directory to request cancellation.
CANCEL_FILENAME = "cancel.request"


class RunCancelled(Exception):
    """Raised inside a run when cancellation has been requested."""

    def __init__(self, reason: str = "cancelled by user") -> None:
        super().__init__(reason)
        self.reason = reason


class CancellationToken:
    """Thread-safe cancellation flag, optionally backed by a file.

    ``watch_file`` is polled at most every ``poll_interval_s`` seconds so
    a tight loop calling :meth:`check` does not hammer the filesystem.
    """

    def __init__(self, watch_file: str | Path | None = None, poll_interval_s: float = 0.25) -> None:
        self._event = threading.Event()
        self._reason = ""
        self._lock = threading.Lock()
        self.watch_file = Path(watch_file) if watch_file is not None else None
        self.poll_interval_s = poll_interval_s
        self._last_poll = 0.0

    def cancel(self, reason: str = "cancelled by user") -> None:
        with self._lock:
            if not self._reason:
                self._reason = reason
        self._event.set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason or "cancelled by user"

    @property
    def cancelled(self) -> bool:
        if self._event.is_set():
            return True
        if self.watch_file is None:
            return False
        now = time.monotonic()
        if now - self._last_poll < self.poll_interval_s:
            return False
        self._last_poll = now
        try:
            if self.watch_file.exists():
                text = self.watch_file.read_text(encoding="utf-8").strip()
                self.cancel(text or "cancellation requested")
                return True
        except OSError:
            return False
        return False

    def check(self) -> None:
        """Raise :class:`RunCancelled` if cancellation has been requested."""
        if self.cancelled:
            raise RunCancelled(self.reason)

    def wait(self, timeout_s: float) -> bool:
        """Sleep up to ``timeout_s``, returning early when cancelled.

        Returns ``True`` when the wait was cut short by cancellation.
        """
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self.cancelled
            if self._event.wait(min(remaining, self.poll_interval_s)):
                return True
            if self.cancelled:
                return True


def request_cancel(run_dir: str | Path, reason: str = "cancelled by user") -> Path:
    """Write the cancellation sentinel into a run directory."""
    path = Path(run_dir) / CANCEL_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(reason, encoding="utf-8")
    return path


def clear_cancel(run_dir: str | Path) -> None:
    """Remove a cancellation sentinel (used when a run directory is reused)."""
    (Path(run_dir) / CANCEL_FILENAME).unlink(missing_ok=True)


__all__ = [
    "CANCEL_FILENAME",
    "CancellationToken",
    "RunCancelled",
    "clear_cancel",
    "request_cancel",
]
