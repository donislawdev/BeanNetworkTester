"""Layout invariants that the old GUI silently violated.

The Statistics tab needed ~1090 px of height inside a 900 px window, so ``pack``
gave the session panel and the event log no space at all: "Mark bug", "Save repro
report", "Copy CLI" and the whole event table were simply unreachable. Nothing
could catch that, because the fake tkinter ignored geometry calls entirely.
"""
from fakes import check
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


def test_the_main_window_goes_back_to_the_second_monitor_it_was_left_on():
    """Wiring, not arithmetic: `app._restore_geometry` has to ASK about monitors.

    `scaling.geometry_fits` learned to take a monitor lookup, and the way to lose
    that fix quietly is to leave the caller passing nothing - the function keeps
    its old default and the window keeps coming back to the primary monitor. Both
    halves are here: the geometry is restored while that monitor exists, and it is
    dropped once it does not, which is the guard this used to be.
    """
    run_gui("""
        from beantester import winenv

        winenv.monitor_work_area = lambda x, y: (1920, 0, 3000, 1920)
        app.ui.set("geometry", "800x600+2400+100")
        app._restore_geometry()
        assert root.kw["geometry"] == "800x600+2400+100", root.kw["geometry"]

        # ...and with that monitor unplugged the window must NOT be put back there.
        winenv.monitor_work_area = lambda x, y: (0, 0, 1920, 1080)
        app._restore_geometry()
        spec = root.kw["geometry"]
        assert spec != "800x600+2400+100", spec
        assert int(spec.split("+")[1]) < 1920, spec
    """)


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


