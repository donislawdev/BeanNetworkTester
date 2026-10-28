"""``tools/ci_linux_package_smoke.py``: every judge passes what a good bundle prints
and names each way a bad one was measured to go wrong (a smoke that cannot fail
proves nothing)."""
import os
import sys

from fakes import ROOT, check

sys.path.insert(0, os.path.join(ROOT, "tools"))

import ci_linux_package_smoke as smoke                       # noqa: E402

GOOD_REPRO = "[bean] Reproduce: ~/work/BeanNetworkTester/BeanNetworkTester --duration 2 --seed 42 --simulate\n"


def test_a_good_bundle_passes_every_judge():
    check("codes", smoke.judge_codes(0, 0, 3) == [])
    check("repro from ~", smoke.judge_repro(GOOD_REPRO) == [])
    check("repro from its own folder",
          smoke.judge_repro("Reproduce: ./BeanNetworkTester --simulate --seed 1") == [])
    check("doctor", smoke.judge_doctor("user files: /t/config/BeanNetworkTester\n", "/t/config") == [])
    check("window", smoke.judge_window(True, "") == [])


def test_every_wrong_exit_code_is_named():
    for codes, word in (((1, 0, 3), "--version"), ((0, 7, 3), "simulated"), ((0, 0, 1), "configuration")):
        found = smoke.judge_codes(*codes)
        check(f"{codes}: {word}", len(found) == 1 and word in found[0], f"({found})")


def test_every_wrong_repro_line_is_named():
    """It said ``BeanNetworkTester.exe`` on Linux before the package (measured)."""
    for line, word in (("Reproduce: BeanNetworkTester.exe --simulate", "not from ~"),
                       ("Reproduce: sudo ~/b/BeanNetworkTester --simulate", "under sudo"),
                       ("Reproduce: python3 bean_network_tester.py --simulate", "not from ~"),
                       ("Reproduce: ~/b/BeanNetworkTester --seed 1", "lost --simulate"),
                       ("Finished: ok", "no Reproduce")):
        found = smoke.judge_repro(line)
        check(f"{line!r}: {word}", any(word in f for f in found), f"({found})")


def test_a_data_folder_elsewhere_is_named():
    found = smoke.judge_doctor("user files: /u/x/AppData/Local/BeanNetworkTester", "/t/config")
    check("AppData is caught", len(found) == 1 and "AppData" in found[0], f"({found})")
    check("no such line is caught", smoke.judge_doctor("OK python", "/t/config") != [])


def test_a_window_that_did_not_open_or_spoke_is_named():
    check("no window", "no window" in " ".join(smoke.judge_window(False, "")))
    for line in ('Fontconfig warning: "/etc/fonts/conf.d/48-guessfamily.conf", line 19',
                 "fc-match: symbol lookup error: fc-match: undefined symbol",
                 "No tkinter. Use CLI mode", "Traceback (most recent call last):"):
        found = smoke.judge_window(True, line + "\n")
        check(f"{line[:30]!r} is caught", len(found) == 1 and "printed 1 line" in found[0], f"({found})")


def test_it_needs_a_display_and_one_program(monkeypatch, capsys):
    check("usage", smoke.main([]) == 2)
    monkeypatch.setattr(smoke.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    check("no display fails, never skips", smoke.main(["/b/BeanNetworkTester"]) == 1
          and "display" in capsys.readouterr().out)
