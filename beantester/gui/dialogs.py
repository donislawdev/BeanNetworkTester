"""Dark, in-app replacements for ``tkinter.messagebox`` / ``simpledialog``.

On Windows those two call the native ``MessageBox()``, which means the dialog
is a white system window that no ttk style can reach - and, worse, its buttons
come from the OS, so an English UI still asked "Tak / Nie" on a Polish Windows.
These dialogs are ordinary Toplevels: themed like the rest of the app and with
their labels translated through ``T()`` like everything else.

File pickers stay native on purpose (``tkinter.filedialog``): a file browser
should look like the system's, not like us.
"""
import tkinter as tk
from tkinter import ttk

from ..i18n import T
from .scaling import scaled
from .theme import ACC, BG, FONT, WARN, apply_dark_titlebar
from .. import crashlog

WRAP = 380
_result = {}          # per-dialog result, keyed by the toplevel


def _center(win, parent):
    """Place the dialog over its parent and only THEN show it."""
    try:
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        x = px + max(0, (pw - w) // 2)
        y = py + max(0, (ph - h) // 3)
        win.geometry(f"+{int(x)}+{int(y)}")
    except Exception as _exc:
        crashlog.note(_exc, "gui.dialogs")
    try:
        win.deiconify()
        win.lift()
        win.focus_force()
    except Exception as _exc:
        crashlog.note(_exc, "gui.dialogs")


def _close(win, value):
    _result[str(win)] = value
    try:
        win.grab_release()
    except Exception as _exc:
        crashlog.note(_exc, "gui.dialogs")
    try:
        win.destroy()
    except Exception as _exc:
        crashlog.note(_exc, "gui.dialogs")


def _shell(parent, title):
    win = tk.Toplevel(parent)
    try:
        win.withdraw()          # built hidden: no white flash, no jump into place
    except Exception as _exc:
        crashlog.note(_exc, "gui.dialogs")
    win.title(title)
    win.configure(bg=BG)
    try:
        win.transient(parent)
        win.resizable(False, False)
    except Exception as _exc:
        crashlog.note(_exc, "gui.dialogs")
    apply_dark_titlebar(win)    # must happen before the window is first shown
    body = ttk.Frame(win, padding=scaled(18))
    body.pack(fill="both", expand=True)
    return win, body


def _run(win, default=None):
    _result.setdefault(str(win), default)
    try:
        win.grab_set()
        win.wait_window()
    except Exception as _exc:
        crashlog.note(_exc, "gui.dialogs")
    return _result.pop(str(win), default)


def _message(parent, title, message, accent, buttons, default=None):
    """A message dialog. ``buttons`` is a list of (i18n key, value, style)."""
    win, body = _shell(parent, title)
    row = ttk.Frame(body)
    row.pack(fill="x")
    ttk.Label(row, text="\u25cf", foreground=accent, background=BG,
              font=(FONT, 14, "bold")).pack(side="left", padx=(0, scaled(10)),
                                            anchor="n")
    ttk.Label(row, text=message, wraplength=scaled(WRAP), justify="left").pack(
        side="left", anchor="w")

    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(scaled(18), 0))
    for key, value, style in reversed(buttons):
        button = ttk.Button(bar, text=T(key), style=style,
                            command=lambda v=value: _close(win, v))
        button.pack(side="right", padx=(scaled(8), 0))
    win.protocol("WM_DELETE_WINDOW", lambda: _close(win, default))
    win.bind("<Escape>", lambda e: _close(win, default))
    win.bind("<Return>", lambda e: _close(win, buttons[0][1]))
    _center(win, parent)
    return _run(win, default)


def show_info(parent, title, message):
    return _message(parent, title, message, ACC,
                    [("buttons.ok", True, "Accent.TButton")], default=True)


def show_warning(parent, title, message):
    return _message(parent, title, message, "#ffb454",
                    [("buttons.ok", True, "Accent.TButton")], default=True)


def show_error(parent, title, message):
    return _message(parent, title, message, WARN,
                    [("buttons.ok", True, "Accent.TButton")], default=True)


def ask_yes_no(parent, title, message):
    return bool(_message(parent, title, message, ACC,
                         [("buttons.yes", True, "Accent.TButton"),
                          ("buttons.no", False, "TButton")], default=False))


def show_help(parent, title, text):
    """A read-only help sheet (the "?" next to a filter-expression field).

    A tooltip cannot be this: it disappears the moment you click, and you cannot
    read a syntax cheat-sheet that runs away from the pointer. The "?" used to be
    a LABEL with a hand cursor - it looked like a button, and clicking it did the
    one thing you did not want (hid the tooltip).
    """
    win, body = _shell(parent, title)
    ttk.Label(body, text=text, wraplength=scaled(WRAP + 120), justify="left").pack(
        anchor="w")
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(scaled(18), 0))
    ttk.Button(bar, text=T("buttons.ok"), style="Accent.TButton",
               command=lambda: _close(win, True)).pack(side="right")
    win.protocol("WM_DELETE_WINDOW", lambda: _close(win, True))
    win.bind("<Escape>", lambda e: _close(win, True))
    win.bind("<Return>", lambda e: _close(win, True))
    _center(win, parent)
    return _run(win, True)


def ask_string(parent, title, prompt):
    """Returns the typed text, or None when cancelled."""
    win, body = _shell(parent, title)
    ttk.Label(body, text=prompt, wraplength=scaled(WRAP), justify="left").pack(anchor="w")
    var = tk.StringVar(value="")
    entry = ttk.Entry(body, textvariable=var, width=32)
    entry.pack(fill="x", pady=(scaled(10), 0))
    try:
        entry.focus_set()
    except Exception as _exc:
        crashlog.note(_exc, "gui.dialogs")

    def accept():
        _close(win, var.get())

    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(scaled(18), 0))
    ttk.Button(bar, text=T("buttons.cancel"),
               command=lambda: _close(win, None)).pack(side="right")
    ttk.Button(bar, text=T("buttons.ok"), style="Accent.TButton",
               command=accept).pack(side="right", padx=(0, scaled(8)))
    win.protocol("WM_DELETE_WINDOW", lambda: _close(win, None))
    win.bind("<Escape>", lambda e: _close(win, None))
    win.bind("<Return>", lambda e: accept())
    _center(win, parent)
    return _run(win, None)
