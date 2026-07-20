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

from beantester import exitcodes
from beantester.cli import _Terminated, build_arg_parser, config_from_args, run_cli
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


def test_fail_on_no_traffic_is_shorthand_for_min_packets_one():
    args = build_arg_parser().parse_args(["--simulate", "--fail-on-no-traffic"])
    check("--fail-on-no-traffic == --min-packets 1",
          config_from_args(args)["min_packets"] == 1)


def test_exit_code_runtime_without_pydivert():
    """A capture that cannot start is RUNTIME, not 0.

    This used to rely on WinDivert being absent from the machine - true on the
    Linux CI, FALSE on the elevated Windows runner (which has pydivert installed
    and admin rights), where a real capture started, saw no traffic and exited 0.
    So the failure is forced deterministically instead: an injected engine whose
    ``start`` raises, exactly as a missing/unopenable driver would.
    """
    class _CannotStartEngine:
        fault = False

        def set_seed(self, *_a, **_k): pass
        def set_params(self, *_a, **_k): pass
        def set_buffer(self, *_a, **_k): pass
        def set_dest(self, *_a, **_k): pass
        def set_lan(self, *_a, **_k): pass
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


def test_print_config_dumps_the_effective_settings():
    code, out, _ = cli(["--print-config", "--preset", "presets.3g", "--loss", "7"])
    settings = json.loads(out)
    check("--print-config: exits OK", code == exitcodes.OK)
    check("--print-config: flags beat the preset", settings["loss"] == 7)
    check("--print-config: the preset is applied", settings["latency"] == 150,
          f"({settings['latency']})")
    check("--print-config: duration is part of the model", "duration" in settings)


def test_doctor_reports_the_environment():
    code, out, _ = cli(["--doctor"])
    check("--doctor: reports python", "python" in out)
    check("--doctor: reports the platform", "platform" in out)
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
