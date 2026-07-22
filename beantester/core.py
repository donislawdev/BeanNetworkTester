"""Decision core - pure, testable without WinDivert.

``BeanCore.decide()`` inspects a single packet's metadata and returns a
``Decision``. The pipeline order (numbered below) is part of the contract:
1) process targeting -> 2) destination targeting -> 2b) LAN mode
-> 2c) blocking (firewall) -> 3) NAT -> 4) RST -> 5) flapping -> 6) MTU
-> 7) SYN -> 8) loss -> 9) corruption -> 10) latency/jitter/spike
-> 11) bandwidth (per-direction token bucket) -> 12) duplication.
"""
import random
import threading
import time
from typing import List, NamedTuple, Optional

from .matchers import KIND_INT, KIND_IP, PORT_BOUNDS, parse_matcher, port_expression
from .utils import clamp01, is_local_ip


class Decision(NamedTuple):
    """Outcome for a single packet.

    ``releases`` lists the times at which the packet (and any duplicate)
    should be injected; ``reason`` names the drop cause for statistics and
    ``emit_rst`` asks the engine to inject a TCP RST toward the app.
    """
    drop: bool
    corrupt: bool
    releases: List[float]
    reason: Optional[str] = None
    emit_rst: bool = False
    # True when the packet passed the targeting gate (steps 1-2), i.e. this flow
    # is in scope for impairment. False only when process/destination targeting
    # excluded it. Lets the engine mark which connections are actually being
    # impaired, not merely observed. Every impairment path leaves it True.
    scoped: bool = True


MAX_FLOWS = 200_000         # hard ceiling on each flow table (see _FlowTable)
FLOW_ROTATE_S = 30.0        # a flow survives at least this long without traffic


