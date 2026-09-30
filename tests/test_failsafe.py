"""Fail-safe: the app must never leave the user without a working network.

Killing the process is harmless (Windows closes the WinDivert handle). The
dangerous state is a process that is still ALIVE with an open divert and no
working capture thread: WinDivert keeps diverting packets into a queue nobody
drains, the user silently loses connectivity, and the UI still says "running".

These tests pin down the three guarantees:
  * a session stops itself at its ``duration`` deadline,
  * a dead worker thread makes the engine stop (= release the divert) and say so,
  * the GUI survives a broken tick, never calls Tcl from a worker thread, and
    always releases the engine when the window closes,
  * no stop waits for the log, which is the caller's code and can block or raise.
"""
import threading
import time

import pytest

from beantester.engine import _LIVE_ENGINES, BeanEngine, deadline_reached
from beantester.i18n import T
from fakes import FakePacket, check
from gui_harness import run_gui


class ExplodingDivert:
    """Serves a few packets, then fails the way a broken driver would."""

    def __init__(self, packets=3):
        self.packets = packets
        self.i = 0
        self.closed = False
        self.sent = []

    def open(self):
        pass

    def recv(self):
        if self.closed:
            raise OSError("closed")
        if self.i < self.packets:
            self.i += 1
            return FakePacket(size=100, port=1000 + self.i)
        raise OSError("driver went away")

    def send(self, packet, recalculate_checksum=True):
        self.sent.append(packet)

    def close(self):
        self.closed = True


class QuietDivert:
    """Never returns a packet; just blocks until closed."""

    def __init__(self):
        self.closed = False

    def open(self):
        pass

    def recv(self):
        while not self.closed:
            time.sleep(0.005)
        raise OSError("closed")

    def send(self, packet, recalculate_checksum=True):
        pass

    def close(self):
        self.closed = True


def _wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# --- the deadline ----------------------------------------------------------- #


def test_deadline_reached_is_a_pure_function():
    check("deadline: None means no limit", deadline_reached(None, 10 ** 9) is False)
    check("deadline: not yet", deadline_reached(100.0, 99.9) is False)
    check("deadline: exactly on time counts", deadline_reached(100.0, 100.0) is True)
    check("deadline: past", deadline_reached(100.0, 100.1) is True)


def test_engine_stops_itself_when_the_duration_elapses():
    eng = BeanEngine()
    divert = QuietDivert()
    eng.start("test", divert=divert, duration=0.3)
    check("duration: the session is running", eng.is_running() is True)
    # Upper bound has a small tolerance: time_left() is deadline - now, and on a
    # coarse monotonic clock (Windows) the first read can land a hair ABOVE the
    # nominal duration (seen: 0.30000000000001). The point of the check is "there
    # is a positive countdown no larger than the duration", not exact arithmetic.
    check("duration: time_left counts down", 0 < eng.time_left() <= 0.3 + 0.05,
          f"({eng.time_left()})")

    # ``is_running()`` goes False at the TOP of stop(), because ``_capture_loop``
    # runs ``while self._running`` and has to end there. Everything stop()
    # PROMISES - the divert closed, the STOP event logged, the workers joined -
    # happens after it. So waiting on the flag and asserting a post-condition in
    # the next statement is a race, and not a rare one: measured at 10 failures in
    # 30 runs, which is what CI caught. Wait for the promise, not for the flag.
    def stopped_completely():
        kinds = [(e[2], e[3]) for e in eng.events_snapshot()]
        return (not eng.is_running() and divert.closed
                and ("STOP", "events.duration_reached") in kinds)

    check("duration: the engine stops itself", _wait_until(stopped_completely),
          f"(running={eng.is_running()}, closed={divert.closed}, "
          f"events={[(e[2], e[3]) for e in eng.events_snapshot()]})")
    check("duration: the reason is recorded", eng.stop_reason == "duration",
          f"({eng.stop_reason})")
    check("duration: the divert is released", divert.closed is True)
    kinds = [(e[2], e[3]) for e in eng.events_snapshot()]
    check("duration: the event log says why",
          ("STOP", "events.duration_reached") in kinds, f"({kinds})")


def test_stop_releases_the_divert_before_anything_that_can_block():
    """Nothing drains the divert between ``_running = False`` and ``close()``.

    ``_capture_loop`` runs ``while self._running``, so the flag going down IS the
    end of draining: under a real WinDivert, whose ``recv()`` returns immediately
    under traffic, the thread is gone within microseconds. Everything stop() does
    after that leaves the divert OPEN while WinDivert keeps diverting into it -
    and the steps in between can block. ``_resolver.stop()`` joins with a 0.25 s
    timeout and a resolve in flight really uses it (measured in an earlier
    session: STOP took 252 ms with a scan running, against ~100 ms idle).

    Measured with a divert whose ``recv()`` returns immediately and a 200 ms
    resolver join: the divert used to stay open and undrained for 200.06 ms after
    the capture thread had left. It now closes BEFORE that thread finishes
    leaving, which is the point - closing is what ends it.

    Asserted as ORDER rather than as elapsed time, so it cannot flake.
    """
    eng = BeanEngine()
    divert = QuietDivert()
    order = []

    real_close = divert.close

    def close():
        order.append("divert.close")
        real_close()

    divert.close = close

    real_resolver_stop = eng._resolver.stop

    def resolver_stop(*a, **kw):
        order.append("resolver.stop")
        return real_resolver_stop(*a, **kw)

    eng._resolver.stop = resolver_stop

    eng.start("test", divert=divert)
    eng.stop()

    check("stop() closed the divert", "divert.close" in order, f"({order})")
    check("stop() stopped the resolver", "resolver.stop" in order, f"({order})")
    check("the divert is released BEFORE the blocking joins",
          order.index("divert.close") < order.index("resolver.stop"), f"({order})")


def test_no_duration_means_no_deadline():
    eng = BeanEngine()
    eng.start("test", divert=QuietDivert())
    try:
        check("no duration: time_left is None", eng.time_left() is None)
        time.sleep(0.4)
        check("no duration: still running", eng.is_running() is True)
    finally:
        eng.stop()


# --- fail-open -------------------------------------------------------------- #


def test_a_dead_capture_thread_fails_open():
    """Regression: the engine used to keep 'running' with an open divert."""
    eng = BeanEngine()
    divert = ExplodingDivert(packets=3)
    eng.start("test", divert=divert)

    # Wait for the promise, not for the flag - the same fix
    # test_the_engine_stops_itself_after_its_duration already carries. ``_running``
    # is cleared as the SECOND statement of ``_stop_locked`` (deliberately: an
    # early clear stops the watchdog firing a second, racing stop), and the divert
    # is closed several statements later, with the event logged after that. So
    # "not is_running()" is true well before any of the three things asserted
    # below, and a loaded runner can be scheduled away inside that window. It was
    # green ~5/5 locally and red on CI, which is exactly the shape of that gap.
    def stopped_completely():
        kinds = [(e[2], e[3]) for e in eng.events_snapshot()]
        return (not eng.is_running() and divert.closed
                and ("STOP", "events.fault") in kinds)

    check("fail-open: the engine stops on a capture failure and finishes teardown",
          _wait_until(stopped_completely),
          f"(running={eng.is_running()}, closed={divert.closed}, "
          f"events={[(e[2], e[3]) for e in eng.events_snapshot()]})")
    check("fail-open: the divert is closed (network restored)", divert.closed is True)
    check("fail-open: the reason is recorded", eng.stop_reason == "fault",
          f"({eng.stop_reason})")
    check("fail-open: the fault is kept for the report",
          "driver went away" in str(eng.fault), f"({eng.fault})")
    kinds = [(e[2], e[3]) for e in eng.events_snapshot()]
    check("fail-open: the event log says why", ("STOP", "events.fault") in kinds,
          f"({kinds})")


class UnopenableDivert(QuietDivert):
    """A handle that will not open - a rejected filter, a blocked driver, no
    elevation. Its ``recv()`` still "works", exactly like the real thing: a
    pydivert handle that never opened raises ``RuntimeError("WinDivert handle is
    not open")`` from recv, which is a symptom naming nothing."""

    ERROR = OSError("[WinError 87] The parameter is incorrect")

    def open(self):
        raise self.ERROR


def test_a_divert_that_cannot_open_fails_the_start_instead_of_faulting_later():
    """Audit F1. The real cause has to reach the caller, not just crashlog.

    ``open()``'s exception used to be swallowed into a debug crash record, and the
    damage was all in what came next: ``_running`` went True, three workers were
    spawned, and the capture thread's first ``recv()`` failed with a message that
    names nothing. THAT became ``self.fault``, the log, the event log and the repro
    report, while the actual cause - measured with a filter the driver rejects,
    ``OSError [WinError 87]``, or ``[WinError 5]`` when not elevated - never left
    crashlog at ``severity=debug``.

    Both callers already knew what to do and neither could ever be reached:
    ``cli._run_session`` wraps start() to report "cannot start the capture: {e}"
    with exit RUNTIME, and the GUI's ``_finish_start`` shows the start-failed
    dialog with advice - which a non-elevated user needed and never saw. Which
    advice that is now depends on the error (see the test below): it used to be
    "run as Administrator" for every one of them.
    """
    divert = UnopenableDivert()
    engine = BeanEngine()
    raised = None
    try:
        engine.start("test", divert=divert)
    except Exception as exc:
        raised = exc

    check("the start fails instead of appearing to succeed", raised is not None)
    check("and it is the REAL cause, not a symptom from the capture thread",
          raised is UnopenableDivert.ERROR, f"({raised!r})")
    check("the engine is not left believing it is running",
          engine.is_running() is False)
    check("no fault was recorded, because there was no session to fault",
          engine.fault is None, f"({engine.fault!r})")
    check("atexit is not left tracking a session that never began",
          engine not in set(_LIVE_ENGINES))
    check("the dead handle is dropped", engine._divert is None)

    # ...and the engine is reusable, so the GUI's START button works on the next try
    recover = QuietDivert()
    engine.start("test", divert=recover)
    check("a later START is not refused", engine.is_running() is True)
    engine.stop()
    check("and the recovered session releases its divert", recover.closed is True)


class _UnloadingDivert:
    """A divert that answers 433 for its first ``fails`` opens, like a driver that
    another program is still unloading."""

    def __init__(self, fails):
        self.fails = fails
        self.opens = 0
        self.closed = False
        self._closing = threading.Event()

    def open(self):
        self.opens += 1
        if self.opens <= self.fails:
            error = OSError("[WinError 433] The specified device does not exist.")
            error.winerror = 433
            raise error

    def recv(self):
        """Wait to be closed, then raise - the way a real handle behaves.

        🔴 It used to raise 10 ms after the session started, which raced the
        assertion that the session came up: `_capture_loop` catches a recv fault
        and fail-stops, so a main thread descheduled for longer than that (a full
        suite with GUI subprocesses on a loaded machine, seen 2026-08-18) read
        `is_running()` as False and reddened a test about the OPEN path. Nothing
        about the product was wrong. This fake exists to answer 433 on open, so
        that is the only thing it should decide.
        """
        self._closing.wait(5.0)
        raise RuntimeError("stopped")

    def send(self, *_a, **_k):
        pass

    def close(self):
        self.closed = True
        self._closing.set()          # lets the blocked recv() above finish


