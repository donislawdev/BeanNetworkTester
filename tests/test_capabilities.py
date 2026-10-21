"""``beantester/capabilities.py``: the one answer to "does this system have it".

The gate itself is two lines; what this file holds is the reason it can stay the ONE
reader. Measured on Linux (2026-10-20): Ping that answered every request "failed",
a reset that ended in an ``AttributeError`` recorded as a fault, and an Adapters tab
of two blank tables - three tools that each decided for themselves and got it wrong.
So the checks below are about the next tool more than about these five:

* every module that loads a Windows DLL is either a capability here or listed below
  with the reason it gates itself;
* every tool's ``needs`` names a capability, and the capability modules a tool's
  logic imports are exactly the one its ``needs`` names;
* the answer follows the module at the moment it is asked, so a test standing a
  module's ``supported`` in moves the gate with it.

No window anywhere: the GUI's side (the shared panel, the greyed menu entries) is in
``tests/test_toolbox.py`` and ``tests/test_gui_state.py``.
"""
import ast
import json
import os
import sys

import pytest

from beantester import capabilities, icmp, icmpsock, paths
from fakes import check

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "beantester")

# Modules that load a Windows DLL and are NOT a tool's capability, each with the
# platform gate it carries itself. A new module that loads one goes into the
# registry or here, with its reason - never silently.
GATED_ITSELF = {
    "beantester/winenv.py": "the Windows helpers; every one answers is_windows() first",
    "beantester/driver.py": "the WinDivert driver; is_windows() before every call",
    "beantester/portmap.py": "the socket table; psutil off Windows (_Native is Windows only)",
    "beantester/crashlog.py": "the native crash hook; armed only on a real Windows capture",
    "beantester/gui/theme.py": "the dark title bar; sys.platform checked before uxtheme",
    "beantester/capture_backend.py": "IsUserAnAdmin in the Windows backend, after is_windows()",
}


def _loads_a_windows_dll(path):
    """True when the file calls ``WinDLL(...)`` or touches ``ctypes.windll`` - in CODE,
    not in a comment or a docstring that mentions them."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "WinDLL":
                return True
        if isinstance(node, ast.Attribute) and node.attr == "windll":
            return True
    return False


def _package_files():
    for folder, _dirs, files in os.walk(PACKAGE):
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(folder, name)
                yield os.path.relpath(path, ROOT).replace(os.sep, "/"), path


def _capability_files():
    return {f"beantester/{c.module.__name__.rsplit('.', 1)[1]}.py": name
            for name, c in capabilities.CAPABILITIES.items()}


def _direct_imports(rel):
    """The ``beantester`` modules a file under ``beantester/nettools`` imports by name."""
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    here = rel[:-3].split("/")[:-1]                        # its package, as parts
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        base = here[:len(here) - node.level + 1] if node.level else []
        target = base + (node.module.split(".") if node.module else [])
        if node.module is None:                            # from .. import a, b
            found.update("/".join(target + [alias.name]) + ".py" for alias in node.names)
        else:
            found.add("/".join(target) + ".py")
    return found


def test_every_capability_answers_through_its_module():
    for name, cap in capabilities.CAPABILITIES.items():
        check(f"{name}: the module has supported()", callable(getattr(cap.module, "supported", None)))
        check(f"{name}: the name is the key", cap.name == name, f"({cap.name})")


def test_a_tool_that_needs_nothing_is_always_available_and_a_typo_is_loud():
    check("'' is available", capabilities.available("") is True)
    check("and has nothing to say", capabilities.why_not("") is None)
    with pytest.raises(KeyError):
        capabilities.available("pnig")


def test_the_answer_follows_the_module_when_it_is_asked(monkeypatch):
    # Without words of its own (Ping has them on Linux: the test after the next one).
    monkeypatch.setattr(icmp, "why_not", lambda: None)
    monkeypatch.setattr(icmp, "supported", lambda: True)
    check("a module that says yes", capabilities.available("ping") is True)
    check("nothing to say", capabilities.why_not("ping") is None)
    monkeypatch.setattr(icmp, "supported", lambda: False)
    check("the same module saying no, a moment later", capabilities.available("ping") is False)
    check("and the reason to show", capabilities.why_not("ping") == capabilities.NOT_HERE)


@pytest.mark.parametrize("platform, sockets, ping", [
    ("win32", None, True), ("linux", icmpsock.DGRAM, True), ("linux", icmpsock.RAW, True),
    ("linux", None, False)])
def test_windows_offers_every_capability_and_linux_ping_when_it_may_send(monkeypatch, platform,
                                                                         sockets, ping):
    """The predicates read ``sys.platform`` when asked; every answer on either runner.
    Linux has Ping when this process may open an ICMP socket - ``icmpsock.kind``, stood
    in, because the real one asks this runner's kernel (on Windows it asks Winsock) -
    and none of the rest yet."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(icmpsock, "kind", lambda: sockets)
    got = {name: capabilities.available(name) for name in capabilities.CAPABILITIES}
    windows = platform == "win32"
    want = {name: windows or (name == "ping" and ping) for name in capabilities.CAPABILITIES}
    check(f"{platform}, {sockets}: {want}", got == want, f"({got})")


