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


def _measure():
    """(worst function, worst file) as (name, count) pairs, plus how many files."""
    worst_function = ("", 0)
    worst_file = ("", 0)
    paths = _package_files()
    for path in paths:
        tree, live = _logic_lines(open(path, encoding="utf-8").read())
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        count = len(live)
        if count > worst_file[1]:
            worst_file = (rel, count)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            span = sum(1 for n in live if node.lineno <= n <= (node.end_lineno or 0))
            if span > worst_function[1]:
                worst_function = (f"{rel}::{node.name}", span)
    return worst_function, worst_file, len(paths)


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
          f"(worst: {worst_function[0]} at {worst_function[1]})")
    check(f"no module exceeds {FILE_CEILING} logic lines",
          worst_file[1] <= FILE_CEILING,
          f"(worst: {worst_file[0]} at {worst_file[1]})")


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
