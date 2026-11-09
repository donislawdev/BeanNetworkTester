"""Tools tab: NAT and STUN - how does this network's router treat a call?

One Start runs the jobs of ``nettools/nat.py`` one after another, one worker run
each, and every job's rows go up as it ends: the public address and the NAT
mapping, the hairpin both at once and one side first, then the TURN server on
each transport. Ping's skeleton, its sibling in the network group: the two
servers, Start, Copy and "?" in one bar; the status, session and conclusion lines;
the table of facts the conclusion is drawn from.

A run belongs to the WINDOW (``NatRun``, kept against the App, like Ping's
``PingRun``): it takes a few seconds and must not stop half way because the
language changed - which rebuilds every panel - or another tab came to the front.
Its poll is on the root window for the same reason. Stop takes effect inside the
running job (``nettools.nat.Run.stop``): nothing more is sent after it.
"""
import time
import tkinter as tk
import weakref
from tkinter import ttk

from ... import crashlog
from ...i18n import T
from ...nettools import Refused, nat
from .. import dialogs
from ..clipboard import copy_confirmed
from ..labels import wrapping_label
from ..theme import CHARS, NAT_COLORS, PAGE_WRAP_PAD, ROWS, space
from ..tooltip import add_tooltip
from ..widgets import SortableTree
from ..widgets.sortable_tree import make_room
from .base import Poller, StatusLine, job, remembered

AREA = "gui.toolbox.nat"
ID = "nat"
STEP = "step"

COLUMNS = {"test": "tools.nat.col.test", "result": "tools.nat.col.result",
           "details": "tools.nat.col.details"}
TIPS = {"test": "tips.tools_nat_col_test", "result": "tips.tools_nat_col_result",
        "details": "tips.tools_nat_col_details"}
MIN_CHARS = {"details": CHARS["nat_details"]}


def help_keys() -> tuple[str, ...]:
    """The "?" sheet: what the tool shows, what each row means, what it cannot see."""
    return ("tools.nat.help_body", "tools.nat.help_rows", "tools.nat.help_limits")

# The servers a first Start asks (the owner's choice, 2026-11-09): Cloudflare lists
# its STUN server for use without an account, and its TURN server answers Binding
# on a second address and port, which the mapping test needs.
DEFAULT_STUN = "stun.cloudflare.com:3478"
DEFAULT_TURN = "turn.cloudflare.com"

# Which session line, by what the connection log says of this run's flows.
SESSION_NONE = "tools.nat.session.none"


def result_words():
    """Every word the Result and Test columns can show, for ``make_room``."""
    widest = {"transport": "UDP", "port": 65535, "address": "255.255.255.255"}
    return {"test": [T(key, **widest) for key in nat.ROW_NAMES.values()],
            "result": [T(key, **widest) for key in RESULT_KEYS]}


RESULT_KEYS = ("tools.nat.result.address", "tools.nat.result.independent",
               "tools.nat.result.by_address", "tools.nat.result.by_address_port",
               "tools.nat.result.works", "tools.nat.result.fails", "tools.nat.result.one_way",
               "tools.nat.result.answers", "tools.nat.result.no_answer",
               "tools.nat.result.no_address", "tools.nat.result.not_found",
               "tools.nat.result.not_turn", "tools.nat.result.refused",
               "tools.nat.result.not_checked")


