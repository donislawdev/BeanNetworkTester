"""Dark theme: colour palette and ttk style configuration.

Two rules this file exists to enforce:

* **Every pixel goes through ``scaled()``** - fonts are in points and follow
  ``tk scaling``, everything else must follow the DPI factor explicitly.
* **A disabled widget must LOOK disabled.** ttk does not do that for free: an
  entry whose ``state`` is ``disabled`` keeps its normal colours unless the
  style declares a ``disabled`` map. Every interactive style below therefore
  carries one - otherwise the user cannot tell whether a field is live.

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
    # a disabled label must grey out too (the field labels next to a switched-off
    # section are set to state=disabled together with their entries)
    for label_style in ("TLabel", "Card.TLabel", "Unit.TLabel", "Hint.TLabel",
                        "Muted.TLabel", "Help.TLabel"):
        s.map(label_style, foreground=[("disabled", DIS_FG)])
    s.configure("TLabelframe", background=BG, foreground=MUT, borderwidth=1,
                bordercolor=LINE_C, lightcolor=LINE_C, darkcolor=LINE_C)
    s.configure("TLabelframe.Label", background=BG, foreground=ACC, font=(FONT, 9, "bold"))

    # -- buttons ------------------------------------------------------------ #
    s.configure("TButton", background=BTN_BG, foreground=FG, borderwidth=1,
                bordercolor=BTN_BORDER, lightcolor=BTN_BG, darkcolor=BTN_BG,
                focuscolor=BTN_BG, relief="flat",
                padding=(scaled(10), scaled(5)), font=(FONT, 9))
    # A focused control MUST look focused (WCAG 2.4.7). clam draws a focus ring
    # from the widget's focuscolor / the border's colour; the theme used to gag it
    # by setting focuscolor to the background, so keyboard users could not tell
    # where they were. Bordered buttons get a solid accent outline on focus; the
    # flat coloured buttons below get a contrasting focuscolor so their ring shows.
    s.map("TButton",
          background=[("disabled", DIS_BG), ("pressed", BTN_BORDER),
                      ("focus", BTN_HOVER), ("active", BTN_HOVER)],
          bordercolor=[("disabled", DIS_BG), ("focus", ACC), ("active", ACC)],
          lightcolor=[("focus", ACC), ("active", BTN_HOVER)],
          darkcolor=[("focus", ACC), ("active", BTN_HOVER)],
          foreground=[("disabled", DIS_FG)])
    s.configure("Accent.TButton", background=ACC, foreground="#0c1220",
                font=(FONT, 10, "bold"), padding=scaled(8), borderwidth=0,
                focuscolor="#0c1220")
    s.map("Accent.TButton",
          background=[("disabled", DIS_BG), ("focus", "#6fb0ff"),
                      ("active", "#6fb0ff")],
          foreground=[("disabled", DIS_FG)])
    # STOP is a different action -> a different colour
    s.configure("Stop.TButton", background=STOP_C, foreground="#1a0d0c",
                font=(FONT, 10, "bold"), padding=scaled(8), borderwidth=0,
                focuscolor="#1a0d0c")
    s.map("Stop.TButton",
          background=[("disabled", DIS_BG), ("focus", "#ff8378"),
                      ("active", "#ff8378")],
          foreground=[("disabled", DIS_FG)])
    # "Apply changes" while the form differs from what the engine runs
    s.configure("Dirty.TButton", background=UP_C, foreground="#20160a",
                font=(FONT, 9, "bold"), padding=scaled(6), borderwidth=0,
                focuscolor="#20160a")
    s.map("Dirty.TButton",
          background=[("disabled", DIS_BG), ("focus", "#ffc978"),
                      ("active", "#ffc978")],
          foreground=[("disabled", DIS_FG)])
    # the "?" cheat-sheet button next to a filter-expression field
    s.configure("Help.TButton", background=BG2, foreground=ACC,
                font=(FONT, 9, "bold"), borderwidth=0, focuscolor=ACC,
                padding=(scaled(3), 0))
    s.map("Help.TButton",
          background=[("focus", BTN_BG), ("active", BTN_BG), ("disabled", BG2)],
          foreground=[("disabled", DIS_FG)])

    # Donate: visible, but an outline button - it must not compete with START,
    # nor look like one of the session controls
    s.configure("Donate.TButton", background=BG, foreground=DONATE_C,
                bordercolor=DONATE_C, lightcolor=BG, darkcolor=BG, focuscolor=DONATE_C,
                font=(FONT, 9, "bold"), borderwidth=1, padding=(scaled(10), scaled(4)))
    s.map("Donate.TButton",
          background=[("focus", "#3a2b33"), ("active", "#3a2b33"),
                      ("disabled", DIS_BG)],
          foreground=[("disabled", DIS_FG)],
          bordercolor=[("focus", DONATE_C), ("active", DONATE_C)])

    # collapsible section header
    s.configure("Section.TButton", background=BG, foreground=ACC,
                font=(FONT, 9, "bold"), borderwidth=0, focuscolor=ACC,
                padding=(scaled(2), scaled(3)), anchor="w")
    s.map("Section.TButton", background=[("focus", BG2), ("active", BG2)])

    # header gear: an icon-only button that opens the Settings window. Flat and
    # on the header background so it sits quietly next to the status/donate, and
    # lights up to BG2 on hover/focus like the section headers.
    s.configure("Gear.TButton", background=BG, borderwidth=0, focuscolor=ACC,
                relief="flat", padding=(scaled(4), scaled(2)))
    s.map("Gear.TButton",
          background=[("focus", BG2), ("active", BG2), ("pressed", BG2),
                      ("disabled", BG)])

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

    # -- menubutton (the profile picker: a grouped menu, not a combobox) ----- #
    # Styled to read like the old combobox (dark field + a down arrow), so the
    # only visible change is that its dropdown groups presets and own profiles
    # under headings that cannot be picked.
    s.configure("TMenubutton", background=FIELD, foreground=FG, arrowcolor=MUT,
                bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                relief="flat", borderwidth=1, padding=scaled(3), focuscolor=FIELD,
                anchor="w")
    s.map("TMenubutton",
          background=[("disabled", DIS_BG), ("focus", "#20242e"), ("active", "#20242e")],
          foreground=[("disabled", DIS_FG)],
          arrowcolor=[("disabled", DIS_FG)],
          bordercolor=[("disabled", DIS_BG), ("focus", ACC), ("active", ACC)],
          lightcolor=[("focus", ACC), ("active", ACC)],
          darkcolor=[("focus", ACC), ("active", ACC)])

    # The profile picker must read like the traffic-filter combobox: a FLAT dark
    # field, no raised arrow button. Borrow the combobox's own field element (same
    # outline + fieldbackground, so the two are pixel-siblings), but for the arrow
    # use the plain ``Menubutton.indicator`` triangle - NOT ``Combobox.downarrow``.
    # clam draws the downarrow as a bordered, sunken button (a lighter #39404e box
    # around the arrow), which stood out as a "white arrow" next to the flat filter
    # combobox; the menubutton indicator is a bare triangle with no box. The label
    # still comes from the menubutton (textvariable) and clicking posts the grouped
    # menu. See gui/pages/control.py.
    try:
        s.layout("Profile.TMenubutton", [
            ("Combobox.field", {"sticky": "nswe", "children": [
                ("Menubutton.indicator", {"side": "right", "sticky": ""}),
                ("Combobox.padding", {"sticky": "nswe", "children": [
                    ("Menubutton.label", {"sticky": "w"})]})]})])
    except Exception as _exc:
        crashlog.note(_exc, "gui.theme")
    s.configure("Profile.TMenubutton", fieldbackground=FIELD, background=FIELD,
                foreground=FG, arrowcolor=MUT, bordercolor=BORDER, lightcolor=BORDER,
                darkcolor=BORDER, borderwidth=1, padding=scaled(2), anchor="w")
    s.map("Profile.TMenubutton",
          fieldbackground=[("disabled", DIS_BG)],
          foreground=[("disabled", DIS_FG)],
          arrowcolor=[("disabled", DIS_FG)],
          bordercolor=[("disabled", DIS_BG), ("focus", ACC), ("active", ACC)],
          lightcolor=[("focus", ACC), ("active", ACC)],
          darkcolor=[("focus", ACC), ("active", ACC)])

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


def style_menu(menu, like_combobox=False):
    """Dark-theme a classic ``tk.Menu`` (ttk styles do not reach it).

    ``like_combobox`` paints the menu like a readonly combobox's popdown - the
    darker ``FIELD`` surface used by ``*TCombobox*Listbox`` in ``init_style`` -
    so the profile picker's dropdown matches the traffic-filter combobox it sits
    next to (a menu on the lighter ``BG2`` card colour read as a different, paler
    control). Context menus keep the default card colour.
    """
    try:
        menu.configure(background=FIELD if like_combobox else BG2, foreground=FG,
                       activebackground=ACC, activeforeground="#0c1220",
                       disabledforeground=DIS_FG, selectcolor=ACC,
                       borderwidth=0, relief="flat", activeborderwidth=0,
                       font=(FONT, 9))
    except Exception as _exc:
        crashlog.note(_exc, "gui.theme")
    return menu


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
