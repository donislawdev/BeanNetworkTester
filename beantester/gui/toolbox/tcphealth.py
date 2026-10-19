"""Tools tab: TCP health - what Windows' TCP stack measures for a watched connection.
The numbers are ``tcpestats``'s; the list, the differences and the words are
``nettools/tcphealth.py``'s.

"Does the stack see my 200 ms as 200 ms of round trip, my 5% loss as resent
segments?" A connection is put on the list from a row menu - the socket table
beside this tool, or the Connections page of a session (the owner's choice,
2026-10-19: no second socket table here). Turning counting on for it needs
administrator rights; without them the tool says so in a line of its own, like
"Clean up the driver" does.

Layout (the owner's choice of the rendered two, 2026-10-19): the list above, the
chosen connection's details below with its round trips charted BESIDE them - stacked
under the details, the chart left them one pixel of a 678 px window.

Read once a second while this tool is on screen (every tool on this tab works only
when looked at), or all the time when the box under the buttons is ticked - the
owner asked for both, the first by default. One worker run reads everything on the
list and turns counting on for what was just asked, and the next run starts only
after the last one answered: a run waiting behind another is REPLACED by a newer one
(``ToolJob``), so asking twice could have lost the first request.
"""
import time
import tkinter as tk
import weakref
from tkinter import ttk

from ... import crashlog, tcpestats
from ...i18n import T
from ...nettools import tcphealth
from .. import dialogs
from ..chart import chart_canvas, draw_rtt_chart
from ..clipboard import copy_confirmed
from ..labels import wrapping_label
from ..theme import CHARS, HEALTH_COLORS, ROWS, size, space
from ..tooltip import add_tooltip
from ..widgets import SortableTree
from .base import Poller, StatusLine, job, remembered
from .details import DetailsMenu, render_detail, say

AREA = "gui.toolbox.tcphealth"

COLUMNS = {"process": "tools.tcphealth.col.process", "local": "tools.tcphealth.col.local",
           "remote": "tools.tcphealth.col.remote", "state": "tools.tcphealth.col.state",
           "rtt": "tools.tcphealth.col.rtt", "resent": "tools.tcphealth.col.resent"}
TIPS = {column: f"tips.tools_tcphealth_col_{column}" for column in COLUMNS}
MIN_CHARS = {"process": CHARS["process"], "local": CHARS["address"],
             "remote": CHARS["address"], "state": CHARS["tcp_state"], "rtt": CHARS["rtt"],
             "resent": CHARS["resent"]}
DETAIL_COLUMNS = {"item": "tools.tcphealth.col.item", "value": "tools.tcphealth.col.value",
                  "note": "tools.tcphealth.col.note"}
DETAIL_TIPS = {column: f"tips.tools_tcphealth_col_{column}" for column in DETAIL_COLUMNS}
DETAIL_MIN_CHARS = {"item": CHARS["item"], "value": CHARS["address"], "note": CHARS["note"]}

CYCLE = "cycle"
READ_EVERY_MS = 1000

# What the log says when asking to watch a connection did not put it on the list.
REFUSED_LOG = {tcphealth.GONE: "tools.tcphealth.log_gone",
               tcphealth.AMBIGUOUS: "tools.tcphealth.log_ambiguous",
               tcphealth.UNREADABLE: "tools.tcphealth.log_unreadable",
               tcphealth.FULL: "tools.tcphealth.log_full"}

# The watched connections of each window: they outlive a rebuild (a language change)
# and die with the window, like the tools' inputs (``base.remembered``).
_LISTS: "weakref.WeakKeyDictionary[object, tcphealth.Watchlist]" = weakref.WeakKeyDictionary()


def watchlist(app):
    return _LISTS.setdefault(app, tcphealth.Watchlist())


def render(watch):
    return tuple(say(cell) for cell in tcphealth.cells(watch))


def watch_from(app, request):
    """A row menu's "Show TCP health": this tool on screen, the connection on its list."""
    app.select_page("tools")
    page = app.pages["tools"]
    page.select(TcpHealthPanel.ID)
    panel = page.panels.get(TcpHealthPanel.ID)
    if isinstance(panel, TcpHealthPanel):
        panel.ask(request)


def offered(proto, remote_ip, state=""):
    """Whether a row menu offers "Show TCP health" for a row."""
    return tcpestats.supported() and tcphealth.watchable(proto, remote_ip, state)