class _FlowTable:
    """Flow bookkeeping that is bounded in SIZE, not only in age, and evicts in O(1).

    Two things have to be true of this table at once, and the old dict was only
    ever one of them:

    * **It must not grow without a ceiling.** The previous version pruned by AGE
      only (drop anything idle for 60 s), so its steady state was
      ``(new flows per second) x 60`` with no upper bound at all. For a browser
      that is a few thousand entries. But this is a network TESTER - it gets
      pointed at load generators, port scans and connection-churn tests, which
      open tens of thousands of short-lived flows a second. Measured: at 50 000
      new flows/s the table settled at **3.2 million entries and 779 MB**.

    * **It must never do O(n) work in the packet hot path.** The age prune rebuilt
      the whole dict, INSIDE ``decide()``, under ``core._lock``. Measured: 30 ms at
      100 000 entries, 124 ms at 640 000, and **1001 ms at 3.2 million - a full
      second with the capture thread frozen, every 5 seconds**. A frozen capture
      thread means WinDivert is queueing the user's packets into a void, which is
      the exact failure FAIL-OPEN exists to prevent. The memory was the symptom;
      this was the disease.

    So: two generations. Writes always land in ``_new``; lookups check ``_new``
    then ``_old``. When ``_new`` fills its half of the budget (or the age window
    passes), ``_old`` is **dropped whole** and ``_new`` takes its place. That is a
    dict deallocation - O(1) - instead of a rebuild, and total residency is capped
    at ``limit``.

    The trade: under heavy churn a flow can be forgotten before it is ``limit``
    seconds old. That is the SAFE direction. A forgotten flow reads back as
    ``None``, which the NAT check treats as "never seen" - so the packet passes.
    Eviction can therefore cost a missed NAT-expiry drop (a false negative); it can
    never invent one (a false positive). Losing an impairment is acceptable; a
    frozen capture thread is not.
    """

    __slots__ = ("_new", "_old", "_limit", "_half", "_rotate_s", "_next_rotate",
                 "_retired")

    def __init__(self, limit=MAX_FLOWS, rotate_s=FLOW_ROTATE_S):
        self._limit = max(2, int(limit))
        self._half = max(1, self._limit // 2)
        self._rotate_s = float(rotate_s)
        self._new = {}
        self._old = {}
        self._next_rotate = 0.0
        # Retired generations wait here to be freed by the WATCHDOG, not by the
        # capture thread. Dropping the last reference to a dict is O(1) in Python
        # but O(n) in CPython's teardown: freeing a 200 000-entry generation costs
        # ~7 ms (measured), and up to 22 ms in the engine. That is a stall in the
        # packet hot path, inside core._lock - in a tool whose entire job is to
        # inject a PRECISE amount of latency. So the rotation only moves a
        # reference; somebody else pays for the funeral.
        self._retired = []

    def get(self, key, default=None):
        value = self._new.get(key)
        if value is not None:
            return value
        value = self._old.get(key)
        return default if value is None else value

    def set(self, key, value):
        self._new[key] = value
        self._enforce_ceiling()

    def touch(self, key, value):
        """Read the previous value and write the new one in a single lookup pass."""
        previous = self.get(key)
        self._new[key] = value
        self._enforce_ceiling()
        return previous

    def _rotate(self):
        """Retire a generation. Truly O(1): nothing is freed on this thread."""
        if self._old:
            self._retired.append(self._old)    # the watchdog frees it
        self._old = self._new
        self._new = {}

    def _enforce_ceiling(self):
        """The SIZE bound is checked on every write - a ``len()`` and a compare.

        It used to be checked only from ``_prune()``, which is throttled to once a
        second, so between two checks the table could take on a whole second of
        churn unopposed. Measured at 150 000 new flows/s: the table peaked at
        299 999 entries against a 200 000 ceiling - bounded, but 50% over the
        number the tests assert. A ceiling that only holds at the churn rates we
        happened to test is not a ceiling.

        The AGE rotation stays throttled (``maybe_rotate``): time passing is not
        urgent, a table filling up is.
        """
        if len(self._new) >= self._half:
            self._rotate()

    def maybe_rotate(self, now):
        """Retire a generation on AGE. O(1): the old dict is handed to the watchdog."""
        if len(self._new) < self._half and now < self._next_rotate:
            return False
        self._rotate()
        self._next_rotate = now + self._rotate_s
        return True

    def drain_retired(self):
        """Hand the retired generations to the caller, who pays for freeing them."""
        retired, self._retired = self._retired, []
        return retired

    def clear(self):
        # the caller may be the capture thread (reset_buckets), so the generations
        # go to the graveyard rather than being freed here
        if self._new:
            self._retired.append(self._new)
        if self._old:
            self._retired.append(self._old)
        self._new = {}
        self._old = {}
        self._next_rotate = 0.0

    def __len__(self):
        return len(self._new) + len(self._old)

    def __contains__(self, key):
        return key in self._new or key in self._old


class BeanCore:
    """Decide what to do with a single packet. No network dependency."""

    def __init__(self):
        self._lock = threading.Lock()
        # impairments
        self.loss = 0.0
        self.corrupt = 0.0
        self.dup = 0.0
        self.latency_s = 0.0
        self.jitter_s = 0.0
        self.rate_down = 0          # B/s (inbound), 0 = unlimited
        self.rate_up = 0            # B/s (outbound)
        self._bucket = {True: 0.0, False: 0.0}
        # Bounded link buffer for the rate limiter, in SECONDS of queueing delay.
        # 0 == unbounded (the legacy token bucket, which could run seconds ahead of
        # real time - see decide() step 11). A real shaped link has a finite buffer;
        # bounding it caps the added latency AND lets a rate INCREASE take effect
        # (a stale bucket used to swallow every later high-rate step). The core
        # default is 0 so a bare BeanCore()/set_params() keeps the old behaviour;
        # production sets it through apply_settings (DEFAULT_SETTINGS["buffer"]).
        self.buffer_s = 0.0
        # targeting
        self.target_active = False
        self.target_ports = set()
        self.dst_active = False
        self.dst_ip = ""            # raw expression text (for summaries/reports)
        self.dst_port = ""          # raw expression text
        self.dst_ip_matcher = parse_matcher("", KIND_IP)
        self.dst_port_matcher = parse_matcher("", KIND_INT)
        self.lan_only = False       # LAN mode: cuts internet traffic (public addresses)
        # blocking (firewall): drop traffic to matching destinations. The two
        # expressions combine with OR, and an EMPTY expression does not take part -
        # so block_port='443' with no block_ip blocks 443 to ANY address rather than
        # blocking everything. Applied after the targeting gate (next to LAN mode),
        # so pointing the tool at a process blocks only that process's traffic.
        self.block_active = False
        self.block_ip = ""          # raw expression text (for summaries/reports)
        self.block_port = ""        # raw expression text
        self.block_ip_matcher = parse_matcher("", KIND_IP)
        self.block_port_matcher = parse_matcher("", KIND_INT)
        # advanced impairments
        self.flap_enabled = False
        self.flap_period_s = 0.0
        self.flap_down = 0.0
        self.syn_drop = 0.0
        self.max_size = 0
        self.spike_prob = 0.0       # chance of a latency spike
        self.spike_s = 0.0          # extra delay during a spike
        # NAT mapping expiry
        self.nat_timeout_s = 0.0    # >0 => after this many idle s the mapping disappears
        # RST injection (connection reset)
        self.rst_prob = 0.0         # chance a TCP packet resets its own flow
        self.rst_cooldown_s = 3.0
        self._reset_now_deadline = 0.0
        # variable throughput over time: [(dur_s, down_bps, up_bps), ...]
        self.schedule = []
        self._sched_total = 0.0
        self._sched_start = 0.0
        self._session_start = 0.0   # session clock zero (see reset_buckets)
        # flow state - BOUNDED (size and age); see _FlowTable
        self._flow_last = _FlowTable()      # flowkey -> last activity
        self._reset_until = _FlowTable()    # flowkey -> RST cooldown deadline
        self._prune_next = 0.0      # earliest time the next rotation may run

    # -- setters ----------------------------------------------------------- #
    @staticmethod
    def _rate_bps(kbps):
        """KB/s -> B/s. A POSITIVE limit never rounds down to 0 (== unlimited).

        ``int(0.0005 * 1024) == 0`` used to turn a tiny-but-real cap into no cap at
        all, so ``--down 0.0005`` behaved like ``--down 0``. A positive value now
        floors at 1 B/s: an extremely slow link, which is what was asked for.
        """
        bps = int(kbps * 1024)
        if bps <= 0 and kbps > 0:
            bps = 1
        return max(0, bps)

    def set_params(self, loss_pct, corrupt_pct, dup_pct,
                   latency_ms, jitter_ms, down_kbps, up_kbps):
        with self._lock:
            self.loss = clamp01(loss_pct / 100.0)
            self.corrupt = clamp01(corrupt_pct / 100.0)
            self.dup = clamp01(dup_pct / 100.0)
            self.latency_s = max(0.0, latency_ms) / 1000.0
            self.jitter_s = max(0.0, jitter_ms) / 1000.0
            self.rate_down = self._rate_bps(down_kbps)
            self.rate_up = self._rate_bps(up_kbps)

    def set_buffer(self, buffer_ms):
        """Bounded link buffer for the rate limiter, in ms. 0 == unbounded."""
        with self._lock:
            self.buffer_s = max(0.0, buffer_ms) / 1000.0

    def set_target(self, active, ports=None):
        """Point the core at a set of local ports.

        ``ports`` may be a plain set (tests, one-shot resolution) **or** a live
        container implementing ``__contains__`` - see
        :class:`beantester.targeting.ProcessTargeting`, which re-resolves itself
        when it is asked about a port it has never seen. The hot-path test in
        ``decide()`` (``local_port not in self.target_ports``) is the same either
        way, which is exactly why targeting could be made live without touching
        the decision pipeline.
        """
        with self._lock:
            self.target_active = bool(active)
            if ports is None:
                self.target_ports = set()
            elif isinstance(ports, (set, frozenset, list, tuple)):
                self.target_ports = set(ports)
            else:
                self.target_ports = ports

    def set_dest(self, active, ip=None, port=None):
        """Destination targeting. ``ip``/``port`` are filter expressions (see
        :mod:`beantester.matchers`): a plain value still works, but so do lists,
        ranges, CIDR, wildcards, comparisons, ``re:`` patterns and ``!`` exclusions.

        Raises a translated ``ValueError`` on a malformed expression; callers
        (GUI, CLI, ``apply_settings``) validate before applying.
        """
        ip_matcher = parse_matcher(ip, KIND_IP, "fields.ip")
        port_matcher = parse_matcher(port_expression(port), KIND_INT, "fields.port",
                                     bounds=PORT_BOUNDS)
        with self._lock:
            self.dst_active = bool(active)
            # raw text is kept for summaries/reports; the matchers do the work
            self.dst_ip = ip_matcher.raw
            self.dst_port = port_matcher.raw
            self.dst_ip_matcher = ip_matcher
            self.dst_port_matcher = port_matcher

    def set_lan(self, enabled):
        with self._lock:
            self.lan_only = bool(enabled)

    def set_block(self, active, ip=None, port=None):
        """Blocking (firewall). ``ip``/``port`` are filter expressions (see
        :mod:`beantester.matchers`), so lists, ranges, CIDR, wildcards, ``re:``
        patterns and ``!`` exclusions all work.

        A packet is dropped (reason ``block``) when its destination matches a
        NON-EMPTY block expression - IP OR port. An empty expression does not take
        part, so ``port='443'`` with no IP blocks 443 to any address rather than
        blocking everything. Raises a translated ``ValueError`` on a malformed
        expression; callers (GUI, CLI, ``apply_settings``) validate before applying.
        """
        ip_matcher = parse_matcher(ip, KIND_IP, "fields.ip")
        port_matcher = parse_matcher(port_expression(port), KIND_INT, "fields.port",
                                     bounds=PORT_BOUNDS)
        with self._lock:
            self.block_active = bool(active)
            self.block_ip = ip_matcher.raw
            self.block_port = port_matcher.raw
            self.block_ip_matcher = ip_matcher
            self.block_port_matcher = port_matcher

    def set_flap(self, enabled, period_s, down_pct):
        with self._lock:
            self.flap_enabled = bool(enabled)
            self.flap_period_s = max(0.0, period_s)
            self.flap_down = clamp01(down_pct / 100.0)

    def set_advanced(self, syn_drop_pct, max_size):
        with self._lock:
            self.syn_drop = clamp01(syn_drop_pct / 100.0)
            self.max_size = max(0, int(max_size))

    def set_spike(self, prob_pct, spike_ms):
        with self._lock:
            self.spike_prob = clamp01(prob_pct / 100.0)
            self.spike_s = max(0.0, spike_ms) / 1000.0

    def set_nat(self, timeout_s):
        with self._lock:
            self.nat_timeout_s = max(0.0, timeout_s)

    def set_rst(self, prob_pct, cooldown_s):
        with self._lock:
            self.rst_prob = clamp01(prob_pct / 100.0)
            self.rst_cooldown_s = max(0.1, cooldown_s)

    def reset_now(self, duration_s=2.0, now=None):
        """Manual reset: cut all active connections for the next ``duration_s``."""
        with self._lock:
            base = now if now is not None else time.monotonic()
            self._reset_now_deadline = base + duration_s

    def set_schedule(self, steps_kbps):
        """``steps_kbps``: ``[(dur_s, down_kbps, up_kbps), ...]``. Empty = constant limit."""
        with self._lock:
            self.schedule = [(max(0.01, d), self._rate_bps(dn), self._rate_bps(up))
                             for (d, dn, up) in (steps_kbps or [])]
            self._sched_total = sum(s[0] for s in self.schedule)
            # restart the cycle from the beginning so applying a schedule
            # mid-session starts at step 1 instead of somewhere in the middle
            self._sched_start = time.monotonic()

    def reset_buckets(self, now):
        with self._lock:
            self._bucket = {True: now, False: now}
            self._sched_start = now
            self._session_start = now
            self._flow_last.clear()
            self._reset_until.clear()
            self._prune_next = 0.0

    # -- helpers ------------------------------------------------------------ #
    @staticmethod
    def _flowkey(local_port, remote_ip, remote_port):
        if local_port is None or remote_ip is None or remote_port is None:
            return None
        return (local_port, remote_ip, remote_port)

    def _current_rates(self, now):
        if not self.schedule or self._sched_total <= 0:
            return self.rate_down, self.rate_up
        pos = (now - self._sched_start) % self._sched_total
        acc = 0.0
        for dur, dn, up in self.schedule:
            acc += dur
            if pos < acc:
                return dn, up
        return self.schedule[-1][1], self.schedule[-1][2]

    def drain_retired(self):
        """Retired flow generations, for somebody who is NOT the capture thread.

        Called by the engine's watchdog. Freeing a 200 000-entry dict costs ~7 ms
        (up to 22 ms measured in the engine) - a stall the packet path must not pay
        in a tool whose job is to inject a precise amount of latency.
        """
        with self._lock:
            return self._flow_last.drain_retired() + self._reset_until.drain_retired()

    def _prune(self, now):
        """Keep the flow tables bounded. O(1) - see :class:`_FlowTable`.

        This used to rebuild both dicts (``{k: v for ...}``) from inside
        ``decide()``, under the lock: 124 ms at 640 000 entries, 1001 ms at 3.2
        million. Now it retires a generation, which is a dict deallocation.

        Still throttled, because at high packet rates even an O(1) call has a cost
        worth not paying a hundred thousand times a second.
        """
        if now < self._prune_next:
            return
        self._prune_next = now + 1.0
        self._flow_last.maybe_rotate(now)
        self._reset_until.maybe_rotate(now)

    def in_scope(self, local_port, remote_ip=None, remote_port=None):
        """Whether a flow is in targeting scope RIGHT NOW (read-only, no effects).

        Mirrors the targeting gates of ``decide`` (steps 1-2) without touching any
        flow table or bucket. The connections view uses it to colour a row by the
        target as it stands now, not by the last packet the flow happened to send:
        an idle flow otherwise kept a stale flag, so a firefox row stayed marked
        "in scope" after the target had been narrowed to chrome.
        """
        with self._lock:
            if self.target_active and local_port not in self.target_ports:
                return False
            if self.dst_active:
                if self.dst_ip_matcher and not self.dst_ip_matcher.matches(remote_ip):
                    return False
                if self.dst_port_matcher and not self.dst_port_matcher.matches(remote_port):
                    return False
            return True

    def targeting_active(self):
        """True when any targeting (process or destination) is narrowing traffic."""
        with self._lock:
            return bool(self.target_active or self.dst_active)

    def decide(self, size, is_outbound, local_port, now, rng,
               remote_ip=None, remote_port=None, is_syn=False, is_tcp=False):
        with self._lock:
            # 1) process targeting
            if self.target_active and local_port not in self.target_ports:
                return Decision(False, False, [now], scoped=False)
            # 2) destination targeting (remote IP/port) - filter expressions
            if self.dst_active:
                if self.dst_ip_matcher and not self.dst_ip_matcher.matches(remote_ip):
                    return Decision(False, False, [now], scoped=False)
                if self.dst_port_matcher and not self.dst_port_matcher.matches(remote_port):
                    return Decision(False, False, [now], scoped=False)

            # 2b) LAN mode: cut the internet (public addresses), keep the local network
            if self.lan_only and remote_ip and not is_local_ip(remote_ip):
                return Decision(True, False, [], "lan")

            # 2c) blocking (firewall): drop matching destinations. OR of the two
            # expressions, each taking part only when non-empty (an empty matcher
            # is falsy and would otherwise match everything) - so a single field
            # blocks on that field alone. See set_block().
            if self.block_active and (
                    (self.block_ip_matcher and self.block_ip_matcher.matches(remote_ip))
                    or (self.block_port_matcher
                        and self.block_port_matcher.matches(remote_port))):
                return Decision(True, False, [], "block")

            key = self._flowkey(local_port, remote_ip, remote_port)

            # 3) NAT mapping expiry (keep-alive test)
            #
            # The flow table is maintained ONLY when NAT is switched on. It used to
            # be written for every packet whether or not anything read it - and the
            # NAT check is its only reader, and NAT is off by default. So the common
            # configuration paid for a table it never looked at: 50 000 packets left
            # 50 000 entries behind, for nothing.
            if self.nat_timeout_s > 0 and key is not None:
                last = self._flow_last.touch(key, now)
                expired = last is not None and (now - last) > self.nat_timeout_s
                if expired and not is_outbound:
                    return Decision(True, False, [], "nat")

            # Rotate the bounded tables. O(1) (see _FlowTable) and throttled, so it
            # is safe to call from the hot path - which is the point: the tables must
            # stay bounded even in a session that runs for days.
            if key is not None and (self._flow_last or self._reset_until):
                self._prune(now)

            # 4) RST injection (connection reset)
            if is_tcp and key is not None:
                until = self._reset_until.get(key, 0.0)
                if now < until:
                    return Decision(True, False, [], "rst")
                trigger = (now < self._reset_now_deadline) or \
                          (self.rst_prob > 0 and rng.random() < self.rst_prob)
                if trigger:
                    self._reset_until.set(key, now + self.rst_cooldown_s)
                    return Decision(True, False, [], "rst", True)

            # 5) link outage (flapping)
            if self.flap_enabled and self.flap_period_s > 0:
                # session-relative phase: with the same seed and settings the
                # outage pattern repeats identically between sessions (an
                # absolute-clock phase made repro runs diverge on flapping)
                phase = (now - self._session_start) % self.flap_period_s
                if phase < self.flap_period_s * self.flap_down:
                    # its own reason: a link outage is not packet loss, and
                    # mixing the two made "Dropped" (and the effective-loss
                    # figure in the session panel) report a link outage as loss
                    return Decision(True, False, [], "flap")

            # 6) MTU black hole
            if self.max_size > 0 and size > self.max_size:
                return Decision(True, False, [], "mtu")

            # 7) TCP SYN dropping
            if is_syn and self.syn_drop > 0 and rng.random() < self.syn_drop:
                return Decision(True, False, [], "syn")

            # 8) loss
            if self.loss > 0 and rng.random() < self.loss:
                return Decision(True, False, [])

            # 9) corruption
            corrupt = self.corrupt > 0 and rng.random() < self.corrupt

            # 10) latency + jitter + latency spike
            delay = self.latency_s
            if self.jitter_s > 0:
                delay += rng.uniform(-self.jitter_s, self.jitter_s)
                if delay < 0:
                    delay = 0.0
            if self.spike_prob > 0 and rng.random() < self.spike_prob:
                delay += self.spike_s
            release = now + delay

            # 11) throughput limit (time-variable, per-direction token bucket with
            #     a BOUNDED buffer). ``b`` is the link's virtual finish time: the
            #     moment it becomes free after everything queued so far. The delay
            #     this packet sits through before its own transmit is ``b - now``.
            #
            #     A real shaped link buffers only so much before it drops. With
            #     ``buffer_s == 0`` the buffer is unbounded (legacy behaviour: the
            #     bucket could run tens of seconds ahead, which both injected huge
            #     latency AND meant a rate INCREASE never took effect - the stale
            #     bucket kept gating every later high-rate step). With
            #     ``buffer_s > 0`` a packet that would push the queueing delay past
            #     the buffer is TAIL-DROPPED (reason ``rate``): the delivered rate
            #     stays exactly at ``rate``, the added latency is bounded by
            #     ``buffer_s``, and after a rate rise the buffer drains within
            #     ``buffer_s`` instead of never. An empty buffer (``queued == 0``)
            #     always accepts the packet, so a tiny buffer throttles hard but
            #     never blacks the link out completely.
            down_bps, up_bps = self._current_rates(now)
            rate = up_bps if is_outbound else down_bps
            if rate > 0:
                b = self._bucket[is_outbound]
                if b < now:
                    b = now
                queued = b - now
                if self.buffer_s > 0 and queued > 0 and \
                        queued + size / rate > self.buffer_s:
                    return Decision(True, False, [], "rate")
                b += size / rate
                self._bucket[is_outbound] = b
                if b > release:
                    release = b

            releases = [release]
            # 12) duplication
            if self.dup > 0 and rng.random() < self.dup:
                dup_release = release + rng.uniform(0.0, 0.02)
                # a duplicate is a second copy on the wire: charge the bucket for it,
                # or the shaped link quietly carries (1 + dup%) of its limit. If the
                # bounded buffer has no room for the copy, the copy is what gets
                # dropped - the original already went through.
                if rate > 0:
                    b = self._bucket[is_outbound]
                    if self.buffer_s > 0 and (b - now) > 0 and \
                            (b - now) + size / rate > self.buffer_s:
                        pass                # no room for the duplicate; original stands
                    else:
                        self._bucket[is_outbound] = b + size / rate
                        releases.append(dup_release)
                else:
                    releases.append(dup_release)

            return Decision(False, corrupt, releases)

    @staticmethod
    def build_rst_fields(pkt):
        """Return the RST fields to inject (aimed at the local end)."""
        is_out = bool(getattr(pkt, "is_outbound", True))
        tcp = getattr(pkt, "tcp", None)
        if tcp is None:
            return None
        if is_out:
            # observed local->remote; the RST pretends to come from remote->local
            seq = getattr(tcp, "ack_num", 0)
            src_ip, dst_ip = getattr(pkt, "dst_addr", None), getattr(pkt, "src_addr", None)
            src_port, dst_port = pkt.dst_port, pkt.src_port
        else:
            seq = getattr(tcp, "seq_num", 0)
            src_ip, dst_ip = getattr(pkt, "src_addr", None), getattr(pkt, "dst_addr", None)
            src_port, dst_port = pkt.src_port, pkt.dst_port
        return dict(direction_inbound=True, src_ip=src_ip, dst_ip=dst_ip,
                    src_port=src_port, dst_port=dst_port, seq_num=seq)

    @staticmethod
    def corrupt_packet(packet, rng=random):
        """Flip a random bit in the payload. Return True on success."""
        try:
            payload = packet.payload
            if not payload:
                return False
            data = bytearray(payload)
            idx = rng.randrange(len(data))
            data[idx] ^= (1 << rng.randrange(8))
            packet.payload = bytes(data)
            return True
        except Exception as exc:
            # NOT silent (convention 30). This returns False on a REAL failure - a
            # payload setter that started raising, an unexpected packet type - exactly
            # as it does for the legitimate empty-payload case above. So a broken
            # corruptor would read as "0 corrupted", indistinguishable from "no
            # payloads to corrupt", and the tester would blame their traffic instead
            # of the tool - the precise class of silent lie this project removes.
            # once() keeps it free in the packet hot path (a traceback at most once).
            # Imported lazily so core.py still imports only utils/matchers at load
            # (layering contract: tests/test_layering.py::test_core_stays_pure).
            from . import crashlog
            crashlog.once("core.corrupt", exc)
            return False
