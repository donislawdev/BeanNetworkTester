"""Tools tab: sockets. The rows and the search are computed in ``nettools/sockets.py``.

Every TCP and UDP socket on the machine - listeners, open connections, the ones
closing - with its state and its process, without a session: the question "which
port does my application listen on?" comes BEFORE anything is impaired, and the
connection table only knows traffic that crossed the driver.

Read when the tab is first looked at and then when asked - or by itself, when the
box beside Refresh is ticked (the owner, 2026-11-10; off until then). In 2026-09-23
a table that read itself was turned down for two reasons, and both are answered
here rather than waved away:

* "it would move under the pointer": the row at the top of the view stays there
  across a read (``SortableTree.set_model(keep_view=True)``), the selection is
  kept by key as it always was, and a socket that closes does not vanish - it
  stays for a few seconds, marked (``nettools/sockets.py::_changes``).
* "at a hundred thousand sockets each read is a second of work": the time between
  two reads is never less than twenty times what the last one took
  (``sockets.read_every_ms``), and the status line says when that stretched it.

🔴 It reads ONLY WHILE LOOKED AT (the owner's condition, 2026-11-10): the Tools
page in front, this tab chosen, the window not minimised (``base.on_screen``).
Asked twice - when a wait is started and when it runs out - so with the tab out of
sight there is no read and no timer either: ``refresh`` (the page's tick, which
only the tool on screen gets) is what starts the waiting again. The next wait
starts when an answer lands, never while a read is out.

The "Show" box, "Mark now" and "Save CSV" (slice 2, 2026-11-11) take nothing more
from the machine: a choice and the file are views of the read the window has, and
a mark is ONE read the person asked for, while looking. Only that read sets the
mark - on what it found, not on the window's last read, which may be minutes old.
A row's "Reset this connection" is the Connections page's (``field_actions``);
when every reset started has ended, the next tick on screen reads once, so the
rows say they closed.

One request at a time. The worker keeps only the LAST request that waits
(``gui/model_worker.py``), and a search queued behind a read would have been
computed on the table it was queued against - the old one - and shown after the
new. So nothing is queued: while the worker is busy the inputs are only
remembered, and each answer that lands is compared with them and asked again
when they moved (``_on_outcome``). Refresh pressed during the table's own read is
remembered the same way, and its read is asked for when that one lands.
"""
import threading
import time
import tkinter as tk
import weakref
from tkinter import ttk

from ...i18n import T
from ...nettools import sockets
from ...nettools.tcphealth import Request
from ...tcprow import Connection
from .. import csv_export, dialogs
from ..field_actions import block_ip_address, can_reset, leave_process_alone, reset_connection
from ..labels import wrapping_label
from ..theme import (CHARS, PAGE_WRAP_PAD, ROWS, SOCKET_COLORS, set_menu_entry_available,
                     space, style_menu)
from ..tooltip import add_tooltip
from ..widgets import SortableTree, make_room
from .base import Debounce, Poller, StatusLine, choice, job, on_screen, remembered
from .ping import offered as ping_offered, ping_from
from .tcphealth import offered, watch_from, watching
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
           "state": "tools.sockets.col.state", "opened": "tools.sockets.col.opened",
           "change": "tools.sockets.col.change",
           "remote_ip": "conns.remote_ip", "remote_port": "conns.remote_port"}
TIPS = {column: f"tips.tools_sockets_col_{column}" for column in COLUMNS}
NUMERIC = frozenset({"local_port", "remote_port", "pid"})
# Centred for the connection table's reason: each follows a right-aligned number,
# and left-aligned it touched it - the first render read "22 LISTEN" as one value.
CENTERED = frozenset({"proto", "state"})
# Sorted the latest first at the first click: the change column is read for what
# changed just now, and from the other end that is below every older change.
NEWEST_FIRST = frozenset({"change"})
MIN_CHARS = {"proto": CHARS["proto"], "local_ip": CHARS["address"],
             "local_port": CHARS["port"], "remote_ip": CHARS["address"],
             "remote_port": CHARS["port"], "state": CHARS["tcp_state"],
             "pid": CHARS["pid"], "proc": CHARS["process"], "change": CHARS["tcp_state"],
             "opened": CHARS["tcp_state"]}
