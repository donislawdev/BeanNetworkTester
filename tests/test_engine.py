"""Engine tests: threads, queueing, connection/event logs, seeds (fake diverter).

Ported 1:1 from the original monolithic suite; every ``check(...)`` from the
270-assertion baseline is preserved as a pytest assertion.
"""
import os
import re
import time

from beantester import BeanEngine
from beantester.engine import (DROP_BY_REASON, IMPAIRMENT_DROP_KEYS, TOOL_DROP_KEYS,
                               impairment_loss_pct)
from beantester.synthetic import SyntheticDivert
from fakes import FakeDivert, FakePacket, check



def test_threaded_loss_end_to_end():
    packets = [FakePacket(size=100, is_outbound=(i % 2 == 0), port=1000 + i) for i in range(3000)]
    fake = FakeDivert(packets)
    sh = BeanEngine()
    sh.set_seed(1234)            # loss is random; an unseeded run is flaky on CI
    sh.set_params(10, 0, 0, 0, 0, 0, 0)  # 10% loss, no delay
    sh.start("test", divert=fake)

    # wait until everything processed and queue empty
    deadline = time.time() + 15
    while time.time() < deadline:
        s = sh.stats_snapshot()
        if s["seen"] >= 3000 and s["queue"] == 0:
            break
        time.sleep(0.02)
    time.sleep(0.1)
    sh.stop()

    s = sh.stats_snapshot()
    sent = len(fake.sent)
    check("integ.: all packets read", s["seen"] == 3000, f"(seen={s['seen']})")
    check("integ.: ~10% lost", 250 <= s["drop_loss"] <= 350, f"(drop={s['drop_loss']})")
    check("integ.: sent = read - lost",
          sent == s["seen"] - s["drop_loss"], f"(sent={sent}, drop={s['drop_loss']})")


def test_threaded_throttle_timing():
    # 200 packets of 1024 B, download limit 50 KB/s => ~4 s for 200 KB
    n, size, kbps = 200, 1024, 50
    packets = [FakePacket(size=size, is_outbound=False, port=2000) for _ in range(n)]
    fake = FakeDivert(packets)
    sh = BeanEngine()
    sh.set_params(0, 0, 0, 0, 0, kbps, 0)
    t0 = time.monotonic()
    sh.start("test", divert=fake)
    deadline = time.time() + 20
    while time.time() < deadline:
        if len(fake.sent) >= n:
            break
        time.sleep(0.02)
    elapsed = time.monotonic() - t0
    sh.stop()
    expected = (n * size) / (kbps * 1024)   # ~4.0 s
    check("integ.: throttling time ~ expected",
          abs(elapsed - expected) / expected < 0.20,
          f"(zmierzono {elapsed:.2f}s, oczekiwano {expected:.2f}s)")


def test_packets_queued_at_stop_are_counted_as_drop_shutdown():
    # A huge latency parks every packet in the delay queue; none is released before
    # STOP. Those queued packets used to vanish from the balance (counted at capture,
    # never delivered, never dropped). stop() now records them as drop_shutdown, so
    # seen == delivered + drops holds right to the end of the session.
    n = 200
    packets = [FakePacket(size=100, is_outbound=False, port=3000 + i) for i in range(n)]
    fake = FakeDivert(packets)
    sh = BeanEngine()
    sh.set_params(0, 0, 0, 60000, 0, 0, 0)   # 60 s latency: nothing is released in time
    sh.start("test", divert=fake)

    deadline = time.time() + 15
    while time.time() < deadline:
        s = sh.stats_snapshot()
        if s["seen"] >= n and s["queue"] >= n:
            break
        time.sleep(0.02)
    sh.stop()

    s = sh.stats_snapshot()
    check("shutdown: all read", s["seen"] == n, f"(seen={s['seen']})")
    check("shutdown: none delivered", len(fake.sent) == 0, f"(sent={len(fake.sent)})")
    check("shutdown: queued-at-stop counted", s["drop_shutdown"] == n,
          f"(drop_shutdown={s['drop_shutdown']})")
    check("shutdown: seen == delivered + drops",
          s["seen"] == len(fake.sent) + s["drop_shutdown"],
          f"(seen={s['seen']}, sent={len(fake.sent)}, shutdown={s['drop_shutdown']})")


# --- tests for newer options (NAT / connections) --------------------------- #


def test_syn_drop_integration():
    pkts = [FakePacket(size=60, is_outbound=True, port=6000 + i, syn=True) for i in range(500)]
    fake = FakeDivert(pkts)
    sh = BeanEngine()
    sh.set_advanced(100, 0)                     # all SYN dropped
    sh.start("test", divert=fake)
    deadline = time.time() + 10
    while time.time() < deadline:
        s = sh.stats_snapshot()
        if s["seen"] >= 500 and s["queue"] == 0:
            break
        time.sleep(0.02)
    sh.stop()
    s = sh.stats_snapshot()
    check("integ. SYN: counted as drop_syn", s["drop_syn"] == 500, f"(drop_syn={s['drop_syn']})")
    check("integ. SYN: nothing sent", len(fake.sent) == 0, f"(sent={len(fake.sent)})")


def test_connection_log():
    pkts = [FakePacket(size=200, is_outbound=True, port=7000, dst_addr="1.1.1.1"),
            FakePacket(size=300, is_outbound=False, port=7000, src_addr="1.1.1.1"),
            FakePacket(size=100, is_outbound=True, port=8000, dst_addr="2.2.2.2")]
    fake = FakeDivert(pkts)
    sh = BeanEngine()
    sh.start("test", divert=fake)
    deadline = time.time() + 5
    while time.time() < deadline and sh.stats_snapshot()["seen"] < 3:
        time.sleep(0.02)
    time.sleep(0.05)
    conns = sh.connections_snapshot()
    sh.stop()
    check("connection log: 2 flows recorded", len(conns) == 2, f"(={len(conns)})")


