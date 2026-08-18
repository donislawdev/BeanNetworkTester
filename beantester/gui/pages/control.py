"""Control page: the settings form (registry-driven) inside a scrollable body.

Contains no natively scrollable widget (no Treeview/Text), which is the rule
that keeps the mouse-wheel dispatcher unambiguous.

The search bar at the top marks and jumps; it never filters. Hiding what does
not match would fight two things this page already does: fields are packed
left-to-right in rows (so a hidden field leaves a hole in its row) and sections
are spread over two columns by weights computed at build time (so sections
disappearing rebalances the page under the reader). Marking keeps the page still
and keeps the user's sense of where things live - see `gui/form_search.py` for
what counts as a match.
"""
import tkinter as tk
from tkinter import ttk

from ... import crashlog
from ...fields import BOOL, FIELDS
from ...i18n import T
from .. import form_search as search
from ..form import ControlForm
from ..labels import wrapping_label
from ..scaling import scaled
from ..scrollable import ScrollableFrame
from ..theme import popdown_height, popdown_width
from ..tooltip import add_tooltip

# 🔴 The query lives here, at module level, on purpose. It must survive a rebuild
# of this page - a language switch rebuilds the whole UI, and crossing the
# two-column threshold rebuilds the form - and it must NOT survive closing the
# program (owner's decision, 2026-08-18: a search box that greets you with last
# week's word is a puzzle, not a convenience). A module global is exactly that
# lifetime. It is not on `App` because that file sits on the code-shape ratchet
# with zero headroom, and because the App has no other reason to know.
_LAST_QUERY = [""]

SEARCH_DEBOUNCE_MS = 120


