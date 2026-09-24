"""The Tools tab: its registry, its lazy panels, and a tool that fails on its own.

Two layers, tested separately on purpose. The PAGE (``gui/pages/toolbox.py``) is
a dispatcher over ``gui/toolbox.TOOLS``, so most of its tests swap the registry
for two toy tools that count what is done to them - that is the only way to see
"built on first view" and "the others are not refreshed" with one real tool in
the registry. The expression tester, the first real tool, is tested through its
panel below; its logic has its own file (``test_nettools_exprtest.py``).
"""
import textwrap

from gui_harness import run_gui

# Two toy tools that record what the page does to them. Their tab label reuses a
# real key so the smoke check for raw i18n keys has nothing to say about them.
TOYS = """
from tkinter import ttk
from beantester.gui.pages import toolbox as page_mod
from beantester.gui.toolbox import Tool

built = []

class Toy:
    ID = "a"
    def __init__(self, app, parent):
        built.append(self.ID)
        self.frame = ttk.Frame(parent)
        self.refreshed = 0
        self.torn = 0
        self.prefs = []
    def refresh(self):
        self.refreshed += 1
    def teardown(self):
        self.torn += 1
    def on_pref_changed(self, key):
        self.prefs.append(key)

class ToyB(Toy):
    ID = "b"

def use_toys(*classes):
    page_mod.TOOLS = tuple(Tool(c.ID, "app.tabs.tools", c) for c in classes)
    page_mod.TOOL_BY_ID = {tool.id: tool for tool in page_mod.TOOLS}
"""

# What the window does once it is built, and the fake Tk does not: real Tk QUEUES
# the <<NotebookTabChanged>> of the Tools page's own `select` and runs it after the
# constructor, whichever page is on screen (measured 2026-09-24 on Tk 8.6.15 and
# 9.0.4) - then the tick. A tool that goes to work on either works at every start.
START_UP = """
def opened_on_start_up():
    page = app.pages["tools"]
    assert app.current_page() is not page, "the window opens on another page"
    for callback in page.nb.bindings["<<NotebookTabChanged>>"]:
        callback(None)
    app._tick()
"""


def test_the_tools_page_is_the_renderer_of_its_registry():
    """Every registry entry is a tab, in order, and builds into its own panel class."""
    run_gui("""
        from beantester.gui.pages.toolbox import ToolboxPage
        from beantester.gui.toolbox import TOOLS

        page = app.pages["tools"]
        assert isinstance(page, ToolboxPage), type(page)
        # SUBPAGES is what the render check and the layout test walk - derived,
        # so a tool is measured in CI the day it is added
        assert page.SUBPAGES == tuple((t.id, t.label) for t in TOOLS), page.SUBPAGES
        assert len(page.nb.tabs()) == len(TOOLS)
        assert len({t.id for t in TOOLS}) == len(TOOLS), "tool ids must be unique"
        for tool in TOOLS:
            page.select(tool.id)
            assert page.current() == tool.id, (tool.id, page.current())
            assert isinstance(page.panels[tool.id], tool.factory), \\
                (tool.id, type(page.panels[tool.id]))
    """)


def test_a_panel_is_built_on_first_view_and_the_open_tab_is_remembered():
    run_gui(TOYS + textwrap.dedent("""
        use_toys(Toy, ToyB)
        app.ui.set("tools_page", "b")
        page = page_mod.ToolboxPage(app, root)
        assert built == ["b"], built                 # only the tab that is open
        assert page.current() == "b"

        page.select("a")                             # built SYNCHRONOUSLY in select
        assert built == ["b", "a"], built
        # what <<NotebookTabChanged>> runs - and real Tk runs it late, once the window
        # is built, for the constructor's own select: with another page on screen it
        # remembers the tab and puts nothing to work
        assert app.current_page() is not page
        page._on_subpage()
        assert app.ui.get("tools_page") == "a", app.ui.get("tools_page")
        assert page.panels["a"].refreshed == 0, "a page off screen is not looked at"
        app.pages["tools"] = page
        app.select_page("tools")
        page._on_subpage()                           # a tab changed on screen: a look
        assert page.panels["a"].refreshed == 1
        page.select("a")
        assert built == ["b", "a"], "a panel is built once, not on every look"

        # the tick reaches the tool on screen and no other
        before = page.panels["b"].refreshed
        page.refresh()
        assert page.panels["b"].refreshed == before
        assert page.panels["a"].refreshed == 2       # _on_subpage + refresh

        # broadcasts reach every panel that exists
        page.on_pref_changed("rate_unit")
        assert page.panels["a"].prefs == page.panels["b"].prefs == ["rate_unit"]
        page.teardown()
        assert page.panels["a"].torn == page.panels["b"].torn == 1

        # a tool that is gone from the registry opens the first tab
        app.ui.set("tools_page", "removed-in-a-later-version")
        assert page_mod.ToolboxPage(app, root).current() == "a"
    """))