def test_a_driver_that_is_still_unloading_is_waited_for_not_reported(monkeypatch):
    """A start that arrived 100 ms early should wait, not fail.

    433 means the WinDivert service is mid-unload, which finishes as soon as the
    last program using it lets go. Our own instances no longer do that to each
    other (driver.release_on_exit stands down), but another WinDivert program can,
    and that case is over in milliseconds.
    """
    monkeypatch.setattr(BeanEngine, "OPEN_RETRY_DELAYS_S", (0.0, 0.0))
    lines = []
    engine = BeanEngine(log_fn=lines.append)
    divert = _UnloadingDivert(fails=2)
    engine.start("test", divert=divert)
    check("the start survives a driver that was still unloading",
          engine.is_running() is True)
    check("it took exactly the retries it needed", divert.opens == 3, f"({divert.opens})")
    check("and the pause is explained in the log, not silent",
          any(T("log.driver_still_unloading") == line for line in lines), f"({lines})")
    engine.stop()


def test_a_driver_that_never_comes_back_still_fails_instead_of_hanging(monkeypatch):
    """The retry is a courtesy, not a loop: a session blocked by somebody else's
    RUNNING session lasts as long as that session, and the window must say so."""
    monkeypatch.setattr(BeanEngine, "OPEN_RETRY_DELAYS_S", (0.0, 0.0))
    engine = BeanEngine()
    divert = _UnloadingDivert(fails=99)
    raised = None
    try:
        engine.start("test", divert=divert)
    except Exception as exc:
        raised = exc
    check("the start gives up", raised is not None)
    check("with the REAL error, which is what the dialog explains",
          getattr(raised, "winerror", None) == 433, f"({raised!r})")
    check("after a bounded number of tries", divert.opens == 3, f"({divert.opens})")
    check("and nothing is left running", engine.is_running() is False)


def test_the_start_failure_advice_fits_the_failure_not_every_failure():
    """Reported from an ELEVATED window: "[WinError 433] ... Run as Administrator."

    433 is not a rights problem. It is what a SECOND instance leaves behind when it
    exits: its cleanup stops the shared WinDivert service, the service sits in "stop
    pending" while the first instance still holds a handle, and every open until
    then fails this way (measured 2026-08-04). The dialog appended the elevation
    sentence to every failure, so the one user who had already done the right thing
    was sent to do it again.

    Both directions are asserted, because keeping the advice for the error that
    really means it is half the fix.
    """
    run_gui("""
        import beantester.gui.dialogs as dialogs

        shown = []
        dialogs.show_error = lambda parent, title, message: shown.append(message)

        class OpenFailed(OSError):
            def __init__(self, code, text):
                super().__init__(text)
                self.winerror = code
                self._text = text
            def __str__(self):
                return self._text

        busy = OpenFailed(433, "[WinError 433] The specified device does not exist.")
        app._is_admin = True
        app._finish_start(busy)
        assert shown, "a failed start has to tell the user something"
        assert "WinError 433" in shown[-1], shown[-1]
        assert bnt.T("dialogs.driver_busy") in shown[-1], shown[-1]
        assert bnt.T("dialogs.run_as_admin") not in shown[-1], (
            "an elevated window was told to run as Administrator: " + shown[-1])

        # the failure that IS about rights keeps the sentence that helps
        app._is_admin = False
        app._finish_start(OpenFailed(5, "[WinError 5] Access is denied."))
        assert bnt.T("dialogs.run_as_admin") in shown[-1], shown[-1]

        # ...and the button comes back either way, or the window is stuck
        assert app.running is False
    """)


def test_the_start_banner_is_logged_before_a_worker_can_fault():
    """Audit F6: the live log used to read BACKWARDS on an early fault.

    The "Start. Filter: ..." line sat BELOW the thread spawn, so a session that
    died in its first milliseconds printed the recv error and the fault ABOVE its
    own start line. Measured against the real driver with a rejected filter:

        recv error: WinDivert handle is not open
        engine fault: ... - the session was stopped, the network is normal
        Start. Filter: this is not a valid filter  (seed=...)
        Stop.

    The event log was always ordered correctly (a worker-initiated stop blocks on
    _stop_lock until start() returns), so only the log a tester actually watches
    was lying.
    """
    lines = []
    engine = BeanEngine(log_fn=lines.append)
    engine.start("test", divert=ExplodingDivert(packets=0))   # faults on first recv
    deadline = time.time() + 5
    while time.time() < deadline and engine.is_running():
        time.sleep(0.01)
    engine.stop()

    # Matched on text the TRANSLATION cannot move: the seed the engine prints and
    # the exception message it interpolates. An earlier version looked for the word
    # "fault" and passed or failed by the machine's UI language - green on an
    # English CI runner, red on this Polish one, which is a test reporting the
    # locale rather than the code.
    def first(needle):
        return next((i for i, ln in enumerate(lines) if needle in ln), None)

    start_at, fault_at = first("seed="), first("driver went away")
    check("the session announced itself", start_at is not None, f"({lines})")
    check("the failure was reported", fault_at is not None, f"({lines})")
    check("and the start line comes FIRST", start_at < fault_at,
          f"(start at {start_at}, fault at {fault_at}: {lines})")


def test_a_failed_start_never_leaves_an_open_divert(monkeypatch):
    """Regression (F1): start() was not atomic.

    ``_running`` went True and the divert was opened BEFORE the worker threads were
    spawned, and the engine was added to ``_LIVE_ENGINES`` only AFTER. So a failing
    ``Thread.start()`` (out of threads/memory - most likely under the load this tool
    is pointed at) left a 'running' engine with an open divert that nothing drained
    and that atexit could not even see, and every later START was refused forever.
    """
    import threading

    real_start = threading.Thread.start
    calls = {"n": 0}

    def flaky_start(self, *a, **k):
        # let the resolver thread come up, then fail like a machine out of threads
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("can't start new thread")
        return real_start(self, *a, **k)

    eng = BeanEngine()
    divert = QuietDivert()
    monkeypatch.setattr(threading.Thread, "start", flaky_start)
    try:
        eng.start("test", divert=divert)
    except RuntimeError as exc:
        raised = str(exc)
    else:
        raised = None
    monkeypatch.undo()

    check("failed start: the error propagates to the caller",
          raised == "can't start new thread", f"({raised})")
    check("failed start: the engine is NOT left running", eng.is_running() is False)
    check("failed start: the divert is closed (network restored)",
          divert.closed is True)
    check("failed start: atexit is not left tracking a half-started engine",
          eng not in set(_LIVE_ENGINES))
    # the whole point: START works again instead of being wedged on "already running"
    recover = QuietDivert()
    eng.start("test", divert=recover)
    check("failed start: a later START is not refused", eng.is_running() is True)
    eng.stop()
    check("failed start: the recovered session releases its divert too",
          recover.closed is True)


class _IdleSocketSource:
    """A socket-event source that announces nothing until it is closed."""

    def __init__(self):
        self.closed = threading.Event()

    def __iter__(self):
        self.closed.wait(10)
        return iter(())

    def close(self):
        self.closed.set()


def test_the_slow_part_of_a_start_runs_before_the_handle_opens():
    """External review P1-5: from the open on, WinDivert queues every packet the
    filter matches for a capture thread that does not exist yet. The socket watcher
    and the first target resolve ran in that gap - 35-56 ms measured (elevated,
    cold), most of it the resolve. Before the open they hold nothing: the traffic
    still flows untouched. The resolve still comes before the first packet, which
    is what it is for, and still after the watcher, whose map it reads."""
    from beantester.matchers import KIND_PROCESS, parse_matcher
    order = []
    eng = BeanEngine()
    targeting = eng.target_for(parse_matcher("no-such-process.exe", KIND_PROCESS, "target"))
    real_refresh = targeting.refresh

    def refresh(*a, **k):
        order.append("target resolved")
        return real_refresh(*a, **k)

    targeting.refresh = refresh
    eng.set_target(True, targeting)

    class Driver(QuietDivert):
        def open(self):
            order.append("handle opened")

        def recv(self):
            order.append("capture reading")
            return super().recv()

    def socket_source():
        order.append("socket watcher opened")
        return _IdleSocketSource()

    eng.start("test", divert=Driver(), socket_source=socket_source)
    try:
        _wait_until(lambda: "capture reading" in order)
        first = list(dict.fromkeys(order))          # first time each step happened
    finally:
        eng.stop()
    check("start order: watcher, target, handle, capture",
          first == ["socket watcher opened", "target resolved", "handle opened",
                    "capture reading"], f"({order})")


def test_a_handle_that_will_not_open_leaves_no_socket_watcher_behind(monkeypatch):
    """The other side of opening the socket watcher first (P1-5): when the NETWORK
    handle then refuses, the watcher's own WinDivert handle and thread go with the
    failed start instead of sniffing on with nothing to stop them."""
    monkeypatch.setattr(BeanEngine, "OPEN_RETRY_DELAYS_S", (0.0, 0.0))
    source = _IdleSocketSource()
    eng = BeanEngine()
    raised = None
    try:
        eng.start("test", divert=_UnloadingDivert(fails=99), socket_source=lambda: source)
    except OSError as exc:
        raised = exc
    check("the start fails with the handle's own error",
          getattr(raised, "winerror", None) == 433, f"({raised!r})")
    check("the socket watcher's handle is closed with it", source.closed.is_set())
    check("and the engine keeps no watcher", eng._socketwatch is None)
    check("and nothing runs", eng.is_running() is False)


def test_a_socket_handle_failure_is_recorded_only_for_a_start_that_opened(monkeypatch):
    """The SOCKET handle opens first now (P1-5), so a start without the rights or
    the driver fails there before it fails at the NETWORK handle - the same cause
    twice. The start's own error reaches the user (dialog, CLI line); a crash
    record of the SOCKET half would be noise (D-35). One that failed ALONE is
    recorded: targeting then runs on the slower poller all session."""
    monkeypatch.setattr(BeanEngine, "OPEN_RETRY_DELAYS_S", (0.0, 0.0))
    recorded = []
    monkeypatch.setattr("beantester.crashlog.once",
                        lambda subsystem, exc: recorded.append(subsystem))

    def refuse():
        raise OSError("[WinError 5] Access is denied.")

    eng = BeanEngine()
    with pytest.raises(OSError):
        eng.start("test", divert=_UnloadingDivert(fails=99), socket_source=refuse)
    check("a start that failed anyway leaves no record of the same cause",
          "engine.socketwatch.start" not in recorded, f"({recorded})")
    eng.start("test", divert=QuietDivert(), socket_source=refuse)
    eng.stop()
    check("a socket handle that failed alone is recorded, once",
          recorded.count("engine.socketwatch.start") == 1, f"({recorded})")


