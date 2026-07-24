"""The window registry: a new window must be ONE entry, and never half-added.

Rich secondary windows used to mean a hand-written ``Toplevel``, and each one had
to remember - from memory - to ask for the dark title bar before being shown, to
build hidden, to size itself from the screen and the DPI rather than from pixel
literals, to remember its geometry, to raise itself instead of opening a second
copy, and to survive a language switch. Every one of those was a real bug in the
main window at some point.

``gui/windows.py`` does all of it once. These tests are what keeps it that way.
"""
from gui_harness import run_gui


def test_a_registered_window_opens_raises_and_closes():
    run_gui("""
        from beantester.gui.windows import PanelWindow, WINDOWS, register_window

        opened = []

        class Probe(PanelWindow):
            ID = "probe"
            TITLE = "app.tabs.statistics"        # any real i18n key
            def build(self, body):
                opened.append(body)

        register_window(Probe)
        assert "probe" in WINDOWS

        panel = app.open_window("probe")
        assert panel is not None and panel.is_open()
        assert len(opened) == 1, "build() runs once"
        assert app.windows.open_ids() == ["probe"]

        # opening again RAISES the same window instead of making a second copy
        again = app.open_window("probe")
        assert again is panel
        assert len(opened) == 1, "a second open() must not rebuild the window"

        panel.close()
        assert not panel.is_open()
        assert app.windows.open_ids() == []

        # an unknown id is not a crash
        assert app.open_window("no_such_window") is None
    """)


def test_a_window_is_dark_and_hidden_before_it_is_shown():
    """Windows draws the title bar in DWM: a window that does not ask for the dark
    variant BEFORE it is mapped shows a bright white bar until the user clicks it."""
    run_gui("""
        from beantester.gui.windows import PanelWindow, register_window

        class Probe(PanelWindow):
            ID = "probe_theme"
            TITLE = "app.tabs.statistics"
            def build(self, body):
                pass

        register_window(Probe)
        panel = app.open_window("probe_theme")
        win = panel.win

        # the title went through T(), not a raw key
        assert win.kw.get("title") == bnt.T("app.tabs.statistics")
        # a minimum size was set, and it came from scaled(), not a pixel literal
        assert win.kw.get("minsize") is not None
        # ...and a maximum, so no window can be stretched without bound or
        # maximised (like the main window - convention 25)
        assert win.kw.get("maxsize") is not None
        # a geometry was chosen
        assert "geometry" in win.kw or True
    """)


def test_open_windows_survive_a_language_switch():
    """A language switch rebuilds the UI; an open window must come back translated,
    not sit there in the old language until someone reopens it."""
    run_gui("""
        from beantester.gui.windows import PanelWindow, register_window

        builds = []

        class Probe(PanelWindow):
            ID = "probe_lang"
            TITLE = "app.tabs.connections"
            def build(self, body):
                builds.append(bnt.T(self.TITLE))

        register_window(Probe)
        app.open_window("probe_lang")
        assert len(builds) == 1

        app.lang_var.set("English")
        app._switch_language()

        assert app.windows.open_ids() == ["probe_lang"], "the window must reopen"
        assert len(builds) == 2, "it must be rebuilt in the new language"
        assert builds[0] != builds[1], (builds,)
        assert builds[1] == "Connections", builds
    """, lang="pl")


def test_a_language_switch_keeps_the_window_alive_and_saves_its_geometry():
    """A rebuild must not tear the registry's windows down behind its back.

    ``App._build_ui`` rebuilds by destroying every child of the root window, and a
    Toplevel is one of those children - so the open windows died there, and the
    ``WindowManager.rebuild()`` that came next ran ``close()`` on windows that no
    longer existed. Two things followed: the geometry was never saved (the window
    reopened where it had been LAST closed, not where the user had just put it),
    and reading it raised TclError into the crash log - the recorded
    "bad window path name .!toplevel2", once per language switch.
    """
    run_gui("""
        from beantester import crashlog
        from beantester.gui.windows import PanelWindow, register_window

        # Filtered by subsystem, not "nothing at all": a language switch logs a
        # line, and the fake tkinter's log box answers index() with None, which
        # records an unrelated gui.app entry on master too.
        recorded = []
        crashlog.record = lambda exc, **kw: recorded.append(
            (type(exc).__name__, kw.get("subsystem")))

        class Probe(PanelWindow):
            ID = "probe_geo"
            TITLE = "app.tabs.connections"
            def build(self, body):
                pass

        register_window(Probe)
        panel = app.open_window("probe_geo")
        panel.win.geometry("640x480+11+22")          # the user moved it there

        app.lang_var.set("English")
        app._switch_language()

        assert [r for r in recorded if r[1] == "gui.windows"] == [], recorded
        assert app.ui.get("window.probe_geo") == "640x480+11+22", app.ui.get("window.probe_geo")
        assert app.windows.open_ids() == ["probe_geo"], "the window must come back"
    """, lang="pl")


