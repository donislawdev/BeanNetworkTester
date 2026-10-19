"""Tools tab: network adapters and the proxy. The rows and the report are made in
``nettools/adapters.py`` and ``nettools/proxy.py``.

"Which adapter does my traffic leave through, which address does it have, which
gateway and DNS server does it use?" - asked before a test is set up, and asked
again when a VPN or a virtual switch is in the way. What ``ipconfig /all`` prints,
as two tables: every adapter above (the one the internet goes through first, then
the ones that are up), and the chosen adapter's details below.

The proxy is the first row of the list, whatever the sort (the owner's choice of
the two rendered layouts, 2026-10-14): "which way does my traffic go" is the same
question, and its details reuse the table and the row menu below - a program that
uses a proxy connects to IT, so its address is offered to the Control page like a
gateway's.

A snapshot, read when the tab is first looked at and then when asked - the
pattern of the socket table: a list that re-read itself on every tick would move
under the pointer. Windows only (the owner's decision, 2026-09-24): elsewhere the
tab says so in one line.

The chosen adapter is remembered by the name the system keeps for it
(``AdapterName``), not by its index: Learn says an index may change when an
adapter is disabled and enabled again, and the details would then belong to
another one.
"""
import time
import tkinter as tk
from tkinter import ttk
from typing import NamedTuple

from ...i18n import T
from ...nettools import adapters, proxy
from .. import dialogs
from ..clipboard import copy_confirmed
from ..field_actions import fill_field
from ..theme import ADAPTER_COLORS, CHARS, ROWS, set_menu_entry_available, space, style_menu
from ..tooltip import add_tooltip
from ..widgets import SortableTree
from .base import Poller, StatusLine, job, remembered
from ... import crashlog

AREA = "gui.toolbox.adapters"

COLUMNS = {"name": "tools.adapters.col.name", "status": "tools.adapters.col.status",
           "kind": "tools.adapters.col.kind", "ipv4": "tools.adapters.col.ipv4",
           "internet": "tools.adapters.col.internet"}
TIPS = {column: f"tips.tools_adapters_col_{column}" for column in COLUMNS}
MIN_CHARS = {"name": CHARS["adapter"], "status": CHARS["if_status"],
             "kind": CHARS["if_kind"], "ipv4": CHARS["address"],
             "internet": CHARS["internet"]}

DETAIL_COLUMNS = {"item": "tools.adapters.col.item", "value": "tools.adapters.col.value",
                  "note": "tools.adapters.col.note"}
DETAIL_TIPS = {column: f"tips.tools_adapters_col_{column}" for column in DETAIL_COLUMNS}
DETAIL_MIN_CHARS = {"item": CHARS["item"], "value": CHARS["address"], "note": CHARS["note"]}

READ = "read"

# Entries of the details menu, by position: "Copy value" and "Limit to this address".
COPY_VALUE, LIMIT = 0, 1
# The list's menu: "Copy all of this adapter's details" (the owner's request, 2026-10-19).
COPY_ADAPTER = 0


def say(part):
    """A cell's text: ``Words`` in the window's language, anything else as it is."""
    if isinstance(part, adapters.Words):
        return T(part.key, code=part.code)
    return "" if part is None else str(part)


class Read(NamedTuple):
    """One Refresh: the adapters and the proxy, read together on the worker."""
    adapters: object            # nettools.adapters.Snapshot
    proxy: object               # proxy.Reading; None where it is not read


def read_all():
    """The adapters and, where supported, the proxy. ONE job, so a second Refresh
    cannot drop half of it (the worker keeps only the newest request), and the proxy
    read never raises - it cannot cost the adapter list."""
    return Read(adapters.read(), proxy.read() if proxy.supported() else None)


class ProxyEntry(NamedTuple):
    """The proxy as a row of the adapter list."""
    reading: object
    key: str = "proxy"
    up: bool = True