def test_a_socket_watcher_that_cannot_start_its_thread_closes_its_handle(monkeypatch):
    """The SOCKET handle opens before the watcher's thread starts, so a thread that
    will not start (out of threads - the load this tool is pointed at) left an open
    handle behind a watcher the engine had already let go of. It is closed now,
    and the session carries on without the live map, as for any SOCKET failure."""
    source = _IdleSocketSource()
    real_start = threading.Thread.start

    def start(thread, *a, **k):
        if thread.name == "bean-socket-watcher":
            raise RuntimeError("can't start new thread")
        return real_start(thread, *a, **k)

    monkeypatch.setattr(threading.Thread, "start", start)
    eng = BeanEngine()
    eng.start("test", divert=QuietDivert(), socket_source=lambda: source)
    try:
        closed, watcher, running = source.closed.is_set(), eng._socketwatch, eng.is_running()
    finally:
        monkeypatch.undo()
        eng.stop()
    check("the socket handle is closed", closed)
    check("the engine keeps no watcher", watcher is None)
    check("and the session runs on without it", running is True)


def test_a_socket_handle_waits_for_an_unloading_driver_too(monkeypatch):
    """The SOCKET handle opens first now (P1-5), so it is the one that meets a
    driver another program is still unloading. Without the wait the NETWORK handle
    has always had, it fell back to the poller for the whole session while the
    NETWORK handle, a moment later, found the driver ready."""
    monkeypatch.setattr(BeanEngine, "OPEN_RETRY_DELAYS_S", (0.0, 0.0))
    attempts = []

    def unloading_then_ready():
        attempts.append(1)
        if len(attempts) == 1:
            error = OSError("[WinError 433] The specified device does not exist.")
            error.winerror = 433
            raise error
        return _IdleSocketSource()

    lines = []
    eng = BeanEngine(log_fn=lines.append)
    eng.start("test", divert=QuietDivert(), socket_source=unloading_then_ready)
    try:
        watcher = eng._socketwatch
        live = watcher is not None and watcher.is_running()
    finally:
        eng.stop()
    check("the socket watcher waited for the driver and runs", live, f"({attempts})")
    check("after exactly the one retry it needed", len(attempts) == 2, f"({attempts})")
    check("and the pause is explained in the log",
          T("log.driver_still_unloading") in lines, f"({lines})")


def test_a_failure_right_after_the_handle_opens_still_closes_it(monkeypatch):
    """Between the open and the workers, a dozen steps sat outside the try that
    stops a failed start: an exception there - or a Ctrl+C, which lands on the
    CLI's main thread, the one running start() - left the session "running" with
    an open handle nothing drained and atexit could not see (P1-5, found in the
    analysis of the start order)."""
    def refuse():
        raise RuntimeError("no timer for this session")

    monkeypatch.setattr("beantester.winenv.request_fine_timers", refuse)
    divert = QuietDivert()
    eng = BeanEngine()
    try:
        with pytest.raises(RuntimeError):
            eng.start("test", divert=divert)
        closed, running = divert.closed, eng.is_running()
        tracked = eng in set(_LIVE_ENGINES)
    finally:
        monkeypatch.undo()
        eng.stop()
    check("the handle is closed (network restored)", closed is True)
    check("the session is not left running", running is False)
    check("and atexit is not left tracking it", tracked is False)


def _count_timer_calls(monkeypatch, granted=True):
    """Replace the winenv timer calls with counters; returns the call log."""
    from beantester import engine as engine_mod

    calls = []
    monkeypatch.setattr(engine_mod.winenv, "request_fine_timers",
                        lambda *a, **k: calls.append("request") or granted)
    monkeypatch.setattr(engine_mod.winenv, "release_fine_timers",
                        lambda *a, **k: calls.append("release") or True)
    return calls


def test_the_fine_timer_request_is_balanced_on_every_session_path(monkeypatch):
    """A granted fine timer tick MUST be given back - clean stop, double stop and
    failed start alike.

    ``timeBeginPeriod`` is refcounted BY THE OS, per process, and an unbalanced pair
    is invisible from inside the program: it just means this process keeps a finer
    system timer for the rest of its life. Nothing would ever report that, which is
    why the balance gets a test rather than a comment.
    """
    import threading

    calls = _count_timer_calls(monkeypatch)
    eng = BeanEngine()
    eng.start("test", divert=QuietDivert())
    eng.stop()
    eng.stop()                          # idempotent: the second stop releases nothing
    check("fine timers: one request and one release per session",
          calls == ["request", "release"], f"({calls})")

    eng.start("test", divert=QuietDivert())
    eng.stop()
    check("fine timers: the next session is balanced too",
          calls == ["request", "release"] * 2, f"({calls})")

    # ...and a start that blows up half way must not walk off with the tick either
    real_start = threading.Thread.start
    attempts = {"n": 0}

    def flaky_start(self, *a, **k):
        attempts["n"] += 1
        if attempts["n"] > 1:
            raise RuntimeError("can't start new thread")
        return real_start(self, *a, **k)

    monkeypatch.setattr(threading.Thread, "start", flaky_start)
    try:
        eng.start("test", divert=QuietDivert())
    except RuntimeError:
        pass
    monkeypatch.undo()
    check("fine timers: a failed start gives the tick back",
          calls == ["request", "release"] * 3, f"({calls})")


def test_a_refused_fine_timer_request_is_never_released(monkeypatch):
    """Off Windows (or with winmm missing) the request is refused - and then there
    is nothing to give back. Releasing one we never took decrements a refcount that
    belongs to somebody else, which would cancel THEIR fine timer."""
    calls = _count_timer_calls(monkeypatch, granted=False)
    eng = BeanEngine()
    eng.start("test", divert=QuietDivert())
    eng.stop()
    check("fine timers: a refused request is not released",
          calls == ["request"], f"({calls})")


def test_the_background_timer_opt_out_is_asked_for_once_per_process(monkeypatch):
    """The opt-out is a process-wide POLICY, not a per-session request.

    It is also the part that makes the fine timer survive: without it Windows 11
    keeps granting ``timeBeginPeriod`` while quietly ceasing to honour it once the
    process is no longer in front - which is where this tool lives, since the
    tester starts a session and switches to the application under test. Measured
    before it was added: the third and every later session in one process was back
    to a 15.6 ms tick with a perfectly balanced request/release log.
    """
    from beantester import winenv

    monkeypatch.setattr(winenv, "_TIMER_OPT_OUT", [None])
    winenv._allow_fine_timers_in_background()
    winenv._TIMER_OPT_OUT[0] = "already answered"
    again = winenv._allow_fine_timers_in_background()
    check("timer opt-out: the answer is memoised, not asked for again",
          again == "already answered", f"({again!r})")


def test_the_fine_timer_calls_are_safe_to_make_anywhere():
    """They run on every session start/stop, on every platform, so they may never
    raise - and off Windows there is nothing to ask for."""
    from beantester import winenv

    granted = winenv.request_fine_timers()
    if granted:
        winenv.release_fine_timers()        # never leave the test run holding one
    if not winenv.is_windows():
        check("fine timers: a no-op off Windows", granted is False)
    check("fine timers: releasing without holding does not raise",
          winenv.release_fine_timers() in (True, False))


# A value nothing else in this process would choose: not CPython's 5 ms default
# and not winenv.THREAD_SWITCH_S. See _switch_baseline for why it must be neither.
_SWITCH_SENTINEL = 0.004
_SWITCH_ORIGINAL = []


def _switch_baseline():
    """Put the process at a KNOWN interval with no holders, and return it.

    Two ways these tests can quietly stop testing anything, both hit during the
    mutation run for this change:

    1. They share one process-global holder count. A test that leaks a holder
       leaves the next one's ``start()`` looking at a non-zero count, so it
       changes nothing, restores nothing, and passes.
    2. Asserting "the interval came back to whatever it was when I started" is a
       TAUTOLOGY once anything has leaked - and with the release deleted, every
       engine session in this file leaks, so by the time these tests run the
       process is already sitting at the shortened value and "restored" is true
       by accident. The deleted-release mutant survived exactly this way.

    So the baseline is a value chosen HERE, distinct from both the default and
    the one the engine installs, and the assertions compare against it.
    """
    import sys
    from beantester import winenv

    if not _SWITCH_ORIGINAL:
        _SWITCH_ORIGINAL.append(sys.getswitchinterval())
    winenv._SWITCH_STATE[0] = None
    winenv._SWITCH_STATE[1] = 0
    sys.setswitchinterval(_SWITCH_SENTINEL)
    return _SWITCH_SENTINEL


def _switch_restore():
    """Leave the process as this file found it, holders included."""
    import sys
    from beantester import winenv

    winenv._SWITCH_STATE[0] = None
    winenv._SWITCH_STATE[1] = 0
    if _SWITCH_ORIGINAL:
        sys.setswitchinterval(_SWITCH_ORIGINAL[0])


def test_the_shortened_switch_interval_is_in_force_only_while_a_session_runs():
    """The engine shortens CPython's thread-switch interval for the SESSION.

    Measured (2026-07-29, real WinDivert, paired inside one session, 24 pairs of
    24): a median 1.33-1.36x more packets a second, because the two hot threads
    hand every packet to each other and CPython lets a thread waiting for the
    interpreter lock sleep up to 5 ms before it insists.

    Asserted on the VALUE rather than on a call log: a call log stays green if
    the pair is wired to the wrong knob, and this number is the only thing the
    rest of the process can actually feel.
    """
    import sys
    from beantester import winenv

    before = _switch_baseline()
    eng = BeanEngine()
    try:
        eng.start("test", divert=QuietDivert())
        during = sys.getswitchinterval()
        eng.stop()
        after = sys.getswitchinterval()          # read BEFORE the cleanup below
    finally:
        _switch_restore()
    check("switch interval: shortened while the session runs",
          during == winenv.THREAD_SWITCH_S, f"({during})")
    check("switch interval: the session gives it back",
          after == before, f"({after})")


def test_the_switch_interval_is_restored_on_every_session_path():
    """Clean stop, double stop and a start that blows up half way - all give it
    back. An unbalanced pair is invisible from inside the program: the process
    simply keeps somebody else's interval for the rest of its life, and nothing
    would ever report it. Same hazard as the fine timer tick, minus the OS
    refcount that would at least catch it there.
    """
    import sys
    import threading

    before = _switch_baseline()
    eng = BeanEngine()
    try:
        eng.start("test", divert=QuietDivert())
        eng.stop()
        eng.stop()                       # idempotent: the second stop gives nothing back
        check("switch interval: restored after a clean (and doubled) stop",
              sys.getswitchinterval() == before, f"({sys.getswitchinterval()})")

        real_start = threading.Thread.start
        attempts = {"n": 0}

        def flaky_start(self, *a, **k):
            attempts["n"] += 1
            if attempts["n"] > 1:
                raise RuntimeError("can't start new thread")
            return real_start(self, *a, **k)

        threading.Thread.start = flaky_start
        try:
            eng.start("test", divert=QuietDivert())
        except RuntimeError:
            pass
        finally:
            threading.Thread.start = real_start
        check("switch interval: a failed start gives it back too",
              sys.getswitchinterval() == before, f"({sys.getswitchinterval()})")
    finally:
        _switch_restore()


