"""Statistics page: three sub-pages instead of one over-stuffed column.

The old layout packed the counter grid, the chart, the session/reproduction
panel and the event table into one non-scrollable frame. Their combined height
(~1090 px at 100%) exceeded the 900 px window, so ``pack`` simply gave the last
two panels no space at all: "Mark bug", "Save repro report", "Copy CLI" and the
whole event log were unreachable. Splitting by purpose keeps every part usable
down to 1366x768 and lets each grow independently.

The counter grid reflows its column count with the window width, so a maximised
window on a 4K screen no longer shows four narrow cells and a lot of nothing.
"""
import tkinter as tk
from tkinter import ttk

from ...engine import impairment_loss_pct
from ...i18n import T, event_kind_label
from ...views import sort_events
from ..chart import draw_throughput_chart
from ..labels import wrapping_label
from ..rates import average_kbps
from ..scaling import scaled
from ..scrollable import ScrollableFrame
from .. import scope
from ..theme import BG2, DOWN_C, EVENT_COLORS, UP_C
from ..tooltip import add_tooltip, retip
from ..widgets import SortableTree
from ... import crashlog

# What the figures on this page COVER, in this page's words. Keyed by every
# coverage state (gui/scope.py enforces that at import), because the state that
# had no wording of its own is exactly the one that read as its opposite: with
# the driver filter narrowed, "ALL captured traffic" described a capture that had
# already been cut down to the destination.
SCOPE_NOTES = scope.keys_for_states({
    scope.ALL: "stats.scope_note",
    scope.CAPTURE: "stats.scope_note_capture",
    scope.CAPTURE_PROCESS: "stats.scope_note_capture_process",
    scope.VIEW: "stats.scope_note_scoped",
})

# The bubble is the longer version of the very sentence above it, so it follows
# the same state - and is re-worded on the tick with it (see _sync_scope_note).
SCOPE_TIPS = scope.keys_for_states({
    scope.ALL: "tips.scope_note",
    scope.CAPTURE: "tips.scope_note_capture",
    scope.CAPTURE_PROCESS: "tips.scope_note_capture",
    scope.VIEW: "tips.scope_note_scoped",
})

# The chart caption names its own scope: this is the one figure on the page
# somebody screenshots and sends on, so "which traffic is this?" has to survive
# leaving the window.
THROUGHPUT_TITLES = scope.keys_for_states({
    scope.ALL: "frames.throughput",
    scope.CAPTURE: "frames.throughput_capture",
    scope.CAPTURE_PROCESS: "frames.throughput_capture",
    scope.VIEW: "frames.throughput_scoped",
})

CELLS = (
    ("down", "stats.download", "KB/s", "tips.stat_down"),
    ("up", "stats.upload", "KB/s", "tips.stat_up"),
    ("seen", "stats.packets", "", "tips.stat_seen"),
    ("queue", "stats.queued", "", "tips.stat_queue"),
    ("drop_loss", "stats.dropped", "", "tips.stat_loss"),
    ("corrupted", "stats.corrupted", "", "tips.stat_corrupted"),
    ("duplicated", "stats.duplicated", "", "tips.stat_duplicated"),
    ("drop_overflow", "stats.overflow", "", "tips.stat_overflow"),
    ("drop_shutdown", "stats.shutdown_dropped", "", "tips.stat_shutdown"),
    ("drop_send", "stats.send_failed", "", "tips.stat_send_failed"),
    ("drop_rate", "stats.rate_dropped", "", "tips.stat_rate"),
    ("drop_syn", "stats.syn_dropped", "", "tips.stat_syn"),
    ("drop_mtu", "stats.mtu_dropped", "", "tips.stat_mtu"),
    ("drop_nat", "stats.nat_expired", "", "tips.stat_nat"),
    ("drop_rst", "stats.rst_reset", "", "tips.stat_rst"),
    ("drop_lan", "stats.lan_cut", "", "tips.stat_lan"),
    ("drop_block", "stats.block_cut", "", "tips.stat_block"),
    ("drop_flap", "stats.flap_cut", "", "tips.stat_flap"),
    ("rst_sent", "stats.rst_sent", "", "tips.stat_rst_sent"),
)

