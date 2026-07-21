"""Dark theme: colour palette and ttk style configuration.

Two rules this file exists to enforce:

* **Every pixel goes through ``scaled()``** - fonts are in points and follow
  ``tk scaling``, everything else must follow the DPI factor explicitly.
* **A disabled widget must LOOK disabled.** ttk does not do that for free: an
  entry whose ``state`` is ``disabled`` keeps its normal colours unless the
  style declares a ``disabled`` map. Every interactive style below therefore
  carries one - otherwise the user cannot tell whether a field is live.
* **Focus must not look like hover.** Both states existed and both painted the
  same lighter fill, so "the keyboard is here" and "the mouse is over this" were
  the same picture - and a button that kept focus after its window closed read as
  stuck under the cursor. Hover is the FILL; focus is the RING (clam's
  ``Button.focus`` element, via ``focuscolor``). No style may map ``focus`` to a
  colour it also maps for ``active``; ``tools/ci_gui_render.py`` fails if one does.

The combobox popdown is a classic Tk listbox living in its own toplevel; ttk
styles do not reach it, so its colours are set through the option database in
``init_style(root)``.
"""
import sys

import tkinter as tk
from tkinter import ttk

from .scaling import scaled
from .. import crashlog

# surfaces (page -> card -> input): three depths, so panels and fields read as
# separate things instead of one flat blob
BG = "#1e2127"            # page background
BG2 = "#252932"           # cards: section panels, stat cells, chart
FIELD = "#171a20"         # inputs (entries, comboboxes, log)
BORDER = "#39404e"        # input / panel outline

FG, MUT = "#e4e6eb", "#9aa0aa"
# A disabled field must look INERT: it melts into the card instead of standing
# out. The first attempt made it *lighter* than a live input, which drew the eye
# to exactly the widget that does nothing.
DIS_BG, DIS_FG = "#242832", "#616978"
ACC, OK, WARN = "#4f9dff", "#4caf50", "#ff6b6b"
STOP_C = "#e2574c"        # STOP must not look like START
DOWN_C, UP_C = "#4f9dff", "#ffb454"

# Event-table row colours. A bug marker must be findable at a glance - the
# whole point of the button is "I saw it happen HERE", and the row used to look
# exactly like every other row.
EVENT_COLORS = {
    "BUG": {"foreground": "#ffd166", "background": "#4a3a12"},
    "START": {"foreground": "#8fe08f"},
    "STOP": {"foreground": "#9aa0aa"},
    "RESET": {"foreground": "#ffb454"},
    "CHANGE": {"foreground": "#8ec7ff"},
}

# Connection-table row colour. A flow that is IN targeting scope is actually being
# impaired, not merely observed. The page only applies this when a target is
# actually narrowing (see ConnsPage._tag_of), so it never floods. A warm amber
# FOREGROUND reads far cleaner than the old brown background, which went muddy over
# the blue-grey table and looked like a defect rather than a highlight.
CONN_COLORS = {
    "impaired": {"foreground": "#ffb454"},
}

GRID_C = "#333845"        # chart grid lines
TIP_BG, TIP_FG = "#0f1116", "#e4e6eb"
LINE_C = "#2f3542"        # separators
# Secondary buttons ("Load scenario...", "Clear", "Save...", "Delete"...) used to
# be painted in BG2 - the exact colour of the card they sit on, so they were
# nearly invisible. They get their own, lighter surface plus an outline.
BTN_BG, BTN_HOVER, BTN_BORDER = "#394152", "#4a5468", "#525d73"
DONATE_C = "#ff8fb1"      # the support button (not a session control - own colour)
SCROLL_BG = "#3a4150"     # scrollbar thumb
SCROLL_TROUGH = "#20232b"

FONT = "Segoe UI"
MONO_FONT = "Consolas"


