"""Fail-safe: the app must never leave the user without a working network.

Killing the process is harmless (Windows closes the WinDivert handle). The
dangerous state is a process that is still ALIVE with an open divert and no
working capture thread: WinDivert keeps diverting packets into a queue nobody
drains, the user silently loses connectivity, and the UI still says "running".

These tests pin down the three guarantees:
  * a session stops itself at its ``duration`` deadline,
  * a dead worker thread makes the engine stop (= release the divert) and say so,
  * the GUI survives a broken tick, never calls Tcl from a worker thread, and
    always releases the engine when the window closes.
"""
import time

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

    def open(self):
        self.opens += 1
        if self.opens <= self.fails:
            error = OSError("[WinError 433] The specified device does not exist.")
            error.winerror = 433
            raise error

    def recv(self):
        time.sleep(0.01)
        raise RuntimeError("stopped")

    def send(self, *_a, **_k):
        pass

    def close(self):
        self.closed = True


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


def test_target_syncing_reads_only_the_main_thread_snapshot():
    """``_refresh_target`` works off ``_target_expr``, never off the tk variable.

    The background refresher that used to call this is gone (resolving moved to
    ``target_resolver``), but the separation it forced is worth keeping: the
    snapshot is taken on the main thread, and everything downstream consumes the
    plain string. That is what makes it safe to call this from anywhere later.
    """
    run_gui("""
        app.vars["target"].set("chrome.exe")
        assert app._snapshot_target() == "chrome.exe"

        # an empty field means "no targeting" - there is no checkbox to tick
        app.vars["target"].set("   ")
        assert app._snapshot_target() == ""

        # from now on the tk variable explodes if anything downstream reads it
        class Exploding:
            def get(self):
                raise AssertionError("_refresh_target read the tk variable")
            def set(self, *a):
                raise AssertionError("_refresh_target wrote the tk variable")

        app.vars["target"] = Exploding()
        app._target_expr = "chrome.exe"
        app._refresh_target()          # consumes the snapshot only
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


# -- pure winenv helpers: no UAC, no ctypes, no excuse for being untested ----- #


def test_the_relaunch_quoting_survives_a_path_with_spaces_and_quotes():
    """``_quote`` builds the parameter string handed to ``ShellExecuteW`` when the
    app re-launches itself elevated. It is a pure function and it was untested,
    while a mis-quoted argument means the elevated copy starts with the WRONG
    settings - or, with a crafted path, with extra ones.
    """
    from beantester import winenv

    check("a plain argument is wrapped", winenv._quote("--simulate") == '"--simulate"')

    # Built from parts so the test's own escaping cannot be what it measures.
    sep = chr(92)
    spaced = "C:" + sep + "Program Files" + sep + "bean.py"
    check("a path with spaces stays ONE argument",
          winenv._quote(spaced) == '"' + spaced + '"', f"({winenv._quote(spaced)})")
    check("...and its backslashes are passed through untouched",
          winenv._quote(spaced).count(sep) == 2, f"({winenv._quote(spaced)})")

    quoted = winenv._quote('a"b')
    check("an embedded quote is escaped, not left to close the string early",
          quoted == '"a\\"b"', f"({quoted})")
    check("the result always opens and closes with a quote",
          quoted.startswith('"') and quoted.endswith('"'), f"({quoted})")
    check("a non-string argument does not explode", winenv._quote(7) == '"7"')


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
