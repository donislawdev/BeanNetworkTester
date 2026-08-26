"""Pure GUI helpers: wheel deltas, DPI scaling, window geometry, tooltip, chart.

None of these import tkinter, so they run everywhere. They are the parts that
used to be hard-coded pixel arithmetic buried inside widget code.
"""
from beantester.gui import scaling
from beantester.gui.wheel import UNITS_PER_NOTCH, wheel_units
from fakes import check


# -- mouse wheel (BUG: the Control page did not scroll) --------------------- #
def test_wheel_units_windows():
    check("wheel: one notch up scrolls up", wheel_units(120, "win32") == -UNITS_PER_NOTCH)
    check("wheel: one notch down scrolls down", wheel_units(-120, "win32") == UNITS_PER_NOTCH)
    check("wheel: three notches at once", wheel_units(-360, "win32") == 3 * UNITS_PER_NOTCH)


def test_wheel_units_precision_touchpad():
    """int(-1 * (delta / 120)) used to return 0 for every sub-notch delta."""
    check("wheel: small delta still scrolls", wheel_units(30, "win32") == -UNITS_PER_NOTCH,
          f"({wheel_units(30, 'win32')})")
    check("wheel: small negative delta still scrolls", wheel_units(-8, "win32") == UNITS_PER_NOTCH)


def test_wheel_units_mac_and_x11():
    check("wheel: macOS reports notches directly", wheel_units(1, "darwin") == -UNITS_PER_NOTCH)
    check("wheel: X11 Button-4 = up", wheel_units(0, "linux", num=4) == -UNITS_PER_NOTCH)
    check("wheel: X11 Button-5 = down", wheel_units(0, "linux", num=5) == UNITS_PER_NOTCH)


def test_wheel_units_clamped_and_safe():
    check("wheel: absurd deltas are clamped",
          abs(wheel_units(100000, "win32")) == 5 * UNITS_PER_NOTCH)
    check("wheel: no delta = no scroll", wheel_units(0, "win32") == 0)
    check("wheel: garbage never raises", wheel_units("x", "win32") == 0)


# -- DPI scaling ------------------------------------------------------------- #
def test_scaled_follows_the_dpi_factor():
    try:
        scaling.set_scale(1.0)
        check("scale: 100% is identity", scaling.scaled(20) == 20)
        scaling.set_scale(1.5)
        check("scale: 150% grows pixels", scaling.scaled(20) == 30)
        scaling.set_scale(2.0)
        check("scale: 200% doubles pixels", scaling.scaled(20) == 40)
        check("scale: column widths grow too", scaling.column_width("packets") > 40)
    finally:
        scaling.set_scale(1.0)


# -- window geometry --------------------------------------------------------- #
def test_initial_geometry_fits_the_smallest_supported_screen():
    w, h, x, y = scaling.initial_geometry(1366, 768, scale=1.0)
    check("geometry: fits 1366x768 (the old 680x900 did not)",
          w <= 1366 - scaling.CHROME_W and h <= 768 - scaling.CHROME_H, f"({w}x{h})")
    check("geometry: window is on screen", 0 <= x and 0 <= y)


def test_initial_geometry_scales_with_dpi():
    _, h_100, _, _ = scaling.initial_geometry(3840, 2160, scale=1.0)
    _, h_200, _, _ = scaling.initial_geometry(3840, 2160, scale=2.0)
    check("geometry: a 200% screen gets a physically similar window",
          h_200 == 2 * h_100, f"({h_100} -> {h_200})")


def test_geometry_fits_rejects_stale_saved_geometry():
    check("geometry: a saved size that no longer fits is rejected",
          not scaling.geometry_fits("2400x1500+10+10", 1366, 768))
    check("geometry: a window parked off-screen is rejected",
          not scaling.geometry_fits("800x600+3000+10", 1366, 768))
    check("geometry: a valid saved geometry is accepted",
          scaling.geometry_fits("800x600+40+40", 1366, 768))
    check("geometry: garbage is rejected", not scaling.geometry_fits("nonsense", 1366, 768))


def _primary_only(x, y):
    """One monitor, 3840x2088 of work area. The nearest one is always this one."""
    return (0, 0, 3840, 2088)


