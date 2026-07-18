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

WINDOW_S = 1.0          # average over this much time
WARMUP_S = 0.8          # below this the window is too young to trust
AVG_MIN_S = 0.5         # session average needs at least this much elapsed time


def average_kbps(total_bytes, elapsed_s, min_elapsed_s=AVG_MIN_S):
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

    def __init__(self, window_s=WINDOW_S, warmup_s=WARMUP_S):
        self.window_s = float(window_s)
        self.warmup_s = float(warmup_s)
        self._samples = deque()      # (t, bytes_in, bytes_out)

    def reset(self):
        self._samples.clear()

    def __len__(self):
        return len(self._samples)

    def add(self, now, bytes_in, bytes_out):
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