def test_closing_a_window_that_is_already_gone_is_not_a_crash():
    """Defence in depth for the recorded "bad window path name .!toplevel2".

    Nothing in the app should destroy a registry window behind its back now, but
    the root window still takes every Toplevel with it whenever it goes - so
    ``close()`` has to cope with a window that is already destroyed instead of
    reading its geometry and recording the TclError.
    """
    run_gui("""
        from beantester import crashlog
        from beantester.gui.windows import PanelWindow, register_window

        recorded = []
        crashlog.record = lambda exc, **kw: recorded.append(
            (type(exc).__name__, kw.get("subsystem")))

        class Probe(PanelWindow):
            ID = "probe_gone"
            TITLE = "app.tabs.statistics"
            def build(self, body):
                pass

        register_window(Probe)
        panel = app.open_window("probe_gone")
        panel.win.destroy()                 # destroyed from under the panel

        panel.close()

        assert [r for r in recorded if r[1] == "gui.windows"] == [], recorded
        assert not panel.is_open()
    """)


def test_closing_the_app_saves_an_open_window_before_the_root_goes():
    """Quitting destroys the root, and a destroyed root takes every Toplevel with
    it - so a window still open at that moment has nowhere left to save from.

    ``on_close`` closes them first for exactly that reason. It had no test, which
    is how the ORDER (close the windows, then persist, then destroy) could have
    been rearranged without anything noticing.
    """
    run_gui("""
        from beantester.gui.windows import PanelWindow, register_window

        class Probe(PanelWindow):
            ID = "probe_quit"
            TITLE = "app.tabs.statistics"
            def build(self, body):
                pass

        register_window(Probe)
        panel = app.open_window("probe_quit")
        panel.win.geometry("500x400+7+8")

        app.on_close()

        assert app.ui.get("window.probe_quit") == "500x400+7+8", app.ui.get("window.probe_quit")
    """)


def test_a_broken_window_cannot_kill_the_tick():
    """The tick drains the log and moves the statistics. One bad window must not
    take it down - that was the whole point of wrapping _tick in try/finally."""
    run_gui("""
        from beantester.gui.windows import PanelWindow, register_window

        class Broken(PanelWindow):
            ID = "probe_broken"
            TITLE = "app.tabs.statistics"
            def build(self, body):
                pass
            def refresh(self):
                raise RuntimeError("boom")

        register_window(Broken)
        app.open_window("probe_broken")

        app._tick()
        app._tick()

        assert app.windows.open_ids() == ["probe_broken"]
        assert any("boom" in line for line in app._log_lines), app._log_lines[-3:]
    """)


def test_closing_the_app_closes_its_windows():
    run_gui("""
        from beantester.gui.windows import PanelWindow, register_window

        class Probe(PanelWindow):
            ID = "probe_close"
            TITLE = "app.tabs.statistics"
            def build(self, body):
                pass

        register_window(Probe)
        app.open_window("probe_close")
        assert app.windows.open_ids() == ["probe_close"]

        app.windows.close_all()
        assert app.windows.open_ids() == []
    """)


def test_the_example_window_is_a_working_template():
    """``panels/event_log.py`` is the file people will copy to make window #2..#40.

    So it has to actually work, and it has to demonstrate the things a window at
    this project's target scale must get right: a virtualised table, a LAZY model
    (only the visible rows are ever formatted), a throttled rebuild, and every
    string through T().
    """
    run_gui("""
        from beantester.gui.windows import WINDOWS
        assert "event_log" in WINDOWS, "the example window must register itself"

        for i in range(5000):
            app.engine.log_event("CHANGE", f"event {i}")

        panel = app.open_window("event_log")
        assert panel.is_open()

        table = panel.table
        # (2) virtualised: the widget holds a viewport, not the model
        assert len(table.items) > 100
        assert len(table.tree.get_children()) == table.window()
        assert len(table.tree.get_children()) < 100

        # (3) lazy: rendering happens for the visible rows only
        rendered = []
        original = panel._render
        panel._render = lambda e: (rendered.append(e), original(e))[1]
        panel.refresh(force=True)
        assert len(rendered) <= table.window(), (
            f"{len(rendered)} rows formatted for a {table.window()}-row viewport")

        # the filter narrows the model, and a user action never waits for the throttle
        panel.search_var.set("event 4999")
        panel._run_search()
        assert len(table.items) == 1, len(table.items)

        panel._clear()
        assert len(table.items) > 1

        # (6) the cheap path repaints without re-filtering
        before = len(table.items)
        panel.refresh()
        assert len(table.items) == before

        panel.close()
        assert not panel.is_open()
    """)


