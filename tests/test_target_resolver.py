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

    def name_of(self, pid):
        return self._info.get(pid, ("", None))[0]

    def ancestors(self, pid, depth=8):
        return []


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

        def name_of(self, pid):
            return ""

        def ancestors(self, pid, depth=8):
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


# -- wired into the engine ----------------------------------------------------- #
def test_the_capture_thread_never_touches_the_socket_table():
    """The whole point, asserted end to end.

    Runs a real session over synthetic traffic with targeting active, then checks
    WHICH threads made the socket table look. The capture thread must not be
    among them.
    """
    table = _CountingTable(ports={5001: 200}, info={200: ("chrome.exe", 1)})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)

    engine = BeanEngine()
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