def test_two_overlapping_sessions_do_not_restore_each_other_s_interval():
    """Two engines in one process is a real shape here - the tests do it, and
    nothing stops a caller. The second one to stop must restore the value that
    was in force before the FIRST one asked, and the first one to stop must not
    pull the shorter interval out from under a session that is still running.
    """
    import sys
    from beantester import winenv

    before = _switch_baseline()
    a, b = BeanEngine(), BeanEngine()
    try:
        a.start("test", divert=QuietDivert())
        b.start("test", divert=QuietDivert())
        b.stop()
        still_short = sys.getswitchinterval()
        a.stop()
        after = sys.getswitchinterval()          # read BEFORE the cleanup below
    finally:
        _switch_restore()
    check("switch interval: one session stopping leaves the other one's in place",
          still_short == winenv.THREAD_SWITCH_S, f"({still_short})")
    check("switch interval: the last one out restores the original",
          after == before, f"({after})")


def test_releasing_a_switch_interval_nobody_took_changes_nothing():
    """It runs on every stop, on every platform, so it may never raise - and a
    release without a matching request must not install a saved value from some
    earlier, already balanced session."""
    import sys
    from beantester import winenv

    before = _switch_baseline()
    try:
        first = winenv.release_fast_thread_switch()
        check("switch interval: releasing without holding is refused, not raised",
              first is False, f"({first!r})")
        check("switch interval: and it leaves the value alone",
              sys.getswitchinterval() == before, f"({sys.getswitchinterval()})")
    finally:
        _switch_restore()


def test_stop_is_idempotent_and_keeps_the_first_reason():
    eng = BeanEngine()
    eng.start("test", divert=QuietDivert())
    eng.stop()
    check("stop: reason defaults to the user", eng.stop_reason == "user")
    eng.stop()                       # a second stop must be a no-op, not a crash
    check("stop: calling it twice is safe", eng.is_running() is False)


def test_a_running_engine_is_registered_for_the_exit_hook():
    """An engine left running at interpreter exit must still release the divert."""
    eng = BeanEngine()
    divert = QuietDivert()
    eng.start("test", divert=divert)
    check("atexit: a running engine is tracked", eng in set(_LIVE_ENGINES))
    eng.stop()
    check("atexit: a stopped engine is forgotten", eng not in set(_LIVE_ENGINES))
    check("atexit: the divert was released", divert.closed is True)


def test_a_worker_stop_never_blocks_on_a_held_stop_lock():
    """Regression (F2): STOP took 2.09 s when it raced the duration deadline.

    An external stop() holds ``_stop_lock`` AND joins the worker threads (2 s timeout).
    The watchdog firing the deadline - and ``_fail_stop`` on a dead worker - used to call
    the same blocking ``stop()``: it waited for the lock the user's stop was holding,
    while the user's stop waited to join the watchdog, so STOP hung for the full join
    timeout. They now go through ``_worker_stop``, which takes the lock non-blockingly
    and bows out when it cannot, so the join completes at once.

    Asserted structurally (does the worker stop return while the lock is held?), not as
    elapsed wall-clock, so it cannot flake - exactly like
    test_stop_releases_the_divert_before_anything_that_can_block.
    """
    import threading

    eng = BeanEngine()
    eng.start("test", divert=QuietDivert())
    # Stand in for an external stop() already in flight: hold _stop_lock the way it does.
    eng._stop_lock.acquire()
    try:
        returned = threading.Event()

        def worker_stop():
            eng._worker_stop(reason="duration")   # must NOT block on the held lock
            returned.set()

        threading.Thread(target=worker_stop, daemon=True).start()
        check("F2: a worker-initiated stop does not block on a held _stop_lock",
              returned.wait(timeout=2.0),
              "(_worker_stop blocked - STOP would hang for the whole join timeout)")
        # it bowed out WITHOUT stopping, because the (simulated) external stop owns the
        # teardown - the fail-open close is that stop's job, not a second racing one
        check("F2: while another stop holds the lock, the worker stop is a no-op",
              eng.is_running() is True, f"(running={eng.is_running()})")
    finally:
        eng._stop_lock.release()
    eng.stop()
    check("F2: the ordinary stop still tears the session down", eng.is_running() is False)


def test_a_capture_fault_racing_an_external_stop_does_not_wait_for_it():
    """F13: the CAPTURE thread waits for a start, never for another stop.

    A recv() that fails for its own reason a moment before the user presses STOP
    used to block on ``_stop_lock`` while that stop was joining this very thread
    with a 2.0 s timeout. No deadlock, but STOP took the whole timeout. The
    docstring said it "cannot deadlock against an external STOP", which is true
    only when the fault IS that stop closing the divert.

    Structural, not wall-clock, so it cannot flake: hold the lock the way an
    external stop does, with ``_running`` already cleared as ``_stop_locked``
    clears it, and assert the fault path returns instead of waiting.
    """
    import threading

    eng = BeanEngine()
    eng.start("test", divert=QuietDivert())
    eng._stop_lock.acquire()
    try:
        # exactly the state an external stop is in while it joins the workers
        eng._running = False
        returned = threading.Event()

        def capture_fault():
            eng._fault_stop_blocking()
            returned.set()

        threading.Thread(target=capture_fault, daemon=True).start()
        check("F13: the capture fault does not wait on a stop that owns the teardown",
              returned.wait(timeout=2.0),
              "(it blocked - STOP would take the whole 2 s join timeout)")
    finally:
        eng._running = True
        eng._stop_lock.release()
    eng.stop()
    check("F13: the session still tears down normally", eng.is_running() is False)


def test_a_capture_fault_still_waits_for_a_start_that_holds_the_lock():
    """The other half: while ``start()`` holds the lock the session IS still
    running, and that is the case the blocking path exists for - a divert failing
    on its very first reads. Bowing out there would hand the teardown to the
    watchdog a tick later for nothing."""
    import threading

    eng = BeanEngine()
    eng.start("test", divert=QuietDivert())
    eng._stop_lock.acquire()            # stand in for start() still finishing
    try:
        returned = threading.Event()

        def capture_fault():
            eng._fault_stop_blocking()
            returned.set()

        threading.Thread(target=capture_fault, daemon=True).start()
        check("F13: it does NOT bow out while a start holds the lock",
              not returned.wait(timeout=0.4),
              "(it gave up on a start - the real fault would be lost to the watchdog)")
        check("F13: and the session is still up while it waits",
              eng.is_running() is True)
    finally:
        eng._stop_lock.release()
    check("F13: once the lock is free it completes the fail-open stop",
          _wait_until(lambda: not eng.is_running()), f"(running={eng.is_running()})")


def test_the_first_fault_is_the_one_kept_for_the_report():
    """The watchdog's "worker thread died unexpectedly" is a SYMPTOM of the real
    error. When both land, the cause has to survive - it is the only half of the
    report worth reading."""
    import threading

    eng = BeanEngine()
    eng.start("test", divert=QuietDivert())
    # Both faults have to land while the engine is STILL RUNNING - that is the only
    # state in which the second one reaches `self.fault` at all. So the lock is held
    # here, which makes `_worker_stop` bow out and leaves the session up.
    #
    # From ANOTHER thread, deliberately: `_stop_lock` is an RLock, so calling this
    # on the thread holding it re-enters, the stop completes, `_running` goes False
    # and the second fault returns at the guard - the test then passes while
    # guarding nothing. Which is what it did, until the mutation caught the TEST.
    eng._stop_lock.acquire()
    try:
        def two_faults():
            eng._fail_stop(RuntimeError("the driver went away"), blocking=False)
            eng._fail_stop(RuntimeError("worker thread Thread-1 died unexpectedly"),
                           blocking=False)

        t = threading.Thread(target=two_faults, daemon=True)
        t.start()
        t.join(timeout=5.0)
        check("fault: the faulting thread did not block", not t.is_alive())
        check("fault: the session is still up, so both faults were recorded",
              eng.is_running() is True)
        check("fault: the cause survives the symptom",
              "driver went away" in str(eng.fault), f"({eng.fault})")
    finally:
        eng._stop_lock.release()
    eng.stop()


# --- the GUI ---------------------------------------------------------------- #


def test_a_broken_tick_never_kills_the_refresh_loop():
    """Regression: one exception used to stop every refresh for the whole session."""
    run_gui("""
        scheduled = []
        root.after = lambda ms, fn=None: scheduled.append(ms)

        page = app.pages["control"]
        def boom():
            raise RuntimeError("page exploded")
        page.refresh = boom
        app.select_page("control")

        app._tick()                                  # must not raise
        assert scheduled, "the tick did not reschedule itself after an exception"
        assert any("page exploded" in line for line in app._log_lines), app._log_lines

        page.refresh = lambda: None
        app._tick()
        assert len(scheduled) == 2, scheduled          # the loop is alive
    """)


def test_the_ui_notices_when_the_engine_stops_itself():
    """Duration reached / worker fault: the chrome must stop saying 'running'."""
    run_gui("""
        app.running = True            # the engine is NOT running (never started)
        app._sync_running_ui()
        assert app.btn_start.kw["text"] == bnt.T("buttons.stop")

        app._tick()

        assert app.running is False, "the UI kept claiming the session is live"
        assert app.btn_start.kw["text"] == bnt.T("buttons.start")
        assert app.status.kw["text"] == bnt.T("app.status.stopped")
        assert app.filter_cb.kw.get("state") == "readonly"    # unlocked again
    """)


def test_the_target_verdict_never_reads_the_tk_variable():
    """``_refresh_target_verdict`` works off the engine and the applied target.

    It never touches the tk variable: that is what makes it safe to call from
    anywhere, and since 2026-09-28 it is also the rule - the field reaches the
    engine only through "Apply changes", so the verdict has no business reading it.
    """
    run_gui("""
        from beantester.settings import apply_targeting

        apply_targeting(app.engine, "chrome.exe", announce=False)
        app._applied_target = "chrome.exe"

        # from now on the tk variable explodes if anything reads or writes it
        class Exploding:
            def get(self):
                raise AssertionError("the verdict read the tk variable")
            def set(self, *a):
                raise AssertionError("the verdict wrote the tk variable")

        app.vars["target"] = Exploding()
        app._refresh_target_verdict()
    """)


def test_the_gui_starts_the_session_with_its_duration():
    run_gui("""
        started = {}
        app.engine.start = (lambda filt, divert=None, duration=0, **kw:
                            started.update(filter=filt, duration=duration))
        app.vars["duration"].set("12")
        app._start()
        app._settle_transition()       # start now runs off the UI thread (chunk B)

        assert app.running is True
        assert started["duration"] == 12, started
    """)


