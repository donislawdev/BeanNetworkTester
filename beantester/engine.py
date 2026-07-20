"""Threaded engine: capture + delayed re-injection around ``BeanCore``.

Works with real WinDivert (``pydivert``) or any injected object exposing
``recv()`` / ``send()`` / ``close()`` (fakes in tests, ``SyntheticDivert``
in ``--simulate`` mode). Also keeps live statistics, the event log and the
connection log used by the GUI, CLI and reproduction reports.

Note on layering: ``i18n.T`` is used here only to format live log lines in
the UI language (a deliberate leaf dependency); persisted data - event kinds,
event descriptions, reports - is stored as keys/English and translated by the
presentation layer. Scenario orchestration lives in ``scenario_runner``.

Fail-safe (why the watchdog exists)
-----------------------------------
A dead process is harmless: Windows closes the WinDivert handle and traffic
returns to normal. The dangerous state is a process that is still ALIVE with an
open divert but no working capture thread - WinDivert keeps diverting packets
into a queue nobody drains, so the user silently loses connectivity while the
UI still says "running". ``_watchdog_loop`` therefore stops the engine (which
closes the divert = fail-open) as soon as a worker thread dies, and an
``atexit`` hook guarantees the handle is released even on an abrupt shutdown.
The same watchdog enforces the session deadline (``duration``).
"""
import atexit
import heapq
import itertools
import random
import threading
import time
import weakref

from . import portmap
from .core import BeanCore
from .i18n import T
from .scenario_runner import ScenarioRunner
from . import crashlog

WATCHDOG_TICK_S = 0.2      # how often the deadline / worker health is checked

# Every running engine, so the interpreter can never exit with an open divert
# (a leaked handle keeps the WinDivert driver - and its .sys file - loaded).
_LIVE_ENGINES = weakref.WeakSet()


def deadline_reached(deadline, now):
    """Pure helper: has the session deadline passed? (``None`` = no limit)."""
    return deadline is not None and now >= deadline


def _stop_live_engines():
    for engine in list(_LIVE_ENGINES):
        try:
            engine.stop(reason="exit")
        except Exception as _exc:
            crashlog.note(_exc, "engine")


atexit.register(_stop_live_engines)


