"""GUI state that must survive a rebuild, and the no-auto-apply rule.

The language switch destroys and rebuilds every widget. It used to rebuild them
from scratch: a running session came back showing "START" / "Stopped" with the
traffic filter unlocked, and a loaded scenario silently disappeared from the UI
while still being scheduled. Nothing covered that - hence this file.
"""
from gui_harness import run_gui


def test_language_switch_keeps_running_state():
    run_gui("""
        app.running = True                      # pretend a session is live
        app._sync_running_ui()
        app.lang_var.set("English")
        app._switch_language()

        assert app.running is True
        assert app.btn_start.kw["text"] == bnt.T("buttons.stop"), app.btn_start.kw
        assert app.status.kw["text"] == bnt.T("app.status.running")
        assert app.status.kw["style"] == "Good.TLabel"
        # the title bar carries the RUNNING tag while a capture is live
        assert bnt.T("app.title.running") in app.root.kw["title"], app.root.kw
        # convention 7: the traffic filter is applied at start -> locked while running
        assert app.filter_cb.kw.get("state") == "disabled", app.filter_cb.kw

        app.running = False                     # stop -> title back to bare app name
        app._sync_running_ui()
        assert app.root.kw["title"] == bnt.APP_NAME, app.root.kw
    """)


def test_the_running_icon_lands_on_the_window_not_just_the_default():
    """The recording dot must reach the window the user is looking at.

    ``iconphoto(True, img)`` is Tk's ``-default``: the icon for toplevels created
    from then on. On Windows it lands on the window class, and the main window
    keeps the icon it owns from ``iconbitmap(bean.ico)`` - so the swap showed the
    dot on the next dialog opened and never on the title bar or the taskbar,
    which is exactly how the bug reached a release. Measured with WM_GETICON: the
    window's icon handle did not change at all until the ``False`` call was added.
    """
    run_gui("""
        app.root.kw["icons"] = []               # forget the startup icon calls
        app.running = True
        app._sync_running_ui()
        icons = app.root.kw["icons"]
        assert ("window", app._icon_running) in icons, icons
        assert ("default", app._icon_running) in icons, icons   # future toplevels

        app.root.kw["icons"] = []
        app.running = False
        app._sync_running_ui()
        icons = app.root.kw["icons"]
        assert ("window", app._icon_idle) in icons, icons
    """)


def test_language_switch_keeps_scenario_and_loop():
    run_gui("""
        import json, tempfile, os
        path = os.path.join(tempfile.mkdtemp(), "s.json")
        json.dump({"loop": True, "steps": [{"at": 0, "settings": {"loss": 5}}]},
                  open(path, "w"))
        import tkinter.filedialog as fd
        fd.askopenfilename = lambda *a, **k: path
        app.load_scenario()
        before = app.scenario_lbl.kw["text"]
        assert "s.json" in before

        app.lang_var.set("English")
        app._switch_language()
        assert app._scenario is not None
        assert "s.json" in app.scenario_lbl.kw["text"], app.scenario_lbl.kw
        assert app.loop_var.get() is True
    """)


def test_language_switch_keeps_page_sorting_and_filter():
    run_gui("""
        app.select_page("connections")
        app.conn_sort = {"col": "idle", "reverse": False}
        app.set_filter_cli_key("udp")
        app.lang_var.set("English")
        app._switch_language()

        assert app._page_id == "connections"
        assert app._filter_cli_key() == "udp"        # not reset by the rebuild
        assert app.pages["connections"].table.sort["col"] == "idle"
    """)


def test_preset_and_lan_do_not_auto_apply():
    """Nothing applies itself: the form fills, "Apply changes" pushes."""
    run_gui("""
        app.running = True
        app._applied_sig = app._signature(app._raw_settings())
        assert app._is_dirty() is False

        app.profile_var.set(bnt.T("presets.terrible"))
        app.load_selected_profile()
        assert float(app.loss_var.get()) == 10.0
        assert app._is_dirty() is True               # form differs from the engine
        assert app.engine.core.loss == 0.0           # ...and the engine was NOT touched

        app._applied_sig = app._signature(app._raw_settings())
        app.lan_var.set(True)
        app.on_form_changed()
        assert app._is_dirty() is True
        assert app.engine.core.lan_only is False     # LAN goes through Apply too
    """)


