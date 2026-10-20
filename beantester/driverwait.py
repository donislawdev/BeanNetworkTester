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

from . import capture_backend
from . import crashlog
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
        # The clock the platform's driver stamps packets with (capture_backend):
        # QueryPerformanceCounter on Windows, CLOCK_MONOTONIC on Linux - and the
        # words its warnings use, which name that driver.
        backend = capture_backend.current()
        self.qpc = backend.stamp_now
        self._stamp_frequency = backend.stamp_frequency
        self._text = backend.text
        self._overload_counters = backend.overload_counters
        self._overflow_last = None
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
        # The overload counters (watch_overflow): a reset starts their window at
        # the driver's count as last read, not at zero - the driver's count runs
        # for the handle's whole life.
        self._overflow_base = self._overflow_last
        self.bypassed = self.dropped = 0
        self._overflow_warned = 0.0

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
            self.freq = self._stamp_frequency()
        self.next_at = 0.0
        self.floor = (self.qpc() or 0) if self.freq else 0
        # A new session is a new handle, whose overload counts start at zero.
        self._overflow_last = None
        self._overflow_base = None
        self.bypassed = self.dropped = 0
        self._overflow_warned = 0.0

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
        self._log(T(self._text("driver_wait"), ms=f"{waited_ms:.0f}"))
        if first:
            # into the event log too, so it reaches the repro report
            self._log_event("WARN", self._text("driver_wait_event"))

    # -- what an overloaded driver did with packets this tool never got ---------- #
    def watch_overflow(self, divert, now):
        """Fold in the driver's count of packets it let past this tool or dropped.

        Asked by the watchdog tick (5 times a second, off the packet path: one
        ``stats()`` is ~0.1 ms, and calling it while another thread receives was
        measured clean - 560 calls, no error, every packet delivered). A no-op
        where the driver keeps no such count: WinDivert, the simulate path, test
        doubles (``capture_backend.overload_counters`` says ``None``).

        Warned the way the driver wait is - once every WARN_S, the first time into
        the event log - because it is the same state seen from the other side: a
        tool that is not keeping up. The bypassed packets are the reason it has to
        be said at all: they were never impaired, and no other counter knows.
        """
        with crashlog.quiet("driverwait.overflow"):
            counts = self._overload_counters(divert)
            if counts is None:
                return
            if self._overflow_base is None:
                self._overflow_base = counts
            self._overflow_last = counts
            bypassed = counts["bypassed"] - self._overflow_base["bypassed"]
            dropped = counts["dropped"] - self._overflow_base["dropped"]
            grew = bypassed > self.bypassed or dropped > self.dropped
            self.bypassed, self.dropped = bypassed, dropped
            if grew and now - self._overflow_warned >= WARN_S:
                first = self._overflow_warned == 0.0
                self._overflow_warned = now
                self._log(T(self._text("overflow"), bypassed=bypassed, dropped=dropped))
                if first:
                    self._log_event("WARN", self._text("overflow_event"))

    def say_overflow_total(self):
        """At STOP: the session's totals, when there were any (never on Windows).

        From the watchdog's last reading, so up to one tick (0.2 s) of the very end
        may be missing - the handle is closed by then and cannot be asked again.
        """
        if self.bypassed or self.dropped:
            self._log(T(self._text("overflow_total"), bypassed=self.bypassed, dropped=self.dropped))
