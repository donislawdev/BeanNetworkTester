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
    return SocketEvent(kind, pid, port)


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


def test_owner_targeted_reads_the_live_map_without_waiting_for_a_rebuild():
    """`__contains__` answers from a set rebuilt on the resolver's thread, so the
    FIRST packet of a fresh connection is judged before any rebuild it triggers.
    Measured end to end 2026-07-28: 20 fresh connections against a process target
    with `--syn-drop 100` gave 20 established connections and `drop_syn` 0.

    `owner_targeted` is the one path that consults the live map instead, so it answers
    correctly with NO refresh having happened - which is what this asserts by
    never starting a resolver.
    """
    names = _Names({100: "chrome.exe", 200: "svchost.exe"})
    watcher = SocketWatcher(names=names,
                            source_factory=lambda: _Source([ev(CONNECT, 100, 5000),
                                                            ev(CONNECT, 200, 6000)]))
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=watcher)
    watcher.start()
    try:
        _wait(lambda: watcher.pid_for(5000) == 100)
        # no resolver: the rebuilt port set is still empty, as it is for every
        # brand-new socket at the moment its SYN is judged
        check("the rebuilt set knows nothing yet", 5000 not in targeting)
        check("...and owner_targeted cannot help until a rebuild names the pid",
              targeting.owner_targeted(5000) is False)

        targeting.refresh()          # what the resolver does on the miss above
        check("after the rebuild the fresh socket is covered",
              targeting.owner_targeted(5000) is True)
        check("another process's socket is not",
              targeting.owner_targeted(6000) is False)
    finally:
        watcher.stop()


def test_owner_targeted_survives_a_table_that_cannot_answer():
    """`set_table` takes anything with the read surface, and `pid_for` only became
    part of that contract with `owner_targeted`. This runs on the CAPTURE THREAD, so a
    table without it has to answer False - an AttributeError there would kill the
    capture thread and fail the session open (convention 20)."""
    class _NoPidFor:
        def snapshot(self):
            return {}

    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=_NoPidFor())
    targeting._pids = frozenset({100})
    check("a table without pid_for answers False instead of raising",
          targeting.owner_targeted(5000) is False)


def test_owner_targeted_says_no_for_portless_traffic():
    """ICMP reaches this now, and it did not before UDP was covered.

    Step 1 asks for a TCP SYN or for anything that is NOT TCP, and ICMP is not
    TCP - so every ping packet calls ``owner_targeted(None)`` on the CAPTURE
    THREAD. Previously only a TCP SYN could get here, so the ``port is None``
    guard sat on a path nothing ever took.

    It needs its own guard against the REAL class: mutating that line to
    ``return True`` was caught by NOTHING (checked 2026-07-28), because the core
    test drives a ``_FakePorts`` double with its own implementation. A portless
    packet answering True would drag every ping on the machine into scope while a
    process target is set - the exact false positive targeting exists to avoid.
    """
    class _Table:
        def snapshot(self):
            return {5000: 100}

        def pid_for(self, port):
            return {5000: 100}.get(port)

    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=_Table())
    targeting._pids = frozenset({100})
    check("a port we have is still covered", targeting.owner_targeted(5000) is True)
    check("portless traffic answers False, it does not fall through",
          targeting.owner_targeted(None) is False)


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
