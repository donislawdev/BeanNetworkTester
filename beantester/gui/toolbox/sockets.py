"""Tools tab: sockets. The rows and the search are computed in ``nettools/sockets.py``.

Every TCP and UDP socket on the machine - listeners, open connections, the ones
closing - with its state and its process, without a session: the question "which
port does my application listen on?" comes BEFORE anything is impaired, and the
connection table only knows traffic that crossed the driver.

A snapshot, read when the tab is first looked at and then when asked (the owner's
decision, 2026-09-23): a table that re-read itself every tick would move under the
pointer, and at a hundred thousand sockets each read is a second of work.

One request at a time. The worker keeps only the LAST request that waits
(``gui/model_worker.py``), and a search queued behind a read would have been
computed on the table it was queued against - the old one - and shown after the
new. So nothing is queued: while the worker is busy the inputs are only
remembered, and each answer that lands is compared with them and asked again
when they moved (``_on_outcome``).
"""
import time
import tkinter as tk
from tkinter import ttk

from ...i18n import T
from ...nettools import sockets
from .. import dialogs
from ..field_actions import block_ip_address, leave_process_alone
from ..labels import wrapping_label
from ..theme import CHARS, ROWS, space, style_menu
from ..tooltip import add_tooltip
from ..widgets import SortableTree
from .base import Debounce, Poller, StatusLine, job, remembered
from ... import crashlog

AREA = "gui.toolbox.sockets"

# Column -> header key. The connection table's headers where the meaning is the
# same; the tooltips are this table's own - that table's speak of captured packets.
# The ORDER is the connection table's too, process first: the table scrolls
# sideways, and the first render (760 px) put PID and process - the answer to "who
# holds this port?" - past the right edge. The remote end, empty on every listener,
# goes last.
COLUMNS = {"proc": "conns.process", "pid": "conns.pid", "proto": "conns.proto",
           "local_ip": "tools.sockets.col.local_ip", "local_port": "conns.local_port",
           "state": "tools.sockets.col.state", "remote_ip": "conns.remote_ip",
           "remote_port": "conns.remote_port"}
TIPS = {column: f"tips.tools_sockets_col_{column}" for column in COLUMNS}
NUMERIC = frozenset({"local_port", "remote_port", "pid"})
# Centred for the connection table's reason: each follows a right-aligned number,
# and left-aligned it touched it - the first render read "22 LISTEN" as one value.
CENTERED = frozenset({"proto", "state"})
MIN_CHARS = {"proto": CHARS["proto"], "local_ip": CHARS["address"],
             "local_port": CHARS["port"], "remote_ip": CHARS["address"],
             "remote_port": CHARS["port"], "state": CHARS["tcp_state"],
             "pid": CHARS["pid"], "proc": CHARS["process"]}

READ, VIEW = "read", "view"

# Menu entries a row may be refused, by position (0 is "Copy", 1 the separator).
NEEDS_NAME = (2, 3)         # target / leave alone: the process's name
NEEDS_REMOTE = (4, 5)       # limit to / block: an address on the other end


def render(s):
    """One row's cells, in ``COLUMNS`` order. Called only for the rows on screen."""
    return (s.proc, "" if s.pid is None else s.pid, s.proto, s.local_ip, s.local_port,
            s.state, s.remote_ip, "" if s.remote_port is None else s.remote_port)


def address(s):
    """The remote address as a Control field takes it: without an IPv6 zone."""
    return s.remote_ip.split("%")[0]


