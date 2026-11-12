"""Tools tab: which ports of another computer answer? Computed in ``nettools/portscan.py``.

Type an address or a name and the ports - in the Control page's port language, or
filled in by "Common ports", "Ports 1-1024" or "All ports" - tick TCP and UDP, and
press Scan. The rows say per port whether something answered: open, closed, no
answer, and why a port could not be asked.

A scan is two runs of the tool's worker (``ToolJob``, kept against the window like
Port check's, so a language change mid-scan rebuilds the panel and not the scan): the
PLAN - the name looked up, the ports listed, the pace chosen from where the computer
is - and the SCAN. Between the two, a scan that can take longer than ``ASK_OVER_S``
asks first, with how long it can take. While it runs the button is Stop, and how far
it is comes from the scan itself (``portscan.Progress``), shown at the page's tick.
Closing the window is a Stop as well (``stop_window``): the worker would outlive it.
"""
import time
import tkinter as tk
from tkinter import ttk

from ... import crashlog
from ...i18n import T, sentences
from ...nettools import Refused, portscan
from .. import csv_export, dialogs
from ..clipboard import copy_confirmed
from ..labels import wrapping_label
from ..theme import CHARS, PAGE_WRAP_PAD, ROWS, SCAN_COLORS, space, style_menu
from ..tooltip import add_tooltip
from ..widgets import SortableTree
from .base import Poller, StatusLine, job, remembered

AREA = "gui.toolbox.portscan"
ID = "portscan"
PLAN, SCAN = "plan", "scan"
# A scan that can take longer than this asks first (``portscan.estimate_s``, the
# slowest the first round can be): every port behind a router is about 1 h 42 min.
ASK_OVER_S = 300

COLUMNS = {"port": "tools.portscan.col.port", "proto": "conns.proto",
           "state": "tools.portscan.col.state", "service": "tools.portscan.col.service",
           "detail": "tools.portscan.col.detail"}
TIPS = {column: f"tips.tools_portscan_col_{column}" for column in COLUMNS}
NUMERIC = frozenset({"port"})
CENTERED = frozenset({"proto"})
MIN_CHARS = {"port": CHARS["port"], "proto": CHARS["proto"], "state": CHARS["verdict"],
             "service": CHARS["service"], "detail": CHARS["scan_detail"]}

PROTOCOL_NAMES = {portscan.TCP: "tools.portscan.tcp", portscan.UDP: "tools.portscan.udp"}
STATE_TEXT = "tools.portscan.state.{state}"
ROW_TAGS = {portscan.OPEN: "open", portscan.UNREACHABLE: "problem",
            portscan.DENIED: "problem", portscan.FAILED: "problem"}
# The buttons that fill the ports box, and what they type.
PRESETS = (("tools.portscan.common", "tips.tools_portscan_common", portscan.COMMON_TEXT),
           ("tools.portscan.well_known", "tips.tools_portscan_well_known", portscan.WELL_KNOWN),
           ("tools.portscan.all", "tips.tools_portscan_all", portscan.ALL_PORTS))
SESSION_NONE = "tools.portscan.session.none"


def help_keys() -> tuple[str, ...]:
    """The "?" sheet: what the tool asks, what each answer means, what it sends."""
    return ("tools.portscan.help_body", "tools.portscan.help_states",
            "tools.portscan.help_sends")


def render(row):
    """One row's cells, in ``COLUMNS`` order. Called only for the rows on screen."""
    return (portscan.port_text(row), row.proto, T(STATE_TEXT.format(state=row.state)),
            row.service, detail_text(row))


def detail_text(row):
    """What the port answered beside its state: a reply's size, an error number."""
    if row.reply:
        return T("tools.portscan.detail.reply", bytes=row.reply)
    if row.code and row.state != portscan.CLOSED and row.state != portscan.SILENT:
        return T("tools.portscan.detail.code", code=row.code)
    return ""


