"""The targeted port set is resolved on its own thread, never on the packet path.

The invariant this file exists for: ``ProcessTargeting.__contains__`` runs inside
``BeanCore.decide()``, on the capture thread, holding the core lock, at up to
150 000 calls a second. It may look things up. It may not go and ASK the operating
system, which is what it used to do - four iphlpapi calls, an O(n) dict copy and a
``psutil.Process()`` per PID, at a steady ~20 Hz whenever a target was set (every
packet from every non-targeted application is a miss, and a miss triggered the
rebuild).

A stalled capture thread is the failure the whole fail-open design exists to
prevent: WinDivert keeps diverting into a queue nobody drains, so the user loses
connectivity while the UI still says "running".
"""
import threading
import time

import bean_network_tester as bnt
from beantester.engine import BeanEngine
from beantester.synthetic import SyntheticDivert
from beantester.target_resolver import TargetResolver
from beantester.targeting import ProcessTargeting
from fakes import check


class _CountingTable:
    """A socket table that records every time somebody makes it look."""

    def __init__(self, ports=None, info=None):
        self.ports = dict(ports or {})
        self._info = dict(info or {})
        self.refreshes = 0
        self.threads = set()

    def refresh(self, now=None, force=False):
        self.refreshes += 1
        self.threads.add(threading.current_thread().name)
        return True

    def snapshot(self):
        return dict(self.ports)

    def name_of(self, pid, allow_bulk=True):
        return self._info.get(pid, ("", None))[0]

    def ancestors(self, pid, depth=8, allow_bulk=True):
        return []

    # the engine's side of the PortTable surface (see _process_for / _pid_for)
    def refresh_if_stale(self, now=None, miss=False):
        return self.refresh(now=now, force=True)

    def process_for_port(self, port, now=None, allow_refresh=True):
        if allow_refresh:
            self.refresh_if_stale(now, miss=True)
        pid = self.ports.get(port)
        return self.name_of(pid) if pid else ""

    def pid_for(self, port):
        return self.ports.get(port)


def _targeting(expr="chrome", table=None):
    table = table if table is not None else _CountingTable(
        ports={5001: 200}, info={200: ("chrome.exe", 1)})
    return ProcessTargeting(bnt.parse_target(expr), table=table), table


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


# -- the resolver itself ------------------------------------------------------ #
def test_a_miss_wakes_the_resolver_and_the_new_port_is_picked_up():
    """The wake-up, not the timer, is what closes the race on a new connection."""
    targeting, table = _targeting()
    targeting.refresh()

    # A long interval on purpose: if the port appears, it is because the MISS woke
    # the resolver, not because a routine tick happened to come round.
    resolver = TargetResolver(interval=5.0)
    resolver.retarget(targeting)
    resolver.start()
    try:
        check("the resolver did its first pass", _wait(lambda: resolver.rebuilds >= 1))
        settled = resolver.rebuilds

        table.ports[5002] = 200                 # the app opens a socket right now
        check("the packet path says 'not mine' for now", 5002 not in targeting)
        check("the miss woke the resolver",
              _wait(lambda: resolver.rebuilds > settled))
        check("and the new port is now targeted", _wait(lambda: 5002 in targeting))
    finally:
        resolver.stop()


def test_stop_joins_the_thread_because_it_holds_os_handles():
    targeting, _ = _targeting()
    resolver = TargetResolver(interval=0.02)
    resolver.retarget(targeting)
    resolver.start()
    check("the resolver is running", _wait(resolver.is_running))

    resolver.stop()
    check("stop() joined, it did not merely signal", not resolver.is_running())


