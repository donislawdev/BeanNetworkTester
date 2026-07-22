"""Windows driver-lifecycle safety, verified without a real Service Manager.

The bug this guards against was a hard interpreter crash on the Windows CI:

    Windows fatal exception: access violation
      driver.service_state -> installed_drivers -> cleanup_driver -> release_on_exit

Its cause was ctypes calling advapi32 with default (32-bit int) prototypes on
64-bit Windows, which truncated the pointer-sized service-control HANDLEs and made
QueryServiceStatus write through a garbage pointer. The fix is to declare full
argtypes/restype on every advapi32 function used. These tests check the two
properties that keep it fixed and keep it safe off Windows.
"""
import ctypes

from beantester import driver
from fakes import check


def test_advapi_declares_pointer_sized_prototypes():
    """Every advapi32 function used must declare argtypes/restype.

    Without this the calls crash the interpreter on Win64. We build the prototypes
    on any platform (ctypes.windll is Windows-only, so we only assert the intent
    on Windows and assert the code path is reachable/guarded elsewhere).
    """
    if not hasattr(ctypes, "windll"):
        # Not Windows: the whole native path is guarded by is_windows() and never
        # runs. Assert that guard is really there, which is the off-Windows safety.
        check("service_state is a no-op off Windows", driver.service_state("x") is None)
        check("cleanup is a no-op off Windows",
              driver.cleanup_driver() == [
                  "Not Windows - there is no WinDivert driver to clean up."])
        return

    lib = driver._advapi()                      # pragma: no cover - Windows only
    handle = ctypes.wintypes.HANDLE
    for name in ("OpenSCManagerW", "OpenServiceW", "QueryServiceStatus",
                 "ControlService", "DeleteService", "CloseServiceHandle"):
        fn = getattr(lib, name)
        check(f"{name} declares argtypes", fn.argtypes is not None)
        check(f"{name} declares a restype", fn.restype is not None)
    check("handle-returning calls return a pointer-sized HANDLE",
          lib.OpenSCManagerW.restype is handle)


def test_reading_a_service_state_asks_only_for_the_right_to_read():
    """The regression guard for the access-mask bug.

    ``SERVICE_ALL_ACCESS`` is denied on hardened Windows services even to an
    Administrator, so opening a service with it and treating the failure as
    "not installed" turned a protected service into a missing one. Measured on
    Windows 11 from an elevated shell: ``Schedule`` and ``Dnscache`` both returned
    error 5 with ALL_ACCESS and their real state with ``SERVICE_QUERY_STATUS``.

    Go back to the wide mask and this goes red on the Windows runner.
    """
    if not hasattr(ctypes, "windll"):
        check("service_state is a no-op off Windows", driver.service_state("x") is None)
        return

    probes = ("Schedule", "Dnscache", "EventLog")     # core services, always present
    states = {name: driver.service_state(name) for name in probes}
    readable = [n for n, s in states.items()
                if s is not None and s != driver.NO_ACCESS]
    check("a real Windows service reports its state instead of reading as absent",
          readable, f"({states})")
    check("a service that truly does not exist is still None",
          driver.service_state("BeanNetworkTesterNoSuchService") is None)


def test_advapi_and_status_type_are_built_once():
    """``installed_drivers()`` asks about three names; rebuilding the binding and
    re-assigning six sets of prototypes each time is pure waste."""
    if not hasattr(ctypes, "windll"):
        return
    check("the advapi32 binding is cached", driver._advapi() is driver._advapi())
    check("the SERVICE_STATUS type is cached",
          driver._status_type() is driver._status_type())


def test_doctor_says_it_could_not_look_rather_than_not_loaded(monkeypatch):
    """"I was not allowed to check" must never print as a clean bill of health."""
    monkeypatch.setattr(driver, "is_windows", lambda: True)
    monkeypatch.setattr(driver, "installed_drivers",
                        lambda: {"WinDivert": driver.NO_ACCESS})
    _, checks = driver.doctor()
    row = next(c for c in checks if c[0] == "windivert driver")
    check("doctor: an unreadable service is a warning", row[1] == "warn", f"({row})")
    check("doctor: it says the state could not be read",
          "would not report" in row[2], f"({row})")


def test_doctor_still_calls_a_clean_machine_not_loaded(monkeypatch):
    """The other direction: no driver must not start warning people for nothing."""
    monkeypatch.setattr(driver, "is_windows", lambda: True)
    monkeypatch.setattr(driver, "installed_drivers", lambda: {})
    _, checks = driver.doctor()
    row = next(c for c in checks if c[0] == "windivert driver")
    check("doctor: nothing installed stays a clean 'ok'",
          row[1] == "ok" and "not loaded" in row[2], f"({row})")


