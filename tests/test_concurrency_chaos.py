"""Concurrency chaos: many threads hammering one engine, on purpose.

The suite tests each thread's job in isolation. Nothing tested them TOGETHER,
which is how the off-main-thread Tk call in the target refresher survived (the
GUI fake is single threaded, so it could never see it) and how a stop->start race
could slip back in unnoticed.

The invariants below are the ones whose failure is dangerous rather than merely
annoying:

* **FAIL-OPEN** - the engine must never be ``running`` without a live capture
  thread. WinDivert keeps diverting into a queue nobody drains, so the user
  silently loses their network while the UI says "running".
* **no deadlock** - a hung process keeps the WinDivert handle (and its driver
  file) open until it is killed.
* **no leaked threads** - a stopped session must leave nothing behind.
* **no swallowed worker exception** - a worker that dies quietly is a worker whose
  job is not being done.

Since the SOCKET-layer work the session also runs a FOURTH thread, the
``SocketWatcher``, and the connection log reads its live ``port -> pid`` map from the
CAPTURE thread without taking a lock. That is a concurrency surface of its own, so
two tests at the bottom of this file give the engine a real event source: one drives
its lifecycle across start/stop cycles, the other reads the map from the capture
thread while the watcher mutates it and the watchdog republishes it.

Kept deliberately short (a few seconds); it is a smoke alarm, not a soak test.

A note on the traffic these tests run on. ``SyntheticDivert`` sleeps once per
packet, and on Windows the timer granularity turns that into a ceiling: measured,
it delivers **~1900 packets/s no matter what ``gen_kbps`` says** (2000 kbps and
1 Gbps both land there). Its flow space is just as small - three local ports
against three hard-coded remote addresses, so the connection table stops at
**12 rows** however long the test runs. That is fine for the engine tests below,
which are about threads rather than volume, but it is nowhere near a load: a
model-worker test on that table would sort twelve rows and prove nothing.
``FastDivert`` exists for that one test, and only there.
"""
import threading
import time

from beantester.engine import BeanEngine
from beantester.matchers import KIND_PROCESS, parse_matcher
from beantester.settings import DEFAULT_SETTINGS, apply_settings
from beantester.socketwatch import CLOSE, CONNECT, SocketEvent
from beantester.synthetic import SyntheticDivert, _SyntheticPacket, _SyntheticTCP
from beantester.views import filter_sort_connections, traffic_totals
from fakes import check

STRESS_SECONDS = 3.0
CYCLES = 25

# What makes the model-worker test conclusive rather than decorative: enough
# completed rebuilds to have raced anything, over a table big enough that the sort
# is real work. Asserted as conditions the test WAITS for - see the loop.
MIN_BUILDS = 10
MIN_ROWS = 1000

# Conclusiveness for the socket-map test below: enough connection rows stamped with
# the pid the event stream announces to prove the CAPTURE THREAD really read the live
# map. Like MIN_BUILDS/MIN_ROWS this is a condition the test waits for, never a speed
# assertion - a fixed duration would let machine speed decide whether it proved
# anything.
MIN_STAMPED = 50


def _watch_worker_exceptions():
    """Collect anything a thread raises (threads swallow exceptions by default)."""
    errors = []
    lock = threading.Lock()
    previous = threading.excepthook

    def hook(args):
        with lock:
            errors.append(f"{args.exc_type.__name__}: {args.exc_value}")

    threading.excepthook = hook
    return errors, (lambda: setattr(threading, "excepthook", previous))


def test_start_stop_cycles_never_leave_the_network_impaired():
    """A session that is "running" with a dead capture thread is the dangerous state."""
    errors, restore = _watch_worker_exceptions()
    try:
        violations = []
        for cycle in range(CYCLES):
            engine = BeanEngine()
            engine.start("true", divert=SyntheticDivert(seed=cycle))
            time.sleep(0.02)

            if engine.is_running():
                capture = engine._t_cap
                if capture is None or not capture.is_alive():
                    violations.append(f"cycle {cycle}: running with no capture thread")

            engine.stop()
            if engine.is_running():
                violations.append(f"cycle {cycle}: still running after stop()")
            if engine._divert is not None:
                violations.append(f"cycle {cycle}: the divert was not released")

        check("no fail-open violation across start/stop cycles", not violations,
              f"({violations[:3]})")
        check("no worker thread raised", not errors, f"({errors[:3]})")
    finally:
        restore()


