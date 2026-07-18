"""CLI output plumbing (``beantester/clilog.py``).

The CLI is the CI/CD interface (convention 18), and its contract is a channel
split: human-readable **log goes to stderr** with a ``[bean]`` prefix, while
**machine-readable data goes to stdout** (a text line, or one JSON object per
line in ``--format json``). A pipeline redirects stdout to a file and still
watches the log on the console; if the two channels ever blur, or a JSON line
comes out unparseable, the pipeline breaks silently. These tests pin the split,
the level filtering and the NDJSON shape by capturing both streams.
"""
import io
import json

from beantester.clilog import (CliLog, DEBUG, ERROR, INFO, JSON, TEXT, WARN,
                               level_from_args)
from fakes import check


def make_log(level=INFO, fmt=TEXT, samples=True):
    out, err = io.StringIO(), io.StringIO()
    return CliLog(level=level, fmt=fmt, samples=samples, out=out, err=err), out, err


# --- channel separation ------------------------------------------------------ #
def test_log_goes_to_stderr_with_the_bean_prefix():
    log, out, err = make_log()
    log.info("starting up")
    check("log line lands on stderr", "starting up" in err.getvalue())
    check("log line carries the [bean] prefix", err.getvalue().startswith("[bean]"))
    check("nothing leaked onto stdout", out.getvalue() == "", f"(out={out.getvalue()!r})")


def test_data_goes_to_stdout_only():
    log, out, err = make_log()
    log.data({"seen": 5}, "seen=5")
    check("data lands on stdout", out.getvalue().strip() == "seen=5")
    check("data does not leak onto stderr", err.getvalue() == "", f"(err={err.getvalue()!r})")


# --- level filtering --------------------------------------------------------- #
def test_default_info_level_shows_info_but_hides_debug():
    log, _, err = make_log(level=INFO)
    log.debug("noisy internal detail")
    log.info("normal line")
    text = err.getvalue()
    check("info is shown at info level", "normal line" in text)
    check("debug is hidden at info level", "noisy internal detail" not in text)


def test_quiet_level_shows_only_errors():
    log, _, err = make_log(level=ERROR)
    log.info("info line")
    log.warn("warn line")
    log.error("boom")
    text = err.getvalue()
    check("error is shown when quiet", "boom" in text)
    check("info is suppressed when quiet", "info line" not in text)
    check("warn is suppressed when quiet", "warn line" not in text)


def test_verbose_level_shows_debug():
    log, _, err = make_log(level=DEBUG)
    log.debug("compiled matcher: dst_port in {443}")
    check("debug is shown at debug level", "compiled matcher" in err.getvalue())


# --- text vs JSON data ------------------------------------------------------- #
def test_text_format_emits_the_text_line():
    log, out, _ = make_log(fmt=TEXT)
    log.data({"seen": 1, "dropped": 0}, "seen=1 dropped=0")
    check("text format prints the text line, not JSON",
          out.getvalue().strip() == "seen=1 dropped=0")


def test_json_format_emits_one_parseable_object_per_line():
    log, out, _ = make_log(fmt=JSON)
    log.data({"kind": "sample", "seen": 1}, "ignored text")
    log.data({"kind": "summary", "seen": 2, "exit_code": 0}, "ignored text")
    lines = out.getvalue().splitlines()
    check("one line per record (NDJSON)", len(lines) == 2, f"({len(lines)} lines)")
    parsed = [json.loads(line) for line in lines]     # must not raise
    check("first record is the sample", parsed[0] == {"kind": "sample", "seen": 1})
    check("second record is the summary",
          parsed[1] == {"kind": "summary", "seen": 2, "exit_code": 0})


def test_json_data_never_falls_back_to_the_text_argument():
    log, out, _ = make_log(fmt=JSON)
    log.data({"x": 1}, "THE-TEXT-SHOULD-NOT-APPEAR")
    check("the text argument is ignored in JSON mode",
          "THE-TEXT-SHOULD-NOT-APPEAR" not in out.getvalue())


# --- samples suppressed by --quiet ------------------------------------------- #
def test_samples_are_suppressed_when_disabled():
    log, out, _ = make_log(samples=False)
    log.sample({"kind": "sample"}, "sample line")
    check("periodic samples are silent under --quiet", out.getvalue() == "")


def test_samples_are_emitted_when_enabled():
    log, out, _ = make_log(samples=True)
    log.sample({"kind": "sample"}, "sample line")
    check("periodic samples are emitted by default", "sample line" in out.getvalue())


# --- log file ---------------------------------------------------------------- #
def test_log_file_records_both_log_and_data(tmp_path):
    path = tmp_path / "run.log"
    out, err = io.StringIO(), io.StringIO()
    log = CliLog(level=INFO, fmt=TEXT, log_file=str(path), out=out, err=err)
    log.info("hello")
    log.data({"seen": 3}, "seen=3")
    log.close()
    contents = path.read_text(encoding="utf-8")
    check("the log file captured the log line", "hello" in contents)
    check("the log file captured the level label", "info" in contents)
    check("the log file captured the data line", "seen=3" in contents)


def test_a_bad_log_file_path_does_not_kill_the_run(tmp_path):
    out, err = io.StringIO(), io.StringIO()
    bad = tmp_path / "no_such_dir" / "run.log"
    # Must not raise; it reports the problem on stderr and carries on.
    log = CliLog(level=INFO, log_file=str(bad), out=out, err=err)
    log.info("still running")
    check("the run continues despite the bad log path", "still running" in err.getvalue())


# --- writing to a broken stream is swallowed, not fatal ---------------------- #
class _BrokenStream:
    def write(self, *_):
        raise OSError("stream is gone (windowed exe)")

    def flush(self):
        raise OSError("stream is gone")


def test_writing_to_a_dead_stream_is_survived():
    log = CliLog(level=INFO, out=_BrokenStream(), err=_BrokenStream())
    # A windowed build may have no real stdout/stderr; a write must never raise.
    log.info("into the void")
    log.data({"x": 1}, "into the void")
    check("writing to a dead stream does not raise", True)


# --- level_from_args --------------------------------------------------------- #
def test_level_from_args_precedence():
    check("explicit --log-level wins over everything",
          level_from_args(quiet=True, verbose=2, log_level="warn") == WARN)
    check("--quiet beats -v", level_from_args(quiet=True, verbose=3) == ERROR)
    check("-v gives debug", level_from_args(verbose=1) == DEBUG)
    check("the default is info", level_from_args() == INFO)
