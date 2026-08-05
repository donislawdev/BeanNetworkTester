"""BeanEngine drives the SocketWatcher's lifecycle.

This file covers the PLUMBING only: the engine creates, bootstraps, runs and stops
the watcher - started on the real/injected path, absent on the synthetic path,
bootstrapped from the port table, degrading (not killing) on failure, and leaving
no thread behind. That targeting actually RESOLVES against the watcher is a
separate contract, guarded by tests/test_targeting_socketwatch.py.

Driven on a fake divert (idle, so the session stays up) and an injected fake
socket source, so no WinDivert is needed.
"""
import threading
import time

from beantester import crashlog
from beantester.engine import WATCHDOG_TICK_S, BeanEngine
from beantester.socketwatch import BIND, CONNECT, SocketEvent
from fakes import FakeDivert, FakePacket, check


def _wait(pred, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return False


def ev(kind, pid, port):
    return SocketEvent(kind, pid, port)


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

    def collected(self):
        # This fake's map is a fixed dict, so it is always current - "collected
        # now" is the honest stamp. The engine needs the pair because the watcher
        # weighs a snapshot against its own events (see SocketWatcher.reconcile).
        return dict(self._ports), time.monotonic()

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


def test_the_event_source_is_open_before_the_bootstrap_snapshot_is_taken():
    """Subscribe, THEN snapshot - the other order has a hole a socket falls into.

    A socket created between the snapshot being collected and the source being
    opened is in neither: the snapshot predates it, and no event announced it. It
    then stays unknown to the live map until a later reconcile, and a short-lived
    connection is over by then. REPRODUCED 2026-08-04 against the real driver by
    opening a connection inside that window: never in scope for its whole life,
    while the connection table still named an owner for it.

    The order is what closes it, so the order is what this pins: the snapshot is
    collected only once the source is already delivering.
    """
    order = []

    class _WatchingPorts(_FakePorts):
        def collected(self):
            order.append("snapshot")
            return super().collected()

    def factory():
        # the FACTORY, not __iter__: opening the source happens synchronously
        # inside watcher.start(), while __iter__ runs on the watcher thread and
        # would race the assertion instead of ordering it
        order.append("subscribed")
        return _FakeSocketSource([])

    eng = BeanEngine()
    eng._ports = _WatchingPorts({80: 1})
    eng.start("true", divert=FakeDivert([]), socket_source=factory)
    try:
        check("the source was subscribed before the snapshot was collected",
              order[:2] == ["subscribed", "snapshot"], f"({order})")
    finally:
        eng.stop()


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


def test_the_watchdog_keeps_reconciling_the_live_map():
    """The safety net has to be seen RUNNING, not assumed to be.

    Both reconcile call sites sit inside exception handlers - ``crashlog.quiet`` at
    bootstrap, the watchdog's own ``except`` per tick - so anything that makes the
    call raise (a signature the caller did not follow, a table double missing a
    method) turns "the snapshot no longer corrects the map" into a session that
    looks perfectly healthy: same counters, same log, no warning. That is the one
    failure mode this wiring cannot report on its own, so it gets a witness.
    """
    eng = BeanEngine()
    eng._ports = _FakePorts({80: 1})
    src = _FakeSocketSource([ev(CONNECT, 100, 5000)])
    eng.start("true", divert=FakeDivert([]), socket_source=src)
    try:
        w = eng._socketwatch
        check("a watcher was started", w is not None)
        first = w.reconciles
        check("the watchdog reconciles while the session runs",
              _wait(lambda: w.reconciles > first, timeout=3.0),
              f"(stuck at {w.reconciles})")
    finally:
        eng.stop()


def test_a_stop_landing_mid_tick_does_not_fault_the_watchdog():
    """``stop()`` clears ``_socketwatch`` while the watchdog is inside a tick.

    The tick used to read that attribute TWICE - once for the ``is not None``
    guard, once to call ``reconcile`` - with a ``collected()`` call in between. A
    stop landing in that gap turned an ordinary STOP into an ``AttributeError``,
    swallowed by the tick's ``except`` and filed as a crash record. Nobody would
    ever see it; it would just sit in ``crashes/`` making a clean shutdown look
    like a fault.

    The race is a few instructions wide, so it is not raced here - it is STAGED:
    the port table clears the engine's reference from inside the very call that
    sits between the two reads.
    """
    crashlog.reset()

    class _ClearsTheWatcher(_FakePorts):
        def __init__(self, ports, engine):
            super().__init__(ports)
            self._engine = engine
            self.fired = False

        def collected(self):
            # Exactly where a concurrent stop() would land - but only once the
            # WATCHDOG is the caller. _start_socketwatch bootstraps through this
            # same method while _socketwatch is still None, and an earlier version
            # of this test spent its one shot there: nothing was staged, and a
            # mutant restoring the double read survived.
            if not self.fired and self._engine._socketwatch is not None:
                self.fired = True
                self._engine._socketwatch = None
            return super().collected()

    eng = BeanEngine()
    ports = _ClearsTheWatcher({80: 1}, eng)
    eng._ports = ports
    src = _FakeSocketSource([ev(CONNECT, 100, 5000)])
    eng.start("true", divert=FakeDivert([]), socket_source=src)
    try:
        check("the staged stop was reached", _wait(lambda: ports.fired, timeout=3.0))
        time.sleep(WATCHDOG_TICK_S * 2)     # let the tick finish and one more run
    finally:
        eng.stop()

    torn = [r for r in crashlog.recent(50) if r.get("type") == "AttributeError"]
    check("a stop landing mid-tick leaves no crash record", not torn,
          f"({[r.get('message') for r in torn]})")


class _GatedDivert:
    """Hands over its packet only once the test opens the gate.

    Without the gate the assertion would be a race against the watcher thread: the
    packet could reach the capture loop before the CONNECT event was applied, and the
    test would be measuring thread scheduling instead of whether the connection log
    consults the live map at all.
    """

    def __init__(self, packets):
        self.inbox = list(packets)
        self.gate = threading.Event()
        self.sent = []
        self.closed = False

    def open(self):
        pass

    def recv(self):
        self.gate.wait()
        if self.inbox:
            return self.inbox.pop(0)
        while not self.closed:
            time.sleep(0.003)
        raise OSError("closed")

    def send(self, packet, recalculate_checksum=True):
        self.sent.append(packet)

    def close(self):
        self.closed = True
        self.gate.set()              # release a parked recv() so stop() can join


def _row_for(engine, local_port):
    for row in engine.connections_snapshot(limit=None):
        if row["local_port"] == local_port:
            return row
    return None


def test_a_fresh_socket_stamps_the_connection_row_from_the_live_map():
    """Why chunk 2 reaches the connection log at all.

    The poller knows NOTHING about this port - that is the short-lived-connection
    case, where a flow opens and finishes inside one refresh interval and the row used
    to end up with no owner at all. The watcher was told the owner by its CONNECT
    event, so the row gets both a pid and a process name.
    """
    ports = _FakePorts({})                       # the poller never sees this socket
    eng = BeanEngine()
    eng._ports = ports
    divert = _GatedDivert([FakePacket(port=5000)])
    eng.start("true", divert=divert, socket_source=_FakeSocketSource([ev(CONNECT, 100, 5000)]))
    try:
        check("the poller cannot answer for this port", ports.pid_for(5000) is None)
        check("but the watcher was told the owner",
              _wait(lambda: eng._socketwatch.pid_for(5000) == 100))
        divert.gate.set()                        # only now let the packet through
        check("the row was stamped from the live map",
              _wait(lambda: (_row_for(eng, 5000) or {}).get("pid") == 100))
        row = _row_for(eng, 5000)
        check("...and named through the delegated name cache",
              row["proc"] == "chrome.exe", f"({row})")
    finally:
        eng.stop()


def test_a_second_session_gets_a_fresh_watcher_wired_to_the_target():
    """Sessions are started and stopped repeatedly, and each one builds a NEW
    watcher - so the wiring has to be redone, not inherited.

    The failure this pins is silent: the second session would run with a live map
    that tells nobody, so every new socket would wait for a rebuild again and the
    behaviour would quietly be the pre-2026-08 one, only for people who pressed
    STOP once.
    """
    import bean_network_tester as bnt

    eng = BeanEngine()
    eng._ports = _FakePorts({})
    targeting = eng.target_for(bnt.parse_target("chrome"))
    eng.set_target(True, targeting)

    first = None
    for session in range(2):
        eng.start("true", divert=FakeDivert([]), socket_source=_FakeSocketSource([]))
        watcher = eng._socketwatch
        check(f"session {session}: the map is wired to the target",
              watcher is not None and watcher._on_socket == targeting.note_socket)
        if session == 0:
            first = watcher
        eng.stop()
    check("each session really got its own watcher", first is not eng._socketwatch)


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