def test_start_and_stop_run_off_the_ui_thread():
    """A slow WinDivert driver load must not freeze the window (chunk B).

    If _start ran engine.start() on the UI thread, the call below would block for
    the whole sleep; instead it returns at once. The button just keeps showing
    START/STOP (no transitional label) and flips once the worker finishes.
    """
    run_gui("""
        import time
        app.engine.start = lambda filt, divert=None, duration=0, **kw: time.sleep(0.4)
        app.engine.stop = lambda *a, **k: time.sleep(0.4)

        t0 = time.monotonic()
        app._start()
        assert (time.monotonic() - t0) < 0.2, "start blocked the UI thread"
        assert app.running is False                # worker still loading the driver
        assert app.btn_start.kw["text"] == bnt.T("buttons.start")   # no "Starting..." label

        app._settle_transition()
        assert app.running is True
        assert app.btn_start.kw["text"] == bnt.T("buttons.stop")

        t0 = time.monotonic()
        app._stop()
        assert (time.monotonic() - t0) < 0.2, "stop blocked the UI thread"
        assert app.running is True                 # not stopped until the worker joins
        assert app.btn_start.kw["text"] == bnt.T("buttons.stop")    # no "Stopping..." label

        app._settle_transition()
        assert app.running is False
        assert app.btn_start.kw["text"] == bnt.T("buttons.start")
    """)


def test_closing_the_window_always_releases_the_engine():
    """A leaked divert keeps the WinDivert driver - and its .sys file - locked."""
    run_gui("""
        import beantester.gui.dialogs as dialogs
        dialogs.ask_yes_no = lambda *a, **k: True

        stopped = []
        app.engine.stop = lambda *a, **k: stopped.append(1)
        app.running = True
        app.on_close()

        assert stopped, "the engine was not stopped when the window closed"
        assert app.running is False
    """)


def test_closing_the_window_while_start_resolves_opens_no_driver_afterwards():
    """The window closed while START was still resolving its target (external
    review P2-14). on_close stopped an engine that was not running yet and
    released a driver nothing had loaded, and the start then opened one that
    nothing unloaded - reproduced in exactly that order on the old code.

    The REAL engine, not a stand-in for ``engine.start``: whether this start may
    still go ahead is asked inside it, under its stop lock (``admit``), and a
    stand-in would skip exactly that question."""
    run_gui("""
        import threading
        import beantester.gui.app as appmod
        import beantester.driver as drv
        from beantester.synthetic import SyntheticDivert
        resolving, resolved = threading.Event(), threading.Event()
        real_apply = appmod.apply_settings

        def slow_apply(*a, **k):
            resolving.set()
            resolved.wait(10)                   # the synchronous target resolution
            return real_apply(*a, **k)

        appmod.apply_settings = slow_apply
        opened = []

        class Driver(SyntheticDivert):
            def open(self):
                opened.append(1)

        real_start = app.engine.start
        app.engine.start = lambda filt, **k: real_start(filt, divert=Driver(seed=1), **k)
        drv.release_on_exit = lambda log=None: []
        app._start()
        worker = app._transition_thread
        assert resolving.wait(5)
        app.on_close()                          # stop and release, still resolving
        resolved.set()
        worker.join(5)
        assert not worker.is_alive()
        assert not opened, "the driver was opened after the window had closed"
        assert not app.engine.is_running()
    """)


def test_closing_the_window_waits_for_a_start_already_opening_the_driver():
    """The other half of P2-14: past the target and inside engine.start, the stop
    and the driver release have to come AFTER it - before it, the release finds
    nothing loaded and the stop nothing running. Nothing in on_close waits for the
    start: the engine's stop lock, which the start holds while the driver loads,
    is what puts them in that order, so this runs the real engine."""
    run_gui("""
        import threading
        import beantester.driver as drv
        from beantester.synthetic import SyntheticDivert
        opening, loaded = threading.Event(), threading.Event()
        order = []

        class Driver(SyntheticDivert):
            def open(self):
                opening.set()
                loaded.wait(10)                 # the driver load
                order.append("opened")

            def close(self):
                order.append("closed")
                super().close()

        real_start = app.engine.start
        app.engine.start = lambda filt, **k: real_start(filt, divert=Driver(seed=1), **k)
        drv.release_on_exit = lambda log=None: order.append("released") or []
        app._start()
        assert opening.wait(5)
        threading.Timer(0.3, loaded.set).start()
        app.on_close()
        assert order == ["opened", "closed", "released"], order
    """)


def test_a_start_asks_admit_under_the_lock_its_stop_takes():
    """``admit`` is the start's "still wanted?", and it only means something asked
    under the lock a stop takes (external review P2-14, CodeRabbit on PR #230):
    asked before it, a stop and a driver release could land between the answer
    and the start, and the start then loaded a driver nothing unloaded."""
    engine, held = BeanEngine(), []

    def refuse():
        held.append(engine._stop_lock._is_owned())
        return False

    divert = QuietDivert()
    result = engine.start("test", divert=divert, admit=refuse)
    check("admit: asked holding the stop lock", held == [True], f"({held})")
    check("admit: a refused start says so", result is False, f"({result!r})")
    check("admit: and nothing runs", engine.is_running() is False)
    check("admit: a refused start leaves nothing for atexit",
          engine not in set(_LIVE_ENGINES))


def test_a_window_that_closes_right_after_admit_stops_after_the_start():
    """The race itself, made certain: the window closes the moment ``admit`` says
    yes, and is given every chance to finish its stop and its driver release
    first. Asked under the lock, that close waits for the start, then stops it -
    so what the start loaded is unloaded."""
    engine, order = BeanEngine(), []

    class Driver(QuietDivert):
        def open(self):
            order.append("opened")

        def close(self):
            order.append("closed")
            super().close()

    def close_the_window():
        engine.stop()
        order.append("released")

    def admit():
        closing = threading.Thread(target=close_the_window, daemon=True)
        closing.start()
        closing.join(0.3)
        return True

    try:
        engine.start("test", divert=Driver(), admit=admit)
        _wait_until(lambda: "released" in order)
        seen, left_running = list(order), engine.is_running()
    finally:
        engine.stop()                   # a broken admit must not leak a session
    check("admit: a close landing after the answer stops the session it let in",
          seen == ["opened", "closed", "released"], f"({seen})")
    check("admit: nothing is left running", left_running is False)


def test_a_scenario_that_cannot_start_ends_the_session():
    """P3-30: ``start_scenario`` raising out of ``_finish_start`` skipped the UI
    sync, so a running session sat behind a START button - and clicking it
    stopped the session. A timeline that cannot start now fails the session, as
    it does on the command line, and the UI follows on the next tick. Recorded
    only once the session is stopped (CodeRabbit on PR #230): a record writes a
    file, and nothing may stand between a fault and giving the network back."""
    run_gui("""
        from beantester import crashlog
        from beantester.synthetic import SyntheticDivert
        real_start = app.engine.start
        app.engine.start = lambda filt, **k: real_start(
            filt, divert=SyntheticDivert(seed=1), **k)

        def refuse(*a, **k):
            raise RuntimeError("can't start new thread")

        app.engine.start_scenario = refuse
        running_when_recorded = []
        real_note = crashlog.note

        def note(exc, subsystem, message=""):
            if subsystem == "gui.app":
                running_when_recorded.append(app.engine.is_running())
            return real_note(exc, subsystem, message)

        crashlog.note = note

        class _Scenario:
            loop = False

        app._scenario = _Scenario()
        app._start()
        app._settle_transition()                # this raised out of _finish_start
        assert not app.engine.is_running(), "the session runs without its scenario"
        assert "can't start new thread" in str(app.engine.fault), app.engine.fault
        assert any("can't start new thread" in (e.get("message") or "")
                   for e in crashlog.recent(10)), "not recorded"
        assert running_when_recorded == [False], (
            "recorded while the session still ran: %r" % running_when_recorded)
        app._tick()
        assert app.running is False
        assert app.btn_start.kw["text"] == bnt.T("buttons.start")
    """, allow_faults=("can't start new thread",))


def test_a_start_that_fails_shows_the_dialog_that_fits_the_failure():
    """Two cases through one door (``dialogs.show_start_failure``): a missing
    pydivert is an install, anything else is the error with the advice that fits
    it. Neither had a test while the choice lived in the window."""
    run_gui("""
        import threading
        import beantester.gui.dialogs as dialogs
        shown = []
        dialogs.show_error = lambda parent, title, message: shown.append((title, message))
        for err in (ImportError("No module named 'pydivert'"),
                    OSError("[WinError 87] The parameter is incorrect")):
            held = threading.Event()

            def fail(*a, err=err, held=held, **k):
                held.wait(5)                    # still loading when _start returns
                raise err

            app.engine.start = fail
            app._start()
            held.set()
            app._settle_transition()
        assert shown[0] == (bnt.T("dialogs.missing_library"),
                            bnt.T("dialogs.install_pydivert")), shown
        assert shown[1][0] == bnt.T("dialogs.start_failed"), shown
        assert "The parameter is incorrect" in shown[1][1], shown
        assert app.running is False
    """)


# -- pure winenv helpers: no UAC, no ctypes, no excuse for being untested ----- #


def test_the_relaunch_quoting_survives_the_arguments_windows_reparses():
    """What crosses the UAC boundary must be what the user typed.

    The version this replaces wrapped each argument in quotes and escaped inner
    quotes - correct until an argument ENDS in a backslash, which then escapes the
    closing quote and lets the rest of the command line be re-read as part of that
    argument. Measured with ``CommandLineToArgvW``, the same parser the elevated
    process starts with:

        asked for : --target 'evil\\" --loss 100 "' --loss 0
        arrived as: --target 'evil\'  --loss  100  '" --loss 0'

    ``--loss 100`` in the ELEVATED process, from a command line that never said it,
    in a program that damages network traffic for a living.

    🔴 The test that used to be here is the reason this shipped. Its docstring named
    this exact attack ("with a crafted path, with extra ones") and then asserted the
    SHAPE of the answer - that the result starts and ends with a quote, that an
    inner quote becomes a backslash-quote - which is a description of the
    implementation, not a property of it. It passed for as long as the bug existed
    and would have kept passing. This one asks the only question that matters: parse
    it back, do you get what you asked for?
    """
    import ctypes

    from beantester import winenv

    sep = chr(92)
    cases = [
        ["--simulate"],
        ["--target", "C:" + sep + "Program Files" + sep + "bean.py"],
        ["--config", 'a"b.json'],
        ["--target", "x" + sep, "--loss", "100"],
        ["--target", "evil" + sep + '" --loss 100 "', "--loss", "0"],
        ["--target", "a" + sep * 3, "--simulate"],
        [7],                                    # a non-string argument, as before
    ]

    if not hasattr(ctypes, "windll"):
        # Not Windows: there is no CommandLineToArgvW to ask, and the elevation
        # path this builds for does not exist here either. Assert the part that is
        # still true - it produces a string and does not raise on any of them -
        # rather than a weaker version of the real check.
        for args in cases:
            check(f"a parameter string is built off Windows too: {args}",
                  isinstance(winenv._relaunch_params(args), str))
        return

    from ctypes import wintypes                        # pragma: no cover - Windows

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR,
                                           ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)

    def reparse(line):
        count = ctypes.c_int(0)
        argv = shell32.CommandLineToArgvW(line, ctypes.byref(count))
        try:
            return [argv[i] for i in range(count.value)][1:]   # drop argv[0]
        finally:
            ctypes.windll.kernel32.LocalFree(argv)

    for args in cases:
        wanted = [str(a) for a in args]
        line = "bean.exe " + winenv._relaunch_params(args)
        check(f"the elevated copy receives exactly these arguments: {wanted}",
              reparse(line) == wanted, f"(it would receive {reparse(line)})")


