"""The logic behind the Tools tab's diagnostics - no window, runs on Linux CI.

What is pinned here is what the panel cannot check by looking: that every check
``driver.doctor()`` can give has a name in the language files, that the copied
report is the ``--version`` line and the ``--doctor`` output and nothing that
drifts from them, that one broken section costs its own block and not the report,
and that the cleanup is always asked with the window's own marker let go first.
"""
import json
import os

from beantester import capture_backend, driver
from beantester.appinfo import version_line
from beantester.nettools import diagnostics
from fakes import ROOT, check


def _names_doctor_can_give(monkeypatch):
    """Every check name, from every branch doctor() has: Windows or not, frozen or not.

    Taken by RUNNING it rather than read off the source, so a name built any other
    way than a literal is still found. Nothing here touches the machine: the
    service manager, pydivert and the temp folder are all stood in for.
    """
    monkeypatch.setattr(driver, "installed_drivers", lambda: {"WinDivert": "running"})
    monkeypatch.setattr(driver, "pydivert_available", lambda: True)
    monkeypatch.setattr(driver, "stale_temp_dirs", lambda: [])
    # elevated, so the program-folder row answers without writing a probe file
    monkeypatch.setattr(driver, "is_admin", lambda: True)
    names = set()
    for windows in (True, False):
        for frozen in (True, False):
            monkeypatch.setattr(driver, "is_windows", lambda w=windows: w)
            monkeypatch.setattr(driver, "is_frozen", lambda f=frozen: f)
            names |= {row[0] for row in driver.doctor()[1]}

    # ...and Linux's, whichever machine runs this: off Windows the rows are the
    # capture backend's, and on a Windows runner that backend is WinDivert's.
    class _Linux(capture_backend.EBPFDivertBackend):
        @staticmethod
        def doctor_rows():
            return capture_backend.EBPFDivertBackend.doctor_rows(release="6.8.0", root=ROOT, euid=0)
    monkeypatch.setattr(capture_backend, "current", lambda: _Linux())
    monkeypatch.setattr(driver, "is_windows", lambda: False)
    names |= {row[0] for row in driver.doctor()[1]}
    return names


def test_every_check_doctor_can_give_has_a_name_in_every_language(monkeypatch):
    names = _names_doctor_can_give(monkeypatch)
    check("the branches were walked (Windows, frozen: program folder; Linux)",
          {"python", "administrator", "program folder", "windivert driver",
           "kernel", "btf", "privileges"} <= names,
          f"({sorted(names)})")
    for code in ("en", "pl", "zh"):
        with open(os.path.join(ROOT, "lang", f"{code}.json"), encoding="utf-8") as f:
            texts = json.load(f)
        missing = sorted(n for n in names if diagnostics.check_key(n) not in texts)
        check(f"{code}: every check has a name", not missing, f"({missing})")


def test_the_diagnosis_is_doctors_own_list_unchanged(monkeypatch):
    rows = [("python", "ok", "3.14"), ("administrator", "fail", "not elevated")]
    monkeypatch.setattr(driver, "doctor", lambda: (False, rows))
    monkeypatch.setattr(diagnostics, "user_data_dir", lambda: "D:/data")
    found = diagnostics.diagnose()
    check("same checks, same order, same words",
          [tuple(c) for c in found.checks] == rows, f"({found.checks})")
    check("the verdict is doctor's", found.ok is False)
    check("and it says where this account's files are", found.data_dir == "D:/data")


def test_the_report_is_the_version_line_and_the_doctor_output(monkeypatch):
    """What the bug report template asks for, in the order it asks, and nothing else.

    Each block is compared with the function the command line prints through, not
    with a copy of its format written here: the promise is "the same text as
    --version and --doctor", and a second format in this file would pin the
    wrong thing the day the command's output changes.
    """
    diagnosis = diagnostics.Diagnosis(
        True, (diagnostics.Check("python", "ok", "3.14"),
               diagnostics.Check("windivert driver", "warn", "WinDivert=running")),
        "D:/data")
    blocks = diagnostics.report(diagnosis).split("\n\n")
    check("three blocks", len(blocks) == 3, f"({blocks})")
    check("first, exactly what --version prints", blocks[0] == version_line(),
          f"({blocks[0]!r})")
    check("then exactly what --doctor prints",
          blocks[1].split("\n") == driver.format_doctor(diagnosis.checks, "D:/data"),
          f"({blocks[1]!r})")
    # Read, not just headed: a section that fails still starts "crash log: " -
    # "crash log: could not be read (...)" - and would pass a check of the prefix.
    check("then the crash log of this run",
          blocks[2].startswith("crash log: ") and blocks[2].endswith("in this run")
          and "could not be read" not in blocks[2], f"({blocks[2]!r})")


