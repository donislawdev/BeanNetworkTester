"""Crash logging: one sink for every way this program can fail.

Why a whole module
------------------
A tool that grows towards a million lines does not fail in a few places - it fails
in thousands, most of them in code nobody is looking at. There were two problems:

* **Nothing was recorded.** The only handler was Tk's ``report_callback_exception``.
  A crash in a worker thread, a crash before the GUI existed, a crash in the CLI, a
  hard crash in the WinDivert driver - all of it went nowhere. A user could only say
  "it broke", and that was the end of the investigation.
* **102 places said ``except Exception: pass``.** Defensive, and reasonable one at a
  time: the GUI must not die because a tooltip failed. But at scale it means the
  program is *full of failures nobody can see*, and the count only goes up.

This module fixes both. It captures every path a failure can take, writes it
somewhere a user can find and send, and gives the rest of the code a way to swallow
an error **for the user** without hiding it **from the developer** (:func:`quiet`).

What it captures
----------------
======================  ==================================================
``sys.excepthook``      an unhandled exception on the main thread
``threading.excepthook``  the same on a worker - previously recorded NOWHERE,
                        which is how a dead capture thread stayed invisible
Tk callback handler     a crash inside a widget callback
``faulthandler``        a HARD crash (segfault) with no Python traceback at all.
                        This one matters: WinDivert is a kernel driver reached
                        through ctypes, and a bad struct there takes the process
                        down without raising anything Python can catch.
:func:`quiet`           the errors we deliberately swallow, recorded at debug level
:func:`record`          anything else, explicitly
======================  ==================================================

What a crash record contains
----------------------------
Enough to reproduce it, not just read it: the version, the platform, whether the
process is elevated, the pydivert/WinDivert versions, the **seed and the full
settings**, the counters, the last lines of the log, and which page/window was
open. A crash report should be one step away from a repro command - the tool
already knows how to produce one.

The data is written locally and sent nowhere; a user who mails a report is opting
into exactly that.

The two things that would break it at scale
-------------------------------------------
* **Duplicate storms.** A crash inside the tick loop fires 1.4 times a second,
  forever. Records are therefore FINGERPRINTED (exception type + the top frames)
  and counted, not appended: the tenth thousand occurrence of a bug costs a dict
  lookup and one integer, not another disk write. The table that holds those counters is bounded,
  and it makes room by dropping the coldest fault rather than by refusing the
  newest - refusing was the same thing as switching the de-duplication off for
  whatever broke last.
* **Unbounded disk.** The log rotates and is capped, so a program left running for
  a fortnight with a repeating fault cannot fill the volume it is diagnosing.
* **A logger that wedges the program.** Every thread reports here, the capture
  thread and the watchdog included, so the one lock this module owns is never held
  while code from OUTSIDE it runs. The context provider is the App's code, and it
  used to run under that lock: a provider that recorded a fault of its own
  deadlocked its thread on it, and one that waited for the Tk main loop deadlocked
  against a main thread waiting for it. Every later report from every thread then
  queued behind them - the GUI froze and the watchdog stopped watching.
"""
import faulthandler
import hashlib
import json
import os
import platform
import sys
import threading
import time
import traceback
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone

from .appinfo import __version__
from .paths import temp_beside, user_data_dir

CRASH_DIR_NAME = "crashes"
LOG_NAME = "crashes.ndjson"
LATEST_NAME = "latest-crash.txt"
NATIVE_NAME = "native-crash.txt"
# One breadcrumb per process: "breadcrumb-<UTC start>-<pid>.json" (see breadcrumb_name).
BREADCRUMB_PREFIX = "breadcrumb"
BREADCRUMB_NAME = "breadcrumb.json"   # the one name every copy shared before 2026-10-02

MAX_LOG_BYTES = 5 * 1024 * 1024     # rotate past this
MAX_ROTATIONS = 5                   # keep this many old logs
MAX_RECORDS = 2000                  # distinct fingerprints held in memory
MAX_LOG_TAIL = 40                   # log lines attached to a record
STALE_TEMP_S = 60.0                 # a temp breadcrumb this old lost its writer
BREADCRUMB_KEEP_S = 30 * 86400.0    # a breadcrumb nobody took is kept this long
BREADCRUMB_REFRESH_S = 86400.0      # an unchanged breadcrumb is written again after this
BREADCRUMB_RETRY_S = 1.0            # the wait after a failed breadcrumb write...
BREADCRUMB_RETRY_MAX_S = 60.0       # ...doubled after each further one, up to this

# Severity. "error" is a real failure; "debug" is something quiet() swallowed.
ERROR = "error"
DEBUG = "debug"