def test_the_no_elevate_switch_is_read_the_way_the_screenshot_workflow_uses_it():
    """``BEAN_NO_ELEVATE=1`` is what keeps an automated GUI run from spawning a
    UAC prompt that nothing can answer. Every value that is not empty and not "0"
    disables elevation - "0" and "" must NOT."""
    import os

    from beantester import winenv

    previous = os.environ.get("BEAN_NO_ELEVATE")
    try:
        for value, expected in (("1", True), ("yes", True), ("true", True),
                                (" 1 ", True), ("0", False), ("", False)):
            os.environ["BEAN_NO_ELEVATE"] = value
            check(f"BEAN_NO_ELEVATE={value!r} -> {expected}",
                  winenv.elevation_disabled() is expected,
                  f"(got {winenv.elevation_disabled()})")
        os.environ.pop("BEAN_NO_ELEVATE", None)
        check("unset means elevation is allowed", winenv.elevation_disabled() is False)
    finally:
        os.environ.pop("BEAN_NO_ELEVATE", None)
        if previous is not None:
            os.environ["BEAN_NO_ELEVATE"] = previous


def test_elevation_is_refused_when_the_switch_is_set():
    """The switch has to reach the decision, not just the reader: an automated run
    that spawns a "runas" child hangs forever in a non-interactive shell."""
    import os

    from beantester import winenv

    previous = os.environ.get("BEAN_NO_ELEVATE")
    os.environ["BEAN_NO_ELEVATE"] = "1"
    try:
        check("elevate_self() refuses while BEAN_NO_ELEVATE is set",
              winenv.elevate_self([]) is False)
    finally:
        os.environ.pop("BEAN_NO_ELEVATE", None)
        if previous is not None:
            os.environ["BEAN_NO_ELEVATE"] = previous


def test_a_worker_the_engine_does_not_own_reports_through_the_same_door():
    """The scenario runner is a worker thread the watchdog cannot see.

    That watchdog walks ``_t_cap`` and ``_t_inj``; the timeline thread lives in
    ``scenario_runner``, above the engine, so a death there was nobody's business -
    the thread vanished and the session kept impairing traffic to a plan that had
    stopped existing. ``worker_failed`` is the door for that thread, and the point
    of it is that it leads to the SAME place as every other worker death rather
    than to a quieter answer of its own.
    """
    eng = BeanEngine()
    eng.start("test", divert=QuietDivert())
    try:
        eng.worker_failed(RuntimeError("the timeline broke"))

        check("fault: a foreign worker's death is recorded like any other",
              "the timeline broke" in str(eng.fault), f"({eng.fault!r})")
        check("fault: and it stops the session, so nothing is left impaired",
              not eng.is_running())
    finally:
        eng.stop()


# --- alive, and no longer doing anything ------------------------------------- #
#
# The other half of fail-open. Until 2026-09-02 the watchdog asked `is_alive()`
# and nothing else, so the one state this module's own docstring calls dangerous -
# a process still ALIVE with an open divert and no working capture thread - was
# the one it could not see. A thread spinning in a regular expression, waiting on
# a deadlocked lock, or blocked on a driver that stopped answering is alive.


class _StallingDivert(QuietDivert):
    """Hands over one packet whose first field access never returns.

    A real stall, not a poked flag: the capture thread gets past `recv()`, writes
    its beat, and then blocks INSIDE our own code, which is exactly the shape the
    watchdog has to tell apart from a quiet link. `release()` lets it finish so the
    test does not leave a thread parked forever.
    """

    def __init__(self):
        super().__init__()
        self.released = threading.Event()
        self._handed_over = False

    def recv(self):
        if not self._handed_over:
            self._handed_over = True
            return _StallingPacket(self.released)
        return super().recv()           # then behave like a quiet link

    def release(self):
        self.released.set()


class _StallingPacket(FakePacket):
    def __init__(self, released):
        super().__init__()
        self._released = released

    @property
    def raw(self):
        # `size = len(packet.raw)` is the first thing the loop does after writing
        # its beat, so blocking here parks the thread on the far side of `recv()`.
        self._released.wait(30)
        return b"\x00" * 100

    @raw.setter
    def raw(self, value):
        pass                            # FakePacket.__init__ assigns it


def test_a_capture_thread_that_is_alive_but_no_longer_moving_fails_open():
    """The session must stop and the divert must close, as for a DEAD thread.

    The threshold is lowered on the instance rather than waited out: ten seconds is
    the shipped value and it is chosen against a healthy session's worst gap
    (31.912 ms measured), not against how long a test may take.
    """
    eng = BeanEngine()
    eng.CAPTURE_STALL_S = 0.3
    divert = _StallingDivert()
    eng.start("test", divert=divert)
    try:
        def stopped_completely():
            kinds = [(e[2], e[3]) for e in eng.events_snapshot()]
            return (not eng.is_running() and divert.closed
                    and ("STOP", "events.fault") in kinds)

        check("stall: the session stops and finishes teardown",
              _wait_until(stopped_completely),
              f"(running={eng.is_running()}, closed={divert.closed})")
        check("stall: the divert is closed (network restored)", divert.closed is True)
        check("stall: the reason is recorded", eng.stop_reason == "fault",
              f"({eng.stop_reason})")
        check("stall: the fault says what happened",
              "capture thread" in str(eng.fault).lower(), f"({eng.fault})")
    finally:
        divert.release()


class _GoesQuietDivert(QuietDivert):
    """One packet, then nothing - an ordinary link that falls silent."""

    def __init__(self):
        super().__init__()
        self._handed_over = False

    def recv(self):
        if not self._handed_over:
            self._handed_over = True
            return FakePacket()
        return super().recv()


def test_a_quiet_link_is_never_mistaken_for_a_stalled_capture_thread():
    """The half that matters more, because a false stall kills a real test.

    A capture thread parked in `recv()` on a link with no traffic has not beaten
    for as long as the link has been silent, which can be the whole session. That
    is indistinguishable from a stall by any counter alone - `_cap_waiting` is the
    only thing that separates them, and this is what would catch its removal.
    """
    eng = BeanEngine()
    eng.CAPTURE_STALL_S = 0.2
    divert = _GoesQuietDivert()
    eng.start("test", divert=divert)
    try:
        # Long past the threshold and past several watchdog ticks (0.2 s each).
        time.sleep(1.5)
        check("quiet link: the session is still running",
              eng.is_running() is True, f"(stop_reason={eng.stop_reason})")
        check("quiet link: the divert is still open", divert.closed is False)
        check("quiet link: nothing was recorded as a fault", eng.fault is None,
              f"({eng.fault})")
    finally:
        eng.stop()


def test_the_stall_check_answers_no_for_every_state_that_is_not_one():
    """The degenerate-but-legal inputs, asked directly so they cannot be missed.

    A session that has not seen its first packet has no beat at all, and a thread
    that has already died is the liveness check's business, not this one - both
    would otherwise fail-stop a session for the wrong reason.
    """
    eng = BeanEngine()
    eng.CAPTURE_STALL_S = 0.01
    check("no beat yet: not a stall", eng._capture_has_stalled() is False)

    eng._cap_beat_at = time.monotonic() - 60
    eng._cap_waiting = False
    check("no capture thread: not a stall", eng._capture_has_stalled() is False)

    eng._t_cap = threading.Thread(target=lambda: None)
    eng._t_cap.start()
    eng._t_cap.join()
    check("dead capture thread: left to the liveness check",
          eng._capture_has_stalled() is False)


# --- a worker that outlives its session (external review P2-12) ----------------- #
#
# STOP joins each worker for 2 s and then gives up, so a worker stuck in our own
# code - the very thing the stall check above stops a session for - is still
# running after STOP. It used to read `_running` and `_divert` live, so the next
# START revived it. Both cases below were reproduced before the fix.


class _ReadersDivert(QuietDivert):
    """A quiet handle that remembers which threads called ``recv()`` on it."""

    def __init__(self):
        super().__init__()
        self.readers = set()

    def recv(self):
        self.readers.add(threading.current_thread())
        return super().recv()


def test_a_capture_thread_that_outlives_its_session_never_reads_the_next_one():
    """It read the NEXT session's handle with the old session's random generator,
    next to the new capture thread and watched by nobody: 957 packets in the
    second after it was released, in the reproduction."""
    eng = BeanEngine()
    eng.CAPTURE_STALL_S = 0.3
    first = _StallingDivert()
    eng.start("test", divert=first)
    stuck = eng._t_cap
    try:
        check("the stall stopped the first session",
              _wait_until(lambda: not eng.is_running() and first.closed))
        second = _ReadersDivert()
        eng.start("test", divert=second)            # waits out the 2 s join
        check("the stuck thread outlived its session's STOP", stuck.is_alive())
        first.release()                             # it gets its packet back
        stuck.join(5)
        check("P2-12: it ended with its session", not stuck.is_alive())
        check("P2-12: without reading the next session's handle",
              stuck not in second.readers)
        check("the next session is running and healthy",
              eng.is_running() and eng.fault is None, f"({eng.fault})")
    finally:
        first.release()
        eng.stop()


def test_a_watchdog_that_outlives_its_session_never_faults_the_next_one():
    """An old watchdog, held past its join by a slow tick, woke up inside the next
    START - after the new workers were created, before they were started - judged
    them dead and recorded "worker thread ... died unexpectedly" against a session
    that was perfectly healthy. The fault stayed on it and went into its report."""
    lines, gate = [], threading.Event()
    state = {"held": False, "second": False}

    def log(text):
        lines.append(text)
        if state["second"] and "seed=" in text and not gate.is_set():
            # The next START's banner: its workers exist but are not started yet,
            # which is where the reproduction found them.
            gate.set()
            old_watchdog.join(5)

    eng = BeanEngine(log_fn=log)
    real_trim = eng._conns_log.trim

    def slow_trim():
        if not state["held"]:
            state["held"] = True
            gate.wait(10)                   # a maintenance tick that outlasts the join
        return real_trim()

    eng._conns_log.trim = slow_trim
    eng.start("test", divert=QuietDivert())
    old_watchdog = eng._t_wd
    try:
        check("the watchdog is inside its slow tick", _wait_until(lambda: state["held"]))
        eng.stop()
        check("and outlived the STOP", old_watchdog.is_alive())
        state["second"] = True
        first_line = len(lines)
        eng.start("test", divert=QuietDivert())
        check("the old watchdog has finished its tick", not old_watchdog.is_alive())
        check("P2-12: the next session is not marked as failed",
              eng.is_running() and eng.fault is None, f"({eng.fault})")
        said = [line for line in lines[first_line:] if "died unexpectedly" in line]
        check("P2-12: and nothing in its log says it failed", not said, f"({said})")
    finally:
        gate.set()
        eng.stop()


