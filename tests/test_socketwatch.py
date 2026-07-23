"""The live local_port -> pid map fed by SOCKET-layer events (chunk 2a).

This module is the replacement for polling the socket table: instead of a
snapshot taken a few times a second (which misses any connection that opens and
closes between two snapshots), the map is updated the instant a socket is
bound/connected/accepted/closed. These tests drive the map through its event
API directly - no WinDivert, no threads - plus one lifecycle test on an injected
fake source. The real Windows source is exercised by the smoke, not here.
"""
import threading
import time

from beantester.socketwatch import (ACCEPT, BIND, CLOSE, CONNECT, LISTEN,
                                     SocketEvent, SocketWatcher, _ipv4)
from fakes import check


def ev(kind, pid, port, proto=6, remote_ip="1.2.3.4", remote_port=443, outbound=True):
    return SocketEvent(kind, pid, proto, port, remote_ip, remote_port, outbound)


class _FakeNames:
    """Stands in for portmap's pid -> name / ancestors cache (no psutil)."""

    def __init__(self):
        self.calls = []

    def name_of(self, pid, cheap=False, allow_bulk=True):
        self.calls.append(("name_of", pid, cheap))
        return {100: "chrome.exe"}.get(pid, "")

    def ancestors(self, pid, depth=8, allow_bulk=True):
        self.calls.append(("ancestors", pid, depth))
        return [(1, "explorer.exe")]


class _FakeSource:
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


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def _watcher():
    return SocketWatcher(names=_FakeNames())


# -- the map ------------------------------------------------------------------ #
def test_add_events_map_the_local_port_to_the_owning_pid():
    """Every "a socket now owns a port" event populates the map."""
    w = _watcher()
    w.apply(ev(CONNECT, 100, 5000))     # TCP outbound
    w.apply(ev(BIND, 101, 5001))        # UDP (QUIC binds, never connects)
    w.apply(ev(ACCEPT, 102, 5002))      # TCP inbound
    w.apply(ev(LISTEN, 103, 5003))      # a server socket
    check("all four add-events mapped their port", w.snapshot() ==
          {5000: 100, 5001: 101, 5002: 102, 5003: 103}, f"({w.snapshot()})")


def test_close_releases_the_port():
    w = _watcher()
    w.apply(ev(CONNECT, 100, 5000))
    w.apply(ev(CLOSE, 100, 5000))
    check("close removed the port", 5000 not in w.snapshot(), f"({w.snapshot()})")


def test_a_stale_close_does_not_evict_a_recycled_port():
    """Windows reuses ports and PIDs: a late CLOSE for the OLD owner must not
    evict the NEW one that has taken the same port number."""
    w = _watcher()
    w.apply(ev(CONNECT, 100, 5000))     # old owner
    w.apply(ev(CONNECT, 200, 5000))     # the port is reused by a different pid
    w.apply(ev(CLOSE, 100, 5000))       # a late close for the OLD owner arrives
    check("the port still belongs to the new owner", w.snapshot().get(5000) == 200,
          f"({w.snapshot()})")


def test_close_for_an_unknown_port_is_harmless():
    w = _watcher()
    w.apply(ev(CLOSE, 100, 5000))       # never added
    check("closing an unknown port does nothing", w.snapshot() == {}, f"({w.snapshot()})")


def test_junk_events_are_ignored_not_raised():
    """The hot path must never be handed a crash: port 0 (not yet assigned) and
    pid 0 (the idle process) are dropped, quietly."""
    w = _watcher()
    for bad in (ev(CONNECT, 100, 0), ev(CONNECT, 0, 5000), ev(CONNECT, -1, 5000)):
        w.apply(bad)
    check("no junk entered the map", w.snapshot() == {}, f"({w.snapshot()})")


# -- reconcile (bootstrap + safety net) --------------------------------------- #
def test_reconcile_bootstraps_and_prunes_only_after_a_two_pass_grace():
    """The snapshot seeds the map and catches missed CLOSEs - but a socket opened
    microseconds before the snapshot was taken (present via its event, absent from
    that snapshot) must survive one miss, or the safety net would evict live
    connections."""
    w = _watcher()
    w.reconcile({80: 1, 443: 2})                      # bootstrap
    check("bootstrap added the snapshot", w.snapshot() == {80: 1, 443: 2})

    w.apply(ev(CONNECT, 9, 5000))                     # a fresh socket via its event
    check("event added the fresh port", w.snapshot().get(5000) == 9)

    w.reconcile({80: 1, 443: 2})                      # snapshot has not caught 5000 yet
    check("fresh port survives ONE absent snapshot", w.snapshot().get(5000) == 9,
          f"({w.snapshot()})")

    w.reconcile({80: 1, 443: 2})                      # still absent -> missed-CLOSE case
    check("absent-twice port is pruned", 5000 not in w.snapshot(), f"({w.snapshot()})")
    check("snapshot ports are always kept", w.snapshot() == {80: 1, 443: 2})


