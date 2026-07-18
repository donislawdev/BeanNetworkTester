"""Scenario orchestration - applies scenario steps to a running engine.

Extracted from ``BeanEngine`` so the engine no longer needs runtime imports
of ``settings``/``summary`` inside a method (the old workaround for a
dependency cycle): this module sits above the engine and imports both sides
normally, keeping dependencies one-directional.
"""
import threading
import time

from .i18n import T
from .settings import apply_settings
from .summary import settings_summary


class ScenarioRunner:
    """Runs one scenario against an engine in a background thread."""

    def __init__(self, engine):
        self.engine = engine
        self._stop = True
        self._thread = None

    def start(self, scenario, base_settings, log=lambda *_: None):
        self._stop = False
        self._thread = threading.Thread(
            target=self._loop, args=(scenario, dict(base_settings), log),
            daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True

    def _loop(self, scenario, base, log):
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
                # "reset_now" is the pre-1.3 spelling of "reset_tcp" (the action
                # only ever reset TCP connections - see BeanCore.decide step 4)
                if str(ev.get("action")) in ("reset_tcp", "reset_now"):
                    eng.reset_now(float(ev.get("duration", 3.0)))
                    log(f"{T('log.scenario')} [{at:.0f}s]: {T('log.scenario_reset')}.")
            prev_t = t
            if not scenario.loop and t > scenario.duration + 0.1:
                log(T("log.scenario_finished"))
                break
            time.sleep(0.1)