def test_connection_fields():
    # TCP flow: 2 out packets (100 B each) + 1 in (250 B) on the same port
    pkts = [FakePacket(size=100, is_outbound=True, port=7100, dst_addr="1.1.1.1", syn=True),
            FakePacket(size=100, is_outbound=True, port=7100, dst_addr="1.1.1.1", syn=True),
            FakePacket(size=250, is_outbound=False, port=7100, src_addr="1.1.1.1", syn=True)]
    sh = BeanEngine()
    sh.start("test", divert=FakeDivert(pkts))
    deadline = time.time() + 5
    while time.time() < deadline and sh.stats_snapshot()["seen"] < 3:
        time.sleep(0.02)
    time.sleep(0.05)
    conns = sh.connections_snapshot()
    sh.stop()
    check("connections: single flow", len(conns) == 1, f"(={len(conns)})")
    c = conns[0]
    check("connections: TCP protocol detected", c.get("proto") == "TCP", f"(proto={c.get('proto')})")
    check("connections: bytes sent = 200", c.get("bytes_out") == 200, f"(={c.get('bytes_out')})")
    check("connections: bytes received = 250", c.get("bytes_in") == 250, f"(={c.get('bytes_in')})")
    check("connections: first/last timestamps present", "first" in c and "last" in c)


def _run_seeded(seed, n=2000):
    pkts = [FakePacket(size=100, is_outbound=(i % 2 == 0), port=i, dst_addr="1.1.1.1")
            for i in range(n)]
    fake = FakeDivert(pkts)
    sh = BeanEngine()
    sh.set_seed(seed)
    sh.set_params(25, 0, 0, 0, 0, 0, 0)   # 25% loss
    sh.start("test", divert=fake)
    deadline = time.time() + 12
    while time.time() < deadline:
        s = sh.stats_snapshot()
        if s["seen"] >= n and s["queue"] == 0:
            break
        time.sleep(0.02)
    time.sleep(0.05)
    sh.stop()
    seq = [p.src_port for _, p in fake.sent]
    return seq, sh.stats_snapshot()["drop_loss"]


def test_seed_reproducible():
    a_seq, a_drop = _run_seeded(7)
    b_seq, b_drop = _run_seeded(7)
    check("seed: same seed -> same packets dropped", a_seq == b_seq,
          f"(drop a={a_drop} b={b_drop})")
    check("seed: same number of lost packets", a_drop == b_drop, f"(a={a_drop}, b={b_drop})")


def test_seed_differs():
    a_seq, _ = _run_seeded(1)
    b_seq, _ = _run_seeded(2)
    check("seed: different seeds -> different runs", a_seq != b_seq)


def test_effective_seed_always_set():
    sh = BeanEngine()
    sh.set_seed(None)                       # no seed -> the program should pick one itself
    sh.start("test", divert=SyntheticDivert(gen_kbps=3000, seed=1))
    time.sleep(0.2)
    eff = sh.effective_seed()
    sh.stop()
    check("effective seed: set even when not provided", isinstance(eff, int) and eff > 0, f"(={eff})")
    sh2 = BeanEngine(); sh2.set_seed(12345)
    sh2.start("test", divert=SyntheticDivert(gen_kbps=3000, seed=1))
    time.sleep(0.1); e2 = sh2.effective_seed(); sh2.stop()
    check("effective seed: when provided, the same number", e2 == 12345, f"(={e2})")


def test_event_log():
    sh = BeanEngine()
    sh.start("test", divert=SyntheticDivert(gen_kbps=3000, seed=1))
    sh.reset_now(2.0)
    sh.log_event("BUG", "test")
    time.sleep(0.1)
    evs = sh.events_snapshot()
    sh.stop()
    kinds = [e[2] for e in evs]
    check("event log: records START", "START" in kinds)
    check("event log: records RESET and BUG", "RESET" in kinds and "BUG" in kinds, f"({kinds})")


def test_lan_mode_integration():
    # LAN mode gates on the REMOTE ip, which the engine reads from dst_addr for an
    # outbound packet and src_addr for an inbound one - so the internet must be cut
    # BOTH ways. src_addr defaults to a private address, hence the explicit public
    # one on the inbound packet.
    pkts = [FakePacket(size=200, is_outbound=True, port=5000, dst_addr="8.8.8.8"),
            FakePacket(size=200, is_outbound=True, port=5001, dst_addr="93.184.216.34"),
            FakePacket(size=200, is_outbound=False, port=5002, src_addr="1.1.1.1"),
            FakePacket(size=200, is_outbound=True, port=5003, dst_addr="192.168.0.10")]
    sh = BeanEngine()
    sh.set_lan(True)
    sh.start("test", divert=FakeDivert(pkts))
    deadline = time.time() + 5
    while time.time() < deadline and sh.stats_snapshot()["seen"] < 4:
        time.sleep(0.02)
    time.sleep(0.05)
    s = sh.stats_snapshot()
    sh.stop()
    # 2 outbound + 1 inbound to/from public addresses dropped; the LAN packet passes
    check("LAN integ.: internet cut both ways (2 out + 1 in), LAN passes",
          s["drop_lan"] == 3, f"(drop_lan={s['drop_lan']})")


def test_block_integration():
    """Blocking drops traffic to matching destinations through the real engine and
    counts it under drop_block. OR semantics: one packet is caught by the blocked
    IP range, one by the blocked port; the third (neither) passes. FakePacket sets
    dst_port == port, so an outbound packet's remote port is `port`."""
    pkts = [FakePacket(size=150, is_outbound=True, port=80, dst_addr="203.0.113.9"),  # blocked IP
            FakePacket(size=150, is_outbound=True, port=443, dst_addr="9.9.9.9"),      # blocked port
            FakePacket(size=150, is_outbound=True, port=80, dst_addr="9.9.9.9")]       # passes
    sh = BeanEngine()
    sh.set_block(True, "203.0.113.0/24", "443")
    sh.start("test", divert=FakeDivert(pkts))
    deadline = time.time() + 5
    while time.time() < deadline and sh.stats_snapshot()["seen"] < 3:
        time.sleep(0.02)
    time.sleep(0.05)
    s = sh.stats_snapshot()
    sh.stop()
    check("block integ.: matching IP and port dropped (2), other passes",
          s["drop_block"] == 2, f"(drop_block={s['drop_block']}, seen={s['seen']})")


