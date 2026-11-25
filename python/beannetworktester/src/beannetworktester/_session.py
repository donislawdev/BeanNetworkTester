"""A session: the program started on an aim, waited for, and stopped with its summary.

The program writes one JSON object per line (``--format json``). The session waits
for its ``start`` object before it hands control back, so the traffic a test sends
next is already slowed, and stops it by closing its standard input
(``--stop-on-stdin-close``): a normal end, with a summary. If the test process dies,
its end of that pipe closes with it and the program stops at once, and ``duration``
stops it in any case.
"""

from __future__ import annotations

import atexit
import collections
import contextlib
import json
import subprocess
import sys
import threading
import warnings

from ._aim import session_flags
from ._lock import MachineLock
from ._program import BadNetworkError, program_command, rights_prefix

DEFAULT_DURATION = 300.0
MAX_DURATION = 86400.0
_EXIT_MEANING = {
    2: "the program refused the command line",
    3: "the program refused the settings",
    4: "the program could not read the scenario",
    5: "the program could not write a file it was asked to write",
    7: "the program has no right to capture",
}
# Every started session that has not been stopped, for the exit handler below. A session
# nobody keeps in a variable still runs: its reader threads hold it (measured: a
# collection with only a weak reference left did not end it).
_LIVE: "set[BadNetwork]" = set()


class BadNetworkWarning(UserWarning):
    """A session ran, but not the way a test would want: it slowed nothing, say."""


class BadNetwork:
    """One session. ``bad_network(...)`` makes one and starts it."""

    def __init__(self, *, server=None, process=None, duration: float = DEFAULT_DURATION,
                 simulate: bool = False, wait: float = 600.0, start_timeout: float = 60.0,
                 **settings):
        try:
            seconds = float(duration)
        except (TypeError, ValueError):
            seconds = -1.0
        if not 0 < seconds <= MAX_DURATION:
            raise BadNetworkError(
                f"duration={duration!r}: give the most seconds the session may run, above 0 "
                f"and at most {MAX_DURATION:g}. It is the safety net if nothing else stops it.")
        self.server, self.process, self.simulate = server, process, bool(simulate)
        self.duration, self.wait, self.start_timeout = seconds, wait, start_timeout
        self.settings = dict(settings)
        self.command: list[str] = []
        self.start_record: dict | None = None
        self.summary: dict | None = None
        self.stderr: collections.deque[str] = collections.deque(maxlen=60)
        self._records: list[dict] = []
        self._proc: subprocess.Popen | None = None
        self._lock = MachineLock()
        self._started = threading.Event()
        self._stopped = False
        self._readers: list[threading.Thread] = []

    # -- life ------------------------------------------------------------------ #

    def start(self) -> "BadNetwork":
        if self._proc is not None:
            raise BadNetworkError("this session has already been started; make a new one")
        flags = session_flags(server=self.server, process=self.process,
                              simulate=self.simulate, settings=self.settings)
        tail = ["--format", "json", "--stop-on-stdin-close", "--duration", f"{self.duration:g}"]
        if self.simulate:
            tail.append("--simulate")
        self.command = (rights_prefix(simulate=self.simulate) + program_command()
                        + flags + tail)
        self._lock.acquire(self.wait)
        try:
            self._launch()
            self._wait_for_start()
        except BaseException:
            self._abandon()
            raise
        _LIVE.add(self)
        return self

    def stop(self, timeout: float = 30.0) -> dict | None:
        """End the session and return its summary (the program's ``summary`` object)."""
        proc = self._proc
        if proc is None or self._stopped:
            return self.summary
        self._stopped = True
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except OSError:
            pass                       # the program already ended: its pipe went with it
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()                # the traffic comes back when the process is gone
            proc.wait()
        self._finish()
        if self.summary is None:
            raise BadNetworkError(self._ended_without_summary(proc.returncode))
        self._warn_about(self.summary)
        return self.summary

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def __enter__(self) -> "BadNetwork":
        return self if self._proc is not None else self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- inside ---------------------------------------------------------------- #

    def _launch(self) -> None:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - the program, from this package
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                creationflags=flags)
        except OSError as exc:
            raise BadNetworkError(f"the program could not be started: {exc}") from exc
        self._readers = [
            threading.Thread(target=self._read_out, args=(self._proc.stdout,), daemon=True),
            threading.Thread(target=self._read_err, args=(self._proc.stderr,), daemon=True)]
        for reader in self._readers:
            reader.start()

    def _read_out(self, stream) -> None:
        for line in stream:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            self._records.append(record)
            if record.get("event") == "start":
                self.start_record = record
                self._started.set()
            elif record.get("event") == "summary":
                self.summary = record
        self._started.set()             # wakes a waiter whose program ended first

    def _read_err(self, stream) -> None:
        for line in stream:
            self.stderr.append(line.rstrip("\n"))

    def _wait_for_start(self) -> None:
        if not self._started.wait(self.start_timeout):
            raise BadNetworkError(f"the program did not start capturing within "
                                  f"{self.start_timeout:g} s.{self._stderr_tail()}")
        if self.start_record is None and self._proc is not None:
            code = self._proc.wait()
            for reader in self._readers:
                reader.join(timeout=5)
            raise BadNetworkError(self._ended_without_summary(code, starting=True))

    def _finish(self) -> None:
        for reader in self._readers:
            reader.join(timeout=5)
        self._lock.release()
        _LIVE.discard(self)

    def _abandon(self) -> None:
        self._stopped = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        self._finish()

    def _stderr_tail(self) -> str:
        lines = [line for line in self.stderr if line.strip()][-8:]
        return ("\nThe program said:\n  " + "\n  ".join(lines)) if lines else ""

    def _ended_without_summary(self, code, starting: bool = False) -> str:
        when = "before it started capturing" if starting else "without a summary"
        meaning = _EXIT_MEANING.get(code, "")
        return (f"the program ended {when}, exit code {code}"
                + (f" ({meaning})" if meaning else "") + "." + self._stderr_tail())

    def _warn_about(self, summary: dict) -> None:
        if summary.get("stop_reason") == "duration":
            warnings.warn(BadNetworkWarning(
                f"the session ended by its duration ({self.duration:g} s) before it was stopped, "
                "so the rest of the test ran on a normal network. Give a longer duration="),
                stacklevel=3)
        counters = summary.get("counters") or {}
        if not self.simulate and counters.get("seen") and not counters.get("scoped_seen"):
            warnings.warn(BadNetworkWarning(
                f"the session slowed nothing: none of the {counters.get('seen')} packets it saw "
                "matched its aim. Check server= or process=."), stacklevel=3)


def bad_network(**options) -> BadNetwork:
    """Start a session and return it. ``with bad_network(...):`` stops it at the end."""
    return BadNetwork(**options).start()


@atexit.register
def _stop_the_rest() -> None:
    for session in list(_LIVE):
        # Leaving anyway: a session that cannot say how it ended still ends when this
        # process's end of its pipe closes.
        with contextlib.suppress(BadNetworkError, OSError):
            session.stop(timeout=10)
