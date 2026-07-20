"""GUI preferences (``gui/prefs.py``): the ui.json-backed settings.

These are NOT engine fields - no CLI flag, no config-file coupling - so they have
their own small registry and their own guards: the registry stays honest (every
pref is grouped and translated), the accessors validate, and each wired behaviour
(chart history, log length, close-confirm, restore-on-start, reset-layout) does
what the switch promises.
"""
from beantester.gui import prefs
from beantester.gui.prefs import PREFS, PREFS_BY_KEY, PREF_GROUPS, BOOL, NUMBER, coerce
from beantester.i18n import set_language, translate
from fakes import check
from gui_harness import run_gui


# -- registry (pure) -------------------------------------------------------- #
def test_every_pref_is_grouped_exactly_once():
    grouped = [k for _, keys in PREF_GROUPS for k in keys]
    check("prefs: every pref appears in a group", set(grouped) == set(PREFS_BY_KEY))
    check("prefs: no pref is listed in two groups", len(grouped) == len(set(grouped)))


def test_pref_texts_resolve_in_every_language():
    keys = []
    for p in PREFS:
        keys += [p.label, p.tip] + [k for k in (p.unit_key, p.hint) if k]
    keys += [label for label, _ in PREF_GROUPS]
    for lang in ("en", "pl"):
        unresolved = [k for k in keys if translate(k, lang) == k]
        check(f"prefs: all texts resolve in {lang}", not unresolved, f"({unresolved})")
    set_language("pl")


def test_coerce_validates_and_falls_back():
    chart = PREFS_BY_KEY["chart_seconds"]        # NUMBER, bounds (10, 3600)
    check("prefs: a number passes through", coerce(chart, "120") == 120)
    check("prefs: out-of-range clamps to the bound", coerce(chart, 999999) == 3600)
    check("prefs: below-range clamps up", coerce(chart, 1) == 10)
    check("prefs: garbage falls back to the default", coerce(chart, "nope") == chart.default)
    confirm = PREFS_BY_KEY["confirm_close"]       # BOOL
    check("prefs: bool coerces", coerce(confirm, "") is False and coerce(confirm, 1) is True)


# -- accessors + persistence ------------------------------------------------ #
def test_pref_accessors_round_trip_and_persist():
    run_gui("""
        # unset -> the declared default
        assert app.pref("confirm_close") is True
        assert app.pref("chart_seconds") == 120

        app.set_pref("confirm_close", False)
        app.set_pref("chart_seconds", 300)
        assert app.pref("confirm_close") is False
        assert app.pref("chart_seconds") == 300
        # set_pref writes through to the ui.json store (key is "pref.<key>")
        assert app.ui.get("pref.confirm_close") is False
        assert app.ui.get("pref.chart_seconds") == 300
    """)


# -- wired behaviours ------------------------------------------------------- #
def test_confirm_close_switch_is_honoured():
    run_gui("""
        from beantester.gui import dialogs
        asked = []
        dialogs.ask_yes_no = lambda *a, **k: asked.append(1) or False

        app.running = True
        app.set_pref("confirm_close", True)
        app.on_close()                       # must ASK (and we answered no -> abort)
        assert asked, "confirm_close on must prompt while running"

        asked.clear()
        app._closing = False
        app.running = True
        app.set_pref("confirm_close", False)
        app.on_close()                       # must NOT ask
        assert not asked, "confirm_close off must not prompt"
    """)


def test_chart_history_length_follows_the_preference():
    run_gui("""
        base = app.chart_samples()
        assert app.down_hist.maxlen == base

        app.set_pref("chart_seconds", 700)   # 700 s / 0.7 s per sample = 1000 samples
        assert app.chart_samples() == 1000
        app._reconcile_chart_len()
        assert app.down_hist.maxlen == 1000
        assert app.up_hist.maxlen == 1000
    """)


def test_a_resized_chart_spans_its_whole_window_at_once():
    """A widened chart must FILL the new window, not creep into it.

    The X axis is labelled from the number of samples the chart is handed, so a
    history that only grows a sample per tick keeps reporting the old window:
    raising the preference used to leave the axis at "-28 s", counting up for
    minutes, under a caption that already said 250. maxlen alone (the assertion
    above) never saw it - maxlen was right the whole time, len was not.
    """
    run_gui("""
        app.down_hist.append(11.0)           # newest sample, must stay newest
        app.up_hist.append(22.0)

        app.set_pref("chart_seconds", 250)
        app._reconcile_chart_len()
        n = app.chart_samples()
        assert len(app.down_hist) == n, (len(app.down_hist), n)
        assert len(app.up_hist) == n, (len(app.up_hist), n)
        assert app.down_hist[-1] == 11.0 and app.up_hist[-1] == 22.0
        assert app.down_hist[0] == 0 and app.up_hist[0] == 0

        app.set_pref("chart_seconds", 30)    # shrinking keeps the newest samples
        app._reconcile_chart_len()
        n = app.chart_samples()
        assert len(app.down_hist) == n, (len(app.down_hist), n)
        assert app.down_hist[-1] == 11.0 and app.up_hist[-1] == 22.0
    """)


def test_log_length_follows_the_preference():
    run_gui("""
        app.set_pref("log_lines", 50)
        for i in range(400):
            app._append_log_line(f"line {i}")
        # kept list is bounded to the preference (plus a small hysteresis margin)
        assert len(app._log_lines) <= 50 + 100, len(app._log_lines)
        assert app._log_lines[-1] == "line 399"
    """)