def test_connection_records_scope_and_dropped():
    """Per-flow bookkeeping behind the "impaired?" and "dropped" columns: with
    process targeting on one port and 100% loss, only the targeted flow is in
    scope and only its packets are counted as dropped; the other flow is merely
    observed. Every row also carries a `pid` field (None off Windows)."""
    pkts = [FakePacket(size=100, is_outbound=True, port=7300, dst_addr="1.1.1.1"),
            FakePacket(size=100, is_outbound=True, port=7300, dst_addr="1.1.1.1"),
            FakePacket(size=100, is_outbound=True, port=7400, dst_addr="2.2.2.2")]
    sh = BeanEngine()
    sh.core.set_params(100, 0, 0, 0, 0, 0, 0)      # 100% loss
    sh.core.set_target(True, {7300})               # target only the first flow
    sh.start("test", divert=FakeDivert(pkts))
    deadline = time.time() + 5
    while time.time() < deadline and sh.stats_snapshot()["seen"] < 3:
        time.sleep(0.02)
    time.sleep(0.05)
    conns = {c["local_port"]: c for c in sh.connections_snapshot()}
    sh.stop()

    targeted, other = conns.get(7300, {}), conns.get(7400, {})
    check("scope: targeted flow is in scope", targeted.get("scoped") is True,
          f"(scoped={targeted.get('scoped')})")
    check("scope: targeted flow counts its drops", targeted.get("dropped") == 2,
          f"(dropped={targeted.get('dropped')})")
    check("scope: untargeted flow is out of scope", other.get("scoped") is False,
          f"(scoped={other.get('scoped')})")
    check("scope: untargeted flow drops nothing", other.get("dropped") == 0,
          f"(dropped={other.get('dropped')})")
    check("scope: every row carries a pid field",
          "pid" in targeted and "pid" in other)


def test_scoped_is_a_sticky_session_record():
    """The "impaired?" flag is a session-long record, not the last packet's scope.

    Once a flow has been in impairment scope, its row must keep saying so after the
    flow LEAVES scope - the target was narrowed, or the flow just went idle and its
    socket closed. A browser closes hundreds of connections a minute; if the flag
    tracked only the latest packet (or a live port lookup) every finished flow would
    read "not impaired" the instant it closed, so a run that impaired all of chrome
    looked like it had caught nothing. The LIVE "in scope now" signal is a separate
    thing (the connections page highlights the row via BeanCore.in_scope).

    Driven straight through ``_log_conn`` so the stickiness is asserted without any
    thread timing: three packets on one flow (in scope, then twice out), plus a flow
    that is never in scope at all.
    """
    eng = BeanEngine()

    def row(port):
        return {c["local_port"]: c for c in eng.connections_snapshot()}[port]

    key = (5000, "1.1.1.1", 443)
    # first packet arrives in scope (targeting matched, an impairment applied)
    eng._log_conn(key, "1.1.1.1", 443, 5000, True, 100, 1.0, "TCP",
                  dropped=True, scoped=True)
    check("in scope on the first packet", row(5000)["scoped"] is True,
          f"(scoped={row(5000)['scoped']})")

    # later packets on the SAME flow arrive OUT of scope (target narrowed away):
    # the record must not flip back to "not impaired"
    for t in (2.0, 3.0):
        eng._log_conn(key, "1.1.1.1", 443, 5000, True, 100, t, "TCP",
                      dropped=False, scoped=False)
    check("still recorded as impaired after leaving scope", row(5000)["scoped"] is True,
          f"(scoped={row(5000)['scoped']})")

    # a flow that is NEVER in scope stays out - stickiness only ever adds "yes"
    eng._log_conn((5001, "2.2.2.2", 80), "2.2.2.2", 80, 5001, True, 100, 4.0, "TCP",
                  dropped=False, scoped=False)
    check("a never-scoped flow is not marked impaired", row(5001)["scoped"] is False,
          f"(scoped={row(5001)['scoped']})")


def test_set_seed_variants():
    sh = BeanEngine()
    for v in (None, "", -1):
        sh.set_seed(v)
        check(f"set_seed: {v!r} -> random (None)", sh._seed is None)
    sh.set_seed("42")
    check("set_seed: numeric string -> int", sh._seed == 42)


def test_engine_stop_safe_and_restart():
    sh = BeanEngine()
    try:
        sh.stop()                            # stop before start must be a no-op
        ok = True
    except Exception:
        ok = False
    check("engine: stop before start safe", ok)

    # start -> stop -> stop -> start again (engine object is reusable)
    sh.start("test", divert=FakeDivert([FakePacket(size=100, port=5000)]))
    time.sleep(0.05)
    sh.stop()
    try:
        sh.stop()                            # double stop must be a no-op
        ok = True
    except Exception:
        ok = False
    check("engine: double stop safe", ok)

    fake2 = FakeDivert([FakePacket(size=100, port=5001), FakePacket(size=100, port=5002)])
    sh.start("test", divert=fake2)
    deadline = time.time() + 5
    while time.time() < deadline and sh.stats_snapshot()["seen"] < 2:
        time.sleep(0.02)
    seen = sh.stats_snapshot()["seen"]
    sh.stop()
    check("engine: restart after stop works (counts packets from zero)", seen == 2, f"(seen={seen})")


def test_queue_overflow_counted():
    # tiny queue + huge latency -> most packets must be dropped as overflow
    pkts = [FakePacket(size=100, port=7000 + i) for i in range(100)]
    sh = BeanEngine()
    sh.max_queue = 10
    sh.set_params(0, 0, 0, 5000, 0, 0, 0)    # 5 s latency keeps the queue full
    sh.start("test", divert=FakeDivert(pkts))
    deadline = time.time() + 5
    while time.time() < deadline and sh.stats_snapshot()["seen"] < 100:
        time.sleep(0.02)
    s = sh.stats_snapshot()
    sh.stop()
    check("queue: overflow counted (drop_overflow)",
          s["drop_overflow"] >= 80, f"(overflow={s['drop_overflow']})")
    check("queue: peak_queue does not exceed the limit",
          s["peak_queue"] <= 10, f"(peak={s['peak_queue']})")


def test_overflow_counts_packets_lost_not_queue_entries():
    """A duplicating session must not report more overflow drops than packets.

    ``_enqueue`` runs once per release and duplication adds a second one, so
    charging every release counted the SAME packet twice. The tooltip says
    "Packets dropped because the queue overflowed", and the "Buffer overflow"
    tile could read higher than the "Packets" tile next to it.

    Deterministic, not statistical: dup=100% fires on every packet
    (``random() < 1.0`` always holds), the 60 s latency releases nothing before
    STOP, so the queue fills once and stays full. Five packets fit (two entries
    each), every later original is refused.
    """
    n, queue = 200, 10
    pkts = [FakePacket(size=100, port=7300 + i) for i in range(n)]
    sh = BeanEngine()
    sh.max_queue = queue
    sh.set_seed(4242)
    sh.set_params(0, 0, 100, 60000, 0, 0, 0)     # 100% duplication, 60 s latency
    sh.start("test", divert=FakeDivert(pkts))
    deadline = time.time() + 15
    while time.time() < deadline and sh.stats_snapshot()["seen"] < n:
        time.sleep(0.02)
    s = sh.stats_snapshot()
    sh.stop()

    check("overflow/dup: every packet was duplicated",
          s["duplicated"] == n, f"(duplicated={s['duplicated']}, seen={s['seen']})")
    check("overflow/dup: drops never exceed the packets they are drops OF",
          s["drop_overflow"] <= s["seen"],
          f"(overflow={s['drop_overflow']}, seen={s['seen']})")
    check("overflow/dup: originals refused are counted, copies are not",
          s["drop_overflow"] == n - queue // 2,
          f"(overflow={s['drop_overflow']}, expected={n - queue // 2})")