def duration_text(seconds):
    """"about 40 s", "about 55 min", "about 1 h 42 min" - in the window's words."""
    seconds = max(1, round(seconds))
    if seconds < 90:
        return T("tools.portscan.time.s", s=seconds)
    minutes = round(seconds / 60)
    if minutes < 90:
        return T("tools.portscan.time.min", min=minutes)
    return T("tools.portscan.time.h", h=minutes // 60, min=minutes % 60)


def progress_text(progress, now):
    """The status line while a scan runs: where it is, how much is done, the time left
    at the pace so far, and the open ports found."""
    if progress.stopped:
        return T("tools.portscan.stopping")
    if progress.at is None:
        return T("tools.common.working")
    proto, port = progress.at
    if progress.again:
        return T("tools.portscan.progress_again", count=progress.again,
                 percent=progress.percent())
    left = progress.left_s(now)
    said = T("tools.portscan.progress", proto=T(PROTOCOL_NAMES[proto]), port=port,
             percent=progress.percent(), opened=progress.opened)
    return said if left is None else sentences(
        (said, T("tools.portscan.left", time=duration_text(left))))


def stop_window(app):
    """The window is closing (``toolbox.stop_sending``): its scan sends nothing more."""
    progress = job(app, ID).progress.get(SCAN)
    if progress is not None:
        progress.stop()


class PortScanPanel:
    ID = ID
    LABEL = "tools.portscan.tab"
    # Asked by the shared "not available" panel too (``gui/pages/toolbox.py``).
    help_keys = staticmethod(help_keys)
    stop_window = staticmethod(stop_window)

    def __init__(self, app, parent):
        self.app = app
        self.job = job(app, self.ID)
        self.memory = remembered(app, self.ID)
        self.frame = ttk.Frame(parent)
        self.address = tk.StringVar(value=self.memory.get("address", ""))
        self.ports = tk.StringVar(value=self.memory.get("ports", portscan.COMMON_TEXT))
        # TCP ticked and UDP not until the person says otherwise: UDP is slower and
        # answers less (the help says why).
        self.protocols = {p: tk.BooleanVar(value=self.memory.get(f"proto_{p}",
                                                                 "1" if p == portscan.TCP else "")
                                           == "1") for p in portscan.PROTOCOLS}
        self.inputs = []
        self._build_bar()
        self._build_boxes()
        self.status = StatusLine(self.frame)
        self.status.label.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        self.session = wrapping_label(self.frame, "", pad=PAGE_WRAP_PAD)
        self.session.pack(fill="x", padx=space("page"), pady=(space("hair"), 0))
        # What the scan means, in plain words: what the person came for.
        self.summary = wrapping_label(self.frame, "", style="TLabel", pad=PAGE_WRAP_PAD)
        self.summary.pack(fill="x", padx=space("page"), pady=(space("hair"), 0))
        self.note = wrapping_label(self.frame, "", pad=PAGE_WRAP_PAD)
        self.note.pack(fill="x", padx=space("page"), pady=(space("hair"), 0))
        self._build_table()

        self.poller = Poller(self.frame, self.job, self._on_outcome)
        answer = self.job.value.get(SCAN)
        if answer is not None:
            self._show(answer)
        self._restore_status()
        if self.job.busy():
            self._say_progress()
            self.poller.start()
        self._sync_controls()

    # -- building ------------------------------------------------------------ #
    def _build_bar(self):
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        self.address_entry = self._entry(bar, "tools.portscan.address", self.address,
                                         CHARS["host"], "tips.tools_portscan_address")
        self.ports_entry = self._entry(bar, "tools.portscan.ports", self.ports,
                                       CHARS["ports"], "tips.tools_portscan_ports")
        dialogs.help_button(bar, self.app.root, "tools.portscan.help_title", help_keys(),
                            "tips.tools_portscan_help").pack(side="left",
                                                             padx=(0, space("inline")))
        self.scan_btn = ttk.Button(bar, text=T("tools.portscan.scan"),
                                   command=self._scan_or_stop)
        self.scan_btn.pack(side="left")
        add_tooltip(self.scan_btn, "tips.tools_portscan_scan")
        self.count = ttk.Label(bar, text="", style="Muted.TLabel")
        self.count.pack(side="right")

    def _entry(self, bar, label_key, var, width, tip_key):
        ttk.Label(bar, text=T(label_key)).pack(side="left")
        entry = ttk.Entry(bar, textvariable=var, width=width)
        entry.pack(side="left", padx=(space("tight"), space("inline")))
        entry.bind("<KeyRelease>", self._typed)
        entry.bind("<Return>", self._scan_key)
        add_tooltip(entry, tip_key)
        self.inputs.append(entry)
        return entry

    def _build_boxes(self):
        boxes = ttk.Frame(self.frame)
        boxes.pack(fill="x", padx=space("page"), pady=(space("tight"), 0))
        for text_key, tip_key, ports in PRESETS:
            button = ttk.Button(boxes, text=T(text_key),
                                command=lambda typed=ports: self._fill(typed))
            button.pack(side="left", padx=(0, space("inline")))
            add_tooltip(button, tip_key)
            self.inputs.append(button)
        for proto, var in self.protocols.items():
            box = ttk.Checkbutton(boxes, text=T(PROTOCOL_NAMES[proto]), variable=var,
                                  command=lambda p=proto, v=var: self._ticked(p, v))
            box.pack(side="left", padx=(space("row") if proto == portscan.TCP else 0,
                                        space("inline")))
            add_tooltip(box, f"tips.tools_portscan_{proto.lower()}")
            self.inputs.append(box)
        self.export_btn = ttk.Button(boxes, text=T("tools.portscan.export"),
                                     command=self._export)
        self.export_btn.pack(side="right")
        add_tooltip(self.export_btn, "tips.tools_portscan_export")
        self.copy_btn = ttk.Button(boxes, text=T("tools.portscan.copy"),
                                   command=self.copy_report)
        self.copy_btn.pack(side="right", padx=(0, space("inline")))
        add_tooltip(self.copy_btn, "tips.tools_portscan_copy")

    def _build_table(self):
        holder = ttk.Frame(self.frame)
        holder.pack(fill="both", expand=True, padx=space("page"),
                    pady=(space("tight"), space("page")))
        column, reverse = self._sort()
        self.table = SortableTree(holder, COLUMNS, sort={"col": column, "reverse": reverse},
                                  on_sort=self._on_sort, height=ROWS["table"],
                                  horizontal=True, min_chars=MIN_CHARS, tips=TIPS,
                                  tags=SCAN_COLORS, numeric=NUMERIC, centered=CENTERED,
                                  empty_text="tools.portscan.empty")
        self.menu = style_menu(tk.Menu(self.frame, tearoff=0))
        self.menu.add_command(label=T("menu.copy_row"), command=self._copy_rows)
        self.table.bind_row_menu(self._show_menu)

    # -- the page calls ------------------------------------------------------ #
    def refresh(self):
        """The tick, while this tab is on screen: how far a running scan is."""
        self._say_progress()
        self._sync_controls()

    def pending(self):
        """Take an answer that has arrived, and say whether one is still due."""
        return self.poller.now()

    def teardown(self):
        self.poller.cancel()

    # -- asking -------------------------------------------------------------- #
    def scan(self):
        """Read what was typed and plan the scan (the button, or Enter)."""
        if self.job.busy() or not self._may_scan():
            return
        try:
            target = portscan.parse_target(self.address.get())
            matcher = portscan.parse_ports(self.ports.get())
        except Refused as refused:
            self.status.refused(T(refused.user_key, **refused.user_args))
            return
        except ValueError as exc:
            self.status.refused(str(exc))
            return
        protocols = self._chosen()
        # No scan's progress while the plan is made: what is running now is the plan
        # (``_scanning``), and a window closed now has no scan to stop.
        self.job.progress.pop(SCAN, None)
        self.job.run(PLAN, lambda: portscan.plan(target, matcher, protocols))
        self.status.working(T("tools.portscan.planning"))
        self._sync_controls()
        self.poller.start()

    def stop(self):
        """Stop the running scan: what it asked so far is shown, said as such."""
        progress = self.job.progress.get(SCAN)
        if progress is None or not self.job.busy():
            return
        progress.stop()
        self._say_progress()
        self._sync_controls()

    def _scan_or_stop(self):
        if self.job.busy():
            self.stop()
        else:
            self.scan()

    def _scan_key(self, _event=None):
        # Enter only ever starts a scan: a key pressed while typing must not stop one.
        self.scan()
        return "break"

    def _start(self, scan_plan):
        """The plan is back: ask first when the scan can be long, then scan."""
        longest = portscan.estimate_s(scan_plan)
        if longest > ASK_OVER_S and not dialogs.ask_yes_no(
                self.app.root, T("tools.portscan.long_title"),
                T("tools.portscan.long_body", time=duration_text(longest),
                  ports=len(scan_plan.ports), protocols=", ".join(scan_plan.protocols),
                  address=scan_plan.target.address)):
            self.status.label.config(text=T("tools.portscan.not_started"), style="Muted.TLabel")
            return
        progress = portscan.Progress()
        self.job.run(SCAN, lambda: portscan.scan(scan_plan, progress), progress)
        self._say_progress()

    def _chosen(self):
        return tuple(p for p, var in self.protocols.items() if var.get())

    def _may_scan(self):
        return (bool(self.address.get().strip()) and bool(self.ports.get().strip())
                and bool(self._chosen()))

    def _fill(self, ports):
        """A preset button: the ports go into the box, where they can be read and
        changed before Scan."""
        self.ports.set(ports)
        self._typed()

    def _typed(self, _event=None):
        # Remembered at every key: a language change rebuilds the panel.
        self.memory["address"] = self.address.get()
        self.memory["ports"] = self.ports.get()
        self._sync_controls()

    def _ticked(self, proto, var):
        self.memory[f"proto_{proto}"] = "1" if var.get() else ""
        self._sync_controls()

    def _on_sort(self, sort):
        self.memory["sort"] = sort["col"]
        self.memory["reverse"] = "1" if sort["reverse"] else ""
        answer = self.job.value.get(SCAN)
        if answer is not None:
            self._show(answer)

    def _sort(self):
        column = self.memory.get("sort", portscan.DEFAULT_SORT[0])
        if column not in COLUMNS:
            column = portscan.DEFAULT_SORT[0]
        return column, bool(self.memory.get("reverse", ""))

    def _scanning(self):
        """The scan's progress while a scan runs; None while the plan is made, or idle."""
        return self.job.progress.get(SCAN) if self.job.busy() else None

    def _say_progress(self):
        if not self.job.busy():
            return
        progress = self._scanning()
        self.status.working(progress_text(progress, time.monotonic()) if progress is not None
                            else T("tools.portscan.planning"))

    # -- answers ------------------------------------------------------------- #
    def _on_outcome(self, outcome):
        if outcome.kind == PLAN:
            if outcome.error:
                self.status.show(outcome)
            else:
                self._start(outcome.value)
        else:
            self._show_status(outcome)
            if not outcome.error:
                self._show(outcome.value)
        self._sync_controls()

    def _restore_status(self):
        """A rebuilt panel says what the newest run said: the scan's end, or a plan
        that was refused after it (a name not found)."""
        scan_done, plan = self.job.last.get(SCAN), self.job.last.get(PLAN)
        if plan is not None and plan.error and (scan_done is None
                                                or plan.finished > scan_done.finished):
            self.status.show(plan)
        elif scan_done is not None:
            self._show_status(scan_done)

    def _show_status(self, outcome):
        if outcome.error:
            self.status.show(outcome)
            return
        answer = outcome.value
        at = time.strftime("%H:%M:%S", time.localtime(outcome.finished))
        text = (T("tools.portscan.status_stopped", time=at) if answer.stopped else
                T("tools.portscan.status_done", time=at, s=f"{answer.elapsed_s:.1f}"))
        self.status.label.config(text=text, style="Muted.TLabel")

    def _show(self, answer):
        column, reverse = self._sort()
        rows = portscan.sort(answer.rows, column, reverse)
        self.table.set_empty_text("tools.portscan.empty_stopped" if answer.stopped
                                  else "tools.portscan.empty")
        self.table.set_model(rows, render=render, key_of=lambda r: r.key,
                             tag_of=lambda r: ROW_TAGS.get(r.state, ""))
        total = portscan.counts(answer)
        sums = {state: sum(n for (_p, s), n in total.items() if s == state)
                for state in portscan.STATES}
        self.count.config(text=T("tools.portscan.count", open=sums[portscan.OPEN],
                                 silent=sums[portscan.SILENT], total=sum(total.values())))
        self.summary.config(text=sentences(T(key, **args)
                                           for key, args in portscan.conclusions(answer)))
        session = self._session_key(answer)
        self.session.config(text=T(session) if session else "")
        self.note.config(text="\n".join(self._notes(answer)))

    def _session_key(self, answer):
        """What the session did to this scan's packets, from the engine's own log of
        what it captured - never guessed from the settings (NAT's reading, the latest
        few flows of the scan)."""
        if not self.app.running:
            return SESSION_NONE
        if not answer.flows:
            return None
        with crashlog.quiet(AREA):
            scopes = [self.app.engine.flow_scope(key) for key in answer.flows]
            if any(scope is True for scope in scopes):
                return "tools.portscan.session.impaired"
            if all(scope is None for scope in scopes):
                return "tools.portscan.session.not_captured"
            return "tools.portscan.session.outside"
        return None

    def _notes(self, answer):
        scan_plan = answer.plan
        target = scan_plan.target
        lines = [T("tools.portscan.note_scanned", address=target.address,
                   ports=len(scan_plan.ports), protocols=", ".join(scan_plan.protocols))
                 + (" " + T("tools.portscan.note_name", name=target.typed) if target.name
                    else ""),
                 T("tools.portscan.note_near" if scan_plan.pace.near else "tools.portscan.note_far",
                   at_once=scan_plan.pace.at_once, rate=scan_plan.pace.per_second,
                   s=portscan.seconds_text(scan_plan.pace.wait_s))]
        if answer.stopped:
            lines.append(T("tools.portscan.note_stopped", made=answer.made,
                           planned=answer.planned))
        if scan_plan.skipped_zero:
            lines.append(T("tools.portscan.note_zero"))
        return lines

    def _sync_controls(self):
        busy = self.job.busy()
        progress = self._scanning()
        self.scan_btn.config(text=T("tools.portscan.stop") if busy else T("tools.portscan.scan"))
        if busy:
            # Stop, until it has been pressed; not while the plan is made (a name
            # looked up), which sends nothing to the computer and ends by itself.
            stoppable = progress is not None and not progress.stopped
            self.scan_btn.state(["!disabled"] if stoppable else ["disabled"])
        else:
            self.scan_btn.state(["!disabled"] if self._may_scan() else ["disabled"])
        for widget in self.inputs:
            widget.state(["disabled"] if busy else ["!disabled"])
        done = self.job.value.get(SCAN) is not None and not busy
        for button in (self.copy_btn, self.export_btn):
            button.state(["!disabled"] if done else ["disabled"])

    # -- the menu on a row, copying, saving ------------------------------------ #
    def _show_menu(self, x_root, y_root):
        try:
            self.menu.tk_popup(x_root, y_root)
        finally:
            with crashlog.quiet(AREA):
                self.menu.grab_release()

    def _copy_rows(self):
        text = self.table.copy_text()
        if text:
            self.app.copy_to_clipboard(text)

    def copy_report(self):
        answer = self.job.value.get(SCAN)
        if answer is not None and not self.job.busy():
            copy_confirmed(self.app, portscan.report(answer), T("tools.portscan.report_logged"),
                           AREA)

    def _export(self):
        """"Save CSV": the rows on screen, in their order. The writer, or None when
        there is no scan to save or an export was already running."""
        answer = self.job.value.get(SCAN)
        if answer is None:
            return None
        return csv_export.export_scan(self.app, list(self.table.items),
                                      answer.plan.target.address, answer.started)
