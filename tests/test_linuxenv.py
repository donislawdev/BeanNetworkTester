"""linuxenv: the window on Linux asks for root through pkexec (polkit).

Nothing here starts pkexec: every call to the system is handed in. The real pkexec
runs in CI (``tools/ci_linux_pkexec_smoke.py``); what it does is in linuxenv's own
docstring.
"""
import os
import signal
import subprocess
import sys
import types

import pytest

from beantester import capture_backend, cli, crashlog, exitcodes, linuxenv, winenv
from fakes import check

PKEXEC = "/usr/bin/pkexec"
USAGE = "pkexec --version |\n       [--keep-cwd] [--user username] [PROGRAM] [ARGUMENTS...]\n"


def have(_name):
    return PKEXEC


class _Rights:
    def __init__(self, has):
        self.has = has

    def has_capture_rights(self):
        return self.has


class _Run:
    """Stands in for ``subprocess.run``: records each command, answers pkexec's
    usage, and ends the copy with ``code``."""

    def __init__(self, code=0, usage=USAGE):
        self.code, self.usage, self.calls = code, usage, []

    def __call__(self, command, env=None, **kw):
        self.calls.append((command, env, kw))
        if command[1:] == ["--help"]:
            return subprocess.CompletedProcess(command, 0, stdout=self.usage, stderr="")
        return subprocess.CompletedProcess(command, self.code)


@pytest.fixture
def started_from_script(monkeypatch, tmp_path):
    """This test process started as ``python -u <checkout>/bean_network_tester.py --gui``."""
    script = tmp_path / "bean_network_tester.py"
    script.write_text("", encoding="utf-8")
    monkeypatch.setattr(winenv, "is_frozen", lambda: False)
    monkeypatch.setattr(sys, "executable", "/v/bin/python")
    monkeypatch.setattr(sys, "orig_argv", ["/v/bin/python", "-u", str(script), "--gui"])
    monkeypatch.setattr(sys, "argv", [str(script), "--gui"])
    return os.path.abspath(str(script))


