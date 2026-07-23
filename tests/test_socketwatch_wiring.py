"""BeanEngine drives the SocketWatcher's lifecycle (chunk 2b).

2b is pure plumbing: the engine creates, bootstraps, runs and stops the watcher,
but targeting does NOT read it yet (that is 2c). So these tests assert the wiring
- started on the real/injected path, absent on the synthetic path, bootstrapped
from the port table, degrading (not killing) on failure, and leaving no thread
behind - not any change in impairment behaviour.

Driven on a fake divert (idle, so the session stays up) and an injected fake
socket source, so no WinDivert is needed.
"""
import threading
import time

from beantester.engine import BeanEngine
from beantester.socketwatch import BIND, CONNECT, SocketEvent
from fakes import FakeDivert, check


def _wait(pred, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return False


def ev(kind, pid, port):
    return SocketEvent(kind, pid, 6, port, "1.2.3.4", 443, True)


class _FakeSocketSource:
    """Yields queued events, then parks like a blocking recv() until close()."""

    def __init__(self, events):
        self._events = list(events)
        self._closed = threading.Event()

    def __iter__(self):
        for e in self._events:
            if self._closed.is_set():
                return
            yield e
        self._closed.wait()

    def close(self):
        self._closed.set()


class _FakePorts:
    """The slice of portmap.PortTable the engine touches during a session."""

    def __init__(self, ports):
        self._ports = dict(ports)

    def refresh(self, now=None, force=False):
        return True

    def refresh_if_stale(self, now=None, miss=False):
        return True

    def snapshot(self):
        return dict(self._ports)

    def warm_names(self):
        pass

    def name_of(self, pid, cheap=False):
        return {1: "svc.exe", 2: "svc.exe", 100: "chrome.exe"}.get(pid, "")

    def ancestors(self, pid, depth=8):
        return []

    def process_for_port(self, port, now=None, allow_refresh=True):
        return self.name_of(self._ports.get(port))

    def pid_for(self, port):
        return self._ports.get(port)


def test_engine_bootstraps_and_runs_the_watcher_from_an_injected_source():
    ports = _FakePorts({80: 1, 443: 2})          # two pre-existing connections
    eng = BeanEngine()
    eng._ports = ports
    src = _FakeSocketSource([ev(CONNECT, 100, 5000)])
    eng.start("true", divert=FakeDivert([]), socket_source=src)
    try:
        w = eng._socketwatch
        check("a watcher was started", w is not None and w.is_running())
        check("bootstrap seeded the map from the port table",
              w.snapshot().get(80) == 1 and w.snapshot().get(443) == 2,
              f"({w.snapshot()})")
        # the counter proves the source -> watcher pipe works without depending on
        # the port surviving the watchdog's reconcile (which legitimately prunes a
        # port the fake snapshot never lists)
        check("the injected socket event was consumed", _wait(lambda: w.events >= 1))
    finally:
        eng.stop()
    check("stop cleared the watcher reference", eng._socketwatch is None)
    check("and stopped its thread", not w.is_running())


def test_synthetic_path_starts_no_watcher_and_falls_back_to_the_poller():
    """A fake/synthetic divert has no SOCKET layer to open, so the engine keeps
    the poller - the testable-without-WinDivert contract."""
    eng = BeanEngine()
    eng._ports = _FakePorts({})
    eng.start("true", divert=FakeDivert([]))     # no socket_source, fake divert
    try:
        check("no watcher on the synthetic path", eng._socketwatch is None)
        check("the session runs on the poller", eng.is_running())
    finally:
        eng.stop()


def test_a_watcher_that_cannot_open_degrades_instead_of_killing_the_session():
    """A denied SOCKET handle must drop the tool to the poller, not the session."""
    def boom():
        raise OSError("SOCKET handle denied")

    eng = BeanEngine()
    eng._ports = _FakePorts({})
    eng.start("true", divert=FakeDivert([]), socket_source=boom)   # factory raises
    try:
        check("the session survived the failed watcher", eng.is_running())
        check("and fell back to no watcher", eng._socketwatch is None)
    finally:
        eng.stop()


def test_stopping_the_engine_leaves_no_watcher_thread_behind():
    before = {t.name for t in threading.enumerate()}
    eng = BeanEngine()
    eng._ports = _FakePorts({})
    eng.start("true", divert=FakeDivert([]),
              socket_source=_FakeSocketSource([ev(BIND, 100, 5001)]))
    time.sleep(0.05)
    eng.stop()
    time.sleep(0.2)
    leaked = {t.name for t in threading.enumerate()} - before
    watchers = {n for n in leaked if "socket-watcher" in n}
    check("no watcher thread outlives the session", not watchers, f"({leaked})")
