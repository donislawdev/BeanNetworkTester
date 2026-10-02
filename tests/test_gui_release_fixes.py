"""GUI regressions for the 1.3 release fixes (run on the fake tkinter)."""
from pathlib import Path

from gui_harness import run_gui


def test_the_form_starts_on_a_perfect_link():
    """It used to open on a hidden 100 ms / 20 ms / 1% impairment."""
    run_gui("""
        assert app._profile_key == "presets.perfect"
        assert app.profile_var.get() == bnt.T("presets.perfect")
        s = app._settings_from_widgets()
        assert (s["latency"], s["jitter"], s["loss"]) == (0.0, 0.0, 0.0), s
        assert app._summary_text in (None, bnt.T("summary.none"))
    """)


def test_a_profile_survives_a_language_switch():
    """The combobox stored the DISPLAYED name, so switching language left an
    English name sitting over a Polish list (and no lookup could find it)."""
    run_gui("""
        app.profile_var.set(bnt.T("presets.roaming"))
        app.load_selected_profile()
        assert app._profile_key == "presets.roaming"
        assert app.profile_var.get() == "Roaming zagraniczny"

        app.lang_var.set("English")
        app._switch_language()
        assert app._profile_key == "presets.roaming"           # unchanged
        assert app.profile_var.get() == "Foreign roaming"      # now in English
        assert app.profile_var.get() in app.profile_names()    # not stale in the menu
    """)


def test_delete_is_disabled_for_a_built_in_preset():
    """It used to look live and then silently do nothing."""
    run_gui("""
        assert app.btn_delete_profile.kw.get("state") == "disabled"

        app.profiles.set("Moje VPN", {k: 0.0 for k in
                                      ("loss", "corrupt", "dup", "lat", "jit", "down", "up")})
        app._profile_key = "Moje VPN"
        app._sync_profile_widgets()
        assert app.btn_delete_profile.kw.get("state") == "normal"

        app.delete_profile()
        assert "Moje VPN" not in app.profiles
        # The fallback is what the NEXT start restores (test_prefs pins that);
        # now no profile is named, because the form still holds the deleted
        # one's values (external review, P3-27).
        assert app.ui.get("profile") == "presets.perfect", app.ui.get("profile")
        assert app._profile_key == "", app._profile_key
        assert app.btn_delete_profile.kw.get("state") == "disabled"
    """)


def test_deleting_the_loaded_profile_names_no_profile_over_its_values():
    """External review, P3-27: the picker read "Perfect network" while the form
    still held the deleted profile's impairments, and START applied them under
    that name. A language switch refills the picker - it must stay blank."""
    run_gui("""
        app.loss_var.set("37")
        app.profiles.set("Moje VPN", app._settings_from_widgets())
        app.select_profile("Moje VPN")
        app.delete_profile()
        assert app.loss_var.get() == "37", "deleting a profile must not reset the form"
        assert app.profile_var.get() == "", app.profile_var.get()
        app.lang_var.set("English")
        app._switch_language()
        assert app.profile_var.get() == "", app.profile_var.get()
    """)


def test_ctrl_c_copies_the_selected_rows():
    run_gui("""
        import fake_tk
        page = app.pages["connections"]
        table = page.table
        table.sync([("a", ("chrome.exe", "TCP", "1.2.3.4", "443", "5000", "7", "0.5", "1.0", "0.1")),
                    ("b", ("msedge.exe", "TCP", "5.6.7.8", "80", "5001", "3", "0.1", "0.2", "0.0"))])
        # the table is virtualised: its widget item ids are recycled viewport slots,
        # so a row is selected by its MODEL key, not by a widget id
        table.select_keys(["a", "b"])
        assert table.selected_keys() == ["a", "b"]

        fake_tk.CLIPBOARD.clear()
        table._on_copy()
        text = "".join(fake_tk.CLIPBOARD)
        assert text.count("\\n") == 1, text            # two rows
        assert "chrome.exe\\tTCP\\t1.2.3.4" in text, text
        assert "msedge.exe" in text, text
    """)


