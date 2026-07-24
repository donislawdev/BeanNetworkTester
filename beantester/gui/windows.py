"""Secondary windows: a base class and a registry, so adding one is one entry.

Why this exists
---------------
The tool has a registry for its settings (``fields.FIELD_DEFS``), for its pages
(``gui.pages.PAGES``), for its filters and for its exit codes - and the payoff is
always the same: a new one is a single entry, and nothing can be half-added.

Windows were the gap. ``gui/dialogs.py`` covers the small modals (info / warning /
error / yes-no / ask-string), but anything richer - a window with its own tables,
charts and inputs - meant a hand-written ``Toplevel``, and every hand-written
``Toplevel`` has to remember, from memory, to:

* set the dark title bar BEFORE it is first shown (Windows draws it in DWM; a Tk
  window that does not ask for the dark variant gets a bright white bar until the
  user clicks it - see ``theme.apply_dark_titlebar``);
* build hidden and only then show, or the window flashes white and jumps;
* size and centre itself from the screen and the DPI, never from pixel literals
  (convention 12);
* remember its geometry across restarts, in ``bean_network_tester_ui.json``;
* raise the EXISTING window instead of opening a second copy;
* survive a language switch (which rebuilds the whole UI).

Every one of those was a real bug in the main window at some point. Getting them
right once, here, is the difference between "we have thirty windows" and "we have
thirty windows and about nine of them flash white".

Adding a window
---------------
Subclass :class:`PanelWindow`, implement ``build(body)``, and register it::

    class PacketLogWindow(PanelWindow):
        ID = "packet_log"
        TITLE = "windows.packet_log"        # i18n key, like everything else

        def build(self, body):
            self.table = SortableTree(body, COLUMNS, ...)

    register_window(PacketLogWindow)

``App.open_window("packet_log")`` then opens it (or raises it, if it is already
open). The tables it puts inside are virtualised, so a window holding hundreds of
thousands of rows costs no more to draw than an empty one.
"""
import tkinter as tk
from tkinter import ttk

from ..i18n import T
from .scaling import geometry_fits, max_window_size, scaled
from .theme import BG, apply_dark_titlebar, disable_maximize
from .. import crashlog

WINDOWS = {}                    # id -> PanelWindow subclass (the registry)

MIN_W, MIN_H = 480, 320         # unscaled; a window smaller than this is unusable


def register_window(cls):
    """Add a window class to the registry. Also usable as a decorator."""
    if not getattr(cls, "ID", ""):
        raise ValueError("a PanelWindow needs an ID")
    WINDOWS[cls.ID] = cls
    return cls


