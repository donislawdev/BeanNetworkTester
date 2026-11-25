"""``--stop-on-stdin-close`` and the NDJSON ``start`` record: how a program that starts
this one (the pytest and Playwright helpers) waits for the capture and ends the run.

The end-to-end cases run the real launcher in a child process with ``--simulate``,
because the point is the PIPE: what a parent sees when it closes its end, and what
happens when the parent dies holding it. Each has a canary - the same run without
the flag - so a green result cannot come from a run that would have stopped anyway.
"""
import io
import json
import os
import subprocess
import sys
import time

import psutil

from beantester import exitcodes
from beantester.cli import _StdinWatch, run_cli
from fakes import ROOT, check

LAUNCHER = os.path.join(ROOT, "bean_network_tester.py")
RUN = ["--simulate", "--format", "json", "--duration", "60", "--interval", "0.5"]
ENV = dict(os.environ, BEAN_NO_ELEVATE="1", PYTHONIOENCODING="utf-8")


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += max(0.0, float(seconds))


def _cli(argv, stdin=None):
    clock, out, err = _Clock(), io.StringIO(), io.StringIO()
    code = run_cli(argv, sleep=clock.sleep, clock=clock, out=out, err=err, stdin=stdin)
    return code, out.getvalue(), err.getvalue()


def _spawn(extra):
    return subprocess.Popen([sys.executable, LAUNCHER, *RUN, *extra], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", env=ENV, cwd=ROOT)


def _stop(proc):
    if proc.poll() is None:
        proc.kill()
    proc.communicate(timeout=30)


# --- the start record --------------------------------------------------------- #


def test_the_first_json_record_says_the_session_has_started():
    code, out, _ = _cli(["--simulate", "--format", "json", "--duration", "2",
                         "--interval", "1", "--seed", "7"])
    records = [json.loads(line) for line in out.splitlines() if line.strip()]
    check("the run ends OK", code == exitcodes.OK, f"({code})")
    check("the first record is start", records and records[0]["event"] == "start",
          f"({records[:1]})")
    start, summary = records[0], records[-1]
    check("start names the version, the seed, the mode and the length",
          set(start) == {"event", "version", "seed", "simulate", "duration_s"}, f"({start})")
    check("start's seed is the one the summary reports", start["seed"] == summary["seed"] == 7,
          f"({start['seed']} / {summary['seed']})")
    check("start says simulate and the duration", start["simulate"] is True
          and start["duration_s"] == 2.0, f"({start})")
    check("exactly one start record", sum(r["event"] == "start" for r in records) == 1)


def test_text_mode_keeps_stdout_for_its_own_lines():
    _, out, err = _cli(["--simulate", "--duration", "1", "--interval", "1"])
    check("no JSON start line in text mode", '"event"' not in out, f"({out[:200]!r})")
    check("the stderr Running line is still there", "Running" in err)


def test_a_run_that_never_starts_writes_no_start_record():
    """A scenario that cannot be read ends the run before the capture: no start."""
    code, out, _ = _cli(["--simulate", "--format", "json", "--duration", "2",
                         "--scenario", os.path.join(ROOT, "no-such-scenario.json")])
    check("the scenario error is the exit", code == exitcodes.SCENARIO, f"({code})")
    check("and no start record was written", '"start"' not in out, f"({out[:200]!r})")


# --- the watch itself ------------------------------------------------------------ #


def test_the_watch_reads_what_is_written_and_fires_only_on_the_close():
    read_end, write_end = os.pipe()
    with os.fdopen(read_end, "rb") as stream:
        watch = _StdinWatch(stream)
        watch.start()
        os.write(write_end, b"x" * 200_000)        # more than a pipe buffer holds
        time.sleep(0.3)
        check("canary: written data is not a close", not watch.closed.is_set())
        os.close(write_end)
        check("the close is seen", watch.closed.wait(5))


def test_no_standard_input_is_a_usage_error_before_anything_opens():
    code, _, err = _cli(["--simulate", "--stop-on-stdin-close", "--duration", "5"],
                        stdin=io.StringIO())
    check("a stream with no descriptor: usage error", code == exitcodes.USAGE, f"({code})")
    check("the message names the flag", "--stop-on-stdin-close" in err, f"({err[-300:]!r})")


# --- end to end, in a child process ------------------------------------------- #


def test_closing_stdin_ends_the_run_at_once_as_a_normal_end():
    proc = _spawn(["--stop-on-stdin-close"])
    try:
        first = json.loads(proc.stdout.readline())
        check("the child says it started", first.get("event") == "start", f"({first})")
        proc.stdin.close()
        proc.stdin = None           # closed: communicate() and _stop() must not touch it
        start = time.monotonic()
        out, err = proc.communicate(timeout=20)
        took = time.monotonic() - start
    finally:
        _stop(proc)
    summary = json.loads(out.strip().splitlines()[-1])
    check("exit 0: a normal end", proc.returncode == exitcodes.OK,
          f"({proc.returncode}, {err[-300:]!r})")
    check("the summary says why", summary.get("stop_reason") == "stdin", f"({summary})")
    check("within a few report-loop passes, not at --duration", took < 5, f"({took:.2f}s)")


def test_canary_without_the_flag_a_closed_stdin_changes_nothing():
    proc = _spawn([])
    try:
        json.loads(proc.stdout.readline())
        proc.stdin.close()
        proc.stdin = None           # closed: communicate() and _stop() must not touch it
        time.sleep(1.5)
        check("canary: the run goes on without the flag", proc.poll() is None,
              f"(exit {proc.returncode})")
    finally:
        _stop(proc)


_PARENT = """
import subprocess, sys, os
child = subprocess.Popen(sys.argv[1:], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
child.stdout.readline()                    # the start record: the capture is open
print(child.pid, flush=True)
os._exit(0)                                # dies holding its end of the pipe
"""


def _orphan(extra):
    """Start the run under a parent that dies at once; returns the run's process."""
    parent = subprocess.run([sys.executable, "-c", _PARENT, sys.executable, LAUNCHER,
                             *RUN, *extra], capture_output=True, text=True, env=ENV,
                            cwd=ROOT, timeout=60)
    return psutil.Process(int(parent.stdout.strip()))


def test_the_run_ends_when_the_program_that_started_it_dies():
    """The dead man's switch. Only THAT it ends is asserted, not its code: nobody is left
    to read the code, and Python's own exit flushes a stdout whose reader died with the
    parent, which fails as 120 (measured 2026-11-25) - as for any run piped into a reader
    that quits early."""
    orphan = _orphan(["--stop-on-stdin-close"])
    try:
        code = orphan.wait(timeout=20)
    except psutil.TimeoutExpired:
        orphan.kill()
        code = "still running"
    check("the orphaned run ended by itself", code != "still running", f"({code})")


def test_canary_an_orphan_without_the_flag_runs_on():
    orphan = _orphan([])
    try:
        time.sleep(1.5)
        check("canary: without the flag the orphan keeps running", orphan.is_running())
    finally:
        try:
            orphan.kill()
        except psutil.NoSuchProcess:
            pass
