"""Windows process environment: Administrator rights, console and DPI.

Everything here is a no-op on other platforms so the engine, the CLI and the
tests stay portable.

Why this module exists
----------------------
The tool now ships as ONE console-subsystem executable that serves both modes
(convention: the docs only ever mention ``BeanNetworkTester.exe``):

  * a console subsystem is what makes the CLI usable at all - a ``--noconsole``
    (GUI subsystem) exe has no stdout/stderr, and cmd.exe/PowerShell do not
    even *wait* for it, so a CI step could never see its output or exit code,
  * the GUI therefore detaches from the console right after start
    (``detach_console``), so a double-clicked exe does not leave a black window
    behind and a GUI launched from a shell does not hijack it,
  * the manifest is ``asInvoker`` (not ``requireAdministrator``): elevation
    always spawns a NEW process, which breaks the caller's pipes and exit code.
    Instead the GUI elevates itself on demand (``elevate_self``) and the CLI
    fails fast with a clear message and exit code ``PERMISSION``.
"""
import os
import sys

from .paths import is_frozen
from . import crashlog


def is_windows():
    return sys.platform.startswith("win")


def is_admin():
    """True when the process holds an elevated (Administrator) token.

    Outside Windows there is nothing to elevate, so the answer is True: the
    engine's real requirement is WinDivert, which only exists on Windows.
    """
    if not is_windows():
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevation_disabled():
    """Escape hatch for CI and tests: ``BEAN_NO_ELEVATE=1``."""
    return str(os.environ.get("BEAN_NO_ELEVATE", "")).strip() not in ("", "0")


def _quote(arg):
    return '"%s"' % str(arg).replace('"', r"\"")


def elevate_self(argv=None):
    """Relaunch this process elevated (UAC prompt). True = relaunched, exit now.

    Returns False when nothing was done: not Windows, already elevated,
    disabled by env, or the user dismissed the UAC prompt. The caller then
    continues unelevated (the GUI keeps working; only starting a real capture
    session will fail, with an explanatory dialog).
    """
    if not is_windows() or is_admin() or elevation_disabled():
        return False
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        import ctypes
        if is_frozen():
            program, args = sys.executable, argv
        else:                       # running from sources: elevate the interpreter
            program, args = sys.executable, [os.path.abspath(sys.argv[0])] + argv
        params = " ".join(_quote(a) for a in args)
        # ShellExecuteW with the "runas" verb is the only supported way to ask
        # for elevation; a return value <= 32 means it did not start (e.g. 1223
        # = the user clicked "No").
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", program, params, os.getcwd(), 1)
        return int(rc) > 32
    except Exception:
        return False


def detach_console():
    """Detach the (console-subsystem) process from its console - GUI mode only.

    If we own the console it closes with us; if we were started from cmd.exe
    the shell keeps its own window, we simply stop writing to it. Standard
    streams are replaced with a null sink so a stray ``print`` in GUI code can
    never raise.
    """
    if not is_windows():
        return False
    try:
        import ctypes
        ok = bool(ctypes.windll.kernel32.FreeConsole())
    except Exception:
        return False
    try:
        null = open(os.devnull, "w", encoding="utf-8")
        sys.stdout = sys.stderr = null
    except OSError:
        sys.stdout = sys.stderr = None
    return ok


# The finest tick the timeBeginPeriod API accepts, and the one the injector wants.
TIMER_PERIOD_MS = 1

# Windows 11 throttles a BACKGROUND process's timer resolution request unless the
# process opts out (see _allow_fine_timers_in_background). Done once per process.
_TIMER_OPT_OUT = [None]

_PROCESS_POWER_THROTTLING = 4        # PROCESS_INFORMATION_CLASS
_IGNORE_TIMER_RESOLUTION = 0x4       # PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION


