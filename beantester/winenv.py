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