def test_a_linux_without_the_right_to_ping_says_how_to_get_it(monkeypatch):
    """The module's own words before the shared ones: on Linux "Windows only for now"
    is no longer true of Ping, and the person can do something about it - and as root
    "start it with sudo" would be no advice: the system took CAP_NET_RAW away."""
    monkeypatch.setattr(icmpsock, "kind", lambda: None)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(paths, "running_as_root", lambda: False)
    check("Linux: Ping's own words", capabilities.why_not("ping") == icmp.NOT_HERE_LINUX,
          f"({capabilities.why_not('ping')})")
    check("the others keep the shared ones",
          capabilities.why_not("adapters") == capabilities.NOT_HERE)
    monkeypatch.setattr(paths, "running_as_root", lambda: True)
    check("as root: the words for root", capabilities.why_not("ping") == icmp.NOT_HERE_ROOT,
          f"({capabilities.why_not('ping')})")
    monkeypatch.setattr(sys, "platform", "darwin")
    check("another system: the shared words", capabilities.why_not("ping") == capabilities.NOT_HERE)
    with open(os.path.join(ROOT, "lang", "en.json"), encoding="utf-8") as f:
        texts = json.load(f)
    user, root = texts[icmp.NOT_HERE_LINUX], texts[icmp.NOT_HERE_ROOT]
    check("the user is told what to do", "sudo" in user and "ping_group_range" in user, f"({user})")
    check("root is not told to use sudo, and is told what is missing",
          "sudo" not in root and "CAP_NET_RAW" in root and "ping_group_range" in root, f"({root})")


def test_every_reason_is_said_in_every_language():
    languages = [n for n in os.listdir(os.path.join(ROOT, "lang")) if n.endswith(".json")]
    check("the language files were found", len(languages) >= 3, f"({languages})")
    for name in languages:
        with open(os.path.join(ROOT, "lang", name), encoding="utf-8") as f:
            texts = json.load(f)
        for cap in capabilities.CAPABILITIES.values():
            check(f"{name}: {cap.reason}", bool(texts.get(cap.reason)))


def test_every_module_that_loads_a_windows_dll_is_a_capability_or_gates_itself():
    loads = {rel for rel, path in _package_files() if _loads_a_windows_dll(path)}
    check("the scan sees the modules it is about", "beantester/icmp.py" in loads, f"({sorted(loads)})")
    known = set(_capability_files()) | set(GATED_ITSELF)
    check("no module loads a Windows DLL without a decision here",
          not loads - known, f"({sorted(loads - known)} - add it to capabilities.py, or to "
                             f"GATED_ITSELF with the gate it carries)")
    check("no stale entry", not set(GATED_ITSELF) - loads, f"({sorted(set(GATED_ITSELF) - loads)})")


def test_the_scan_for_windows_dlls_can_fail(tmp_path):
    """The canary: each shape a DLL load takes is seen, and a mention is not."""
    shapes = {"WinDLL": "import ctypes\nctypes.WinDLL('iphlpapi.dll')\n",
              "bare WinDLL": "from ctypes import WinDLL\nWinDLL('x.dll')\n",
              "windll": "import ctypes\nctypes.windll.shell32.IsUserAnAdmin()\n"}
    for name, code in shapes.items():
        path = tmp_path / f"{name.replace(' ', '_')}.py"
        path.write_text(code, encoding="utf-8")
        check(f"{name} is seen", _loads_a_windows_dll(str(path)))
    quiet = tmp_path / "quiet.py"
    quiet.write_text('"""Calls ctypes.WinDLL(...) on Windows."""\n# windll.x\n', encoding="utf-8")
    check("a docstring or a comment is not a load", not _loads_a_windows_dll(str(quiet)))


def test_every_tool_needs_a_real_capability_and_the_one_its_logic_imports():
    from beantester.gui.toolbox import TOOLS
    files = _capability_files()
    for tool in TOOLS:
        check(f"{tool.id}: needs names a capability",
              tool.needs == "" or tool.needs in capabilities.CAPABILITIES, f"({tool.needs!r})")
        logic = f"beantester/nettools/{tool.id}.py"
        check(f"{tool.id}: its logic module exists", os.path.isfile(os.path.join(ROOT, logic)))
        reached = sorted(files[rel] for rel in _direct_imports(logic) if rel in files)
        check(f"{tool.id}: the system API its logic imports is the one it needs",
              reached == ([tool.needs] if tool.needs else []),
              f"(imports {reached}, needs {tool.needs!r})")


def test_the_import_reader_sees_each_form():
    """The canary for the check above: a tool's logic that reaches a capability module
    in any of the three ways a relative import is written."""
    got = _direct_imports("beantester/nettools/ping.py")
    check("from .. import icmp", "beantester/icmp.py" in got, f"({sorted(got)})")
    check("from .adapters import Words", "beantester/nettools/adapters.py" in got)
    got = _direct_imports("beantester/nettools/adapters.py")
    check("from .. import adapters as system", "beantester/adapters.py" in got, f"({sorted(got)})")
