"""Code-hygiene guards that scale with the codebase.

Two invariants, both true today, both cheap to keep true:

* **No silently swallowed exceptions** (convention 30). ``except ...: pass`` (and
  bare ``except:`` whose body is only ``pass``/``...``) turns a real fault into
  silence - that is how the "target catches nothing" note once vanished. The
  sanctioned replacement is ``crashlog.quiet(...)`` / ``crashlog.once(...)``: the
  user still sees nothing, but the failure stops being invisible.
* **The decision core stays a pure hot path.** ``core.py`` runs ~150k times a
  second; it must not pull in ``logging`` or call ``print`` (both allocate and do
  I/O in the packet path). Tracebacks in the hot path go through
  ``crashlog.once()`` instead.
"""
import ast
import glob
import os

from fakes import ROOT, check


def _pkg_files():
    return glob.glob(os.path.join(ROOT, "beantester", "**", "*.py"), recursive=True)


def _is_trivial_body(body):
    """A handler body that only swallows: a lone ``pass`` or ``...``."""
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, ast.Pass):
        return True
    if (isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is Ellipsis):
        return True
    return False


def test_no_silently_swallowed_exceptions():
    offenders = []
    for path in _pkg_files():
        # crashlog.py IS the sanctioned last-resort sink: if the crash logger
        # itself fails (writing the report, rotating logs, enabling faulthandler)
        # there is nowhere left to report it. Convention 30 allows silence only here.
        if os.path.basename(path) == "crashlog.py":
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and _is_trivial_body(node.body):
                offenders.append(f"{os.path.relpath(path, ROOT)}:{node.lineno}")
    check("no 'except ...: pass' outside crashlog - use crashlog.quiet/once",
          not offenders, f"({offenders})")


def test_core_decision_hot_path_is_pure():
    src = open(os.path.join(ROOT, "beantester", "core.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] == "logging" for a in node.names):
                bad.append(f"import logging (line {node.lineno})")
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "logging":
            bad.append(f"from logging (line {node.lineno})")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "print"):
            bad.append(f"print() (line {node.lineno})")
    check("core.py has no logging/print in the packet hot path",
          not bad, f"({bad})")


def _is_broad_handler(handler):
    """A bare ``except:`` or one catching ``Exception``/``BaseException``."""
    exc = handler.type
    if exc is None:
        return True
    names = exc.elts if isinstance(exc, ast.Tuple) else [exc]
    return any(getattr(n, "id", "") in ("Exception", "BaseException") for n in names)


def _handler_reaches_crashlog_or_reraises(handler):
    """Does the handler record the failure (crashlog) or re-raise it?

    ``crashlog.quiet``/``once``/``note``/``record`` and a bare ``raise`` all count -
    the point of convention 30 is that the fault stops being INVISIBLE, not how.
    """
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Attribute) and node.attr in (
                "quiet", "once", "note", "record"):
            return True
    return False


def test_the_decision_core_never_swallows_an_exception_silently():
    """core.py is the pure decision hot path: EVERY broad ``except`` there must
    route the fault to ``crashlog`` (or re-raise) - never ``return``/assign its way
    to silence.

    The general guard above only recognises a ``pass``/``...`` body, so a handler
    that swallowed via ``return False`` passed it - which is exactly how a silent
    ``except Exception: return False`` lived in ``corrupt_packet`` (finding F3): a
    real fault (a raising payload setter) read as "0 corrupted", indistinguishable
    from "no payloads", and got blamed on the traffic instead of the tool.

    The wider package is deliberately NOT held to this: most of its broad handlers
    are legitimate control-flow fallbacks (a parse that returns ``None`` on bad
    input, ``matches()`` returning ``False`` in the packet path by contract, a DPI
    probe falling back to a default). In the DECISION CORE there is no such case -
    a swallowed exception is always a hidden bug - so the rule can be absolute here.
    """
    src = open(os.path.join(ROOT, "beantester", "core.py"), encoding="utf-8").read()
    offenders = []
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.ExceptHandler) and _is_broad_handler(node)
                and not _handler_reaches_crashlog_or_reraises(node)):
            offenders.append(f"core.py:{node.lineno}")
    check("core.py routes every broad except to crashlog or re-raises (never silent)",
          not offenders, f"({offenders})")