def test_column_widths_are_bounded():
    """ttk has minwidth but no maximum: a column could be dragged over everything."""
    run_gui("""
        table = app.pages["connections"].table
        natural = table.tree.column("proc", "width")
        table.tree.column("proc", width=natural * 20)
        table.clamp_widths()
        assert table.tree.column("proc", "width") == table.max_width("proc")
        assert table.tree.column("proc", "width") < natural * 20

        table.reset_widths()
        assert table.tree.column("proc", "width") == natural
    """)


def test_the_bug_marker_row_is_colour_coded():
    run_gui("""
        app.running = True
        app.engine.start("test", divert=bnt.SyntheticDivert(gen_kbps=1))
        app.engine.log_event("BUG", "events.bug_marker")
        stats = app.pages["statistics"]
        stats.select("events")
        stats.refresh_events()
        app.engine.stop()

        tree = stats.events.tree
        tagged = {tree.tags[iid][0] for iid in tree.order if tree.tags[iid]}
        assert "BUG" in tagged, tagged
        assert "BUG" in tree.tag_styles, tree.tag_styles
    """)


def test_tooltip_is_suppressed_while_a_dropdown_is_open():
    """A profile/preset tooltip used to fire over the just-opened combobox list,
    covering the very options the user was about to pick."""
    run_gui("""
        from beantester.gui import tooltip
        w = app.profile_cb

        assert tooltip._grab_active(w) is False           # nothing grabbing yet

        root.grab_set()                                   # popdown opens -> grab
        assert tooltip._grab_active(w) is True
        # short-circuits before touching the bubble window
        assert tooltip._show_bubble(w, "Presets", 100, 100) is None
    """)


def test_short_dropdowns_do_not_spawn_a_popdown_scrollbar():
    """A list that fits must not add the popdown scrollbar - it renders as a light
    bar over the near-black dropdown. height == item count keeps ttk from adding one."""
    run_gui("""
        assert app.filter_cb.kw.get("height") == len(app.filter_display), app.filter_cb.kw
        app.open_window("settings")      # the language box lives in Settings now
        assert app.lang_cb.kw.get("height") == len(app._lang_name2code), app.lang_cb.kw
    """)


def test_profile_picker_is_the_same_widget_as_the_traffic_filter():
    """Conv 41: a dropdown looks like its sibling by BEING it. The picker spent a
    while as a Menubutton + tk.Menu imitating a combobox, and the imitation could
    not be finished - on Windows a tk.Menu is a native Win32 popup, so its frame,
    its width and the highlight on the current row are outside Tk's reach."""
    source = (Path(__file__).resolve().parents[1]
              / "beantester" / "gui" / "pages" / "control.py").read_text(encoding="utf-8")
    assert "ttk.Combobox(" in source
    assert "Menubutton" not in source and "tk.Menu(" not in source
    run_gui("""
        cb = app.profile_cb
        assert cb.kw.get("state") == "readonly", cb.kw
        assert not cb.kw.get("style"), cb.kw        # the plain, shared TCombobox look
        assert list(cb.kw["values"]) == app.profile_names(), cb.kw
        # a list that fits must not spawn the popdown scrollbar
        assert cb.kw["height"] == len(app.profile_names()), cb.kw
    """)


def test_scenario_dialog_defaults_to_the_bundled_scenarios_dir():
    """The picker used to open wherever the OS last left it; the examples live under
    _internal/scenarios, which the user would never find on their own."""
    import os
    from beantester.paths import scenarios_dir
    d = scenarios_dir()
    assert os.path.basename(d) == "scenarios"
    assert os.path.isdir(d)


