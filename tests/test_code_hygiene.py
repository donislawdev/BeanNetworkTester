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
# 🔴 ...but a mention from the TEST tree is not LIFE. The trees above decide what
# gets READ. This decides what counts as a consumer, and they are different
# questions. A definition whose only callers are its own tests is dead code with a
# test suite attached: it passes, it reads as maintained, and nothing in the
# program would notice if it vanished.
#
# MEASURED, and it is why this line exists: `views.SearchIndex` was ~90 lines of
# search cache with five tests, a docstring pricing its benefit, and ZERO
# consumers - and this guard called it alive for months because `test_views.py`
# named it. Removing the tests from the walk instead would blind the scan to the
# GUI tests, which are Python source inside `run_gui("""...""")` strings and are
# the only place several live names appear (see the block below). So the mentions
# are still collected, and marked.
TEST_TREES = ("tests/",)
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

    # The nine this guard could not see until TEST_TREES stopped counting as life
    # (2026-09-02). Each one is here with what it actually is, not with a shrug:
    # the point of this dict is that an unused name carries a REASON, and "nobody
    # has decided yet" is a reason as long as it says so. Tracked as B-16.
    "_settle_transition": "EXISTS for the tests and says so in its own docstring: "
                          "the live UI drains _ui_queue from _tick and never needs "
                          "it, so a headless test can drive the async start/stop "
                          "deterministically. Deleting it deletes those tests",
    "reset_default_table": "the same, and its docstring is one word long: (tests). "
                           "Drops the shared port table so one test cannot inherit "
                           "another's",
    "install_tk": "SUPERSEDED by App._on_ui_exception, which does strictly more "
                  "(records, logs, and shows one dialog per fingerprint) and owns "
                  "report_callback_exception. Not deleted yet for one reason: its "
                  "two tests are the ONLY guard on the source=\"tk-callback\" tag "
                  "reaching the file, and the live path has none. The tag needs a "
                  "test on App._on_ui_exception before this can go - B-16",
    "recent": "reads the crash log back 'for the UI', and there is no crash panel. "
              "No consumer, no decision taken - B-16",
    "set_enabled": "the global off switch for crash recording. Nothing turns it "
                   "off. No consumer, no decision taken - B-16",
    "driver_used": "an accessor for _DRIVER_USED[0], which driver.py reads "
                   "directly at the one place that cares. Redundant wrapper - B-16",
    "notices_text": "reads THIRD-PARTY-NOTICES.md. The About window shows the "
                    "about.third_party LABEL and never the file. Either the window "
                    "is missing something or this is - B-16",
    "show_info": "the third of show_error / show_warning / show_info. The family is "
                 "complete and only two members are called. Deleting it is a "
                 "decision about that symmetry - B-16",
    "time_left": "seconds until the deadline. Nothing asks. No consumer, no "
                 "decision taken - B-16",
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
            outside = "TESTS" if rel.startswith(TEST_TREES) else "EXTERNAL"
            for word in found:
                mentions.setdefault(word, set()).add(site or outside)

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
            # "TESTS" is deliberately absent from this list: a test is not a
            # consumer. A definition that genuinely exists FOR the tests says so in
            # KNOWN_UNUSED, where the reason is written down and read.
            living = [s for s in mentions.get(name, ())
                      if s == "EXTERNAL"
                      or (s != "TESTS" and s not in dead and s != key)]
            if not living:
                dead.add(key)
                grew = True
        if not grew:
            return sorted(dead), files, len(definitions)


def test_a_definition_only_its_own_tests_name_is_not_counted_as_alive():
    """The guard for the guard: without this, TEST_TREES could be reverted silently.

    Filling KNOWN_UNUSED makes the scan green again, so the test above passes just
    as happily whether a test mention counts as life or not - and the whole point of
    that distinction is that `views.SearchIndex` was ~90 lines with five tests, a
    docstring pricing its benefit and no consumers, and this file called it alive
    for months.

    `_settle_transition` is the probe because it is the clearest case in the tree:
    its own docstring says the live UI never needs it and it exists so a headless
    test can drive the async start/stop. If it is ever called from the package, this
    goes red and says so, which is the right kind of red.
    """
    dead, _, _ = _unreferenced()
    names = {name for name, _rel, _line in dead}
    check("a definition whose only callers are tests is reported unused",
          "_settle_transition" in names,
          "(a test mention is being counted as a consumer again)")


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


