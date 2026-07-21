"""Main application window.

Composition only: the pages (``gui/pages/``) own their widgets, the field
registry (``fields.py``) owns the form, and this class owns the *state* - the
engine, the tk variables keyed by settings key, the log and the window itself.

Notable behaviour (all deliberate, see PROJECT_NOTES):
  * nothing auto-applies: presets, profiles, LAN mode and a loaded config file
    only fill the form; "Apply changes" pushes them to a running engine and
    lights up while the form differs from what the engine is running,
  * a language switch rebuilds the UI but never lies about the session: the
    running state, the locked traffic filter, the loaded scenario, the active
    page, the sorting and the search box all survive it (the log is cleared on
    purpose - no mixed languages),
  * every visible text is looked up through ``T()`` at widget-build time.
"""
import csv
import os
import queue
import sys
import threading
import time
from collections import deque

import tkinter as tk
from tkinter import ttk, filedialog

from ..appinfo import APP_NAME, AUTHOR, SUPPORT_URL
from ..engine import BeanEngine
from ..fields import BOOL as F_BOOL
from ..fields import CHOICE as F_CHOICE
from ..fields import NUMBER as F_NUMBER
from ..fields import SEED as F_SEED
from ..fields import FIELD_DEFS, SECTIONS, UI_ONLY_KEYS, off_value
from ..filters import cli_key_for, i18n_key_for, i18n_keys, windivert_for
from .. import crashlog
from ..i18n import (FALLBACK_LANGUAGE, T, available_languages, current_language,
                    set_language)
from ..paths import CONNECTIONS_CSV_FILE, CSV_FILE, scenarios_dir
from ..presets import (PRESETS, preset_to_settings, resolve_preset,
                       settings_to_preset)
from ..processes import port_process_map
from ..repro import save_repro_report, settings_to_cli_string
from ..scenario import load_scenario_file
from ..settings import (DEFAULT_SETTINGS, apply_settings, apply_targeting,
                        load_config_file, non_profile_active, save_config_file,
                        settings_from_raw)
from ..summary import settings_summary
from ..utils import number_string
from ..views import avg_packet_bytes, connection_proc, filter_sort_connections
from . import dialogs
from .icon import (apply_window_icon, make_gear_icon, show_idle_icon,
                   show_running_icon)
from .pages import PAGES
from .profiles import ProfileStore
from .rates import PeakWindow
from .labels import wrapping_label
from .scaling import (geometry_fits, init_scaling, initial_geometry,
                      max_window_size, min_window_size, scaled)
from .scrollable import WheelDispatcher
from .theme import (BG, FIELD, FG, MONO_FONT, MUT, apply_dark_titlebar,
                    disable_maximize, init_style, popdown_height,
                    unhighlight_combobox)
from .tooltip import add_tooltip
from .ui_state import DEFAULTS as UI_DEFAULTS, UiStateStore
from . import prefs
from .prefs import PREFS_BY_KEY
from . import panels          # noqa: F401  (importing it REGISTERS the windows)
from .windows import WindowManager

DEFAULT_PROFILE = "presets.perfect"    # the form always starts on a perfect link
TICK_MS = 700                      # UI refresh period
LOG_LINES = 6                      # height of the log strip, in text lines
CHART_SAMPLES = 120                # throughput history length (~80 s at 0.7 s)
SECTION_BY_ID = {s.id: s for s in SECTIONS}
# On a FRESH install (no saved ui state) the advanced sections start collapsed:
# opening the tool on a dozen expanded panels of NAT/MTU/schedule jargon is a wall
# for a first-time user. Only the simple, common sections stay open; the choice is
# remembered per-user afterwards, so a power user expands them once.
FIRST_RUN_COLLAPSED = ["destination", "flapping", "advanced", "schedule",
                       "session", "repro"]


