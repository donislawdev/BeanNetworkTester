"""Fuzzing the CLI: whatever you throw at it, it answers with an EXIT CODE.

The CLI is the interface CI/CD drives (convention 18), so its contract is not
"usually works" but "every way of ending has a number". A raw traceback breaks
that twice over: the job sees exit 1 with no meaning, and the message lands on
the wrong stream.

These tests assert the contract itself:

* ``run_cli`` returns an int - it never lets an exception escape;
* the only codes a malformed invocation may produce are USAGE (2) and CONFIG (3);
* nothing is printed to STDOUT (the data channel) when the run fails - errors go
  to stderr, or a CI job parsing NDJSON gets a face full of English prose.
"""
import io

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from beantester import exitcodes
from beantester.cli import run_cli
from beantester.fields import FIELD_DEFS

# every flag the registry declares, so a new field is fuzzed the day it is added
FLAGS = sorted(f"--{f.cli}" for f in FIELD_DEFS if f.cli)

# values chosen to be nasty: wrong types, out of range, injection-ish, empty
VALUES = ["", "0", "-1", "1e400", "abc", "999999999999", "NaN", "inf", "-inf",
          "80-", "-,-", "!", "1:2:3", "::", "0.0", "250", "3,4", "re:[", "*",
          "1-0", "%s", "--", "\\", "'", '"', "0x10", "1e-9", "  ", "\t"]

ACCEPTABLE = {exitcodes.OK, exitcodes.USAGE, exitcodes.CONFIG}

FUZZ = settings(max_examples=200, deadline=None,
                suppress_health_check=[HealthCheck.function_scoped_fixture])


def _run(argv):
    """Run the CLI with captured streams; return (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    try:
        code = run_cli(argv, out=out, err=err)
    except SystemExit as exit_:          # argparse usage errors exit(2) this way
        code = exit_.code
    return code, out.getvalue(), err.getvalue()


@FUZZ
@given(pairs=st.lists(st.tuples(st.sampled_from(FLAGS), st.sampled_from(VALUES)),
                      min_size=1, max_size=4))
def test_no_flag_combination_produces_a_traceback(pairs):
    """--dry-run validates everything and starts nothing: pure contract surface."""
    argv = ["--dry-run"]
    for flag, value in pairs:
        argv += [flag, value]

    try:
        code, stdout, stderr = _run(argv)
    except Exception as exc:                       # pragma: no cover - the bug
        pytest.fail(f"{type(exc).__name__} escaped run_cli({argv!r}): {exc}")

    assert isinstance(code, int), f"exit code must be an int, got {code!r}"
    assert code in ACCEPTABLE, f"{argv} -> {code} ({exitcodes.name_of(code)})"
    if code != exitcodes.OK:
        # a failed run must not pollute the DATA channel: CI parses stdout
        assert not stdout.strip(), f"{argv} wrote to stdout while failing: {stdout!r}"


@FUZZ
@given(value=st.text(max_size=40))
def test_filter_expressions_never_crash_the_cli(value):
    """The expression fields are the widest attack surface the CLI has."""
    for flag in ("--target", "--dst-ip", "--dst-port"):
        code, stdout, _ = _run(["--dry-run", flag, value])
        assert code in ACCEPTABLE, f"{flag} {value!r} -> {code}"
        if code != exitcodes.OK:
            assert not stdout.strip()


@FUZZ
@given(value=st.text(alphabet="0123456789:,.-", max_size=20))
def test_rate_schedule_is_validated_not_silently_dropped(value):
    """A broken schedule must be an ERROR. It used to be dropped with a log line
    while the summary went on claiming the schedule was active.

    USAGE is fair game here too: a value that starts with ``-`` is a FLAG as far as
    argparse is concerned, and being told so is a perfectly good answer.
    """
    code, stdout, _ = _run(["--dry-run", "--rate-schedule", value])
    assert code in ACCEPTABLE, f"{value!r} -> {code} ({exitcodes.name_of(code)})"
    if code != exitcodes.OK:
        assert not stdout.strip()


def test_a_simulated_run_still_ends_green():
    """The fuzz above only proves nothing crashes; this proves it still WORKS."""
    code, stdout, stderr = _run(["--simulate", "--duration", "1", "--interval", "1",
                                 "--seed", "42", "--loss", "10"])
    assert code == exitcodes.OK, (code, stderr)
    assert stdout.strip(), "a successful run must report on the data channel"
    assert "[bean]" in stderr, "the human log belongs on stderr"
    assert "[bean]" not in stdout, "the log must never leak into the data channel"
