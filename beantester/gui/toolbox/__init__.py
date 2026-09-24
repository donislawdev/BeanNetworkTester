"""The Tools tab's registry: which tools exist, in which order, built by what.

The Tools PAGE (``gui/pages/toolbox.py``) is a renderer of this table, the way the
main notebook renders ``pages.PAGES``: one sub-tab per entry, in this order. A new
tool is one module in this package and one line below - and nothing else, because
everything that walks the tabs reads them from here: the page, the GUI render
check in CI (``tools/ci_gui_render.py::surfaces``, through the page's
``SUBPAGES``), the smoke test and ``tests/test_toolbox.py``.

The ``id`` is stored in ``ui.json`` (the tab that was open) and prefixes the tool's
i18n keys, so it is not renamed once shipped. The ORDER is free to change: the
remembered tab is found by id, never by position.

Deliberately three fields. More were sketched - whether a tool sends packets,
which group it belongs to, whether it needs administrator rights - and each comes
with the first code that READS it (a flag nothing reads is decoration nobody
checks): sending with the first tool that sends, a group when the tabs stop
fitting (around seven) and the page starts rendering a tab per group instead.
"""
from typing import NamedTuple

from .diagnostics import DiagnosticsPanel
from .exprtest import ExprTestPanel
from .sockets import SocketsPanel


class Tool(NamedTuple):
    id: str             # stable: ui.json and the i18n prefix tools.<id>.*
    label: str          # i18n key of the sub-tab
    factory: type       # the panel class: factory(app, parent) -> .frame


# The owner's order (2026-09-23), most useful to someone testing an application
# first: sockets, is-this-port-free, expression tester, adapters, diagnostics.
# Each tool takes its final place the day it lands.
TOOLS = (
    Tool(SocketsPanel.ID, SocketsPanel.LABEL, SocketsPanel),
    Tool(ExprTestPanel.ID, ExprTestPanel.LABEL, ExprTestPanel),
    Tool(DiagnosticsPanel.ID, DiagnosticsPanel.LABEL, DiagnosticsPanel),
)

TOOL_BY_ID = {tool.id: tool for tool in TOOLS}

__all__ = ["TOOLS", "TOOL_BY_ID", "Tool"]
