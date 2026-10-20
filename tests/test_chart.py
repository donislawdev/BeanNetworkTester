"""``beantester/gui/chart.py``: the line chart under the Statistics throughput and the
Tools tab's RTT.

The throughput picture is pinned item by item: the two expected lists below were
recorded from ``draw_throughput_chart`` BEFORE it became a caller of the shared
``draw_line_chart`` (2026-10-19), so the refactor is proved to draw the same chart -
every line, label, colour and position. A recording canvas, so no Tk is needed.
"""
from beantester import i18n
from beantester.gui import chart, scaling
from beantester.gui.theme import DOWN_C, FONT, GRID_C, MUT, UP_C
from fakes import check

SMALL, BOLD = (FONT, 8), (FONT, 9, "bold")


class Canvas:
    """Keeps what is drawn, rounded, in the order it is drawn."""

    def __init__(self, w, h):
        self.w, self.h, self.items = w, h, []

    def winfo_width(self):
        return self.w

    def winfo_height(self):
        return self.h

    def delete(self, *_):
        self.items.clear()

    def create_line(self, *pts, **kw):
        # A dash only when there is one: the golden pictures above have none.
        self.items.append(("line", tuple(round(p, 2) for p in pts), kw.get("fill"),
                           kw.get("width"), kw.get("smooth"))
                          + ((kw["dash"],) if "dash" in kw else ()))

    def create_text(self, x, y, **kw):
        self.items.append(("text", round(x, 2), round(y, 2), kw.get("anchor"), kw.get("fill"),
                           kw.get("font"), kw.get("text")))

    def create_oval(self, *pts, **kw):
        self.items.append(("oval", tuple(round(p, 2) for p in pts), kw.get("fill")))


def _grid(y, label, right=484):
    return [("line", (52, y, right, y), GRID_C, None, None),
            ("text", 44, y, "e", MUT, SMALL, label)]


THROUGHPUT = (_grid(170.0, "0") + _grid(133.5, "12") + _grid(97.0, "25") + _grid(60.5, "38")
              + _grid(24.0, "50") + [
    ("text", 6, 12, "w", MUT, SMALL, "KB/s"),
    ("text", 52, 182, "w", MUT, SMALL, "-3 s"),
    ("text", 484, 182, "e", MUT, SMALL, "now"),
    ("line", (52.0, 170.0, 196.0, 140.8, 340.0, 111.6, 484.0, 53.2), DOWN_C, 2, True),
    ("oval", (481.0, 50.2, 487.0, 56.2), DOWN_C),
    ("line", (52.0, 155.4, 196.0, 155.4, 340.0, 155.4, 484.0, 152.48), UP_C, 2, True),
    ("oval", (481.0, 149.48, 487.0, 155.48), UP_C),
    ("text", 478, 32, "e", DOWN_C, BOLD, "down 40 KB/s"),
    ("text", 478, 48, "e", UP_C, BOLD, "up 6 KB/s")])

SHORT = (_grid(60.0, "0.00", 284) + _grid(24.0, "0.01", 284) + [
    ("text", 6, 12, "w", MUT, SMALL, "Mbit/s"),
    ("text", 52, 72, "w", MUT, SMALL, "-1 s"),
    ("text", 284, 72, "e", MUT, SMALL, "now"),
    ("line", (52.0, 52.8, 284.0, 45.6), DOWN_C, 2, True),
    ("oval", (281.0, 42.6, 287.0, 48.6), DOWN_C),
    ("line", (52.0, 56.4, 284.0, 49.2), UP_C, 2, True),
    ("oval", (281.0, 46.2, 287.0, 52.2), UP_C),
    ("text", 278, 32, "e", DOWN_C, BOLD, "down 0 KB/s"),
    ("text", 278, 48, "e", UP_C, BOLD, "up 0 KB/s")])


def _drawn(w, h, draw):
    before, lang = scaling.ui_scale(), i18n.current_language()
    scaling.set_scale(1.0)
    i18n.set_language("en")
    try:
        canvas = Canvas(w, h)
        draw(canvas)
        return canvas.items
    finally:
        scaling.set_scale(before)
        i18n.set_language(lang)


def test_the_rtt_chart_keeps_its_ticks_apart_near_zero_and_says_the_smoothed_value():
    """Loopback reads 0 ms (whole milliseconds): an axis topped at 1 printed
    "1 1 0 0 0" on real Tk (2026-10-19). The readout says that 0 as under one
    millisecond, the way the list and the details do."""
    got = _drawn(230, 125, lambda c: chart.draw_rtt_chart(c, [0, 0, 0], [0, 1, 0], 3))
    ticks = [item[6] for item in got if item[0] == "text" and item[1] == 44]   # left of the plot
    check("five ticks, no number twice", len(ticks) == 5 and len(set(ticks)) == 5, f"({ticks})")
    texts = [item[6] for item in got if item[0] == "text"]
    check("the unit, the span and the smoothed value",
          {"ms", "-3 s", "< 1 ms"} <= set(texts), f"({texts})")
    lines = [item for item in got if item[0] == "line" and item[3] == 2]
    check("the newest measurement under the smoothed value",
          [line[2] for line in lines] == [UP_C, DOWN_C], f"({lines})")