def test_a_second_start_is_refused_instead_of_duplicating_the_workers():
    """Two capture threads on one divert = double-processed packets and corrupt stats."""
    engine = BeanEngine()
    engine.start("true", divert=SyntheticDivert(seed=1))
    try:
        raised = False
        try:
            engine.start("true", divert=SyntheticDivert(seed=2))
        except RuntimeError:
            raised = True
        check("start() while running raises", raised)
    finally:
        engine.stop()


def test_engine_survives_concurrent_writers():
    """apply_settings + live targeting + resets + snapshots, all at once, under traffic."""
    errors, restore = _watch_worker_exceptions()
    problems = []
    engine = BeanEngine()
    engine.start("true", divert=SyntheticDivert(seed=99))
    stop = threading.Event()

    def guard(name, fn):
        def run():
            while not stop.is_set():
                try:
                    fn()
                except Exception as exc:                  # pragma: no cover - the bug
                    problems.append(f"{name}: {type(exc).__name__}: {exc}")
                    return
                time.sleep(0.01)
        return run

    counter = {"i": 0}

    def apply_changes():
        i = counter["i"] = counter["i"] + 1
        s = dict(DEFAULT_SETTINGS)
        s.update(loss=i % 50, latency=i % 200, dup=i % 7, corrupt=i % 5,
                 down=i % 500,
                 dst_port="80,443,!8080" if i % 2 else "",
                 rate_schedule="1:100:50,1:200:100" if i % 3 == 0 else "")
        apply_settings(engine, s, lambda *_: None)

    def retarget():
        matcher = parse_matcher("python,!nonexistent_xyz", KIND_PROCESS)
        engine.set_target(True, engine.target_for(matcher))
        engine.set_target(False)

    def poll():
        engine.stats_snapshot()
        engine.connections_snapshot(limit=50)
        engine.connections_snapshot(limit=None)
        engine.events_snapshot()
        engine.reset_now(0.1)

    threads = [threading.Thread(target=guard(name, fn), name=name, daemon=True)
               for name, fn in (("applier", apply_changes),
                                ("targeter", retarget),
                                ("poller", poll))]
    for t in threads:
        t.start()

    deadline = time.monotonic() + STRESS_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.1)
        if not engine.is_running():
            problems.append(f"the engine stopped by itself (fault={engine.fault})")
            break

    stop.set()
    hung = []
    for t in threads:
        t.join(timeout=10)
        if t.is_alive():
            hung.append(t.name)                            # a join that never returns

    seen = engine.stats_snapshot()["seen"]
    engine.stop()
    restore()

    check("no thread deadlocked", not hung, f"({hung})")
    check("no worker raised", not problems, f"({problems[:3]})")
    check("no unhandled thread exception", not errors, f"({errors[:3]})")
    check("traffic actually flowed while all this happened", seen > 0, f"({seen})")
    check("the engine did not fault", engine.fault is None, f"({engine.fault})")


class FastDivert:
    """A divert that does not pace itself, so the connection table actually grows.

    ``SyntheticDivert`` sleeps per packet and tops out at ~1900 packets/s over 12
    flows (see the module docstring). This one measures **~126 000 packets/s and
    ~125 000 connection rows in three seconds**, which is the regime the model
    worker was built for - a filter+sort big enough to take real time while the
    capture thread keeps writing to the very rows it is reading.

    Those numbers are from a dev machine and are NOT a promise: the same three
    seconds produced 8342 packets on a CI runner under coverage, about fifteen
    times less. Nothing here may turn them into a threshold - see the loop in
    the test, which waits for the table it needs instead of assuming a duration
    produces one.

    It lives here rather than in ``beantester``: production has no use for an
    unthrottled generator, and widening ``SyntheticDivert`` to make a test look
    better would be changing the tool to suit the test.
    """

    def __init__(self, ports=range(3000, 3500)):
        self._ports = list(ports)
        self._i = 0
        self.closed = False

    def open(self):
        pass

    def recv(self):
        if self.closed:
            raise OSError("closed")
        self._i += 1
        i = self._i
        return _SyntheticPacket(b"\x00" * 200, i % 2 == 0,
                                self._ports[i % len(self._ports)], "10.0.0.2",
                                f"93.184.{i % 200}.{i % 251}",
                                tcp=_SyntheticTCP(ack=True))

    def send(self, packet, recalculate_checksum=True):
        pass

    def close(self):
        self.closed = True


