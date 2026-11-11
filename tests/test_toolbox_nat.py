"""The Tools tab's NAT and STUN panel (``gui/toolbox/nat.py``) on the fake tkinter.

The network is ``test_nettools_nat.FakeNat`` - the owner's router held in memory -
put where the panel's run takes its network (``nettools.nat._Net``), so these tests
send nothing and run alike on both CI runners. Its logic has its own file
(``test_nettools_nat.py``); this one is what the panel makes of it: the refusals,
the rows as they arrive, Stop, the session line, a rebuild in the middle of a run
and the copied results.
"""
import textwrap

from gui_harness import run_gui

NAT = """
import time
from beantester.i18n import T
from beantester.nettools import nat
from beantester.gui.toolbox import nat as panel_mod
from test_nettools_nat import FakeNat

nat.TRIES_S, nat.ROUND_S, nat.SETTLE_S, nat.OPEN_S, nat.POLL_S = (
    (0.02, 0.02, 0.02), 0.002, 0.02, 0.002, 0.001)
NET = FakeNat()
nat._Net = lambda: NET

def open_nat():
    app.select_page("tools")
    page = app.pages["tools"]
    page.select("nat")
    return page.panels["nat"]

def start(panel, stun="stun.test", turn="turn.test"):
    panel.stun.set(stun)
    panel.turn.set(turn)
    panel._start()

def finish(runner, until=None):
    deadline = time.monotonic() + 10
    while runner.finished is None and not (until and until()):
        assert time.monotonic() < deadline, "the run never ended"
        runner.poller.now()
        time.sleep(0.002)

def shown(panel):
    # the table's model, rendered the way its cells are
    return [panel.table._render(item) for item in panel.table.items]
"""


def test_what_is_not_a_server_is_refused_and_nothing_starts():
    run_gui(NAT + textwrap.dedent("""
        panel = open_nat()
        for stun, turn, key, args in (
                ("", "turn.test", "tools.nat.refused.empty_stun", {}),
                ("stun.test", " ", "tools.nat.refused.empty_turn", {}),
                ("stun.test:99999", "turn.test", "tools.nat.refused.port",
                 {"typed": "stun.test:99999"}),
                ("stun.test", "not a name", "tools.nat.refused.bad_server",
                 {"typed": "not a name"})):
            start(panel, stun, turn)
            assert panel.status.label.cget("text") == T(key, **args), (stun, turn)
            assert panel.status.label.cget("style") == "Status.Bad.TLabel"
        assert panel.runner.run is None and NET.log == [], "nothing was started or sent"
    """))


def test_a_run_shows_each_row_the_conclusion_and_the_time_it_took():
    run_gui(NAT + textwrap.dedent("""
        panel = open_nat()
        assert panel.summary.cget("text") == "" and shown(panel) == []
        assert str(panel.copy_btn.state()).count("disabled"), "nothing to copy yet"
        start(panel)
        assert panel.start_btn.cget("text") == T("tools.nat.stop"), "Start became Stop"
        assert "disabled" in str(panel.stun_entry.state()), "the servers stay as asked"
        finish(panel.runner, until=lambda: len(panel.runner.rows) >= 2)
        panel.refresh()
        assert len(shown(panel)) >= 2 and panel.summary.cget("text") == "", \\
            "no conclusion from part of the rows: it would change as they come"
        finish(panel.runner)
        panel.refresh()
        rows = shown(panel)
        assert len(rows) == 4 + len(nat.TURN_TRANSPORTS), rows
        assert rows[0][0] == T("tools.nat.row.public") and rows[0][1] == "203.0.113.7"
        assert rows[3][1] == T("tools.nat.result.fails"), "one side first, on this router"
        assert panel.summary.cget("text") == T("tools.nat.conclusion.together_only")
        assert panel.session.cget("text") == T("tools.nat.session.none")
        assert panel.status.label.cget("text").startswith(T("tools.nat.status_done",
                                                             time="@@", s="@@").split("@@")[0])
        assert panel.start_btn.cget("text") == T("tools.nat.start")
        assert "disabled" not in str(panel.copy_btn.state())
        # the row's colour is its state's, and a row that works keeps the table's own
        tags = [panel.table._tag_of(item) for item in panel.table.items]
        assert tags[3] == "warn" and tags[0] == "", tags
    """))


def test_stop_in_the_middle_sends_nothing_more_and_says_what_was_not_checked():
    run_gui(NAT + textwrap.dedent("""
        panel = open_nat()
        start(panel)
        finish(panel.runner, until=lambda: len(panel.runner.rows) >= 2)
        panel._start_or_stop()                   # Stop
        finish(panel.runner)
        sent = len(NET.log)
        panel.refresh()
        rows = shown(panel)
        assert len(rows) == 4 + len(nat.TURN_TRANSPORTS), rows
        assert rows[-1][2] == T("tools.nat.detail.stopped"), rows[-1]
        assert panel.status.label.cget("text").startswith(
            T("tools.nat.status_stopped", time="@@").split("@@")[0])
        time.sleep(0.05)
        panel.runner.poller.now()
        assert len(NET.log) == sent, "nothing went out after the run said it stopped"
    """))


def test_a_run_stopped_after_one_failed_turn_transport_does_not_say_no_turn():
    run_gui(NAT + textwrap.dedent("""
        NET.udp_turn, NET.tcp = "420", {3478: "refused", 80: "refused"}
        NET.tls = {5349: "not_tls", 443: "untrusted"}
        copied = []
        panel_mod.copy_confirmed = lambda app, text, said, area: copied.append(text)
        panel = open_nat()
        no_turn = T("tools.nat.conclusion.no_turn")
        start(panel)
        finish(panel.runner)
        panel.refresh()
        assert panel.summary.cget("text").endswith(no_turn), "every transport failed"
        start(panel)
        finish(panel.runner, until=lambda: any(row.test == "turn" for row in panel.runner.rows))
        panel.copy_report()
        assert copied == [], "nothing is copied while the run goes on"
        panel._start_or_stop()                   # Stop, after one TURN transport
        finish(panel.runner)
        panel.refresh()
        assert no_turn not in panel.summary.cget("text")
        panel.copy_report()
        assert len(copied) == 1 and nat.translate("tools.nat.conclusion.no_turn", "en") \\
            not in copied[0]
    """))