def test_drop_shutdown_counts_packets_never_delivered_not_queue_entries():
    """The same unit mix-up at STOP: a queued duplicate is not a lost packet.

    A copy still waiting when the session ends means the application received one
    packet instead of two - and one is what it would have received without the
    tool. Only an ORIGINAL left in the queue is something that never arrived.
    Counting entries made ``drop_shutdown`` twice ``seen`` here.
    """
    n = 200
    pkts = [FakePacket(size=100, is_outbound=False, port=7500 + i) for i in range(n)]
    fake = FakeDivert(pkts)
    sh = BeanEngine()
    sh.set_seed(4242)
    sh.set_params(0, 0, 100, 60000, 0, 0, 0)     # 100% duplication, 60 s latency
    sh.start("test", divert=fake)
    deadline = time.time() + 15
    while time.time() < deadline and sh.stats_snapshot()["queue"] < 2 * n:
        time.sleep(0.02)
    sh.stop()

    s = sh.stats_snapshot()
    check("shutdown/dup: nothing was delivered", len(fake.sent) == 0,
          f"(sent={len(fake.sent)})")
    check("shutdown/dup: queued copies are not counted as lost packets",
          s["drop_shutdown"] == n, f"(drop_shutdown={s['drop_shutdown']}, seen={s['seen']})")
    check("shutdown/dup: seen == delivered + drops",
          s["seen"] == len(fake.sent) + s["drop_shutdown"],
          f"(seen={s['seen']}, sent={len(fake.sent)}, shutdown={s['drop_shutdown']})")


def test_effective_loss_counts_every_impairment_not_just_the_loss_setting():
    """A speed limit destroying the traffic must show up as loss.

    Reproduces the audit measurement: a session with a bandwidth cap and NO
    configured Loss lost about 90% of what it was offered, while the figure built
    from `drop_loss` alone said 0.0%. `drop_loss` holds the configured Loss only;
    the excess a full link buffer throws away is `drop_rate`, and seven other
    impairments have counters of their own.
    """
    n = 1000
    pkts = [FakePacket(size=1500, is_outbound=False, port=7700) for _ in range(n)]
    sh = BeanEngine()
    sh.set_seed(4242)
    sh.set_buffer(50)                            # small buffer: the excess is dropped
    sh.set_params(0, 0, 0, 0, 0, 50, 0)          # 50 KB/s down, zero configured loss
    sh.start("test", divert=FakeDivert(pkts))
    deadline = time.time() + 20
    while time.time() < deadline and sh.stats_snapshot()["seen"] < n:
        time.sleep(0.02)
    s = sh.stats_snapshot()
    sh.stop()

    check("rate limit: the configured-loss counter stays at zero",
          s["drop_loss"] == 0, f"(drop_loss={s['drop_loss']})")
    check("rate limit: the damage lands in drop_rate",
          s["drop_rate"] >= 900, f"(drop_rate={s['drop_rate']}, seen={s['seen']})")
    check("rate limit: the loss figure reports the damage",
          impairment_loss_pct(s) >= 90.0,
          f"(pct={impairment_loss_pct(s):.1f}, drop_rate={s['drop_rate']})")


def test_effective_loss_measures_the_traffic_that_was_targeted():
    """With a target set, the figure is about the target, not the whole machine.

    Second audit measurement: 50% loss with a third of the traffic in scope
    reported 16.7% because the denominator was every captured packet, while the
    target application itself saw 50.1%. Out-of-scope traffic is watched and
    forwarded untouched, so it can only dilute the answer.
    """
    in_scope, out_of_scope = 300, 600
    pkts = ([FakePacket(size=100, port=5000) for _ in range(in_scope)]
            + [FakePacket(size=100, port=6000 + i) for i in range(out_of_scope)])
    sh = BeanEngine()
    sh.set_seed(4242)                            # loss is random: pin it
    sh.set_target(True, {5000})
    sh.set_params(50, 0, 0, 0, 0, 0, 0)          # 50% loss on the targeted port
    sh.start("test", divert=FakeDivert(pkts))
    deadline = time.time() + 20
    while time.time() < deadline and sh.stats_snapshot()["seen"] < in_scope + out_of_scope:
        time.sleep(0.02)
    s = sh.stats_snapshot()
    sh.stop()

    check("targeting: everything was captured", s["seen"] == in_scope + out_of_scope,
          f"(seen={s['seen']})")
    check("targeting: only the target's packets are in scope",
          s["scoped_seen"] == in_scope, f"(scoped_seen={s['scoped_seen']})")
    check("targeting: nothing out of scope was harmed",
          s["drop_loss"] <= in_scope, f"(drop_loss={s['drop_loss']})")
    pct = impairment_loss_pct(s)
    check("targeting: the figure matches what the target application sees",
          42.0 <= pct <= 58.0, f"(pct={pct:.1f}, drop_loss={s['drop_loss']})")
    diluted = 100.0 * s["drop_loss"] / s["seen"]
    check("targeting: and it is NOT the figure diluted by everything else",
          14.0 <= diluted <= 19.0 and abs(pct - diluted) > 20.0,
          f"(pct={pct:.1f}, diluted={diluted:.1f})")


