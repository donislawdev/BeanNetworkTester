"""Tools tab: the expression tester. The answer is computed in ``nettools/exprtest.py``.

Pick a Control-page field, type an expression and a value, and read at once
whether they match - and which term decided it. "Use in the Control field" then
puts the expression into that field, by the same road the connection table's
row actions take (``gui/field_actions.py``).

Decided by the owner, 2026-09-23: the verdict follows the typing (a quarter of a
second after the last key, like the connection search) rather than waiting for a
button, and "Use" REPLACES the field's value - the tester composes a whole
expression, where a table row adds one term.
"""
import tkinter as tk
from tkinter import ttk

from ...fields import FIELDS, expression_fields
from ...i18n import T
from ...matchers import KIND_PROCESS
from ...nettools import exprtest
from ..field_actions import fill_field
from ..labels import wrapping_label
from ..theme import CHARS, popdown_height, popdown_width, space, unhighlight_combobox
from ..tooltip import add_tooltip
from .base import Debounce, help_button, remembered

# The tester's own name for each field it can test. The REGISTRY decides which
# fields appear (``fields.expression_fields()``); these keys only name them. The
# form's labels cannot: `dst_ip` and `block_ip` are both "IP:" and differ only by
# the card they sit in. A new expression field without a key here reddens
# `tests/test_toolbox.py` instead of showing its raw key in the list.
FIELD_NAME_KEY = "tools.exprtest.field.{key}"

# What the value box is called, by the kind of expression it is tested against.
VALUE_LABELS = {KIND_PROCESS: "tools.exprtest.value_process"}
VALUE_LABEL = "tools.exprtest.value"

VERDICT_TEXT = {
    exprtest.MATCH: ("tools.exprtest.match", "Good.TLabel"),
    exprtest.NO_MATCH: ("tools.exprtest.no_match", "Status.Bad.TLabel"),
    exprtest.NO_VALUE: ("tools.exprtest.no_value", "Muted.TLabel"),
    exprtest.BAD_VALUE: ("tools.exprtest.bad_value", "Status.Bad.TLabel"),
    exprtest.BAD_EXPRESSION: ("tools.exprtest.bad_expression", "Status.Bad.TLabel"),
}

# The states in which the expression itself parsed - the only ones "Use" may send
# on. An empty expression is refused separately: in the Process field it means ALL
# traffic, and a button that clears the target is not what this panel is for.
USABLE = frozenset({exprtest.MATCH, exprtest.NO_MATCH, exprtest.NO_VALUE,
                    exprtest.BAD_VALUE})


def field_label(key):
    """The tester's name for one expression field, in the current language."""
    return T(FIELD_NAME_KEY.format(key=key))


