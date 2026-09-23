"""GUI rule 1, made mechanical: a view names no colour, no pixel and no text of its own.

The project's rule reads "zero raw values in views - colours, spacing, font sizes
and texts come only from token and resource files". Nothing enforced it, and the
older pages show what that costs: ~200 ``scaled(<number>)`` calls whose numbers
mean "the gap the Connections page uses" without saying so, so "make the gaps a
little wider" is two hundred edits and a guess about which 8 was which.

This guard covers the files that FOLLOW the rule today - the Tools tab, which was
written against the tokens in ``gui/theme.py`` (``SPACE``, ``CHARS``, ``space()``)
from its first line. It is a glob, not a list: a new tool panel is covered the day
it is created. The older pages are not in scope; they move over in their own change
and join the glob then.

What counts as raw, each with the reason:
* a hex colour string - colours are ``theme.py`` constants and ttk styles;
* any call to ``scaled()`` - a view asks ``space(<role>)`` instead, so the number
  lives once, under a name;
* a number other than 0 in a spacing or size option (``padx``, ``width``...) -
  0 is "no gap", which no token would name better;
* a string literal in ``text=`` / ``title=`` / ``label=`` that is not the key
  handed to ``T()`` - the text of a widget comes from ``lang/*.json``. Only
  whitespace is let through: a newline joining translated lines is layout;
* ``font=`` or a colour option - both belong to a style.
"""
import ast
import glob
import os
import re

from fakes import ROOT, check

SCOPE = ("beantester/gui/toolbox/**/*.py", "beantester/gui/pages/toolbox.py")

SIZE_OPTIONS = {"padx", "pady", "ipadx", "ipady", "width", "height", "wraplength",
                "pad", "minsize", "borderwidth", "highlightthickness", "length"}
TEXT_OPTIONS = {"text", "title", "label"}
STYLE_ONLY = {"font", "bg", "fg", "background", "foreground", "insertbackground",
              "highlightcolor", "highlightbackground", "selectbackground"}
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
TRANSLATORS = {"T", "translate"}


def _docstrings(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def _callee(node):
    func = node.func
    return func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)


def _keys_handed_to_t(tree):
    """String constants that are the FIRST argument of ``T(...)`` - i18n keys."""
    return {id(node.args[0]) for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _callee(node) in TRANSLATORS
            and node.args and isinstance(node.args[0], ast.Constant)}


def violations(source):
    """Every raw value in ``source``, as ``(line, what)``. Exposed for the canary."""
    tree = ast.parse(source)
    prose, keys = _docstrings(tree), _keys_handed_to_t(tree)
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in prose and HEX.match(node.value)):
            found.append((node.lineno, f"hex colour {node.value!r}"))
        if isinstance(node, ast.Call) and _callee(node) == "scaled":
            found.append((node.lineno, "scaled() - ask space(<role>) instead"))
        if not isinstance(node, ast.keyword) or node.arg is None:
            continue
        if node.arg in STYLE_ONLY:
            found.append((node.value.lineno, f"{node.arg}= belongs to a style"))
        for inner in ast.walk(node.value):
            if not isinstance(inner, ast.Constant):
                continue
            number = (isinstance(inner.value, (int, float))
                      and not isinstance(inner.value, bool) and inner.value != 0)
            if node.arg in SIZE_OPTIONS and number:
                found.append((inner.lineno, f"{node.arg}={inner.value!r}"))
            # whitespace carries no language - "\n".join(lines) is layout, not text
            if (node.arg in TEXT_OPTIONS and isinstance(inner.value, str)
                    and inner.value.strip() and id(inner) not in keys):
                found.append((inner.lineno, f"{node.arg}={inner.value!r} is not a T() key"))
    return found


def _files():
    out = []
    for pattern in SCOPE:
        out += glob.glob(os.path.join(ROOT, pattern), recursive=True)
    return sorted(set(out))


def test_the_tools_tab_names_no_raw_colour_pixel_or_text():
    files = _files()
    check("the scan found the Tools tab's files", len(files) >= 4,
          f"({[os.path.relpath(f, ROOT) for f in files]})")
    offenders = {}
    for path in files:
        found = violations(open(path, encoding="utf-8").read())
        if found:
            offenders[os.path.relpath(path, ROOT)] = found
    check("no hex colour, scaled(), numeric spacing, literal text or font in a view",
          not offenders, f"({offenders})")


BAD = '''
def build(parent):
    ttk.Label(parent, text="Hello", foreground="#ff0000")
    ttk.Label(parent, text=T("app.tabs.tools") + ":")
    frame.pack(padx=scaled(8), pady=(4, 0))
    ttk.Entry(parent, width=26, font=("Segoe UI", 9))
    colour = "#1e2127"
'''

GOOD = '''
def build(parent):
    """A docstring may say #1e2127 and "text" freely."""
    ttk.Label(parent, text=T("app.tabs.tools"), style="Muted.TLabel")
    ttk.Label(parent, text="")
    ttk.Label(parent, text="\\n".join(lines))
    frame.pack(padx=space("page"), pady=(space("row"), 0))
    ttk.Entry(parent, width=CHARS["value"])
    grid.grid(row=2, column=1, columnspan=3)
'''


def test_the_guard_rejects_each_kind_of_raw_value_and_passes_clean_code():
    """A guard nobody has watched fail is indistinguishable from one that reads nothing."""
    found = [what for _line, what in violations(BAD)]
    expected = ("text='Hello'", "foreground= belongs", "text=':'", "scaled()",
                "pady=4", "width=26", "font= belongs", "hex colour '#ff0000'",
                "hex colour '#1e2127'")
    missed = [e for e in expected if not any(e in f for f in found)]
    check("every kind of raw value is caught", not missed, f"(missed {missed} in {found})")
    check("clean code passes", violations(GOOD) == [], f"({violations(GOOD)})")
