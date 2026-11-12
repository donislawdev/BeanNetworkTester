"""Tools tab: is a port free? The answer is computed in ``nettools/portcheck.py``.

Type the ports a program needs - one, a list, a range, in the Control page's port
language - or press "All ports", and read, per protocol and IP version, whether a
program could take each: free, held by which program and where it waits, or set
aside by Windows. Checked when asked (the button, or Enter), never while typing:
every port is 262 140 binds, and a table that re-checked itself under the pointer
would be read wrong.

One check at a time: while one runs its button is Stop, and Enter does nothing, so
nothing is queued behind the worker (the socket table's reason,
``gui/toolbox/sockets.py``). How far it is comes from the check itself
(``portcheck.Progress``) and is shown at the page's tick. Sorting is done here, on
the UI thread: ports next to each other that answered the same are one row, so
every port of a machine is a few hundred rows.
"""
import time
import tkinter as tk
from tkinter import ttk

from ... import winenv
from ...i18n import T
from ...nettools import portcheck
from .. import csv_export, dialogs
from ..field_actions import leave_process_alone
from ..labels import wrapping_label
from ..theme import (CHARS, PAGE_WRAP_PAD, PORT_COLORS, ROWS, set_menu_entry_available, space,
                     style_menu)
from ..tooltip import add_tooltip
from ..widgets import SortableTree
from .base import Poller, StatusLine, job, remembered
from ... import crashlog

AREA = "gui.toolbox.portcheck"

# The port first: it is what was asked, and each port has up to four rows. Then the
# answer, and who holds it - name and PID in ONE cell, "node.exe (1234)": two
# holders of one port in two columns ("a, b" | "1, 2") lose which PID is whose,
# and a right-aligned PID as the last column sat on the table's border (render,
# 2026-09-24). Where the holder waits comes last: it is read about a held port.
COLUMNS = {"port": "tools.portcheck.col.port", "proto": "conns.proto",
           "family": "tools.portcheck.col.family", "verdict": "tools.portcheck.col.verdict",
           "holder": "tools.portcheck.col.holder", "listens": "tools.portcheck.col.listens"}
TIPS = {column: f"tips.tools_portcheck_col_{column}" for column in COLUMNS}
NUMERIC = frozenset({"port"})
CENTERED = frozenset({"proto", "family"})
MIN_CHARS = {"port": CHARS["port"], "proto": CHARS["proto"], "family": CHARS["proto"],
             "verdict": CHARS["verdict"], "holder": CHARS["process"],
             "listens": CHARS["adapter"]}

CHECK = "check"
PROTOCOL_NAMES = {"TCP": "tools.portcheck.tcp", "UDP": "tools.portcheck.udp"}
FAMILY_NAMES = {4: "tools.portcheck.ipv4", 6: "tools.portcheck.ipv6"}
VERDICT_TEXT = "tools.portcheck.verdict.{verdict}"
# The Listens on column's words, by ``portcheck.listens_on`` kind; an adapter and an
# address are shown as they are.
PLACE_WORDS = {portcheck.ANYWHERE: "tools.portcheck.listens.any",
               portcheck.THIS_COMPUTER: "tools.portcheck.listens.loopback",
               portcheck.CONNECTION: "tools.portcheck.listens.connection"}
# Row colour by verdict (``theme.PORT_COLORS``); a free row has none.
ROW_TAGS = {portcheck.IN_USE: "blocked", portcheck.UNSEEN: "blocked",
            portcheck.RESERVED: "blocked", portcheck.DENIED: "blocked",
            portcheck.CLOSING: "unsure", portcheck.FAILED: "unsure",
            portcheck.UNREAD: "unsure"}

# Menu entries a row may be refused, by position (0 is "Copy", 1 the separator).
NEEDS_NAME = (2, 3)         # target / leave alone: the holder's process name


def render(row, names=None):
    """One row's cells, in ``COLUMNS`` order. Called only for the rows on screen.
    ``names``: the check's adapter names (``portcheck.Check.names``)."""
    port = row.port if row.last == row.port else f"{row.port}-{row.last}"
    return (port, row.proto, T(FAMILY_NAMES[row.family]),
            T(VERDICT_TEXT.format(verdict=row.verdict), code=row.code),
            ", ".join(filter(None, (_holder_text(pid, name) for pid, name in row.owners))),
            listens_text(row, names))