class NatRun:
    """The window's NAT and STUN run: one at a time, and the panel that shows it."""

    def __init__(self, app):
        self.app = app
        self.job = job(app, ID)
        self.run = None             # nettools.nat.Run, the last one started
        self.rows = []              # its rows as shown, the not-checked ones last
        self.session = None         # the session line's key, or None
        self.finished = None        # time.time() at the end of the run
        self.problem = None         # an Outcome that failed: the program's fault
        self._view = None
        self.poller = Poller(app.root, self.job, self._on_outcome)

    # -- asked by the panel ---------------------------------------------------- #
    def watch(self, panel):
        self._view = weakref.ref(panel) if panel is not None else None

    def running(self):
        return self.run is not None and self.finished is None

    def start(self, stun_server, turn_server):
        if self.running():
            return
        self.run = nat.Run(stun_server, turn_server)
        self.rows, self.session, self.finished, self.problem = [], None, None, None
        self._next()

    def stop(self):
        if not self.running():
            return
        self.run.stop()
        if not self.job.busy():
            self._finish()
        self._changed()

    # -- the run --------------------------------------------------------------- #
    def _next(self):
        run = self.run
        if run.done():
            self._finish()
            return
        self.job.run(STEP, lambda: (run, run.step(lambda: self.run is run)))
        self.poller.start()
        self._changed()

    def _on_outcome(self, outcome):
        run = self.run
        if outcome.error:
            # A fault of the program, not an answer (the jobs turn every refusal of
            # the system into a row): said on the status line, and the run ends.
            self.problem = outcome
            if run is not None:
                run.stop()
            self._finish()
            return
        done_run, rows = outcome.value
        if done_run is not run:
            return                  # the last job of a run replaced since
        self.rows.extend(rows)
        self.session = self._session_words(run)
        self._next()

    def _finish(self):
        if self.finished is not None:
            return
        if self.run.stopped:
            # Read here, once the job that was running has delivered: the rows no job
            # gave say they were not checked, instead of the table just ending.
            self.rows.extend(self.run.not_checked())
        self.finished = time.time()
        self._changed()

    def _session_words(self, run):
        """What the session is doing to this run's packets, from the engine's own log
        of what it captured and impaired - never guessed from the settings."""
        if not self.app.running:
            return SESSION_NONE
        with crashlog.quiet(AREA):
            scopes = [self.app.engine.flow_scope(key) for key in sorted(run.flows)]
            if any(scope is True for scope in scopes):
                return "tools.nat.session.impaired"
            if all(scope is None for scope in scopes):
                return "tools.nat.session.not_captured"
            return "tools.nat.session.outside"
        return None

    def _changed(self):
        panel = self._view() if self._view else None
        if panel is not None:
            with crashlog.quiet(AREA):
                panel.changed()


_RUNS: "weakref.WeakKeyDictionary[object, NatRun]" = weakref.WeakKeyDictionary()


def window_run(app):
    """This window's run (created on first use, kept across rebuilds)."""
    if app not in _RUNS:
        _RUNS[app] = NatRun(app)
    return _RUNS[app]


