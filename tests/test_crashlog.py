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
import sys
import threading

import pytest

from beantester import crashlog


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Point the logger at a temp dir; never touch the real crash folder."""
    monkeypatch.setattr(crashlog, "user_data_dir", lambda: str(tmp_path))
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


def test_an_unhandled_main_thread_exception_is_recorded(isolated):
    """``install()`` claims to take over EVERY failure path; only the worker one
    was guarded. Mutation-checked 2026-08-01: gutting this hook left 106 tests
    green, so the main thread - where a CLI run and the Tk mainloop both live -
    could die without leaving a single line behind.

    The previous ``sys.excepthook`` must still run: we record, we do not swallow.
    """
    crashlog.install(native=False)
    chained = []
    try:
        previous = sys.excepthook
        exc = _boom("main thread died")
        sys.excepthook(type(exc), exc, exc.__traceback__)

        written = _entries(isolated)
        assert any(e["type"] == "ValueError" and "main thread died" in e["message"]
                   and e.get("source") == "main-thread" for e in written), written

        # the hook is a wrapper, not a replacement
        crashlog.reset()
        sys.excepthook = lambda *a: chained.append(a)
        crashlog.install(native=False)
        exc2 = _boom("still chained")
        sys.excepthook(type(exc2), exc2, exc2.__traceback__)
        assert chained, "install() must call the excepthook it replaced"
    finally:
        sys.excepthook = sys.__excepthook__
        crashlog.reset()


def test_a_tk_callback_crash_is_recorded(isolated):
    """Widget callbacks are the third failure path, and the one a user actually
    triggers by clicking. Tk swallows them into its own reporter, so without this
    hook a crash inside a button handler reached nobody. Mutation-checked with
    the main-thread hook above: gutting it changed nothing in the suite."""
    class _Root:
        report_callback_exception = None

    root = _Root()
    handler = crashlog.install_tk(root)
    assert root.report_callback_exception is handler, "the hook must be attached"

    exc = _boom("clicked something fatal")
    handler(type(exc), exc, exc.__traceback__)

    written = _entries(isolated)
    assert any(e["type"] == "ValueError" and "clicked something fatal" in e["message"]
               and e.get("source") == "tk-callback" for e in written), written


def test_attaching_the_tk_hook_to_a_hostile_root_is_not_a_crash(isolated):
    """``install_tk`` runs during startup; a root that refuses the attribute must
    not take the app down with it."""
    class _Hostile:
        def __setattr__(self, name, value):
            raise RuntimeError("no attributes here")

    handler = crashlog.install_tk(_Hostile())
    assert callable(handler), "it still hands back a usable handler"


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
    """Importing the package must NOT leave a crashes/ folder - that looked to users
    like something had crashed. Native capture is requested at install() and armed
    later, at the two points a hard crash becomes possible: a real capture starting
    (engine.start) and the GUI starting (cli._run_gui)."""
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


# -- 9) the GUI arms too, and leaves a breadcrumb the C stack cannot carry ---- #
def test_the_gui_arms_native_capture_without_ever_starting_a_capture(isolated, monkeypatch):
    """The reported crash: ``access violation`` in ``tkinter mainloop``, no Python
    frame above it, no session running.

    It was recorded ONLY because that process had started a capture earlier in its
    life (arm_native never disarms). A GUI that never starts a session would have
    left nothing at all, which is the hole this closes.

    Driven with tkinter made un-importable on purpose, so the test asserts the same
    thing on the Linux runner as on this machine - see the comment in cli._run_gui.
    Reaching a real Tk root here would make it a Windows-only guard pretending to
    be a general one.
    """
    from beantester import cli, exitcodes, winenv

    monkeypatch.setattr(winenv, "is_windows", lambda: False)   # skip the elevation dance
    monkeypatch.setattr(cli, "is_frozen", lambda: False)
    monkeypatch.setitem(sys.modules, "tkinter", None)          # import tkinter -> ImportError
    crashlog._arm_wanted[0] = True                             # what install(native=True) records

    try:
        code = cli._run_gui([])
        assert code == exitcodes.RUNTIME, "a GUI with no tkinter still reports RUNTIME"
        assert crashlog._armed[0], (
            "the GUI entry point must arm native capture; without this a hard crash "
            "in a process that never ran a capture is recorded NOWHERE")
        assert os.path.exists(os.path.join(crashlog.crash_dir(), crashlog.NATIVE_NAME)), (
            "arming must actually open the native-crash file - faulthandler cannot "
            "create it after the crash")
    finally:
        crashlog._cleanup_native()


def test_a_breadcrumb_records_what_a_native_crash_report_cannot(isolated):
    """faulthandler writes STACKS. Which page was open is nowhere in one."""
    crashlog._arm_wanted[0] = True
    crashlog.arm_native()
    try:
        assert crashlog.breadcrumb(page="stats", running=True, windows=["help"])
        path = os.path.join(crashlog.crash_dir(), crashlog.BREADCRUMB_NAME)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["page"] == "stats", f"the open page must be in it (got {data!r})"
        assert data["running"] is True, "whether a session was running must be in it"
        assert data["windows"] == ["help"], "the open windows must be in it"
        assert data["threads"], "the thread names are what say 'no session was running'"
    finally:
        crashlog._cleanup_native()


def test_an_unchanged_breadcrumb_costs_no_disk_write(isolated):
    """The GUI calls this from its TICK, so the de-duplication is what stops it
    being 1.4 disk writes a second for the life of the process - the unbounded-disk
    failure this module's own docstring names."""
    crashlog._arm_wanted[0] = True
    crashlog.arm_native()
    try:
        assert crashlog.breadcrumb(page="control", running=False, windows=[])
        assert not crashlog.breadcrumb(page="control", running=False, windows=[]), (
            "an unchanged state must not be rewritten")
        assert crashlog.breadcrumb(page="conns", running=False, windows=[]), (
            "a CHANGED state must still be written")
    finally:
        crashlog._cleanup_native()


