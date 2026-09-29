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
import threading
import time

import pytest

from beantester import crashlog, scenario_runner
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
                        lambda eng, s, log=lambda *_: None, live=None: applied.append(dict(s)))
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


def test_stop_returns_with_the_thread_already_gone(spy_apply):
    """``stop()`` used to set a flag and return, which is not the same thing.

    The thread was still between two steps, so up to one more ``apply_settings``
    landed on the engine AFTER the caller believed the scenario was over.
    ``BeanEngine.stop()`` calls this while tearing a session down, and
    ``start_scenario`` calls it to replace a runner - in that second case the old
    timeline's last step could overwrite the new one's first.

    The wait is asserted to be SHORT as well, because a join that is correct and
    slow is its own bug here: STOP is the control the user reaches for to undo
    what they just did to their own network.
    """
    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    runner.start(FakeScenario(loop=True, duration=5.0), base_settings={})
    wait_until(lambda: bool(spy_apply))       # it is running and applying steps

    began = time.monotonic()
    runner.stop()
    waited = time.monotonic() - began

    check("stop() returns only once the thread is actually gone",
          not runner._thread.is_alive())
    check("and it does not hold the caller up for a whole step interval",
          waited < 0.1, f"(waited {waited:.3f}s)")
    applied = len(spy_apply)
    time.sleep(0.25)
    check("nothing is applied to the engine after stop() has returned",
          len(spy_apply) == applied, f"({len(spy_apply)} vs {applied})")


def test_starting_again_leaves_no_orphan_applying_the_old_timeline(spy_apply):
    """``start()`` on a runner that still owns a thread.

    It set ``_stop`` back to False and overwrote ``_thread``: the previous thread
    kept running with its stop flag freshly cleared, applying ITS timeline to the
    same engine, and unreachable - ``stop()`` only ever knew about the current
    thread. ``BeanEngine.start_scenario`` builds a fresh runner each time, so this
    is the object's own guarantee rather than a path the program walks; the engine
    side has its own guard (``test_engine.py::
    test_a_second_scenario_stops_the_first_instead_of_orphaning_it``).
    """
    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    runner.start(FakeScenario(loop=True, duration=5.0), base_settings={})
    wait_until(lambda: bool(spy_apply))
    first = runner._thread

    runner.start(FakeScenario(loop=True, duration=5.0), base_settings={})

    check("the first thread is gone before the second one is handed out",
          not first.is_alive())
    check("and the runner really did hand out a second one",
          runner._thread is not first and runner._thread.is_alive())
    runner.stop()


def test_a_thread_still_in_a_step_when_started_again_is_not_the_timeline_any_more(
        monkeypatch):
    """External review P2-12, the runner half: the test above, with a step that
    outlasts ``stop()``'s join - a target resolve, 1.7 s cold.

    ``start()`` clears ``_stop`` for the new thread, so a flag alone told the old
    thread, back from its step, that it was still the live timeline: it went on
    playing the OLD timeline, and a step of it that failed stopped the new session
    as a dead worker. Whose timeline it is, is the thread's identity.
    """
    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    inside, release = threading.Event(), threading.Event()
    state = {"first": None}

    def apply(eng, s, log=None, live=None):
        if threading.current_thread() is state["first"]:
            inside.set()
            release.wait(5)
            raise TypeError("the old step fails on its way out")

    monkeypatch.setattr(scenario_runner, "apply_settings", apply)
    monkeypatch.setattr(scenario_runner, "settings_summary", lambda s, lang: "summary")
    runner.start(FakeScenario(loop=True, duration=5.0), base_settings={})
    state["first"] = first = runner._thread
    try:
        check("the first thread is inside a step", inside.wait(5))
        runner.start(FakeScenario(loop=True, duration=5.0), base_settings={})
        check("stop() inside start() gave up on it", first.is_alive())
        release.set()
        first.join(5)
        check("the old thread has ended", not first.is_alive())
        check("P2-12: its failure did not stop the session it no longer belongs to",
              not engine.failures, f"({engine.failures})")
        check("and the new timeline is still playing", runner.running())
    finally:
        release.set()
        runner.stop()