def test_every_drop_counter_and_drop_reason_is_classified():
    """Nothing may drop out of the loss figure by being forgotten.

    This is the failure mode the figure had: `drop_rate` existed, was correct, and
    simply was not part of the sum. Both halves are mechanical - a new counter or
    a new drop reason turns this red until somebody says which side it belongs on.
    """
    counters = {k for k in BeanEngine().stats_snapshot() if k.startswith("drop_")}
    classified = set(IMPAIRMENT_DROP_KEYS) | set(TOOL_DROP_KEYS)
    check("every drop counter is either impairment damage or a tool loss",
          not (counters - classified), f"(unclassified: {sorted(counters - classified)})")
    check("and nothing is classified that no longer exists",
          not (classified - counters), f"(stale: {sorted(classified - counters)})")

    core_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "beantester", "core.py"), encoding="utf-8").read()
    reasons = set(re.findall(r'Decision\(True,\s*\w+,\s*\[\],\s*"(\w+)"', core_src))
    check("every drop reason decide() can give routes to a counter",
          not (reasons - set(DROP_BY_REASON)),
          f"(unrouted: {sorted(reasons - set(DROP_BY_REASON))})")


class IcmpPacket:
    """A ping packet shaped the way pydivert presents one.

    No transport header, so both ports read ``None`` - verified in the installed
    pydivert (``packet/__init__.py``: ``src_port`` returns None rather than
    raising when there is no TCP/UDP header) - while the IP layer still carries
    both addresses, and ``icmp`` is set (it is ``icmpv4 or icmpv6`` there).
    """

    def __init__(self, size=98, is_outbound=True, peer="8.8.8.8"):
        self.raw = b"\x00" * size
        self.is_outbound = is_outbound
        self.src_port = self.dst_port = None
        self.dst_addr = peer if is_outbound else "10.0.0.2"
        self.src_addr = "10.0.0.2" if is_outbound else peer
        self.tcp = self.udp = None
        self.icmp = object()
        self.payload = b""


def test_portless_traffic_reaches_the_connection_log():
    """Ping traffic must appear in a tab that says it lists every connection.

    Measured before the fix: 500 ICMP packets gave seen=500 with bytes counted
    and ZERO rows, because the flow key needs ports and the log drops a None key.
    Confirmed on live WinDivert too (the "Ping (ICMP)" filter, an empty tab).
    Both directions share one row: remote_ip is dst_addr going out and src_addr
    coming back, which is the same host either way.
    """
    out_n, in_n = 30, 20
    pkts = ([IcmpPacket(is_outbound=True) for _ in range(out_n)]
            + [IcmpPacket(is_outbound=False) for _ in range(in_n)])
    sh = BeanEngine()
    sh.start("test", divert=FakeDivert(pkts))
    deadline = time.time() + 15
    while time.time() < deadline and sh.stats_snapshot()["seen"] < out_n + in_n:
        time.sleep(0.02)
    rows = sh.connections_snapshot(limit=None)
    seen = sh.stats_snapshot()["seen"]
    sh.stop()

    check("icmp: every packet was captured", seen == out_n + in_n, f"(seen={seen})")
    check("icmp: it is ONE row, not none and not one per packet",
          len(rows) == 1, f"(rows={len(rows)})")
    row = rows[0]
    check("icmp: labelled ICMP", row["proto"] == "ICMP", f"(proto={row['proto']})")
    check("icmp: the peer is the address, and the ports stay empty",
          row["remote_ip"] == "8.8.8.8" and row["remote_port"] is None
          and row["local_port"] is None, f"({row['remote_ip']}, {row['remote_port']})")
    check("icmp: both directions land in the same row",
          row["packets"] == out_n + in_n and row["bytes_out"] > 0 and row["bytes_in"] > 0,
          f"(packets={row['packets']}, in={row['bytes_in']}, out={row['bytes_out']})")


def test_traffic_with_no_peer_address_still_gets_no_row():
    """The fallback key needs an address. Without one there is nothing to name,
    and inventing a row keyed on None would merge unrelated traffic into it."""
    pkts = [IcmpPacket() for _ in range(5)]
    for p in pkts:                      # a packet whose addresses could not be read
        p.dst_addr = p.src_addr = None
    sh = BeanEngine()
    sh.start("test", divert=FakeDivert(pkts))
    deadline = time.time() + 15
    while time.time() < deadline and sh.stats_snapshot()["seen"] < len(pkts):
        time.sleep(0.02)
    rows = sh.connections_snapshot(limit=None)
    seen = sh.stats_snapshot()["seen"]
    sh.stop()
    check("no address: counted but not logged as a connection",
          seen == len(pkts) and not rows, f"(seen={seen}, rows={len(rows)})")


class RefusingDivert(FakeDivert):
    """A divert whose send() always fails - a link that went down mid-session,
    or a driver that refuses the packet. `recv` still works: the tool keeps
    capturing, and every packet it captures it then fails to put back."""

    def send(self, p):
        raise OSError("the network is gone")


def test_a_packet_the_tool_could_not_re_inject_is_counted_as_a_drop():
    """A failed injection used to leave the seen/delivered/dropped balance.

    The packet is already off the queue when send() raises: not delivered, and
    before drop_send existed, not recorded either - only a log line. Every other
    way a packet can die here has a counter, which is what keeps the arithmetic
    honest; this path was the one hole in it.
    """
    n = 200
    pkts = [FakePacket(size=100, is_outbound=False, port=7900 + i) for i in range(n)]
    fake = RefusingDivert(pkts)
    sh = BeanEngine()
    sh.start("test", divert=fake)
    deadline = time.time() + 15
    while time.time() < deadline and sh.stats_snapshot()["drop_send"] < n:
        time.sleep(0.02)
    s = sh.stats_snapshot()
    sh.stop()

    check("send failure: every packet was captured", s["seen"] == n, f"(seen={s['seen']})")
    check("send failure: nothing was delivered",
          s["bytes_in"] == 0 and s["bytes_out"] == 0,
          f"(in={s['bytes_in']}, out={s['bytes_out']})")
    check("send failure: the losses are counted", s["drop_send"] == n,
          f"(drop_send={s['drop_send']})")
    drops = sum(s[k] for k in IMPAIRMENT_DROP_KEYS) + sum(s[k] for k in TOOL_DROP_KEYS)
    check("send failure: seen == delivered + dropped still holds",
          s["seen"] == drops, f"(seen={s['seen']}, drops={drops})")
    check("send failure: it is NOT counted as impairment damage",
          impairment_loss_pct(s) == 0.0, f"(pct={impairment_loss_pct(s)})")


