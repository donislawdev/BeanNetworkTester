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
from source_imports import internal_imports as _internal_imports
from source_imports import package_modules as _package_modules


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


# The logic behind the Tools tab. It exists as its own package so that a tool's
# answer is computed once, below the window, and a command-line form of the same
# tool (costed, not built) could call it - both break the day a module in here
# reaches up. LAZY imports count too, unlike the checks above: "not at load" is
# the rule for the CLI launching the GUI, while this package must not know the
# window exists at all.
NETTOOLS_MAY_NOT_REACH = ("gui", "engine", "cli")


def _nettools_violations(path):
    """Upward imports of one file, eager or lazy, plus any tkinter import at all."""
    eager, lazy = _internal_imports(path)
    upward = sorted(m for m in eager | lazy
                    if m.split("/")[0] in NETTOOLS_MAY_NOT_REACH)
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                 else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        upward += [n for n in names if n.split(".")[0] == "tkinter"]
    return upward


def test_nettools_never_reaches_up_into_the_window():
    files = sorted(glob.glob(os.path.join(ROOT, "beantester", "nettools", "*.py")))
    check("the nettools package was found", len(files) >= 2, f"({files})")
    offenders = {os.path.relpath(p, ROOT): v for p in files
                 if (v := _nettools_violations(p))}
    check("nettools imports no gui/engine/cli and no tkinter, even lazily",
          not offenders, f"({offenders})")
    # The canary: the same check on a file that DOES reach into the window must
    # say so, or an extractor that resolves nothing would pass everything above.
    # One assertion per half - the page imports tkinter as well, and that alone
    # kept a single "anything found?" green while the gui/ half saw nothing.
    page = os.path.join(ROOT, "beantester", "gui", "pages", "toolbox.py")
    seen = _nettools_violations(page)
    check("the check resolves an upward import of the package",
          any(v.split("/")[0] == "gui" for v in seen), f"({seen})")
    check("the check sees a tkinter import",
          any(v.split(".")[0] == "tkinter" for v in seen), f"({seen})")


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


# --------------------------------------------------------------------------- #
# Cycles. The four checks above pin the DIRECTION between four named layers; none
# of them can see a loop, and a loop is the other way a dependency graph stops
# being a graph anybody can reason about. Added 2026-09-06 after an audit measured
# both numbers for the first time: zero at module load, two behind lazy imports.
#
# 🔴 The zero is the point. It has held on its own through five releases and 68
# modules, and nothing was watching it - the first import cycle would have been
# found by whoever hit the ImportError, which on this package means at GUI start
# in a frozen build. A guard costs nothing while nothing loops.
# --------------------------------------------------------------------------- #

# The lazy cycles that exist today, each with the reason it is allowed. A NEW one
# reddens this test, which is the whole point: a lazy import is invisible to every
# other check in this file, so a loop hidden behind one can be built by accident
# and stays working right up until somebody hoists the import to the top of its
# file for tidiness.
KNOWN_LAZY_CYCLES = {
    frozenset({"appinfo", "crashlog", "paths"}):
        "paths needs TOOL_ID to build the user data directory and appinfo needs "
        "resource_path to find its own files, so one of the two has to defer - "
        "the reason is written at paths.py's lazy import. crashlog sits in the "
        "same knot because it writes THROUGH paths and stamps records with the "
        "version from appinfo.",
    frozenset({"", "cli", "gui"}):
        "the launch path, and deliberate: cli.main starts the GUI through a lazy "
        "import so that `import beantester` never pulls in tkinter (the test "
        "above is the other half of that rule), and gui reaches back into the "
        "package facade for the public names.",
}


def _cycles(graph):
    """Strongly connected components with more than one member.

    Iterative rather than recursive: this walks 68 modules today and a recursive
    Tarjan would be one deep subpackage away from the interpreter's limit.
    """
    index, low, stack, on_stack, found, counter = {}, {}, [], set(), [], [0]

    def connect(root):
        work = [(root, iter(graph.get(root, ())))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            descended = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter[0]
                    counter[0] += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(graph.get(child, ()))))
                    descended = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            if descended:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                found.append(component)

    for node in graph:
        if node not in index:
            connect(node)
    return [frozenset(c) for c in found if len(c) > 1]


def _graphs():
    eager, combined = {}, {}
    for name, path in _package_modules().items():
        at_load, deferred = _internal_imports(path)
        eager[name] = at_load
        combined[name] = at_load | deferred
    return eager, combined


def test_the_package_has_no_import_cycle_at_module_load():
    """Zero, and it has been zero for five releases with nothing watching it."""
    eager, _ = _graphs()
    check("the import scan actually read the package (an empty graph passes)",
          sum(len(v) for v in eager.values()) > 50,
          f"({sum(len(v) for v in eager.values())} edges)")
    loops = _cycles(eager)
    check("no module-load import cycle",
          not loops,
          f"({[sorted(c) for c in loops]} - an eager loop is an ImportError "
          "waiting for whichever module happens to be imported first)")


def test_every_lazy_import_cycle_is_one_this_file_knows_about():
    """The half no other check here can see - see KNOWN_LAZY_CYCLES.

    A lazy import creates no load-time edge, so the four direction checks above
    pass straight through it. That is right for what they measure and wrong as a
    complete picture: the loop is still there, and the day somebody moves the
    import to the top of the file for tidiness it becomes an ImportError.
    """
    _, combined = _graphs()
    loops = set(_cycles(combined))
    known = set(KNOWN_LAZY_CYCLES)
    check("the lazy graph is not empty (an empty scan passes everything)",
          loops, "(no cycle found at all - the scan probably broke)")
    new = sorted(sorted(c) for c in loops - known)
    check("no lazy import cycle without a declared reason", not new,
          f"({new} - add it to KNOWN_LAZY_CYCLES with the reason, or break it)")
    gone = sorted(sorted(c) for c in known - loops)
    check("a cycle that was broken is removed from the list as well", not gone,
          f"({gone} - the knot is gone, so its entry is now a stale excuse)")
