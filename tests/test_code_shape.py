"""Size ceilings for the package, as a RATCHET: the numbers may only go down.

Why a ceiling here, when nothing has actually gone wrong yet
-----------------------------------------------------------
Nobody reads this code line by line. There is no reviewer to notice that a function
reached three hundred lines over four sessions, each of which added twenty and each
of which was reasonable on its own. A ceiling is the only mechanism that notices,
and it costs nothing while nothing grows.

Why LOGIC lines and not lines
-----------------------------
Measured before choosing the metric (2026-08-02): of 17 770 lines in ``beantester/``,
only 9 776 are logic - **45% of this package is comments, docstrings and blank
lines**. That is deliberate and it is where the measurements and the reasons live. A
raw-line ceiling would therefore be a ceiling on EXPLAINING, pushing the next session
to delete the paragraph that says why a constant is 0.30 rather than to simplify the
function. So comments and docstrings are free; only executable lines count.

Where the numbers come from
---------------------------
They are today's maxima, not a textbook figure: ``init_style`` at 167 logic lines and
``gui/app.py`` at 1299. Nothing has to be rewritten to make this pass, which is the
point - a ceiling picked out of the air either fails on day one or is set so loose it
never fires.

**Lowering these is ordinary work. Raising either is the owner's decision, not a way
to get unblocked** - a threshold bent to fit the code has stopped being a threshold.
When a function crosses it, the answer is to split the function.

What this does NOT check
------------------------
Whether a function does one thing (a tidy twenty-line function doing three things
passes exactly like a good one), whether its name is honest, or whether splitting it
scattered the logic across ten places - that last one has its own cost and no metric.
Nesting depth is not measured either. This guard buys one thing only: nothing grows
past what a person can follow without somebody deciding that it should.
"""
import ast
import os
import sys

from fakes import ROOT, check

# Today's maxima, measured 2026-08-02. Ratchet: down is routine, up is a decision.
# Lowered 2026-08-10 from 167 (`gui/theme.py::init_style`) after that function was
# split by style family. The ceiling had been pinned to it exactly, so ANY change to
# the theme reddened the suite - and the ratchet's own answer to that is to move code
# out, not to raise the number. Down is routine: this took the routine door.
#
# 🔴 BOTH ARE PINNED TO TODAY'S MEASUREMENT, and a test below enforces that. A
# ceiling standing ABOVE the truth is a knob that has quietly loosened: it grants
# headroom nobody decided to grant, and the next arrival slips in under it in
# silence. This one had drifted - `FILE_CEILING` stayed at 1299 after `gui/crash.py`
# was carved out of `app.py` and left it at 1287, so twelve lines of allowance sat
# there for a week and were found only because somebody printed the numbers. That is
# the same defect the crowd counts below exist to catch, one level up.
FUNCTION_CEILING = 133          # beantester/cli.py::_run_session
# Lowered 2026-08-19 from 1202: fifteen compatibility aliases assigned one per line
# became a loop over their names, which is also what mypy asked for (a class does not
# grow attributes from outside its own body). Ten lines out, ten lines off the ceiling.
# Lowered 2026-08-12 from 1287, the same routine door: moving the user files out of
# the install directory needed three lines in `app.py`, which was pinned to the
# ceiling exactly, so the two CSV exports moved to `gui/csv_export.py` instead of the
# number moving up. The crowd band below was re-measured after the drop (`engine.py`
# is 779, still clear of it) - lowering a ceiling tightens that band too.
FILE_CEILING = 1192             # beantester/gui/app.py

# 🔴 THE SECOND KNOB. A ceiling on the worst single item sees one thing growing
# to a record and is blind to everything creeping upward together: five files at
# ninety percent of the limit pass it exactly as cleanly as five files at ten.
#
# So the count of items already in the top band is a ratchet of its own. It may
# fall, and raising it is the same act as raising a ceiling - a decision, not a
# way to get unblocked.
#
# The band is 70%, measured rather than picked (2026-08-06). The distribution
# here is steeply skewed: one file sits at the ceiling and the next is at 60% of
# it, so a tighter band would be a constant 1 and would say nothing. At 70% the
# counts are small and the next candidate is real - `engine.py` has about 130
# lines of headroom before it joins the count.
CROWD_BAND = 0.70
FILES_NEAR_CEILING = 1          # beantester/gui/app.py
FUNCTIONS_NEAR_CEILING = 3      # _run_session, _build_ui, build_arg_parser


