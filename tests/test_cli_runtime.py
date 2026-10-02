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
import threading
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
        # OverflowError out of `re` used to escape as exit 1 with a traceback
        "regex re cannot build": ["--dst-ip", "re:a{99999999999}", "--simulate"],
        "regex too slow per packet": ["--dst-ip", r"re:^([\d:]+)+$", "--simulate"],
        "bad schedule": ["--rate-schedule", "1:x:2", "--simulate"],
        "out of range": ["--loss", "250", "--simulate"],
        "negative duration": ["--duration", "-5", "--simulate"],
        "zero interval": ["--interval", "0", "--simulate"],
        "nan interval": ["--interval", "nan", "--simulate"],
        "infinite interval": ["--interval", "inf", "--simulate"],
        "interval past the ceiling": ["--interval", "86401", "--simulate"],
    }
    for name, argv in cases.items():
        code, out, err = cli(argv)
        check(f"exit: {name} -> CONFIG(3)", code == exitcodes.CONFIG, f"(code={code})")
        check(f"exit: {name} explains itself on stderr", "error:" in err, f"({err!r})")
        check(f"exit: {name} keeps stdout clean", out == "", f"({out!r})")


def test_the_report_interval_is_refused_while_it_is_still_a_number_on_a_command_line():
    """Every rejected interval is rejected by CONFIGURATION, never by the loop.

    ``--interval`` is the only ``type=float`` flag that does not reach
    ``range_errors``: a reporting cadence is not a field in ``fields.py``, because
    it changes nothing about the traffic and belongs in no profile. So it was the
    one numeric door in the program that accepted NaN and infinity, and each of
    them failed differently once the loop had them (measured 2026-09-02):

    * ``nan``  - ``wake > now`` is false forever, so the loop never sleeps. At
      100% of a core, printing nothing, and with no ``--duration`` it never
      returns. Exit code 0.
    * ``inf``  - ``time.sleep`` raises ``OverflowError`` and the session ends as
      a fault.
    * ``1e18`` - the SAME ``OverflowError``, because ``time.sleep`` is int64
      nanoseconds and gives up above ~9.223e9 s. A finiteness test alone would
      have closed two values out of that class, which is why the check is a
      RANGE.

    Asked of ``config_from_args`` rather than of a run, because that is the claim:
    the value dies before anything is started. It also means a regression here
    reports a failure instead of hanging the suite on the loop it describes - on
    virtual time, a NaN interval spins without ever advancing the clock.
    """
    # ``--interval=<value>``, not two tokens: argparse reads a leading "-" as the
    # start of another option, so "-inf" as a separate word never reaches the
    # check this test is about.
    for value in ("nan", "inf", "-inf", "1e18", "86400.5"):
        args = build_arg_parser().parse_args(["--simulate", f"--interval={value}"])
        try:
            config_from_args(args)
        except SystemExit as exc:
            check(f"interval {value}: refused with CONFIG(3)",
                  getattr(exc, "code", None) == exitcodes.CONFIG,
                  f"(code={getattr(exc, 'code', None)})")
        else:
            check(f"interval {value}: refused at all", False, "(it was accepted)")

    # The ceiling itself is a legal cadence, not the first illegal one. Without
    # this the guard could tighten by a second and nothing would notice.
    args = build_arg_parser().parse_args(["--simulate", "--interval", "86400"])
    check("interval 86400: the ceiling itself is accepted",
          config_from_args(args)["interval"] == 86400.0)


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
    def set_loss_burst(self, *_a, **_k): pass
    def set_asymmetry(self, *_a, **_k): pass
    def set_dest(self, *_a, **_k): pass
    def set_ip_family(self, *_a, **_k): pass
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

    class _CannotStartEngine(_TargetedEngine):
        """The same engine surface, with the ONE method that has to fail.

        This used to mirror every setter by hand. A second copy of an interface
        is the copy that falls behind, and it did: the engine gaining a setter
        turned this test red for a reason that has nothing to do with what it
        asserts. ``_OneTickEngine`` already subclasses for the same reason.
        """

        def start(self, *_a, **_k):
            raise RuntimeError("WinDivert could not be opened")

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


def test_the_repro_command_repeats_the_scenario_and_the_simulation(tmp_path):
    """The summary and the report name ONE command, and it is the whole run (P1-3).

    `Reproduce:` left out --scenario and --loop, so pasting it replayed the first
    step's settings for the whole run with nothing changing over time. The
    report's `cli_command` also left out --simulate, which the console line had:
    pasted on an elevated machine it impairs the real network.
    """
    import shlex

    from beantester.cli import build_arg_parser

    scen = _scenario_file(tmp_path, "two-steps.json", {"loop": False, "steps": [
        {"at": 0, "settings": {"loss": 5}},
        {"at": 30, "settings": {"loss": 50}}]})
    report = str(tmp_path / "rep.json")
    out, err = io.StringIO(), io.StringIO()
    code = run_cli(["--simulate", "--scenario", scen, "--loop", "--duration", "0.3",
                    "--interval", "1", "--format", "json", "--repro-out", report],
                   sleep=_budgeted_sleep(), out=out, err=err)
    records = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    command = records[-1]["repro_command"]
    with open(report, encoding="utf-8") as f:
        written = json.load(f)["cli_command"]
    check("repro: the run ended OK", code == exitcodes.OK, f"(code={code})")
    check("repro: the report's command is the summary's", written == command,
          f"({written!r} vs {command!r})")
    parts = [p.strip('"') for p in shlex.split(command, posix=False)]
    argv = parts[2:] if parts[0] == "python" else parts[1:]
    args = build_arg_parser().parse_args(argv)
    check("repro: the command names the scenario as it was typed, and loops it",
          args.scenario == scen and args.loop, f"({command})")
    check("repro: and it stays a simulation", args.simulate, f"({command})")