def test_shortcut_buttons_advertise_their_key():
    """A control with a keyboard shortcut must show it in its own tooltip (conv 40).

    It used to assert on btn_start and btn_apply only, so dropping `shortcut=` from
    "Save file" or "Load file" left the suite green (verified by mutation, 2026-07-21).
    Every button that has a binding in `_bind_shortcuts` is listed here.

    And every control that binds its OWN shortcut, which is the half this test did
    not have when Ctrl+F arrived (2026-08-03): the Connections search box binds it
    on the root itself, so a control outside `_bind_shortcuts` can advertise
    nothing and nobody would notice.
    """
    run_gui("""
        for attr, key in (("btn_start", "F5"), ("btn_apply", "Ctrl+Enter"),
                          ("btn_save", "Ctrl+S"), ("btn_load", "Ctrl+O")):
            widget = getattr(app, attr)
            tip = getattr(widget, "_bnt_tooltip", None)
            assert tip is not None, attr + " lost its tooltip"
            assert key in tip.text, attr + " does not advertise " + key + ": " + tip.text

        entry = app.pages["connections"]._search_entry
        tip = getattr(entry, "_bnt_tooltip", None)
        assert tip is not None, "the search box lost its tooltip"
        assert "Ctrl+F" in tip.text,             "the search box does not advertise Ctrl+F: " + tip.text
    """)


def test_the_wheel_does_not_scroll_the_page_behind_an_open_dropdown():
    run_gui("""
        import fake_tk
        scrolled = []
        app._wheel._resolve = lambda w: ("native", type("T", (), {
            "yview_scroll": lambda self, *a: scrolled.append(a)})())

        event = type("E", (), {"delta": -120, "num": None, "widget": None,
                               "x_root": 10, "y_root": 10})()
        fake_tk.GRAB[0] = None
        app._wheel._on_wheel(event)
        assert scrolled, "the wheel must still scroll when nothing is grabbed"

        scrolled.clear()
        fake_tk.GRAB[0] = object()          # a combobox popdown is open
        app._wheel._on_wheel(event)
        assert not scrolled, "the page must not move under an open dropdown"
        fake_tk.GRAB[0] = None
    """)


def test_the_window_is_capped_and_cannot_be_maximised():
    run_gui("""
        maximum = app.root.kw.get("maxsize")
        assert maximum and maximum[0] > 0 and maximum[1] > 0, maximum
        screen = (app.root.winfo_screenwidth(), app.root.winfo_screenheight())
        assert maximum[0] <= screen[0] and maximum[1] <= screen[1], maximum
        assert "zoomed" not in app.ui.data
    """)


def test_a_target_that_matches_nothing_says_so_on_the_page():
    """A run in which nothing broke looks exactly like a run in which it held up.

    ``_refresh_target_verdict`` only records the verdict on the APPLIED target;
    the banner itself is put on screen by the main thread (``_tick`` ->
    ``_drain_target_warning``).
    """
    run_gui("""
        from beantester.settings import apply_targeting

        apply_targeting(app.engine, "definitely-no-such-process", announce=False)
        app._applied_target = "definitely-no-such-process"
        app._refresh_target_verdict()
        app._drain_target_warning()          # what _tick() does on the main thread
        assert app.target_warning.kw.get("text") == bnt.T("fields.target_no_match")
        assert app.target_warning.winfo_ismapped()

        apply_targeting(app.engine, "", announce=False)
        app._applied_target = ""
        app._refresh_target_verdict()
        app._drain_target_warning()
        assert app.target_warning.kw.get("text") == ""
        assert not app.target_warning.winfo_ismapped()
    """)