class App:
    TICK_MS = TICK_MS

    def __init__(self, root):
        self.root = root
        # Tk maps a default (white, tiny) window the moment it is created and
        # only then gets our geometry/theme - which looked like a white square
        # flashing before the app appeared. Stay hidden until fully built.
        self._withdrawn_first = False
        try:
            root.withdraw()
            self._withdrawn_first = True
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")
        init_scaling(root)
        root.title(APP_NAME)
        self._icon_idle, self._icon_running = apply_window_icon(root)
        root.configure(bg=BG)
        apply_dark_titlebar(root)     # while still hidden, so it never flashes light

        self.ui = UiStateStore()
        # Secondary windows live in a registry, exactly like the pages and the
        # settings fields do (gui/windows.py): a new window is one entry, and it
        # gets the dark title bar, the DPI sizing, the remembered geometry and the
        # language-switch rebuild for free.
        self.windows = WindowManager(self)
        # Every crash from now on carries the seed, the settings and the counters,
        # so a report is one step away from a reproduction rather than a story.
        crashlog.set_context_provider(self._crash_context)
        self._restore_geometry()

        # Log lines are queued here and applied to the tkinter widget only from
        # the main thread (in _tick): tkinter is NOT thread-safe and the
        # engine/scenario/target-refresher threads all call self.log().
        self._log_queue = queue.Queue()
        self._log_lines = []
        self.engine = BeanEngine(self.log)
        self.running = False
        self._applied_target = None     # last expression pushed to the engine
        # Start/stop run their blocking parts (WinDivert driver load ~0.5-1 s, and
        # the worker-thread joins on stop) OFF the UI thread, so the window never
        # freezes. The worker leaves its result in _ui_queue and the main thread
        # applies it in _tick (convention 26: a worker never touches a widget).
        # _transition is None | "starting" | "stopping" while one is in flight.
        self._ui_queue = queue.Queue()
        self._transition = None
        self._transition_thread = None
        self._pending_start_settings = None
        self._closing = False
        # Main-thread snapshot of the targeting fields. The refresher thread used
        # to call tk Variable.get() directly - a Tcl call from a worker thread,
        # which is exactly the kind of thing that makes Tk hang or crash at
        # random (and then the process lingers, holding the WinDivert driver).
        self._target_expr = ""
        # The refresher thread's verdict on the target ("matches nothing", or ""),
        # handed to the main thread the same way log lines are: the thread writes a
        # plain string, _tick() puts it on the widget. It used to call
        # set_target_warning() - i.e. .config()/.pack()/.winfo_ismapped() - straight
        # from the worker, which is a Tcl call off the main thread. Wrapped in a bare
        # except, so on Windows it either vanished silently (and the "your target
        # catches nothing" banner, the whole point of which is to be LOUD, never
        # appeared) or hung Tk - and a hung GUI still holds the WinDivert handle.
        self._pending_target_warning = ""
        self._shown_target_warning = None
        self._scenario = None
        self._scenario_name = ""

        n = self.chart_samples()          # history length is a saved preference
        self.down_hist = deque([0] * n, maxlen=n)
        self.up_hist = deque([0] * n, maxlen=n)
        self._rate_window = PeakWindow()   # 1 s average behind "peak download / upload"
        self.last_snapshot = None
        self.last_rates = (0.0, 0.0)
        self.peak_down = 0.0
        self.peak_up = 0.0
        self.proc_map = {}
        self._proc_refresh_t = 0.0
        self._last_t = time.monotonic()

        # form state (survives a UI rebuild - a language switch must not reset it)
        self.vars = {}
        self.toggles = {}
        self.form = None
        self.filter_cb = None
        self.lang_cb = None
        self.filter_display = []
        self.filter_canon = i18n_keys()
        self._filter_key = DEFAULT_SETTINGS["filter"]
        # The canonical profile id ("presets.perfect", or a user profile's name) -
        # NOT the displayed text: preset names are translated, so storing the label
        # meant that switching the language left the combobox showing an English
        # name over a Polish list (and any lookup by that name failed).
        # A plain assignment on purpose: _set_profile_key() would write this
        # default into ui.json before _restore_last_profile() gets to read the
        # remembered one.
        self._profile_key = DEFAULT_PROFILE
        self.profile_var = tk.StringVar(value="")
        self.loop_var = tk.BooleanVar(value=False)
        # A fresh install has no saved window state at all (no geometry has ever
        # been persisted), so the advanced sections start collapsed. Once the user
        # has their own state, we honour exactly what they left - including an empty
        # list, i.e. "I opened everything".
        saved_collapsed = self.ui.get("collapsed")
        first_run = not str(self.ui.get("geometry", "") or "").strip()
        self.collapsed_sections = list(
            FIRST_RUN_COLLAPSED if (first_run and not saved_collapsed) else saved_collapsed)
        self.conn_query = ""
        self.conn_sort = dict(self.ui.get("conn_sort"))
        self.event_sort = dict(self.ui.get("event_sort"))
        self._page_id = self.ui.get("page", "control")
        self._applied_sig = None
        self._form_changed = True
        self._summary_text = None
        self._dirty_style = None
        self.scenario_lbl = None
        self.profile_cb = None        # the profile picker (the same widget as the filter)
        self.btn_delete_profile = None
        self.target_warning = None      # "no process matched" banner

        init_style(root)           # also styles the combobox popdown (a Tk listbox)
        self.profiles = ProfileStore()
        self._lang = self.ui.get("language") or current_language()
        self._is_admin = self._detect_admin()   # decides the "run as admin" banner
        self.admin_warning = None
        self._init_vars()

        self._build_ui()
        self._restore_last_profile()      # one-time, only if the preference is on
        self._wheel = WheelDispatcher(root)
        self._check_environment()
        root.report_callback_exception = self._on_ui_exception
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._reveal()
        self._tick()

    def _restore_last_profile(self):
        """Refill the form from the last-used profile, if that preference is set.

        Startup only (never on a language-switch rebuild): it FILLS the form, it
        does not apply anything - like every preset/profile pick, the engine only
        sees it through "Apply changes" (convention 15). An unknown saved name
        (a deleted custom profile) is ignored, not an error.
        """
        if not self.pref("restore_profile"):
            return
        key = str(self.ui.get("profile", "") or "")
        if not key:
            return
        if key in PRESETS or key in self.profiles:
            self.select_profile(key)
        else:
            # the profile is gone (deleted by hand, file quarantined as corrupt,
            # removed by another instance): forget it instead of carrying a name
            # that will never resolve again
            self.ui.set("profile", "")
            self.ui.persist()

    def _reveal(self):
        """Show the window once it is laid out (see the withdraw() above)."""
        try:
            self.root.update_idletasks()
            self.root.deiconify()
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")

    # -- window ---------------------------------------------------------------- #
    def _restore_geometry(self):
        root = self.root
        try:
            screen_w = int(root.winfo_screenwidth() or 1366)
            screen_h = int(root.winfo_screenheight() or 768)
        except Exception:
            screen_w, screen_h = 1366, 768
        maximum = max_window_size(screen_w, screen_h)
        saved = str(self.ui.get("geometry", "") or "")
        if saved and geometry_fits(saved, screen_w, screen_h):
            geometry = saved
        else:
            w, h, x, y = initial_geometry(screen_w, screen_h)
            geometry = f"{w}x{h}+{x}+{y}"
        try:
            root.geometry(geometry)
            root.minsize(*min_window_size())
            # a capped size AND no maximise button: the layout has an upper bound
            # at which it still looks like a layout, so do not offer more
            root.maxsize(*maximum)
            disable_maximize(root)
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")

    def _save_geometry(self):
        try:
            self.ui.set("geometry", self.root.winfo_geometry())
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")

    # -- form state ------------------------------------------------------------ #
    def _init_vars(self):
        """One tk variable per settings key, created once and reused on rebuild."""
        for field in FIELD_DEFS:
            default = DEFAULT_SETTINGS[field.key]
            if field.kind == F_BOOL:
                self.vars[field.key] = tk.BooleanVar(value=bool(default))
            elif field.kind == F_CHOICE:
                self.vars[field.key] = tk.StringVar(value="")
            elif field.kind == F_SEED:
                self.vars[field.key] = tk.StringVar(
                    value="" if default in (None, -1, "") else str(default))
            elif field.kind == F_NUMBER:
                self.vars[field.key] = tk.StringVar(value=number_string(default))
            else:
                self.vars[field.key] = tk.StringVar(value=str(default or ""))
        for section in SECTIONS:
            if section.toggle:                    # no section carries one today
                self.toggles[section.id] = tk.BooleanVar(value=True)
        # The form starts on the "Perfect network" preset (all zeros = the
        # defaults). It used to start on a hidden 100 ms / 20 ms / 1% impairment,
        # so a freshly opened tool already claimed to be degrading the link while
        # the profile box said nothing of the sort.
        for key, value in preset_to_settings(DEFAULT_PROFILE).items():
            self.vars[key].set(number_string(value))

    # -- UI construction ------------------------------------------------------- #
    def _build_ui(self):
        """Build (or rebuild on a language change) the whole UI."""
        root = self.root
        set_language(self._lang)
        for widget in root.winfo_children():
            widget.destroy()

        pad = scaled(14)
        header = ttk.Frame(root)
        header.pack(side="top", fill="x", padx=pad, pady=(scaled(12), scaled(2)))
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(side="left")
        self.author_label = ttk.Label(header, text=T("app.author", author=AUTHOR),
                                      style="Author.TLabel")
        self.author_label.pack(side="left", padx=(scaled(10), 0),
                               anchor="s", pady=(0, scaled(3)))
        self._author_shown = True       # our own state: see _fit_header
        self.status = ttk.Label(header, text=T("app.status.stopped"),
                                style="Status.Bad.TLabel")
        self.status.pack(side="right")
        add_tooltip(self.status, "tips.status")
        langs = available_languages()
        self._lang_name2code = {name: code for code, name in langs}
        current_name = next((name for code, name in langs if code == self._lang), self._lang)
        # The language box moved into the Settings window, but the App still owns
        # the variable and the name<->code map: the Settings combobox binds to
        # lang_var, and smoke / _switch_language rely on it existing even when the
        # window is closed. lang_cb is set by the Settings window while it is open
        # (and back to None on close) - see _sync_running_chrome.
        self.lang_var = tk.StringVar(value=current_name)
        self.lang_cb = None
        # Header entry point to the Settings window: a gear where the language box
        # used to sit. Icon-only keeps the header narrow (the donate button already
        # clips at 1366x768 - see _fit_header) and is language-proof. The image ref
        # is held on self or Tk garbage-collects it and the button goes blank.
        self._gear_icon = None
        try:
            self._gear_icon = make_gear_icon(scaled(20), MUT)
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")
        if self._gear_icon is not None:
            gear = ttk.Button(header, style="Gear.TButton", image=self._gear_icon,
                              command=lambda: self.open_window("settings"))
        else:                                   # no image -> a plain text fallback
            gear = ttk.Button(header, text=T("buttons.settings"),
                              command=lambda: self.open_window("settings"))
        gear.pack(side="right", padx=(0, scaled(10)))
        add_tooltip(gear, "tips.settings")
        # Visible, but deliberately NOT next to the language box: a mis-click on a
        # button that opens a browser is worse than one that changes a combobox.
        donate = self.donate_btn = ttk.Button(header, text=T("buttons.donate"),
                                              style="Donate.TButton",
                                              command=self.open_donate)
        donate.pack(side="right", padx=(0, scaled(22)))
        add_tooltip(donate, "tips.donate")
        # Tk's pack gives the LAST widget packed whatever space is left, so on a
        # narrow header the donate button was the one that got clipped: at 1366x768
        # - the minimum resolution this tool documents - the Polish "Wesprzyj
        # projekt" rendered as "Wesp". (English "Donate" fits, which is why nothing
        # caught it.) Rather than pick a width per language, drop the one element
        # that is purely decorative: the author line. See _fit_header.
        header.bind("<Configure>", lambda e: self._fit_header(header, e.width),
                    add="+")
        # ...and once more when the geometry has actually settled: the first
        # <Configure> arrives before anything is laid out
        self.root.after_idle(
            lambda: self._fit_header(header, header.winfo_width()))

        # Fixed-height summary strip. It used to be a wrapping label of variable
        # height inside the pack chain: a longer summary (e.g. after picking a
        # worse preset) grew it by a line, the notebook below was resized, and the
        # whole page visibly jumped. Its height is now reserved up front.
        self.summary_holder = ttk.Frame(root, height=scaled(36))
        self.summary_holder.pack(side="top", fill="x", padx=pad, pady=(0, scaled(4)))
        self.summary_holder.pack_propagate(False)
        self.summary = ttk.Label(self.summary_holder, text=T("summary.none"),
                                 style="Muted.TLabel", justify="left", anchor="nw",
                                 wraplength=scaled(620))
        # Packed to its TEXT, not to the strip. Filling the (full-width, fixed-height)
        # holder made the label 500 px wider than its own sentence, and a tooltip
        # covers the WIDGET - so the bubble fired over empty background halfway
        # across the header, nowhere near the line it explains.
        self.summary.pack(side="left", anchor="nw")
        add_tooltip(self.summary, "tips.summary")
        # Not admin -> the WinDivert driver will not load and START will fail. Say
        # it up front, as a banner, instead of only a line in the log strip at the
        # bottom (easy to miss) and a dialog after the click. Same treatment as the
        # other "your run is not doing what you think" warnings.
        if not self._is_admin:
            self.admin_warning = wrapping_label(root, T("warn.not_admin"),
                                                style="Bad.TLabel")
            self.admin_warning.pack(side="top", fill="x", padx=pad,
                                    pady=(0, scaled(4)))
        # A queue overflow means the TOOL is dropping the user's packets - packets
        # they did not ask to lose - so their measured loss is partly ours. That was
        # a number in a table on a page they might never open. It is now a banner:
        # a run whose numbers are WRONG must not look like a run that went fine.
        self.engine_warning = wrapping_label(root, "", style="Bad.TLabel")
        self._shown_engine_warning = None
        root.bind("<Configure>", self._on_root_configure, add="+")

        # The bottom strip (START/STOP + log) is packed FIRST, against the bottom
        # edge, so the notebook can never take its space. It used to share a
        # ttk.PanedWindow with the notebook: whenever a page changed its
        # requested height (switching tabs, expanding a section) the sash was
        # pushed down and the bottom pane collapsed to zero - START, "Apply
        # changes" and the log simply vanished. ttk.Panedwindow has no per-pane
        # minsize, so there is no safe way to hold it back.
        bottom = ttk.Frame(root)
        bottom.pack(side="bottom", fill="x", padx=pad, pady=(0, scaled(10)))

        bar = ttk.Frame(bottom)
        bar.pack(side="top", fill="x", pady=(scaled(6), scaled(6)))
        self.btn_start = ttk.Button(bar, text=T("buttons.start"), style="Accent.TButton",
                                    command=self.toggle)
        self.btn_start.pack(side="left")
        add_tooltip(self.btn_start, "tips.start", shortcut="F5")
        self.btn_apply = ttk.Button(bar, text=T("buttons.apply"),
                                    command=lambda: self.apply_if_running(announce=True))
        self.btn_apply.pack(side="left", padx=scaled(8))
        add_tooltip(self.btn_apply, "tips.apply", shortcut="Ctrl+Enter")
        load = ttk.Button(bar, text=T("buttons.load_file"), command=self.load_config_file)
        load.pack(side="right")
        save = ttk.Button(bar, text=T("buttons.save_file"), command=self.save_config_file)
        save.pack(side="right", padx=scaled(6))
        add_tooltip(load, "tips.load_config", shortcut="Ctrl+O")
        add_tooltip(save, "tips.save_config", shortcut="Ctrl+S")
        # "About" lives HERE, not in the header. The header is where the donate
        # button already gets clipped at 1366x768 (see _fit_header), and the one
        # window carrying our LGPL notice may not be the one that falls off the
        # edge of a small screen.
        about = ttk.Button(bar, text=T("buttons.about"),
                           command=lambda: self.open_window("about"))
        about.pack(side="right", padx=(0, scaled(6)))
        add_tooltip(about, "tips.about")

        self.log_wrap = ttk.Frame(bottom)
        self.log_wrap.pack(side="top", fill="x")
        log_sb = ttk.Scrollbar(self.log_wrap, orient="vertical")
        log_sb.pack(side="right", fill="y")
        self.log_box = tk.Text(self.log_wrap, height=LOG_LINES, state="disabled",
                               font=(MONO_FONT, 9), bg=FIELD, fg=MUT,
                               insertbackground=FG, relief="flat", borderwidth=0,
                               highlightthickness=0, wrap="none",
                               yscrollcommand=log_sb.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        log_sb.config(command=self.log_box.yview)

        # ...and only then the notebook, which takes whatever is left
        nb_holder = ttk.Frame(root)
        nb_holder.pack(side="top", fill="both", expand=True, padx=pad,
                       pady=(0, scaled(4)))
        self.nb = ttk.Notebook(nb_holder)
        self.nb.pack(fill="both", expand=True)
        self.pages = {}
        for page_def in PAGES:
            page = page_def.factory(self, self.nb)
            self.nb.add(page.frame, text=T(page_def.label))
            self.pages[page_def.id] = page
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._on_page_changed())

        self._bind_shortcuts()
        self.set_filter_cli_key(self._filter_key)
        self._sync_profile_widgets()
        self.form.set_values(self._settings_for_form())
        self._update_scenario_label()
        self.select_page(self._page_id)
        self._sync_running_ui()

        if self._log_lines:                       # restore the log after a rebuild
            self.log_box.config(state="normal")
            tail = self._log_lines[-self.pref("log_lines"):]
            self.log_box.insert("end", "\n".join(tail) + "\n")
            self.log_box.config(state="disabled")
            self.log_box.see("end")
        self._form_changed = True

    def _settings_for_form(self):
        """Current form values as a settings dict (unvalidated, for redisplay)."""
        s = dict(DEFAULT_SETTINGS)
        s.update(self._raw_settings(gated=False))
        return s

    def _bind_shortcuts(self):
        binds = {"<F5>": lambda e: self.toggle(),
                 "<Control-Return>": lambda e: self.apply_if_running(announce=True),
                 "<Control-s>": lambda e: self.save_config_file(),
                 "<Control-o>": lambda e: self.load_config_file(),
                 "<Control-l>": lambda e: self.clear_log()}
        for sequence, handler in binds.items():
            try:
                self.root.bind(sequence, handler)
            except Exception as _exc:
                crashlog.note(_exc, "gui.app")

    def _on_root_configure(self, event=None):
        """Keep the summary wrapping to the real window width (not a fixed 620 px)."""
        try:
            width = self.summary_holder.winfo_width()
            if width and width > scaled(80):
                self.summary.config(wraplength=width - scaled(8))
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")

    # -- language --------------------------------------------------------------- #
    def _switch_language(self):
        new = self._lang_name2code.get(self.lang_var.get(), FALLBACK_LANGUAGE)
        if new == self._lang:
            return
        self._filter_key = self._filter_cli_key()      # display names are localised
        self._lang = new
        self.ui.set("language", new)
        self._log_lines = []          # the log starts fresh in the new language
        self._build_ui()
        # the open secondary windows are part of the UI: rebuild them in the new
        # language as well, or they sit there in the old one until reopened
        self.windows.rebuild()
        self.log(T("app.language_changed"))

    # -- pages ------------------------------------------------------------------ #
    def select_page(self, page_id):
        if page_id not in self.pages:
            page_id = PAGES[0].id
        self._page_id = page_id
        for index, page_def in enumerate(PAGES):
            if page_def.id == page_id:
                try:
                    self.nb.select(index)
                except Exception as _exc:
                    crashlog.note(_exc, "gui.app")
                break
        self.ui.set("page", page_id)

    def _on_page_changed(self):
        try:
            index = int(self.nb.index(self.nb.select()))
            self._page_id = PAGES[index].id
            self.ui.set("page", self._page_id)
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")
        page = self.current_page()
        if page is not None:
            page.refresh()

    def current_page(self):
        return self.pages.get(self._page_id)

    # -- traffic filter ---------------------------------------------------------- #
    def _filter_cli_key(self):
        """CLI key of the selected filter, regardless of the UI language."""
        var = self.vars.get("filter")
        display = list(self.filter_display)
        canon = list(self.filter_canon)
        if var is None or not display:
            return self._filter_key
        try:
            return cli_key_for(canon[display.index(var.get())])
        except ValueError:
            return self._filter_key

    def set_filter_cli_key(self, key):
        self._filter_key = key or DEFAULT_SETTINGS["filter"]
        var = self.vars.get("filter")
        if var is not None:
            var.set(T(i18n_key_for(self._filter_key)))

    # -- settings <-> widgets ----------------------------------------------------- #
    def _fit_header(self, header, width):
        """Hide the author line when the header cannot fit everything else.

        Tk's pack gives the LAST widget packed whatever space is left over, and the
        donate button is last - so on a narrow header IT is the one that gets
        clipped. At 1366x768 (the minimum resolution this tool documents) the
        Polish "Wesprzyj projekt" rendered as "Wesp": the button asked for 143 px
        and was given 64. English "Donate" fits, which is why nothing caught it.

        The fix drops the one element up there that is purely decorative - the
        author line. Two things make this fiddly, and both were bugs first:

        * "does it fit" is not arithmetic. Padding, fonts and DPI all get a vote,
          so the test is the widget itself: a button whose actual width is under
          the width it ASKED for is a button with its text cut off.
        * ``winfo_ismapped()`` is NOT the state to branch on. The first
          ``<Configure>`` arrives before the header has been laid out - the button
          reports a width of 1 and the label is not mapped yet - so a check for
          "is the label showing" answers *no* and the hide branch never runs. We
          track it ourselves.
        """
        label = getattr(self, "author_label", None)
        donate = getattr(self, "donate_btn", None)
        if label is None or donate is None or width <= 1:
            return
        with crashlog.quiet("gui.header"):
            wanted = donate.winfo_reqwidth()
            actual = donate.winfo_width()
            # width 1 == "not laid out yet": trust the request, not the reality
            clipped = actual <= 1 or actual < wanted
            if clipped and self._author_shown:
                label.pack_forget()
                self._author_shown = False
            elif not self._author_shown and not clipped:
                spare = width - sum(child.winfo_reqwidth()
                                    for child in header.winfo_children())
                if spare > label.winfo_reqwidth() + scaled(24):
                    label.pack(side="left", padx=(scaled(10), 0), anchor="s",
                               pady=(0, scaled(3)), before=self.status)
                    self._author_shown = True

    def open_window(self, window_id):
        """Open (or raise) a registered secondary window - see ``gui/windows.py``.

        The one entry point: a window is never constructed by hand, so it always
        gets the dark title bar, the DPI sizing, the remembered geometry and the
        language-switch rebuild.
        """
        self._release_focus()
        return self.windows.open(window_id)

    def _release_focus(self):
        """Take focus (and any stale hover) off the control that just acted.

        ttk hands a button keyboard focus when it is clicked, and this theme paints
        `focus` exactly like `active` - so a button that opened a window sat there
        looking permanently hovered once that window was closed and focus came back
        to it. Giving focus to the window itself is what ``unhighlight_combobox``
        does about the same symptom on a readonly combobox.
        """
        with crashlog.quiet("gui.app"):
            widget = self.root.focus_get()
            if widget is not None and widget is not self.root:
                with crashlog.quiet("gui.app"):
                    widget.state(["!active", "!focus"])     # ttk widgets only
            self.root.focus_set()

    def row_limit(self):
        """Most rows a table may show (0 = no limit).

        A registry field, so it is read from the form like any other setting. The
        tables are virtualised - rendering costs the same at 400 rows as at 400 000
        - so this bounds the pure-Python filter/sort, not the drawing.
        """
        try:
            value = int(float(self.vars["row_limit"].get() or 0))
        except (KeyError, TypeError, ValueError):
            value = DEFAULT_SETTINGS.get("row_limit", 0)
        return max(0, value)

    # -- GUI preferences (ui.json-backed, see gui/prefs.py) --------------------- #
    def pref(self, key):
        """Live value of a GUI preference (validated, falls back to its default)."""
        p = PREFS_BY_KEY[key]
        return prefs.coerce(p, self.ui.get(prefs.ui_key(key), p.default))

    def set_pref(self, key, value):
        """Store a GUI preference and persist it now (a preference must survive an
        unclean exit, unlike session state that is written on close)."""
        self.ui.set(prefs.ui_key(key), value)
        self.ui.persist()

    def chart_samples(self):
        """Chart history length in samples, derived from the seconds preference and
        the tick period (each sample is one tick)."""
        secs = self.pref("chart_seconds")
        return max(2, round(secs / (self.TICK_MS / 1000.0)))

    @staticmethod
    def _resized_hist(hist, n):
        """History resized to ``n`` samples: newest kept, missing past zero-filled.

        The zero padding is the whole point. The chart's X axis is labelled from
        the number of samples it was handed, so a history that is merely ALLOWED
        to grow to the new length keeps reporting the OLD window and creeps
        towards the new one one tick at a time - raising the preference to 250 s
        left the axis reading "-28 s" and counting up for four minutes while the
        caption already claimed 250. Padding makes a widened chart look exactly
        like a freshly started one, which is what ``__init__`` builds.
        Shrinking needs no padding: the deque drops the oldest samples itself.
        """
        pad = [0] * max(0, n - len(hist))
        return deque(pad + list(hist), maxlen=n)

    def _reconcile_chart_len(self):
        """Resize the throughput history to match the current preference."""
        n = self.chart_samples()
        if getattr(self, "down_hist", None) is None or self.down_hist.maxlen == n:
            return
        self.down_hist = self._resized_hist(self.down_hist, n)
        self.up_hist = self._resized_hist(self.up_hist, n)

    def reset_ui_layout(self):
        """Forget remembered window state: geometry, collapsed sections, table
        sorts, the sash and the remembered page. Everything else (the form, the
        session) is untouched. A deliberate, confirmed action from Settings."""
        if not dialogs.ask_yes_no(self.root, T("dialogs.reset_layout_title"),
                                  T("dialogs.reset_layout_body")):
            return
        for key in ("geometry", "page", "stats_page", "collapsed", "log_height",
                    "conn_sort", "event_sort"):
            self.ui.set(key, UI_DEFAULTS[key])
        for wid in list(self.ui.data):
            if wid.startswith("window."):        # secondary-window geometries
                self.ui.set(wid, "")
        self.collapsed_sections = []
        self.ui.persist()
        self.windows.close_all()
        self._restore_geometry()      # empty geometry -> recompute a centred one
        self._build_ui()
        self.log(T("log.layout_reset"))

    def _raw_settings(self, gated=True):
        """Raw (string/bool) form values keyed by settings key.

        ``gated`` applies the section 'enable' checkboxes, i.e. what the engine
        would actually get. Cheap: no parsing, no regex compilation - which is
        why it can run on every keystroke and on every tick (the old code called
        the full validating reader ~1.4x per second, recompiling matchers).
        """
        raw = {}
        for field in FIELD_DEFS:
            if field.key == "filter":
                raw["filter"] = self._filter_cli_key()
                continue
            var = self.vars.get(field.key)
            if var is None:
                continue
            section = SECTION_BY_ID[field.section]
            if gated and section.toggle and not bool(self.toggles[section.id].get()):
                raw[field.key] = off_value(field)
            else:
                raw[field.key] = var.get()
        return raw

    def _settings_from_widgets(self):
        """Validated settings dict; raises a translated ``ValueError``."""
        return settings_from_raw(self._raw_settings(), self._lang)

    def _settings_to_widgets(self, s):
        merged = dict(DEFAULT_SETTINGS)
        merged.update({k: v for k, v in s.items() if k in DEFAULT_SETTINGS})
        self.set_filter_cli_key(str(merged.get("filter", DEFAULT_SETTINGS["filter"])))
        self.form.set_values(merged)
        self.on_form_changed()

    def on_form_changed(self):
        """Any widget edit: recompute the dirty flag now, the summary next tick."""
        self._form_changed = True
        self._refresh_dirty()
        self._refresh_start_enabled()

    def on_sections_changed(self, collapsed):
        self.collapsed_sections = list(collapsed)
        self.ui.set("collapsed", self.collapsed_sections)

    # -- summary / dirty state ------------------------------------------------- #
    @staticmethod
    def _signature(raw):
        """Fingerprint of the settings THE ENGINE would receive.

        ui_only fields (row_limit) are excluded on purpose: nothing sends them to
        the engine and the tables re-read them on every refresh, so including them
        made "Apply changes" light up for a change that was already live.
        """
        return tuple(sorted((k, str(v)) for k, v in raw.items()
                            if k not in UI_ONLY_KEYS))

    def _is_dirty(self):
        if not self.running or self._applied_sig is None:
            return False
        return self._signature(self._raw_settings()) != self._applied_sig

    def _refresh_dirty(self):
        style = "Dirty.TButton" if self._is_dirty() else "TButton"
        if style == self._dirty_style:
            return
        self._dirty_style = style
        try:
            self.btn_apply.config(style=style)
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")

    def _refresh_start_enabled(self):
        """Disable START while the form holds a value the engine would reject.

        Only when stopped: a running session shows STOP, which must always work.
        The offending field is already flagged red by live validation, so this
        simply removes the "click START -> error dialog" round-trip.
        """
        btn = getattr(self, "btn_start", None)
        form = getattr(self, "form", None)
        if btn is None or form is None:
            return
        if self._transition is not None:
            return                      # a start/stop is in flight: button stays transitional
        blocked = form.has_errors() and not self.running
        try:
            btn.config(state="disabled" if blocked else "normal")
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")

    def _refresh_summary(self):
        if not self._form_changed:
            return
        self._form_changed = False
        raw = self._raw_settings()
        if not self.running:
            prefix = "summary.prefix_preview"
        elif self._is_dirty():
            prefix = "summary.prefix_pending"
        else:
            prefix = "summary.prefix"
        text = settings_summary(raw, self._lang, prefix_key=prefix)
        if text == self._summary_text:
            return
        self._summary_text = text
        try:
            self.summary.config(text=text)
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")

    # -- profiles ---------------------------------------------------------------- #
    @staticmethod
    def _short_label(key):
        """Short form of a field label: drop the trailing colon/explanations."""
        return T(key).split("(")[0].strip().rstrip(":").strip()

    def _active_non_profile_settings(self, s):
        """Translated labels of active settings a profile will NOT store."""
        return [self._short_label(key) for key in non_profile_active(s)]

    def _is_reserved_profile_name(self, name):
        """True for names taken by a built-in preset (in any language)."""
        return resolve_preset(name) is not None

    def profile_names(self):
        """Everything the picker offers: presets first, then the user's own.

        Nothing else - no group headings. The dropdown sits under the "Profiles"
        heading and every row in it is a profile, so a row that only says which
        group comes next is a row the user can pick and get nothing from.
        """
        self._preset_disp2canon = {T(k): k for k in PRESETS}
        return [T(k) for k in PRESETS] + self.profiles.names()

    def profile_label(self, key):
        """Displayed name of a profile id (presets are translated, own ones are not)."""
        return T(key) if key in PRESETS else str(key or "")

    def profile_key_for(self, label):
        """Displayed name -> canonical id (or the name itself, for own profiles)."""
        return getattr(self, "_preset_disp2canon", {}).get(label, label)

    def _sync_profile_widgets(self):
        """Refill the profile list, show the selection, gate the Delete button."""
        if self.profile_cb is None:
            return
        try:
            names = self.profile_names()      # also refreshes the label<->key lookups
            self.profile_cb.config(values=names, height=popdown_height(names))
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")
        try:
            self.profile_var.set(self.profile_label(self._profile_key))
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")
        if self.btn_delete_profile is not None:
            try:
                # built-in presets and the group headings are not deletable;
                # the button used to look live and then silently do nothing
                deletable = self._profile_key in self.profiles
                self.btn_delete_profile.config(
                    state="normal" if deletable else "disabled")
            except Exception as _exc:
                crashlog.note(_exc, "gui.app")

    def on_profile_selected(self, event=None):
        """``<<ComboboxSelected>>`` on the profile picker."""
        unhighlight_combobox(event)      # readonly comboboxes stay "selected" otherwise
        self.load_selected_profile()

    def _set_profile_key(self, key):
        """Make ``key`` the current profile AND the one remembered for next start.

        The single place that writes ``_profile_key``. It used to be written by
        each of the three paths that change the current profile, and only one of
        them (picking from the list) also remembered it - so saving a new profile,
        which is how a user ENDS UP on their own profile, left "Restore the last
        profile on startup" pointing at the preset picked before it. Persisting
        right here, not on close, is the same rule preferences follow: a
        deliberate choice must survive an unclean exit.
        """
        self._profile_key = key
        self.ui.set("profile", key)
        self.ui.persist()

    def select_profile(self, key):
        """Fill the form from a preset/profile id. Never applies by itself."""
        preset = PRESETS.get(key) or self.profiles.get(key)
        if not preset:
            return
        self._set_profile_key(key)
        for setting, value in preset_to_settings(preset).items():
            self.vars[setting].set(number_string(value))
        self._sync_profile_widgets()
        self.form.validate_all()
        self.form.apply_overrides()
        self.on_form_changed()
        self.log(f"{T('log.loaded_profile')}: {self.profile_label(key)}")
        if self.running:
            self.log(T("log.apply_needed"))

    def load_selected_profile(self):
        """Load whatever ``profile_var`` currently names.

        Every row in the picker is a real profile (``profile_names``), so there
        is nothing to pick that does not load something.
        """
        self.select_profile(self.profile_key_for(self.profile_var.get()))

    def save_profile(self):
        # warn up front (once, contextually) when active settings fall outside the
        # profile scope, so nothing is lost silently
        try:
            extras = self._active_non_profile_settings(self._settings_from_widgets())
        except Exception:
            extras = []
        if extras:
            dialogs.show_warning(
                self.root, T("dialogs.profile_scope_title"),
                T("dialogs.profile_scope_warning", fields=", ".join(extras)))
        name = dialogs.ask_string(self.root, T("dialogs.save_profile"),
                                  T("dialogs.profile_name"))
        name = (name or "").strip()
        if not name:
            return
        if self._is_reserved_profile_name(name):
            dialogs.show_error(self.root, T("log.error"), T("dialogs.profile_name_taken"))
            return
        try:
            values = settings_to_preset(self._settings_from_widgets())
            self.profiles.set(name, {k: float(v) for k, v in values.items()})
        except ValueError:
            dialogs.show_error(self.root, T("log.error"), T("dialogs.values_numbers"))
            return
        self._persist_profiles()
        self._set_profile_key(name)      # saving one also SELECTS it - remember that
        self._sync_profile_widgets()
        self.log(f"{T('log.profile_saved')}: {name}")

    def delete_profile(self):
        name = self._profile_key
        if name not in self.profiles:
            return                    # presets are not deletable (button is disabled)
        self.profiles.delete(name)
        self._persist_profiles()
        # remember what we fall back TO, not the name that no longer exists
        self._set_profile_key(DEFAULT_PROFILE)
        self._sync_profile_widgets()
        self.log(f"{T('log.profile_deleted')}: {name}")

    def _persist_profiles(self):
        err = self.profiles.persist()
        if err:
            self.log(f"{T('log.profiles_not_saved')}: {err}")

    # -- session actions ---------------------------------------------------------- #
    # Internal stat keys are engine-speak ("seen"); a CSV is read by people and
    # by spreadsheets, so it gets column names that mean something.
    CSV_COLUMNS = {"seen": "packets_seen", "drop_loss": "dropped_loss",
                   "drop_overflow": "dropped_overflow", "drop_syn": "dropped_syn",
                   "drop_mtu": "dropped_mtu", "drop_nat": "dropped_nat",
                   "drop_rst": "dropped_rst", "drop_lan": "dropped_lan",
                   "drop_block": "dropped_block",
                   "drop_flap": "dropped_link_outage", "drop_rate": "dropped_rate_limit",
                   "drop_shutdown": "dropped_at_stop",
                   "queue": "queue_len",
                   "peak_queue": "queue_peak"}

    def export_csv(self):
        snap = self.engine.stats_snapshot()
        header = ["time", *(self.CSV_COLUMNS.get(k, k) for k in snap)]
        try:
            write_header = not os.path.exists(CSV_FILE)
            if not write_header:
                with open(CSV_FILE, newline="", encoding="utf-8") as f:
                    existing = next(csv.reader(f), [])
                if existing != header:
                    # the stat columns changed between versions: appending would
                    # silently misalign rows against the old header
                    backup = CSV_FILE[:-4] + time.strftime(".%Y%m%d-%H%M%S.csv")
                    os.replace(CSV_FILE, backup)
                    self.log(f"{T('log.csv_rotated')} {os.path.basename(backup)}")
                    write_header = True
            with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(header)
                writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), *snap.values()])
            self.log(f"{T('log.stats_saved_to')} {os.path.basename(CSV_FILE)}")
        except Exception as e:
            self.log(f"{T('log.csv_error')}: {e}")

    # Mirrors the table's columns so the export is the table, on disk. Raw bytes,
    # not KB: a CSV is read by a spreadsheet or a script, where exact, summable
    # integers beat the one-decimal KB the table shows for people. `impaired` is
    # "yes"/"no" in English, like the headers - the CSV is language-independent.
    CONN_CSV_HEADER = ["process", "pid", "proto", "remote_ip", "remote_port",
                       "local_port", "packets", "impaired", "dropped",
                       "download_bytes", "upload_bytes", "total_bytes",
                       "avg_bytes", "duration_s", "idle_s"]

    def export_connections_csv(self):
        """Write the CURRENT connection view (search + sort) to a CSV snapshot.

        The display row-limit is a rendering cap, not part of what the user asked
        to see, so the export carries every filtered row - sorted the same way the
        table is. The file is overwritten atomically each time (tmp + os.replace):
        it is a snapshot of "the connections as they are now", not an append log
        like the stats CSV.
        """
        now = self.engine.now_ref()
        rows = filter_sort_connections(
            self.engine.connections_snapshot(limit=None), self.conn_query,
            self.conn_sort["col"], self.conn_sort["reverse"],
            now=now, proc_map=self.proc_map, limit=0)
        path = CONNECTIONS_CSV_FILE
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(self.CONN_CSV_HEADER)
                for c in rows:
                    last = c.get("last", now)
                    packets = c.get("packets", 0) or 0
                    writer.writerow([
                        connection_proc(c, self.proc_map) or "?",
                        c.get("pid") or "",
                        c.get("proto", "IP"), c.get("remote_ip", ""),
                        c.get("remote_port", ""), c.get("local_port", ""),
                        packets, "yes" if c.get("scoped") else "no",
                        c.get("dropped", 0),
                        c.get("bytes_in", 0), c.get("bytes_out", 0), c.get("bytes", 0),
                        avg_packet_bytes(c),
                        f"{max(0.0, last - c.get('first', now)):.1f}",
                        f"{max(0.0, now - last):.1f}"])
            os.replace(tmp, path)
            self.log(f"{T('log.conns_saved_to')} {os.path.basename(path)} ({len(rows)})")
        except Exception as e:
            self.log(f"{T('log.csv_error')}: {e}")

    def mark_bug(self):
        if not self.running:
            self.log(T("log.marker_needs_start"))
            return
        self.engine.log_event("BUG", "events.bug_marker")
        info = self.engine.session_info()
        self.log(f"*** {T('log.bug_marked')} @ {info['elapsed']:.1f}s "
                 f"(seed={info['seed']}) ***")

    def save_repro(self):
        if self.engine.effective_seed() is None:
            self.log(T("log.start_first"))
            return
        path = filedialog.asksaveasfilename(title=T("dialogs.save_repro"),
                                            defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            report = save_repro_report(path, self.engine, self._settings_from_widgets())
            self.log(f"{T('log.repro_saved_to')} {os.path.basename(path)}")
            self.log(f"{T('log.repro_command')}: {report['cli_command']}")
        except Exception as e:
            dialogs.show_error(self.root, T("log.error"),
                               f"{T('dialogs.report_not_saved')}: {e}")

    def copy_repro_cli(self):
        try:
            cli = settings_to_cli_string(self._settings_from_widgets(),
                                         seed=self.engine.effective_seed())
            self.copy_to_clipboard(cli)
            self.log(f"{T('log.copied')}: {cli}")
        except Exception as e:
            self.log(f"{T('log.not_copied')}: {e}")

    def open_donate(self):
        """Open the support page (voluntary - it funds the project's development)."""
        try:
            import webbrowser
            webbrowser.open_new_tab(SUPPORT_URL)
            self.log(f"{T('log.donate_opened')}: {SUPPORT_URL}")
        except Exception as e:
            self.log(f"{T('log.error')}: {e}")

    def copy_to_clipboard(self, text):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except Exception as e:
            self.log(f"{T('log.not_copied')}: {e}")

    # -- targeting straight from the connection table ------------------------------ #
    def set_target_expression(self, expression):
        self.vars["target"].set(expression)
        self.form.set_values(self._settings_for_form())
        self.on_form_changed()
        self.log(f"{T('log.target_set')}: {expression}")
        if self.running:
            self.log(T("log.apply_needed"))

    def set_destination(self, ip, port):
        self.vars["dst_ip"].set(str(ip or ""))
        self.vars["dst_port"].set(str(port or ""))
        self.form.set_values(self._settings_for_form())
        self.on_form_changed()
        self.log(f"{T('log.dest_set')}: {ip}:{port}")
        if self.running:
            self.log(T("log.apply_needed"))

    # -- scenario / config files ---------------------------------------------------- #
    def _update_scenario_label(self):
        if self.scenario_lbl is None:
            return
        try:
            self.scenario_lbl.config(text=self._scenario_name or T("fields.scenario_none"))
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")

    def load_scenario(self):
        path = filedialog.askopenfilename(
            title=T("dialogs.load_scenario"),
            initialdir=scenarios_dir(),
            filetypes=[("JSON", "*.json"), (T("dialogs.all_files"), "*.*")])
        if not path:
            return
        try:
            self._scenario = load_scenario_file(path)
            self.loop_var.set(self._scenario.loop or self.loop_var.get())
            self._scenario_name = (f"{T('log.scenario')}: {os.path.basename(path)} "
                                   f"({len(self._scenario.steps)} {T('log.steps')}, "
                                   f"{self._scenario.duration:.0f}s)")
            self._update_scenario_label()
            self.log(f"{T('log.scenario_loaded')}: {os.path.basename(path)}")
        except Exception as e:
            dialogs.show_error(self.root, T("log.error"),
                               f"{T('dialogs.scenario_not_loaded')}: {e}")

    def clear_scenario(self):
        self._scenario = None
        self._scenario_name = ""
        self._update_scenario_label()
        self.log(T("log.scenario_cleared"))

    def load_config_file(self):
        path = filedialog.askopenfilename(
            title=T("dialogs.load_config"),
            filetypes=[("JSON", "*.json"), (T("dialogs.all_files"), "*.*")])
        if not path:
            return
        try:
            self._settings_to_widgets(load_config_file(path))
            self.log(f"{T('log.config_loaded_from')} {os.path.basename(path)}")
            if self.running:
                self.log(T("log.apply_needed"))
        except Exception as e:
            dialogs.show_error(self.root, T("log.error"),
                               f"{T('dialogs.not_loaded')}: {e}")

    def save_config_file(self):
        path = filedialog.asksaveasfilename(title=T("dialogs.save_config"),
                                            defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            save_config_file(path, self._settings_from_widgets())
            self.log(f"{T('log.config_saved_to')} {os.path.basename(path)}")
        except Exception as e:
            dialogs.show_error(self.root, T("log.error"),
                               f"{T('dialogs.not_saved')}: {e}")

    # -- apply / start / stop -------------------------------------------------------- #
    def apply_if_running(self, *_, announce=False):
        if not self.running:
            if announce:
                self.log(T("log.apply_needs_start"))
            return
        try:
            s = self._settings_from_widgets()
        except ValueError as e:
            self.log(f"{T('log.error')}: {e}")
            return
        apply_settings(self.engine, s, self.log)
        self.engine.log_event("CHANGE", settings_summary(s, "en"))
        self.log(f"{T('log.applied_changes')}: {settings_summary(s, self._lang)}")
        self._applied_sig = self._signature(self._raw_settings())
        self._form_changed = True
        self._refresh_dirty()

    def reset_now_click(self):
        if not self.running:
            self.log(T("log.reset_needs_start"))
            return
        self.engine.reset_now(3.0)
        self.log(T("log.resetting"))

    def _snapshot_target(self):
        """Read the target field ON THE MAIN THREAD (tkinter is not thread-safe).

        The refresher thread only ever sees this plain string.
        """
        try:
            expression = str(self.vars["target"].get()).strip()
        except Exception:
            expression = ""
        self._target_expr = expression
        return self._target_expr

    def set_target_warning(self, text):
        """Show (or clear) the "targeting is doing nothing" banner.

        MAIN THREAD ONLY - it touches widgets. Worker threads set
        ``_pending_target_warning`` instead; ``_drain_target_warning`` applies it.
        """
        if self.target_warning is None:
            return
        try:
            if text:
                self.target_warning.config(text=text)
                if not self.target_warning.winfo_ismapped():
                    self.target_warning.pack(fill="x", pady=(scaled(5), 0))
            else:
                self.target_warning.config(text="")
                self.target_warning.pack_forget()
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")

    def _drain_engine_warning(self):
        """Show (or clear) "the tool is losing packets on its own". Main thread only."""
        text = ""
        with crashlog.quiet("gui.app"):
            if self.engine.stats_snapshot().get("drop_overflow", 0) > 0:
                text = T("warn.queue_overflow")
        if text == self._shown_engine_warning:
            return                      # unchanged: no widget work at all
        self._shown_engine_warning = text
        with crashlog.quiet("gui.app"):
            if text:
                self.engine_warning.config(text=text)
                if not self.engine_warning.winfo_ismapped():
                    # `after=self.summary_holder`, NOT `before=self.nb`: the notebook
                    # lives inside its own holder, so it is not a sibling here and
                    # pack() refuses - silently, since this is wrapped. The banner
                    # then existed, reported itself as mapped, and drew nothing.
                    self.engine_warning.pack(side="top", fill="x",
                                             padx=scaled(14), pady=(0, scaled(4)),
                                             after=self.summary_holder)
            else:
                self.engine_warning.config(text="")
                self.engine_warning.pack_forget()

    def _drain_target_warning(self):
        """Render the current target verdict. Main thread only."""
        text = self._pending_target_warning
        if text == self._shown_target_warning:
            return                      # nothing changed: no widget work at all
        self._shown_target_warning = text
        self.set_target_warning(text)

    def _refresh_target(self, force=False):
        """Keep the engine's target in step with the field, and report what it caught.

        This used to run on a 2 s background loop (``_target_refresher``, removed).
        Every pass called ``apply_targeting``, which resolved the port set
        SYNCHRONOUSLY - four syscalls and a psutil walk - on a thread nobody
        watched. Worse, the loop was never joined while ``_finish_start`` spawned a
        new one on every start, so a STOP followed by a START inside its sleep left
        the old one running as well: one extra permanent scanner per fast restart.

        Keeping the port set fresh is ``target_resolver``'s job now. What is left
        here is cheap and runs on the main thread from ``_tick``: apply the
        expression when the USER changed it, then read the verdict.

        NO WIDGET IS TOUCHED HERE - the verdict goes into a plain field and
        ``_drain_target_warning`` renders it. Deliberately kept that way: it is the
        shape that stops a Tcl call ever leaving the main thread, whoever calls this
        next (convention 26).
        """
        expression = self._target_expr
        if force or expression != self._applied_target:
            self._applied_target = expression
            if not expression:
                self.engine.set_target(False)
            else:
                # One shared implementation (settings.apply_targeting) compiles the
                # expression and points the engine at it, so the GUI and
                # apply_settings can never drift apart.
                apply_targeting(self.engine, expression, self.log, announce=force)
        if not expression:
            self._pending_target_warning = ""
            return
        targeting = self.engine.targeting()
        if targeting is None:
            self._pending_target_warning = T("fields.target_no_match")
            return
        if targeting.refreshes == 0:
            # Just typed, never resolved: the resolver thread only runs during a
            # session, and reporting "matches nothing" before anybody looked would
            # be a lie. One resolve here - bounded to once per edit, not per tick.
            with crashlog.quiet("gui.app"):
                targeting.refresh()
        # A target that matches nothing impairs nothing - and a run in which
        # nothing broke looks exactly like a run in which everything held up.
        # Say so on the page, not only in the log.
        self._pending_target_warning = (
            "" if targeting.matched else T("fields.target_no_match"))

    def toggle(self):
        self._stop() if self.running else self._start()

    def _start(self):
        if self._transition is not None:
            return                      # a start/stop is already in flight
        try:
            s = self._settings_from_widgets()
        except ValueError as e:
            dialogs.show_error(self.root, T("log.error"), str(e))
            return
        self.engine.set_seed(s.get("seed", -1))
        self._pending_start_settings = s
        filt = windivert_for(s["filter"])
        duration = s.get("duration", 0)
        # Immediate feedback: the psutil target resolution and the WinDivert driver
        # load (~0.5-1 s) run on the worker thread below, so without this the click
        # feels dead until the driver is up. Log now, on the UI thread, before work.
        self.log(T("log.starting"))

        def work():
            # Both the psutil target resolution and the WinDivert driver load
            # (~0.5-1 s) run here, on the worker thread, so the UI never freezes.
            # duration is a START-time setting (like the traffic filter): the
            # engine owns the deadline and stops itself when it is reached.
            apply_settings(self.engine, s, self.log)
            self.engine.start(filt, duration=duration)

        self._begin_transition("starting", work)

    def _finish_start(self, err):
        """Apply the result of an async start. Main thread only (from _tick)."""
        if err is not None:
            if isinstance(err, ImportError):
                dialogs.show_error(self.root, T("dialogs.missing_library"),
                                   T("dialogs.install_pydivert"))
            else:
                dialogs.show_error(self.root, T("dialogs.start_failed"),
                                   f"{err}\n\n{T('dialogs.run_as_admin')}")
            self._sync_running_ui()     # button back to START
            return
        if self._closing:
            # the window is going away; on_close already stops the engine, so do
            # not resurrect a UI nobody is driving any more
            return
        s = self._pending_start_settings
        self.running = True
        self._applied_sig = self._signature(self._raw_settings())
        self.peak_down = self.peak_up = 0.0
        self._rate_window.reset()
        if self._scenario is not None:
            self._scenario.loop = self.loop_var.get()
            self.engine.start_scenario(self._scenario, s, log=self.log)
        self._snapshot_target()
        # No refresher thread any more: _tick applies a changed expression and the
        # engine's resolver keeps the port set fresh (see _refresh_target).
        self._applied_target = None     # re-apply once, now that the engine is up
        self._sync_running_ui()

    def _stop(self):
        if self._transition is not None:
            return
        self.log(T("log.stopping"))     # immediate feedback (see _start)
        self._begin_transition("stopping", self.engine.stop)

    def _finish_stop(self, _err):
        """Apply the result of an async stop. Main thread only (from _tick).

        engine.stop() joins its own workers and is best-effort; even if it raised,
        the session is over and the watchdog + atexit still release the divert
        (fail-open, convention 20), so there is nothing to undo here.
        """
        self.running = False
        self._applied_sig = None
        self._sync_running_ui()

    def _begin_transition(self, kind, work):
        """Run a blocking engine call (start/stop) OFF the UI thread.

        ``work`` is a zero-arg callable run on a worker thread; its outcome - None
        on success or the exception on failure - is handed back to the main thread
        through ``_ui_queue`` and applied on the UI thread (``_poll_transition``,
        with ``_tick`` as a backstop). NO WIDGET is touched from the worker
        (convention 26). The button keeps showing START/STOP the whole time - the
        work is normally milliseconds, and a second click is a no-op while a
        transition is in flight, so there is nothing to relabel or disable.
        """
        self._transition = kind

        def run():
            try:
                work()
                err = None
            except Exception as e:      # carried to the main thread, never swallowed
                err = e
            self._ui_queue.put((kind, err))

        self._transition_thread = threading.Thread(target=run, daemon=True)
        self._transition_thread.start()
        self._poll_transition()

    def _poll_transition(self):
        """Flip the button as soon as the worker finishes, not on the next _tick.

        Runs on the UI thread; while a transition is in flight it re-arms itself via
        root.after so START/STOP updates feel instant even though the driver load /
        thread join ran on a worker thread. _tick drains the same queue as a backstop
        (and in the fake-tk tests, where timers never fire on their own).
        """
        self._drain_ui_queue()
        if self._transition is not None:
            self.root.after(30, self._poll_transition)

    def _drain_ui_queue(self):
        """Apply finished start/stop transitions. Main thread only (from _tick)."""
        while True:
            try:
                kind, err = self._ui_queue.get_nowait()
            except queue.Empty:
                return
            self._transition = None
            self._transition_thread = None
            if kind == "starting":
                self._finish_start(err)
            else:
                self._finish_stop(err)

    def _settle_transition(self):
        """Block until an in-flight start/stop has been applied.

        The live UI drains _ui_queue from _tick and never needs this; it exists so
        a headless test can drive the async start/stop deterministically.
        """
        t = self._transition_thread
        if t is not None:
            t.join()
        self._drain_ui_queue()

    def _on_engine_stopped(self):
        """The engine stopped itself: the deadline was reached, or a worker died.

        The engine already logged why (and released the divert - the network is
        back to normal); the UI only has to stop lying about the session.
        """
        self.running = False
        self._applied_sig = None
        self._sync_running_ui()

    def _on_ui_exception(self, exc, value, tb):
        """Tk callback crashed: say so instead of swallowing it.

        Tk's default handler prints a traceback to stderr - which does not exist
        in a windowed build, so the error was invisible and the refresh loop kept
        limping. The session is NOT stopped: the engine is healthy (its own
        watchdog covers engine faults) and killing a running test because a
        tooltip threw would be worse than the bug.

        It is also written to the CRASH LOG, with the seed, the settings and the
        counters attached - so "it broke" turns into a report somebody can act on.
        """
        import traceback
        if value is not None:
            value.__traceback__ = tb
            crashlog.record(value, source="tk-callback")
        detail = "".join(traceback.format_exception_only(exc, value)).strip()
        self.log(T("log.ui_error", e=detail))
        try:
            dialogs.show_error(self.root, T("dialogs.internal_error_title"),
                               T("dialogs.internal_error", e=detail))
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")

    def _crash_context(self):
        """App state attached to every crash report (see crashlog.set_context_provider).

        The point is that a crash report should be one step away from a REPRO, not
        just something to read: the seed and the settings are what make the failure
        happen again.
        """
        context = {"page": self._page_id, "running": self.running}
        try:
            context["seed"] = self.engine.effective_seed()
            context["counters"] = dict(self.engine.stats_snapshot())
            settings = self._settings_from_widgets()
            context["settings"] = settings
            context["repro_command"] = settings_to_cli_string(
                settings, seed=self.engine.effective_seed())
            context["log_tail"] = list(self._log_lines[-crashlog.MAX_LOG_TAIL:])
            context["open_windows"] = self.windows.open_ids()
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")
        return context

    def _sync_running_ui(self):
        """Make the chrome tell the truth about the session.

        Called after every start/stop AND after every UI rebuild: a language
        switch used to leave a running session showing "START" / "Stopped" and an
        unlocked traffic filter (which breaks the "filter is applied only at
        start" rule).
        """
        running = self.running
        try:
            self.btn_start.config(
                text=T("buttons.stop" if running else "buttons.start"),
                style="Stop.TButton" if running else "Accent.TButton")
            self.status.config(
                text=T("app.status.running" if running else "app.status.stopped"),
                style="Good.TLabel" if running else "Status.Bad.TLabel")
            # Title bar + taskbar icon also tell the truth: a running capture
            # gets an "RUNNING" tag and the recording-dot icon, so it is obvious
            # the tool is live even when the window is minimised.
            self.root.title(
                "%s  %s" % (APP_NAME, T("app.title.running")) if running
                else APP_NAME)
            if running:
                show_running_icon(self.root, self._icon_running)
            else:
                show_idle_icon(self.root, self._icon_idle)
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")
        # lang_cb is None whenever the Settings window is closed - it lives there
        # now, not in the header - so skip it unless it is actually on screen.
        for widget in (self.filter_cb, self.lang_cb):
            # the traffic filter is applied at start only, and switching the
            # language rebuilds the whole UI - neither is safe mid-session
            if widget is None:
                continue
            try:
                widget.config(state="disabled" if running else "readonly")
            except Exception as _exc:
                crashlog.note(_exc, "gui.app")
        if self.form is not None:
            # every other START-only field (today: "Run time") locks with it
            self.form.refresh_field_states()
        self._form_changed = True
        self._refresh_dirty()
        self._refresh_start_enabled()

    def on_close(self):
        if self.running and self.pref("confirm_close"):
            if not dialogs.ask_yes_no(self.root, T("dialogs.confirm_close_title"),
                                      T("dialogs.confirm_close_running")):
                return
        # From here the window IS closing: a start still in flight must not
        # resurrect the UI when its worker finishes (engine.stop below waits on the
        # engine's own _stop_lock, so it cannot leak a divert - fail-open).
        self._closing = True
        try:
            # secondary windows persist their geometry on the way out, so they
            # come back where the user left them
            self.windows.close_all()
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")
        try:
            # always release the divert: a leaked handle keeps the WinDivert
            # driver loaded, which locks its .sys file until a reboot
            self.engine.stop()
            self.running = False
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")
        try:
            # ...and unload the driver itself. Not after every session (a restart
            # must stay instant), but once, here: while it is loaded the kernel
            # holds WinDivert64.sys next to the exe, and the app's own folder
            # cannot be deleted - even after its contents are gone.
            from ..driver import release_on_exit
            release_on_exit(lambda line: self.log(f"{T('log.driver')}: {line}"))
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")
        try:
            self._save_geometry()
            self.ui.persist()
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")
        self.root.destroy()

    def _report_storage_problems(self):
        """A profile file that vanished or broke must SAY so, not just be gone."""
        for store, key in ((self.profiles, "log.profiles_problem"),
                           (self.ui, "log.ui_state_problem")):
            problem = getattr(store, "problem", None)
            if problem:
                self.log(f"{T(key)}: {problem}")
                store.problem = None

    def _detect_admin(self):
        """Do we hold the rights WinDivert needs? True when the question is moot.

        Off Windows there is no driver to elevate for (that is logged separately),
        so we do not nag; on Windows we ask the OS. Unknown -> don't cry wolf.
        """
        if not sys.platform.startswith("win"):
            return True
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")
            return True

    def _check_environment(self):
        if not sys.platform.startswith("win"):
            self.log(T("log.note_windows"))
        elif not self._is_admin:
            self.log(T("log.note_admin"))
        try:
            import pydivert  # noqa: F401
            self.log(T("log.ready"))
        except ImportError:
            self.log(T("log.no_pydivert"))
        self._report_storage_problems()

    # -- periodic refresh -------------------------------------------------------- #
    def _visible(self):
        """False when the window is minimised - skip every expensive redraw."""
        try:
            if str(self.root.state()) == "iconic":
                return False
            viewable = self.root.winfo_viewable()
            return True if viewable is None else bool(viewable)
        except Exception:
            return True

    def _peak_rates(self, now, snap):
        """Throughput averaged over ~1 s - the figure the "peak" line reports.

        The arithmetic lives in ``gui/rates.py`` (pure, unit-tested): it used to
        live here, untested, with an eviction rule that threw away the very sample
        that made the window wide enough, so the session's peak read 0 / 0 KB/s for
        the entire life of the tool.
        """
        return self._rate_window.add(now, snap["bytes_in"], snap["bytes_out"])

    def _sample(self):
        """Snapshot the engine and keep the throughput history continuous."""
        now = time.monotonic()
        snap = self.engine.stats_snapshot()
        if self.last_snapshot is not None:
            dt = max(1e-3, now - self._last_t)
            down = (snap["bytes_in"] - self.last_snapshot["bytes_in"]) / 1024.0 / dt
            up = (snap["bytes_out"] - self.last_snapshot["bytes_out"]) / 1024.0 / dt
            down, up = max(0.0, down), max(0.0, up)
            self._reconcile_chart_len()
            self.down_hist.append(down)
            self.up_hist.append(up)
            self.last_rates = (down, up)
            averaged = self._peak_rates(now, snap)
            if self.running and averaged is not None:
                self.peak_down = max(self.peak_down, averaged[0])
                self.peak_up = max(self.peak_up, averaged[1])
        self.last_snapshot, self._last_t = snap, now

    def _tick(self):
        """One UI refresh. Never raises: the loop must survive a broken tick.

        The body used to run unguarded with the reschedule as its last statement,
        so a single exception (a page refresh, a psutil hiccup) killed the timer
        for the rest of the session: the log stopped draining and the statistics
        froze while the engine kept running.
        """
        try:
            self._drain_ui_queue()      # finished async start/stop (main thread only)
            self._drain_log()           # worker-thread log lines (main thread only)
            self._drain_target_warning()   # worker-thread verdict (main thread only)
            self._drain_engine_warning()   # "the tool itself is dropping packets"
            self._sample()
            self._snapshot_target()     # main-thread read of the target field
            if self.running:
                # Cheap now: applies only when the expression changed, and the
                # resolving happens on the engine's resolver thread.
                self._refresh_target()
            if self._transition is None and self.running and not self.engine.is_running():
                self._on_engine_stopped()      # deadline reached / worker fault
            if self._visible():
                page = self.current_page()
                if page is not None:
                    page.refresh()
                self.windows.refresh()      # open secondary windows tick too
                self._refresh_summary()
                self._refresh_dirty()
                now = time.monotonic()
                if self.running and (now - self._proc_refresh_t) > 3.0:
                    self._proc_refresh_t = now
                    self.proc_map = port_process_map() or self.proc_map
        except Exception as e:                 # pragma: no cover - defensive
            self.log(T("log.ui_error", e=e))
        finally:
            self.root.after(TICK_MS, self._tick)

    # -- logging ------------------------------------------------------------------ #
    def log(self, msg):
        """Thread-safe logging entry point (worker threads never touch widgets)."""
        stamp = time.strftime("%H:%M:%S")
        self._log_queue.put(f"[{stamp}] {msg}")
        if threading.current_thread() is threading.main_thread():
            self._drain_log()

    def clear_log(self):
        self._log_lines = []
        try:
            self.log_box.config(state="normal")
            self.log_box.delete("1.0", "end")
            self.log_box.config(state="disabled")
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")

    def _drain_log(self):
        """Apply queued log lines to the widget. Main thread only."""
        if getattr(self, "log_box", None) is None:
            return                      # UI not built yet; lines stay queued
        while True:
            try:
                line = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log_line(line)

    def _append_log_line(self, line):
        # How many lines to keep is a saved preference. A little hysteresis (trim
        # only past keep + 100) keeps this off the hot path: we do not reslice the
        # whole list on every single line once the cap is reached.
        keep = self.pref("log_lines")
        self._log_lines.append(line)
        if len(self._log_lines) > keep + 100:
            self._log_lines = self._log_lines[-keep:]
        self.log_box.config(state="normal")
        self.log_box.insert("end", line + "\n")
        try:            # keep the widget bounded too, not just the in-memory list
            count = int(self.log_box.index("end-1c").split(".")[0])
            if count > keep + 100:
                self.log_box.delete("1.0", f"{count - keep}.0")
        except Exception as _exc:
            crashlog.note(_exc, "gui.app")
        self.log_box.see("end")
        self.log_box.config(state="disabled")


# -- backwards-compatible attribute names --------------------------------------- #
# The GUI smoke and PROJECT_NOTES refer to these names; they now proxy the
# registry-keyed variables instead of being separate attributes.
def _var_property(key):
    return property(lambda self: self.vars[key])


for _name, _key in (("loss_var", "loss"), ("corr_var", "corrupt"), ("dup_var", "dup"),
                    ("lat_var", "latency"), ("jit_var", "jitter"),
                    ("down_var", "down"), ("up_var", "up"),
                    ("syn_var", "syn_drop"), ("mtu_var", "max_size"),
                    ("spike_prob_var", "spike_prob"), ("spike_ms_var", "spike_ms"),
                    ("nat_var", "nat_timeout"), ("rst_var", "rst_prob"),
                    ("sched_var", "rate_schedule"), ("seed_var", "seed"),
                    ("target_var", "target"), ("dst_ip_var", "dst_ip"),
                    ("dst_port_var", "dst_port"), ("lan_var", "lan_mode"),
                    ("flap_period", "flap_period"), ("flap_downpct", "flap_down"),
                    ("filter_var", "filter")):
    setattr(App, _name, _var_property(_key))


# older private names kept working (docs, scripts, the GUI smoke)
App._apply_if_running = App.apply_if_running
App._export_csv = App.export_csv
App._save_profile = App.save_profile
App._delete_profile = App.delete_profile
App._load_selected_profile = App.load_selected_profile
App._load_scenario = App.load_scenario
App._clear_scenario = App.clear_scenario
App._load_config_file = App.load_config_file
App._save_config_file = App.save_config_file
App._mark_bug = App.mark_bug
App._save_repro = App.save_repro
App._copy_repro_cli = App.copy_repro_cli
App._reset_now_click = App.reset_now_click
App._on_close = App.on_close
App._profile_names = App.profile_names
