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
_result: dict = {}    # per-dialog result, keyed by the toplevel


def _center(win, parent, focus=None):
    """Place the dialog over its parent and only THEN show it.

    ``focus`` is the widget the keyboard should land on. It has to be given HERE
    rather than set by the caller beforehand, for two reasons that stack: the
    dialog is built withdrawn (see ``_shell``), where focus does not stick, and
    ``focus_force`` below moves it to the window and would discard it anyway.
    That is why "Save profile..." opened with the cursor nowhere and the name
    field had to be clicked.
    """
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
        if focus is not None:
            focus.focus_set()
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


def start_failure_message(err, elevated):
    """What the start-failed dialog says: the error, plus advice that FITS it.

    Here rather than in ``App`` because it is dialog CONTENT, and because the
    advice comes from a table the command line reads too (``driver.py``) - the
    window and the console must not grow two opinions about the same Win32 error.
    The elevation hint is one entry in that table, not the answer to everything:
    it used to be appended to every failure, including to a window that was
    already elevated (WinError 433, which is about the driver, not about rights).
    """
    from ..driver import open_failure_hint
    key = open_failure_hint(err, elevated)
    return f"{err}\n\n{T(key)}" if key else str(err)


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
    _center(win, parent, focus=entry)      # type straight away, no click needed
    return _run(win, None)


def choose_columns(parent, title, prompt, columns, visible):
    """Tick which columns a table shows. Returns the chosen ids, or None if cancelled.

    ``columns`` is ``[(id, label)]`` in table order and ``visible`` the ids ticked
    on entry. A small modal rather than an entry in the window registry: it is
    opened, answered and closed, so remembered geometry and raise-instead-of-open
    would be machinery for nobody. It is also not a menu of checkbuttons - with
    seventeen columns that is a list you scroll past, and the tkinter double this
    project tests GUIs on knows only ``add_command``, so a menu version would ship
    with nothing checking it.

    **The OK button goes disabled when nothing is ticked.** Hiding every column
    leaves a table that shows nothing and offers no way back, since the header the
    user would right-click is gone too. Refusing the empty answer at the point of
    the click is kinder than accepting it and silently keeping one column.
    """
    win, body = _shell(parent, title)
    ttk.Label(body, text=prompt, wraplength=scaled(WRAP), justify="left").pack(anchor="w")

    chosen = set(visible)
    vars_by_id = {}
    grid = ttk.Frame(body)
    grid.pack(fill="both", expand=True, pady=(scaled(10), 0))
    # Two columns of checkboxes: seventeen in one strip is taller than the minimum
    # supported window (convention: 1366x768) and would need its own scrollbar.
    per_column = (len(columns) + 1) // 2
    ok_holder = {}

    def refresh_ok():
        button = ok_holder.get("button")
        if button is not None:
            with crashlog.quiet("gui.dialogs"):
                button.config(state=("normal" if chosen else "disabled"))

    def toggle(col_id, var):
        if var.get():
            chosen.add(col_id)
        else:
            chosen.discard(col_id)
        refresh_ok()

    for index, (col_id, label) in enumerate(columns):
        var = tk.BooleanVar(value=col_id in chosen)
        vars_by_id[col_id] = var
        box = ttk.Checkbutton(grid, text=label, variable=var,
                              command=lambda c=col_id, v=var: toggle(c, v))
        box.grid(row=index % per_column, column=index // per_column,
                 sticky="w", padx=(0, scaled(18)), pady=scaled(2))

    def select_all():
        for col_id, var in vars_by_id.items():
            var.set(True)
            chosen.add(col_id)
        refresh_ok()

    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(scaled(18), 0))
    ttk.Button(bar, text=T("buttons.cancel"),
               command=lambda: _close(win, None)).pack(side="right")
    ok = ttk.Button(bar, text=T("buttons.ok"), style="Accent.TButton",
                    command=lambda: _close(win, sorted(chosen, key=[c for c, _ in columns].index)))
    ok.pack(side="right", padx=(0, scaled(8)))
    ok_holder["button"] = ok
    ttk.Button(bar, text=T("buttons.select_all_columns"),
               command=select_all).pack(side="left")
    refresh_ok()

    win.protocol("WM_DELETE_WINDOW", lambda: _close(win, None))
    win.bind("<Escape>", lambda e: _close(win, None))
    _center(win, parent)
    return _run(win, None)