def test_release_on_exit_never_raises_and_is_a_noop_without_a_driver():
    """release_on_exit must be crash-proof: it runs on the way out of every CLI
    run, and a fault there (the access violation) would take the process down
    AFTER a successful session. With no driver marked used, it does nothing.
    """
    driver._DRIVER_USED[0] = False
    result = driver.release_on_exit(log=lambda *_: None)
    check("release_on_exit is a no-op when no driver was used", result == [])


def test_release_on_exit_swallows_a_cleanup_fault(monkeypatch):
    """Even if cleanup blows up, exit must not crash (crashlog.quiet catches it)."""
    driver._DRIVER_USED[0] = True
    monkeypatch.setattr(driver, "is_windows", lambda: True)

    def boom():
        raise RuntimeError("SCM exploded")

    monkeypatch.setattr(driver, "cleanup_driver", boom)
    # Must return without raising; the fault is recorded, not propagated.
    result = driver.release_on_exit(log=lambda *_: None)
    check("a cleanup fault does not crash the exit path", result == [])
    check("the driver-used flag is cleared even on fault",
          driver._DRIVER_USED[0] is False)


# --- stop_and_remove: the STOP + DELETE path, driven through a fake advapi ---- #
#
# stop_and_remove runs on the way out of every real-capture session
# (release_on_exit) and it STOPS and DELETES a Windows service, so it must never be
# exercised for the first time on a user's machine. It is pure Service-Manager glue,
# so a fake advapi covers every branch here - no admin, no real driver, and
# identically on the Linux CI (is_windows is forced True). The one thing the fake
# cannot stand in for - the 64-bit HANDLE prototypes - is what
# test_advapi_declares_pointer_sized_prototypes pins on the real thing.


class _FakeStatus(ctypes.Structure):
    # A real ctypes.Structure (not wintypes, so it also builds on Linux) so that
    # ``ctypes.byref(status)`` inside stop_and_remove has something valid to point at.
    _fields_ = [("dwCurrentState", ctypes.c_uint)]


class _FakeAdvapi:
    """Records the Service-Manager calls stop_and_remove makes, and returns whatever
    handles / results the test asked for. A 0 handle means the OS refused."""

    def __init__(self, scm=1, service=1, deleted=True):
        self.scm = scm
        self.service = service
        self.deleted = deleted
        self.calls = []

    def OpenSCManagerW(self, machine, database, access):
        self.calls.append(("OpenSCManagerW", access))
        return self.scm

    def OpenServiceW(self, manager, name, access):
        self.calls.append(("OpenServiceW", name, access))
        return self.service

    def QueryServiceStatus(self, handle, buf):
        return True

    def ControlService(self, handle, control, buf):
        self.calls.append(("ControlService", control))
        return True

    def DeleteService(self, handle):
        self.calls.append(("DeleteService",))
        return self.deleted

    def CloseServiceHandle(self, handle):
        self.calls.append(("CloseServiceHandle",))
        return True


def _fake_scm(monkeypatch, fake, last_error=0):
    monkeypatch.setattr(driver, "is_windows", lambda: True)
    monkeypatch.setattr(driver, "_advapi", lambda: fake)
    monkeypatch.setattr(driver, "_status_type", lambda: _FakeStatus)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: last_error)


def test_stop_and_remove_stops_then_deletes_and_closes_every_handle(monkeypatch):
    fake = _FakeAdvapi(scm=1, service=42, deleted=True)
    _fake_scm(monkeypatch, fake)
    result = driver.stop_and_remove("WinDivert")
    check("a service that stops and deletes reports both",
          result == "WinDivert: stopped and removed", f"({result})")
    ops = [c[0] for c in fake.calls]
    check("it issues a STOP before the DELETE",
          "ControlService" in ops and "DeleteService" in ops
          and ops.index("ControlService") < ops.index("DeleteService"), f"({ops})")
    check("both the service and the manager handle are closed",
          ops.count("CloseServiceHandle") == 2, f"({ops})")


def test_stop_and_remove_reports_a_removal_that_would_not_take(monkeypatch):
    fake = _FakeAdvapi(scm=1, service=42, deleted=False)
    _fake_scm(monkeypatch, fake)
    result = driver.stop_and_remove("WinDivert")
    check("a service that stops but will not delete says so",
          "stopped (removal failed" in result, f"({result})")


