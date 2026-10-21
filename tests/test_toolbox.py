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
    """Every registry entry is a tab, in order, and builds into its own panel class -
    on a system that offers every capability, so the Linux runner sees the panels too
    (what a system without one shows is the test after this one)."""
    run_gui("""
        from beantester import capabilities
        from beantester.gui.pages.toolbox import ToolboxPage
        from beantester.gui.toolbox import TOOLS
        for cap in capabilities.CAPABILITIES.values():
            cap.module.supported = lambda: True
        app._build_ui()

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


def test_a_tool_this_system_lacks_says_so_and_builds_nothing():
    """The registry's ``needs``, asked by the page (``capabilities.why_not``): the tool's
    panel is not built at all - nothing in it can reach the missing API - and the tab
    says so in the shared words, keeps the tool's "?" and, for a tool that sends,
    leaves out the line of what it sends. Measured before this on Linux: every ping
    "failed" with code -1 and the Adapters tab was two blank tables."""
    run_gui("""
        from beantester import adapters as system_adapters, icmp
        from beantester.gui.pages import toolbox as page_mod
        from beantester.gui.toolbox import TOOL_BY_ID
        from beantester.gui.toolbox import ping as pp
        from beantester.i18n import T
        icmp.supported = lambda: False
        system_adapters.supported = lambda: False
        built_anyway = []
        real_init = pp.PingPanel.__init__
        pp.PingPanel.__init__ = lambda self, *a, **k: built_anyway.append(1) or real_init(
            self, *a, **k)
        app._build_ui()
        page = app.pages["tools"]
        for tool_id in ("ping", "adapters"):
            page.select(tool_id)
            panel = page.panels[tool_id]
            assert isinstance(panel, page_mod._NotHere), (tool_id, type(panel))
            texts = [w.kw.get("text") for w in fake_tk.walk(page.tabs[tool_id])]
            assert T("tools.not_here") in texts, (tool_id, texts)
            helps = [w for w in fake_tk.walk(panel.frame) if w.kw.get("style") == "Help.TButton"]
            assert len(helps) == 1, (tool_id, "the tool's own ? stays")
        texts = [w.kw.get("text") for w in fake_tk.walk(page.tabs["ping"])]
        assert T("tools.ping.sends") not in texts, "a tool that cannot run sends nothing"
        assert built_anyway == [], "Ping's panel was built on a system without Ping"
        page.refresh()                     # the page calls reach a panel with no behaviour
        page.teardown()
        pp.PingPanel.__init__ = real_init

        # the same registry on a system that has it: the real panel, built on first view
        icmp.supported = lambda: True
        app._build_ui()
        page = app.pages["tools"]
        page.select("ping")
        assert isinstance(page.panels["ping"], TOOL_BY_ID["ping"].factory)
        page.select("exprtest")            # a tool that needs nothing, on either system
        assert isinstance(page.panels["exprtest"], TOOL_BY_ID["exprtest"].factory)
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


def test_diagnostics_on_linux_speaks_of_linux_and_greys_out_what_it_cannot_read():
    """On Linux the panel spoke of Windows: the greyed-out cleanup button's tip said
    "Unloads a WinDivert driver" over the note saying there is nothing to clean up,
    the "?" sheet explained administrator rights and WinDivert's states, and the two
    report boxes promised adapters and a WinHTTP proxy that the report then gave as
    "not read on this system". Built once per platform, the way the Tools page
    builds it: the platform is only stood in for while the panel is made."""
    run_gui(DIAG + textwrap.dedent("""
        from beantester import capabilities, capture_backend, driver
        from beantester.gui.toolbox.diagnostics import BOX_NOT_HERE, OPTIONAL_BOXES, DiagnosticsPanel
        from beantester.gui.tooltip import tooltip_text

        # the real answer off Windows (DIAG stands in a Windows administrator's "")
        dg.cleanup_blocker = lambda: capture_backend.current().CLEANUP_BLOCKER
        real_is_windows = driver.is_windows

        def build(windows, backend, readable):
            driver.is_windows = lambda: windows
            capture_backend._CURRENT = backend
            for spec in OPTIONAL_BOXES:
                capabilities.CAPABILITIES[spec.needs].module.supported = lambda r=readable: r
            try:
                return DiagnosticsPanel(app, app.root)
            finally:
                driver.is_windows = real_is_windows

        def sheet(panel):
            opened = []
            dialogs.show_help = lambda parent, title, body: opened.append(body)
            [button] = [w for w in fake_tk.walk(panel.frame) if w.kw.get("style") == "Help.TButton"]
            button.kw["command"]()
            return opened[0]

        linux = build(False, capture_backend._EBPFDIVERT, False)
        assert linux.clean_btn._bnt_tooltip.text == tooltip_text("tools.diagnostics.clean_linux")
        assert "disabled" in linux.clean_btn.state()
        for section, (box, ticked) in linux.boxes.items():
            assert "disabled" in box.state(), section
            assert box._bnt_tooltip.text == tooltip_text(BOX_NOT_HERE), section
            assert not ticked.get(), section
        assert linux.include == {}, "a box it cannot fill never reaches the report"
        text = sheet(linux)
        assert T("tools.diagnostics.help_linux") in text, text
        assert T("tools.diagnostics.clean_linux") in text, text
        assert "Windows" not in text and "WinDivert" not in text, text
        assert T("tools.diagnostics.help_adapters") not in text, "no paragraph for a greyed-out box"

        # Windows: what it always was, the sheet in its old order
        windows = build(True, capture_backend._WINDIVERT, True)
        assert windows.clean_btn._bnt_tooltip.text == tooltip_text("tips.tools_diagnostics_clean")
        for spec in OPTIONAL_BOXES:
            box, ticked = windows.boxes[spec.section]
            assert "disabled" not in box.state(), spec.section
            assert box._bnt_tooltip.text == tooltip_text(spec.tip), spec.section
            assert windows.include[spec.section] is ticked
        assert sheet(windows) == "\\n\\n".join(T(key) for key in (
            "tools.diagnostics.help_body", "tools.diagnostics.help_windows",
            "tools.diagnostics.help_copy", "tools.diagnostics.help_adapters",
            "tools.diagnostics.help_proxy"))
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
    """Every page is built when the window opens, and the Tools page builds the tool
    that was open with it - so a read in the constructor would ask the system at every
    start of the program, for a tab nobody may open. (Ping is the first tab since
    2026-10-19, so the window opens here on the remembered socket table.)"""
    run_gui(SOCK + START_UP + textwrap.dedent("""
        app.ui.set("tools_page", "sockets")
        app._build_ui()                  # the window, opening on a remembered tool
        assert "sockets" in app.pages["tools"].panels, "the open tool is built at start"
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
        from beantester.gui.theme import MENU_ENTRY_INERT, MENU_ENTRY_LIVE
        panel = open_sockets()
        settle(panel)
        menu = panel.menu
        for port, named, remote in ((13882, False, True), (8080, True, False),
                                    (50001, True, True)):
            select_port(panel, port)
            panel._show_menu(0, 0)
            for index in (2, 3):
                want = MENU_ENTRY_LIVE if named else MENU_ENTRY_INERT
                assert menu.entry_states[index] == want, (port, index)
            for index in (4, 5):
                want = MENU_ENTRY_LIVE if remote else MENU_ENTRY_INERT
                assert menu.entry_states[index] == want, (port, index)

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


# -- TCP health ---------------------------------------------------------------------- #
# The socket table above, and Windows' EStats stood in for at ``tcpestats.watch`` and
# ``tcpestats.read`` - what those answer is test_tcpestats.py's. ``ANSWER[0]`` is what
# every reading says; ``admin`` what the process's token says.
TCPH = SOCK + """
from beantester import driver, tcpestats
from beantester.nettools import tcphealth as th
from beantester.tcprow import Connection
from beantester.gui.toolbox.tcphealth import render as health_cells

SAMPLE = tcpestats.Sample(214, 231, 18, 402, 31, 342, 16488, 1, 9, 27, 1460, 2400, 18100)
ANSWER = [tcpestats.Reading(tcpestats.OK, SAMPLE)]
LINKED = Connection("fe80::1%12", 50001, "fe80::5%12", 443)
admin = [True]
watched, readings = [], []

def est_watch(connection, system=None):
    watched.append(connection)
    return ANSWER[0]

def est_read(connection, system=None):
    readings.append(connection)
    return ANSWER[0]

tcpestats.supported = lambda: True
tcpestats.watch = est_watch
tcpestats.read = est_read
driver.is_admin = lambda: admin[0]

def health():
    return app.pages["tools"].panels["tcphealth"]

def watch_linked():
    sockets_panel = open_sockets()
    settle(sockets_panel)
    select_port(sockets_panel, 50001)
    sockets_panel._health()
    panel = health()
    settle(panel)
    return panel
"""


def test_show_tcp_health_from_the_socket_table_watches_that_connection():
    """The owner's choice (2026-10-19): a connection comes from a row menu, here the
    socket table's. Only a TCP row with a connection behind it is offered."""
    run_gui(TCPH + textwrap.dedent("""
        from beantester.gui.theme import MENU_ENTRY_INERT, MENU_ENTRY_LIVE
        from beantester.gui.toolbox.sockets import HEALTH
        sockets_panel = open_sockets()
        settle(sockets_panel)
        for port, offered in ((8080, False), (13882, False), (5353, False), (50001, True)):
            select_port(sockets_panel, port)
            sockets_panel._show_menu(0, 0)
            want = MENU_ENTRY_LIVE if offered else MENU_ENTRY_INERT
            assert sockets_panel.menu.entry_states[HEALTH] == want, (port, want)
        panel = watch_linked()
        assert app.pages["tools"].current() == "tcphealth", "the tool is put on screen"
        assert watched == [LINKED], ("counting turned on for that one", watched)
        cells = health_cells(panel.table.items[0])
        assert cells == ("chrome.exe", "[fe80::1%12]:50001", "[fe80::5%12]:443",
                         T("tools.tcphealth.state.open"), "214 ms", "0 B"), cells
        assert panel.table.selected_keys() == [th.key_of(LINKED)], "and chosen"
        rows = {d.key: d for d in panel.details.items}
        assert rows["srtt"].value == "214 ms" and rows["mss"].value == "1460 B", rows["srtt"]
        at = time.strftime("%H:%M:%S", time.localtime(panel.job.last["cycle"].finished))
        assert panel.status.label.cget("text") == T("tools.tcphealth.status", time=at)
        assert panel.admin_note is None, "an elevated window has nothing to explain"
    """))


def test_the_numbers_are_read_while_on_screen_or_in_the_background_and_never_after_the_end():
    """The owner's answer (2026-10-19): read while the tool is on screen by default,
    and also in the background when the box is ticked. An ended connection keeps its
    last numbers and is not asked about again - and the timer stops with it."""
    run_gui(TCPH + textwrap.dedent("""
        panel = watch_linked()
        assert readings == [], "the first run only turned counting on (and read once)"
        panel._tick()
        settle(panel)
        assert readings == [LINKED], "on screen: read"
        app.select_page("control")
        panel._tick()
        settle(panel)
        assert readings == [LINKED], "another page on screen: not read"
        panel.background.set(True)
        panel._background_ticked()
        assert panel.memory["background"] == "1"
        panel._tick()
        settle(panel)
        assert len(readings) == 2, "asked to keep reading in the background"
        ANSWER[0] = tcpestats.Reading(tcpestats.ENDED, code=1168)
        panel._tick()
        settle(panel)
        cells = health_cells(panel.table.items[0])
        assert cells[3] == T("tools.tcphealth.state.ended") and cells[4] == "214 ms", cells
        panel._tick()
        settle(panel)
        assert len(readings) == 3, "an ended connection is read no more"
        assert panel._timer is None, "and nothing is left to time"
    """))


def test_show_tcp_health_from_the_connections_page_looks_the_local_address_up():
    """A Connections row names no local address: it is looked up in the socket table
    on the tool's worker. Closed since the row was drawn: said in the log."""
    run_gui(TCPH + textwrap.dedent("""
        from beantester import portmap
        from beantester.gui.pages import conns
        table = [[SocketRow("TCP", 4, "192.0.2.10", 51000, "198.51.100.7", 443,
                            "ESTABLISHED", 7)]]
        portmap.socket_rows = lambda: (table[0], [])
        row = {"proc": "app.exe", "pid": 7, "proto": "TCP", "local_port": 51000,
               "remote_ip": "198.51.100.7", "remote_port": 443}
        assert conns.show_health(app, row) is True
        panel = health()
        settle(panel)
        found = Connection("192.0.2.10", 51000, "198.51.100.7", 443)
        assert [w.connection for w in panel.table.items] == [found]
        assert panel.table.selected_keys() == [th.key_of(found)], "the new one is chosen"
        table[0] = []
        conns.show_health(app, dict(row, local_port=51001))
        settle(panel)
        app._logview.drain()
        gone = T("tools.tcphealth.log_gone", address="198.51.100.7:443")
        assert any(gone in line for line in app._log_lines), app._log_lines[-3:]
        assert len(panel.table.items) == 1, "and nothing was added"
        assert conns.show_health(app, {"proto": "TCP"}) is False, "a row with no ports"
    """))


def test_connections_asked_in_quick_succession_all_reach_the_list():
    """A worker run waiting behind another is REPLACED by a newer one (ToolJob): asked
    while a run is out, a second run would wait and a third replace it - the second
    request lost. So requests wait on the list and go out together when the run
    that is out answers."""
    run_gui(TCPH + textwrap.dedent("""
        hold = threading.Event()
        def slow_watch(connection, system=None):
            hold.wait(5)
            return est_watch(connection)
        tcpestats.watch = slow_watch
        sockets_panel = open_sockets()
        settle(sockets_panel)
        select_port(sockets_panel, 50001)
        sockets_panel._health()
        panel = health()
        assert panel.job.busy()
        others = [Connection("192.0.2.10", port, "198.51.100.7", 2) for port in (1, 2)]
        for other in others:
            panel.ask(th.Request("b.exe", 9, connection=other))
        hold.set()
        settle(panel)
        assert sorted(watched) == sorted([LINKED, *others]), watched
        assert len(panel.table.items) == 3, [w.key for w in panel.table.items]
    """))


def test_without_administrator_rights_the_tool_says_why_and_the_list_outlives_a_rebuild():
    run_gui(TCPH + textwrap.dedent("""
        admin[0] = False
        ANSWER[0] = tcpestats.Reading(tcpestats.NEEDS_ADMIN, code=5)
        panel = watch_linked()
        assert panel.admin_note is not None
        assert panel.admin_note.cget("text") == T("tools.tcphealth.needs_admin")
        cells = health_cells(panel.table.items[0])
        assert cells[3] == T("tools.tcphealth.state.needs_admin") and cells[4] == "", cells
        assert panel._timer is None, "refused: nothing to read again"
        app._build_ui()
        app.select_page("tools")
        app.pages["tools"].select("tcphealth")
        again = health()
        assert again is not panel
        assert [w.key for w in again.table.items] == [th.key_of(LINKED)], "the list stays"
        again.stop()
        assert again.table.items == [], "taken off the list"
        assert "disabled" in again.copy_btn.state() and "disabled" in again.stop_btn.state()
    """))


def test_the_report_is_copied_and_the_far_end_goes_to_the_control_page():
    run_gui(TCPH + textwrap.dedent("""
        app.vars["dst_port"].set("443")
        panel = watch_linked()
        panel.copy_report()
        assert root.clipboard_get() == th.report(panel.list), root.clipboard_get()
        assert any(T("log.copied") in line and T("tools.tcphealth.report_logged") in line
                   for line in app._log_lines), app._log_lines[-3:]
        panel.details.select_keys(["remote"])
        panel.details_menu.limit()
        limited = (app.vars["dst_ip"].get(), app.vars["dst_port"].get())
        assert limited == ("fe80::5", "443"), ("the address, without its zone", limited)
    """))


def test_a_round_trip_not_measured_colours_its_row_on_the_list():
    """The details say for how long; the list says which connection - in the caution
    colour of the details' row (the owner's choice, 2026-10-19)."""
    run_gui(TCPH + textwrap.dedent("""
        panel = watch_linked()
        watch = panel.table.items[0]
        assert panel.table._tag_of(watch) == "", "measured: no colour"
        watch.measured_at -= 10
        watch.last = watch.last._replace(bytes_out=watch.last.bytes_out + 200)
        panel._show()
        assert panel.table._tag_of(watch) == "stale", panel.table._tag_of(watch)
        iid = next(iid for iid, key in zip(panel.table._slots, panel.table._slot_keys)
                   if key == str(watch.key))
        assert panel.table.tree.tags[iid] == ("stale",), ("drawn", panel.table.tree.tags[iid])
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
        from beantester.gui.theme import MENU_ENTRY_INERT, MENU_ENTRY_LIVE
        panel = open_ports()
        type_ports(panel, "8080")
        panel.check()
        settle(panel)
        menu = panel.menu
        for proto, named in (("TCP", True), ("UDP", False)):
            panel.table.select_keys([row(panel, 8080, proto).key])
            panel._show_menu(0, 0)
            for index in (2, 3):
                want = MENU_ENTRY_LIVE if named else MENU_ENTRY_INERT
                assert menu.entry_states[index] == want, (proto, index)
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


# -- network adapters ------------------------------------------------------------- #
# The system is stood in for at the logic's `read`: the real one asks Windows, whose
# adapters differ on every runner (and do not exist on the Linux one). The ranking
# and the details run for real on top of three made-up adapters. `gate` holds a
# read back for the tests that need one still running.
ADAPT = """
import threading, time
from beantester.i18n import T
from beantester.adapters import AdapterRow, AddressRow, Reading
from beantester.nettools import adapters as ad

def row(key, index, status=1, kind=6, addresses=(), gateways=(), dns=()):
    return AdapterRow(key, index, 0, key.title(), "", kind, status, "", 1500, None, None,
                      False, "", tuple(addresses), tuple(gateways), tuple(dns), "", None, None)

ROWS = [row("down", 21, status=2, kind=53),
        row("eth", 9, addresses=[AddressRow("192.168.1.5", 4, 24, 3, 3, 4)],
            gateways=["192.168.1.1"], dns=["fe80::53%9", "fec0:0:0:ffff::1%1"]),
        row("wifi", 12, kind=71)]
gate = threading.Event()
gate.set()
reads, supported = [], [True]

def fake_read(native=None):
    reads.append(1)
    gate.wait(5)
    return ad.Snapshot(ad.rank(Reading(tuple(ROWS), {4: 9, 6: 0})), time.time(), 2,
                       next(ad._MADE))

ad.read = fake_read
# The SYSTEM module, which the Tools page's gate (capabilities) and the tool's own
# logic both ask - so the Linux runner sees the tool, and a test can take it away.
from beantester import adapters as system_adapters, proxy as system_proxy
system_adapters.supported = lambda: supported[0]

# The proxy, read in the same job: never this machine's own settings in a test.
from beantester.nettools import proxy as px
from beantester.proxy import MachineProxy, UserProxy, Variable
from beantester.proxy import Reading as ProxyReading
NO_PROXY = ProxyReading(UserProxy(False, "", "", ""), "", MachineProxy("", ""), "", (), "")
SET_PROXY = ProxyReading(
    UserProxy(True, "", "http=192.0.2.10:8080;https=proxy.example.com:8443", "<local>"), "",
    MachineProxy("192.0.2.30:3128", ""), "",
    (Variable("HTTP_PROXY", "http://user:secret@192.0.2.40:8080", "user"),), "")
PROXY = [NO_PROXY]
proxy_reads = []

def fake_proxy_read(native=None):
    proxy_reads.append(1)
    return PROXY[0]

px.read = fake_proxy_read
system_proxy.supported = lambda: supported[0]

def open_adapters():
    app.select_page("tools")
    page = app.pages["tools"]
    page.select("adapters")
    return page.panels["adapters"]

def settle(panel):
    deadline = time.monotonic() + 5
    while panel.pending():
        assert time.monotonic() < deadline, "the worker never answered"
        time.sleep(0.01)

def shown(panel):
    return [a.key for a in panel.table.items]

def details(panel):
    return {d.key: d for d in panel.details.items}

def choose(panel, key):
    # what a click does: through the table's own route, so on_select is told
    panel.table._choose(shown(panel).index(key))
"""


def test_the_adapters_are_read_when_first_looked_at_and_the_way_out_comes_first():
    run_gui(ADAPT + START_UP + textwrap.dedent("""
        app.ui.set("tools_page", "adapters")
        app._build_ui()                  # the window, opening on a remembered tool
        assert "adapters" in app.pages["tools"].panels, "the remembered tool is built"
        opened_on_start_up()
        assert reads == [], "and reads nothing until it is on screen"

        panel = open_adapters()
        settle(panel)
        assert reads == [1] and proxy_reads == [1], (reads, proxy_reads)
        assert shown(panel) == ["proxy", "eth", "wifi", "down"], shown(panel)
        assert panel.table.selected_keys() == ["eth"], "the way out is chosen first"
        assert details(panel)["name"].value == "Eth"
        assert panel.table.items[3].up is False and panel.table._tag_of(
            panel.table.items[3]) == "down", "an adapter that is down is muted"
        from beantester.gui.toolbox.adapters import COLUMNS, render
        cells = dict(zip(COLUMNS, render(panel.table.items[1]), strict=True))
        assert cells == {"name": "Eth", "status": T("tools.adapters.status.up"),
                         "kind": T("tools.adapters.kind.ethernet"),
                         "ipv4": "192.168.1.5/24", "internet": "IPv4"}, cells
        cells = dict(zip(COLUMNS, render(panel.table.items[0]), strict=True))
        assert cells == {"name": T("tools.adapters.proxy.row"),
                         "status": T("tools.adapters.proxy.state.not_set"),
                         "kind": T("tools.adapters.kind.proxy"), "ipv4": "",
                         "internet": ""}, cells
        assert panel.table._tag_of(panel.table.items[0]) == "", "the proxy row is not muted"
        app._tick()
        panel.refresh()
        settle(panel)
        assert reads == [1], "after that, only Refresh reads"
        panel.read()
        settle(panel)
        assert reads == [1, 1], reads
    """))


def test_the_chosen_adapter_shows_its_details_and_outlives_a_refresh_and_a_rebuild():
    run_gui(ADAPT + textwrap.dedent("""
        panel = open_adapters()
        settle(panel)
        choose(panel, "wifi")
        assert details(panel)["name"].value == "Wifi", details(panel)["name"]
        panel.read()
        settle(panel)
        assert panel.table.selected_keys() == ["wifi"], "a refresh keeps the choice"
        assert details(panel)["name"].value == "Wifi"
        app._build_ui()
        again = open_adapters()
        assert again is not panel
        assert again.table.selected_keys() == ["wifi"], "so does a rebuild"
        assert details(again)["name"].value == "Wifi"
        assert reads == [1, 1], "a rebuild shows what the window read, it does not read again"
        # the chosen adapter is gone (unplugged): the way out takes its place
        ROWS.pop()
        again.read()
        settle(again)
        assert again.table.selected_keys() == ["eth"], again.table.selected_keys()
        assert details(again)["name"].value == "Eth"
    """))


def test_a_header_click_sorts_each_table_and_the_order_outlives_a_rebuild():
    run_gui(ADAPT + textwrap.dedent("""
        panel = open_adapters()
        settle(panel)
        panel.table._clicked("kind")
        assert shown(panel) == ["proxy", "eth", "down", "wifi"], "the proxy stays first"
        panel.table._clicked("kind")
        assert shown(panel) == ["proxy", "wifi", "down", "eth"], "reversed too"
        panel.table._clicked("kind")
        assert shown(panel) == ["proxy", "eth", "down", "wifi"], shown(panel)
        assert panel.table.selected_keys() == ["eth"], "sorting keeps the choice"
        items = [T(d.item.key) for d in panel.details.items]
        panel.details._clicked("item")
        assert [T(d.item.key) for d in panel.details.items] == sorted(
            items, key=str.casefold), "the details sort by what the cell says"
        app._build_ui()
        again = open_adapters()
        assert shown(again) == ["proxy", "eth", "down", "wifi"], shown(again)
        assert again.details.sort == {"col": "item", "reverse": False}, again.details.sort
        assert reads == [1], reads
    """))


def test_an_adapter_read_that_fails_says_why_and_keeps_the_rows_it_had():
    run_gui(ADAPT + textwrap.dedent("""
        panel = open_adapters()
        settle(panel)
        def refused(native=None):
            raise OSError("the adapter list refused on purpose")
        ad.read = refused
        panel.read()
        settle(panel)
        status = panel.status.label
        assert "refused on purpose" in status.cget("text"), status.cget("text")
        assert status.cget("style") == "Status.Bad.TLabel"
        assert shown(panel) == ["proxy", "eth", "wifi", "down"], "the last good rows stay"
        at = time.strftime("%H:%M:%S",
                           time.localtime(panel.job.value["read"].adapters.read_at))
        assert panel.note.cget("text") == T("tools.adapters.note_stale", time=at)
        ad.read = fake_read
        panel.read()
        settle(panel)
        assert panel.note.cget("text") == "", "a read that works clears the note"
    """), allow_faults=("on purpose",))


def test_a_first_read_that_fails_is_not_an_empty_list_and_is_not_retried_by_itself():
    run_gui(ADAPT + textwrap.dedent("""
        calls = []
        def refused(native=None):
            calls.append(1)
            raise ad.Unreadable("tools.adapters.error_not_ready", "answered 1228 on purpose")
        ad.read = refused
        panel = open_adapters()
        settle(panel)
        text = panel.status.label.cget("text")
        assert text == T("tools.common.failed", error=T("tools.adapters.error_not_ready")), text
        assert panel.table.items == []
        assert panel.table._empty_text == "tools.adapters.empty_failed", panel.table._empty_text
        assert "disabled" in panel.copy_btn.state(), "no rows, no report to copy"
        for _ in range(3):
            app._tick()
            panel.refresh()
        settle(panel)
        assert calls == [1], "a failed read waits for Refresh, not for the next tick"
    """), allow_faults=("on purpose",))


def test_a_rebuild_keeps_a_failed_read_and_hands_a_running_one_to_the_new_panel():
    """A language change after a failed first read, and another during a read."""
    run_gui(ADAPT + textwrap.dedent("""
        def refused(native=None):
            raise OSError("the adapter list refused on purpose")
        ad.read = refused
        panel = open_adapters()
        settle(panel)
        app._build_ui()
        again = open_adapters()
        assert "refused on purpose" in again.status.label.cget("text"), "the failure is kept"
        assert again.table._empty_text == "tools.adapters.empty_failed"

        ad.read = fake_read
        gate.clear()
        again.read()
        assert again.job.busy()
        app._build_ui()
        third = open_adapters()
        assert third.status.label.cget("text") == T("tools.common.working")
        assert "disabled" in third.refresh_btn.state(), "one read at a time"
        gate.set()
        settle(third)
        assert shown(third) == ["proxy", "eth", "wifi", "down"], shown(third)
        assert reads == [1], "the answer reached the new panel without asking again"
    """), allow_faults=("on purpose",))


def test_off_windows_the_tool_says_so_and_asks_nothing():
    """The page's shared panel, not the tool's: before it, this tab was two blank
    tables on Linux - its own sentence for the case was never drawn (measured
    2026-10-20, Ubuntu 26.04 and WSL)."""
    run_gui(ADAPT + textwrap.dedent("""
        from beantester.gui.pages import toolbox as page_mod
        supported[0] = False
        app._build_ui()
        panel = open_adapters()
        assert isinstance(panel, page_mod._NotHere), type(panel)
        app._tick()
        app.pages["tools"].refresh()
        assert reads == [] and proxy_reads == [], (reads, proxy_reads)
    """))


def test_the_details_menu_copies_a_value_and_limits_to_a_gateway_keeping_the_port():
    run_gui(ADAPT + textwrap.dedent("""
        from beantester.gui.theme import MENU_ENTRY_INERT, MENU_ENTRY_LIVE
        from beantester.gui.toolbox.details import DetailsMenu
        COPY_VALUE, LIMIT = DetailsMenu.COPY_VALUE, DetailsMenu.LIMIT
        app.vars["dst_port"].set("443")
        panel = open_adapters()
        settle(panel)
        details_menu = panel.details_menu
        menu = details_menu.menu
        for key, can_limit in (("gateway|0", True), ("dns|0", True), ("dns|1", False),
                               ("name", False)):
            panel.details.select_keys([key])
            details_menu.show(0, 0)
            assert menu.entry_states[COPY_VALUE] == MENU_ENTRY_LIVE, key
            want = MENU_ENTRY_LIVE if can_limit else MENU_ENTRY_INERT
            assert menu.entry_states[LIMIT] == want, (key, menu.entry_states[LIMIT])

        panel.details.select_keys(["dns|0"])
        details_menu.limit()
        assert app.vars["dst_ip"].get() == "fe80::53", "the address, without its zone"
        panel.details.select_keys(["gateway|0"])
        details_menu.limit()
        limited = (app.vars["dst_ip"].get(), app.vars["dst_port"].get())
        assert limited == ("192.168.1.1", "443"), ("the port stays", limited)
        assert any(T("tools.adapters.log_limited") in line for line in app._log_lines)
        panel.details.select_keys(["dns|1"])
        details_menu.limit()
        assert app.vars["dst_ip"].get() == "192.168.1.1", "a placeholder is not offered"

        panel.details.select_keys(["name"])
        details_menu.copy_value()
        assert root.clipboard_get() == "Eth", root.clipboard_get()
    """))


def test_the_adapters_report_is_copied_whole():
    run_gui(ADAPT + textwrap.dedent("""
        panel = open_adapters()
        settle(panel)
        panel.copy_report()
        known = panel.job.value["read"]
        want = ad.report(known.adapters) + chr(10) * 2 + px.report(known.proxy)
        assert root.clipboard_get() == want, root.clipboard_get()
        assert any(T("log.copied") in line and T("tools.adapters.report_logged") in line
                   for line in app._log_lines), app._log_lines[-3:]
    """))


def test_the_list_menu_copies_the_one_adapter_the_right_click_chose():
    """The owner's request (2026-10-19): everything about ONE adapter, in the report's
    words. A right click selects through the table's own write, which does not tell
    ``on_select`` - so the menu takes the choice itself, and the details below show
    the adapter that is copied."""
    run_gui(ADAPT + textwrap.dedent("""
        from beantester.gui.theme import MENU_ENTRY_LIVE
        from beantester.gui.toolbox.adapters import COPY_ADAPTER
        PROXY[0] = SET_PROXY
        panel = open_adapters()
        settle(panel)
        assert panel.table.selected_keys() == ["eth"]
        panel.table.select_keys(["wifi"])       # what a right click on "wifi" does
        panel._show_list_menu(0, 0)
        assert panel.list_menu.entry_states[COPY_ADAPTER] == MENU_ENTRY_LIVE
        assert details(panel)["name"].value == "Wifi", "the details follow the right click"
        panel._copy_adapter()
        known = panel.job.value["read"]
        wifi = next(a for a in known.adapters.adapters if a.key == "wifi")
        text = root.clipboard_get()
        assert text == ad.adapter_report(wifi, known.adapters.read_at), text
        assert text.split(chr(10))[1] == "Wifi", "that adapter, not the one chosen before"
        logged = T("tools.adapters.adapter_logged", name="Wifi")
        assert any(T("log.copied") in line and logged in line for line in app._log_lines)

        panel.table.select_keys(["proxy"])
        panel._show_list_menu(0, 0)
        panel._copy_adapter()
        assert root.clipboard_get() == px.report(known.proxy), root.clipboard_get()
        assert "secret" not in root.clipboard_get(), "a password is not copied either"
    """))


def test_the_proxy_row_comes_first_and_offers_its_address_like_a_gateway():
    """T-13 (the owner's choice of the rendered layouts, 2026-10-14): the proxy is the
    first row whatever the sort, its details reuse the table and the row menu, a
    password never reaches the screen, and a server given as a name is not offered."""
    run_gui(ADAPT + textwrap.dedent("""
        from beantester.gui.theme import MENU_ENTRY_INERT, MENU_ENTRY_LIVE
        from beantester.gui.toolbox.adapters import COLUMNS, render
        from beantester.gui.toolbox.details import DetailsMenu, render_detail
        LIMIT = DetailsMenu.LIMIT
        PROXY[0] = SET_PROXY
        app.vars["dst_port"].set("443")
        panel = open_adapters()
        settle(panel)
        cells = dict(zip(COLUMNS, render(panel.table.items[0]), strict=True))
        assert cells["status"] == T("tools.adapters.proxy.state.in_use"), cells
        assert cells["ipv4"] == "192.0.2.10", "the first server, as the list shows an address"
        assert panel.table.selected_keys() == ["eth"], "the way out is still chosen first"
        choose(panel, "proxy")
        rows = details(panel)
        assert list(rows) == ["detect", "script", "server|0", "server|1", "bypass",
                              "winhttp|0", "env|HTTP_PROXY"], list(rows)
        assert rows["env|HTTP_PROXY"].value == "http://***@192.0.2.40:8080", rows["env|HTTP_PROXY"]
        assert not any("secret" in cell for d in panel.details.items for cell in render_detail(d))
        menu = panel.details_menu
        for key, can_limit in (("server|0", True), ("server|1", False), ("winhttp|0", True),
                               ("env|HTTP_PROXY", True), ("detect", False)):
            panel.details.select_keys([key])
            menu.show(0, 0)
            want = MENU_ENTRY_LIVE if can_limit else MENU_ENTRY_INERT
            assert menu.menu.entry_states[LIMIT] == want, (key, menu.menu.entry_states[LIMIT])
        panel.details.select_keys(["server|0"])
        menu.limit()
        limited = (app.vars["dst_ip"].get(), app.vars["dst_port"].get())
        assert limited == ("192.0.2.10", "443"), ("the proxy's address, the port stays", limited)
        panel.read()
        settle(panel)
        assert panel.table.selected_keys() == ["proxy"], "a refresh keeps the proxy chosen"
        app._build_ui()
        again = open_adapters()
        assert again.table.selected_keys() == ["proxy"], "so does a rebuild"
        assert "server|0" in details(again)
    """))


def test_a_proxy_that_cannot_be_read_says_so_and_the_adapters_stay():
    run_gui(ADAPT + textwrap.dedent("""
        PROXY[0] = ProxyReading(None, "OSError: refused on purpose", MachineProxy("", ""), "",
                                (), "")
        panel = open_adapters()
        settle(panel)
        assert shown(panel) == ["proxy", "eth", "wifi", "down"], shown(panel)
        from beantester.gui.toolbox.adapters import render
        assert render(panel.table.items[0])[1] == T("tools.adapters.proxy.state.unreadable")
        choose(panel, "proxy")
        row = details(panel)["user"]
        assert row.note == ("OSError: refused on purpose",), row
    """))


def test_the_environment_report_adds_the_adapters_only_when_ticked():
    """Off until ticked, and kept across a rebuild like every tool's input. The boxes
    are offered whatever the system (a Linux runner has no Adapters tool): the tick
    is the question here, the greyed-out box is
    ``test_diagnostics_on_linux_speaks_of_linux_and_greys_out_what_it_cannot_read``'s."""
    run_gui(DIAG + textwrap.dedent("""
        from beantester import capabilities
        from beantester.gui.toolbox.diagnostics import OPTIONAL_BOXES
        for spec in OPTIONAL_BOXES:
            capabilities.CAPABILITIES[spec.needs].module.supported = lambda: True
        blank = chr(10) * 2
        panel = open_diag()
        settle(panel)
        assert panel.include["adapters"].get() is False, "off until ticked"
        assert panel.include["proxy"].get() is False, "the proxy too, a box of its own"
        panel.copy_report()
        text = root.clipboard_get()
        assert "network adapters" not in text and "proxy" not in text, text
        panel.include["adapters"].set(True)
        panel._ticked()
        panel.copy_report()
        last = root.clipboard_get().split(blank)[-1]
        assert last.startswith("network adapters"), last
        panel.include["proxy"].set(True)
        panel._ticked()
        panel.copy_report()
        last = root.clipboard_get().split(blank)[-1]
        assert last.startswith("proxy"), last
        app._build_ui()
        again = open_diag()
        assert again.include["adapters"].get() is True, "the tick outlives a rebuild"
        assert again.include["proxy"].get() is True
    """))


# -- ping ---------------------------------------------------------------------------- #
# Nothing is sent: `ping.send` and the name lookup are stood in for, and `ping_gate`
# holds a request back for the tests that need one still out - its own name, since
# SOCK's `fake_read` waits on `gate`. The fake Tk fires no timer, so a test asks for
# the next request itself (`runner._send()`), the way the run's timer would, and
# `answered` collects what the worker said.
PING = SOCK + """
import threading
from beantester import icmp
from beantester.nettools import ping as pg
from beantester.gui.toolbox import ping as pp

sent, looked, sizes = [], [], []
ANSWERS = []
ping_gate = threading.Event()
ping_gate.set()

def fake_send(target, wait_s, system=None, size=32):
    ping_gate.wait(5)
    sent.append((target.address, wait_s))
    sizes.append(size)
    return ANSWERS.pop(0) if ANSWERS else icmp.Echo(0, 201, 64, target.address)

def fake_lookup(name):
    looked.append(name)
    return [(2, 1, 0, "", ("192.0.2.10", 0))]

pg.send = fake_send
pg._lookup = fake_lookup
icmp.supported = lambda: True      # the Linux runner too (capabilities)
# ...and built again: the window built the Tools page's first tab, Ping, at start -
# before the line above - and a page keeps the panel a tab got.
app._build_ui()

def open_ping():
    app.select_page("tools")
    page = app.pages["tools"]
    page.select("ping")
    return page.panels["ping"]

def answered(runner):
    deadline = time.monotonic() + 5
    while runner.poller.now():
        assert time.monotonic() < deadline, "the worker never answered"
        time.sleep(0.01)

def start(panel, text):
    panel.host.set(text)
    panel._start()
    answered(panel.runner)
"""


def test_ping_refuses_what_is_not_one_address_and_sends_nothing():
    """The promise is "to the address you type": a text that is not plainly an
    address or a host name never reaches the worker, the lookup or the wire."""
    run_gui(PING + textwrap.dedent("""
        panel = open_ping()
        for typed, key, args in (("999.1.1.1", "tools.ping.refused.bad_address",
                                  {"typed": "999.1.1.1"}),
                                 ("", "tools.ping.refused.empty", {}),
                                 ("224.0.0.1", "tools.ping.refused.not_one",
                                  {"typed": "224.0.0.1"})):
            panel.host.set(typed)
            panel._start()
            assert panel.status.label.cget("text") == T(key, **args), typed
            assert panel.status.label.cget("style") == "Status.Bad.TLabel"
        assert sent == [] and looked == [], (sent, looked)
        assert not panel.runner.running and panel.runner.run is None
        assert not panel.runner.job.busy(), "nothing was asked of the worker"
    """))


def test_a_ping_runs_from_start_to_stop_one_row_per_answer():
    run_gui(PING + textwrap.dedent("""
        from beantester.gui.toolbox.ping import render
        panel = open_ping()
        start(panel, "192.0.2.10")
        runner = panel.runner
        assert sent == [("192.0.2.10", 4)], ("the default wait is ping.exe's 4 s", sent)
        assert runner.running and panel.start_btn.cget("text") == T("tools.ping.stop")
        assert "disabled" in panel.entry.states, "the address cannot change mid-run"
        assert "disabled" in panel.every_box.states and "disabled" in panel.wait_box.states
        ANSWERS.append(icmp.Echo(icmp.IP_REQ_TIMED_OUT))
        runner._send()                   # what the run's timer does
        answered(runner)
        runner._send()
        answered(runner)
        rows = panel.table.items
        assert [r.seq for r in rows] == [3, 2, 1], "the newest on top"
        assert rows[1].kind == "lost", "the row's colour is its kind (PING_COLORS)"
        cells = render(rows[0], runner.run.target)
        assert cells[2:] == ("201 ms", 64, T("tools.ping.result.reply")), cells
        assert render(rows[1], runner.run.target)[2:] == ("", "", T("tools.ping.result.lost"))
        summary = panel.summary.cget("text")
        assert summary.startswith(T("tools.ping.summary", sent=3, replies=2, lost=1,
                                    pct="33.3")), summary
        assert T("tools.ping.summary_rtt", low="201", avg="201", high="201", jitter="< 1",
                 p95="201") in summary, summary
        panel._start_or_stop()           # Stop
        assert not runner.running and panel.start_btn.cget("text") == T("tools.ping.start")
        assert "disabled" not in panel.entry.states
        runner._send()                   # a timer that fired after Stop sends nothing
        assert not runner.job.busy() and len(sent) == 3, sent
        assert "disabled" not in panel.copy_btn.states
        panel.copy_report()
        assert root.clipboard_get().startswith("Ping 192.0.2.10: 32 bytes every 1 s"), \
            root.clipboard_get()
    """))


def test_a_name_is_looked_up_once_and_the_address_it_gave_is_shown():
    run_gui(PING + textwrap.dedent("""
        panel = open_ping()
        start(panel, "Example.com")
        panel.runner._send()
        answered(panel.runner)
        assert looked == ["example.com"], ("once, at Start", looked)
        assert [a for a, _w in sent] == ["192.0.2.10", "192.0.2.10"], sent
        named = T("tools.ping.named", name="Example.com", address="192.0.2.10")
        assert named in panel.status.label.cget("text"), panel.status.label.cget("text")

        def nowhere(name):
            looked.append(name)
            return []
        pg._lookup = nowhere
        panel._start_or_stop()
        start(panel, "nowhere.example")
        assert not panel.runner.running, "no address, so the run ends where it began"
        assert panel.status.label.cget("text") == T("tools.ping.refused.not_found",
                                                    name="nowhere.example")
        assert len(sent) == 2, "and nothing was sent for it"
    """))


def test_the_ping_goes_on_behind_another_page_and_across_a_rebuild():
    """The scene it is for: Start, go to Control, change the latency, come back."""
    run_gui(PING + textwrap.dedent("""
        panel = open_ping()
        start(panel, "192.0.2.10")
        runner = panel.runner
        app.select_page("control")
        runner._send()
        answered(runner)
        assert runner.run.sent == 2, "pinged with another page in front"
        app._build_ui()                  # a language change
        assert pp.window_run(app) is runner and runner.running, "the run is the window's"
        runner._send()
        answered(runner)
        again = open_ping()
        again.refresh()
        assert [r.seq for r in again.table.items] == [3, 2, 1], "all of it, on the new panel"
        assert again.start_btn.cget("text") == T("tools.ping.stop")
    """))


def test_the_session_line_says_what_the_engine_did_to_these_pings():
    """From the engine's own log of what it captured and impaired - never guessed."""
    run_gui(PING + textwrap.dedent("""
        panel = open_ping()
        asked, verdict = [], [True]
        app.engine.flow_scope = lambda key: (asked.append(key), verdict[0])[1]
        start(panel, "192.0.2.10")
        assert panel.session.cget("text") == T("tools.ping.session.none"), "no session"
        assert asked == [], "and the log is not asked without one"
        app.running = True
        for value, key in ((True, "impaired"), (False, "outside"), (None, "not_captured")):
            verdict[0] = value
            panel.runner._send()
            answered(panel.runner)
            assert panel.session.cget("text") == T("tools.ping.session." + key), value
        assert asked[-1] == ("ICMP", "192.0.2.10"), asked
        app.running = False
    """))


def test_an_answer_for_a_replaced_run_is_dropped():
    """A request of the old run still out when Start is pressed again: its answer
    arrives first (the worker delivers it before the new run's first request starts)
    and belongs to nobody on screen."""
    run_gui(PING + textwrap.dedent("""
        panel = open_ping()
        ping_gate.clear()
        panel.host.set("192.0.2.10")
        panel._start()                   # held back on the worker
        old = panel.runner.run
        panel._start_or_stop()           # Stop
        panel.host.set("198.51.100.7")
        panel._start()                   # the new run's first request waits behind it
        ping_gate.set()
        answered(panel.runner)
        answered(panel.runner)
        assert panel.runner.run is not old and old.sent == 0, "the old answer was dropped"
        assert [r.echo.reply_from for r in panel.runner.run.results] == ["198.51.100.7"]
    """))


def test_nothing_is_sent_after_stop_even_by_a_request_asked_for_before_it():
    """README, "Tools": echo requests from Start to Stop. A name lookup can take
    seconds, and a request can wait for the worker behind the last one of an old run:
    Stop pressed meanwhile, no echo goes out once they are over."""
    run_gui(PING + textwrap.dedent("""
        held = threading.Event()

        def slow_lookup(name):
            held.wait(5)
            looked.append(name)
            return [(2, 1, 0, "", ("192.0.2.10", 0))]
        pg._lookup = slow_lookup
        panel = open_ping()
        panel.host.set("example.com")
        panel._start()                   # the lookup is held on the worker
        panel._start_or_stop()           # Stop, before it answers
        held.set()
        answered(panel.runner)
        assert looked == ["example.com"] and sent == [], ("no echo after Stop", sent)
        assert not panel.runner.running and panel.runner.run.sent == 0
        assert panel.start_btn.cget("text") == T("tools.ping.start")

        ping_gate.clear()
        panel.host.set("192.0.2.10")
        panel._start()                   # out, its answer held
        panel._start_or_stop()           # Stop
        panel.host.set("198.51.100.7")
        panel._start()                   # waits behind it for the worker
        panel._start_or_stop()           # Stop, before its turn
        ping_gate.set()
        answered(panel.runner)
        assert [a for a, _w in sent] == ["192.0.2.10"], ("only the one out before Stop", sent)
        assert panel.runner.run.sent == 0 and not panel.runner.running

        sent.clear()
        held.clear()
        panel.host.set("example.com")
        panel._start()                   # the lookup is held again
        panel.ping("198.51.100.7")       # "Ping this address" replaces the run meanwhile
        held.set()
        answered(panel.runner)
        assert [a for a, _w in sent] == ["198.51.100.7"], ("not the replaced run's", sent)
    """))


def test_ping_sends_the_size_typed_and_stops_by_itself_after_the_number_chosen():
    run_gui(PING + textwrap.dedent("""
        panel = open_ping()
        panel.host.set("192.0.2.10")
        panel.size.set("70000")
        panel._start()
        assert panel.status.label.cget("text") == T("tools.ping.refused.size", typed="70000",
                                                    most=65500), panel.status.label.cget("text")
        assert sent == [] and not panel.runner.running, "a size refused sends nothing"
        panel.size.set("1372")
        panel.count = lambda: 3              # the "Pings" box set to a number
        start(panel, "192.0.2.10")
        runner = panel.runner
        assert sizes == [1372], ("the size typed reaches the request", sizes)
        assert "disabled" in panel.size_entry.states and "disabled" in panel.count_box.states
        for _ in range(2):
            runner._send()
            answered(runner)
        assert not runner.running and len(sent) == 3, ("done after the third", sent)
        at = time.strftime("%H:%M:%S", time.localtime(runner.stopped_at))
        assert panel.status.label.cget("text") == T("tools.ping.status_done", n=3,
                                                    target="192.0.2.10", time=at)
        runner._send()                       # a timer that fired after the last one
        assert not runner.job.busy() and len(sent) == 3, sent
        assert "disabled" not in panel.size_entry.states
    """))


def test_the_summary_splits_the_run_where_the_session_changed():
    """The scene the tool is for: ping, start a session, look. The line says the part
    since then and how it differs from before - not an average of both; a ping that was
    out while the session changed is in neither part."""
    run_gui(PING + textwrap.dedent("""
        marks = [None]
        app.engine.session_mark = lambda: marks[0]
        panel = open_ping()
        ANSWERS.extend([icmp.Echo(0, 1, 64, "192.0.2.10")] * 2)
        start(panel, "192.0.2.10")
        runner = panel.runner
        runner._send()
        answered(runner)
        assert panel.summary.cget("text").startswith(T("tools.ping.summary", sent=2, replies=2,
                                                       lost=0, pct="0.0"))
        marks[0] = (1, "START", "filter=ping, seed=1")
        for _ in range(2):                   # 201 ms: the fake's answer
            runner._send()
            answered(runner)
        part = runner.run.parts[-1]
        at = time.strftime("%H:%M:%S", time.localtime(part.started))
        text = panel.summary.cget("text")
        assert text.startswith(T("tools.ping.part.now", time=at, what=T("tools.ping.part.start"),
                                 sent=2, lost=0, pct="0.0")), text
        assert T("tools.ping.part.against", what=T("tools.ping.part.none"), d_rtt="+200",
                 d_loss="+0.0") in text, text
        assert runner.run.chart_changes() == [2], runner.run.chart_changes()
        assert panel._chart_drawn[-1] == (2,), "the chart is drawn with the change"
        ping_gate.clear()
        runner._send()                       # out...
        marks[0] = (2, "CHANGE", "latency 100 ms")
        ping_gate.set()                      # ...while the settings were applied
        answered(runner)
        assert not runner.run.results[-1].counted, "in no part"
        assert runner.run.parts[-1].stats.sent == 2, "and not in the part it went in"
    """))


def test_the_tab_says_above_the_tool_what_it_sends_and_only_there():
    run_gui(PING + textwrap.dedent("""
        page = app.pages["tools"]
        open_ping()
        said = [w.kw.get("text") for w in fake_tk.walk(page.tabs["ping"]) if w.kw.get("text")]
        assert T("tools.ping.sends") in said, "said above Ping"
        page.select("sockets")
        other = [w.kw.get("text") for w in fake_tk.walk(page.tabs["sockets"]) if w.kw.get("text")]
        assert T("tools.ping.sends") not in other, "and nowhere else"
    """))


def test_ping_this_address_from_the_socket_table_pings_its_far_end_with_its_zone():
    run_gui(PING + textwrap.dedent("""
        from beantester.gui.theme import MENU_ENTRY_INERT, MENU_ENTRY_LIVE
        from beantester.gui.toolbox.sockets import PING as PING_ENTRY
        sockets_panel = open_sockets()
        settle(sockets_panel)
        for port, offered in ((8080, False), (5353, False), (50001, True), (13882, True)):
            select_port(sockets_panel, port)
            sockets_panel._show_menu(0, 0)
            want = MENU_ENTRY_LIVE if offered else MENU_ENTRY_INERT
            assert sockets_panel.menu.entry_states[PING_ENTRY] == want, (port, want)
        select_port(sockets_panel, 50001)
        sockets_panel._ping()
        assert app.pages["tools"].current() == "ping", "the tool is put on screen"
        answered(pp.window_run(app))
        assert sent == [("fe80::5%12", 4)], ("the far end, with the zone it needs", sent)
    """))