class BeanEngine:
    def __init__(self, log_fn=lambda *_: None):
        self.log = log_fn
        self.core = BeanCore()
        self._divert = None
        self._running = False
        self._heap = []
        self._counter = itertools.count()
        self._cv = threading.Condition()
        self.max_queue = 20000
        self._slock = threading.Lock()
        self._conns = {}            # connection log: flowkey -> stats
        self._clock = threading.Lock()
        # Sampling RNG for _trim_conns. Deliberately NOT self._rng: that one is
        # seeded and drives the packet decisions, so drawing from it here would
        # make a session's impairments depend on how often the table happened to
        # be trimmed - i.e. it would silently break reproducibility.
        self._rng_evict = random.Random(0)
        self._overflow_warned = 0.0     # rate-limit for the queue-overflow warning
        self._seed = None           # None => random; int => reproducible
        self._rng = random
        self._effective_seed = None  # actually used seed (always concrete after start)
        self._start_wall = None
        self._start_mono = None
        self._filter = ""
        self._events = []           # event log: (elapsed, iso, kind, text)
        self._elock = threading.Lock()
        self._scenario_runner = None
        self._t_cap = None          # capture thread (joined on stop)
        self._t_inj = None          # inject thread (joined on stop)
        self._t_wd = None           # watchdog thread (deadline + worker health)
        self._stop_lock = threading.RLock()
        self._deadline = None       # monotonic time to stop at (None = no limit)
        self._duration = 0.0        # the requested session length, for reports
        self._stop_mono = None      # session clock, frozen at STOP (see now_ref)
        self._stop_wall = None
        self._targeting = None      # live ProcessTargeting, when a target is set
        self._ports = portmap.default_table()   # local port -> process (capture time)
        self.stop_reason = None     # "user" | "duration" | "fault" | "exit"
        self.fault = None           # last fatal worker error, if any
        self.reset_stats()

    def set_seed(self, seed):
        self._seed = None if seed in (None, "", -1) else int(seed)

    def effective_seed(self):
        return self._effective_seed

    def log_event(self, kind, text):
        now = time.monotonic()
        elapsed = (now - self._start_mono) if self._start_mono else 0.0
        with self._elock:
            self._events.append((round(elapsed, 2),
                                 time.strftime("%Y-%m-%d %H:%M:%S"), kind, text))
            if len(self._events) > 5000:
                self._events = self._events[-4000:]

    def events_snapshot(self):
        with self._elock:
            return list(self._events)

    def now_ref(self):
        """The session clock's "now": frozen at STOP.

        Everything the UI derives from a timestamp (a connection's idle time, the
        session duration) must stop moving when the session does - a stopped
        tester that keeps counting seconds is simply lying.
        """
        return self._stop_mono if self._stop_mono is not None else time.monotonic()

    def session_info(self):
        elapsed = (self.now_ref() - self._start_mono) if self._start_mono else 0.0
        stamp = lambda w: (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(w))
                           if w else None)
        return dict(seed=self._effective_seed, filter=self._filter,
                    start=stamp(self._start_wall), start_wall=self._start_wall,
                    stop=stamp(self._stop_wall), stop_wall=self._stop_wall,
                    running=self._running, elapsed=round(elapsed, 1),
                    duration=self._duration, stop_reason=self.stop_reason)

    def time_left(self, now=None):
        """Seconds until the deadline (``None`` when the session has no limit)."""
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - (time.monotonic() if now is None else now))

    # -- thin delegates to the decision core -------------------------------- #
    def set_params(self, *a):
        self.core.set_params(*a)

    def set_buffer(self, *a):
        self.core.set_buffer(*a)

    def set_target(self, active, ports=None):
        """Point the engine at a set of local ports (or a live port container)."""
        if not active:
            self._targeting = None
        self.core.set_target(active, ports)

    def targeting(self):
        """The live ``ProcessTargeting`` in use, if any."""
        return self._targeting

    def target_for(self, matcher):
        """Live targeting for a compiled matcher (reused while the expression holds).

        Rebuilding it on every refresh would throw away the port cache and the
        process-info cache several times a second for nothing.
        """
        from .targeting import ProcessTargeting
        current = self._targeting
        if current is None or current.expression != getattr(matcher, "raw", str(matcher)):
            current = ProcessTargeting(matcher)
            self._targeting = current
        current.refresh()
        return current

    def set_flap(self, *a):
        self.core.set_flap(*a)

    def set_dest(self, *a):
        self.core.set_dest(*a)

    def in_scope_now(self, local_port, remote_ip=None, remote_port=None):
        """Whether a flow is in targeting scope right now (see BeanCore.in_scope)."""
        return self.core.in_scope(local_port, remote_ip, remote_port)

    def targeting_active(self):
        """True when process or destination targeting is narrowing traffic."""
        return self.core.targeting_active()

    def set_lan(self, *a):
        self.core.set_lan(*a)

    def set_block(self, *a):
        self.core.set_block(*a)

    def set_advanced(self, *a):
        self.core.set_advanced(*a)

    def set_spike(self, *a):
        self.core.set_spike(*a)

    def set_nat(self, *a):
        self.core.set_nat(*a)

    def set_rst(self, *a):
        self.core.set_rst(*a)

    def set_schedule(self, *a):
        self.core.set_schedule(*a)

    def reset_now(self, *a):
        self.core.reset_now(*a)
        self.log_event("RESET", "events.manual_reset")

    # -- scenario ------------------------------------------------------------ #
    def is_running(self):
        return self._running

    def start_scenario(self, scenario, base_settings, log=lambda *_: None):
        """Start a background runner that applies scenario steps over time."""
        self._scenario_runner = ScenarioRunner(self)
        self._scenario_runner.start(scenario, base_settings, log)

    def stop_scenario(self):
        if self._scenario_runner is not None:
            self._scenario_runner.stop()

    # -- statistics / connection log ----------------------------------------- #
    def reset_stats(self):
        with self._slock:
            self.st = dict(seen=0, drop_loss=0, drop_overflow=0, corrupted=0,
                           duplicated=0, drop_syn=0, drop_mtu=0, drop_nat=0,
                           drop_rst=0, drop_lan=0, drop_block=0, drop_flap=0,
                           drop_rate=0, drop_shutdown=0, rst_sent=0,
                           bytes_in=0, bytes_out=0,
                           bytes_in_total=0, bytes_out_total=0,
                           queue=0, peak_queue=0)
        # counters back to zero means the warning should be able to fire again:
        # a fresh measurement window that overflows must say so afresh
        self._overflow_warned = 0.0
        with self._clock:
            self._conns.clear()

    def connections_snapshot(self, limit=200):
        """Rows of the connection log.

        ``limit=<int>``  the ``limit`` most recently active flows, newest first.
                         Uses ``heapq.nlargest``: O(n log limit), not a full sort
                         of a table that may hold 200 000 rows.
        ``limit=None``   every flow, UNSORTED - a pointer copy, ~25 ms at the cap.
                         This is what the virtualised tables ask for: they sort by
                         the column the user picked anyway, so sorting here as well
                         was the same 100 ms of work done twice per refresh.

        The copy is taken under the lock; any sorting happens outside it. A sort
        under ``_clock`` would stall the CAPTURE thread, and a stalled capture
        thread means WinDivert is queueing the user's packets into a void.
        """
        with self._clock:
            values = list(self._conns.values())
        if limit is None:
            return values
        return heapq.nlargest(limit, values, key=lambda c: c["last"])

    # A connection row is ~350 B, so the cap IS the memory budget: 200k flows is
    # roughly 70-100 MB, which is what a long capture on a busy machine needs if
    # the tables are to show the session honestly instead of an arbitrary slice.
    MAX_CONNS = 200_000
    EVICT_KEEP = 0.9                    # trim back to this fraction of the cap
    EVICT_SAMPLES = 2000                # stamps sampled to estimate the cutoff

    def _trim_conns(self):
        """Evict the oldest flows once the log outgrows its cap.

        Runs on the WATCHDOG thread, never on the capture thread, and does the
        expensive part without the lock. The old version sorted the whole table
        from inside ``_log_conn`` - i.e. on the capture thread, under ``_clock``.
        At the previous 2000-row cap nobody could feel it; at 200 000 it is a
        ~300 ms freeze of the capture thread, and a frozen capture thread means
        WinDivert is quietly queueing (and then dropping) the user's packets.

        Measured at the cap: sorting = ~300 ms, a sampled cutoff = ~6 ms (no lock)
        plus a scan-and-delete = ~16 ms (lock held). The cutoff is an estimate,
        so the table lands near - not exactly on - ``EVICT_KEEP``; for dropping
        stale flows that is entirely good enough.
        """
        with self._clock:
            if len(self._conns) <= self.MAX_CONNS:
                return
            # a pointer copy, not a deep copy: cheap even at 200k
            values = list(self._conns.values())
        # ---- outside the lock: estimate the activity cutoff from a sample ----
        target_drop = len(values) - int(self.MAX_CONNS * self.EVICT_KEEP)
        if target_drop <= 0:
            return
        sample = [values[self._rng_evict.randrange(len(values))]["last"]
                  for _ in range(min(self.EVICT_SAMPLES, len(values)))]
        sample.sort()
        index = int(len(sample) * target_drop / len(values))
        cutoff = sample[min(index, len(sample) - 1)]
        # ---- lock again, only for the cheap part -----------------------------
        with self._clock:
            doomed = [k for k, c in self._conns.items() if c["last"] <= cutoff]
            for key in doomed:
                self._conns.pop(key, None)

    # kept under its old name: the capture path no longer evicts, but callers
    # (and tests) that ask for a trim explicitly still get one
    _evict_conns = _trim_conns

    def _log_conn(self, key, remote_ip, remote_port, local_port, is_out, size, now,
                  proto="IP", dropped=False, scoped=False):
        if key is None:
            return
        with self._clock:
            c = self._conns.get(key)
            if c is None:
                # NO eviction here: trimming is the watchdog's job (_trim_conns).
                # Doing it on the capture thread meant a new flow could pay for a
                # full sort of the table while holding the lock.
                c = dict(remote_ip=remote_ip, remote_port=remote_port,
                         local_port=local_port, proto=proto, packets=0, bytes=0,
                         bytes_in=0, bytes_out=0, dropped=0, first=now, last=now,
                         dir="", scoped=bool(scoped),
                         proc=self._process_for(local_port),
                         pid=self._pid_for(local_port))
                self._conns[key] = c
            elif not c["proc"]:
                # the socket may not have been in the table yet when the flow
                # appeared - try again while packets keep coming, otherwise the
                # row would stay a "?" forever (resolve the pid on the same retry)
                c["proc"] = self._process_for(local_port)
                if not c.get("pid"):
                    c["pid"] = self._pid_for(local_port)
            c["packets"] += 1
            c["bytes"] += size
            if is_out:
                c["bytes_out"] += size
            else:
                c["bytes_in"] += size
            if dropped:
                c["dropped"] += 1
            # scoped tracks the LATEST packet: targeting can change mid-session,
            # and the row should reflect whether the flow is in scope right now
            c["scoped"] = bool(scoped)
            c["last"] = now
            c["dir"] = "out" if is_out else "in"
            c["proto"] = proto

    def _process_for(self, local_port):
        """Process name owning ``local_port`` right now ("" when unknown).

        Resolved HERE, at capture time, and stored in the connection record: the
        GUI used to look the port up when it *displayed* the row, seconds later,
        by which time the socket was long closed - which is why the process
        column was mostly "?" even when running as Administrator.
        """
        try:
            return self._ports.process_for_port(local_port)
        except Exception as _exc:
            # once(), not note(): this is the capture thread. A port table that
            # started failing turns every row's process into "?" - worth one
            # traceback, not one per packet.
            crashlog.once("engine.ports", _exc)
            return ""

    def _pid_for(self, local_port):
        """PID owning ``local_port`` right now (None when unknown).

        Same reasoning as ``_process_for``: resolved at capture time and stored,
        because the socket is usually gone by the time the row is displayed.
        """
        try:
            return self._ports.pid_for(local_port)
        except Exception as _exc:
            crashlog.once("engine.ports.pid", _exc)
            return None

    def stats_snapshot(self):
        with self._slock:
            s = dict(self.st)
        with self._cv:
            s["queue"] = len(self._heap)
        return s

    def _bump(self, key, n=1):
        with self._slock:
            self.st[key] += n

    # -- lifecycle ------------------------------------------------------------ #
    def start(self, filt, divert=None, duration=0):
        """Start a session.

        ``divert``   - optional object with recv()/send()/close() (tests, --simulate),
        ``duration`` - seconds after which the engine stops itself (0 = no limit).
        """
        # Held for the whole start: a worker can fail (and call stop()) before the
        # remaining threads are even spawned - stop() would then null out the
        # thread handles under our feet.
        with self._stop_lock:
            return self._start_locked(filt, divert, duration)

    def _start_locked(self, filt, divert, duration):
        if self._running:
            # Internal/developer error: the GUI and CLI both guard against
            # this, but a second start would spawn duplicate worker threads
            # sharing one divert (double-processed packets, corrupt stats).
            raise RuntimeError("BeanEngine.start() called while already running")
        if divert is None:
            import pydivert
            from . import driver
            divert = pydivert.WinDivert(filt)
            # a REAL driver was loaded: the kernel now holds its .sys file, so it
            # has to be unloaded before the process leaves (see driver.py)
            driver.mark_driver_used()
            # ...and this is the ONLY moment a native (segfault) crash becomes
            # possible - the kernel driver is now in play - so arm native crash
            # capture now, not at launch (keeps crashes/ from appearing until it
            # can actually be needed). No-op under --simulate/tests (no real driver).
            crashlog.arm_native()
        self._divert = divert
        if hasattr(self._divert, "open"):
            try:
                self._divert.open()
            except Exception as _exc:
                crashlog.note(_exc, "engine")
        self._running = True
        # always establish a concrete seed - this makes EVERY session reproducible
        self._effective_seed = self._seed if self._seed is not None else random.randrange(1, 2**31 - 1)
        self._rng = random.Random(self._effective_seed)
        self._filter = filt
        self._start_wall = time.time()
        self._start_mono = time.monotonic()
        self._stop_mono = self._stop_wall = None
        self.reset_stats()
        with self._elock:
            self._events = []
        self.core.reset_buckets(time.monotonic())
        try:
            self._duration = max(0.0, float(duration or 0))
        except (TypeError, ValueError):
            self._duration = 0.0
        self._deadline = (self._start_mono + self._duration) if self._duration > 0 else None
        self.stop_reason = None
        self.fault = None
        self._t_cap = threading.Thread(target=self._capture_loop, daemon=True)
        self._t_inj = threading.Thread(target=self._inject_loop, daemon=True)
        self._t_wd = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._t_cap.start()
        self._t_inj.start()
        self._t_wd.start()
        _LIVE_ENGINES.add(self)
        self.log(f"{T('log.start_filter')}: {filt}  (seed={self._effective_seed})")
        self.log_event("START", f"filter={filt}, seed={self._effective_seed}"
                                + (f", duration={self._duration:g}s" if self._duration else ""))

    EVENT_BY_REASON = {"duration": "events.duration_reached",
                       "fault": "events.fault"}

    def stop(self, reason="user"):
        """Stop the session and release the divert. Safe to call twice / from any thread."""
        with self._stop_lock:
            if not self._running:
                return
            self._running = False
            self._stop_mono = time.monotonic()
            self._stop_wall = time.time()
            self.stop_reason = reason
            self.stop_scenario()
            self.log_event("STOP", self.EVENT_BY_REASON.get(reason, "events.stopped"))
            with self._cv:
                self._cv.notify_all()
            # closing the divert unblocks a capture thread stuck in recv() AND
            # releases the WinDivert driver (which otherwise keeps its .sys file
            # locked - see beantester/driver.py)
            if self._divert is not None:
                try:
                    self._divert.close()
                except Exception as _exc:
                    crashlog.note(_exc, "engine")
            # join the worker threads before releasing self._divert: they read the
            # attribute live, so a quick stop->start would otherwise leave an old
            # capture thread consuming packets from the NEW session's divert
            for t in (self._t_cap, self._t_inj, self._t_wd):
                if t is not None and t.is_alive() and t is not threading.current_thread():
                    t.join(timeout=2.0)
            self._t_cap = self._t_inj = self._t_wd = None
            self._divert = None
            self._deadline = None
            with self._cv:
                discarded = len(self._heap)
                self._heap.clear()
            if discarded:
                # Packets still queued for delayed injection when the session ended:
                # counted at capture (seen / bytes_*_total) but never delivered. Record
                # them instead of letting them vanish from the seen/delivered/dropped
                # balance - they were dropped BY the shutdown, not lost in transit.
                self._bump("drop_shutdown", discarded)
            _LIVE_ENGINES.discard(self)
            self.log(T("log.stop"))

    def _fail_stop(self, error):
        """A worker died: stop the session so the network is never left impaired."""
        if not self._running:
            return
        self.fault = str(error)
        self.log(T("log.engine_fault", e=self.fault))
        self.stop(reason="fault")

    # -- watchdog -------------------------------------------------------------- #
    def _watchdog_loop(self):
        """Enforce the deadline, keep the connection log bounded, and make a dead
        worker thread fail *open*."""
        while self._running:
            time.sleep(WATCHDOG_TICK_S)
            if not self._running:
                return
            # bounded memory is this thread's job now, so the capture thread never
            # pays for it (see _trim_conns)
            try:
                self._trim_conns()
                # Same principle: freeing a retired 200k flow generation costs
                # ~7-22 ms (measured). The capture thread must not spend that in a
                # tool whose job is to inject a PRECISE amount of latency, so the
                # rotation only hands the dict over and the frees happen here.
                self.core.drain_retired()
            except Exception as _exc:
                crashlog.note(_exc, "engine")
            if deadline_reached(self._deadline, time.monotonic()):
                self.log(T("log.duration_reached", v=f"{self._duration:g}"))
                self.stop(reason="duration")
                return
            for t in (self._t_cap, self._t_inj):
                if t is not None and not t.is_alive():
                    self._fail_stop(RuntimeError(
                        f"worker thread {t.name} died unexpectedly"))
                    return

    # -- worker threads -------------------------------------------------------- #
    def _capture_loop(self):
        rng = self._rng
        while self._running:
            try:
                packet = self._divert.recv()
            except Exception as e:
                if self._running:
                    # The divert is still open but nothing drains it any more:
                    # WinDivert would keep queueing (and then dropping) the user's
                    # packets. Fail OPEN - stop the session and release the driver.
                    self.log(f"{T('log.recv_error')}: {e}")
                    self._fail_stop(e)
                break
            now = time.monotonic()
            size = len(packet.raw)
            is_out = bool(getattr(packet, "is_outbound", True))
            local_port = remote_port = remote_ip = None
            is_syn = is_tcp = False
            try:
                if is_out:
                    local_port, remote_port = packet.src_port, packet.dst_port
                    remote_ip = getattr(packet, "dst_addr", None)
                else:
                    local_port, remote_port = packet.dst_port, packet.src_port
                    remote_ip = getattr(packet, "src_addr", None)
            except Exception as _exc:
                crashlog.once("engine.packet", _exc)
            proto = "IP"
            try:
                if getattr(packet, "tcp", None) is not None:
                    is_tcp = True
                    proto = "TCP"
                    tcp = packet.tcp
                    if getattr(tcp, "syn", False) and not getattr(tcp, "ack", False):
                        is_syn = True
                elif getattr(packet, "udp", None) is not None:
                    proto = "UDP"
                elif getattr(packet, "icmp", None) is not None or getattr(packet, "icmpv6", None) is not None:
                    proto = "ICMP"
            except Exception as _exc:
                crashlog.once("engine.packet", _exc)

            key = BeanCore._flowkey(local_port, remote_ip, remote_port)

            self._bump("seen")
            self._bump("bytes_out_total" if is_out else "bytes_in_total", size)
            dec = self.core.decide(size, is_out, local_port, now, rng,
                                   remote_ip=remote_ip, remote_port=remote_port,
                                   is_syn=is_syn, is_tcp=is_tcp)
            # Log AFTER the decision (decide() reads none of the connection log, so
            # the order is free): the flow row then records whether THIS packet was
            # dropped and whether the flow is in targeting scope - impaired, not
            # merely observed.
            self._log_conn(key, remote_ip, remote_port, local_port, is_out, size,
                           now, proto, dropped=dec.drop, scoped=dec.scoped)
            if dec.drop:
                if dec.emit_rst:
                    self._send_rst(packet)
                self._bump({"syn": "drop_syn", "mtu": "drop_mtu", "nat": "drop_nat",
                            "rst": "drop_rst", "lan": "drop_lan", "block": "drop_block",
                            "flap": "drop_flap", "rate": "drop_rate"}.get(dec.reason, "drop_loss"))
                continue
            if dec.corrupt and self.core.corrupt_packet(packet, rng):
                self._bump("corrupted")
            for rel in dec.releases:
                self._enqueue(rel, packet)
            if len(dec.releases) > 1:
                self._bump("duplicated")

    def _send_rst(self, packet):
        """Inject a TCP RST to the local end to reset the connection."""
        fields = BeanCore.build_rst_fields(packet)
        if not fields:
            return
        rst = self._build_rst_packet(packet, fields)
        if rst is None:
            return
        try:
            self._divert.send(rst)
            self._bump("rst_sent")
        except Exception as e:
            if self._running:
                self.log(f"{T('log.rst_inject_failed')} ({e})")

    def _build_rst_packet(self, packet, fields):
        """Construct the RST packet to inject; ``None`` if it cannot be built.

        The traffic source owns packet construction. A divert that exposes
        ``make_rst`` (``SyntheticDivert`` in --simulate mode, test fakes) builds an
        RST of its own packet type, so the RST path - and the ``rst_sent`` counter
        - can be exercised without WinDivert. The real WinDivert divert has no such
        hook, so this falls back to building a pydivert packet directly.
        """
        maker = getattr(self._divert, "make_rst", None)
        if maker is not None:
            try:
                return maker(packet, fields)
            except Exception as e:
                if self._running:
                    self.log(f"{T('log.rst_inject_failed')} ({e})")
                return None
        try:
            import pydivert
            raw = bytearray(packet.raw)
            rst = pydivert.Packet(memoryview(raw), packet.interface,
                                  pydivert.Direction.INBOUND)
            rst.src_addr, rst.dst_addr = fields["src_ip"], fields["dst_ip"]
            rst.src_port, rst.dst_port = fields["src_port"], fields["dst_port"]
            rst.tcp.rst = True
            rst.tcp.syn = rst.tcp.fin = rst.tcp.psh = rst.tcp.ack = False
            rst.tcp.seq_num = fields["seq_num"]
            rst.payload = b""
            return rst
        except Exception as e:
            if self._running:
                self.log(f"{T('log.rst_inject_failed')} ({e})")
            return None

    # A queue overflow means the TOOL is dropping the user's packets - packets they
    # did not ask to lose. Their measured loss is then not their application's loss,
    # it is ours, and a tester who does not know that will file a bug against the
    # wrong thing. So it has to be loud. But it can happen 150 000 times a second,
    # so it must also be rate-limited, or the log becomes the second bug.
    OVERFLOW_WARN_S = 5.0

    def _warn_overflow(self):
        """Say - once every OVERFLOW_WARN_S - that we are losing packets ourselves."""
        now = time.monotonic()
        if now - self._overflow_warned < self.OVERFLOW_WARN_S:
            return
        first = self._overflow_warned == 0.0
        self._overflow_warned = now
        with self._slock:
            dropped = self.st["drop_overflow"]
        self.log(T("log.queue_overflow", n=dropped, q=self.max_queue))
        if first:
            # in the event log too, so it lands in the repro report: a run whose
            # numbers are wrong must say so in the artefact people read later
            self.log_event("WARN", "events.queue_overflow")

    def _enqueue(self, release, packet):
        with self._cv:
            if len(self._heap) >= self.max_queue:
                self._bump("drop_overflow")
                overflowed = True
            else:
                overflowed = False
                heapq.heappush(self._heap, (release, next(self._counter), packet))
                q = len(self._heap)
                with self._slock:
                    if q > self.st["peak_queue"]:
                        self.st["peak_queue"] = q
                self._cv.notify()
        if overflowed:
            self._warn_overflow()       # outside the lock: it logs, and logging waits

    def _inject_loop(self):
        while self._running:
            with self._cv:
                while self._running and not self._heap:
                    self._cv.wait()
                if not self._running:
                    break
                release, _, packet = self._heap[0]
                now = time.monotonic()
                if release > now:
                    self._cv.wait(timeout=min(release - now, 0.5))
                    continue
                heapq.heappop(self._heap)
            try:
                if self._divert is not None:
                    self._divert.send(packet)
                    if getattr(packet, "is_outbound", True):
                        self._bump("bytes_out", len(packet.raw))
                    else:
                        self._bump("bytes_in", len(packet.raw))
            except Exception as e:
                if self._running:
                    self.log(f"{T('log.send_error')}: {e}")
