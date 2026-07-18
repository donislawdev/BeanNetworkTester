"""A VIRTUALISED Treeview with sortable headers, row tags and stable selection.

This is the shared base for EVERY table in the tool (the connection log, the
event log, and whatever comes next), which is why the behaviour lives here and
not in the pages.

Why it is virtualised
---------------------
``ttk.Treeview`` has no virtualisation of its own: every row is a real Tcl item,
and the old ``sync()`` called ``item()`` **and** ``move()`` for each of them on
every refresh. ``move()`` on a large tree is worse than quadratic. Measured on
real Tk 8.6:

======  ==================  ==============
rows    old sync()          this sync()
======  ==================  ==============
   400  3 ms                ~1 ms
10 000  353 ms              ~1 ms
50 000  49 654 ms (50 s!)   ~1 ms
100000  197 741 ms (3 min)  ~1 ms
======  ==================  ==============

So the widget now holds only a WINDOW of rows - the ones on screen plus a small
buffer - in a fixed set of recycled item ids (``__v0``, ``__v1``, ...). The full
model lives in Python, the scrollbar is driven from the model offset, and a
repaint costs a CONSTANT number of Tcl calls no matter how many rows there are.
The table can hold hundreds of thousands of rows and still scroll in ~1 ms.

What callers must know
----------------------
* the ids passed to :meth:`sync` are model KEYS, not widget ids: they identify a
  row in the model, survive sorting, and are what selection is remembered by (the
  widget's item ids are recycled and meaningless);
* :meth:`selection_values`, :meth:`selected_rows`, :meth:`selected_keys` and
  :meth:`key_at` all answer from the model, so they survive a repaint;
* everything else - sorting, header arrows, tooltips, tags, Ctrl+C, column-width
  clamping - behaves exactly as before.

Kept from the original:

* **sorting** - clickable headers with an arrow, remembered per table;
* **Ctrl+C** - copies the selected row(s) as tab-separated text;
* **column widths behave** - ttk offers ``minwidth`` but no maximum, so a column
  could be dragged to any width at all, pushing the others out of sight (it is
  clamped on release; a double click on a separator resets the widths). A
  ``stretch=True`` column is RECOMPUTED by ttk to fill the tree, so dragging it
  snapped straight back - stretch is therefore refused on a table that has a
  horizontal scrollbar;
* **row tags** - a table can colour a row by kind (a bug marker must be findable
  at a glance).
"""
import sys
from tkinter import ttk

from ..scaling import column_width, scaled
from ..tooltip import make_bubble
from ..wheel import wheel_units
from ... import crashlog

ASC, DESC = "\u25b2", "\u25bc"
MAX_WIDTH_FACTOR = 3.0          # a column may grow to 3x its natural width
BUFFER_ROWS = 4                 # slots kept past the viewport, hides scroll tearing
MIN_WINDOW = 12                 # slots to keep even before the widget has a size