def test_the_session_line_says_what_the_session_does_to_these_packets():
    run_gui(NAT + textwrap.dedent("""
        panel = open_nat()
        asked = []
        app.running = True
        app.engine.flow_scope = lambda key: asked.append(key) or True
        start(panel)
        finish(panel.runner)
        panel.refresh()
        assert panel.session.cget("text") == T("tools.nat.session.impaired")
        assert asked and all(len(key) == 3 for key in asked), "the log's flow keys"
        app.engine.flow_scope = lambda key: None
        start(panel)
        finish(panel.runner)
        panel.refresh()
        assert panel.session.cget("text") == T("tools.nat.session.not_captured")
        # nothing sent at all (no name was found): the filter is not blamed for it
        start(panel, "nowhere.test", "elsewhere.test")
        finish(panel.runner)
        panel.refresh()
        assert not panel.runner.run.flows and panel.session.cget("text") == ""
        app.running = False
    """))


def test_closing_the_window_stops_the_run():
    run_gui(NAT + textwrap.dedent("""
        from beantester.gui import toolbox
        panel = open_nat()
        start(panel)
        finish(panel.runner, until=lambda: len(panel.runner.rows) >= 2)
        toolbox.stop_sending(app)
        assert panel.runner.run.stopped, "the job in flight reads it before every send"
        finish(panel.runner)
        sent = len(NET.log)
        time.sleep(0.05)
        panel.runner.poller.now()
        assert len(NET.log) == sent
    """))


def test_a_run_goes_on_through_a_rebuild_and_the_new_panel_shows_it():
    """A language change rebuilds every panel while the run's job is out: the run
    belongs to the window, so it ends, and the rebuilt panel shows all of it."""
    run_gui(NAT + textwrap.dedent("""
        panel = open_nat()
        start(panel)
        finish(panel.runner, until=lambda: len(panel.runner.rows) >= 2)
        app._build_ui()
        rebuilt = open_nat()
        assert rebuilt is not panel and rebuilt.runner is panel.runner
        finish(rebuilt.runner)
        rebuilt.refresh()
        assert len(shown(rebuilt)) == 4 + len(nat.TURN_TRANSPORTS)
        assert rebuilt.stun.get() == "stun.test", "what was typed outlives the rebuild"
    """))


def test_copy_results_is_the_english_report():
    run_gui(NAT + textwrap.dedent("""
        copied = []
        panel_mod.copy_confirmed = lambda app, text, said, area: copied.append(text)
        panel = open_nat()
        panel.copy_report()
        assert copied == [], "nothing before a run"
        start(panel)
        finish(panel.runner)
        panel.copy_report()
        assert copied == [nat.report(panel.runner.run, panel.runner.rows)]
        assert "Public address: 203.0.113.7" in copied[0]
    """))


def test_the_row_menu_copies_the_public_address_without_logging_it():
    """The menu the way a person reaches it: a right click on a row, through the
    table's own binding, and each entry by its place in the menu - so a menu never
    bound, or built in another order than COPY_ADDRESS and COPY_ROW say, fails here."""
    run_gui(NAT + textwrap.dedent("""
        from beantester.gui.theme import MENU_ENTRY_INERT, MENU_ENTRY_LIVE

        class Click:
            x_root = y_root = y = 10

        panel = open_nat()
        menu, tree = panel.menu, panel.table.tree
        right_click = tree.bindings["<<ContextMenu>>"][-1]
        entry = lambda index: menu.commands[index]["command"]
        copied = lambda: [line for line in app._log_lines if T("log.copied") in line]

        def on_a_row():
            tree.row_at = panel.table._slots[0]
            menu.posted = 0
            assert right_click(Click()) == "break" and menu.posted == 1, "the menu opened"

        assert right_click(Click()) == "break" and menu.posted == 0, "no row, no menu"
        app.copy_to_clipboard("before")
        entry(panel_mod.COPY_ADDRESS)()
        assert root.clipboard_get() == "before", "nothing to copy before a run"

        NET.silent = {("stun", port) for port in (3478, 443, 53)}
        start(panel)
        finish(panel.runner)
        NET.silent = set()
        assert panel.runner.rows and nat.public_address(panel.runner.rows) is None
        on_a_row()
        assert menu.entry_states[panel_mod.COPY_ADDRESS] == MENU_ENTRY_INERT, "no address"
        assert menu.entry_states[panel_mod.COPY_ROW] == MENU_ENTRY_LIVE

        start(panel)
        finish(panel.runner, until=lambda: nat.public_address(panel.runner.rows))
        on_a_row()
        assert menu.entry_states[panel_mod.COPY_ADDRESS] == MENU_ENTRY_LIVE, "as soon as the run has it"
        entry(panel_mod.COPY_ADDRESS)()
        assert root.clipboard_get() == "203.0.113.7", root.clipboard_get()
        assert T("tools.nat.address_logged") in copied()[-1], copied()
        assert "203.0.113.7" not in copied()[-1], "the log line does not carry it"
        entry(panel_mod.COPY_ROW)()
        row = panel.table.copy_text()
        assert row and root.clipboard_get() == row, (row, root.clipboard_get())
        finish(panel.runner)
    """))
