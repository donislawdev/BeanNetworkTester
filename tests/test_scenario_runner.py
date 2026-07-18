"""Scenario orchestration (``beantester/scenario_runner.py``).

``test_engine.py`` already proves the engine delegates to a ``ScenarioRunner``.
What was untested is the runner's OWN loop: does it push each step's settings to
the engine as time advances, fire the scheduled ``reset_tcp`` events, and - for a
looping scenario - keep going past its duration instead of stopping?

The runner is orchestration, so its collaborators are spied on rather than run:
``apply_settings`` and ``settings_summary`` have their own tests, and driving a
real engine over real wall-clock time would make these flaky. A fake engine and a
fake scenario let each assertion be exact.
"""
import time

import pytest

from beantester import scenario_runner
from beantester.scenario_runner import ScenarioRunner
from fakes import check


class FakeEngine:
    def __init__(self):
        self.running = True
        self.events = []
        self.resets = []

    def is_running(self):
        return self.running

    def log_event(self, kind, desc):
        self.events.append((kind, desc))

    def reset_now(self, duration):
        self.resets.append(duration)


class FakeScenario:
    """Two steps and one reset event, with time-driven behaviour under our control."""

    def __init__(self, loop=False, duration=0.3):
        self.steps = [object(), object()]
        self.loop = loop
        self.duration = duration

    def settings_at(self, t, base):
        return {"loss": 0} if t < 0.15 else {"loss": 50}

    def events_between(self, prev_t, t):
        if prev_t < 0.1 <= t:
            yield (0.1, {"action": "reset_tcp", "duration": 2.0})


@pytest.fixture
def spy_apply(monkeypatch):
    """Capture what the runner applies, without running the real settings layer."""
    applied = []
    monkeypatch.setattr(scenario_runner, "apply_settings",
                        lambda eng, s, log=lambda *_: None: applied.append(dict(s)))
    monkeypatch.setattr(scenario_runner, "settings_summary", lambda s, lang: "summary")
    return applied


def _join(runner, timeout=3.0):
    if runner._thread is not None:
        runner._thread.join(timeout)


def test_runner_applies_each_step_and_fires_reset_events(spy_apply):
    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    runner.start(FakeScenario(loop=False, duration=0.3), base_settings={})
    _join(runner)                           # a non-looping scenario ends by itself

    check("the runner is not still running", not runner._thread.is_alive())
    check("both distinct steps were applied to the engine",
          {"loss": 0} in spy_apply and {"loss": 50} in spy_apply, f"({spy_apply})")
    check("the scheduled reset_tcp event fired once with its duration",
          engine.resets == [2.0], f"({engine.resets})")
    check("each applied step is logged as a SCENARIO event",
          any(kind == "SCENARIO" for kind, _ in engine.events), f"({engine.events})")


def test_a_change_is_applied_only_when_the_settings_actually_change(spy_apply):
    class Constant(FakeScenario):
        def settings_at(self, t, base):
            return {"loss": 7}      # never changes

        def events_between(self, prev_t, t):
            return iter(())

    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    runner.start(Constant(loop=False, duration=0.3), base_settings={})
    _join(runner)
    check("an unchanged scenario applies its settings exactly once",
          spy_apply == [{"loss": 7}], f"({spy_apply})")


def test_a_looping_scenario_keeps_running_past_its_duration(spy_apply):
    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    runner.start(FakeScenario(loop=True, duration=0.2), base_settings={})
    try:
        time.sleep(0.45)            # well past the 0.2s duration
        check("a looping scenario is still running after its duration elapses",
              runner._thread.is_alive())
    finally:
        runner.stop()
        _join(runner)
    check("stop() actually stops the loop", not runner._thread.is_alive())


def test_the_runner_stops_when_the_engine_stops(spy_apply):
    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    runner.start(FakeScenario(loop=True, duration=5.0), base_settings={})
    time.sleep(0.15)
    engine.running = False          # engine went down; the runner must notice
    _join(runner)
    check("the runner exits once the engine is no longer running",
          not runner._thread.is_alive())
