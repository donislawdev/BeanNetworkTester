"""Line charts: a grid, a Y axis, one line per series and live readouts.

One drawing, three charts. The Statistics throughput chart came first; the Tools
tab's TCP health and Ping draw round-trip times the same way, so the drawing is
``draw_line_chart`` and each chart is a caller that says what its numbers are.
A value of None is "nothing here" - a ping that came back with no reply - and the
line breaks there rather than diving to a zero that never happened.

Throughput: the series are KB/s, which is what the engine counts and what the
caller holds. The Y axis is LABELLED in whichever unit the reader picked (see
``gui/rates.py``), so the picture is the same and only the numbers beside it
change - the docstring used to say "Y axis in KB/s" and that stopped being
true the moment the preference existed.
"""
import tkinter as tk
from collections.abc import Callable, Sequence
from typing import NamedTuple

from ..i18n import T
from ..nettools.tcphealth import rtt_number
from ..utils import nice_ceiling
from .rates import BASE_LABEL, DEFAULT_UNIT, UNIT_LABEL, in_unit
from .scaling import chart_geometry, scaled
from .theme import BG2, DOWN_C, FONT, GRID_C, MUT, UP_C, WARN


RTT_LEAST_PEAK = 4      # ms: the lowest top of the round-trip axis
PING_HEADROOM = 1.3     # the Ping chart's top: this much above its highest round trip
LINE_PX = 2             # a series' line, and the Ping chart's lost-ping mark
LOST_MARK_PX = 10       # how tall the lost-ping mark stands on the time axis
CHANGE_DASH = (4, 3)    # the Ping chart's line where the session changed: dash, gap


class Series(NamedTuple):
    """One line: its values, oldest first, its colour, and what the top right says
    about its newest value ("" says nothing)."""
    values: Sequence[float]
    color: str
    readout: str = ""


def _axis_label(value, peak):
    """Y-axis number with enough precision that adjacent ticks stay distinct.

    A tiny peak (an idle link sits at peak=1) needs decimals, or 0.25/0.5/0.75
    all round to the same integer and the axis reads "0 0 0 1 1".
    """
    if peak >= 10:
        return f"{value:.0f}"
    if peak >= 1:
        return f"{value:.1f}"
    return f"{value:.2f}"


def draw_throughput_chart(canvas, down_hist, up_hist, sample_interval_s=0.7,
                          unit=DEFAULT_UNIT):
    """Redraw the throughput chart on the given canvas.

    ``unit`` changes the AXIS LABELS and the caption only. The history and the
    plot scale stay in KB/s, which is what the caller holds and what the
    engine counts - converting the data as well would mean the "nice" ceiling
    were computed on one scale and drawn on another, and the shape of the line
    is the same either way.
    """
    peak = nice_ceiling(max(max(down_hist), max(up_hist), 1.0))

    def readout(key, hist):
        return T(key, v=f"{hist[-1]:.0f}") if len(hist) >= 2 else ""

    draw_line_chart(canvas, (Series(down_hist, DOWN_C, readout("chart.cur_down", down_hist)),
                             Series(up_hist, UP_C, readout("chart.cur_up", up_hist))),
                    peak, lambda v: _axis_label(in_unit(v, unit), in_unit(peak, unit)),
                    UNIT_LABEL.get(unit, BASE_LABEL),
                    f"-{len(down_hist) * sample_interval_s:.0f} s")


def chart_canvas(parent, width, height):
    """A canvas for a line chart: the card colour, no focus ring. Here and not in the
    view, because a tk.Canvas takes its colour as an option and a view names none."""
    return tk.Canvas(parent, bg=BG2, highlightthickness=0, width=width, height=height)


def draw_rtt_chart(canvas, smoothed, sample, span_s):
    """TCP health: one connection's round trips in ms, the newest measurement under
    the smoothed value Windows keeps - and the smoothed one said at the top right."""
    # Whole milliseconds on an axis of five ticks: a top under 4 would print the same
    # number twice ("1 1 0 0 0", rendered on loopback, 2026-10-19).
    peak = nice_ceiling(max(max(smoothed, default=0), max(sample, default=0), RTT_LEAST_PEAK))
    readout = (T("tools.tcphealth.chart_now", v=rtt_number(round(smoothed[-1])))
               if len(smoothed) >= 2 else "")
    draw_line_chart(canvas, (Series(sample, UP_C), Series(smoothed, DOWN_C, readout)),
                    peak, lambda v: f"{v:.0f}", T("tools.tcphealth.unit_ms"), f"-{span_s} s")


def _canvas_size(canvas):
    """The canvas's size, or a stand-in while it has none yet (not mapped)."""
    try:
        width = canvas.winfo_width()
        height = canvas.winfo_height()
    except Exception:
        width = height = 0
    if not width or width <= 1:
        width = scaled(500)
    if not height or height <= 1:
        height = scaled(200)
    return width, height