def test_the_model_worker_survives_a_live_connection_table():
    """The connections page hands the ENGINE to its worker, not a snapshot of it.

    ``conns.refresh()`` puts ``app.engine`` in the request payload on purpose - a
    snapshot costs ~70 ms at half a million rows, which is most of what moving the
    sort off the UI thread just bought back. So ``_build_model`` calls
    ``connections_snapshot()`` on the WORKER, and that returns
    ``list(self._conns.values())``: the outer list is a copy taken under the lock,
    but every row in it is the live dict the capture thread keeps updating.

    ``model_worker.py`` states in its docstring that this is safe, because it reads
    individual keys (atomic under the GIL) and never iterates a dict the capture
    thread could resize. Nothing tested that claim: all seven ``AsyncModel`` tests
    feed it a fake ``build``, and the engine chaos tests never involve the worker.
    This runs the real pipeline - snapshot, filter, sort, totals, scope - on the
    real ``AsyncModel``, against a real engine under real load, while settings and
    targeting change underneath.

    What it was MEASURED to catch (each mutation applied, test confirmed red):

    * ``connections_snapshot`` handing back the live ``dict.values()`` view instead
      of a copy taken under the lock. That is the tempting optimisation here - the
      copy is O(n) - and it turns every rebuild into a race with the capture thread
      creating a flow.

    What it does NOT catch, measured rather than assumed, so nobody re-derives it:

    * taking the snapshot copy WITHOUT the lock. The window is real but too narrow
      to hit reliably in a few seconds; it stayed green.
    * iterating a row (``dict(c)``, ``**c``, ``.items()``). Harmless TODAY only
      because ``_log_conn`` builds each row with its full key set and never adds
      one afterwards, so a row never changes size. If a row ever gains a key
      conditionally, that stops being true and this test will not warn you.

    The crashlog watch matters more than it looks: ``AsyncModel._run`` catches
    everything, records it and keeps the previous table on screen, so a worker that
    raises on every single build still leaves a green test and a quietly frozen
    table.
    """
    from beantester import crashlog
    from beantester.gui.model_worker import AsyncModel

    errors, restore_hook = _watch_worker_exceptions()
    swallowed = []
    real_note = crashlog.note
    crashlog.note = lambda exc, where="": swallowed.append(f"{where}: {exc!r}")

    engine = BeanEngine()
    apply_settings(engine, DEFAULT_SETTINGS, lambda *_: None)
    engine.start("true", divert=FastDivert())

    queries = ["", "93.184", "443", "tcp", "zzz-matches-nothing"]
    columns = ["bytes", "last", "remote_ip", "remote_port", "local_port",
               "packets", "dur", "idle", "proto"]
    builds = {"n": 0, "rows": 0}

    def build(request):
        """What ConnectionsPage._build_model does, minus the widgets."""
        conns = request["engine"].connections_snapshot(limit=None)
        shown = filter_sort_connections(
            conns, request["query"], request["sort"], request["reverse"],
            now=request["now"], proc_map=request["proc_map"],
            limit=request["limit"])
        totals = traffic_totals(conns, request["query"], request["proc_map"])
        scope_active = request["engine"].targeting_active()
        return {"rows": shown, "total": len(conns), "totals": totals,
                "scope_active": scope_active}

    model = AsyncModel(build, name="conns-model")
    stop = threading.Event()
    problems = []

    def churn():
        """Settings and targeting move under the worker, as they do in the GUI."""
        i = 0
        while not stop.is_set():
            try:
                i += 1
                s = dict(DEFAULT_SETTINGS)
                s.update(loss=i % 40, latency=i % 150, dup=i % 6, down=i % 400,
                         dst_port="80,443,!8080" if i % 2 else "")
                apply_settings(engine, s, lambda *_: None)
                if i % 3 == 0:
                    matcher = parse_matcher("python,!nonexistent_xyz", KIND_PROCESS)
                    engine.set_target(True, engine.target_for(matcher))
                else:
                    engine.set_target(False)
            except Exception as exc:                   # pragma: no cover - the bug
                problems.append(f"churn: {type(exc).__name__}: {exc}")
                return
            time.sleep(0.01)

    churner = threading.Thread(target=churn, name="applier", daemon=True)
    churner.start()

    # The "UI thread": ask, pick up, ask again - exactly the request/poll cycle
    # ConnectionsPage drives from _tick and _poll_soon.
    #
    # It runs for at least STRESS_SECONDS and then KEEPS GOING until the table is
    # big enough for the sort to be real work. A fixed wall-clock budget would let
    # machine speed decide whether the test is conclusive, and that is not
    # hypothetical: the first version asserted "> 10 000 packets seen" after three
    # seconds, a threshold taken from this dev machine, and CI managed 8342 under
    # coverage on a shared runner. Waiting for the CONDITION costs nothing where
    # the machine is fast and stops the test being a speed test where it is not.
    soft_deadline = time.monotonic() + STRESS_SECONDS
    hard_deadline = time.monotonic() + 30.0
    i = 0
    try:
        while time.monotonic() < hard_deadline:
            if (time.monotonic() >= soft_deadline
                    and builds["n"] > MIN_BUILDS and builds["rows"] > MIN_ROWS):
                break
            i += 1
            model.request({"engine": engine, "query": queries[i % len(queries)],
                           "sort": columns[i % len(columns)],
                           "reverse": i % 2 == 0, "limit": (0, 400, 50_000)[i % 3],
                           "now": time.monotonic(), "proc_map": {}})
            result = model.poll()
            if result is not None:
                builds["n"] += 1
                builds["rows"] = max(builds["rows"], result["total"])
                if not isinstance(result["rows"], list):
                    problems.append(f"rows is {type(result['rows'])}")
                if not isinstance(result["totals"], dict):
                    problems.append(f"totals is {type(result['totals'])}")
            time.sleep(0.005)

        # let whatever is in flight land, so busy() means something below
        for _ in range(200):
            if model.poll() is not None:
                builds["n"] += 1
            if not model.busy():
                break
            time.sleep(0.02)
    finally:
        stop.set()
        churner.join(timeout=10)
        seen = engine.stats_snapshot()["seen"]
        engine.stop()
        crashlog.note = real_note
        restore_hook()

    # Diagnostics first: a swallowed build explains every other symptom below.
    check("no build raised into crashlog", not swallowed, f"({swallowed[:3]})")
    check("no thread raised", not errors, f"({errors[:3]})")
    # Then the conclusiveness checks. A green run over twelve rows at 900 packets/s
    # would prove nothing, so the test asserts it ran in the regime it claims.
    # These are CONDITIONS, not speeds: the loop above waits for them rather than
    # hoping a fixed number of seconds produced them. There is no packet-count
    # assertion because the row count already implies one - a thousand distinct
    # flows cannot exist without traffic - and counting packets instead measured
    # how fast the machine was.
    check("the worker was actually exercised", builds["n"] > MIN_BUILDS,
          f"({builds['n']} builds; {seen} packets seen)")
    check("the table was big enough for the sort to mean something",
          builds["rows"] > MIN_ROWS,
          f"({builds['rows']} rows - the point is a real sort; {seen} packets seen)")
    check("nothing went wrong on the driving side", not problems, f"({problems[:3]})")
    check("the worker did not wedge", model.busy() is False)
    check("the engine did not fault", engine.fault is None, f"({engine.fault})")
    leaked = [t.name for t in threading.enumerate() if t.name == "conns-model"]
    check("no model-worker thread outlived the test", not leaked, f"({leaked})")


