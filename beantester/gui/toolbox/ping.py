"""Tools tab: Ping - is the session's latency and loss really reaching the traffic?

The only tool on this tab that sends anything: an echo request to the address the
person typed, at the pace they chose, from Start to Stop (``icmp.py`` sends one,
``nettools/ping.py`` decides what and keeps what came back). Everything else is
drawing.

A run belongs to the WINDOW, not to this panel (``PingRun``, kept against the App):
the scene it exists for is "Start, go to Control, change the latency, come back and
look", so it goes on while another tab is in front - unlike the tab's other tools,
which work only while they are looked at - and a language change, which rebuilds
every panel and builds this one again only when its tab is next opened, must not
stop it either. Its timer is on the root window for the same reason.

One request is out at a time: the next goes a pace after the last one went and
never before its answer came, so a reply is always shown on the row it belongs to.
The pace and the wait cannot change during a run (their boxes are off): a report
saying "every 1 s" over pings sent every 5 s would be wrong.

Layout (the owner's choice of the rendered two, 2026-10-19): the rows on the left,
the round trips charted beside them - the TCP health arrangement; the chart across
the top left the table 10 px of a 678 px window.
"""
import time
import tkinter as tk
import weakref
from tkinter import ttk

from ... import capabilities, crashlog
from ...i18n import T
from ...nettools import Refused, ping
from .. import dialogs
from ..chart import chart_canvas, draw_ping_chart
from ..clipboard import copy_confirmed
from ..labels import wrapping_label
from ..theme import (CHARS, PAGE_WRAP_PAD, PING_COLORS, ROWS, popdown_height, popdown_width,
                     size, space)
from ..tooltip import add_tooltip
from ..widgets import SortableTree
from .base import Poller, StatusLine, job, remembered
from .details import say

AREA = "gui.toolbox.ping"
ID = "ping"

COLUMNS = {"seq": "tools.ping.col.seq", "sent": "tools.ping.col.sent",
           "rtt": "tools.ping.col.rtt", "ttl": "tools.ping.col.ttl",
           "result": "tools.ping.col.result"}
TIPS = {column: f"tips.tools_ping_col_{column}" for column in COLUMNS}
MIN_CHARS = {"seq": CHARS["seq"], "sent": CHARS["sent_at"], "rtt": CHARS["rtt"],
             "ttl": CHARS["proto"], "result": CHARS["result"]}
NUMERIC = frozenset({"seq", "rtt"})
# All the same width: centred, so the number beside them does not touch them
# (``SortableTree``'s rule; the render had "64 Reply" read as one value).
CENTERED = frozenset({"sent", "ttl"})

# The "?" sheet: the shared paragraphs around the one about this system
# (``ping.platform_help``), joined by ``dialogs.sheet_text``.
HELP_FIRST, HELP_LAST = "tools.ping.help_body", "tools.ping.help_end"


def help_keys() -> tuple[str, ...]:
    return (HELP_FIRST,) + tuple(ping.platform_help()) + (HELP_LAST,)


START, ECHO = "start", "echo"
# Which session line, by what the engine's connection log says of this ping's row.
SESSION_WORDS = {None: "tools.ping.session.not_captured", True: "tools.ping.session.impaired",
                 False: "tools.ping.session.outside"}


def pace_text(seconds):
    """A choice of the pace or the wait: "200 ms" under a second, "2 s" from one."""
    if seconds < 1:
        return T("tools.ping.ms", n=round(seconds * 1000))
    return T("tools.ping.seconds", n=f"{seconds:g}")


def count_text(count):
    """A choice of how many pings: "until Stop" for 0."""
    return T("tools.ping.count_endless") if not count else T("tools.ping.count_n", n=count)


def render(result, target):
    echo = result.echo
    rtt = "" if echo.rtt_ms is None else f"{ping.rtt_number(echo.rtt_ms)} ms"
    words = say(ping.result_words(echo))
    if ping.answered_by_other(echo, target):
        words = T("tools.ping.result.from", result=words, address=echo.reply_from)
    return (result.seq, time.strftime("%H:%M:%S", time.localtime(result.sent)), rtt,
            "" if echo.ttl is None else echo.ttl, words)