def test_a_tool_that_fails_does_not_take_the_tab_or_the_tick_down():
    """``App._tick`` refreshes the page in ONE try with the summary bar and the
    secondary windows - an exception out of a panel would stop all of them and
    log an error every 700 ms. And a tool whose constructor raises must become a
    message, not half a panel above one."""
    run_gui(TOYS + textwrap.dedent("""
        from beantester.i18n import T

        class Broken:
            ID = "broken"
            def __init__(self, app, parent):
                ttk.Label(parent, text=T("app.tabs.tools"))  # half built, then...
                raise RuntimeError("tool constructor fails on purpose")

        class Noisy(Toy):
            ID = "noisy"
            def refresh(self):
                raise RuntimeError("tool refresh fails on purpose")
            def teardown(self):
                raise RuntimeError("tool teardown fails on purpose")
            def focus_search(self):
                raise RuntimeError("tool search fails on purpose")

        use_toys(Broken, Noisy, ToyB)
        app._build_ui()                                # the App's own page, rebuilt
        page = app.pages["tools"]
        assert isinstance(page.panels["broken"], page_mod._Unavailable)
        tab = page.tabs["broken"]
        assert tab.winfo_children() == [page.panels["broken"].frame], \\
            "what the tool built before failing is cleared away"
        page.select("broken")
        assert isinstance(page.panels["broken"], page_mod._Unavailable), "not retried"

        page.select("noisy")
        app.select_page("tools")
        marker = T("log.ui_error", e="@@").split("@@")[0]
        app._tick()
        app._tick()
        assert not [l for l in app._log_lines if marker in l], app._log_lines[-5:]
        assert page.focus_search() is False            # falls through to the table
        page.select("b")
        page.refresh()
        assert page.panels["b"].refreshed >= 1, "a sibling of a broken tool still works"
        app._build_ui()                                # teardown of a noisy panel too
    """), allow_faults=("on purpose",))


def test_ctrl_f_on_the_tools_tab_finds_the_box_of_the_tool_on_screen():
    """The socket table has a search box of its own, and Ctrl+F on it goes there. A
    tool without one sends the shortcut on to the connection table - what Ctrl+F did
    from this tab before any tool had a box."""
    run_gui("""
        from beantester.gui.pages import focus_search
        app.select_page("tools")
        page = app.pages["tools"]
        page.select("sockets")
        focus_search(app)
        assert app.current_page() is page, app.current_page()
        assert root.focus_get() is page.panels["sockets"].entry, root.focus_get()

        page.select("exprtest")
        focus_search(app)
        assert app.current_page() is app.pages["connections"], app.current_page()
    """)


def test_resetting_the_layout_forgets_the_open_tool():
    run_gui("""
        from beantester.gui import dialogs
        dialogs.ask_yes_no = lambda *a, **k: True
        app.ui.set("tools_page", "exprtest")
        app.reset_ui_layout()
        assert app.ui.get("tools_page") == "", app.ui.get("tools_page")
    """)


# -- the expression tester ------------------------------------------------------ #
PANEL = """
from beantester.i18n import T
from beantester.gui.toolbox.base import remembered

def open_tester():
    app.select_page("tools")
    page = app.pages["tools"]
    page.select("exprtest")
    return page.panels["exprtest"]

def pick(panel, key):
    panel.field_var.set(panel.labels[key])
    panel._on_field()

def type_in(panel, name, text):
    panel.vars[name].set(text)
    panel._typed(name)
"""


def test_the_field_list_names_every_expression_field_once_in_every_language():
    """The list maps a shown name back to a field key through a dict, so two
    fields sharing a name in ANY language would silently send one to the other -
    and the form's own labels would do exactly that (`dst_ip` and `block_ip` are
    both "IP:")."""
    run_gui("""
        from beantester.fields import expression_fields
        from beantester.gui.toolbox.exprtest import FIELD_NAME_KEY, field_label
        for code in LANGS:
            bnt.set_language(code)
            keys = [f.key for f in expression_fields()]
            names = [field_label(k) for k in keys]
            assert len(set(names)) == len(names), (code, names)
            raw = [k for k, n in zip(keys, names) if n == FIELD_NAME_KEY.format(key=k)]
            assert not raw, (code, raw)
    """)


def test_the_tester_answers_and_names_the_term_that_decided():
    run_gui(PANEL + textwrap.dedent("""
        panel = open_tester()
        pick(panel, "dst_ip")
        type_in(panel, "expression", "10.0.0.0/16, !10.0.5.0/24")
        type_in(panel, "value", "10.0.5.7")
        verdict = panel.evaluate()
        assert verdict.state == "no_match", verdict
        assert panel.verdict.cget("text") == T("tools.exprtest.no_match")
        details = panel.details.cget("text")
        assert "!10.0.5.0/24" in details, details
        assert "disabled" not in panel.use.state(), "a parsed expression can be used"
        assert "disabled" in panel.pid.state(), "a pid means nothing to an address"

        pick(panel, "target")
        assert "disabled" not in panel.pid.state()
        assert panel.value_label.cget("text") == T("tools.exprtest.value_process")
        assert T("tools.exprtest.note_process_tree") in panel.notes.cget("text")

        # what was typed is saved on the key, not when the pause runs out
        assert remembered(app, "exprtest")["expression"] == "10.0.0.0/16, !10.0.5.0/24"
    """))


