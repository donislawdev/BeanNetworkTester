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
  and counted, not appended: the tenth thousand occurrence of a bug costs one
  integer, not another disk write.
* **Unbounded disk.** The log rotates and is capped, so a program left running for
  a fortnight with a repeating fault cannot fill the volume it is diagnosing.
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
from contextlib import contextmanager
from datetime import datetime, timezone

from .appinfo import __version__
from .paths import app_dir

CRASH_DIR_NAME = "crashes"
LOG_NAME = "crashes.ndjson"
LATEST_NAME = "latest-crash.txt"
NATIVE_NAME = "native-crash.txt"

MAX_LOG_BYTES = 5 * 1024 * 1024     # rotate past this
MAX_ROTATIONS = 5                   # keep this many old logs
MAX_RECORDS = 2000                  # distinct fingerprints held in memory
MAX_LOG_TAIL = 40                   # log lines attached to a record

# Severity. "error" is a real failure; "debug" is something quiet() swallowed.
ERROR = "error"
DEBUG = "debug"

_lock = threading.Lock()
_seen = {}                          # fingerprint -> record (with a count)
_context_provider = None            # set by the App/CLI: returns a dict of state
_installed = False
_enabled = True


# -- where ------------------------------------------------------------------- #
def crash_dir():
    """Directory the crash files live in. Next to the executable, like the profiles."""
    return os.path.join(app_dir(), CRASH_DIR_NAME)


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

    The App passes the seed, the settings, the counters and the open page; the CLI
    passes the parsed configuration. Whatever it returns is best-effort: a context
    provider that itself raises must not turn a crash into two.
    """
    global _context_provider
    _context_provider = fn


def _collect_context():
    base = {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "argv": sys.argv[1:],
        "elevated": _is_elevated(),
        "pydivert": _module_version("pydivert"),
        "threads": [t.name for t in threading.enumerate()],
    }
    if _context_provider is not None:
        try:
            extra = _context_provider() or {}
            if isinstance(extra, dict):
                base.update(extra)
        except Exception as exc:            # a broken provider must not mask the crash
            base["context_provider_failed"] = f"{type(exc).__name__}: {exc}"
    return base


def _is_elevated():
    try:
        if os.name == "nt":
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return None


def _module_version(name):
    try:
        module = sys.modules.get(name) or __import__(name)
        return getattr(module, "__version__", "present")
    except Exception:
        return None


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
    return hashlib.sha1("|".join(parts).encode("utf-8", "replace")).hexdigest()[:12]


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


def _record(exc, source, subsystem, severity, note):
    exc_type = type(exc)
    tb = exc.__traceback__
    frames = traceback.extract_tb(tb) if tb is not None else []
    fingerprint = _fingerprint(exc_type, frames)

    with _lock:
        existing = _seen.get(fingerprint)
        if existing is not None:
            existing["count"] += 1
            existing["last_seen"] = _now_iso()
            # A repeating fault (a crash inside the tick loop fires 1.4x a second)
            # costs one integer from here on - not another disk write.
            return existing

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
        if len(_seen) < MAX_RECORDS:
            _seen[fingerprint] = entry

    _write(entry)
    return entry


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


_once_seen = set()


def once(subsystem, exc):
    """Record the FIRST occurrence only, at negligible cost. For the packet path.

    ``note()`` builds a traceback and takes a lock - about a microsecond. That is
    nothing sixty times a second, and about 15% of a core at 150 000 packets a
    second, which is what the capture loop actually runs at. This is a set lookup on
    a short string (~40 ns): a malformed packet reports itself once and then costs
    nothing at all.
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


def arm_native():
    """Enable native (segfault) capture - lazily, when it can actually happen.

    faulthandler must hold its file open BEFORE a hard crash, so it genuinely
    cannot be created only "once a problem occurs". But a native crash can only
    come from the WinDivert KERNEL DRIVER, which nothing touches until a real
    capture starts - so it is armed THEN, not at launch. The effect the user
    asked for: opening the GUI, or a ``--simulate`` run, creates no ``crashes/``
    folder at all; ``native-crash.txt`` appears only once the driver is in play,
    and a clean exit removes it again if nothing was written (see _cleanup_native).
    Idempotent - a start/stop/start cycle arms it once.
    """
    if not _arm_wanted[0] or _armed[0]:
        return
    _armed[0] = True
    _install_faulthandler()


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
    """
    global _native_stream, _native_path
    try:
        faulthandler.disable()
    except Exception:
        pass
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
        directory = crash_dir()
        if os.path.isdir(directory) and not os.listdir(directory):
            os.rmdir(directory)
    except OSError:
        pass


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
    global _native_stream, _native_path
    with _lock:
        _seen.clear()
    _arm_wanted[0] = False
    _armed[0] = False
    _native_stream = _native_path = None


def set_enabled(value):
    global _enabled
    _enabled = bool(value)