def test_stopping_joins_every_worker_thread():
    """A leaked worker keeps reading a divert that belongs to the NEXT session."""
    before = {t.name for t in threading.enumerate()}
    engine = BeanEngine()
    engine.start("true", divert=SyntheticDivert(seed=5))
    time.sleep(0.05)
    engine.stop()
    time.sleep(0.3)

    leaked = {t.name for t in threading.enumerate()} - before
    check("no worker thread outlives stop()", not leaked, f"({leaked})")
    check("the thread handles are cleared",
          engine._t_cap is None and engine._t_inj is None and engine._t_wd is None)


# -- the SOCKET-layer watcher, which is the session's fourth thread ------------ #
class _LiveSocketSource:
    """A socket-event source that keeps producing until it is closed.

    The fakes in ``tests/test_socketwatch*.py`` yield a fixed list and then park,
    which is right for asserting a mapping but useless here: chaos needs the event
    stream to still be MOVING while everything else moves. This one cycles through
    its ports for ever, and closes a stale one every few events so the map both grows
    and shrinks underneath whoever is reading it.

    The pacing matters. Without the sleep this saturates a core and starves the very
    threads the test is about, which would make a green run meaningless.
    """

    def __init__(self, ports, pid=4242, delay=0.0005):
        self._ports = list(ports)
        self._pid = pid
        self._delay = delay
        self._closed = threading.Event()

    def __iter__(self):
        i = 0
        while not self._closed.is_set():
            i += 1
            yield SocketEvent(CONNECT, self._pid, self._ports[i % len(self._ports)])
            if i % 4 == 0:
                stale = self._ports[(i - 3) % len(self._ports)]
                yield SocketEvent(CLOSE, self._pid, stale)
            if self._delay:
                time.sleep(self._delay)

    def close(self):
        self._closed.set()


