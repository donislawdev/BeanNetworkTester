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

from ...i18n import T, event_kind_label
from ...views import sort_events
from ..chart import draw_throughput_chart
from ..labels import wrapping_label
from ..rates import average_kbps
from ..scaling import scaled
from ..theme import BG2, DOWN_C, EVENT_COLORS, UP_C
from ..tooltip import add_tooltip
from ..widgets import SortableTree
from ... import crashlog

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
    ("start", "session.start", ""),
    ("stop", "session.stop", ""),
    ("elapsed", "session.duration", ""),
    ("eff_loss", "session.eff_loss", ""),
    ("peak_queue", "session.peak_queue", ""),
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
            self._cells.append(cell)
        self.grid.bind("<Configure>", self._on_grid_configure)
        self._relayout_cells(4)

        scope = wrapping_label(parent, T("stats.scope_note"))
        scope.pack(fill="x", padx=scaled(10), pady=(scaled(2), 0))
        add_tooltip(scope, "tips.scope_note")

        frame = ttk.LabelFrame(parent, text=T("frames.throughput"))
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
            ttk.Label(info, text=T(cap) + ":", style="Muted.TLabel").grid(
                row=i // 2, column=(i % 2) * 2, sticky="w",
                padx=(0, scaled(6)), pady=scaled(2))
            value = ttk.Label(info, text="-")
            value.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w",
                       padx=(0, scaled(24)), pady=scaled(2))
            self.sess_labels[key] = value
            if tip:
                add_tooltip(value, tip)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", padx=scaled(8), pady=(0, scaled(8)))
        mark = ttk.Button(buttons, text=T("buttons.mark_bug"), command=self.app.mark_bug)
        mark.pack(side="left")
        repro = ttk.Button(buttons, text=T("buttons.save_repro"), command=self.app.save_repro)
        repro.pack(side="left", padx=scaled(6))
        copy = ttk.Button(buttons, text=T("buttons.copy_cli"), command=self.app.copy_repro_cli)
        copy.pack(side="left")
        add_tooltip(mark, "tips.mark_bug")
        add_tooltip(repro, "tips.save_repro")
        add_tooltip(copy, "tips.copy_cli")

    def _build_events(self, parent):
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True, padx=scaled(8), pady=scaled(6))
        self.events = SortableTree(holder, EVENT_COLUMNS, sort=self.app.event_sort,
                                   on_sort=self._on_event_sort, height=14,
                                   stretch=("desc",), tips=EVENT_TIPS,
                                   tags=EVENT_COLORS,
                                   min_chars={"t": 6, "time": 18, "type": 10, "desc": 40})
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

    def refresh_counters(self):
        snap = self.app.last_snapshot or {}
        rates = self.app.last_rates
        self.stat_labels["down"].config(text=f"{rates[0]:.0f}")
        self.stat_labels["up"].config(text=f"{rates[1]:.0f}")
        for key in ("seen", "queue", "drop_loss", "corrupted", "duplicated",
                    "drop_overflow", "drop_shutdown", "drop_rate", "drop_syn", "drop_mtu",
                    "drop_nat", "drop_rst", "drop_lan", "drop_block", "drop_flap", "rst_sent"):
            self.stat_labels[key].config(text=str(snap.get(key, 0)))

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
        self.sess_labels["start"].config(text=info["start"] or "-")
        # a running session has no stop time yet - and a stopped one must show it
        self.sess_labels["stop"].config(text=info["stop"] or "-")
        elapsed = info["elapsed"]
        self.sess_labels["elapsed"].config(
            text=(human_duration(elapsed) if info["start"] else "-"))
        seen = max(1, snap.get("seen", 0))
        self.sess_labels["eff_loss"].config(
            text=f"{100.0 * snap.get('drop_loss', 0) / seen:.1f}%")
        self.sess_labels["peak_queue"].config(text=str(snap.get("peak_queue", 0)))
        self.sess_labels["peak_rate"].config(
            text=f"{app.peak_down:.0f} / {app.peak_up:.0f} KB/s")
        down_mb = bytes_to_mb(snap.get("bytes_in", 0))
        up_mb = bytes_to_mb(snap.get("bytes_out", 0))
        total_mb = round(down_mb + up_mb, 2)
        self.sess_labels["data_down"].config(text=f"{down_mb:.2f}")
        self.sess_labels["data_up"].config(text=f"{up_mb:.2f}")
        self.sess_labels["data_total"].config(text=f"{total_mb:.2f}")
        elapsed = info["elapsed"] or 0.0
        total_bytes = snap.get("bytes_in", 0) + snap.get("bytes_out", 0)
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