def test_use_replaces_the_field_and_refuses_an_empty_or_unreadable_expression():
    """Empty, in the Process field, means ALL traffic once applied - a button that
    clears the target is not what this panel is for (CLAUDE.md, rule 6)."""
    run_gui(PANEL + textwrap.dedent("""
        panel = open_tester()
        pick(panel, "dst_ip")
        app.vars["dst_ip"].set("192.168.0.0/16")
        type_in(panel, "expression", "  10.0.0.0/8 ")
        panel.use_it()
        assert app.vars["dst_ip"].get() == "10.0.0.0/8", app.vars["dst_ip"].get()
        assert any(T("tools.exprtest.field.dst_ip") in line for line in app._log_lines)

        for text in ("   ", "10.0.0.0/8, !"):
            type_in(panel, "expression", text)
            panel.evaluate()
            assert "disabled" in panel.use.state(), text
            panel.use_it()
            assert app.vars["dst_ip"].get() == "10.0.0.0/8", (text, app.vars["dst_ip"].get())

        pick(panel, "target")
        app.vars["target"].set("chrome")
        type_in(panel, "expression", "")
        panel.use_it()
        assert app.vars["target"].get() == "chrome", "the target was cleared"
    """))


def test_what_was_typed_survives_a_rebuild_of_the_window():
    """A language change rebuilds every widget and every page object; the inputs
    live against the App (decided 2026-09-23: until the program closes)."""
    run_gui(PANEL + textwrap.dedent("""
        panel = open_tester()
        pick(panel, "target")
        type_in(panel, "expression", "chrome, !chromedriver")
        type_in(panel, "value", "chromedriver.exe")
        app._build_ui()
        again = open_tester()
        assert again is not panel
        assert again.field_key() == "target", again.field_key()
        assert again.vars["expression"].get() == "chrome, !chromedriver"
        assert again.vars["value"].get() == "chromedriver.exe"
        assert again.evaluate().state == "no_match"
        assert again.verdict.cget("text") == T("tools.exprtest.no_match")
    """))


def test_a_rebuild_puts_the_typing_timer_away_first():
    """A timer left scheduled on a destroyed widget fires into Tcl's background
    error handler, where nothing reports it (rig `lang_timers`)."""
    run_gui(PANEL + textwrap.dedent("""
        panel = open_tester()
        scheduled, cancelled = [], []
        panel.frame.after = lambda ms, fn: scheduled.append(fn) or "job-1"
        panel.frame.after_cancel = lambda job: cancelled.append(job)
        type_in(panel, "expression", "443")
        assert scheduled, "typing schedules the verdict"
        app._build_ui()
        assert cancelled == ["job-1"], cancelled

        # and a widget that cannot schedule any more is not acted on either
        from beantester.gui.toolbox.base import Debounce
        ran = []
        class Gone:
            def after(self, *a):
                raise RuntimeError("widget already destroyed on purpose")
        Debounce(Gone(), lambda: ran.append(1))()
        assert ran == []
    """), allow_faults=("on purpose",))


# -- diagnostics ------------------------------------------------------------------- #
# The checks are stood in for: a real driver.doctor() asks the service manager of
# whatever machine runs the suite. `gate` holds a check back for the tests that need
# one still running.
DIAG = """
import threading, time
from beantester.gui import dialogs
from beantester.i18n import T
from beantester.nettools import diagnostics as dg

FAKE = dg.Diagnosis(False, (dg.Check("python", "ok", "3.14"),
                            dg.Check("windivert driver", "warn", "WinDivert=running"),
                            dg.Check("administrator", "fail", "not elevated"),
                            dg.Check("future check", "later", "no key for it yet")),
                    "D:/data")
gate = threading.Event()
gate.set()
calls, cleaned = [], []

def fake_diagnose():
    calls.append("check")
    gate.wait(5)
    return FAKE

dg.diagnose = fake_diagnose
dg.cleanup_blocker = lambda: ""
dg.clean_up = lambda seen: (cleaned.append(1), ("WinDivert: stopped and removed",))[1]

def open_diag():
    app.select_page("tools")
    page = app.pages["tools"]
    page.select("diagnostics")
    page._on_subpage()          # what the tab change runs on real Tk: the first look
    return page.panels["diagnostics"]

def settle(panel):
    deadline = time.monotonic() + 5
    while panel.pending():
        assert time.monotonic() < deadline, "the worker never answered"
        time.sleep(0.01)

def texts(widget):
    return [w.kw.get("text") for w in fake_tk.walk(widget) if w.kw.get("text")]

def style_of(widget, text):
    return next(w.kw.get("style") for w in fake_tk.walk(widget) if w.kw.get("text") == text)
"""


def test_diagnostics_shows_every_check_with_its_verdict_and_checks_once_by_itself():
    run_gui(DIAG + textwrap.dedent("""
        panel = open_diag()
        settle(panel)
        assert calls == ["check"], "the first view checks once, by itself"
        shown = texts(panel.rows)
        for name, state, style in (("python", "ok", "Good.TLabel"),
                                   ("windivert driver", "warn", "Status.Warn.TLabel"),
                                   ("administrator", "fail", "Status.Bad.TLabel")):
            assert T(dg.check_key(name)) in shown, (name, shown)
            assert style_of(panel.rows, T("tools.diagnostics.state." + state)) == style
        # the program's own words, as --doctor prints them
        assert "WinDivert=running" in shown and "not elevated" in shown, shown
        # a check doctor() gives before the language files know it: its own name,
        # never a raw key; a state it does not know: shown as it is, muted
        assert "future check" in shown and "LATER" in shown, shown
        assert not [t for t in shown if t.startswith("tools.")], shown
        assert T("about.data_dir", path="D:/data") in shown
        assert panel.verdict.cget("text") == T("tools.diagnostics.verdict_fail")
        assert panel.verdict.cget("style") == "Status.Bad.TLabel"
        assert "disabled" not in panel.copy_btn.state()

        # checked again: the rows are rebuilt in a NEW container, so the resize
        # handlers bound to the old one go with it
        first = panel.rows
        panel.check()
        settle(panel)
        assert calls == ["check", "check"], calls
        assert panel.rows is not first and not first.winfo_exists()
    """))


