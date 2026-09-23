"""Which package modules a source file imports - read from the source, never by importing it.

Two guards ask this question: ``test_layering.py`` (which way the dependencies
point, and whether they loop) and ``test_no_telemetry.py`` (what the Tools tab
reaches into when it promises to send nothing). One resolver for both, because
the traps below are paid for once and a second copy would have to find them
again.

Module names are package-relative with slashes (``gui/app``, ``driver``); the
package ``__init__`` is ``""``.
"""
import ast
import os

from fakes import ROOT


def _resolve_dotted(dotted, modules):
    """Longest prefix of an absolute `beantester.a.b` name that is a real module."""
    parts = dotted.split(".")
    if parts and parts[0] == "beantester":
        parts = parts[1:]
    candidate = "/".join(parts)
    while candidate:
        if candidate in modules:
            return candidate
        candidate = candidate.rsplit("/", 1)[0] if "/" in candidate else ""
    return None


def _relative_base(node, current, is_package):
    """Package path a `from .x import y` is relative to, as a module path.

    🔴 A package's ``__init__`` IS its package, so its `.` is itself, not its
    parent - `from .diagnostics import X` in ``gui/toolbox/__init__.py`` is
    ``gui/toolbox/diagnostics``. Resolved the other way, five ``__init__`` files
    lost every edge they have, and three pointed at the wrong module
    (``gui/pages -> gui/toolbox``): a real lazy cycle went unseen, and a cycle that
    does not exist was listed in ``test_layering.KNOWN_LAZY_CYCLES`` with a reason
    read off the wrong edge.
    """
    parts = [p for p in current.split("/") if p]
    if not is_package:
        parts = parts[:-1]
    up = node.level - 1
    if up:
        parts = parts[:-up] if up <= len(parts) else []
    if node.module:
        parts = parts + [node.module.replace(".", "/")]
    return "/".join(p for p in parts if p)


def _named_modules(base, aliases, current, modules):
    """The submodules `from <base> import a, b` names, else `base` itself.

    🔴 This is the whole trap. `from . import core` is an edge to the SUBMODULE,
    not to the package's ``__init__``: resolving it the other way reports one
    23-module cycle covering half the package - measured while writing this, and
    convincing, because it looks exactly like the tangle a reader expects to find.
    """
    hits = {(base + "/" + alias.name).strip("/") for alias in aliases}
    hits = {h for h in hits if h in modules and h != current}
    if hits:
        return hits
    return {base} if base in modules and base != current else set()


def _import_targets(node, current, modules, is_package):
    """Internal modules one import statement points at (empty for anything else)."""
    if isinstance(node, ast.Import):
        found = {_resolve_dotted(a.name, modules) for a in node.names}
        return {f for f in found if f is not None and f != current}
    if not isinstance(node, ast.ImportFrom):
        return set()
    if node.level:
        return _named_modules(_relative_base(node, current, is_package), node.names,
                              current, modules)
    if not (node.module or "").startswith("beantester"):
        return set()
    base = _resolve_dotted(node.module, modules)
    return set() if base is None else _named_modules(base, node.names,
                                                     current, modules)


def _statements(nodes):
    """Every statement reachable from `nodes` without entering a function body.

    Yields `(statement, is_lazy)`. A function body is descended into with
    is_lazy=True and never resets: an import three blocks deep inside a method is
    still deferred until that method runs.
    """
    stack = [(node, False) for node in reversed(nodes)]
    while stack:
        node, is_lazy = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack += [(child, True) for child in reversed(node.body)]
            continue
        yield node, is_lazy
        children = []
        for attr in ("body", "orelse", "finalbody"):
            children += getattr(node, attr, None) or []
        for handler in getattr(node, "handlers", None) or []:
            children += handler.body
        stack += [(child, is_lazy) for child in reversed(children)]


def internal_imports(path):
    """(eager, lazy-only) internal module names for one file, at FULL granularity.

    This keeps ``gui/app`` apart from ``gui``: collapsing a subpackage to its top
    name would merge every module under ``gui/`` into one node and hide any loop
    inside it.
    """
    modules = package_modules()
    current = module_name(path)
    is_package = os.path.basename(path) == "__init__.py"
    eager, lazy = set(), set()
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    for node, is_lazy in _statements(tree.body):
        targets = _import_targets(node, current, modules, is_package)
        (lazy if is_lazy else eager).update(targets)
    return eager, lazy - eager


def module_name(path):
    name = os.path.relpath(path, os.path.join(ROOT, "beantester"))
    name = name.replace(os.sep, "/")[: -len(".py")]
    if name.endswith("/__init__"):
        name = name[: -len("/__init__")]
    return "" if name == "__init__" else name


def package_modules():
    """``{module name: path}`` for every module in the package."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "beantester")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                path = os.path.join(dirpath, name)
                out[module_name(path)] = path
    return out
