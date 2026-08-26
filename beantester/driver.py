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
from .paths import directory_is_writable, executable_dir, is_frozen
from .winenv import is_admin, is_windows

# Set once a session actually opened a REAL WinDivert handle (not --simulate and
# not a test fake): only then is there a driver to unload at exit.
_DRIVER_USED = [False]

# Lazy, Windows-only singletons (see _advapi / _status_type).
_ADVAPI = [None]
_STATUS_TYPE = [None]


def mark_driver_used():
    _DRIVER_USED[0] = True
    _take_use_marker()


def driver_used():
    return _DRIVER_USED[0]


# -- "is anybody else using this driver?" --------------------------------------- #
#
# The WinDivert service is MACHINE-WIDE, and stopping it is not a private act:
# MEASURED 2026-08-04 (Win11, elevated, two processes, filter `false` so nothing is
# ever diverted) - while instance A holds a handle, instance B exiting and running
# the cleanup below leaves the service in "stop pending", and every WinDivertOpen
# on the whole machine then fails with 433 until A closes. The tool was breaking
# its own other window, and telling that window to run as Administrator.
#
# The check is a named kernel object, which is the cheapest thing Windows has that
# answers "does another PROCESS still need this": the object lives exactly as long
# as one handle to it is open, and the kernel closes ours even if we are killed, so
# there is no stale state to clean up. Every instance takes one when it opens a
# real divert; on the way out we drop ours and then look whether the object is
# still there.
#
# What this does NOT cover, stated rather than implied: another PROGRAM that uses
# WinDivert (there are several). Nothing in Windows reports the open handles of a
# device, so that case is handled at the other end - BeanEngine.start() retries a
# 433 briefly, and the message says what happened.
#
# Skipping the cleanup costs nothing when somebody else is using the driver: the
# driver stays loaded because of THEIR handle, so the stop could not have freed the
# .sys file anyway (convention 22). It is only ever effective for the last user.
#
# What the marker MEANS, precisely, because the loose reading would be a bug: "this
# process has opened a real divert and may open another one", NOT "has a handle open
# at this instant". It is taken at the first real open and held until the process
# exits. So an idle instance - one that started a session earlier and stopped it -
# still makes a closing instance stand down, and the driver stays loaded until that
# idle one leaves too. That is deliberate: the alternative is to drop and re-take it
# around every session, which would let a start and somebody else's exit interleave
# in the one way that costs a real 433. The price is a driver left loaded while the
# user still has a window of this tool open, which is exactly when they are not
# trying to delete its folder.
_USE_MARKER = [None]
_USE_MARKER_NAMES = (r"Global\BeanNetworkTester.WinDivertInUse",
                     "BeanNetworkTester.WinDivertInUse")
_SYNCHRONIZE = 0x00100000
_KERNEL32 = [None]


def _kernel32():
    """kernel32 with FULL prototypes - a HANDLE is pointer-sized (see _advapi)."""
    if _KERNEL32[0] is not None:
        return _KERNEL32[0]
    import ctypes
    from ctypes import wintypes

    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    lib.CreateMutexW.restype = wintypes.HANDLE
    lib.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    lib.OpenMutexW.restype = wintypes.HANDLE
    lib.CloseHandle.argtypes = [wintypes.HANDLE]
    lib.CloseHandle.restype = wintypes.BOOL
    _KERNEL32[0] = lib
    return lib


def _take_use_marker():
    """Announce to any other instance that this process is using the driver."""
    if _USE_MARKER[0] is not None or not is_windows():
        return
    with crashlog.quiet("driver.use_marker"):
        api = _kernel32()
        for name in _USE_MARKER_NAMES:
            # The Global namespace is what makes this work across sessions; it
            # needs a privilege an elevated process has, and a real divert needs
            # elevation anyway. The session-local name is the fallback rather than
            # the plan, so two instances in ONE session still find each other if
            # the global name is refused.
            handle = api.CreateMutexW(None, False, name)
            if handle:
                _USE_MARKER[0] = (handle, name)
                return


def _drop_use_marker():
    """Release ours and answer: is ANOTHER process still using the driver?"""
    marker, _USE_MARKER[0] = _USE_MARKER[0], None
    if not is_windows():
        return False
    with crashlog.quiet("driver.use_marker"):
        api = _kernel32()
        if marker is not None:
            api.CloseHandle(marker[0])
        name = marker[1] if marker is not None else _USE_MARKER_NAMES[0]
        # Ours is closed, so anything left belongs to somebody else.
        other = api.OpenMutexW(_SYNCHRONIZE, False, name)
        if other:
            api.CloseHandle(other)
            return True
    return False

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
# MEASURED 2026-08-04: this is what DeleteService returns on a perfectly healthy,
# single-instance exit - WinDivert marks its OWN service for deletion when it
# installs it, so the service disappears by itself once the last handle to it
# closes. Our delete is therefore never the thing that removes it, and reporting
# 1072 as "removal failed - it may be in use" described a success as a failure in
# the log line the user reads on every close.
_ERROR_SERVICE_MARKED_FOR_DELETE = 1072