def test_the_window_asks_for_root_only_where_it_can_and_root_would_help(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("BEAN_NO_ELEVATE", raising=False)
    monkeypatch.setattr(capture_backend, "current", lambda: _Rights(False))
    desk = {"DISPLAY": ":0"}
    check("a person at a desktop, without rights, with pkexec: asks",
          linuxenv.wants_root(desk, 1000, have) is True)
    check("root never asks: root without CAP_BPF (a container) would start copy after copy",
          linuxenv.wants_root(desk, 0, have) is False)
    check("no display: no window to ask from", linuxenv.wants_root({}, 1000, have) is False)
    check("no pkexec", linuxenv.wants_root(desk, 1000, lambda name: None) is False)
    monkeypatch.setenv("BEAN_NO_ELEVATE", "1")
    check("BEAN_NO_ELEVATE, as on Windows", linuxenv.wants_root(desk, 1000, have) is False)
    monkeypatch.delenv("BEAN_NO_ELEVATE")
    monkeypatch.setattr(capture_backend, "current", lambda: _Rights(True))
    check("the capabilities are already there", linuxenv.wants_root(desk, 1000, have) is False)
    monkeypatch.setattr(capture_backend, "current", lambda: _Rights(False))
    monkeypatch.setattr(sys, "platform", "win32")
    check("not Linux: winenv asks there", linuxenv.wants_root(desk, 1000, have) is False)


def test_pkexec_is_given_only_the_locale_it_will_not_refuse():
    """pkexec exits 127 when SHELL is not in /etc/shells or a variable it keeps holds
    `/`, `%` or `..` (validate_environment_variable) - before it asks anything."""
    env = {"LANG": "pl_PL.UTF-8", "LANGUAGE": "pl:en", "LC_ALL": "C/odd", "LC_TIME": "a%b",
           "LC_CTYPE": "x..y", "LC_NUMERIC": "", "SHELL": "/usr/bin/fish",
           "TERM": "xterm-256color", "DISPLAY": ":0", "HOME": "/u/ana", "PATH": "/usr/bin"}
    given = linuxenv.pkexec_environment(env)
    check("the locale that passes pkexec's rules, nothing else",
          given == {"LANG": "pl_PL.UTF-8", "LANGUAGE": "pl:en"}, f"({given})")


def test_the_copy_is_started_the_way_this_program_was(monkeypatch, started_from_script):
    script = started_from_script
    cmd = linuxenv.relaunch_command(["--gui"], PKEXEC, True)
    check("from sources: no agent of pkexec's own, -B added, the script absolute",
          cmd == [PKEXEC, "--disable-internal-agent", "--keep-cwd", "/v/bin/python", "-B", "-u",
                  script, "--gui"], f"({cmd})")
    old = linuxenv.relaunch_command(["--gui"], PKEXEC, False)
    check("no --keep-cwd where pkexec has none", old == [PKEXEC, "--disable-internal-agent",
                                                         "/v/bin/python", "-B", "-u", script,
                                                         "--gui"], f"({old})")
    monkeypatch.setattr(sys, "orig_argv", ["/v/bin/python", "-B", script])
    monkeypatch.setattr(sys, "argv", [script])
    once = linuxenv.relaunch_command([], PKEXEC, True)
    check("-B given once", once.count("-B") == 1, f"({once})")
    monkeypatch.setattr(sys, "orig_argv", ["/v/bin/python", "-m", "beantester"])
    monkeypatch.setattr(sys, "argv", ["/c/beantester/__main__.py"])
    module = linuxenv.relaunch_command([], PKEXEC, True)
    check("python -m, with --keep-cwd", module == [PKEXEC, "--disable-internal-agent",
                                                    "--keep-cwd", "/v/bin/python", "-B", "-m",
                                                    "beantester"], f"({module})")
    check("python -m without it: root's home cannot import it, so nothing to repeat",
          linuxenv.relaunch_command([], PKEXEC, False) is None)
    monkeypatch.setattr(winenv, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", "/opt/bnt/BeanNetworkTester")
    frozen = linuxenv.relaunch_command(["--gui"], PKEXEC, True)
    check("a frozen build: the executable and its arguments", frozen == [
        PKEXEC, "--disable-internal-agent", "--keep-cwd", "/opt/bnt/BeanNetworkTester", "--gui"],
        f"({frozen})")


def test_what_pkexec_answers_decides_who_opens_the_window(capsys, started_from_script):
    env = {"LANG": "C.UTF-8", "SHELL": "/bin/bash", "DISPLAY": ":0"}
    for answer, expected in ((0, 0), (1, 1), (7, 7), (-15, 143), (126, None), (127, None)):
        run = _Run(answer)
        got = linuxenv.ask_for_root(["--gui"], run, have, env)
        check(f"pkexec answers {answer}: {expected}", got == expected, f"({got})")
    command, given, kw = run.calls[-1]
    check("the copy is started through pkexec without its own agent",
          command[:2] == [PKEXEC, "--disable-internal-agent"] and "--keep-cwd" in command,
          f"({command})")
    check("with the locale only", given == {"LANG": "C.UTF-8"}, f"({given})")
    check("and keeps the terminal, for as long as it runs", kw == {}, f"({kw})")
    check("a copy that did not run is said on stderr",
          "did not start the window as root (exit 127)" in capsys.readouterr().err)
    nothing = _Run()
    check("no pkexec: nothing to ask through",
          linuxenv.ask_for_root([], nothing, lambda name: None, env) is None and not nothing.calls)



def test_a_pkexec_that_cannot_be_started_is_recorded_and_said(monkeypatch, capsys,
                                                               started_from_script):
    noted = []
    monkeypatch.setattr(crashlog, "note", lambda exc, section: noted.append(section))

    def broken(command, env=None, **kw):
        raise OSError("gone")
    check("pkexec that cannot be started: the window opens here",
          linuxenv.ask_for_root([], broken, have, {}) is None)
    check("recorded, and said on stderr",
          "linuxenv.pkexec" in noted and "could not be started (gone)" in capsys.readouterr().err,
          f"({noted})")

    started = []

    def no_usage(command, env=None, **kw):
        if command[1:] == ["--help"]:
            raise subprocess.TimeoutExpired(command, 10)
        started.append(command)
        return subprocess.CompletedProcess(command, 3)
    noted.clear()
    check("a usage that cannot be read: recorded, and asked without --keep-cwd",
          linuxenv.ask_for_root([], no_usage, have, {}) == 3 and noted == ["linuxenv.keep_cwd"]
          and started and "--keep-cwd" not in started[0], f"({noted}, {started})")


def test_an_old_pkexec_and_python_m_ask_nothing(monkeypatch):
    """polkit 0.105 (Ubuntu 22.04) has no --keep-cwd: `python -m beantester` from a
    checkout would start in root's home and fail to import. Nothing is asked."""
    monkeypatch.setattr(winenv, "is_frozen", lambda: False)
    monkeypatch.setattr(sys, "orig_argv", ["/v/bin/python", "-m", "beantester"])
    monkeypatch.setattr(sys, "argv", ["/c/beantester/__main__.py"])
    run = _Run(usage="pkexec --version |\n       [--user username] PROGRAM [ARGUMENTS...]\n")
    check("the window opens without root", linuxenv.ask_for_root([], run, have, {}) is None)
    check("and only the usage was read", [c[0][1:] for c in run.calls] == [["--help"]],
          f"({run.calls})")


def test_ctrl_c_while_the_copy_runs_is_waited_through(started_from_script):
    """Ctrl+C in the terminal reaches the copy too. Here it must neither end the
    wait (subprocess.run kills its child on an exception) nor become SIG_IGN, which
    the copy would inherit through pkexec."""
    before = signal.getsignal(signal.SIGINT)
    seen = []

    def run(command, env=None, **kw):
        if command[1:] == ["--help"]:
            return subprocess.CompletedProcess(command, 0, stdout=USAGE, stderr="")
        seen.append(signal.getsignal(signal.SIGINT))
        signal.raise_signal(signal.SIGINT)
        return subprocess.CompletedProcess(command, 5)

    check("the copy's code comes back, no KeyboardInterrupt",
          linuxenv.ask_for_root([], run, have, {}) == 5)
    check("a handler that does nothing, not SIG_IGN", seen and seen[0] not in (
        signal.SIG_IGN, signal.SIG_DFL, signal.default_int_handler), f"({seen})")
    check("and the old one is back", signal.getsignal(signal.SIGINT) is before)


class _Person:
    """What the copy finds about the person: the parent process and their files."""

    def __init__(self, uid=1000, env=None, cwd="/u/ana/bnt", files=(), home="/u/ana"):
        self.uid, self.cwd_, self.files, self.home = uid, cwd, set(files), home
        self.env = {"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.Q"} \
            if env is None else env

    def real_uid(self, pid):
        return self.uid

    def environ(self, pid):
        return dict(self.env)

    def cwd(self, pid):
        return self.cwd_

    def home_of(self, uid):
        return self.home

    def owns_file(self, uid, path):
        return uid == 1000 and path in self.files


XAUTH = "/run/user/1000/.mutter-Xwaylandauth.Q"
HOME_XAUTH = "/u/ana/.Xauthority"


def test_the_copy_takes_the_desktop_of_the_person_who_asked():
    asked = {"PKEXEC_UID": "1000"}
    found = linuxenv.desktop_of_parent(asked, _Person(files=[XAUTH]), 42)
    check("display, X authority and folder of the person's process",
          found == {"DISPLAY": ":0", "XAUTHORITY": XAUTH, "cwd": "/u/ana/bnt"}, f"({found})")
    check("a parent that is not the person's: nothing",
          linuxenv.desktop_of_parent(asked, _Person(uid=1001, files=[XAUTH]), 42) == {})
    check("no PKEXEC_UID: nothing", linuxenv.desktop_of_parent({}, _Person(files=[XAUTH]), 42) == {})
    odd = _Person(env={"DISPLAY": "$(id):0", "XAUTHORITY": XAUTH}, files=[XAUTH])
    check("a DISPLAY that is not one: nothing", linuxenv.desktop_of_parent(asked, odd, 42) == {})
    for display in (":1", "localhost:10.0", "unix:0"):
        ok = linuxenv.desktop_of_parent(asked, _Person(env={"DISPLAY": display}), 42)
        check(f"{display!r} is a display", ok.get("DISPLAY") == display, f"({ok})")
    foreign = linuxenv.desktop_of_parent(asked, _Person(files=[HOME_XAUTH]), 42)
    check("an X authority file that is not the person's: ~/.Xauthority instead",
          foreign.get("XAUTHORITY") == HOME_XAUTH, f"({foreign})")
    x11 = linuxenv.desktop_of_parent(asked, _Person(env={"DISPLAY": ":0"}, files=[HOME_XAUTH]), 42)
    check("an X11 session that sets none: ~/.Xauthority, as pkexec itself would",
          x11.get("XAUTHORITY") == HOME_XAUTH, f"({x11})")
    relative = _Person(env={"DISPLAY": ":0", "XAUTHORITY": "x/.Xauthority"}, files=["x/.Xauthority"])
    check("a relative path is not taken",
          "XAUTHORITY" not in linuxenv.desktop_of_parent(asked, relative, 42))
    gone = linuxenv.desktop_of_parent(asked, _Person(cwd=None, files=[XAUTH]), 42)
    check("a folder that cannot be read is left", "cwd" not in gone and gone["DISPLAY"] == ":0")


def test_only_the_copy_pkexec_started_takes_anything(monkeypatch):
    moved = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(os, "chdir", moved.append)
    env = {"PKEXEC_UID": "1000"}
    taken = linuxenv.take_desktop(env, _Person(files=[XAUTH]), 42)
    check("the copy: display and X authority set, the folder entered",
          taken == ["DISPLAY", "XAUTHORITY", "cwd"] and env["DISPLAY"] == ":0"
          and env["XAUTHORITY"] == XAUTH and moved == ["/u/ana/bnt"], f"({taken}, {env}, {moved})")
    moved.clear()
    sudo = {"PKEXEC_UID": "1000", "DISPLAY": ":5"}
    check("a DISPLAY already there (sudo keeps it): left as it is",
          linuxenv.take_desktop(sudo, _Person(files=[XAUTH]), 42) == [] and sudo["DISPLAY"] == ":5"
          and not moved)
    check("not under pkexec: nothing", linuxenv.take_desktop({}, _Person(files=[XAUTH]), 42) == [])
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    check("not root: nothing", linuxenv.take_desktop({"PKEXEC_UID": "1000"},
                                                     _Person(files=[XAUTH]), 42) == [])


def test_the_parent_is_read_from_its_proc_entries(tmp_path):
    entry = tmp_path / "4242"
    entry.mkdir()
    (entry / "status").write_text("Name:\tpython\nUid:\t1000\t1001\t1002\t1003\n", encoding="ascii")
    (entry / "environ").write_bytes(b"A=1\0DISPLAY=:0\0DISPLAY=:9\0junk\0X=a=b\0")
    system = linuxenv._System(str(tmp_path))
    check("the REAL uid", system.real_uid(4242) == 1000)
    check("the environment, first value of a name wins, no '=' skipped",
          system.environ(4242) == {"A": "1", "DISPLAY": ":0", "X": "a=b"}, f"({system.environ(4242)})")
    check("a process that is gone: nothing", system.real_uid(9999) is None
          and system.environ(9999) == {} and system.cwd(9999) is None)


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="file owners are a POSIX question")
def test_an_x_authority_file_is_a_regular_file_of_the_person(tmp_path):
    mine = tmp_path / "Xauthority"
    mine.write_bytes(b"cookie")
    link = tmp_path / "link"
    link.symlink_to(mine)
    owns = linuxenv._System.owns_file
    check("a regular file of theirs", owns(os.getuid(), str(mine)) is True)
    check("not someone else's", owns(os.getuid() + 1, str(mine)) is False)
    check("not a link to one", owns(os.getuid(), str(link)) is False)
    check("not a folder", owns(os.getuid(), str(tmp_path)) is False)
    proc = tmp_path / "proc" / "77"
    proc.mkdir(parents=True)
    (proc / "cwd").symlink_to(tmp_path)
    check("the parent's folder through its cwd link",
          linuxenv._System(str(tmp_path / "proc")).cwd(77) == str(tmp_path))


def _fake_tk(tk_fails):
    tkinter = types.ModuleType("tkinter")

    class TclError(Exception):
        pass

    def tk():
        if tk_fails:
            raise TclError("no display name and no $DISPLAY environment variable")
        return types.SimpleNamespace(mainloop=lambda: None)

    tkinter.TclError, tkinter.Tk = TclError, tk
    return tkinter


def _gui(monkeypatch, tk_fails=True, app_fails=False):
    """cli._run_gui up to the window, with nothing real; returns the window's failures
    and the times the copy's desktop was taken."""
    failed, taken = [], []
    gui = types.ModuleType("beantester.gui")

    def app(root):
        if app_fails:
            raise sys.modules["tkinter"].TclError("a widget option")
    gui.App = app
    monkeypatch.setattr(winenv, "is_windows", lambda: False)
    monkeypatch.setattr(winenv, "set_dpi_awareness", lambda: None)
    monkeypatch.setattr(crashlog, "arm_native", lambda: None)
    monkeypatch.setattr(cli, "is_frozen", lambda: False)
    monkeypatch.setattr(cli, "_window_did_not_open",
                        lambda exc: failed.append(type(exc).__name__) or exitcodes.RUNTIME)
    monkeypatch.setattr(linuxenv, "take_desktop", lambda: taken.append("taken") or [])
    monkeypatch.setitem(sys.modules, "tkinter", _fake_tk(tk_fails))
    monkeypatch.setitem(sys.modules, "beantester.gui", gui)
    return failed, taken


def test_the_window_waits_for_the_copy_and_opens_here_only_when_it_did_not_run(monkeypatch):
    _failed, taken = _gui(monkeypatch, tk_fails=False)
    asked = []
    monkeypatch.setattr(linuxenv, "wants_root", lambda: True)
    monkeypatch.setattr(linuxenv, "ask_for_root", lambda argv: asked.append(argv) or 7)
    check("the copy ran: its code, no window here", cli._run_gui(["--gui"]) == 7
          and asked == [["--gui"]] and not taken, f"({asked}, {taken})")
    monkeypatch.setattr(linuxenv, "ask_for_root", lambda argv: None)
    check("it did not run: the window opens here", cli._run_gui([]) == exitcodes.OK)
    check("and the screen is taken before Tk (a no-op outside pkexec's copy)",
          taken == ["taken"], f"({taken})")
    monkeypatch.setattr(linuxenv, "wants_root", lambda: False)
    monkeypatch.setattr(linuxenv, "ask_for_root", lambda argv: asked.append("asked") or 7)
    asked.clear()
    check("nothing to ask: nothing asked", cli._run_gui([]) == exitcodes.OK and not asked)


def test_a_copy_that_cannot_reach_the_screen_hands_the_window_back(monkeypatch):
    failed, _taken = _gui(monkeypatch, tk_fails=True)
    monkeypatch.setattr(linuxenv, "wants_root", lambda: False)
    monkeypatch.setattr(linuxenv, "started_by_pkexec", lambda: True)
    check("pkexec's copy without a screen: pkexec's own 'did not run'",
          cli._run_gui([]) == linuxenv.NO_WINDOW == 127)
    check("and it still says why", failed == ["TclError"], f"({failed})")
    monkeypatch.setattr(linuxenv, "started_by_pkexec", lambda: False)
    check("a window that cannot open anywhere else: as before",
          cli._run_gui([]) == exitcodes.RUNTIME)
    _gui(monkeypatch, tk_fails=False, app_fails=True)
    monkeypatch.setattr(linuxenv, "started_by_pkexec", lambda: True)
    check("a fault in the window itself is not handed back", cli._run_gui([]) == exitcodes.RUNTIME)


# -- the frozen build's library path ---------------------------------------------- #
def test_the_programs_the_package_starts_get_the_persons_library_path(monkeypatch):
    """The bootloader points LD_LIBRARY_PATH at the bundle; a system program that
    inherits it loads the bundle's older libraries and stops (measured 2026-10-28:
    "fc-match: symbol lookup error" on Ubuntu 26.04, Fedora 44 and Arch). The value
    the person had comes back, or none when they had none."""
    monkeypatch.setattr(linuxenv, "is_linux", lambda: True)
    monkeypatch.setattr(winenv, "is_frozen", lambda: True)
    env = {"LD_LIBRARY_PATH": "/b/_internal", "LD_LIBRARY_PATH_ORIG": "/opt/cuda/lib64", "X": "1"}
    check("their own value back", linuxenv.restore_library_path(env) is True
          and env == {"LD_LIBRARY_PATH": "/opt/cuda/lib64", "X": "1"}, f"({env})")
    env = {"LD_LIBRARY_PATH": "/b/_internal", "X": "1"}
    linuxenv.restore_library_path(env)
    check("none of their own: none at all", env == {"X": "1"}, f"({env})")
    env = {"LD_LIBRARY_PATH": "/b/_internal", "LD_LIBRARY_PATH_ORIG": ""}
    linuxenv.restore_library_path(env)
    check("an empty one is none (an empty entry would mean the working folder)", env == {},
          f"({env})")


def test_from_sources_and_on_windows_the_library_path_is_left_alone(monkeypatch):
    for linux, frozen in ((True, False), (False, True)):
        monkeypatch.setattr(linuxenv, "is_linux", lambda linux=linux: linux)
        monkeypatch.setattr(winenv, "is_frozen", lambda frozen=frozen: frozen)
        env = {"LD_LIBRARY_PATH": "/u/ana/lib", "LD_LIBRARY_PATH_ORIG": "/x"}
        check(f"linux={linux}, frozen={frozen}: untouched",
              linuxenv.restore_library_path(env) is False
              and env == {"LD_LIBRARY_PATH": "/u/ana/lib", "LD_LIBRARY_PATH_ORIG": "/x"})


def test_the_library_path_is_restored_before_the_program_does_anything(monkeypatch):
    done = []
    monkeypatch.setattr(crashlog, "install", lambda: done.append("crashlog"))
    monkeypatch.setattr(linuxenv, "restore_library_path", lambda: done.append("library path"))
    monkeypatch.setattr(cli, "run_cli", lambda argv: done.append("cli") or 0)
    monkeypatch.setattr(cli, "_run_gui", lambda argv, relaunched: done.append("gui") or 0)
    cli.main(["--version"])
    cli.main([])
    check("before the command line and before the window",
          done == ["crashlog", "library path", "cli", "crashlog", "library path", "gui"], f"({done})")