def _logic_lines(source):
    """Line numbers that carry executable code: no blanks, comments or docstrings.

    Docstrings are found through the AST rather than by matching quotes, so a string
    that merely LOOKS like one (a multi-line literal assigned to a name) still counts
    as logic - which is right, because it is.
    """
    tree = ast.parse(source)
    lines = source.splitlines()
    doc = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            doc.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    live = set()
    for number in range(1, len(lines) + 1):
        text = lines[number - 1].strip()
        if text and not text.startswith("#") and number not in doc:
            live.add(number)
    return tree, live


def _package_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "beantester")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        out += [os.path.join(dirpath, n) for n in filenames if n.endswith(".py")]
    return out


def _sizes():
    """Every file and every function with its logic-line count, biggest first."""
    files, functions = [], []
    paths = _package_files()
    for path in paths:
        tree, live = _logic_lines(open(path, encoding="utf-8").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        files.append((len(live), rel))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            span = sum(1 for n in live if node.lineno <= n <= (node.end_lineno or 0))
            functions.append((span, f"{rel}::{node.name}"))
    files.sort(reverse=True)
    functions.sort(reverse=True)
    return files, functions, len(paths)


def _measure():
    """(worst function, worst file) as (name, count) pairs, plus how many files."""
    files, functions, seen = _sizes()
    worst_file = (files[0][1], files[0][0]) if files else ("", 0)
    worst_function = (functions[0][1], functions[0][0]) if functions else ("", 0)
    return worst_function, worst_file, seen


def test_no_function_or_file_has_grown_past_the_ratchet():
    """Nothing in the package is longer than the longest thing was on 2026-08-02.

    Crossing this is not a licence to raise the number. A function over the ceiling
    gets split - which is exactly what happened to the one case another project hit
    on the day it introduced the same guard.
    """
    worst_function, worst_file, seen = _measure()

    # The canary from test_repo_conventions, applied here: a walk that finds nothing
    # satisfies both ceilings perfectly and looks like a guard that works.
    check("the shape scan actually read the package "
          "(an empty scan passes every ceiling ever set)", seen >= 30, f"({seen} files)")

    check(f"no function exceeds {FUNCTION_CEILING} logic lines "
          f"(split it - do not raise the ceiling)",
          worst_function[1] <= FUNCTION_CEILING,
          f"(worst: {worst_function[0]} at {worst_function[1]}, "
          f"{FUNCTION_CEILING - worst_function[1]} lines of headroom left)")
    check(f"no module exceeds {FILE_CEILING} logic lines",
          worst_file[1] <= FILE_CEILING,
          f"(worst: {worst_file[0]} at {worst_file[1]}, "
          f"{FILE_CEILING - worst_file[1]} lines of headroom left)")


def test_the_ratchet_measures_logic_and_not_explanation():
    """Comments and docstrings must stay free, or the ceiling punishes the thing
    this project is built on.

    Without this, the cheapest way to get back under the limit would be to delete
    the paragraph explaining why a constant is what it is - the exact opposite of
    what convention 5 asks for. Checked directly rather than assumed: a body padded
    with ninety lines of comment measures the same as the body alone.
    """
    bare = "def f():\n" + "    x = 1\n" * 5
    padded = "def f():\n" + '    """Doc."""\n' + "    # note\n" * 90 + "    x = 1\n" * 5
    _, live_bare = _logic_lines(bare)
    _, live_padded = _logic_lines(padded)
    check("ninety lines of comment and a docstring do not count as logic",
          len(live_padded) == len(live_bare),
          f"(bare {len(live_bare)}, padded {len(live_padded)})")


def test_the_metric_still_counts_code(tmp_path):
    """The other half of the test above, and it is not decoration.

    "Comments do not move the number" is satisfied perfectly by a metric that
    counts NOTHING - and a ceiling standing on a metric stuck at zero passes for
    ever while the code grows underneath it. The rule the neighbouring rule set
    states is symmetric on purpose: add N lines of comment and N lines of code to
    the same function, and only the second may move the measure.
    """
    bare = "def f():\n" + "    x = 1\n" * 5
    with_code = "def f():\n" + "    x = 1\n" * 5 + "    y = 2\n" * 7
    _, live_bare = _logic_lines(bare)
    _, live_code = _logic_lines(with_code)
    check("seven more lines of code move the measure by exactly seven",
          len(live_code) - len(live_bare) == 7,
          f"(bare {len(live_bare)}, with code {len(live_code)})")


def test_nothing_else_is_creeping_up_on_the_ceilings():
    """THE SECOND KNOB - see CROWD_BAND for why one is not enough.

    A ceiling on the worst item watches one thing. It cannot see the shape this
    project actually drifts into: several files climbing together, none of them a
    record, all of them past the point where a person can follow them. The count
    of items already in the top band is the ratchet for that, and like every
    ratchet here it may fall and may not rise without a decision.
    """
    files, functions, seen = _sizes()
    check("the shape scan actually read the package", seen >= 30, f"({seen} files)")

    file_band = FILE_CEILING * CROWD_BAND
    crowded_files = [f"{name} ({n})" for n, name in files if n >= file_band]
    check(f"at most {FILES_NEAR_CEILING} module(s) within {CROWD_BAND:.0%} of the "
          f"ceiling ({file_band:.0f} lines) - split one before adding another",
          len(crowded_files) <= FILES_NEAR_CEILING, f"({crowded_files})")

    function_band = FUNCTION_CEILING * CROWD_BAND
    crowded_functions = [f"{name} ({n})" for n, name in functions if n >= function_band]
    check(f"at most {FUNCTIONS_NEAR_CEILING} function(s) within {CROWD_BAND:.0%} of "
          f"the ceiling ({function_band:.0f} lines)",
          len(crowded_functions) <= FUNCTIONS_NEAR_CEILING, f"({crowded_functions})")


def test_the_crowd_counts_are_not_set_so_loosely_that_they_never_fire():
    """A ratchet parked far above the current state is a ratchet that never moves.

    The counts above are today's measurements, so they must be EXACT, not
    generous. Frozen one above the truth, the guard would allow the next arrival
    silently - which is the failure it exists to prevent, wearing its own badge.
    """
    files, functions, _ = _sizes()
    actual_files = sum(1 for n, _ in files if n >= FILE_CEILING * CROWD_BAND)
    actual_functions = sum(1 for n, _ in functions if n >= FUNCTION_CEILING * CROWD_BAND)
    check("the module count is today's measurement, not a looser number",
          actual_files == FILES_NEAR_CEILING,
          f"(measured {actual_files}, frozen at {FILES_NEAR_CEILING} - lower it)")
    check("the function count is today's measurement, not a looser number",
          actual_functions == FUNCTIONS_NEAR_CEILING,
          f"(measured {actual_functions}, frozen at {FUNCTIONS_NEAR_CEILING} - lower it)")


def test_the_ceilings_are_not_set_so_loosely_that_they_never_fire():
    """The same rule as above, applied one level up: to the CEILINGS themselves.

    "Down is routine, up is a decision" only holds if down actually happens. A
    ceiling left above the truth grants headroom nobody decided to grant, and the
    next arrival slips in under it silently - so the number has to BE the
    measurement, not merely be above it.

    Measured, not hypothetical: `FILE_CEILING` stayed at 1299 after `gui/crash.py`
    was carved out of `app.py` and left it at 1287. Twelve lines of allowance sat
    there for a week, and nothing was watching that gap - the crowd counts guard
    the population of the top band, not the height of the band. This test is the
    missing half.

    Shrinking something therefore comes with a two-line chore: bring the ceiling
    down with it. That is the routine door, and it is meant to be routine.
    """
    files, functions, _ = _sizes()
    biggest_file = max(files)
    biggest_function = max(functions)
    check("the file ceiling IS the largest module, not a number above it",
          biggest_file[0] == FILE_CEILING,
          f"({biggest_file[1]} is {biggest_file[0]}, ceiling is {FILE_CEILING} - "
          f"move the ceiling to {biggest_file[0]})")
    check("the function ceiling IS the largest function, not a number above it",
          biggest_function[0] == FUNCTION_CEILING,
          f"({biggest_function[1]} is {biggest_function[0]}, ceiling is "
          f"{FUNCTION_CEILING} - move the ceiling to {biggest_function[0]})")


# 🔴 THE SECOND KNOB, on the complexity axis - the counterpart of
# FILES_NEAR_CEILING and FUNCTIONS_NEAR_CEILING, and it was missing until
# 2026-08-21. `max-complexity` watches ONE function: the most branching one in the
# tree. It is blind to the shape the size ratchet already grew a knob for - the
# runners-up climbing together, none of them a record. With the ceiling at 29,
# `cli._run_session` could go from 27 to 29 across three sessions and every gate in
# this repository would stay green the whole way.
#
# Today's measurement, same 70% band as the size counts (CROWD_BAND): three
# functions reach 21 or more - `core.decide` (29), `cli._run_session` (27) and
# `summary.settings_summary` (25). `engine._capture_loop` is next at 20, roughly
# one branch of headroom, which is what makes this band a real one rather than a
# number that can never fire.
#
# Measured over the WHOLE tree, like the ceiling above it and unlike the size
# counts, which walk the package only. That is deliberate: the ceiling this band
# hangs from is repo-wide, so a band scoped to the package would be measuring a
# different thing from the number it is a percentage of.
COMPLEX_NEAR_CEILING = 3        # decide, _run_session, settings_summary


# Ruff is not in requirements-dev.txt: it lives in requirements-lint.txt, which a
# contributor may not have installed. The two checks below skip themselves rather
# than fail in that case - the same choice the admin-only tests make, and for the
# same reason: a red that means "you did not install a tool" teaches people to
# ignore red.
def _ruff_findings(rule, setting, limit):
    """How many findings ``rule`` raises with ``setting`` at ``limit``.

    None when ruff is not installed here, so every caller skips rather than fails.
    """
    import subprocess
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--select", rule,
             "--config", f"{setting} = {limit}",
             "--output-format", "concise", "--no-cache", "."],
            cwd=ROOT, capture_output=True, text=True)
    except OSError:
        return None
    if "No module named" in proc.stderr or proc.returncode not in (0, 1):
        return None
    return len([ln for ln in proc.stdout.splitlines() if rule in ln])


