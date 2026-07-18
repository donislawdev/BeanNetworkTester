"""Tooltip bubbles.

One bubble window per application, reused - not a fresh ``Toplevel`` per hover.

Why it matters: Windows FLASHES an application's taskbar button when a new
top-level window appears in a program that is not in the foreground. The tool
creates a tooltip whenever the pointer rests on a widget, so an idle,
*stopped* app kept lighting up its own taskbar icon for no reason at all (a
user-visible "it wants something from me"). Reusing one hidden window - shown,
moved and hidden again - removes the cause instead of hiding the symptom, and
costs less than building a Toplevel + Label every 400 ms of hovering.
"""
import tkinter as tk

from ..i18n import T
from .scaling import scaled, tooltip_position
from .theme import FONT, TIP_BG, TIP_FG
from .. import crashlog

_BUBBLES = {}          # toplevel name -> (window, label)


def _bubble_for(widget):
    """The shared (hidden) bubble window of this widget's toplevel."""
    root = widget.winfo_toplevel()
    key = str(root)
    entry = _BUBBLES.get(key)
    if entry is not None:
        try:
            if entry[0].winfo_exists():
                return entry
        except Exception as _exc:
            crashlog.note(_exc, "gui.tooltip")
    window = tk.Toplevel(root)
    try:
        window.withdraw()                    # never mapped while it has no text
        window.wm_overrideredirect(True)
        window.transient(root)
        window.attributes("-topmost", True)
    except Exception as _exc:
        crashlog.note(_exc, "gui.tooltip")
    label = tk.Label(window, text="", justify="left", bg=TIP_BG, fg=TIP_FG,
                     relief="solid", borderwidth=1, wraplength=scaled(340),
                     font=(FONT, 9), padx=scaled(8), pady=scaled(6))
    label.pack()
    entry = (window, label)
    _BUBBLES[key] = entry
    return entry


def _grab_active(widget):
    """True while any window holds a Tk grab - e.g. an open combobox popdown.

    A bubble shown then would cover the very dropdown the user just opened (its
    list sits right under the field the tooltip describes). The popdown is
    created by Tcl and is NOT a tkinter-registered widget, so ``grab_current``
    routes it through ``_nametowidget`` and raises on it; the raw ``grab
    current`` call returns the window path as a plain string instead.
    ``grab_current`` stays as a fallback for environments without ``.tk`` (the
    test double). A modal dialog also grabs, but those carry no tooltips and the
    background can't emit hover events under a modal grab, so nothing is lost.
    """
    tk_obj = getattr(widget, "tk", None)
    if tk_obj is not None:
        with crashlog.quiet("gui.tooltip"):
            return bool(tk_obj.call("grab", "current", widget._w))
    with crashlog.quiet("gui.tooltip"):
        return widget.grab_current() is not None
    return False


def _show_bubble(widget, text, x_root, y_root, height=0):
    if not text:
        return None
    if _grab_active(widget):
        return None
    try:
        window, label = _bubble_for(widget)
    except Exception:
        return None
    try:
        label.config(text=text)
        window.update_idletasks()
        tip_w = window.winfo_reqwidth() or scaled(340)
        tip_h = window.winfo_reqheight() or scaled(60)
        screen_w = widget.winfo_screenwidth() or 1920
        screen_h = widget.winfo_screenheight() or 1080
        px, py = tooltip_position(x_root, y_root, height, tip_w, tip_h,
                                  screen_w, screen_h)
        window.wm_geometry(f"+{px}+{py}")
        window.deiconify()
        window.lift()
    except Exception:
        return None
    return window


def _hide_bubble(widget):
    try:
        window, _ = _bubble_for(widget)
        window.withdraw()
    except Exception as _exc:
        crashlog.note(_exc, "gui.tooltip")


class Tooltip:
    """A tooltip bubble shown when hovering over a widget."""

    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.shown = False
        self._after = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Motion>", self._rearm, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _rearm(self, _=None):
        """Re-arm after a click: <Enter> will not fire again without leaving."""
        if not self.shown and self._after is None:
            self._schedule()

    def _schedule(self, _=None):
        self._cancel()
        try:
            self._after = self.widget.after(self.delay, self._show)
        except Exception:
            self._after = None

    def _cancel(self):
        if self._after:
            try:
                self.widget.after_cancel(self._after)
            except Exception as _exc:
                crashlog.note(_exc, "gui.tooltip")
            self._after = None

    def _show(self):
        self._after = None
        if self.shown or not self.text:
            return
        try:
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty()
            h = self.widget.winfo_height()
        except Exception:
            return
        if _show_bubble(self.widget, self.text, x, y, h or 0) is not None:
            self.shown = True

    def _hide(self, _=None):
        self._cancel()
        if self.shown:
            _hide_bubble(self.widget)
            self.shown = False


def tooltip_text(key, shortcut=None):
    """The bubble text for ``key`` with an optional keyboard ``shortcut`` line.

    The accelerator is shown on its own line in brackets (``[F5]``) - a bare
    token with no translatable word, so it needs no i18n key of its own.
    """
    text = T(key) if key else ""
    if shortcut:
        text = f"{text}\n[{shortcut}]" if text else f"[{shortcut}]"
    return text


def add_tooltip(widget, key, shortcut=None):
    """Attach a tooltip with the translated text for the i18n ``key``.

    ``shortcut`` (e.g. ``"F5"``, ``"Ctrl+Enter"``) is appended so a control that
    has a keyboard shortcut advertises it in its own tooltip (convention 51). The
    Tooltip is stored on the widget (``_bnt_tooltip``) so tests can read it back.
    """
    if not key:
        return widget
    widget._bnt_tooltip = Tooltip(widget, tooltip_text(key, shortcut))
    return widget


class _BubbleHandle:
    """What ``make_bubble`` hands back: something that can be ``destroy()``ed."""

    def __init__(self, widget):
        self.widget = widget

    def destroy(self):
        _hide_bubble(self.widget)


def make_bubble(widget, text, x_root, y_root, height=0):
    """Show the shared bubble at a screen position; returns a handle (or None)."""
    if _show_bubble(widget, text, x_root, y_root, height) is None:
        return None
    return _BubbleHandle(widget)
