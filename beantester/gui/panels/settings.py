"""The "Settings" window: app/view preferences, away from the traffic scenario.

Two kinds of setting live here, on purpose:

* **Registry fields marked ``surface="settings"``** (today: the table row limit).
  These are engine-adjacent view knobs - they have a CLI flag, a default, and they
  travel inside a saved config file. Rendered by the same ``ControlForm`` as the
  Control page.
* **GUI preferences** (``gui/prefs.py``): language, chart history, log length, the
  close-confirm switch, restore-last-profile, and the reset-layout action. These
  are NOT engine settings - they persist in ``*_ui.json`` and must survive a
  restart without being dragged into a traffic config file. Rendered here.

Adding a preference is one ``Pref`` entry (plus its i18n keys); this window renders
it, validates it and persists it through ``App.set_pref``.
"""
import tkinter as tk
from tkinter import ttk

from ...fields import SETTINGS_SECTIONS
from ...i18n import T, available_languages
from ...utils import number_string
from ...validators import parse_number
from ..accordion import CollapsibleSection
from ..form import ControlForm
from ..labels import wrapping_label
from ..prefs import ACTION, BOOL, NUMBER, PREF_GROUPS, PREFS_BY_KEY
from ..scaling import scaled
from ..theme import popdown_height, unhighlight_combobox
from ..tooltip import add_tooltip
from ..windows import PanelWindow, register_window


