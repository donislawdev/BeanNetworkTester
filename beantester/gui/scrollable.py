"""Scrollable container + ONE global mouse-wheel dispatcher.

Why it is written this way (the old version did not scroll at all):

* The old code bound ``<Enter>``/``<Leave>`` on the *inner* frame and used them
  to add/remove a global ``bind_all`` wheel handler. In Tk, moving the pointer
  from a parent window into one of its children delivers ``<Leave>`` to the
  parent (detail ``NotifyInferior``). The Control page is covered by
  LabelFrames/Entries, so the wheel binding was torn down the moment the cursor
  touched any control - the wheel only worked over the few bare pixels between
  the panels.
* On Windows Tk delivers ``<MouseWheel>`` to the widget with **focus**, not the
  one under the pointer, so ``event.widget`` cannot be trusted. The pointer
  position can: the dispatcher hit-tests with ``winfo_containing`` and walks up
  the master chain to find the scrollable that owns that spot.
* Wheel deltas are platform-specific (Windows: multiples of 120 but not always;
  macOS: small integers; X11: Button-4/5). ``wheel_units`` normalises them and
  is a pure function, so it is unit-tested without a display.

Rule of thumb kept by the pages: a natively scrollable widget (Treeview, Text)
never lives inside a ``ScrollableFrame`` - scroll inside scroll is exactly what
this dispatcher would have to guess about.
"""
import sys

import tkinter as tk
from tkinter import ttk

from .scaling import scaled
from .theme import BG
from .wheel import wheel_units
from .. import crashlog

_OWNER_ATTR = "_bnt_scroll_owner"


def _can_scroll(widget):
    """True when a widget has something to scroll vertically."""
    try:
        first, last = widget.yview()
        return (last - first) < 0.999
    except Exception:
        return False


class WheelDispatcher:
    """Routes every wheel event to whatever is under the pointer."""

    def __init__(self, root, platform=None):
        self.root = root
        self.platform = platform or sys.platform
        self._disarm_combobox_wheel(root)
        root.bind_all("<MouseWheel>", self._on_wheel, add="+")
        root.bind_all("<Button-4>", self._on_wheel, add="+")
        root.bind_all("<Button-5>", self._on_wheel, add="+")

    @staticmethod
    def _disarm_combobox_wheel(root):
        """Stop a combobox from changing its value when the page is scrolled.

        ``ttk::combobox`` ships a CLASS binding on the wheel that steps through
        its values. Bindtags run widget -> class -> toplevel -> all, so it fires
        long before our dispatcher: scrolling the Control page with the pointer
        happening to pass over a combobox silently changed the selected traffic
        filter / profile.

        The class binding is REPLACED with a no-op that returns ``None`` (not
        ``"break"``) - the event keeps travelling to the ``all`` bindtag, where
        the dispatcher below scrolls the page the pointer is actually over.
        """
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                root.bind_class("TCombobox", sequence, lambda _e: None)
                root.bind_class("TSpinbox", sequence, lambda _e: None)
            except Exception as _exc:
                crashlog.note(_exc, "gui.scrollable")

    # -- resolution --------------------------------------------------------- #
    def _under_pointer(self, event):
        try:
            widget = self.root.winfo_containing(event.x_root, event.y_root)
        except Exception:
            widget = None
        return widget if widget is not None else getattr(event, "widget", None)

    def _resolve(self, widget):
        """Walk up from ``widget`` to the first thing that can scroll."""
        seen = 0
        while widget is not None and seen < 40:
            seen += 1
            owner = getattr(widget, _OWNER_ATTR, None)
            if owner is not None:
                return ("canvas", owner)
            if isinstance(widget, (ttk.Treeview, tk.Text, tk.Listbox)) and _can_scroll(widget):
                return ("native", widget)
            widget = getattr(widget, "master", None)
        return (None, None)

    # -- handling ----------------------------------------------------------- #
    def _popdown_open(self):
        """True while a combobox popdown (or any dialog) holds the grab.

        An open popdown is a separate toplevel with a Tk grab. Our root-level
        ``bind_all`` still saw the wheel, so scrolling with a dropdown open
        scrolled the PAGE BEHIND IT while the list just sat there - the page
        moved out from under the very control that was open.
        """
        try:
            return self.root.grab_current() is not None
        except Exception:
            return False

    def _on_wheel(self, event):
        if self._popdown_open():
            return "break"
        units = wheel_units(getattr(event, "delta", 0), self.platform,
                            getattr(event, "num", None))
        if not units:
            return None
        kind, target = self._resolve(self._under_pointer(event))
        if target is None:
            return None
        if kind == "native":
            # When Tk delivered the event to this very widget its class binding
            # already scrolled it; scrolling again here would double the step.
            if target is getattr(event, "widget", None):
                return None
            try:
                target.yview_scroll(units, "units")
            except tk.TclError as _exc:
                crashlog.note(_exc, "gui.scrollable")
            return "break"
        target.scroll(units)
        return "break"


