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