def test_stop_never_waits_for_a_scan_in_flight():
    """STOP is the control this tool may never make slow.

    A resolve is not always cheap. Measured on a normal desktop: **1.7 seconds**
    the first time (25 PIDs own sockets but the process-info cache holds 346 - the
    expensive part is one full ``psutil.process_iter()``), against 1.4 ms once
    warm. An earlier version of this joined with a 2 s timeout, so pressing STOP
    while that scan was in flight blocked for 1.6 s - on the button the user
    reaches for precisely because they have just broken their own network.

    Not joining that is safe: ``stop()`` has already cleared the target and set the
    stop flag, so a straggler finishes at most one more scan into an object nobody
    reads any more, then exits. It is a daemon either way.
    """
    class _SlowTable:
        def __init__(self, delay):
            self.delay = delay
            self.inside = threading.Event()

        def refresh(self, now=None, force=False):
            self.inside.set()
            time.sleep(self.delay)
            return True

        def snapshot(self):
            return {}

        def name_of(self, pid, allow_bulk=True):
            return ""

        def ancestors(self, pid, depth=8, allow_bulk=True):
            return []

    slow = _SlowTable(3.0)               # far longer than any sane join timeout
    targeting = ProcessTargeting(bnt.parse_target("app"), table=slow)
    resolver = TargetResolver(interval=0.02, min_interval=0.0)
    resolver.retarget(targeting)
    resolver.start()
    try:
        check("the resolver is inside a scan", slow.inside.wait(timeout=5))

        t0 = time.monotonic()
        resolver.stop()
        elapsed_ms = (time.monotonic() - t0) * 1000
        check("stop() did not wait for the scan", elapsed_ms < 900,
              f"({elapsed_ms:.0f} ms)")
    finally:
        resolver.stop()
        time.sleep(3.1)                  # let the straggler retire before we leave


def test_stop_does_join_an_idle_resolver():
    """The other half: the common case must still be clean, not merely fast."""
    targeting, _ = _targeting()
    resolver = TargetResolver(interval=5.0)
    resolver.retarget(targeting)
    resolver.start()
    check("the resolver settled", _wait(lambda: resolver.rebuilds >= 1))

    resolver.stop()
    check("an idle resolver is joined, not abandoned", not resolver.is_running())


def test_retargeting_swaps_a_reference_instead_of_churning_threads():
    """Applying settings repeatedly must not start and stop a thread each time."""
    first, _ = _targeting("chrome")
    second, _ = _targeting("firefox")
    resolver = TargetResolver(interval=0.02)
    resolver.start()
    try:
        thread = resolver._thread
        for _ in range(20):
            resolver.retarget(first)
            resolver.retarget(second)
            resolver.retarget(None)
        check("forty retargets, still the same thread", resolver._thread is thread)
        check("and it is still alive", resolver.is_running())
    finally:
        resolver.stop()


def test_an_orphaned_targeting_stops_waking_the_resolver():
    """A target that has been replaced must not keep poking the thread awake."""
    old, _ = _targeting("chrome")
    new, _ = _targeting("firefox")
    resolver = TargetResolver(interval=5.0)
    resolver.retarget(old)
    resolver.retarget(new)

    check("the replaced targeting was detached", old._on_miss is None)
    check("the current one is attached", new._on_miss is not None)


def test_a_failing_refresh_does_not_kill_the_resolver():
    """A socket table that hiccups leaves the port set stale, not the session dead."""
    class _Broken:
        def refresh(self, *a, **k):
            raise RuntimeError("socket table exploded")

        def snapshot(self):
            return {}

        def name_of(self, pid, allow_bulk=True):
            return ""

        def ancestors(self, pid, depth=8, allow_bulk=True):
            return []

    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=_Broken())
    resolver = TargetResolver(interval=0.02)
    resolver.retarget(targeting)
    resolver.start()
    try:
        time.sleep(0.15)
        check("the resolver survived a broken table", resolver.is_running())
    finally:
        resolver.stop()


def test_constant_misses_cannot_turn_into_a_continuous_scan():
    """The floor, and why it is not optional.

    Targeting narrows traffic to ONE application, so every packet from every other
    application is a miss - misses arrive continuously, not occasionally. If a miss
    simply woke the resolver, the wake would be re-armed as fast as it was consumed
    and the socket table would be scanned without pause. Measured while this guard
    was missing: 63 rebuilds a second against a 0.3 s routine tick, bounded only by
    the GIL.
    """
    targeting, _ = _targeting()
    targeting.refresh()

    # routine tick far away, so anything that happens is miss-driven
    resolver = TargetResolver(interval=5.0, min_interval=0.05)
    resolver.retarget(targeting)
    resolver.start()
    try:
        check("the resolver settled", _wait(lambda: resolver.rebuilds >= 1))
        base = resolver.rebuilds

        stop = threading.Event()

        def storm():                      # unrelated traffic: a miss every time
            while not stop.is_set():
                9999 in targeting

        noise = threading.Thread(target=storm, daemon=True)
        noise.start()
        time.sleep(0.6)
        stop.set()
        noise.join(timeout=2)

        did = resolver.rebuilds - base
        # 0.6 s at a 0.05 s floor allows about 12; anything approaching "continuous"
        # is in the dozens-to-hundreds. The margin is deliberately generous - this
        # asserts the ORDER of magnitude, not a stopwatch.
        check("the rebuild rate stayed bounded by the floor", did <= 25,
              f"({did} rebuilds in 0.6 s of constant misses)")
    finally:
        resolver.stop()