def _stats_words(head, stats, short=False):
    """``head`` and what ``stats`` adds to it: the longest run of losses (from two in a
    row - one lost ping is no burst), the round trips, and the replies that came back
    changed. ``short`` leaves the lowest and highest round trip to the copied results:
    a part's line also says how it differs from the part before, and with them it took
    three lines at 760 px in Polish and English (rendered)."""
    words = [head]
    if stats.longest_loss >= 2:
        words.append(T("tools.ping.summary_streak", n=stats.longest_loss))
    trips = stats.round_trips()
    if trips:
        low, avg, high = (ping.rtt_number(v) for v in trips)
        jitter = stats.jitter()
        said = {"avg": avg, "jitter": "-" if jitter is None else ping.rtt_number(jitter),
                "p95": ping.rtt_number(stats.p95())}
        words.append(T("tools.ping.part.rtt", **said) if short
                     else T("tools.ping.summary_rtt", low=low, high=high, **said))
    if stats.changed:
        words.append(T("tools.ping.summary_changed", n=stats.changed))
    return " ".join(words)


def _against(now, before):
    """How the part now differs from the one before it, or "" while either has nothing
    counted to differ by."""
    if not now.stats.sent or not before.stats.sent:
        return ""
    what = T(f"tools.ping.part.{before.kind}")
    loss = f"{now.stats.lost_pct() - before.stats.lost_pct():+.1f}"
    now_avg, before_avg = now.stats.average(), before.stats.average()
    if now_avg is None or before_avg is None:
        return T("tools.ping.part.against_loss", what=what, d_loss=loss)
    return T("tools.ping.part.against", what=what, d_rtt=f"{round(now_avg - before_avg):+d}",
             d_loss=loss)


def summary_text(run):
    """The line under the status: the run's numbers - or, once the session changed
    during the run, the part it is in now and how it differs from the part before (an
    average across a change says nothing; ``nettools/ping.py``)."""
    if run is None or not run.sent:
        return ""
    if len(run.parts) < 2:
        total = run.total
        return _stats_words(T("tools.ping.summary", sent=total.sent, replies=total.replies,
                              lost=total.lost, pct=f"{total.lost_pct():.1f}"), total)
    now, before = run.parts[-1], run.parts[-2]
    stats = now.stats
    head = T("tools.ping.part.now",
             time=time.strftime("%H:%M:%S", time.localtime(now.started)),
             what=T(f"tools.ping.part.{now.kind}"), sent=stats.sent, lost=stats.lost,
             pct=f"{stats.lost_pct():.1f}")
    against = _against(now, before)
    return _stats_words(head, stats, short=True) + (" " + against if against else "")


def sort_key(result, column):
    echo = result.echo
    return {"seq": result.seq, "sent": result.sent,
            "rtt": -1 if echo.rtt_ms is None else echo.rtt_ms,
            "ttl": -1 if echo.ttl is None else echo.ttl,
            "result": result.kind}[column]