def test_apply_clears_the_dirty_flag():
    run_gui("""
        app.running = True
        app._applied_sig = app._signature(app._raw_settings())
        app.loss_var.set("7")
        app.on_form_changed()
        assert app._is_dirty() is True
        app.apply_if_running(announce=True)
        assert app._is_dirty() is False
        assert abs(app.engine.core.loss - 0.07) < 1e-9
    """)


def test_summary_prefix_tells_the_truth_about_the_session():
    """The strip used to say "Active:" even while the app was stopped."""
    run_gui("""
        app.loss_var.set("5")          # the form starts perfect: give it something to say
        app.on_form_changed()
        app._refresh_summary()
        assert app._summary_text.startswith(bnt.T("summary.prefix_preview")), app._summary_text

        app.running = True
        app._applied_sig = app._signature(app._raw_settings())
        app._form_changed = True
        app._refresh_summary()
        assert app._summary_text.startswith(bnt.T("summary.prefix")), app._summary_text

        app.loss_var.set("42")
        app.on_form_changed()
        app._refresh_summary()
        assert app._summary_text.startswith(bnt.T("summary.prefix_pending")), app._summary_text
    """)


def test_connection_row_feeds_the_targeting_fields():
    run_gui("""
        app.set_target_expression("chrome.exe")
        assert app.target_var.get() == "chrome.exe"
        s = app._settings_from_widgets()
        assert s["target"] == "chrome.exe"

        app.set_destination("10.0.0.7", "443")
        s = app._settings_from_widgets()
        assert s["dst_ip"] == "10.0.0.7" and s["dst_port"] == "443"
    """)


def test_no_section_carries_an_enable_checkbox():
    """The three "Enable" boxes are gone.

    They were switches that did nothing: an empty target / destination and a zero
    flap period already mean "no restriction", so the checkbox only ever cost a
    click (and could be left unticked over a filled-in field, which read as a bug).
    """
    run_gui("""
        assert app.toggles == {}, app.toggles
        assert [s.id for s in bnt.SECTIONS if s.toggle] == []

        # an untouched form restricts nothing
        s = app._settings_from_widgets()
        assert s["target"] == "" and s["dst_ip"] == "" and s["flap_period"] == 0

        # ...and a typed value reaches the engine with no box to tick first
        app.target_var.set("chrome.exe")
        assert app._settings_from_widgets()["target"] == "chrome.exe"
        assert app.form.entries["target"].kw.get("state") != "disabled"
    """)


def test_importing_a_config_overwrites_every_field():
    """A loaded config describes the traffic completely: a field the file does not
    mention goes back to its default instead of keeping whatever was there."""
    run_gui("""
        app.dst_ip_var.set("1.2.3.4")

        app._settings_to_widgets(dict(bnt.DEFAULT_SETTINGS, loss=5))
        assert app.dst_ip_var.get() == ""
        assert app._settings_from_widgets()["dst_ip"] == ""

        app._settings_to_widgets(dict(bnt.DEFAULT_SETTINGS, dst_ip="5.6.7.8"))
        assert app.dst_ip_var.get() == "5.6.7.8"
        assert app._settings_from_widgets()["dst_ip"] == "5.6.7.8"
    """)