def test_diagnostics_checks_when_first_looked_at_and_not_at_start_up():
    """The tool the window reopens on is built with the window, so a check in its
    constructor asked the service manager at every start of the program, for a tab
    nobody might open (B-21)."""
    run_gui(DIAG + START_UP + textwrap.dedent("""
        app.ui.set("tools_page", "diagnostics")
        app._build_ui()                  # the window, opening on a remembered tool
        assert "diagnostics" in app.pages["tools"].panels, "the remembered tool is built"
        opened_on_start_up()
        assert calls == [], "and checks nothing until it is on screen"

        panel = open_diag()
        settle(panel)
        assert calls == ["check"], calls
        app._tick()
        panel.refresh()
        settle(panel)
        assert calls == ["check"], "after that, only Check again checks"
    """))


def test_a_first_check_that_fails_says_so_and_is_not_retried_by_itself():
    """A failure waits for "Check again". Asked again on every tick, a service
    manager that refuses would be asked for as long as the tab stays open."""
    run_gui(DIAG + textwrap.dedent("""
        def refused():
            calls.append("check")
            raise OSError("the service manager refused on purpose")
        dg.diagnose = refused
        panel = open_diag()
        settle(panel)
        assert calls == ["check"], calls
        assert "refused on purpose" in panel.status.label.cget("text")
        assert "disabled" in panel.copy_btn.state(), "no rows, no report to copy"
        assert "disabled" not in panel.check_btn.state(), "and it can be asked again"
        for _ in range(3):
            app._tick()
            panel.refresh()
            settle(panel)
        assert calls == ["check"], calls
        panel.check()
        settle(panel)
        assert calls == ["check", "check"], calls
    """), allow_faults=("on purpose",))


def test_a_check_that_fails_says_why_and_keeps_the_rows_it_had():
    run_gui(DIAG + textwrap.dedent("""
        panel = open_diag()
        settle(panel)
        def refused():
            raise OSError("the service manager refused on purpose")
        dg.diagnose = refused
        panel.check()
        settle(panel)
        status = panel.status.label
        assert "refused on purpose" in status.cget("text"), status.cget("text")
        assert status.cget("style") == "Status.Bad.TLabel"
        assert "WinDivert=running" in texts(panel.rows), "the last good rows stay"
        assert "disabled" not in panel.check_btn.state(), "and it can be asked again"
    """), allow_faults=("on purpose",))


def test_cleaning_up_waits_for_the_session_and_for_a_yes():
    """The driver is the session's: it stays loaded while one runs, starts or stops
    (the handle opens before `running` turns True and closes after it turns False),
    and it is unloaded only after the person has read what that interrupts."""
    run_gui(DIAG + textwrap.dedent("""
        panel = open_diag()
        settle(panel)
        answers = []
        dialogs.ask_yes_no = lambda *a: answers.pop(0)
        for running, transition in ((True, None), (False, "starting"), (False, "stopping")):
            app.running, app._transition = running, transition
            panel.refresh()
            assert "disabled" in panel.clean_btn.state(), (running, transition)
            panel.clean()
            assert cleaned == [], (running, transition)
        app.running, app._transition = False, None
        panel.refresh()
        assert "disabled" not in panel.clean_btn.state()

        answers.append(False)
        panel.clean()
        settle(panel)
        assert cleaned == [], "no means no"

        def start_meanwhile(*a):
            app.running = True               # a session began while the question was open
            return True
        dialogs.ask_yes_no = start_meanwhile
        panel.clean()
        assert cleaned == [], "the session is asked about again after the answer"
        app.running = False

        dialogs.ask_yes_no = lambda *a: True
        del calls[:]
        panel.clean()
        settle(panel)
        assert cleaned == [1]
        assert any(T("log.driver") in line and "stopped and removed" in line
                   for line in app._log_lines), app._log_lines[-3:]
        assert "stopped and removed" in panel.clean_note.cget("text")
        assert calls == ["check"], "the driver row is checked again after a cleanup"
    """))


def test_the_cleanup_is_held_to_what_was_open_at_the_yes():
    """The work runs later, on a worker, and a START pressed in between must still be
    caught (``driver.cleanup_driver``) - so the count of opened diverts is read on
    the UI thread at the yes, not by the worker when it gets round to it."""
    run_gui(DIAG + textwrap.dedent("""
        panel = open_diag()
        settle(panel)
        reads, asked = [], []
        def opens_so_far():
            reads.append(threading.current_thread() is threading.main_thread())
            return 41
        dg.opens_so_far = opens_so_far
        dg.clean_up = lambda seen: asked.append(seen) or ("done",)
        dialogs.ask_yes_no = lambda *a: False
        panel.clean()
        assert reads == [], "no yes, nothing read"
        dialogs.ask_yes_no = lambda *a: True
        panel.clean()
        settle(panel)
        assert reads == [True], "read once, on the UI thread"
        assert asked == [41], asked
    """))


