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


def test_the_profile_picker_fits_its_longest_name():
    """BUG: the picker was a hardcoded 24 characters wide.

    ttk sizes a combobox popdown from the widget and never from its contents, so
    the list truncated in silence - "Zapchane lacze domowe (bufferbloat)" (35
    characters) showed up as "Zapchane lacze domowe (bufferb", in both
    languages, with nothing on screen saying the name went on. Presets get added
    and renamed; a width typed by hand goes stale the first time one of them
    grows.
    """
    run_gui("""
        names = app.profile_names()
        longest = max(len(n) for n in names)
        assert app.profile_cb.kw["width"] >= longest, (
            app.profile_cb.kw["width"], max(names, key=len))
    """)


def test_the_profile_picker_regrows_when_a_long_profile_is_saved():
    """A picker that fits at build time can stop fitting a keystroke later:
    saving a profile is exactly how a long name enters this list."""
    run_gui("""
        from beantester.gui.theme import POPDOWN_MAX_CHARS
        before = app.profile_cb.kw["width"]
        # longer than the longest PRESET, or nothing moves - the picker is
        # already as wide as its widest built-in name
        name = "Backup link at the warehouse, evening"
        assert len(name) > max(len(n) for n in app.profile_names())
        app.profiles.set(name, {})
        app._sync_profile_widgets()
        after = app.profile_cb.kw["width"]
        assert after > before, (before, after)
        assert after >= len(name), (after, name)

        # ...but a name nobody should be able to shove the row apart with is capped
        app.profiles.set("x" * 300, {})
        app._sync_profile_widgets()
        assert app.profile_cb.kw["width"] == POPDOWN_MAX_CHARS, app.profile_cb.kw["width"]
    """)


def test_the_live_stats_tab_is_scrolled_so_the_chart_cannot_vanish():
    """BUG: the throughput chart was squeezed to a ten-pixel sliver.

    The counter grid reflows its columns with the window WIDTH, so a narrow
    window turns it into five tall rows. It packs at its natural height, and the
    chart - packed ``expand=True`` - got the leftover, which was almost nothing.
    A canvas asking for 180 px is still shrunk below it when pack has nothing
    left to hand out, so the request alone was never a floor.
    """
    run_gui("""
        stats = app.pages["statistics"]
        assert getattr(stats, "scroll", None) is not None, "the Live tab is not scrolled"
        assert stats.canvas.kw.get("height", 0) > 0, stats.canvas.kw
    """)


