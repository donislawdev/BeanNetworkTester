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
* the header says it out loud: these are ALL captured connections, not just the
  ones being impaired. Targeting decides what gets broken, not what gets seen.
"""

import time
import tkinter as tk
from tkinter import ttk

from ...i18n import T
from ...views import (avg_packet_bytes, connection_proc, filter_sort_connections,
                      traffic_totals)
from ..model_worker import AsyncModel
from ..labels import wrapping_label
from ..scaling import scaled
from ..theme import CONN_COLORS, style_menu
from ..tooltip import add_tooltip
from ..widgets import SortableTree
from ... import crashlog

COLUMNS = {"proc": "conns.process", "pid": "conns.pid", "proto": "conns.proto",
           "remote_ip": "conns.remote_ip", "remote_port": "conns.remote_port",
           "local_port": "conns.local_port", "packets": "conns.packets",
           "scoped": "conns.scoped", "dropped": "conns.dropped",
           "down": "conns.down", "up": "conns.up", "kb": "conns.kb",
           "avg": "conns.avg", "dur": "conns.time", "idle": "conns.idle"}

MIN_CHARS = {"proc": 16, "pid": 7, "proto": 5, "remote_ip": 18, "remote_port": 6,
             "local_port": 6, "packets": 7, "scoped": 7, "dropped": 8, "down": 8,
             "up": 8, "kb": 8, "avg": 7, "dur": 6, "idle": 6}

# One tooltip per COLUMN, shown next to its header. The old single tooltip hung
# on the whole tree, so it popped up over the rows and explained nothing about
# the column actually under the pointer.
COLUMN_TIPS = {"proc": "tips.col_process", "pid": "tips.col_pid",
               "proto": "tips.col_proto", "remote_ip": "tips.col_remote_ip",
               "remote_port": "tips.col_remote_port", "local_port": "tips.col_local_port",
               "packets": "tips.col_packets", "scoped": "tips.col_scoped",
               "dropped": "tips.col_dropped", "down": "tips.col_down",
               "up": "tips.col_up", "kb": "tips.col_kb", "avg": "tips.col_avg",
               "dur": "tips.col_dur", "idle": "tips.col_idle"}

SEARCH_DEBOUNCE_MS = 250
# The heavy part (filter + sort of the whole model) is throttled: the table is
# virtualised, so SCROLLING is free and instant no matter how big the model is,
# but re-sorting 200 000 rows on every 700 ms tick would burn ~15% of a core for
# nothing. A user-visible action (sorting, searching) always refreshes at once.
REBUILD_MS = 1000


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

        scope = wrapping_label(self.frame, T("conns.scope_note"))
        scope.pack(anchor="w", padx=scaled(10), pady=(0, scaled(4)))
        add_tooltip(scope, "tips.scope_note")

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
        self.menu.add_command(label=T("menu.limit_dest"), command=self._limit_dest)
        self.menu.add_separator()
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

    def _limit_dest(self):
        row = self._selected()
        if not row:
            return
        self.app.set_destination(str(row.get("remote_ip") or ""),
                                 str(row.get("remote_port") or ""))

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
                c.get("remote_port"), c.get("local_port"), packets,
                scoped, c.get("dropped", 0),
                f"{c.get('bytes_in', 0) / 1024.0:.1f}",
                f"{c.get('bytes_out', 0) / 1024.0:.1f}",
                f"{c.get('bytes', 0) / 1024.0:.1f}", f"{avg_packet_bytes(c)}",
                f"{dur:.1f}", f"{idle:.1f}")

    def _in_scope(self, c):
        """Ask the engine whether this flow is in targeting scope RIGHT NOW.

        Called for visible rows only (SortableTree.repaint renders the on-screen
        slice), so the per-row engine call is bounded to a screenful.
        """
        return self.app.engine.in_scope_now(
            c.get("local_port"), c.get("remote_ip"), c.get("remote_port"))

    def _tag_of(self, c):
        """Colour a row that is in targeting scope (being impaired, not just seen).

        Only when targeting actually narrows the traffic (``_scope_active``): with
        no target every flow is in scope, so tagging them all just turned the whole
        table into an alarm that meant nothing. Scope is recomputed against the
        CURRENT target, so an idle flow no longer keeps a stale highlight.
        """
        return "impaired" if (self._scope_active and self._in_scope(c)) else ""

    @staticmethod
    def _key_of(c):
        return f"{c.get('local_port')}|{c.get('remote_ip')}|{c.get('remote_port')}"

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