def test_a_shipped_scenario_named_the_way_the_command_names_it_runs_anywhere(
        tmp_path, monkeypatch):
    """Every install puts the exe on PATH, so a copied command is run from any folder.

    The window names a shipped scenario from the program's folder
    (``scenarios\\x.json``; ``_internal\\scenarios\\x.json`` next to the exe), and
    from any other folder that name ended the run with the scenario error (exit 4).
    """
    monkeypatch.chdir(tmp_path)
    name = os.path.join("scenarios", "cafe-wifi.json")
    out, err = io.StringIO(), io.StringIO()
    code = run_cli(["--simulate", "--scenario", name, "--duration", "0.3",
                    "--interval", "1", "--format", "json"],
                   sleep=_budgeted_sleep(), out=out, err=err)
    check("shipped scenario: the run from another folder ends OK",
          code == exitcodes.OK, f"(code={code}, stderr={err.getvalue()!r})")
    records = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    command = records[-1]["repro_command"] if records else ""
    check("shipped scenario: its command still names it as it was typed",
          f"--scenario {name} " in command + " ", f"({command})")


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


def test_a_failure_before_the_session_is_not_called_finishing_the_run():
    """The last-resort handler also catches what fails BEFORE the session - loading
    the settings, starting the engine - and said "while finishing the run" about a
    run that never began (external review NOWE-3-5)."""
    from beantester.engine import BeanEngine

    class _FaultsOnSeed(BeanEngine):
        def set_seed(self, seed):
            raise RuntimeError("the seed went away")

    out, err = io.StringIO(), io.StringIO()
    clock = FakeClock()
    code = run_cli(["--simulate", "--duration", "1"], sleep=clock.sleep, clock=clock,
                   engine=_FaultsOnSeed(), out=out, err=err)
    lines = [l for l in err.getvalue().splitlines() if "unexpected failure" in l]
    check("fault before the session: RUNTIME, not a traceback",
          code == exitcodes.RUNTIME, f"(code={code})")
    check("fault before the session: the line names its phase truthfully",
          len(lines) == 1 and "outside the session" in lines[0]
          and "finishing" not in lines[0], f"({lines})")


def test_a_schedule_that_is_not_a_time_and_speeds_is_a_config_error():
    """``--rate-schedule 1:nan:0`` passed --dry-run and ended the real run with
    "unexpected failure" and exit 1; ``10:-100:0`` ran with NO limit in silence
    (external review P2-2). Both are the settings' fault: CONFIG, before anything
    starts."""
    for bad in ("1:nan:0", "10:-100:0", "0:100:100", "1:99999999999:0"):
        for mode in (["--dry-run"], ["--duration", "1"]):
            code, _, err = cli(["--simulate", "--rate-schedule", bad] + mode)
            check(f"schedule {bad!r} {mode[0]}: CONFIG", code == exitcodes.CONFIG,
                  f"(code={code}, err={err!r})")


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


def test_a_termination_is_logged_under_the_name_of_its_signal():
    """Ctrl+Break arrives as SIGBREAK and was logged as "Terminated (SIGTERM)",
    which sent the reader looking for a job runner that never sent one. The code
    stays 143 for both (the exit codes are a contract)."""
    def ctrl_break(_s):
        raise _Terminated("Ctrl+Break")

    import signal
    before = signal.getsignal(signal.SIGTERM)
    err = io.StringIO()
    code = run_cli(["--simulate", "--duration", "5"], sleep=ctrl_break,
                   out=io.StringIO(), err=err)
    check("exit: Ctrl+Break -> 143", code == exitcodes.TERMINATED, f"(code={code})")
    check("and the log names Ctrl+Break", "Terminated (Ctrl+Break)." in err.getvalue(),
          f"({err.getvalue()!r})")
    # Left installed, the handler outlived the run with nothing left to end, and
    # a process running the CLI in-process (this suite) ignored SIGTERM after it.
    check("the run leaves the process's own SIGTERM handler as it found it",
          signal.getsignal(signal.SIGTERM) is before)


def _record_signal_handlers(monkeypatch):
    """Install the CLI's handlers into a dict instead of the process: {signum: handler}.

    ``SIGBREAK`` exists only on Windows, so it is given a number here too - the
    Linux runner has to prove the same thing.
    """
    import signal
    monkeypatch.setattr(signal, "SIGBREAK", getattr(signal, "SIGBREAK", 21), raising=False)
    installed = {}

    def fake_signal(sig, handler):
        previous = installed.get(sig, "before")
        installed[sig] = handler
        return previous
    monkeypatch.setattr(signal, "signal", fake_signal)
    monkeypatch.setattr(signal, "getsignal", lambda sig: installed.get(sig, "before"))
    return signal, installed