class ExprTestPanel:
    ID = "exprtest"
    LABEL = "tools.exprtest.tab"

    def __init__(self, app, parent):
        self.app = app
        self.memory = remembered(app, self.ID)
        self.frame = ttk.Frame(parent)
        self.keys = [field.key for field in expression_fields()]
        self.labels = {key: field_label(key) for key in self.keys}
        self.by_label = {label: key for key, label in self.labels.items()}
        if self.memory.get("field") not in self.labels:
            self.memory["field"] = self.keys[0]
        self.debounce = Debounce(self.frame, self.evaluate)
        # One variable per input, restored from what this window remembers. Read
        # through the variable, never `entry.get()`: that is what the form and the
        # connection search do, and the one the GUI tests can drive.
        self.vars = {name: tk.StringVar(value=self.memory.get(name, ""))
                     for name in ("expression", "value", "pid")}

        # Three columns: label | input (stretches) | "?". The pid sits in the value's
        # own row frame, right after the value it belongs to - in a grid column of
        # its own it was pushed to the far edge by the stretching one.
        grid = ttk.Frame(self.frame)
        grid.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        grid.columnconfigure(1, weight=1)
        self._build_field_row(grid)
        self._label(grid, "tools.exprtest.expression", row=1)
        self._entry(grid, "expression", "tips.tools_exprtest_expression").grid(
            row=1, column=1, columnspan=2, sticky="ew", pady=(0, space("tight")))
        self.value_label = self._label(grid, VALUE_LABEL, row=2)
        probe = ttk.Frame(grid)
        probe.grid(row=2, column=1, columnspan=2, sticky="w", pady=(0, space("tight")))
        self._entry(probe, "value", "tips.tools_exprtest_value",
                    width=CHARS["value"]).pack(side="left")
        self.pid_label = ttk.Label(probe, text=T("tools.exprtest.pid"))
        self.pid_label.pack(side="left", padx=(space("inline"), space("tight")))
        self.pid = self._entry(probe, "pid", "tips.tools_exprtest_pid", width=CHARS["pid"])
        self.pid.pack(side="left")

        self.verdict = ttk.Label(self.frame, text="", style="Muted.TLabel")
        self.verdict.pack(anchor="w", padx=space("page"), pady=(space("row"), 0))
        self.details = wrapping_label(self.frame, "")
        self.details.pack(anchor="w", padx=space("page"), pady=(space("hair"), 0))
        self.notes = wrapping_label(self.frame, "")
        self.notes.pack(anchor="w", padx=space("page"), pady=(space("hair"), 0))
        self.use = ttk.Button(self.frame, text=T("tools.exprtest.use"), command=self.use_it)
        self.use.pack(anchor="w", padx=space("page"), pady=(space("row"), 0))
        add_tooltip(self.use, "tips.tools_exprtest_use")

        self._sync_kind()
        self.evaluate()

    # -- building ------------------------------------------------------------ #
    def _build_field_row(self, grid):
        ttk.Label(grid, text=T("tools.exprtest.field_label")).grid(
            row=0, column=0, sticky="w", padx=(0, space("tight")), pady=(0, space("tight")))
        values = [self.labels[key] for key in self.keys]
        self.field_var = tk.StringVar(value=self.labels[self.memory["field"]])
        picker = ttk.Combobox(grid, textvariable=self.field_var, values=values,
                              state="readonly", height=popdown_height(values),
                              width=popdown_width(values))
        picker.grid(row=0, column=1, sticky="w", pady=(0, space("tight")))
        picker.bind("<<ComboboxSelected>>", self._on_field, add="+")
        add_tooltip(picker, "tips.tools_exprtest_field")
        help_button(grid, self.app, "tools.exprtest.help_title", "tools.exprtest.help_body",
                    "tips.tools_exprtest_help").grid(row=0, column=2, sticky="e",
                                                     pady=(0, space("tight")))

    @staticmethod
    def _label(grid, key, row):
        label = ttk.Label(grid, text=T(key))
        label.grid(row=row, column=0, sticky="w", padx=(0, space("tight")),
                   pady=(0, space("tight")))
        return label

    def _entry(self, grid, name, tip_key, **options):
        """An entry bound to the remembered input ``name``. The caller places it."""
        entry = ttk.Entry(grid, textvariable=self.vars[name], **options)
        # Saved on EVERY key, not when the pause runs out: a language change inside
        # that quarter of a second rebuilds this panel, and the last word typed
        # would be gone.
        entry.bind("<KeyRelease>", lambda e: self._typed(name), add="+")
        entry.bind("<Return>", self.debounce.now, add="+")
        add_tooltip(entry, tip_key)
        return entry

    # -- reacting ------------------------------------------------------------ #
    def _typed(self, name):
        self.memory[name] = self.vars[name].get()
        self.debounce()

    def _on_field(self, event=None):
        unhighlight_combobox(event)      # readonly comboboxes stay "selected" otherwise
        key = self.by_label.get(self.field_var.get())
        if key is None:
            return
        self.memory["field"] = key
        self._sync_kind()
        self.debounce.now()

    def field_key(self):
        return self.memory["field"]

    def _sync_kind(self):
        """Name the value box for the chosen field; a pid only means something for a process."""
        kind = FIELDS[self.field_key()].expr_kind
        is_process = kind == KIND_PROCESS
        self.value_label.config(text=T(VALUE_LABELS.get(kind, VALUE_LABEL)))
        # Greyed rather than hidden, like a dormant field on the Control page: the
        # row keeps its shape when the field changes, and the grey says "not for
        # this one" instead of making a box appear and vanish under the pointer.
        self.pid.state(["!disabled"] if is_process else ["disabled"])
        self.pid_label.config(style="TLabel" if is_process else "Muted.TLabel")

    def evaluate(self):
        """Compute and show the verdict for what is typed now. Returns it."""
        verdict = exprtest.evaluate(self.field_key(), self.vars["expression"].get(),
                                    self.vars["value"].get(), self.vars["pid"].get())
        key, style = VERDICT_TEXT[verdict.state]
        self.verdict.config(text=T(key), style=style)
        self.details.config(text="\n".join(self._detail_lines(verdict)))
        self.notes.config(text="\n".join(self._note_lines(verdict)))
        self.use.state(["!disabled"] if self._usable(verdict) else ["disabled"])
        return verdict

    def _usable(self, verdict):
        return verdict.state in USABLE and bool(self.vars["expression"].get().strip())

    @staticmethod
    def _detail_lines(verdict):
        if verdict.state == exprtest.BAD_EXPRESSION:
            return [verdict.problem]
        lines = []
        if verdict.state == exprtest.BAD_VALUE:
            lines.append(T(verdict.problem_key, **dict(verdict.problem_args)))
        if verdict.selected_by:
            lines.append(T("tools.exprtest.selected_by", terms=", ".join(verdict.selected_by)))
        if verdict.excluded_by:
            lines.append(T("tools.exprtest.excluded_by", terms=", ".join(verdict.excluded_by)))
        if verdict.state == exprtest.NO_MATCH and not verdict.excluded_by:
            lines.append(T("tools.exprtest.no_term"))
        if (verdict.state == exprtest.MATCH and not verdict.everything
                and not verdict.selected_by):
            lines.append(T("tools.exprtest.not_excluded"))
        if verdict.canonical:
            lines.append(T("tools.exprtest.read_as", expression=verdict.canonical))
        return lines

    def _note_lines(self, verdict):
        if verdict.state == exprtest.BAD_EXPRESSION:
            return []
        lines = []
        if verdict.everything:
            lines.append(T("tools.exprtest.note_everything"))
        elif verdict.bounds_nothing:
            lines.append(T("tools.exprtest.note_bounds_nothing"))
        if FIELDS[self.field_key()].expr_kind == KIND_PROCESS:
            lines.append(T("tools.exprtest.note_process_tree"))
        return lines

    # -- acting -------------------------------------------------------------- #
    def use_it(self):
        """Put the tested expression into its Control field, replacing the value there."""
        verdict = self.evaluate()        # what is on screen NOW, not at the last pause
        if not self._usable(verdict):
            return
        key = self.field_key()
        fill_field(self.app, key, self.vars["expression"].get().strip(),
                   "log.tools_exprtest_filled", field=field_label(key))

    def teardown(self):
        self.debounce.cancel()
