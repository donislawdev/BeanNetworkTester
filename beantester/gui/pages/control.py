"""Control page: the settings form (registry-driven) inside a scrollable body.

Contains no natively scrollable widget (no Treeview/Text), which is the rule
that keeps the mouse-wheel dispatcher unambiguous.
"""
from tkinter import ttk

from ...i18n import T
from ..form import ControlForm
from ..labels import wrapping_label
from ..scaling import scaled
from ..scrollable import ScrollableFrame
from ..theme import popdown_height
from ..tooltip import add_tooltip


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
        self.scroll = ScrollableFrame(self.frame, top_margin=scaled(8))
        self.form = ControlForm(self.scroll.body, app, scroller=self.scroll, extras={
            "target": self._build_target,
            "advanced": self._build_advanced,
            "repro": self._build_repro,
            "profiles": self._build_profiles,
        })
        app.form = self.form

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
                                      values=names, state="readonly", width=24,
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