def test_stopping_from_inside_the_runner_thread_does_not_raise(spy_apply,
                                                               monkeypatch):
    """The runner's own failure path comes back through ``stop()``.

    ``_loop`` catches, calls ``engine.worker_failed``, and on the real engine that
    is ``_fail_stop`` -> ``_worker_stop`` -> ``_stop_locked`` -> ``stop_scenario()``
    -> ``ScenarioRunner.stop()`` - on the runner thread itself. A join without the
    current-thread check raises ``RuntimeError`` there, i.e. inside the net that
    exists to handle a failure. The fake engine below is the real call chain
    collapsed to its one relevant step.
    """
    def explode(*_a, **_kw):
        raise TypeError("a value the engine cannot use")

    monkeypatch.setattr(scenario_runner, "apply_settings", explode)

    def joins(): return [r for r in crashlog.recent(50) if r["type"] == "RuntimeError"]

    before = len(joins())               # counted, not assumed empty: the crash
                                        # table is global and outlives one test
    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    engine.worker_failed = lambda error: runner.stop()      # what the engine does
    runner.start(FakeScenario(loop=False, duration=5.0), base_settings={})
    _join(runner)

    check("the runner thread ended without a second exception",
          not runner._thread.is_alive())
    check("and the crash log holds the timeline's fault, not a join error",
          len(joins()) == before, f"({[r['type'] for r in joins()]})")


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


def test_a_broken_timeline_stops_the_session_before_it_says_so(monkeypatch):
    """The engine is told FIRST; the line for the user comes after.

    ``log`` is the caller's and can block: on the CLI it is a write to a console
    that a text selection holds until it ends. Said first, it kept the session
    impairing traffic for as long as the console was held (measured 2026-09-28).
    Recorded here as "how many failures had the engine been told about when the
    line was said".
    """
    def explode(*_a, **_kw):
        raise TypeError("a value the engine cannot use")

    monkeypatch.setattr(scenario_runner, "apply_settings", explode)
    monkeypatch.setattr(scenario_runner, "settings_summary", lambda s, lang: "summary")

    engine = FakeEngine()
    said = []
    runner = ScenarioRunner(engine)
    runner.start(FakeScenario(loop=False, duration=5.0), base_settings={},
                 log=lambda line: said.append((len(engine.failures), str(line))))
    _join(runner)

    told_at = [told for told, line in said if "TypeError" in line]
    check("the failure is said", told_at, f"({said!r})")
    check("and only once the engine has been told to stop", told_at == [1],
          f"({said!r})")


