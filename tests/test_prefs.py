"""GUI preferences (``gui/prefs.py``): the ui.json-backed settings.

These are NOT engine fields - no CLI flag, no config-file coupling - so they have
their own small registry and their own guards: the registry stays honest (every
pref is grouped and translated), the accessors validate, and each wired behaviour
(chart history, log length, close-confirm, restore-on-start, reset-layout) does
what the switch promises.
"""
from beantester.gui import prefs
from beantester.gui.prefs import PREFS, PREFS_BY_KEY, PREF_GROUPS, coerce
from beantester.i18n import set_language, translate
from fakes import check
from gui_harness import run_gui


# -- registry (pure) -------------------------------------------------------- #
def test_every_pref_is_rendered_in_exactly_one_place():
    """A pref belongs to a preference GROUP or to a registry SECTION - never both,
    never neither. Either way it is unreachable in the window, which is the whole
    failure this guards: a preference nobody can find is a preference that does
    not exist.

    "Show only the targeted traffic" is the one that names a section: it has to be
    read next to "Capture only the targeted traffic", and those two live in
    different registries on purpose (convention 42).
    """
    grouped = [k for _, keys in PREF_GROUPS for k in keys]
    check("prefs: no pref is listed in two groups", len(grouped) == len(set(grouped)))
    sectioned = {p.key for p in PREFS if p.section}
    both = sorted(set(grouped) & sectioned)
    check("prefs: no pref is both grouped and sectioned", not both, f"({both})")
    homeless = sorted(set(PREFS_BY_KEY) - set(grouped) - sectioned)
    check("prefs: every pref is rendered somewhere", not homeless, f"({homeless})")


def test_a_pref_can_only_name_a_section_that_will_actually_render_it():
    """A typo in ``Pref.section`` fails SILENTLY - nothing looks the id up, the
    extra builder simply never asks for that pref, and the checkbox is gone from
    the window with nobody the wiser. Same class as a stray id in
    ``FIRST_RUN_COLLAPSED``.

    The section must also be on the SETTINGS surface and declare an ``extra``
    builder, since that is the only hook a pref can be rendered through.
    """
    from beantester.fields import SECTIONS, SETTINGS_SECTIONS
    by_id = {s.id: s for s in SECTIONS}
    settings_ids = {s.id for s in SETTINGS_SECTIONS}
    for p in PREFS:
        if not p.section:
            continue
        sec = by_id.get(p.section)
        check(f"prefs: {p.key} names a real section", sec is not None, p.section)
        check(f"prefs: {p.key} names a Settings-window section",
              p.section in settings_ids, p.section)
        check(f"prefs: the {p.section} section has an extra builder to render it",
              bool(sec.extra), repr(sec.extra))
        check(f"prefs: {p.key} is reachable through prefs_in_section",
              p in prefs.prefs_in_section(p.section))


def test_only_prefs_that_can_show_a_hint_declare_one():
    """A hint on a checkbox is text nobody will ever read.

    ``SettingsWindow._build_pref_row`` handles BOOL and ACTION first and
    **returns**, so only a NUMBER row ever reaches the line that draws
    ``pref.hint``. Nothing raises: the text is simply written, translated into
    every language, and then shown to no one.

    Measured, not hypothetical. ``scope_view_to_target`` carried a 250-character
    hint that never appeared on screen - and its TOOLTIP had grown into the
    longest string in the language files trying to carry the same explanation.
    That is word for word what
    ``test_field_registry.py::test_only_fields_that_can_show_a_hint_declare_one``
    already records about ``narrow_filter``: the same hole, one registry over,
    which is why this guard is its mirror rather than a new idea.
    """
    stray = [(p.key, p.kind) for p in PREFS if p.hint and p.kind != prefs.NUMBER]
    check("prefs: no pref declares a hint its row cannot show",
          not stray, f"({stray})")


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


def test_the_first_run_collapse_list_names_real_sections():
    """A typo in ``FIRST_RUN_COLLAPSED`` fails SILENTLY.

    Nothing looks the id up - the form asks "is my id in this list", so an entry
    that matches no section simply never matches, and the panel it was meant to
    fold opens on a fresh install with nobody the wiser. Same class as a preset
    with no translation or a column missing from the docs: wrong, and invisible.

    The list also has to name CONTROL-page sections. Collapsing a Settings-window
    section from here would be a line that reads as if it did something.
    """
    from beantester.fields import CONTROL_SECTIONS
    from beantester.gui.app import FIRST_RUN_COLLAPSED
    control = {s.id for s in CONTROL_SECTIONS}
    stray = [s for s in FIRST_RUN_COLLAPSED if s not in control]
    assert not stray, (stray, sorted(control))
    assert len(set(FIRST_RUN_COLLAPSED)) == len(FIRST_RUN_COLLAPSED), FIRST_RUN_COLLAPSED
    # and the panels a first-time user needs must NOT be folded away
    for stays_open in ("profiles", "traffic", "latency", "impairments"):
        assert stays_open not in FIRST_RUN_COLLAPSED, stays_open


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