def test_the_socket_watcher_survives_start_stop_cycles():
    """The watcher is the session's FOURTH thread and it holds a WinDivert handle, so
    it has to come and go exactly as capture, inject and watchdog do. Nothing in this
    file used to start the engine with a socket source at all, so the watcher - and
    the poller-vs-watcher table swap behind it - never took part in the chaos."""
    errors, restore = _watch_worker_exceptions()
    try:
        violations = []
        for cycle in range(CYCLES):
            engine = BeanEngine()
            engine.start("true", divert=SyntheticDivert(seed=cycle),
                         socket_source=_LiveSocketSource(range(4000, 4010)))
            time.sleep(0.02)

            if engine.is_running():
                if engine._socketwatch is None:
                    violations.append(f"cycle {cycle}: running without a watcher")
                capture = engine._t_cap
                if capture is None or not capture.is_alive():
                    violations.append(f"cycle {cycle}: running with no capture thread")

            engine.stop()
            if engine._socketwatch is not None:
                violations.append(f"cycle {cycle}: the watcher outlived stop()")
            if engine._divert is not None:
                violations.append(f"cycle {cycle}: the divert was not released")

        check("no fail-open or lifecycle violation across cycles", not violations,
              f"({violations[:3]})")
        check("no worker thread raised", not errors, f"({errors[:3]})")
        # the THREAD is what actually leaks, and stop() only joins for 0.25 s
        time.sleep(0.3)
        leaked = [t.name for t in threading.enumerate() if "socket-watcher" in t.name]
        check("no watcher thread outlived its session", not leaked, f"({leaked})")
    finally:
        restore()


