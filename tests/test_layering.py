"""Layering guard: enforce the allowed dependency direction.

Allowed direction (nothing points back up):

    utils -> core -> engine -> cli / gui

Invariants pinned here (all true today; keep them true):

* ``core`` stays pure: among internal modules it may import only ``utils`` and
  ``matchers`` (its decision leaf deps). It must never reach up to ``settings``,
  ``engine``, ``cli`` or ``gui``.
* ``engine`` never imports ``gui`` or ``cli``.
* No top-level (non-gui) module imports ``gui`` at module load. ``cli`` may launch
  the GUI, but only through a lazy import inside a function.
* ``tkinter`` is never imported at module load outside ``gui/`` (lazy imports
  inside functions are fine - that is how ``cli`` and ``legal`` probe for Tk).

Lazy imports (inside a function body) are intentionally ignored: they do not
create a load-time dependency, so they do not pull tkinter into ``import
beantester`` and do not form an import cycle.
"""
import ast
import glob
import os

from fakes import ROOT, check


def _module_level(path):
    """Return (internal_module_names, imports_tkinter_at_load) for one file.

    Only imports that run at module load count: anything nested inside a
    function/method definition is skipped on purpose.
    """
    tree = ast.parse(open(path, encoding="utf-8").read())
    intra = set()
    tk = [False]

    def add(dotted):
        parts = dotted.split(".")
        if parts[0] == "beantester" and len(parts) > 1:
            intra.add(parts[1])

    def walk(nodes):
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue  # lazy imports inside functions are allowed
            if isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.split(".")[0] == "tkinter":
                        tk[0] = True
                    add(a.name)
            elif isinstance(n, ast.ImportFrom):
                mod = n.module or ""
                if mod.split(".")[0] == "tkinter":
                    tk[0] = True
                if n.level > 0:
                    if mod:
                        add("beantester." + mod)
                    else:
                        for a in n.names:
                            intra.add(a.name)  # from . import core, engine
                elif mod.startswith("beantester"):
                    add(mod)
            for attr in ("body", "orelse", "finalbody"):
                child = getattr(n, attr, None)
                if isinstance(child, list):
                    walk(child)
            if isinstance(n, ast.Try):
                for h in n.handlers:
                    walk(h.body)

    walk(tree.body)
    return intra, tk[0]


def _pkg_file(name):
    return os.path.join(ROOT, "beantester", name)


def _top_level_modules():
    return glob.glob(os.path.join(ROOT, "beantester", "*.py"))


def test_core_stays_pure():
    intra, _ = _module_level(_pkg_file("core.py"))
    allowed = {"utils", "matchers"}
    check("core.py imports only utils/matchers internally",
          intra <= allowed, f"(also imports {sorted(intra - allowed)})")


def test_engine_never_imports_gui_or_cli():
    intra, _ = _module_level(_pkg_file("engine.py"))
    check("engine.py does not import gui/cli",
          not (intra & {"gui", "cli", "app"}),
          f"({sorted(intra & {'gui', 'cli', 'app'})})")


def test_gui_not_imported_at_module_load_outside_gui():
    offenders = []
    for path in _top_level_modules():
        intra, _ = _module_level(path)
        if "gui" in intra:
            offenders.append(os.path.basename(path))
    check("no top-level module imports gui at load (cli launches it lazily)",
          not offenders, f"({offenders})")


def test_tkinter_never_imported_at_module_load_outside_gui():
    offenders = []
    for path in glob.glob(os.path.join(ROOT, "beantester", "**", "*.py"),
                          recursive=True):
        if os.sep + "gui" + os.sep in path:
            continue  # gui/ is the tkinter layer
        _, tk = _module_level(path)
        if tk:
            offenders.append(os.path.relpath(path, ROOT))
    check("tkinter is only imported lazily outside gui/",
          not offenders, f"({offenders})")