# -- dynamic process trees ----------------------------------------------------- #
class _TreeTable:
    """A socket table whose process TREE can grow while the test runs."""

    def __init__(self):
        self.ports = {5001: 100}                    # the parent's own socket
        self.info = {100: ("myapp.exe", 1)}         # pid -> (name, ppid)
        self.refreshes = 0

    def refresh(self, now=None, force=False):
        self.refreshes += 1
        return True

    def snapshot(self):
        return dict(self.ports)

    def name_of(self, pid, allow_bulk=True):
        return self.info.get(pid, ("", None))[0]

    def ancestors(self, pid, depth=8, allow_bulk=True):
        chain, current = [], self.info.get(pid, ("", None))[1]
        while current and len(chain) < depth:
            name, parent = self.info.get(current, ("", None))
            chain.append((current, name))
            current = parent
        return chain


def test_a_child_spawned_mid_session_starts_being_impaired():
    """The targeted app spawns workers while the session runs - that is the norm.

    A browser opens a network-service child; a game launcher spawns a downloader; a
    test harness forks per case. Their sockets belong to the target as much as the
    parent's, and they appear at a moment nobody can schedule for.
    """
    table = _TreeTable()
    targeting = ProcessTargeting(bnt.parse_target("myapp"), table=table)
    targeting.refresh()
    check("only the parent's socket is targeted at first",
          targeting.ports() == {5001}, f"({targeting.ports()})")

    resolver = TargetResolver(interval=5.0, min_interval=0.02)
    resolver.retarget(targeting)
    resolver.start()
    try:
        check("the resolver settled", _wait(lambda: resolver.rebuilds >= 1))

        # the app spawns a worker, which opens its own socket
        table.info[200] = ("myapp-helper.exe", 100)
        table.ports[7001] = 200
        check("the child's FIRST packet slips through (the documented race)",
              7001 not in targeting)
        check("but the child is targeted moments later", _wait(lambda: 7001 in targeting))

        # ...and a grandchild, two levels down
        table.info[300] = ("renderer.exe", 200)
        table.ports[7002] = 300
        9999 in targeting                            # any packet re-arms the miss
        check("a grandchild is targeted too", _wait(lambda: 7002 in targeting))

        check("the whole tree is in scope", targeting.ports() == {5001, 7001, 7002},
              f"({targeting.ports()})")
    finally:
        resolver.stop()


def test_an_excluded_child_is_not_pulled_back_in_by_its_parent():
    """`myapp, !myapp-helper` must keep excluding the helper as it respawns."""
    table = _TreeTable()
    targeting = ProcessTargeting(bnt.parse_target("myapp, !myapp-helper"), table=table)
    resolver = TargetResolver(interval=5.0, min_interval=0.02)
    resolver.retarget(targeting)
    resolver.start()
    try:
        check("the resolver settled", _wait(lambda: resolver.rebuilds >= 1))
        table.info[200] = ("myapp-helper.exe", 100)
        table.ports[7001] = 200
        9999 in targeting
        check("a rebuild happened", _wait(lambda: resolver.rebuilds >= 2))
        time.sleep(0.05)
        check("the excluded child stays out despite its matching parent",
              7001 not in targeting, f"({targeting.ports()})")
        check("the parent itself is still targeted", 5001 in targeting)
    finally:
        resolver.stop()