def test_looking_now_puts_the_armed_timer_away_first():
    """`pending()` looks now while a timer is armed. A timer only forgotten keeps
    re-arming beside the new one - a second chain `cancel()` cannot reach, which a
    rebuild leaves firing into a destroyed widget."""
    run_gui(textwrap.dedent("""
        from beantester.gui.toolbox.base import Poller
        armed, cancelled = [], []
        class Widget:
            def after(self, ms, fn):
                armed.append(len(armed) + 1)
                return armed[-1]
            def after_cancel(self, timer):
                cancelled.append(timer)
        class Job:
            def busy(self):
                return True
            def collect(self):
                return None
        poller = Poller(Widget(), Job(), lambda outcome: None)
        poller.start()
        poller.now()
        poller.now()
        assert armed == [1, 2, 3], armed
        assert cancelled == [1, 2], "each look puts the armed timer away first"
        poller.cancel()
        assert cancelled == armed, "and the teardown reaches the one left"
    """))


def test_a_cleanup_that_cannot_run_from_here_says_why_before_anyone_presses_it():
    run_gui(DIAG + textwrap.dedent("""
        dg.cleanup_blocker = lambda: "tools.diagnostics.clean_needs_admin"
        panel = open_diag()
        settle(panel)
        assert "disabled" in panel.clean_btn.state()
        assert panel.clean_note.cget("text") == T("tools.diagnostics.clean_needs_admin")
        dialogs.ask_yes_no = lambda *a: True
        panel.clean()
        assert cleaned == []
    """))


def test_a_rebuild_mid_check_hands_the_answer_to_the_new_panel():
    """A language change while the check runs: the answer must reach the panel
    that exists when it lands, and nothing is asked twice."""
    run_gui(DIAG + textwrap.dedent("""
        gate.clear()
        panel = open_diag()
        assert panel.job.busy()
        app._build_ui()
        again = open_diag()
        assert again is not panel
        assert again.status.label.cget("text") == T("tools.common.working")
        gate.set()
        settle(again)
        assert "WinDivert=running" in texts(again.rows)
        assert calls == ["check"], calls

        # an answer already known is shown after a rebuild, without asking again
        app._build_ui()
        third = open_diag()
        assert "WinDivert=running" in texts(third.rows) and calls == ["check"], calls
        assert not third.job.busy()
    """))


def test_the_environment_report_is_copied_whole():
    run_gui(DIAG + textwrap.dedent("""
        panel = open_diag()
        settle(panel)
        panel.copy_report()
        copied = root.clipboard_get()
        blank = chr(10) * 2
        # the crash-log block counts faults as they happen, so the two blocks that
        # are this machine's report are compared exactly and the third by its shape
        assert copied.split(blank)[:2] == dg.report(FAKE).split(blank)[:2], copied
        # read, not just headed: a failed section is "crash log: could not be read"
        crash = copied.split(blank)[2]
        assert crash.startswith("crash log: ") and "could not be read" not in crash, copied
        assert any(T("log.copied") in line and T("tools.diagnostics.report_logged") in line
                   for line in app._log_lines), app._log_lines[-3:]
    """))


# -- sockets ------------------------------------------------------------------------ #
# The machine is stood in for at the logic's `read`: the real one asks the system,
# whose sockets differ on every runner. `gate` holds a read back for the tests that
# need one still running.
SOCK = """
import threading, time
from beantester.i18n import T
from beantester.nettools import sockets as sk
from beantester.portmap import SocketRow

ROWS = [SocketRow("TCP", 4, "0.0.0.0", 8080, "", None, "LISTEN", 1234),
        SocketRow("TCP", 6, "fe80::1%12", 50001, "fe80::5%12", 443, "ESTABLISHED", 1234),
        SocketRow("TCP", 4, "127.0.0.1", 13882, "127.0.0.1", 5000, "TIME_WAIT", 0),
        SocketRow("UDP", 4, "0.0.0.0", 5353, "", None, "", 100)]
NAMES = {1234: "chrome.exe", 100: "mdns.exe"}
gate = threading.Event()
gate.set()
reads, failed_tables = [], []

def fake_read():
    reads.append(1)
    gate.wait(5)
    return sk.Snapshot(tuple(sk._sockets(ROWS, NAMES)), tuple(failed_tables), time.time(), 3)

sk.read = fake_read

def open_sockets():
    app.select_page("tools")
    page = app.pages["tools"]
    page.select("sockets")
    return page.panels["sockets"]

def settle(panel):
    deadline = time.monotonic() + 5
    while panel.pending():
        assert time.monotonic() < deadline, "the worker never answered"
        time.sleep(0.01)

def shown(panel):
    return [s.local_port for s in panel.table.items]

def search(panel, text):
    panel.query.set(text)
    panel._typed()
    panel.debounce.now()

def select_port(panel, port):
    key = next(s.key for s in panel.table.items if s.local_port == port)
    panel.table.select_keys([key])
"""