def test_the_control_search_bar_can_be_switched_off_and_back_on():
    """The box goes away, and comes back ABOVE the page body.

    The order is the part that can go wrong silently: pack hands out space in
    CALL order, so a bar re-packed after the scroller exists lands UNDER the whole
    page unless it names what to sit before.

    Upgraded 2026-08-20: the fake now models pack order, so this asserts the bar
    is BACK ABOVE the page body rather than merely that the call carried
    ``before=``. Until then the real question had to go to a live render, because
    ``pack_slaves`` answered in creation order and could not tell the two apart.
    """
    run_gui("""
        page = app.pages["control"]
        assert app.pref("show_control_search") is True, "default is: the box is there"
        assert page._bar.winfo_ismapped(), "the bar should start on the page"

        app.set_pref("show_control_search", False)
        page.on_pref_changed("show_control_search")
        assert not page._bar.winfo_ismapped(), "the bar is still on the page"

        app.set_pref("show_control_search", True)
        page.on_pref_changed("show_control_search")
        assert page._bar.winfo_ismapped(), "the bar did not come back"
        assert page._bar.pack_info.get("before") is page.scroll.vsb, (
            "re-packed without before= - it would sit under the page body")
        packed = page.frame.pack_slaves()
        assert packed.index(page._bar) < packed.index(page.scroll.canvas), (
            "the bar came back UNDER the page body: %r" % (packed,))

        # an unrelated preference must not move it
        page.on_pref_changed("chart_seconds")
        assert page._bar.winfo_ismapped()
    """)


def test_hiding_the_search_takes_its_marks_and_its_folds_with_it():
    """The marks are painted on the FORM, not on the bar.

    So a query left standing when the box goes away leaves fields highlighted
    with nothing left to clear them from, and the sections the search unfolded
    stay unfolded. A debounce still in flight would repaint both a moment after
    the bar was gone, which is why the pending job is cancelled rather than left
    to run against a hidden box.
    """
    run_gui("""
        page = app.pages["control"]
        page.query_var.set("port")
        page._apply()
        assert page._targets, "the fixture needs a query that actually matches"
        marked = [w for w, _kind, _old in page._marks]
        assert marked

        # A debounce in flight. The fake's `after` returns nothing, so the job is
        # planted by hand and the cancel is recorded - what matters is that the
        # timer is taken back, not how the fake numbers it.
        cancelled = []
        page._job = "pending-search"
        page.frame.after_cancel = lambda job: cancelled.append(job)

        app.set_pref("show_control_search", False)
        page.on_pref_changed("show_control_search")

        assert cancelled == ["pending-search"], cancelled
        assert page._job is None, "a pending search would repaint a hidden box"
        assert page.query_var.get() == ""
        assert page._marks == [], "fields left highlighted with no box to clear them"
        assert not page._opened, "sections the search opened stayed open"
        for widget in marked:
            assert not str(widget.cget("style")).startswith("Hit"), widget.kw
    """)


def test_a_hidden_search_bar_survives_a_language_switch():
    """The page is REBUILT from scratch by a language switch, and the rebuild
    packs the bar before anything reads the preference - so the state has to be
    re-applied, not assumed."""
    run_gui("""
        app.set_pref("show_control_search", False)
        app.pages["control"].on_pref_changed("show_control_search")

        app.lang_var.set(app._lang_name2code and "English" or "English")
        app._switch_language()

        page = app.pages["control"]
        assert not page._bar.winfo_ismapped(), "the rebuilt page brought the bar back"
        assert page.focus_search() is False
    """)


def test_the_settings_checkbox_hides_the_search_immediately():
    """End to end, through the window the user actually clicks.

    Storing alone is not enough here: every other preference is re-read by the
    next tick anyway, but a widget appearing or disappearing up to 0.7 s after
    the click reads as a broken checkbox. This is the path that closes that gap
    (``SettingsWindow._store`` -> ``gui/pages/pref_changed``).
    """
    run_gui("""
        page = app.pages["control"]
        panel = app.open_window("settings")
        var = panel._pref_vars["show_control_search"]

        var.set(False)
        panel._store("show_control_search", False)
        assert app.pref("show_control_search") is False, "not persisted"
        assert not page._bar.winfo_ismapped(), "still on the page after the click"

        var.set(True)
        panel._store("show_control_search", True)
        assert page._bar.winfo_ismapped(), "the box did not come back"
    """)