def test_one_signal_ends_the_run_and_a_second_cannot_cut_the_cleanup_short(monkeypatch):
    """External review P2-24. The handler raised on EVERY signal, so a second one
    - a CI runner that repeats SIGTERM, a second Ctrl+Break - landed in the middle
    of the cleanup (the engine stopping, the driver unloading) and cut it short.
    It raises once, never after the run has begun to end, and the run leaves the
    process's own handlers as it found them."""
    import pytest
    signal, installed = _record_signal_handlers(monkeypatch)
    previous = {}
    cli_module._install_signal_handlers(previous)
    handler = installed[signal.SIGTERM]
    check("both signals are handled", installed[signal.SIGBREAK] is handler)

    with pytest.raises(_Terminated) as first:
        handler(signal.SIGTERM, None)
    check("the first one ends the run, named", first.value.label == "SIGTERM")
    check("a second one is ignored", handler(signal.SIGTERM, None) is None)

    cli_module._install_signal_handlers({})
    handler = installed[signal.SIGBREAK]
    with pytest.raises(_Terminated) as brk:
        handler(signal.SIGBREAK, None)
    check("Ctrl+Break is called Ctrl+Break", brk.value.label == "Ctrl+Break")

    cli_module._install_signal_handlers({})
    cli_module._close_signal_gate()
    check("nothing is raised once the run has begun to end",
          installed[signal.SIGTERM](signal.SIGTERM, None) is None)

    cli_module._restore_signal_handlers(previous)
    check("the previous handlers are back", installed[signal.SIGTERM] == "before",
          f"({installed[signal.SIGTERM]!r})")


def _run_cli_catching(argv, **kwargs):
    """``run_cli`` that turns an exception ESCAPING it into a result: the promise
    under test is an exit code, and a raw traceback is the regression."""
    out, err = io.StringIO(), io.StringIO()
    try:
        code = run_cli(argv, out=out, err=err, **kwargs)
    except (KeyboardInterrupt, _Terminated) as exc:
        code = f"escaped: {type(exc).__name__}"
    return code, out.getvalue(), err.getvalue()


def test_a_signal_while_the_handlers_are_installed_ends_the_run_it_cancelled(
        monkeypatch):
    """Review of #237. The handler was in place before the gate opened, so a
    SIGTERM in between was dropped and the cancelled run went on - a session, on a
    real run. Opening the gate before ``run_cli``'s ``try`` instead let it escape
    as a traceback. It is held now, and raised as the gate opens: 143, and nothing
    of the run it cancelled is done."""
    signal, installed = _record_signal_handlers(monkeypatch)
    record, order = signal.signal, []

    def signal_meanwhile(sig, handler):
        old = record(sig, handler)
        order.append(sig)
        if len(order) == 2:          # the first one is in place, the gate not open
            installed[order[0]](order[0], None)
        return old
    monkeypatch.setattr(signal, "signal", signal_meanwhile)
    code, out, err = _run_cli_catching(["--print-config"])
    check("the signal ends the run: 143", code == exitcodes.TERMINATED,
          f"(code={code!r}, err={err!r})")
    check("logged under its name", "Terminated (SIGTERM)." in err, f"({err!r})")
    check("and nothing of the cancelled run was done", out == "", f"({out!r})")
    check("the previous handlers are back",
          [installed[s] for s in order[:2]] == ["before", "before"], f"({installed!r})")


def test_an_installation_cut_short_still_puts_back_what_it_replaced(monkeypatch):
    """Review of #237. A Ctrl+C on the bytecode after ``signal.signal`` replaced a
    handler: the old one was only known from that call's return value, which was
    lost with it, and the installation ran outside ``run_cli``'s ``try`` - a
    traceback instead of 130, and the CLI's handler left in the process."""
    signal, installed = _record_signal_handlers(monkeypatch)
    record, calls = signal.signal, []

    def ctrl_c_after(sig, handler):
        old = record(sig, handler)
        calls.append(sig)
        if len(calls) == 1:          # the first replacement; the rest put back
            raise KeyboardInterrupt
        return old
    monkeypatch.setattr(signal, "signal", ctrl_c_after)
    code, _, err = _run_cli_catching(["--print-config"])
    check("an ordinary Ctrl+C: 130", code == exitcodes.INTERRUPTED,
          f"(code={code!r}, err={err!r})")
    check("the handler it replaced is back", installed[signal.SIGTERM] == "before",
          f"({installed!r})")


def test_a_ctrl_c_during_the_cleanup_still_puts_the_handlers_back(monkeypatch):
    """Review of #237. The handlers were put back after the driver was unloaded and
    the log closed, in the same block, so a second Ctrl+C while the driver unloaded
    - Ctrl+C is not gated, a second one forces the matter - left the CLI's handler
    in the process, gate closed, ignoring SIGTERM from then on."""
    import pytest
    signal, installed = _record_signal_handlers(monkeypatch)

    def release():
        raise KeyboardInterrupt
    monkeypatch.setattr(cli_module.driver, "release_on_exit", release)
    with pytest.raises(KeyboardInterrupt):
        run_cli(["--print-config"], out=io.StringIO(), err=io.StringIO())
    check("the previous handlers are back",
          installed[signal.SIGTERM] == "before" and installed[signal.SIGBREAK] == "before",
          f"({installed!r})")


