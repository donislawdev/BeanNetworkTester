"""WinDivert driver lifecycle and environment diagnostics.

The bug this module exists for
------------------------------
``pydivert`` ships ``WinDivert.dll`` + ``WinDivert64.sys`` inside its package.
When the tool was frozen with PyInstaller **--onefile**, the package was
unpacked into ``%TEMP%\\_MEIxxxxx`` at every start and the *kernel* loaded the
driver from there. As long as the WinDivert service stays loaded, the kernel
holds an open handle to that ``.sys`` file: the temp directory cannot be
removed - not by the exiting process, not by the user, not until a reboot.
That is exactly the "I closed the app and the WinDivert file in tmp was locked"
report.

The fix has three parts:
  1. the build is now **onedir** (see ``BeanNetworkTester.spec``): the driver
     lives next to the exe, at a stable path, and is never copied into %TEMP%,
  2. the engine closes the WinDivert handle deterministically (fail-safe stop),
  3. this module can stop/remove a *leftover* driver service and report stale
     temp directories - exposed as ``--cleanup-driver`` and ``--doctor``.

The cleanup is deliberately NOT run on every stop: unloading and reloading the
driver costs ~0.5-1 s per session (a user decision - a session restart must
stay instant). It IS run once when the process exits (``release_on_exit``),
because of this report:

    "I deleted everything inside dist\\BeanNetworkTester and Windows still said
     the folder was in use - and it was EMPTY."

That is the driver, even though the ``.sys`` file is no longer listed. Windows
lets a file be deleted while a handle is open (share-delete): the file vanishes
from the directory listing but stays in a *pending delete* state, and the
directory that holds it cannot be removed until the last handle - here, the
KERNEL's handle on the loaded WinDivert driver - is closed. Unloading the driver
service when the app closes releases it, and the folder can be deleted normally.
"""
import glob
import os
import tempfile

from . import crashlog
from .winenv import is_admin, is_windows

# Set once a session actually opened a REAL WinDivert handle (not --simulate and
# not a test fake): only then is there a driver to unload at exit.
_DRIVER_USED = [False]


def mark_driver_used():
    _DRIVER_USED[0] = True


def driver_used():
    return _DRIVER_USED[0]

# WinDivert registers itself under a version-dependent service name; pydivert
# has shipped 1.1 / 1.4 / 2.x over time, so every known name is checked.
DRIVER_SERVICES = ("WinDivert", "WinDivert1.4", "WinDivert1.1")

# Service control constants (winsvc.h)
_SC_MANAGER_ALL_ACCESS = 0xF003F
_SERVICE_ALL_ACCESS = 0xF01FF
_SERVICE_CONTROL_STOP = 0x1
_SERVICE_STOPPED = 0x1
_ERROR_SERVICE_DOES_NOT_EXIST = 1060

STATE_LABELS = {1: "stopped", 2: "start pending", 3: "stop pending",
                4: "running", 5: "continue pending", 6: "pause pending",
                7: "paused"}


def _advapi():
    """advapi32 with FULL prototypes.

    Without this, calling these functions on 64-bit Windows crashes the whole
    interpreter with an access violation. ctypes defaults every argument and the
    return value to C ``int`` (32-bit); a service-control HANDLE is a 64-bit
    pointer, so it is silently truncated, and ``QueryServiceStatus`` then writes
    through a garbage handle. The symptom is exactly the CI failure:

        Windows fatal exception: access violation
          ... driver.py service_state -> installed_drivers -> cleanup_driver
          -> release_on_exit

    Declaring argtypes/restype makes ctypes pass real 64-bit handles and marshal
    the return values correctly. This is not optional on Win64; it is the contract.
    """
    import ctypes
    from ctypes import wintypes

    lib = ctypes.windll.advapi32
    # A handle is pointer-sized. wintypes.HANDLE is the right width on 32- and 64-bit.
    H = wintypes.HANDLE
    lib.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    lib.OpenSCManagerW.restype = H
    lib.OpenServiceW.argtypes = [H, wintypes.LPCWSTR, wintypes.DWORD]
    lib.OpenServiceW.restype = H
    lib.QueryServiceStatus.argtypes = [H, ctypes.c_void_p]
    lib.QueryServiceStatus.restype = wintypes.BOOL
    lib.ControlService.argtypes = [H, wintypes.DWORD, ctypes.c_void_p]
    lib.ControlService.restype = wintypes.BOOL
    lib.DeleteService.argtypes = [H]
    lib.DeleteService.restype = wintypes.BOOL
    lib.CloseServiceHandle.argtypes = [H]
    lib.CloseServiceHandle.restype = wintypes.BOOL
    return lib


def service_state(name):
    """Return ``'running'`` / ``'stopped'`` / ... , or ``None`` if not installed."""
    if not is_windows():
        return None
    import ctypes
    from ctypes import wintypes

    class _STATUS(ctypes.Structure):
        _fields_ = [("dwServiceType", wintypes.DWORD),
                    ("dwCurrentState", wintypes.DWORD),
                    ("dwControlsAccepted", wintypes.DWORD),
                    ("dwWin32ExitCode", wintypes.DWORD),
                    ("dwServiceSpecificExitCode", wintypes.DWORD),
                    ("dwCheckPoint", wintypes.DWORD),
                    ("dwWaitHint", wintypes.DWORD)]

    api = _advapi()
    manager = api.OpenSCManagerW(None, None, _SC_MANAGER_ALL_ACCESS)
    if not manager:
        return None
    try:
        handle = api.OpenServiceW(manager, name, _SERVICE_ALL_ACCESS)
        if not handle:
            return None
        try:
            status = _STATUS()
            if not api.QueryServiceStatus(handle, ctypes.byref(status)):
                return None
            return STATE_LABELS.get(int(status.dwCurrentState), "unknown")
        finally:
            api.CloseServiceHandle(handle)
    finally:
        api.CloseServiceHandle(manager)


