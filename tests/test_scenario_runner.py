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
from fakes import check, wait_until


class FakeEngine:
    def __init__(self):
        self.running = True
        self.events = []
        self.resets = []
        self.failures = []          # what the runner reported as a worker death

    def is_running(self):
        return self.running

    def log_event(self, kind, desc):
        self.events.append((kind, desc))

    def reset_now(self, duration):
        self.resets.append(duration)

    def worker_failed(self, error):
        """The real engine stops the session here (``BeanEngine._fail_stop``); the
        fake only records that it was told, which is the part being asserted."""
        self.failures.append(error)
        self.running = False


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


def test_the_runner_fires_exactly_the_actions_the_validator_accepts(spy_apply):
    """The runner reads ``scenario.ACTIONS`` instead of listing the names again.

    It used to carry its own copy of the tuple, one module away from the
    validator that decides which names are legal. The two agreeing was a
    coincidence maintained by hand, and the failure mode is silent in both
    directions: an action dropped from ``ACTIONS`` would keep working here long
    after the file that declares it stopped accepting it, and one added there
    would validate fine and then do nothing.
    """
    from beantester.scenario import ACTIONS

    def run(action):
        class OneAction(FakeScenario):
            def events_between(self, prev_t, t):
                if prev_t < 0.1 <= t:
                    yield (0.1, {"action": action, "duration": 1.5})
        engine = FakeEngine()
        runner = ScenarioRunner(engine)
        runner.start(OneAction(loop=False, duration=0.3), base_settings={})
        _join(runner)
        return engine.resets

    for action in ACTIONS:
        check(f"the runner honours {action!r}", run(action) == [1.5],
              f"({run(action)})")
    check("the runner ignores a name the validator would reject",
          run("reset_now") == [], "(reset_now is no longer an action)")


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
        # A fixed wait, deliberately: the assertion is that the loop is STILL
        # running past its duration, and absence of an ending cannot be polled.
        time.sleep(0.45)            # well past the 0.2s duration
        check("a looping scenario is still running after its duration elapses",
              runner._thread.is_alive())
    finally:
        runner.stop()
        _join(runner)
    check("stop() actually stops the loop", not runner._thread.is_alive())


def test_a_completed_timeline_reports_that_it_finished(spy_apply):
    """The runner is the only thing that knows when a timeline is over.

    The CLI used to have no way to ask: a non-looping scenario ended, the runner
    thread exited, and the session ran on forever (printing "Scenario finished."
    while doing exactly that). Deriving the end from ``scenario.duration`` on the
    caller's side would be a SECOND reader of the same fact - and the tail
    (``duration + 0.1``) lives here, so the two would drift on the first edit.
    """
    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    check("a runner that has not started has not finished", not runner.finished)
    runner.start(FakeScenario(loop=False, duration=0.3), base_settings={})
    _join(runner)
    check("a completed non-looping timeline reports finished", runner.finished)


def test_a_looping_runner_never_reports_finished(spy_apply):
    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    runner.start(FakeScenario(loop=True, duration=0.2), base_settings={})
    try:
        time.sleep(0.45)                      # well past the 0.2 s duration
        check("a looping timeline never reports finished", not runner.finished)
    finally:
        runner.stop()
        _join(runner)
    check("and stopping it is still not 'finished'", not runner.finished)


def test_a_runner_the_engine_shut_down_did_not_finish(spy_apply):
    """"The engine went away" and "the timeline is over" are different endings.

    Both end the runner's loop. Only the second one may end the session: if a
    dead engine reported ``finished``, the CLI would report a clean
    ``scenario_done`` for a run that actually faulted.
    """
    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    runner.start(FakeScenario(loop=False, duration=5.0), base_settings={})
    wait_until(lambda: bool(spy_apply))
    engine.running = False
    _join(runner)
    check("an engine shutdown is not a finished timeline", not runner.finished)


def test_the_runner_stops_when_the_engine_stops(spy_apply):
    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    runner.start(FakeScenario(loop=True, duration=5.0), base_settings={})
    wait_until(lambda: bool(spy_apply))       # the runner has applied its first step
    engine.running = False          # engine went down; the runner must notice
    _join(runner)
    check("the runner exits once the engine is no longer running",
          not runner._thread.is_alive())


def test_a_timeline_that_breaks_takes_the_session_down_with_it(monkeypatch):
    """The failure this net exists for, measured before it existed.

    A scenario carrying a value of the wrong type raised inside ``apply_settings``
    on this daemon thread. Nothing caught it, so: the thread died, no further step
    was ever applied, ``finished`` stayed False - and without ``--duration`` that
    flag is the only ending a run has (see ``cli.py``, "a scenario's timeline is an
    ending too"). The session went on impairing traffic to a plan that had stopped
    existing, and the only trace was an entry in the crash log.

    The engine already has one answer for a worker that dies (``_fail_stop``:
    "stop the session so the network is never left impaired"). The thread that
    CHANGES the impairment over time now gets that same answer instead of a
    quieter one of its own.
    """
    logged = []
    boom = TypeError("a value the engine cannot use")

    def explode(*_a, **_kw):
        raise boom

    monkeypatch.setattr(scenario_runner, "apply_settings", explode)
    monkeypatch.setattr(scenario_runner, "settings_summary", lambda s, lang: "summary")

    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    runner.start(FakeScenario(loop=False, duration=5.0), base_settings={},
                 log=logged.append)
    _join(runner)

    check("the thread does not survive as a zombie", not runner._thread.is_alive())
    check("the engine is told a worker died", engine.failures == [boom],
          f"({engine.failures!r})")
    check("and the user is told, in the log they are watching",
          any("TypeError" in str(line) for line in logged), f"({logged!r})")
    check("a broken timeline is still not a FINISHED one", not runner.finished,
          "'finished' means the timeline ran out - see its own docstring")