def _a_signal_on_the_first_gate_close(monkeypatch):
    """Where a pending SIGTERM lands on the way out: CPython runs a pending handler
    when a function is entered, so in ``_close_signal_gate()`` itself, with the
    gate still open. The handler closes the gate and raises, and that is what the
    first call does here. Returns the list of calls."""
    real, calls = cli_module._close_signal_gate, []

    def close():
        calls.append(1)
        if len(calls) == 1:
            cli_module._signal_gate[0] = False
            raise _Terminated("SIGTERM")
        real()
    monkeypatch.setattr(cli_module, "_close_signal_gate", close)
    return calls


def test_a_signal_on_the_way_out_is_still_a_coded_exit_with_its_cleanup(monkeypatch):
    """Review of #237. ``run_cli`` closed the gate in the first line of its
    ``finally``. A SIGTERM landing there - the run done and the gate still open,
    as after ``--print-config``, ``--doctor`` or a usage error - escaped as a
    traceback, and the driver release, ``log.close()`` and the restore were all
    skipped. An error being reported with the gate open could be cut short the
    same way. The gate closes before ``run_cli`` reports anything now, and a
    signal on that close is an ordinary 143."""
    from beantester.clilog import CliLog
    signal, installed = _record_signal_handlers(monkeypatch)
    released, closed = [], []
    monkeypatch.setattr(cli_module.driver, "release_on_exit",
                        lambda: released.append(1) or [])
    real_close = CliLog.close
    monkeypatch.setattr(CliLog, "close", lambda self: closed.append(1) or real_close(self))
    _a_signal_on_the_first_gate_close(monkeypatch)
    code, _, err = _run_cli_catching(["--print-config"])
    check("a coded exit, not a traceback: 143", code == exitcodes.TERMINATED,
          f"(code={code!r}, err={err!r})")
    check("logged under its name", "Terminated (SIGTERM)." in err, f"({err!r})")
    check("the driver release ran", released == [1], f"({released})")
    check("the log was closed", closed == [1], f"({closed})")
    check("the previous handlers are back",
          installed[signal.SIGTERM] == "before" and installed[signal.SIGBREAK] == "before",
          f"({installed!r})")

    gate_when_reported = []
    real_error = CliLog.error
    monkeypatch.setattr(CliLog, "error", lambda self, msg: gate_when_reported.append(
        cli_module._signal_gate[0]) or real_error(self, msg))
    code, _, err = _run_cli_catching(["--gui", "--loss", "30"])
    check("a usage error is still a usage error", code == exitcodes.USAGE,
          f"(code={code!r}, err={err!r})")
    check("and it is reported with the gate already closed",
          gate_when_reported == [False], f"({gate_when_reported})")


def _signal_after(monkeypatch, method, exc):
    """``BeanEngine.<method>`` does its job, then ``exc`` lands on the next bytecode."""
    from beantester.engine import BeanEngine
    real = getattr(BeanEngine, method)

    def patched(self, *args, **kwargs):
        real(self, *args, **kwargs)
        raise exc
    monkeypatch.setattr(BeanEngine, method, patched)


def _run_watching_the_release(monkeypatch, argv):
    """Run the CLI; returns ``(code, stdout, stderr, engine running when the driver
    was released)``. Unloading the driver under our own open handle fails, so the
    engine must be stopped by then."""
    from beantester.engine import BeanEngine
    engine, seen = BeanEngine(), {}

    def release():
        seen["running"] = engine.is_running()
        return []
    monkeypatch.setattr(cli_module.driver, "release_on_exit", release)
    out, err = io.StringIO(), io.StringIO()
    code = run_cli(argv, engine=engine, sleep=FakeClock().sleep, out=out, err=err)
    return code, out.getvalue(), err.getvalue(), seen.get("running")


def test_a_signal_while_the_capture_starts_stops_the_engine_before_the_driver_goes(
        monkeypatch):
    """External review P2-24, reproduced: SIGTERM landing just after
    ``engine.start`` returned was caught as an ordinary failure - exit 1 with
    "cannot start the capture: " and nothing after the colon - and the engine was
    still running when ``run_cli`` returned."""
    _signal_after(monkeypatch, "start", _Terminated())
    code, _, err, running = _run_watching_the_release(
        monkeypatch, ["--simulate", "--duration", "5"])
    check("a signal is a terminated run", code == exitcodes.TERMINATED, f"(code={code})")
    check("not a capture that failed to start", "cannot start the capture" not in err,
          f"({err!r})")
    check("the engine was stopped before the driver was released", running is False,
          f"(running={running})")