class ControlPage:
    ID = "control"
    LABEL = "app.tabs.control"

    def __init__(self, app, parent):
        self.app = app
        self.frame = ttk.Frame(parent)
        # a hairline under the tab strip + a margin below it: the scrolled content
        # used to start flush against the tabs, so a half-scrolled header looked
        # like it was overlapping them
        rule = ttk.Frame(self.frame, style="Line.TFrame", height=max(1, scaled(1)))
        rule.pack(side="top", fill="x")
        rule.pack_propagate(False)
        # Search state, before the bar that writes it and the form it points into.
        self._index = search.build_index()
        self._targets = []           # entries the arrows walk, in page order
        self._at = 0                 # which one is current
        self._marked = []            # (widget, the style it had before)
        self._folds_before = None    # sections the user had closed, to put back
        self._job = None
        self._build_search_bar()
        self.scroll = ScrollableFrame(self.frame, top_margin=scaled(8))
        self.form = ControlForm(self.scroll.body, app, scroller=self.scroll,
                                on_rebuilt=self._reapply, extras={
            "target": self._build_target,
            "advanced": self._build_advanced,
            "repro": self._build_repro,
            "profiles": self._build_profiles,
        })
        app.form = self.form
        # A query typed before a language switch (or before the window was
        # widened into two columns) is still in the box after the rebuild, so the
        # marks have to come back with it.
        if _LAST_QUERY[0]:
            self.frame.after_idle(self._apply)

    # -- search -------------------------------------------------------------- #
    def _build_search_bar(self):
        bar = ttk.Frame(self.frame)
        bar.pack(side="top", fill="x", padx=scaled(10), pady=(scaled(7), 0))
        ttk.Label(bar, text=T("fields.search")).pack(side="left")
        self.query_var = tk.StringVar(value=_LAST_QUERY[0])
        entry = ttk.Entry(bar, textvariable=self.query_var, width=26)
        entry.pack(side="left", padx=(scaled(4), scaled(8)))
        entry.bind("<KeyRelease>", self._on_key)
        entry.bind("<Return>", lambda e: self._step(1))
        entry.bind("<Escape>", lambda e: self.clear())
        add_tooltip(entry, "tips.control_search", shortcut="Ctrl+F")
        self._entry = entry
        # Bound on the ROOT through the shared dispatcher, for the same reason the
        # connection table does it: a shortcut that only works once the caret is
        # already in the box is not a shortcut. The dispatcher is what keeps the
        # two boxes from taking Ctrl+F away from each other.
        with crashlog.quiet("gui.pages.control"):
            from . import focus_search as _dispatch
            self.app.root.bind("<Control-f>", lambda e: _dispatch(self.app))
            self.app.root.bind("<Control-F>", lambda e: _dispatch(self.app))
        # One line for both answers: "3 / 7" while there is something to walk, and
        # the sentence naming another window when the only match lives there.
        self._verdict = ttk.Label(bar, text="", style="Muted.TLabel")
        self._verdict.pack(side="left")

    def focus_search(self):
        """Put the caret in the box (the Ctrl+F path, see gui/app.py)."""
        self._entry.focus_set()
        self._entry.select_range(0, "end")

    def _on_key(self, event):
        # Enter and Escape have their own bindings; letting them through here
        # would re-run the search a second time on the same keystroke.
        if getattr(event, "keysym", "") in ("Return", "Escape"):
            return
        if self._job is not None:
            with crashlog.quiet("gui.pages.control"):
                self.frame.after_cancel(self._job)
        self._job = self.frame.after(SEARCH_DEBOUNCE_MS, self._apply)

    def clear(self):
        self.query_var.set("")
        self._apply()

    def _apply(self):
        """Mark what matches, reveal it, and say what was found. The whole feature."""
        self._job = None
        query = self.query_var.get()
        _LAST_QUERY[0] = query
        self._unmark()
        hits = search.find(self._index, query)
        here, elsewhere = search.summarise(hits)
        self._targets = self._jump_targets(here)
        self._at = 0
        if not query.strip():
            self._restore_folds()
            self._verdict.config(text="")
            return
        if self._folds_before is None:
            # Snapshot ONCE per search, not per keystroke: the second letter would
            # otherwise record the sections the first letter had just opened, and
            # clearing the box would leave the page unfolded for good.
            self._folds_before = [sid for sid, panel in self.form.sections.items()
                                  if not panel.is_open]
        for entry in here:
            self._mark(entry)
        if self._targets:
            self._reveal(self._targets[0])
        self._verdict.config(text=self._verdict_text(elsewhere))

    def _jump_targets(self, here):
        """What the arrows walk: fields, plus a section that has no field of its own.

        A section title matches its own fields too (they carry it in their
        haystack), so counting both would report "3" for a group with two fields
        and mark two - a number that does not match what the eye can see. Sections
        with no fields of their own (Profiles) still have to be reachable, so they
        stay in.
        """
        with_fields = {e.section_id for e in here if e.kind == search.FIELD}
        return [e for e in here
                if e.kind == search.FIELD or e.section_id not in with_fields]

    def _verdict_text(self, elsewhere):
        if self._targets:
            return "%d / %d" % (self._at + 1, len(self._targets))
        if elsewhere:
            # Not a dead end: the field exists, it simply renders in another
            # window, and saying so is the whole point of indexing that surface.
            return T("fields.search_elsewhere", name=elsewhere[0].label)
        return T("fields.search_none")

    def _step(self, delta):
        """Next hit, wrapping. Enter is the only key people try for this."""
        if not self._targets:
            return
        self._at = (self._at + delta) % len(self._targets)
        self._reveal(self._targets[self._at])
        self._verdict.config(text="%d / %d" % (self._at + 1, len(self._targets)))

    def _widget_for(self, entry):
        if entry.kind == search.SECTION:
            panel = self.form.sections.get(entry.section_id)
            return panel.header if panel else None
        # A checkbox field has no separate label - the widget IS the label
        # (gui/form.py::_place_one), so fall back to the entry widget.
        return self.form.labels.get(entry.key) or self.form.entries.get(entry.key)

    def _mark(self, entry):
        """Bold the words that matched. Which widget carries them comes from the
        REGISTRY, not from asking the widget what it is: a checkbox field has no
        separate label because its text IS the checkbox (gui/form.py::_place_one),
        and a filter dropdown has no text of its own at all - for that one the
        scroll is the whole answer.
        """
        if entry.kind != search.FIELD:
            return
        label = self.form.labels.get(entry.key)
        if label is not None:
            self._swap_style(label, "Hit.TLabel")
            return
        field = FIELDS.get(entry.key)
        if field is not None and field.kind == BOOL:
            widget = self.form.entries.get(entry.key)
            if widget is not None:
                self._swap_style(widget, "Hit.TCheckbutton")

    def _swap_style(self, widget, hit_style):
        with crashlog.quiet("gui.pages.control"):
            self._marked.append((widget, str(widget.cget("style") or "")))
            widget.configure(style=hit_style)

    def _unmark(self):
        for widget, style in self._marked:
            # A widget destroyed by a rebuild cannot be put back, and that is not
            # a failure worth a dialog - but it is worth the crash log saying so.
            with crashlog.quiet("gui.pages.control"):
                widget.configure(style=style)
        self._marked = []

    def _reveal(self, entry):
        """Open the section a hit sits in and scroll to it.

        🔴 `set_open`, never `toggle`: toggling runs the accordion's callback,
        which writes the fold state into `ui.json` through `App.on_sections_changed`
        - so searching would permanently unfold the sections the user had chosen
        to keep closed. The page opens them for the length of the search and puts
        them back in `_restore_folds`.
        """
        panel = self.form.sections.get(entry.section_id)
        if panel is None:
            return
        if not panel.is_open:
            panel.set_open(True)
        widget = self._widget_for(entry) or panel.frame
        try:
            self.frame.after_idle(lambda: self.scroll.ensure_visible(widget))
        except Exception:
            self.scroll.ensure_visible(widget)

    def _restore_folds(self):
        if self._folds_before is None:
            return
        for section_id in self._folds_before:
            panel = self.form.sections.get(section_id)
            if panel is not None and panel.is_open:
                panel.set_open(False)
        self._folds_before = None

    def _reapply(self):
        """The form rebuilt itself (column switch): the marks referred to dead widgets."""
        self._marked = []
        self._folds_before = None
        if _LAST_QUERY[0]:
            self._apply()

    # -- extra widgets referenced by fields.SECTIONS ------------------------- #
    def _build_target(self, body):
        """The "this target matches nothing" banner (packed only when it does)."""
        self.app.target_warning = wrapping_label(body, "", style="Bad.TLabel")
        # A rebuilt banner starts empty, so forget what the OLD one was showing -
        # otherwise the next _drain_target_warning() would see "no change" and the
        # warning would stay invisible for the rest of the session.
        self.app._shown_target_warning = None

    def _build_advanced(self, body):
        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x", pady=(scaled(6), 0))
        btn = ttk.Button(row, text=T("buttons.reset_now"), command=self.app.reset_now_click)
        btn.pack(side="left")
        add_tooltip(btn, "tips.reset_now")

    def _build_repro(self, body):
        app = self.app
        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x", pady=(scaled(6), 0))
        app.scenario_lbl = ttk.Label(row, text=T("fields.scenario_none"), style="Hint.TLabel")
        app.scenario_lbl.pack(side="left")
        loop = ttk.Checkbutton(row, text=T("fields.loop"), variable=app.loop_var)
        loop.pack(side="right")
        clear = ttk.Button(row, text=T("buttons.clear"), command=app.clear_scenario)
        clear.pack(side="right", padx=scaled(6))
        load = ttk.Button(row, text=T("buttons.load_scenario"), command=app.load_scenario)
        load.pack(side="right")
        for w in (loop, clear, load):
            add_tooltip(w, "tips.scenario")

    def _build_profiles(self, body):
        app = self.app
        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x", pady=(scaled(6), 0))
        # The SAME widget as the traffic filter, deliberately: a dropdown built
        # from a tk.Menu can never match a combobox popdown, because on Windows a
        # menu is a native Win32 popup - Tk styles reach the entries but not the
        # frame Windows draws around it (a light border), the width cannot be tied
        # to the button, and the current entry is not highlighted on open. Two
        # pickers sitting on the same page must not look like two different tools.
        # Group headings stay in the list and snap back when picked (see
        # App.load_selected_profile).
        names = app.profile_names()
        app.profile_cb = ttk.Combobox(row, textvariable=app.profile_var,
                                      values=names, state="readonly",
                                      width=popdown_width(names),
                                      height=popdown_height(names))
        app.profile_cb.bind("<<ComboboxSelected>>", app.on_profile_selected)
        app.profile_cb.pack(side="left")
        save = ttk.Button(row, text=T("buttons.save_as"), command=app.save_profile)
        save.pack(side="left", padx=scaled(6))
        delete = ttk.Button(row, text=T("buttons.delete"), command=app.delete_profile)
        delete.pack(side="left")
        app.btn_delete_profile = delete
        add_tooltip(app.profile_cb, "tips.profiles")
        add_tooltip(save, "tips.save_profile")
        add_tooltip(delete, "tips.delete_profile")

    # -- lifecycle ----------------------------------------------------------- #
    def refresh(self):
        pass