SESSION_ROWS = (
    ("host", "session.host", ""),
    ("private_ipv4", "session.private_ipv4", ""),
    ("private_ipv6", "session.private_ipv6", ""),
    ("seed", "session.seed", "tips.eff_seed"),
    # Which traffic the driver handed over. A saved screenshot of this panel used
    # to be unreadable on that point: two sessions with the same `packets` figure
    # could describe two different worlds, and only the CLI and the repro report
    # said which. The GUI never mentioned it anywhere.
    ("capture", "session.capture", "tips.session_capture"),
    ("start", "session.start", ""),
    ("stop", "session.stop", ""),
    ("elapsed", "session.duration", ""),
    ("eff_loss", "session.eff_loss", "tips.eff_loss"),
    ("peak_queue", "session.peak_queue", ""),
    ("driver_wait", "session.driver_wait", "tips.driver_wait"),
    ("peak_rate", "session.peak_rate", "tips.peak_rate"),
    ("data_down", "session.down_mb", "tips.data_down"),
    ("data_up", "session.up_mb", "tips.data_up"),
    ("data_total", "session.total_mb", "tips.data_total"),
    ("avg_rate", "session.avg_rate", "tips.avg_rate"),
)

EVENT_COLUMNS = {"t": "events.col_t", "time": "events.col_time",
                 "type": "events.col_type", "desc": "events.col_desc"}

EVENT_TIPS = {"t": "tips.col_event_t", "time": "tips.col_event_time",
              "type": "tips.col_event_type", "desc": "tips.col_event_desc"}

CELL_MIN_W = 168        # design width of one counter cell (unscaled)


