"""How long a packet had already waited in WinDivert's queue when this tool got it.

Carved out of ``engine.py`` on 2026-09-30, the way ``connlog.py`` and ``damage.py``
were: a measurement with its own state - the QPC seams, its sample clock, the rate
limit of its warning and its peak - that was reachable only as two methods, three
constants and four attributes on ``BeanEngine``, which sat on its size and
attribute bands with the start order (external review P1-5) still to be fixed.

WinDivert stamps every packet with a QueryPerformanceCounter value (pydivert
``Packet.timestamp``), so this is a MEASUREMENT, not a heuristic - which is why no
heuristic was written. Measured idle on the owner's machine (2026-07-28, real
driver): 0.049-0.163 ms, median ~0.08 ms. The warning threshold is therefore
several hundred times the normal value, not a guess at one: below it there is
nothing to say, above it the tool is adding delay it does not otherwise account
for anywhere.
"""
import time

from . import winenv
from .i18n import T

SAMPLE_S = 0.05         # 20 samples a second, whatever the rate
WARN_MS = 50.0
WARN_S = 5.0            # rate limit, as for the engine's other warnings


class DriverWait:
    """The queue in front of the engine's own: one per engine, reset with its stats.

    ``qpc`` and ``freq`` are seams, so a test can drive the measurement without
    Windows. ``freq`` is asked for when a session starts (``begin``) and only when
    nobody has supplied one: a test that wants the capture loop to measure a known
    wait sets both BEFORE start(), and that must not be overwritten. The frequency
    cannot change, so one call per session is the right price.

    ``peak_ms`` is written by the capture thread only and read by
    ``BeanEngine.stats_snapshot`` without a lock, the way the core's
    ``loss_bursts`` is: one float, and a snapshot may be a moment old. It used to
    live in the stats dict under the stats lock, and the one thing that lock
    bought was that a sample racing a stats reset landed wholly before it or
    wholly after it. Now a sample taken the instant before a reset can outlive it:
    one sample, of a measurement taken 20 times a second.
    """

    def __init__(self, log, log_event):
        self._log, self._log_event = log, log_event
        self.qpc = winenv.qpc_now
        self.freq = None
        self.floor = 0          # QPC when the session's capture thread started
        self.reset()

    def reset(self):
        """A fresh window: no peak, the next packet sampled, the warning armed.

        Armed again because counters back to zero mean a fresh measurement window,
        and one that backs up must say so afresh.
        """
        self.peak_ms = 0.0
        self.next_at = 0.0
        self._warned = 0.0

    def begin(self):
        """A session's capture thread is about to start.

        The QPC frequency (once), the first packet sampled - and the FLOOR: a
        packet stamped before this moment was queued while nothing read the
        handle, so its wait measures how long the START took, not a driver the
        tool cannot keep up with. External review P1-5: the first packet of a
        session was sampled, it was the oldest one in the queue, and a slow start
        (35-56 ms measured, elevated, with a target) became the session's peak and
        a "the driver is dropping packets" warning. Read by the caller the moment
        before the capture thread starts, so what it excludes is exactly the time
        nobody was reading.
        """
        if self.freq is None:
            self.freq = winenv.qpc_frequency()
        self.next_at = 0.0
        self.floor = (self.qpc() or 0) if self.freq else 0

    def sample(self, packet, now):
        """Record how long ``packet`` waited inside the driver before we saw it.

        The capture loop calls this once its monotonic ``now`` has reached
        ``next_at`` - sampled on TIME, not on a packet count (see the loop for
        why), and ``next_at`` moves on here.

        Silent when there is nothing to measure: a synthetic packet has no
        timestamp, and there is no QPC outside Windows. Both are the simulate
        path, which has no driver queue - the same reason
        ``BeanEngine._read_driver_queue`` returns None there. A stamp from the
        future (clock skew, or a stamp this tool did not write) gives a negative
        wait, which neither comparison below can take. A stamp under the floor
        is the start's, not the driver's (see ``begin``).
        """
        self.next_at = now + SAMPLE_S
        stamp = getattr(packet, "timestamp", 0)
        freq = self.freq
        if not stamp or not freq or stamp < self.floor:
            return
        ticks = self.qpc()
        if ticks is None:
            return
        waited_ms = (ticks - stamp) / freq * 1000.0
        if waited_ms > self.peak_ms:
            self.peak_ms = round(waited_ms, 3)
        if waited_ms >= WARN_MS:
            self._warn(waited_ms)

    def _warn(self, waited_ms):
        """Say - once every WARN_S - that the DRIVER is backing up.

        Rate-limited for the reason written above ``BeanEngine.OVERFLOW_WARN_S``.
        It used to be worded as a LATENCY problem ("this wait lands on the delay
        you are measuring"), which is true and is not the half that matters.
        MEASURED 2026-07-28 (real WinDivert, --filter loopback, 64 B UDP flood,
        control run without the tool losing 0.00%): at 138k packets/s offered, the
        tool moved ~14k/s and **91.75% of the traffic was destroyed by the
        driver**, with driver_wait_peak at 198 ms - while drop_overflow,
        drop_shutdown, drop_send and drop_loss all read ZERO. A full driver queue
        is not slow delivery, it is silent loss, and WinDivert exposes no counter
        for it (checked: the DLL exports Get/SetParam only, and params 0-4 are the
        queue triple plus the version). This warning is therefore the ONLY signal
        the tool has for that state, so it has to name the loss.

        Why the numbers land where they do: under saturation the queue sits at its
        limit, so the wait converges on QUEUE_LEN / service rate. At 4096 and
        ~14k/s that is ~290 ms, and the run measured 198-346 ms across three loads.
        The 50 ms threshold is therefore crossed whenever the tool serves below
        ~82k packets/s - do not "tune" it upwards without redoing that arithmetic,
        because it is what makes the state visible at all.
        """
        now = time.monotonic()
        if now - self._warned < WARN_S:
            return
        first = self._warned == 0.0
        self._warned = now
        self._log(T("log.driver_wait", ms=f"{waited_ms:.0f}"))
        if first:
            # into the event log too, so it reaches the repro report
            self._log_event("WARN", "events.driver_wait")