def test_the_socket_table_reads_when_first_looked_at_and_not_at_start_up():
    """Every page is built when the window opens, and the Tools page builds its first
    tool with it - so a read in the constructor would ask the system at every start
    of the program, for a tab nobody may open."""
    run_gui(SOCK + START_UP + textwrap.dedent("""
        assert "sockets" in app.pages["tools"].panels, "the first tool is built at start"
        opened_on_start_up()
        assert reads == [], "and reads nothing until it is on screen"

        panel = open_sockets()
        settle(panel)
        assert reads == [1], reads
        assert shown(panel) == [5353, 8080, 13882, 50001], shown(panel)
        assert panel.count.cget("text") == T("conns.shown_of", shown=4, total=4)
        assert panel.status.label.cget("style") == "Muted.TLabel"
        # each cell under its own header - strict: one value per column, no fewer
        from beantester.gui.toolbox.sockets import COLUMNS, render
        cells = dict(zip(COLUMNS, render(panel.table.items[1]), strict=True))
        assert cells == {"proc": "chrome.exe", "pid": 1234, "proto": "TCP",
                         "local_ip": "0.0.0.0", "local_port": 8080, "state": "LISTEN",
                         "remote_ip": "", "remote_port": ""}, cells
        app._tick()
        panel.refresh()
        settle(panel)
        assert reads == [1], "after that, only Refresh reads"
        panel.read()
        settle(panel)
        assert reads == [1, 1], reads
    """))


def test_a_search_typed_during_a_read_is_answered_on_that_read():
    """The worker keeps only the last request that waits, so a search queued behind a
    read would be computed on the table it was queued against. Nothing is queued: the
    search waits in the box, and the answer that lands is checked against it."""
    run_gui(SOCK + textwrap.dedent("""
        gate.clear()
        panel = open_sockets()
        panel.pending()
        assert "disabled" in panel.refresh_btn.state(), "no second read while one runs"
        search(panel, "proto:udp")
        gate.set()
        settle(panel)
        assert shown(panel) == [5353], shown(panel)
        assert reads == [1], "answered on the read it waited for, not by reading again"
        assert "disabled" not in panel.refresh_btn.state()
    """))


def test_the_query_and_the_order_outlive_a_rebuild_of_the_window():
    run_gui(SOCK + textwrap.dedent("""
        panel = open_sockets()
        settle(panel)
        panel.table._clicked("local_port")            # ascending -> descending
        settle(panel)
        assert shown(panel) == [50001, 13882, 8080, 5353], shown(panel)
        search(panel, "proto:tcp")
        settle(panel)
        app._build_ui()
        again = open_sockets()
        settle(again)
        assert again is not panel
        assert again.query.get() == "proto:tcp"
        assert again.table.sort == {"col": "local_port", "reverse": True}, again.table.sort
        assert shown(again) == [50001, 13882, 8080], shown(again)
        assert reads == [1], "a rebuild shows what the window read, it does not read again"
    """))


def test_a_read_that_fails_says_why_and_keeps_the_rows_it_had():
    run_gui(SOCK + textwrap.dedent("""
        panel = open_sockets()
        settle(panel)
        def refused():
            raise OSError("the socket table refused on purpose")
        sk.read = refused
        panel.read()
        settle(panel)
        status = panel.status.label
        assert "refused on purpose" in status.cget("text"), status.cget("text")
        assert status.cget("style") == "Status.Bad.TLabel"
        assert shown(panel) == [5353, 8080, 13882, 50001], "the last good rows stay"
        at = time.strftime("%H:%M:%S", time.localtime(panel._latest().snapshot.read_at))
        assert T("tools.sockets.note_stale", time=at) in panel.note.cget("text")
        # a search is a new VIEW of the same old rows: they must still say how old
        search(panel, "proto:tcp")
        settle(panel)
        assert shown(panel) == [8080, 13882, 50001], shown(panel)
        assert T("tools.sockets.note_stale", time=at) in panel.note.cget("text"), \\
            panel.note.cget("text")
    """), allow_faults=("on purpose",))


def test_a_socket_table_the_system_refuses_is_said_in_the_windows_language():
    """A failure the tool can name is not an English exception in a Polish window;
    the program's own words still go to the crash log."""
    run_gui(SOCK + textwrap.dedent("""
        def refused():
            raise sk.Unreadable("tools.sockets.error_denied", "the system refused on purpose")
        sk.read = refused
        panel = open_sockets()
        settle(panel)
        text = panel.status.label.cget("text")
        assert text == T("tools.common.failed", error=T("tools.sockets.error_denied")), text
        assert "on purpose" not in text, text
    """), allow_faults=("on purpose",))


def test_a_first_read_that_fails_is_not_an_empty_machine_and_is_not_retried_by_itself():
    run_gui(SOCK + textwrap.dedent("""
        calls = []
        def refused():
            calls.append(1)
            raise OSError("nothing to read on purpose")
        sk.read = refused
        panel = open_sockets()
        settle(panel)
        assert panel.table.items == []
        assert panel.table._empty_text == "tools.sockets.empty_failed", panel.table._empty_text
        for _ in range(3):
            app._tick()
            panel.refresh()
        settle(panel)
        assert calls == [1], "a failed read waits for Refresh, not for the next tick"
    """), allow_faults=("on purpose",))


