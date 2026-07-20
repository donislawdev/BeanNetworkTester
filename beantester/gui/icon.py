"""Window icon: loads ``bean.png`` / ``bean.ico`` or draws the bean itself."""
import base64
import math
import os
import struct
import sys
import zlib
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


def _rgba_png(size, rgba):
    """Encode a ``size``x``size`` RGBA byte buffer as PNG bytes (stdlib only)."""
    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xffffffff))
    raw = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4]
                   for y in range(size))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def _gear_covers(px, py, c, r_hole, r_body, r_out, tooth_half, step):
    """True when supersample point ``(px, py)`` falls on the gear shape."""
    dx, dy = px - c, py - c
    r = math.hypot(dx, dy)
    if r <= r_hole or r > r_out:
        return False
    if r <= r_body:
        return True                     # solid ring body
    ang = math.atan2(dy, dx) % step     # between body and tips: tooth sector only
    return min(ang, step - ang) <= tooth_half


def _make_gear_icon_put(size, color, teeth):
    """Legacy aliased gear (single ``PhotoImage.put`` per pixel), kept as a
    fallback for a Tk build without PNG support (or the test tkinter stub)."""
    img = tk.PhotoImage(width=size, height=size)
    c = (size - 1) / 2.0
    r_out, r_body, r_hole = size * 0.46, size * 0.34, size * 0.16
    tooth_half = (math.pi / teeth) * 0.55
    step = 2.0 * math.pi / teeth
    for y in range(size):
        for x in range(size):
            if _gear_covers(x, y, c, r_hole, r_body, r_out, tooth_half, step):
                img.put(color, to=(x, y))
    return img


def make_gear_icon(size, color, teeth=8, _ss=4):
    """Draw an anti-aliased settings gear as a transparent PhotoImage in ``color``.

    Supersampled ``_ss``x and emitted as an RGBA PNG (stdlib ``zlib``/``struct``,
    no PIL), so edge pixels carry partial alpha and the teeth stay crisp on ANY
    button background - the old per-pixel ``put`` had no alpha and rasterised
    jagged teeth at header size. ``size`` is already DPI-scaled (convention 12).
    Falls back to the aliased routine if the Tk build cannot read PNG data.
    """
    size = max(8, int(size))
    try:
        r, g, b = (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
    except (ValueError, IndexError):
        r = g = b = 0xE4                 # sensible light-grey if colour is odd
    ss = max(1, int(_ss))
    span = size * ss
    c = (span - 1) / 2.0
    r_out, r_body, r_hole = span * 0.47, span * 0.33, span * 0.17
    tooth_half = (math.pi / teeth) * 0.5
    step = 2.0 * math.pi / teeth
    area = ss * ss
    buf = bytearray(size * size * 4)
    for oy in range(size):
        base_y = oy * ss
        for ox in range(size):
            base_x = ox * ss
            cov = 0
            for sy in range(ss):
                yy = base_y + sy
                for sx in range(ss):
                    if _gear_covers(base_x + sx, yy, c, r_hole, r_body, r_out,
                                    tooth_half, step):
                        cov += 1
            if cov:
                i = (oy * size + ox) * 4
                buf[i], buf[i + 1], buf[i + 2] = r, g, b
                buf[i + 3] = (255 * cov) // area
    try:
        return tk.PhotoImage(data=base64.b64encode(_rgba_png(size, bytes(buf))),
                             format="png")
    except tk.TclError:
        return _make_gear_icon_put(size, color, teeth)


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


# Tk's ``iconphoto(True, img)`` is ``-default``: the icon for toplevels created
# FROM NOW ON. On Windows that lands on the window CLASS, and a window that owns
# an icon of its own - which the main window does, from ``iconbitmap(bean.ico)``
# above - keeps showing that one. So the running swap used to be invisible
# exactly where it matters (title bar, taskbar) while the recording dot DID show
# up on the next dialog opened, which is how the bug was spotted. Both calls are
# needed: ``False`` for this window, ``True`` so later windows match the state.
def _set_icon(window, image, default_too=True):
    try:
        if default_too:
            window.iconphoto(True, image)
        window.iconphoto(False, image)
        return True
    except Exception as _exc:
        crashlog.note(_exc, "gui.icon")
        return False


def show_running_icon(window, running):
    """Put the recording-dot icon on ``window`` (and on windows opened later)."""
    if running is None:
        return False
    return _set_icon(window, running)


def show_idle_icon(window, idle):
    """Back to the resting icon, preferring the shipped ``bean.ico``.

    The .ico carries hand-drawn 16/24/32 px frames; ``bean.png`` is a single
    256 px image, so restoring through the photo would leave the taskbar on a
    downscale of it for the rest of the session - softer than the icon the app
    started with, and permanently so after the first capture.
    """
    ok = _set_icon(window, idle) if idle is not None else False
    try:
        ico = resource_path("bean.ico")
        if sys.platform.startswith("win") and os.path.exists(ico):
            window.iconbitmap(ico)
            return True
    except Exception as _exc:
        crashlog.note(_exc, "gui.icon")
    return ok
