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
        self._targets = []           # entries Enter walks, in page order
        self._at = 0                 # which one is current
        self._marks = []             # per target: (widget, kind, style it had)
        self._opened = set()         # sections the SEARCH opened, to close again
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
        # Applied only now, with the scroller and the form already built: putting
        # the bar BACK needs `before=` to name the scroller, and hiding it runs a
        # clear, which talks to the form. `_build_search_bar` packed it, so that
        # is the state this starts from.
        self._search_shown = True
        self._sync_search_visibility()
        # A query typed before a language switch (or before the window was
        # widened into two columns) is still in the box after the rebuild, so the
        # marks have to come back with it.
        if self._search_shown and _LAST_QUERY[0]:
            self.frame.after_idle(self._apply)

    # -- search -------------------------------------------------------------- #
    def _build_search_bar(self):
        """The bar sits on the RIGHT, against the page's own margin.

        On the left it read as a stray label floating above the first section with
        the whole width empty beside it. On the right it lines up with the page
        margin, sits clear of the eye's path down the first column, and lands
        where a find box is looked for.

        🔴 The BOX is what the eye calls "the search", so the box is what has to
        be flush with the margin. Measured on real Tk (1200x900): with the count
        pinned to the right the entry ended 65 px short of the section cards
        beside it, and a control that stops short of every other right edge on the
        page reads as something dropped on top of the page rather than part of it.
        So the count moved to the LEFT of the label, where it still cannot push
        anything around: everything right of it has a fixed width.

        Packed right to left: entry (against the margin), its label, the count,
        then the sentence that names another window - which is free to grow
        leftwards into empty space without moving anything.
        """
        bar = ttk.Frame(self.frame)
        self._bar = bar
        self._pack_bar()
        self.query_var = tk.StringVar(value=_LAST_QUERY[0])
        entry = ttk.Entry(bar, textvariable=self.query_var, width=24)
        entry.pack(side="right")
        self._count = ttk.Label(bar, text="", style="Muted.TLabel",
                                width=8, anchor="e")
        entry.bind("<KeyRelease>", self._on_key)
        entry.bind("<Return>", lambda e: self._step(1))
        entry.bind("<Shift-Return>", lambda e: self._step(-1))
        entry.bind("<Escape>", lambda e: self.clear())
        add_tooltip(entry, "tips.control_search", shortcut="Ctrl+F")
        self._entry = entry
        ttk.Label(bar, text=T("fields.search")).pack(side="right",
                                                    padx=(scaled(6), scaled(5)))
        self._count.pack(side="right")
        # Free to grow leftwards: "..." is in the Settings window, or "nothing
        # matches". Never to the right of the box, which must not move.
        self._note = ttk.Label(bar, text="", style="Muted.TLabel", anchor="e")
        self._note.pack(side="right", padx=(0, scaled(10)))
        # Bound on the ROOT through the shared dispatcher, for the same reason the
        # connection table does it: a shortcut that only works once the caret is
        # already in the box is not a shortcut. The dispatcher is what keeps the
        # two boxes from taking Ctrl+F away from each other.
        with crashlog.quiet("gui.pages.control"):
            from . import focus_search as _dispatch
            self.app.root.bind("<Control-f>", lambda e: _dispatch(self.app))
            self.app.root.bind("<Control-F>", lambda e: _dispatch(self.app))

    def _pack_bar(self, **extra):
        """Where the bar sits, in ONE place - it is packed twice.

        Once at build time and once when the preference brings it back, and two
        copies of these numbers would drift the day somebody tunes one of them.

        The padding is low rather than high on purpose: sitting under the tab
        strip with a wide gap below it, the bar looked attached to the tabs. Tight
        to the content it belongs to, it reads as the page's own header row.

        🔴 Bringing it back passes ``before=``. pack hands out space in CALL
        order, so a bar re-packed after the scroller exists would land UNDER the
        page body - and the fake tkinter cannot see that (it checks that
        ``before=`` names a sibling and keeps children in creation order), so this
        one is answered by a live render, not by the suite.
        """
        self._bar.pack(side="top", fill="x", padx=(scaled(12), scaled(14)),
                       pady=(scaled(12), scaled(3)), **extra)

    def search_is_visible(self):
        """Is the search bar on the page? (the preference, read live)"""
        return bool(self.app.pref("show_control_search"))

    def on_pref_changed(self, key):
        """A preference was written in the Settings window (see gui/pages)."""
        if key == "show_control_search":
            self._sync_search_visibility()

    def _sync_search_visibility(self):
        """Bring the bar in or out, once per actual change."""
        want = self.search_is_visible()
        if want == self._search_shown:
            return
        self._search_shown = want
        if want:
            self._pack_bar(before=self.scroll.vsb)
        else:
            self._hide_search()

    def _hide_search(self):
        """Take the bar away, and leave nothing of the search behind.

        Clearing first is not tidiness. The marks are painted on the FORM, not on
        the bar, so a query left standing would leave fields highlighted with no
        box left to clear them from - and the sections the search had unfolded
        would stay unfolded. A debounce still in flight would repaint both a
        moment after the bar was gone.
        """
        if self._job is not None:
            with crashlog.quiet("gui.pages.control"):
                self.frame.after_cancel(self._job)
            self._job = None
        self.query_var.set("")
        self._apply()               # unmarks, refolds, forgets the query
        with crashlog.quiet("gui.pages.control"):
            # Only if the caret is actually in there: typing into a widget that
            # is no longer on screen is the one way this could swallow keystrokes.
            if self.frame.focus_get() is self._entry:
                self.frame.focus_set()
        self._bar.pack_forget()

    def focus_search(self):
        """Put the caret in the box (the Ctrl+F path, see gui/app.py).

        ``False`` means "not available here": with the box switched off the
        dispatcher passes Ctrl+F on to the connection table, which is what the
        shortcut did from this page before it had a box at all.
        """
        if not self._search_shown:
            return False
        self._entry.focus_set()
        self._entry.select_range(0, "end")
        return True

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
        self._targets, self._marks = self._claim(here)
        self._at = 0
        if not query.strip():
            self._restore_folds()
            self._say("", "")
            return
        if self._targets:
            self._paint()
            self._reveal(self._targets[0])
        self._say(self._count_text(), self._note_text(elsewhere))

    def _claim(self, here):
        """Pair every hit with the widget that will show it - one widget, one hit.

        🔴 Two hits CAN land on the same widget: a dropdown field has no text of
        its own, so it marks its section header, and that header is often a hit in
        its own right (searching "ruch" matches the section AND the filter inside
        it). Measured on real Tk before this: the header was painted as the
        current hit and then repainted as an ordinary one by the later target, so
        "1 / 5" was shown with nothing filled anywhere - the count promising a
        place the eye could not find.

        The second claim on a widget is therefore dropped, which keeps the
        invariant this feature rests on: as many marks as the count says, each in
        its own place.
        """
        targets, marks, seen = [], [], []
        for entry in here:
            mark = self._mark(entry)
            if mark is None or any(mark[0] is widget for widget in seen):
                continue
            seen.append(mark[0])
            targets.append(entry)
            marks.append(mark)
        return targets, marks

    def _say(self, count, note):
        self._count.config(text=count)
        self._note.config(text=note)

    def _count_text(self):
        return "%d / %d" % (self._at + 1, len(self._targets)) if self._targets else ""

    def _note_text(self, elsewhere):
        if elsewhere:
            # Not a dead end: the field exists, it simply renders in another
            # window, and saying so is the whole point of indexing that surface.
            return T("fields.search_elsewhere", name=elsewhere[0].label)
        return "" if self._targets else T("fields.search_none")

    def _step(self, delta):
        """Next hit, wrapping. Enter forwards, Shift+Enter back."""
        if not self._targets:
            return
        self._at = (self._at + delta) % len(self._targets)
        self._paint()
        self._reveal(self._targets[self._at])
        self._count.config(text=self._count_text())

    def _widget_for(self, entry):
        if entry.kind == search.SECTION:
            panel = self.form.sections.get(entry.section_id)
            return panel.header if panel else None
        # A checkbox field has no separate label - the widget IS the label
        # (gui/form.py::_place_one), so fall back to the entry widget.
        return self.form.labels.get(entry.key) or self.form.entries.get(entry.key)

    def _mark(self, entry):
        """Claim the widget that will carry this hit: (widget, kind, old style).

        Which widget it is comes from the REGISTRY, not from asking the widget
        what it is - the fake Tk the tests run on has one widget class for
        everything, and more importantly the registry is where the answer belongs:

        * a field with a label of its own -> that label,
        * a checkbox field -> the checkbox, whose text IS its label,
        * anything else (a dropdown, or a section with no fields) -> the SECTION
          HEADER, because a hit the page cannot point at is a hit the user cannot
          see. This is the case that made the count lie: the traffic filter is a
          dropdown, so before this it was counted and never marked.
        """
        widget, kind = None, "label"
        if entry.kind == search.FIELD:
            widget = self.form.labels.get(entry.key)
            if widget is None:
                field = FIELDS.get(entry.key)
                if field is not None and field.kind == BOOL:
                    widget, kind = self.form.entries.get(entry.key), "check"
        if widget is None:
            panel = self.form.sections.get(entry.section_id)
            widget, kind = (panel.header if panel is not None else None), "section"
        if widget is None:
            return None
        with crashlog.quiet("gui.pages.control"):
            return (widget, kind, str(widget.cget("style") or ""))
        return None

    HIT_STYLES = {"label": ("Hit.TLabel", "HitDim.TLabel"),
                  "check": ("Hit.TCheckbutton", "HitDim.TCheckbutton"),
                  "section": ("Hit.Section.TButton", "HitDim.Section.TButton")}

    def _paint(self):
        """Fill the current hit, tint the rest.

        Every match looking identical is what made "3 / 7" useless: Enter moved
        the page and nothing on it said which one you had arrived at.
        """
        for index, mark in enumerate(self._marks):
            widget, kind, _old = mark
            current, other = self.HIT_STYLES[kind]
            with crashlog.quiet("gui.pages.control"):
                widget.configure(style=current if index == self._at else other)

    def _unmark(self):
        for widget, _kind, old in self._marks:
            # A widget destroyed by a rebuild cannot be put back, and that is not
            # a failure worth a dialog - but it is worth the crash log saying so.
            with crashlog.quiet("gui.pages.control"):
                widget.configure(style=old)
        self._marks = []
        # The style a field SHOULD have can have changed while it was marked (a
        # schedule taking over the rate fields greys their labels), so the form
        # gets the last word rather than the style we happened to remember.
        with crashlog.quiet("gui.pages.control"):
            self.form.apply_overrides()

    def _reveal(self, entry):
        """Open the section a hit sits in and scroll to it.

        🔴 `set_open`, never `toggle`: toggling runs the accordion's callback,
        which writes the fold state into `ui.json` through `App.on_sections_changed`
        - so searching would permanently unfold the sections the user had chosen
        to keep closed. What the search opened it closes again in
        `_restore_folds`.
        """
        panel = self.form.sections.get(entry.section_id)
        if panel is None:
            return
        if not panel.is_open:
            panel.set_open(True)
            # Track what the SEARCH opened rather than snapshotting what was
            # closed when it started: a user who opens a section by hand
            # mid-search means to keep it open, and a snapshot would fold it away
            # again the moment the box was cleared.
            self._opened.add(entry.section_id)
        widget = self._widget_for(entry) or panel.frame
        with crashlog.quiet("gui.pages.control"):
            self.frame.after_idle(lambda: self.scroll.ensure_visible(widget))

    def _restore_folds(self):
        for section_id in sorted(self._opened):
            panel = self.form.sections.get(section_id)
            if panel is not None and panel.is_open:
                panel.set_open(False)
        self._opened = set()

    def _reapply(self):
        """The form rebuilt itself (column switch): the marks referred to dead widgets.

        The rebuild reads the fold state back from the App, so whatever the search
        had opened is closed again by the rebuild itself - the page must forget it
        rather than trying to close it twice.
        """
        self._marks = []
        self._opened = set()
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