def test_a_target_that_cannot_be_used_says_everything_is_impaired():
    """The banner used to say the OPPOSITE of the truth here.

    A target that was applied but could not be used - no psutil, an expression
    that narrows nothing, a regex refused at apply time - leaves the engine with
    no targeting at all, so EVERY connection in the filter is impaired. The banner
    said "traffic is NOT being impaired". Both ways in (START and "Apply
    changes") are covered, and the banner goes away with the session.
    """
    run_gui("""
        from beantester.synthetic import SyntheticDivert

        def no_psutil(matcher):
            raise ImportError("psutil is not installed")

        app.engine.target_for = no_psutil
        real_start = app.engine.start
        app.engine.start = (lambda filt, divert=None, duration=0, **kw:
                            real_start(filt, divert=SyntheticDivert(seed=3),
                                       duration=duration))
        everything = bnt.T("fields.target_all_traffic")

        app.vars["target"].set("chrome.exe")
        app._start(); app._settle_transition()
        assert app.running and app.engine.targeting() is None
        app._tick(); app._tick()     # verdict, then render
        assert app._pending_target_warning == everything, app._pending_target_warning
        assert app.target_warning.kw.get("text") == everything

        app.vars["target"].set("")                  # applied: nothing was aimed at
        app.apply_if_running()
        app._tick(); app._tick()     # verdict, then render
        assert app._pending_target_warning == "", app._pending_target_warning

        app.vars["target"].set("firefox.exe")       # applied again, same failure
        app.apply_if_running()
        app._tick(); app._tick()     # verdict, then render
        assert app._pending_target_warning == everything, app._pending_target_warning

        app._stop(); app._settle_transition()
        app._tick(); app._tick()     # verdict, then render
        assert app._pending_target_warning == "", "the banner outlived the session"
        assert not app.target_warning.winfo_ismapped()
    """, allow_faults=("psutil is not installed",))


def test_start_only_fields_are_locked_while_a_session_runs():
    """EVERY field the registry marks start_only greys out mid-session, on
    whichever surface renders it.

    This used to name ``duration`` and the filter combobox by hand, which made it
    a test of two EXAMPLES rather than of the rule (convention 16's mistake, and
    PROJECT_NOTES rule 2.6: one value, several consumers, a guard on one of them).
    ``narrow_filter`` was added to the registry later, landed on the Settings
    window's own ControlForm, and stayed clickable for an entire session whenever
    that window was open before START - with this test green throughout. Deriving
    the list from FIELD_DEFS means the fourth start_only field cannot repeat it.

    The window is opened BEFORE the session starts on purpose: that is the order
    that was broken. Opened after, the build path already read the registry.
    """
    run_gui("""
        from beantester.fields import CHOICE, FIELD_DEFS, FIELDS, SECTIONS

        surface_of = {key: sec.surface for sec in SECTIONS for key in sec.fields}
        start_only = [f.key for f in FIELD_DEFS if f.start_only]
        assert start_only, "no start_only field in the registry - the rule lost its subject"

        app.open_window("settings")
        settings_form = app.windows._open["settings"].form

        def widget(key):
            # the traffic filter is a CHOICE and belongs to App, not to a form
            if FIELDS[key].kind == CHOICE:
                return app.filter_cb
            form = settings_form if surface_of[key] == "settings" else app.form
            return form.entries[key]

        for key in start_only:
            assert widget(key).kw.get("state") in (None, "normal", "readonly"), key

        app.running = True
        app._sync_running_ui()
        for key in start_only:
            assert widget(key).kw.get("state") == "disabled", (
                key + " stayed editable while a session was running")

        app.running = False
        app._sync_running_ui()
        for key in start_only:
            expected = ("readonly" if FIELDS[key].kind == CHOICE
                        else "normal")
            assert widget(key).kw.get("state") == expected, key
    """)