def test_connection_menu_needs_a_row_to_act_on():
    """The context menu popped up on an empty table, offering "Copy row" with no row."""
    run_gui("""
        page = app.pages["connections"]
        tree = page.table.tree

        class Ev:
            x_root = y_root = 10
            y = 10

        tree.row_at = None                      # empty table / clicked below the rows
        assert page._popup(Ev()) == "break"
        assert page.menu.posted == 0, "menu shown with nothing to act on"

        # a real row. The table is virtualised, so identify_row() gives back a
        # VIEWPORT SLOT id (__v0, __v1, ...), which the table maps to the model key -
        # the widget ids are recycled and say nothing about which row was clicked.
        page.table.sync([("r1", ("chrome.exe", "TCP", "1.2.3.4", "443",
                                 "5000", "10", "1.0", "2.0", "0.1"))])
        tree.row_at = page.table._slots[0]
        page._popup(Ev())
        assert page.table.selected_keys() == ["r1"]
        assert page.menu.posted == 1
        assert page.menu.entry_states[page.TARGET_INDEX]["state"] == "normal"

        # a row whose process could not be resolved cannot be targeted
        page.table.sync([("r2", ("?", "TCP", "1.2.3.4", "443",
                                 "5000", "10", "1.0", "2.0", "0.1"))])
        tree.row_at = page.table._slots[0]
        page._popup(Ev())
        assert page.menu.entry_states[page.TARGET_INDEX]["state"] == "disabled"

        # clicking a slot BELOW the last row acts on nothing
        tree.row_at = page.table._slots[-1]
        page.menu.posted = 0
        assert page._popup(Ev()) == "break"
        assert page.menu.posted == 0, "menu shown for an empty viewport slot"
    """)


def test_dialogs_are_in_app_and_translated():
    """Native message boxes are white AND take their buttons from the OS - an
    English UI still asked "Tak / Nie" on a Polish Windows."""
    run_gui("""
        import beantester.gui.app as appmod
        import beantester.gui.dialogs as dialogs

        src = open(appmod.__file__, encoding="utf-8").read()
        assert "messagebox." not in src and "simpledialog." not in src, src[:0]
        # file pickers stay native on purpose
        assert "filedialog." in src

        for key in ("buttons.ok", "buttons.cancel", "buttons.yes", "buttons.no"):
            for lang in ("en", "pl"):
                assert bnt.translate(key, lang) != key, (key, lang)

        calls = []
        dialogs.ask_yes_no = lambda parent, title, msg: calls.append(title) or False
        app.running = True
        app.on_close()                       # user answers "No" -> nothing happens
        assert calls and app.running is True
    """)


def test_target_verdict_is_recorded_not_rendered_off_the_main_thread():
    """``_refresh_target`` must leave its verdict in a field, never draw it itself.

    ``_refresh_target`` used to call ``set_target_warning`` directly, so
    ``.config()`` / ``.winfo_ismapped()`` / ``.pack()`` ran on a worker thread.
    On Windows that either hangs Tk - and a hung GUI keeps the WinDivert handle
    open, which is the one thing FAIL-OPEN exists to prevent - or raises
    ``RuntimeError: main thread is not in main loop`` into a bare ``except``,
    silently swallowing the very banner that is supposed to shout.

    The background refresher that made this urgent is gone (resolving moved to
    ``target_resolver``), but the SHAPE is the guard: as long as the verdict goes
    into ``_pending_target_warning`` and only ``_drain_target_warning`` renders it,
    calling this from a thread again can never put a Tcl call on one. The test
    still runs it on a worker thread, which is the hostile case.
    """
    run_gui("""
        import threading

        touched = []
        banner = app.target_warning
        for name in ("config", "configure", "pack", "pack_forget", "winfo_ismapped"):
            original = getattr(banner, name, None)
            if original is None:
                continue

            def spy(*a, _n=name, _o=original, **kw):
                touched.append((_n, threading.current_thread() is threading.main_thread()))
                return _o(*a, **kw)

            setattr(banner, name, spy)

        # an expression that resolves to no process at all: the branch that raises
        # the "your target catches nothing" banner
        app.vars["target"].set("no_such_process_anywhere_xyz")
        app._snapshot_target()

        worker = threading.Thread(target=app._refresh_target, name="target-refresher")
        worker.start()
        worker.join(timeout=30)
        assert not worker.is_alive(), "the refresher thread hung"

        # 1) the worker thread touched NOTHING
        off_main = [t for t in touched if not t[1]]
        assert not off_main, f"Tcl called from a worker thread: {off_main}"

        # 2) but the verdict was recorded, and the main thread renders it
        assert app._pending_target_warning == bnt.T("fields.target_no_match")
        app._drain_target_warning()
        assert touched, "the banner was never applied on the main thread"
        assert all(is_main for _, is_main in touched)
        assert banner.kw.get("text") == bnt.T("fields.target_no_match")

        # 3) a matching target clears it again, and an unchanged verdict is free
        before = len(touched)
        app._drain_target_warning()
        assert len(touched) == before, "an unchanged banner must cost no widget work"
    """)


