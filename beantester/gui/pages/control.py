"""Control page: the settings form (registry-driven) inside a scrollable body.

Contains no natively scrollable widget (no Treeview/Text), which is the rule
that keeps the mouse-wheel dispatcher unambiguous.
"""
import tkinter as tk
from tkinter import ttk

from ...i18n import T
from ..form import ControlForm
from ..labels import wrapping_label
from ..scaling import scaled
from ..scrollable import ScrollableFrame
from ..theme import style_menu
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
        # A grouped MENU, not a combobox: "-- presets --" / "-- mine --" are group
        # headings, and a menu can render them disabled so they cannot be picked.
        # The combobox listed them as ordinary options that silently snapped back.
        app.profile_mb = ttk.Menubutton(row, textvariable=app.profile_var,
                                        width=24, direction="below",
                                        style="Profile.TMenubutton")
        app.profile_menu = style_menu(tk.Menu(app.profile_mb, tearoff=0),
                                      like_combobox=True)
        app.profile_mb["menu"] = app.profile_menu
        # Post the menu ourselves on click: a ttk.Menubutton posts on mouse-down
        # and the quick release can toggle it straight back shut, which is the
        # intermittent "the profile dropdown would not open". Doing it explicitly
        # is deterministic and rebuilds the list so it is always current.
        app.profile_mb.bind("<Button-1>", app._post_profile_menu)
        app.profile_mb.pack(side="left")
        save = ttk.Button(row, text=T("buttons.save_as"), command=app.save_profile)
        save.pack(side="left", padx=scaled(6))
        delete = ttk.Button(row, text=T("buttons.delete"), command=app.delete_profile)
        delete.pack(side="left")
        app.btn_delete_profile = delete
        add_tooltip(app.profile_mb, "tips.profiles")
        add_tooltip(save, "tips.save_profile")
        add_tooltip(delete, "tips.delete_profile")

    # -- lifecycle ----------------------------------------------------------- #
    def refresh(self):
        pass