def test_the_live_map_pushes_into_targeting_while_the_resolver_rebuilds():
    """The stability pass for the push path (convention: a new primitive gets one).

    ``note_socket`` runs on the WATCHER thread, ``refresh``/``adopt_new_pids`` on
    the resolver's, and ``__contains__`` on the capture thread - three threads on
    one object, two of them writing. The dangerous outcomes are not "an assertion
    fails" but the quiet ones, so this looks for those:

    * a port announced for a targeted process is LOST because a rebuild that
      started earlier published a set computed without it (the same class of bug
      the socket map's evidence rule exists for),
    * a set that grows without bound - the pending queue is fed by every socket
      event on the machine, and the ruled-out cache by every process that is not
      the target,
    * a deadlock between the two locks, or an exception on any of the threads.

    Short and deliberately brutal: no sleeps in the writers, so they interleave as
    hard as the GIL allows.
    """
    from beantester.targeting import ProcessTargeting

    class _Table:
        """Every pid is chrome, so anything announced SHOULD end up in scope."""

        def __init__(self):
            self.ports = {}
            self.lock = threading.Lock()

        def refresh(self, now=None, force=False):
            return True

        def snapshot(self):
            with self.lock:
                return dict(self.ports)

        def name_of(self, pid, cheap=False):
            return "chrome.exe"

        def ancestors(self, pid, depth=8):
            return []

        def pid_for(self, port):
            with self.lock:
                return self.ports.get(port)

    table = _Table()
    targeting = ProcessTargeting(parse_matcher("chrome", KIND_PROCESS), table=table)
    stop = threading.Event()
    problems, announced = [], []

    def watcher():                       # the live map, announcing new sockets
        port = 20000
        while not stop.is_set():
            port += 1
            pid = 1000 + (port % 7)
            with table.lock:
                table.ports[port] = pid
            try:
                targeting.note_socket(port, pid)
                announced.append(port)
            except Exception as exc:     # pragma: no cover - the bug
                problems.append(f"note_socket: {type(exc).__name__}: {exc}")
                return

    def resolver():                      # the rebuild, and the adoption path
        while not stop.is_set():
            try:
                targeting.adopt_new_pids()
                targeting.refresh()
            except Exception as exc:     # pragma: no cover - the bug
                problems.append(f"resolver: {type(exc).__name__}: {exc}")
                return

    def reader():                        # the packet path
        while not stop.is_set():
            try:
                _ = 19999 in targeting          # the lookup itself is the point
            except Exception as exc:     # pragma: no cover - the bug
                problems.append(f"reader: {type(exc).__name__}: {exc}")
                return

    threads = [threading.Thread(target=fn, daemon=True)
               for fn in (watcher, resolver, reader)]
    for thread in threads:
        thread.start()
    time.sleep(STRESS_SECONDS)
    stop.set()
    for thread in threads:
        thread.join(timeout=10)
    check("no thread was left running", not [t for t in threads if t.is_alive()])
    check("nothing raised on any of the three threads", not problems, f"({problems[:3]})")
    check("the run was conclusive (sockets really were announced)",
          len(announced) > 200, f"({len(announced)} announced)")

    # The last announced port must be in scope: it belongs to a matching process and
    # nothing has closed it. This is the "an older rebuild ate a newer event" check.
    targeting.adopt_new_pids()
    targeting.refresh()
    check("a port announced during the storm is in scope", announced[-1] in targeting,
          f"(port {announced[-1]})")
    # Bounds. Both are cleared by every rebuild, so after one they must be empty,
    # and the pending queue may never exceed its ceiling whatever happens.
    check("the pending queue stayed inside its ceiling",
          len(targeting._pending_pids) <= targeting.MAX_PENDING_PIDS,
          f"({len(targeting._pending_pids)})")
    check("a rebuild clears the ruled-out cache", not targeting._not_ours,
          f"({len(targeting._not_ours)})")
    check("...and the late-port list", not targeting._late_owners,
          f"({len(targeting._late_owners)})")