def test_the_table_says_why_it_is_empty_and_what_its_rows_are_missing():
    run_gui(SOCK + textwrap.dedent("""
        ROWS.append(SocketRow("TCP", 4, "10.0.0.2", 9000, "", None, "LISTEN", None))
        failed_tables.append("udp/v6")
        panel = open_sockets()
        settle(panel)
        note = panel.note.cget("text")
        assert T("tools.sockets.note_failed", tables="udp/v6") in note, note
        assert T("tools.sockets.note_no_pid", count=1) in note, note
        search(panel, "state:closing")
        settle(panel)
        assert panel.table._empty_text == "tools.sockets.empty_match"

        ROWS.clear()
        failed_tables.clear()
        panel.read()
        settle(panel)
        assert panel.table._empty_text == "tools.sockets.empty", panel.table._empty_text
    """))


def test_the_row_menu_offers_what_the_row_can_do_and_fills_the_control_fields():
    """A row with no process (TIME_WAIT) cannot be targeted, a listener has no remote
    address to limit to or block. The address goes into the field without its IPv6
    zone - the Control fields take an address, not an interface."""
    run_gui(SOCK + textwrap.dedent("""
        panel = open_sockets()
        settle(panel)
        menu = panel.menu
        for port, named, remote in ((13882, False, True), (8080, True, False),
                                    (50001, True, True)):
            select_port(panel, port)
            panel._show_menu(0, 0)
            for index in (2, 3):
                want = "normal" if named else "disabled"
                assert menu.entry_states[index]["state"] == want, (port, index)
            for index in (4, 5):
                want = "normal" if remote else "disabled"
                assert menu.entry_states[index]["state"] == want, (port, index)

        select_port(panel, 50001)
        panel._limit()
        limited = (app.vars["dst_ip"].get(), app.vars["dst_port"].get())
        assert limited == ("fe80::5", "443"), limited
        panel._block()
        assert app.vars["block_ip"].get() == "fe80::5", app.vars["block_ip"].get()
        panel._target()
        assert app.vars["target"].get() == "chrome.exe", app.vars["target"].get()
        panel._leave_alone()
        assert app.vars["target"].get() == "chrome.exe,!chrome.exe", app.vars["target"].get()

        # the right click itself goes through the table's shared route
        class Ev:
            x_root = y_root = y = 10
        panel.table.tree.row_at = None
        menu.posted = 0
        assert panel.table.row_menu_at_pointer(Ev()) == "break"
        assert menu.posted == 0, "a menu with no row under the pointer"
    """))


# -- the port check ------------------------------------------------------------------ #
# The machine is stood in for: a bind that refuses TCP 9010 the way a Windows
# reservation does (WSAEACCES), and a socket table with one server on 8080. The
# logic runs for real on top of them. `gate` holds a check back for the tests that
# need one still running.
PORTS = """
import threading, time
from beantester.i18n import T
from beantester.nettools import portcheck as pc
from beantester.nettools import sockets as sk
from beantester.gui.toolbox.portcheck import render

pc.WINDOWS = True
HOLDER = sk.Socket("k", "TCP", 4, "0.0.0.0", 8080, "", None, "LISTEN", 1234, "node.exe")
gate = threading.Event()
gate.set()
checks = []
real_check = pc.check

def reserved_9010(proto, family, port):
    return 10013 if (proto, port) == ("TCP", 9010) else 0

def fake_check(matcher, protocols, families):
    checks.append((str(matcher), protocols, families))
    gate.wait(5)
    return real_check(matcher, protocols, families, bind=reserved_9010,
                      read=lambda: sk.Snapshot((HOLDER,), (), time.time(), 1))

pc.check = fake_check

def open_ports():
    app.select_page("tools")
    page = app.pages["tools"]
    page.select("portcheck")
    page._on_subpage()          # what the tab change runs on real Tk
    return page.panels["portcheck"]

def settle(panel):
    deadline = time.monotonic() + 5
    while panel.pending():
        assert time.monotonic() < deadline, "the worker never answered"
        time.sleep(0.01)

def type_ports(panel, text):
    panel.ports.set(text)
    panel._typed()

def untick(panel, boxes, value, name):
    boxes[value].set(False)
    panel._ticked(name, boxes[value])

def row(panel, port, proto="TCP", family=4):
    return next(r for r in panel.table.items
                if (r.port, r.proto, r.family) == (port, proto, family))
"""