# -- the same shape, everywhere else: an INVENTORY rather than a rule ----------- #
#
# The guard above holds `core.py` to an absolute rule and says, in its own
# docstring, why the rest of the package is not held to it: most broad handlers
# out here are legitimate control-flow fallbacks - a parse returning None on bad
# input, a DPI probe falling back to a default, a widget query answered by a
# toolkit that has already destroyed the widget.
#
# That reasoning is right and this does not touch it. What it leaves open is the
# COUNT. Finding F3 was a silent `except Exception: return False` in the decision
# core; the same shape exists 93 times elsewhere, and nothing could tell a new one
# from the 93 that were considered and kept. So the population is frozen instead
# of the practice: today's numbers, per file, and they may only go DOWN.
#
# Measured 2026-09-06 with the same two predicates the core guard uses, so the two
# can never drift into meaning different things by "silent" and "broad".
#
# 🔴 A file absent from this map must have ZERO. That is what makes the map a
# ratchet rather than a list of the usual suspects: a NEW file full of silent
# handlers cannot slip in by simply not being mentioned.
SILENT_BROAD_HANDLERS = {
    "gui/app.py": 13,
    # 12 on 2026-09-06, then seven were dealt with in the same change - the file
    # this inventory was built to look at first, because it is on the targeting
    # path. The five left are per-PID lookups (`_make_native`, the two halves of
    # `_native_process_info`, `_psutil_created`, `_psutil_process_info`), where a
    # process that exited between the listing and the query, or one that denies a
    # handle, is an ORDINARY event: recording those would fill the crash log with
    # the normal running of the machine. The seven that went were the whole-table
    # collapses and the capability probes, where silence is indistinguishable
    # from an empty machine.
    "portmap.py": 5,
    # The recorder itself, and the one module allowed to swallow by this
    # repository's own rule (see the per-file ignore in pyproject.toml): a crash
    # reporter that raises while reporting a crash is worse than a quiet one.
    "crashlog.py": 10,
    "gui/widgets/sortable_tree.py": 9,
    "cli.py": 5,
    "engine.py": 5,
    "gui/tooltip.py": 4,
    "legal.py": 4,
    "winenv.py": 4,
    "gui/scrollable.py": 3,
    "gui/windows.py": 3,
    "gui/form.py": 2,
    "gui/icon.py": 2,
    "gui/pages/stats.py": 2,
    "gui/scaling.py": 2,
    "gui/theme.py": 2,
    "i18n.py": 2,
    "utils.py": 2,
    "driver.py": 1,
    "filters.py": 1,
    "gui/chart.py": 1,
    "gui/csv_export.py": 1,
    "gui/pages/conns.py": 1,
    "matchers.py": 1,
    "settings.py": 1,
}


def _silent_broad_handlers():
    """Per package file: how many broad handlers neither record nor re-raise."""
    counts = {}
    root = os.path.join(ROOT, "beantester")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            tree = ast.parse(open(path, encoding="utf-8").read())
            found = sum(1 for node in ast.walk(tree)
                        if isinstance(node, ast.ExceptHandler)
                        and _is_broad_handler(node)
                        and not _handler_reaches_crashlog_or_reraises(node))
            if found:
                counts[rel] = found
    return counts


def test_no_file_grows_a_new_silently_swallowed_exception():
    """The population of the F3 shape may fall and may not rise.

    Nothing here says any of the 93 is wrong. It says that the next one is a
    DECISION: either it is a fallback worth keeping, and the number beside its
    file goes up in the same change with a reason - which is the owner's call, the
    same as raising any ceiling in this repository - or it routes to `crashlog`
    like the convention asks.
    """
    measured = _silent_broad_handlers()
    check("the handler scan actually read the package (an empty scan passes)",
          sum(measured.values()) > 50, f"({sum(measured.values())} found)")

    grown = sorted(f"{name}: {n} (was {SILENT_BROAD_HANDLERS.get(name, 0)})"
                   for name, n in measured.items()
                   if n > SILENT_BROAD_HANDLERS.get(name, 0))
    check("no file swallows more broadly than it did", not grown,
          f"({grown} - route the new one to crashlog.quiet/once/note, or raise "
          "its number here on purpose)")


def test_the_silent_handler_inventory_is_todays_measurement():
    """The pinning half, for the reason every ceiling in this repository has one.

    A number parked above the truth grants room nobody decided to grant, and the
    next arrival slips in under it in silence - which is precisely the failure
    this inventory exists to prevent, wearing its own badge. So fixing a handler
    comes with a two-character chore: bring its number down with it.
    """
    measured = _silent_broad_handlers()
    stale = sorted(f"{name}: {frozen} frozen, {measured.get(name, 0)} measured"
                   for name, frozen in SILENT_BROAD_HANDLERS.items()
                   if measured.get(name, 0) != frozen)
    check("every frozen count is the measurement, not a number above it",
          not stale, f"({stale} - lower it, that is what makes the fix stick)")