def listens_text(row, names=None):
    """Where the holders wait, in the window's words: "all networks", an adapter's
    name, "this computer"... - "" for a port nobody holds."""
    return ", ".join(T(PLACE_WORDS[kind]) if kind in PLACE_WORDS else value
                     for kind, value in portcheck.listens_on(row, names))


def _holder_text(pid, name):
    if name and pid is not None:
        return T("tools.portcheck.holder", name=name, pid=pid)
    if pid is not None:
        return T("tools.portcheck.holder_pid", pid=pid)
    return name        # another account's socket, off Windows: no PID given


def holder(row):
    """The first holder with a name, or "" - what the row menu acts on."""
    return next((name for _pid, name in row.owners if name), "") if row else ""


def progress_text(progress):
    """The status line while a check runs: where it is and how much is done."""
    if progress.stopped:
        return T("tools.portcheck.stopping")
    if progress.at is None:
        return T("tools.common.working")
    proto, family, port = progress.at
    return T("tools.portcheck.progress", proto=T(PROTOCOL_NAMES[proto]),
             family=T(FAMILY_NAMES[family]), port=port, percent=progress.percent())


class PortCheckPanel:
    ID = "portcheck"
    LABEL = "tools.portcheck.tab"

    def __init__(self, app, parent):
        self.app = app
        self.job = job(app, self.ID)
        self.memory = remembered(app, self.ID)
        self.frame = ttk.Frame(parent)
        self.ports = tk.StringVar(value=self.memory.get("ports", ""))
        # Every box ticked until the person unticks one: a range is set aside per
        # protocol and per IP version, and the one left out is the one that bites.
        self.protocols = {p: self._flag(f"proto_{p}") for p in portcheck.PROTOCOLS}
        self.families = {f: self._flag(f"family_{f}") for f in portcheck.FAMILIES}
        # Free rows shown until the person hides them: a port typed to be checked
        # must be able to read Free.
        self.hide_free = tk.BooleanVar(value=self.memory.get("hide_free", "") == "1")

        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        ttk.Label(bar, text=T("tools.portcheck.ports")).pack(side="left")
        self.entry = ttk.Entry(bar, textvariable=self.ports, width=CHARS["ports"])
        self.entry.pack(side="left", padx=(space("tight"), space("inline")))
        self.entry.bind("<KeyRelease>", self._typed)
        self.entry.bind("<Return>", self._check_key)
        add_tooltip(self.entry, "tips.tools_portcheck_ports")
        dialogs.help_button(bar, app.root, "tools.portcheck.help_title",
                            "tools.portcheck.help_body", "tips.tools_portcheck_help").pack(
            side="left", padx=(0, space("inline")))
        self.check_btn = ttk.Button(bar, text=T("tools.portcheck.check"),
                                    command=self._check_or_stop)
        self.check_btn.pack(side="left")
        add_tooltip(self.check_btn, "tips.tools_portcheck_check")
        self.all_btn = ttk.Button(bar, text=T("tools.portcheck.all"), command=self.check_all)
        self.all_btn.pack(side="left", padx=(space("inline"), 0))
        add_tooltip(self.all_btn, "tips.tools_portcheck_all")
        self.count = ttk.Label(bar, text="", style="Muted.TLabel")
        self.count.pack(side="right")

        boxes = ttk.Frame(self.frame)
        boxes.pack(fill="x", padx=space("page"), pady=(space("tight"), 0))
        for proto, var in self.protocols.items():
            self._box(boxes, var, PROTOCOL_NAMES[proto], "tips.tools_portcheck_protocol",
                      f"proto_{proto}")
        for family, var in self.families.items():
            self._box(boxes, var, FAMILY_NAMES[family], "tips.tools_portcheck_family",
                      f"family_{family}")
        hide = ttk.Checkbutton(boxes, text=T("tools.portcheck.hide_free"),
                               variable=self.hide_free, command=self._hide_free_ticked)
        hide.pack(side="left", padx=(space("row"), space("inline")))
        add_tooltip(hide, "tips.tools_portcheck_hide_free")
        self.export_btn = ttk.Button(boxes, text=T("tools.portcheck.export"),
                                     command=self._export)
        self.export_btn.pack(side="right")
        add_tooltip(self.export_btn, "tips.tools_portcheck_export")

        self.status = StatusLine(self.frame)
        self.status.label.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        # What was checked, what was left out, or how old the rows are.
        self.note = wrapping_label(self.frame, "", pad=PAGE_WRAP_PAD)
        self.note.pack(fill="x", padx=space("page"), pady=(space("hair"), 0))

        holder_frame = ttk.Frame(self.frame)
        holder_frame.pack(fill="both", expand=True, padx=space("page"),
                          pady=(space("tight"), space("page")))
        column, reverse = self._sort()
        self.table = SortableTree(holder_frame, COLUMNS, sort={"col": column, "reverse": reverse},
                                  on_sort=self._on_sort, height=ROWS["table"],
                                  horizontal=True, min_chars=MIN_CHARS, tips=TIPS,
                                  tags=PORT_COLORS, numeric=NUMERIC, centered=CENTERED,
                                  empty_text="tools.portcheck.empty")
        self._build_menu()

        self.poller = Poller(self.frame, self.job, self._on_outcome)
        # What this window already knows is shown as it is. Nothing is checked until
        # asked: there is nothing to check before a port is typed.
        answer = self.job.value.get(CHECK)
        if answer is not None:
            self._show(answer)
        last = self.job.last.get(CHECK)
        if last is not None:
            self._show_status(last)
            if last.error:
                self._show_failure()
        if self.job.busy():
            self._say_progress()
            self.poller.start()
        self._sync_buttons()

    # -- building ------------------------------------------------------------ #
    def _flag(self, name):
        return tk.BooleanVar(value=self.memory.get(name, "1") == "1")

    def _box(self, parent, var, text_key, tip_key, name):
        box = ttk.Checkbutton(parent, text=T(text_key), variable=var,
                              command=lambda: self._ticked(name, var))
        box.pack(side="left", padx=(0, space("inline")))
        add_tooltip(box, tip_key)

    def _build_menu(self):
        self.menu = style_menu(tk.Menu(self.frame, tearoff=0))
        self.menu.add_command(label=T("menu.copy_row"), command=self._copy_rows)
        self.menu.add_separator()
        self.menu.add_command(label=T("menu.target_process"), command=self._target)
        self.menu.add_command(label=T("menu.leave_process_alone"), command=self._leave_alone)
        self.table.bind_row_menu(self._show_menu)

    # -- the page calls ------------------------------------------------------ #
    def refresh(self):
        """The tick, while this tab is on screen: how far a running check is."""
        self._say_progress()
        self._sync_buttons()

    def pending(self):
        """Take an answer that has arrived, and say whether one is still due."""
        return self.poller.now()

    def teardown(self):
        self.poller.cancel()

    # -- asking -------------------------------------------------------------- #
    def check(self):
        """Ask the system about the ports typed now (the button, or Enter)."""
        if not self._may_check():
            return
        try:
            matcher = portcheck.parse(self.ports.get())
        except ValueError as exc:
            self.status.refused(str(exc))
            return
        protocols, families = self._chosen()
        if not self._audit_allows(matcher, protocols, families):
            return
        progress = portcheck.Progress()
        self.job.run(CHECK, lambda: portcheck.with_adapter_names(
            portcheck.check(matcher, protocols, families, progress=progress)), progress)
        self.status.working()
        self._sync_buttons()
        self.poller.start()

    def check_all(self):
        """"All ports": 1-65535 typed into the box, and checked."""
        if self.job.busy():
            return
        self.ports.set(portcheck.ALL_PORTS)
        self._typed()
        self.check()

    def stop(self):
        """Stop the running check: what it checked so far is shown, said as such."""
        progress = self.job.progress.get(CHECK)
        if progress is None or not self.job.busy():
            return
        progress.stop()
        self._say_progress()
        self._sync_buttons()

    def _check_or_stop(self):
        if self.job.busy():
            self.stop()
        else:
            self.check()

    def _check_key(self, _event=None):
        # Enter only ever starts a check: a key pressed while typing must not stop one.
        self.check()
        return "break"

    def _audit_allows(self, matcher, protocols, families):
        """True to go on. On a Windows that writes every bind to its Security log, a
        check of more than ``portcheck.AUDIT_ASK_BINDS`` asks first: each port it
        checks is an entry there, and older entries make room for them. A Windows
        that will not say (no administrator rights) asks too, in words that say it
        may: the computers that log every connection by policy are the ones whose
        users have no administrator rights."""
        if not portcheck.WINDOWS:
            return True
        audited = winenv.binds_audited()
        if audited is False:
            return True
        binds = portcheck.planned(matcher, protocols, families)
        if binds <= portcheck.AUDIT_ASK_BINDS:
            return True
        title, body = (("tools.portcheck.audit_title", "tools.portcheck.audit_body")
                       if audited else ("tools.portcheck.audit_title_unknown",
                                        "tools.portcheck.audit_body_unknown"))
        return bool(dialogs.ask_yes_no(self.app.root, T(title), T(body, count=binds)))

    def _chosen(self):
        protocols = tuple(p for p, var in self.protocols.items() if var.get())
        families = tuple(f for f, var in self.families.items() if var.get())
        return protocols, families

    def _may_check(self):
        protocols, families = self._chosen()
        return (not self.job.busy() and bool(self.ports.get().strip())
                and bool(protocols) and bool(families))

    def _typed(self, _event=None):
        # Remembered at every key: a language change rebuilds the panel.
        self.memory["ports"] = self.ports.get()
        self._sync_buttons()

    def _ticked(self, name, var):
        self.memory[name] = "1" if var.get() else ""
        self._sync_buttons()

    def _hide_free_ticked(self):
        self.memory["hide_free"] = "1" if self.hide_free.get() else ""
        answer = self.job.value.get(CHECK)
        if answer is not None:
            self._show(answer)

    def _on_sort(self, sort):
        self.memory["sort"] = sort["col"]
        self.memory["reverse"] = "1" if sort["reverse"] else ""
        answer = self.job.value.get(CHECK)
        if answer is not None:
            self._show(answer)

    def _sort(self):
        column = self.memory.get("sort", portcheck.DEFAULT_SORT[0])
        if column not in COLUMNS:
            column = portcheck.DEFAULT_SORT[0]
        return column, bool(self.memory.get("reverse", ""))

    def _say_progress(self):
        progress = self.job.progress.get(CHECK)
        if self.job.busy():
            self.status.working(progress_text(progress) if progress is not None else None)

    # -- answers ------------------------------------------------------------- #
    def _on_outcome(self, outcome):
        self._show_status(outcome)
        if outcome.error:
            self._show_failure()
        else:
            self._show(outcome.value)
        self._sync_buttons()

    def _show_status(self, outcome):
        """Done, failed, or stopped: a stopped check is not "done", its table holds
        only the ports it checked."""
        if outcome.error or not outcome.value.stopped:
            self.status.show(outcome)
            return
        at = time.strftime("%H:%M:%S", time.localtime(outcome.finished))
        self.status.label.config(text=T("tools.portcheck.status_stopped", time=at),
                                 style="Muted.TLabel")

    def _show(self, answer):
        column, reverse = self._sort()
        rows = portcheck.sort(answer.rows, column, reverse)
        shown = [r for r in rows if r.verdict != portcheck.FREE] if self.hide_free.get() else rows
        self.table.set_empty_text("tools.portcheck.empty_all_free" if rows else
                                  "tools.portcheck.empty_stopped" if answer.stopped else
                                  "tools.portcheck.empty_unavailable")
        names = answer.names or {}
        self.table.set_model(shown, render=lambda r: render(r, names), key_of=lambda r: r.key,
                             tag_of=lambda r: ROW_TAGS.get(r.verdict, ""))
        taken, unknown = portcheck.not_free(rows), portcheck.unknown(rows)
        total = portcheck.checked(rows)
        self.count.config(text=T("tools.portcheck.count_unknown", taken=taken, unknown=unknown,
                                 total=total) if unknown
                          else T("tools.portcheck.count", taken=taken, total=total))
        self.note.config(text="\n".join(self._notes(answer, stale=self._check_failed())))

    def _check_failed(self):
        """The newest check failed, so the rows on screen are older than the last try."""
        last = self.job.last.get(CHECK)
        return bool(last is not None and last.error)

    def _notes(self, answer, stale=False):
        lines = []
        if stale:
            at = time.strftime("%H:%M:%S", time.localtime(answer.checked_at))
            lines.append(T("tools.portcheck.note_stale", time=at))
        lines.append(T("tools.portcheck.note_checked", ports=answer.asked,
                       what=", ".join([*answer.protocols,
                                       *(T(FAMILY_NAMES[f]) for f in answer.families)])))
        if answer.stopped:
            lines.append(self._stopped_note(answer))
        if answer.skipped_zero:
            lines.append(T("tools.portcheck.note_zero"))
        if answer.unavailable:
            lines.append(T("tools.portcheck.note_unavailable",
                           families=", ".join(T(FAMILY_NAMES[f]) for f in answer.unavailable)))
        if answer.unread:
            tables = ", ".join(T("tools.portcheck.table_name", proto=T(PROTOCOL_NAMES[p]),
                                 family=T(FAMILY_NAMES[f])) for p, f in answer.unread)
            lines.append(T("tools.portcheck.note_unread", tables=tables,
                           verdict=T(VERDICT_TEXT.format(verdict=portcheck.UNREAD))))
        return lines

    @staticmethod
    def _stopped_note(answer):
        if answer.stopped_at is None:
            return T("tools.portcheck.note_stopped_none")
        proto, family, port = answer.stopped_at
        return T("tools.portcheck.note_stopped", made=answer.made, planned=answer.planned,
                 proto=T(PROTOCOL_NAMES[proto]), family=T(FAMILY_NAMES[family]), port=port)

    def _show_failure(self):
        """The check failed: say so, and keep the last good rows with their age."""
        answer = self.job.value.get(CHECK)
        if answer is None:
            self.table.set_empty_text("tools.portcheck.empty_failed")
            self.table.set_model([], render=render, key_of=lambda r: r.key)
            self.note.config(text="")
            return
        self.note.config(text="\n".join(self._notes(answer, stale=True)))

    def _sync_buttons(self):
        busy = self.job.busy()
        progress = self.job.progress.get(CHECK)
        self.check_btn.config(text=T("tools.portcheck.stop") if busy
                              else T("tools.portcheck.check"))
        if busy:
            # Stop, until it has been pressed: then the check is ending by itself.
            stoppable = progress is not None and not progress.stopped
            self.check_btn.state(["!disabled"] if stoppable else ["disabled"])
        else:
            self.check_btn.state(["!disabled"] if self._may_check() else ["disabled"])
        protocols, families = self._chosen()
        self.all_btn.state(["!disabled"] if not busy and protocols and families
                           else ["disabled"])
        self.export_btn.state(["!disabled"] if self.job.value.get(CHECK) is not None
                              else ["disabled"])

    # -- the menu on a row ---------------------------------------------------- #
    def _selected(self):
        keys = self.table.selected_keys()
        return self.table.item_for_key(keys[0]) if keys else None

    def _show_menu(self, x_root, y_root):
        named = bool(holder(self._selected()))
        for index in NEEDS_NAME:
            with crashlog.quiet(AREA):
                set_menu_entry_available(self.menu, index, named)
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
        name = holder(self._selected())
        if name:
            self.app.set_target_expression(name)

    def _leave_alone(self):
        name = holder(self._selected())
        if name:
            leave_process_alone(self.app, name)

    def _export(self):
        """"Save CSV": the rows on screen - "Hide free ports" and the order as they
        are - read from what the window holds. The writer, or None when there is no
        check to save or an export was already running."""
        answer = self.job.value.get(CHECK)
        if answer is None:
            return None
        return csv_export.export_ports(self.app, list(self.table.items), answer.checked_at)
