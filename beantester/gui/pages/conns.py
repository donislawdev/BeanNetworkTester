"""Connections page: the live connection table.

Notable behaviour:

* the search box is debounced (it used to re-filter and re-sort 1000 rows on
  every keystroke) and ``Esc`` clears it - the old "Clear" BUTTON next to it
  only ever emptied the search field, which is not worth a button;
* "Freeze" stops the rows (sorted by traffic) from moving out from under the
  pointer;
* the context menu feeds a row straight back into the targeting fields, and
  ``Ctrl+C`` copies the selected row(s);
* the process name comes from the ENGINE, resolved when the packet was captured
  - looking the port up at display time meant that any socket which had since
  closed showed as "?", which was most of them;
* idle/duration freeze when the session stops (the tester is not running, so
  nothing should keep ticking);
* the header says out loud what the table COVERS - and which of the four answers
  it is depends on the session, not on this page (see ``gui/scope.py``). It used
  to claim "ALL captured connections ... targeting decides what gets broken, not
  what gets seen" unconditionally, which is the opposite of the truth once the
  driver's own filter has been narrowed to the destination.
"""

import time
import tkinter as tk
from tkinter import ttk

from ...i18n import T
from ...matchers import add_term
from ...views import (avg_packet_bytes, connection_proc, filter_sort_connections,
                      traffic_totals)
from .. import dialogs
from ..model_worker import AsyncModel
from ..labels import wrapping_label
from ..scaling import scaled
from .. import scope
from ..theme import CONN_COLORS, style_menu
from ..tooltip import add_tooltip, retip
from ..widgets import SortableTree
from ... import crashlog

# This page's wording for each coverage state (gui/scope.py insists on all four).
SCOPE_NOTES = scope.keys_for_states({
    scope.ALL: "conns.scope_note",
    scope.CAPTURE: "conns.scope_note_capture",
    scope.CAPTURE_PROCESS: "conns.scope_note_capture_process",
    scope.VIEW: "conns.scope_note_scoped",
})

SCOPE_TIPS = scope.keys_for_states({
    scope.ALL: "tips.scope_note",
    scope.CAPTURE: "tips.scope_note_capture",
    scope.CAPTURE_PROCESS: "tips.scope_note_capture",
    scope.VIEW: "tips.scope_note_scoped",
})

COLUMNS = {"proc": "conns.process", "pid": "conns.pid", "proto": "conns.proto",
           "remote_ip": "conns.remote_ip", "remote_port": "conns.remote_port",
           "local_port": "conns.local_port", "packets": "conns.packets",
           "scoped": "conns.scoped", "dropped": "conns.dropped",
           "down": "conns.down", "up": "conns.up", "kb": "conns.kb",
           "down_seen": "conns.down_seen", "up_seen": "conns.up_seen",
           "avg": "conns.avg", "dur": "conns.time", "idle": "conns.idle"}

MIN_CHARS = {"proc": 16, "pid": 7, "proto": 5, "remote_ip": 18, "remote_port": 6,
             "local_port": 6, "packets": 7, "scoped": 7, "dropped": 8, "down": 8,
             "up": 8, "kb": 8, "down_seen": 11, "up_seen": 11,
             "avg": 7, "dur": 6, "idle": 6}

# One tooltip per COLUMN, shown next to its header. The old single tooltip hung
# on the whole tree, so it popped up over the rows and explained nothing about
# the column actually under the pointer.
COLUMN_TIPS = {"proc": "tips.col_process", "pid": "tips.col_pid",
               "proto": "tips.col_proto", "remote_ip": "tips.col_remote_ip",
               "remote_port": "tips.col_remote_port", "local_port": "tips.col_local_port",
               "packets": "tips.col_packets", "scoped": "tips.col_scoped",
               "dropped": "tips.col_dropped", "down": "tips.col_down",
               "up": "tips.col_up", "kb": "tips.col_kb",
               "down_seen": "tips.col_down_seen", "up_seen": "tips.col_up_seen",
               "avg": "tips.col_avg",
               "dur": "tips.col_dur", "idle": "tips.col_idle"}


def port_cell(port):
    """Text for a port cell: empty for traffic that has no ports (ICMP).

    Without this the value goes to Tk as ``None`` and renders as the literal
    string "None" - the connection log carries portless rows since ping traffic
    started reaching it.
    """
    return "" if port is None else port