def _second_monitor_right(x, y):
    """A portrait monitor attached to the right of a 3840-wide primary."""
    return (3840, 0, 4920, 1920) if x >= 3820 else (0, 0, 3840, 2088)


def test_geometry_fits_tells_a_second_monitor_from_an_unplugged_one():
    """A window left on a second monitor used to come back on the first one.

    Both checks below use the SAME saved geometry, at x=4000 - past the primary
    monitor's width, so the old code called it "off screen" and threw it away. The
    only thing that separates a window on a second monitor from a window on a
    monitor that has been unplugged is whether that spot is still on a display,
    and nothing but the system can answer that. Hence ``bounds_at``.
    """
    saved = "800x600+4000+100"
    check("geometry: a window on the second monitor is kept",
          scaling.geometry_fits(saved, 3840, 2088, _second_monitor_right))
    check("geometry: the same spot with that monitor gone is rejected",
          not scaling.geometry_fits(saved, 3840, 2088, _primary_only))
    check("geometry: with nothing to ask, the old primary-screen answer stands",
          not scaling.geometry_fits(saved, 3840, 2088))


def test_geometry_fits_accepts_the_monitors_that_have_negative_coordinates():
    """The primary monitor owns the origin, so a monitor left of or above it is at
    negative coordinates - and Tk writes those into ``ui.json`` as "+-1800"."""
    def left(x, y):
        return (-1920, 0, 0, 1080)

    def above(x, y):
        return (0, -1080, 1920, 0)

    check("geometry: a monitor to the left is a valid place for a window",
          scaling.geometry_fits("800x600+-1800+100", 1920, 1080, left))
    check("geometry: so is a monitor above the primary one",
          scaling.geometry_fits("800x600+100+-900", 1920, 1080, above))
    check("geometry: and the numbers are still checked there",
          not scaling.geometry_fits("800x600+-5000+100", 1920, 1080, left))


def test_a_window_bigger_than_the_primary_monitor_still_fits_its_own():
    """The size half of the same assumption: a 4K second monitor next to a laptop
    screen. The saved window fits where it was left, and only the primary screen
    said otherwise."""
    def four_k_on_the_right(x, y):
        return (1366, 0, 5206, 2160)

    check("geometry: judged against the monitor it is on",
          scaling.geometry_fits("2400x1300+1400+100", 1366, 768, four_k_on_the_right))
    check("geometry: and a window that fits NOTHING is still rejected",
          not scaling.geometry_fits("9000x5000+1400+100", 1366, 768,
                                    four_k_on_the_right))


def test_a_window_centres_on_the_monitor_it_is_given():
    x, y = scaling.centred_in((0, 0, 1920, 1080), 800, 600)
    check("centred: on the primary monitor", x == 560 and 0 < y < 200, f"({x}, {y})")
    x, _ = scaling.centred_in((1920, 0, 3000, 1920), 800, 600)
    check("centred: on the second monitor, not back on the first",
          1920 <= x and x + 800 <= 3000, f"(x={x})")
    x, y = scaling.centred_in((-1920, -200, 0, 880), 800, 600)
    check("centred: a monitor at negative coordinates is a monitor",
          -1920 <= x and x + 800 <= 0 and y >= -200, f"({x}, {y})")
    x, y = scaling.centred_in((1920, 0, 2200, 200), 800, 600)
    check("centred: a window bigger than its monitor still STARTS on it",
          (x, y) == (1920, 0), f"({x}, {y})")


def test_min_window_size_never_exceeds_the_smallest_screen():
    for scale in (1.0, 1.5, 2.0):
        w, h = scaling.min_window_size(scale)
        check(f"minsize fits 1366x768 at {scale}x",
              w <= 1366 - scaling.CHROME_W and h <= 768 - scaling.CHROME_H, f"({w}x{h})")


# -- tooltip / chart --------------------------------------------------------- #
def test_tooltip_flips_above_at_the_bottom_of_the_screen():
    screen = (0, 0, 1920, 1080)
    _, y = scaling.tooltip_position(100, 1040, 20, 300, 80, screen)
    check("tooltip: flips above instead of falling off the screen", y < 1040, f"(y={y})")
    x, _ = scaling.tooltip_position(1900, 100, 20, 300, 80, screen)
    check("tooltip: clamped to the right edge", x + 300 <= 1920, f"(x={x})")
    x, y = scaling.tooltip_position(100, 100, 20, 300, 80, screen)
    check("tooltip: normal case sits below the widget", y > 100 and x >= 100)