def test_a_panel_window_reserves_its_footer_before_its_content():
    """BUG: "Close" was sliced in half by the bottom edge of the Settings window.

    pack hands out height in call order, so a footer packed LAST gets whatever
    the content above left over - and the Settings content grew past its 520 px
    until that was nothing. Packing the footer first reserves it, and the
    content is what runs out of room instead. About had the same shape and was
    one longer translation away from the same bug.
    """
    run_gui("""
        for window_id in ("settings", "about"):
            app.windows.open(window_id)
            panel = app.windows._open[window_id]
            packed = panel.body.pack_slaves()
            bottom = [i for i, w in enumerate(packed)
                      if (w.pack_info or {}).get("side") == "bottom"]
            assert bottom, f"{window_id}: no bottom-packed footer"
            assert bottom[0] == 0, (
                f"{window_id}: the footer is packed at position {bottom[0]} of "
                f"{len(packed)}, so the content above it claims the height first")
            app.windows.close(window_id)
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


def test_a_tooltip_never_covers_empty_space():
    """A tooltip belongs to the WIDGET, so a label stretched across its row shows
    its bubble over the blank space beside the sentence too. The summary strip did
    exactly that: measured on real Tk, the label was 508 px wider and 17 px taller
    than its own text, so hovering the empty header fired "what the tool is doing
    with your traffic" nowhere near the line it explains.

    Exempt: buttons, entries and comboboxes (there the whole box IS the control,
    so covering all of it is right) and containers - a group box or a stat tile
    with a tooltip is meant to answer for everything inside it.
    """
    run_gui("""
        def stretched(widget, found=None):
            found = [] if found is None else found
            for child in widget.winfo_children():
                info = child.pack_info or {}
                text = child.kw.get("text")
                is_leaf_label = (bool(text) and not child.kw.get("command")
                                 and not child.winfo_children())
                if (hasattr(child, "_bnt_tooltip") and is_leaf_label
                        and (info.get("fill") in ("x", "both") or info.get("expand"))):
                    found.append((text, info))
                stretched(child, found)
            return found

        for page in ("control", "statistics", "connections"):
            app.select_page(page)
        bad = stretched(root)
        assert not bad, bad
    """)


# -- the Control-page search -------------------------------------------------- #


def test_searching_marks_what_matched_and_counts_it():
    """The whole promise in one run: type, see the match bolded, see how many."""
    run_gui("""
        page = app.pages["control"]
        page.query_var.set("loss")
        page._apply()

        label = app.form.labels["loss"]
        assert label.cget("style") == "Hit.TLabel", label.cget("style")
        assert page._verdict.cget("text").startswith("1 / "), page._verdict.cget("text")

        # ...and the field next to it, which did not match, is untouched
        other = app.form.labels["latency"]
        assert other.cget("style") == "Card.TLabel", other.cget("style")
    """)


def test_clearing_the_search_puts_every_style_back():
    """A mark left behind after the box is empty is a page that looks broken."""
    run_gui("""
        page = app.pages["control"]
        before = app.form.labels["loss"].cget("style")
        page.query_var.set("loss")
        page._apply()
        assert app.form.labels["loss"].cget("style") == "Hit.TLabel"

        page.clear()
        assert app.form.labels["loss"].cget("style") == before, (
            app.form.labels["loss"].cget("style"))
        assert page._verdict.cget("text") == "", page._verdict.cget("text")
    """)


def test_a_hit_in_a_folded_section_is_opened_but_never_remembered():
    """🔴 The regression this feature could most easily cause.

    Fold state is persisted (`App.on_sections_changed` -> `ui.json`), so opening a
    section through the accordion's own toggle would make a search permanently
    unfold what the user had chosen to keep closed. The search must open it for
    the length of the search and put it back.
    """
    run_gui("""
        page = app.pages["control"]
        panel = app.form.sections["advanced"]
        panel.set_open(False)
        app.on_sections_changed(["advanced"])
        assert app.collapsed_sections == ["advanced"]
        written = app.ui.get("collapsed")

        page.query_var.set("--syn-drop")          # a field inside that section
        page._apply()
        assert panel.is_open, "the section holding the hit must be opened"
        assert app.collapsed_sections == ["advanced"], (
            "opening it for a search must not change the remembered state: "
            + str(app.collapsed_sections))
        assert app.ui.get("collapsed") == written, "nothing may be written to ui.json"

        page.clear()
        assert not panel.is_open, "clearing the search must fold it back"
    """)


def test_a_field_that_lives_in_the_settings_window_says_so():
    """Decision of 2026-08-18: a hit this page cannot jump to still answers."""
    run_gui("""
        from beantester.i18n import T
        page = app.pages["control"]
        page.query_var.set("row_limit")           # renders in the Settings window
        page._apply()
        text = page._verdict.cget("text")
        assert text and "/" not in text, "there is nothing on this page to walk: " + text
        assert text == T("fields.search_elsewhere", name=T("fields.row_limit").rstrip(":")), text
        assert not page._marked, "nothing on this page may be marked"
    """)


def test_a_query_that_matches_nothing_says_so_instead_of_going_quiet():
    run_gui("""
        from beantester.i18n import T
        page = app.pages["control"]
        page.query_var.set("zzzznothing")
        page._apply()
        assert page._verdict.cget("text") == T("fields.search_none"), page._verdict.cget("text")
    """)


def test_the_search_survives_the_form_rebuilding_itself():
    """Crossing the two-column threshold destroys every widget in the form. The
    marks pointed at those widgets, so without the rebuild hook the page would
    come back with a query in the box and nothing marked."""
    run_gui("""
        page = app.pages["control"]
        page.query_var.set("loss")
        page._apply()
        assert app.form.labels["loss"].cget("style") == "Hit.TLabel"

        app.form.set_columns(2)                   # rebuilds the whole form
        assert app.form.columns == 2
        assert app.form.labels["loss"].cget("style") == "Hit.TLabel", (
            "the mark did not come back after the rebuild")
    """)


def test_only_the_control_page_has_a_search_box():
    """The Settings window renders the SAME ControlForm; the search belongs to the
    page, not to the form, or it would appear in both."""
    run_gui("""
        from beantester.gui.form import ControlForm
        assert hasattr(app.pages["control"], "query_var")
        assert not hasattr(ControlForm, "query_var")

        app.windows.open("settings")
        panel = app.windows._open.get("settings")
        assert panel is not None
        assert not hasattr(panel, "query_var"), "the Settings window grew a search box"
        # its form is a ControlForm all the same - that is the point of the check
        assert isinstance(getattr(panel, "form", None), ControlForm)
    """)


def test_one_ctrl_f_reaches_whichever_search_box_is_in_front():
    """🔴 Two boxes, one shortcut - and a root binding without `add` REPLACES the
    one before it, so the page built second would have silently taken Ctrl+F away
    from the other. From a page with no box the shortcut keeps its older
    behaviour: bring the connection table forward and type there."""
    run_gui("""
        from beantester.gui.pages import focus_search
        control, conns = app.pages["control"], app.pages["connections"]

        app.select_page("control")
        focus_search(app)
        assert app.current_page() is control, "Ctrl+F left the Control page"
        assert root.focus_get() is control._entry, "the caret missed the field search"

        app.select_page("connections")
        focus_search(app)
        assert root.focus_get() is conns._search_entry, "the caret missed the table search"

        app.select_page("statistics")
        focus_search(app)
        assert app.current_page() is conns, "from a page with no box it must fall back"
        assert root.focus_get() is conns._search_entry
    """)