def _ruff_complexity_findings(limit):
    """How many functions ruff reports above ``limit``, or None if ruff is absent."""
    return _ruff_findings("C901", "lint.mccabe.max-complexity", limit)


def test_the_complexity_ceiling_is_the_measurement_not_a_number_above_it():
    """The same rule the file and function ceilings live by, on the third axis.

    A ceiling parked above the truth grants headroom nobody decided to grant, and
    the next arrival slips in under it in silence. So `max-complexity` has to BE
    the most branching function in the tree: nothing may exceed it, and lowering
    it by one must produce a finding.

    Complexity is not length. The size ratchet already watches how long a function
    is, and the two do not move together - a hundred lines of straight-line setup
    is readable, forty lines with eight nested branches is not.
    """
    import tomllib
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as handle:
        ceiling = tomllib.load(handle)["tool"]["ruff"]["lint"]["mccabe"]["max-complexity"]

    at_ceiling = _ruff_complexity_findings(ceiling)
    if at_ceiling is None:
        return                      # ruff not installed here: nothing to measure
    check(f"nothing in the tree is more complex than {ceiling}",
          at_ceiling == 0, f"({at_ceiling} function(s) over the ceiling)")

    below = _ruff_complexity_findings(ceiling - 1)
    check(f"the ceiling {ceiling} IS a real measurement, not headroom",
          below and below > 0,
          f"(nothing reaches {ceiling} - lower max-complexity to the real maximum)")