class SortableTree:
    """Wraps a virtualised ``ttk.Treeview`` + scrollbars in ``parent``."""

    HEADER_TIP_DELAY = 350                  # ms of hovering a header before the tip

    def __init__(self, parent, columns, sort=None, on_sort=None,
                 height=10, stretch=(), horizontal=False, min_chars=None,
                 tips=None, tags=None, selectmode="extended"):
        self.columns = dict(columns)            # column id -> i18n key of its header
        self.sort = dict(sort or {"col": next(iter(self.columns)), "reverse": False})
        self.on_sort = on_sort
        self._min_chars = dict(min_chars or {})
        self.tips = dict(tips or {})            # column id -> i18n key of its tooltip
        self._tip_window = None
        self._tip_column = None
        self._tip_job = None
        self._natural = {}                      # column id -> width it was born with
        self._platform = sys.platform

        # -- model (every row) vs viewport (what the widget actually holds) ----- #
        self.items = []                 # raw model items - may be hundreds of thousands
        self._render = lambda item: item[1]
        self._key_of = lambda item: item[0]
        self._tag_of = lambda item: ""
        self._index = None              # key -> position, built lazily (see set_model)
        self.offset = 0                 # model row rendered in slot 0
        self._slots = []                # widget item ids, recycled forever
        self._slot_keys = []            # slot index -> model key currently shown
        self._selected = []             # selected MODEL KEYS (survive a repaint)
        self._painted = {}              # slot iid -> (values, tags) last written
        self._height = max(1, int(height))

        if horizontal and stretch:
            # ttk re-stretches such a column back to fill the tree on the next
            # <Configure>, so a drag "snapped back" a moment after the mouse was
            # released. With a horizontal scrollbar there is nothing to fill.
            stretch = ()

        self.frame = ttk.Frame(parent)
        self.frame.pack(fill="both", expand=True)
        self.vsb = ttk.Scrollbar(self.frame, orient="vertical",
                                 command=self._on_scrollbar)
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.tree = ttk.Treeview(self.frame, columns=tuple(self.columns),
                                 show="headings", height=self._height,
                                 selectmode=selectmode)
        self.tree.grid(row=0, column=0, sticky="nsew")
        if horizontal:
            hsb = ttk.Scrollbar(self.frame, orient="horizontal")
            hsb.grid(row=1, column=0, sticky="ew")
            hsb.config(command=self.tree.xview)
            self.tree.configure(xscrollcommand=hsb.set)
        self.frame.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)

        for col, key in self.columns.items():
            width = self._width_for(col, key)
            self._natural[col] = width
            self.tree.column(col, anchor="w", stretch=(col in stretch),
                             width=width, minwidth=scaled(40))
        for tag, options in (tags or {}).items():
            try:
                self.tree.tag_configure(tag, **options)
            except Exception as _exc:
                crashlog.note(_exc, "gui.widgets.sortable_tree")
        self.refresh_headers()
        self._ensure_slots(self._height + BUFFER_ROWS)

        # Header tooltips only. The old code hung ONE tooltip on the whole tree,
        # so it popped up over the rows (covering them and the buttons below) and
        # said nothing useful about the column under the pointer.
        self.tree.bind("<Motion>", self._on_motion, add="+")
        self.tree.bind("<Leave>", self._hide_tip, add="+")
        self.tree.bind("<ButtonPress>", self._hide_tip, add="+")
        self.tree.bind("<Destroy>", self._hide_tip, add="+")
        # column widths: clamp after a drag, reset on a double click
        self.tree.bind("<ButtonRelease-1>", self._on_release, add="+")
        self.tree.bind("<Double-Button-1>", self._on_double, add="+")
        # copying
        self.tree.bind("<Control-c>", self._on_copy, add="+")
        self.tree.bind("<Control-C>", self._on_copy, add="+")
        self.tree.bind("<Control-Insert>", self._on_copy, add="+")
        # selection is remembered by model key, because item ids are recycled
        self.tree.bind("<<TreeviewSelect>>", self._on_select, add="+")
        # The wheel moves the WINDOW, not the widget's own yview. This is a
        # binding on the widget ITSELF - it is not the global wheel dispatcher
        # (convention 13), which owns the page scroller. A table never lives inside
        # a ScrollableFrame (convention 14), so the two can never fight over an
        # event: this handler returns "break", and the page scroller never sees a
        # wheel event that happened over a table.
        self.tree.bind("<MouseWheel>", self._on_wheel, add="+")
        self.tree.bind("<Button-4>", self._on_wheel, add="+")
        self.tree.bind("<Button-5>", self._on_wheel, add="+")
        self.tree.bind("<Configure>", self._on_configure, add="+")
        self.tree.bind("<Prior>", lambda e: self.scroll_by(-self.window()), add="+")
        self.tree.bind("<Next>", lambda e: self.scroll_by(self.window()), add="+")

    # -- the viewport ---------------------------------------------------------- #
    def window(self):
        """How many model rows the widget currently has slots for."""
        return len(self._slots)

    def _ensure_slots(self, count):
        """Create/destroy the recycled item ids.

        The ONLY place rows are inserted or deleted: when the table is built and
        when it is resized - never on a data refresh.
        """
        count = max(MIN_WINDOW, int(count))
        blank = ("",) * len(self.columns)
        while len(self._slots) < count:
            iid = "__v%d" % len(self._slots)
            try:
                self.tree.insert("", "end", iid=iid, values=blank)
            except Exception:
                break
            self._slots.append(iid)
            self._slot_keys.append(None)
            self._painted[iid] = None
        while len(self._slots) > count:
            iid = self._slots.pop()
            self._slot_keys.pop()
            self._painted.pop(iid, None)
            try:
                self.tree.delete(iid)
            except Exception as _exc:
                crashlog.note(_exc, "gui.widgets.sortable_tree")

    def _visible_rows(self):
        """Rows that fit in the widget right now (falls back to the built height)."""
        try:
            height = int(self.tree.winfo_height() or 0)
            row_h = int(ttk.Style().lookup("Treeview", "rowheight") or 0)
            if height > 0 and row_h > 0:
                return max(1, height // row_h)
        except Exception as _exc:
            crashlog.note(_exc, "gui.widgets.sortable_tree")
        return self._height

    def _on_configure(self, _=None):
        needed = self._visible_rows() + BUFFER_ROWS
        if needed != self.window():
            self._ensure_slots(needed)
            self.offset = min(self.offset, self.max_offset())
            self.repaint()

    def max_offset(self):
        return max(0, len(self.items) - self.window())

    def scroll_by(self, lines):
        self.set_offset(self.offset + int(lines))
        return "break"

    def set_offset(self, offset):
        offset = max(0, min(int(offset), self.max_offset()))
        if offset == self.offset:
            return
        self.offset = offset
        self.repaint()

    def _on_wheel(self, event):
        units = wheel_units(getattr(event, "delta", 0), self._platform,
                            getattr(event, "num", None))
        if units:
            self.scroll_by(units)
        # "break": the window already moved, ttk must not also scroll its yview
        return "break"

    def _on_scrollbar(self, action, value, unit=None):
        total = max(1, len(self.items))
        if action == "moveto":
            self.set_offset(int(float(value) * total))
        elif action == "scroll":
            step = int(value) * (self.window() if str(unit) == "pages" else 1)
            self.scroll_by(step)

    def _sync_scrollbar(self):
        total = max(1, len(self.items))
        first = min(1.0, self.offset / total)
        last = min(1.0, (self.offset + self.window()) / total)
        try:
            self.vsb.set(first, last)
        except Exception as _exc:
            crashlog.note(_exc, "gui.widgets.sortable_tree")

    # -- the model ------------------------------------------------------------- #
    # Two ways in, one machine underneath:
    #
    #   sync(rows)                  EAGER  - the caller has already formatted every
    #                                        row. Fine for small tables (the event
    #                                        log is capped at a few hundred).
    #   set_model(items, render=)   LAZY   - the caller hands over RAW items and a
    #                                        render function that is called ONLY for
    #                                        the rows on screen.
    #
    # The lazy form is what makes a big table actually cheap. Rendering is not the
    # only per-row cost: formatting 200 000 rows into strings on every 700 ms tick
    # would burn hundreds of milliseconds even if the widget never saw them. With
    # set_model, a refresh touches ~60 rows no matter how many the model holds.
    def sync(self, rows):
        """Eager: ``rows`` are ``(key, values)`` or ``(key, values, tag)``."""
        self.set_model(list(rows),
                       render=lambda r: r[1],
                       key_of=lambda r: r[0],
                       tag_of=lambda r: r[2] if len(r) > 2 else "")

    def set_model(self, items, render, key_of, tag_of=None):
        """Lazy: keep ``items`` as they are; format only what is visible.

        ``render(item) -> values``   called for the visible rows only
        ``key_of(item) -> key``      stable identity (selection survives sorting)
        ``tag_of(item) -> tag``      optional row tag (colouring)

        No O(n) work happens here at all - not even building a key index. That is
        deliberate: at 200 000 rows, an index rebuild per refresh costs more than
        everything else in this class put together, and it is only needed when the
        user actually copies or right-clicks a row (see ``_ensure_index``).
        """
        self.items = list(items)
        self._render = render
        self._key_of = key_of
        self._tag_of = tag_of or (lambda _item: "")
        self._index = None                  # invalidated; rebuilt on demand
        self.offset = min(self.offset, self.max_offset())
        self.repaint()

    @property
    def rows(self):
        """The model as ``(key, values, tags)`` triples. O(n) - avoid in hot paths."""
        return [(str(self._key_of(item)), tuple(self._render(item)),
                 self._tag_or_empty(item)) for item in self.items]

    def _tag_or_empty(self, item):
        tag = self._tag_of(item)
        return (tag,) if tag else ()

    def _ensure_index(self):
        """key -> position, built only when something actually asks for it."""
        if self._index is None:
            self._index = {str(self._key_of(item)): i
                           for i, item in enumerate(self.items)}
        return self._index

    def repaint(self):
        """Write the visible slice into the recycled slots. Constant Tcl cost."""
        blank = ("",) * len(self.columns)
        window = self.window()
        visible = self.items[self.offset:self.offset + window]
        selected = set(self._selected)
        for i, iid in enumerate(self._slots):
            if i < len(visible):
                item = visible[i]
                key = str(self._key_of(item))
                values = tuple(self._render(item))
                tags = self._tag_or_empty(item)
            else:
                key, values, tags = None, blank, ()
            self._slot_keys[i] = key
            # talk to Tcl only when the slot's CONTENT changed: a table that is not
            # moving costs nothing at all
            if self._painted.get(iid) != (values, tags):
                self.tree.item(iid, values=values, tags=tags)
                self._painted[iid] = (values, tags)
        self._restore_selection(selected)
        self._sync_scrollbar()

    # -- selection (by model key: item ids are recycled) ------------------------ #
    def _slot_of(self, iid):
        try:
            return self._slots.index(iid)
        except ValueError:
            return -1

    def _on_select(self, _=None):
        try:
            chosen = self.tree.selection() or ()
        except Exception:
            return
        keys, wanted = [], []
        for iid in chosen:
            slot = self._slot_of(iid)
            if slot < 0:
                continue
            key = self._slot_keys[slot]
            if key is not None:                 # a blank slot maps to no model row
                keys.append(key)
                wanted.append(iid)
        self._selected = keys
        # A click can land on a blank slot below the last real row: ttk highlights
        # it, but it selects nothing. Drop those from the widget selection so an
        # empty row cannot sit there looking selected. Re-setting the selection
        # fires <<TreeviewSelect>> again, but with a clean set, so it settles at once.
        if tuple(wanted) != tuple(chosen):
            try:
                if wanted:
                    self.tree.selection_set(*wanted)
                else:
                    self.tree.selection_remove(*chosen)
            except Exception as _exc:
                crashlog.note(_exc, "gui.widgets.sortable_tree")

    def _restore_selection(self, selected=None):
        selected = set(self._selected) if selected is None else selected
        wanted = [self._slots[i] for i, key in enumerate(self._slot_keys)
                  if key is not None and key in selected]
        try:
            if tuple(self.tree.selection() or ()) != tuple(wanted):
                self.tree.selection_set(*wanted)
        except Exception as _exc:
            crashlog.note(_exc, "gui.widgets.sortable_tree")

    def selected_keys(self):
        """Model keys of the selected rows (only those still in the model)."""
        index = self._ensure_index()
        return [k for k in self._selected if k in index]

    def select_keys(self, keys):
        index = self._ensure_index()
        self._selected = [str(k) for k in keys if str(k) in index]
        self._restore_selection()

    def item_for_key(self, key):
        """The RAW model item behind a key (None when it is gone)."""
        pos = self._ensure_index().get(str(key))
        return self.items[pos] if pos is not None else None

    def row_for_key(self, key):
        """``(key, values, tags)`` for a key - renders that one row."""
        item = self.item_for_key(key)
        if item is None:
            return None
        return (str(key), tuple(self._render(item)), self._tag_or_empty(item))

    def key_at(self, y):
        """Model key of the row at widget y (for a right click), or None."""
        try:
            iid = self.tree.identify_row(y)
        except Exception:
            return None
        slot = self._slot_of(iid)
        if slot < 0:
            return None
        return self._slot_keys[slot]

    def selected_rows(self):
        """Values of every selected row."""
        out = []
        for key in self.selected_keys():
            row = self.row_for_key(key)
            if row is not None:
                out.append(row[1])
        return out

    def selection_values(self):
        rows = self.selected_rows()
        return rows[0] if rows else None

    # -- header tooltips ------------------------------------------------------- #
    def _column_at(self, x):
        """Column id under the pointer, or None."""
        try:
            spec = self.tree.identify_column(x)       # "#1", "#2", ...
            index = int(str(spec).lstrip("#")) - 1
        except (TypeError, ValueError):
            return None
        keys = list(self.columns)
        return keys[index] if 0 <= index < len(keys) else None

    def _on_motion(self, event):
        try:
            region = self.tree.identify_region(event.x, event.y)
        except Exception:
            region = None
        if region != "heading":
            self._hide_tip()
            return
        column = self._column_at(event.x)
        if column is None or column not in self.tips:
            self._hide_tip()
            return
        if column == self._tip_column:
            return                                    # already showing/queued
        self._hide_tip()
        self._tip_column = column
        try:
            self._tip_job = self.tree.after(
                self.HEADER_TIP_DELAY,
                lambda c=column, x=event.x_root, y=event.y_root: self._show_tip(c, x, y))
        except Exception:
            self._tip_job = None

    def _show_tip(self, column, x_root, y_root):
        from ...i18n import T
        self._tip_job = None
        if column != self._tip_column:
            return
        self._tip_window = make_bubble(self.tree, T(self.tips[column]),
                                       x_root, y_root, height=scaled(18))

    def _hide_tip(self, _=None):
        self._tip_column = None
        if self._tip_job is not None:
            try:
                self.tree.after_cancel(self._tip_job)
            except Exception as _exc:
                crashlog.note(_exc, "gui.widgets.sortable_tree")
            self._tip_job = None
        if self._tip_window is not None:
            try:
                self._tip_window.destroy()
            except Exception as _exc:
                crashlog.note(_exc, "gui.widgets.sortable_tree")
            self._tip_window = None

    # -- column widths --------------------------------------------------------- #
    def max_width(self, col):
        return int(self._natural.get(col, scaled(80)) * MAX_WIDTH_FACTOR)

    def clamp_widths(self):
        """Cap every column at its maximum. Never widens one, never touches a
        column the user did not drag past the limit.

        (The lower bound is ttk's own ``minwidth``; enforcing a floor here as well
        made columns *other* than the dragged one jump, which is the second half
        of "the resize behaves oddly".)
        """
        for col in self.columns:
            try:
                width = int(self.tree.column(col, "width") or 0)
            except Exception:
                continue
            limit = self.max_width(col)
            if width > limit:
                self.tree.column(col, width=limit)

    def reset_widths(self):
        """Back to the widths derived from the header text and the current DPI."""
        for col, width in self._natural.items():
            try:
                self.tree.column(col, width=width)
            except Exception as _exc:
                crashlog.note(_exc, "gui.widgets.sortable_tree")

    def _region(self, event):
        try:
            return self.tree.identify_region(event.x, event.y)
        except Exception:
            return None

    def _on_release(self, event):
        if self._region(event) == "separator":
            self.clamp_widths()

    def _on_double(self, event):
        if self._region(event) == "separator":
            self.reset_widths()
            return "break"

    # -- copying --------------------------------------------------------------- #
    def copy_text(self, header=False):
        """The selected rows as tab-separated text (what Ctrl+C puts on the clipboard)."""
        from ...i18n import T
        rows = self.selected_rows()
        if not rows:
            return ""
        lines = []
        if header:
            lines.append("\t".join(T(key) for key in self.columns.values()))
        lines += ["\t".join("" if v is None else str(v) for v in row) for row in rows]
        return "\n".join(lines)

    def _on_copy(self, _=None):
        text = self.copy_text()
        if not text:
            return "break"
        try:
            self.tree.clipboard_clear()
            self.tree.clipboard_append(text)
        except Exception as _exc:
            crashlog.note(_exc, "gui.widgets.sortable_tree")
        return "break"

    # -- headers --------------------------------------------------------------- #
    def _width_for(self, col, key):
        from ...i18n import T
        return column_width(T(key) + "  " + DESC, self._min_chars.get(col, 6))

    def refresh_headers(self):
        from ...i18n import T
        for col, key in self.columns.items():
            arrow = ""
            if col == self.sort["col"]:
                arrow = "  " + (DESC if self.sort["reverse"] else ASC)
            self.tree.heading(col, text=T(key) + arrow,
                              command=lambda c=col: self._clicked(c))

    def _clicked(self, col):
        if self.sort["col"] == col:
            self.sort["reverse"] = not self.sort["reverse"]
        else:
            self.sort = {"col": col, "reverse": self.sort.get("default_reverse", False)}
        self.refresh_headers()
        # a new order means the rows under the pointer are different anyway; go
        # back to the top, which is what the user looks at when sorting
        self.offset = 0
        if self.on_sort:
            self.on_sort(dict(self.sort))