class TcpHealthPanel:
    ID = "tcphealth"
    LABEL = "tools.tcphealth.tab"

    def __init__(self, app, parent):
        self.app = app
        self.job = job(app, self.ID)
        self.memory = remembered(app, self.ID)
        self.list = watchlist(app)
        self.frame = ttk.Frame(parent)
        self.supported = tcpestats.supported()
        self._timer = None
        self._drawn = None

        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        self.stop_btn = self._button(bar, "tools.tcphealth.stop", "tips.tools_tcphealth_stop",
                                     self.stop)
        self.copy_btn = self._button(bar, "tools.tcphealth.copy_report",
                                     "tips.tools_tcphealth_copy", self.copy_report)
        self.background = tk.BooleanVar(value=self.memory.get("background") == "1")
        box = ttk.Checkbutton(bar, text=T("tools.tcphealth.background"),
                              variable=self.background, command=self._background_ticked)
        box.pack(side="left", padx=(0, space("inline")))
        add_tooltip(box, "tips.tools_tcphealth_background")
        dialogs.help_button(bar, app.root, "tools.tcphealth.help_title",
                            "tools.tcphealth.help_body",
                            "tips.tools_tcphealth_help").pack(side="right")

        # Asked once: a running process does not gain or lose administrator rights.
        # A line of its own only when there is something to say: the tables need the
        # height (``SIZE`` in theme.py).
        self.blocker = tcphealth.blocker()
        self.admin_note = None
        if self.blocker:
            self.admin_note = wrapping_label(self.frame, T(self.blocker))
            self.admin_note.pack(fill="x", padx=space("page"), pady=(space("hair"), 0))
        self.status = StatusLine(self.frame)
        self.status.label.pack(fill="x", padx=space("page"), pady=(space("row"), 0))

        top = ttk.Frame(self.frame)
        top.pack(fill="x", padx=space("page"), pady=(space("tight"), 0))
        self.table = SortableTree(
            top, COLUMNS, sort={"col": "", "reverse": False}, on_sort=lambda _s: self._show(),
            height=ROWS["watched"], min_chars=MIN_CHARS, tips=TIPS, tags=HEALTH_COLORS,
            selectmode="browse", empty_text="tools.tcphealth.empty" if self.supported
            else "tools.tcphealth.windows_only")
        self.table.bind_select(self._on_select)

        bottom = ttk.Frame(self.frame)
        bottom.pack(fill="both", expand=True, padx=space("page"),
                    pady=(space("row"), space("page")))
        box = ttk.LabelFrame(bottom, text=T("tools.tcphealth.chart"))
        box.pack(side="right", fill="y", padx=(space("row"), 0))
        # The legend first, at the bottom: what is left of the height goes to the
        # canvas, so a line more above (the administrator note) shrinks the chart,
        # not its legend (rendered 2026-10-19 without the note's room: the legend went).
        legend = ttk.Frame(box)
        legend.pack(side="bottom", fill="x", padx=space("tight"), pady=(0, space("tight")))
        for style, key in (("Swatch.Down.TLabel", "tools.tcphealth.legend_smoothed"),
                           ("Swatch.Up.TLabel", "tools.tcphealth.legend_sample")):
            ttk.Label(legend, text="  ", style=style).pack(side="left")
            ttk.Label(legend, text=T(key)).pack(side="left", padx=(space("tight"), space("row")))
        self.canvas = chart_canvas(box, size("side_chart"), size("chart"))
        self.canvas.pack(fill="both", expand=True, padx=space("tight"), pady=space("tight"))
        self.canvas.bind("<Configure>", lambda _e: self._draw())
        self.details = SortableTree(
            bottom, DETAIL_COLUMNS, sort={"col": "", "reverse": False},
            on_sort=lambda _s: self._show_details(), height=ROWS["details"], horizontal=True,
            min_chars=DETAIL_MIN_CHARS, tips=DETAIL_TIPS, tags=HEALTH_COLORS,
            selectmode="browse", empty_text="tools.tcphealth.empty_details")
        self.details_menu = DetailsMenu(app, self.frame, self.details,
                                        "tools.tcphealth.log_limited", AREA)

        self.poller = Poller(self.frame, self.job, self._on_outcome)
        self._show()
        if self.job.busy():
            self.poller.start()
        self._arm()

    # -- building ------------------------------------------------------------ #
    @staticmethod
    def _button(bar, text_key, tip_key, command):
        button = ttk.Button(bar, text=T(text_key), command=command)
        button.pack(side="left", padx=(0, space("inline")))
        add_tooltip(button, tip_key)
        return button

    # -- the page calls ------------------------------------------------------ #
    def refresh(self):
        """The tick, while this tool is on screen."""
        self._arm()
        self._sync_buttons()

    def pending(self):
        """Take an answer that has arrived, and say whether one is still due."""
        return self.poller.now()

    def teardown(self):
        self.poller.cancel()
        if self._timer is not None:
            with crashlog.quiet(AREA):
                self.frame.after_cancel(self._timer)
            self._timer = None

    # -- asking -------------------------------------------------------------- #
    def ask(self, request):
        """Put a connection on the list (a row menu, through ``watch_from``)."""
        if request.connection is not None:
            self.memory["chosen"] = tcphealth.key_of(request.connection)
        if self.list.ask(request) == tcphealth.FULL:
            self.app.log(T(REFUSED_LOG[tcphealth.FULL], n=tcphealth.MAX_WATCHED))
        self._show()
        self._read()

    def _on_screen(self):
        page = self.app.pages.get("tools")
        return self.app.current_page() is page and page.current() == self.ID

    def _read(self):
        """One worker run: what was asked, and everything still being read. Never
        while a run is out - see the module's last paragraph."""
        if not self.supported or self.job.busy() or not self.list.busy():
            return
        requests, self.list.pending = self.list.pending, []
        connections = self.list.to_read()
        self.job.run(CYCLE, lambda: tcphealth.cycle(requests, connections))
        self.poller.start()

    def _tick(self):
        self._timer = None
        if self.list.pending or self.background.get() or self._on_screen():
            self._read()
        self._arm()

    def _arm(self):
        """Keep the once-a-second timer going while something is on the list."""
        if self._timer is None and self.supported and self.list.busy():
            with crashlog.quiet(AREA):
                self._timer = self.frame.after(READ_EVERY_MS, self._tick)

    def _background_ticked(self):
        self.memory["background"] = "1" if self.background.get() else ""

    # -- answers ------------------------------------------------------------- #
    def _on_outcome(self, outcome):
        if outcome.error:
            self.status.show(outcome)
        else:
            added = [key for key in self.list.watches]
            for request, kind in self.list.apply(outcome.value, outcome.finished):
                target = request.target
                self.app.log(T(REFUSED_LOG.get(kind, "tools.tcphealth.log_unreadable"),
                               address=f"{target.remote_ip}:{target.remote_port}"
                               if target else ""))
            new = [key for key in self.list.watches if key not in added]
            if new:
                self.memory["chosen"] = new[-1]
            at = time.strftime("%H:%M:%S", time.localtime(outcome.finished))
            self.status.label.config(text=T("tools.tcphealth.status", time=at),
                                     style="Muted.TLabel")
        self._show()
        if self.list.pending:
            self._read()
        self._arm()

    def _show(self):
        watches = list(self.list.watches.values())
        sort = self.table.sort
        if sort["col"] in COLUMNS:
            at = list(COLUMNS).index(sort["col"])
            watches.sort(key=lambda w: tcphealth.sort_key(w, at), reverse=sort["reverse"])
        self.table.set_model(watches, render=render, key_of=lambda w: w.key,
                             tag_of=tcphealth.tag_of)
        chosen = self.memory.get("chosen")
        if chosen not in self.list.watches:
            chosen = next(iter(self.list.watches), None)
        self.memory["chosen"] = chosen
        self.table.select_keys([chosen] if chosen else [])
        self._show_details()
        self._sync_buttons()

    def _on_select(self):
        keys = self.table.selected_keys()
        if keys:
            self.memory["chosen"] = keys[0]
            self._show_details()

    def _chosen(self):
        return self.list.watches.get(self.memory.get("chosen") or "")

    def _show_details(self):
        watch = self._chosen()
        rows = tcphealth.details(watch) if watch is not None else []
        sort = self.details.sort
        if sort["col"] in DETAIL_COLUMNS:
            at = list(DETAIL_COLUMNS).index(sort["col"])
            rows.sort(key=lambda d: render_detail(d)[at].casefold(), reverse=sort["reverse"])
        self.details.set_model(rows, render=render_detail, key_of=lambda d: d.key,
                               tag_of=lambda d: d.tag)
        self._draw()

    def _draw(self):
        """The chosen connection's round trips - redrawn only when they or the size
        changed (the Statistics chart's rule)."""
        watch = self._chosen()
        smoothed, sample, span = tcphealth.chart(watch, self.list.read_at)
        with crashlog.quiet(AREA):
            source = (self.canvas.winfo_width(), self.canvas.winfo_height(), tuple(smoothed),
                      tuple(sample), span)
            if source != self._drawn:
                draw_rtt_chart(self.canvas, smoothed, sample, span)
                self._drawn = source

    def _sync_buttons(self):
        self.stop_btn.state(["!disabled"] if self._chosen() is not None else ["disabled"])
        self.copy_btn.state(["!disabled"] if self.list.watches else ["disabled"])

    # -- the buttons -------------------------------------------------------- #
    def stop(self):
        """Take the chosen connection off the list. Counting is NOT turned off
        (Learn: another program may be watching it too)."""
        watch = self._chosen()
        if watch is not None:
            self.list.remove(watch.key)
            self.memory["chosen"] = None
            self._show()

    def copy_report(self):
        if self.list.watches:
            copy_confirmed(self.app, tcphealth.report(self.list),
                           T("tools.tcphealth.report_logged"), AREA)