def test_the_scenario_controls_lock_while_a_session_runs():
    """External review P2-17, owner decisions D-6 and D-29.

    Load and Clear changed the label and the log mid-session while the timeline
    started at START went on unchanged, and Loop is read at START only. They lock
    with the START-only fields, and the section's note says why - a disabled
    button cannot explain itself.
    """
    run_gui("""
        from beantester.i18n import T

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        texts = {T("buttons.load_scenario"), T("buttons.clear"), T("fields.loop")}
        body = app.form.sections["repro"].body
        controls = [w for w in descendants(body) if w.kw.get("text") in texts]
        assert len(controls) == 3, [w.kw.get("text") for w in descendants(body)]
        note = app.form.notes["repro"]

        app.running = True
        app._sync_running_ui()
        assert [w.kw.get("state") for w in controls] == ["disabled"] * 3, controls
        assert note.kw.get("text") == T("fields.locked_running"), note.kw

        app.running = False
        app._sync_running_ui()
        assert [w.kw.get("state") for w in controls] == ["normal"] * 3, controls
        assert not note.kw.get("text"), note.kw
    """)


def test_a_column_switch_keeps_the_filter_the_lock_and_the_labels():
    """External review P2-16a, b, d.

    Crossing the one/two-column width rebuilds the form, and the widgets the App
    keeps in step came back as new: the filter the user had picked reverted to
    the previous one (and START captured that), the filter was editable
    mid-session, the scenario label said "no scenario" with one loaded, and
    "Delete" came back live for a built-in preset.
    """
    run_gui("""
        from types import SimpleNamespace
        from beantester.filters import i18n_key_for
        from beantester.i18n import T

        def switch_columns():
            app.form.set_columns(3 - app.form.columns)

        app.vars["filter"].set(T(i18n_key_for("out")))
        app.form._on_choice(SimpleNamespace(widget=app.filter_cb))
        switch_columns()
        assert app._filter_cli_key() == "out", app._filter_cli_key()

        app._scenario_name = "Scenario: mine.json"
        app._update_scenario_label()
        assert app.btn_delete_profile.kw.get("state") == "disabled", "a preset to start with"
        switch_columns()
        assert app.scenario_lbl.kw.get("text") == "Scenario: mine.json", app.scenario_lbl.kw
        assert app.btn_delete_profile.kw.get("state") == "disabled", app.btn_delete_profile.kw

        app.running = True
        app._sync_running_ui()
        switch_columns()
        assert app.filter_cb.kw.get("state") == "disabled", app.filter_cb.kw
        app.running = False
        app._sync_running_ui()
    """)


def test_long_notes_wrap_instead_of_being_cut():
    """The "all captured connections" note was clipped at the frame edge."""
    run_gui("""
        page = app.pages["connections"]
        notes = [w for w in page.frame.winfo_children()
                 if w.kw.get("text") == bnt.T("conns.scope_note")]
        assert notes, "the scope note is missing"
        wrap = notes[0].kw.get("wraplength")
        assert wrap and wrap > 0, notes[0].kw
        assert wrap <= notes[0].master.winfo_width(), (wrap, notes[0].master.winfo_width())
    """)


def test_the_ui_rebuild_does_not_pile_up_configure_handlers_on_the_root():
    """`_build_ui` runs on every language switch, and the root window outlives it.

    It used to bind `<Configure>` on the root each time - once for
    `_on_root_configure`, and once more for every banner built with
    `wrapping_label(root, ...)` - all with `add="+"` and nothing to remove them. So
    the handlers multiplied one per rebuild: measured 2 after the first build, 8
    after three language switches. Each is cheap, but it is O(rebuilds) work on
    every resize, forever. The handler is now bound once in __init__, and the
    banners wrap through it instead of self-binding, so the count is fixed at one.
    """
    run_gui("""
        def configure_handlers():
            return root.bindings.get("<Configure>", [])

        assert len(configure_handlers()) == 1, configure_handlers()

        for _ in range(4):                       # what four language switches do
            app._lang = "en" if app._lang == "pl" else "pl"
            app._build_ui()

        assert len(configure_handlers()) == 1, (
            "the rebuild leaked a <Configure> handler onto the root", configure_handlers())

        # ...and the banner still wraps: the leak was closed by folding it into the
        # single handler, not by dropping the wrapping. Assert the width-derived
        # value, not just "truthy" - a banner keeps its initial build-time
        # wraplength, so only checking for one would pass even if the fold were gone.
        from beantester.gui.scaling import scaled
        app.engine_warning.config(text="a long overflow warning that has to wrap")
        app._on_root_configure()
        assert app.engine_warning.kw.get("wraplength") == root.winfo_width() - scaled(28), (
            app.engine_warning.kw.get("wraplength"), root.winfo_width())
    """)