def test_nothing_else_is_creeping_up_on_the_complexity_ceiling():
    """The crowd count, one axis over - see COMPLEX_NEAR_CEILING for why.

    Both halves live in ONE test on purpose, which is a deviation from the size
    ratchet above and it is about cost, not tidiness: every reading here is a ruff
    subprocess over the whole tree (measured 0.6 s warm, 2.4 s cold), and splitting
    the two questions would pay for the same measurement twice to print two
    sentences. `check` gives each half its own wording, which is what the split was
    ever for.
    """
    import tomllib
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as handle:
        ceiling = tomllib.load(handle)["tool"]["ruff"]["lint"]["mccabe"]["max-complexity"]

    band = int(ceiling * CROWD_BAND)
    crowded = _ruff_complexity_findings(band)
    if crowded is None:
        return                      # ruff not installed here: nothing to measure

    check(f"at most {COMPLEX_NEAR_CEILING} function(s) within {CROWD_BAND:.0%} of "
          f"max-complexity ({band + 1} or more) - simplify one before adding another",
          crowded <= COMPLEX_NEAR_CEILING,
          f"({crowded} in the band, COMPLEX_NEAR_CEILING is {COMPLEX_NEAR_CEILING})")
    check("the complexity crowd count is today's measurement, not a looser number",
          crowded == COMPLEX_NEAR_CEILING,
          f"(measured {crowded}, frozen at {COMPLEX_NEAR_CEILING} - lower it)")


def test_the_argument_ceiling_is_the_measurement_not_a_number_above_it():
    """`max-args` on the third axis: how many things a caller must line up.

    Complexity and length are both blind to it - a fifteen-argument constructor
    can be four lines of straight-line assignment and pass them both. The rule at
    ruff's own default of 5 would be red on 25 signatures on day one, so it is
    pinned to the widest one instead and ratchets down from there.
    """
    import tomllib
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as handle:
        ceiling = tomllib.load(handle)["tool"]["ruff"]["lint"]["pylint"]["max-args"]

    over = _ruff_findings("PLR0913", "lint.pylint.max-args", ceiling)
    if over is None:
        return                      # ruff not installed here: nothing to measure
    check(f"no signature takes more than {ceiling} arguments "
          f"(split the call - do not raise the ceiling)",
          over == 0, f"({over} signature(s) over the ceiling)")

    below = _ruff_findings("PLR0913", "lint.pylint.max-args", ceiling - 1)
    check(f"the ceiling {ceiling} IS a real measurement, not headroom",
          below and below > 0,
          f"(nothing reaches {ceiling} - lower max-args to the real maximum)")