def test_a_signal_on_the_session_guard_still_stops_the_engine(monkeypatch):
    """Review of #237. The guard around the session's start closed the gate and
    then stopped the engine. A SIGTERM landing on that close - a Ctrl+C had just
    left ``engine.start`` - skipped the stop, and the driver was released under a
    running engine. The engine is stopped whatever the close raised."""
    _signal_after(monkeypatch, "start", KeyboardInterrupt())
    _a_signal_on_the_first_gate_close(monkeypatch)
    code, _, err, running = _run_watching_the_release(
        monkeypatch, ["--simulate", "--duration", "5"])
    # 143 and not the Ctrl+C's 130: proof that the signal did land on the close.
    check("a coded exit: 143", code == exitcodes.TERMINATED, f"(code={code}, err={err!r})")
    check("the engine was stopped before the driver was released", running is False,
          f"(running={running})")


def _console_stand_ins(monkeypatch):
    """The console handler's surroundings, recorded: what it registered, which
    signal it asked the main thread for, and how long it held the process."""
    signal, installed = _record_signal_handlers(monkeypatch)
    registered, asked, held = [], [], []
    monkeypatch.setattr(cli_module, "_console_token", [None])
    monkeypatch.setattr(cli_module, "_console_active", [False])
    monkeypatch.setattr(cli_module, "_console_label", [None])
    monkeypatch.setattr(cli_module.winenv, "add_console_ctrl_handler",
                        lambda handler: registered.append(handler) or "token")
    monkeypatch.setattr(cli_module, "_interrupt_main", asked.append)
    monkeypatch.setattr(cli_module, "_hold_the_process", held.append)
    return signal, installed, registered, asked, held


def test_closing_the_console_ends_the_run_with_its_cleanup(monkeypatch):
    """External review P2-20, reproduced by closing a real console (WM_CLOSE):
    exit 0xC000013A, no summary, no repro report, and after a real capture the
    WinDivert driver stayed loaded. The C runtime answered CTRL_CLOSE_EVENT with
    TRUE, and Windows ends the process as soon as a handler returns, so no Python
    ran at all. The console handler hands the close to the main thread as a
    SIGBREAK under its own name and holds the process open: the run ends the way a
    Ctrl+Break ends it, with its cleanup and 143."""
    from beantester.engine import BeanEngine
    signal, installed, registered, asked, held = _console_stand_ins(monkeypatch)
    clock, engine, seen, answers = FakeClock(), BeanEngine(), {}, []

    def release():
        seen["running"] = engine.is_running()
        return []
    monkeypatch.setattr(cli_module.driver, "release_on_exit", release)

    def sleep(seconds):
        clock.sleep(seconds)
        if clock.t >= 1.0 and registered and not answers:
            # Windows calls the handler on a thread of its own...
            windows = threading.Thread(target=lambda: answers.append(registered[0](2)))
            windows.start()
            windows.join()
            for sig in asked:            # ...and CPython runs the signal on this one
                installed[sig](sig, None)

    out, err = io.StringIO(), io.StringIO()
    code = run_cli(["--simulate", "--duration", "5", "--format", "json"], sleep=sleep,
                   clock=clock, engine=engine, out=out, err=err)
    summary = [json.loads(line) for line in out.getvalue().splitlines()
               if '"summary"' in line]
    check("the handler is registered for the run", len(registered) == 1, f"({registered})")
    check("it takes the close and holds the process open",
          answers == [True] and held == [cli_module._CONSOLE_HOLD_S], f"({answers}, {held})")
    check("as a SIGBREAK for the main thread", asked == [signal.SIGBREAK], f"({asked})")
    check("the run ends terminated: 143", code == exitcodes.TERMINATED,
          f"(code={code}, err={err.getvalue()!r})")
    check("named for what happened", "Terminated (console window closed)." in err.getvalue(),
          f"({err.getvalue()!r})")
    check("with its summary", len(summary) == 1
          and summary[0]["stop_reason"] == "terminated", f"({summary!r})")
    check("and the engine stopped before the driver was released",
          seen.get("running") is False, f"({seen})")
    check("once the run is over, a close goes the way it always went",
          registered[0](2) is False and asked == [signal.SIGBREAK], f"({asked})")

    def ctrl_break(seconds):
        clock.sleep(seconds)
        installed[signal.SIGBREAK](signal.SIGBREAK, None)

    err = io.StringIO()
    code = run_cli(["--simulate", "--duration", "5"], sleep=ctrl_break, clock=clock,
                   out=io.StringIO(), err=err)
    check("the next run keeps the one handler", len(registered) == 1, f"({registered})")
    check("and its Ctrl+Break is a Ctrl+Break again",
          code == exitcodes.TERMINATED and "Terminated (Ctrl+Break)." in err.getvalue(),
          f"(code={code}, {err.getvalue()!r})")