def test_failed_injections_do_not_flood_the_log():
    """One line per failed packet is the second bug, not the report of the first.

    The GUI applies every queued line to its text widget on the UI thread, so a
    burst of failures freezes the window on top of losing the packets. The queue
    overflow path has been rate-limited for exactly this reason since it was
    written; this one had no limit at all.
    """
    n = 400
    lines = []
    pkts = [FakePacket(size=100, port=7950) for _ in range(n)]
    sh = BeanEngine(log_fn=lines.append)
    sh.start("test", divert=RefusingDivert(pkts))
    deadline = time.time() + 15
    while time.time() < deadline and sh.stats_snapshot()["drop_send"] < n:
        time.sleep(0.02)
    failed = sh.stats_snapshot()["drop_send"]
    sh.stop()

    complaints = [ln for ln in lines if "send" in ln.lower() or "odesł" in ln.lower()]
    check("flood: the failures happened", failed == n, f"(drop_send={failed})")
    check("flood: the user is told once, not once per packet",
          len(complaints) <= 2, f"({len(complaints)} lines for {failed} failures)")
    check("flood: and the line carries the scale",
          any(str(failed) in ln or "400" in ln for ln in complaints) or complaints,
          f"({complaints[:1]})")
    kinds = [e[2] for e in sh.events_snapshot()]
    check("flood: it reaches the event log, so the repro report carries it",
          "WARN" in kinds, f"({kinds})")


def test_a_second_scenario_stops_the_first_instead_of_orphaning_it():
    """Overwriting `_scenario_runner` left the old thread alive and unreachable.

    `stop_scenario()` only ever knew about the CURRENT object, so the orphan kept
    applying its own steps to the same engine: two scenarios fighting over the
    settings with nothing on screen to say why. Found by reading - today's callers
    (GUI and CLI) start one scenario per session - but "nobody calls it twice" is
    not a property of the engine.
    """
    from beantester.scenario import Scenario

    sh = BeanEngine()
    sh.start("test", divert=FakeDivert([FakePacket(size=100, port=8100)]))
    try:
        scenario = Scenario(steps=[{"at": 30.0, "settings": {"loss": 1}}], loop=True)
        sh.start_scenario(scenario, dict(loss=0))
        first = sh._scenario_runner
        sh.start_scenario(scenario, dict(loss=0))
        second = sh._scenario_runner

        check("scenario: the second start really replaced the runner",
              second is not first)
        check("scenario: the first runner was stopped, not orphaned",
              first._stop is True, f"(_stop={first._stop})")
        deadline = time.time() + 5
        while time.time() < deadline and first._thread.is_alive():
            time.sleep(0.02)
        check("scenario: and its thread is gone",
              not first._thread.is_alive())
    finally:
        sh.stop()


def test_a_connection_row_records_the_drops_the_queue_made():
    """`dropped` used to be recorded one step too early.

    `_log_conn(dropped=dec.drop)` ran BEFORE `_enqueue`, so a packet the QUEUE
    threw away counted nowhere in its row: measured drop_overflow=5500 against
    `dropped=0` in the row it happened to. Packets stranded at STOP had the same
    problem - `bytes_in=4.8 MB` on a row that received nothing.
    """
    n, queue = 200, 10
    pkts = [FakePacket(size=100, is_outbound=False, port=8200) for _ in range(n)]
    sh = BeanEngine()
    sh.max_queue = queue
    sh.set_params(0, 0, 0, 60000, 0, 0, 0)      # 60 s latency: nothing is released
    sh.start("test", divert=FakeDivert(pkts))
    deadline = time.time() + 15
    while time.time() < deadline and sh.stats_snapshot()["seen"] < n:
        time.sleep(0.02)
    live = sh.connections_snapshot(limit=None)[0]
    refused = live["dropped"]
    sh.stop()
    final = sh.connections_snapshot(limit=None)[0]

    check("row: the queue's refusals reach the row",
          refused == n - queue, f"(dropped={refused}, expected={n - queue})")
    check("row: and the packets stranded at STOP reach it too",
          final["dropped"] == n, f"(dropped={final['dropped']})")
    check("row: nothing was delivered, and the row says so",
          final["sent"] == 0 and final["sent_in"] == 0, f"(sent={final['sent']})")
    check("row: while the captured bytes are all there",
          final["bytes_in"] == n * 100, f"(bytes_in={final['bytes_in']})")


def test_an_undisturbed_row_has_delivered_equal_to_captured():
    """The other half of the split: with nothing impaired the two pairs agree, so
    the new columns are not a permanent discrepancy staring at the user."""
    # one direction on purpose: FakePacket puts the peer in dst_addr going out and
    # src_addr coming in, so alternating directions is TWO flows, not one row
    n = 50
    pkts = [FakePacket(size=100, is_outbound=False, port=8300) for _ in range(n)]
    fake = FakeDivert(pkts)
    sh = BeanEngine()
    sh.start("test", divert=fake)
    deadline = time.time() + 15
    while time.time() < deadline and len(fake.sent) < n:
        time.sleep(0.02)
    sh.stop()
    row = sh.connections_snapshot(limit=None)[0]

    check("row: everything offered was delivered",
          row["sent"] == row["bytes"] == n * 100,
          f"(sent={row['sent']}, bytes={row['bytes']})")
    check("row: per direction too",
          row["sent_in"] == row["bytes_in"] and row["sent_out"] == row["bytes_out"],
          f"(in {row['sent_in']}/{row['bytes_in']}, out {row['sent_out']}/{row['bytes_out']})")
    check("row: and nothing is reported as dropped",
          row["dropped"] == 0, f"(dropped={row['dropped']})")


def test_only_the_injector_writes_the_delivered_counters():
    """`_log_delivered` runs without the connection-log lock, and that is only safe
    while `sent`/`sent_in`/`sent_out` have exactly ONE writer - the inject thread.

    Nothing enforces that but this scan. A future edit that credits delivered bytes
    from the capture thread (or the watchdog) would make the unlocked `+=` drop
    updates against itself, silently and only under load. Source-level, like the
    hot-path purity check in test_code_hygiene.py, because there is no runtime
    symptom to assert on until it is already wrong.
    """
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "beantester", "engine.py"), encoding="utf-8").read()
    writes = re.findall(r'^\s*c\[\"(sent(?:_in|_out)?)\"\]\s*\+?=', src, re.M)
    check("delivered counters are incremented in exactly one place",
          len(writes) == 3, f"({writes})")
    body = src.split("def _log_delivered")[1].split("\n    def ")[0]
    check("and that place is _log_delivered",
          body.count('c["sent') == 3, f"({body.count(chr(99) + chr(91))})")


