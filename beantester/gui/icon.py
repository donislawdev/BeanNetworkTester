"""Window icon: loads ``bean.png`` / ``bean.ico`` or draws the bean itself."""
import math
import os
import sys
import tkinter as tk

from ..paths import resource_path
from .. import crashlog


def _put_dot(img, size):
    """Stamp a red "recording" dot in the lower-right corner of ``img``.

    Pure ``PhotoImage.put`` (no PIL): signals a live capture at a glance and
    stays visible even at 16 px taskbar size.
    """
    dcx, dcy = size * 0.76, size * 0.76
    dr = max(2.0, size * 0.20)
    for y in range(size):
        for x in range(size):
            d = ((x - dcx) / dr) ** 2 + ((y - dcy) / dr) ** 2
            if d > 1.0:
                continue
            img.put("#8a1010" if d > 0.62 else "#e53935", to=(x, y))  # ring + fill


def make_bean_icon(size=64, active=False):
    """Draw the bean icon as a PhotoImage (fallback when ``bean.png`` is missing).

    ``active=True`` adds the red recording dot used while a capture is running.
    """
    img = tk.PhotoImage(width=size, height=size)
    cx, cy = size * 0.52, size * 0.50
    rx, ry = size * 0.37, size * 0.40
    nx, ny = size * 0.16, size * 0.50
    nrx, nry = size * 0.30, size * 0.26
    for y in range(size):
        for x in range(size):
            ox, oy = (x - cx) / rx, (y - cy) / ry
            e = ox * ox + oy * oy
            if e > 1.0:
                continue
            nxr, nyr = (x - nx) / nrx, (y - ny) / nry
            if nxr * nxr + nyr * nyr <= 1.0:
                continue  # kidney notch
            h = (-(x - cx) / rx) + (-(y - cy) / ry)
            if e > 0.86:
                col = "#4a802c"      # outline
            elif h > 0.7:
                col = "#b7e48a"      # highlight
            else:
                col = "#78c24a"      # body
            img.put(col, to=(x, y))
    if active:
        _put_dot(img, size)
    return img


def _running_variant(idle, size=64):
    """Running-state icon: the idle image with a red dot stamped on a copy.

    Copying keeps a user-supplied ``bean.png``'s artwork; if the copy is not
    possible we fall back to drawing the bean ourselves with the dot.
    """
    try:
        w = idle.width() or size
        h = idle.height() or size
        dst = tk.PhotoImage(width=w, height=h)
        dst.tk.call(dst, "copy", str(idle))
        _put_dot(dst, min(w, h))
        return dst
    except Exception as _exc:
        crashlog.note(_exc, "gui.icon")
        return make_bean_icon(size, active=True)


def make_gear_icon(size, color, teeth=8):
    """Draw a settings gear as a transparent PhotoImage in ``color``.

    Pure ``PhotoImage.put`` (no PIL, like the bean): an annulus body, ``teeth``
    rectangular teeth around it and a hollow centre. Only the gear pixels are
    stamped, so the rest stays transparent and the button background shows
    through. ``size`` is already DPI-scaled by the caller (convention 12).
    """
    size = max(8, int(size))
    img = tk.PhotoImage(width=size, height=size)
    c = (size - 1) / 2.0
    r_out = size * 0.46            # tooth tips
    r_body = size * 0.34           # ring outer edge (tooth base)
    r_hole = size * 0.16           # centre hole
    tooth_half = (math.pi / teeth) * 0.55   # angular half-width of one tooth
    step = 2.0 * math.pi / teeth
    for y in range(size):
        for x in range(size):
            dx, dy = x - c, y - c
            r = math.hypot(dx, dy)
            if r <= r_hole or r > r_out:
                continue
            if r <= r_body:
                img.put(color, to=(x, y))   # solid ring body
                continue
            # between body and tips: a pixel only counts inside a tooth sector
            ang = math.atan2(dy, dx) % step
            if min(ang, step - ang) <= tooth_half:
                img.put(color, to=(x, y))
    return img


def apply_window_icon(root):
    """Set the window icon; return ``(idle, running)`` PhotoImages.

    Both are returned so the caller keeps a reference (else Tk garbage-collects
    them) and can swap to the running variant while a capture is live.
    """
    try:
        ico = resource_path("bean.ico")
        if sys.platform.startswith("win") and os.path.exists(ico):
            root.iconbitmap(ico)
    except Exception as _exc:
        crashlog.note(_exc, "gui.icon")
    idle = running = None
    try:
        png = resource_path("bean.png")
        idle = tk.PhotoImage(file=png) if os.path.exists(png) else make_bean_icon(64)
        running = _running_variant(idle)
        root.iconphoto(True, idle)
    except Exception:
        try:
            idle = make_bean_icon(64)
            running = make_bean_icon(64, active=True)
            root.iconphoto(True, idle)
        except Exception:
            idle = running = None
    return idle, running
