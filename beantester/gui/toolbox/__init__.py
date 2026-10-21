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

Deliberately few fields. More were sketched - which group a tool belongs to,
whether it needs administrator rights - and each comes with the first code that
READS it (a flag nothing reads is decoration nobody checks): a group when the
tabs stop fitting and the page starts rendering a tab per group instead. With
Ping the strip holds seven, and in Polish it ends 15 px short of the window
(rendered 2026-10-19 at 760 px): an eighth tool needs the groups first.

``sends`` came with Ping, the first tool that sends anything (2026-10-19), and has
two readers. The page puts the tool's own sentence of what it sends
(``tools.<id>.sends``) above it. And ``tests/test_no_telemetry.py`` holds the README
promise to it: the tools marked here are the ones whose code may send, and the
promise names each of them.

``needs`` came with Linux (2026-10-20): the capability (``beantester/capabilities.py``)
a tool cannot work without, ``""`` for one that works everywhere. Its reader is the
page, which builds the tool's panel only where the system offers it and the shared
"not available on this system" panel everywhere else - so a panel never asks the
question itself. ``tests/test_capabilities.py`` checks each name against the
capabilities and each tool against the system modules its logic imports.
"""
from typing import NamedTuple

from .adapters import AdaptersPanel
from .diagnostics import DiagnosticsPanel
from .exprtest import ExprTestPanel
from .ping import PingPanel
from .portcheck import PortCheckPanel
from .sockets import SocketsPanel
from .tcphealth import TcpHealthPanel


class Tool(NamedTuple):
    id: str             # stable: ui.json and the i18n prefix tools.<id>.*
    label: str          # i18n key of the sub-tab
    factory: type       # the panel class: factory(app, parent) -> .frame
    sends: bool = False  # puts something on the network (see the module's docstring)
    needs: str = ""     # a capability (beantester/capabilities.py); "" = works everywhere


# The owner's order (2026-09-23), most useful to someone testing an application
# first: sockets, is-this-port-free, expression tester, adapters, diagnostics.
# Each tool takes its final place the day it lands: TCP health right after the
# sockets, whose row menu puts a connection on its list (the owner, 2026-10-19),
# and Ping first - it shows whether the session works at all (the owner, 2026-10-19).
TOOLS = (
    Tool(PingPanel.ID, PingPanel.LABEL, PingPanel, sends=True, needs="ping"),
    Tool(SocketsPanel.ID, SocketsPanel.LABEL, SocketsPanel),
    Tool(TcpHealthPanel.ID, TcpHealthPanel.LABEL, TcpHealthPanel, needs="tcp_health"),
    Tool(PortCheckPanel.ID, PortCheckPanel.LABEL, PortCheckPanel),
    Tool(ExprTestPanel.ID, ExprTestPanel.LABEL, ExprTestPanel),
    Tool(AdaptersPanel.ID, AdaptersPanel.LABEL, AdaptersPanel, needs="adapters"),
    Tool(DiagnosticsPanel.ID, DiagnosticsPanel.LABEL, DiagnosticsPanel),
)

TOOL_BY_ID = {tool.id: tool for tool in TOOLS}

__all__ = ["TOOLS", "TOOL_BY_ID", "Tool"]