def test_restore_last_profile_fills_only_when_enabled():
    run_gui("""
        from beantester.presets import PRESETS
        key = list(PRESETS)[-1]              # the worst preset, definitely not default

        # off: startup restore is a no-op even with a saved profile
        app.set_pref("restore_profile", False)
        app.ui.set("profile", key)
        app.select_profile("presets.perfect")
        app._restore_last_profile()
        assert app._profile_key == "presets.perfect", app._profile_key

        # on: the saved profile is refilled (form only - never auto-applied)
        app.set_pref("restore_profile", True)
        app.ui.set("profile", key)
        app._restore_last_profile()
        assert app._profile_key == key, app._profile_key
    """)


def test_restore_last_profile_covers_the_users_own_profiles():
    """Saving a profile is how a user ends up ON their own profile, and that path
    used to change the current profile without remembering it - so the restore
    preference reopened on the preset picked before the save. Deleting one must
    remember the fallback, not the name that no longer exists."""
    run_gui("""
        import beantester.gui.dialogs as _dlg
        app.set_pref("restore_profile", True)
        app.select_profile("presets.terrible")

        _dlg.ask_string = lambda *a, **k: "My VPN"
        app.save_profile()
        assert app._profile_key == "My VPN", app._profile_key
        assert app.ui.get("profile") == "My VPN", app.ui.get("profile")

        # a fresh start would refill it, not the preset picked before the save
        app.select_profile("presets.perfect")
        app.ui.set("profile", "My VPN")
        app._restore_last_profile()
        assert app._profile_key == "My VPN", app._profile_key

        app.delete_profile()
        assert app.ui.get("profile") == "presets.perfect", app.ui.get("profile")

        # a profile that vanished while the app was closed: ignored, and the dead
        # pointer is dropped rather than kept forever
        app.ui.set("profile", "gone for good")
        app._restore_last_profile()
        assert app._profile_key == "presets.perfect", app._profile_key
        assert app.ui.get("profile") == "", app.ui.get("profile")
    """)


def test_settings_window_number_field_validates_before_persisting():
    """A numeric preference edited in the window persists only when valid, and
    paints the field red (without storing garbage) when it is not."""
    run_gui("""
        panel = app.open_window("settings")
        var = panel._pref_vars["chart_seconds"]
        entry = panel._pref_entries["chart_seconds"]

        from beantester.gui.prefs import PREFS_BY_KEY
        var.set("240")
        panel._on_pref_number(PREFS_BY_KEY["chart_seconds"])
        assert entry.kw.get("style") == "TEntry"
        assert app.pref("chart_seconds") == 240

        # out of range: field goes red, the stored value is untouched
        var.set("999999")
        panel._on_pref_number(PREFS_BY_KEY["chart_seconds"])
        assert entry.kw.get("style") == "Bad.TEntry"
        assert app.pref("chart_seconds") == 240

        # not a number: same
        var.set("abc")
        panel._on_pref_number(PREFS_BY_KEY["chart_seconds"])
        assert entry.kw.get("style") == "Bad.TEntry"
        assert app.pref("chart_seconds") == 240
    """)


def test_settings_window_number_field_says_why_it_is_red():
    """A red border is not a reason. The registry field on the same window (the
    row limit) named its allowed range from day one, while the preferences only
    turned red - the same mistake looked like two different bugs. Every reason is
    listed under its own group, and the line disappears once the value is good."""
    run_gui("""
        panel = app.open_window("settings")
        from beantester.gui.prefs import PREFS_BY_KEY
        err, keys = panel._pref_errors["prefs.group_view"]
        assert "chart_seconds" in keys and "log_lines" in keys

        panel._pref_vars["chart_seconds"].set("2")          # bounds are (10, 3600)
        panel._on_pref_number(PREFS_BY_KEY["chart_seconds"])
        assert err.pack_info is not None, "the reason must be shown, not just the red box"
        first = err.kw["text"]
        assert "3600" in first and "10" in first, first

        # a second bad field in the same group adds a reason, it does not replace one
        panel._pref_vars["log_lines"].set("3")              # bounds are (50, 100000)
        panel._on_pref_number(PREFS_BY_KEY["log_lines"])
        both = err.kw["text"]
        assert first in both and "100000" in both, both

        # fixing one clears only its own reason
        panel._pref_vars["chart_seconds"].set("120")
        panel._on_pref_number(PREFS_BY_KEY["chart_seconds"])
        assert first not in err.kw["text"] and "100000" in err.kw["text"], err.kw["text"]

        # fixing the last one takes the whole line away again
        panel._pref_vars["log_lines"].set("500")
        panel._on_pref_number(PREFS_BY_KEY["log_lines"])
        assert err.kw["text"] == "", err.kw["text"]
        assert err.pack_info is None
    """)


def test_reset_ui_layout_forgets_window_state():
    run_gui("""
        from beantester.gui import dialogs
        dialogs.ask_yes_no = lambda *a, **k: True

        app.ui.set("geometry", "800x600+10+10")
        app.ui.set("collapsed", ["advanced", "flapping"])
        app.collapsed_sections = ["advanced", "flapping"]

        app.reset_ui_layout()
        assert app.ui.get("geometry") == "", app.ui.get("geometry")
        assert app.ui.get("collapsed") == []
        assert app.collapsed_sections == []
    """)
