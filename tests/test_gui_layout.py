"""Layout invariants that the old GUI silently violated.

The Statistics tab needed ~1090 px of height inside a 900 px window, so ``pack``
gave the session panel and the event log no space at all: "Mark bug", "Save repro
report", "Copy CLI" and the whole event table were simply unreachable. Nothing
could catch that, because the fake tkinter ignored geometry calls entirely.
"""
from gui_harness import run_gui


def test_window_fits_the_smallest_supported_screen():
    run_gui("""
        spec = root.kw["geometry"]
        size = spec.split("+")[0]
        w, h = (int(x) for x in size.split("x"))
        assert w <= 1366 - 40 and h <= 768 - 90, spec
        min_w, min_h = root.kw["minsize"]
        assert min_w <= w and min_h <= h, (root.kw["minsize"], spec)
    """, screen=(1366, 768))


def test_window_scales_up_on_a_4k_screen():
    run_gui("""
        spec = root.kw["geometry"]
        w, h = (int(x) for x in spec.split("+")[0].split("x"))
        assert w > 1200 and h > 1400, spec          # 200% DPI -> twice the pixels
    """, screen=(3840, 2160), dpi=192.0)


def test_control_page_body_is_scrollable():
    run_gui("""
        page = app.pages["control"]
        assert hasattr(page.scroll, "canvas")
        assert page.form.parent is page.scroll.body
        # a scrollable container must not contain a natively scrolling widget
        import fake_tk
        trees = fake_tk.find(page.scroll.body,
                             lambda w: isinstance(w, fake_tk.Treeview))
        assert not trees, "Treeview inside a ScrollableFrame"
    """)


def test_statistics_is_split_so_nothing_is_cut_off():
    run_gui("""
        page = app.pages["statistics"]
        assert [p for p, _ in page.SUBPAGES] == ["live", "session", "events"]
        # the repro buttons and the event table live on their own sub-pages now
        assert page.sess_labels and page.events is not None
        page.select("session")
        assert page.current() == "session"
        page.select("events")
        assert page.current() == "events"
    """)


def test_summary_strip_has_a_reserved_fixed_height():
    """BUG: a longer summary used to add a line and shove the whole page down."""
    run_gui("""
        assert app.summary_holder.kw.get("height", 0) > 0
        assert app.summary_holder.kw.get("propagate") is False

        app.loss_var.set("1")
        app._form_changed = True
        app._refresh_summary()
        short = app._summary_text
        app.profile_var.set(bnt.T("presets.terrible"))     # long, multi-part summary
        app.load_selected_profile()
        app.mtu_var.set("500"); app.nat_var.set("30"); app.rst_var.set("5")
        app._form_changed = True
        app._refresh_summary()
        assert len(app._summary_text) > len(short)          # text grew...
        assert app.summary_holder.kw.get("height", 0) > 0   # ...container did not
    """)


def test_start_bar_and_log_can_never_be_squeezed_away():
    """A ttk.PanedWindow pushed its sash down whenever a page grew, and the whole
    bottom strip (START / Apply / log) disappeared. It is packed to the bottom now."""
    run_gui("""
        import fake_tk
        assert not hasattr(app, "paned")
        bar = app.btn_start.master
        assert bar.pack_info["side"] == "top"
        bottom = bar.master
        assert bottom.pack_info["side"] == "bottom"      # anchored, not negotiable
        assert bottom.pack_info.get("expand") in (None, False, 0)
        assert app.log_box.master is app.log_wrap and app.log_wrap.master is bottom
        # the notebook only gets what is left over
        assert app.nb.master.pack_info["expand"] is True
    """)


def test_stop_button_and_language_picker_reflect_the_session():
    run_gui("""
        assert app.btn_start.kw["style"] == "Accent.TButton"
        # the language box lives in the Settings window now, not the header
        app.open_window("settings")
        assert app.lang_cb.kw.get("state") == "readonly"

        app.running = True
        app._sync_running_ui()
        assert app.btn_start.kw["style"] == "Stop.TButton"   # STOP is not START
        assert app.lang_cb.kw.get("state") == "disabled"     # no rebuild mid-session
        assert app.filter_cb.kw.get("state") == "disabled"

        app.running = False
        app._sync_running_ui()
        assert app.btn_start.kw["style"] == "Accent.TButton"
        assert app.lang_cb.kw.get("state") == "readonly"
    """)


def test_an_overridden_field_is_visibly_disabled():
    """A throughput schedule REPLACES the constant limits - so they must look dead.

    They used to sit there live and editable while the engine took its rates from
    the schedule steps, i.e. the form advertised a limit nobody was applying. The
    label is greyed by swapping its style: a disabled ttk.Label paints a filled box.
    """
    run_gui("""
        app.vars["rate_schedule"].set("5:500:500")
        app.form.apply_overrides()
        assert app.form.entries["down"].kw.get("state") == "disabled"
        assert app.form.labels["down"].kw.get("style") == "CardOff.TLabel"
        assert app.form.labels["down"].kw.get("state") is None
        assert app.form.notes["speed_limit"].kw.get("text") == bnt.T("fields.schedule_overrides")

        app.vars["rate_schedule"].set("")
        app.form.apply_overrides()
        assert app.form.entries["down"].kw.get("state") == "normal"
        assert app.form.labels["down"].kw.get("style") == "Card.TLabel"
        assert app.form.notes["speed_limit"].kw.get("text") == ""
    """)


