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

from fakes import ROOT, check

# Today's maxima, measured 2026-08-02. Ratchet: down is routine, up is a decision.
FUNCTION_CEILING = 167          # beantester/gui/theme.py::init_style
FILE_CEILING = 1299             # beantester/gui/app.py

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
FUNCTIONS_NEAR_CEILING = 4      # init_style, _run_session, _build_ui, build_arg_parser


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