class PingRun:
    """The window's ping: one run at a time, and the panel that shows it, if any."""

    def __init__(self, app):
        self.app = app
        self.job = job(app, ID)
        self.run = None             # ping.Run, the last one started
        self.running = False
        self.session = None         # the last session line's key, or None
        self.stopped_at = None
        self._timer = None
        self._view = None           # weakref to the panel drawing this run
        self.poller = Poller(app.root, self.job, self._on_outcome)

    # -- asked by the panel ---------------------------------------------------- #
    def watch(self, panel):
        self._view = weakref.ref(panel) if panel is not None else None

    def start(self, target, every_s, wait_s, size=ping.DEFAULT_SIZE, count=ping.DEFAULT_COUNT):
        self.stop()
        self.run = ping.Run(target, every_s, wait_s, size=size, count=count)
        self.running = True
        self.session = None
        self.stopped_at = None
        self._send()

    def stop(self):
        if self.running:
            self.stopped_at = time.time()
        self.running = False
        self._cancel()
        self._changed()

    # -- the run --------------------------------------------------------------- #
    def _send(self):
        self._timer = None
        if not self.running:
            return
        run = self.run
        mark = self._mark()
        self.job.run(START if not run.target.address else ECHO,
                     lambda: _one(run, lambda: self._wanted(run), mark))
        self.poller.start()
        self._changed()

    def _mark(self):
        """The session's mark now (``engine.session_mark``): which part a ping is in."""
        with crashlog.quiet(AREA):
            return self.app.engine.session_mark()
        return None

    def _wanted(self, run):
        """WORKER: whether ``run`` may still send - it is this window's run and Stop has
        not been pressed. Two reads of fields only the UI thread writes."""
        return self.running and self.run is run

    def _on_outcome(self, outcome):
        if outcome.error:
            # A fault of the program, not an answer (``_one`` catches the refusals and
            # ``icmp.echo`` never raises): said on the status line, and the run stops.
            self.running = False
            self._cancel()
            self._changed(outcome)
            return
        run, sent_at, target, answer, mark = outcome.value
        if run is not self.run:
            # The answer to the last request of a run replaced since: the worker
            # delivers it before it starts the new run's first one.
            return
        if answer is None:
            # Stopped before it went (``_one``): nothing was sent, nothing to show.
            return
        if isinstance(answer, Refused):
            # Only a name lookup refuses: no address, nothing sent, the run ends.
            self.running = False
            self._changed(answer)
            return
        run.target = target
        run.add(sent_at, answer, mark, self._mark())
        self.session = self._session_words(target)
        if self.running and run.done():
            # The number of pings asked for: the run ends on its last answer.
            self.running = False
            self.stopped_at = time.time()
        if self.running:
            delay = run.next_at(sent_at, time.time()) - time.time()
            with crashlog.quiet(AREA):
                self._timer = self.app.root.after(max(0, round(delay * 1000)), self._send)
        self._changed()

    def _session_words(self, target):
        """What the session is doing to these pings, from the engine's own log of
        what it captured and impaired - never guessed from the settings."""
        if not self.app.running:
            return "tools.ping.session.none"
        key = ("ICMP", target.address.split("%")[0])
        with crashlog.quiet(AREA):
            return SESSION_WORDS[self.app.engine.flow_scope(key)]
        return None

    def _cancel(self):
        if self._timer is not None:
            with crashlog.quiet(AREA):
                self.app.root.after_cancel(self._timer)
            self._timer = None

    def _changed(self, problem=None):
        panel = self._view() if self._view else None
        if panel is not None:
            with crashlog.quiet(AREA):
                panel.changed(problem)


def _one(run, wanted, mark):
    """WORKER: the run's next request - with the name looked up first, the first time.
    ``(run, sent_at, target, Echo or Refused, mark)``; the time is taken here, the
    moment before the request goes, because a request asked for while the last one of
    a replaced run still waits starts only when that one is answered. The Echo is
    ``None`` when ``wanted()`` said Stop came first (README, "Tools": from Start to
    Stop). ``mark`` - the session's when the request was asked for - only rides along
    to the answer."""
    sent_at = time.time()
    try:
        target, echo = ping.start_and_send(run.target, run.wait_s, wanted=wanted,
                                           size=run.size)
    except Refused as refused:
        return run, sent_at, run.target, refused, mark
    return run, sent_at, target, echo, mark


_RUNS: "weakref.WeakKeyDictionary[object, PingRun]" = weakref.WeakKeyDictionary()


def window_run(app):
    """This window's ping run (created on first use, kept across rebuilds)."""
    if app not in _RUNS:
        _RUNS[app] = PingRun(app)
    return _RUNS[app]


def offered(remote_ip):
    """Whether a row menu offers "Ping this address" for a row's remote address."""
    if not capabilities.available("ping"):
        return False
    try:
        return bool(remote_ip) and bool(ping.parse(str(remote_ip)).address)
    except Refused:
        return False