def init_style(root=None):
    """Configure the shared ttk styles for the dark theme."""
    s = ttk.Style()
    try:
        s.theme_use("clam")
    except Exception as _exc:
        crashlog.note(_exc, "gui.theme")

    # -- surfaces ---------------------------------------------------------- #
    s.configure("TFrame", background=BG)
    s.configure("Card.TFrame", background=BG2)
    s.configure("Line.TFrame", background=LINE_C)
    s.configure("TLabel", background=BG, foreground=FG, font=(FONT, 9))
    s.configure("Card.TLabel", background=BG2, foreground=FG, font=(FONT, 9))
    s.configure("Title.TLabel", background=BG, foreground=FG, font=(FONT, 17, "bold"))
    s.configure("Good.TLabel", background=BG, foreground=OK, font=(FONT, 10, "bold"))
    s.configure("Bad.TLabel", background=BG2, foreground=WARN, font=(FONT, 9))
    s.configure("Status.Bad.TLabel", background=BG, foreground=WARN, font=(FONT, 10, "bold"))
    s.configure("Muted.TLabel", background=BG, foreground=MUT, font=(FONT, 9))
    s.configure("Author.TLabel", background=BG, foreground=MUT, font=(FONT, 9))
    s.configure("Stat.TLabel", background=BG2, foreground=FG, font=(FONT, 11, "bold"))
    s.configure("StatCap.TLabel", background=BG2, foreground=MUT, font=(FONT, 9))
    s.configure("Hint.TLabel", background=BG2, foreground=MUT, font=(FONT, 9))
    # a switched-off field label: a plain muted colour swap, no widget state
    # (ttk paints a disabled ttk.Label with a filled box, which looked broken)
    s.configure("CardOff.TLabel", background=BG2, foreground=DIS_FG, font=(FONT, 9))
    s.configure("Unit.TLabel", background=BG2, foreground=MUT, font=(FONT, 9))
    # the "?" syntax help used to melt into the background
    s.configure("Help.TLabel", background=BG2, foreground=ACC, font=(FONT, 9, "bold"))
    # Defensive only: NOTHING in this tool switches a label with `state` today.
    # A switched-off field label is greyed by swapping its style to CardOff.TLabel
    # (see just above, and ControlForm._apply_toggle_state / apply_overrides),
    # precisely because a state-disabled ttk.Label paints a filled box. These maps
    # cost nothing and keep a label readable if some future code does set state.
    for label_style in ("TLabel", "Card.TLabel", "Unit.TLabel", "Hint.TLabel",
                        "Muted.TLabel", "Help.TLabel"):
        s.map(label_style, foreground=[("disabled", DIS_FG)])
    s.configure("TLabelframe", background=BG, foreground=MUT, borderwidth=1,
                bordercolor=LINE_C, lightcolor=LINE_C, darkcolor=LINE_C)
    s.configure("TLabelframe.Label", background=BG, foreground=ACC, font=(FONT, 9, "bold"))

    # -- buttons ------------------------------------------------------------ #
    # FOCUS AND HOVER MUST NOT LOOK THE SAME (see the module docstring). Hover is
    # the fill; focus is the ring clam's ``Button.focus`` element draws INSIDE the
    # button - every clam button layout has it, and at thickness 1 it costs no
    # space (measured: a button is 82x31 with and without it; at 3 it grows to
    # 86x35, which is why this is not scaled()).
    s.configure("TButton", background=BTN_BG, foreground=FG, borderwidth=1,
                bordercolor=BTN_BORDER, lightcolor=BTN_BG, darkcolor=BTN_BG,
                focuscolor=ACC, focusthickness=1, focussolid=True, relief="flat",
                padding=(scaled(10), scaled(5)), font=(FONT, 9))
    s.map("TButton",
          background=[("disabled", DIS_BG), ("pressed", BTN_BORDER),
                      ("active", BTN_HOVER)],
          bordercolor=[("disabled", DIS_BG)],
          lightcolor=[("active", BTN_HOVER)],
          darkcolor=[("active", BTN_HOVER)],
          foreground=[("disabled", DIS_FG)])
    # The coloured buttons carry their ring in their own ink colour: an accent-blue
    # ring on an accent-blue button would be invisible.
    s.configure("Accent.TButton", background=ACC, foreground="#0c1220",
                font=(FONT, 10, "bold"), padding=scaled(8), borderwidth=0,
                focuscolor="#0c1220")
    s.map("Accent.TButton",
          background=[("disabled", DIS_BG), ("active", "#6fb0ff")],
          foreground=[("disabled", DIS_FG)])
    # STOP is a different action -> a different colour
    s.configure("Stop.TButton", background=STOP_C, foreground="#1a0d0c",
                font=(FONT, 10, "bold"), padding=scaled(8), borderwidth=0,
                focuscolor="#1a0d0c")
    s.map("Stop.TButton",
          background=[("disabled", DIS_BG), ("active", "#ff8378")],
          foreground=[("disabled", DIS_FG)])
    # "Apply changes" while the form differs from what the engine runs
    s.configure("Dirty.TButton", background=UP_C, foreground="#20160a",
                font=(FONT, 9, "bold"), padding=scaled(6), borderwidth=0,
                focuscolor="#20160a")
    s.map("Dirty.TButton",
          background=[("disabled", DIS_BG), ("active", "#ffc978")],
          foreground=[("disabled", DIS_FG)])
    # the "?" cheat-sheet button next to a filter-expression field
    s.configure("Help.TButton", background=BG2, foreground=ACC,
                font=(FONT, 9, "bold"), borderwidth=0, focuscolor=ACC,
                padding=(scaled(3), 0))
    s.map("Help.TButton",
          background=[("active", BTN_BG), ("disabled", BG2)],
          foreground=[("disabled", DIS_FG)])

    # Donate: visible, but an outline button - it must not compete with START,
    # nor look like one of the session controls
    s.configure("Donate.TButton", background=BG, foreground=DONATE_C,
                bordercolor=DONATE_C, lightcolor=BG, darkcolor=BG, focuscolor=DONATE_C,
                font=(FONT, 9, "bold"), borderwidth=1, padding=(scaled(10), scaled(4)))
    s.map("Donate.TButton",
          background=[("active", "#3a2b33"), ("disabled", DIS_BG)],
          foreground=[("disabled", DIS_FG)],
          bordercolor=[("active", DONATE_C)])

    # collapsible section header
    s.configure("Section.TButton", background=BG, foreground=ACC,
                font=(FONT, 9, "bold"), borderwidth=0, focuscolor=ACC,
                padding=(scaled(2), scaled(3)), anchor="w")
    s.map("Section.TButton", background=[("active", BG2)])

    # header gear: an icon-only button that opens the Settings window. Flat on the
    # header at rest (bevel colours pinned to BG so clam draws no raised edge), but
    # a small icon needs a REAL hover chip - the old BG->BG2 map was a one-shade
    # change nobody could see, so it never read as clickable. Hover lights up to
    # the secondary-button surface; press goes a shade lighter.
    s.configure("Gear.TButton", background=BG, bordercolor=BG, lightcolor=BG,
                darkcolor=BG, borderwidth=0, focuscolor=ACC, relief="flat",
                padding=scaled(5))
    s.map("Gear.TButton",
          background=[("disabled", BG), ("pressed", BTN_HOVER),
                      ("active", BTN_BG)],
          bordercolor=[("active", BTN_BORDER)],
          lightcolor=[("active", BTN_BG), ("pressed", BTN_HOVER)],
          darkcolor=[("active", BTN_BG), ("pressed", BTN_HOVER)])

    # -- checkbuttons ------------------------------------------------------- #
    # clam's built-in indicator is a flat, tiny, badly aligned square that no
    # amount of option juggling fixes. Draw the box ourselves instead.
    s.configure("TCheckbutton", background=BG2, foreground=FG, font=(FONT, 9),
                focuscolor=ACC, padding=(0, scaled(2)), borderwidth=0)
    s.map("TCheckbutton",
          background=[("active", BG2)],
          foreground=[("disabled", DIS_FG)])
    _install_check_indicator(s)

    # -- entries ------------------------------------------------------------ #
    s.configure("TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG,
                borderwidth=1, bordercolor=BORDER, lightcolor=BORDER,
                darkcolor=BORDER, padding=scaled(2))
    s.map("TEntry",
          fieldbackground=[("disabled", DIS_BG), ("readonly", DIS_BG)],
          foreground=[("disabled", DIS_FG), ("readonly", DIS_FG)],
          bordercolor=[("disabled", DIS_BG), ("focus", ACC)],
          lightcolor=[("focus", ACC)], darkcolor=[("focus", ACC)])
    # a value that does not parse / is out of range (live validation)
    s.configure("Bad.TEntry", fieldbackground=FIELD, foreground=WARN,
                insertcolor=FG, borderwidth=2, bordercolor=WARN,
                lightcolor=WARN, darkcolor=WARN, padding=scaled(2))
    s.map("Bad.TEntry",
          fieldbackground=[("disabled", DIS_BG)],
          foreground=[("disabled", DIS_FG)])

    # -- comboboxes --------------------------------------------------------- #
    s.configure("TCombobox", fieldbackground=FIELD, background=BG2, foreground=FG,
                arrowcolor=MUT, borderwidth=1, bordercolor=BORDER,
                lightcolor=BORDER, darkcolor=BORDER, padding=scaled(2))
    s.map("TCombobox",
          fieldbackground=[("disabled", DIS_BG), ("readonly", FIELD)],
          foreground=[("disabled", DIS_FG)],
          arrowcolor=[("disabled", DIS_FG)],
          bordercolor=[("disabled", DIS_BG), ("focus", ACC)],
          # a readonly combobox keeps its text "selected" after a pick, which
          # rendered as a permanent highlight bar - paint it as normal text
          selectbackground=[("readonly", FIELD), ("!focus", FIELD)],
          selectforeground=[("readonly", FG), ("!focus", FG)])

    # NOTE: the profile picker is a plain readonly TCombobox on purpose - it used
    # to be a Menubutton + tk.Menu styled to imitate one, and the imitation could
    # never be finished: on Windows a tk.Menu is a native Win32 popup, so its
    # frame, its width and the highlight on the current entry are outside Tk's
    # reach. Two dropdowns on the same page must be the same widget.

    # -- scrollbars --------------------------------------------------------- #
    for orient in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        s.configure(orient, background=SCROLL_BG, troughcolor=SCROLL_TROUGH,
                    bordercolor=SCROLL_TROUGH, arrowcolor=MUT,
                    darkcolor=SCROLL_BG, lightcolor=SCROLL_BG,
                    gripcount=0, borderwidth=0, relief="flat",
                    arrowsize=scaled(12))
        s.map(orient,
              background=[("disabled", DIS_BG), ("active", "#4b5468")],
              arrowcolor=[("disabled", DIS_BG)])

    # -- notebook / tables --------------------------------------------------- #
    # clam paints a tab from several elements (Notebook.tab -> Notebook.padding ->
    # Notebook.focus -> Notebook.label) and marks the selected one by GROWING it
    # (an `expand` map). Recolouring the style alone only tinted the inner element,
    # leaving a small filled box inside a full-size slot plus a dashed focus ring.
    # So: own layout (no focus element), no size change, colour-only selection.
    try:
        s.layout("TNotebook.Tab", [
            ("Notebook.tab", {"sticky": "nswe", "children": [
                ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                    ("Notebook.label", {"side": "top", "sticky": ""})]})]})])
    except Exception as _exc:
        crashlog.note(_exc, "gui.theme")
    s.configure("TNotebook", background=BG, borderwidth=0, bordercolor=BG,
                lightcolor=BG, darkcolor=BG,
                tabmargins=(scaled(2), scaled(4), scaled(2), 0))
    tab_pad = (scaled(18), scaled(8))
    s.configure("TNotebook.Tab", background=BG2, foreground=MUT, font=(FONT, 9),
                padding=tab_pad, borderwidth=0, focuscolor=BG2,
                bordercolor=BG2, lightcolor=BG2, darkcolor=BG2)
    s.map("TNotebook.Tab",
          expand=[("selected", (0, 0, 0, 0))],          # no growing, no jumping
          padding=[("selected", tab_pad), ("active", tab_pad)],
          background=[("selected", ACC), ("disabled", DIS_BG), ("active", BTN_HOVER)],
          bordercolor=[("selected", ACC), ("disabled", DIS_BG), ("active", BTN_HOVER)],
          lightcolor=[("selected", ACC), ("disabled", DIS_BG), ("active", BTN_HOVER)],
          darkcolor=[("selected", ACC), ("disabled", DIS_BG), ("active", BTN_HOVER)],
          foreground=[("selected", "#0c1220"), ("disabled", DIS_FG), ("active", FG)],
          font=[("selected", (FONT, 9, "bold"))])
    s.configure("TPanedwindow", background=BG)
    s.configure("Sash", sashthickness=scaled(6), gripcount=0)
    # tables must grow with the font, otherwise text is clipped at 125%+
    s.configure("Treeview", background=BG2, fieldbackground=BG2, foreground=FG,
                borderwidth=0, rowheight=scaled(22), font=(FONT, 9))
    s.configure("Treeview.Heading", background=BG, foreground=MUT,
                font=(FONT, 9, "bold"), relief="flat", padding=scaled(3),
                borderwidth=0)
    s.map("Treeview.Heading", background=[("active", BG2)])
    s.map("Treeview", background=[("selected", "#33455f")], foreground=[("selected", FG)])

    # -- the combobox popdown is a classic Tk listbox: style it via options --- #
    if root is not None:
        try:
            root.option_add("*TCombobox*Listbox.background", FIELD)
            root.option_add("*TCombobox*Listbox.foreground", FG)
            root.option_add("*TCombobox*Listbox.selectBackground", ACC)
            root.option_add("*TCombobox*Listbox.selectForeground", "#0c1220")
            root.option_add("*TCombobox*Listbox.borderWidth", 0)
            root.option_add("*TCombobox*Listbox.highlightThickness", 0)
            root.option_add("*TCombobox*Listbox.font", (FONT, 9))
        except Exception as _exc:
            crashlog.note(_exc, "gui.theme")
    return s