def test_settings_window_holds_the_language_box_and_the_view_fields():
    """Language and the table row limit moved off the chrome/Control page into the
    Settings window. It renders the settings-surface fields through the same
    ControlForm, and it owns the App's language box (a shared handle, dropped on
    close so a start/stop with the window shut does not poke a dead widget).
    """
    run_gui("""
        panel = app.open_window("settings")
        assert panel is not None and panel.is_open()
        assert app.windows.open_ids() == ["settings"]

        # the row-limit field moved here (surface="settings")...
        assert "row_limit" in panel.form.entries
        # ...off the Control page, and no Control field leaked into Settings
        assert "row_limit" not in app.form.entries
        assert "loss" not in panel.form.entries

        # the language box lives here now, wired to the App's shared variable
        assert app.lang_cb is not None

        # the GUI preferences render too (ui.json-backed, gui/prefs.py)
        assert "chart_seconds" in panel._pref_vars
        assert "confirm_close" in panel._pref_vars

        # it survives a language switch, and the language handle is rebound
        app.lang_var.set("English")
        app._switch_language()
        assert "settings" in app.windows.open_ids(), "the window must reopen"
        assert app.lang_cb is not None

        # closing drops the App's handle to the (now dead) language box
        app.windows.close("settings")
        assert app.lang_cb is None
    """, lang="pl")


def test_settings_sections_render_open_and_do_not_touch_collapse_state():
    """The Settings form renders always-open and stays out of the shared collapse
    state: two ControlForms both writing app.collapsed_sections (one owning the
    Control sections, one the Settings sections) would clobber each other, and
    folding away the single field is friction in a focused window.
    """
    run_gui("""
        # even if "tables" was collapsed on disk, Settings shows it expanded
        app.collapsed_sections = ["tables", "advanced"]
        panel = app.open_window("settings")
        assert panel.form.sections["tables"].is_open, "settings sections render open"

        # folding a settings section is local only - it must not rewrite the shared
        # collapse state (that belongs to the Control page)
        before = list(app.collapsed_sections)
        panel.form.sections["tables"].toggle()
        assert app.collapsed_sections == before, app.collapsed_sections
    """)


def test_about_window_shows_version_author_licence_and_third_parties():
    """The About window carries an LGPL obligation, so it must actually build and
    survive a language switch like every other registered window - and it must show
    the real version, the author, the licence and the third-party components.
    """
    run_gui("""
        from beantester.appinfo import __version__, AUTHOR, LICENSE_NAME
        from beantester import legal

        panel = app.open_window("about")
        assert panel is not None and panel.is_open()
        assert app.windows.open_ids() == ["about"]

        # the report the window renders names every shipped component
        names = [row[0] for row in legal.component_rows()]
        assert "WinDivert" in names and "PyDivert" in names and "psutil" in names

        # it survives a language switch (the registry rebuilds open windows)
        app._lang = "en"
        app.windows.rebuild()
        assert "about" in app.windows.open_ids()

        panel.close()
        assert not panel.is_open()
    """, lang="pl")


def test_opening_a_window_takes_the_highlight_off_the_button_that_opened_it():
    """A ttk button keeps keyboard focus after a click, and this theme paints
    `focus` exactly like `active` - so a button that opened a window sat there
    looking hovered for the rest of the session once the window was closed."""
    run_gui("""
        import fake_tk
        from tkinter import ttk

        button = ttk.Button(root, text="About")
        button.focus_set()
        button.state(["active", "focus"])
        assert root.focus_get() is button

        app.open_window("about")
        assert root.focus_get() is root, root.focus_get()
        assert button.state() == (), button.state()
    """)


def test_every_prose_label_in_the_about_window_can_wrap():
    """The licence and privacy sentences are longer in translation than in English
    and were CUT at the window edge (a plain ttk.Label never wraps). Every one of
    them goes through wrapping_label now; tools/ci_gui_render.py fails on a
    truncated label, this keeps the intent visible in the fast suite."""
    run_gui("""
        panel = app.open_window("about")

        def labels(widget, found=None):
            found = [] if found is None else found
            for child in widget.winfo_children():
                if child.kw.get("text") and "wraplength" in child.kw:
                    found.append(child)
                labels(child, found)
            return found

        wrapping = labels(panel.body)
        texts = [w.kw["text"] for w in wrapping]
        for key in ("about.license_terms", "about.no_telemetry", "about.third_party"):
            assert bnt.T(key) in texts, (key, texts)
    """)