# 🔴 The rule list is a RATCHET, and it is recorded in two places for the reason
# every other double record here exists: nothing stopped a future change from
# deleting a family out of `select` to make a red build green, and a check that
# has vanished cannot fail to announce itself.
#
# `BLOCKING` is the subset the pull request actually stands on. It is written down
# separately because `--select` on the ci.yml command line REPLACES the list in
# pyproject.toml - so a rule can be configured, visible to anyone running plain
# `ruff check`, and yet absent from the only run that can block a merge. That is
# not hypothetical: it is the exact mistake this test was written to make
# impossible, on the day PLR0913 was added.
SELECTED_RULES = {"F", "B", "S", "ASYNC", "C90", "PLR0913"}
BLOCKING_RULES = {"F", "B", "C90", "PLR0913"}


def test_the_selected_rules_only_ever_grow():
    """Growing the list is free (add it in both places); shrinking it reddens."""
    import tomllib
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as handle:
        selected = set(tomllib.load(handle)["tool"]["ruff"]["lint"]["select"])

    lost = sorted(SELECTED_RULES - selected)
    check("no rule family has quietly left the ruff configuration", not lost,
          f"({lost} - dropping one is a decision, so change SELECTED_RULES too)")
    gained = sorted(selected - SELECTED_RULES)
    check("a newly selected rule is recorded here as well", not gained,
          f"({gained} - add it to SELECTED_RULES, that is what makes it stick)")


def test_every_blocking_rule_is_named_in_the_workflow_that_blocks():
    """The configured list and the list CI runs are two different things.

    ci.yml runs ruff twice: once blocking, once reporting with --exit-zero. Between
    them they must account for every selected rule - a rule in neither is a gate
    nobody runs, and a blocking rule missing from the first command is a gate that
    exists only on a developer machine.
    """
    import re
    path = os.path.join(ROOT, ".github", "workflows", "ci.yml")
    with open(path, encoding="utf-8") as handle:
        workflow = handle.read()
    runs = re.findall(r"ruff check --select ([A-Z0-9,]+)", workflow)
    check("ci.yml still runs ruff twice (one blocking, one report)",
          len(runs) == 2, f"(found {len(runs)} ruff invocations)")
    if len(runs) != 2:
        return
    blocking, reporting = (set(r.split(",")) for r in runs)
    check("the blocking run names exactly the rules that must block",
          blocking == BLOCKING_RULES,
          f"(workflow blocks on {sorted(blocking)}, expected {sorted(BLOCKING_RULES)})")
    check("every selected rule is either blocking or reported, none is unrun",
          blocking | reporting == SELECTED_RULES,
          f"(workflow runs {sorted(blocking | reporting)}, "
          f"configured {sorted(SELECTED_RULES)})")


# The modules mypy is strict about, recorded here so the list in pyproject.toml
# cannot quietly shrink. Add to BOTH when a module gains annotations; this one is
# the ratchet, and like every ratchet here it may rise and may not fall.
STRICTLY_TYPED = {
    "beantester.utils",
    "beantester.gui.rates",
    "beantester.gui.scope",
}


def test_the_strictly_typed_modules_only_ever_grow():
    """Gradual typing without a ratchet is a plan, not a property.

    `disallow_untyped_defs` is on for three modules. Nothing stops the next
    change from dropping one out of `pyproject.toml` to make a red build green -
    and nothing would ever say so, because the check that vanished cannot fail.

    So the list is recorded twice: in the configuration, and here. Growing it is
    free (add to both), shrinking it reddens. That is the same shape as
    FILE_CEILING, one axis over.
    """
    import tomllib
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as handle:
        config = tomllib.load(handle)
    strict = set()
    for override in config["tool"]["mypy"].get("overrides", []):
        if override.get("disallow_untyped_defs"):
            module = override.get("module")
            strict |= set(module if isinstance(module, list) else [module])

    lost = sorted(STRICTLY_TYPED - strict)
    check("no module has quietly lost its strict typing", not lost,
          f"({lost} - dropping one is a decision, so change STRICTLY_TYPED too)")
    gained = sorted(strict - STRICTLY_TYPED)
    check("a newly strict module is recorded here as well", not gained,
          f"({gained} - add it to STRICTLY_TYPED, that is what makes it stick)")
