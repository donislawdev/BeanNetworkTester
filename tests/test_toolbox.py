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