# What the change column says, by ``Socket.change`` - for exactly as long as the
# row has that change's colour (``SOCKET_COLORS``), so the word explains the colour.
# It said "appeared <time>" for good while the colour went after seconds, next to an
# "opened" column a second apart: two times and a colour that did not match.
NEW_WORD, CLOSED_AT = "tools.sockets.new", "tools.sockets.closed_at"
# "opened" where the system keeps no bind time: the read that first saw the socket.
OPENED_SEEN = "tools.sockets.opened_seen"
# The "Show" box: what each choice reads as.
SHOW_TEXT = {sockets.ALL: "tools.sockets.show_all",
             sockets.LISTENING: "tools.sockets.show_listening",
             sockets.CONNECTED: "tools.sockets.show_connected",
             sockets.SINCE_MARK: "tools.sockets.show_mark"}

READ, VIEW = "read", "view"
# A read that also sets the mark ("Mark now"): a READ to the worker, with mark=True.
MARK = "mark"
# The shortest wait before a read the table starts by itself: a tick's worth of
# room for the window to draw the answer it has just been given.
MIN_WAIT_MS = 50

# Menu entries a row may be refused, by position (0 is "Copy", 1 the separator).
NEEDS_NAME = (2, 3)         # target / leave alone: the process's name
NEEDS_REMOTE = (4, 5)       # limit to / block: an address on the other end
RESET = 6                   # "Reset this connection": one this system can reset
HEALTH = 7                  # "Show TCP health": a TCP connection (tcphealth.offered)
PING = 8                    # "Ping this address": one address on the other end


def clock(at):
    return time.strftime("%H:%M:%S", time.localtime(at))


def change_text(s):
    """The change column: "new", or "closed" and when, while the row is coloured for
    it; "" otherwise."""
    if s.change == sockets.NEW:
        return T(NEW_WORD)
    if s.change == sockets.CLOSED:
        return T(CLOSED_AT, time=clock(s.at))
    return ""


def seconds_text(seconds):
    return T("tools.sockets.seconds", n=seconds)


def show_text(which):
    return T(SHOW_TEXT.get(which, SHOW_TEXT[sockets.ALL]))


def opened_text(created, now=None, seen=None):
    """When the socket was bound: the time for one bound today, the date and time
    for an older one. Where the system does not say (Linux): "~" and the time of the
    read that first saw it (``Socket.seen_at``), and "" for one there at the first."""
    if created is None:
        return "" if seen is None else T(OPENED_SEEN, time=_day_or_time(seen, now))
    return _day_or_time(created, now)


def _day_or_time(at, now=None):
    when = time.localtime(at)
    today = time.localtime(time.time() if now is None else now)
    if (when.tm_year, when.tm_yday) == (today.tm_year, today.tm_yday):
        return time.strftime("%H:%M:%S", when)
    return time.strftime("%Y-%m-%d %H:%M", when)


def proc_text(s):
    """The process cell: a service host's sockets with the service they belong to,
    as Resource Monitor writes it."""
    if s.service and s.proc:
        return T("tools.sockets.proc_service", proc=s.proc, service=s.service)
    return s.proc


def render(s):
    """One row's cells, in ``COLUMNS`` order. Called only for the rows on screen."""
    return (proc_text(s), "" if s.pid is None else s.pid, s.proto, s.local_ip,
            s.local_port, s.state, opened_text(s.created, seen=s.seen_at), change_text(s),
            s.remote_ip,
            "" if s.remote_port is None else s.remote_port)


def address(s):
    """The remote address as a Control field takes it: without an IPv6 zone."""
    return s.remote_ip.split("%")[0]


def connection_of(s):
    """The row's four numbers, as TCP health names a connection."""
    return Connection(s.local_ip, s.local_port, s.remote_ip, s.remote_port)


def _mark_of(snapshot):
    return snapshot.carry.mark if snapshot.carry is not None else None


def reset_row(s):
    """The row as "Reset this connection" reads one: the Connections page's words."""
    return {"proto": s.proto, "local_port": s.local_port, "remote_ip": s.remote_ip,
            "remote_port": s.remote_port}


_RESETS: "weakref.WeakKeyDictionary[object, list[threading.Thread]]" = \
    weakref.WeakKeyDictionary()


def resets(app):
    """The resets started from this window's row menu that the table has not read
    after yet. Kept for the window, like its job (``base.job``): a language change
    rebuilds the panel while one runs, and the read that follows it must not go
    with the old panel."""
    return _RESETS.setdefault(app, [])