def test_a_resize_after_the_label_is_gone_is_not_a_crash():
    """``wrapping_label`` binds <Configure> on the CONTAINER, not on the label.

    The container routinely outlives the label - the two banners at app.py:395 and
    :403 hang off the root window itself, and every ``_build_ui`` rebuild destroys
    the labels and leaves their handlers behind. Nothing unbinds them, so the next
    resize called ``configure`` on a destroyed widget: TclError("invalid command
    name .!label"), recorded once per dead handler, and one more handler added per
    rebuild.
    """
    run_gui("""
        import tkinter as tk
        from beantester import crashlog
        from beantester.gui.labels import wrapping_label

        recorded = []
        crashlog.record = lambda exc, **kw: recorded.append(
            (type(exc).__name__, kw.get("subsystem")))

        holder = tk.Frame(app.root)
        label = wrapping_label(holder, "a note long enough to wrap")
        assert label.kw.get("wraplength"), "the label must wrap while it lives"

        handlers = holder.bindings.get("<Configure>") or []
        assert handlers, "wrapping_label must listen on its container"

        label.destroy()
        for handler in handlers:                    # the resize still arrives
            handler(type("Event", (), {"width": 500})())

        assert [r for r in recorded if r[1] == "gui.labels"] == [], recorded
    """)


def test_the_connection_table_has_no_stretch_columns():
    """A stretch column is recomputed by ttk and snaps back after a drag."""
    run_gui("""
        table = app.pages["connections"].table
        for col in table.columns:
            assert table.tree.cols[col].get("stretch") is False, col
    """)


def test_the_header_never_clips_the_donate_button():
    """At 1366x768 - the minimum resolution this tool documents - the Polish
    "Wesprzyj projekt" rendered as "Wesp".

    Tk's pack hands the LAST widget packed whatever space is left, and the donate
    button is last, so it is the one that gets cut off. English "Donate" fits,
    which is exactly why no test caught it: the bug only exists in the language
    most of the users speak. The author line - the only decorative thing in the
    header - gives way instead.
    """
    run_gui("""
        header = app.donate_btn.master
        donate = app.donate_btn

        # the fake tkinter reports fixed sizes, so state the situation outright:
        # a button that ASKS for 143 px and is only GIVEN 64 is a button with its
        # text cut off - which is exactly what "Wesprzyj projekt" -> "Wesp" was.
        donate.winfo_reqwidth = lambda: 143
        donate.winfo_width = lambda: 64

        app._author_shown = True
        app._fit_header(header, 762)
        assert not app._author_shown, "the author line must give way, not the button"

        # once the button is whole again and there is room to spare, it comes back
        donate.winfo_width = lambda: 143
        app.author_label.winfo_reqwidth = lambda: 117
        for child in header.winfo_children():
            if child is not app.author_label:
                child.winfo_reqwidth = lambda: 50
        app._fit_header(header, 4000)
        assert app._author_shown, "the author line must return on a wide window"
    """)


def test_the_queue_overflow_banner_is_actually_in_the_layout():
    """A banner that is not packed is not a warning.

    The first version packed it with ``before=self.nb`` - but the notebook lives
    inside its own holder, so it is not a sibling of the banner and pack() refuses.
    Wrapped in ``crashlog.quiet``, that refusal was silent: the widget existed, it
    had the text, ``winfo_ismapped()`` even said yes, and it drew NOTHING. Only
    rendering the window showed it. So the test is not "is there a label" - it is
    "is the label in the geometry manager's list".
    """
    run_gui("""
        # the tool is dropping the user's own packets
        app.engine.st["drop_overflow"] = 500
        app._drain_engine_warning()

        assert app.engine_warning.kw.get("text") == bnt.T("warn.queue_overflow")
        slaves = app.root.pack_slaves()
        assert app.engine_warning in slaves, (
            "the banner is not in the layout - it will render as nothing")

        # and it goes away again when the numbers are clean
        app.engine.st["drop_overflow"] = 0
        app._drain_engine_warning()
        assert app.engine_warning not in app.root.pack_slaves()
        assert app.engine_warning.kw.get("text") == ""
    """)


