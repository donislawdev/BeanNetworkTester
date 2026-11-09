"""The Tools tab's registry: which tools exist, in which order, built by what.

The Tools PAGE (``gui/pages/toolbox.py``) is a renderer of these tables, the way the
main notebook renders ``pages.PAGES``: one tab per GROUP, and in each group one tab
per tool, in this order. A new tool is one module in this package and one line
below - and nothing else, because everything that walks the tabs reads them from
here: the page, the GUI render check in CI (``tools/ci_gui_render.py::surfaces``,
through the page's ``SUBPAGES``), the smoke test and ``tests/test_toolbox.py``.

The ``id`` is stored in ``ui.json`` (the tab that was open) and prefixes the tool's
i18n keys, so it is not renamed once shipped. The ORDER is free to change: the
remembered tab is found by id, never by position. A group is never stored: the
page finds it from the tool, so moving a tool to another group changes no file a
person has on disk.

Deliberately few fields: each comes with the first code that READS it (a flag
nothing reads is decoration nobody checks). ``group`` came just before the eighth
tool (2026-11-09). One row of tool tabs held seven, on the narrower sub-tabs
(``Sub.TNotebook`` in ``gui/theme.py``): in Polish on Linux it asked 678 px of 728
with Noto Sans and about 704 with DejaVu Sans (2026-10-26, a 760 px window, which is
also the narrowest it gets), and ``tools/ci_gui_render.py`` fails on a row of tabs
that does not fit. The groups say what a tool works on - the network, this computer,
this program - and the network group holds exactly the tools that send. It has no
default: a tool without a group would land on no tab at all.

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


class Group(NamedTuple):
    id: str             # stable within the code; never stored
    label: str          # i18n key of the group's tab


NETWORK, COMPUTER, PROGRAM = "network", "computer", "program"

# What a tool works on, in the order the tabs show (the owner chose these, 2026-11-09).
GROUPS = (
    Group(NETWORK, "tools.group.network"),
    Group(COMPUTER, "tools.group.computer"),
    Group(PROGRAM, "tools.group.program"),
)


class Tool(NamedTuple):
    id: str             # stable: ui.json and the i18n prefix tools.<id>.*
    label: str          # i18n key of the sub-tab
    factory: type       # the panel class: factory(app, parent) -> .frame
    group: str          # a GROUPS id; no default (see the module's docstring)
    sends: bool = False  # puts something on the network (see the module's docstring)
    needs: str = ""     # a capability (beantester/capabilities.py); "" = works everywhere


# The owner's order (2026-09-23), most useful to someone testing an application
# first: sockets, is-this-port-free, expression tester, adapters, diagnostics.
# Each tool takes its final place the day it lands: TCP health right after the
# sockets, whose row menu puts a connection on its list (the owner, 2026-10-19),
# and Ping first - it shows whether the session works at all (the owner, 2026-10-19).
# Within a group the tools keep that order.
TOOLS = (
    Tool(PingPanel.ID, PingPanel.LABEL, PingPanel, NETWORK, sends=True, needs="ping"),
    Tool(SocketsPanel.ID, SocketsPanel.LABEL, SocketsPanel, COMPUTER),
    Tool(TcpHealthPanel.ID, TcpHealthPanel.LABEL, TcpHealthPanel, COMPUTER,
         needs="tcp_health"),
    Tool(PortCheckPanel.ID, PortCheckPanel.LABEL, PortCheckPanel, COMPUTER),
    Tool(AdaptersPanel.ID, AdaptersPanel.LABEL, AdaptersPanel, COMPUTER, needs="adapters"),
    Tool(ExprTestPanel.ID, ExprTestPanel.LABEL, ExprTestPanel, PROGRAM),
    Tool(DiagnosticsPanel.ID, DiagnosticsPanel.LABEL, DiagnosticsPanel, PROGRAM),
)

TOOL_BY_ID = {tool.id: tool for tool in TOOLS}


def tools_in(group_id, tools=None):
    """The tools of one group, in the registry's order."""
    return tuple(tool for tool in (TOOLS if tools is None else tools) if tool.group == group_id)


__all__ = ["COMPUTER", "GROUPS", "Group", "NETWORK", "PROGRAM", "TOOLS", "TOOL_BY_ID",
           "Tool", "tools_in"]
