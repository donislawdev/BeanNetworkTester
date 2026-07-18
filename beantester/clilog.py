"""CLI output: human logs on stderr, machine-readable data on stdout.

Two channels, deliberately separated so a pipeline can do

    BeanNetworkTester.exe --simulate --format json --duration 30 > run.ndjson

and still see the log on the console (and in the job output):

  * LOG   -> stderr, prefixed ``[bean]`` (convention 1), filtered by level,
  * DATA  -> stdout, either the classic text line or one JSON object per line
             (NDJSON: periodic ``sample`` records plus a final ``summary``).

Levels: ``--quiet`` = errors only (and no periodic samples), the default is
``info`` (what the old CLI printed), ``-v`` adds ``debug`` (what the tool is
actually doing: effective settings, compiled matchers, resolved process ports,
scenario steps, driver open/close).
"""
import json
import sys
import time
from . import crashlog

LOG_PREFIX = "[bean]"

ERROR, WARN, INFO, DEBUG = 0, 1, 2, 3
LEVEL_NAMES = {"error": ERROR, "warn": WARN, "info": INFO, "debug": DEBUG}
LEVEL_LABELS = {ERROR: "error", WARN: "warn", INFO: "info", DEBUG: "debug"}

TEXT, JSON = "text", "json"


def _write(stream, text):
    """Write a line to a stream that may not exist (windowed exe) or be closed."""
    if stream is None:
        return
    try:
        stream.write(text + "\n")
        stream.flush()
    except (OSError, ValueError, AttributeError) as _exc:
        crashlog.note(_exc, "clilog")


class CliLog:
    """Log/data sink for one CLI run."""

    def __init__(self, level=INFO, fmt=TEXT, log_file=None, samples=True,
                 out=None, err=None):
        self.level = level
        self.fmt = fmt
        self.samples = samples
        self._out = sys.stdout if out is None else out
        self._err = sys.stderr if err is None else err
        self._file = None
        self.log_path = log_file
        if log_file:
            try:
                self._file = open(log_file, "a", encoding="utf-8")
            except OSError as e:                       # never kill a run over a log file
                _write(self._err, f"{LOG_PREFIX} cannot open log file "
                                  f"{log_file!r}: {e}")

    # -- log channel (stderr) ------------------------------------------------ #
    def log(self, level, msg):
        line = f"{LOG_PREFIX} {msg}"
        if level <= self.level:
            _write(self._err, line)
        self._to_file(f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
                      f"{LEVEL_LABELS.get(level, '?'):<5} {msg}")

    def error(self, msg):
        self.log(ERROR, msg)

    def warn(self, msg):
        self.log(WARN, msg)

    def info(self, msg):
        self.log(INFO, msg)

    def debug(self, msg):
        self.log(DEBUG, msg)

    # -- data channel (stdout) ----------------------------------------------- #
    def data(self, record, text):
        """Emit one data record: JSON object (``--format json``) or text line."""
        _write(self._out, json.dumps(record, ensure_ascii=False)
               if self.fmt == JSON else text)
        self._to_file(text)

    def sample(self, record, text):
        """A periodic data record; suppressed by ``--quiet``."""
        if self.samples:
            self.data(record, text)

    def _to_file(self, text):
        if text and self._file is not None:
            try:
                self._file.write(text + "\n")
                self._file.flush()
            except (OSError, ValueError) as _exc:
                crashlog.note(_exc, "clilog")

    def close(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError as _exc:
                crashlog.note(_exc, "clilog")
            self._file = None


def level_from_args(quiet=False, verbose=0, log_level=None):
    """Resolve the log level from ``-q`` / ``-v`` / ``--log-level``.

    ``--log-level`` is explicit and wins; otherwise ``-q`` beats ``-v`` (a
    pipeline that asks for silence gets silence).
    """
    if log_level:
        return LEVEL_NAMES[str(log_level).lower()]
    if quiet:
        return ERROR
    if verbose:
        return DEBUG
    return INFO
