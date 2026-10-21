"""A run under ``sudo`` hands its files back to the person who ran it (``paths``).

MEASURED 2026-10-20 on Ubuntu 26.04: a window started with sudo wrote
``bean_network_tester_ui.json`` as root, mode 0600, into the person's own folder;
their next start without sudo could not read it and set it aside as corrupt. The
same run, saving over a file of theirs, would take that one too - ``os.replace``
puts root's temp file in its place. And its GitHub button logged "opened" while no
browser opened.

Everything here runs on any runner: the effective user, sudo's variables, a
directory's owner and ``os.chown`` are stood in for. The last tests hold every
place in the package that makes a file or a directory to the rule, so the next
writer cannot forget it in silence.
"""
import ast
import os
import sys
import types

import pytest

from beantester import jsonfile, paths
from fakes import ROOT, check


class _Owned:
    """A real ``os.stat`` result with the owner this test says (``st_uid``)."""

    def __init__(self, result, uid):
        self._result, self.st_uid = result, uid

    def __getattr__(self, name):
        return getattr(self._result, name)


def _become_sudo(monkeypatch):
    """A Linux root process started by uid/gid 1000 through sudo. Returns what was
    chowned, ``followed`` - whether each chown would follow a link - and ``owners`` -
    path -> uid, the owner ``os.stat`` reports; a chown moves it, the way the real
    one would."""
    chowned, followed, owners = [], [], {}
    real_stat = os.stat

    def fake_stat(path, *a, **k):
        result = real_stat(path, *a, **k)
        key = os.path.abspath(path)
        return _Owned(result, owners[key]) if key in owners else result

    def fake_chown(path, uid, gid, *, follow_symlinks=True):
        chowned.append((os.path.abspath(path), uid, gid))
        followed.append(follow_symlinks)
        owners[os.path.abspath(path)] = uid

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(os, "chown", fake_chown, raising=False)
    monkeypatch.setattr(os, "stat", fake_stat)
    monkeypatch.setenv("SUDO_UID", "1000")
    monkeypatch.setenv("SUDO_GID", "1000")
    return types.SimpleNamespace(chowned=chowned, followed=followed, owners=owners)


@pytest.fixture
def sudo(monkeypatch):
    return _become_sudo(monkeypatch)


def test_who_ran_it_is_read_from_sudo_and_only_by_root(monkeypatch, sudo):
    check("root through sudo", paths.invoking_user() == (1000, 1000))
    check("is root", paths.running_as_root() is True)
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    check("not root: nobody to hand anything to", paths.invoking_user() is None)
    check("is not root", paths.running_as_root() is False)
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.delenv("SUDO_GID")
    check("root, but sudo did not say who", paths.invoking_user() is None)
    check("root all the same", paths.running_as_root() is True)
    monkeypatch.setenv("SUDO_GID", "x")
    check("or said it in a way that is not a number", paths.invoking_user() is None)
    monkeypatch.setattr(sys, "platform", "win32")
    check("Windows: never", paths.invoking_user() is None)
    check("Windows: never root", paths.running_as_root() is False)


def test_a_file_is_handed_back_only_inside_the_persons_own_directory(tmp_path, sudo):
    mine, roots = tmp_path / "mine", tmp_path / "roots"
    mine.mkdir()
    roots.mkdir()
    sudo.owners[str(mine)], sudo.owners[str(roots)] = 1000, 0
    check("in their folder", paths.hand_back(str(mine / "ui.json")) is True)
    check("in root's own place it stays root's", paths.hand_back(str(roots / "x.json")) is False)
    check("one change of owner, to them", sudo.chowned == [(str(mine / "ui.json"), 1000, 1000)],
          f"({sudo.chowned})")
    # They own the folder, so they can put a link where the file was before the chown
    # runs: a chown that followed it would give them whatever the link points at.
    check("the entry itself, never what a link there points at", sudo.followed == [False],
          f"({sudo.followed})")


def test_a_failed_change_of_owner_is_never_a_failure_of_the_write(monkeypatch, tmp_path, sudo):
    sudo.owners[str(tmp_path)] = 1000

    def refuse(*_a, **_k):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(os, "chown", refuse, raising=False)
    check("answered, not raised", paths.hand_back(str(tmp_path / "f")) is False)