def test_the_port_check_waits_to_be_asked_and_answers_per_protocol_and_ip_version():
    run_gui(PORTS + START_UP + textwrap.dedent("""
        app.ui.set("tools_page", "portcheck")
        app._build_ui()
        opened_on_start_up()
        panel = open_ports()
        settle(panel)
        assert checks == [], "nothing is checked before a port is typed"
        assert "disabled" in panel.check_btn.state(), "and there is nothing to check"

        type_ports(panel, "8080, 9010")
        assert "disabled" not in panel.check_btn.state()
        panel.check()
        settle(panel)
        assert checks == [("8080, 9010", ("TCP", "UDP"), (4, 6))], checks
        assert len(panel.table.items) == 8, len(panel.table.items)
        first = panel.table.items[0]
        assert (first.port, first.proto, first.family, first.verdict) == \\
            (8080, "TCP", 4, pc.IN_USE), "what stops a program comes first"
        cells = render(row(panel, 8080))
        assert cells == (8080, "TCP", T("tools.portcheck.ipv4"),
                         T("tools.portcheck.verdict.in_use"),
                         T("tools.portcheck.holder", name="node.exe", pid=1234)), cells
        assert row(panel, 9010).verdict == row(panel, 9010, family=6).verdict == pc.RESERVED
        assert row(panel, 9010, "UDP").verdict == pc.FREE, "a reservation is per protocol"
        assert panel.count.cget("text") == T("tools.portcheck.count", taken=3, total=8)
        tags = {r.verdict: panel.table._tag_of(r) for r in panel.table.items}
        assert tags == {pc.IN_USE: "blocked", pc.RESERVED: "blocked", pc.FREE: ""}, tags
        assert T("tools.portcheck.note_checked", ports="8080, 9010",
                 what="TCP, UDP, IPv4, IPv6") in panel.note.cget("text")
        assert panel.status.label.cget("style") == "Muted.TLabel"

        for callback in panel.entry.bindings["<Return>"]:
            callback(None)
        settle(panel)
        assert len(checks) == 2, "Enter checks too"
    """))


def test_ports_the_parser_refuses_never_reach_the_worker():
    """The port language's own sentence, in the window's language, at once - not an
    English exception from a worker."""
    run_gui(PORTS + textwrap.dedent("""
        panel = open_ports()
        type_ports(panel, "9100-9000")
        panel.check()
        assert checks == [] and not panel.job.busy(), checks
        text = panel.status.label.cget("text")
        assert "9100-9000" in text and "Error" not in text, text
        assert panel.status.label.cget("style") == "Status.Bad.TLabel"
    """))


def test_too_many_ports_are_refused_with_their_numbers_in_the_windows_language():
    run_gui(PORTS + textwrap.dedent("""
        panel = open_ports()
        type_ports(panel, "1-1001")
        panel.check()
        settle(panel)
        text = panel.status.label.cget("text")
        want = T("tools.common.failed", error=T("tools.portcheck.error_too_many",
                                                count=1001, limit=pc.MAX_PORTS))
        assert text == want and "1001" in text, text
        assert panel.table.items == [], "nothing was checked"
    """))       # and nothing for the crash log: the harness fails on any recorded fault


def test_the_boxes_choose_what_is_checked_and_are_kept_across_a_rebuild():
    run_gui(PORTS + textwrap.dedent("""
        panel = open_ports()
        type_ports(panel, "8080")
        untick(panel, panel.protocols, "UDP", "proto_UDP")
        untick(panel, panel.families, 6, "family_6")
        panel.check()
        settle(panel)
        assert checks[-1][1:] == (("TCP",), (4,)), checks
        assert [(r.proto, r.family) for r in panel.table.items] == [("TCP", 4)]

        untick(panel, panel.protocols, "TCP", "proto_TCP")
        assert "disabled" in panel.check_btn.state(), "no protocol, nothing to check"
        panel.check()
        assert len(checks) == 1, checks

        app._build_ui()
        again = open_ports()
        assert again.ports.get() == "8080"
        assert [v.get() for v in again.protocols.values()] == [False, False]
        assert [v.get() for v in again.families.values()] == [True, False]
        assert len(again.table.items) == 1, "the answer outlives the rebuild"
    """))


def test_one_check_at_a_time_and_a_rebuild_mid_check_gets_the_answer():
    run_gui(PORTS + textwrap.dedent("""
        gate.clear()
        panel = open_ports()
        type_ports(panel, "8080")
        panel.check()
        assert panel.job.busy() and "disabled" in panel.check_btn.state()
        panel.check()
        assert len(checks) == 1, "nothing is queued behind a running check"
        app._build_ui()
        again = open_ports()
        assert again.status.label.cget("text") == T("tools.common.working")
        gate.set()
        settle(again)
        assert len(again.table.items) == 4 and len(checks) == 1, checks
        assert "disabled" not in again.check_btn.state()
    """))


def test_the_port_check_row_menu_acts_on_the_program_that_holds_the_port():
    run_gui(PORTS + textwrap.dedent("""
        panel = open_ports()
        type_ports(panel, "8080")
        panel.check()
        settle(panel)
        menu = panel.menu
        for proto, named in (("TCP", True), ("UDP", False)):
            panel.table.select_keys([row(panel, 8080, proto).key])
            panel._show_menu(0, 0)
            for index in (2, 3):
                want = "normal" if named else "disabled"
                assert menu.entry_states[index]["state"] == want, (proto, index)
        panel.table.select_keys([row(panel, 8080).key])
        panel._target()
        assert app.vars["target"].get() == "node.exe", app.vars["target"].get()
    """))


def test_a_header_click_sorts_the_port_check_without_checking_again():
    run_gui(PORTS + textwrap.dedent("""
        panel = open_ports()
        type_ports(panel, "9010, 8080, 7000")
        panel.check()
        settle(panel)
        panel.table._clicked("port")
        ports = [r.port for r in panel.table.items]
        assert ports == sorted(ports), ports
        panel.table._clicked("port")
        ports = [r.port for r in panel.table.items]
        assert ports == sorted(ports, reverse=True), ports
        assert len(checks) == 1, checks
    """))