class _HungSendDivert(QuietDivert):
    """One packet in; the first ``send()`` hangs until released - a driver that
    stopped answering."""

    def __init__(self):
        super().__init__()
        self.sending, self.released = threading.Event(), threading.Event()
        self._handed_over = False

    def recv(self):
        if not self._handed_over:
            self._handed_over = True
            return FakePacket(size=100, port=7001)
        return super().recv()

    def send(self, packet, recalculate_checksum=True):
        self.sending.set()
        self.released.wait(10)


def test_an_inject_thread_that_outlives_its_session_ends_with_it():
    """The injector read ``_running`` live as well: one hung in ``send()`` past the
    join came back into the next session's queue, a second injector nobody
    watched."""
    eng = BeanEngine()
    first = _HungSendDivert()
    eng.start("test", divert=first)
    hung = eng._t_inj
    try:
        check("the injector is hung in send()", first.sending.wait(5))
        eng.stop()                                  # gives up on it after 2 s
        check("and outlived the STOP", hung.is_alive())
        eng.start("test", divert=QuietDivert())
        first.released.set()
        hung.join(5)
        check("P2-12: it ended with its session", not hung.is_alive())
    finally:
        first.released.set()
        eng.stop()


def test_a_stop_or_a_fault_from_a_finished_session_leaves_the_running_one_alone():
    """Each door a worker can knock on, asked directly with the session it belongs
    to after that session has ended - including the bow-out of a stop that finds
    the lock taken, which the scenarios above never reach."""
    lines = []
    eng = BeanEngine(log_fn=lines.append)
    eng.start("test", divert=QuietDivert())
    finished = eng._session
    eng.stop()
    eng.start("test", divert=QuietDivert())
    try:
        said = len(lines)
        eng._fail_stop(RuntimeError("stale fault"), blocking=False, session=finished)
        eng._fail_stop(RuntimeError("stale fault"), blocking=True, session=finished)
        with eng._stop_lock:
            eng._stop_locked("fault", ("stale line",), session=finished)
        taken, done = threading.Event(), threading.Event()

        def hold_the_lock():
            with eng._stop_lock:
                taken.set()
                done.wait(5)

        holder = threading.Thread(target=hold_the_lock, daemon=True)
        holder.start()
        taken.wait(5)
        try:
            eng._worker_stop("duration", ("stale line",), session=finished)
        finally:
            done.set()
            holder.join(5)
        check("the running session is still running", eng.is_running())
        check("and carries no fault", eng.fault is None, f"({eng.fault})")
        stale = [line for line in lines[said:] if "stale" in line]
        check("and nothing of the finished session was said", not stale, f"({stale})")
    finally:
        eng.stop()


# --- an injector that stops moving, and what STOP waits for -------------------- #
#
# The injector had no watchdog of its own: stuck on one packet it delivered nothing
# while the session looked healthy (external review P3-9). STOP gave every stuck
# worker a 2 s join of its own, long after the divert had closed (NOWE-5a-2). And a
# worker it gave up on could spin on a core for the rest of the program's life
# without a word (owner decision D-33).


def test_an_inject_thread_that_is_alive_but_no_longer_moving_fails_open():
    """A ``send()`` the driver never answers stops the session and closes the
    divert, as a stalled capture thread does. The threshold is lowered on the
    instance for the same reason as there."""
    eng = BeanEngine()
    eng.CAPTURE_STALL_S = 0.3
    eng.JOIN_S = 0.2                    # the hung send outlives the join; keep it short
    divert = _HungSendDivert()
    eng.start("test", divert=divert)
    try:
        check("the injector is hung in send()", divert.sending.wait(5))
        check("P3-9: the session stops and the divert closes",
              _wait_until(lambda: not eng.is_running() and divert.closed),
              f"(running={eng.is_running()}, closed={divert.closed})")
        check("P3-9: as a fault", eng.stop_reason == "fault", f"({eng.stop_reason})")
        check("P3-9: that names the injector",
              "inject thread" in str(eng.fault), f"({eng.fault})")
    finally:
        divert.released.set()
        eng.stop()


def test_a_packet_waiting_out_its_delay_is_not_a_stalled_injector():
    """Seconds spent waiting for a packet's release time are the job, not a stall:
    the injector counts as busy from the moment the packet leaves the queue until
    it is back on the wire, and not a moment longer. Either end in the wrong place
    stops a healthy session with a false fault."""
    eng = BeanEngine()
    eng.CAPTURE_STALL_S = 0.3
    eng.set_params(0, 0, 0, 1000, 0, 0, 0)         # every packet is held for 1 s
    divert = _GoesQuietDivert()
    eng.start("test", divert=divert)
    try:
        # Past the release, and past the threshold twice more after it.
        time.sleep(1.8)
        check("latency: the packet was delivered",
              eng.stats_snapshot()["bytes_out"] == 100,
              f"({eng.stats_snapshot()['bytes_out']})")
        check("latency: the session is still running", eng.is_running() is True,
              f"(fault={eng.fault})")
        check("latency: nothing was recorded as a fault", eng.fault is None,
              f"({eng.fault})")
    finally:
        eng.stop()


class _EveryWorkerHungDivert(QuietDivert):
    """One packet in; then ``recv()`` and ``send()`` both hang until released,
    deaf to ``close()`` - a driver that stopped answering."""

    def __init__(self):
        super().__init__()
        self.reading, self.sending = threading.Event(), threading.Event()
        self.released = threading.Event()
        self._handed_over = False

    def recv(self):
        if not self._handed_over:
            self._handed_over = True
            return FakePacket(size=100, port=7003)
        self.reading.set()
        self.released.wait(10)
        raise OSError("closed")

    def send(self, packet, recalculate_checksum=True):
        self.sending.set()
        self.released.wait(10)


def test_stop_gives_its_stuck_workers_one_budget_between_them():
    """Two stuck workers made STOP wait 2 s EACH - up to 6 s with the watchdog -
    with the divert already closed and nothing left to restore (NOWE-5a-2)."""
    eng = BeanEngine()
    eng.JOIN_S = 1.0
    divert = _EveryWorkerHungDivert()
    eng.start("test", divert=divert)
    capture, injector = eng._t_cap, eng._t_inj
    try:
        check("both workers are stuck",
              divert.reading.wait(5) and divert.sending.wait(5))
        began = time.monotonic()
        eng.stop()
        took = time.monotonic() - began
        check("and both outlive the STOP", capture.is_alive() and injector.is_alive())
        check("NOWE-5a-2: STOP waited out one budget, not one each",
              0.9 <= took < 1.6, f"({took:.2f} s against a budget of 1.0 s)")
        check("the divert was closed all the same", divert.closed is True)
    finally:
        divert.released.set()
        capture.join(5)
        injector.join(5)
        eng.stop()


def test_an_ordinary_stop_does_not_wait_for_the_watchdog_tick(monkeypatch):
    """The watchdog slept through its tick and STOP's join waited for it: nearly all
    of an ordinary STOP (median 82 ms, worst 212 ms, measured 2026-09-29). A tick
    made long here stretches that to the whole join budget unless STOP wakes it.

    The watchdog is seen ENTERING its wait before STOP, not assumed to be there
    after a sleep: a watchdog still on its way when STOP drops the flag leaves at
    once, and the test would then pass without the wake."""
    import beantester.engine as engine_module

    monkeypatch.setattr(engine_module, "WATCHDOG_TICK_S", 5.0)
    entered = threading.Event()
    real_init = engine_module._Session.__init__

    def init(session, divert, stuck=()):
        real_init(session, divert, stuck)
        real_wait = session.woken.wait

        def wait(timeout=None):
            entered.set()
            return real_wait(timeout)       # the real wait, only announced

        session.woken.wait = wait

    monkeypatch.setattr(engine_module._Session, "__init__", init)
    eng = BeanEngine()
    eng.start("test", divert=QuietDivert())
    watchdog = eng._t_wd
    check("the watchdog is inside its first tick", entered.wait(5))
    began = time.monotonic()
    eng.stop()
    took = time.monotonic() - began
    check("STOP woke the watchdog, and it has ended", not watchdog.is_alive())
    check("STOP did not wait out the tick", took < 1.0, f"({took:.2f} s)")


def test_a_start_says_when_part_of_the_previous_session_is_still_stuck():
    """A worker STOP gave up on is said at the next START - first, before the
    handle opens - and at every START while it lives, not only the next one. Once
    it has ended, nothing is said."""
    lines = []
    eng = BeanEngine(log_fn=lines.append)
    eng.JOIN_S = 0.2
    stuck_line = T("log.previous_session_stuck")
    first = _HungSendDivert()
    eng.start("test", divert=first)
    hung = eng._t_inj

    def said_at_start():
        mark = len(lines)
        eng.start("test", divert=QuietDivert())
        return stuck_line in lines[mark:], lines[mark:mark + 1]

    try:
        check("the injector is hung in send()", first.sending.wait(5))
        eng.stop()
        check("and outlived the STOP", hung.is_alive())
        said, head = said_at_start()
        check("D-33: the next START says so", said, f"({lines[-4:]})")
        check("D-33: as its first line", head == [stuck_line], f"({head})")
        eng.stop()                                  # a clean session in between
        said, _ = said_at_start()
        check("D-33: and the START after that, while it still hangs", said,
              f"({lines[-4:]})")
        eng.stop()
        first.released.set()
        hung.join(5)
        said, _ = said_at_start()
        check("D-33: nothing once it has ended", not said, f"({lines[-4:]})")
    finally:
        first.released.set()
        eng.stop()


# --- the log is the caller's code: it can block, and it can raise ------------- #
#
# On the CLI the log is a plain write to stderr. A console whose text is being
# selected with the mouse holds that write until the selection ends, and so does a
# pipe nobody reads any more. Every stop path used to SAY why before it stopped, so
# the divert stayed open for exactly as long as the log was held - measured
# 2026-09-28 on all six paths below, and on a session past its --duration.


class _FrozenLog:
    """A log that stops returning at the first line containing ``needle``."""

    def __init__(self):
        self.needle = None
        self.lines = []
        self.frozen = threading.Event()
        self.thaw = threading.Event()
        self.raised = None              # the error a start() on another thread got

    def __call__(self, line):
        line = str(line)
        self.lines.append(line)
        if self.needle and self.needle in line and not self.thaw.is_set():
            self.frozen.set()
            self.thaw.wait(10)


