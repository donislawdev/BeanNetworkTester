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
"""
import threading
import time

from beantester.engine import BeanEngine
from beantester.matchers import KIND_PROCESS, parse_matcher
from beantester.settings import DEFAULT_SETTINGS, apply_settings
from beantester.synthetic import SyntheticDivert
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