def reset_offered(s):
    """"Reset this connection" for a row that IS one, and one this system resets
    (``field_actions.can_reset``, the Connections page's own rule). Not for a row
    marked closed - there is nothing left to reset - nor for PID 0: a connection
    in TIME_WAIT, which no program holds and which Windows refuses (317, measured
    in ``tcpreset``)."""
    return bool(s and s.change != sockets.CLOSED and s.pid != 0 and s.remote_ip
                and s.remote_port is not None and can_reset(reset_row(s)))


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
        self.live = tk.BooleanVar(value=self.memory.get("live") == "1")
        box = ttk.Checkbutton(bar, text=T("tools.sockets.live"), variable=self.live,
                              command=self._live_ticked)
        box.pack(side="left", padx=space("inline"))
        add_tooltip(box, "tips.tools_sockets_live")
        self.every, self.every_box = choice(
            bar, self.memory, "tools.sockets.every", sockets.EVERY_S, "every",
            sockets.DEFAULT_EVERY_S, "tips.tools_sockets_every", seconds_text)
        self._timer = None          # the wait before the next read the table starts
        self._read_at = None        # time.monotonic() the last read's answer landed
        self._failures = 0          # reads that failed in a row
        self._took = []             # what the last two reads took, in ms
        self._quiet = False         # the read that is out was started by the table
        self._asked = None          # READ or MARK pressed while that read was out
        self._resets = resets(app)  # the row menu's resets that have not been read after
        self.count = ttk.Label(bar, text="", style="Muted.TLabel")
        self.count.pack(side="right")
        self._build_which_row()

        self.status = StatusLine(self.frame)
        self.status.label.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        # What the rows on screen are missing, or how old they are.
        self.note = wrapping_label(self.frame, "", pad=PAGE_WRAP_PAD)
        self.note.pack(fill="x", padx=space("page"), pady=(space("hair"), 0))

        holder = ttk.Frame(self.frame)
        holder.pack(fill="both", expand=True, padx=space("page"),
                    pady=(space("tight"), space("page")))
        column, reverse = self._sort()
        self.table = SortableTree(holder, COLUMNS, sort={"col": column, "reverse": reverse},
                                  on_sort=self._on_sort, height=ROWS["table"],
                                  horizontal=True, min_chars=MIN_CHARS, tips=TIPS,
                                  numeric=NUMERIC, centered=CENTERED, tags=SOCKET_COLORS,
                                  empty_text="tools.common.working")
        self.table.start_reversed = NEWEST_FIRST
        a_year_on = 86_400 * 365
        make_room(self.table, {"change": [T(NEW_WORD), T(CLOSED_AT, time=clock(0))],
                               "opened": [opened_text(0, now=a_year_on),
                                          opened_text(None, now=a_year_on, seen=0)]})
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
            self._say(read)
            if read.error:
                self._show_failure()
        if self.job.busy():
            self.status.working()
            self.poller.start()
        elif latest is not None and not self._answers_the_inputs(latest):
            # typed inside the pause before a rebuild: remembered, never searched
            self._ask(VIEW)
        self._sync_buttons()

    def _build_which_row(self):
        """Which sockets, the mark and the file: a row of their own, the first one
        being full (``render_live``: the pace box ends just before the count)."""
        which = ttk.Frame(self.frame)
        which.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        self.which, self.which_box = choice(
            which, self.memory, "tools.sockets.show", sockets.SHOWS, "which", sockets.ALL,
            "tips.tools_sockets_show", show_text)
        self.which_box.bind("<<ComboboxSelected>>", self._which_chosen, add="+")
        self.mark_btn = ttk.Button(which, text=T("tools.sockets.mark"), command=self.mark)
        self.mark_btn.pack(side="left")
        add_tooltip(self.mark_btn, "tips.tools_sockets_mark")
        self.export_btn = ttk.Button(which, text=T("tools.sockets.export"),
                                     command=self._export)
        self.export_btn.pack(side="left", padx=(space("inline"), 0))
        add_tooltip(self.export_btn, "tips.tools_sockets_export")

    def _build_menu(self):
        self.menu = style_menu(tk.Menu(self.frame, tearoff=0))
        self.menu.add_command(label=T("menu.copy_row"), command=self._copy_rows)
        self.menu.add_separator()
        self.menu.add_command(label=T("menu.target_process"), command=self._target)
        self.menu.add_command(label=T("menu.leave_process_alone"), command=self._leave_alone)
        self.menu.add_command(label=T("menu.limit_dest"), command=self._limit)
        self.menu.add_command(label=T("menu.block_ip"), command=self._block)
        self.menu.add_command(label=T("menu.reset_connection"), command=self._reset)
        self.menu.add_command(label=T("menu.show_tcp_health"), command=self._health)
        self.menu.add_command(label=T("menu.ping_address"), command=self._ping)
        self.table.bind_row_menu(self._show_menu)

    # -- the page calls ------------------------------------------------------ #
    def refresh(self):
        """The tick, while this tab is on screen: the first look reads, and a table
        that reads itself goes back to waiting for its next read."""
        self._read_if_never()
        self._read_after_reset()
        self._arm()
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
        self._disarm()

    def focus_search(self):
        """Ctrl+F while this tool is on screen: its own search box."""
        with crashlog.quiet(AREA):
            self.entry.focus_set()
            self.entry.select_range(0, "end")
        return "break"

    # -- asking -------------------------------------------------------------- #
    def read(self):
        """Read the machine again (the Refresh button)."""
        self._take(READ)

    def mark(self):
        """"Mark now": a read that sets the mark, and the table showing what opened
        and closed since it (``sockets.Mark``). A read of its own, not the last one:
        that may be minutes old (``sockets.read``)."""
        self._set_which(sockets.SINCE_MARK)
        self._take(MARK)

    def _take(self, kind):
        if not self.job.busy():
            self._ask(kind)
        elif self._quiet:
            # The table's own read is out, and the button did not say so (_ask). The
            # person's read follows it, naming every process again; until then the
            # window shows it was taken, both buttons greyed out - so a Refresh
            # pressed after a Mark now (or the other way round) is not taken, and a
            # mark asked for is never lost to it.
            self._asked = kind
            self._quiet = False
            self.status.working()
            self._sync_buttons()

    def _read_if_never(self):
        # Not after a read that failed: that says so, and waits for Refresh rather
        # than asking the system again on every tick.
        if READ not in self.job.last and not self.job.busy():
            self._ask(READ)

    def _ask(self, kind, by_itself=False):
        query, (column, reverse), which = self.query.get(), self._sort(), self.which()
        # Taken HERE, on the UI thread: the worker does not reach back into the
        # window (convention 26), and nothing reads while this runs.
        latest = self._latest()
        snapshot = latest.snapshot if latest is not None else None
        if kind in (READ, MARK):
            # The read before this one goes with it, so the answer says what
            # changed. A read the table starts keeps the names it has; one the
            # person asked for names every process again.
            mark = kind == MARK
            self.job.run(READ, lambda: sockets.table(None, query, column, reverse, snapshot,
                                                     not by_itself, which, mark))
            self._quiet = by_itself
            if not by_itself:
                # Not for the table's own reads: "Working..." would blink in the
                # status line at every one of them, and so would the button.
                self.status.working()
        elif snapshot is None:
            return
        else:
            self.job.run(VIEW, lambda: sockets.table(snapshot, query, column, reverse,
                                                     show=which))
        self._sync_buttons()
        self.poller.start()

    # -- reading by itself ----------------------------------------------------- #
    def _watching(self):
        """Ticked, and looked at: see the module docstring."""
        return bool(self.live.get()) and on_screen(self.app, self.ID)

    def _pace_ms(self):
        # The quicker of the last two reads: one read is slow whenever a new program
        # turns up (it takes the process snapshot, 71 ms measured), and that alone
        # must not stretch the pace and have the status line say so. A table that is
        # slow to read is slow twice running.
        return sockets.read_every_ms(self.every(), min(self._took, default=0),
                                     self._failures)

    def _arm(self):
        """Start the wait for the next read, unless one is waiting or out."""
        if self._timer is not None or self.job.busy() or not self._watching():
            return
        wait = 0.0
        if self._read_at is not None:
            wait = self._pace_ms() - (time.monotonic() - self._read_at) * 1000
        with crashlog.quiet(AREA):
            self._timer = self.frame.after(max(MIN_WAIT_MS, int(wait)), self._tick)

    def _disarm(self):
        if self._timer is not None:
            with crashlog.quiet(AREA):
                self.frame.after_cancel(self._timer)
            self._timer = None

    def _tick(self):
        """The wait ran out. Asked again whether anyone is looking: the tab may
        have been left, or the window minimised, while it ran."""
        self._timer = None
        if self._watching() and not self.job.busy():
            self._ask(READ, by_itself=True)

    def _live_ticked(self):
        self.memory["live"] = "1" if self.live.get() else ""
        self.memory.pop("stopped", None)
        self._failures = 0
        self._disarm()
        if self.live.get():
            self._read_at = None        # ticked: the first read is now
            self._arm()
        read = self.job.last.get(READ)
        if read is not None:
            self._say(read)
        latest = self._latest()
        if latest is not None:
            self.note.config(text="\n".join(
                self._notes(latest.snapshot, stale=self._read_failed())))

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

    def _which_chosen(self, _event=None):
        self._asked_again()

    def _set_which(self, which):
        """Choose in the "Show" box from code, as a click would, remembered."""
        self.memory["which"] = which
        with crashlog.quiet(AREA):
            self.which_box.set(show_text(which))

    # -- answers ------------------------------------------------------------- #
    def _latest(self):
        """The newest view this window has, whichever kind of work made it."""
        views = list(self.job.value.values())
        return max(views, key=lambda v: v.made) if views else None

    def _on_outcome(self, outcome):
        if outcome.kind == READ:
            self._quiet = False
            self._read_at = time.monotonic()
            self._took = [*self._took[-1:], outcome.elapsed_ms]
            self._failures = self._failures + 1 if outcome.error else 0
            if self._failures >= sockets.FAILURES_TO_STOP and self.live.get():
                # Whatever is wrong is not passing: stop asking, and say so.
                self.live.set(False)
                self.memory["live"] = ""
                self.memory["stopped"] = "1"
            self._say(outcome)
        if outcome.error:
            self._show_failure()
        else:
            self._show(outcome.value, keep_view=outcome.kind == READ)
        if self._asked and not self.job.busy():
            # Refresh or Mark pressed during the table's own read (``_take``). Taken
            # with the inputs as they are now, so it answers a search typed meanwhile too.
            kind, self._asked = self._asked, None
            self._ask(kind)
            return
        # Typed or sorted while the worker was busy: those inputs were remembered,
        # not sent (see the module docstring), so this answer may be for older ones.
        latest = self._latest()
        if latest is not None and not self._answers_the_inputs(latest):
            self._asked_again()
        self._arm()
        self._sync_buttons()

    def _say(self, read):
        """The status line for a read: when it was, and when the next one comes if
        the table reads itself. "Read at", not the other tools' "Done at": the rows
        are a reading of the machine, and the table that reads itself says "Read" too."""
        if read.error:
            self.status.show(read)
            return
        if not self.live.get():
            self.status.label.config(text=T("tools.sockets.status_read", time=clock(read.finished),
                                            ms=read.elapsed_ms), style="Muted.TLabel")
            return
        # To a tenth of a second, and "slow" only when that shows: in whole seconds
        # 2.4 s read "every 2 s, not every 2 s", and 2.02 s is not worth saying.
        chosen, every = self.every(), round(self._pace_ms() / 1000, 1)
        slow = every > chosen
        text = T("tools.sockets.status_live_slow" if slow else "tools.sockets.status_live",
                 time=clock(read.finished), ms=read.elapsed_ms, every=f"{every:g}",
                 chosen=chosen)
        self.status.label.config(text=text, style="Muted.TLabel")

    def _answers_the_inputs(self, view):
        return ((view.query, view.sort, view.show)
                == (self.query.get(), self._sort(), self.which()))

    def _show(self, view, keep_view=False):
        snapshot = view.snapshot
        if not snapshot.sockets:
            empty = "tools.sockets.empty"
        elif view.show == sockets.SINCE_MARK and not view.query:
            empty = "tools.sockets.empty_since_mark"
        else:
            empty = "tools.sockets.empty_match"
        self.table.set_empty_text(empty)
        # Across a read the row at the top of the view stays there. A new search or
        # order is a view of the same read, and starts where the table stood, as before.
        self.table.set_model(view.rows, render=render, key_of=lambda s: s.key,
                             tag_of=lambda s: s.change, keep_view=keep_view)
        self.count.config(text=T("conns.shown_of", shown=len(view.rows), total=view.total))
        # Asked of the job, not remembered by the panel: a search or a sort after a
        # failed Refresh shows the same old rows, and they must still say how old.
        self.note.config(text="\n".join(self._notes(snapshot, stale=self._read_failed())))

    def _read_failed(self):
        """The newest read failed, so the rows on screen are older than the last try."""
        read = self.job.last.get(READ)
        return bool(read is not None and read.error)

    def _notes(self, snapshot, stale=False):
        lines = []
        mark = _mark_of(snapshot)
        if mark is not None and self.which() == sockets.SINCE_MARK:
            # Since when: the click, or the first read when nobody has clicked.
            key = "tools.sockets.note_mark" if mark.asked else "tools.sockets.note_since_first"
            lines.append(T(key, time=clock(mark.at)))
            if mark.dropped:
                lines.append(T("tools.sockets.note_mark_dropped", n=mark.dropped,
                               max=sockets.MAX_CLOSED))
        if self.memory.get("stopped"):
            lines.append(T("tools.sockets.note_live_stopped", n=sockets.FAILURES_TO_STOP))
        if stale:
            lines.append(T("tools.sockets.note_stale", time=clock(snapshot.read_at)))
        if snapshot.failed:
            lines.append(T("tools.sockets.note_failed", tables=", ".join(snapshot.failed)))
        unnamed = sockets.without_owner(snapshot)
        if unnamed:
            lines.append(T(sockets.no_owner_note(), count=unnamed))
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
        # A read the table started leaves the buttons as they are: see _ask.
        busy = self.job.busy() and not self._quiet
        for button in (self.refresh_btn, self.mark_btn):
            button.state(["disabled"] if busy else ["!disabled"])
        # nothing on screen, nothing to save: it wrote an empty file (UX-GUI-007)
        latest = self._latest()
        self.export_btn.state(["!disabled"] if latest is not None and latest.rows
                              else ["disabled"])

    def _export(self):
        """"Save CSV": the rows on screen - this search, this "Show", this order -
        as they are, read from what the window holds. Nothing is read again. The
        writer, or None when one was already running (``csv_export.export_sockets``)."""
        latest = self._latest()
        return csv_export.export_sockets(self.app,
                                         list(latest.rows) if latest is not None else [])

    # -- the menu on a row ---------------------------------------------------- #
    def _selected(self):
        keys = self.table.selected_keys()
        return self.table.item_for_key(keys[0]) if keys else None

    def _health_offered(self, s):
        """"Show TCP health" for a row with a connection behind it. One that has
        closed only while it is on that tool's list, where its numbers are: a new
        watch of it would be an empty entry saying it ended."""
        if not (s and offered(s.proto, s.remote_ip, s.state)):
            return False
        return s.change != sockets.CLOSED or watching(self.app, connection_of(s))

    def _show_menu(self, x_root, y_root):
        s = self._selected()
        named, remote = bool(s and s.proc), bool(s and s.remote_ip)
        health = self._health_offered(s)
        # A listening socket's remote side is 0.0.0.0 or ::, which is nobody.
        pingable = bool(s and ping_offered(s.remote_ip))
        for indexes, allowed in ((NEEDS_NAME, named), (NEEDS_REMOTE, remote),
                                 ((RESET,), reset_offered(s)),
                                 ((HEALTH,), health), ((PING,), pingable)):
            for index in indexes:
                with crashlog.quiet(AREA):
                    set_menu_entry_available(self.menu, index, allowed)
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

    def _reset(self):
        """Reset the row's connection - the Connections page's reset, on its worker,
        with its line in the log. When it has ended the table reads once (``refresh``),
        so the row says it closed; with the tab out of sight, at the next look."""
        s = self._selected()
        if reset_offered(s):
            worker = reset_connection(self.app, reset_row(s))
            if worker is not None:
                self._resets.append(worker)

    def _read_after_reset(self):
        # Once EVERY reset has ended: a read between two would show the later one's
        # connection open, and none would follow it. Not while any read is out
        # either: it may have started before the reset ended. The next tick asks again.
        pending = self._resets
        if pending and not any(w.is_alive() for w in pending) and not self.job.busy():
            pending.clear()
            self.read()

    def _health(self):
        """The connection onto TCP health's list, that tool on screen. The row has
        all four numbers, so nothing is looked up."""
        s = self._selected()
        if self._health_offered(s):
            watch_from(self.app, Request(s.proc, s.pid, connection=connection_of(s)))

    def _ping(self):
        """Ping the row's remote address - with its IPv6 zone, which a link-local
        address needs to be reached at all."""
        s = self._selected()
        if s and ping_offered(s.remote_ip):
            ping_from(self.app, s.remote_ip)

    def _limit(self):
        s = self._selected()
        if s and s.remote_ip:
            self.app.set_destination(address(s), str(s.remote_port or ""))

    def _block(self):
        s = self._selected()
        if s and s.remote_ip:
            block_ip_address(self.app, address(s))