def test_a_tooltip_stays_on_the_monitor_that_shows_the_widget():
    """Reported 2026-08-26: on a second monitor the bubble opened on the first one.

    The bubble was clamped into ``(0, 0, screen_w, screen_h)``, and on Windows
    that pair is the PRIMARY monitor whatever the window is on - so hovering a "?"
    on a monitor to the right pinned the bubble to the right edge of the primary
    one. Both rectangles below are ones a single-monitor clamp gets wrong, and the
    second is the one easiest to write off as impossible: the primary monitor owns
    the origin, so a monitor left of or above it has NEGATIVE coordinates.
    """
    right = (1920, 0, 3000, 1920)             # portrait monitor, right of primary
    x, y = scaling.tooltip_position(2400, 300, 20, 300, 80, right)
    check("tooltip: opens on the monitor the widget is on",
          1920 <= x and x + 300 <= 3000, f"(x={x})")
    check("tooltip: and still sits below the widget there", y > 300, f"(y={y})")
    x, _ = scaling.tooltip_position(2960, 300, 20, 300, 80, right)
    check("tooltip: clamped to THAT monitor's right edge, not the primary's",
          1920 <= x and x + 300 <= 3000, f"(x={x})")

    left = (-1920, -200, 0, 880)              # monitor left of and above primary
    x, y = scaling.tooltip_position(-1900, 800, 20, 300, 80, left)
    check("tooltip: a negative origin is a position, not an error",
          -1920 <= x and x + 300 <= 0, f"(x={x})")
    check("tooltip: flips above WITHIN the left monitor", -200 <= y < 800, f"(y={y})")


def test_a_tooltip_bigger_than_the_monitor_still_starts_on_it():
    """The degenerate case, kept honest: a bubble wider or taller than the screen.

    It cannot fit, so it will overflow - but it must overflow off the FAR edge
    with its top-left corner still on the monitor, or the text starts off-screen
    and the bubble is unreadable rather than merely clipped.
    """
    monitor = (1920, 0, 2600, 400)
    x, y = scaling.tooltip_position(2000, 100, 20, 900, 700, monitor)
    check("tooltip: oversized bubble starts inside the monitor",
          1920 <= x <= 2600 and 0 <= y <= 400, f"({x}, {y})")


def test_chart_geometry_leaves_room_for_the_axes():
    g = scaling.chart_geometry(600, 200)
    check("chart: plot area inside the margins",
          g["pw"] == 600 - g["ml"] - g["mr"] and g["ph"] == 200 - g["mt"] - g["mb"])
    g = scaling.chart_geometry(10, 10)
    check("chart: never collapses to zero", g["pw"] >= 1 and g["ph"] >= 1)


# -- peak throughput (BUG: session peak read 0 / 0 KB/s for ever) ----------- #
def test_peak_window_reports_a_peak_at_the_real_tick_rate():
    """The reported bug, reproduced as arithmetic.

    App ticks every 700 ms. The old eviction rule (`while len > 2 and
    now - window[0] > 1.0: popleft()`) left exactly two samples 0.7 s apart, and
    the 0.8 s freshness guard then rejected every single one of them. The result
    was not "a slightly wrong peak" - it was `None` on every tick, for ever, so
    the Session page showed 0 / 0 KB/s no matter what the link was doing.
    """
    from beantester.gui.rates import PeakWindow
    window = PeakWindow()
    peak_down = peak_up = 0.0
    bytes_in = bytes_out = 0
    for i in range(12):                       # ~8 s of a session
        now = i * 0.700                       # App.TICK_MS
        bytes_in += int(100 * 1024 * 0.7)     # steady 100 KB/s down
        bytes_out += int(20 * 1024 * 0.7)     # steady  20 KB/s up
        rates = window.add(now, bytes_in, bytes_out)
        if rates is not None:
            peak_down = max(peak_down, rates[0])
            peak_up = max(peak_up, rates[1])
    check("peak: a running session reports a non-zero peak", peak_down > 0 and peak_up > 0,
          f"(down={peak_down:.1f} up={peak_up:.1f} KB/s)")
    check("peak: the peak is the real rate, not a burst artefact",
          abs(peak_down - 100.0) < 1.0 and abs(peak_up - 20.0) < 1.0,
          f"(down={peak_down:.1f} up={peak_up:.1f} KB/s)")