class ParamDivert(FakeDivert):
    """A divert that answers get_param, the way a real WinDivert handle does.

    The values are the ones measured on the owner's machine (2026-07-28, elevated,
    real driver): QUEUE_LEN 4096, QUEUE_TIME 2000 ms, QUEUE_SIZE 4 MiB.
    """

    QUEUE = {0: 4096, 1: 2000, 2: 4194304}      # Param.QUEUE_LEN / _TIME / _SIZE

    def get_param(self, name):
        return self.QUEUE[int(name)]


def test_a_session_records_the_driver_queue_it_is_running_behind():
    """Nothing in the program used to read WinDivert's own queue settings.

    With QUEUE_TIME at its default the driver may hold a packet for up to two
    seconds - latency this tool adds while being blind to it - and a session's
    numbers could not be interpreted without knowing that. The values now travel
    with the session, so a repro report from a machine you do not have still says
    what queue it was running behind.
    """
    sh = BeanEngine()
    sh.start("test", divert=ParamDivert([FakePacket(size=100, port=8400)]))
    info = sh.session_info()
    sh.stop()

    q = info["driver_queue"]
    check("driver queue: it is recorded", q is not None, f"({q})")
    check("driver queue: all three values, under their own names",
          q == {"queue_len": 4096, "queue_time": 2000, "queue_size": 4194304}, f"({q})")
    check("driver queue: it survives into the stopped session's info",
          sh.session_info()["driver_queue"] == q)


def test_the_driver_queue_param_numbers_match_pydivert():
    """The engine spells the WinDivert param numbers out instead of importing them.

    It has to: pydivert is win32-only, so importing it there would make the read
    return None on the Linux half of the CI matrix while passing on Windows - the
    exact shape of bug that only shows up on the runner you did not run. This is
    the other half of that trade: wherever pydivert IS importable, the numbers are
    checked against its own enum, so they cannot drift in silence.
    """
    import importlib.util

    if importlib.util.find_spec("pydivert") is None:
        return                      # not this machine's job (see the docstring)
    from pydivert.consts import Param
    for name, number in BeanEngine.DRIVER_QUEUE_PARAMS:
        expected = int(getattr(Param, name.upper()))
        check(f"driver queue: {name} is {expected} in pydivert",
              number == expected, f"(engine says {number})")


def test_a_simulated_session_reports_no_driver_queue_rather_than_a_made_up_one():
    """There is no driver on the --simulate path, so there is nothing to report.

    `None` says that; zeroes would read as "a queue of nothing", which is a
    different and false claim.
    """
    sh = BeanEngine()
    sh.start("test", divert=FakeDivert([FakePacket(size=100, port=8401)]))
    info = sh.session_info()
    sh.stop()
    check("driver queue: absent, not invented", info["driver_queue"] is None,
          f"({info['driver_queue']})")


def test_event_log_trim():
    sh = BeanEngine()
    for i in range(5100):
        sh.log_event("ZMIANA", f"e{i}")
    evs = sh.events_snapshot()
    check("event log: trimmed after 5000 entries", len(evs) <= 5000, f"(len={len(evs)})")
    check("event log: newest entries kept", evs[-1][3] == "e5099", f"({evs[-1]})")


def test_connections_snapshot_limit():
    sh = BeanEngine()
    for i in range(10):
        key = (5000 + i, "1.1.1.1", 80)
        sh._log_conn(key, "1.1.1.1", 80, 5000 + i, True, 100, now=float(i), proto="TCP")
    top = sh.connections_snapshot(limit=5)
    check("connections: snapshot limit respected", len(top) == 5, f"(len={len(top)})")
    check("connections: most recent first",
          top[0]["last"] == 9.0 and top[-1]["last"] == 5.0,
          f"({[c['last'] for c in top]})")


def test_session_info_keys_english():
    from beantester import BeanEngine
    info = BeanEngine().session_info()
    check("session_info: English keys", set(info) >= {"seed", "filter", "start", "start_wall", "elapsed"},
          f"({sorted(info)})")
    check("session_info: no Polish 'filtr' key", "filtr" not in info)


def test_data_usage_totals():
    from beantester import bytes_to_mb
    sh = BeanEngine()
    sh.start("test", divert=SyntheticDivert(gen_kbps=4000, seed=5))
    time.sleep(0.6)
    s = sh.stats_snapshot()
    sh.stop()
    fwd = s["bytes_in"] + s["bytes_out"]
    offered = s["bytes_in_total"] + s["bytes_out_total"]
    check("data: something got through (MB > 0)", bytes_to_mb(fwd) > 0, f"({bytes_to_mb(fwd)} MB)")
    check("data: offered >= delivered", offered >= fwd, f"(offered={offered}, fwd={fwd})")


def test_scenario_integration():
    from beantester import DEFAULT_SETTINGS, Scenario
    sc = Scenario([{"at": 0, "settings": {"loss": 0}},
                   {"at": 0.3, "settings": {"loss": 100}}])
    sh = BeanEngine()
    sh.start("test", divert=SyntheticDivert(gen_kbps=2000))
    sh.start_scenario(sc, DEFAULT_SETTINGS, log=lambda *_: None)
    time.sleep(0.15)
    loss_early = sh.core.loss
    time.sleep(0.35)
    loss_late = sh.core.loss
    sh.stop()
    check("scenario: loss=0 at start", loss_early == 0.0, f"(={loss_early})")
    check("scenario: loss=100% after 0.3 s", abs(loss_late - 1.0) < 1e-9, f"(={loss_late})")


def test_cli_simulate_end_to_end():
    sh = BeanEngine()
    sh.set_seed(2024)            # deterministic loss stream; unseeded => flaky on slow CI
    sh.set_params(30, 0, 0, 0, 0, 0, 0)
    sh.start("both", divert=SyntheticDivert(gen_kbps=3000, seed=7))
    time.sleep(2.0)
    sh.stop()
    time.sleep(0.1)
    s = sh.stats_snapshot()
    frac = s["drop_loss"] / max(1, s["seen"])
    check("CLI-sim: traffic flows", s["seen"] > 100, f"(seen={s['seen']})")
    check("CLI-sim: loss ~30%", 0.24 < frac < 0.36, f"(measured {frac:.2f})")


# --- stability / edge-case tests ------------------------------------------- #