# -- wired into the engine ----------------------------------------------------- #
def test_the_capture_thread_never_touches_the_socket_table():
    """The whole point, asserted end to end.

    Runs a real session over synthetic traffic with targeting active, then checks
    WHICH threads made the socket table look. The capture thread must not be
    among them.

    The table is injected into BOTH the targeting AND the engine on purpose. An
    earlier version of this test gave the counting table only to the targeting and
    left the engine on ``portmap.default_table()`` - so it watched an object the
    capture thread never used, passed, and missed the fact that ``_log_conn`` ->
    ``_process_for`` -> ``process_for_port`` was still rebuilding the real table
    about sixteen times a second on that very thread. A live run caught what the
    test could not; the test now watches what the engine actually uses.
    """
    table = _CountingTable(ports={5001: 200}, info={200: ("chrome.exe", 1)})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)

    engine = BeanEngine()
    engine._ports = table                       # the table the capture thread reads
    engine.set_target(True, targeting)
    engine.start("true", divert=SyntheticDivert(seed=7))
    try:
        check("traffic flowed", _wait(lambda: engine.stats_snapshot()["seen"] > 200))
        check("the resolver was doing the looking", table.refreshes > 0)
    finally:
        engine.stop()

    capture_threads = {name for name in table.threads if "capture" in name.lower()}
    check("no socket-table access from a capture thread",
          not capture_threads, f"({sorted(table.threads)})")
    check("the resolver thread stopped with the engine",
          not engine.resolver().is_running())


def test_a_target_applied_mid_session_still_gets_a_live_port_set():
    """Start broad, then narrow it down - and the port set must not freeze.

    A regression this rewrite introduced and very nearly shipped: the resolver was
    started only when a target already existed at ``start()``. Press START, watch
    for a while, then type a process name - a completely ordinary workflow - and
    nobody was left keeping the port set fresh. It froze at whatever the first
    resolve produced, so sockets the target opened afterwards were never picked up.
    That is exactly the failure live targeting was built to prevent.

    The resolver's life is the SESSION's now, target or no target; with nothing to
    resolve it blocks on its event and costs nothing.
    """
    table = _CountingTable(ports={5001: 200}, info={200: ("chrome.exe", 1),
                                                    201: ("chrome.exe", 1)})
    engine = BeanEngine()
    engine._ports = table

    engine.start("true", divert=SyntheticDivert(seed=13))       # no target yet
    try:
        check("the resolver runs even with nothing to resolve",
              engine.resolver().is_running())

        # the user narrows it down while the session is running
        targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
        engine.set_target(True, targeting)
        targeting.refresh()                    # what apply_targeting(announce) does
        check("the resolver is still up", engine.resolver().is_running())

        # ...and the app opens a new socket, which is the whole point of a LIVE set
        table.ports[6001] = 201
        check("the new socket misses at first", 6001 not in targeting)
        check("but the resolver picks it up", _wait(lambda: 6001 in targeting))
    finally:
        engine.stop()
    check("and it stops with the session", not engine.resolver().is_running())


def test_stopping_the_engine_leaves_no_resolver_thread_behind():
    before = {t.name for t in threading.enumerate()}
    targeting, _ = _targeting()

    engine = BeanEngine()
    engine.set_target(True, targeting)
    engine.start("true", divert=SyntheticDivert(seed=3))
    time.sleep(0.05)
    engine.stop()
    time.sleep(0.2)

    leaked = {t.name for t in threading.enumerate()} - before
    check("no thread outlives the session", not leaked, f"({leaked})")


def test_repeated_start_stop_cycles_do_not_stack_resolver_threads():
    """The regression this rewrite also removes.

    The GUI used to spawn a refresher thread on every start and never join it, so a
    STOP followed by a START inside its 2 s sleep left the OLD thread looping as
    well - one extra permanent scanner per fast restart cycle.
    """
    before = {t.name for t in threading.enumerate()}
    targeting, _ = _targeting()
    engine = BeanEngine()
    engine.set_target(True, targeting)

    for cycle in range(5):
        engine.start("true", divert=SyntheticDivert(seed=cycle))
        time.sleep(0.02)
        engine.stop()

    time.sleep(0.2)
    leaked = {t.name for t in threading.enumerate()} - before
    check("five start/stop cycles leave no thread behind", not leaked, f"({leaked})")