@register_window
class SettingsWindow(PanelWindow):
    """Language, the settings-surface registry fields, and the GUI preferences."""

    ID = "settings"
    TITLE = "windows.settings"
    SIZE = (520, 520)

    def build(self, body):
        pad = scaled(12)
        app = self.app
        self._pref_vars = {}
        self._pref_entries = {}
        self._pref_errors = {}      # group label -> (error label, its number keys)
        self._pref_messages = {}    # pref key -> live validation message

        # -- language (not a registry field: it lives in *_ui.json) ------------ #
        lang_row = ttk.Frame(body)
        lang_row.pack(side="top", fill="x", padx=pad, pady=(pad, scaled(6)))
        ttk.Label(lang_row, text=T("app.language_label")).pack(side="left")
        names = [name for _, name in available_languages()]
        cb = ttk.Combobox(lang_row, textvariable=app.lang_var, values=names,
                          state="disabled" if app.running else "readonly",
                          width=14, height=popdown_height(names))
        cb.pack(side="left", padx=(scaled(8), 0))
        # Switching the language rebuilds the whole UI (and this window with it),
        # so it is not safe mid-session - locked exactly like on the header before.
        cb.bind("<<ComboboxSelected>>",
                lambda e: (unhighlight_combobox(e), app._switch_language()))
        add_tooltip(cb, "tips.language")
        # The App drives the mid-session lock through this handle (guarded for the
        # window being closed - see App._sync_running_chrome).
        app.lang_cb = cb

        rule = ttk.Frame(body, style="Line.TFrame", height=max(1, scaled(1)))
        rule.pack(side="top", fill="x", padx=pad, pady=(0, scaled(4)))
        rule.pack_propagate(False)

        # -- registry fields (surface="settings") ----------------------------- #
        # Same ControlForm as the Control page, pointed at the settings sections.
        # Shared app.vars keep both forms in sync, so a value loaded from a config
        # file updates here too, live. The form's host packs itself expand=True
        # (it fills the scrollable Control page); wrap it in a fill="x" holder so it
        # does not grab the leftover height here and leave a gap before the prefs.
        form_holder = ttk.Frame(body)
        form_holder.pack(side="top", fill="x")
        self.form = ControlForm(form_holder, app, sections=SETTINGS_SECTIONS,
                                collapsible=False)

        # -- GUI preferences (ui.json-backed, see gui/prefs.py) --------------- #
        for group_label, keys in PREF_GROUPS:
            self._build_pref_group(body, group_label, keys)

        foot = ttk.Frame(body)
        foot.pack(side="bottom", fill="x", padx=pad, pady=pad)
        ttk.Button(foot, text=T("buttons.close"), command=self.close).pack(side="right")

    # -- preference rows ------------------------------------------------------- #
    def _build_pref_group(self, body, group_label, keys):
        panel = CollapsibleSection(body, T(group_label), is_open=True, on_toggle=None)
        panel.pack()
        for key in keys:
            self._build_pref_row(panel.body, PREFS_BY_KEY[key])
        numbers = tuple(k for k in keys if PREFS_BY_KEY[k].kind == NUMBER)
        if numbers:
            # Same error line the registry fields get from ControlForm: packed only
            # while it says something, so the card does not reserve a blank row.
            err = wrapping_label(panel.body, "", style="Bad.TLabel")
            self._pref_errors[group_label] = (err, numbers)

    def _build_pref_row(self, card, pref):
        app = self.app
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(0, scaled(5)))

        if pref.kind == BOOL:
            var = tk.BooleanVar(value=bool(app.pref(pref.key)))
            chk = ttk.Checkbutton(
                row, text=T(pref.label), variable=var,
                command=lambda k=pref.key, v=var: app.set_pref(k, bool(v.get())))
            chk.pack(side="left", anchor="w")
            add_tooltip(chk, pref.tip)
            self._pref_vars[pref.key] = var
            return

        if pref.kind == ACTION:
            btn = ttk.Button(row, text=T(pref.label),
                             command=lambda p=pref: getattr(app, p.action)())
            btn.pack(side="left")
            add_tooltip(btn, pref.tip)
            return

        # NUMBER: label | entry | unit | hint, with live validation like the form
        label = ttk.Label(row, text=T(pref.label), style="Card.TLabel")
        label.pack(side="left", padx=(0, scaled(6)))
        var = tk.StringVar(value=number_string(app.pref(pref.key)))
        entry = ttk.Entry(row, textvariable=var, width=pref.width)
        entry.pack(side="left")
        add_tooltip(entry, pref.tip)
        add_tooltip(label, pref.tip)
        if pref.unit_key:
            ttk.Label(row, text=T(pref.unit_key), style="Unit.TLabel").pack(
                side="left", padx=(scaled(5), 0))
        if pref.hint:
            ttk.Label(row, text=T(pref.hint), style="Hint.TLabel").pack(
                side="left", padx=(scaled(8), 0))
        self._pref_vars[pref.key] = var
        self._pref_entries[pref.key] = entry
        handler = lambda e=None, p=pref: self._on_pref_number(p)
        entry.bind("<KeyRelease>", handler, add="+")
        entry.bind("<FocusOut>", handler, add="+")

    def _on_pref_number(self, pref):
        """Validate a numeric preference and persist it; a bad value (out of range
        or not a number) paints the field red and SAYS WHY, instead of storing
        garbage. The red border alone never named the allowed range - the registry
        fields above it did, which made the same mistake look like two bugs."""
        var = self._pref_vars[pref.key]
        entry = self._pref_entries[pref.key]
        try:
            value = parse_number(str(var.get()).strip(), pref.label, pref.bounds)
        except ValueError as exc:
            entry.config(style="Bad.TEntry")
            self._pref_messages[pref.key] = str(exc)
        else:
            entry.config(style="TEntry")
            self._pref_messages.pop(pref.key, None)
            self.app.set_pref(
                pref.key, int(value) if float(value).is_integer() else value)
        self._show_pref_errors()

    def _show_pref_errors(self):
        """List every live reason under its group, the way ControlForm does."""
        for err, keys in self._pref_errors.values():
            messages = [self._pref_messages[k] for k in keys
                        if k in self._pref_messages]
            if messages:
                err.config(text="  •  ".join(messages))
                if not err.winfo_ismapped():
                    err.pack(fill="x", pady=(scaled(5), 0))
            else:
                err.config(text="")
                err.pack_forget()

    def close(self):
        # Drop the App's handle to our language box before the widgets die, so
        # a start/stop with the window closed does not poke a dead widget.
        if getattr(self.app, "lang_cb", None) is not None:
            self.app.lang_cb = None
        super().close()