# Windows draws the title bar itself (DWM), and it only uses the dark variant if
# the window explicitly asks for it. Tk never does, so a freshly created window
# shows a LIGHT title bar until the first activation repaints it - which is why
# a dialog looked half-white until you clicked it.
DWMWA_USE_IMMERSIVE_DARK_MODE = 20        # 19 on Windows 10 builds < 19041

# The title bar is only half of what Windows draws for us. The SYSTEM MENU (the
# one behind the icon in the title bar, or Alt+Space) and the frame around a
# classic ``tk.Menu`` popup are painted by the system too, and they ignore the
# per-window DWM attribute above - they follow a PROCESS-WIDE dark-mode flag that
# lives in undocumented uxtheme exports. Without it a dark app shows a bright
# white system menu in every window (and a light rim around our context menus).
# The exports have no names, only ordinals:
_UXTHEME_SET_PREFERRED_APP_MODE = 135     # AllowDarkModeForApp(BOOL) on 1809
_UXTHEME_FLUSH_MENU_THEMES = 136          # drops the cached (light) menu theme
_PREFERRED_APP_MODE_FORCE_DARK = 2        # not "allow": our UI is dark ALWAYS,
# so following the system theme would leave a light menu on a light Windows.
_DARK_MODE_MIN_BUILD = 17763              # first build with these exports
_app_mode_applied = False


