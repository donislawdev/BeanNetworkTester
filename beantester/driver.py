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

# Lazy, Windows-only singletons (see _advapi / _status_type).
_ADVAPI = [None]
_STATUS_TYPE = [None]


def mark_driver_used():
    _DRIVER_USED[0] = True


def driver_used():
    return _DRIVER_USED[0]

# WinDivert registers itself under a version-dependent service name; pydivert
# has shipped 1.1 / 1.4 / 2.x over time, so every known name is checked.
DRIVER_SERVICES = ("WinDivert", "WinDivert1.4", "WinDivert1.1")

# Service control constants (winsvc.h)
#
# READING a service state must ask for the RIGHTS TO READ, nothing more. This is
# not hygiene, it is correctness: a service whose security descriptor does not
# grant full control reads back as "not installed" if you open it with
# SERVICE_ALL_ACCESS. Measured on Windows 11, from an ELEVATED shell:
#
#     OpenServiceW(Schedule, SERVICE_ALL_ACCESS)    -> NULL, error 5 (access denied)
#     OpenServiceW(Schedule, SERVICE_QUERY_STATUS)  -> handle, state = running
#
# Same for Dnscache; EventLog happens to grant both. So the old mask turned "this
# service is protected" into "this service does not exist" - in the one command
# (--doctor) whose entire job is to tell the user the truth about their machine.
# The ALL_ACCESS pair below is still used by the CLEANUP path, which genuinely
# needs to stop and delete (and is gated on is_admin()).
_SC_MANAGER_ALL_ACCESS = 0xF003F
_SC_MANAGER_CONNECT = 0x0001
_SERVICE_ALL_ACCESS = 0xF01FF
_SERVICE_QUERY_STATUS = 0x0004
_SERVICE_CONTROL_STOP = 0x1
_SERVICE_STOPPED = 0x1
_ERROR_ACCESS_DENIED = 5
_ERROR_SERVICE_DOES_NOT_EXIST = 1060

STATE_LABELS = {1: "stopped", 2: "start pending", 3: "stop pending",
                4: "running", 5: "continue pending", 6: "pause pending",
                7: "paused"}

# Third answer, distinct from a state and from None: the service manager refused
# to let us look. "I cannot tell" and "it is not there" lead the user to opposite
# conclusions, so they must not share a return value.
NO_ACCESS = "no access"


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

    Loaded with ``use_last_error=True`` so ``ctypes.get_last_error()`` actually
    reports the Win32 error. Without it the call site read a thread-local that
    ctypes never populated, so it always saw 0 and could not tell "not installed"
    (1060) from "access denied" (5) - both branches returned the same string.

    Cached: ``installed_drivers()`` asks about three service names, and each call
    used to rebuild the binding and re-assign six sets of prototypes.
    """
    if _ADVAPI[0] is not None:
        return _ADVAPI[0]
    import ctypes
    from ctypes import wintypes

    lib = ctypes.WinDLL("advapi32", use_last_error=True)
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
    _ADVAPI[0] = lib
    return lib


def _status_type():
    """SERVICE_STATUS, built once. Windows-only: ``ctypes.wintypes`` does not even
    import on Linux, so this cannot live at module level (CI runs on ubuntu too)."""
    if _STATUS_TYPE[0] is not None:
        return _STATUS_TYPE[0]
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

    _STATUS_TYPE[0] = _STATUS
    return _STATUS


def service_state(name):
    """State of one service, asking only for the right to READ it.

    Returns a label from ``STATE_LABELS``, ``None`` when the service is genuinely
    not installed, or ``NO_ACCESS`` when the service manager refused to tell us.
    That third answer matters: reporting "not installed" for a service we were not
    allowed to open sends the user looking in the wrong place - see the note on the
    access masks above, where SERVICE_ALL_ACCESS is denied on real Windows services
    even to an Administrator.
    """
    if not is_windows():
        return None
    import ctypes

    api = _advapi()
    manager = api.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
    if not manager:
        # SC_MANAGER_CONNECT is granted to Authenticated Users, so this failing at
        # all means something unusual - not an absent service.
        return NO_ACCESS
    try:
        handle = api.OpenServiceW(manager, name, _SERVICE_QUERY_STATUS)
        if not handle:
            err = ctypes.get_last_error()
            return None if err == _ERROR_SERVICE_DOES_NOT_EXIST else NO_ACCESS
        try:
            status = _status_type()()
            if not api.QueryServiceStatus(handle, ctypes.byref(status)):
                return NO_ACCESS
            return STATE_LABELS.get(int(status.dwCurrentState), "unknown")
        finally:
            api.CloseServiceHandle(handle)
    finally:
        api.CloseServiceHandle(manager)


def installed_drivers():
    """``{service name: state}`` for every WinDivert service present.

    A service we were not allowed to read is present with the state ``NO_ACCESS``
    rather than being dropped: absent from this dict means "not installed", and
    that claim has to stay trustworthy.
    """
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

    api = _advapi()
    manager = api.OpenSCManagerW(None, None, _SC_MANAGER_ALL_ACCESS)
    if not manager:
        return f"{name}: cannot open the service manager (Administrator required)"
    try:
        # ALL_ACCESS on purpose here: this path stops and DELETES. Narrowing it to
        # SERVICE_STOP|DELETE|QUERY_STATUS was measured and does NOT help - a
        # hardened service denies DELETE itself, so the honest thing left to do is
        # report WHY rather than pretend the service was never there.
        handle = api.OpenServiceW(manager, name, _SERVICE_ALL_ACCESS)
        if not handle:
            err = ctypes.get_last_error()
            if err == _ERROR_ACCESS_DENIED:
                return (f"{name}: access denied - the service exists but this "
                        f"account may not stop or remove it")
            if err != _ERROR_SERVICE_DOES_NOT_EXIST:
                return f"{name}: cannot open the service (Windows error {err})"
            return f"{name}: not installed"
        try:
            status = _status_type()()
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
            blocked = [n for n, s in drivers.items() if s == NO_ACCESS]
            detail = ", ".join(f"{n}={s}" for n, s in drivers.items())
            if blocked:
                # "I could not look" must never be printed as a clean bill of health
                detail += (" - the service manager would not report the state; "
                           "re-run as Administrator to be sure")
            elif running:
                detail += (" - a session may still be active elsewhere; "
                           "use --cleanup-driver if not")
            checks.append(("windivert driver",
                           "warn" if (running or blocked) else "ok", detail))
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
