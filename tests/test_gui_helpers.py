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


def test_min_window_size_never_exceeds_the_smallest_screen():
    for scale in (1.0, 1.5, 2.0):
        w, h = scaling.min_window_size(scale)
        check(f"minsize fits 1366x768 at {scale}x",
              w <= 1366 - scaling.CHROME_W and h <= 768 - scaling.CHROME_H, f"({w}x{h})")


# -- tooltip / chart --------------------------------------------------------- #
def test_tooltip_flips_above_at_the_bottom_of_the_screen():
    _, y = scaling.tooltip_position(100, 1040, 20, 300, 80, 1920, 1080)
    check("tooltip: flips above instead of falling off the screen", y < 1040, f"(y={y})")
    x, _ = scaling.tooltip_position(1900, 100, 20, 300, 80, 1920, 1080)
    check("tooltip: clamped to the right edge", x + 300 <= 1920, f"(x={x})")
    x, y = scaling.tooltip_position(100, 100, 20, 300, 80, 1920, 1080)
    check("tooltip: normal case sits below the widget", y > 100 and x >= 100)


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