_lock = threading.Lock()
# Ordered because the order IS the eviction policy: freshest last, so the table
# makes room by dropping the fault nobody has seen for longest. See _record.
_seen: OrderedDict[str, dict] = OrderedDict()   # fingerprint -> record (+ a count)
# A repeat's fingerprint, found without reading its traceback again: (exception
# type, the code and instruction of its last four frames) -> fingerprint. See
# _quick_key for why that pair decides the fingerprint exactly. Cleared, not
# trimmed, when it reaches _QUICK_MAX: it is a shortcut, and losing it costs one
# slow lookup per fault, not a record.
_quick: dict[tuple, str] = {}
_QUICK_MAX = 4 * MAX_RECORDS
# The part of a crash context that cannot change while the process lives, built
# once (see _static_context). None until then.
_static = None
_context_provider = None            # set by the App/CLI: returns a dict of state
# Per thread: is this thread inside the context provider right now? A fault the
# provider itself records must not ask the provider again (see _collect_context).
_local = threading.local()
_installed = False
_enabled = True


# -- where ------------------------------------------------------------------- #
def crash_dir():
    """Directory the crash files live in - the user's data directory, by the profiles."""
    return os.path.join(user_data_dir(), CRASH_DIR_NAME)


def _ensure_dir():
    path = crash_dir()
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return None
    return path


# -- context ----------------------------------------------------------------- #
def set_context_provider(fn):
    """Register a callable returning a dict of app state to attach to every crash.

    The App passes the seed, the settings, the counters and the open page. Whatever
    it returns is best-effort: a context provider that itself raises must not turn a
    crash into two.

    It runs on WHICHEVER thread recorded the fault - the capture thread, the
    watchdog, a worker - so it must read plain data only: no GUI toolkit call (Tk
    waits for its own main loop, which may be the thread waiting on us), and no lock
    a recording thread may already hold. A fault it records itself is recorded
    without asking it again.
    """
    global _context_provider
    _context_provider = fn


def _collect_context():
    static = _static_context()
    base = {
        "version": static["version"],
        "python": static["python"],
        "platform": static["platform"],
        "frozen": static["frozen"],
        "argv": sys.argv[1:],
        "elevated": static["elevated"],
        "pydivert": _module_version("pydivert"),
        "threads": [t.name for t in threading.enumerate()],
    }
    if _context_provider is None:
        return base
    if getattr(_local, "in_provider", False):
        # The provider recorded a fault of its own. Asking it again would run the
        # same failing code again, record again, ask again - recursion, and before
        # the context moved out of the lock, a thread deadlocked on itself.
        base["context_provider_skipped"] = "re-entered"
        return base
    _local.in_provider = True
    try:
        extra = _context_provider() or {}
        if isinstance(extra, dict):
            base.update(extra)
    except Exception as exc:            # a broken provider must not mask the crash
        base["context_provider_failed"] = f"{type(exc).__name__}: {exc}"
    finally:
        _local.in_provider = False
    return base


def _static_context():
    """The facts of a crash context that cannot change while the process lives.

    Built ONCE, because one of them is expensive in a way the rest of this module
    is not: ``platform.platform()`` asks WMI on Windows, and the first call in a
    process MEASURED 58-151 ms on this machine (2026-10-02, CPython 3.14.7; later
    calls are cached by ``platform`` itself). Paid on the thread that failed, that
    was the capture thread standing still at its first ``once()`` while the driver
    queued the user's packets (performance review W-D3). A real capture start
    builds it beforehand (``arm_for_capture``); anywhere else the first record pays
    it once. WMI waits without the interpreter lock (measured: a thread ticking
    every millisecond was late by at most 2.3 ms across the call), so building it
    early stalls nobody else.

    Two threads racing here both build it and the second write wins; the values
    are identical, so there is nothing to lock.
    """
    global _static
    static = _static
    if static is None:
        static = _static = {
            "version": __version__,
            "python": sys.version.split()[0],
            "platform": _platform_text(),
            "frozen": bool(getattr(sys, "frozen", False)),
            "elevated": _is_elevated(),
        }
    return static


def _platform_text():
    """``platform.platform()``, or what can be said without it.

    A broken WMI repository makes that call raise, and a raise inside the context
    used to cost the WHOLE record - ``record`` swallows it and writes nothing.
    """
    try:
        return platform.platform()
    except Exception as exc:
        return f"{sys.platform} (platform.platform() failed: {type(exc).__name__})"


def _is_elevated():
    try:
        if os.name == "nt":
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return None


def _module_version(name):
    """The version of an ALREADY LOADED module, or ``"not loaded"``. Never imports.

    It used to import the module when it was not loaded, on the thread that failed:
    pydivert costs ~97 ms to import here (MEASURED 2026-10-02, ``-X importtime``),
    and under ``--simulate`` or in the GUI before the first START nothing has
    loaded it - so the first fault on any thread paid that, the capture thread
    included (performance review W-D3). A crash report says what the process HAD,
    and a module it never loaded is not part of the failure.
    """
    module = sys.modules.get(name)
    if module is None:
        return "not loaded"
    return getattr(module, "__version__", "present")