class SocketsPanel:
    ID = "sockets"
    LABEL = "tools.sockets.tab"

    def __init__(self, app, parent):
        self.app = app
        self.job = job(app, self.ID)
        self.memory = remembered(app, self.ID)
        self.frame = ttk.Frame(parent)
        self.debounce = Debounce(self.frame, self._search)
        self.query = tk.StringVar(value=self.memory.get("query", ""))

        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        ttk.Label(bar, text=T("fields.search")).pack(side="left")
        self.entry = ttk.Entry(bar, textvariable=self.query, width=CHARS["search"])
        self.entry.pack(side="left", padx=(space("tight"), space("inline")))
        self.entry.bind("<KeyRelease>", self._typed)
        self.entry.bind("<Return>", self.debounce.now)
        self.entry.bind("<Escape>", self._clear)
        add_tooltip(self.entry, "tips.tools_sockets_search", shortcut="Ctrl+F")
        dialogs.help_button(bar, app.root, "tools.sockets.help_title",
                            "tools.sockets.help_body", "tips.tools_sockets_help").pack(
            side="left", padx=(0, space("inline")))
        self.refresh_btn = ttk.Button(bar, text=T("tools.sockets.refresh"), command=self.read)
        self.refresh_btn.pack(side="left")
        add_tooltip(self.refresh_btn, "tips.tools_sockets_refresh")
        self.count = ttk.Label(bar, text="", style="Muted.TLabel")
        self.count.pack(side="right")

        self.status = StatusLine(self.frame)
        self.status.label.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        # What the rows on screen are missing, or how old they are.
        self.note = wrapping_label(self.frame, "")
        self.note.pack(fill="x", padx=space("page"), pady=(space("hair"), 0))

        holder = ttk.Frame(self.frame)
        holder.pack(fill="both", expand=True, padx=space("page"),
                    pady=(space("tight"), space("page")))
        column, reverse = self._sort()
        self.table = SortableTree(holder, COLUMNS, sort={"col": column, "reverse": reverse},
                                  on_sort=self._on_sort, height=ROWS["table"],
                                  horizontal=True, min_chars=MIN_CHARS, tips=TIPS,
                                  numeric=NUMERIC, centered=CENTERED,
                                  empty_text="tools.common.working")
        self._build_menu()

        self.poller = Poller(self.frame, self.job, self._on_outcome)
        # What this window already knows is shown as it is. The FIRST read waits for
        # the tab to be on screen (refresh / pending): every page is built when the
        # window opens, and this tab's first tool with it.
        latest = self._latest()
        if latest is not None:
            self._show(latest)
        read = self.job.last.get(READ)
        if read is not None:
            self.status.show(read)
            if read.error:
                self._show_failure()
        if self.job.busy():
            self.status.working()
            self.poller.start()
        elif latest is not None and not self._answers_the_inputs(latest):
            # typed inside the pause before a rebuild: remembered, never searched
            self._ask(VIEW)
        self._sync_buttons()

    def _build_menu(self):
        self.menu = style_menu(tk.Menu(self.frame, tearoff=0))
        self.menu.add_command(label=T("menu.copy_row"), command=self._copy_rows)
        self.menu.add_separator()
        self.menu.add_command(label=T("menu.target_process"), command=self._target)
        self.menu.add_command(label=T("menu.leave_process_alone"), command=self._leave_alone)
        self.menu.add_command(label=T("menu.limit_dest"), command=self._limit)
        self.menu.add_command(label=T("menu.block_ip"), command=self._block)
        self.table.bind_row_menu(self._show_menu)

    # -- the page calls ------------------------------------------------------ #
    def refresh(self):
        """The tick, while this tab is on screen: the first look reads."""
        self._read_if_never()
        self._sync_buttons()

    def pending(self):
        """Take an answer that has arrived, and say whether one is still due.

        The GUI render check calls this until it says no - which is also a look at
        the tab, so it starts the first read the way a tick would.
        """
        self._read_if_never()
        return self.poller.now()

    def teardown(self):
        self.poller.cancel()
        self.debounce.cancel()

    def focus_search(self):
        """Ctrl+F while this tool is on screen: its own search box."""
        with crashlog.quiet(AREA):
            self.entry.focus_set()
            self.entry.select_range(0, "end")
        return "break"

    # -- asking -------------------------------------------------------------- #
    def read(self):
        """Read the machine again (the Refresh button)."""
        if not self.job.busy():
            self._ask(READ)

    def _read_if_never(self):
        # Not after a read that failed: that says so, and waits for Refresh rather
        # than asking the system again on every tick.
        if READ not in self.job.last and not self.job.busy():
            self._ask(READ)

    def _ask(self, kind):
        query, (column, reverse) = self.query.get(), self._sort()
        if kind == READ:
            self.job.run(READ, lambda: sockets.table(None, query, column, reverse))
            self.status.working()
        else:
            # Taken HERE, on the UI thread: the worker does not reach back into the
            # window (convention 26), and nothing reads while this runs.
            latest = self._latest()
            if latest is None:
                return
            snapshot = latest.snapshot
            self.job.run(VIEW, lambda: sockets.table(snapshot, query, column, reverse))
        self._sync_buttons()
        self.poller.start()

    def _asked_again(self):
        """A view for the inputs as they are now, unless one is on its way."""
        if not self.job.busy():
            self._ask(VIEW)

    def _typed(self, _event=None):
        # Remembered at every key, not when the pause runs out: a language change
        # inside that pause rebuilds the panel and would lose the last characters.
        self.memory["query"] = self.query.get()
        self.debounce()

    def _search(self):
        self.memory["query"] = self.query.get()
        self._asked_again()

    def _clear(self, _event=None):
        self.query.set("")
        self._typed()
        self.debounce.now()

    def _on_sort(self, sort):
        self.memory["sort"] = sort["col"]
        self.memory["reverse"] = "1" if sort["reverse"] else ""
        self._asked_again()

    def _sort(self):
        column = self.memory.get("sort", sockets.DEFAULT_SORT[0])
        if column not in COLUMNS:
            column = sockets.DEFAULT_SORT[0]
        return column, bool(self.memory.get("reverse", ""))

    # -- answers ------------------------------------------------------------- #
    def _latest(self):
        """The newest view this window has, whichever kind of work made it."""
        views = list(self.job.value.values())
        return max(views, key=lambda v: v.made_at) if views else None

    def _on_outcome(self, outcome):
        if outcome.kind == READ:
            self.status.show(outcome)
        if outcome.error:
            self._show_failure()
        else:
            self._show(outcome.value)
        # Typed or sorted while the worker was busy: those inputs were remembered,
        # not sent (see the module docstring), so this answer may be for older ones.
        latest = self._latest()
        if latest is not None and not self._answers_the_inputs(latest):
            self._asked_again()
        self._sync_buttons()

    def _answers_the_inputs(self, view):
        return (view.query, view.sort) == (self.query.get(), self._sort())

    def _show(self, view):
        snapshot = view.snapshot
        if not snapshot.sockets:
            empty = "tools.sockets.empty"
        else:
            empty = "tools.sockets.empty_match"
        self.table.set_empty_text(empty)
        self.table.set_model(view.rows, render=render, key_of=lambda s: s.key)
        self.count.config(text=T("conns.shown_of", shown=len(view.rows),
                                 total=len(snapshot.sockets)))
        self.note.config(text="\n".join(self._notes(snapshot)))

    def _notes(self, snapshot, stale=False):
        lines = []
        if stale:
            at = time.strftime("%H:%M:%S", time.localtime(snapshot.read_at))
            lines.append(T("tools.sockets.note_stale", time=at))
        if snapshot.failed:
            lines.append(T("tools.sockets.note_failed", tables=", ".join(snapshot.failed)))
        unnamed = sockets.without_owner(snapshot)
        if unnamed:
            lines.append(T("tools.sockets.note_no_pid", count=unnamed))
        return lines

    def _show_failure(self):
        """The read failed: say so, and keep the last good rows with their age."""
        latest = self._latest()
        if latest is None:
            self.table.set_empty_text("tools.sockets.empty_failed")
            self.table.set_model([], render=render, key_of=lambda s: s.key)
            self.note.config(text="")
            return
        self.note.config(text="\n".join(self._notes(latest.snapshot, stale=True)))

    def _sync_buttons(self):
        self.refresh_btn.state(["disabled"] if self.job.busy() else ["!disabled"])

    # -- the menu on a row ---------------------------------------------------- #
    def _selected(self):
        keys = self.table.selected_keys()
        return self.table.item_for_key(keys[0]) if keys else None

    def _show_menu(self, x_root, y_root):
        s = self._selected()
        named, remote = bool(s and s.proc), bool(s and s.remote_ip)
        for indexes, allowed in ((NEEDS_NAME, named), (NEEDS_REMOTE, remote)):
            for index in indexes:
                with crashlog.quiet(AREA):
                    self.menu.entryconfigure(index, state="normal" if allowed else "disabled")
        try:
            self.menu.tk_popup(x_root, y_root)
        finally:
            with crashlog.quiet(AREA):
                self.menu.grab_release()

    def _copy_rows(self):
        text = self.table.copy_text()
        if text:
            self.app.copy_to_clipboard(text)

    def _target(self):
        s = self._selected()
        if s and s.proc:
            self.app.set_target_expression(s.proc)

    def _leave_alone(self):
        s = self._selected()
        if s:
            leave_process_alone(self.app, s.proc)

    def _limit(self):
        s = self._selected()
        if s and s.remote_ip:
            self.app.set_destination(address(s), str(s.remote_port or ""))

    def _block(self):
        s = self._selected()
        if s and s.remote_ip:
            block_ip_address(self.app, address(s))