def test_the_doctor_format_is_the_one_the_command_line_has_always_printed():
    """Moved out of the CLI so the window could share it - and the text did not move.

    The bug report template has asked for this output for many releases; a report
    pasted from an older version and one from this version must read alike.
    """
    lines = driver.format_doctor([("python", "ok", "3.14"),
                                  ("windivert driver", "warn", "x")], "D:/data")
    check("the columns", lines == ["OK   python             3.14",
                                   "WARN windivert driver   x",
                                   "user files: D:/data"], f"({lines})")


def test_a_section_that_fails_costs_its_own_block_and_nothing_else(monkeypatch):
    def broken(_diagnosis):
        raise OSError("the system said no")

    notes = []
    monkeypatch.setattr(diagnostics.crashlog, "note", lambda exc, area, *a: notes.append(area))
    sections = (diagnostics.REPORT_SECTIONS[0],
                diagnostics.Section("proxy", broken),
                diagnostics.REPORT_SECTIONS[1])
    diagnosis = diagnostics.Diagnosis(True, (diagnostics.Check("python", "ok", "3.14"),), "D:")
    blocks = diagnostics.report(diagnosis, sections).split("\n\n")
    check("the sections around it are whole",
          blocks[0] == version_line() and blocks[2].startswith("OK   python"), f"({blocks})")
    check("its own block says it could not be read, and why",
          blocks[1] == "proxy: could not be read (OSError)", f"({blocks[1]!r})")
    check("and the failure is recorded, not swallowed", notes == ["nettools.diagnostics"],
          f"({notes})")


def _snapshot():
    from beantester.adapters import AdapterRow, Reading
    from beantester.nettools import adapters
    row = AdapterRow("{E}", 9, 0, "Ethernet", "Intel", 6, 1, "AA-BB-CC-DD-EE-FF", 1500,
                     None, None, False, "", (), ("192.168.1.1",), (), "", None, None)
    return adapters.Snapshot(adapters.rank(Reading((row,), {4: 9})), 0.0, 3, 1)


def test_the_network_adapters_are_in_the_report_only_when_asked_for():
    """The bug report template asks for this report in a PUBLIC issue, and the
    adapters carry this machine's addresses and MAC: off until the person ticks
    the box (the owner's decision, 2026-10-13)."""
    snapshot = _snapshot()
    diagnosis = diagnostics.Diagnosis(True, (diagnostics.Check("python", "ok", "3.14"),),
                                      "D:", {"adapters": diagnostics.Found(snapshot)})
    plain = diagnostics.report(diagnosis)
    check("not in the report by default", "AA-BB-CC-DD-EE-FF" not in plain
          and "network adapters" not in plain and len(plain.split("\n\n")) == 3, f"({plain})")
    asked = diagnostics.report(diagnosis, include=("adapters",)).split("\n\n")
    check("asked for: one more block, after the others", len(asked) == 4, f"({asked})")
    from beantester.nettools import adapters
    check("the same text the adapters tool copies",
          asked[3] == adapters.report(snapshot), f"({asked[3]!r})")
    check("the optional sections are the adapters and the proxy, each its own box",
          [s.id for s in diagnostics.REPORT_SECTIONS if s.optional] == ["adapters", "proxy"])


def _proxy_reading():
    from beantester.proxy import MachineProxy, Reading, UserProxy, Variable
    return Reading(UserProxy(True, "", "192.0.2.10:8080", "<local>"), "",
                   MachineProxy("", ""), "",
                   (Variable("HTTP_PROXY", "http://user:secret@192.0.2.40:8080", "user"),), "")


def test_the_proxy_is_in_the_report_only_when_asked_for(monkeypatch):
    """The proxy's own box (the owner's decision, 2026-10-14): off until ticked, read
    with the checks, and a failure costs its own block."""
    from beantester.nettools import adapters, proxy
    monkeypatch.setattr(driver, "doctor", lambda: (True, [("python", "ok", "3.14")]))
    monkeypatch.setattr(adapters, "supported", lambda: False)
    monkeypatch.setattr(proxy, "supported", lambda: True)
    reading = _proxy_reading()
    monkeypatch.setattr(proxy, "read", lambda native=None: reading)
    diagnosis = diagnostics.diagnose()
    check("read with the checks", diagnosis.found["proxy"] == diagnostics.Found(reading),
          f"({dict(diagnosis.found)})")
    plain = diagnostics.report(diagnosis)
    check("not in the report by default", "192.0.2.10" not in plain, f"({plain})")
    block = diagnostics.report(diagnosis, include=("proxy",)).split("\n\n")[-1]
    check("asked for: the text the adapters tool copies", block == proxy.report(reading),
          f"({block!r})")
    check("with the password hidden", "secret" not in block and "***@192.0.2.40" in block,
          f"({block!r})")

    notes = []
    monkeypatch.setattr(diagnostics.crashlog, "note", lambda exc, area, *a: notes.append(area))

    def refused(native=None):
        raise OSError("the proxy read refused on purpose")
    monkeypatch.setattr(proxy, "read", refused)
    diagnosis = diagnostics.diagnose()
    block = diagnostics.report(diagnosis, include=("proxy",)).split("\n\n")[-1]
    check("a failed read costs its own block", block.startswith(
        "proxy: could not be read (OSError: "), f"({block!r})")
    check("and is recorded", notes == ["nettools.diagnostics.proxy"], f"({notes})")


