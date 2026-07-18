"""Throughput chart: grid, Y axis in KB/s, down/up series and live readouts."""
from ..i18n import T
from ..utils import nice_ceiling
from .scaling import chart_geometry, scaled
from .theme import DOWN_C, FONT, GRID_C, MUT, UP_C


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


def draw_throughput_chart(canvas, down_hist, up_hist, sample_interval_s=0.7):
    """Redraw the throughput chart on the given canvas."""
    c = canvas
    try:
        width = c.winfo_width()
        height = c.winfo_height()
    except Exception:
        width = height = 0
    if not width or width <= 1:
        width = scaled(500)
    if not height or height <= 1:
        height = scaled(200)
    g = chart_geometry(width, height)
    c.delete("all")
    x0, y0, pw, ph = g["ml"], g["mt"], g["pw"], g["ph"]

    peak = nice_ceiling(max(max(down_hist), max(up_hist), 1.0))

    # horizontal grid + Y-axis values (KB/s). Five ticks when there is room, two
    # (floor + peak) when the plot is too short for five labels to stand apart -
    # a short plot stacked them into an unreadable "1 1 0 0", which was the "ugly
    # at a small window" report. Labels carry just enough precision that no two
    # collapse to the same string (with peak=1 the old ":.0f" printed 0,0,0,1,1).
    fracs = (0.0, 0.25, 0.5, 0.75, 1.0) if ph >= scaled(70) else (0.0, 1.0)
    for frac in fracs:
        y = y0 + ph - ph * frac
        c.create_line(x0, y, x0 + pw, y, fill=GRID_C)
        c.create_text(g["ml"] - scaled(8), y, anchor="e", fill=MUT, font=(FONT, 8),
                      text=_axis_label(peak * frac, peak))
    # the unit caption sits ABOVE the plot, not on top of the topmost value
    c.create_text(scaled(6), y0 - scaled(12), anchor="w", fill=MUT, font=(FONT, 8),
                  text="KB/s")

    # X axis labels (time) - inside the bottom margin, not clipped by the edge
    n = len(down_hist)
    baseline = y0 + ph + scaled(12)
    c.create_text(x0, baseline, anchor="w", fill=MUT, font=(FONT, 8),
                  text=f"-{n * sample_interval_s:.0f} s")
    c.create_text(x0 + pw, baseline, anchor="e", fill=MUT, font=(FONT, 8),
                  text=T("chart.now"))

    def plot(hist, color):
        if len(hist) < 2:
            return None
        pts = []
        for i, v in enumerate(hist):
            x = x0 + pw * (i / (len(hist) - 1))
            y = y0 + ph - (min(v, peak) / peak) * ph
            pts += [x, y]
        c.create_line(*pts, fill=color, width=scaled(2), smooth=True)
        r = scaled(3)
        c.create_oval(pts[-2] - r, pts[-1] - r, pts[-2] + r, pts[-1] + r,
                      fill=color, outline="")
        return hist[-1]

    cur_d = plot(down_hist, DOWN_C)
    cur_u = plot(up_hist, UP_C)

    # current values, top-right (they used to sit over the left-hand grid values)
    if cur_d is not None:
        right = x0 + pw - scaled(6)
        c.create_text(right, y0 + scaled(8), anchor="e", fill=DOWN_C,
                      font=(FONT, 9, "bold"), text=T("chart.cur_down", v=f"{cur_d:.0f}"))
        c.create_text(right, y0 + scaled(24), anchor="e", fill=UP_C,
                      font=(FONT, 9, "bold"), text=T("chart.cur_up", v=f"{cur_u:.0f}"))