def test_reconcile_grace_resets_when_a_port_reappears():
    w = _watcher()
    w.apply(ev(CONNECT, 9, 5000))
    w.reconcile({})                                   # absent once (on watch)
    w.reconcile({5000: 9})                            # reappears -> cleared
    w.reconcile({})                                   # absent once again, not twice running
    check("a port that reappeared is not pruned on a single later miss",
          w.snapshot().get(5000) == 9, f"({w.snapshot()})")


# -- name resolution is delegated, not duplicated ----------------------------- #
def test_name_and_ancestors_delegate_to_the_names_table():
    names = _FakeNames()
    w = SocketWatcher(names=names)
    check("name_of delegates", w.name_of(100) == "chrome.exe")
    check("ancestors delegate", w.ancestors(100) == [(1, "explorer.exe")])
    check("both calls went to the names table",
          [c[0] for c in names.calls] == ["name_of", "ancestors"], f"({names.calls})")


def test_refresh_is_a_noop_the_events_keep_it_live():
    """ProcessTargeting calls table.refresh(); on this table it must be free and
    must not clear the live map."""
    w = _watcher()
    w.apply(ev(CONNECT, 100, 5000))
    check("refresh returns False (nothing rebuilt)", w.refresh() is False)
    check("refresh left the live map intact", w.snapshot() == {5000: 100})


# -- the reader thread -------------------------------------------------------- #
def test_the_watcher_thread_applies_events_from_its_source():
    events = [ev(CONNECT, 100, 5000), ev(BIND, 100, 5001), ev(CLOSE, 100, 5000)]
    w = SocketWatcher(names=_FakeNames(), source_factory=lambda: _FakeSource(events))
    w.start()
    try:
        check("the watcher applied its events", _wait(lambda: w.events >= 3))
        check("connect+bind added, close removed", w.snapshot() == {5001: 100},
              f"({w.snapshot()})")
        check("the reader thread is alive", w.is_running())
    finally:
        w.stop()
    check("stop joined the thread", not w.is_running())


def test_stop_is_safe_without_a_start():
    w = _watcher()
    w.stop()                                          # must not raise
    check("still not running", not w.is_running())


def test_stop_does_not_record_the_close_induced_error_as_a_crash(monkeypatch):
    """stop() closes the source, and on real WinDivert the parked recv() then raises
    (WinError 995, "I/O aborted"). That is the NORMAL shutdown path, not a fault - it
    must not land in the crash log, or every STOP leaves a spurious entry."""
    from beantester import crashlog
    recorded = []
    monkeypatch.setattr(crashlog, "_once_seen", set())
    monkeypatch.setattr(crashlog, "record", lambda exc, **kw: recorded.append(kw))

    class _RaisingSource:
        def __init__(self):
            self._closed = threading.Event()

        def __iter__(self):
            self._closed.wait()                       # park like a blocking recv()
            raise OSError("[WinError 995] aborted")   # ...then raise, as pydivert does

        def close(self):
            self._closed.set()

    w = SocketWatcher(names=_FakeNames(), source_factory=_RaisingSource)
    w.start()
    _wait(w.is_running)
    w.stop()
    time.sleep(0.05)
    check("the close-induced error was NOT recorded as a crash", recorded == [],
          f"({recorded})")

    # ...but an error while NOT stopping still is: a socket stream that dies mid-run
    # is traffic sailing through unimpaired.
    recorded.clear()
    raised = threading.Event()

    class _DiesWhileRunning:
        def __iter__(self):
            raised.set()
            raise OSError("stream died")

        def close(self):
            pass

    w2 = SocketWatcher(names=_FakeNames(), source_factory=_DiesWhileRunning)
    w2.start()
    check("the failing source ran", raised.wait(timeout=5))
    time.sleep(0.05)
    check("a mid-run failure IS recorded", len(recorded) == 1, f"({recorded})")
    w2.stop()


# -- the address decode locked by the spike ----------------------------------- #
def test_ipv4_decodes_high_byte_first():
    """The 2026-07-22 spike proved WinDivert stores the IPv4 addr MSB-first in
    addr[0]; the naive low-byte-first decode printed 192.168.1.29 as
    29.1.168.192. This locks the correct order."""
    check("ipv4 reads MSB-first", _ipv4([0xC0A8011D, 0, 0, 0]) == "192.168.1.29",
          f"({_ipv4([0xC0A8011D, 0, 0, 0])})")
    check("a bad addr array is empty, not an exception", _ipv4(None) == "")