def ping_from(app, address):
    """A row menu's "Ping this address": this tool on screen, pinging the address."""
    app.select_page("tools")
    page = app.pages["tools"]
    page.select(PingPanel.ID)
    panel = page.panels.get(PingPanel.ID)
    if isinstance(panel, PingPanel):
        panel.ping(str(address))


class PingPanel:
    ID = ID
    LABEL = "tools.ping.tab"
    # Asked by the shared "not available" panel too (``gui/pages/toolbox.py``).
    help_keys = staticmethod(help_keys)

    def __init__(self, app, parent):
        self.app = app
        self.memory = remembered(app, self.ID)
        self.runner = window_run(app)
        self.frame = ttk.Frame(parent)
        self._drawn = None
        self._chart_drawn = None

        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        ttk.Label(bar, text=T("tools.ping.address")).pack(side="left")
        self.host = tk.StringVar(value=self.memory.get("host", ""))
        self.entry = ttk.Entry(bar, textvariable=self.host, width=CHARS["host"])
        self.entry.pack(side="left", padx=(space("tight"), space("inline")))
        self.entry.bind("<Return>", lambda _e: self._start_or_stop())
        add_tooltip(self.entry, "tips.tools_ping_address")
        self.start_btn = self._button(bar, "tools.ping.start", "tips.tools_ping_start",
                                      self._start_or_stop)
        self.copy_btn = self._button(bar, "tools.ping.copy", "tips.tools_ping_copy",
                                     self.copy_report)
        dialogs.help_button(bar, app.root, "tools.ping.help_title", help_keys(),
                            "tips.tools_ping_help").pack(side="right")

        options = ttk.Frame(self.frame)
        options.pack(fill="x", padx=space("page"), pady=(space("tight"), 0))
        self.every, self.every_box = self._choice(
            options, "tools.ping.every", ping.EVERY_S, "every", ping.DEFAULT_EVERY_S,
            "tips.tools_ping_every")
        self.wait, self.wait_box = self._choice(
            options, "tools.ping.wait", ping.WAIT_S, "wait", ping.DEFAULT_WAIT_S,
            "tips.tools_ping_wait")
        # The size is typed, not chosen: a packet size limit cuts at one byte (1372
        # bytes of data passed --max-size 1400 and 1373 did not), so the person needs
        # the exact number on either side of it. Checked at Start, like the address.
        ttk.Label(options, text=T("tools.ping.size")).pack(side="left")
        self.size = tk.StringVar(value=self.memory.get("size", str(ping.DEFAULT_SIZE)))
        self.size_entry = ttk.Entry(options, textvariable=self.size, width=CHARS["port"])
        self.size_entry.pack(side="left", padx=(space("tight"), 0))
        self.size_entry.bind("<Return>", lambda _e: self._start_or_stop())
        add_tooltip(self.size_entry, "tips.tools_ping_size")
        ttk.Label(options, text=T("tools.ping.bytes")).pack(side="left",
                                                             padx=(space("hair"), space("row")))
        self.count, self.count_box = self._choice(
            options, "tools.ping.count", ping.COUNTS, "count", ping.DEFAULT_COUNT,
            "tips.tools_ping_count", text=count_text)

        self.status = StatusLine(self.frame)
        self.status.label.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        # Wrapped inside both page margins: a Polish summary is longer than the 760 px
        # window (``PAGE_WRAP_PAD``).
        self.session = wrapping_label(self.frame, "", pad=PAGE_WRAP_PAD)
        self.session.pack(fill="x", padx=space("page"), pady=(space("hair"), 0))
        self.summary = wrapping_label(self.frame, "", style="TLabel", pad=PAGE_WRAP_PAD)
        self.summary.pack(fill="x", padx=space("page"), pady=(space("hair"), 0))

        body = ttk.Frame(self.frame)
        body.pack(fill="both", expand=True, padx=space("page"),
                  pady=(space("row"), space("page")))
        box = ttk.LabelFrame(body, text=T("tools.ping.chart", n=ping.CHARTED))
        box.pack(side="right", fill="y", padx=(space("row"), 0))
        # The legend first, at the bottom: a shorter window shrinks the canvas, not
        # the legend (the TCP health chart's lesson).
        legend = ttk.Frame(box)
        legend.pack(side="bottom", fill="x", padx=space("tight"), pady=(0, space("tight")))
        for style, key in (("Swatch.Down.TLabel", "tools.ping.legend_rtt"),
                           ("Swatch.Lost.TLabel", "tools.ping.legend_lost")):
            ttk.Label(legend, text="  ", style=style).pack(side="left")
            ttk.Label(legend, text=T(key)).pack(side="left", padx=(space("tight"), space("row")))
        self.canvas = chart_canvas(box, size("side_chart"), size("chart"))
        self.canvas.pack(fill="both", expand=True, padx=space("tight"), pady=space("tight"))
        self.canvas.bind("<Configure>", lambda _e: self._draw())
        # The dashed line where the session changed has no legend entry: a third one
        # widened the box past the chart (299 px) or, in a second row, left the chart
        # 71 px tall at 760x678 (rendered). The tip and the help say what it is.
        add_tooltip(self.canvas, "tips.tools_ping_chart")
        # Sideways scrolling: a router's answer ("TTL expired on the way (from ...)")
        # is longer than the Result column at 760 px; widened, it scrolls instead of
        # squeezing the numbers. The copied results always carry it whole.
        self.table = SortableTree(
            body, COLUMNS, sort={"col": "", "reverse": False}, on_sort=lambda _s: self._show(),
            height=ROWS["table"], horizontal=True, min_chars=MIN_CHARS, tips=TIPS,
            tags=PING_COLORS, selectmode="browse", numeric=NUMERIC, centered=CENTERED,
            empty_text="tools.ping.empty")

        self.runner.watch(self)
        self.changed()

    # -- building ------------------------------------------------------------ #
    @staticmethod
    def _button(bar, text_key, tip_key, command):
        button = ttk.Button(bar, text=T(text_key), command=command)
        button.pack(side="left", padx=(0, space("inline")))
        add_tooltip(button, tip_key)
        return button

    def _choice(self, parent, label_key, values, name, default, tip_key, text=None):
        """A read-only box of fixed choices, remembered for the window."""
        text = text or pace_text
        shown = [text(v) for v in values]
        by_text = dict(zip(shown, values, strict=True))
        chosen = self.memory.get(name, default)
        var = tk.StringVar(value=text(chosen if chosen in values else default))
        ttk.Label(parent, text=T(label_key)).pack(side="left")
        box = ttk.Combobox(parent, textvariable=var, values=shown, state="readonly",
                           height=popdown_height(shown), width=popdown_width(shown, 0))
        box.pack(side="left", padx=(space("tight"), space("row")))
        box.bind("<<ComboboxSelected>>",
                 lambda _e: self.memory.__setitem__(name, by_text.get(var.get(), default)),
                 add="+")
        add_tooltip(box, tip_key)
        return (lambda: by_text.get(var.get(), default)), box

    # -- the page calls ------------------------------------------------------ #
    def refresh(self):
        """The tick, while this tool is on screen: draw what arrived while it was not."""
        if self._signature() != self._drawn:
            self._show()

    def pending(self):
        return self.runner.job.busy() and self.runner.run is not None \
            and self.runner.run.sent == 0

    def teardown(self):
        self.runner.watch(None)

    # -- asking -------------------------------------------------------------- #
    def ping(self, address):
        """A row menu's "Ping this address": that address, at the chosen pace, now."""
        self.host.set(address)
        self._start()

    def _start_or_stop(self):
        if self.runner.running:
            self.runner.stop()
        else:
            self._start()

    def _start(self):
        text = self.host.get()
        self.memory["host"] = text
        self.memory["size"] = self.size.get()
        try:
            target = ping.parse(text)
            size = ping.parse_size(self.size.get())
        except Refused as refused:
            self.status.refused(T(refused.user_key, **refused.user_args))
            return
        self.runner.start(target, self.every(), self.wait(), size, self.count())

    # -- answers ------------------------------------------------------------- #
    def changed(self, problem=None):
        """The run moved on - or ended on a ``Refused`` name or a failed ``Outcome``:
        drawn now if on screen, else at the next look (``refresh``)."""
        if isinstance(problem, Refused):
            self.status.refused(T(problem.user_key, **problem.user_args))
        elif problem is not None:
            self.status.show(problem)
        if problem is not None or self._on_screen():
            self._show(keep_status=problem is not None)

    def _on_screen(self):
        # The page is None while a rebuild builds it - and builds this panel, the
        # first tab, inside its constructor - when no page is current either: `None is
        # None` took this tool down on every language change (caught by the GUI tests).
        page = self.app.pages.get("tools")
        return (page is not None and self.app.current_page() is page
                and page.current() == self.ID)

    def _signature(self):
        runner = self.runner
        run = runner.run
        return (id(run), run.sent if run else 0, runner.running, runner.session,
                self.table.sort["col"], self.table.sort["reverse"])

    def _show(self, keep_status=False):
        runner, run = self.runner, self.runner.run
        self._drawn = self._signature()
        self._sync_controls()
        if not keep_status:
            self._show_status()
        self.session.config(text=T(runner.session) if runner.session and run else "")
        self.summary.config(text=summary_text(run))
        results = list(run.results) if run else []
        sort = self.table.sort
        if sort["col"] in COLUMNS:
            results.sort(key=lambda r: sort_key(r, sort["col"]), reverse=sort["reverse"])
        else:
            results.reverse()       # the newest on top: it is what a live view reads
        target = run.target if run else None
        self.table.set_model(results, render=lambda r: render(r, target),
                             key_of=lambda r: r.seq, tag_of=lambda r: r.kind)
        self._draw()

    def _show_status(self):
        runner, run = self.runner, self.runner.run
        if run is None or (not runner.running and not run.sent):
            # Nothing was sent (a name that was not found): nothing to report.
            self.status.label.config(text="", style="Muted.TLabel")
            return
        target = run.target
        named = (T("tools.ping.named", name=target.typed, address=target.address)
                 if target.name and target.address else target.typed)
        if runner.running:
            at = time.strftime("%H:%M:%S", time.localtime(run.started))
            text = (T("tools.ping.status_running", target=named, every=pace_text(run.every_s),
                      time=at) if target.address else T("tools.ping.status_lookup",
                                                         name=target.typed))
        else:
            at = time.strftime("%H:%M:%S", time.localtime(runner.stopped_at or time.time()))
            text = (T("tools.ping.status_done", n=run.sent, target=named, time=at)
                    if run.done() else T("tools.ping.status_stopped", target=named, time=at))
        self.status.label.config(text=text, style="Muted.TLabel")

    def _draw(self):
        """The last pings' round trips - redrawn only when they or the size changed."""
        run = self.runner.run
        values = run.chart() if run else []
        changes = run.chart_changes() if run else []
        with crashlog.quiet(AREA):
            source = (self.canvas.winfo_width(), self.canvas.winfo_height(), tuple(values),
                      tuple(changes))
            if source != self._chart_drawn:
                draw_ping_chart(self.canvas, values, changes)
                self._chart_drawn = source

    def _sync_controls(self):
        running = self.runner.running
        self.start_btn.config(text=T("tools.ping.stop") if running else T("tools.ping.start"))
        for widget in (self.entry, self.size_entry):
            widget.state(["disabled"] if running else ["!disabled"])
        for box in (self.every_box, self.wait_box, self.count_box):
            box.state(["disabled"] if running else ["!disabled", "readonly"])
        self.copy_btn.state(["!disabled"] if self.runner.run and self.runner.run.sent
                            else ["disabled"])

    # -- the buttons -------------------------------------------------------- #
    def copy_report(self):
        run = self.runner.run
        if run and run.sent:
            copy_confirmed(self.app, ping.report(run), T("tools.ping.report_logged"), AREA)
