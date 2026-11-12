"""``tools/ci_linux_package_smoke.py``: every judge passes what a good bundle prints
and names each way a bad one was measured to go wrong (a smoke that cannot fail
proves nothing)."""
import os
import subprocess
import sys

from beantester import desktop
from fakes import ROOT, check

sys.path.insert(0, os.path.join(ROOT, "tools"))

import ci_linux_package_smoke as smoke                       # noqa: E402

# xwininfo -root -tree lines of the window: ours, and Tk's default class (measured).
WINDOW = '     0x2004b0 "Bean Network Tester": ("beannetworktester" "Beannetworktester")  1000x810+140+30'
TK_DEFAULT = '     0x2004b0 "Bean Network Tester": ("tk" "Tk")  1000x810+140+30  +140+30'
# A tooltip is a top-level window of the program's title too. Xvfb's pointer starts in the
# middle of the screen and rested on a field with one: the tooltip was listed before the
# main window (WSL Ubuntu, 3 starts of 3, 2026-11-12).
TOOLTIP = '     0x200665 "Bean Network Tester": ("!toplevel" "Toplevel")  366x140+493+427  +493+427'
OTHER_TITLE = '     0x300010 "Settings": ("beannetworktester" "Beannetworktester")  400x300+0+0  +0+0'
PROGRAM = "/t/BeanNetworkTester/BeanNetworkTester"
ENTRY = f'[Desktop Entry]\nExec="{PROGRAM}"\nStartupWMClass=Beannetworktester\n'
GOOD_REPRO ="[bean] Reproduce: ~/work/BeanNetworkTester/BeanNetworkTester --duration 2 --seed 42 --simulate\n"


def test_a_good_bundle_passes_every_judge():
    check("codes", smoke.judge_codes(0, 0, 3) == [])
    check("repro from ~", smoke.judge_repro(GOOD_REPRO) == [])
    check("repro from its own folder",
          smoke.judge_repro("Reproduce: ./BeanNetworkTester --simulate --seed 1") == [])
    check("doctor", smoke.judge_doctor("user files: /t/config/BeanNetworkTester\n", "/t/config") == [])
    check("window", smoke.judge_window(WINDOW, "") == [])
    check("menu entry", smoke.judge_entry(0, ENTRY, "", PROGRAM, True) == [])


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
    check("no window", "no window" in " ".join(smoke.judge_window(None, "")))
    check("Tk's default class", "class" in " ".join(smoke.judge_window(TK_DEFAULT, "")))
    for line in ('Fontconfig warning: "/etc/fonts/conf.d/48-guessfamily.conf", line 19',
                 "fc-match: symbol lookup error: fc-match: undefined symbol",
                 "No tkinter. Use CLI mode", "Traceback (most recent call last):"):
        found = smoke.judge_window(WINDOW, line + "\n")
        check(f"{line[:30]!r} is caught", len(found) == 1 and "printed 1 line" in found[0], f"({found})")


def _window_among(monkeypatch, *lines):
    """``window_line`` over an ``xwininfo -root -tree`` listing of these lines."""
    listing = "xwininfo: Window id: 0x5ba (the root window) (has no name)\n\n" + "\n".join(lines) + "\n"
    monkeypatch.setattr(smoke.subprocess, "run",
                        lambda args, **_kw: subprocess.CompletedProcess(args, 0, listing, ""))
    return smoke.window_line()


def test_the_main_window_is_judged_behind_a_tooltip(monkeypatch):
    """A tooltip of the same title listed first must not stand in for the main window,
    and a main window of the wrong class is still named."""
    found = _window_among(monkeypatch, TOOLTIP, WINDOW)
    check("the main window, not the tooltip", found == WINDOW, f"({found!r})")
    check("so the judge passes it", smoke.judge_window(found, "") == [])
    for lines, why in (((TOOLTIP, TK_DEFAULT), "a tooltip and Tk's default class"),
                       ((TK_DEFAULT,), "only Tk's default class"),
                       ((TOOLTIP, OTHER_TITLE), "the program's class under another title")):
        named = smoke.judge_window(_window_among(monkeypatch, *lines), "")
        check(f"{why}: the class is named", any("class" in f for f in named), f"({named})")
    check("no window of that title", _window_among(monkeypatch, OTHER_TITLE) is None)


def test_every_wrong_menu_entry_is_named():
    for case, word in (((5, None, "", PROGRAM, True), "answered 5"),
                       ((0, ENTRY.replace(PROGRAM, "/elsewhere/B"), "", PROGRAM, True), "this program"),
                       ((0, ENTRY.replace("StartupWMClass=Beannetworktester", ""), "", PROGRAM, True),
                        "class"),
                       ((0, ENTRY, "x.desktop: error: value is not quoted\n", PROGRAM, True),
                        "desktop-file-validate"),
                       ((0, ENTRY, "", PROGRAM, False), "left the entry")):
        found = smoke.judge_entry(*case)
        check(word, any(word in f for f in found), f"({found})")


def test_the_validator_is_heard_by_its_exit_code_and_both_streams():
    """desktop-file-validate's exit code says whether it found an error, and it can
    say so on either stream or on none; a warning comes with exit 0 and still counts,
    because a clean entry here has neither."""
    check("a clean entry", smoke.validator_says(0, "", "") == "")
    check("an error without a word: its exit code",
          smoke.validator_says(1, "", "") == "exit 1 without a word")
    check("an error on stderr", "error: bad" in smoke.validator_says(1, "", "error: bad\n"))
    check("an error on stdout", "not quoted" in smoke.validator_says(1, "x: error: not quoted\n", ""))
    check("a warning with exit 0", "hint" in smoke.validator_says(0, "x: hint: y\n", ""))


def test_it_looks_for_what_the_program_writes():
    """The smoke's own copies of the class and the file name (it runs on the bundle,
    without the program's sources) are the program's."""
    check("the window's class", smoke.WINDOW_CLASS == desktop.WINDOW_CLASS)
    check("the entry's file name", smoke.ENTRY_FILE == desktop.FILE_NAME)


def test_it_needs_a_display_and_one_program(monkeypatch, capsys):
    check("usage", smoke.main([]) == 2)
    monkeypatch.setattr(smoke.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    check("no display fails, never skips", smoke.main(["/b/BeanNetworkTester"]) == 1
          and "display" in capsys.readouterr().out)