def _allow_fine_timers_in_background():
    """Tell Windows to honour our timer request even when we are not in front.

    Without this, ``timeBeginPeriod`` on Windows 11 is a fix that WORKS ON THE
    DEVELOPER'S MACHINE AND THEN STOPS. Measured here: the request kept being
    granted (return code 0, request/release perfectly balanced) while the effect
    quietly went away after roughly ten seconds - ``Condition.wait(10 ms)`` went
    10.1, 10.3, then back to 15.6 ms for every later session in the same process.
    That is the OS declining to honour a background process's request, and this
    tool spends its whole working life in the background: the tester starts a
    session and switches to the application under test.

    With the opt-out the same wait stayed at 10.1-10.7 ms across 40 s of sampling.

    Called once per process; the policy costs nothing while we are not asking for
    a fine tick, so there is nothing to undo. Fails harmlessly on Windows older
    than 10 1709, which had no such throttling to opt out of.
    """
    if _TIMER_OPT_OUT[0] is not None:
        return _TIMER_OPT_OUT[0]
    _TIMER_OPT_OUT[0] = False
    if not is_windows():
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class _PowerThrottlingState(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG),
                        ("ControlMask", wintypes.ULONG),
                        ("StateMask", wintypes.ULONG)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                   ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetProcessInformation.restype = wintypes.BOOL
        # ControlMask says which policy we are setting, StateMask=0 says "do NOT
        # ignore my timer resolution" - i.e. honour it in the background too.
        state = _PowerThrottlingState(1, _IGNORE_TIMER_RESOLUTION, 0)
        _TIMER_OPT_OUT[0] = bool(kernel32.SetProcessInformation(
            kernel32.GetCurrentProcess(), _PROCESS_POWER_THROTTLING,
            ctypes.byref(state), ctypes.sizeof(state)))
    except Exception as _exc:
        crashlog.note(_exc, "winenv")
    return _TIMER_OPT_OUT[0]


def request_fine_timers(period_ms=TIMER_PERIOD_MS):
    """Ask Windows for a fine timer tick. True when granted (Windows only).

    ``BeanEngine`` holds a delayed packet by waiting on a Condition with a
    timeout, and on Windows such a timeout is rounded UP to the system timer
    tick - 15.6 ms unless THIS process asks for better. That rounding is the
    whole of the added-latency error: measured on Win11 / CPython 3.14,
    ``Condition.wait(1 ms)`` took a median of 15.56 ms, and the engine overshot a
    configured 10 ms of latency by a median of 8.30 ms.

    **Reading the system-wide resolution proves nothing here.** Since Windows 10
    2004 the tick is per-process: this machine was already running a 1.0 ms tick
    (``NtQueryTimerResolution`` said so - something else had asked for it) while
    our waits were still being rounded to 15.6 ms. A future session that queries
    the global value and concludes "the timer is already fine" would be reading a
    number that does not apply to us. Only asking changes anything: after
    ``timeBeginPeriod(1)`` the same wait took 1.51 ms and the engine's overshoot
    fell to 0.54 ms.

    The OS refcounts these per process, so every request MUST be matched by a
    :func:`release_fine_timers`. The call costs ~1.3 us for the pair (measured),
    so it belongs to the session, not to the process: nothing holds a finer tick
    while the tool sits idle.
    """
    if not is_windows():
        return False
    # Order matters only in that the opt-out has to be in place for the request to
    # be honoured; it is a process-wide policy, so it is set once and left alone.
    _allow_fine_timers_in_background()
    try:
        import ctypes
        return ctypes.WinDLL("winmm").timeBeginPeriod(int(period_ms)) == 0
    except Exception as _exc:
        crashlog.note(_exc, "winenv")
        return False


def release_fine_timers(period_ms=TIMER_PERIOD_MS):
    """Give back one :func:`request_fine_timers`. Call ONLY for a granted request.

    Unbalanced calls are how a process ends up holding a fine tick for its whole
    life (or giving back one it never took), so the caller tracks whether the
    request was granted rather than releasing blindly.
    """
    if not is_windows():
        return False
    try:
        import ctypes
        return ctypes.WinDLL("winmm").timeEndPeriod(int(period_ms)) == 0
    except Exception as _exc:
        crashlog.note(_exc, "winenv")
        return False


def set_dpi_awareness():
    """Mark the process DPI-aware BEFORE the Tk root exists.

    Per-Monitor-V2 first: with the old "system aware" mode the window is bitmap
    scaled (blurry) as soon as it is dragged to a monitor with a different
    scaling factor, which is the normal laptop + external screen setup.
    """
    if not is_windows():
        return None
    import ctypes
    try:                                   # Win 10 1703+: per-monitor v2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return "per-monitor-v2"
    except Exception as _exc:
        crashlog.note(_exc, "winenv")
    for attempt, call in (
            ("per-monitor", lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2)),
            ("system", lambda: ctypes.windll.shcore.SetProcessDpiAwareness(1)),
            ("legacy", lambda: ctypes.windll.user32.SetProcessDPIAware())):
        try:
            call()
            return attempt
        except Exception:
            continue
    return None