def test_window_is_hidden_until_it_is_laid_out():
    """Tk maps a small white window on creation; it must not be seen."""
    run_gui("""
        assert app._withdrawn_first is True
    """)


def test_tick_skips_the_heavy_work_when_minimised():
    run_gui("""
        calls = []
        page = app.pages["control"]
        page.refresh = lambda: calls.append(1)
        app.select_page("control")

        root.state = lambda *a: "iconic"
        app._tick()
        assert not calls, "page refreshed while minimised"
        assert app.last_snapshot is not None      # sampling still happens (history)

        root.state = lambda *a: "normal"
        app._tick()
        assert calls, "page not refreshed after restore"
    """)


def test_every_page_is_registered_and_built():
    run_gui("""
        from beantester.gui.pages import PAGES
        assert [p.id for p in PAGES] == ["control", "statistics", "connections"]
        assert set(app.pages) == {p.id for p in PAGES}
        assert len(app.nb.tabs()) == 3
    """)


def test_fields_with_a_help_sheet_get_the_question_mark_button():
    """Filter-expression fields share the syntax cheat sheet; buffer has its own
    "?" sheet (help_body). The schedule field must NOT grow one."""
    run_gui("""
        assert set(app.form.helps) == {"target", "dst_ip", "dst_port", "block_ip", "block_port", "buffer"}, app.form.helps
        assert "rate_schedule" not in app.form.helps
    """)


def test_no_dead_error_labels_eating_vertical_space():
    """An empty error label still costs a full text line - eleven of them added up."""
    run_gui("""
        # a section with nothing to validate has no error label at all
        assert "traffic" not in app.form.errors
        # and the others keep theirs unmapped until they actually have something to say
        for sid, label in app.form.errors.items():
            assert label.pack_info is None, sid

        app.loss_var.set("999")
        app.form.validate_section("impairments")
        assert app.form.errors["impairments"].pack_info is not None
        assert app.form.errors["impairments"].kw["text"]

        app.loss_var.set("1")
        app.form.validate_section("impairments")
        assert app.form.errors["impairments"].pack_info is None
        assert app.form.errors["impairments"].kw["text"] == ""
    """)


def test_sections_spread_into_two_columns_on_a_wide_page():
    """One column left the right half empty; a grid left holes under the sections
    (grid row heights are shared across columns), so real column frames it is."""
    run_gui("""
        from beantester.gui.form import columns_for
        from beantester.gui.scaling import scaled
        assert columns_for(600, scaled) == 1
        assert columns_for(700, scaled) == 1        # too narrow for a 3-field row
        assert columns_for(1400, scaled) == 2

        form = app.form
        assert form.columns == 1 and len(form.column_frames) == 1

        form.set_columns(2)
        assert len(form.column_frames) == 2
        parents = [p.frame.master for p in form.sections.values()]
        left = parents.count(form.column_frames[0])
        right = parents.count(form.column_frames[1])
        assert left and right and abs(left - right) <= 3, (left, right)
        # every section is packed inside its column frame, never gridded
        assert all(p.frame.pack_info is not None for p in form.sections.values())

        # the rebuild keeps the form state (the vars live on the App)
        app.loss_var.set("7")
        form.set_columns(1)
        assert form.columns == 1
        assert app.loss_var.get() == "7"
        assert app._settings_from_widgets()["loss"] == 7.0
    """)


def test_table_tooltips_belong_to_the_headers_not_the_whole_table():
    """One tooltip on the whole tree popped up over the rows (covering them and
    the STOP button) and said nothing about the column under the pointer."""
    run_gui("""
        import fake_tk
        table = app.pages["connections"].table
        assert set(table.tips) == set(table.columns), table.tips
        for key in table.tips.values():
            for lang in ("en", "pl"):
                assert bnt.translate(key, lang) != key, (key, lang)

        class Ev:
            x = 40
            y = 8
            x_root = 400
            y_root = 300

        # over a data row: no tooltip at all
        table.tree.identify_region = lambda x, y: "cell"
        table._on_motion(Ev())
        assert table._tip_column is None

        # over a header: the tooltip belongs to THAT column
        table.tree.identify_region = lambda x, y: "heading"
        table.tree.identify_column = lambda x: "#3"
        table._on_motion(Ev())
        assert table._tip_column == list(table.columns)[2]

        # leaving the header row drops it again
        table.tree.identify_region = lambda x, y: "cell"
        table._on_motion(Ev())
        assert table._tip_column is None and table._tip_window is None
    """)


def test_expanding_a_section_scrolls_it_into_view():
    """Expanding a section pinned to the bottom edge revealed its content below
    the viewport - you had to scroll by hand to see what you had just opened."""
    run_gui("""
        form = app.form
        scroll = app.pages["control"].scroll
        seen = []
        scroll.ensure_visible = lambda widget, margin=None: seen.append(widget)

        panel = form.sections["profiles"]
        panel.set_open(False)
        form._on_section_toggle(panel)
        assert not seen, "collapsing should not scroll anywhere"

        panel.set_open(True)
        form._on_section_toggle(panel)
        assert seen == [panel.frame], seen
        assert "profiles" not in app.collapsed_sections
    """)
