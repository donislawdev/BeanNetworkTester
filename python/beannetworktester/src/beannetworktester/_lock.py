"""One session at a time.

Two sessions that see the same traffic add up: two of 100 ms each slowed a server
by 200 ms (measured 2026-11-25). Parallel test workers would then slow each other's
tests, so a session takes this lock for as long as it runs, and a second one waits.
The system drops the lock when the process that holds it ends, however it ends.

The file is in /tmp on Linux, the machine's own and not $TMPDIR, so every user and
every environment shares the lock. On Windows it is in the user's temporary folder.
"""

from __future__ import annotations

import errno
import os
import stat
import sys
import tempfile
import time

from ._program import BadNetworkError

LOCK_NAME = "beannetworktester.lock"

# Never a link or a FIFO: on Linux the path is the same for every user of the machine,
# a link planted there would point the lock at another file, and a FIFO would block the
# open. Windows has neither flag, and the folder there is the user's own.
_SAFE = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)


def lock_path() -> str:
    folder = tempfile.gettempdir() if sys.platform == "win32" else "/tmp"  # noqa: S108
    return os.path.join(folder, LOCK_NAME)


def _not_a_lock(path: str) -> BadNetworkError:
    return BadNetworkError(f"{path} is not a plain file, so it is not a lock this package "
                           "made. Remove it, and run the tests again.")


def _open(path: str):
    """The lock file, opened for reading when it is there, and made when it is not.

    For reading, because the file may be another user's: a test run under sudo leaves
    one owned by root, which this user may lock but not write, and which Linux does not
    let a create-or-open in /tmp touch at all. Both locks work on a file open for reading.
    """
    mode = "rb"
    try:
        fd = os.open(path, os.O_RDONLY | _SAFE)
    except FileNotFoundError:
        mode = "r+b"
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | _SAFE, 0o644)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _not_a_lock(path) from exc
            raise BadNetworkError(f"The lock file {path} cannot be made: {exc}") from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise _not_a_lock(path) from exc
        raise BadNetworkError(f"The lock file {path} cannot be opened: {exc}") from exc
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise _not_a_lock(path)
    return os.fdopen(fd, mode)


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
        handle = _open(self.path)
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
