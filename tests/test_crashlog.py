"""The crash logger: it is the safety net, so it needs one of its own.

A crash logger has an unusual contract. It runs at the exact moment the program is
already failing, so:

* **it must never raise.** A logger that throws while recording turns one bug into
  two, and hides the first.
* **it must not flood.** A fault in the tick loop fires 1.4 times a second, and a
  fault in the packet path 150 000 times a second. Writing a file per occurrence
  fills the user's disk and buries the interesting failures.
* **it must catch what nothing else does.** A worker thread's exception is printed
  to a stderr that does not exist in a windowed build; a segfault in the WinDivert
  driver produces no Python traceback at all.
* **it must make the crash reproducible.** A stack trace with no seed and no
  settings tells you what broke, not how to break it again.

This tests all four.
"""
import json
import os
import threading

import pytest

from beantester import crashlog


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Point the logger at a temp dir; never touch the real crash folder."""
    monkeypatch.setattr(crashlog, "app_dir", lambda: str(tmp_path))
    crashlog.reset()
    crashlog.set_enabled(True)
    crashlog.set_context_provider(None)
    yield tmp_path
    crashlog.reset()


def _boom(message="boom"):
    """A real exception, with a real traceback attached."""
    try:
        raise ValueError(message)
    except ValueError as exc:
        return exc


def _entries(tmp_path):
    path = os.path.join(str(tmp_path), crashlog.CRASH_DIR_NAME, crashlog.LOG_NAME)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# -- 1) it records, with enough context to reproduce ------------------------- #
def test_a_crash_is_recorded_with_the_state_needed_to_reproduce_it(isolated):
    crashlog.set_context_provider(lambda: {"seed": 4242, "settings": {"loss": 10},
                                           "page": "connections"})
    entry = crashlog.record(_boom("kaboom"), source="test")

    assert entry is not None
    assert entry["type"] == "ValueError"
    assert entry["message"] == "kaboom"
    assert "ValueError: kaboom" in entry["traceback"]

    context = entry["context"]
    assert context["version"], "a crash without a version cannot be triaged"
    # the seed and the settings are what turn a stack trace into a repro
    assert context["seed"] == 4242
    assert context["settings"] == {"loss": 10}

    written = _entries(isolated)
    assert len(written) == 1
    assert written[0]["fingerprint"] == entry["fingerprint"]


# -- 2) a repeating fault costs one line, not one per occurrence -------------- #
def test_a_repeating_fault_is_counted_not_re_written(isolated):
    """A crash inside the tick loop fires 1.4x a second, forever."""
    for _ in range(500):
        entry = crashlog.record(_boom("same place every time"), source="tick")

    assert entry["count"] == 500
    written = _entries(isolated)
    assert len(written) == 1, f"{len(written)} disk writes for one repeating fault"


def test_different_faults_get_different_fingerprints(isolated):
    crashlog.record(_boom("one"), source="test")

    def other():
        try:
            raise KeyError("two")
        except KeyError as exc:
            crashlog.record(exc, source="test")

    other()
    prints = {e["fingerprint"] for e in _entries(isolated)}
    assert len(prints) == 2, "two different bugs must not be merged into one"


# -- 3) it never raises, whatever it is handed ------------------------------- #
@pytest.mark.parametrize("value", [
    None, "not an exception", 42, Exception(), ValueError("no traceback"),
])
def test_recording_never_raises(isolated, value):
    """It runs while the program is already failing. It cannot add a second bug."""
    crashlog.record(value, source="test")           # must not raise
    crashlog.note(value, "subsystem")
    crashlog.once("hot-path-subsystem", value)


def test_a_context_provider_that_raises_cannot_turn_one_crash_into_two(isolated):
    def broken():
        raise RuntimeError("the context provider is itself broken")

    crashlog.set_context_provider(broken)
    entry = crashlog.record(_boom(), source="test")
    assert entry is not None, "a broken context provider must not lose the crash"


# -- 4) it catches what nothing else does ------------------------------------ #
def test_a_worker_thread_exception_is_recorded(isolated):
    """Previously recorded NOWHERE: threads print to a stderr a windowed build
    does not have, and then die quietly."""
    crashlog.install(native=False)
    try:
        def explode():
            raise RuntimeError("worker died")

        t = threading.Thread(target=explode, name="worker")
        t.start()
        t.join(timeout=5)

        written = _entries(isolated)
        assert any(e["type"] == "RuntimeError" and "worker died" in e["message"]
                   for e in written), written
    finally:
        crashlog.reset()


def test_install_is_idempotent(isolated):
    crashlog.install(native=False)
    first = threading.excepthook
    crashlog.install(native=False)
    assert threading.excepthook is first, "installing twice must not stack hooks"


# -- 5) quiet(): swallow for the user, record for us ------------------------- #
def test_quiet_swallows_the_error_but_does_not_hide_it(isolated):
    """The replacement for the ~100 `except Exception: pass` sites."""
    with crashlog.quiet("gui.tooltip"):
        raise RuntimeError("a tooltip would not draw")

    # the user's session carried on...
    written = _entries(isolated)
    # ...but the failure is on the record
    assert len(written) == 1
    assert written[0]["severity"] == crashlog.DEBUG
    assert written[0]["subsystem"] == "gui.tooltip"


def test_quiet_lets_the_program_continue(isolated):
    reached = []
    for i in range(3):
        with crashlog.quiet("gui.test"):
            if i == 1:
                raise ValueError("only the middle one fails")
        reached.append(i)
    assert reached == [0, 1, 2], "quiet() must not break the loop it wraps"


def test_once_records_the_first_occurrence_only(isolated):
    """The packet path runs 150 000 times a second: it cannot afford a traceback."""
    for _ in range(10_000):
        crashlog.once("engine.packet", _boom("malformed packet"))
    written = _entries(isolated)
    assert len(written) == 1, f"{len(written)} writes from the hot path"


# -- 6) it is bounded ---------------------------------------------------------- #
def test_the_in_memory_table_is_bounded(isolated):
    """A program with thousands of DISTINCT faults must not be memory-bombed by the
    thing that is supposed to be diagnosing it.

    Distinct fingerprints are the point: the same fault repeated is already handled
    by the counter. Each exception below is raised from its own generated line, so
    each gets its own fingerprint - which is what actually loads the table.
    """
    for i in range(crashlog.MAX_RECORDS + 200):
        namespace = {}
        exec(f"def f{i}():\n    raise ValueError('distinct fault {i}')", namespace)
        try:
            namespace[f"f{i}"]()
        except ValueError as exc:
            crashlog.record(exc, source="test")

    prints = {e["fingerprint"] for e in _entries(isolated)}
    assert len(prints) > 100, f"the faults were not distinct ({len(prints)})"
    assert len(crashlog._seen) <= crashlog.MAX_RECORDS, (
        f"the crash table grew to {len(crashlog._seen)} "
        f"(ceiling {crashlog.MAX_RECORDS})")


def test_disabled_records_nothing(isolated):
    crashlog.set_enabled(False)
    assert crashlog.record(_boom(), source="test") is None
    assert _entries(isolated) == []


# -- 7) the human-readable report --------------------------------------------- #
def test_format_report_is_readable_and_carries_the_repro(isolated):
    crashlog.set_context_provider(lambda: {"seed": 99})
    entry = crashlog.record(_boom("readable"), source="test")
    text = crashlog.format_report(entry)

    assert "ValueError" in text
    assert "readable" in text
    assert "99" in text, "the report must carry the seed - it is the repro"
    assert isinstance(text, str) and len(text) > 50


# -- 5) the on-disk log rotates instead of growing without bound ------------- #
def test_the_log_rotates_when_it_grows_past_the_limit(isolated, monkeypatch):
    """A fault in the packet path fires 150k/s; the ndjson log must not grow
    forever. When it passes the size limit it is rolled to ``.1``."""
    monkeypatch.setattr(crashlog, "MAX_LOG_BYTES", 200)     # tiny, for the test
    directory = crashlog.crash_dir()
    os.makedirs(directory, exist_ok=True)
    log_path = os.path.join(directory, crashlog.LOG_NAME)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("x" * 500 + "\n")                           # already over the limit

    crashlog.record(_boom("after rotation"), source="test")

    assert os.path.exists(log_path + ".1"), "the oversized log was not rotated aside"
    assert "x" * 500 in open(log_path + ".1", encoding="utf-8").read(), \
        "the rotated file must keep the old content"
    fresh = open(log_path, encoding="utf-8").read()
    assert "after rotation" in fresh, "the new crash goes into a fresh log"
    assert "x" * 500 not in fresh, "the fresh log must not contain the old content"


# -- 6) reading the table back for the UI ----------------------------------- #
def _fault(exc_type, message="x"):
    """A real exception of a chosen type. The fingerprint keys on the exception
    TYPE (and stack frame), so different types are different faults - which is how
    these tests create distinct entries without needing distinct call sites."""
    try:
        raise exc_type(message)
    except exc_type as exc:
        return exc


def test_recent_returns_faults_most_frequent_first(isolated):
    crashlog.record(_fault(KeyError), source="a")           # rare: count 1
    crashlog.record(_fault(ValueError), source="b")         # common: count 2
    crashlog.record(_fault(ValueError), source="b")

    entries = crashlog.recent()
    assert len(entries) == 2, f"two distinct faults expected (got {len(entries)})"
    assert entries[0]["count"] == 2, f"most frequent first (got {entries[0]['count']})"
    assert entries[0]["count"] >= entries[-1]["count"], "ordering must be by count desc"


def test_recent_respects_its_limit(isolated):
    for exc_type in (ValueError, KeyError, IndexError, TypeError, RuntimeError):
        crashlog.record(_fault(exc_type), source="s")       # 5 distinct fingerprints
    assert len(crashlog.recent(limit=3)) == 3, "recent(limit=) must cap the list"


def test_summary_counts_errors_swallowed_and_distinct(isolated):
    crashlog.record(_fault(ValueError), source="a", severity=crashlog.ERROR)
    crashlog.record(_fault(KeyError), source="b", severity=crashlog.DEBUG)
    crashlog.record(_fault(KeyError), source="b", severity=crashlog.DEBUG)

    s = crashlog.summary()
    assert s["errors"] == 1, f"one error-severity fault (got {s['errors']})"
    assert s["swallowed"] == 2, f"debug fault counted by occurrence (got {s['swallowed']})"
    assert s["distinct"] == 2, f"two distinct fingerprints (got {s['distinct']})"


def test_summary_is_empty_when_nothing_has_gone_wrong(isolated):
    s = crashlog.summary()
    assert s == {"errors": 0, "swallowed": 0, "distinct": 0}, f"(got {s})"


# -- 8) crashes/ is not created until it can actually be needed -------------- #
def test_launch_creates_no_crash_folder_until_a_capture_arms_it(isolated):
    """Just launching must NOT leave a crashes/ folder - that looked to users like
    something had crashed. Native capture is requested at install but armed lazily,
    the first time a real capture starts."""
    crashlog._arm_wanted[0] = True          # what install(native=True) records
    crashlog._armed[0] = False
    assert not os.path.isdir(crashlog.crash_dir()), "crashes/ appeared before arming"

    crashlog.arm_native()                   # a real capture started (engine.start)
    path = os.path.join(crashlog.crash_dir(), crashlog.NATIVE_NAME)
    try:
        assert os.path.exists(path), "arming did not open the native-crash file"
    finally:
        crashlog._cleanup_native()          # close the faulthandler stream


def test_arm_native_is_a_noop_when_native_was_not_requested(isolated):
    """--simulate / no-native builds never open the file."""
    crashlog._arm_wanted[0] = False
    crashlog.arm_native()
    assert not os.path.isdir(crashlog.crash_dir())


def test_cleanup_removes_the_empty_native_file_and_dir(isolated):
    """A healthy exit must not leave the empty native-crash file (nor an empty
    crashes/ dir) behind."""
    directory = crashlog.crash_dir()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, crashlog.NATIVE_NAME)
    open(path, "w").close()                              # the empty file, as created
    crashlog._native_path = path
    crashlog._native_stream = None

    crashlog._cleanup_native()

    assert not os.path.exists(path), "the empty native-crash file was left behind"
    assert not os.path.isdir(directory), "the now-empty crashes dir was left behind"


def test_cleanup_keeps_a_non_empty_native_file(isolated):
    """A run that actually segfaulted wrote to the file - that must be preserved."""
    directory = crashlog.crash_dir()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, crashlog.NATIVE_NAME)
    with open(path, "w", encoding="utf-8") as f:
        f.write("Fatal Python error: Segmentation fault\n")
    crashlog._native_path = path
    crashlog._native_stream = None

    crashlog._cleanup_native()

    assert os.path.exists(path), "a native crash report must survive a clean exit"