def test_stop_and_remove_without_a_manager_asks_for_administrator(monkeypatch):
    fake = _FakeAdvapi(scm=0)
    _fake_scm(monkeypatch, fake)
    result = driver.stop_and_remove("WinDivert")
    check("no Service-Manager handle points at the admin requirement",
          "Administrator required" in result, f"({result})")


def test_stop_and_remove_explains_access_denied(monkeypatch):
    fake = _FakeAdvapi(scm=1, service=0)
    _fake_scm(monkeypatch, fake, last_error=driver._ERROR_ACCESS_DENIED)
    result = driver.stop_and_remove("WinDivert")
    check("access denied is explained, not disguised as 'not installed'",
          "access denied" in result, f"({result})")


def test_stop_and_remove_reads_a_missing_service_as_not_installed(monkeypatch):
    fake = _FakeAdvapi(scm=1, service=0)
    _fake_scm(monkeypatch, fake, last_error=driver._ERROR_SERVICE_DOES_NOT_EXIST)
    result = driver.stop_and_remove("WinDivert")
    check("a genuinely absent service reads as not installed",
          result == "WinDivert: not installed", f"({result})")


def test_stop_and_remove_surfaces_an_unexpected_open_error(monkeypatch):
    fake = _FakeAdvapi(scm=1, service=0)
    _fake_scm(monkeypatch, fake, last_error=1234)
    result = driver.stop_and_remove("WinDivert")
    check("an unexpected Windows error is surfaced with its code",
          "Windows error 1234" in result, f"({result})")


def test_stop_and_remove_is_a_noop_off_windows(monkeypatch):
    monkeypatch.setattr(driver, "is_windows", lambda: False)
    result = driver.stop_and_remove("WinDivert")
    check("off Windows there is nothing to remove",
          result == "WinDivert: not Windows, nothing to do", f"({result})")


# --- cleanup_driver: the --cleanup-driver / release_on_exit orchestration ----- #
def test_cleanup_driver_stops_every_installed_service(monkeypatch):
    monkeypatch.setattr(driver, "is_windows", lambda: True)
    monkeypatch.setattr(driver, "is_admin", lambda: True)
    monkeypatch.setattr(driver, "installed_drivers",
                        lambda: {"WinDivert": "running", "WinDivert1.4": "stopped"})
    visited = []
    monkeypatch.setattr(driver, "stop_and_remove",
                        lambda name: (visited.append(name),
                                      f"{name}: stopped and removed")[1])
    monkeypatch.setattr(driver, "stale_temp_dirs", lambda: [])
    lines = driver.cleanup_driver()
    check("cleanup visits every installed service",
          visited == ["WinDivert", "WinDivert1.4"], f"({visited})")
    check("cleanup reports a line per service",
          [l for l in lines if "stopped and removed" in l] == lines, f"({lines})")


def test_cleanup_driver_surfaces_stale_temp_directories(monkeypatch):
    monkeypatch.setattr(driver, "is_windows", lambda: True)
    monkeypatch.setattr(driver, "is_admin", lambda: True)
    monkeypatch.setattr(driver, "installed_drivers", lambda: {"WinDivert": "running"})
    monkeypatch.setattr(driver, "stop_and_remove",
                        lambda name: f"{name}: stopped and removed")
    monkeypatch.setattr(driver, "stale_temp_dirs", lambda: [r"C:\Temp\_MEI123"])
    lines = driver.cleanup_driver()
    check("a leftover onefile temp dir is surfaced",
          any("_MEI123" in l for l in lines), f"({lines})")


def test_cleanup_driver_refuses_without_administrator(monkeypatch):
    monkeypatch.setattr(driver, "is_windows", lambda: True)
    monkeypatch.setattr(driver, "is_admin", lambda: False)
    lines = driver.cleanup_driver()
    check("cleanup without admin explains why it cannot",
          any("Administrator" in l for l in lines), f"({lines})")


def test_cleanup_driver_with_nothing_installed_says_so(monkeypatch):
    monkeypatch.setattr(driver, "is_windows", lambda: True)
    monkeypatch.setattr(driver, "is_admin", lambda: True)
    monkeypatch.setattr(driver, "installed_drivers", lambda: {})
    lines = driver.cleanup_driver()
    check("nothing installed reports nothing to clean up",
          any("nothing to clean up" in l for l in lines), f"({lines})")