class PanelWindow:
    """A themed, DPI-aware, geometry-remembering ``Toplevel``.

    Subclasses implement :meth:`build`; everything above is handled here.
    """

    ID = ""
    TITLE = ""                  # i18n key
    SIZE = (720, 520)           # unscaled default; scaled() is applied for real
    RESIZABLE = True
    MAX_FACTOR = 1.6            # how far past its default a window may be dragged

    def __init__(self, app):
        self.app = app
        self.win = None
        self.body = None

    # -- lifecycle ------------------------------------------------------------ #
    def open(self):
        """Show the window, or raise it if it is already open."""
        if self.win is not None:
            self._raise()
            return self
        win = tk.Toplevel(self.app.root)
        self.win = win
        try:
            win.withdraw()          # built hidden: no white flash, no jump
        except Exception as _exc:
            crashlog.note(_exc, "gui.windows")
        win.title(T(self.TITLE) if self.TITLE else "")
        try:
            win.configure(bg=BG)
        except Exception as _exc:
            crashlog.note(_exc, "gui.windows")
        # the dark title bar has to be asked for BEFORE the window is first mapped
        apply_dark_titlebar(win)
        try:
            win.minsize(scaled(MIN_W), scaled(MIN_H))
            win.resizable(self.RESIZABLE, self.RESIZABLE)
            # every window is capped and cannot be maximised, exactly like the main
            # window: past a point the layout is just a slab of empty background, so
            # do not offer more (convention 25). max_window_size clamps to the screen.
            win.maxsize(*self._max_size(win))
            disable_maximize(win)
            win.protocol("WM_DELETE_WINDOW", self.close)
        except Exception as _exc:
            crashlog.note(_exc, "gui.windows")

        self.body = ttk.Frame(win, padding=scaled(10))
        self.body.pack(fill="both", expand=True)
        self.build(self.body)

        self._restore_geometry()
        try:
            win.deiconify()
            win.lift()
            # The pre-map call above set the dark attribute; now that the window is
            # actually on screen, re-assert it so DWM repaints the frame dark right
            # away instead of leaving a white bar until the window is first clicked.
            apply_dark_titlebar(win)
        except Exception as _exc:
            crashlog.note(_exc, "gui.windows")
        return self

    def close(self):
        self._save_geometry()
        win, self.win, self.body = self.win, None, None
        if win is None:
            return
        try:
            win.destroy()
        except Exception as _exc:
            crashlog.note(_exc, "gui.windows")

    def is_open(self):
        return self.win is not None

    def _raise(self):
        try:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
        except Exception as _exc:
            crashlog.note(_exc, "gui.windows")

    def _max_size(self, win):
        """Upper bound for this window: its default size grown by ``MAX_FACTOR``,
        always clamped to the screen so it can never exceed what fits."""
        try:
            screen_w = int(win.winfo_screenwidth() or 0)
            screen_h = int(win.winfo_screenheight() or 0)
        except Exception:
            screen_w = screen_h = 0
        want = (int(self.SIZE[0] * self.MAX_FACTOR),
                int(self.SIZE[1] * self.MAX_FACTOR))
        return max_window_size(screen_w, screen_h, want=want)

    # -- geometry (remembered per window id) ----------------------------------- #
    def _state_key(self):
        return f"window.{self.ID}"

    def _restore_geometry(self):
        """Reuse the saved size/position - but only if it still fits the screen.

        A geometry saved on a second monitor that is no longer attached puts the
        window somewhere the user cannot reach it. The main window learned this the
        hard way; this is the same guard (``scaling.geometry_fits``).
        """
        win = self.win
        saved = self.app.ui.get(self._state_key())
        try:
            screen_w = win.winfo_screenwidth()
            screen_h = win.winfo_screenheight()
        except Exception:
            screen_w = screen_h = 0
        if saved and screen_w and geometry_fits(saved, screen_w, screen_h):
            try:
                win.geometry(saved)
                return
            except Exception as _exc:
                crashlog.note(_exc, "gui.windows")
        width, height = scaled(self.SIZE[0]), scaled(self.SIZE[1])
        try:
            x = max(0, (screen_w - width) // 2)
            y = max(0, (screen_h - height) // 3)
            win.geometry(f"{width}x{height}+{x}+{y}")
        except Exception as _exc:
            crashlog.note(_exc, "gui.windows")

    def _save_geometry(self):
        """Remember where the user left this window - if it is still there to ask.

        A Toplevel is a CHILD OF ROOT, so anything that destroys the root takes
        this window with it while ``self.win`` still points at it. Asking a
        destroyed window for its geometry raises TclError ("bad window path
        name"), which was then caught and RECORDED - a crash-log entry per close,
        for a window that was simply already gone.
        """
        win = self.win
        if win is None:
            return
        try:
            if not win.winfo_exists():
                return
            self.app.ui.set(self._state_key(), win.geometry())
        except Exception as _exc:
            crashlog.note(_exc, "gui.windows")

    # -- what a subclass implements -------------------------------------------- #
    def build(self, body):
        """Fill ``body``. Everything in it goes through ``T()`` and ``scaled()``."""
        raise NotImplementedError

    def refresh(self):
        """Called on the App tick while the window is open. Optional."""


class WindowManager:
    """The open windows of one App. Opens, raises, refreshes, rebuilds, closes."""

    def __init__(self, app):
        self.app = app
        self._open = {}                 # id -> PanelWindow instance

    def open(self, window_id):
        cls = WINDOWS.get(window_id)
        if cls is None:
            return None
        panel = self._open.get(window_id)
        if panel is None or not panel.is_open():
            panel = cls(self.app)
            self._open[window_id] = panel
        return panel.open()

    def close(self, window_id):
        panel = self._open.pop(window_id, None)
        if panel is not None:
            panel.close()

    def close_all(self):
        for window_id in list(self._open):
            self.close(window_id)

    def refresh(self):
        """Tick every open window. One broken window must not kill the others - or
        the tick loop (which is what drains the log and moves the statistics)."""
        for panel in list(self._open.values()):
            if not panel.is_open():
                continue
            try:
                panel.refresh()
            except Exception as exc:                    # pragma: no cover
                self.app.log(T("log.ui_error", e=exc))

    def rebuild(self):
        """A language switch rebuilds the UI; the open windows come back with it."""
        reopen = [wid for wid, panel in self._open.items() if panel.is_open()]
        self.close_all()
        for window_id in reopen:
            self.open(window_id)

    def open_ids(self):
        return [wid for wid, panel in self._open.items() if panel.is_open()]

    def toplevels(self):
        """The Toplevel widgets this registry currently owns.

        ``App._build_ui`` rebuilds the main UI by destroying every child of the
        root window - and a Toplevel is a child of the root. That tore the open
        windows down behind the registry's back, so ``rebuild()`` then ran
        ``close()`` on windows that no longer existed: their geometry was never
        saved (after a language switch the window came back where it used to be,
        not where the user had put it) and reading it raised into the crash log.
        The rebuild skips these; closing them is the registry's job.
        """
        return {panel.win for panel in self._open.values() if panel.win is not None}
