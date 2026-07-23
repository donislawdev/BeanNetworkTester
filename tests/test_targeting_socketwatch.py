"""Targeting resolves against the live socket-event map (chunk 2c).

Before 2c, ProcessTargeting resolved against the polling PortTable, so a new
connection was targeted only at the next poll (up to a refresh interval late, and
never at all if it opened and closed in between). Now the engine points targeting
at the SocketWatcher when a session has one, so a connection is targeted the
instant its SOCKET event arrives. These tests prove the table swap (unit), the
end-to-end resolution through a watcher (integration), and the engine binding -
all without WinDivert.
"""
import threading
import time

import bean_network_tester as bnt
from beantester.engine import BeanEngine
from beantester.socketwatch import CONNECT, SocketEvent, SocketWatcher
from beantester.targeting import ProcessTargeting
from beantester.target_resolver import TargetResolver
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


class _Names:
    def __init__(self, names):
        self._names = dict(names)

    def name_of(self, pid, cheap=False):
        return self._names.get(pid, "")

    def ancestors(self, pid, depth=8):
        return []


class _Source:
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
    """portmap.PortTable surface the engine touches (bootstrap + delegation)."""

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
        return {100: "chrome.exe"}.get(pid, "")

    def ancestors(self, pid, depth=8):
        return []

    def process_for_port(self, port, now=None, allow_refresh=True):
        return self.name_of(self._ports.get(port))

    def pid_for(self, port):
        return self._ports.get(port)


# -- unit: the table swap ----------------------------------------------------- #
def test_set_table_swaps_which_map_targeting_resolves_against():
    class _T:
        def __init__(self, ports, names):
            self.ports, self._n = ports, names

        def refresh(self, now=None, force=False):
            return True

        def snapshot(self):
            return dict(self.ports)

        def name_of(self, pid, cheap=False):
            return self._n.get(pid, "")

        def ancestors(self, pid, depth=8):
            return []

    a = _T({5000: 1}, {1: "chrome.exe"})
    b = _T({6000: 2}, {2: "chrome.exe"})
    t = ProcessTargeting(bnt.parse_target("chrome"), table=a)
    t.refresh()
    check("resolves against table A", t.ports() == {5000}, f"({t.ports()})")
    t.set_table(b)
    t.refresh()
    check("after set_table it resolves against table B", t.ports() == {6000},
          f"({t.ports()})")


# -- integration: targeting via a live watcher -------------------------------- #
def test_a_connection_is_targeted_the_moment_its_socket_event_arrives():
    """The whole point of chunk 2: no poll, no race. A CONNECT event for a matching
    process puts its local port in scope, driven by the event, not a snapshot."""
    names = _Names({100: "chrome.exe"})
    source = _Source([ev(CONNECT, 100, 5000)])
    watcher = SocketWatcher(names=names, source_factory=lambda: source)
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=watcher)

    resolver = TargetResolver(interval=5.0, min_interval=0.02)
    watcher.start()
    resolver.retarget(targeting)
    resolver.start()
    try:
        # asking about the port both drives the miss-wake and is the assertion
        check("chrome's socket is targeted from its event",
              _wait(lambda: 5000 in targeting))
        check("an unrelated port is not targeted", 9999 not in targeting)
    finally:
        resolver.stop()
        watcher.stop()


# -- engine binding ----------------------------------------------------------- #
def test_engine_binds_targeting_to_the_watcher_when_present():
    eng = BeanEngine()
    eng._ports = _FakePorts({})
    targeting = eng.target_for(bnt.parse_target("chrome"))     # built before start
    check("built against the poller before start", targeting.table is eng._ports)
    eng.set_target(True, targeting)
    eng.start("true", divert=FakeDivert([]), socket_source=_Source([]))
    try:
        check("start rebound targeting to the live watcher",
              targeting.table is eng._socketwatch and eng._socketwatch is not None)
    finally:
        eng.stop()


def test_engine_keeps_targeting_on_the_poller_without_a_watcher():
    """Synthetic/simulate path: no watcher, so targeting stays on the poller."""
    eng = BeanEngine()
    eng._ports = _FakePorts({})
    targeting = eng.target_for(bnt.parse_target("chrome"))
    eng.set_target(True, targeting)
    eng.start("true", divert=FakeDivert([]))                   # no socket source
    try:
        check("no watcher on the synthetic path", eng._socketwatch is None)
        check("targeting stays on the poller", targeting.table is eng._ports)
    finally:
        eng.stop()
