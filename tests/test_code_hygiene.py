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
import re

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


# -- code nothing calls any more ------------------------------------------------- #
#
# 🔴 An ALLOW-list of trees, never a deny-list, and that is the whole safety
# argument. `internal_tools/`, `.claude/` and `crashes/` exist on the maintainer's
# machine and in no checkout, so a scan that walked ROOT would find a name USED
# here (a rig names it) and DEAD in CI - green locally, red on the pull request,
# over a difference nobody can see from the diff. Naming the trees that are
# actually in the repository makes that impossible instead of merely guarded
# against. Measured 2026-08-21: no name in the package is used only from a rig
# today, so this costs nothing now and stops costing something later.
USAGE_TREES = ("beantester", "tests", "tools", "lang", "scenarios")
USAGE_FILES = ("bean_network_tester.py", "smoke_gui.py", "build.py",
               "BeanNetworkTester.spec")
USAGE_EXTS = (".py", ".json", ".spec")
WALK_SKIP = {"__pycache__", "build", "dist"}

# 🔴 EVERY WORD COUNTS, including one inside a comment or a string, and that is a
# MEASUREMENT rather than a preference. Counting only code tokens finds six more
# names here and five of them are alive: `reset_ui_layout`, `_settle_transition`,
# `show_info` and `sync` are called from inside `run_gui("""...""")` blocks - the
# GUI tests are Python source in a string, executed in a subprocess, and the suite
# holds 204 of those calls - while `on_pref_changed` is reached through
# `getattr(page, "on_pref_changed", None)`. A guard that accuses living code is a
# guard people learn to ignore, so this one errs the other way.
#
# The price is real and is named here rather than discovered later: a definition
# whose name is an ordinary English word survives on prose alone. `PortTable.age`
# did exactly that and had to be found by hand. What this catches is an abandoned
# helper with a distinctive name; it is not a substitute for reading.
#
# Same trade in the other direction: names are matched as WORDS, not resolved, so
# two classes with a `close()` share one answer. Fewer false alarms, more misses.
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# A decorator that hands the object to a registry IS a call site, just not a
# visible one. Written as the exact names rather than a substring match, so a
# future `@register_anything` cannot quietly become a way out of this guard.
REGISTERED_BY = {"register_window"}

# 🔴 Unreferenced ON PURPOSE, each with the reason it stays. A RATCHET: it may
# shrink and may not grow without somebody deciding that it should - a list that
# absorbs whatever the scan finds is not a guard, it is a place to put things.
KNOWN_UNUSED = {
    "ui_scale": "the getter paired with set_scale(), which IS used (init_scaling); "
                "PROJECT_NOTES lists it as part of the scaling surface",
    "make_scrollable": "the compatibility alias the notes say stays. Deleting it is "
                       "a decision about that promise, not about this scan",
    "get_field": "an OVERRIDE of string.Formatter.get_field - the base class calls "
                 "it, so no line in this package ever names it. Deleting it would "
                 "restore attribute access inside translation templates",
}


def _package_definitions():
    """Every function and class in the package: name, file, line, end, decorators."""
    out = []
    for path in _pkg_files():
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        for node in ast.walk(ast.parse(open(path, encoding="utf-8").read())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.append((node.name, rel, node.lineno, node.end_lineno or node.lineno,
                            [ast.unparse(d) for d in node.decorator_list]))
    return out


def _usage_files():
    """Every file in the repository that could legitimately name a symbol.

    🔴 EXCEPT THIS ONE, and it is not an optimisation: `KNOWN_UNUSED` lives here,
    so a name written into the exception list would be a mention of itself and the
    scan would report it as used. The guard would disarm itself in the act of
    recording an exception - and the two entries in that list are exactly the
    names it would stop watching. Measured: removing this file from the scan
    changes nothing else, the same 1003 definitions minus those two.
    """
    mine = os.path.abspath(__file__)
    out = []
    for tree in USAGE_TREES:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, tree)):
            dirnames[:] = [d for d in dirnames if d not in WALK_SKIP]
            out += [os.path.join(dirpath, n) for n in filenames
                    if n.endswith(USAGE_EXTS)]
    out += [os.path.join(ROOT, n) for n in USAGE_FILES]
    return [p for p in out
            if os.path.isfile(p) and os.path.abspath(p) != mine]


def _unreferenced():
    """(unreferenced definitions, files read, definitions seen), to a FIXED POINT.

    Iterated rather than counted once, because a dead caller keeps its callee
    looking alive: `BeanCore.in_scope` had exactly one caller in the whole tree and
    that caller was `BeanEngine.in_scope_now`, which nothing called either. One
    pass sees a name mentioned twice and calls it used.
    """
    definitions = _package_definitions()
    names = {name for name, *_ in definitions}
    spans = {}
    for name, rel, line, end, _decorators in definitions:
        spans.setdefault(rel, []).append((line, end, (name, rel, line)))

    def enclosing(rel, number):
        """The innermost definition containing this line, or None."""
        best = None
        for start, end, key in spans.get(rel, ()):
            if start <= number <= end and (best is None or start >= best[2]):
                best = key
        return best

    mentions, files = {}, 0
    for path in _usage_files():
        files += 1
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        in_package = rel.startswith("beantester/")
        try:
            text = open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            found = [w for w in _WORD.findall(line) if w in names]
            if not found:
                continue
            site = enclosing(rel, number) if in_package else None
            for word in found:
                mentions.setdefault(word, set()).add(site or "EXTERNAL")

    dead = set()
    while True:
        grew = False
        for name, rel, line, _end, decorators in definitions:
            key = (name, rel, line)
            if key in dead or (name.startswith("__") and name.endswith("__")):
                continue
            if any(d in REGISTERED_BY for d in decorators):
                continue
            # A mention from a dead site is not life, and neither is a function
            # naming itself - recursion keeps nothing alive.
            living = [s for s in mentions.get(name, ())
                      if s == "EXTERNAL" or (s not in dead and s != key)]
            if not living:
                dead.add(key)
                grew = True
        if not grew:
            return sorted(dead), files, len(definitions)


def test_no_definition_in_the_package_is_unreferenced():
    """Nothing in the package is left over from a change that moved on without it.

    Nobody reads this code line by line. A helper written in one session and
    superseded in the next keeps compiling, keeps passing, keeps being read as
    something that matters - and the only thing that notices is a scan.
    """
    dead, files, definitions = _unreferenced()

    # The canary this file's neighbours all carry: a scan that reads nothing finds
    # no dead code and looks exactly like a scan that works.
    check("the dead-code scan actually read the repository",
          files >= 100 and definitions >= 500,
          f"({files} files, {definitions} definitions)")

    unexpected = [f"{name} ({rel}:{line})" for name, rel, line in dead
                  if name not in KNOWN_UNUSED]
    check("every definition in the package is named from somewhere that is alive",
          not unexpected,
          f"({unexpected} - delete it, or add it to KNOWN_UNUSED with the reason)")


def test_the_known_unused_list_only_ever_shrinks():
    """A name that got a caller back must LEAVE the list, or the list rots.

    Without this, an exception written once outlives its reason and the next
    session reads it as a rule. Same shape as every other ratchet here: the cheap
    direction is free, the other one is a decision.
    """
    dead, _files, _definitions = _unreferenced()
    still_dead = {name for name, _rel, _line in dead}
    revived = sorted(name for name in KNOWN_UNUSED if name not in still_dead)
    check("no name on the exception list has quietly gained a caller", not revived,
          f"({revived} - it is used again, so take it out of KNOWN_UNUSED)")