# -- fingerprinting ---------------------------------------------------------- #
def _fingerprint(exc_type, frames):
    """Identity of a BUG, not of an occurrence.

    Built from the exception type and the top few frames (file + function + line),
    so the same fault raised a million times is one record with a counter - not a
    million records, and not a full disk.
    """
    parts = [getattr(exc_type, "__name__", str(exc_type))]
    for frame in frames[-4:]:
        parts.append(f"{os.path.basename(frame.filename)}:{frame.name}:{frame.lineno}")
    # sha256, and NOT because this is a signature - it is a dedup key, where a
    # collision would cost one merged crash record and nothing else. The reason
    # is cheaper than that: "sha1" in a source file is a finding in every scanner
    # that looks (Semgrep raised it here), and answering the same false alarm
    # every quarter costs more than the one-word change ever will. Nothing
    # persists these ids between runs, so no stored record is invalidated - a
    # crash text file written by an older version simply carries the old id.
    return hashlib.sha256("|".join(parts).encode("utf-8", "replace")).hexdigest()[:12]


def _subsystem_of(frames):
    """Which part of the program failed - so crashes group by area, not into a heap.

    At a million lines "it crashed" is useless; "it crashed in gui.pages.conns" is a
    place to start. Taken from the deepest frame that belongs to this package.
    """
    for frame in reversed(frames):
        path = frame.filename.replace("\\", "/")
        if "/beantester/" in path:
            tail = path.split("/beantester/", 1)[1]
            return "beantester." + os.path.splitext(tail)[0].replace("/", ".")
    return "unknown"


# -- the sink ---------------------------------------------------------------- #
def record(exc, source="unknown", subsystem=None, severity=ERROR, note=""):
    """Record one failure. Never raises - a crash logger that crashes is worthless."""
    if not _enabled:
        return None
    try:
        return _record(exc, source, subsystem, severity, note)
    except Exception:
        return None


def _quick_key(exc_type, tb):
    """What decides a fault's fingerprint, read straight off the traceback objects.

    The fingerprint is the exception type plus file, function and line of the last
    four frames (``_fingerprint``), and all three come from a frame's CODE object
    and the INSTRUCTION it stopped at: ``extract_tb`` takes the file and function
    from ``f_code`` and the line from the code's position table at ``tb_lasti``.
    So this pair maps to exactly one fingerprint, and a repeat can be counted
    without ``extract_tb``, which builds a summary per frame and asks ``linecache``
    about every file (an ``os.stat`` per frame, and in the frozen build every one
    of them fails).

    The code objects are held by ``_quick``, not the frames: no local of a failed
    call outlives it through here.
    """
    last = []
    while tb is not None:
        last.append((tb.tb_frame.f_code, tb.tb_lasti))
        tb = tb.tb_next
    return (exc_type, tuple(last[-4:]))


def _record(exc, source, subsystem, severity, note):
    exc_type = type(exc)
    tb = exc.__traceback__
    quick = _quick_key(exc_type, tb)
    with _lock:
        fingerprint = _quick.get(quick)
        existing = _seen.get(fingerprint) if fingerprint is not None else None
        if existing is not None:
            # A repeating fault (a crash inside the tick loop fires 1.4x a second;
            # a socket event that fails, once per event) costs a dict lookup and
            # one integer from here on - not a traceback walk, and not another
            # disk write (performance review W-D2; measured in `once` below).
            return _count_again(existing, fingerprint)

    frames = traceback.extract_tb(tb) if tb is not None else []
    fingerprint = _fingerprint(exc_type, frames)

    with _lock:
        if len(_quick) >= _QUICK_MAX:
            _quick.clear()
        _quick[quick] = fingerprint
        existing = _seen.get(fingerprint)
        if existing is not None:
            # A fingerprint can be reached by more than one shortcut key - two
            # instructions on one line, two files with one base name - or the key
            # was dropped when _quick was cleared: still one record, one more
            # occurrence.
            return _count_again(existing, fingerprint)

    # Built OUTSIDE the lock, and that is a deadlock fix, not tidiness (reproduced
    # 2026-09-28, both ways). The context comes from the App's provider: the GUI's
    # read a Tk variable and, on an invalid form field, recorded that ValueError -
    # from inside the lock, into the lock, on the same thread. And a Tk call from a
    # worker waits for the main loop, which could itself be waiting right here.
    # Either way the lock stayed held, and every later report from every thread -
    # the watchdog's too - queued behind it for good.
    entry = {
        "fingerprint": fingerprint,
        "first_seen": _now_iso(),
        "last_seen": _now_iso(),
        "count": 1,
        "severity": severity,
        "source": source,
        "subsystem": subsystem or _subsystem_of(frames),
        "type": getattr(exc_type, "__name__", str(exc_type)),
        "message": str(exc)[:500],
        "note": note,
        "traceback": "".join(
            traceback.format_exception(exc_type, exc, tb))[:8000],
        "context": _collect_context(),
    }
    with _lock:
        existing = _seen.get(fingerprint)
        if existing is not None:
            # Another thread recorded this same NEW fault while this one was
            # building its context: one record, one more occurrence, no second
            # disk write. The context built here is simply dropped.
            return _count_again(existing, fingerprint)
        # The table used to REFUSE a new fingerprint once it was full, and that
        # turned the ceiling into a cliff: a fault arriving late never got a slot,
        # so every one of its occurrences looked new, built a full context and
        # wrote to disk again. MEASURED on this machine (2026-09-03), the same
        # repeating fault: 137 us and zero writes with a slot, 1926 us and a write
        # PER OCCURRENCE without one - 14x, and back then the expensive half was
        # built inside the lock every other caller of this module waits on. In
        # other words the de-duplication this module is built around stopped
        # working exactly when the program was failing most.
        #
        # So the table makes room instead of refusing: in a shipped build it is a
        # dedup CACHE and nothing else, since neither read-back helper at the
        # bottom of this module has a caller in the package (B-16) and the crash
        # log on disk already holds every fault's first occurrence. What eviction
        # costs is therefore one counter nobody reads. What REFUSING costs is the
        # ability to recognise the fault that is happening now, which is the half
        # worth having. (Naming those two helpers here would have been enough to
        # make the dead-code scan call them alive - it counts words, comments
        # included. Their names are in tests/test_code_hygiene.py.)
        _seen[fingerprint] = entry
        if len(_seen) > MAX_RECORDS:
            _seen.popitem(last=False)       # the least recently seen fault

    _write(entry)
    return entry