_GWL_STYLE = -16
_WS_MAXIMIZEBOX = 0x00010000


def disable_maximize(window):
    """Take the maximise button off the title bar. No-op off Windows.

    Tk can forbid resizing entirely (``resizable(False, False)``) but not
    maximising alone, and ``maxsize()`` still leaves a maximise button that
    "works" by snapping the window to the cap - which looks like a bug. Removing
    the style bit removes the promise.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        user32 = ctypes.windll.user32
        get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        style = get_long(hwnd, _GWL_STYLE)
        set_long(hwnd, _GWL_STYLE, style & ~_WS_MAXIMIZEBOX)
        # SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0004 | 0x0020)
        return True
    except Exception:
        return False


def apply_dark_app_mode():
    """Put the whole PROCESS in dark mode, for the parts Windows draws itself.

    Covers what ``apply_dark_titlebar`` cannot: the system menu behind the title
    bar icon, the frame Windows puts around a ``tk.Menu`` popup and the native
    file pickers. It is a process flag, not a window one, so calling it once is
    enough - every window created afterwards inherits it.

    Undocumented on purpose (these uxtheme exports have ordinals, no names), so
    it is gated on the build that introduced them and every failure is silent:
    the worst case is the light menu we already had. No-op off Windows.
    """
    global _app_mode_applied
    if _app_mode_applied or not sys.platform.startswith("win"):
        return False
    _app_mode_applied = True          # one attempt per process, success or not
    try:
        import ctypes
        if sys.getwindowsversion().build < _DARK_MODE_MIN_BUILD:
            return False
        uxtheme = ctypes.windll.uxtheme
        set_mode = uxtheme[_UXTHEME_SET_PREFERRED_APP_MODE]
        set_mode.restype = ctypes.c_int
        set_mode.argtypes = (ctypes.c_int,)
        set_mode(_PREFERRED_APP_MODE_FORCE_DARK)
        # Menu themes are cached per process and the cache is already filled with
        # the light one by the time we get here, so asking is not enough.
        flush = uxtheme[_UXTHEME_FLUSH_MENU_THEMES]
        flush.restype = None
        flush.argtypes = ()
        flush()
        return True
    except Exception as _exc:
        crashlog.note(_exc, "gui.theme")
    return False


def apply_dark_titlebar(window):
    """Ask DWM for a dark title bar on this window. No-op off Windows.

    Setting the attribute is not enough on its own: DWM only repaints the
    non-client frame on the next activation, so a window shown without being
    activated (a Toplevel opened while the main window keeps focus) sat there with
    a bright white bar until the user clicked it. Forcing a frame change right
    after makes DWM repaint the bar dark immediately - call this once the window is
    actually mapped (see PanelWindow.open).
    """
    if not sys.platform.startswith("win"):
        return False
    # Piggy-backed here (it is a no-op after the first call) so that no window can
    # ever ask for a dark frame and still get a white system menu inside it.
    apply_dark_app_mode()
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attribute in (DWMWA_USE_IMMERSIVE_DARK_MODE, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value),
                    ctypes.sizeof(value)) == 0:
                # SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0004 | 0x0020)
                return True
    except Exception as _exc:
        crashlog.note(_exc, "gui.theme")
    return False


def style_menu(menu):
    """Dark-theme a classic ``tk.Menu`` (ttk styles do not reach it).

    Only context menus use this now - a menu is never a stand-in for a dropdown
    (see the note next to the combobox styles in ``init_style``).
    """
    try:
        menu.configure(background=BG2, foreground=FG,
                       activebackground=ACC, activeforeground="#0c1220",
                       disabledforeground=DIS_FG, selectcolor=ACC,
                       borderwidth=0, relief="flat", activeborderwidth=0,
                       font=(FONT, 9))
    except Exception as _exc:
        crashlog.note(_exc, "gui.theme")
    return menu


POPDOWN_ROWS = 20                 # ttk's own default popdown height, in rows


def popdown_height(values):
    """Rows to give a combobox popdown so a list that FITS gets no scrollbar.

    ttk adds the popdown scrollbar as soon as the list is longer than ``height``,
    and it renders as a light bar over the near-black dropdown - an eyesore for a
    list that would fit anyway. Asking for exactly as many rows as there are
    values removes it; past ``POPDOWN_ROWS`` we fall back to ttk's own default
    instead of growing a dropdown taller than the screen (the profile list is the
    only one the user can grow without limit).
    """
    return min(len(values), POPDOWN_ROWS)


def unhighlight_combobox(event=None, widget=None):
    """Drop the selection AND the focus ring a readonly combobox keeps after a pick.

    A readonly combobox holds keyboard focus after a mouse selection, so the
    accent focus outline lingers as if the control were still active (it reads
    as "stuck highlighted"). Handing focus to its container clears the ring;
    keyboard users get it back the moment they Tab to it again.
    """
    target = widget if widget is not None else getattr(event, "widget", None)
    if target is None:
        return
    with crashlog.quiet("gui.theme"):
        target.selection_clear()
    with crashlog.quiet("gui.theme"):
        target.master.focus_set()


# -- hand-drawn checkbox indicator -------------------------------------------- #
_CHECK_IMAGES = []          # Tk only keeps a weak grip on PhotoImages
_INDICATOR_READY = [False]


def _tick_pixels(size):
    """Coordinates of the checkmark strokes for a box of ``size`` px."""
    points = []

    def stroke(x1, y1, x2, y2):
        steps = int(max(abs(x2 - x1), abs(y2 - y1))) or 1
        for i in range(steps + 1):
            points.append((int(x1 + (x2 - x1) * i / steps),
                           int(y1 + (y2 - y1) * i / steps)))

    stroke(size * 0.26, size * 0.50, size * 0.44, size * 0.68)
    stroke(size * 0.44, size * 0.68, size * 0.76, size * 0.30)
    return points


def _check_image(size, fill, border, tick=None, gap=0):
    """The indicator, drawn by hand, with ``gap`` transparent px of breathing room.

    The gap is part of the IMAGE on purpose. Padding on the image element is
    swallowed by clam's checkbutton layout (the label ends up glued to the box),
    and a padded, coloured spacer would be wrong on one of the two surfaces the
    checkbuttons live on (page vs card). A fresh Tk photo image is fully
    transparent, so the extra columns simply show whatever is behind them.
    """
    img = tk.PhotoImage(width=size + gap, height=size)
    try:
        img.put(border, to=(0, 0, size, size))
        img.put(fill, to=(1, 1, size - 1, size - 1))
        if tick:
            weight = max(2, size // 7)
            for x, y in _tick_pixels(size):
                img.put(tick, to=(x, y, min(size, x + weight), min(size, y + weight)))
    except Exception as _exc:
        crashlog.note(_exc, "gui.theme")
    return img


def _install_check_indicator(style):
    """Replace clam's checkbox indicator with a crisp, DPI-scaled drawn box."""
    if _INDICATOR_READY[0]:
        return
    try:
        size = max(13, scaled(15))
        gap = max(6, scaled(8))                     # space between box and text
        off = _check_image(size, FIELD, BORDER, gap=gap)
        on = _check_image(size, ACC, ACC, "#0c1220", gap=gap)
        dis = _check_image(size, DIS_BG, DIS_BG, gap=gap)
        hot = _check_image(size, FIELD, ACC, gap=gap)
        _CHECK_IMAGES.extend([off, on, dis, hot])
        style.element_create("Bnt.Checkbutton.indicator", "image", off,
                             ("disabled", dis), ("selected", on), ("active", hot),
                             border=0, sticky="")
        style.layout("TCheckbutton", [
            ("Checkbutton.padding", {"sticky": "nswe", "children": [
                ("Bnt.Checkbutton.indicator", {"side": "left", "sticky": ""}),
                ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                    ("Checkbutton.label", {"sticky": "nswe"})]})]})])
        style.configure("TCheckbutton", padding=(0, scaled(2)))
        _INDICATOR_READY[0] = True
    except Exception:
        # any Tk/theme quirk: fall back to the built-in indicator rather than
        # ending up with a checkbutton that has no indicator at all
        _INDICATOR_READY[0] = False
