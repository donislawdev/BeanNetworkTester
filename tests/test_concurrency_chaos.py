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
from beantester.synthetic import SyntheticDivert, _SyntheticPacket, _SyntheticTCP
from beantester.views import filter_sort_connections, traffic_totals
from fakes import check

STRESS_SECONDS = 3.0
CYCLES = 25


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

    def send(self, packet):
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
    deadline = time.monotonic() + STRESS_SECONDS
    i = 0
    try:
        while time.monotonic() < deadline:
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
    check("the worker was actually exercised", builds["n"] > 10, f"({builds['n']})")
    check("the table was big enough for the sort to mean something",
          builds["rows"] > 1000, f"({builds['rows']} rows - the point is a real sort)")
    check("traffic really flowed while it did", seen > 10_000, f"({seen})")
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
