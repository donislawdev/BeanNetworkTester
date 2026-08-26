"""Windows process environment: Administrator rights, console and DPI.

Everything here is a no-op on other platforms so the engine, the CLI and the
tests stay portable - with ONE deliberate exception, marked as such where it
lives: :func:`request_fast_thread_switch` tunes the CPython interpreter, not
Windows, so it does its work everywhere. It sits here because this is where the
process-global knobs live - the ones a SESSION takes and must give back
(:func:`request_fine_timers` is the other one), and having them in one place is
what keeps the give-back paths symmetrical.

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
import threading

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


# -- window-manager bindings, with FULL prototypes --------------------------- #
# These live here and not in ``gui/theme.py`` for two reasons: they are Win32,
# not Tk (this module is where the process-level Windows knobs already are), and
# a test that walks them must not need tkinter, or the guard is vacuous on a
# runner without it.
#
# WHY the prototypes, and what is actually measured. ctypes defaults every
# argument and the return value to C ``int`` (32-bit). That already crashed this
# project once - see ``driver._advapi``, where a truncated 64-bit SC_HANDLE took
# the interpreter down with an access violation on CI. The calls below were
# written without prototypes for a long time, and the honest answer about THEM,
# measured on this machine 2026-08-05 rather than reasoned about, is narrower:
#
#   * ``GetParent`` returned the SAME value both ways. A window handle is
#     documented as a 32-bit-safe value, so truncating it is harmless in practice.
#   * ``GetWindowLongPtrW(GWL_STYLE)`` returned the same value for the root window
#     (0x16cf0008) and for a withdrawn Toplevel (0x06cf0008) - the only two shapes
#     ``disable_maximize`` is ever called on, replayed in its exact call order.
#   * It returned a DIFFERENT value for a WS_POPUP window: a transient dialog
#     (0x94cc0008) and the tooltip bubble (0x96000008) both have the top bit set,
#     so the default signed 32-bit restype reads them as NEGATIVE - and writing
#     that back through ``SetWindowLongPtr`` would pass a sign-extended value
#     where a 64-bit LONG_PTR is expected.
#
# So the hazard is REACHABLE but not currently REACHED: no call site today both
# reads a popup's style and writes it back. That is a property of today's call
# sites, not of this code, and one transient non-resizable window would end it.
# Declaring the prototypes costs nothing and removes the whole question.
_USER32 = [None]
_DWMAPI = [None]
_MONITORINFO = [None]

# MonitorFromPoint: the point is on no monitor at all (a window dragged past the
# edge of the desktop), so answer with the nearest one rather than nothing.
MONITOR_DEFAULTTONEAREST = 2


def monitorinfo_type():
    """The ``MONITORINFO`` layout, built on first use and cached.

    Not at module scope, and not a plain ``c_void_p`` at the call site either:
    ``ctypes.wintypes`` cannot even be IMPORTED off Windows (which is why every
    binding in this file is lazy), and this is the one struct here the system
    WRITES THROUGH a pointer we hand it - the shape that took the interpreter
    down in ``driver._advapi``. Declaring it is what makes the prototype real.
    """
    if _MONITORINFO[0] is None:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD),
                        ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT),
                        ("dwFlags", wintypes.DWORD)]

        _MONITORINFO[0] = MONITORINFO
    return _MONITORINFO[0]


def user32():
    """user32 with full prototypes, or None off Windows. Cached."""
    if _USER32[0] is not None:
        return _USER32[0] or None
    _USER32[0] = False
    if not is_windows():
        return None
    with crashlog.quiet("winenv.user32"):
        import ctypes
        from ctypes import wintypes

        lib = ctypes.WinDLL("user32", use_last_error=True)
        H = wintypes.HWND
        lib.GetParent.argtypes = [H]
        lib.GetParent.restype = H
        lib.SetWindowPos.argtypes = [H, H, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.UINT]
        lib.SetWindowPos.restype = wintypes.BOOL
        # HMONITOR is a HANDLE, so its result is pointer-sized: exactly the shape
        # ctypes' default 32-bit restype truncates.
        lib.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        lib.MonitorFromPoint.restype = wintypes.HMONITOR
        lib.GetMonitorInfoW.argtypes = [wintypes.HMONITOR,
                                        ctypes.POINTER(monitorinfo_type())]
        lib.GetMonitorInfoW.restype = wintypes.BOOL
        # 64-bit Windows has the ...Ptr forms; 32-bit has only the plain ones, and
        # there LONG_PTR is a LONG. Declared for whichever this build actually has,
        # so the guard walks what exists instead of a list somebody wrote down.
        for name, result in (("GetWindowLongPtrW", ctypes.c_ssize_t),
                             ("GetWindowLongW", ctypes.c_long)):
            if hasattr(lib, name):
                fn = getattr(lib, name)
                fn.argtypes = [H, ctypes.c_int]
                fn.restype = result
        for name, value in (("SetWindowLongPtrW", ctypes.c_ssize_t),
                            ("SetWindowLongW", ctypes.c_long)):
            if hasattr(lib, name):
                fn = getattr(lib, name)
                fn.argtypes = [H, ctypes.c_int, value]
                fn.restype = value
        _USER32[0] = lib
    return _USER32[0] or None


def dwmapi():
    """dwmapi with full prototypes, or None off Windows (and pre-Vista). Cached."""
    if _DWMAPI[0] is not None:
        return _DWMAPI[0] or None
    _DWMAPI[0] = False
    if not is_windows():
        return None
    with crashlog.quiet("winenv.dwmapi"):
        import ctypes
        from ctypes import wintypes

        lib = ctypes.WinDLL("dwmapi", use_last_error=True)
        lib.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                              ctypes.c_void_p, wintypes.DWORD]
        lib.DwmSetWindowAttribute.restype = ctypes.c_long        # HRESULT
        _DWMAPI[0] = lib
    return _DWMAPI[0] or None


# What the prototype guard walks. A factory added here without an entry is a
# factory nothing checks, so the list is the registry and the test reads it -
# rather than the test naming six function names that drift the day one moves.
NATIVE_FACTORIES = {"user32": user32, "dwmapi": dwmapi}


def monitor_work_area(x, y):
    """The usable rectangle of the monitor showing ``(x, y)``: ``(l, t, r, b)``.

    ``None`` off Windows, or when the system will not answer - callers must have
    a fallback, and today's fallback is the primary screen, which is what the
    whole program used before this existed.

    WHY THIS IS NOT ``winfo_screenwidth()``. Tk has no concept of a second
    monitor: on Windows it reports the screen as ``GetSystemMetrics(SM_CXSCREEN)``,
    which Microsoft documents as ALWAYS the primary monitor, "not necessarily the
    monitor that displays your application" ("Positioning Objects on Multiple
    Display Monitors"). Anything that clamps a window into ``(0, 0, screen_w,
    screen_h)`` therefore drags it back onto the primary monitor - reported
    2026-08-26 for the tooltip bubble, which appeared on the first monitor while
    the window it explained was on the second.

    Three properties this returns that the screen metrics cannot:

    * the rectangle of the monitor the point is really on, whichever that is;
    * NEGATIVE coordinates, because the primary monitor owns the origin and a
      monitor placed left of - or above - it lives at negative x/y. Measured on
      this machine 2026-08-26: Tk honours ``wm_geometry("+-500+100")`` as a real
      position, so a bubble can be put there;
    * the WORK area, not the whole monitor, so a bubble at the bottom of the
      screen no longer slides under the taskbar (measured here: 2160 px of
      monitor, 2088 px of work area).

    Deliberately NOT cached: monitors are plugged in, unplugged and rearranged
    while the program runs, and a cached rectangle would be a stale answer that
    nothing invalidates. The price of asking every time was MEASURED rather than
    assumed - 4 us per call on this machine, 2026-08-26 - against one call per
    hover, after a 400 ms delay. A cache here would buy nothing and owe an
    invalidation nobody would write.
    """
    lib = user32()
    if lib is None:
        return None
    with crashlog.quiet("winenv.monitor"):
        import ctypes
        from ctypes import wintypes

        handle = lib.MonitorFromPoint(wintypes.POINT(int(x), int(y)),
                                      MONITOR_DEFAULTTONEAREST)
        if not handle:
            return None
        info = monitorinfo_type()()
        info.cbSize = ctypes.sizeof(info)
        if not lib.GetMonitorInfoW(handle, ctypes.byref(info)):
            return None
        area = info.rcWork
        if area.right <= area.left or area.bottom <= area.top:
            # A monitor with no usable area is not an answer, it is a reason to
            # fall back. Nothing observed producing one; it costs one comparison.
            return None
        return (int(area.left), int(area.top), int(area.right), int(area.bottom))
    return None


# QueryPerformanceCounter, because that is the clock WinDivert stamps its packets
# with: ``Packet.timestamp`` is a raw QPC value, so the ONLY way to turn it into
# "how long did this packet wait in the driver" is to read the same counter. Not
# time.perf_counter(): it is derived from QPC but carries an arbitrary epoch
# offset, so subtracting a raw stamp from it is meaningless.
_QPC_FREQ = [None]      # ticks per second; read once, it cannot change


def qpc_frequency():
    """QPC ticks per second, or ``None`` where there is no QPC (non-Windows)."""
    if _QPC_FREQ[0] is None:
        if not is_windows():
            _QPC_FREQ[0] = 0
        else:
            with crashlog.quiet("winenv.qpc"):
                import ctypes
                freq = ctypes.c_int64()
                if ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(freq)):
                    _QPC_FREQ[0] = int(freq.value)
            if _QPC_FREQ[0] is None:
                _QPC_FREQ[0] = 0
    return _QPC_FREQ[0] or None


def qpc_now():
    """The current QPC tick count, or ``None`` where there is no QPC.

    Costs one syscall-ish call, so the caller decides how often to ask - this is
    not something to do per packet (see ``BeanEngine._sample_driver_wait``).
    """
    if not is_windows():
        return None
    try:
        import ctypes
        counter = ctypes.c_int64()
        if ctypes.windll.kernel32.QueryPerformanceCounter(ctypes.byref(counter)):
            return int(counter.value)
    except Exception as _exc:
        crashlog.once("winenv.qpc", _exc)
    return None


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


# How long a thread waiting for the interpreter lock sleeps before it insists.
# CPython ships 5 ms. MEASURED as the engine's binding constraint - see
# request_fast_thread_switch - and 0.5 ms is the KNEE, not the floor: 1 ms still
# behaves like 5 ms, and 0.1 / 0.05 / 0.01 ms buy nothing more.
THREAD_SWITCH_S = 0.0005

# [saved original, holders]. Not the OS's refcount (there is none for this) -
# ours, because two engines can live in one process and the second one to stop
# must not restore a value the first one is still relying on. Guarded: two
# engines starting at once would otherwise both read 0 holders, and the one that
# saved SECOND would save the already-shortened interval and "restore" that for
# the life of the process. Taken on start/stop only, never per packet.
_SWITCH_STATE = [None, 0]
_SWITCH_LOCK = threading.Lock()


def request_fast_thread_switch(interval_s=THREAD_SWITCH_S):
    """Shorten the interpreter's thread-switch interval for this SESSION.

    NOT a Windows call - this one tunes CPython and works on every platform. It
    lives beside :func:`request_fine_timers` because it is the same KIND of
    thing: a process-global knob a session takes and must give back.

    Why the engine wants it, MEASURED 2026-07-29 (Win11, elevated, real
    WinDivert, 64 B UDP flood, no impairment configured). The engine runs two
    threads that hand every packet to each other, and both leave the interpreter
    for a syscall - capture in ``recv``, injector in ``send``. Whoever comes back
    first has to re-acquire the interpreter lock, and with the default 5 ms
    interval it can wait for a slice of that. The syscalls are not slow; the
    waiting is:

        one thread, no contender      recv 15.3 us   send 26.9 us
        the engine, 5 ms   (default)  recv 41.7 us   send 56.7 us
        the engine, 0.5 ms            recv 19.9 us   send 32.0 us

    End to end, measured PAIRED inside one session (the interval flipped
    mid-run, windows alternating, order swapped every pair, so machine drift
    passes through both halves): **median 1.33-1.36x more packets a second, 24
    pairs out of 24**, on loopback AND over a real interface to a WSL guest. The
    release heap stops backing up with it (``peak_queue`` 253 -> 8-62), which is
    the same finding read off a counter instead of a clock.

    It is not bought with CPU - 103.1 -> 92.9 us of process CPU per packet - and
    it does not cost delay accuracy, which is what this tool actually promises:
    against a configured 10 ms, lateness stayed at a median of 0.73 vs 0.76 ms
    and a p95 of 1.71 vs 1.65 ms, with the shorter interval ahead in 3 pairs of 6
    (a coin toss, i.e. no effect either way).

    Every request MUST be matched by a :func:`release_fast_thread_switch`.
    """
    try:
        with _SWITCH_LOCK:
            if _SWITCH_STATE[1] == 0:
                # Saved, not assumed to be the CPython default: a test - or an
                # embedding process - may have set its own, and that is what we
                # owe them back.
                _SWITCH_STATE[0] = sys.getswitchinterval()
                sys.setswitchinterval(interval_s)
            _SWITCH_STATE[1] += 1
        return True
    except Exception as _exc:
        crashlog.note(_exc, "winenv")
        return False


def release_fast_thread_switch():
    """Give back one :func:`request_fast_thread_switch`. Only for a granted one.

    Restores the value that was in force before the FIRST holder asked, and only
    once the last holder has let go. Releasing blindly would let one session's
    stop pull the interval out from under another session that is still running -
    the same unbalance hazard as the fine timer tick, minus the OS refcount to
    catch it.
    """
    try:
        with _SWITCH_LOCK:
            if _SWITCH_STATE[1] <= 0:
                return False
            _SWITCH_STATE[1] -= 1
            if _SWITCH_STATE[1] == 0 and _SWITCH_STATE[0] is not None:
                sys.setswitchinterval(_SWITCH_STATE[0])
                _SWITCH_STATE[0] = None
        return True
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
