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
        page._on_subpage()                           # what <<NotebookTabChanged>> runs
        assert app.ui.get("tools_page") == "a", app.ui.get("tools_page")
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


def test_ctrl_f_on_the_tools_tab_goes_to_the_connection_search():
    """No tool has a search box yet, so Ctrl+F keeps doing what it did from any
    page without one: bring the connection table forward."""
    run_gui("""
        from beantester.gui.pages import focus_search
        app.select_page("tools")
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
    app.pages["tools"].select("diagnostics")
    return app.pages["tools"].panels["diagnostics"]

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
