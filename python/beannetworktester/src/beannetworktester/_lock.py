"""One session at a time on a machine.

Two sessions that see the same traffic add up: two of 100 ms each slowed a server
by 200 ms (measured 2026-11-25). Parallel test workers would then slow each other's
tests, so a session takes this lock for as long as it runs, and a second one waits.
The system drops the lock when the process that holds it ends, however it ends.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

from ._program import BadNetworkError

LOCK_NAME = "beannetworktester.lock"


def lock_path() -> str:
    return os.path.join(tempfile.gettempdir(), LOCK_NAME)


def _try_lock(handle) -> bool:
    if sys.platform == "win32":
        import msvcrt
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)   # type: ignore[attr-defined]
        except OSError:
            return False
        return True
    import fcntl
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle) -> None:
    if sys.platform == "win32":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)       # type: ignore[attr-defined]
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class MachineLock:
    """Held from a session's start to its stop. ``path`` is for the tests."""

    def __init__(self, path: str | None = None):
        self.path = lock_path() if path is None else path
        self._handle = None

    def acquire(self, wait: float, *, sleep=time.sleep, clock=time.monotonic) -> None:
        handle = open(self.path, "a+b")       # noqa: SIM115 - held until release()
        deadline = clock() + max(0.0, wait)
        while not _try_lock(handle):
            if clock() >= deadline:
                handle.close()
                raise BadNetworkError(
                    f"Another bad_network session has been running on this machine for the "
                    f"{wait:g} s this one waited. Sessions run one at a time, because two would "
                    "add up: with parallel test workers (pytest-xdist, Playwright workers), the "
                    "tests that slow the network wait for each other. Give a longer wait=, or "
                    "run those tests in one worker.")
            sleep(0.2)
        self._handle = handle

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            _unlock(handle)
        finally:
            handle.close()

    @property
    def held(self) -> bool:
        return self._handle is not None