def _frozen_at_the_deadline(eng, log, monkeypatch):
    log.needle = T("log.duration_reached", v="0.2")
    divert = QuietDivert()
    eng.start("test", divert=divert, duration=0.2)
    return divert


def _frozen_at_a_recv_error(eng, log, monkeypatch):
    log.needle = "driver went away"
    divert = ExplodingDivert(packets=0)
    eng.start("test", divert=divert)
    return divert


def _frozen_at_a_dead_worker(eng, log, monkeypatch):
    log.needle = "died unexpectedly"
    monkeypatch.setattr(eng, "_capture_loop", lambda session: None)    # ends at once
    divert = QuietDivert()
    eng.start("test", divert=divert)
    return divert


def _frozen_at_a_stall(eng, log, monkeypatch):
    log.needle = "stopped making progress"
    eng.CAPTURE_STALL_S = 0.3
    divert = _StallingDivert()
    eng.start("test", divert=divert)
    return divert


def _frozen_at_a_foreign_worker(eng, log, monkeypatch):
    log.needle = "the timeline broke"
    divert = QuietDivert()
    eng.start("test", divert=divert)
    threading.Thread(target=eng.worker_failed,
                     args=(RuntimeError("the timeline broke"),), daemon=True).start()
    return divert


def _frozen_at_a_failed_start(eng, log, monkeypatch):
    log.needle = "would not start"

    def refuse():
        raise RuntimeError("the resolver would not start")

    monkeypatch.setattr(eng._resolver, "start", refuse)
    divert = QuietDivert()

    def start():
        # start() blocks in the log it says on its way out, so it runs here
        try:
            eng.start("test", divert=divert)
        except RuntimeError as exc:
            log.raised = str(exc)

    threading.Thread(target=start, daemon=True).start()
    return divert


@pytest.mark.parametrize("path", [
    _frozen_at_the_deadline, _frozen_at_a_recv_error, _frozen_at_a_dead_worker,
    _frozen_at_a_stall, _frozen_at_a_foreign_worker, _frozen_at_a_failed_start,
], ids=lambda path: path.__name__.removeprefix("_frozen_at_"))
def test_a_stop_closes_the_divert_while_the_log_is_still_blocked(path, monkeypatch):
    """Close first, SAY why afterwards - and still in the order a tester reads.

    The divert has to close while the log is still held: that is the whole fix.
    The rest of the teardown too, so a held log keeps nothing of the session.
    Then, once the log moves again, the reason has to come before "Stop.", the
    order the lines had before (convention: a log that reads backwards cannot tell
    a tester what happened when).
    """
    log = _FrozenLog()
    eng = BeanEngine(log_fn=log)
    divert = path(eng, log, monkeypatch)
    try:
        check("the stop path reached the log and the log is held",
              log.frozen.wait(5), f"({log.lines})")
        check("the divert is closed while the log is still held (network restored)",
              _wait_until(lambda: divert.closed, 3.0),
              f"(running={eng.is_running()}, lines={log.lines})")
        check("and the session is no longer running", eng.is_running() is False)
        # The rest of the teardown does not wait for the log either: the
        # system-wide timer request, the switch interval and the atexit entry.
        check("and nothing of the session is still held while the log is",
              eng not in set(_LIVE_ENGINES) and not eng._fine_timers
              and not eng._fast_switch,
              f"(tracked={eng in set(_LIVE_ENGINES)}, timers={eng._fine_timers}, "
              f"switch={eng._fast_switch})")
    finally:
        log.thaw.set()
        if hasattr(divert, "release"):
            divert.release()
    eng.stop()      # waits for the stop that was held, so the log is complete

    reason = next((i for i, line in enumerate(log.lines) if log.needle in line), None)
    stop = [i for i, line in enumerate(log.lines) if line == T("log.stop")]
    check("the reason is said once the log moves again", reason is not None,
          f"({log.lines})")
    check("and before the one 'Stop.' line", len(stop) == 1 and reason < stop[0],
          f"({log.lines})")
    if path is _frozen_at_a_failed_start:
        check("the caller still gets the start's own error",
              _wait_until(lambda: log.raised is not None)
              and log.raised == "the resolver would not start", f"({log.raised!r})")


def test_a_start_line_held_by_the_log_does_not_hold_the_traffic():
    """The START lines are said by start() itself, holding the stop lock. They used
    to be said with the handle already open and no capture thread yet, so a log
    that blocked on them (a console paused by a text selection) held ALL the
    filtered traffic for as long as it blocked - found with NOWE-5a-1, pinned to
    P1-5. Said now once the capture thread is reading."""
    log = _FrozenLog()
    log.needle = "seed="

    class Drained(QuietDivert):
        def __init__(self):
            super().__init__()
            self.reading = threading.Event()

        def recv(self):
            self.reading.set()
            return super().recv()

    divert = Drained()
    eng = BeanEngine(log_fn=log)
    starting = threading.Thread(target=eng.start, args=("test",), kwargs={"divert": divert},
                                daemon=True)
    starting.start()
    try:
        check("the start line reached the log and the log is held",
              log.frozen.wait(5), f"({log.lines})")
        check("and the handle is being read while it is held",
              divert.reading.wait(5), f"({log.lines})")
    finally:
        log.thaw.set()
        starting.join(5)
        eng.stop()


class _RefusingSendDivert(_GoesQuietDivert):
    """One packet in, and the driver refuses to put it back on the wire."""

    def send(self, packet, recalculate_checksum=True):
        raise OSError("the driver refused the packet")


def test_an_injector_held_by_the_log_it_warns_in_still_fails_open():
    """A failed ``send()`` is said on the injector's own thread, and a console
    paused mid-selection holds that line - with nothing watching the injector, the
    divert stayed open for as long as the console stayed paused (P3-9).

    Not a case of the parametrized test above, on purpose: there the log holds a
    line the STOP says, after its teardown. Here it holds a worker BEFORE any stop,
    and the stop then spends its join budget on that worker - so "nothing of the
    session is still held" is not true yet while the log is, and only the divert is
    asked about.
    """
    log = _FrozenLog()
    log.needle = "the driver refused the packet"
    eng = BeanEngine(log_fn=log)
    eng.CAPTURE_STALL_S = 0.3
    divert = _RefusingSendDivert()
    eng.start("test", divert=divert)
    try:
        check("the injector is held by its own warning", log.frozen.wait(5),
              f"({log.lines})")
        check("P3-9: the divert closes while the log is still held (network restored)",
              _wait_until(lambda: divert.closed, 3.0),
              f"(running={eng.is_running()}, lines={log.lines})")
        check("P3-9: and the session is over", eng.is_running() is False)
        check("P3-9: stopped for the injector", "inject thread" in str(eng.fault),
              f"({eng.fault})")
    finally:
        log.thaw.set()
        eng.stop()


def test_a_log_that_raises_cannot_cancel_a_stop(monkeypatch):
    """A log that RAISES took the stop down with it.

    MEASURED 2026-09-28: a log raising on the deadline line killed the watchdog -
    the session never stopped, and nothing was left to notice anything else. At
    START it was worse: the announcement raised into the failure handler, whose own
    fault line raised again before it could stop, so the divert stayed open and the
    caller got the log's error instead of the real one.
    """
    def broken(line):
        raise RuntimeError("the log is gone")

    eng = BeanEngine(log_fn=broken)
    divert = QuietDivert()
    eng.start("test", divert=divert, duration=0.2)
    check("deadline: a session with a broken log still starts", eng.is_running() is True)

    def stopped_completely():
        kinds = [(e[2], e[3]) for e in eng.events_snapshot()]
        return (not eng.is_running() and divert.closed
                and ("STOP", "events.duration_reached") in kinds)

    check("deadline: and still stops at its deadline, teardown and all",
          _wait_until(stopped_completely, 3.0),
          f"(running={eng.is_running()}, closed={divert.closed})")

    def refuse():
        raise RuntimeError("the resolver would not start")

    eng = BeanEngine(log_fn=broken)
    monkeypatch.setattr(eng._resolver, "start", refuse)
    divert = QuietDivert()
    raised = None
    try:
        eng.start("test", divert=divert)
    except RuntimeError as exc:
        raised = str(exc)
    check("failed start: the caller gets the start's error, not the log's",
          raised == "the resolver would not start", f"({raised!r})")
    check("failed start: the divert is closed", divert.closed is True)
    check("failed start: nothing is left running or tracked",
          eng.is_running() is False and eng not in set(_LIVE_ENGINES))


# --- START and STOP must survive the worker ending badly ---------------------- #


def test_a_start_that_fails_outside_Exception_still_gives_the_button_back():
    """The queue is fed in a `finally`, so `_transition` can never stick.

    `_transition` is only ever cleared by `_poll_transition` reading that queue.
    A `run()` that ends without putting leaves the flag on "starting" forever:
    `_start` and `_stop` return immediately while a transition is in flight, and
    `_poll_transition` keeps re-arming `root.after(30, ...)`. START and STOP are
    then dead for the life of the window, with a divert possibly still open -
    which is the one control a network tester must never take away.

    `KeyboardInterrupt` because it is not an `Exception`: the old handler caught
    that class and nothing else, so anything outside it escaped past the `put`.
    """
    run_gui("""
        def boom(*a, **k):
            raise KeyboardInterrupt("out of nowhere")
        app.engine.start = boom

        app._start()
        app._settle_transition()

        assert app._transition is None, ("the button is stuck on %r"
                                         % (app._transition,))
        assert app.running is False

        # ...and it still works afterwards, which is the point of giving it back.
        app.engine.start = lambda filt, divert=None, duration=0, **kw: None
        app._start()
        app._settle_transition()
        assert app.running is True
    """, allow_faults=("out of nowhere",))


def test_one_window_per_fault_not_one_per_occurrence():
    """A binding that fires in a series must not stack modal windows.

    `crashlog.record` deduplicates by fingerprint and counts the repeats.
    `dialogs.show_error` deduplicated nothing, so an exception out of something
    like `<Configure>` - which fires continuously while a window edge is dragged -
    buried the user under a stack of modals to close one by one, on top of the
    original fault and with the rest of the interface not responding.
    """
    run_gui("""
        import beantester.gui.dialogs as dialogs

        shown = []
        dialogs.show_error = lambda parent, title, body: shown.append(body)

        def raise_it():
            raise ValueError("the same fault")

        for _ in range(5):
            try:
                raise_it()
            except ValueError as exc:
                app._on_ui_exception(type(exc), exc, exc.__traceback__)

        assert len(shown) == 1, ("one window per fault, got %d" % len(shown))

        # Every occurrence still reaches the log, which is where the repeats live.
        hits = [l for l in app._log_lines if "the same fault" in l]
        assert len(hits) == 5, hits

        # A DIFFERENT fault is still shown: this deduplicates, it does not go quiet.
        def raise_other():
            raise TypeError("a different fault")
        try:
            raise_other()
        except TypeError as exc:
            app._on_ui_exception(type(exc), exc, exc.__traceback__)
        assert len(shown) == 2, shown
    """, allow_faults=("the same fault", "a different fault"))
