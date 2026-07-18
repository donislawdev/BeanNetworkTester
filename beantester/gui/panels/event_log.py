"""A worked example of a secondary window - COPY THIS FILE to make a new one.

It is a real, useful window (a filterable event log you can keep open next to the
main one), but its job here is to be a TEMPLATE. Everything a window in this tool
has to get right is done once, in order, with a comment saying why:

  1. a registry entry (``ID``/``TITLE``) - nothing is constructed by hand
  2. a VIRTUALISED table - the only kind that survives a real capture
  3. a LAZY model - format the rows on screen, never the whole table
  4. every string through ``T()``, every pixel through ``scaled()``
  5. widgets built once in ``build()``; ``refresh()`` only moves data
  6. a throttle, so a big model does not eat the tick
  7. failures recorded, not swallowed (``crashlog.quiet``)

To make your own window: copy this file, change ``ID``/``TITLE``, change the
columns, change ``_render``, and call ``register_window`` on it. Nothing else is
required - the dark title bar, the DPI sizing, the remembered geometry, the
raise-instead-of-duplicate behaviour and the language-switch rebuild all come from
:class:`~beantester.gui.windows.PanelWindow`.
"""
import time
import tkinter as tk
from tkinter import ttk

from ... import crashlog
from ...i18n import T, event_kind_label
from ...views import sort_events
from ..scaling import scaled
from ..theme import EVENT_COLORS
from ..tooltip import add_tooltip
from ..widgets import SortableTree
from ..windows import PanelWindow, register_window

# (1) Columns are a dict of {column id -> i18n key}. Adding a column is one entry
#     here plus one branch in _render: the table works out its own widths from the
#     header text and the current DPI, so no pixel numbers appear anywhere.
COLUMNS = {"t": "events.col_t", "time": "events.col_time",
           "type": "events.col_type", "desc": "events.col_desc"}

TIPS = {"t": "tips.col_event_t", "time": "tips.col_event_time",
        "type": "tips.col_event_type", "desc": "tips.col_event_desc"}

# (6) The model is re-filtered and re-sorted at most this often. Scrolling never
#     waits for it - the table is virtualised, so a repaint is ~0.1 ms whatever the
#     model holds. Only the DATA refresh is throttled.
REBUILD_MS = 500
SEARCH_DEBOUNCE_MS = 250


@register_window
class EventLogWindow(PanelWindow):
    """The session's event log, in its own window, with a filter."""

    ID = "event_log"
    TITLE = "windows.event_log"
    SIZE = (860, 560)

    # -- build: runs ONCE, when the window opens ---------------------------- #
    def build(self, body):
        self._query = ""
        self._search_job = None
        self._last_build = 0.0

        top = ttk.Frame(body)
        top.pack(fill="x", pady=(0, scaled(6)))

        ttk.Label(top, text=T("fields.search")).pack(side="left")
        self.search_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.search_var, width=24)
        entry.pack(side="left", padx=(scaled(6), 0))
        # (6) debounce, the same way the Connections page does it: re-filtering on
        #     every keystroke rebuilds the model several times per word typed
        entry.bind("<KeyRelease>", lambda e: self._debounce())
        entry.bind("<Escape>", lambda e: self._clear())
        add_tooltip(entry, "tips.event_search")

        clear = ttk.Button(top, text=T("buttons.clear"), command=self._clear)
        clear.pack(side="left", padx=(scaled(6), 0))

        self.count = ttk.Label(top, text="", style="Muted.TLabel")
        self.count.pack(side="right")

        # (4) No pixel numbers: the table works its widths out from the header text
        #     and the current DPI. `min_chars` is the ONE thing it cannot guess - a
        #     column headed "time" whose contents are "2026-07-14 12:58:58" needs to
        #     be told so, or the timestamps come out clipped. (This is exactly the
        #     kind of bug you only see by LOOKING at the window - see PROJECT_NOTES
        #     on rendering the GUI under Xvfb.)
        self.table = SortableTree(
            body, COLUMNS,
            sort={"col": "t", "reverse": True},
            on_sort=self._on_sort,
            height=20, horizontal=True, tips=TIPS, tags=EVENT_COLORS,
            min_chars={"t": 6, "time": 18, "type": 10, "desc": 40},
        )

        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(scaled(8), 0))
        copy = ttk.Button(actions, text=T("menu.copy_row"),
                          command=lambda: self.app.copy_to_clipboard(
                              self.table.copy_text(header=True)))
        copy.pack(side="left")
        add_tooltip(copy, "tips.event_copy")

        self.refresh(force=True)

    # -- refresh: runs on every tick; must stay cheap ----------------------- #
    def refresh(self, force=False):
        now = time.monotonic()
        if not force and (now - self._last_build) < REBUILD_MS / 1000.0:
            # (6) the cheap path: repaint the ~20 visible rows, nothing else
            self.table.repaint()
            return
        self._last_build = now

        events = self.app.engine.events_snapshot()
        if self._query:
            needle = self._query.lower()
            events = [e for e in events if needle in self._blob(e)]
        events = sort_events(events, self.table.sort["col"], self.table.sort["reverse"])

        limit = self.app.row_limit()
        if limit and len(events) > limit:
            events = events[:limit]

        # (3) LAZY: the raw events go in; _render is called only for what is shown
        self.table.set_model(events, render=self._render, key_of=self._key,
                             tag_of=lambda e: str(e[2]))
        self.count.config(text=T("conns.shown_of", shown=len(events),
                                 total=len(self.app.engine.events_snapshot())))

    # -- the four functions a new window actually has to write --------------- #
    @staticmethod
    def _key(event):
        """Stable identity of a row. Selection is remembered by this, not by an
        item id - the widget's ids are recycled viewport slots."""
        return f"{event[0]}|{event[1]}|{event[2]}|{event[3]}"

    @staticmethod
    def _render(event):
        """Format ONE row. Called only for the rows on screen - so it may be as
        expensive as it likes, and the model may be enormous."""
        return (f"{event[0]:.1f}", event[1], event_kind_label(event[2]), T(event[3]))

    @staticmethod
    def _blob(event):
        """What the search matches against."""
        return f"{event[1]} {event[2]} {T(event[3])}".lower()

    def _on_sort(self, _sort):
        self.refresh(force=True)          # a user action never waits for the throttle

    # -- search ------------------------------------------------------------- #
    def _debounce(self):
        if self._search_job is not None:
            with crashlog.quiet("gui.windows.event_log"):
                self.win.after_cancel(self._search_job)
        self._search_job = self.win.after(SEARCH_DEBOUNCE_MS, self._run_search)

    def _run_search(self):
        self._search_job = None
        self._query = self.search_var.get().strip()
        self.refresh(force=True)

    def _clear(self):
        self.search_var.set("")
        self._run_search()
