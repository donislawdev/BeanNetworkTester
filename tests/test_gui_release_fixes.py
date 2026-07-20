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
        assert app._profile_key == "presets.perfect"
        assert app.btn_delete_profile.kw.get("state") == "disabled"
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
    """A control with a keyboard shortcut must show it in its own tooltip (conv 40)."""
    run_gui("""
        assert "F5" in app.btn_start._bnt_tooltip.text, app.btn_start._bnt_tooltip.text
        assert "Ctrl+Enter" in app.btn_apply._bnt_tooltip.text, app.btn_apply._bnt_tooltip.text
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

    ``_refresh_target`` runs on the refresher THREAD, so it only records the
    verdict; the banner itself is put on screen by the main thread (``_tick`` ->
    ``_drain_target_warning``). The end result the user sees is unchanged.
    """
    run_gui("""
        app.vars["target"].set("definitely-no-such-process")
        app._snapshot_target()
        app._refresh_target(force=True)
        app._drain_target_warning()          # what _tick() does on the main thread
        assert app.target_warning.kw.get("text") == bnt.T("fields.target_no_match")
        assert app.target_warning.winfo_ismapped()

        app.vars["target"].set("")
        app._snapshot_target()
        app._refresh_target(force=True)
        app._drain_target_warning()
        assert app.target_warning.kw.get("text") == ""
        assert not app.target_warning.winfo_ismapped()
    """)


def test_start_only_fields_are_locked_while_a_session_runs():
    """"Run time" is consumed by BeanEngine.start(), exactly like the traffic
    filter - so, exactly like the filter, it must not look editable mid-session."""
    run_gui("""
        assert app.form.entries["duration"].kw.get("state") in (None, "normal")

        app.running = True
        app._sync_running_ui()
        assert app.form.entries["duration"].kw.get("state") == "disabled"
        assert app.form.labels["duration"].kw.get("style") == "CardOff.TLabel"
        assert app.filter_cb.kw.get("state") == "disabled"

        app.running = False
        app._sync_running_ui()
        assert app.form.entries["duration"].kw.get("state") == "normal"
        assert app.filter_cb.kw.get("state") == "readonly"
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