def test_the_banner_also_fires_when_the_tool_cannot_re_inject():
    """A failed injection loses the user's packets exactly as an overflow does,
    so it has to be as loud. Overflow keeps precedence: it is the one the user
    can act on by lowering the latency or the rate."""
    run_gui("""
        app.engine.st["drop_send"] = 12
        app._drain_engine_warning()
        assert app.engine_warning.kw.get("text") == bnt.T("warn.send_failed")
        assert app.engine_warning in app.root.pack_slaves(), (
            "the banner is not in the layout - it will render as nothing")

        # both at once: the overflow message wins, and neither is silent
        app.engine.st["drop_overflow"] = 3
        app._drain_engine_warning()
        assert app.engine_warning.kw.get("text") == bnt.T("warn.queue_overflow")

        app.engine.st["drop_overflow"] = 0
        app.engine.st["drop_send"] = 0
        app._drain_engine_warning()
        assert app.engine_warning.kw.get("text") == ""
    """)


def test_the_statistics_copy_menu_is_dark_like_every_other_context_menu():
    """It came up WHITE in the middle of a dark program - reported from a running
    build, 2026-08-19.

    ttk styles do not reach a classic ``tk.Menu``: on Windows it is a native Win32
    popup, so it keeps the system colours unless something configures it. The
    connection table wraps its menu in ``theme.style_menu``; this one was built
    bare. Nothing could go red over it, because the fake tkinter records colours
    and never renders them - which is why the rule guard in
    ``test_repo_conventions.py`` was added beside this test rather than instead
    of it: this one proves THIS menu is dark, that one proves the next menu
    somebody adds cannot repeat the mistake.
    """
    run_gui("""
        from beantester.gui.theme import ACC, BG2, FG
        page = app.pages["statistics"]
        menu = page._copy_menu()
        assert menu.cget("background") == BG2, menu.kw
        assert menu.cget("foreground") == FG, menu.kw
        assert menu.cget("activebackground") == ACC, menu.kw
        # the cached menu is the SAME object on the second call, so a second
        # right-click cannot get an unstyled one
        assert page._copy_menu() is menu
    """)


def test_an_entry_a_row_cannot_use_is_coloured_inert_not_disabled():
    """Entries a row cannot use read BLURRED on Windows - seen on a running build,
    2026-09-24, in the Sockets and Port check menus.

    Tk draws a disabled menu label first in the system's white 3-D highlight, one
    pixel down and right, and no option turns that off. So the entry stays
    "normal" and only its colours say it is inert - and going back to usable has
    to hand EVERY one of those colours back to the menu, or an entry greyed out
    once stays grey on the next row that can use it. What this cannot see is the
    drawing itself (the fake tkinter never renders); that was checked with a probe
    on real Tk 9.0 and 8.6.
    """
    run_gui("""
        from beantester.gui.theme import (DIS_FG, MENU_ENTRY_INERT,
                                          set_menu_entry_available)
        menu = app.pages["connections"].menu
        set_menu_entry_available(menu, 4, False)
        inert = menu.entry_states[4]
        assert "state" not in inert, inert
        assert inert["foreground"] == DIS_FG, inert
        assert inert["activeforeground"] == DIS_FG, inert
        set_menu_entry_available(menu, 4, True)
        live = menu.entry_states[4]
        assert live == dict.fromkeys(MENU_ENTRY_INERT, ""), live
    """)
