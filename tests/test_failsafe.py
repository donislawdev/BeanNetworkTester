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

    def send(self, packet):
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

    def send(self, packet):
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

    check("duration: the engine stops itself", _wait_until(lambda: not eng.is_running()))
    check("duration: the reason is recorded", eng.stop_reason == "duration",
          f"({eng.stop_reason})")
    check("duration: the divert is released", divert.closed is True)
    kinds = [(e[2], e[3]) for e in eng.events_snapshot()]
    check("duration: the event log says why",
          ("STOP", "events.duration_reached") in kinds, f"({kinds})")


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

    check("fail-open: the engine stops on a capture failure",
          _wait_until(lambda: not eng.is_running()))
    check("fail-open: the divert is closed (network restored)", divert.closed is True)
    check("fail-open: the reason is recorded", eng.stop_reason == "fault",
          f"({eng.stop_reason})")
    check("fail-open: the fault is kept for the report",
          "driver went away" in str(eng.fault), f"({eng.fault})")
    kinds = [(e[2], e[3]) for e in eng.events_snapshot()]
    check("fail-open: the event log says why", ("STOP", "events.fault") in kinds,
          f"({kinds})")


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


def test_the_target_refresher_never_touches_tkinter():
    """Tcl is not thread-safe: the worker thread may only see a main-thread snapshot."""
    run_gui("""
        app.vars["target"].set("chrome.exe")
        assert app._snapshot_target() == "chrome.exe"

        # an empty field means "no targeting" - there is no checkbox to tick
        app.vars["target"].set("   ")
        assert app._snapshot_target() == ""

        # from now on every tk variable explodes if the worker thread touches it
        class Exploding:
            def get(self):
                raise AssertionError("tk variable read from the refresher thread")
            def set(self, *a):
                raise AssertionError("tk variable written from the refresher thread")

        app.vars["target"] = Exploding()
        app._target_expr = "chrome.exe"
        app._refresh_target()          # this is what the worker thread runs
    """)


def test_the_gui_starts_the_session_with_its_duration():
    run_gui("""
        started = {}
        app.engine.start = (lambda filt, divert=None, duration=0:
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
        app.engine.start = lambda filt, divert=None, duration=0: time.sleep(0.4)
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