def test_the_console_handler_takes_only_a_close_during_a_run(monkeypatch):
    """The handler stands FIRST in the process's list, before the C runtime's, so
    whatever it takes never reaches Python's own handling: Ctrl+C and Ctrl+Break
    must go on, and so must logoff and shutdown (a run under a service must not
    end because somebody logged off). Outside a run nothing is taken either."""
    signal, _, _, asked, held = _console_stand_ins(monkeypatch)
    cli_module._console_active[0] = True
    for ctrl_type in (0, 1, 5, 6):       # Ctrl+C, Ctrl+Break, logoff, shutdown
        check(f"event {ctrl_type} goes on", cli_module._on_console_event(ctrl_type) is False)
    check("and asks nothing of the main thread", asked == [] and held == [],
          f"({asked}, {held})")
    check("a close is taken", cli_module._on_console_event(2) is True)
    check("handed over as SIGBREAK, named, with the process held",
          asked == [signal.SIGBREAK] and held == [cli_module._CONSOLE_HOLD_S]
          and cli_module._console_label[0] == "console window closed", f"({asked}, {held})")
    cli_module._console_active[0] = False
    check("outside a run a close goes on too", cli_module._on_console_event(2) is False)
    check("without a word to the main thread", asked == [signal.SIGBREAK], f"({asked})")


def test_a_signal_or_ctrl_c_while_the_scenario_starts_is_an_ordinary_interrupted_run(
        monkeypatch, tmp_path):
    """External review P2-24 and NOWE-5b-1, reproduced: a signal while the
    scenario started was "scenario error: " with exit 4, and a Ctrl+C there left
    the engine running at the driver release, with no summary. Arming the scenario
    is part of the session now: the same code, the same summary as a Ctrl+C in
    the loop."""
    scen = _scenario_file(tmp_path, "two.json", {"loop": False, "steps": [
        {"at": 0, "settings": {"loss": 5}}, {"at": 5, "settings": {"loss": 50}}]})
    for exc, want, reason in ((_Terminated(), exitcodes.TERMINATED, "terminated"),
                              (KeyboardInterrupt(), exitcodes.INTERRUPTED, "interrupted")):
        monkeypatch.undo()               # the real start_scenario under each patch
        _signal_after(monkeypatch, "start_scenario", exc)
        code, out, err, running = _run_watching_the_release(
            monkeypatch, ["--simulate", "--scenario", scen, "--format", "json"])
        name = type(exc).__name__
        check(f"{name} while the scenario starts: exit {want}", code == want,
              f"(code={code}, err={err!r})")
        summary = [json.loads(line) for line in out.splitlines() if '"summary"' in line]
        check(f"{name}: the run still hands back its summary",
              len(summary) == 1 and summary[0]["stop_reason"] == reason,
              f"({summary!r})")
        check(f"{name}: the engine was stopped before the driver was released",
              running is False, f"(running={running})")


def test_the_end_of_a_scenario_is_seen_without_waiting_for_the_next_report(tmp_path):
    """External review P2-21, reproduced: a scenario that ended after about a
    second ran to 6.0 s at ``--interval 6`` - the loop slept to the next report
    before it looked. In a real session the last step went on impairing for up to
    ``--interval``, which can be a day. No nap is longer than ``POLL_S`` now, and
    a nap asked for longer than a second fails this test rather than sleeping it."""
    scen = _scenario_file(tmp_path, "short.json", {"loop": False, "steps": [
        {"at": 0, "settings": {"loss": 5}}, {"at": 0.2, "settings": {"loss": 50}}]})
    asked = []

    def sleep(seconds):
        asked.append(seconds)
        if seconds > 1.0:
            raise _NeverEnded(f"asked to sleep {seconds:g} s before looking again")
        time.sleep(seconds)

    out = io.StringIO()
    code = run_cli(["--simulate", "--scenario", scen, "--interval", "20", "--format",
                    "json"], sleep=sleep, out=out, err=io.StringIO())
    summary = [json.loads(line) for line in out.getvalue().splitlines()
               if '"summary"' in line]
    check("the scenario ended the run", code == exitcodes.OK and len(summary) == 1
          and summary[0]["stop_reason"] == "scenario_done", f"(code={code}, {summary!r})")
    check("no nap was longer than the poll", max(asked) <= cli_module.POLL_S,
          f"(longest {max(asked):g} s)")
    # Half the report interval: far enough from 20 s to tell the two apart, and
    # out of reach of a slow runner (the scenario ends on a real thread, in real
    # time, so the run takes about 0.2-0.45 s; review of #237).
    check("the run ended near the scenario's end, not at the 20 s report",
          summary[0]["elapsed_s"] < 10.0, f"({summary[0]['elapsed_s']} s)")


def test_a_report_taken_a_hair_before_its_tick_is_that_tick_and_not_taken_twice():
    """A real clock can wake a little early. The report condition allows 1e-9 s
    early, and the next tick is computed with the same allowance: without it a
    report taken just before its tick left that same tick as the next one, and it
    was reported again a moment later - two samples for one second."""
    clock = FakeClock()

    def sleep(seconds):
        clock.t += seconds
        if seconds >= 1e-3 and abs(clock.t - round(clock.t)) < 1e-6:
            clock.t = round(clock.t) - 5e-10          # woke a hair before the tick

    out = io.StringIO()
    run_cli(["--simulate", "--duration", "3", "--interval", "1", "--format", "json"],
            sleep=sleep, clock=clock, out=out, err=io.StringIO())
    samples = [line for line in out.getvalue().splitlines() if '"sample"' in line]
    check("one report per tick", len(samples) == 3, f"({len(samples)} reports)")


