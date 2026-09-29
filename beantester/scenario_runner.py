"""Scenario orchestration - applies scenario steps to a running engine.

Extracted from ``BeanEngine`` so the engine no longer needs runtime imports
of ``settings``/``summary`` inside a method (the old workaround for a
dependency cycle): this module sits above the engine and imports both sides
normally, keeping dependencies one-directional.
"""
import threading
import time

from . import crashlog
from .i18n import T
from .scenario import ACTIONS
from .settings import apply_settings
from .summary import settings_summary


class ScenarioRunner:
    """Runs one scenario against an engine in a background thread."""

    # Long enough that a runner between two steps is always joined (it waits on
    # the doorbell below, so it exits in microseconds), short enough that one
    # inside ``apply_settings`` can never hold STOP up. The same number and the
    # same reason as ``TargetResolver.JOIN_S``: STOP is how the user undoes the
    # damage they just did to their own network, so it is the one control this
    # tool may never make slow.
    JOIN_S = 0.25

    def __init__(self, engine, clock=time.monotonic):
        self.engine = engine
        # Injectable so a test can play hundreds of cycles of a timeline in
        # microseconds and see where each one begins (external review P2-3).
        self._clock = clock
        self._stop = True
        self._thread = None
        # The doorbell that makes the join in stop() cheap. The loop used to sleep
        # in 0.1 s steps, so joining it would have meant waiting up to that long
        # for a runner with nothing left to do - on a path ``BeanEngine.stop()``
        # walks. Set by stop(), cleared by start(); nothing else touches it, which
        # is why it can never be left set while the loop is meant to run.
        self._wake = threading.Event()
        # Set by the runner thread, read by whoever owns the session. A plain
        # bool on purpose (like ``_stop``): one writer, one transition, never
        # back. It means ONE thing - the timeline ran out - and deliberately not
        # "the runner is no longer running": ``stop()`` and a dead engine also
        # end the loop, and neither of those is a scenario that completed.
        self.finished = False
        # What every step is laid over. START sets it, and "Apply changes" during
        # the timeline replaces it (``rebase``, owner decision D-6): a base frozen
        # at START made the next step put back everything Apply had changed, the
        # target and the destination included (external review P2-17).
        # ``_rebased_from`` is the base the last applied step was computed with,
        # kept until the timeline next looks (see ``_play``).
        # Both change only under ``_lock``, which is also held while a step is
        # applied - so a step can land neither between an Apply and its new base
        # (it would put the old base back) nor on top of it unseen. ``stop()``
        # never takes it, so STOP cannot be kept waiting by an Apply, and the
        # log the runner is given here is the window's queue, not a widget.
        self._lock = threading.Lock()
        self._base = {}
        self._rebased_from = None

    def start(self, scenario, base_settings, log=lambda *_: None):
        """Start the timeline, after stopping any thread this runner still owns.

        It used to set ``_stop`` back to False and overwrite ``_thread``, which is
        how a runner could leave an orphan behind: the previous thread kept
        running with its own stop flag freshly CLEARED, applying its timeline to
        the same engine, and unreachable through ``stop()`` because that only ever
        knew about the current thread. ``BeanEngine.start_scenario`` builds a fresh
        runner every time, so nothing in the program reaches this today - which is
        the same "nobody calls it twice today is not a property of the object" the
        engine-side docstring already argues for its own half of this.
        """
        self.stop()
        self._wake.clear()
        self.finished = False
        # Set here, before the thread exists, so an Apply that arrives before the
        # thread's first step is not overwritten by the START settings.
        with self._lock:
            self._base = dict(base_settings)
            self._rebased_from = None
        self._thread = threading.Thread(
            target=self._loop, args=(scenario, log), daemon=True)
        # Only now, with the new thread already the one this runner owns: cleared
        # any earlier, it would let a thread that outlived stop()'s join above see
        # itself as the live timeline again (see _owns).
        self._stop = False
        self._thread.start()

    def stop(self, timeout=JOIN_S):
        """End the timeline, and wait briefly for the thread to actually be gone.

        A flag on its own let ``stop()`` return while the thread was still between
        two steps, so up to one more ``apply_settings`` landed on the engine AFTER
        the caller believed the scenario was over - and on a restart, the old
        timeline's last step could overwrite the new one's first.

        It never joins the CALLING thread, and that is not defensive coding: the
        runner thread reaches here on its own failure path. ``_loop`` catches, calls
        ``engine.worker_failed``, which is ``_fail_stop`` -> ``_worker_stop`` ->
        ``_stop_locked`` -> ``stop_scenario()`` -> here. Joining yourself raises,
        and it would raise inside the net that exists to handle a failure.

        No deadlock against ``BeanEngine.stop()``, which holds ``_stop_lock`` while
        calling this: the runner thread never BLOCKS on that lock (its only route
        to it is ``_fail_stop(blocking=False)``, which bows out under contention),
        and ``apply_settings`` reaches no further than ``core._lock``.
        """
        self._stop = True
        self._wake.set()
        # A local reference: a concurrent start() may put a new thread in place,
        # and this join belongs to the old one. `_thread` is deliberately NOT
        # cleared - a stopped runner that can still be asked whether its thread is
        # gone is what the guards on this class read.
        thread = self._thread
        if (thread is not None and thread.is_alive()
                and thread is not threading.current_thread()):
            thread.join(timeout=timeout)

    def running(self):
        """True while the thread is still applying the timeline (any ending: False)."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _owns(self):
        """Is the CALLING thread this runner's live timeline?

        False once ``stop()`` was called, and for a thread a later ``start()``
        replaced. Asked by the runner thread itself, and not only between steps:
        ``stop()`` joins for ``JOIN_S`` and a step can take longer - resolving a
        target walks the socket table, measured at 1.7 s cold - so a step can
        still be in flight after STOP returned. It then went on to install the old
        target into the NEXT session and log a SCENARIO event there (external
        review P2-12, reproduced); ``apply_settings`` asks this before it installs
        a target, and ``_play`` before it records anything.
        """
        return not self._stop and self._thread is threading.current_thread()

    def rebase(self, base, log=lambda *_: None):
        """"Apply changes" while the timeline runs: apply ``base`` and lay every
        later step over it. False when the timeline is not running - nothing was
        applied, and the caller applies on its own.

        What Apply changed stays until the timeline next changes: keys no step
        sets (the target, the destination) for the rest of the session, keys the
        steps set until the next step sets them again. Applying here, under the
        lock a step is applied with, is what makes that exact - see ``__init__``.
        """
        with self._lock:
            if not self.running():
                return False
            apply_settings(self.engine, base, log)
            # The base the last step came from, not the one before it: two
            # Applies inside one tick still compare against the step on the wire.
            if self._rebased_from is None:
                self._rebased_from = self._base
            self._base = dict(base)
            return True

    def _loop(self, scenario, log):
        """The thread body: run the timeline, and never die in silence.

        Before this wrapper, an exception in the loop killed the daemon thread and
        nothing else happened. The session kept running with whatever the last step
        had applied, no further step was ever applied, ``finished`` stayed False -
        and without ``--duration`` that flag is the ONLY ending a run has, so the
        session went on until somebody stopped it. Measured 2026-08-26 with a
        scenario carrying a value of the wrong type: thread dead, uncaught
        TypeError, ``engine.is_running()`` still True.

        A worker that dies takes the session down with it - that is not a new rule,
        it is ``BeanEngine._fail_stop``: "a worker died: stop the session so the
        network is never left impaired". The thread that CHANGES the impairment
        over time is exactly the one that must not be allowed to disappear while
        the impairment stays.
        """
        try:
            self._timeline(scenario, log)
        except Exception as exc:                      # noqa: BLE001 - the net itself
            try:
                crashlog.record(exc, "scenario_runner")
                if not self._owns():
                    # A step that failed after STOP: whatever session is running
                    # now is not this timeline's, and must not be stopped for it.
                    return
                # Stop FIRST, then say why: `log` is the caller's and can block (a
                # paused console), and said first it kept the session impairing
                # traffic for as long as it blocked (measured 2026-09-28).
                self.engine.worker_failed(exc)
                log(T("log.scenario_failed", e=f"{type(exc).__name__}: {exc}"))
            except Exception as _exc:
                # A safety net that can itself fall through is not one.
                crashlog.note(_exc, "scenario_runner")

    def _timeline(self, scenario, log):
        start = self._clock()
        prev_t, last = -1.0, None
        log(f"{T('log.scenario_start')} ({len(scenario.steps)} {T('log.steps')}, "
            f"{T('log.loop') if scenario.loop else T('log.once')}).")
        while self.engine.is_running() and self._owns():
            t = self._clock() - start
            if scenario.loop and scenario.duration > 0 and t > scenario.duration:
                # The LAST step first - its settings and its action (owner
                # decision D-5). Wrapping the moment the clock passed it skipped
                # both, unless a tick happened to land exactly on its `at`
                # (external review P2-3).
                self._play(scenario, prev_t, scenario.duration, last, log)
                # Whole cycles on from the old start, not "now": the overshoot
                # belongs to the next cycle. Restarting from now made every cycle
                # up to a tick longer than the file says, and the error added up.
                start += (t // scenario.duration) * scenario.duration
                prev_t, last = -1.0, None
                continue
            last = self._play(scenario, prev_t, t, last, log)
            prev_t = t
            if not scenario.loop and t > scenario.duration + 0.1:
                self.finished = True
                log(T("log.scenario_finished"))
                break
            # The doorbell, not a plain sleep: the step interval is unchanged, but
            # stop() can now end this wait at once instead of leaving whoever
            # called it to wait out the rest of a tick. See ScenarioRunner.stop.
            self._wake.wait(0.1)

    def _play(self, scenario, prev_t, t, last, log):
        """The timeline at ``t``: its settings if they changed, and the actions in
        ``(prev_t, t]``. Returns the settings now applied."""
        eng = self.engine
        with self._lock:
            s = scenario.settings_at(t, self._base)
            if self._rebased_from is not None:
                # An Apply since the last tick. If the TIMELINE has not moved
                # (the same step, on the base it was applied with), what Apply
                # set stands; if a step began this very tick, it goes on.
                moved = scenario.settings_at(t, self._rebased_from) != last
                self._rebased_from = None
                if last is not None and not moved:
                    last = s
            if s != last:
                apply_settings(eng, s, log, live=self._owns)
                if not self._owns():
                    return last         # stopped while it applied: nothing more of it
                last = s
                eng.log_event("SCENARIO", settings_summary(s, "en"))
        for at, ev in scenario.events_between(prev_t, t):
            # From scenario.ACTIONS, not a second list of the same names: a
            # copy here would keep honouring an action the validator has
            # stopped accepting, which is how "reset_now" outlived its own
            # removal for exactly as long as nobody looked.
            if str(ev.get("action")) in ACTIONS:
                eng.reset_now(float(ev.get("duration", 3.0)))
                log(f"{T('log.scenario')} [{at:.0f}s]: {T('log.scenario_reset')}.")
        return last