def test_the_capture_thread_reads_the_live_socket_map_under_churn():
    """The connection log resolves the owning pid from the live SOCKET map, and it
    does so ON THE CAPTURE THREAD, without a lock, while the watcher thread mutates
    that map and the watchdog republishes it wholesale. That is a concurrency surface
    no test covered: ``test_socketwatch.py`` hammers the map with a synthetic reader
    in isolation, and the tests in this file never gave the engine a socket source.

    Why the crashlog watch is the whole test, not decoration: ``engine._pid_for`` and
    ``_process_for`` SWALLOW their exceptions into ``crashlog.once`` by design (a
    broken port table must not kill a session over a display name). So a read that
    started raising under concurrency would leave every assertion below green and the
    only trace would be a crash entry nobody looked at. Patching ``once`` also defeats
    its ``_once_seen`` dedupe, so repeated failures are visible rather than collapsing
    into one.

    What this WOULD catch (mutation-confirmed): a ``SocketWatcher.pid_for`` that
    raises, and an engine that stops consulting the live map at all (rows then never
    get stamped and the conclusiveness check fails).

    What it does NOT catch, so nobody assumes otherwise: putting the LOCK back into
    ``pid_for``. A lock does not raise - it contends, and this test does not measure
    contention. That property has its own guard,
    ``test_socketwatch.py::test_pid_for_takes_no_lock_because_the_capture_thread_calls_it``.
    """
    from beantester import crashlog

    errors, restore_hook = _watch_worker_exceptions()
    swallowed = []
    real_once = crashlog.once
    crashlog.once = lambda subsystem, exc: swallowed.append(f"{subsystem}: {exc!r}")

    pid = 4242
    engine = BeanEngine()
    apply_settings(engine, DEFAULT_SETTINGS, lambda *_: None)
    # the SAME ports FastDivert generates, or pid_for would always miss and a green
    # run would prove nothing at all
    engine.start("true", divert=FastDivert(),
                 socket_source=_LiveSocketSource(range(3000, 3500), pid=pid))
    stop = threading.Event()
    problems = []

    def churn():
        """Settings and targeting move under the capture thread, as in the GUI."""
        i = 0
        while not stop.is_set():
            try:
                i += 1
                s = dict(DEFAULT_SETTINGS)
                s.update(loss=i % 40, latency=i % 150, dup=i % 6, down=i % 400,
                         dst_port="80,443,!8080" if i % 2 else "")
                apply_settings(engine, s, lambda *_: None)
                if i % 3 == 0:
                    matcher = parse_matcher("python,!nonexistent_xyz", KIND_PROCESS)
                    engine.set_target(True, engine.target_for(matcher))
                else:
                    engine.set_target(False)
            except Exception as exc:                   # pragma: no cover - the bug
                problems.append(f"churn: {type(exc).__name__}: {exc}")
                return
            time.sleep(0.01)

    churner = threading.Thread(target=churn, name="applier", daemon=True)
    churner.start()

    # Wait for the CONDITION (rows actually stamped from the map), not for a duration.
    stamped = 0
    soft_deadline = time.monotonic() + STRESS_SECONDS
    hard_deadline = time.monotonic() + 30.0
    try:
        while time.monotonic() < hard_deadline:
            stamped = sum(1 for c in engine.connections_snapshot(limit=None)
                          if c.get("pid") == pid)
            if time.monotonic() >= soft_deadline and stamped > MIN_STAMPED:
                break
            if not engine.is_running():
                problems.append(f"the engine stopped by itself (fault={engine.fault})")
                break
            time.sleep(0.05)
    finally:
        stop.set()
        churner.join(timeout=10)
        seen = engine.stats_snapshot()["seen"]
        engine.stop()
        crashlog.once = real_once
        restore_hook()

    # Diagnostics first: a swallowed read explains anything else that looks odd.
    check("nothing was swallowed into the crash log", not swallowed, f"({swallowed[:3]})")
    check("no thread raised", not errors, f"({errors[:3]})")
    check("nothing went wrong on the driving side", not problems, f"({problems[:3]})")
    # Then conclusiveness: prove the capture thread really read the LIVE map.
    check("connection rows were stamped from the live socket map",
          stamped > MIN_STAMPED,
          f"({stamped} rows carry the event stream's pid; {seen} packets seen)")
    check("the engine did not fault", engine.fault is None, f"({engine.fault})")
    time.sleep(0.3)
    leaked = [t.name for t in threading.enumerate() if "socket-watcher" in t.name]
    check("no watcher thread outlived the test", not leaked, f"({leaked})")