def test_the_scrollbar_covers_the_page_not_only_what_sits_below_the_search_bar():
    """The scrollbar has to claim the page's cavity BEFORE the search bar does.

    pack hands out space in CALL order, so the slave packed first with
    ``side="right"`` takes the full height and the ``side="top"`` bar after it
    lands to its LEFT. The other way round the bar takes the full width first and
    the scrollbar reaches only from under the bar downwards, which leaves a dead
    strip beside the search row - what the page looked like until 2026-09-03.

    The fake tkinter models pack ORDER but not geometry, so this holds the
    mechanism. MEASURED on real Tk (one 300 px frame, both orders side by side):
    scrollbar first it runs 299 px and the bar comes out 17 px narrower, exactly
    the scrollbar; scrollbar last it runs 269 px and the bar is full width.
    """
    run_gui("""
        page = app.pages["control"]
        packed = page.frame.pack_slaves()
        vsb, bar, canvas = page.scroll.vsb, page._bar, page.scroll.canvas
        for widget in (vsb, bar, canvas):
            assert widget in packed, (widget, packed)
        assert packed.index(vsb) < packed.index(bar), (
            "the search bar took the width before the scrollbar, which then "
            "stops short of this row: %r" % (packed,))
        assert packed.index(bar) < packed.index(canvas), (
            "the search bar landed under the page body: %r" % (packed,))
        assert vsb.pack_info.get("side") == "right", vsb.pack_info
        assert bar.pack_info.get("side") == "top", bar.pack_info
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
    """Filter-expression fields share the syntax cheat sheet, and a field that
    declares ``help_body`` gets its own "?" sheet. The schedule must NOT grow one.

    Derived from the registry rather than listed here: the set used to be six
    names typed out, so adding a field with a help sheet meant editing this line
    as well as the registry - and the one that gets forgotten is always the test.
    The expression half stays explicit because those five share ONE sheet for a
    reason unrelated to any ``help_body``.
    """
    run_gui("""
        from beantester.fields import FIELD_DEFS
        expression_help = {"target", "dst_ip", "dst_port", "block_ip", "block_port"}
        own_sheet = {f.key for f in FIELD_DEFS if f.help_body}
        assert set(app.form.helps) == expression_help | own_sheet, app.form.helps
        assert "rate_schedule" not in app.form.helps
        assert own_sheet, "no field declares a help sheet any more"
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
            for lang in LANGS:
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

        # over a header: the tooltip belongs to THAT column. With everything
        # shown the display position and the registry position agree - which is
        # why this test could not see the hidden-column bug. That case has its
        # own test below (test_a_header_tooltip_still_names_its_own_column...).
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
        assert page._count.cget("text").startswith("1 / "), page._note.cget("text")

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
        # An empty box reports nothing at either end: no position to give, and
        # no other surface to point at.
        assert page._note.cget("text") == ""
        assert page._count.cget("text") == "", page._count.cget("text")
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
        text = page._note.cget("text")
        assert text and "/" not in text, "there is nothing on this page to walk: " + text
        assert text == T("fields.search_elsewhere", name=T("fields.row_limit").rstrip(":")), text
        assert not page._marks, "nothing on this page may be marked"
    """)


def test_a_query_that_matches_nothing_says_so_instead_of_going_quiet():
    run_gui("""
        from beantester.i18n import T
        page = app.pages["control"]
        page.query_var.set("zzzznothing")
        page._apply()
        assert page._note.cget("text") == T("fields.search_none"), page._note.cget("text")
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

        # The Control page's box can be switched OFF in the Settings window, and
        # then it is a page without a box: focusing a widget that is not on
        # screen would swallow the keystrokes that followed the shortcut.
        app.select_page("control")
        app.set_pref("show_control_search", False)
        control.on_pref_changed("show_control_search")
        focus_search(app)
        assert app.current_page() is conns, "a hidden box kept Ctrl+F to itself"
        assert root.focus_get() is conns._search_entry
    """)


def test_the_hit_you_are_on_looks_different_from_the_rest():
    """Reported by the owner: with several matches, Enter moved the page and
    nothing said WHICH one you had arrived at - every match looked the same.

    The current one is filled (`Hit.*`), the others are tinted (`HitDim.*`), and
    the pair moves together with the count.
    """
    run_gui("""
        page = app.pages["control"]
        page.query_var.set("port")             # matches two fields, no section
        page._apply()
        assert len(page._targets) > 1, page._targets

        first = page._marks[0][0]
        second = page._marks[1][0]
        assert first.cget("style") == "Hit.TLabel", first.cget("style")
        assert second.cget("style") == "HitDim.TLabel", second.cget("style")
        assert page._count.cget("text") == "1 / %d" % len(page._targets)

        page._step(1)
        assert first.cget("style") == "HitDim.TLabel", "the old current stayed filled"
        assert second.cget("style") == "Hit.TLabel", "the new current was not filled"
        assert page._count.cget("text") == "2 / %d" % len(page._targets)

        # ...and it wraps rather than stopping at the end
        for _ in range(len(page._targets) - 1):
            page._step(1)
        assert page._count.cget("text") == "1 / %d" % len(page._targets)
        assert first.cget("style") == "Hit.TLabel"
    """)


def test_the_search_highlight_is_not_the_colour_everything_else_uses():
    """Also reported by the owner: the first version painted hits in the page
    accent, which is the colour of every section header, link and "?" button - so
    the highlight vanished into the page it was meant to stand out from.

    The check is that the colours DIFFER, not that any particular one was picked:
    the palette may be retuned, the meaning may not collide again.
    """
    run_gui("""
        from beantester.gui import theme
        assert theme.HIT != theme.ACC, "the highlight is the page accent again"
        assert theme.HIT not in (theme.BG, theme.BG2), "it is the surface colour"
        assert theme.HIT not in (theme.OK, theme.WARN, theme.DONATE_C), (
            "it now means the same as running / faulty / support")
        assert theme.HIT_TEXT != theme.HIT, "the text is the same colour as its fill"
        assert theme.HIT_TEXT in (theme.BG, theme.BG2) or theme.HIT_TEXT < "#404040", (
            "text on the fill has to be the dark end, or it will not read")
    """)


def test_a_match_with_no_text_of_its_own_marks_its_section():
    """The traffic filter is a dropdown and Profiles has no fields at all: both
    were counted and never marked, so the count promised something the page did
    not show."""
    run_gui("""
        page = app.pages["control"]
        page.query_var.set("profil")           # a section with no fields of its own
        page._apply()
        assert page._targets, "the Profiles section must be reachable"
        widget, kind, _old = page._marks[0]
        assert kind == "section", kind
        assert widget is app.form.sections["profiles"].header
        assert widget.cget("style") == "Hit.Section.TButton", widget.cget("style")

        page.clear()
        assert widget.cget("style") == "Section.TButton", widget.cget("style")
    """)


def test_a_section_the_user_opens_during_a_search_is_left_open():
    """The page closes what IT opened, not everything that happened to be closed
    when the search started - otherwise clearing the box folds away a section the
    user deliberately opened while looking at the results."""
    run_gui("""
        page = app.pages["control"]
        advanced, block = app.form.sections["advanced"], app.form.sections["block"]
        advanced.set_open(False)
        block.set_open(False)
        app.on_sections_changed(["advanced", "block"])

        page.query_var.set("--syn-drop")       # lives in "advanced"
        page._apply()
        assert advanced.is_open, "the section holding the hit must open"
        assert not block.is_open

        block.set_open(True)                   # the user opens another one by hand
        page.clear()
        assert not advanced.is_open, "what the search opened must close again"
        assert block.is_open, "what the USER opened must stay open"
    """)


def test_a_query_of_nothing_but_punctuation_is_not_a_search():
    """Edge cases that must not raise or light up the page: a lone flag prefix,
    spaces, and characters that would be a regular expression somewhere else."""
    run_gui("""
        page = app.pages["control"]
        for query in ("--", "   ", "(", "*", ".*", "re:", "]["):
            page.query_var.set(query)
            page._apply()
            if query.strip() in ("--", ""):
                # No POSITION - which is the claim. Nothing matched, so the count
                # is blank whether the box strips to nothing or holds characters
                # that match nothing.
                assert page._count.cget("text") == "", (query, page._count.cget("text"))
                assert not page._marks, query
            # whatever it finds, it must not raise and must not leave the page
            # marked once it is cleared
        page.clear()
        assert not page._marks and page._count.cget("text") == ""
    """)


def test_two_hits_never_fight_over_one_widget():
    """Measured on real Tk: "ruch" matches the traffic SECTION and the dropdown
    inside it, and a dropdown has no text of its own so it marks the same header.
    The header was painted current and then repainted as an ordinary match by the
    later hit, so the count said "1 / 5" with nothing filled anywhere."""
    run_gui("""
        page = app.pages["control"]
        page.query_var.set("ruch")
        page._apply()
        widgets = [m[0] for m in page._marks]
        assert len(widgets) == len(set(id(w) for w in widgets)), "a widget marked twice"
        assert len(page._marks) == len(page._targets), "count and marks disagree"
        filled = [m[0] for m in page._marks if "HitDim" not in str(m[0].cget("style"))]
        assert len(filled) == 1, "exactly one hit is the current one: %d" % len(filled)
        assert filled[0] is page._marks[page._at][0]
    """)


# -- copying the figures off the Statistics page ------------------------------ #


def test_the_session_panel_copies_exactly_what_it_shows():
    """Every value on that panel is a label, so nothing could be selected, let
    alone copied - the machine name and its addresses had to be retyped by hand.

    The text is built from `SESSION_ROWS`, so a row added to the registry is
    copied the day it appears rather than the day somebody remembers.
    """
    run_gui("""
        import fake_tk
        from beantester.gui.pages.stats import SESSION_ROWS
        from beantester.i18n import T

        app.select_page("statistics")
        page = app.pages["statistics"]
        page.select("session")
        page.refresh()

        fake_tk.CLIPBOARD.clear()
        page._copy_visible("session")
        text = "".join(fake_tk.CLIPBOARD)
        lines = text.splitlines()
        assert len(lines) == len(SESSION_ROWS), (len(lines), len(SESSION_ROWS))
        for (key, cap, _tip), line in zip(SESSION_ROWS, lines):
            shown = page.sess_labels[key].cget("text")
            assert line == "%s: %s" % (T(cap), shown), (line, shown)
        assert any(T("session.host") in line for line in lines), lines
    """)


def test_the_counters_tab_copies_its_figures_with_their_units():
    run_gui("""
        import fake_tk
        from beantester.gui.pages.stats import CELLS
        from beantester.i18n import T

        app.select_page("statistics")
        page = app.pages["statistics"]
        page.select("live")

        fake_tk.CLIPBOARD.clear()
        page._copy_visible("live")
        lines = "".join(fake_tk.CLIPBOARD).splitlines()
        assert len(lines) == len(CELLS), (len(lines), len(CELLS))
        # the unit belongs to the caption on this tab, and the copy keeps it
        down = [l for l in lines if l.startswith(T("stats.download"))]
        assert down and "(KB/s)" in down[0], down
    """)


def test_copying_one_value_takes_that_value_and_nothing_else():
    run_gui("""
        import fake_tk
        app.select_page("statistics")
        page = app.pages["statistics"]
        page.select("session")
        page.refresh()

        value = page.sess_labels["private_ipv4"]
        page._clicked = (value, "session")
        fake_tk.CLIPBOARD.clear()
        page._copy_one()
        assert "".join(fake_tk.CLIPBOARD) == value.cget("text"), fake_tk.CLIPBOARD
    """)


def test_a_copy_is_confirmed_only_when_the_clipboard_really_has_it():
    """`App.copy_to_clipboard` logs its own failure, so a success line printed
    blindly beside it would contradict the error the user just read."""
    run_gui("""
        import fake_tk
        from beantester.i18n import T
        app.select_page("statistics")
        page = app.pages["statistics"]
        page.select("session")

        fake_tk.CLIPBOARD.clear()
        page._copy_visible("session")
        assert any(T("log.copied") in line for line in app._log_lines), app._log_lines[-3:]

        # a clipboard that refuses the text says nothing cheerful
        before = len(app._log_lines)
        real_append = type(root).clipboard_append
        type(root).clipboard_append = lambda self, text: None
        try:
            fake_tk.CLIPBOARD.clear()
            page._copy_visible("session")
        finally:
            type(root).clipboard_append = real_append
        assert len(app._log_lines) == before, app._log_lines[before:]
    """, allow_faults=("CLIPBOARD selection doesn't exist",))


def test_the_statistics_page_does_not_steal_ctrl_c_from_the_tables():
    """The same class as the Ctrl+F collision: the connection table and the event
    log own Ctrl+C, on their own widgets. A root binding here would replace
    nothing today and everything tomorrow, so there must not be one."""
    run_gui("""
        app.select_page("statistics")
        assert "<Control-c>" not in root.bindings, sorted(root.bindings)
        assert "<Control-C>" not in root.bindings, sorted(root.bindings)

        conns = app.pages["connections"]
        assert "<Control-c>" in conns.table.tree.bindings, "the table lost its copy"
    """)


def test_a_header_tooltip_still_names_its_own_column_after_others_are_hidden():
    """🔴 Reported from the running program: hide a column and every header to its
    right explained the WRONG one - one case showed the tooltip of a column that
    was not even on screen.

    `identify_column` answers with a DISPLAY position, and the resolution counted
    it against the full column list, so the two agreed only while everything was
    shown. The old tooltip test asserted exactly that agreement and never hid a
    column, which is why the suite was quiet about it.
    """
    run_gui("""
        table = app.pages["connections"].table
        keys = list(table.columns)

        class Ev:
            x = 40
            y = 8
            x_root = 400
            y_root = 300

        table.tree.identify_region = lambda x, y: "heading"

        # hide the SECOND column: everything right of it shifts one place left
        table.set_visible_columns([k for k in keys if k != keys[1]])
        table.tree.identify_column = lambda x: "#2"      # 2nd column ON SCREEN
        table._hide_tip()
        table._on_motion(Ev())
        assert table._tip_column == keys[2], (
            "the tooltip named %r while the pointer was on %r"
            % (table._tip_column, keys[2]))
        assert table._tip_column in table._visible, "it named a hidden column"

        # only two columns left: the last one on screen is the last one asked for
        pair = [keys[0], keys[5]]
        table.set_visible_columns(pair)
        table.tree.identify_column = lambda x: "#2"
        table._hide_tip()
        table._on_motion(Ev())
        assert table._tip_column == keys[5], (table._tip_column, keys[5])

        # and with everything back, the first column is the first column again
        table.set_visible_columns(keys)
        table.tree.identify_column = lambda x: "#1"
        table._hide_tip()
        table._on_motion(Ev())
        assert table._tip_column == keys[0], table._tip_column
    """)


def test_no_tooltip_past_the_last_column():
    """Tk answers with an empty spec in the bare strip right of the headers, and
    the old arithmetic turned that into a ValueError rather than an answer."""
    run_gui("""
        table = app.pages["connections"].table

        class Ev:
            x = 4000
            y = 8
            x_root = 400
            y_root = 300

        table.tree.identify_region = lambda x, y: "heading"
        table.tree.identify_column = lambda x: ""
        table._hide_tip()
        table._on_motion(Ev())
        assert table._tip_column is None and table._tip_window is None
    """)


def test_the_harness_models_pack_order_so_layout_tests_can_ask_about_it():
    """The instrument that checks layout has to model the thing being checked.

    ``pack_slaves`` returned CREATION order while its docstring claimed pack
    order (measured 2026-08-20). Nothing was red: a widget re-packed above an
    existing sibling looked correct here and landed under the whole page on real
    Tk, so every ordering question had to be answered by rendering. The Control
    page re-packs its search bar whenever the preference brings it back, which is
    exactly that shape.

    Four cases, because Tk answers all four: append, ``before=``, ``after=``, and
    re-packing an already-packed widget (which MOVES it).
    """
    import fake_tk
    root = fake_tk.Root()
    a, b, c = (fake_tk.W(root) for _ in range(3))
    order = lambda: root.pack_slaves()

    a.pack(side="top")
    c.pack(side="top")
    check("harness: pack appends in call order", order() == [a, c], f"{order()}")

    b.pack(side="top", before=c)
    check("harness: before= puts it in front of the named sibling",
          order() == [a, b, c], f"{order()}")

    b.pack_forget()
    check("harness: forgetting takes it out of the order", order() == [a, c],
          f"{order()}")

    b.pack(side="top", after=a)
    check("harness: after= puts it behind the named sibling",
          order() == [a, b, c], f"{order()}")

    a.pack(side="top")
    check("harness: re-packing MOVES rather than duplicates",
          order() == [b, c, a], f"{order()}")


def test_the_two_lan_switches_share_one_row():
    """One decision seen from two sides, so they sit side by side.

    Stacked, each of them had a card's width of nothing beside it, and the
    second one read as an afterthought under the first rather than as its
    mirror. A checkbox takes a whole row BY KIND (``gui/form.py::SPAN_KINDS`` -
    a long label clips in half a card), so this only holds while the registry
    overrides that with ``span=False``: one edit in ``fields.py`` puts them back
    in a column with nothing red.

    The dropdown above them must NOT join in: it is a CHOICE, it is the widest
    thing in the card, and it keeps its own row.
    """
    run_gui("""
        lan = app.form.entries["lan_mode"]
        net = app.form.entries["internet_only"]
        assert lan.master is net.master, "the LAN switches are not in one row"
        assert app.form.entries["filter"].master is not lan.master, (
            "the traffic dropdown was pulled into the checkbox row")

        # ...and they must not TOUCH. They shipped with the second one's box hard
        # against the end of the first one's label, because the checkbox branch
        # packed with no padding while every other kind went through a cell that
        # had some. Two controls with nothing between them read as one.
        gap = (lan.pack_info or {}).get("padx")
        gap = gap[1] if isinstance(gap, (tuple, list)) else gap
        assert gap, "no room to the right of the first switch: %r" % (lan.pack_info,)
    """)


def test_turning_asymmetry_on_copies_the_download_values_across():
    """🔴 The design decision this whole card rests on, in the one place a user
    meets it.

    The alternative was "leave the upload box empty to mean the same as
    download". An empty numeric box means ZERO everywhere else in this program,
    so the reading a newcomer would give it is the one that would be wrong - and
    in a reproduction command the inheritance would not be visible at all.

    The switch removes the question instead of answering it: ticking it copies
    each field's mirror across, so the second set of boxes is never blank and
    describes the same link it described a moment ago. Only an edit changes
    anything. The pairs come from ``Field.mirror_of`` rather than from a list
    here, so a value added to the card later cannot be left out of the copy.
    """
    run_gui("""
        from beantester.fields import FIELD_DEFS
        mirrors = [(f.key, f.mirror_of) for f in FIELD_DEFS
                   if f.live_when == "asym" and f.mirror_of]
        assert len(mirrors) == 7, mirrors

        for _up, base in mirrors:                 # distinct values, so a copy shows
            app.vars[base].set("42")
        for up, _base in mirrors:
            app.vars[up].set("")
        assert not app.vars["asym"].get()

        app.vars["asym"].set(True)                # what the checkbox variable does
        app.form._on_switch(__import__("beantester.fields", fromlist=["FIELDS"])
                            .FIELDS["asym"])      # ...and then its command
        for up, base in mirrors:
            assert app.vars[up].get() == app.vars[base].get() == "42", (up, base,
                app.vars[up].get())

        # Turning it back off leaves the work alone: the values are inert either
        # way, and wiping them would punish somebody comparing against a
        # symmetric run.
        app.vars["latency_up"].set("7")
        app.vars["asym"].set(False)
        app.form._on_switch(__import__("beantester.fields", fromlist=["FIELDS"])
                            .FIELDS["asym"])
        assert app.vars["latency_up"].get() == "7", app.vars["latency_up"].get()
    """)


def test_the_upload_fields_look_dead_while_the_switch_is_off():
    """An editable box that changes nothing is a lie about what the tool is
    doing - the rule ``apply_overrides`` already enforced for a field another
    field had taken over. A field waiting on a switch is the same statement seen
    from the other side, so it goes through the same place."""
    run_gui("""
        from beantester.fields import FIELD_DEFS
        upload = [f.key for f in FIELD_DEFS if f.live_when == "asym"]
        assert upload

        app.vars["asym"].set(False)
        app.form.apply_overrides()
        for key in upload:
            assert app.form.is_dormant(key), key
            assert app.form.entries[key].cget("state") == "disabled", key

        app.vars["asym"].set(True)
        app.form.apply_overrides()
        for key in upload:
            assert not app.form.is_dormant(key), key
            assert app.form.entries[key].cget("state") == "normal", key
        # the switch itself is never dormant - nothing gates it
        assert not app.form.is_dormant("asym")
    """)


def test_a_profile_switch_reaches_the_form_as_a_switch_not_as_text():
    """🔴 FOUND by the asymmetry work, and it is a class rather than one field.

    Both loops that fill the form from a preset or profile called
    ``number_string`` on every value. That held for as long as every profile
    field was a number - and ``asym`` is the first that is not. The switch went
    in as the string ``"0"``, which real tkinter coerces back to False by luck,
    and a profile storing it ON would have arrived as ``"1"`` and worked for the
    same wrong reason. The next checkbox to join the profile scope would have
    inherited it in silence.
    """
    run_gui("""
        from beantester.fields import FIELD_DEFS
        from beantester.presets import settings_to_preset
        from beantester.settings import DEFAULT_SETTINGS

        switches = [f.key for f in FIELD_DEFS if f.in_profile and f.kind == "bool"]
        assert switches, "no switch is stored in a profile any more"

        for key in switches:                       # a fresh form: off, as a BOOL
            assert app.vars[key].get() is False, (key, repr(app.vars[key].get()))

        app.profiles.set("asymmetric link",
                         settings_to_preset(dict(DEFAULT_SETTINGS, asym=True,
                                                 latency=200, latency_up=30)))
        app.select_profile("asymmetric link")
        assert app.vars["asym"].get() is True, repr(app.vars["asym"].get())
        assert app.vars["latency_up"].get() == "30", app.vars["latency_up"].get()

        app.select_profile("presets.perfect")      # ...and back off, still a BOOL
        assert app.vars["asym"].get() is False, repr(app.vars["asym"].get())
    """)