def test_a_gui_session_keeps_the_target_banner_honest():
    """The tick loop end to end: apply on change, and report what was matched.

    The GUI no longer runs a refresher thread - `_tick` applies a changed target
    expression and the engine's resolver keeps the port set fresh. That rewiring
    was verified against a real session (real engine, real resolver, synthetic
    traffic) and this pins the behaviour it must keep:

      * a target that matches nothing raises the banner - a run in which nothing
        broke looks exactly like a run in which everything held up;
      * a target that DOES match takes it back down;
      * clearing the field drops targeting altogether;
      * none of it stalls the capture.

    The socket table is faked so the test is deterministic and fast. Against the
    real one the first resolve costs about 1.7 s on a normal desktop, which is a
    measurement worth knowing but not worth spending in every suite run.
    """
    run_gui("""
        import time
        from beantester import portmap
        from beantester.synthetic import SyntheticDivert

        class FakeTable:
            def __init__(self):
                self.ports = {5001: 200}
                self.info = {200: ("realapp.exe", 1)}
            def refresh(self, now=None, force=False): return True
            def snapshot(self): return dict(self.ports)
            def name_of(self, pid, allow_bulk=True): return self.info.get(pid, ("", None))[0]
            def ancestors(self, pid, depth=8, allow_bulk=True): return []
            def refresh_if_stale(self, now=None, miss=False): return True
            def process_for_port(self, port, now=None, allow_refresh=True): return ""
            def pid_for(self, port): return self.ports.get(port)

        table = FakeTable()
        portmap.default_table = lambda: table
        # The engine bound portmap.default_table() at construction, BEFORE this
        # monkeypatch, and targeting now resolves against that bound table
        # (engine._ports = the one shared instance), so point it at the fake too -
        # exactly as the resolver and socket-watcher tests inject their table.
        app.engine._ports = table

        real_start = app.engine.start
        app.engine.start = (lambda filt, divert=None, duration=0:
                            real_start(filt, divert=SyntheticDivert(seed=21),
                                       duration=duration))

        def settle(seconds=1.0):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                app._tick()
                time.sleep(0.02)

        app._start(); app._settle_transition()
        assert app.running is True, "the GUI did not start"
        settle(0.3)
        assert app.engine.resolver().is_running(), "no resolver for the session"
        assert app._pending_target_warning == "", repr(app._pending_target_warning)
        seen1 = app.engine.stats_snapshot()["seen"]
        assert seen1 > 0, "no traffic"

        # a target nothing matches: the banner must shout
        app.vars["target"].set("no_such_process_xyz")
        settle(1.0)
        tg = app.engine.targeting()
        assert app._applied_target == "no_such_process_xyz", app._applied_target
        assert tg is not None and tg.refreshes > 0, "the resolver never resolved it"
        assert app._pending_target_warning == bnt.T("fields.target_no_match"), \
            "banner should shout: %r" % app._pending_target_warning
        assert app._shown_target_warning == app._pending_target_warning, "not rendered"

        # a target that DOES own a socket: the banner must come back down
        app.vars["target"].set("realapp")
        settle(1.0)
        tg = app.engine.targeting()
        assert tg.expression == "realapp", tg.expression
        assert tg.matched is True and len(tg.ports()) > 0, sorted(tg.ports())
        assert app._pending_target_warning == "", \
            "a matching target must clear the banner: %r" % app._pending_target_warning
        assert app._shown_target_warning == "", "the banner was not taken down"

        # clearing the field drops targeting entirely
        app.vars["target"].set("")
        settle(0.4)
        assert app.engine.targeting() is None, "clearing must drop targeting"
        assert app._pending_target_warning == "", "no target, no banner"

        assert app.engine.stats_snapshot()["seen"] > seen1, "traffic stalled"

        t0 = time.monotonic()
        app._stop(); app._settle_transition()
        stop_ms = (time.monotonic() - t0) * 1000
        assert app.running is False, "the GUI did not stop"
        assert stop_ms < 900, "STOP took %.0f ms" % stop_ms
        assert not app.engine.resolver().is_running(), "resolver outlived the session"
    """)