def installed_drivers():
    """``{service name: state}`` for every WinDivert service present."""
    found = {}
    for name in DRIVER_SERVICES:
        state = service_state(name)
        if state is not None:
            found[name] = state
    return found


def stop_and_remove(name):
    """Stop and delete one driver service. Returns a human-readable result."""
    if not is_windows():
        return f"{name}: not Windows, nothing to do"
    import ctypes
    from ctypes import wintypes

    class _STATUS(ctypes.Structure):
        _fields_ = [("dwServiceType", wintypes.DWORD),
                    ("dwCurrentState", wintypes.DWORD),
                    ("dwControlsAccepted", wintypes.DWORD),
                    ("dwWin32ExitCode", wintypes.DWORD),
                    ("dwServiceSpecificExitCode", wintypes.DWORD),
                    ("dwCheckPoint", wintypes.DWORD),
                    ("dwWaitHint", wintypes.DWORD)]

    api = _advapi()
    manager = api.OpenSCManagerW(None, None, _SC_MANAGER_ALL_ACCESS)
    if not manager:
        return f"{name}: cannot open the service manager (Administrator required)"
    try:
        handle = api.OpenServiceW(manager, name, _SERVICE_ALL_ACCESS)
        if not handle:
            err = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
            if err == _ERROR_SERVICE_DOES_NOT_EXIST:
                return f"{name}: not installed"
            return f"{name}: not installed"
        try:
            status = _STATUS()
            api.ControlService(handle, _SERVICE_CONTROL_STOP, ctypes.byref(status))
            deleted = bool(api.DeleteService(handle))
            return (f"{name}: stopped and removed" if deleted
                    else f"{name}: stopped (removal failed - it may be in use)")
        finally:
            api.CloseServiceHandle(handle)
    finally:
        api.CloseServiceHandle(manager)


def stale_temp_dirs():
    """PyInstaller onefile leftovers (``%TEMP%\\_MEI*``) - the locked-file symptom.

    Only reported, never deleted: a directory may belong to a running instance.
    """
    pattern = os.path.join(tempfile.gettempdir(), "_MEI*")
    return sorted(p for p in glob.glob(pattern) if os.path.isdir(p))


def cleanup_driver():
    """Stop and remove every leftover WinDivert service. Returns report lines."""
    lines = []
    if not is_windows():
        return ["Not Windows - there is no WinDivert driver to clean up."]
    if not is_admin():
        return ["Administrator rights are required to unload the WinDivert driver."]
    drivers = installed_drivers()
    if not drivers:
        return ["No WinDivert driver service is installed - nothing to clean up."]
    for name in drivers:
        lines.append(stop_and_remove(name))
    leftovers = stale_temp_dirs()
    if leftovers:
        lines.append("Stale PyInstaller temp directories (safe to delete once no "
                     "instance is running): " + ", ".join(leftovers))
    return lines


def release_on_exit(log=lambda *_: None):
    """Unload the WinDivert driver on the way out (only if this run loaded it).

    Cheap where it does not matter (a ``--simulate`` run never loaded a driver,
    so this is a no-op) and worth ~0.5-1 s where it does: the alternative is a
    folder the user cannot delete until the next reboot.
    """
    if not _DRIVER_USED[0] or not is_windows():
        return []
    _DRIVER_USED[0] = False
    with crashlog.quiet("driver.release_on_exit"):
        lines = cleanup_driver()
        for line in lines:
            log(line)
        return lines
    return []


def pydivert_available():
    try:
        import pydivert  # noqa: F401
        return True
    except Exception:
        return False


def doctor():
    """Environment report used by ``--doctor``: ``(ok, [(check, state, detail)])``."""
    import platform
    import sys

    checks = [("python", "ok", platform.python_version()),
              ("platform", "ok" if is_windows() else "warn",
               f"{platform.system()} {platform.release()}"
               + ("" if is_windows() else " - capture needs Windows; use --simulate")),
              ("frozen", "ok", "yes" if getattr(sys, "frozen", False) else "no")]

    if is_windows():
        checks.append(("administrator", "ok" if is_admin() else "fail",
                       "elevated" if is_admin()
                       else "not elevated - a capture session cannot start"))
        checks.append(("pydivert", "ok" if pydivert_available() else "fail",
                       "importable" if pydivert_available()
                       else "missing - pip install pydivert"))
        drivers = installed_drivers()
        if drivers:
            running = [n for n, s in drivers.items() if s == "running"]
            checks.append(("windivert driver",
                           "warn" if running else "ok",
                           ", ".join(f"{n}={s}" for n, s in drivers.items())
                           + (" - a session may still be active elsewhere; "
                              "use --cleanup-driver if not" if running else "")))
        else:
            checks.append(("windivert driver", "ok", "not loaded"))
        leftovers = stale_temp_dirs()
        checks.append(("temp leftovers", "warn" if leftovers else "ok",
                       ", ".join(leftovers) if leftovers else "none"))
    else:
        checks.append(("pydivert", "warn" if not pydivert_available() else "ok",
                       "not required outside Windows (--simulate works)"))

    ok = all(state != "fail" for _, state, _ in checks)
    return ok, checks