def test_an_adapter_list_that_cannot_be_read_costs_its_own_section(monkeypatch):
    from beantester.nettools import adapters, proxy
    monkeypatch.setattr(driver, "doctor", lambda: (True, [("python", "ok", "3.14")]))
    monkeypatch.setattr(adapters, "supported", lambda: True)
    monkeypatch.setattr(proxy, "supported", lambda: False)
    notes = []
    monkeypatch.setattr(diagnostics.crashlog, "note", lambda exc, area, *a: notes.append(area))

    def refused():
        raise OSError("the adapter list refused on purpose")
    monkeypatch.setattr(adapters, "read", refused)
    diagnosis = diagnostics.diagnose()
    check("the checks are still there", diagnosis.ok and len(diagnosis.checks) == 1)
    found = diagnosis.found["adapters"]
    check("the adapters are not, and why is kept",
          found.value is None and "refused on purpose" in found.error, f"({found})")
    check("a fault of the program is recorded", notes == ["nettools.diagnostics.adapters"],
          f"({notes})")
    block = diagnostics.report(diagnosis, include=("adapters",)).split("\n\n")[-1]
    check("the section says it could not be read", block.startswith(
        "network adapters: could not be read (OSError: "), f"({block!r})")

    def not_ready():
        raise adapters.Unreadable("tools.adapters.error_not_ready", "answered 1228")
    monkeypatch.setattr(adapters, "read", not_ready)
    notes.clear()
    diagnosis = diagnostics.diagnose()
    check("a reason the person can wait out is not a fault", notes == [], f"({notes})")

    monkeypatch.setattr(adapters, "supported", lambda: False)
    diagnosis = diagnostics.diagnose()
    block = diagnostics.report(diagnosis, include=("adapters",)).split("\n\n")[-1]
    check("off Windows the section says so", diagnosis.found["adapters"].value is None
          and block == "network adapters: not read on this system", f"({block!r})")


def test_why_the_driver_cannot_be_cleaned_up_from_here(monkeypatch):
    from beantester import capture_backend
    # WinDivert's answers - Windows, and a platform with no capture driver of its own
    # (the backend is pinned: on the Linux runner it is eBPFDivert's, below).
    monkeypatch.setattr(capture_backend, "_CURRENT", capture_backend._WINDIVERT)
    cases = {(False, False): "tools.diagnostics.clean_windows_only",
             (False, True): "tools.diagnostics.clean_windows_only",
             (True, False): "tools.diagnostics.clean_needs_admin",
             (True, True): ""}
    for (windows, admin), expected in cases.items():
        monkeypatch.setattr(driver, "is_windows", lambda w=windows: w)
        monkeypatch.setattr(driver, "is_admin", lambda a=admin: a)
        got = diagnostics.cleanup_blocker()
        check(f"windows={windows} admin={admin}", got == expected, f"({got!r})")
    # Linux: nothing to clean - the kernel does it (measured: unregister() after a
    # SIGKILL changed nothing, 2.6 s either way).
    monkeypatch.setattr(capture_backend, "_CURRENT", capture_backend._EBPFDIVERT)
    monkeypatch.setattr(driver, "is_windows", lambda: False)
    check("Linux says why there is nothing to clean",
          diagnostics.cleanup_blocker() == "tools.diagnostics.clean_linux")
    check("and the command line says it in its own words",
          driver.cleanup_driver() == [capture_backend.EBPFDivertBackend.CLEANUP_LINE]
          and "kernel" in capture_backend.EBPFDivertBackend.CLEANUP_LINE)


def test_the_window_cleans_up_with_its_own_marker_let_go_first(monkeypatch):
    """A window that has run a session holds the use marker until it exits; asked
    without letting it go, the warning about ANOTHER instance could never fire."""
    asked = []
    monkeypatch.setattr(driver, "cleanup_driver",
                        lambda release_own=False, opens_seen=None:
                        asked.append((release_own, opens_seen)) or ["done"])
    check("the lines come back", diagnostics.clean_up(7) == ("done",))
    check("with release_own, and what was open at the yes", asked == [(True, 7)],
          f"({asked})")
    monkeypatch.setattr(driver, "_OPENS", [5])
    check("the count read at the yes is the driver's own",
          diagnostics.opens_so_far() == 5, f"({diagnostics.opens_so_far()})")
