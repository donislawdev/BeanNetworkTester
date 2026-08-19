"""The CLI as a CI/CD citizen: exit codes, timing, output channels, assertions.

Everything here used to be untested: ``tests/test_cli.py`` only ever exercised
the argument parser, so the *runner* could (and did) return 0 for a missing
scenario file, overshoot ``--duration`` by an entire ``--interval``, print
errors to stdout and crash with a traceback on an unwritable path.

The report loop takes its clock and its sleep function as arguments, so the
timing tests run in microseconds instead of seconds.
"""
import io
import json
import os
import time

from beantester import cli as cli_module
from beantester import exitcodes, winenv
from beantester.cli import (_Terminated, _print_conns, build_arg_parser,
                            config_from_args, run_cli)
from fakes import check


class FakeClock:
    """Virtual time: ``sleep`` moves the clock instead of blocking."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += max(0.0, float(seconds))


def cli(argv, clock=None, out=None, err=None):
    """Run the CLI on virtual time; returns ``(code, stdout, stderr)``."""
    clock = clock or FakeClock()
    out = out if out is not None else io.StringIO()
    err = err if err is not None else io.StringIO()
    code = run_cli(argv, sleep=clock.sleep, clock=clock, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


# --- timing: --duration must mean what it says ----------------------------- #


def test_duration_stops_at_the_deadline_not_at_the_next_report():
    """Regression: --duration 3 --interval 2 used to run for 4 s."""
    clock = FakeClock()
    code, _, _ = cli(["--simulate", "--duration", "3", "--interval", "2"], clock=clock)
    check("duration: exits OK", code == exitcodes.OK, f"(code={code})")
    check("duration: stops at 3 s, not at the next 2 s tick",
          abs(clock.t - 3.0) < 0.01, f"(ran {clock.t}s)")


def test_a_short_duration_beats_a_long_interval():
    """Regression: --duration 1 --interval 5 used to run for 5 s."""
    clock = FakeClock()
    code, _, _ = cli(["--simulate", "--duration", "1", "--interval", "5"], clock=clock)
    check("duration: honoured below one report interval",
          code == exitcodes.OK and abs(clock.t - 1.0) < 0.01, f"(ran {clock.t}s)")


def test_reports_are_emitted_every_interval():
    clock = FakeClock()
    code, out, _ = cli(["--simulate", "--duration", "5", "--interval", "1",
                        "--format", "json"], clock=clock)
    samples = [json.loads(line) for line in out.strip().splitlines()
               if '"sample"' in line]
    check("interval: one report per second", len(samples) == 5, f"({len(samples)})")
    check("interval: report timestamps advance",
          [s["t"] for s in samples] == [1.0, 2.0, 3.0, 4.0, 5.0],
          f"({[s['t'] for s in samples]})")
    check("interval: run ends OK", code == exitcodes.OK)


# --- exit codes ------------------------------------------------------------- #


def test_exit_code_ok():
    code, _, _ = cli(["--simulate", "--duration", "1"])
    check("exit: a clean run is 0", code == exitcodes.OK, f"(code={code})")


def test_exit_code_config_for_bad_input():
    cases = {
        "unknown preset": ["--preset", "nope", "--simulate"],
        "bad expression": ["--dst-port", "80,abc", "--simulate"],
        "bad schedule": ["--rate-schedule", "1:x:2", "--simulate"],
        "out of range": ["--loss", "250", "--simulate"],
        "negative duration": ["--duration", "-5", "--simulate"],
        "zero interval": ["--interval", "0", "--simulate"],
    }
    for name, argv in cases.items():
        code, out, err = cli(argv)
        check(f"exit: {name} -> CONFIG(3)", code == exitcodes.CONFIG, f"(code={code})")
        check(f"exit: {name} explains itself on stderr", "error:" in err, f"({err!r})")
        check(f"exit: {name} keeps stdout clean", out == "", f"({out!r})")


def test_exit_code_scenario_when_the_scenario_file_is_missing():
    """Regression: a missing scenario file used to end in a GREEN run."""
    code, _, err = cli(["--simulate", "--duration", "1",
                        "--scenario", "definitely-not-here.json"])
    check("exit: missing scenario -> SCENARIO(4)", code == exitcodes.SCENARIO,
          f"(code={code})")
    check("exit: the scenario error is reported", "scenario error" in err.lower())


def test_exit_code_io_for_unwritable_artifacts(tmp_path):
    missing = str(tmp_path / "no_such_dir" / "x.json")
    code, _, err = cli(["--simulate", "--save-config", missing])
    check("exit: unwritable --save-config -> IO(5)", code == exitcodes.IO, f"({code})")
    check("exit: no traceback leaks", "Traceback" not in err)

    code, _, _ = cli(["--simulate", "--duration", "1", "--repro-out", missing])
    check("exit: unwritable --repro-out -> IO(5)", code == exitcodes.IO, f"({code})")


def test_exit_code_assertion_when_nothing_was_captured():
    code, _, err = cli(["--simulate", "--duration", "1", "--min-packets", "999999999"])
    check("exit: --min-packets not met -> ASSERTION(6)", code == exitcodes.ASSERTION,
          f"(code={code})")
    check("exit: the assertion says why", "expected at least" in err)


def test_the_connection_listing_survives_a_row_with_no_ports():
    """`--log-conns` must not die on a ping row.

    The listing pads the ports with a width spec, and `format(None, '<6')` is a
    TypeError, not a blank - it would take the whole run's output down. Rows
    without ports could not occur until ICMP started reaching the connection log,
    so this guard arrived with them.
    """
    lines = []

    class _Log:
        def info(self, msg):
            lines.append(msg)

    class _Engine:
        def connections_snapshot(self, limit=30):
            return [dict(remote_ip="8.8.8.8", remote_port=None, local_port=None,
                         packets=7, bytes=686, dir="out", proto="ICMP"),
                    dict(remote_ip="1.1.1.1", remote_port=443, local_port=5000,
                         packets=2, bytes=200, dir="out", proto="TCP")]

    _print_conns(_Engine(), _Log())
    body = "\n".join(lines)
    check("conns listing: both rows printed", len(lines) == 3, f"({lines})")
    check("conns listing: the portless row shows a placeholder, not None",
          "8.8.8.8:-" in body and "None" not in body, f"({body})")
    check("conns listing: a normal row still shows its ports",
          "1.1.1.1:443" in body and "local:5000" in body, f"({body})")


# --- targeting: a target that stops matching must not be silent ------------- #


def _engine_stats(**over):
    """A stats dict with the ENGINE's own key set.

    Copied from a real ``BeanEngine`` rather than written out here, so a counter
    added to the engine cannot leave this fake answering with a key the CLI
    reads. Constructing one starts no threads (they belong to ``start()``).
    """
    from beantester.engine import BeanEngine
    stats = dict(BeanEngine().st)
    stats["queue"] = 0
    stats.update(over)
    return stats


class _ScriptedTargeting:
    """A ``ProcessTargeting`` stand-in whose verdict can move mid-run."""

    def __init__(self, description="probe.exe"):
        self.matched = True
        self.description = description

    def refresh(self, *_a, **_k):
        return frozenset()

    def describe(self):
        return self.description if self.matched else "(none)"

    def pids(self):
        return {4242} if self.matched else set()

    def __len__(self):
        return 1 if self.matched else 0


class _TargetedEngine:
    """Enough engine to run a session that HAS a live process target.

    A real engine cannot play this part: ``--target`` is stripped in
    ``--simulate`` (synthetic ports belong to nobody), and a real capture needs
    WinDivert and an elevated token - the environment dependence this file
    already pays for twice over. ``flip_at`` is which poll of ``targeting()``
    the target stops matching on, i.e. the moment the targeted process exits.
    """

    fault = False

    def __init__(self, flip_at=None, **stats):
        self.target = _ScriptedTargeting()
        self.flip_at = flip_at
        self.polls = 0
        self.stats = _engine_stats(**stats)

    def set_seed(self, *_a, **_k): pass
    def set_params(self, *_a, **_k): pass
    def set_buffer(self, *_a, **_k): pass
    def set_dest(self, *_a, **_k): pass
    def set_lan(self, *_a, **_k): pass
    def set_internet_only(self, *_a, **_k): pass
    def set_block(self, *_a, **_k): pass
    def set_advanced(self, *_a, **_k): pass
    def set_spike(self, *_a, **_k): pass
    def set_nat(self, *_a, **_k): pass
    def set_rst(self, *_a, **_k): pass
    def set_flap(self, *_a, **_k): pass
    def set_schedule(self, *_a, **_k): pass
    def set_target(self, *_a, **_k): pass
    def start(self, *_a, **_k): pass
    def stop(self, *_a, **_k): pass
    def is_running(self): return True
    def effective_seed(self): return 7
    def connections_snapshot(self, limit=None): return []
    def stats_snapshot(self): return dict(self.stats)

    def target_for(self, _matcher):
        return self.target

    def targeting(self):
        self.polls += 1
        if self.flip_at is not None and self.polls >= self.flip_at:
            self.target.matched = False
        return self.target


def _targeted_run(monkeypatch, engine, argv):
    """One CLI run with a process target, on virtual time.

    ``is_admin`` is forced because a targeted run is by definition not
    ``--simulate``: without this the test would pass on an elevated shell and on
    Linux CI, and fail on a plain Windows shell - a third environment-dependent
    result in a file that already documents two.
    """
    monkeypatch.setattr(cli_module.winenv, "is_admin", lambda: True)
    clock = FakeClock()
    out, err = io.StringIO(), io.StringIO()
    code = run_cli(argv, sleep=clock.sleep, clock=clock, engine=engine,
                   out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_the_run_says_when_the_process_target_stops_matching(monkeypatch):
    """A targeted process that exits mid-run used to be invisible from the CLI.

    MEASURED 2026-07-28 against a real capture (elevated, real WinDivert):
    targeting a PID and then restarting that process left 5 of 5 fresh
    connections untouched, and the only targeting line in the entire run was the
    one printed at start - exit code OK, nothing else said. The GUI re-reads that
    verdict on every tick and raises a banner; the CLI, which is the CI/CD
    interface, said nothing at all.

    Also pins the other half: the message belongs to the CHANGE. Reporting the
    verdict every interval would bury it in the sample stream.
    """
    lost = _TargetedEngine(flip_at=3, seen=500, scoped_seen=40)
    code, _, err = _targeted_run(monkeypatch, lost,
                                 ["--target", "probe.exe", "--duration", "5",
                                  "--interval", "1"])
    check("target: a target that dies does not end the run", code == exitcodes.OK,
          f"(code={code})")
    check("target: losing the target is reported", "no longer matches" in err,
          f"({err!r})")
    check("target: it is said once, not every interval",
          err.count("no longer matches") == 1, f"({err!r})")

    kept = _TargetedEngine(seen=500, scoped_seen=40)
    _, _, quiet = _targeted_run(monkeypatch, kept,
                                ["--target", "probe.exe", "--duration", "5",
                                 "--interval", "1"])
    check("target: a target that keeps matching says nothing new",
          "no longer matches" not in quiet, f"({quiet!r})")


def test_a_target_that_caught_nothing_is_called_out_at_the_end(monkeypatch):
    """`--min-packets` guards the capture FILTER; this guards the TARGET.

    They fail differently: traffic can flow for the whole run while the targeted
    process never matches, and that run impairs nothing and still exits 0. The
    engine has always counted it (`scoped_seen`) - it just never left the JSON
    summary's `counters`.
    """
    caught_nothing = _TargetedEngine(seen=500, scoped_seen=0)
    _, _, err = _targeted_run(monkeypatch, caught_nothing,
                              ["--target", "probe.exe", "--duration", "2"])
    check("scope: a target that caught nothing is called out",
          "caught nothing" in err, f"({err!r})")
    # In text mode the summary goes down the LOG channel (_emit_summary); in
    # --format json it is the counters of the summary record instead.
    check("scope: the summary says how much was in scope",
          "In scope: 0 of 500" in err, f"({err!r})")

    worked = _TargetedEngine(seen=500, scoped_seen=40)
    _, _, err = _targeted_run(monkeypatch, worked,
                              ["--target", "probe.exe", "--duration", "2"])
    check("scope: a target that DID catch traffic is not accused",
          "caught nothing" not in err, f"({err!r})")
    check("scope: and its share is still reported", "In scope: 40 of 500" in err,
          f"({err!r})")

    # Nothing captured at all is the FILTER's story, and --min-packets is the
    # flag that tells it. Saying both would point the user at the wrong thing.
    silent = _TargetedEngine(seen=0, scoped_seen=0)
    _, _, err = _targeted_run(monkeypatch, silent,
                              ["--target", "probe.exe", "--duration", "2"])
    check("scope: no traffic at all is not blamed on the target",
          "caught nothing" not in err, f"({err!r})")


def test_fail_on_no_traffic_is_shorthand_for_min_packets_one():
    args = build_arg_parser().parse_args(["--simulate", "--fail-on-no-traffic"])
    check("--fail-on-no-traffic == --min-packets 1",
          config_from_args(args)["min_packets"] == 1)


def _needs_permission_to_answer(what):
    """Skip, with a reason, when the CLI would refuse before reaching the point.

    Two tests here assert what the CLI does once it is ALLOWED to open the driver.
    On Windows without an elevated shell the permission check answers first, so
    they used to fail - a permanent pair of red lines that this project
    re-diagnosed every few sessions and that a contributor met with no
    explanation. They are skipped instead, so "green means green" holds
    everywhere.

    A skip is not silence: pytest names it and prints the reason. That matters,
    because the alternative - deleting the assertion - would leave the elevated
    run proving less than it does today.
    """
    import pytest

    if os.name == "nt" and not winenv.is_admin():
        pytest.skip("%s needs an elevated shell on Windows: the CLI answers "
                    "PERMISSION(7) before it gets this far" % what)


def test_exit_code_runtime_without_pydivert():
    """A capture that cannot start is RUNTIME, not 0.

    This used to rely on WinDivert being absent from the machine - true on the
    Linux CI, FALSE on the elevated Windows runner (which has pydivert installed
    and admin rights), where a real capture started, saw no traffic and exited 0.
    So the failure is forced deterministically instead: an injected engine whose
    ``start`` raises, exactly as a missing/unopenable driver would.

    The injected engine is still not enough on its own: ``run_cli`` refuses on
    PERMISSION before it ever reaches the engine, so an unelevated Windows shell
    never gets here. Measured, not assumed - forcing ``is_admin()`` False still
    produced ``code=7``.
    """
    _needs_permission_to_answer("a capture that cannot start")

    class _CannotStartEngine:
        fault = False

        def set_seed(self, *_a, **_k): pass
        def set_params(self, *_a, **_k): pass
        def set_buffer(self, *_a, **_k): pass
        def set_dest(self, *_a, **_k): pass
        def set_lan(self, *_a, **_k): pass
        def set_internet_only(self, *_a, **_k): pass
        def set_block(self, *_a, **_k): pass
        def set_advanced(self, *_a, **_k): pass
        def set_spike(self, *_a, **_k): pass
        def set_nat(self, *_a, **_k): pass
        def set_rst(self, *_a, **_k): pass
        def set_flap(self, *_a, **_k): pass
        def set_schedule(self, *_a, **_k): pass
        def set_target(self, *_a, **_k): pass

        def start(self, *_a, **_k):
            raise RuntimeError("WinDivert could not be opened")

        def stop(self, *_a, **_k): pass

    out, err = io.StringIO(), io.StringIO()
    clock = FakeClock()
    code = run_cli(["--loss", "5", "--duration", "1"], sleep=clock.sleep,
                   clock=clock, engine=_CannotStartEngine(), out=out, err=err)
    check("exit: a capture that cannot start -> RUNTIME(1)",
          code == exitcodes.RUNTIME, f"(code={code})")
    check("exit: the driver error goes to stderr",
          "error:" in err.getvalue() and out.getvalue() == "")
    # The REASON has to survive the trip, not just the exit code (audit F1). The
    # engine used to swallow a failed open() and let the capture thread report
    # "WinDivert handle is not open" instead - a symptom naming nothing - so this
    # branch was unreachable and the user never learned it was, say, [WinError 5].
    check("exit: and it says WHY, not just that something failed",
          "WinDivert could not be opened" in err.getvalue(), f"({err.getvalue()!r})")


def test_the_console_also_says_what_to_do_about_a_driver_that_will_not_open(monkeypatch):
    """The window and the console answer the same failure, from one table.

    A driver error is not a GUI problem: whoever hits WinError 433 from a script
    needs the same sentence the window shows ("another copy just closed, wait a
    few seconds"), and the console used to print the raw Win32 error with nothing
    to do about it. ``is_admin`` is forced because a non-elevated run never reaches
    the start at all - it fails earlier, with PERMISSION.
    """
    from beantester.i18n import T

    class _BusyDriverEngine:
        fault = False

        def __getattr__(self, _name):        # every set_* the CLI applies
            return lambda *_a, **_k: None

        def start(self, *_a, **_k):
            error = OSError("[WinError 433] The specified device does not exist.")
            error.winerror = 433
            raise error

        def stop(self, *_a, **_k): pass

    monkeypatch.setattr(cli_module.winenv, "is_admin", lambda: True)
    out, err = io.StringIO(), io.StringIO()
    clock = FakeClock()
    code = run_cli(["--loss", "5", "--duration", "1"], sleep=clock.sleep,
                   clock=clock, engine=_BusyDriverEngine(), out=out, err=err)
    check("exit: a driver that will not open is still RUNTIME(1)",
          code == exitcodes.RUNTIME, f"(code={code})")
    check("the console carries the raw Win32 error",
          "WinError 433" in err.getvalue(), f"({err.getvalue()!r})")
    check("...and the advice that fits it",
          T("dialogs.driver_busy") in err.getvalue(), f"({err.getvalue()!r})")
    check("...and not the elevation advice, which is about a different error",
          T("dialogs.run_as_admin") not in err.getvalue(), f"({err.getvalue()!r})")


class _NeverEnded(BaseException):
    """The report loop outlived its budget: this run does not end on its own.

    ``BaseException``, not ``Exception``, and for a reason worth keeping: the
    session now catches ``Exception`` to turn an unforeseen fault into a coded
    exit (see the fault tests below), which swallowed this signal and made the
    budget look like a clean RUNTIME. Cancellation-shaped exceptions have to
    travel the way ``KeyboardInterrupt`` does - straight out.
    """


def _budgeted_sleep(budget=100, nap=0.05):
    """A real sleep that turns "this run never ends" into a NAMED failure.

    The scenario runner lives on its own thread and reads the wall clock, so the
    ``FakeClock`` used elsewhere in this file cannot drive it. Real time it is -
    but the regression under test is an INFINITE run, and a test that hangs
    reports nothing. Raising ``_NeverEnded`` makes "it never ended" an outcome a
    test can assert in either direction: a failure where the run should stop, and
    an expectation where it genuinely cannot.
    """
    calls = [0]

    def sleep(seconds):
        calls[0] += 1
        if calls[0] > budget:
            raise _NeverEnded(f"{budget} report-loop naps and still going")
        time.sleep(min(seconds, nap))
    return sleep


def _scenario_file(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_a_finished_scenario_ends_the_run_even_without_a_duration(tmp_path):
    """Regression: it printed "Scenario finished." and then ran forever.

    MEASURED 2026-08-01 before the fix: a two-step, non-looping scenario with no
    --duration was still reporting samples when a hard timeout killed it at 12 s
    (exit 124 - a code from `timeout`, not from this tool). In CI that is a job
    that hangs to its timeout, with no summary record and, on a real run, with
    the driver still loaded.
    """
    scen = _scenario_file(tmp_path, "two-steps.json", {"loop": False, "steps": [
        {"at": 0, "settings": {"loss": 5}},
        {"at": 0.2, "settings": {"loss": 50}}]})
    out, err = io.StringIO(), io.StringIO()
    code = run_cli(["--simulate", "--scenario", scen, "--interval", "1",
                    "--format", "json"],
                   sleep=_budgeted_sleep(), out=out, err=err)
    records = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    check("scenario: a finished timeline ends the run", code == exitcodes.OK,
          f"(code={code})")
    check("scenario: the last record is the summary",
          records and records[-1]["event"] == "summary",
          f"({[r['event'] for r in records]})")
    check("scenario: and it says WHY the run ended",
          records[-1]["stop_reason"] == "scenario_done",
          f"({records[-1]['stop_reason']!r})")


def test_an_explicit_duration_still_wins_over_the_scenario(tmp_path):
    """--duration is the user speaking; a derived end must never override it."""
    scen = _scenario_file(tmp_path, "long.json", {"loop": False, "steps": [
        {"at": 0, "settings": {"loss": 5}},
        {"at": 30, "settings": {"loss": 50}}]})
    out, err = io.StringIO(), io.StringIO()
    code = run_cli(["--simulate", "--scenario", scen, "--duration", "0.3",
                    "--interval", "1", "--format", "json"],
                   sleep=_budgeted_sleep(), out=out, err=err)
    records = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    check("scenario: --duration wins", code == exitcodes.OK, f"(code={code})")
    check("scenario: and the reason is the deadline, not the timeline",
          records[-1]["stop_reason"] == "duration",
          f"({records[-1]['stop_reason']!r})")


def test_a_scenario_with_no_timeline_does_not_cut_the_run_short(tmp_path):
    """A one-step scenario is settings, not a timeline - it must not end the run.

    Degenerate but legal input: ``Scenario.duration`` is the ``at`` of the last
    step, so a single step at 0 has duration 0 and the runner reports finished
    within ~0.1 s. Ending the session there would turn "apply these settings"
    into a run that exits immediately - a new bug in place of the old one.
    """
    scen = _scenario_file(tmp_path, "one-step.json", {"loop": False, "steps": [
        {"at": 0, "settings": {"loss": 5}}]})
    out, err = io.StringIO(), io.StringIO()
    run_cli(["--simulate", "--scenario", scen, "--duration", "0.4",
             "--interval", "1", "--format", "json"],
            sleep=_budgeted_sleep(), out=out, err=err)
    records = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    check("scenario: a timeline-less scenario runs to the deadline",
          records[-1]["stop_reason"] == "duration",
          f"({records[-1]['stop_reason']!r})")


def test_a_looping_scenario_runs_to_its_duration_not_to_its_timeline(tmp_path):
    """A loop passes its ``duration`` over and over; that must not end the run."""
    scen = _scenario_file(tmp_path, "looping.json", {"loop": True, "steps": [
        {"at": 0, "settings": {"loss": 5}},
        {"at": 0.2, "settings": {"loss": 50}}]})
    out, err = io.StringIO(), io.StringIO()
    run_cli(["--simulate", "--scenario", scen, "--duration", "0.5",
             "--interval", "1", "--format", "json"],
            sleep=_budgeted_sleep(), out=out, err=err)
    records = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    check("scenario: a looping run ends on its deadline",
          records[-1]["stop_reason"] == "duration",
          f"({records[-1]['stop_reason']!r})")


def test_the_loop_flag_takes_the_derived_ending_away_again(tmp_path):
    """``--loop`` turns a finite file into an endless one, and it must be read.

    ``_run_session`` does ``scen.loop = scen.loop or cfg["loop"]`` BEFORE the end
    is planned, so a file that would otherwise stop the run must stop stopping it
    the moment the flag is passed. Easy to get wrong by reading the file's own
    ``loop`` instead of the effective one, and the failure would be a run that
    ends while the user asked for it to repeat.
    """
    import pytest

    scen = _scenario_file(tmp_path, "finite.json", {"loop": False, "steps": [
        {"at": 0, "settings": {"loss": 5}},
        {"at": 0.2, "settings": {"loss": 50}}]})
    out, err = io.StringIO(), io.StringIO()
    with pytest.raises(_NeverEnded):
        run_cli(["--simulate", "--scenario", scen, "--loop", "--interval", "1"],
                sleep=_budgeted_sleep(budget=12), out=out, err=err)
    check("scenario: --loop takes the derived ending away",
          "will not stop the run on its own" in err.getvalue(),
          f"({err.getvalue()!r})")


def test_an_engine_that_cannot_report_the_scenario_end_says_so(tmp_path):
    """``engine=`` is a public seam, so the double may predate this feature.

    Falling back to the old behaviour is right - the alternative is crashing on
    somebody's test harness - but falling back QUIETLY would restore the hang
    with nothing to explain it. The code claims it reports the fallback; this is
    that claim being checked rather than believed.

    The reason has to be the RIGHT one, too. The first version of this branch
    fell through to the shared warning and told the user the scenario "has a
    single step, so there is no timeline" - about a two-step file with a
    perfectly good timeline. True-sounding prose next to correct code is the
    failure this project spends the most effort on, and a test that only asserted
    "some warning appeared" walked straight past it.
    """
    import pytest

    from beantester.engine import BeanEngine

    class _OlderDouble(BeanEngine):
        scenario_finished = None          # an engine from before this existed

    scen = _scenario_file(tmp_path, "finite.json", {"loop": False, "steps": [
        {"at": 0, "settings": {"loss": 5}},
        {"at": 0.2, "settings": {"loss": 50}}]})
    out, err = io.StringIO(), io.StringIO()
    with pytest.raises(_NeverEnded):
        run_cli(["--simulate", "--scenario", scen, "--interval", "1"],
                sleep=_budgeted_sleep(budget=12), engine=_OlderDouble(),
                out=out, err=err)
    log = err.getvalue()
    check("scenario: an engine that cannot answer falls back to the old ending",
          "cannot report when a scenario ends" in log, f"({log!r})")
    check("scenario: and the reason given is that one, not a made-up one",
          "single step" not in log and "it repeats" not in log, f"({log!r})")


def test_a_scenario_that_cannot_end_the_run_says_so_up_front(tmp_path):
    """Half the fix for the hang is honesty about the half that still hangs.

    A looping scenario has no end to derive and a one-step one has no timeline,
    so with no --duration these runs genuinely go on forever - as they always
    have. What was missing is anybody saying so: the run printed "Running.
    Ctrl+C to stop." and left the reader to find out. ``_NeverEnded`` here is the
    EXPECTED outcome, which is exactly why the warning has to be there.
    """
    import pytest

    for name, payload in (
            ("loops.json", {"loop": True, "steps": [
                {"at": 0, "settings": {"loss": 5}},
                {"at": 0.2, "settings": {"loss": 50}}]}),
            ("single.json", {"loop": False, "steps": [
                {"at": 0, "settings": {"loss": 5}}]})):
        scen = _scenario_file(tmp_path, name, payload)
        out, err = io.StringIO(), io.StringIO()
        with pytest.raises(_NeverEnded):
            run_cli(["--simulate", "--scenario", scen, "--interval", "1"],
                    sleep=_budgeted_sleep(budget=12), out=out, err=err)
        check(f"scenario: {name} warns that the run will not stop on its own",
              "will not stop the run on its own" in err.getvalue(),
              f"({err.getvalue()!r})")


# --- an unforeseen fault is still a coded exit ------------------------------- #


def test_an_unexpected_session_fault_is_a_coded_exit_with_a_full_summary():
    """``cli.py`` promises "never a raw traceback"; the session path had no net.

    ``test_cli_fuzz.py`` proves it for the PARSING surface only - every case
    there runs under --dry-run. MEASURED 2026-08-01: a RuntimeError raised inside
    the report loop escaped ``run_cli`` entirely - no ``[bean] error:`` line, no
    summary record, a Python traceback and CPython's exit 1 (which collides with
    RUNTIME, so a job could not even tell the two apart).
    """
    from beantester.engine import BeanEngine

    class _FaultsMidRun(BeanEngine):
        def __init__(self):
            super().__init__()
            self._passes = 0

        def is_running(self):
            self._passes += 1
            if self._passes > 3:
                raise RuntimeError("driver read failed mid-run")
            return super().is_running()

    out, err = io.StringIO(), io.StringIO()
    clock = FakeClock()
    code = run_cli(["--simulate", "--duration", "0", "--interval", "1",
                    "--format", "json"], sleep=clock.sleep, clock=clock,
                   engine=_FaultsMidRun(), out=out, err=err)
    records = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    check("fault: an unforeseen error is RUNTIME, not a traceback",
          code == exitcodes.RUNTIME, f"(code={code})")
    check("fault: it says what happened, on stderr",
          "driver read failed mid-run" in err.getvalue(), f"({err.getvalue()!r})")
    check("fault: the data channel still gets a complete summary",
          records and records[-1]["event"] == "summary"
          and "counters" in records[-1],
          f"({[r['event'] for r in records]})")
    check("fault: and the summary says the run faulted",
          records[-1]["stop_reason"] == "fault", f"({records[-1]['stop_reason']!r})")


def test_a_fault_outside_the_session_is_still_a_coded_exit():
    """The last-resort backstop: even the summary path itself may not crash out.

    Distinct from the test above: there the session is alive and can still be
    summarised. Here the failure is in building the result, so there is nothing
    to report - but a raw traceback and an uncoded exit are still forbidden.
    """
    from beantester.engine import BeanEngine

    class _FaultsOnSummary(BeanEngine):
        def stats_snapshot(self):
            raise RuntimeError("counters went away")

    out, err = io.StringIO(), io.StringIO()
    clock = FakeClock()
    code = run_cli(["--simulate", "--duration", "1", "--interval", "1"],
                   sleep=clock.sleep, clock=clock, engine=_FaultsOnSummary(),
                   out=out, err=err)
    check("fault: a broken summary path is RUNTIME, not a traceback",
          code == exitcodes.RUNTIME, f"(code={code})")
    check("fault: and it still names the cause",
          "counters went away" in err.getvalue(), f"({err.getvalue()!r})")
    # One fault, two failed steps (the loop, then the report it needed the same
    # broken call for). Both get a line, and the lines have to be TELLABLE APART
    # or they read as two separate bugs.
    lines = [l for l in err.getvalue().splitlines() if "unexpected failure" in l]
    check("fault: each failed step is described as itself",
          len(set(lines)) == len(lines), f"({lines})")


def test_exit_code_interrupted_and_terminated():
    def boom_interrupt(_s):
        raise KeyboardInterrupt()

    def boom_term(_s):
        raise _Terminated()

    code = run_cli(["--simulate", "--duration", "5"], sleep=boom_interrupt,
                   out=io.StringIO(), err=io.StringIO())
    check("exit: Ctrl+C -> 130", code == exitcodes.INTERRUPTED, f"(code={code})")

    code = run_cli(["--simulate", "--duration", "5"], sleep=boom_term,
                   out=io.StringIO(), err=io.StringIO())
    check("exit: SIGTERM -> 143", code == exitcodes.TERMINATED, f"(code={code})")


def test_usage_errors_keep_argparse_exit_code_2():
    raised = None
    try:
        build_arg_parser().parse_args(["--nope"])
    except SystemExit as e:
        raised = e.code
    check("exit: unknown flag -> USAGE(2)", raised == exitcodes.USAGE, f"({raised})")


def test_gui_flag_combined_with_settings_is_a_usage_error():
    """``--gui --loss 30`` must not quietly become a headless impairment run.

    ``main()`` routes a bare ``--gui`` to the GUI, so the flag only reaches the CLI
    runner when it was combined with something else. That used to be accepted and
    then ignored: the flag advertised "force the GUI" and instead started a session
    with no window and no STOP button - on a tool that breaks the user's network.
    """
    code, out, err = cli(["--gui", "--loss", "30", "--duration", "600"])
    check("--gui + settings -> USAGE(2)", code == exitcodes.USAGE, f"(code={code})")
    check("--gui: the reason is on stderr", "--gui" in err, f"({err!r})")
    # a failed run never writes to the data channel (same contract as test_cli_fuzz)
    check("--gui: stdout stays clean", not out.strip(), f"({out!r})")


# --- output channels -------------------------------------------------------- #


def test_logs_go_to_stderr_and_data_to_stdout():
    code, out, err = cli(["--simulate", "--duration", "2", "--interval", "1"])
    check("channels: the log is on stderr", "[bean]" in err, f"({err!r})")
    check("channels: stdout carries only data", "[bean]" not in out, f"({out!r})")
    check("channels: reports land on stdout", "down=" in out)
    check("channels: run OK", code == exitcodes.OK)


def test_json_format_is_parsable_ndjson():
    code, out, _ = cli(["--simulate", "--seed", "42", "--duration", "2",
                        "--interval", "1", "--format", "json"])
    records = [json.loads(line) for line in out.strip().splitlines()]
    kinds = [r["event"] for r in records]
    check("json: samples then a summary", kinds == ["sample", "sample", "summary"],
          f"({kinds})")
    summary = records[-1]
    check("json: the summary carries the exit code",
          summary["exit_code"] == exitcodes.OK and summary["exit_name"] == "OK")
    check("json: the summary carries the stop reason",
          summary["stop_reason"] == "duration", f"({summary['stop_reason']})")
    check("json: the summary carries the seed and a repro command",
          summary["seed"] == 42 and "--seed 42" in summary["repro_command"],
          f"({summary.get('repro_command')})")
    check("json: run OK", code == exitcodes.OK)


def test_quiet_prints_nothing_but_errors():
    code, out, err = cli(["--simulate", "--duration", "2", "--interval", "1", "-q"])
    check("quiet: no reports", out == "", f"({out!r})")
    check("quiet: no log", err == "", f"({err!r})")
    check("quiet: still succeeds", code == exitcodes.OK)

    code, _, err = cli(["--simulate", "--duration", "1", "-q", "--min-packets", "999999999"])
    check("quiet: errors still surface", code == exitcodes.ASSERTION and "[bean]" in err)


def test_verbose_says_what_the_tool_is_doing():
    _, _, err = cli(["--simulate", "--duration", "1", "-v",
                     "--dst-port", "443", "--loss", "5"])
    for needle in ("effective settings", "WinDivert filter", "matcher dst_port",
                   "opening the divert"):
        check(f"verbose: logs {needle!r}", needle in err, f"({err!r})")


def test_log_file_captures_the_session(tmp_path):
    path = str(tmp_path / "run.log")
    cli(["--simulate", "--duration", "1", "--interval", "1", "--log-file", path])
    text = open(path, encoding="utf-8").read()
    check("--log-file: the log is on disk", "Running" in text, f"({text!r})")
    check("--log-file: reports are on disk too", "down=" in text)


# --- CI helpers -------------------------------------------------------------- #


def test_dry_run_validates_without_starting_anything():
    code, out, err = cli(["--simulate", "--loss", "5", "--dry-run"])
    check("--dry-run: valid config exits OK", code == exitcodes.OK, f"({code})")
    check("--dry-run: nothing was started", "Running" not in err and out == "")

    code, _, _ = cli(["--dry-run", "--dst-ip", "10.0.0.1-2001:db8::1"])
    check("--dry-run: an invalid config still fails", code == exitcodes.CONFIG)


def test_dry_run_catches_a_misspelled_setting_in_a_config_file(tmp_path):
    """The preflight's whole job: find out whether the next command will work.

    MEASURED before: ``{"loss": 10, "latancy": 300}`` passed --dry-run with
    "Configuration is valid" and exit 0, and the real run then went out with
    latency 0 - a green pipeline that impaired less than it was told to.
    """
    path = tmp_path / "typo.json"
    path.write_text(json.dumps({"loss": 10, "latancy": 300}), encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    code = run_cli(["--dry-run", "--config", str(path)], out=out, err=err)
    check("preflight: a typo in the config file is CONFIG(3)",
          code == exitcodes.CONFIG, f"(code={code})")
    check("preflight: and the message names the key",
          "latancy" in err.getvalue(), f"({err.getvalue()!r})")
    check("preflight: a failed check writes nothing to the data channel",
          not out.getvalue().strip(), f"({out.getvalue()!r})")


def test_dry_run_says_what_it_did_not_check():
    """It validates the CONFIGURATION; it is documented as answering more.

    MEASURED: with ``is_admin()`` false, --dry-run returns 0 and says
    "Configuration is valid" while the very next real run exits PERMISSION(7).
    Widening the check would break validating a config on a build box and running
    it elsewhere, so the honest fix is the sentence: say which half was checked
    and name the command that does the other half.
    """
    out, err = io.StringIO(), io.StringIO()
    code = run_cli(["--dry-run", "--loss", "10"], out=out, err=err)
    check("preflight: a good config is still OK", code == exitcodes.OK,
          f"(code={code})")
    check("preflight: the success line points at --doctor for the environment",
          "--doctor" in err.getvalue(), f"({err.getvalue()!r})")


def test_print_config_dumps_the_effective_settings():
    code, out, _ = cli(["--print-config", "--preset", "presets.3g", "--loss", "7"])
    settings = json.loads(out)
    check("--print-config: exits OK", code == exitcodes.OK)
    check("--print-config: flags beat the preset", settings["loss"] == 7)
    # from the source, not a copy: this asserts that a preset REACHES the dump,
    # not what 3G happens to be tuned to this month
    from beantester.presets import PRESETS
    check("--print-config: the preset is applied",
          settings["latency"] == PRESETS["presets.3g"]["lat"],
          f"({settings['latency']})")
    check("--print-config: duration is part of the model", "duration" in settings)


def test_doctor_says_where_the_users_own_files_are():
    """The one environment fact a person cannot look up for themselves.

    The folder follows the ACCOUNT the program runs as, so the same person gets a
    different one when they start it elevated onto another account. Nothing else in
    the program says where it is, which is what made that silent.

    No admin rights needed: this line is printed whatever the driver checks decide,
    which is also why it is a line rather than a check with a state.
    """
    from beantester.paths import user_data_dir
    _, out, _ = cli(["--doctor"])
    check("--doctor: names the user's data directory", user_data_dir() in out,
          f"({out[-300:]})")

    _, js, _ = cli(["--doctor", "--format", "json"])
    payload = json.loads(js.strip().splitlines()[0])
    check("--doctor --format json: carries it as a field",
          payload.get("data_dir") == user_data_dir(), f"({payload.get('data_dir')})")


def test_doctor_reports_the_environment():
    code, out, _ = cli(["--doctor"])
    # The two lines it prints are true on any machine, elevated or not.
    check("--doctor: reports python", "python" in out)
    check("--doctor: reports the platform", "platform" in out)
    # The VERDICT is not: without admin rights `driver.doctor()` reports a box
    # that cannot capture, and exit 1 is the right answer there, not a defect.
    _needs_permission_to_answer("--doctor's healthy-box verdict")
    check("--doctor: exits OK on a healthy (simulate-capable) box",
          code == exitcodes.OK, f"({code})")


# --- duration is a first-class setting -------------------------------------- #


def test_duration_is_part_of_the_settings_model():
    args = build_arg_parser().parse_args(["--simulate", "--duration", "12"])
    cfg = config_from_args(args)
    check("duration: lands in the settings dict", cfg["settings"]["duration"] == 12)
    check("duration: drives the run", cfg["duration"] == 12)


def test_duration_flag_does_not_clobber_a_config_file(tmp_path):
    """--duration defaults to None, not 0: an absent flag must not zero the file."""
    from beantester import DEFAULT_SETTINGS, save_config_file
    path = str(tmp_path / "cfg.json")
    s = dict(DEFAULT_SETTINGS)
    s.update(duration=30, loss=4)
    save_config_file(path, s)

    cfg = config_from_args(build_arg_parser().parse_args(["--config", path]))
    check("precedence: the file's duration survives", cfg["settings"]["duration"] == 30,
          f"({cfg['settings']['duration']})")

    cfg = config_from_args(build_arg_parser().parse_args(
        ["--config", path, "--duration", "5"]))
    check("precedence: the flag still wins", cfg["settings"]["duration"] == 5)


def test_duration_survives_the_repro_command():
    from beantester import (DEFAULT_SETTINGS, settings_to_cli,
                            settings_to_cli_string)
    s = dict(DEFAULT_SETTINGS)
    s.update(loss=10, duration=25)
    argv = settings_to_cli(s, seed=1)
    check("repro: --duration is reproduced", "--duration" in argv, f"({argv})")
    parsed = config_from_args(build_arg_parser().parse_args(argv))["settings"]
    check("repro: the duration round-trips", parsed["duration"] == 25)
    check("repro: the command names this build",
          settings_to_cli_string(s).startswith("python bean_network_tester.py")
          or settings_to_cli_string(s).startswith("BeanNetworkTester.exe"))


def test_repro_command_follows_a_frozen_build(monkeypatch):
    """A frozen user has no ``python bean_network_tester.py`` to paste."""
    from beantester import DEFAULT_SETTINGS, appinfo, paths, repro
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    cmd = repro.settings_to_cli_string(dict(DEFAULT_SETTINGS, loss=5))
    check("repro: the frozen command is the exe",
          cmd.startswith(appinfo.EXE_NAME), f"({cmd})")


def test_the_saved_config_round_trips_through_the_cli(tmp_path):
    path = str(tmp_path / "out.json")
    code, _, _ = cli(["--simulate", "--loss", "3", "--duration", "7",
                      "--save-config", path])
    check("--save-config: exits OK", code == exitcodes.OK)
    saved = json.load(open(path, encoding="utf-8"))
    check("--save-config: stores the settings",
          saved["loss"] == 3 and saved["duration"] == 7, f"({saved})")
    check("--save-config: the file exists", os.path.exists(path))


# --- warning: a run that damages everything, with nothing to end it -------- #


class _OneTickEngine(_TargetedEngine):
    """Enough engine to finish a run that has no ``--duration``.

    Without a deadline the report loop ends only when the engine stops itself
    (``is_running()`` going false), which is exactly the shape of run this
    warning is about - so a fake that never stops would hang the suite instead
    of testing it. ``started`` records whether the capture was ever opened.
    """

    stop_reason = "user"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.ticks = 0
        self.started = False

    def start(self, *_a, **_k):
        self.started = True

    def is_running(self):
        self.ticks += 1
        return self.ticks < 2


def _real_run(monkeypatch, argv, engine=None):
    """One NON-simulate CLI run on a fake engine, admin gate forced open.

    The warning is deliberately silent in ``--simulate`` (there is no real
    traffic to damage), so proving it needs a real-mode run - which on a plain
    Windows shell has neither an elevated token nor WinDivert. Same seam and the
    same reason as ``_targeted_run`` above.
    """
    monkeypatch.setattr(cli_module.winenv, "is_admin", lambda: True)
    engine = engine or _OneTickEngine(seen=10)
    clock = FakeClock()
    out, err = io.StringIO(), io.StringIO()
    code = run_cli(argv, sleep=clock.sleep, clock=clock, engine=engine,
                   out=out, err=err)
    return code, out.getvalue(), err.getvalue(), engine


def _warned(err):
    from beantester.i18n import translate
    return translate("warn.global_impairment", "en") in err


def test_a_run_that_impairs_everything_forever_says_so_before_it_starts(monkeypatch):
    """The accident this whole audit came from: ``--lat 5`` and nothing else.

    A mistyped flag opened a real capture with no target and no deadline and
    impaired 11 844 packets of a live machine over 202 s before anybody noticed.
    Nothing warned, because nothing looked at the SHAPE of the run - only at
    whether each value was in range. The message goes to stderr, so a pipeline
    reading stdout is untouched (convention 18).
    """
    _, out, err, engine = _real_run(monkeypatch, ["--loss", "50"])
    check("warning: an unscoped, endless impairment is announced", _warned(err))
    check("warning: it goes to stderr, not to the data channel", not _warned(out))
    check("warning: the run still happens (a warning, not a refusal)",
          engine.started)


def test_the_warning_names_lan_mode_which_reads_like_a_scope(monkeypatch):
    """MEASURED in core.decide() step 2b: LAN mode DROPS every public address.

    It is the one flag whose name argues the other way ("only the local
    network"), and on its own, with the whole rest of the form at zero, it cuts
    the machine's internet. It was found by walking the gates in decide() rather
    than by reading the field names, which is the only reason it is here.
    """
    _, _, err, _ = _real_run(monkeypatch, ["--lan-mode"])
    check("warning: LAN mode alone is a machine-wide impairment", _warned(err))


def test_the_warning_names_internet_only_too(monkeypatch):
    """Its mirror cuts the machine's local network the same way, and the name
    reads just as much like a scope ("only the internet") as LAN mode's does.

    The registry is what makes this true - the field declares ``IMPAIRS_ALL`` -
    but a declaration nobody exercises is how the first one got missed, so the
    second gate is asked the question rather than assumed to inherit the answer.
    """
    _, _, err, _ = _real_run(monkeypatch, ["--internet-only"])
    check("warning: Internet only alone is a machine-wide impairment", _warned(err))


def test_the_lan_abbreviation_still_reaches_lan_mode(monkeypatch):
    """🔴 MEASURED, and the reason the new flag is not called ``--lan-cut``.

    argparse keeps ``allow_abbrev`` on here by decision (ADR 2026-08-02: people
    may already be typing ``--lat``), so a SECOND option starting with ``lan-``
    would make ``--lan`` ambiguous and argparse would refuse it outright with
    exit 2 - silently breaking a shortcut of a documented flag. This asserts the
    abbreviation still resolves, which is the property the naming protects.
    """
    parser = cli_module.build_arg_parser()
    args = parser.parse_args(["--lan"])
    check("--lan still means --lan-mode", args.lan_mode is True)
    check("--internet-only did not attach itself to it",
          args.internet_only is False)


def test_a_bounded_run_is_not_warned_about(monkeypatch):
    """Three ways to bound a run, and each one has to buy silence.

    A warning that also fires on careful runs is a warning people learn to skip,
    which would cost exactly the case above.
    """
    for argv, why in (
            (["--loss", "50", "--duration", "5"], "a deadline"),
            (["--loss", "50", "--target", "probe.exe"], "a process target"),
            (["--loss", "50", "--dst-ip", "10.0.0.1"], "a destination"),
            (["--block-ip", "10.0.0.1"], "blocking, which bounds its own damage"),
            (["--simulate", "--loss", "50"], "--simulate, where nothing is real"),
    ):
        _, _, err, _ = _real_run(monkeypatch, argv)
        check(f"warning: silent when the run has {why}", not _warned(err),
              f"({argv})")


def test_dry_run_previews_the_shape_and_not_only_the_values():
    """"Configuration is valid" is about each value. This is about the SHAPE.

    --dry-run is the cheapest place to learn that a config would impair the whole
    machine with nothing to end it: it opens no driver and passes no traffic, and
    it needs no elevated token, so a pipeline can ask the question for free.
    """
    code, _, err = cli(["--dry-run", "--loss", "50"])
    check("--dry-run: still exits OK", code == exitcodes.OK, f"(code={code})")
    check("--dry-run: previews an unbounded config", _warned(err))
    _, _, err = cli(["--dry-run", "--loss", "50", "--duration", "5"])
    check("--dry-run: silent on a bounded config", not _warned(err))


def test_blocking_bounds_only_its_own_damage(monkeypatch):
    """A block is not a target, and this is the pair that proves the difference.

    ``--block-ip`` alone is bounded: it drops traffic to the address it names and
    nothing else, so warning about it would be the false alarm that teaches
    people to ignore the real one. Add ``--loss 50`` and the run is machine-wide
    again - the block scopes the block, not the loss.

    Written because the mutation "blocking counts as a bound for every other
    impairment" SURVIVED the first version of these guards: the silent case alone
    reads identically whether blocking is IMPAIRS_MATCHED or a narrowing field.
    """
    _, _, err, _ = _real_run(monkeypatch, ["--block-ip", "10.0.0.1"])
    check("warning: a block on its own is already bounded", not _warned(err))
    _, _, err, _ = _real_run(monkeypatch, ["--loss", "50", "--block-ip", "10.0.0.1"])
    check("warning: a block does not bound the loss beside it", _warned(err))


def test_a_block_that_matches_everything_is_not_a_bounded_block(monkeypatch):
    """The other side of the test above, and the one that was missing.

    A block bounds its own damage BECAUSE it names something. `--block-ip '*'`
    names everything, so it cuts every connection on this machine - and this is
    the machine Claude Code runs on. MEASURED before the fix: it dropped 5 of 5
    addresses and raised no warning at all, while `--loss 50`, which only
    degrades the link, raised one. The expression that severed the network looked
    safer than the one that slowed it down.

    Same hole as `--target *` (fixed 2026-08-06) seen from the other side, and
    answered by the same `Matcher.covers_everything`.

    The narrow cases below are the half that matters most: they are what makes
    this a fix rather than a new false alarm. `172.*` is included because that is
    how people actually write a prefix.
    """
    for argv, why in (
            (["--block-ip", "*"], "an IP wildcard covering everything"),
            (["--block-port", "*"], "a port wildcard covering everything"),
            (["--block-ip", "re:.*"], "a regular expression matching all"),
            (["--block-ip", "0.0.0.0/0"], "the whole address space as a CIDR"),
    ):
        _, _, err, _ = _real_run(monkeypatch, argv)
        check(f"warning: a block by {why} is machine-wide", _warned(err), f"({argv})")

    for argv, why in (
            (["--block-ip", "172.*"], "a one-octet prefix, the way people write it"),
            (["--block-ip", "10.0.0.1"], "a single address"),
            (["--block-ip", "172.16.0.0/12"], "a real subnet"),
            (["--block-port", "443"], "a single port"),
            (["--block-ip", "*", "--duration", "5"], "everything, but with a deadline"),
            (["--block-ip", "*", "--target", "probe.exe"], "everything, but one process"),
    ):
        _, _, err, _ = _real_run(monkeypatch, argv)
        check(f"warning: silent for {why}", not _warned(err), f"({argv})")


def test_an_exclusion_only_target_is_not_a_bound(monkeypatch):
    """``!chrome.exe`` is non-empty and narrows nothing.

    Every "is a target set?" test written as a truth check reads it as scoped;
    it means "the whole machine except Chrome". See
    ``Matcher.selects_nothing_in_particular``.
    """
    _, _, err, _ = _real_run(monkeypatch, ["--loss", "50", "--target", "!chrome.exe"])
    check("warning: an expression of pure exclusions bounds nothing", _warned(err))


def test_a_target_that_matches_everything_is_not_a_bound_either(monkeypatch):
    """The other half of the same question, and it went the other way.

    ``!chrome.exe`` has no positive term, which the check above already caught.
    ``*`` HAS one - so every truth test, including the one this warning stood on,
    read it as a scope. MEASURED before the fix: ``--loss 100 --target *``
    printed no warning while ``--loss 100`` alone did, i.e. the expression that
    bounds nothing looked safer than no expression at all.

    Both halves now go through ``Matcher.bounds_nothing``. The pairs below are
    the point: each unbounded form is checked beside a genuinely narrow one, so a
    fix that simply warns more often does not pass.
    """
    for expression in ("*", "**", "re:.*", ">0", "0-999999"):
        _, _, err, _ = _real_run(monkeypatch, ["--loss", "50", "--target", expression])
        check(f"warning: --target {expression} bounds nothing", _warned(err), f"({err!r})")

    for expression in ("chrome.exe", "chrome.exe, !chromedriver", "?", "*.exe"):
        _, _, err, _ = _real_run(monkeypatch, ["--loss", "50", "--target", expression])
        check(f"no warning: --target {expression} really does narrow",
              not _warned(err), f"({err!r})")

    # The same rule on a destination, where "everything" is spelled differently.
    for expression in ("0.0.0.0/0", "::/0"):
        _, _, err, _ = _real_run(monkeypatch, ["--loss", "50", "--dst-ip", expression])
        check(f"warning: --dst-ip {expression} covers a whole family",
              _warned(err), f"({err!r})")
    _, _, err, _ = _real_run(monkeypatch, ["--loss", "50", "--dst-ip", "10.0.0.0/8"])
    check("no warning: a real CIDR still bounds", not _warned(err), f"({err!r})")


def test_a_broken_scenario_never_opens_the_capture(monkeypatch, tmp_path):
    """MEASURED before the fix: the run printed "Start.", impaired traffic and
    only THEN said the file was broken.

    The file is readable without touching the driver, and ``--dry-run`` already
    validated it up front - the real path did not. Same exit code as before, so
    no pipeline changes meaning.
    """
    path = tmp_path / "broken.json"
    path.write_text('{"steps": [{"at": 0, "whatever": 1}]}', encoding="utf-8")
    code, _, err, engine = _real_run(monkeypatch, ["--loss", "5", "--scenario", str(path)])
    check("scenario: a broken file still exits SCENARIO",
          code == exitcodes.SCENARIO, f"(code={code})")
    check("scenario: a broken file never opens the capture", not engine.started)
    check("scenario: it says which file", "broken.json" in err, f"({err!r})")


def test_every_bad_value_is_reported_in_one_run(monkeypatch):
    """A command line arrives FINISHED, so one problem per run is the cheapest
    way to make somebody give up on a tool.

    MEASURED before the fix: `--loss 500 --latency -5 --dup 900` named the
    latency and stopped. Three mistakes, three runs.

    The form deliberately still fails on the first field - it is typed into live,
    and complaints about fields nobody has reached yet are noise. The split is
    the point, not an inconsistency (see settings.range_errors).
    """
    code, _, err, _ = _real_run(monkeypatch, ["--loss", "500", "--latency", "-5",
                                              "--dup", "900"])
    check("a bad value still exits CONFIG", code == exitcodes.CONFIG, f"(code={code})")
    for field in ("Loss", "Latency", "Duplication"):
        check(f"the message names {field}", field in err, f"({err!r})")


def test_a_mistyped_preset_is_offered_the_nearest_one(monkeypatch):
    """A closed vocabulary answers a typo with the nearest value, not only the list.

    Seventeen canonical ids is a long list to read, and this tool already
    suggests a nearest match for a mistyped config key and a mistyped scenario
    key - a preset name was the one closed vocabulary left without it.

    The suggestion has to come from what a person can TYPE: searching the ids
    alone finds nothing close to "modemm", because the id carries a prefix the
    user never writes.
    """
    code, _, err, _ = _real_run(monkeypatch, ["--preset", "modemm"])
    check("an unknown preset still exits CONFIG", code == exitcodes.CONFIG, f"(code={code})")
    check("and suggests something", "did you mean" in err, f"({err!r})")
    check("and the suggestion mentions the modem preset", "56k" in err, f"({err!r})")

    # A name close to a translated one resolves through the same vocabulary.
    _, _, err, _ = _real_run(monkeypatch, ["--preset", "satelite"])
    check("a misspelt English name is matched too", "did you mean" in err, f"({err!r})")