SEARCH_DEBOUNCE_MS = 250
# The heavy part (filter + sort of the whole model) is throttled: the table is
# virtualised, so SCROLLING is free and instant no matter how big the model is,
# but re-sorting 200 000 rows on every 700 ms tick would burn ~15% of a core for
# nothing. A user-visible action (sorting, searching) always refreshes at once.
REBUILD_MS = 1000



def append_to_field(app, key, term, log_key):
    """Add one term to an expression field, keeping what is already there.

    The row actions build a field up click by click - block this address, then
    that one - so they append. Replacing would throw away what the previous click
    put there, which is the opposite of what the second click means.
    ``matchers.add_term`` owns the syntax (convention 10): it drops repeats, keeps
    the comma escape of a regex intact and never leaves an empty term behind.

    Like every other row action this only fills the form (convention 15): the
    running session hears about it through the same "apply needed" line, and
    nothing reaches the engine until the user presses Apply.

    It lives on the PAGE rather than on ``App`` for a measured reason: ``app.py``
    was already the largest module in the package and sits on the size ratchet in
    ``tests/test_code_shape.py``, which went red when these three helpers were
    added there. The ratchet's answer is to put code where it belongs rather than
    to raise the number, and a Connections row action belongs to the Connections
    page.
    """
    updated = add_term(app.vars[key].get(), term)
    app.vars[key].set(updated)
    app.form.set_values(app._settings_for_form())
    app.on_form_changed()
    app.log(f"{T(log_key)}: {updated}")
    if app.running:
        app.log(T("log.apply_needed"))


def block_ip_address(app, ip):
    """Add an address to the blocking field (decision pipeline step 2c)."""
    if str(ip or "").strip():
        append_to_field(app, "block_ip", str(ip).strip(), "log.block_ip_added")


def leave_process_alone(app, name):
    """Exclude a process from impairment by adding ``!name`` to the target.

    With a target already set this narrows it. With the target EMPTY it turns
    "impair everything" into "impair everything except this one", because a bare
    negative means exactly that in this expression language - and that is the case
    the menu entry is really for.
    """
    name = str(name or "").strip()
    if not name or name == "?":
        app.log(T("log.no_process_for_row"))
        return
    append_to_field(app, "target", f"!{name}", "log.process_excluded")