def _count_again(existing, fingerprint):
    """One more occurrence of a fault already in the table. Caller holds ``_lock``."""
    existing["count"] += 1
    existing["last_seen"] = _now_iso()
    # Freshest last. The eviction in _record drops the OTHER end of the table,
    # and a fault firing right now is the last thing it may drop.
    _seen.move_to_end(fingerprint)
    return existing


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write(entry):
    directory = _ensure_dir()
    if directory is None:
        return
    path = os.path.join(directory, LOG_NAME)
    try:
        _rotate_if_needed(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        return
    if entry["severity"] == ERROR:
        try:
            with open(os.path.join(directory, LATEST_NAME), "w",
                      encoding="utf-8") as f:
                f.write(format_report(entry))
        except OSError:
            pass


def _rotate_if_needed(path):
    try:
        if os.path.getsize(path) < MAX_LOG_BYTES:
            return
    except OSError:
        return
    for i in range(MAX_ROTATIONS - 1, 0, -1):
        older, newer = f"{path}.{i}", f"{path}.{i + 1}"
        if os.path.exists(older):
            try:
                os.replace(older, newer)
            except OSError:
                pass
    try:
        os.replace(path, f"{path}.1")
    except OSError:
        pass


def format_report(entry):
    """The human-readable form - what a user pastes into a bug report."""
    ctx = entry.get("context", {})
    lines = [
        "Bean Network Tester - crash report",
        "=" * 60,
        f"when       : {entry['first_seen']}  (seen {entry['count']}x)",
        f"id         : {entry['fingerprint']}",
        f"where      : {entry['subsystem']}   (via {entry['source']})",
        f"what       : {entry['type']}: {entry['message']}",
        "",
        f"version    : {ctx.get('version')}  frozen={ctx.get('frozen')}",
        f"platform   : {ctx.get('platform')}",
        f"python     : {ctx.get('python')}   pydivert={ctx.get('pydivert')}",
        f"elevated   : {ctx.get('elevated')}",
        f"seed       : {ctx.get('seed')}",
        f"page       : {ctx.get('page')}   running={ctx.get('running')}",
        "",
    ]
    if ctx.get("repro_command"):
        lines += ["reproduce with:", f"  {ctx['repro_command']}", ""]
    if ctx.get("settings"):
        lines += ["settings:",
                  json.dumps(ctx["settings"], indent=2, ensure_ascii=False,
                             sort_keys=True, default=str), ""]
    if ctx.get("counters"):
        lines += ["counters:",
                  json.dumps(ctx["counters"], indent=2, sort_keys=True,
                             default=str), ""]
    if ctx.get("log_tail"):
        lines += ["last log lines:"] + [f"  {line}" for line in ctx["log_tail"]] + [""]
    lines += ["traceback:", entry.get("traceback", "")]
    return "\n".join(lines)


def note(exc, subsystem, message=""):
    """Record an error we are deliberately swallowing. The replacement for ``pass``.

    The user-visible behaviour does not change - a tooltip that will not draw still
    must not take the window down - but the failure stops being invisible. This is
    what the 100-odd ``except Exception: pass`` sites became.
    """
    record(exc, source="swallowed", subsystem=subsystem, severity=DEBUG, note=message)


_once_seen: set[tuple] = set()


def once(subsystem, exc):
    """Record the FIRST occurrence only, at negligible cost. For the packet path.

    ``note()`` walks the traceback and takes a lock even for a fault it has seen.
    This used to say "about a microsecond", and it was never measured. MEASURED
    2026-10-02 (Win11, CPython 3.14.7, one fault raised from a source file, depth
    2 to 32 frames, the disk write stubbed out): a REPEAT cost 198-380 us while
    ``extract_tb`` ran for every occurrence - ``linecache`` stats each frame's
    file - and 3.9-6.9 us since ``_record`` finds a repeat by ``_quick_key``.
    Either is nothing sixty times a second and too much 14 000 times a second
    (a real WinDivert session, measured end to end - see the "What this actually
    sustains" section of ``engine.py``; ``--simulate`` runs ten times that). This
    is a set lookup on a short string (~40 ns), so a malformed packet reports
    itself once and then costs nothing at all.
    """
    if subsystem in _once_seen:
        return
    _once_seen.add(subsystem)
    record(exc, source="hot-path", subsystem=subsystem, severity=DEBUG)


# -- swallowing, without hiding ---------------------------------------------- #
@contextmanager
def quiet(subsystem, note="", severity=DEBUG):
    """Swallow an error for the USER, record it for the DEVELOPER.

    This replaces ``except Exception: pass``. The behaviour the user sees is
    unchanged - a tooltip that cannot be drawn still must not take the window down -
    but the failure stops being invisible.

        with quiet("gui.tooltip"):
            self.tip.destroy()

    Not for per-packet code: a context manager costs about a microsecond, which is
    nothing 60 times a second and quite a lot 150 000 times a second.
    """
    try:
        yield
    except Exception as exc:
        record(exc, source="quiet", subsystem=subsystem, severity=severity, note=note)


# -- installation ------------------------------------------------------------ #
def install(native=True):
    """Take over every failure path. Idempotent."""
    global _installed
    if _installed:
        return
    _installed = True

    previous_hook = sys.excepthook

    def _excepthook(exc_type, value, tb):
        if value is not None:
            value.__traceback__ = tb
            record(value, source="main-thread")
        previous_hook(exc_type, value, tb)

    sys.excepthook = _excepthook

    def _thread_hook(args):
        # Worker crashes were recorded NOWHERE. That is how a dead capture thread -
        # the failure the whole fail-open design exists to catch - stayed invisible.
        if args.exc_value is not None:
            args.exc_value.__traceback__ = args.exc_traceback
            name = args.thread.name if args.thread else "?"
            record(args.exc_value, source=f"thread:{name}")

    threading.excepthook = _thread_hook

    if native:
        # Do NOT open the native-crash file here. It is armed lazily, the first
        # time a real capture starts (see arm_native): just launching the GUI must
        # not leave a crashes/ folder behind that looks like something crashed.
        _arm_wanted[0] = True
        import atexit
        atexit.register(_cleanup_native)


_native_stream = None       # the open faulthandler sink, kept for cleanup
_native_path = None
_arm_wanted = [False]       # native capture was requested at install()
_armed = [False]            # faulthandler is actually enabled (a file now exists)
_breadcrumb_last = None     # the state last written, so an unchanged one costs no disk
_breadcrumb_text = None     # the exact text of that write: what makes the file ours
_breadcrumb_file = None     # this process's own breadcrumb name, chosen at its first write
_breadcrumb_retry_at = 0.0  # monotonic time before which no write is tried again
_breadcrumb_wait = BREADCRUMB_RETRY_S   # what the next failed write waits
_breadcrumb_written_at = 0.0  # wall time of the last write: the sweep reads mtime, wall time too


def arm_native():
    """Enable native (segfault) capture. Idempotent - armed once per process.

    faulthandler must hold its file open BEFORE a hard crash, so it genuinely
    cannot be created only "once a problem occurs". It is therefore armed at the
    two moments a hard crash becomes possible: when a real capture starts (the
    WinDivert kernel driver comes into play - ``engine.start``) and when the GUI
    starts (``cli._run_gui``).

    The GUI half was added on 2026-08-05, after a crash that this design had
    recorded only by luck. The docstring here used to say a native crash "can only
    come from the WinDivert KERNEL DRIVER", and that is simply not true of a Tk
    process: the crash in question was ``access violation`` inside ``tkinter
    mainloop`` with no Python frame above it and no session running. It was
    captured at all only because that process had run a capture EARLIER and this
    function never disarms - a GUI that had never started a session would have left
    nothing behind at all.

    What it costs, said out loud because it is the reason the old design was
    lazier: ``_cleanup_native`` deletes the empty file and the empty directory on a
    CLEAN exit, so a healthy run still leaves nothing - but a GUI killed from Task
    Manager, or one that loses power, now leaves an empty ``crashes/native-crash.txt``
    next to the executable where before it only could after a real session.
    That is the price of recording the next one.

    A ``--simulate`` run or a plain CLI session still arms only at ``engine.start``,
    so nothing changes for them.
    """
    if not _arm_wanted[0] or _armed[0]:
        return
    _armed[0] = True
    _install_faulthandler()


def arm_for_capture():
    """A REAL capture is about to start: arm native capture and build the context.

    ``engine.start`` calls this on the real-driver path, before the handle opens -
    the moment the project's start already reserves for slow work, because nothing
    is queued in the driver yet. Building the fixed context here is what keeps it
    off the capture thread (``_static_context`` says what it costs). Not done by
    ``arm_native`` itself: the GUI arms that at launch, on the thread that is about
    to show the window. ``--simulate`` does not need it - a stalled synthetic
    source delays nobody's packets.
    """
    arm_native()
    _static_context()


def _install_faulthandler():
    """Catch HARD crashes: no Python traceback exists for those.

    WinDivert is a kernel driver reached through ctypes. A bad struct or a use of a
    handle after it was closed takes the process down with a segfault, and Python
    never gets to raise anything. ``faulthandler`` writes the C-level stack to a
    file we can still read afterwards - the difference between "it just vanished"
    and a bug report.
    """
    global _native_stream, _native_path
    directory = _ensure_dir()
    if directory is None:
        return
    try:
        path = os.path.join(directory, NATIVE_NAME)
        stream = open(path, "a", buffering=1)
        faulthandler.enable(file=stream, all_threads=True)
        _native_stream, _native_path = stream, path
    except Exception:
        pass


def breadcrumb(**state):
    """Leave the current UI state on disk, for a crash that cannot write anything.

    ``faulthandler`` can only write STACKS. Everything that makes a crash report
    useful - which page was open, whether a session was running, which windows -
    lives in :func:`set_context_provider`, and that is only ever consulted from
    :func:`record`, i.e. from a Python-level failure. A native crash reaches
    neither. The reported one is exactly that shape: a C-level access violation in
    Tk's own display phase, whose report says nothing about what the tool was
    doing.

    So the state is written BEFORE it is needed, next to the native-crash file and
    removed with it (see ``_cleanup_native``), which keeps the "a healthy run
    leaves nothing behind" property in one place.

    **The de-duplication is what makes this a state hook rather than a heartbeat,
    and it is deliberate that it lives HERE and not in the caller.** The GUI calls
    this from its tick, because that is the one place that cannot forget a new
    piece of state the way three hand-placed call sites would; an unchanged state
    therefore costs a dict comparison and no disk at all. Writing 1.4 times a
    second for the life of the process is precisely the unbounded-disk failure this
    module's own docstring names.

    Best-effort by definition: this must never turn a crash into two, so nothing
    here raises and nothing here is required to have worked.

    What it does NOT do is give up on a state after one failed write. The state is
    remembered only once it is on disk: remembering it first (as this did until
    2026-10-01) turned a single failed write - a temp file another copy swept, a
    replace that lost to another writer - into "this state is never written",
    because every later tick compared equal and returned.

    Nor does it try again on every tick. A write that keeps failing waits
    ``BREADCRUMB_RETRY_S`` before the next try, twice that after the next failure,
    up to ``BREADCRUMB_RETRY_MAX_S``, and one that works starts the count over.
    MEASURED 2026-10-01 with a read-only breadcrumb (the replace fails AFTER the
    temp file is written): every try took about 2 ms of the UI thread and created,
    wrote and deleted one temp file - 1.4 files a second for the life of the
    process. The state current when the wait ends is the one written, so a burst of
    changes during it costs one write, not one each.

    An unchanged state is written again once a day (``BREADCRUMB_REFRESH_S``). Any
    clean exit removes a breadcrumb older than ``BREADCRUMB_KEEP_S``, and nothing
    tells a dead copy's from the one a GUI left unchanged for a month - so without
    this the GUI's own went with them, and a crash after that had no state on disk
    (CodeRabbit on PR #247). Wall time, because that sweep reads the file's mtime.
    """
    global _breadcrumb_last, _breadcrumb_text, _breadcrumb_retry_at, _breadcrumb_wait
    global _breadcrumb_written_at
    if not _armed[0] or not _enabled:
        return False
    if (state == _breadcrumb_last
            and time.time() - _breadcrumb_written_at < BREADCRUMB_REFRESH_S):
        return False
    now = time.monotonic()
    if now < _breadcrumb_retry_at:
        return False
    text = _write_breadcrumb(state)
    if text is None:
        _breadcrumb_retry_at = now + _breadcrumb_wait
        _breadcrumb_wait = min(_breadcrumb_wait * 2, BREADCRUMB_RETRY_MAX_S)
        return False
    _breadcrumb_last, _breadcrumb_text = dict(state), text
    _breadcrumb_written_at = time.time()
    _breadcrumb_wait = BREADCRUMB_RETRY_S
    return True


def breadcrumb_name() -> str:
    """This process's breadcrumb file name: ``breadcrumb-<UTC start>-<pid>.json``.

    Every copy of the program wrote ONE ``breadcrumb.json`` until 2026-10-02, so the
    copy started after a native crash replaced the dead one's state on its first
    tick and deleted it on its clean exit: the stack survived in ``native-crash.txt``
    (appended, never replaced), what the program was doing did not (external
    review NOWE-5b-3, owner decision). One file per process keeps it. The pid alone
    would not: Windows hands a pid out again within seconds, so the restart could
    get the dead copy's number. The moment this process first needed the name is
    in it too, and the two sort the files by start.
    """
    global _breadcrumb_file
    if _breadcrumb_file is None:
        _breadcrumb_file = _breadcrumb_file_name(datetime.now(timezone.utc), os.getpid())
    return _breadcrumb_file


def _breadcrumb_file_name(start, pid):
    """The breadcrumb name of the process ``pid`` that started at ``start`` (UTC)."""
    return f"{BREADCRUMB_PREFIX}-{start:%Y%m%dT%H%M%SZ}-{pid}.json"


def _write_breadcrumb(state):
    """Put ``state`` on disk. The text written, or None when it is not there.

    The text is built BEFORE any file exists, so a state json cannot hold never
    creates one.
    """
    directory = _ensure_dir()
    if directory is None:
        return None
    payload = dict(state)
    payload["written"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["version"] = __version__
    payload["pid"] = os.getpid()
    payload["threads"] = [t.name for t in threading.enumerate()]
    try:
        # The state comes from the UI: a value json cannot serialise must not take
        # the process down on the way to describing a crash.
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return None
    path = os.path.join(directory, breadcrumb_name())
    # Unique per writer: two copies of the GUI both leave a breadcrumb, and they
    # used to leave it through one `breadcrumb.json.tmp`. See paths.temp_beside -
    # and note that this one is written from a TICK, so "two writers at the same
    # moment" is not a corner case here, it is 1.4 chances a second.
    tmp = None
    try:
        tmp = temp_beside(path)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return None
    return text


def _cleanup_native():
    """On a CLEAN exit, drop the empty native-crash file (and dir, if empty).

    ``faulthandler`` has to hold the file open BEFORE a hard crash, so the file is
    created on every launch whether or not anything ever crashed - which is why a
    perfectly healthy run left a puzzling empty ``crashes/native-crash.txt`` next
    to the executable. A real segfault takes the process down and never reaches
    this handler, so the file only survives when it actually holds a crash. The
    ``crashes/`` directory is removed too, but only when it is now empty (a run
    that recorded nothing leaves nothing behind; a run that logged a real fault
    keeps its ``crashes.ndjson`` and the directory with it).

    The breadcrumb goes the same way and for the same reason: it describes the
    state a native crash happened IN, so a clean exit means nobody wants it - but
    only THIS process's breadcrumb (see ``_sweep_breadcrumbs``). Every run of the
    program installs this handler, a ``--doctor`` as much as a second GUI, and each
    used to delete whatever breadcrumb was there: the one a GUI still running had
    written, which its de-duplication then never wrote again.
    """
    global _native_stream, _native_path, _breadcrumb_last, _breadcrumb_text
    # Close the diverts BEFORE the handler that would record a hard crash inside
    # one of them goes away. `atexit` is LIFO, `engine.py` registers its own
    # `_stop_live_engines` at IMPORT and `install()` registers this handler later,
    # so this one runs FIRST - and it used to disable faulthandler while a ctypes
    # call into the WinDivert kernel driver was still to come. MEASURED rather than
    # reasoned (2026-09-03): with a stand-in engine in `_LIVE_ENGINES`,
    # `faulthandler.is_enabled()` read False at the moment `stop()` ran, so a
    # segfault in `divert.close()` at exit would have left nothing at all - the one
    # failure this whole module exists for.
    #
    # Looked up in `sys.modules` rather than imported: `engine` imports THIS module,
    # so an import here would be a cycle, and importing a module at interpreter
    # shutdown is its own hazard. A process that never loaded the engine has no
    # divert to close. The registration in `engine.py` stays as the net for the
    # case where `install()` never ran at all.
    live = sys.modules.get("beantester.engine")
    if live is not None:
        try:
            live._stop_live_engines()       # idempotent: stop() forgets the engine
        except Exception:
            pass
    try:
        faulthandler.disable()
    except Exception:
        pass
    mine, own = _breadcrumb_text, _breadcrumb_file
    _breadcrumb_last = _breadcrumb_text = None
    directory = crash_dir()
    _sweep_breadcrumbs(directory, own, mine)
    stream, path = _native_stream, _native_path
    _native_stream = _native_path = None
    if stream is not None:
        try:
            stream.close()
        except Exception:
            pass
    if path:
        try:
            if os.path.exists(path) and os.path.getsize(path) == 0:
                os.remove(path)
        except OSError:
            pass
    try:
        if os.path.isdir(directory) and not os.listdir(directory):
            os.rmdir(directory)
    except OSError:
        pass


def _sweep_breadcrumbs(directory, own, mine):
    """Remove this process's breadcrumb, and the leftovers nobody will come for.

    ``own`` is this process's file name and ``mine`` the text it wrote there last
    (None: it wrote none). Its file goes only while it still holds exactly that
    text - read, never parsed, see ``_still_holds``.

    Every other breadcrumb belongs to a copy still running or to one that died
    (a native crash, a kill), and nothing here guesses which: a pid says nothing,
    Windows hands it out again within seconds. A dead copy's breadcrumb is the one
    worth keeping - it describes the state a crash happened in - so it stays until
    it is ``BREADCRUMB_KEEP_S`` old, by when nobody will send it anywhere. The one
    name every copy shared before 2026-10-02 (``BREADCRUMB_NAME``) goes the same
    way. A copy still running is not caught by the age: it writes its breadcrumb
    again every ``BREADCRUMB_REFRESH_S``, changed or not.

    A temp file is unique per writer (``paths.temp_beside``) and lives for
    milliseconds, so one older than ``STALE_TEMP_S`` belongs to a writer that was
    killed mid-write - and an orphan here stops ``crashes/`` from ever being
    removed. A younger one may be another copy's write in progress: sweeping it
    made that copy's replace fail. The sweep is by PREFIX, so the temp files of
    every name shape, old and new, go the same way.
    """
    if own is not None:
        path = os.path.join(directory, own)
        if _still_holds(path, mine):
            try:
                os.remove(path)
            except OSError:
                pass
    try:
        names = os.listdir(directory)
    except OSError:
        return
    now = time.time()
    for name in names:
        if not name.startswith(BREADCRUMB_PREFIX) or name == own:
            continue
        if name.endswith(".tmp"):
            keep = STALE_TEMP_S
        elif name.endswith(".json"):
            keep = BREADCRUMB_KEEP_S
        else:
            continue
        leftover = os.path.join(directory, name)
        try:
            if now - os.path.getmtime(leftover) > keep:
                os.remove(leftover)
        except OSError:
            pass


def _still_holds(path, text):
    """True when the file at ``path`` holds exactly ``text``: read, never parsed.

    Compared rather than parsed because this runs at exit, from ``atexit``, on a
    file any copy of the program - or anything else - may have put there. A json
    parser answers deep nesting with ``RecursionError`` (see ``jsonfile``), which
    walked out of the pid check this replaced and left the rest of
    ``_cleanup_native`` undone; and it read the whole file, whatever its size. A
    comparison reads one character more than ``text`` and cannot fail that way.
    """
    if text is None:
        return False                # this process wrote no breadcrumb
    try:
        with open(path, encoding="utf-8") as f:
            return f.read(len(text) + 1) == text
    except (OSError, ValueError):
        return False                # missing, unreadable or not text: not ours


def install_tk(root):
    """Route Tk widget-callback crashes here as well."""
    def handler(exc_type, value, tb):
        if value is not None:
            value.__traceback__ = tb
            record(value, source="tk-callback")
    try:
        root.report_callback_exception = handler
    except Exception:
        pass
    return handler


# -- reading it back --------------------------------------------------------- #
def recent(limit=20):
    """The crashes this process has seen, most frequent first (for the UI)."""
    with _lock:
        entries = list(_seen.values())
    entries.sort(key=lambda e: (-e["count"], e["last_seen"]))
    return entries[:limit]


def summary():
    """One line for the log: what has gone wrong so far."""
    with _lock:
        errors = sum(e["count"] for e in _seen.values() if e["severity"] == ERROR)
        debug = sum(e["count"] for e in _seen.values() if e["severity"] == DEBUG)
        distinct = len(_seen)
    return {"errors": errors, "swallowed": debug, "distinct": distinct}


def reset():
    """Forget everything (tests)."""
    global _native_stream, _native_path, _breadcrumb_last, _breadcrumb_text
    global _breadcrumb_retry_at, _breadcrumb_wait, _breadcrumb_file, _breadcrumb_written_at
    global _static
    with _lock:
        _seen.clear()
        _quick.clear()
    _static = None
    _arm_wanted[0] = False
    _armed[0] = False
    _native_stream = _native_path = None
    _breadcrumb_last = _breadcrumb_text = _breadcrumb_file = None
    _breadcrumb_retry_at, _breadcrumb_wait = 0.0, BREADCRUMB_RETRY_S
    _breadcrumb_written_at = 0.0


def set_enabled(value):
    global _enabled
    _enabled = bool(value)