def test_nothing_changes_hands_without_sudo(monkeypatch, tmp_path, sudo):
    sudo.owners[str(tmp_path)] = 1000
    monkeypatch.delenv("SUDO_UID")
    check("root without sudo", paths.hand_back(str(tmp_path / "f")) is False)
    monkeypatch.setattr(sys, "platform", "win32")
    check("Windows", paths.hand_back(str(tmp_path / "f")) is False)
    check("nothing was chowned", sudo.chowned == [])


def test_make_dirs_hands_back_only_the_levels_it_created_top_down(tmp_path, sudo):
    existing = tmp_path / "home"
    existing.mkdir()
    sudo.owners[str(existing)] = 1000
    target = existing / "data" / "crashes"
    data = existing / "data"
    # each new level is theirs once handed back - which is what lets the next one go
    paths.make_dirs(str(target))
    check("both levels exist", target.is_dir())
    got = [p for p, _u, _g in sudo.chowned]
    check("the new levels, the outer one first, and not the one that was there",
          got == [str(data), str(target)], f"({got})")
    sudo.chowned.clear()
    paths.make_dirs(str(target))
    check("a directory that is there keeps its owner", sudo.chowned == [], f"({sudo.chowned})")


def test_every_atomic_write_publishes_a_file_that_is_theirs(tmp_path, sudo):
    """``temp_beside`` is the one door: ``write_json`` (profiles, ui.json, configs),
    the repro report and the crash files all go through it."""
    sudo.owners[str(tmp_path)] = 1000
    target = tmp_path / "bean_network_tester_ui.json"
    check("written", jsonfile.write_json(str(target), {"a": 1}) is None)
    check("the file is there", target.is_file())
    handed = [p for p, _u, _g in sudo.chowned]
    check("its temp file was handed back before it took the target's place",
          len(handed) == 1 and os.path.dirname(handed[0]) == str(tmp_path)
          and os.path.basename(handed[0]).startswith(target.name + "."), f"({handed})")


def test_the_page_buttons_start_no_browser_as_root(monkeypatch):
    pytest.importorskip("tkinter")
    from beantester.gui import links           # imported as itself, before the stand-ins
    from beantester.i18n import T
    _become_sudo(monkeypatch)
    opened, lines = [], []
    monkeypatch.setattr(links.webbrowser, "open_new_tab", lambda url: opened.append(url) or True)
    check("under sudo: not opened", links.open_page(links.GITHUB, lines.append) is False)
    check("no browser was asked", opened == [])
    check("the log says why, with the address",
          lines == [f"{T('log.page_open_yourself')}: {links.GITHUB.url}"], f"({lines})")
    monkeypatch.delenv("SUDO_UID")
    lines.clear()
    check("root without sudo (su, doas, a root login): not opened either",
          links.open_page(links.GITHUB, lines.append) is False and opened == [], f"({opened})")
    check("and the log says why", lines == [f"{T('log.page_open_yourself')}: {links.GITHUB.url}"],
          f"({lines})")
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    lines.clear()
    check("not root: the browser, as before", links.open_page(links.GITHUB, lines.append)
          is True and opened == [links.GITHUB.url], f"({opened})")


# -- every place that makes a file or a directory ----------------------------------- #
# What may create one without handing it back, and why. Everything else that opens a
# file for writing, makes a directory or a temp file must be in a function that calls
# hand_back, make_dirs or temp_beside.
CREATES_WITHOUT_HANDING_BACK = {
    ("beantester/paths.py", "directory_is_writable"): "a probe file, removed at once",
    ("beantester/winenv.py", "detach_console"): "os.devnull",
    ("beantester/paths.py", "make_dirs"): "the helper itself (hands back each level)",
}
HANDS_BACK = {"hand_back", "make_dirs", "temp_beside"}
_WRITE_MODES = set("wax+")


def _creates(call):
    """What this call creates - ``"open"``, ``"dir"``, ``"temp"`` - or ``None``."""
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name == "open" and not (isinstance(func, ast.Attribute)
                               and getattr(func.value, "id", "") not in ("io", "codecs")):
        mode = call.args[1] if len(call.args) >= 2 else next(
            (k.value for k in call.keywords if k.arg == "mode"), None)
        if mode is None:
            return None                                       # read
        if not isinstance(mode, ast.Constant):
            return "open"                                     # a mode we cannot read: count it
        return "open" if set(str(mode.value)) & _WRITE_MODES else None
    if name in ("makedirs", "mkdir"):
        return "dir"
    if name in ("mkstemp", "mkdtemp", "NamedTemporaryFile", "write_text", "write_bytes"):
        return "temp"
    return None