def test_peak_window_is_honest_while_it_is_still_warming_up():
    """Too young to answer is `None`, never 0.0 - a zero would poison the maximum."""
    from beantester.gui.rates import PeakWindow
    window = PeakWindow()
    check("peak: the first sample cannot be a rate", window.add(0.0, 0, 0) is None)
    check("peak: half a window is still not a rate", window.add(0.4, 50_000, 0) is None)


def test_peak_window_averages_over_a_second_not_over_one_tick():
    """A delayed burst released in one tick must not read above the shaper's limit."""
    from beantester.gui.rates import PeakWindow
    window = PeakWindow()
    result = None
    for i in range(6):
        now = i * 0.5
        # 512 KB arrives in a single 0.5 s tick, nothing in the others: a burst.
        bytes_in = 512 * 1024 if i >= 3 else 0
        result = window.add(now, bytes_in, 0)
    check("peak: a one-tick burst is averaged over the window, not over the tick",
          result is not None and result[0] < 600,
          f"(reported {result[0]:.0f} KB/s for a 512 KB burst)")


def test_peak_window_resets_between_sessions():
    from beantester.gui.rates import PeakWindow
    window = PeakWindow()
    for i in range(5):
        window.add(i * 0.7, i * 100_000, 0)
    window.reset()
    check("peak: START clears the window", window.add(99.0, 999_999, 0) is None)


# -- session average throughput (was inline + untested in the Session page) -- #
def test_average_kbps_is_total_bytes_over_elapsed():
    """The Session "avg" figure: lifetime bytes / elapsed, in 1024-based KB/s."""
    from beantester.gui.rates import average_kbps
    check("avg-rate: 1 MB over 1 s is 1024 KB/s",
          abs(average_kbps(1024 * 1024, 1.0) - 1024.0) < 1e-6)
    check("avg-rate: 2048 B over 2 s is 1 KB/s",
          abs(average_kbps(2048, 2.0) - 1.0) < 1e-6)
    check("avg-rate: too little elapsed time reads 0, not a spike",
          average_kbps(500_000, 0.3) == 0.0)
    check("avg-rate: no traffic is 0", average_kbps(0, 10.0) == 0.0)


# -- the running-state icon: BOTH branches ----------------------------------- #
def test_the_running_icon_copies_the_idle_artwork_and_stamps_a_dot():
    """The primary branch: keep a user-supplied ``bean.png``'s artwork and stamp
    the running dot on a COPY of it.

    This branch was unreachable in tests until the tkinter double grew a working
    ``tk.call`` (2026-08-01) - the copy raised, the exception went to crashlog and
    every GUI test silently exercised the fallback below instead. Neither branch
    had a guard, so the swap went unnoticed; this pins both.
    """
    from gui_harness import run_gui
    run_gui("""
        import fake_tk
        from beantester.gui import icon

        idle = icon.make_bean_icon(64)
        fake_tk.INTERP.calls.clear()
        running = icon._running_variant(idle, 64)

        assert running is not None and running is not idle, "it must be a COPY"
        copies = [c for c in fake_tk.INTERP.calls if len(c) > 1 and c[1] == "copy"]
        assert copies, "the idle artwork must be copied, not redrawn: " + str(
            fake_tk.INTERP.calls)
    """)


def test_the_running_icon_falls_back_to_drawing_when_the_copy_is_impossible():
    """A user-supplied PNG that Tk cannot copy must still produce a running icon,
    not an exception on the way to the taskbar."""
    from gui_harness import run_gui
    run_gui("""
        from beantester.gui import icon

        class Hostile:
            def width(self): raise RuntimeError("no size for you")
            def height(self): return 64

        drawn = icon._running_variant(Hostile(), 64)
        assert drawn is not None, "the fallback must still hand back an icon"
    """, allow_faults=("no size for you",))