class _MovingClock(FakeClock):
    """Virtual time that also moves on every READ, as a real clock does, starting
    where a real monotonic clock is after a few days of uptime."""

    def __init__(self, start=5e5, step=1e-3):
        super().__init__()
        self.t, self.step = start, step

    def __call__(self):
        self.t += self.step
        return self.t


def test_a_report_interval_finer_than_the_clock_still_ends_the_run():
    """External review P3-18, reproduced: ``--interval 1e-300 --duration 1`` never
    ended. ``next_report += interval`` in a loop until it passed the clock: 1e-300
    added to a clock near 5e5 is lost to rounding, so that loop spun forever, the
    engine long stopped by its own deadline and no summary written. The tick is
    computed from the start now, and an interval that fine reports on every pass
    until the deadline.

    Run on a thread with a timeout, because the regression is a HANG and a test
    that hangs reports nothing; the virtual clock moves on every read, since the
    loop's naps are lost to rounding once the interval is below its resolution."""
    clock, out, result = _MovingClock(), io.StringIO(), {}

    def run():
        result["code"] = run_cli(["--simulate", "--interval", "1e-300", "--duration", "1",
                                  "--format", "json"], sleep=clock.sleep, clock=clock,
                                 out=out, err=io.StringIO())
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(10)
    check("the run ended", not worker.is_alive())
    check("with exit OK and its summary", result.get("code") == exitcodes.OK
          and '"summary"' in out.getvalue(), f"({result})")


def test_a_report_on_every_pass_still_naps_for_the_interval():
    """Review of #237. An interval finer than the clock reports on every pass, and
    such a pass had no nap left at all - about 43 000 reports a second. MEASURED
    2026-10-01 on a real capture of ~8 000 packets/s: 13 000 of 16 000 packets
    captured that way, about 15 700 at ``--interval 1e-4`` or ``1``. ``sleep(0)``
    returns at once (0.5 us) and did not help; a nap for the interval, which the OS
    rounds up to its shortest sleep (~0.53 ms on Windows), is what 1e-4 gets."""
    clock, asked = _MovingClock(), []

    def sleep(seconds):
        asked.append(seconds)
        clock.sleep(seconds)
    out = io.StringIO()
    code = run_cli(["--simulate", "--interval", "1e-300", "--duration", "0.5",
                    "--format", "json"], sleep=sleep, clock=clock, out=out,
                   err=io.StringIO())
    samples = [line for line in out.getvalue().splitlines() if '"sample"' in line]
    check("the run reported and ended", code == exitcodes.OK and len(samples) > 1,
          f"(code={code}, {len(samples)} reports)")
    check("every pass napped for the interval",
          len(asked) >= len(samples) and all(nap == 1e-300 for nap in asked),
          f"({len(asked)} naps for {len(samples)} reports, shortest "
          f"{min(asked, default=None)!r})")


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


def test_every_drop_a_reason_can_name_is_in_each_sample():
    """A sample left out two of the drops the link inflicts: a run with
    ``--max-size`` or ``--flap-period`` reported zero losses every interval while
    its packets were being dropped, and only the summary said so (external review
    P3-7c). Tied to ``damage.DROP_BY_REASON``, the one list of what a dropped
    packet can be counted as, so a reason added there is in the samples too - each
    counter with a value no other has, read back from the NDJSON record and from
    the text line."""
    from beantester import cli as cli_module
    from beantester.damage import DROP_BY_REASON
    counters = sorted(set(DROP_BY_REASON.values()) | {"drop_loss"})
    values = {name: 1000 + i for i, name in enumerate(counters)}
    stats = _engine_stats(**values)
    record = cli_module._sample_record(1.0, 0.0, 0.0, stats)
    missing = {name: record.get(name) for name in counters if record.get(name) != values[name]}
    check("NDJSON: every drop counter, under its own name", not missing, f"({missing})")
    text = cli_module._sample_text(1.0, 0.0, 0.0, stats)
    unseen = [name for name in counters if f"={values[name]}" not in text]
    check("text: every drop counter's value", not unseen, f"({unseen} in {text!r})")


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


def test_the_loss_flag_survived_gaining_a_neighbour(monkeypatch):
    """🔴 MEASURED, and the cost `--loss-burst` was allowed to charge.

    ``allow_abbrev`` is on by decision (ADR 2026-08-02), so a second option
    starting with ``loss`` changes what the prefixes mean. Measured on this
    parser: ``--loss`` still resolves, because argparse prefers an EXACT match
    over a prefix one, and ``--loss-b`` reaches the new flag. What did NOT
    survive is ``--los``, which used to work and is now ambiguous - a real if
    small cost, accepted deliberately rather than discovered later, and pinned
    here so nobody spends an afternoon on it as a bug.
    """
    parser = cli_module.build_arg_parser()
    args = parser.parse_args(["--loss", "5"])
    check("--loss still means the loss percentage", args.loss == 5.0, f"({args.loss})")
    check("and it did not swallow the run length", args.loss_burst is None,
          f"({args.loss_burst})")
    args = parser.parse_args(["--loss-b", "20"])
    check("--loss-b reaches the run length", args.loss_burst == 20.0,
          f"({args.loss_burst})")
    try:
        parser.parse_args(["--los", "5"])
        code = 0
    except SystemExit as exc:
        code = exc.code
    check("--los is now ambiguous, which is the accepted cost of the name",
          code == 2, f"(exit {code})")


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

    for expression in ("chrome.exe", "chrome.exe, !chromedriver", "?"):
        _, _, err, _ = _real_run(monkeypatch, ["--loss", "50", "--target", expression])
        check(f"no warning: --target {expression} really does narrow",
              not _warned(err), f"({err!r})")


