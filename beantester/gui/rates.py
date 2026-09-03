"""Throughput averaging - a pure helper, so the number on screen can be tested.

Why this is not a one-liner in ``App._sample``:

A tick delta is a bad ruler for a *peak*. The UI timer is nominally 700 ms and
drifts under load, the injector releases a delayed burst in one go, and the token
bucket shapes the AVERAGE rate rather than any single 700 ms window. Divide a burst
by a short-and-slightly-wrong dt and the peak comes out ABOVE the configured limit
("limit 256 KB/s, peak 278 KB/s"), which reads as a bug in the shaper. So the peak
is averaged over a full second.

The bug this class was extracted to fix: the eviction rule dropped the sample that
made the window a second wide.

    while len(window) > 2 and (now - window[0][0]) > WINDOW:   # WRONG
        window.popleft()

With ticks 0.7 s apart the window settled on exactly two samples 0.7 s apart, the
0.8 s freshness guard rejected every one of them, and the session's "peak
download / upload" therefore read **0 / 0 KB/s for ever**. It had no test, which is
why it survived: it is not a GUI problem, it is arithmetic wearing a GUI costume.

The rule below evicts a sample only when the one BEHIND it is still old enough to
anchor the window, so the span is always >= WINDOW once the session is warm.
"""
from collections import deque
from typing import Optional

from ..fields import FIELD_DEFS

# -- units ------------------------------------------------------------------ #
# Everything inside this program counts throughput in KB/s, where K is 1024: the
# CLI flags, the config file, the schedule string, the shipped scenarios and the
# NDJSON `down_kbps`/`up_kbps` fields all carry that number, and several of them
# are frozen contracts. So the unit preference is a DISPLAY choice and nothing
# else - it converts on the way to the screen and never on the way to a file.
#
# 🔴 The Mbit/s factor is the one number here that surprises people, so it is
# derived in the open rather than typed: 1 KB/s is 1024 bytes, a byte is 8 bits,
# and a megabit is 1e6 bits (decimal, as every network interface and every ISP
# means it). That makes 1024 KB/s come out as 8.389 Mbit/s and NOT 8.0. Rounding
# it to 8 would be a 4.9% lie in the direction people already expect, which is
# exactly the kind of number that never gets questioned again.
BASE_LABEL = "KB/s"
RATE_UNITS = (
    ("kb", BASE_LABEL, 1.0),
    ("mbit", "Mbit/s", 1024.0 * 8.0 / 1_000_000.0),
    ("mb", "MB/s", 1.0 / 1024.0),
)
UNIT_FACTOR = {key: factor for key, _, factor in RATE_UNITS}
UNIT_LABEL = {key: label for key, label, _ in RATE_UNITS}
DEFAULT_UNIT = RATE_UNITS[0][0]

# Which settings fields carry a throughput in the base unit. A VIEW over the
# field registry rather than a list of names, so a third rate field is picked up
# by declaring its unit and nothing here has to remember it.
RATE_FIELD_KEYS = tuple(f.key for f in FIELD_DEFS if f.unit == BASE_LABEL)


def in_unit(kbps, unit):
    """A KB/s figure expressed in ``unit``. Unknown units read as the base one."""
    try:
        value = float(kbps)
    except (TypeError, ValueError):
        return 0.0
    return value * UNIT_FACTOR.get(unit, 1.0)


def format_rate(kbps, unit):
    """``kbps`` rendered in ``unit``, with the precision that unit needs.

    KB/s keeps the whole numbers it has always printed. The other two are smaller
    numbers - 1024 KB/s is 1.0 MB/s - so printing them the same way would round a
    real speed limit to "0" and make the readout look broken. Three significant
    figures, which is what ``utils.human_bytes`` settled on for the same reason.
    """
    value = in_unit(kbps, unit)
    if unit == DEFAULT_UNIT:
        return f"{value:.0f}"
    if value >= 100:
        return f"{value:.0f}"
    return f"{value:.1f}" if value >= 10 else f"{value:.2f}"


def rate_with_unit(kbps, unit):
    """``format_rate`` plus the unit, for the places that print both together."""
    return f"{format_rate(kbps, unit)} {UNIT_LABEL.get(unit, BASE_LABEL)}"


WINDOW_S = 1.0          # average over this much time
WARMUP_S = 0.8          # below this the window is too young to trust
AVG_MIN_S = 0.5         # session average needs at least this much elapsed time


def average_kbps(total_bytes: float, elapsed_s: float,
                 min_elapsed_s: float = AVG_MIN_S) -> float:
    """Session-average throughput in KB/s (1024-based), or 0 while too young.

    ``total_bytes / elapsed`` is the honest lifetime average, but dividing by an
    ``elapsed`` still near zero at the first tick prints an absurd spike, so the
    figure stays 0 until the session has run ``min_elapsed_s``. Pure and tested;
    the value used to be computed inline in the Statistics page from a MB figure
    already rounded to two decimals - this keeps the full-precision byte count.
    """
    return total_bytes / 1024.0 / elapsed_s if elapsed_s > min_elapsed_s else 0.0


class PeakWindow:
    """Sliding window over cumulative byte counters -> KB/s, averaged over ~1 s."""

    def __init__(self, window_s: float = WINDOW_S, warmup_s: float = WARMUP_S) -> None:
        self.window_s = float(window_s)
        self.warmup_s = float(warmup_s)
        self._samples: deque[tuple[float, int, int]] = deque()

    def reset(self) -> None:
        self._samples.clear()

    def __len__(self) -> int:
        return len(self._samples)

    def add(self, now: float, bytes_in: int,
            bytes_out: int) -> Optional[tuple[float, float]]:
        """Record a snapshot; return ``(down_kbs, up_kbs)`` or ``None`` if too young.

        ``None`` means "no honest answer yet", not "zero" - the caller must not
        fold it into a maximum.
        """
        samples = self._samples
        samples.append((float(now), int(bytes_in), int(bytes_out)))

        # Keep the OLDEST sample that still anchors a full window: drop samples[0]
        # only while samples[1] is itself at least a window old.
        while len(samples) > 2 and (now - samples[1][0]) >= self.window_s:
            samples.popleft()

        t0, in0, out0 = samples[0]
        span = now - t0
        if span < self.warmup_s:
            return None
        down = max(0.0, (bytes_in - in0) / 1024.0 / span)
        up = max(0.0, (bytes_out - out0) / 1024.0 / span)
        return down, up