# --- a loop, played on virtual time ------------------------------------------ #
class _Clock:
    """Virtual monotonic time (``ScenarioRunner(clock=...)``)."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class _Ticks:
    """The runner's doorbell, where every wait is one tick of virtual time.

    0.3 s and not the real 0.1: a tick that never lands on the last step's `at`
    is exactly the case that skipped it (external review P2-3), so the test must
    not be lucky. The engine goes down after ``ticks`` waits.
    """

    def __init__(self, clock, engine, ticks, step=0.3):
        self.clock, self.engine, self.left, self.step = clock, engine, ticks, step

    def wait(self, timeout):
        self.clock.t += self.step
        self.left -= 1
        if self.left <= 0:
            self.engine.running = False

    def set(self):
        pass

    def clear(self):
        pass


def _loop_virtually(monkeypatch, ticks):
    """Play a 10 s loop - loss 1 from 0 s, loss 5 plus a reset at 10 s - on virtual
    time; return the (time, loss) of every apply and the (time, duration) of every
    reset, times counted from the start."""
    from beantester.scenario import parse_scenario
    from beantester.settings import DEFAULT_SETTINGS
    clock, engine = _Clock(), FakeEngine()
    applied = []
    monkeypatch.setattr(scenario_runner, "apply_settings",
                        lambda eng, s, log=None, live=None:
                        applied.append((clock.t - 1000.0, s["loss"])))
    monkeypatch.setattr(scenario_runner, "settings_summary", lambda s, lang: "summary")
    resets = []
    engine.reset_now = lambda duration: resets.append((clock.t - 1000.0, duration))
    scenario = parse_scenario({"loop": True, "steps": [
        {"at": 0, "settings": {"loss": 1}},
        {"at": 10, "settings": {"loss": 5}, "action": "reset_tcp", "duration": 2}]})
    runner = ScenarioRunner(engine, clock=clock)
    runner._wake = _Ticks(clock, engine, ticks)
    runner._stop = False
    runner._thread = threading.current_thread()     # played on this thread
    runner._base = dict(DEFAULT_SETTINGS)
    runner._timeline(scenario, lambda *_: None)
    return applied, resets


def test_a_loop_plays_its_last_step_before_it_starts_over(monkeypatch):
    """Owner decision D-5: the last step's settings AND its action, every cycle.

    The runner wrapped the moment the clock passed the last `at`, before asking
    the timeline what was due there. Unless a tick landed exactly on it, the last
    step never ran - in `congested-vpn` and `overloaded-game-server` it is the
    recovery phase (external review P2-3).
    """
    applied, resets = _loop_virtually(monkeypatch, ticks=1700)      # ~510 s
    last_steps = [t for t, loss in applied if loss == 5]
    check("50 cycles, the last step applied in every one", len(last_steps) >= 50,
          f"({len(last_steps)} of ~51)")
    check("and its reset fired every time, with its own duration",
          len(resets) == len(last_steps) and {d for _, d in resets} == {2.0},
          f"({len(resets)} resets, {len(last_steps)} applies)")


def test_a_loop_does_not_drift(monkeypatch):
    """Cycle k begins at k x 10 s, whatever the ticks do.

    Each wrap used to restart the cycle from "now", throwing away however far the
    tick had overshot the end - up to a tick per cycle, adding up. Here a cycle
    starts where the loss goes back to 1.
    """
    applied, _ = _loop_virtually(monkeypatch, ticks=1700)
    starts = [t for t, loss in applied if loss == 1][1:51]         # cycles 1..50
    late = [(k, round(t - 10.0 * k, 3)) for k, t in enumerate(starts, 1)
            if not 0.0 <= t - 10.0 * k < 0.3 + 1e-6]
    check("50 cycle starts, each within one tick of k x 10 s",
          len(starts) == 50 and not late, f"(late: {late[:5]}, count {len(starts)})")


# --- "Apply changes" while the timeline runs (owner decision D-6) ------------ #
class _TicksWith(_Ticks):
    """``_Ticks`` that runs ``on_tick[n]`` after its n-th wait: on the runner's
    own thread and outside its lock, where an Apply lands between two ticks."""

    def __init__(self, clock, engine, ticks, on_tick):
        super().__init__(clock, engine, ticks)
        self.on_tick, self.n = on_tick, 0

    def wait(self, timeout):
        super().wait(timeout)
        self.n += 1
        if self.n in self.on_tick:
            self.on_tick[self.n]()


_START = {"loss": 0, "target": "a.exe"}
_APPLY = {"loss": 20, "target": "b.exe"}


def _steps(*losses):
    """A timeline setting ``loss`` at 0 s, 10 s, 20 s... - and nothing else."""
    from beantester.scenario import parse_scenario
    return parse_scenario({"steps": [{"at": 10 * i, "settings": {"loss": loss}}
                                     for i, loss in enumerate(losses)]})


def _spy_rebase_run(monkeypatch, apply_after_tick, apply=None):
    """Play loss 1 at 0 s and loss 5 at 10 s in the runner's thread on 0.3 s
    virtual ticks, with an Apply after tick ``apply_after_tick``; return every
    apply as (time, loss, target)."""
    from beantester.settings import DEFAULT_SETTINGS
    clock, engine = _Clock(), FakeEngine()
    applied = []
    monkeypatch.setattr(scenario_runner, "apply_settings", lambda eng, s, log=None, live=None: applied.append(
        (round(clock.t - 1000.0, 1), s["loss"], s["target"])))
    monkeypatch.setattr(scenario_runner, "settings_summary", lambda s, lang: "summary")
    runner = ScenarioRunner(engine, clock=clock)
    base = dict(DEFAULT_SETTINGS, **_START)
    runner._wake = _TicksWith(clock, engine, 60, {
        apply_after_tick: lambda: runner.rebase(dict(base, **_APPLY))})
    runner.start(_steps(1, 5), base)
    _join(runner, 5.0)
    return applied


def test_an_apply_stands_until_the_timeline_moves_and_the_next_step_builds_on_it(monkeypatch):
    """External review P2-17: the base was frozen at START.

    The step after an Apply put back everything it had changed - the target
    included - and a step whose settings had not changed was re-applied over it
    at the next tick. Now Apply is applied at once, nothing touches it while the
    step stays the same, and the next step is laid over the Apply's settings.
    """
    applied = _spy_rebase_run(monkeypatch, apply_after_tick=10)       # at 3 s
    check("start, the Apply, then the next step over the Apply's target",
          applied == [(0.0, 1, "a.exe"), (3.0, 20, "b.exe"), (10.2, 5, "b.exe")],
          f"({applied})")


def test_an_apply_in_the_tick_a_step_begins_does_not_swallow_the_step(monkeypatch):
    """The timeline moved on the same tick: the new step still goes on, over
    the Apply. Treating it as "nothing moved since the Apply" skipped it."""
    applied = _spy_rebase_run(monkeypatch, apply_after_tick=34)       # at 10.2 s
    check("the Apply, then the step that began in the same tick, over it",
          applied == [(0.0, 1, "a.exe"), (10.2, 20, "b.exe"), (10.2, 5, "b.exe")],
          f"({applied})")


def test_an_apply_waits_for_a_step_being_applied(monkeypatch):
    """A step half-applied when an Apply arrives must finish FIRST.

    Otherwise the step, computed on the old base, lands after the Apply and puts
    the old target back - and the timeline, already on the new base, sees no
    reason to correct it until the next step. The runner applies both under one
    lock: here the step is held inside ``apply_settings`` while an Apply comes in
    from another thread, the way the window's "Apply changes" does.
    """
    from beantester.settings import DEFAULT_SETTINGS
    clock, engine = _Clock(), FakeEngine()
    applied, entered, release = [], threading.Event(), threading.Event()
    runner = ScenarioRunner(engine, clock=clock)

    def spy(eng, s, log=None, live=None):
        applied.append((s["loss"], s["target"]))
        if s["loss"] == 5 and threading.current_thread() is runner._thread:
            entered.set()
            release.wait(5)

    monkeypatch.setattr(scenario_runner, "apply_settings", spy)
    monkeypatch.setattr(scenario_runner, "settings_summary", lambda s, lang: "summary")
    base = dict(DEFAULT_SETTINGS, **_START)
    runner._wake = _Ticks(clock, engine, 100)
    runner.start(_steps(1, 5, 9), base)
    try:
        assert entered.wait(5), "the step at 10 s was never applied"
        apply = threading.Thread(target=runner.rebase, args=(dict(base, **_APPLY),))
        apply.start()
        apply.join(0.3)
        waited = apply.is_alive()
    finally:
        release.set()
    apply.join(5)
    _join(runner, 5.0)
    check("the Apply waited for the step being applied", waited, f"({applied})")
    check("so the step came first and the Apply's target is what stayed",
          applied.index((5, "a.exe")) < applied.index((20, "b.exe"))
          and applied[-1][1] == "b.exe", f"({applied})")


def test_an_apply_after_the_timeline_ended_is_left_to_the_caller(spy_apply):
    """A finished (or stopped) timeline applies nothing: the window applies
    the settings itself, so they are not applied twice or dropped."""
    engine = FakeEngine()
    runner = ScenarioRunner(engine)
    check("no timeline, nothing applied", runner.rebase({"loss": 3}) is False
          and spy_apply == [], f"({spy_apply})")
