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

    def __init__(self, engine):
        self.engine = engine
        self._stop = True
        self._thread = None
        # Set by the runner thread, read by whoever owns the session. A plain
        # bool on purpose (like ``_stop``): one writer, one transition, never
        # back. It means ONE thing - the timeline ran out - and deliberately not
        # "the runner is no longer running": ``stop()`` and a dead engine also
        # end the loop, and neither of those is a scenario that completed.
        self.finished = False

    def start(self, scenario, base_settings, log=lambda *_: None):
        self._stop = False
        self.finished = False
        self._thread = threading.Thread(
            target=self._loop, args=(scenario, dict(base_settings), log),
            daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True

    def _loop(self, scenario, base, log):
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
            self._timeline(scenario, base, log)
        except Exception as exc:                      # noqa: BLE001 - the net itself
            try:
                crashlog.record(exc, "scenario_runner")
                log(T("log.scenario_failed", e=f"{type(exc).__name__}: {exc}"))
                self.engine.worker_failed(exc)
            except Exception as _exc:
                # A safety net that can itself fall through is not one.
                crashlog.note(_exc, "scenario_runner")

    def _timeline(self, scenario, base, log):
        eng = self.engine
        start = time.monotonic()
        prev_t, last = -1.0, None
        log(f"{T('log.scenario_start')} ({len(scenario.steps)} {T('log.steps')}, "
            f"{T('log.loop') if scenario.loop else T('log.once')}).")
        while eng.is_running() and not self._stop:
            t = time.monotonic() - start
            if scenario.loop and scenario.duration > 0 and t > scenario.duration:
                start = time.monotonic()
                prev_t, last = -1.0, None
                continue
            s = scenario.settings_at(t, base)
            if s != last:
                apply_settings(eng, s, log)
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
            prev_t = t
            if not scenario.loop and t > scenario.duration + 0.1:
                self.finished = True
                log(T("log.scenario_finished"))
                break
            time.sleep(0.1)
