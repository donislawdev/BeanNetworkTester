"""Registry-driven form: renders ``fields.SECTIONS`` / ``fields.FIELD_DEFS``.

The Control page used to be ~180 lines of hand-placed widgets, and every new
setting meant editing the builder, the reader, the writer, the profile-scope
tuple and the summary. Now the form is a *renderer* of the field registry: one
entry in ``fields.py`` produces the widget, its label, its unit, its tooltip,
its live validation and its profile scope.

Layout note: fields are packed left-to-right in compact rows (label | entry |
unit), N per row as declared by the section. An earlier version used a grid with
weighted entry columns, which stretched the gap between a field and its unit
across the whole window and made the page look scattered.

Live validation is uniform: expressions go through ``matchers.parse_matcher``
and numbers through ``validators.parse_number``, which also checks the declared
bounds - so ``loss = 250`` is rejected in the field instead of being silently
clamped inside the engine.
"""
import tkinter as tk
from tkinter import ttk

from .. import fields as F
from ..fields import CONTROL_SECTIONS, FIELDS, SECTIONS
from ..filters import i18n_keys
from ..i18n import T
from ..matchers import parse_matcher
from ..settings import parse_schedule
from ..utils import number_string
from ..validators import parse_number, parse_seed
from . import dialogs
from .accordion import CollapsibleSection
from .labels import wrapping_label
from .scaling import scaled
from .theme import unhighlight_combobox
from .tooltip import add_tooltip
from .. import crashlog

SECTION_BY_ID = {s.id: s for s in SECTIONS}
SPAN_KINDS = (F.CHOICE, F.BOOL, F.EXPR, F.SCHEDULE)
VALIDATED_KINDS = (F.NUMBER, F.EXPR, F.SCHEDULE, F.SEED)

# Below this width a second column of sections would squeeze the wider rows
# (e.g. the three impairment fields) - so the page stays single-column on a
# small window and only spreads out when there is room (maximised / big screen).
TWO_COLUMN_WIDTH = 940


def columns_for(width, scale_px):
    """How many section columns fit into ``width`` px. Pure, so it is testable."""
    return 2 if int(width) >= scale_px(TWO_COLUMN_WIDTH) else 1