class NatPanel:
    ID = ID
    LABEL = "tools.nat.tab"
    # Asked by the shared "not available" panel too (``gui/pages/toolbox.py``).
    help_keys = staticmethod(help_keys)

    def __init__(self, app, parent):
        self.app = app
        self.memory = remembered(app, self.ID)
        self.runner = window_run(app)
        self.frame = ttk.Frame(parent)
        self._drawn = None

        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        self.stun, self.stun_entry = self._server(bar, "tools.nat.stun", "stun", DEFAULT_STUN,
                                                  "tips.tools_nat_stun")
        self.turn, self.turn_entry = self._server(bar, "tools.nat.turn", "turn", DEFAULT_TURN,
                                                  "tips.tools_nat_turn")
        self.start_btn = self._button(bar, "tools.nat.start", "tips.tools_nat_start",
                                      self._start_or_stop)
        self.copy_btn = self._button(bar, "tools.nat.copy", "tips.tools_nat_copy",
                                     self.copy_report)
        dialogs.help_button(bar, app.root, "tools.nat.help_title", help_keys(),
                            "tips.tools_nat_help").pack(side="right")

        self.status = StatusLine(self.frame)
        self.status.label.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        self.session = wrapping_label(self.frame, "", pad=PAGE_WRAP_PAD)
        self.session.pack(fill="x", padx=space("page"), pady=(space("hair"), 0))
        # The conclusion in plain words: what the person came for.
        self.summary = wrapping_label(self.frame, "", style="TLabel", pad=PAGE_WRAP_PAD)
        self.summary.pack(fill="x", padx=space("page"), pady=(space("hair"), 0))

        body = ttk.Frame(self.frame)
        body.pack(fill="both", expand=True, padx=space("page"),
                  pady=(space("row"), space("page")))
        # Sideways scrolling, as Ping's table: a detail longer than its column scrolls
        # instead of squeezing the other two. The copied results carry it whole.
        self.table = SortableTree(
            body, COLUMNS, sort={"col": "", "reverse": False}, on_sort=lambda _s: self._show(),
            height=ROWS["table"], horizontal=True, min_chars=MIN_CHARS, tips=TIPS,
            tags=NAT_COLORS, selectmode="browse", empty_text="tools.nat.empty")
        make_room(self.table, result_words())

        self.runner.watch(self)
        self.changed()

    # -- building ------------------------------------------------------------ #
    @staticmethod
    def _button(bar, text_key, tip_key, command):
        button = ttk.Button(bar, text=T(text_key), command=command)
        button.pack(side="left", padx=(0, space("inline")))
        add_tooltip(button, tip_key)
        return button

    def _server(self, bar, label_key, name, default, tip_key):
        """A server box with its label, remembered for the window (not in ui.json)."""
        ttk.Label(bar, text=T(label_key)).pack(side="left")
        var = tk.StringVar(value=self.memory.get(name, default))
        entry = ttk.Entry(bar, textvariable=var, width=CHARS["host"])
        entry.pack(side="left", padx=(space("tight"), space("inline")))
        entry.bind("<Return>", lambda _e: self._start_or_stop())
        add_tooltip(entry, tip_key)
        return var, entry

    # -- the page calls ------------------------------------------------------ #
    def refresh(self):
        """The tick, while this tool is on screen: draw what arrived while it was not."""
        if self._signature() != self._drawn:
            self._show()

    def pending(self):
        return self.runner.job.busy() and not self.runner.rows

    def teardown(self):
        self.runner.watch(None)

    # -- asking -------------------------------------------------------------- #
    def _start_or_stop(self):
        if self.runner.running():
            self.runner.stop()
        else:
            self._start()

    def _start(self):
        self.memory["stun"] = self.stun.get()
        self.memory["turn"] = self.turn.get()
        try:
            stun_server = nat.parse_server(self.stun.get(), "stun")
            turn_server = nat.parse_server(self.turn.get(), "turn")
        except Refused as refused:
            self.status.refused(T(refused.user_key, **refused.user_args))
            return
        self.runner.start(stun_server, turn_server)

    def copy_report(self):
        run = self.runner.run
        if run is not None and self.runner.rows:
            copy_confirmed(self.app, nat.report(run, self.runner.rows),
                           T("tools.nat.report_logged"), AREA)

    # -- answers ------------------------------------------------------------- #
    def changed(self):
        """The run moved on: drawn now if on screen, else at the next look."""
        if self._on_screen() or self.runner.problem is not None:
            self._show()

    def _on_screen(self):
        page = self.app.pages.get("tools")
        return (page is not None and self.app.current_page() is page
                and page.current() == self.ID)

    def _signature(self):
        runner = self.runner
        return (id(runner.run), len(runner.rows), runner.finished, runner.session,
                runner.run.stopped if runner.run else None,
                self.table.sort["col"], self.table.sort["reverse"])

    def _show(self):
        runner = self.runner
        self._drawn = self._signature()
        self._sync_controls()
        self._show_status()
        self.session.config(text=T(runner.session) if runner.session else "")
        self.summary.config(text=" ".join(T(key) for key in nat.conclusion(runner.rows)))
        rows = list(enumerate(runner.rows))
        column = self.table.sort["col"]
        if column in COLUMNS:
            at = list(COLUMNS).index(column)
            rows.sort(key=lambda item: nat.words(item[1])[at], reverse=self.table.sort["reverse"])
        self.table.set_model(rows, render=lambda item: nat.words(item[1]),
                             key_of=lambda item: item[0],
                             tag_of=lambda item: "" if item[1].state == nat.OK else item[1].state)

    def _show_status(self):
        runner, run = self.runner, self.runner.run
        if runner.problem is not None:
            self.status.show(runner.problem)
            return
        if run is None:
            # A refusal of what was typed stays on the line until the next Start.
            return
        if runner.finished is None:
            at = time.strftime("%H:%M:%S", time.localtime(run.started))
            self.status.label.config(text=T("tools.nat.status_running", time=at),
                                     style="Muted.TLabel")
            return
        at = time.strftime("%H:%M:%S", time.localtime(runner.finished))
        text = (T("tools.nat.status_stopped", time=at) if run.stopped else
                T("tools.nat.status_done", time=at, s=f"{runner.finished - run.started:.1f}"))
        self.status.label.config(text=text, style="Muted.TLabel")

    def _sync_controls(self):
        runner = self.runner
        running = runner.running()
        stopping = running and runner.run.stopped
        self.start_btn.config(text=T("tools.nat.stop") if running else T("tools.nat.start"))
        self.start_btn.state(["disabled"] if stopping else ["!disabled"])
        for entry in (self.stun_entry, self.turn_entry):
            entry.state(["disabled"] if running else ["!disabled"])
        self.copy_btn.state(["!disabled"] if runner.rows and not running else ["disabled"])