# What a start gets while somebody else's cleanup is still unloading the driver.
# Named here because two modules test for it: the hint table below and the
# retry in BeanEngine.start().
ERROR_NO_SUCH_DEVICE = 433

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
            if bool(api.DeleteService(handle)):
                return f"{name}: stopped and removed"
            # WHY the delete failed decides whether anything is wrong at all, and
            # this used to be thrown away. MEASURED (see the constant): 1072 on
            # every ordinary exit, because WinDivert already scheduled the removal
            # itself - the service does vanish, and the STOP above is the part that
            # actually unloads the driver and frees its .sys file.
            err = ctypes.get_last_error()
            if err == _ERROR_SERVICE_MARKED_FOR_DELETE:
                return f"{name}: stopped (removal was already scheduled)"
            return f"{name}: stopped (removal failed, Windows error {err})"
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


def _another_instance_holds_the_driver():
    """Read-only: does a handle to the use marker exist?

    Accurate only while WE hold none - which is exactly the case in the caller that
    asks (``--cleanup-driver`` is a one-shot command that never opens a divert).
    ``release_on_exit`` asks the same question the other way round: it drops its own
    marker first, so whatever is left belongs to somebody else.
    """
    if not is_windows() or _USE_MARKER[0] is not None:
        return False
    with crashlog.quiet("driver.use_marker"):
        api = _kernel32()
        other = api.OpenMutexW(_SYNCHRONIZE, False, _USE_MARKER_NAMES[0])
        if other:
            api.CloseHandle(other)
            return True
    return False


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
    if _another_instance_holds_the_driver():
        # Said, not obeyed: this function is also `--cleanup-driver`, which is a
        # rescue command someone typed on purpose. But they deserve to know that
        # the session they are about to stop belongs to a running instance, and
        # that its next start will fail with 433 until this settles.
        lines.append("WARNING: another instance of this tool is using the WinDivert "
                     "driver right now. Unloading it will interrupt that session.")
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

    **Never at the expense of another instance.** The service is machine-wide, so
    this used to reach across and stop the driver under a session that was still
    running - see the marker block above for the measurement. Nothing is lost by
    standing down: their handle keeps the driver loaded, so the stop could not have
    freed anything, and whoever leaves last does the unloading.
    """
    if not _DRIVER_USED[0] or not is_windows():
        return []
    _DRIVER_USED[0] = False
    with crashlog.quiet("driver.release_on_exit"):
        # Always drop ours FIRST, whatever we decide next: the answer is about the
        # others, and a marker left behind would make the next instance stand down
        # for a process that has already gone.
        if _drop_use_marker():
            lines = ["Another instance is still using the WinDivert driver - "
                     "leaving it loaded for them."]
            for line in lines:
                log(line)
            return lines
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


# -- why a start failed --------------------------------------------------------- #
#
# ``WinDivertOpen`` reports its failures as Win32 error codes, and this tool used
# to answer every one of them with "Run as Administrator" - the advice for exactly
# ONE of them. What that costs is not theoretical: MEASURED 2026-08-04 on Windows
# 11, elevated, two processes and the filter ``false`` (which matches no packet at
# all), a session holding a handle open while a second instance exits and runs
# ``release_on_exit`` leaves the service in "stop pending", and every open after
# that fails with **433** until the first handle closes. The user was elevated,
# nothing about their rights was wrong, and the window told them to run as
# Administrator.
#
# The mapping lives here rather than in the window because the CLI reports the same
# failure and must not grow a second copy of these sentences. It yields i18n KEYS,
# never text: this module translates nothing (convention: only keys in code).
OPEN_ERROR_HINTS = {
    2: "dialogs.driver_missing",       # ERROR_FILE_NOT_FOUND - WinDivert*.sys gone
    5: "dialogs.run_as_admin",         # ERROR_ACCESS_DENIED - the ONE rights problem
    87: "dialogs.filter_refused",      # ERROR_INVALID_PARAMETER - the filter expression
    433: "dialogs.driver_busy",        # ERROR_NO_SUCH_DEVICE - measured above
    577: "dialogs.driver_signature",   # ERROR_INVALID_IMAGE_HASH
    1275: "dialogs.driver_blocked",    # ERROR_DRIVER_BLOCKED - security software, VMs
}


def open_failure_hint(exc, elevated=None):
    """The i18n key of the advice that fits THIS failure (``""`` when none does).

    ``elevated`` is injected so the caller can pass what it already knows (the GUI
    decides its "run as Administrator" banner from the same answer) and so a test
    can state both worlds without touching the machine it runs on.
    """
    key = OPEN_ERROR_HINTS.get(getattr(exc, "winerror", None))
    if key is not None:
        return key
    # An error we do not recognise. Elevation is a fair guess when the process is
    # NOT elevated - and a falsehood when it is, which is the whole point here.
    if elevated is None:
        elevated = is_admin()
    return "" if elevated else "dialogs.run_as_admin"


def _program_folder_check():
    """Could something running as this user replace the files we load when elevated?

    This program asks for administrator rights and THEN loads ``WinDivert.dll`` from
    its own folder. If that folder can be written without administrator rights, then
    anything running as the user - no elevation needed - can leave its own DLL there
    and have the elevated copy load it. That turns "code as you" into "code as
    Administrator", and the UAC prompt shows a signed, trusted executable while it
    happens.

    It is not a defect of this program: it is what a user-scope install IS. But this
    program is the one that does the elevating, so it is the one that should say so.
    MEASURED 2026-08-26 on a real machine, because the first version of the audit
    assumed the opposite: WinGet's default for this package (``InstallerType: zip``
    with ``NestedInstallerType: portable``) is a USER-scope install under
    ``%LOCALAPPDATA%\\Microsoft\\WinGet\\Packages``, where the user has full control -
    and so does an archive unpacked anywhere in the profile. ``--scope machine`` and
    Chocolatey's package folder do not.

    Reported as a WARN rather than a FAIL: it does not stop a session from starting,
    and on most machines the user cannot change it without reinstalling. "Not
    checked" is a warn too - an unanswered question must not print as a clean bill of
    health, which is the rule the WinDivert row above already lives by.
    """
    folder = executable_dir()
    if is_admin():
        return ("program folder", "warn",
                f"{folder} - not checked: this run is already elevated, so a "
                f"successful write says nothing about an ordinary user. Run "
                f"--doctor WITHOUT administrator rights to check it")
    writable = directory_is_writable(folder)
    if writable is None:
        return ("program folder", "warn", f"{folder} - could not be checked")
    if writable:
        return ("program folder", "warn",
                f"{folder} - writable without administrator rights: anything running "
                f"as you can replace the files this program loads when it elevates. "
                f"Installing with 'winget install --scope machine' avoids this")
    return ("program folder", "ok",
            f"{folder} - not writable without administrator rights")


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
        # Only for a frozen build: from sources the "program folder" is a source
        # checkout the developer owns by definition, and the driver comes out of
        # site-packages rather than from next to the exe. A row that is trivially
        # true tells nobody anything and trains people to skip the report.
        if is_frozen():
            checks.append(_program_folder_check())
        drivers = installed_drivers()
        if drivers:
            running = [n for n, s in drivers.items() if s == "running"]
            blocked = [n for n, s in drivers.items() if s == NO_ACCESS]
            # The state a start CANNOT survive, and the one this report used to
            # call "ok": while the service is stopping, every WinDivertOpen on this
            # machine fails with 433 (measured 2026-08-04). A doctor that says the
            # machine is healthy while nothing can start is worse than no doctor.
            stopping = [n for n, s in drivers.items() if s == "stop pending"]
            detail = ", ".join(f"{n}={s}" for n, s in drivers.items())
            if blocked:
                # "I could not look" must never be printed as a clean bill of health
                detail += (" - the service manager would not report the state; "
                           "re-run as Administrator to be sure")
            elif stopping:
                detail += (" - the driver is still unloading, so a session cannot "
                           "start yet (WinDivertOpen fails with 433). It finishes "
                           "when the last program using it closes its handle")
            elif running:
                detail += (" - a session may still be active elsewhere; "
                           "use --cleanup-driver if not")
            checks.append(("windivert driver",
                           "warn" if (running or blocked or stopping) else "ok",
                           detail))
        else:
            checks.append(("windivert driver", "ok", "not loaded"))
        leftovers = stale_temp_dirs()
        checks.append(("temp leftovers", "warn" if leftovers else "ok",
                       ", ".join(leftovers) if leftovers else "none"))
        # Deliberately NOT read here. The values live behind an open WinDivert
        # handle, and opening one loads the driver - which would falsify the
        # "windivert driver" line printed two checks above, in the same report. A
        # session reads them at START and puts them in its log and its repro
        # report, where they cost nothing extra.
        checks.append(("driver queue", "ok",
                       "read at session start (log line + repro report "
                       "'session.driver_queue'); needs an open handle, so --doctor "
                       "does not load the driver just to look"))
    else:
        checks.append(("pydivert", "warn" if not pydivert_available() else "ok",
                       "not required outside Windows (--simulate works)"))

    ok = all(state != "fail" for _, state, _ in checks)
    return ok, checks
