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
from ...filters import narrowed_filter, windivert_for
from ...i18n import T, available_languages
from ...matchers import KIND_INT, KIND_IP, PORT_BOUNDS, parse_matcher, port_expression
from ...settings import setting_expression
from ...utils import number_string
from ...validators import parse_number
from ..accordion import CollapsibleSection
from ..form import ControlForm
from ..labels import wrapping_label
from ..prefs import ACTION, BOOL, NUMBER, PREF_GROUPS, PREFS_BY_KEY, prefs_in_section
from ..scaling import scaled
from ..scrollable import ScrollableFrame
from ..theme import popdown_height, unhighlight_combobox
from ..tooltip import add_tooltip
from ..windows import PanelWindow, register_window
from ... import crashlog


@register_window
class SettingsWindow(PanelWindow):
    """Language, the settings-surface registry fields, and the GUI preferences."""

    ID = "settings"
    TITLE = "windows.settings"
    # Grown from 520x520 when the Scope card arrived. Height is the binding
    # dimension: reserving the footer (below) means the CONTENT is what runs out
    # of room, so a card too many simply pushed the last group off the bottom -
    # the Behaviour panel rendered as a bare header with nothing under it.
    # The size alone is not the fix, and cannot be: a saved geometry is restored
    # in preference to it (PanelWindow._restore_geometry), so anyone who has
    # opened this window before keeps the old one. The scroller below is what
    # makes the content reachable at ANY height - this just means it usually
    # does not have to.
    SIZE = (560, 620)

    def build(self, body):
        pad = scaled(12)
        app = self.app

        # Packed FIRST, though it sits at the bottom. pack hands out height in
        # call order, so a footer packed last gets whatever the content left -
        # which was nothing, and "Close" was sliced in half by the window edge.
        # Reserving it here means the content above is what runs out of room,
        # and the button a user needs to shut the window always exists.
        foot = ttk.Frame(body)
        foot.pack(side="bottom", fill="x", padx=pad, pady=pad)
        ttk.Button(foot, text=T("buttons.close"), command=self.close).pack(side="right")

        # ...and what runs out of room now scrolls instead of vanishing. Reserving
        # the footer protects the Close button and nothing else: everything above
        # it was simply cut off at the window edge, with no scrollbar and no hint
        # that a whole group of preferences was still down there. This window grows
        # with every preference added, in every language, at every DPI, so the
        # height can only be right by accident - the scroller makes it not matter.
        self.scroll = ScrollableFrame(body)
        body = self.scroll.body

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
        self._scope_status = None
        self._scope_shown = None        # memo: what the status line currently says
        self._scope_inputs = None       # memo: the values it was computed from
        self.form = ControlForm(form_holder, app, sections=SETTINGS_SECTIONS,
                                collapsible=False,
                                extras={"scope": self._build_scope_extra})

        # -- GUI preferences (ui.json-backed, see gui/prefs.py) --------------- #
        for group_label, keys in PREF_GROUPS:
            self._build_pref_group(body, group_label, keys)

    # -- the "Scope" card ------------------------------------------------------ #
    def _build_scope_extra(self, body):
        """The rest of the Scope card: the view preference, and the live verdict.

        The two switches sit here TOGETHER because reading either one alone is
        how the confusion starts - "Capture only..." changes what the tool takes
        in and cannot be undone without restarting the session, "Show only..."
        changes what is on screen and flips live. They come from two registries
        (convention 42), so the card is the only place they can meet.
        """
        for pref in prefs_in_section("scope"):
            self._build_pref_row(body, pref)
        # The verdict, because ticking the box is a REQUEST: a wildcard, an re:
        # pattern, a process-only target or no destination at all cannot be
        # expressed as a driver filter, and the option then does nothing. Until
        # now the only way to learn that was to start a session and read the log.
        self._scope_status = wrapping_label(body, "", style="Hint.TLabel")
        self._sync_scope_status()

    def _narrowing_verdict(self):
        """Will (or did) the capture actually narrow? ``None`` when unanswerable.

        While a session runs the answer is the SESSION's - the handle's filter
        was fixed when it opened, so a destination typed since then describes a
        session that does not exist. Stopped, it is a preview of the fields as
        they stand, asked of the driver's own parser exactly as ``start()`` will
        ask it (``filters.narrowed_filter`` -> ``WinDivertHelperCompileFilter``),
        so the preview cannot promise something the start would refuse.
        """
        app = self.app
        raw = app._raw_settings()
        if not raw.get("narrow_filter"):
            return None                 # not asked for: nothing to report
        if app.running:
            return bool(app.engine.capture_narrowed())
        try:
            ip = parse_matcher(setting_expression("dst_ip", raw.get("dst_ip")), KIND_IP)
            port = parse_matcher(port_expression(raw.get("dst_port")), KIND_INT,
                                 bounds=PORT_BOUNDS)
        except ValueError:
            # A half-typed expression is the form's business, not this line's -
            # it is already flagged in red under the field it belongs to.
            return None
        return narrowed_filter(windivert_for(raw.get("filter")), ip, port)[1]

    def _sync_scope_status(self):
        """Repaint the verdict line, and only when something behind it moved.

        The verdict costs a call into the driver's filter parser, so it is
        memoised on its inputs rather than recomputed on every tick.
        """
        label = self._scope_status
        if label is None:
            return
        app = self.app
        raw = app._raw_settings()
        inputs = (bool(raw.get("narrow_filter")), raw.get("dst_ip"),
                  raw.get("dst_port"), raw.get("filter"), app.running,
                  app.engine.capture_narrowed())
        if inputs == self._scope_inputs:
            return
        self._scope_inputs = inputs
        verdict = self._narrowing_verdict()
        text = "" if verdict is None else T(
            "scope.narrow_works" if verdict else "scope.narrow_has_no_effect")
        if text == self._scope_shown:
            return
        self._scope_shown = text
        with crashlog.quiet("gui.panels.settings"):
            label.config(text=text, style="Hint.TLabel" if verdict else "Bad.TLabel")
            if text:
                if not label.winfo_ismapped():
                    label.pack(fill="x", pady=(scaled(4), 0))
            else:
                label.pack_forget()

    def refresh(self):
        """Ticked by the App while this window is open (PanelWindow.refresh).

        ``refresh_field_states`` is here because this window renders START-only
        fields (``narrow_filter``) on its OWN ``ControlForm``, and
        ``App._sync_running_ui`` only ever refreshed the Control page's form. A
        window opened BEFORE the session started therefore kept the checkbox
        clickable for the whole run, while the same field opened AFTER the start
        came up correctly disabled - the build path reads the registry, nothing
        re-read it afterwards. Ticking it here heals the state whatever moved it,
        not just start/stop.
        """
        with crashlog.quiet("gui.panels.settings"):
            self.form.refresh_field_states()
            self._sync_scope_status()

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
                command=lambda k=pref.key, v=var: self._store(k, bool(v.get())))
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
            self._store(pref.key,
                        int(value) if float(value).is_integer() else value)
        self._show_pref_errors()

    def _store(self, key, value):
        """Persist a preference and tell the pages, in ONE place.

        Both kinds of row write through here so that "a preference was changed"
        has a single meaning: the value is on disk (``App.set_pref`` persists
        immediately - a preference must survive a hard crash) and anything that
        has to look different NOW already does. Without the second half a switch
        waits for the next tick, and the one that shows or hides a widget looks
        broken while it waits. See ``gui/pages/__init__.py::pref_changed``.
        """
        self.app.set_pref(key, value)
        with crashlog.quiet("gui.panels.settings"):
            from ..pages import pref_changed
            pref_changed(self.app, key)

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