class ConnsPage:
    ID = "connections"
    LABEL = "app.tabs.connections"

    def __init__(self, app, parent):
        self.app = app
        self.frame = ttk.Frame(parent)
        self._search_job = None
        self._last_build = 0.0          # throttle for the heavy filter+sort
        self._now = 0.0                 # session clock used by _render
        self._scope_active = False      # True when a target is narrowing traffic now
        # the filter+sort runs OFF the UI thread (see gui/model_worker.py)
        self._model = AsyncModel(self._build_model, name="conns-model")
        self._poll_job = None           # the fast poll while a rebuild is in flight

        top = ttk.Frame(self.frame)
        top.pack(fill="x", padx=scaled(10), pady=scaled(8))
        ttk.Label(top, text=T("fields.search")).pack(side="left")
        self.search_var = tk.StringVar(value=app.conn_query)
        entry = ttk.Entry(top, textvariable=self.search_var, width=24)
        entry.pack(side="left", padx=(scaled(4), scaled(8)))
        entry.bind("<KeyRelease>", lambda e: self._schedule_search())
        entry.bind("<Escape>", lambda e: self._clear_search())
        add_tooltip(entry, "tips.conn_search")
        # The same "?" affordance the expression fields use (gui/form.py): the search
        # box understands `port:443` and `ip:10.0.0.0/8`, and a cheat sheet you can
        # read is the only way anyone finds that out. A tooltip cannot be it - it
        # runs away from the pointer as soon as you click.
        help_btn = ttk.Button(top, text=T("fields.match_help"), style="Help.TButton",
                              width=2, command=self._show_search_help)
        help_btn.pack(side="left", padx=(0, scaled(8)))
        add_tooltip(help_btn, "tips.conn_search_help")

        self.pause_var = tk.BooleanVar(value=False)
        pause = ttk.Checkbutton(top, text=T("buttons.freeze"), variable=self.pause_var,
                                command=lambda: self.refresh(force=True))
        pause.pack(side="left", padx=scaled(10))
        add_tooltip(pause, "tips.freeze")

        export = ttk.Button(top, text=T("buttons.export_conns"),
                            command=app.export_connections_csv)
        export.pack(side="left", padx=scaled(10))
        add_tooltip(export, "tips.export_conns")

        self.count = ttk.Label(top, text="", style="Muted.TLabel")
        self.count.pack(side="right")

        # Same reasoning as on the Statistics page: the note says what the table
        # COVERS, so it renders the coverage verdict rather than one of its inputs.
        state = self.app.coverage().state
        note = wrapping_label(self.frame, T(SCOPE_NOTES[state]))
        note.pack(anchor="w", padx=scaled(10), pady=(0, scaled(4)))
        add_tooltip(note, SCOPE_TIPS[state])
        self._scope_note = note
        self._scope_note_state = state

        holder = ttk.Frame(self.frame)
        holder.pack(fill="both", expand=True, padx=scaled(10), pady=(0, scaled(10)))
        # No stretch columns: this table scrolls horizontally, so a width the user
        # drags is a width they keep (a stretch column is recomputed by ttk on the
        # next <Configure> and visibly snaps back).
        self.table = SortableTree(holder, COLUMNS, sort=app.conn_sort,
                                  on_sort=self._on_sort, height=18,
                                  horizontal=True, tags=CONN_COLORS,
                                  min_chars=MIN_CHARS, tips=COLUMN_TIPS)
        self.table.sort.setdefault("default_reverse", True)
        # A layout saved by an earlier run. Unknown ids are dropped by the table
        # (a column may have been removed since), and an empty or missing entry
        # simply leaves every column showing.
        saved = app.ui.get("conn_columns")
        if isinstance(saved, list) and saved:
            self.table.set_visible_columns(saved)
        self._build_menu()

        # footer: summed traffic over the WHOLE filtered set (not just the rows the
        # display limit lets through), so the number the cap hides is still visible
        self.totals = ttk.Label(self.frame, text="", style="Muted.TLabel")
        self.totals.pack(fill="x", padx=scaled(10), pady=(0, scaled(8)))

    # -- context menu -------------------------------------------------------- #
    TARGET_INDEX = 3           # "Target this process" (after the separator)

    def _build_menu(self):
        self.menu = style_menu(tk.Menu(self.frame, tearoff=0))
        self.menu.add_command(label=T("menu.copy_row"), command=self._copy_row)
        self.menu.add_command(label=T("menu.copy_ip"), command=self._copy_ip)
        self.menu.add_separator()
        self.menu.add_command(label=T("menu.target_process"), command=self._target_process)
        self.menu.add_command(label=T("menu.leave_process_alone"),
                              command=self._leave_process_alone)
        self.menu.add_command(label=T("menu.limit_dest"), command=self._limit_dest)
        self.menu.add_command(label=T("menu.block_ip"), command=self._block_ip)
        self.menu.add_separator()
        self.menu.add_command(label=T("menu.choose_columns"),
                              command=self._choose_columns)
        self.menu.add_command(label=T("menu.reset_widths"),
                              command=self.table.reset_widths)
        self.table.tree.bind("<Button-3>", self._popup)
        self.table.tree.bind("<Button-2>", self._popup)      # macOS

    def _popup(self, event):
        """Show the menu only when it has a row to act on.

        It used to pop up anywhere in the table - including an empty one - so an
        empty view offered "Copy row" / "Target this process" with nothing to copy
        or target.
        """
        key = self.table.key_at(event.y)
        if key is None:
            return "break"
        # select by MODEL key: the widget's item ids are recycled viewport slots,
        # so they say nothing about which connection was clicked
        self.table.select_keys([key])
        # a row whose process could not be resolved (no admin rights) cannot be
        # targeted - grey the entry out instead of failing after the click
        selected = self._selected() or {}
        name = str(selected.get("proc") or "").strip()
        try:
            self.menu.entryconfigure(
                self.TARGET_INDEX,
                state="normal" if name and name != "?" else "disabled")
        except Exception as _exc:
            crashlog.note(_exc, "gui.pages.conns")
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.menu.grab_release()
            except Exception as _exc:
                crashlog.note(_exc, "gui.pages.conns")
        return "break"

    def _selected(self):
        values = self.table.selection_values()
        if not values:
            return None
        keys = list(COLUMNS)
        return dict(zip(keys, values))

    def _copy_row(self):
        # every selected row, tab separated - the same thing Ctrl+C puts on the
        # clipboard (SortableTree owns it, so every future table gets it too)
        text = self.table.copy_text()
        if text:
            self.app.copy_to_clipboard(text)

    def _copy_ip(self):
        row = self._selected()
        if row:
            self.app.copy_to_clipboard(str(row.get("remote_ip", "")))

    def _target_process(self):
        row = self._selected()
        if not row:
            return
        name = str(row.get("proc") or "").strip()
        if not name or name == "?":
            self.app.log(T("log.no_process_for_row"))
            return
        self.app.set_target_expression(name)

    def _choose_columns(self):
        """Ask which columns to show, then remember the answer in ui.json."""
        chosen = dialogs.choose_columns(
            self.app.root, T("dialogs.choose_columns_title"),
            T("dialogs.choose_columns"),
            [(col, T(key)) for col, key in COLUMNS.items()],
            self.table.visible_columns())
        if chosen is None:
            return                      # cancelled: leave the table as it was
        self.table.set_visible_columns(chosen)
        self.app.ui.set("conn_columns", list(self.table.visible_columns()))

    def _show_search_help(self):
        """The search cheat sheet, opened by the "?" next to the box."""
        dialogs.show_help(self.app.root, T("dialogs.conn_search_help_title"),
                          T("dialogs.conn_search_help"))

    def _leave_process_alone(self):
        row = self._selected()
        if not row:
            return
        leave_process_alone(self.app, str(row.get("proc") or "").strip())

    def _limit_dest(self):
        row = self._selected()
        if not row:
            return
        self.app.set_destination(str(row.get("remote_ip") or ""),
                                 str(row.get("remote_port") or ""))

    def _block_ip(self):
        row = self._selected()
        if not row:
            return
        block_ip_address(self.app, str(row.get("remote_ip") or ""))

    # -- search -------------------------------------------------------------- #
    def _schedule_search(self):
        if self._search_job is not None:
            try:
                self.frame.after_cancel(self._search_job)
            except Exception as _exc:
                crashlog.note(_exc, "gui.pages.conns")
        try:
            self._search_job = self.frame.after(SEARCH_DEBOUNCE_MS, self._run_search)
        except Exception:
            self._search_job = None
            self._run_search()

    def _run_search(self):
        self._search_job = None
        self.app.conn_query = self.search_var.get()
        self.refresh(force=True)          # a user action never waits for the throttle

    def _clear_search(self):
        self.search_var.set("")
        self._run_search()

    def _on_sort(self, sort):
        self.app.conn_sort = sort
        self.app.ui.set("conn_sort", {k: sort[k] for k in ("col", "reverse")})
        self.refresh(force=True)          # a user action never waits for the throttle

    # -- refresh ------------------------------------------------------------- #
    DUTY = 5                    # a rebuild may use at most 1/DUTY of the time

    def _render(self, c):
        """Format ONE connection row. Called only for the rows on screen."""
        now = self._now
        last = c.get("last", now)
        idle = max(0.0, now - last)
        dur = max(0.0, last - c.get("first", now))
        packets = c.get("packets") or 0
        # The COLUMN is the session-long record "was this flow ever in impairment
        # scope" (a sticky flag the engine keeps per flow), NOT a live lookup. A
        # closed or idle flow's ephemeral port has left the socket table, so a live
        # check flips every finished connection to "no" the instant it closes -
        # which read as "the tool caught almost nothing" even when it had impaired
        # them all while they were alive. The LIVE "in scope right now" signal is
        # the row highlight (_tag_of), which still follows the CURRENT target, so
        # narrowing chrome->firefox drops the highlight without erasing the record.
        scoped = T("conns.yes") if c.get("scoped") else T("conns.no")
        return (connection_proc(c, self.app.proc_map) or "?",
                c.get("pid") or "", c.get("proto", "IP"), c.get("remote_ip"),
                port_cell(c.get("remote_port")), port_cell(c.get("local_port")), packets,
                scoped, c.get("dropped", 0),
                # delivered first (what the application got), captured after it -
                # the gap between the two pairs IS the damage this row suffered
                f"{c.get('sent_in', 0) / 1024.0:.1f}",
                f"{c.get('sent_out', 0) / 1024.0:.1f}",
                f"{c.get('sent', 0) / 1024.0:.1f}",
                f"{c.get('bytes_in', 0) / 1024.0:.1f}",
                f"{c.get('bytes_out', 0) / 1024.0:.1f}",
                f"{avg_packet_bytes(c)}",
                f"{dur:.1f}", f"{idle:.1f}")

    def _tag_of(self, c):
        """Colour a row EXACTLY when the "impaired?" column says "yes".

        Both read the one stored per-flow ``scoped`` record, so the colour and the
        column can never disagree. They used to differ: the column read the stored
        record ("was this flow ever in impairment scope") while the highlight asked
        the engine LIVE ("is its port in the target set right now"). For a closed or
        idle flow those answer differently - the live check flips to "no" the moment
        the socket closes - so a row could be orange while its column said "no", and
        another could say "yes" with no colour. That mismatch is what read as "the
        table is wrong". One signal now, for both.

        Only when targeting actually narrows the traffic (``_scope_active``): with no
        target every flow counts as in scope, and colouring all of them is an alarm
        that means nothing.
        """
        return "impaired" if (self._scope_active and c.get("scoped")) else ""

    @staticmethod
    def _key_of(c):
        """Identity of a row, stable across sorts. MUST be unique per row.

        The protocol is part of it because portless rows (ICMP) have no ports to
        tell them apart: without it, ping and any other portless protocol to the
        same address - ESP or GRE to a VPN gateway, say - collapse to the same
        key, and the widget's key index is a dict, so selecting one would land on
        the other.
        """
        return (f"{c.get('proto')}|{c.get('local_port')}|"
                f"{c.get('remote_ip')}|{c.get('remote_port')}")

    def _sync_scope_note(self):
        """Re-word the note (and its bubble) when the coverage changed.

        The note states what the table COVERS, and both of its inputs can move
        while this page is already built: the preference is a checkbox, and the
        capture verdict lands when a session starts. A note describing the other
        state is the misleading sentence it exists to prevent.
        """
        note = getattr(self, "_scope_note", None)
        if note is None:
            return
        state = self.app.coverage().state
        if state == getattr(self, "_scope_note_state", None):
            return
        self._scope_note_state = state
        with crashlog.quiet("gui.pages.conns"):
            note.config(text=T(SCOPE_NOTES[state]))
            retip(note, SCOPE_TIPS[state])

    def refresh(self, force=False):
        """Repaint always (cheap); rebuild off-thread (never blocks the UI).

        The table is virtualised, so a repaint costs ~0.1 ms whatever the model
        holds. The filter and the sort are what grow - 361 ms at 500 000 rows,
        1.5 s at two million - and those now run on a worker (``AsyncModel``). The
        previous rows stay on screen while it works: a table that is one second
        stale is not a problem, a window that will not scroll or STOP is.
        """
        if self.pause_var.get():
            return
        app = self.app
        self._sync_scope_note()

        # 1) pick up a finished rebuild, if there is one (main thread, ~0 ms)
        result = self._model.poll()
        if result is not None:
            self._apply(result)

        # 2) the session clock, which STOPS when the session does: "idle" kept
        #    counting seconds on a stopped tester, which is simply not true
        self._now = app.engine.now_ref()
        self.table.repaint()            # ~0.1 ms: keeps idle/duration ticking over

        # 3) ask for a new rebuild, throttled - unless the user did something, in
        #    which case they get one now
        now = time.monotonic()
        if not force and (now - self._last_build) < REBUILD_MS / 1000.0:
            return
        self._last_build = now
        self._model.request({
            # The ENGINE goes to the worker, not a snapshot of it - but NOT because
            # the copy is expensive. It is not: measured 2026-07-21 (Win11 AMD64,
            # CPython 3.14.6, median of 7) a pointer copy is 0.7 ms at the 200k cap
            # and 2.4 ms at 500k. This comment used to claim ~70 ms, which is wrong
            # by a factor of ~30 and would justify moving the call back here.
            # The real reason is the LOCK: connections_snapshot() acquires the
            # engine's _clock, the same lock the capture thread takes on every
            # logged packet. Taking the snapshot here would make the UI THREAD queue
            # behind the capture thread. On the worker that wait costs nobody a
            # frame, and the worker may call it safely for exactly that reason.
            "engine": app.engine,
            "query": app.conn_query,
            "sort": dict(self.table.sort),
            "limit": app.row_limit(),
            "now": self._now,
            "proc_map": dict(app.proc_map),
            # Read on the UI thread and carried across, like every other input
            # here: the worker must not reach back into App (convention 26).
            "scoped_only": app.scoped_view(),
        })
        # The tick is 700 ms apart, and a user who just hit a header or typed a
        # search should not wait that long to see the answer they asked for. Poll
        # the worker briskly until it lands, then stop.
        self._poll_soon()

    POLL_MS = 40

    def _poll_soon(self):
        """Main thread: check the worker often enough to feel instant, then stop."""
        if self._poll_job is not None:
            with crashlog.quiet("gui.pages.conns"):
                self.frame.after_cancel(self._poll_job)
            self._poll_job = None
        if not self._model.busy():
            return
        with crashlog.quiet("gui.pages.conns"):
            self._poll_job = self.frame.after(self.POLL_MS, self._drain_model)

    def _drain_model(self):
        self._poll_job = None
        result = self._model.poll()
        if result is not None:
            self._apply(result)
            self.table.repaint()
        self._poll_soon()

    def _build_model(self, request):
        """Runs on the WORKER thread. Touches no widget, and must not raise."""
        # limit=None: the raw rows, unsorted - the engine no longer sorts a table
        # this page is about to sort by the user's column anyway
        conns = request["engine"].connections_snapshot(limit=None)
        # "Show only the targeted traffic": drop the rows the targeting never
        # selected, BEFORE filtering, sorting and totalling, so the table, the
        # "shown X of Y" counter and the footer all describe the same set. The
        # flag is the row's own sticky `scoped` - once a flow has been in scope it
        # stays listed, which is the same answer the "impaired?" column gives and
        # deliberately NOT a live re-check (a finished flow would flip to "no" the
        # moment its port left the socket table; see engine._log_conn).
        if request.get("scoped_only"):
            conns = [c for c in conns if c.get("scoped")]
        # the limit is passed IN, so it can bound the sort itself instead of only
        # trimming its result (see views.filter_sort_connections)
        shown = filter_sort_connections(
            conns, request["query"],
            request["sort"]["col"], request["sort"]["reverse"],
            now=request["now"], proc_map=request["proc_map"], limit=request["limit"])
        # summed over the FILTERED set (not the limited `shown`): the footer must
        # count every matching flow, not only the rows the cap let through
        totals = traffic_totals(conns, request["query"], request["proc_map"])
        # Whether a target is narrowing at all. With no target every flow is in
        # scope, so the whole-table tint would mean nothing - it fires only when
        # targeting is on (per-row scope is then checked live in _tag_of). One
        # cheap lock instead of the old O(n) any_scoped/any_unscoped scan.
        scope_active = request["engine"].targeting_active()
        return {"rows": shown, "total": len(conns), "limit": request["limit"],
                "totals": totals, "scope_active": scope_active}

    def _apply(self, result):
        """Main thread: swap the finished model in whole."""
        rows, total, limit = result["rows"], result["total"], result["limit"]
        self._scope_active = result.get("scope_active", False)
        # LAZY: hand over the raw rows; _render runs for the visible ones only
        self.table.set_model(rows, render=self._render, key_of=self._key_of,
                             tag_of=self._tag_of)
        if limit and len(rows) >= limit:
            text = T("conns.shown_of_limited", shown=len(rows), total=total, limit=limit)
        else:
            text = T("conns.shown_of", shown=len(rows), total=total)
        self.count.config(text=text)
        t = result.get("totals") or {"down": 0, "up": 0, "total": 0}
        self.totals.config(text=T("conns.totals",
                                  down=f"{t['down'] / 1024.0:.1f}",
                                  up=f"{t['up'] / 1024.0:.1f}",
                                  total=f"{t['total'] / 1024.0:.1f}"))