class ScrollableFrame:
    """A vertically scrollable container. Use ``.body`` as the parent frame.

    ``top_margin`` keeps the scrolled content from touching whatever sits above
    it: flush against the notebook's tab strip, a half-scrolled section header
    was clipped mid-glyph right at the tabs and read as if the page were drawn
    *over* them.
    """

    def __init__(self, parent, padding=0, top_margin=0):
        self.canvas = tk.Canvas(parent, bg=BG, highlightthickness=0,
                                yscrollincrement=scaled(18))
        self.vsb = ttk.Scrollbar(parent, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_scrollbar)
        self.vsb.pack(side="right", fill="y", pady=(top_margin, 0))
        self.canvas.pack(side="left", fill="both", expand=True,
                         pady=(top_margin, 0))

        self.body = ttk.Frame(self.canvas, padding=padding)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        setattr(self.canvas, _OWNER_ATTR, self)
        setattr(self.body, _OWNER_ATTR, self)

        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    # -- geometry ----------------------------------------------------------- #
    def _on_body_configure(self, _=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except tk.TclError as _exc:
            crashlog.note(_exc, "gui.scrollable")

    def _on_canvas_configure(self, event=None):
        """Keep the inner frame as wide as the viewport and hold the position.

        Resizing the viewport re-clamps ``yview``; remembering the top fraction
        and restoring it stops the content from jumping when the layout above
        the notebook changes height.
        """
        try:
            width = event.width if event is not None else self.canvas.winfo_width()
            self.canvas.itemconfigure(self._window, width=width)
            top = self.canvas.yview()[0]
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            self.canvas.yview_moveto(top)
        except (tk.TclError, TypeError, IndexError) as _exc:
            crashlog.note(_exc, "gui.scrollable")

    def _on_scrollbar(self, first, last):
        try:
            self.vsb.set(first, last)
        except tk.TclError as _exc:
            crashlog.note(_exc, "gui.scrollable")

    # -- scrolling ---------------------------------------------------------- #
    def can_scroll(self):
        return _can_scroll(self.canvas)

    def scroll(self, units):
        """Scroll by N units; a no-op when everything already fits."""
        if not units or not self.can_scroll():
            return
        try:
            self.canvas.yview_scroll(int(units), "units")
        except tk.TclError as _exc:
            crashlog.note(_exc, "gui.scrollable")

    def ensure_visible(self, widget, margin=None):
        """Scroll just enough to bring ``widget`` into view.

        Expanding a section sitting at the bottom edge revealed its content
        *below* the viewport, so the user had to scroll by hand to see what they
        had just opened.
        """
        margin = scaled(10) if margin is None else margin
        try:
            self.canvas.update_idletasks()
            total = int(self.body.winfo_height() or 0)
            view = int(self.canvas.winfo_height() or 0)
            if total <= 0 or view <= 0 or total <= view:
                return                       # everything already fits
            top = int(widget.winfo_rooty()) - int(self.body.winfo_rooty())
            height = int(widget.winfo_height() or 0)
            current = float(self.canvas.canvasy(0))
            bottom = top + height + margin
            if bottom > current + view:
                # prefer showing the START of a widget taller than the viewport
                target = max(0, min(total - view, bottom - view))
                if height + margin > view:
                    target = max(0, min(total - view, top - margin))
            elif top - margin < current:
                target = max(0, top - margin)
            else:
                return                       # already visible
            self.canvas.yview_moveto(target / float(total))
        except Exception as _exc:
            crashlog.note(_exc, "gui.scrollable")

    def yview_fraction(self):
        try:
            return float(self.canvas.yview()[0])
        except Exception:
            return 0.0

    def set_yview_fraction(self, fraction):
        try:
            self.canvas.yview_moveto(max(0.0, min(1.0, float(fraction or 0.0))))
        except Exception as _exc:
            crashlog.note(_exc, "gui.scrollable")


def make_scrollable(parent):
    """Backwards-compatible helper: returns the inner frame."""
    return ScrollableFrame(parent).body