class ControlForm:
    """Builds the Control-page form and owns its widgets (not its state).

    The tk variables live on the ``App`` (``app.vars`` / ``app.toggles``) so the
    rest of the app keeps working with plain settings keys.
    """

    def __init__(self, parent, app, extras=None, scroller=None, sections=None,
                 collapsible=True):
        self.app = app
        self.parent = parent
        self.extras = extras or {}
        self.scroller = scroller        # the ScrollableFrame the form lives in
        # Which registry sections this form renders. The Control page passes the
        # default (CONTROL_SECTIONS); the Settings window passes SETTINGS_SECTIONS.
        self._sections = CONTROL_SECTIONS if sections is None else tuple(sections)
        # The Control page folds sections and remembers the state; the Settings
        # window renders them always-open and does NOT touch the shared collapse
        # state (two forms writing app.collapsed_sections would clobber each other,
        # and hiding the one field behind a fold is friction in a focused window).
        self._collapsible = collapsible
        self.sections = {}          # id -> CollapsibleSection
        self.entries = {}           # settings key -> widget
        self.labels = {}            # settings key -> its label widget
        self.errors = {}            # section id -> error label (packed only when set)
        self.notes = {}             # section id -> override note label
        self.helps = {}             # settings key -> its "?" cheat-sheet button
        self._invalid = set()       # section ids whose fields currently fail validation
        self.columns = 1
        self.column_frames = []
        self._relayout_job = None
        self.host = ttk.Frame(parent)
        self.host.pack(fill="both", expand=True)
        self._build()
        self.host.bind("<Configure>", self._on_host_configure)

    # -- construction -------------------------------------------------------- #
    def _build(self):
        app = self.app
        self.sections, self.entries, self.labels = {}, {}, {}
        self.errors, self.notes, self.helps = {}, {}, {}

        # Real column FRAMES, not grid columns: in a grid the row height is
        # shared across columns, so one tall section on the left blew a hole
        # under the section next to it on the right.
        self.column_frames = []
        for index in range(self.columns):
            frame = ttk.Frame(self.host)
            frame.pack(side="left", fill="both", expand=True, anchor="n",
                       padx=(0, scaled(10) if index < self.columns - 1 else 0))
            self.column_frames.append(frame)
        assignment = self._assign_columns()

        for sec in self._sections:
            panel = CollapsibleSection(
                self.column_frames[assignment[sec.id]], T(sec.label),
                is_open=(sec.id not in app.collapsed_sections
                         if self._collapsible else True),
                on_toggle=self._on_section_toggle if self._collapsible else None)
            panel.pack()
            self.sections[sec.id] = panel
            body = panel.body

            if sec.toggle:
                var = app.toggles[sec.id]
                chk = ttk.Checkbutton(body, text=T(sec.toggle), variable=var,
                                      command=lambda s=sec.id: self._on_toggle(s))
                chk.pack(anchor="w", pady=(0, scaled(4)))

            if sec.fields:
                self._place_fields(body, sec)
                if any(FIELDS[k].overridden_by or FIELDS[k].start_only
                       for k in sec.fields):
                    # wrapping, not a fixed 560 px: a long note (or a longer
                    # translation) was simply CUT at the panel edge. Shows either
                    # the override reason (schedule) or the "locked mid-session"
                    # reason for start-only fields - which a disabled widget cannot
                    # explain itself, because ttk sends it no hover event.
                    note = wrapping_label(body, "", style="Hint.TLabel")
                    # Packed ONCE, up front, and kept mapped for the section's life:
                    # an empty ttk.Label reserves the same one-line height as a full
                    # one, so toggling only its TEXT (below) never changes the section
                    # height. Packing/forgetting it on every START/STOP instead made
                    # the whole scrolled form reflow and visibly jump (the note line
                    # appears when a start-only field locks mid-session).
                    note.pack(fill="x", pady=(scaled(5), 0))
                    self.notes[sec.id] = note
                if any(FIELDS[k].kind in VALIDATED_KINDS for k in sec.fields):
                    err = wrapping_label(body, "", style="Bad.TLabel")
                    self.errors[sec.id] = err          # packed only when non-empty

            builder = self.extras.get(sec.extra) if sec.extra else None
            if builder:
                builder(body)

        for sec in self._sections:
            if sec.toggle:
                self._apply_toggle_state(sec.id)
        self.apply_overrides()
        self.validate_all()

    def _rows_of(self, sec):
        """Group a section's fields into rows of ``sec.columns`` (span = own row)."""
        rows, current = [], []
        for key in sec.fields:
            field = FIELDS[key]
            if field.span or field.kind in SPAN_KINDS:
                if current:
                    rows.append(current)
                    current = []
                rows.append([field])
                continue
            current.append(field)
            if len(current) >= max(1, sec.columns):
                rows.append(current)
                current = []
        if current:
            rows.append(current)
        return rows

    def _place_fields(self, body, sec):
        rows = self._rows_of(sec)
        for index, row_fields in enumerate(rows):
            row = ttk.Frame(body, style="Card.TFrame")
            row.pack(fill="x", pady=(0 if index == 0 else scaled(5), 0))
            for field in row_fields:
                self._place_one(row, field, sec)

    def _place_one(self, row, field, sec):
        app = self.app

        if field.kind == F.BOOL:
            widget = ttk.Checkbutton(row, text=T(field.label),
                                     variable=app.vars[field.key],
                                     command=app.on_form_changed)
            widget.pack(side="left", anchor="w")
            add_tooltip(widget, field.tip)
            self.entries[field.key] = widget
            return

        if field.kind == F.CHOICE:
            names = i18n_keys()
            display = [T(n) for n in names]
            app.filter_display = display
            app.filter_canon = names
            var = app.vars[field.key]
            if var.get() not in display:
                var.set(display[0])
            # height = item count: a short list must not spawn a popdown scrollbar
            # (it renders as a light bar against the near-black dropdown - an eyesore
            # for a list that fits without scrolling)
            widget = ttk.Combobox(row, textvariable=var, values=display,
                                  state="readonly", height=len(display))
            widget.pack(side="left", fill="x", expand=True)
            widget.bind("<<ComboboxSelected>>", self._on_choice, add="+")
            add_tooltip(widget, field.tip)
            self.entries[field.key] = widget
            app.filter_cb = widget
            return

        span = field.span or field.kind in SPAN_KINDS
        cell = ttk.Frame(row, style="Card.TFrame")
        cell.pack(side="left", fill="x", expand=span,
                  padx=(0, scaled(6) if span else scaled(22)))

        label = ttk.Label(cell, text=T(field.label), style="Card.TLabel")
        label.pack(side="left", padx=(0, scaled(6)))
        self.labels[field.key] = label

        entry = ttk.Entry(cell, textvariable=app.vars[field.key], width=field.width)
        entry.pack(side="left", fill="x", expand=span)
        self.entries[field.key] = entry
        add_tooltip(label, field.tip)
        add_tooltip(entry, field.tip)

        unit = field.unit or (T(field.unit_key) if field.unit_key else "")
        if unit:
            ttk.Label(cell, text=unit, style="Unit.TLabel").pack(
                side="left", padx=(scaled(5), 0))
        if field.kind == F.EXPR:
            # A real BUTTON, not a label that merely looks clickable: hovering it
            # shows the short tip, clicking it opens the full cheat sheet (which
            # is exactly what the pointer-shaped cursor was promising all along).
            help_btn = ttk.Button(cell, text=T("fields.match_help"),
                                  style="Help.TButton", width=2,
                                  command=self._show_match_help)
            help_btn.pack(side="left", padx=(scaled(8), 0))
            add_tooltip(help_btn, "tips.match_syntax")
            self.helps[field.key] = help_btn
        elif field.help_body:
            # Same "?" affordance for any registry field that declares its own
            # help sheet (not only filter expressions): hover shows the short tip,
            # a click opens the full explanation via dialogs.show_help.
            help_btn = ttk.Button(cell, text=T("fields.match_help"),
                                  style="Help.TButton", width=2,
                                  command=lambda f=field: self._show_field_help(f))
            help_btn.pack(side="left", padx=(scaled(8), 0))
            add_tooltip(help_btn, field.tip)
            self.helps[field.key] = help_btn
        if field.hint:
            ttk.Label(cell, text=T(field.hint), style="Hint.TLabel").pack(
                side="left", padx=(scaled(8), 0))

        entry.bind("<KeyRelease>", lambda e, s=sec.id: self._on_edit(s), add="+")
        entry.bind("<FocusOut>", lambda e, s=sec.id: self._on_edit(s), add="+")

    # -- events -------------------------------------------------------------- #
    def _show_match_help(self):
        dialogs.show_help(self.app.root, T("dialogs.match_help_title"),
                          T("dialogs.match_help"))

    def _show_field_help(self, field):
        """Open the "?" help sheet a field declares (help_title / help_body)."""
        dialogs.show_help(self.app.root, T(field.help_title), T(field.help_body))

    def _on_choice(self, event):
        unhighlight_combobox(event)      # readonly comboboxes stay "selected" otherwise
        self.app.on_form_changed()

    def _on_edit(self, section_id):
        self.validate_section(section_id)
        self.apply_overrides()
        self.app.on_form_changed()

    def _on_toggle(self, section_id):
        self._apply_toggle_state(section_id)
        self.validate_section(section_id)
        self.app.on_form_changed()

    def _on_section_toggle(self, panel):
        self.app.on_sections_changed(
            [sid for sid, p in self.sections.items() if not p.is_open])
        if panel.is_open and self.scroller is not None:
            # after_idle: let the layout settle before measuring where it landed
            try:
                self.host.after_idle(lambda: self.scroller.ensure_visible(panel.frame))
            except Exception:
                self.scroller.ensure_visible(panel.frame)

    # -- responsive section layout ------------------------------------------- #
    def _weight(self, sec):
        """Rough height of a section, used to balance the columns."""
        rows = len(self._rows_of(sec)) if sec.fields else 0
        return 2 + rows + (1 if sec.toggle else 0) + (1 if sec.extra else 0)

    def _assign_columns(self):
        """Spread the sections over the columns, keeping them roughly even."""
        if self.columns <= 1:
            return {sec.id: 0 for sec in self._sections}
        heights = [0] * self.columns
        assignment = {}
        for sec in self._sections:
            target = heights.index(min(heights))
            assignment[sec.id] = target
            heights[target] += self._weight(sec)
        return assignment

    def _on_host_configure(self, event):
        want = columns_for(getattr(event, "width", 0) or 0, scaled)
        if want == self.columns:
            return
        if self._relayout_job is not None:
            try:
                self.host.after_cancel(self._relayout_job)
            except Exception as _exc:
                crashlog.note(_exc, "gui.form")
        try:
            self._relayout_job = self.host.after(
                80, lambda n=want: self.set_columns(n))
        except Exception:
            self._relayout_job = None
            self.set_columns(want)

    def set_columns(self, columns):
        """Switch between one and two columns.

        Tk cannot re-parent a widget, so crossing the threshold rebuilds the
        form. That is cheap and safe: every value lives in ``app.vars`` /
        ``app.toggles``, which survive the rebuild, exactly like a language switch.
        """
        self._relayout_job = None
        columns = max(1, min(2, int(columns)))
        if columns == self.columns:
            return
        self.columns = columns
        for child in list(self.host.winfo_children()):
            child.destroy()
        self._build()
        self.app.set_filter_cli_key(self.app._filter_key)

    def _apply_toggle_state(self, section_id):
        """Grey out a section whose 'enable' box is unchecked.

        ttk does not do this for free: without an explicit state change (and the
        ``disabled`` maps in ``theme.py``) an inactive field looks exactly like a
        live one, and the user cannot tell whether it does anything.
        """
        sec = SECTION_BY_ID[section_id]
        enabled = bool(self.app.toggles[section_id].get()) if sec.toggle else True
        for key in sec.fields:
            entry = self.entries.get(key)
            if entry is not None:
                try:
                    entry.config(state=("normal" if enabled else "disabled"))
                except tk.TclError as _exc:
                    crashlog.note(_exc, "gui.form")
            label = self.labels.get(key)
            if label is not None:
                try:
                    label.config(style="Card.TLabel" if enabled else "CardOff.TLabel")
                except tk.TclError as _exc:
                    crashlog.note(_exc, "gui.form")

    def is_locked(self, key):
        """True when a field is applied at START only and a session is running.

        The traffic filter has always been locked mid-session (it is consumed by
        ``BeanEngine.start()``); "Run time" is consumed by the very same call and
        was left editable, so it looked like it could still move the deadline.
        """
        return bool(FIELDS[key].start_only and getattr(self.app, "running", False))

    def is_overridden(self, key):
        """True when another field currently takes precedence over ``key``."""
        field = FIELDS[key]
        source = F.overriding_field(field)
        if source is None:
            return False
        var = self.app.vars.get(source.key)
        return bool(var is not None and F.is_active(source, var.get()))

    def apply_overrides(self):
        """Decide, in ONE place, which fields are live right now.

        A field is dead when another field has taken it over (a throughput
        schedule replaces the constant Download/Upload limits) or when it only
        applies at START and a session is running (the traffic filter, "Run
        time"). Either way it must LOOK dead: ttk will not do that for free, and
        an editable field that changes nothing is a lie about what the tool is
        doing.
        """
        for sec in self._sections:
            note_keys = []
            for key in sec.fields:
                field = FIELDS[key]
                if not (field.overridden_by or field.start_only):
                    continue
                overridden = self.is_overridden(key)
                locked = self.is_locked(key)
                dead = overridden or locked
                if overridden and field.override_note:
                    note_keys.append(field.override_note)
                elif locked:
                    note_keys.append("fields.locked_running")
                entry = self.entries.get(key)
                if entry is not None and field.kind != F.CHOICE:   # the combobox
                    try:                                           # is owned by App
                        entry.config(state="disabled" if dead else "normal")
                    except tk.TclError as _exc:
                        crashlog.note(_exc, "gui.form")
                label = self.labels.get(key)
                if label is not None:
                    try:
                        label.config(style="CardOff.TLabel" if dead else "Card.TLabel")
                    except tk.TclError as _exc:
                        crashlog.note(_exc, "gui.form")
            note = self.notes.get(sec.id)
            if note is None:
                continue
            # The label stays mapped (see _place_fields); only its text changes, so
            # the section keeps a constant height and the form does not jump.
            try:
                note.config(text=T(note_keys[0]) if note_keys else "")
            except tk.TclError as _exc:
                crashlog.note(_exc, "gui.form")

    # kept as the name the App calls after every start/stop
    refresh_field_states = apply_overrides

    def section_enabled(self, section_id):
        sec = SECTION_BY_ID.get(section_id)
        if sec is None or not sec.toggle:
            return True
        var = self.app.toggles.get(section_id)
        return bool(var.get()) if var is not None else False

    # -- validation ---------------------------------------------------------- #
    def validate_section(self, section_id):
        """Validate one section; paint bad fields red and list every reason."""
        sec = SECTION_BY_ID.get(section_id)
        err_label = self.errors.get(section_id)
        if sec is None or err_label is None:
            return []
        messages = []
        enabled = self.section_enabled(section_id)
        for key in sec.fields:
            field = FIELDS[key]
            entry = self.entries.get(key)
            if entry is None or field.kind in (F.BOOL, F.CHOICE):
                continue
            if not enabled or self.is_overridden(key) or self.is_locked(key):
                self._mark(entry, ok=True)
                continue
            text = str(self.app.vars[key].get()).strip()
            try:
                self._parse(field, text)
                self._mark(entry, ok=True)
            except ValueError as e:
                self._mark(entry, ok=False)
                messages.append(str(e))
        try:
            if messages:
                err_label.config(text="  \u2022  ".join(messages))
                if not err_label.winfo_ismapped():
                    err_label.pack(fill="x", pady=(scaled(5), 0))
            else:
                err_label.config(text="")
                err_label.pack_forget()
        except tk.TclError as _exc:
            crashlog.note(_exc, "gui.form")
        if messages:
            self._invalid.add(section_id)
        else:
            self._invalid.discard(section_id)
        return messages

    def has_errors(self):
        """True when any field currently fails live validation.

        Drives START: a value the engine would reject should not launch a session
        only to fail in a dialog - the bad field is already flagged red.
        """
        return bool(self._invalid)

    @staticmethod
    def _parse(field, text):
        if field.kind == F.NUMBER:
            parse_number(text, field.label, field.bounds)
        elif field.kind == F.EXPR:
            if text:
                parse_matcher(text, field.expr_kind, field.label, field.bounds)
        elif field.kind == F.SCHEDULE:
            if text:
                parse_schedule(text)
        elif field.kind == F.SEED:
            parse_seed(text)

    @staticmethod
    def _mark(entry, ok):
        try:
            entry.config(style="TEntry" if ok else "Bad.TEntry")
        except tk.TclError as _exc:
            crashlog.note(_exc, "gui.form")

    def validate_all(self):
        messages = []
        for sec in self._sections:
            if sec.fields:
                messages += self.validate_section(sec.id)
        return messages

    def set_values(self, settings):
        """Push a settings dict into the widgets (and refresh toggles/validation)."""
        app = self.app
        for field in FIELDS.values():
            if field.key not in app.vars:
                continue
            value = settings.get(field.key)
            var = app.vars[field.key]
            if field.kind == F.BOOL:
                var.set(bool(value))
            elif field.kind == F.CHOICE:
                app.set_filter_cli_key(str(value or "both"))
            elif field.kind == F.SEED:
                var.set("" if value in (None, -1, "", "-1") else str(value))
            elif field.kind == F.NUMBER:
                var.set(number_string(value))
            else:
                var.set("" if value is None else str(value))
        for sec in self._sections:
            if not sec.toggle:
                continue
            # Turn a section ON when the incoming settings actually use it, but
            # never turn it OFF: the checkbox is the user's switch (on by
            # default), and loading a config without a target must not silently
            # flip it off under them.
            if any(F.is_active(FIELDS[k], settings.get(k, "")) for k in sec.fields):
                app.toggles[sec.id].set(True)
            self._apply_toggle_state(sec.id)
        self.apply_overrides()
        self.validate_all()