_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _name(call):
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _unhanded(source, rel):
    """``(function, line, what)`` for each creating call whose function never hands back.

    A function answers for its OWN calls: those of a function nested in it are left
    out on both sides - what it creates, and the hand_back that would excuse it.
    The nested one is walked as a function of its own.
    """
    tree = ast.parse(source)
    found = []
    for func in ast.walk(tree):
        if not isinstance(func, _FUNCTIONS):
            continue
        inner = {id(n) for f in ast.walk(func) if f is not func
                 and isinstance(f, _FUNCTIONS) for n in ast.walk(f)}
        calls = [n for n in ast.walk(func) if isinstance(n, ast.Call) and id(n) not in inner]
        what = [(c.lineno, _creates(c)) for c in calls if _creates(c)]
        if not what or (rel, func.name) in CREATES_WITHOUT_HANDING_BACK:
            continue
        if HANDS_BACK & {_name(c) for c in calls}:
            continue
        found.extend((func.name, line, kind) for line, kind in what)
    return found


def _stale(exceptions, root=ROOT):
    """The exceptions that no longer name a function defined in their file."""
    stale = []
    for rel, function in exceptions:
        path = os.path.join(root, rel)
        defined = os.path.isfile(path) and any(
            isinstance(n, _FUNCTIONS) and n.name == function
            for n in ast.walk(ast.parse(_read(path))))
        if not defined:
            stale.append((rel, function))
    return stale


def test_every_place_that_makes_a_file_hands_it_back():
    seen, bad = 0, []
    for folder, _dirs, files in os.walk(os.path.join(ROOT, "beantester")):
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(folder, name)
                rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                source = _read(path)
                seen += sum(1 for n in ast.walk(ast.parse(source))
                            if isinstance(n, ast.Call) and _creates(n))
                bad.extend(f"{rel}:{line} {func} ({kind})" for func, line, kind in _unhanded(source, rel))
    check("the scan sees the places it is about", seen >= 12, f"({seen})")
    check("every one hands back what it makes, or says why it need not",
          not bad, f"({bad} - call paths.hand_back / make_dirs, write through temp_beside, or "
                   f"list it in CREATES_WITHOUT_HANDING_BACK with the reason)")
    # A renamed or removed function would leave its exception behind, ready to excuse
    # the next function that takes the old name - so the name must still be defined.
    stale = _stale(CREATES_WITHOUT_HANDING_BACK)
    check("no stale exception", not stale, f"({stale})")


def test_the_scan_for_files_made_can_fail():
    """The canary: each shape a writer takes is seen, and one that hands back is not."""
    shapes = {
        "open w": "def f(p):\n    with open(p, 'w') as h:\n        h.write('x')\n",
        "open a, mode=": "def f(p):\n    open(p, mode='a').close()\n",
        "makedirs": "import os\ndef f(p):\n    os.makedirs(p, exist_ok=True)\n",
        "mkstemp": "import tempfile\ndef f(d):\n    return tempfile.mkstemp(dir=d)\n",
        "a nested hand_back does not cover the outer open":
            "def f(p):\n    open(p, 'w').close()\n    def g(q):\n        hand_back(q)\n",
    }
    for name, code in shapes.items():
        check(f"{name} is seen", _unhanded(code, "beantester/x.py") != [], f"({name})")
    check("an exception whose function is gone is stale",
          _stale({("beantester/paths.py", "no_such_function"): ""})
          == [("beantester/paths.py", "no_such_function")])
    check("so is one whose file is gone",
          _stale({("beantester/no_such_file.py", "f"): ""}) == [("beantester/no_such_file.py", "f")])
    check("one that names a function there is not",
          _stale({("beantester/paths.py", "make_dirs"): ""}) == [])
    quiet = {
        "read": "def f(p):\n    return open(p).read()\n",
        "read rb": "def f(p):\n    return open(p, 'rb').read()\n",
        "handed back": "def f(p):\n    open(p, 'a').close()\n    hand_back(p)\n",
        "through temp_beside": "def f(p):\n    t = temp_beside(p)\n    open(t, 'w').close()\n",
    }
    for name, code in quiet.items():
        check(f"{name} is fine", _unhanded(code, "beantester/x.py") == [], f"({name})")