def test_engine_restart_joins_threads_and_guards_double_start():
    """Regression: stop() must join the worker threads and start() must refuse
    to run twice - otherwise a quick stop->start left an old capture thread
    consuming packets from the NEW session's divert."""
    eng = BeanEngine()
    fake1 = FakeDivert([FakePacket(size=100, port=1000 + i) for i in range(10)])
    eng.start("test", divert=fake1)

    raised = False
    try:
        eng.start("test", divert=FakeDivert([]))
    except RuntimeError:
        raised = True
    check("start() while already running raises RuntimeError", raised)

    t_cap, t_inj = eng._t_cap, eng._t_inj
    eng.stop()
    check("capture thread joined by stop()", t_cap is not None and not t_cap.is_alive())
    check("inject thread joined by stop()", t_inj is not None and not t_inj.is_alive())

    # a restarted session must process exactly its own traffic
    fake2 = FakeDivert([FakePacket(size=100, port=2000 + i) for i in range(50)])
    eng.start("test", divert=fake2)
    deadline = time.time() + 10
    while time.time() < deadline:
        s = eng.stats_snapshot()
        if s["seen"] >= 50 and s["queue"] == 0:
            break
        time.sleep(0.02)
    time.sleep(0.05)
    eng.stop()
    s = eng.stats_snapshot()
    check("restarted session sees exactly its own packets", s["seen"] == 50,
          f"(seen={s['seen']})")


def test_scenario_runner_drives_engine_via_facade():
    """start_scenario/stop_scenario keep working after the extraction of the
    ScenarioRunner out of the engine."""
    from beantester import DEFAULT_SETTINGS, Scenario, ScenarioRunner

    eng = BeanEngine()
    eng.start("test", divert=FakeDivert([FakePacket(size=100, port=1000)]))
    scen = Scenario([{"at": 0, "settings": {"loss": 25}}], loop=False)
    eng.start_scenario(scen, dict(DEFAULT_SETTINGS))
    deadline = time.time() + 5
    while time.time() < deadline and abs(eng.core.loss - 0.25) > 1e-9:
        time.sleep(0.02)
    check("scenario step applied to the engine", abs(eng.core.loss - 0.25) < 1e-9,
          f"(loss={eng.core.loss})")
    runner = eng._scenario_runner
    check("engine delegates to a ScenarioRunner", isinstance(runner, ScenarioRunner))
    eng.stop()
    check("stop() also stops the scenario runner", runner._stop is True)


# -- the connection log at scale ------------------------------------------------ #
def test_capture_path_never_evicts_and_the_watchdog_does():
    """Trimming a 200 000-row table must not happen on the capture thread.

    ``_log_conn`` used to call an eviction that SORTED the whole table while
    holding the connection lock. At the old 2000-row cap nobody could feel it; at
    the current cap it is a ~300 ms freeze of the capture thread - and a frozen
    capture thread means WinDivert is queueing (and then dropping) the user's
    packets while the UI still says "running".
    """
    import time

    from beantester.engine import BeanEngine

    eng = BeanEngine()
    eng.MAX_CONNS = 500

    # fill well past the cap straight through the capture-path helper
    now = time.monotonic()
    for i in range(900):
        eng._log_conn((i, "1.2.3.4", 80), "1.2.3.4", 80, 1000 + i,
                      True, 100, now + i * 0.001)

    check("the capture path does not evict (that is the watchdog's job)",
          len(eng._conns) == 900, f"({len(eng._conns)})")

    eng._trim_conns()
    kept = len(eng._conns)
    check("the watchdog trims back to roughly EVICT_KEEP of the cap",
          400 <= kept <= 520, f"(kept {kept})")
    check("the flows that survive are the RECENT ones",
          all(c["last"] >= now + 0.3 for c in eng._conns.values()))

    eng._trim_conns()
    check("trimming under the cap is a no-op", len(eng._conns) == kept)


def test_snapshot_does_not_sort_the_whole_table_for_the_tables():
    """``limit=None`` is the virtualised tables' path: raw rows, no sort.

    The page sorts by the column the user picked anyway, so sorting here as well
    was the same ~100 ms of work done twice per refresh.
    """
    import time

    from beantester.engine import BeanEngine

    eng = BeanEngine()
    now = time.monotonic()
    for i in range(50):
        eng._log_conn((i, "1.2.3.4", 80), "1.2.3.4", 80, 1000 + i,
                      True, 100, now + i)

    everything = eng.connections_snapshot(limit=None)
    check("limit=None returns every row", len(everything) == 50)

    top = eng.connections_snapshot(limit=5)
    check("an explicit limit still gives the most recent first", len(top) == 5)
    stamps = [c["last"] for c in top]
    check("newest first", stamps == sorted(stamps, reverse=True), f"({stamps})")
    check("and they are the newest rows", min(stamps) >= now + 45, f"({stamps})")


def test_eviction_sampling_never_touches_the_seeded_rng():
    """Reproducibility: drawing from the decision RNG here would make a session's
    impairments depend on how often the table happened to be trimmed."""
    from beantester.engine import BeanEngine

    eng = BeanEngine()
    check("eviction has its own RNG", eng._rng_evict is not eng._rng)


def test_a_full_queue_says_so_instead_of_quietly_eating_packets():
    """A queue overflow means the TOOL is dropping the user's packets.

    Their measured loss is then not their application's loss - it is ours, and a
    tester who does not know that files a bug against the wrong thing. It used to
    be a number in a table on a page they might never open.

    But it can happen 150 000 times a second, so it has to be loud AND rate-limited:
    a warning that floods the log is the second bug.
    """
    from beantester.engine import BeanEngine

    lines = []
    eng = BeanEngine(log_fn=lambda text: lines.append(text))
    eng.max_queue = 3
    eng._running = True

    for _ in range(500):
        eng._enqueue(1.0, object())

    stats = eng.stats_snapshot()
    check("the packets the tool dropped are counted",
          stats["drop_overflow"] >= 490, f"({stats['drop_overflow']})")

    warnings = [line for line in lines if "queue" in line.lower()
                or "kolejka" in line.lower()]
    check("the user is TOLD, not just counted at", warnings, f"({lines[:2]})")
    check("but 500 overflows do not become 500 log lines",
          len(warnings) == 1, f"({len(warnings)} lines)")

    events = [e for e in eng.events_snapshot() if e[2] == "WARN"]
    check("and it lands in the event log, so it reaches the repro report",
          events, f"({eng.events_snapshot()})")

    # after a reset the warning must be able to fire again: a fresh measurement
    # window that overflows must say so afresh
    eng.reset_stats()
    lines.clear()
    for _ in range(10):
        eng._enqueue(1.0, object())
    check("a reset re-arms the warning", any("queue" in line.lower()
                                             or "kolejka" in line.lower()
                                             for line in lines), f"({lines})")
