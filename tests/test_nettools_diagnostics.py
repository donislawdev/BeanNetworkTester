"""The logic behind the Tools tab's diagnostics - no window, runs on Linux CI.

What is pinned here is what the panel cannot check by looking: that every check
``driver.doctor()`` can give has a name in the language files, that the copied
report is the ``--version`` line and the ``--doctor`` output and nothing that
drifts from them, that one broken section costs its own block and not the report,
and that the cleanup is always asked with the window's own marker let go first.
"""
import json
import os

from beantester import driver
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
    return names


def test_every_check_doctor_can_give_has_a_name_in_every_language(monkeypatch):
    names = _names_doctor_can_give(monkeypatch)
    check("the branches were walked (Windows, frozen: program folder)",
          {"python", "administrator", "program folder", "windivert driver"} <= names,
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
    check("then the crash log of this run", blocks[2].startswith("crash log: "),
          f"({blocks[2]!r})")


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


def test_why_the_driver_cannot_be_cleaned_up_from_here(monkeypatch):
    cases = {(False, False): "tools.diagnostics.clean_windows_only",
             (False, True): "tools.diagnostics.clean_windows_only",
             (True, False): "tools.diagnostics.clean_needs_admin",
             (True, True): ""}
    for (windows, admin), expected in cases.items():
        monkeypatch.setattr(driver, "is_windows", lambda w=windows: w)
        monkeypatch.setattr(driver, "is_admin", lambda a=admin: a)
        got = diagnostics.cleanup_blocker()
        check(f"windows={windows} admin={admin}", got == expected, f"({got!r})")


def test_the_window_cleans_up_with_its_own_marker_let_go_first(monkeypatch):
    """A window that has run a session holds the use marker until it exits; asked
    without letting it go, the warning about ANOTHER instance could never fire."""
    asked = []
    monkeypatch.setattr(driver, "cleanup_driver",
                        lambda release_own=False: asked.append(release_own) or ["done"])
    check("the lines come back", diagnostics.clean_up() == ("done",))
    check("with release_own", asked == [True], f"({asked})")