def render(adapter):
    """One adapter's cells, in ``COLUMNS`` order."""
    if isinstance(adapter, ProxyEntry):
        return (T("tools.adapters.proxy.row"), say(proxy.state_words(adapter.reading)),
                T("tools.adapters.kind.proxy"), proxy.first_server(adapter.reading), "")
    row = adapter.row
    return (row.name, say(adapters.status_words(row.status)),
            say(adapters.kind_words(row.kind)), adapter.first_ipv4(),
            ", ".join(f"IPv{v}" for v in adapter.internet))


def adapter_tag(adapter):
    return "" if adapter.up else "down"


def render_detail(detail):
    return (say(detail.item), say(detail.value), ", ".join(say(w) for w in detail.note))


class AdaptersPanel:
    ID = "adapters"
    LABEL = "tools.adapters.tab"

    def __init__(self, app, parent):
        self.app = app
        self.job = job(app, self.ID)
        self.memory = remembered(app, self.ID)
        self.frame = ttk.Frame(parent)
        # Asked once: the platform does not change while the program runs.
        self.supported = adapters.supported()

        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        self.refresh_btn = self._button(bar, "tools.adapters.refresh",
                                        "tips.tools_adapters_refresh", self.read)
        self.copy_btn = self._button(bar, "tools.adapters.copy_report",
                                     "tips.tools_adapters_copy", self.copy_report)
        dialogs.help_button(bar, app.root, "tools.adapters.help_title",
                            "tools.adapters.help_body",
                            "tips.tools_adapters_help").pack(side="right")
        # How old the rows on screen are, after a read that failed. In the bar, where
        # the socket table keeps its row count, and not on a line of its own: the
        # two tables need the height, and the line would stand empty after every
        # read that worked.
        self.note = ttk.Label(bar, text="", style="Muted.TLabel")
        self.note.pack(side="right", padx=(0, space("inline")))

        self.status = StatusLine(self.frame)
        self.status.label.pack(fill="x", padx=space("page"), pady=(space("row"), 0))

        # The list above keeps its few rows and no sideways scrollbar - its five
        # columns fit the narrowest window - so the details below get the height.
        top = ttk.Frame(self.frame)
        top.pack(fill="x", padx=space("page"), pady=(space("tight"), 0))
        self.table = SortableTree(
            top, COLUMNS, sort=self._sort("sort"), on_sort=self._on_sort,
            height=ROWS["adapters"], min_chars=MIN_CHARS, tips=TIPS, tags=ADAPTER_COLORS,
            selectmode="browse", empty_text="tools.common.working" if self.supported
            else "tools.adapters.windows_only")
        self.table.bind_select(self._on_select)
        bottom = ttk.Frame(self.frame)
        bottom.pack(fill="both", expand=True, padx=space("page"),
                    pady=(space("row"), space("page")))
        self.details = SortableTree(
            bottom, DETAIL_COLUMNS, sort=self._sort("detail_sort"),
            on_sort=self._on_detail_sort, height=ROWS["details"], horizontal=True,
            min_chars=DETAIL_MIN_CHARS, tips=DETAIL_TIPS, tags=ADAPTER_COLORS,
            selectmode="browse", empty_text="tools.adapters.empty_details")
        self._build_menu()

        self.poller = Poller(self.frame, self.job, self._on_outcome)
        # What this window already knows is shown as it is. The FIRST read waits for
        # the tab to be on screen (refresh / pending), as the socket table's does.
        known = self.job.value.get(READ)
        if known is not None:
            self._show(known)
        last = self.job.last.get(READ)
        if last is not None:
            self.status.show(last)
            if last.error:
                self._show_failure()
        if self.job.busy():
            self.status.working()
            self.poller.start()
        self._sync_buttons()

    # -- building ------------------------------------------------------------ #
    @staticmethod
    def _button(bar, text_key, tip_key, command):
        button = ttk.Button(bar, text=T(text_key), command=command)
        button.pack(side="left", padx=(0, space("inline")))
        add_tooltip(button, tip_key)
        return button

    def _build_menu(self):
        self.menu = style_menu(tk.Menu(self.frame, tearoff=0))
        self.menu.add_command(label=T("menu.copy_value"), command=self._copy_value)
        self.menu.add_command(label=T("tools.adapters.limit"), command=self._limit)
        self.details.bind_row_menu(self._show_menu)
        self.list_menu = style_menu(tk.Menu(self.frame, tearoff=0))
        self.list_menu.add_command(label=T("tools.adapters.copy_adapter"),
                                   command=self._copy_adapter)
        self.table.bind_row_menu(self._show_list_menu)

    # -- the page calls ------------------------------------------------------ #
    def refresh(self):
        """The tick, while this tab is on screen: the first look reads."""
        self._read_if_never()
        self._sync_buttons()

    def pending(self):
        """Take an answer that has arrived, and say whether one is still due."""
        self._read_if_never()
        return self.poller.now()

    def teardown(self):
        self.poller.cancel()

    # -- asking -------------------------------------------------------------- #
    def read(self):
        """Read the adapters and the proxy again (the Refresh button)."""
        if self.supported and not self.job.busy():
            self.job.run(READ, read_all)
            self.status.working()
            self._sync_buttons()
            self.poller.start()

    def _read_if_never(self):
        # Not after a read that failed: that says so, and waits for Refresh rather
        # than asking the system again on every tick.
        if READ not in self.job.last:
            self.read()

    def copy_report(self):
        known = self.job.value.get(READ)
        if known is not None:
            text = adapters.report(known.adapters)
            if known.proxy is not None:
                text += "\n\n" + proxy.report(known.proxy)
            copy_confirmed(self.app, text, T("tools.adapters.report_logged"), AREA)

    # -- sorting: kept per window, like the socket table's ------------------- #
    def _sort(self, name):
        """``{"col", "reverse"}`` remembered under ``name``. The column "" is the
        model's own order - the ranking above, the property order below - and puts
        an arrow on no header."""
        return {"col": self.memory.get(name, adapters.RANKED),
                "reverse": bool(self.memory.get(name + "_reverse", ""))}

    def _remember_sort(self, name, sort):
        self.memory[name] = sort["col"]
        self.memory[name + "_reverse"] = "1" if sort["reverse"] else ""

    def _on_sort(self, sort):
        self._remember_sort("sort", sort)
        known = self.job.value.get(READ)
        if known is not None:
            self._show(known)

    def _on_detail_sort(self, sort):
        self._remember_sort("detail_sort", sort)
        self._show_details()

    # -- answers ------------------------------------------------------------- #
    def _on_outcome(self, outcome):
        self.status.show(outcome)
        if outcome.error:
            self._show_failure()
        else:
            self.note.config(text="")
            self._show(outcome.value)
        self._sync_buttons()

    def _show(self, known):
        snapshot = known.adapters
        sort = self._sort("sort")
        rows = adapters.sort(snapshot.adapters, sort["col"], sort["reverse"])
        if known.proxy is not None:
            rows = [ProxyEntry(known.proxy), *rows]     # first, whatever the sort
        self.table.set_empty_text("tools.adapters.empty")
        self.table.set_model(rows, render=render, key_of=lambda a: a.key, tag_of=adapter_tag)
        # The adapter chosen before is chosen again; one that is gone gives way to
        # the top of the ranking - the adapter the internet goes through, not the
        # proxy row above it. The keys come from the ROWS, the proxy's among them.
        keys = {a.key for a in rows}
        chosen = self.memory.get("adapter")
        if chosen not in keys:
            chosen = snapshot.adapters[0].key if snapshot.adapters else None
        self.memory["adapter"] = chosen
        self.table.select_keys([chosen] if chosen else [])
        self._show_details()

    def _on_select(self):
        """A person chose another adapter: its details below."""
        keys = self.table.selected_keys()
        if keys:
            self.memory["adapter"] = keys[0]
            self._show_details()

    def _chosen(self):
        key = self.memory.get("adapter")
        return self.table.item_for_key(key) if key else None

    def _show_details(self):
        adapter = self._chosen()
        if isinstance(adapter, ProxyEntry):
            rows = proxy.details(adapter.reading)
        else:
            rows = adapters.details(adapter) if adapter is not None else []
        sort = self._sort("detail_sort")
        column = sort["col"]
        if column in DETAIL_COLUMNS:
            # Sorted by what the cell SAYS, in the window's language - a few dozen
            # rows, so on this thread. Until a header is clicked: the property order.
            at = list(DETAIL_COLUMNS).index(column)
            rows.sort(key=lambda d: render_detail(d)[at].casefold(), reverse=sort["reverse"])
        self.details.set_model(rows, render=render_detail, key_of=lambda d: d.key,
                               tag_of=lambda d: d.tag)

    def _show_failure(self):
        """The read failed: say so, and keep the last good rows with their age."""
        known = self.job.value.get(READ)
        if known is None:
            self.table.set_empty_text("tools.adapters.empty_failed")
            self.table.set_model([], render=render, key_of=lambda a: a.key)
            self._show_details()
            return
        at = time.strftime("%H:%M:%S", time.localtime(known.adapters.read_at))
        self.note.config(text=T("tools.adapters.note_stale", time=at))

    def _sync_buttons(self):
        can_read = self.supported and not self.job.busy()
        self.refresh_btn.state(["!disabled"] if can_read else ["disabled"])
        has_rows = self.job.value.get(READ) is not None
        self.copy_btn.state(["!disabled"] if has_rows else ["disabled"])

    # -- the menus ---------------------------------------------------------- #
    @staticmethod
    def _popup(menu, allowed, x_root, y_root):
        for index, available in allowed.items():
            with crashlog.quiet(AREA):
                set_menu_entry_available(menu, index, available)
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            with crashlog.quiet(AREA):
                menu.grab_release()

    def _show_list_menu(self, x_root, y_root):
        """The right click selected the row under the pointer, but the table does not
        report its own writes as a choice - so the choice is taken here, and the
        details below show the adapter the menu copies."""
        keys = self.table.selected_keys()
        if keys and keys[0] != self.memory.get("adapter"):
            self._on_select()
        self._popup(self.list_menu, {COPY_ADAPTER: self._chosen() is not None},
                    x_root, y_root)

    def _copy_adapter(self):
        """Everything about the chosen row in the report's words (the owner's choice,
        2026-10-19): the adapter's lines under the time they were read, or the proxy's."""
        known, chosen = self.job.value.get(READ), self._chosen()
        if known is None or chosen is None:
            return
        if isinstance(chosen, ProxyEntry):
            text, name = proxy.report(chosen.reading), T("tools.adapters.proxy.row")
        else:
            text = adapters.adapter_report(chosen, known.adapters.read_at)
            name = chosen.row.name
        copy_confirmed(self.app, text, T("tools.adapters.adapter_logged", name=name), AREA)

    def _selected_detail(self):
        keys = self.details.selected_keys()
        return self.details.item_for_key(keys[0]) if keys else None

    def _show_menu(self, x_root, y_root):
        detail = self._selected_detail()
        self._popup(self.menu, {COPY_VALUE: bool(detail and say(detail.value)),
                                LIMIT: bool(detail and detail.address)}, x_root, y_root)

    def _copy_value(self):
        detail = self._selected_detail()
        text = say(detail.value) if detail else ""
        if text:
            copy_confirmed(self.app, text, text, AREA)

    def _limit(self):
        """The gateway's, DNS server's or proxy's address into the Control page's
        destination field - the address only: the port the person set there stays
        (the owner's decision, 2026-10-13; ``set_destination`` would have emptied it)."""
        detail = self._selected_detail()
        if detail and detail.address:
            fill_field(self.app, "dst_ip", detail.address, "tools.adapters.log_limited")
