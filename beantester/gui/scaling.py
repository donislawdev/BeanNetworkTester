from .. import crashlog
"""DPI / resolution scaling.

Every pixel constant in the GUI goes through ``scaled()``. Tk scales *fonts*
(they are given in points) once ``tk scaling`` is set, but it never scales the
hand-written pixel numbers: treeview column widths, chart margins, wraplengths,
window geometry. Those used to be hard-coded, which is why columns were clipped
even at 100% and unusable at 150%.

Pure functions (``wheel_units`` lives in ``scrollable``; ``initial_geometry``,
``text_width`` and ``scaled`` here) are testable without a display.
"""
BASE_DPI = 96.0

# Smallest screen we support (the window must fit there with room for the
# taskbar and the title bar).
MIN_SUPPORTED = (1366, 768)
CHROME_H = 90          # taskbar + title bar reserve
CHROME_W = 40

_scale = 1.0
_font_probe = None     # a tkfont.Font used to measure text, when Tk is available


def ui_scale():
    """Current UI scale factor (1.0 = 96 DPI)."""
    return _scale


def set_scale(value):
    """Override the scale factor (used by tests)."""
    global _scale
    _scale = max(0.5, min(4.0, float(value or 1.0)))
    return _scale


def scaled(px):
    """A pixel constant, scaled for the current DPI."""
    return int(round(float(px) * _scale))


def init_scaling(root):
    """Derive the scale factor from the real screen DPI and tell Tk about it.

    Called once, right after the Tk root exists (the process is already marked
    DPI-aware by ``cli.main``, so ``winfo_fpixels`` reports physical pixels).
    """
    global _font_probe
    dpi = BASE_DPI
    try:
        dpi = float(root.winfo_fpixels("1i")) or BASE_DPI
    except Exception:
        dpi = BASE_DPI
    set_scale(dpi / BASE_DPI)
    try:
        # points -> pixels for every font given in points (the whole theme)
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception as _exc:
        crashlog.note(_exc, "gui.scaling")
    try:
        import tkinter.font as tkfont
        _font_probe = tkfont.nametofont("TkDefaultFont")
    except Exception:
        _font_probe = None
    return _scale


def text_width(text, padding=16, font=None):
    """Width in pixels needed to show ``text``, DPI-aware.

    Falls back to a font-metric estimate when Tk cannot measure (headless tests,
    the fake tkinter used by the GUI smoke).
    """
    probe = font or _font_probe
    if probe is not None:
        try:
            return int(probe.measure(str(text))) + scaled(padding)
        except Exception as _exc:
            crashlog.note(_exc, "gui.scaling")
    return scaled(len(str(text)) * 7 + padding)


def column_width(header, min_chars=0, padding=22):
    """Treeview column width: fits the header, never below ``min_chars``."""
    return max(text_width(header, padding), scaled(min_chars * 7 + padding))


def initial_geometry(screen_w, screen_h, want=(760, 920), scale=None):
    """Startup window geometry, clamped to the screen and centred.

    Returns ``(width, height, x, y)``. The old code hard-coded ``680x900``,
    which does not fit on a 1366x768 laptop - the bottom bar (START/STOP) and
    the log ended up under the taskbar.
    """
    factor = _scale if scale is None else float(scale)
    max_w = max(320, int(screen_w) - CHROME_W)
    max_h = max(320, int(screen_h) - CHROME_H)
    w = min(int(round(want[0] * factor)), max_w)
    h = min(int(round(want[1] * factor)), max_h)
    x = max(0, (int(screen_w) - w) // 2)
    y = max(0, (int(screen_h) - h) // 3)      # slightly above centre reads better
    return w, h, x, y


def min_window_size(scale=None):
    """Smallest usable window: must still fit on the smallest supported screen."""
    factor = _scale if scale is None else float(scale)
    w = int(round(620 * factor))
    h = int(round(560 * factor))
    return (min(w, MIN_SUPPORTED[0] - CHROME_W),
            min(h, MIN_SUPPORTED[1] - CHROME_H))


def max_window_size(screen_w, screen_h, want=(1280, 1000), scale=None):
    """Largest window we allow.

    BOTH dimensions are capped, not just the width: stretched vertically the form
    stops growing and the page simply gains a slab of empty background under it
    (the log strip has a fixed height), which looks broken rather than roomy.
    The maximise button is removed as well - see ``theme.disable_maximize``.

    The cap is always clamped to the screen, so it can never exceed what fits.
    """
    factor = _scale if scale is None else float(scale)
    w = min(int(round(want[0] * factor)), max(320, int(screen_w) - CHROME_W))
    h = min(int(round(want[1] * factor)), max(320, int(screen_h) - CHROME_H))
    return (w, h)


def geometry_fits(geometry, screen_w, screen_h):
    """True when a saved ``WxH+X+Y`` string still fits on the current screen.

    A geometry restored from ``ui.json`` must be re-validated: the user may have
    unplugged the 4K monitor it was saved on.
    """
    try:
        size, _, rest = str(geometry).partition("+")
        w_s, _, h_s = size.partition("x")
        w, h = int(w_s), int(h_s)
    except (TypeError, ValueError):
        return False
    if w < 320 or h < 320 or w > int(screen_w) or h > int(screen_h):
        return False
    parts = rest.split("+")
    try:
        x, y = (int(parts[0]), int(parts[1])) if len(parts) >= 2 else (0, 0)
    except ValueError:
        return False
    # allow a little off-screen slack, but the title bar must stay reachable
    return -20 <= x <= int(screen_w) - 100 and 0 <= y <= int(screen_h) - 60


# -- pure geometry helpers used by the tooltip and the chart ------------------ #
def tooltip_position(x, y, widget_h, tip_w, tip_h, screen_w, screen_h, margin=6):
    """Where to put a tooltip bubble so it stays on screen.

    The old code always placed it below the widget, so hovering anything near the
    bottom of the display pushed the bubble off the monitor.
    """
    px = x + scaled(18)
    py = y + widget_h + margin
    if py + tip_h > screen_h - margin:          # no room below -> flip above
        py = y - tip_h - margin
    if py < margin:                             # nor above -> clamp
        py = margin
    if px + tip_w > screen_w - margin:
        px = max(margin, screen_w - tip_w - margin)
    if px < margin:
        px = margin
    return int(px), int(py)


def chart_geometry(width, height):
    """Plot area for a canvas of the given size (DPI-aware margins).

    The margins are what they are for a reason:

    * ``mt`` reserves a row ABOVE the plot for the "KB/s" caption. It used to be
      drawn at the same height as the topmost axis value, on top of it - which is
      how "2000" and "KB/s" ended up rendered over each other as "KB/2000".
    * ``mb`` reserves a row BELOW the plot for the time labels, which were drawn
      4 px from the canvas edge and clipped in half.
    """
    ml, mr, mt, mb = scaled(52), scaled(16), scaled(24), scaled(30)
    w = max(1, int(width))
    h = max(1, int(height))
    return dict(ml=ml, mr=mr, mt=mt, mb=mb, w=w, h=h,
                pw=max(1, w - ml - mr), ph=max(1, h - mt - mb))