def test_a_target_that_names_every_exe_is_not_a_bound(monkeypatch):
    """External review P3-17. Every socket on Windows but those of ``System`` is
    owned by an ``.exe`` - MEASURED on a real table: ``*.exe`` matched 33 of 34
    owners and 186 of 190 ports. It passed as narrow, and the test above PINNED
    that (``*.exe`` sat in its "really does narrow" list): the probes stood for
    every value there is, and ``System`` and ``a`` are not ``.exe``.

    Each form is checked beside names that really narrow, some of them broad, so
    a fix that simply warns more often does not pass."""
    for expression in ("*.exe", "exe", r"re:\.exe$", "*.*"):
        _, _, err, _ = _real_run(monkeypatch, ["--loss", "50", "--target", expression])
        check(f"warning: --target {expression} impairs every program", _warned(err),
              f"({err!r})")

    for expression in ("svchost", "chrome, firefox, msedge", "*host*", "s*"):
        _, _, err, _ = _real_run(monkeypatch, ["--loss", "50", "--target", expression])
        check(f"no warning: --target {expression} still narrows",
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


def test_the_flags_that_gained_an_up_neighbour_still_work():
    """🔴 MEASURED, and the cost the asymmetry flags were allowed to charge.

    The same shape as ``--loss-burst`` above, seven times over. ``allow_abbrev``
    is on by decision (ADR 2026-08-02), so a second option starting with
    ``latency`` changes what the prefixes mean. Measured on this parser before
    the names were chosen: 18 prefixes that used to work stop working
    (``--lat``, ``--jit``, ``--j``, ``--cor``, ``--spike-p`` and the longer
    forms of each), and every FULL flag survives, because argparse prefers an
    exact match over a prefix one.

    That second half is the one that matters and the reason the cost was
    acceptable: ``settings_to_cli`` emits full flags, so no stored ``Reproduce:``
    command and no documented example moves. Only a hand-typed abbreviation does.

    The alternative measured against this was ``--up-latency``, which costs one
    prefix instead of eighteen and was NOT taken: every other modifier in this
    parser reads ``<noun>-<modifier>`` (``--loss-burst``, ``--spike-prob``,
    ``--rst-cooldown``, ``--flap-down``, ``--nat-timeout``), and ``--up-`` would
    also read as belonging to ``--up``, the upload SPEED limit.
    """
    parser = cli_module.build_arg_parser()
    for flag, dest, neighbour in (("--latency", "latency", "latency_up"),
                                  ("--jitter", "jitter", "jitter_up"),
                                  ("--loss", "loss", "loss_up"),
                                  ("--corrupt", "corrupt", "corrupt_up"),
                                  ("--dup", "dup", "dup_up"),
                                  ("--spike-ms", "spike_ms", "spike_ms_up"),
                                  ("--spike-prob", "spike_prob", "spike_prob_up")):
        args = parser.parse_args([flag, "7"])
        check(f"{flag} still means what it meant",
              getattr(args, dest) == 7.0, f"({getattr(args, dest)})")
        check(f"{flag} did not swallow its -up neighbour",
              getattr(args, neighbour) is None, f"({getattr(args, neighbour)})")
        args = parser.parse_args([f"{flag}-up", "3"])
        check(f"{flag}-up reaches the upload value",
              getattr(args, neighbour) == 3.0, f"({getattr(args, neighbour)})")

    for prefix in ("--lat", "--jit", "--j", "--cor", "--spike-p"):
        try:
            parser.parse_args([prefix, "5"])
            code = 0
        except SystemExit as exc:
            code = exc.code
        check(f"{prefix} is now ambiguous, which is the accepted cost of the names",
              code == 2, f"(exit {code})")


def test_an_upload_impairment_earns_the_blast_radius_warning(monkeypatch):
    """🔴 The rule this project writes in red: never damage traffic globally in
    silence. ``--asym --loss-up 50`` cuts half of everything this machine SENDS,
    with no target and no deadline, and the download loss the warning used to
    look at is zero - so without ``impairs`` on the upload fields it would have
    started without a word.
    """
    _, _, err, _ = _real_run(monkeypatch, ["--asym", "--loss-up", "50"])
    check("warning: an upload-only impairment is still machine-wide", _warned(err))


def test_an_upload_value_left_behind_by_the_switch_warns_about_nothing(monkeypatch):
    """The other half, and the reason ``Field.live_when`` exists.

    Turning the switch back off leaves the seven values sitting in the form, and
    they impair nothing at all. Warning about them would cry wolf on the ordinary
    path of using the feature and then changing your mind - and a warning that
    fires when nothing is wrong is how a real one stops being read.
    """
    _, _, err, _ = _real_run(monkeypatch, ["--loss-up", "50"])
    check("no warning when the switch that reads it is off", not _warned(err))
