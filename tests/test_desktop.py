"""The Linux package's menu entry (``beantester/desktop.py``) and its two options.

``--install-desktop`` writes one Desktop Entry for the person, ``--remove-desktop``
takes it away (owner decision 2026-10-28). What can go wrong is in the file's
own rules - the Desktop Entry Specification quotes ``Exec`` arguments and then
escapes the value as a string, so a path with a quote, a dollar or a backslash is
easy to get wrong - and in where and as whom it is written.
"""
import os
import shutil
import subprocess
import sys
import types

import pytest

from beantester import appinfo, cli, desktop, exitcodes, linuxenv, paths, winenv
from fakes import check

PROGRAM = "/u/ana/BeanNetworkTester/BeanNetworkTester"
ICON = "/u/ana/BeanNetworkTester/_internal/bean.png"


@pytest.fixture
def package(monkeypatch):
    """This run as the Linux package, started by a person (no root)."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "running_as_root", lambda: False)


def _entry(tmp_path):
    return tmp_path / ".local" / "share" / "applications" / desktop.FILE_NAME


def test_the_entry_goes_into_the_persons_applications_folder():
    say = desktop.applications_dir
    check("XDG_DATA_HOME", say({"XDG_DATA_HOME": "/u/ana/.data", "HOME": "/u/ana"})
          == "/u/ana/.data/applications")
    check("a relative one is ignored (XDG spec)", say({"XDG_DATA_HOME": "data", "HOME": "/u/ana"})
          == "/u/ana/.local/share/applications")
    check("none: ~/.local/share", say({"HOME": "/u/ana"}) == "/u/ana/.local/share/applications")


def test_exec_quotes_the_path_the_way_the_specification_does():
    """Quoting first (``"`` ` ``$`` ``\\`` get a backslash), then the string escape
    on top (each backslash doubled), and ``%`` as ``%%`` - the spec's own example:
    a literal backslash in a quoted argument is four backslashes in the file."""
    check("a plain path", desktop.exec_value(PROGRAM) == f'"{PROGRAM}"')
    check("a space needs only the quotes",
          desktop.exec_value("/u/ana/My Apps/B") == '"/u/ana/My Apps/B"')
    check("a double quote", desktop.exec_value('/u/a"b/B') == '"/u/a\\\\"b/B"',
          f"({desktop.exec_value('/u/a\"b/B')})")
    check("a dollar and a backtick", desktop.exec_value("/u/$x`y`/B") == '"/u/\\\\$x\\\\`y\\\\`/B"')
    check("a backslash: four", desktop.exec_value("/u/a\\b/B") == '"/u/a\\\\\\\\b/B"')
    check("a percent sign is not a field code", desktop.exec_value("/u/100%/B") == '"/u/100%%/B"')


def test_the_entry_starts_the_program_itself_and_names_the_windows_class():
    text = desktop.entry_text(PROGRAM, ICON)
    lines = text.splitlines()
    check("a Desktop Entry", lines[0] == "[Desktop Entry]" and "Type=Application" in lines)
    check("the program, not pkexec (the window asks for root itself)",
          f'Exec="{PROGRAM}"' in lines and "pkexec" not in text)
    check("its icon", f"Icon={ICON}" in lines)
    check("the window's class, so the dock shows the entry's name and icon",
          f"StartupWMClass={desktop.WINDOW_CLASS}" in lines)
    check("no terminal", "Terminal=false" in lines)
    check("named as the window is", f"Name={appinfo.APP_NAME}" in lines)


@pytest.mark.skipif(shutil.which("desktop-file-validate") is None,
                    reason="desktop-file-validate is not installed")
def test_the_entry_is_valid_for_desktop_file_validate(tmp_path):
    entry = tmp_path / desktop.FILE_NAME
    entry.write_text(desktop.entry_text('/u/a "b"/$x/B', ICON), encoding="utf-8")
    done = subprocess.run(["desktop-file-validate", str(entry)], capture_output=True, text=True)
    check("no errors, no warnings", done.returncode == 0 and not done.stdout.strip(),
          f"({done.stdout}{done.stderr})")


def test_only_the_linux_package_run_by_a_person_writes_it(monkeypatch, package):
    check("the package, a person: yes", desktop.why_not() is None)
    monkeypatch.setattr(paths, "running_as_root", lambda: True)
    check("under sudo: no - the file would be root's", "without sudo" in desktop.why_not())
    monkeypatch.setattr(paths, "running_as_root", lambda: False)
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    check("from sources: no", "from sources" in desktop.why_not())
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "platform", "win32")
    check("not Linux: no", "not Linux" in desktop.why_not())


def test_install_writes_the_entry_and_writes_it_again(tmp_path, package):
    env = {"HOME": str(tmp_path)}
    path, error = desktop.install(PROGRAM, ICON, env)
    entry = _entry(tmp_path)
    check("written where the menu reads it", error is None and os.path.samefile(path, entry),
          f"({path}, {error})")
    check("with the program", f'Exec="{PROGRAM}"' in entry.read_text(encoding="utf-8"))
    if os.name == "posix":
        check("readable by all, executable by none", (entry.stat().st_mode & 0o777) == 0o644)
    desktop.install(PROGRAM.replace("ana", "ana/new"), ICON, env)
    check("a second install replaces it (the folder moved)",
          "ana/new" in entry.read_text(encoding="utf-8"))
    check("and leaves no temporary file",
          sorted(os.listdir(entry.parent)) == [desktop.FILE_NAME])


def test_a_path_with_a_control_character_is_refused(tmp_path, package):
    path, error = desktop.install("/u/ana/a\nb/B", ICON, {"HOME": str(tmp_path)})
    check("refused, nothing written", path is None and "control character" in error
          and not _entry(tmp_path).exists(), f"({error})")


def test_a_folder_that_cannot_be_written_is_said_and_leaves_nothing(tmp_path, package):
    (tmp_path / ".local").write_text("a file where the folder would be", encoding="utf-8")
    path, error = desktop.install(PROGRAM, ICON, {"HOME": str(tmp_path)})
    check("not written, and why", path is None and error.startswith("cannot write"), f"({error})")


def test_remove_takes_only_its_own_file(tmp_path, package):
    env = {"HOME": str(tmp_path)}
    desktop.install(PROGRAM, ICON, env)
    other = _entry(tmp_path).parent / "org.example.Other.desktop"
    other.write_text("[Desktop Entry]\n", encoding="utf-8")
    path, error = desktop.remove(env)
    check("removed", error is None and path and not _entry(tmp_path).exists())
    check("another program's entry stays", other.exists())
    check("nothing to remove: said, not an error", desktop.remove(env) == (None, None))


def test_the_options_answer_with_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(desktop, "why_not", lambda: "the menu entry is for the Linux package")
    check("not here: 1 and why", cli.run_cli(["--install-desktop"]) == exitcodes.RUNTIME
          and "Linux package" in capsys.readouterr().err)
    monkeypatch.setattr(desktop, "why_not", lambda: None)
    monkeypatch.setattr(desktop, "install", lambda: (None, "cannot write /x: Permission denied"))
    check("not written: 5", cli.run_cli(["--install-desktop"]) == exitcodes.IO)
    monkeypatch.setattr(desktop, "install", lambda: ("/u/ana/x.desktop", None))
    check("written: 0, and where", cli.run_cli(["--install-desktop"]) == exitcodes.OK
          and "/u/ana/x.desktop" in "".join(capsys.readouterr()))
    monkeypatch.setattr(desktop, "remove", lambda: (None, None))
    check("nothing to remove: 0", cli.run_cli(["--remove-desktop"]) == exitcodes.OK
          and "no menu entry" in "".join(capsys.readouterr()))


def test_install_and_remove_together_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as stop:
        cli.build_arg_parser().parse_args(["--install-desktop", "--remove-desktop"])
    check("argparse refuses it", stop.value.code == exitcodes.USAGE)
    capsys.readouterr()


def test_the_class_is_written_the_way_tk_gives_it():
    """Tk title-cases the class it is given (measured: "BeanNetworkTester" became
    "Beannetworktester"), so a class in any other form is one no window has."""
    check("first letter up, the rest down",
          desktop.WINDOW_CLASS == desktop.WINDOW_CLASS.capitalize(), f"({desktop.WINDOW_CLASS})")


def test_the_window_carries_the_class_the_entry_names(monkeypatch):
    """Tk's default class is "Tk" (measured with xwininfo on the package); the
    window's root is made with the class StartupWMClass names."""
    made = []
    fake_tk = types.ModuleType("tkinter")
    fake_tk.Tk = lambda **options: made.append(options) or types.SimpleNamespace(  # type: ignore[attr-defined]
        mainloop=lambda: None)
    fake_gui = types.ModuleType("beantester.gui")
    fake_gui.App = lambda root: None                        # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    monkeypatch.setitem(sys.modules, "beantester.gui", fake_gui)
    monkeypatch.setattr(winenv, "is_windows", lambda: False)
    monkeypatch.setattr(linuxenv, "wants_root", lambda: False)
    monkeypatch.setattr(linuxenv, "take_desktop", lambda: [])
    monkeypatch.setattr(cli.crashlog, "arm_native", lambda: None)
    check("opened", cli._run_gui([]) == exitcodes.OK)
    check("with the entry's class", made == [{"className": desktop.WINDOW_CLASS}], f"({made})")