def draw_ping_chart(canvas, values, changes=()):
    """Ping: the round trip of each of the last pings in ms, oldest first, None for one
    that got no reply - a break in the line and a short mark on the time axis there,
    so a lost ping is seen and never read as a 0 ms one. ``changes`` are the indexes
    of the first ping after the session changed: a dashed line across the plot."""
    trips = [v for v in values if v is not None]
    # Room above the highest round trip: the readout stands in the plot's top right
    # corner, and a steady 204 ms under a 250 ms top ran through it (rendered).
    peak = nice_ceiling(max(max(trips, default=0) * PING_HEADROOM, RTT_LEAST_PEAK))
    newest = next((v for v in reversed(values) if v is not None), None)
    readout = T("tools.ping.chart_now", v=rtt_number(newest)) if newest is not None else ""
    draw_line_chart(canvas, (Series(values, DOWN_C, readout),), peak, lambda v: f"{v:.0f}",
                    T("tools.tcphealth.unit_ms"), T("tools.ping.chart_span", n=len(values)))
    if len(values) < 2:
        return
    g = chart_geometry(*_canvas_size(canvas))
    bottom = g["mt"] + g["ph"]
    dash = tuple(scaled(px) for px in CHANGE_DASH)     # at 200% the line is twice as thick
    for i in changes:
        x = g["ml"] + g["pw"] * (i / (len(values) - 1))
        canvas.create_line(x, g["mt"], x, bottom, fill=MUT, dash=dash)
    for i, value in enumerate(values):
        if value is None:
            x = g["ml"] + g["pw"] * (i / (len(values) - 1))
            canvas.create_line(x, bottom, x, bottom - scaled(LOST_MARK_PX), fill=WARN,
                               width=scaled(LINE_PX))


def draw_line_chart(canvas, series: Sequence[Series], peak: float,
                    axis_label: Callable[[float], str], caption: str, span: str):
    """Draw ``series`` on ``canvas``, everything that was on it gone.

    ``peak`` is the top of the Y axis (values above it are drawn at the top), with
    ``axis_label(value)`` at each tick; ``caption`` - the unit - stands above the
    plot and ``span`` with "now" under it. Each series is a line with a dot on its
    newest value, drawn in the order given (the last one on top), and its readout
    goes to the top right, one under another in the same order.
    """
    c = canvas
    g = chart_geometry(*_canvas_size(c))
    c.delete("all")
    x0, y0, pw, ph = g["ml"], g["mt"], g["pw"], g["ph"]

    # horizontal grid + Y-axis values. Five ticks when there is room, two
    # (floor + peak) when the plot is too short for five labels to stand apart -
    # a short plot stacked them into an unreadable "1 1 0 0", which was the "ugly
    # at a small window" report. Labels carry just enough precision that no two
    # collapse to the same string (with peak=1 the old ":.0f" printed 0,0,0,1,1).
    fracs = (0.0, 0.25, 0.5, 0.75, 1.0) if ph >= scaled(70) else (0.0, 1.0)
    for frac in fracs:
        y = y0 + ph - ph * frac
        c.create_line(x0, y, x0 + pw, y, fill=GRID_C)
        c.create_text(g["ml"] - scaled(8), y, anchor="e", fill=MUT, font=(FONT, 8),
                      text=axis_label(peak * frac))
    # the unit caption sits ABOVE the plot, not on top of the topmost value
    c.create_text(scaled(6), y0 - scaled(12), anchor="w", fill=MUT, font=(FONT, 8),
                  text=caption)

    # X axis labels (time) - inside the bottom margin, not clipped by the edge
    baseline = y0 + ph + scaled(12)
    c.create_text(x0, baseline, anchor="w", fill=MUT, font=(FONT, 8), text=span)
    c.create_text(x0 + pw, baseline, anchor="e", fill=MUT, font=(FONT, 8),
                  text=T("chart.now"))

    def plot(hist, color):
        if len(hist) < 2:
            return False
        # None is "no value here" (a lost ping): the line BREAKS there instead of
        # diving to zero, which would draw a 0 ms round trip that never happened.
        runs, pts = [], []
        for i, v in enumerate(hist):
            if v is None:
                if pts:
                    runs.append(pts)
                pts = []
                continue
            x = x0 + pw * (i / (len(hist) - 1))
            y = y0 + ph - (min(v, peak) / peak) * ph
            pts += [x, y]
        if pts:
            runs.append(pts)
        for run in runs:
            if len(run) >= 4:
                c.create_line(*run, fill=color, width=scaled(LINE_PX), smooth=True)
        if hist[-1] is not None and runs:
            r = scaled(3)
            last = runs[-1]
            c.create_oval(last[-2] - r, last[-1] - r, last[-2] + r, last[-1] + r,
                          fill=color, outline="")
        return bool(runs)

    drawn = [line for line in series if plot(line.values, line.color)]

    # current values, top-right (they used to sit over the left-hand grid values)
    right = x0 + pw - scaled(6)
    for row, line in enumerate(line for line in drawn if line.readout):
        c.create_text(right, y0 + scaled(8 + 16 * row), anchor="e", fill=line.color,
                      font=(FONT, 9, "bold"), text=line.readout)
