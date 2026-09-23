"""Tools page: one sub-tab per tool of the registry in ``gui/toolbox``.

A DISPATCHER and nothing more. What a tool shows and does lives in its panel; this
page builds the tabs, decides which panel exists yet, and hands the page calls on
(``refresh``, ``teardown``, ``focus_search``, ``on_pref_changed``).

Three decisions carry this file, each paid for somewhere else first:

* **Panels are built on first view, and synchronously in ``select``.** Twenty tools
  must not cost twenty panels at start-up. And the GUI render check puts each
  sub-tab on screen with ``select`` and measures straight after
  (``tools/ci_gui_render.py::walk_surfaces``) - a panel waiting for
  ``<<NotebookTabChanged>>`` could be measured as an empty tab.
* **A tool can fail without taking anything else down.** ``App._tick`` runs the
  page refresh in ONE ``try`` with the summary bar, the secondary windows and the
  process map (``gui/app.py``), so an exception out of a panel would stop all of
  them and log an error every 700 ms. Every call into a panel goes through
  ``crashlog.quiet``; a panel whose constructor raises becomes a line saying so,
  once, instead of being retried on every look.
* **The tab that was open is remembered by id** (``ui.json``, ``tools_page``), so
  reordering the registry never reopens the wrong tool.
"""
import tkinter as tk
from tkinter import ttk

from ...i18n import T
from ..labels import wrapping_label
from ..theme import space
from ..toolbox import TOOL_BY_ID, TOOLS
from ... import crashlog

AREA = "gui.pages.toolbox"


class _Unavailable:
    """What a tab shows when its tool could not be built. It has no behaviour."""

    def __init__(self, parent):
        self.frame = wrapping_label(parent, T("tools.unavailable"),
                                    style="Status.Bad.TLabel")


class ToolboxPage:
    ID = "tools"
    LABEL = "app.tabs.tools"
    # Derived, never written out: the render check and the layout tests walk the
    # sub-tabs through this attribute, so a tool is covered the day it is added.
    SUBPAGES = tuple((tool.id, tool.label) for tool in TOOLS)

    def __init__(self, app, parent):
        self.app = app
        self.frame = ttk.Frame(parent)
        self.nb = ttk.Notebook(self.frame)
        self.nb.pack(fill="both", expand=True, pady=(space("tight"), 0))
        self.tabs = {}
        self.panels = {}            # tool id -> panel, only for tools already shown
        for tool in TOOLS:
            tab = ttk.Frame(self.nb)
            self.nb.add(tab, text=T(tool.label))
            self.tabs[tool.id] = tab
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._on_subpage())
        self.select(app.ui.get("tools_page", ""))

    # -- which tab ----------------------------------------------------------- #
    def current(self):
        try:
            return TOOLS[int(self.nb.index(self.nb.select()))].id
        except (tk.TclError, TypeError, ValueError, IndexError):
            # A notebook being torn down answers "" for its selection; the first
            # tool is the same answer `select` gives an id it does not know.
            return TOOLS[0].id

    def select(self, tool_id):
        """Show one tool, building its panel now if this is its first time.

        An id that is not in the registry (a tool removed since the file was
        written) opens the first tab, the way ``App.select_page`` treats an
        unknown page.
        """
        if tool_id not in TOOL_BY_ID:
            tool_id = TOOLS[0].id
        index = [tool.id for tool in TOOLS].index(tool_id)
        with crashlog.quiet(AREA):
            self.nb.select(index)
        self._ensure(tool_id)

    def _on_subpage(self):
        tool_id = self.current()
        self._ensure(tool_id)
        self.app.ui.set("tools_page", tool_id)
        self.refresh()

    def _ensure(self, tool_id):
        panel = self.panels.get(tool_id)
        if panel is not None:
            return panel
        tab = self.tabs[tool_id]
        try:
            panel = TOOL_BY_ID[tool_id].factory(self.app, tab)
            panel.frame.pack(fill="both", expand=True)
        except Exception as exc:
            crashlog.note(exc, AREA)
            # Whatever the panel managed to build before it failed would sit above
            # the message, half a tool pretending to work.
            with crashlog.quiet(AREA):
                for child in tab.winfo_children():
                    child.destroy()
            panel = _Unavailable(tab)
            panel.frame.pack(fill="both", expand=True)
        self.panels[tool_id] = panel
        return panel

    def _each(self, method, *args, panels=None):
        """Call ``method`` on the panels that have it, each on its own."""
        for panel in (self.panels.values() if panels is None else panels):
            handler = getattr(panel, method, None)
            if handler is None:
                continue
            with crashlog.quiet(AREA):
                handler(*args)

    # -- what App and the page registry call ---------------------------------- #
    def refresh(self):
        """The tick, for the tool on screen only - the others are not visible."""
        panel = self.panels.get(self.current())
        if panel is not None:
            self._each("refresh", panels=(panel,))

    def teardown(self):
        self._each("teardown")

    def on_pref_changed(self, key):
        self._each("on_pref_changed", key)

    def focus_search(self):
        """Ctrl+F: the search box of the tool on screen, if it has one.

        ``False`` sends the dispatcher on to the connection table
        (``gui/pages/__init__.py::focus_search``), which is what Ctrl+F did on
        this tab before any tool had a box of its own.
        """
        handler = getattr(self.panels.get(self.current()), "focus_search", None)
        if handler is None:
            return False
        with crashlog.quiet(AREA):
            return handler()
        return False