def test_the_throughput_chart_draws_the_picture_it_drew_before_the_shared_chart():
    got = _drawn(500, 200, lambda c: chart.draw_throughput_chart(
        c, [0, 10, 20, 40], [5, 5, 5, 6], sample_interval_s=0.7, unit="kb"))
    check("five ticks, both series and their readouts, item by item", got == THROUGHPUT,
          "\n" + "\n".join(map(repr, got)))
    got = _drawn(300, 90, lambda c: chart.draw_throughput_chart(
        c, [0.2, 0.4], [0.1, 0.3], sample_interval_s=0.7, unit="mbit"))
    check("a short plot: two ticks, decimals that stay apart", got == SHORT,
          "\n" + "\n".join(map(repr, got)))


def test_a_value_of_none_breaks_the_line_instead_of_drawing_a_zero():
    """A ping with no reply is None: the line stops there and starts again after it -
    a 0 ms round trip that never happened was what the prototype drew (rendered)."""
    got = _drawn(500, 200, lambda c: chart.draw_line_chart(
        c, (chart.Series([10, 20, None, 30, 40], DOWN_C),), 40, str, "ms", "-5"))
    lines = [item for item in got if item[0] == "line" and item[2] == DOWN_C]
    check("two pieces of line, two points each", [len(line[1]) for line in lines] == [4, 4],
          f"({lines})")
    lows = [line[1][i] for line in lines for i in range(1, len(line[1]), 2)]
    check("and none of them at the bottom of the plot", 170.0 not in lows, f"({lows})")
    check("the newest value has its dot", [i for i in got if i[0] == "oval"])
    got = _drawn(500, 200, lambda c: chart.draw_line_chart(
        c, (chart.Series([10, 20, 30, None], DOWN_C),), 40, str, "ms", "-4"))
    check("no dot on a newest value that is not there", not [i for i in got if i[0] == "oval"])
    got = _drawn(500, 200, lambda c: chart.draw_line_chart(
        c, (chart.Series([None, 10, None], DOWN_C),), 40, str, "ms", "-3"))
    check("a single point between gaps is no line", not [
        i for i in got if i[0] == "line" and i[2] == DOWN_C], f"({got})")


def test_the_ping_chart_marks_each_lost_ping_on_the_time_axis():
    from beantester.gui.theme import WARN
    got = _drawn(500, 200, lambda c: chart.draw_ping_chart(c, [200, None, 204, 201, None]))
    marks = [item for item in got if item[0] == "line" and item[2] == WARN]
    check("one mark per ping with no reply, at its place on the axis",
          [mark[1][0] for mark in marks] == [160.0, 484.0], f"({marks})")
    check("standing on the time axis", all(mark[1][1] == 170.0 for mark in marks), f"({marks})")
    texts = [item[6] for item in got if item[0] == "text"]
    check("the newest answer is the readout, the span counts pings",
          "201 ms" in texts and "-5" in texts, f"({texts})")
    ticks = [item[6] for item in got if item[0] == "text" and item[1] == 44]
    # 204 x PING_HEADROOM = 265, to the next nice number: 500 (without the room: 250,
    # and the 204 ms line ran through the readout)
    check("room above the highest round trip for the readout", ticks[-1] == "500", f"({ticks})")
    got = _drawn(500, 200, lambda c: chart.draw_ping_chart(c, [None, None]))
    check("nothing came back yet: marks, no line, no readout",
          len([i for i in got if i[0] == "line" and i[2] == WARN]) == 2
          and not [i for i in got if i[0] == "line" and i[2] == DOWN_C], f"({got})")


def test_the_ping_chart_draws_a_dashed_line_where_the_session_changed():
    from beantester.gui.theme import MUT
    values = [200, None, 204, 201, None]
    plain = _drawn(500, 200, lambda c: chart.draw_ping_chart(c, values))
    check("no change: nothing dashed", not [i for i in plain if len(i) == 6], f"({plain})")
    got = _drawn(500, 200, lambda c: chart.draw_ping_chart(c, values, [2]))
    dashed = [item for item in got if item[0] == "line" and len(item) == 6]
    # the third of five pings: halfway along the plot (the lost marks at 160 and 484)
    check("one muted dashed line, upright, at the first ping after the change",
          len(dashed) == 1 and dashed[0][1][0] == dashed[0][1][2] == 268.0
          and dashed[0][1][3] == 170.0 and dashed[0][1][1] < 170.0
          and dashed[0][2] == MUT and dashed[0][5] == chart.CHANGE_DASH, f"({dashed})")
    check("and the rest as before", [i for i in got if len(i) != 6] == plain, f"({got})")