def test_no_breadcrumb_before_anything_is_armed(isolated):
    """Same rule as the native file: nothing appears until a hard crash is possible,
    or a plain `import beantester` leaves a crashes/ folder behind again."""
    crashlog._arm_wanted[0] = False
    crashlog._armed[0] = False
    assert not crashlog.breadcrumb(page="control", running=False, windows=[])
    assert not os.path.isdir(crashlog.crash_dir()), "crashes/ appeared before arming"


def test_a_breadcrumb_that_cannot_be_serialised_is_swallowed(isolated):
    """The state comes from the UI. A value json cannot write must not take the
    process down ON THE WAY TO DESCRIBING A CRASH - and must not leave the half
    written temp file behind either, because a stray .tmp keeps the directory from
    ever being cleaned up again."""
    crashlog._arm_wanted[0] = True
    crashlog.arm_native()
    try:
        assert not crashlog.breadcrumb(page=object(), running=False, windows=[])
        tmp = os.path.join(crashlog.crash_dir(), crashlog.BREADCRUMB_NAME + ".tmp")
        assert not os.path.exists(tmp), "a failed write left its temp file behind"
    finally:
        crashlog._cleanup_native()


def test_the_running_gui_actually_leaves_one(isolated):
    """The wiring, not just the mechanism.

    Everything above proves ``breadcrumb()`` works if somebody calls it. This is
    the half that rots: the App calls it from ``_tick``, and a tick that stopped
    doing so would leave every test above green and every real crash unexplained.
    """
    from gui_harness import run_gui

    out = run_gui("""
        import json, os
        from beantester import crashlog
        crashlog._arm_wanted[0] = True
        crashlog.arm_native()

        app.select_page("statistics")     # the page the reported crash happened on
        app._tick()

        path = os.path.join(crashlog.crash_dir(), crashlog.BREADCRUMB_NAME)
        assert os.path.exists(path), "a tick left no breadcrumb"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["page"] == "statistics", data
        assert data["running"] is False, data
        print("BREADCRUMB_OK", data["page"])
        crashlog._cleanup_native()
    """)
    assert "BREADCRUMB_OK statistics" in out, out


def test_a_clean_exit_takes_the_breadcrumb_with_it(isolated):
    """It describes the state a crash happened IN. No crash, nobody wants it - and
    the 'a healthy run leaves nothing behind' promise stays true for both files."""
    crashlog._arm_wanted[0] = True
    crashlog.arm_native()
    crashlog.breadcrumb(page="stats", running=True, windows=[])
    path = os.path.join(crashlog.crash_dir(), crashlog.BREADCRUMB_NAME)
    assert os.path.exists(path)

    crashlog._cleanup_native()

    assert not os.path.exists(path), "the breadcrumb outlived a clean exit"
    assert not os.path.isdir(crashlog.crash_dir()), "the now-empty crashes dir was left"