class StatsPage:
    ID = "statistics"
    LABEL = "app.tabs.statistics"
    SUBPAGES = (("live", "app.subtabs.live"),
                ("session", "app.subtabs.session"),
                ("events", "app.subtabs.events"))

    def __init__(self, app, parent):
        self.app = app
        self.frame = ttk.Frame(parent)
        self.nb = ttk.Notebook(self.frame)
        self.nb.pack(fill="both", expand=True, pady=(scaled(4), 0))
        self.tabs = {}
        for sub_id, label in self.SUBPAGES:
            tab = ttk.Frame(self.nb)
            self.nb.add(tab, text=T(label))
            self.tabs[sub_id] = tab
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._on_subpage())

        self.stat_labels = {}
        self.sess_labels = {}
        self._cells = []
        self._grid_cols = 0
        self._chart_job = None

        self._build_live(self.tabs["live"])
        self._build_session(self.tabs["session"])
        self._build_events(self.tabs["events"])
        self.select(app.ui.get("stats_page", "live"))

    # -- sub-pages ----------------------------------------------------------- #
    def _build_live(self, parent):
        # Scrolled, because this tab hit the SAME squeeze the page-level split
        # above was meant to end. The counter grid reflows its columns with the
        # window WIDTH, so a narrow window turns it into five tall rows; the grid
        # packs at its natural height and the chart, packed expand=True, gets the
        # leftover - which was about ten pixels, a black sliver under its own
        # heading. A canvas asking for 180 px is still shrunk below it when pack
        # has nothing left to give, so the request was never a floor.
        # No Treeview/Text/Listbox lives in here (convention 14) - the chart
        # canvas is a drawing surface with no scrolling of its own - so a
        # scroller is safe, and nothing on this tab can be squeezed out of
        # existence again. The trade: the scroller sizes its content to the
        # REQUESTED height (gui/scrollable.py only stretches the width), so the
        # chart no longer grows to fill a tall window - it keeps its 180 px.
        self.scroll = ScrollableFrame(parent, top_margin=scaled(4))
        parent = self.scroll.body

        self.grid = ttk.Frame(parent)
        self.grid.pack(fill="x", padx=scaled(8), pady=scaled(6))
        for key, cap, unit, tip in CELLS:
            cell = tk.Frame(self.grid, bg=BG2)
            value = ttk.Label(cell, text="0", style="Stat.TLabel")
            value.pack(padx=scaled(10), pady=(scaled(8), 0), anchor="w")
            caption = ttk.Label(cell, text=T(cap) + (f" ({unit})" if unit else ""),
                                style="StatCap.TLabel")
            caption.pack(padx=scaled(10), pady=(0, scaled(8)), anchor="w")
            self.stat_labels[key] = value
            for w in (cell, value, caption):
                add_tooltip(w, tip)
                self._attach_copy(w, value, "live")
            self._cells.append(cell)
        self.grid.bind("<Configure>", self._on_grid_configure)
        self._relayout_cells(4)

        # Right under the figures it copies, right-aligned so it does not sit in
        # the reading path of the grid above it.
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=scaled(10), pady=(scaled(2), 0))
        counters = ttk.Button(row, text=T("buttons.copy_counters"),
                              command=lambda: self._copy_visible("live"))
        counters.pack(side="right")
        add_tooltip(counters, "tips.copy_counters")

        # anchor, not fill: the wraplength follows the PARENT's width either way
        # (gui/labels.py), while filling would hand the note - and its tooltip -
        # the empty space to the right of the sentence.
        # The note is the one thing on this page that states what the numbers
        # COVER, so it renders the coverage verdict rather than any single input.
        # Leaving the "ALL captured traffic" wording up over narrowed figures is
        # the tool telling the user the exact opposite of the truth, right next to
        # the numbers it applies to.
        state = self.app.coverage().state
        note = wrapping_label(parent, T(SCOPE_NOTES[state]))
        note.pack(anchor="w", padx=scaled(10), pady=(scaled(2), 0))
        add_tooltip(note, SCOPE_TIPS[state])
        # Kept so the tick can re-word it: the view preference can be toggled -
        # and a session started - while this page is already built, and a note
        # describing the OTHER state is exactly what it exists to prevent.
        self._scope_note = note
        self._scope_note_state = state

        self._chart_frame = ttk.LabelFrame(parent, text=self._throughput_title())
        frame = self._chart_frame
        frame.pack(fill="both", expand=True, padx=scaled(8), pady=scaled(6))
        self.canvas = tk.Canvas(frame, bg=BG2, highlightthickness=0,
                                height=scaled(180))
        self.canvas.pack(fill="both", expand=True, padx=scaled(8), pady=scaled(8))
        # the chart used to be redrawn only on the 700 ms tick, so it lagged
        # visibly behind a window resize
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        row = ttk.Frame(parent)
        row.pack(fill="x", padx=scaled(10), pady=(0, scaled(8)))
        tk.Label(row, text="  ", bg=DOWN_C).pack(side="left")
        ttk.Label(row, text=T("chart.legend_down")).pack(side="left", padx=(scaled(4), scaled(12)))
        tk.Label(row, text="  ", bg=UP_C).pack(side="left")
        ttk.Label(row, text=T("chart.legend_up")).pack(side="left", padx=(scaled(4), 0))
        export = ttk.Button(row, text=T("buttons.export_csv"), command=self.app.export_csv)
        export.pack(side="right")
        add_tooltip(export, "tips.export_csv")

    def _build_session(self, parent):
        frame = ttk.LabelFrame(parent, text=T("frames.session"))
        frame.pack(fill="x", padx=scaled(8), pady=scaled(6))
        info = ttk.Frame(frame)
        info.pack(fill="x", padx=scaled(8), pady=scaled(6))
        for i, (key, cap, tip) in enumerate(SESSION_ROWS):
            caption = ttk.Label(info, text=T(cap) + ":", style="Muted.TLabel")
            caption.grid(row=i // 2, column=(i % 2) * 2, sticky="w",
                         padx=(0, scaled(6)), pady=scaled(2))
            value = ttk.Label(info, text="-")
            value.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w",
                       padx=(0, scaled(24)), pady=scaled(2))
            self.sess_labels[key] = value
            if tip:
                add_tooltip(value, tip)
            # the caption is part of the same row, so right-clicking it copies
            # the value it names rather than doing nothing
            for widget in (caption, value):
                self._attach_copy(widget, value, "session")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", padx=scaled(8), pady=(0, scaled(8)))
        mark = ttk.Button(buttons, text=T("buttons.mark_bug"), command=self.app.mark_bug)
        mark.pack(side="left")
        repro = ttk.Button(buttons, text=T("buttons.save_repro"), command=self.app.save_repro)
        repro.pack(side="left", padx=scaled(6))
        copy = ttk.Button(buttons, text=T("buttons.copy_cli"), command=self.app.copy_repro_cli)
        copy.pack(side="left")
        details = ttk.Button(buttons, text=T("buttons.copy_session"),
                             command=lambda: self._copy_visible("session"))
        details.pack(side="right")
        add_tooltip(mark, "tips.mark_bug")
        add_tooltip(repro, "tips.save_repro")
        add_tooltip(copy, "tips.copy_cli")
        add_tooltip(details, "tips.copy_session")

    # -- copying what is on screen -------------------------------------------- #
    # 🔴 The figures were unreachable: every value here is a `ttk.Label`, which
    # cannot even be SELECTED, so the machine name and the addresses beside it
    # could only be retyped by hand into a bug report. Two ways out, matching what
    # the connection table already does: a right-click menu for one value, and a
    # button for the whole panel (the button is also the keyboard path - a menu
    # that only a mouse can open is not an answer for everyone).
    #
    # Ctrl+C is deliberately NOT bound here. The connection table and the event
    # log own it, and a root binding without `add=` replaces the one before it -
    # the exact defect the Control page's Ctrl+F had to be rescued from.

    def _copy_menu(self):
        menu = getattr(self, "_menu", None)
        if menu is None:
            menu = tk.Menu(self.frame, tearoff=0)
            menu.add_command(label=T("menu.copy_value"), command=self._copy_one)
            menu.add_command(label=T("menu.copy_all"), command=self._copy_panel)
            self._menu = menu
        return menu

    def _attach_copy(self, widget, value_widget, source):
        """Right-click anywhere on a figure - its number, its caption, its cell."""
        widget.bind("<Button-3>",
                    lambda event, v=value_widget, s=source: self._popup(event, v, s))

    def _popup(self, event, value_widget, source):
        self._clicked = (value_widget, source)
        menu = self._copy_menu()
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            with crashlog.quiet("gui.pages.stats"):
                menu.grab_release()
        return "break"

    def session_text(self):
        """The session panel exactly as it reads on screen, one row per line.

        Built from `SESSION_ROWS` rather than a second hand-written list: a row
        added to the registry is copied the day it appears, and cannot quietly go
        missing from the text while sitting on the page.
        """
        return "\n".join(
            "%s: %s" % (T(cap), self.sess_labels[key].cget("text"))
            for key, cap, _tip in SESSION_ROWS if key in self.sess_labels)

    def live_text(self):
        """The counter grid, same rule - `CELLS` is the source, units included."""
        rows = []
        for key, cap, unit, _tip in CELLS:
            label = self.stat_labels.get(key)
            if label is None:
                continue
            caption = T(cap) + (" (%s)" % unit if unit else "")
            rows.append("%s: %s" % (caption, label.cget("text")))
        return "\n".join(rows)

    def _copy(self, text, logged):
        """One clipboard path (`App.copy_to_clipboard`), and no cheerful lie.

        That method logs its own failure and returns nothing, so a success line
        printed blindly next to it would contradict the error the user just read.
        The clipboard is read back instead: the confirmation appears only when the
        text is really there.
        """
        if not text:
            return
        self.app.copy_to_clipboard(text)
        with crashlog.quiet("gui.pages.stats"):
            if self.app.root.clipboard_get() == text:
                self.app.log("%s: %s" % (T("log.copied"), logged))

    def _copy_one(self):
        clicked = getattr(self, "_clicked", None)
        if clicked is None:
            return
        value = str(clicked[0].cget("text") or "")
        self._copy(value, value)

    def _copy_panel(self):
        clicked = getattr(self, "_clicked", None)
        source = clicked[1] if clicked else self.current()
        self._copy_visible(source)

    def _copy_visible(self, source):
        if source == "session":
            self._copy(self.session_text(), T("frames.session"))
        else:
            self._copy(self.live_text(), T("app.subtabs.live"))

    def _build_events(self, parent):
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True, padx=scaled(8), pady=scaled(6))
        self.events = SortableTree(holder, EVENT_COLUMNS, sort=self.app.event_sort,
                                   on_sort=self._on_event_sort, height=14,
                                   stretch=("desc",), tips=EVENT_TIPS,
                                   tags=EVENT_COLORS,
                                   min_chars={"t": 6, "time": 18, "type": 10, "desc": 40},
                                   # elapsed seconds, the one quantity here
                                   numeric={"t"},
                                   # the timestamp follows "t" and is always the
                                   # same width: centred, so a right-aligned
                                   # number cannot touch it
                                   centered={"time"})
        self._event_sig = None

    # -- responsive counter grid --------------------------------------------- #
    def _on_grid_configure(self, event):
        cols = max(2, int(event.width // scaled(CELL_MIN_W)) or 2)
        cols = min(cols, len(CELLS))
        if cols != self._grid_cols:
            self._relayout_cells(cols)

    def _relayout_cells(self, cols):
        self._grid_cols = cols
        for index, cell in enumerate(self._cells):
            cell.grid(row=index // cols, column=index % cols,
                      padx=scaled(4), pady=scaled(4), sticky="nsew")
        for c in range(len(CELLS)):
            try:
                self.grid.columnconfigure(c, weight=1 if c < cols else 0,
                                          minsize=scaled(CELL_MIN_W) if c < cols else 0)
            except Exception as _exc:
                crashlog.note(_exc, "gui.pages.stats")

    # -- chart --------------------------------------------------------------- #
    def _on_canvas_configure(self, _=None):
        if self._chart_job is not None:
            try:
                self.frame.after_cancel(self._chart_job)
            except Exception as _exc:
                crashlog.note(_exc, "gui.pages.stats")
        try:
            self._chart_job = self.frame.after(50, self.draw_chart)
        except Exception:
            self._chart_job = None
            self.draw_chart()

    def _throughput_title(self):
        """Frame caption reflecting the actual chart window (the ``chart_seconds``
        preference), so it never drifts from the live X-axis label.

        It also names the SCOPE. A throughput chart is the one number on this page
        somebody screenshots and sends on, so "which traffic is this?" has to be
        readable from the picture rather than from a tooltip nobody hovered - and
        the caption is redrawn every tick, so it cannot go stale after the
        preference is toggled or a session starts.
        """
        secs = self.app.pref("chart_seconds")
        return T(THROUGHPUT_TITLES[self.app.coverage().state], s=f"{secs:.0f}")

    def draw_chart(self):
        self._chart_job = None
        try:
            draw_throughput_chart(self.canvas, self.app.down_hist, self.app.up_hist,
                                  sample_interval_s=self.app.TICK_MS / 1000.0)
        except Exception as _exc:
            crashlog.note(_exc, "gui.pages.stats")

    # -- refresh ------------------------------------------------------------- #
    def _on_subpage(self):
        self.app.ui.set("stats_page", self.current())
        self.refresh()

    def current(self):
        try:
            index = self.nb.index(self.nb.select())
            return self.SUBPAGES[int(index)][0]
        except Exception:
            return "live"

    def select(self, sub_id):
        for index, (candidate, _) in enumerate(self.SUBPAGES):
            if candidate == sub_id:
                try:
                    self.nb.select(index)
                except Exception as _exc:
                    crashlog.note(_exc, "gui.pages.stats")
                return

    def refresh(self):
        page = self.current()
        if page == "live":
            self.refresh_counters()
            self.draw_chart()
        elif page == "session":
            self.refresh_session()
        elif page == "events":
            self.refresh_events()

    def _sync_scope_note(self):
        """Re-word the note when the coverage changed since it was built.

        The tooltip moves with it. It used to be bound once and never touched
        again, so toggling the preference re-worded the note and left the bubble
        underneath still explaining the other state - the same contradiction one
        hover deeper.
        """
        note = getattr(self, "_scope_note", None)
        if note is None:
            return
        state = self.app.coverage().state
        if state == getattr(self, "_scope_note_state", None):
            return
        self._scope_note_state = state
        with crashlog.quiet("gui.pages.stats"):
            note.config(text=T(SCOPE_NOTES[state]))
            retip(note, SCOPE_TIPS[state])

    def refresh_counters(self):
        self._sync_scope_note()
        self._chart_frame.config(text=self._throughput_title())
        snap = self.app.last_snapshot or {}
        rates = self.app.last_rates
        self.stat_labels["down"].config(text=f"{rates[0]:.0f}")
        self.stat_labels["up"].config(text=f"{rates[1]:.0f}")
        # `seen` is the only counter here with a scoped twin. The impairment
        # counters are already scoped by construction (nothing outside the target
        # can be impaired), and drop_overflow / drop_shutdown / drop_send stay on
        # the FULL traffic on purpose - they are what the TOOL lost, including
        # traffic the user never targeted, and narrowing them would hide it.
        for key in ("seen", "queue", "drop_loss", "corrupted", "duplicated",
                    "drop_overflow", "drop_shutdown", "drop_send",
                    "drop_rate", "drop_syn", "drop_mtu",
                    "drop_nat", "drop_rst", "drop_lan", "drop_block", "drop_flap", "rst_sent"):
            self.stat_labels[key].config(text=str(self.app.scoped_stat(snap, key)))

    def refresh_session(self):
        from ...utils import bytes_to_mb, human_duration, host_identity
        app = self.app
        snap = app.last_snapshot or {}
        info = app.engine.session_info()
        host, ipv4, ipv6 = host_identity()
        self.sess_labels["host"].config(text=host)
        self.sess_labels["private_ipv4"].config(text=ipv4)
        self.sess_labels["private_ipv6"].config(text=ipv6)
        seed = info["seed"]
        self.sess_labels["seed"].config(text="-" if seed is None else str(seed))
        # Straight off the session fact, NOT off the coverage state: this row is
        # about what the driver handed over, which the view preference cannot
        # change. Reading the state here would make a view switch look like a
        # different capture.
        self.sess_labels["capture"].config(
            text=T("session.capture_narrowed" if info["narrowed"]
                   else "session.capture_all"))
        self.sess_labels["start"].config(text=info["start"] or "-")
        # a running session has no stop time yet - and a stopped one must show it
        self.sess_labels["stop"].config(text=info["stop"] or "-")
        elapsed = info["elapsed"]
        self.sess_labels["elapsed"].config(
            text=(human_duration(elapsed) if info["start"] else "-"))
        self.sess_labels["eff_loss"].config(text=f"{impairment_loss_pct(snap):.1f}%")
        self.sess_labels["peak_queue"].config(text=str(snap.get("peak_queue", 0)))
        # "-" rather than "0.0 ms" when there is nothing to measure: on the
        # simulate path there is no driver queue at all, and a zero would read as
        # "measured, and it was nothing"
        waited = snap.get("driver_wait_peak_ms", 0.0)
        self.sess_labels["driver_wait"].config(
            text=f"{waited:.2f} ms" if waited else "-")
        self.sess_labels["peak_rate"].config(
            text=f"{app.peak_down:.0f} / {app.peak_up:.0f} KB/s")
        down_mb = bytes_to_mb(app.scoped_stat(snap, "bytes_in"))
        up_mb = bytes_to_mb(app.scoped_stat(snap, "bytes_out"))
        total_mb = round(down_mb + up_mb, 2)
        self.sess_labels["data_down"].config(text=f"{down_mb:.2f}")
        self.sess_labels["data_up"].config(text=f"{up_mb:.2f}")
        self.sess_labels["data_total"].config(text=f"{total_mb:.2f}")
        elapsed = info["elapsed"] or 0.0
        total_bytes = (app.scoped_stat(snap, "bytes_in")
                       + app.scoped_stat(snap, "bytes_out"))
        avg = average_kbps(total_bytes, elapsed)
        self.sess_labels["avg_rate"].config(text=f"{avg:.0f} KB/s")

    def refresh_events(self):
        events = self.app.engine.events_snapshot()[-300:]
        events = sort_events(events, self.events.sort["col"],
                             self.events.sort["reverse"])[:300]
        signature = (self.events.sort["col"], self.events.sort["reverse"], tuple(events))
        if signature == self._event_sig:
            return
        self._event_sig = signature
        # LAZY model, exactly like the connections table: the raw events go in and
        # only the rows on screen are ever formatted. The kind is also the row TAG -
        # a bug marker has to stand out, that is the whole point of the button that
        # creates it.
        self.events.set_model(events, render=self._render_event,
                              key_of=self._event_key,
                              tag_of=lambda e: str(e[2]))

    @staticmethod
    def _event_key(e):
        return f"{e[0]}|{e[1]}|{e[2]}|{e[3]}"

    @staticmethod
    def _render_event(e):
        return (f"{e[0]:.1f}", e[1], event_kind_label(e[2]), T(e[3]))

    def _on_event_sort(self, sort):
        self.app.event_sort = sort
        self.app.ui.set("event_sort", sort)
        self._event_sig = None
        self.refresh_events()
