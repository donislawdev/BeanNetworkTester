"""Decision-core tests: the full BeanCore.decide() pipeline and its edge cases.

Ported 1:1 from the original monolithic suite; every ``check(...)`` from the
270-assertion baseline is preserved as a pytest assertion.
"""
import random

from beantester import BeanCore, Decision
from fakes import FakePacket, check



def test_loss():
    core = BeanCore(); core.set_params(20, 0, 0, 0, 0, 0, 0)
    rng = random.Random(1)
    n = 20000
    drops = sum(core.decide(100, False, None, 0.0, rng).drop for _ in range(n))
    frac = drops / n
    check("loss ~20%", 0.18 < frac < 0.22, f"(zmierzono {frac:.3f})")


def test_latency_exact():
    core = BeanCore(); core.set_params(0, 0, 0, 100, 0, 0, 0)  # 100 ms, no jitter
    rng = random.Random(1)
    d = core.decide(100, False, None, 5.0, rng)
    rel = d.releases[0] - 5.0
    check("latency = 100 ms", abs(rel - 0.1) < 1e-9, f"(rel={rel:.4f}s)")


def test_jitter_bounds():
    core = BeanCore(); core.set_params(0, 0, 0, 100, 50, 0, 0)
    rng = random.Random(3)
    ok = True
    for _ in range(5000):
        rel = core.decide(100, False, None, 0.0, rng).releases[0]
        if not (0.05 - 1e-9 <= rel <= 0.15 + 1e-9):
            ok = False; break
    check("jitter within 50-150 ms", ok)


def test_throttle_rate():
    # 100 KB/s => 102400 B/s; 1500 B packets
    kbps = 100
    core = BeanCore(); core.set_params(0, 0, 0, 0, 0, kbps, 0)  # download only
    core.reset_buckets(0.0)
    rng = random.Random(1)
    size, n = 1500, 400
    now = 0.0
    last = 0.0
    for _ in range(n):
        rel = core.decide(size, False, None, now, rng).releases[0]
        last = rel
        now = rel  # next packet available as the previous one leaves
    measured = (n * size) / last  # B/s
    target = kbps * 1024
    err = abs(measured - target) / target
    check("throttling ~100 KB/s", err < 0.05, f"(measured {measured/1024:.1f} KB/s)")


def test_throttle_direction_independent():
    core = BeanCore(); core.set_params(0, 0, 0, 0, 0, 50, 0)  # limit download only
    core.reset_buckets(0.0)
    rng = random.Random(1)
    up = core.decide(1500, True, None, 0.0, rng).releases[0]   # upload unlimited
    check("upload unlimited when only download is limited", abs(up - 0.0) < 1e-9, f"(rel={up})")


def test_corrupt_flag_and_mutation():
    core = BeanCore(); core.set_params(0, 100, 0, 0, 0, 0, 0)  # 100% corruption
    rng = random.Random(1)
    d = core.decide(100, False, None, 0.0, rng)
    check("corruption flag set at 100%", d.corrupt is True)
    pkt = FakePacket(payload=b"AAAAAAAA")
    before = pkt.payload
    changed = BeanCore.corrupt_packet(pkt)
    check("payload actually mutated", changed and pkt.payload != before,
          f"(before={before}, after={pkt.payload})")


def test_duplication():
    core = BeanCore(); core.set_params(0, 0, 100, 0, 0, 0, 0)  # 100% duplication
    rng = random.Random(1)
    d = core.decide(100, False, None, 0.0, rng)
    check("duplication yields 2 copies", len(d.releases) == 2, f"(copies={len(d.releases)})")


def test_targeting_gate():
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)   # 100% loss...
    core.set_target(True, {80})              # ...but only for port 80
    rng = random.Random(1)
    # off-target packet -> passed despite 100% loss
    d_other = core.decide(100, True, 1234, 0.0, rng)
    check("off-target packet passed", d_other.drop is False and d_other.releases == [0.0])
    # target packet -> dropped
    d_target = core.decide(100, True, 80, 0.0, rng)
    check("target packet subject to loss", d_target.drop is True)


def test_flapping():
    core = BeanCore()
    core.set_flap(True, 10.0, 30)   # period 10 s, first 30% down (0-3 s)
    rng = random.Random(1)
    down = core.decide(100, False, None, 1.0, rng).drop   # t=1s inside the down window
    up = core.decide(100, False, None, 6.0, rng).drop     # t=6s link works
    check("flapping: dropped inside the outage window", down is True)
    check("flapping: works outside the outage window", up is False)


# --- threaded integration test with a fake diverter ------------------------ #


def test_dest_ip_targeting():
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)      # 100% loss...
    core.set_dest(True, ip="1.2.3.4")           # ...but only to IP 1.2.3.4
    rng = random.Random(1)
    other = core.decide(100, True, 5000, 0.0, rng, remote_ip="9.9.9.9", remote_port=80)
    hit = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.2.3.4", remote_port=80)
    check("dest IP: other host passed", other.drop is False and other.releases == [0.0])
    check("dest IP: target host impaired", hit.drop is True)


def test_dest_port_targeting():
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)
    core.set_dest(True, port=443)
    rng = random.Random(1)
    p80 = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.1.1.1", remote_port=80)
    p443 = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.1.1.1", remote_port=443)
    check("dest port: port 80 passed", p80.drop is False)
    check("dest port: port 443 impaired", p443.drop is True)


def test_syn_drop():
    core = BeanCore()
    core.set_advanced(100, 0)                   # 100% dropped SYN
    rng = random.Random(1)
    syn = core.decide(60, True, 5000, 0.0, rng, is_syn=True)
    data = core.decide(1400, True, 5000, 0.0, rng, is_syn=False)
    check("SYN drop: SYN dropped (reason=syn)", syn.drop is True and syn.reason == "syn")
    check("SYN drop: regular packet passes", data.drop is False)


def test_mtu_blackhole():
    core = BeanCore()
    core.set_advanced(0, 1000)                  # drop packets > 1000 B
    rng = random.Random(1)
    big = core.decide(1500, False, None, 0.0, rng)
    small = core.decide(500, False, None, 0.0, rng)
    check("MTU: big packet dropped (reason=mtu)", big.drop is True and big.reason == "mtu")
    check("MTU: small packet passes", small.drop is False)


def test_latency_spike():
    core = BeanCore()
    core.set_params(0, 0, 0, 100, 0, 0, 0)   # base 100 ms
    core.set_spike(100, 500)                 # 100% chance of +500 ms
    rng = random.Random(1)
    rel = core.decide(100, False, None, 0.0, rng).releases[0]
    check("latency spike: 100+500 ms", abs(rel - 0.6) < 1e-9, f"(rel={rel:.3f}s)")


def test_nat_expiry():
    core = BeanCore()
    core.set_nat(1.0)                        # mapping expires after 1 s
    rng = random.Random(1)
    # outbound creates the mapping
    core.decide(100, True, 5000, 0.0, rng, remote_ip="1.2.3.4", remote_port=443, is_tcp=True)
    # inbound after 0.5 s - OK
    d_ok = core.decide(100, False, 5000, 0.5, rng, remote_ip="1.2.3.4", remote_port=443, is_tcp=True)
    # inbound after 3 s idle - mapping expired -> drop
    d_exp = core.decide(100, False, 5000, 3.5, rng, remote_ip="1.2.3.4", remote_port=443, is_tcp=True)
    check("NAT: fresh traffic passes", d_ok.drop is False)
    check("NAT: inbound after idle dropped", d_exp.drop is True and d_exp.reason == "nat")


def test_rst_injection_decision():
    core = BeanCore()
    core.set_rst(100, 3.0)                   # every TCP resets its own flow
    rng = random.Random(1)
    first = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.2.3.4", remote_port=80, is_tcp=True)
    second = core.decide(100, True, 5000, 0.1, rng, remote_ip="1.2.3.4", remote_port=80, is_tcp=True)
    check("RST: first packet emits RST", first.drop and first.reason == "rst" and first.emit_rst)
    check("RST: subsequent flow packets keep dying (cooldown)",
          second.drop and second.reason == "rst" and not second.emit_rst)


def test_reset_now():
    core = BeanCore()
    core.reset_now(2.0, now=0.0)             # reset everything for 2 s
    rng = random.Random(1)
    d = core.decide(100, True, 6000, 0.5, rng, remote_ip="9.9.9.9", remote_port=443, is_tcp=True)
    check("Reset now: manual reset emits RST", d.drop and d.reason == "rst" and d.emit_rst)


def test_build_rst_fields():
    class T:  # minimal TCP header
        seq_num = 111; ack_num = 222
    class P:
        is_outbound = True; tcp = T()
        src_addr = "10.0.0.2"; dst_addr = "8.8.8.8"
        src_port = 5000; dst_port = 443
    f = BeanCore.build_rst_fields(P())
    ok = (f["direction_inbound"] and f["src_ip"] == "8.8.8.8" and f["dst_ip"] == "10.0.0.2"
          and f["src_port"] == 443 and f["dst_port"] == 5000 and f["seq_num"] == 222)
    check("RST fields: correctly aimed at the local end", ok, f"({f})")


def test_rate_schedule():
    core = BeanCore()
    core.set_schedule([(1.0, 100, 0), (1.0, 400, 0)])   # 1s@100, 1s@400, loop
    core.reset_buckets(0.0)
    r0 = core._current_rates(0.5)     # in the first window
    r1 = core._current_rates(1.5)     # in the second window
    r2 = core._current_rates(2.5)     # first again (loop)
    check("schedule: window 1 = 100 KB/s", r0[0] == 100 * 1024, f"(={r0[0]})")
    check("schedule: window 2 = 400 KB/s", r1[0] == 400 * 1024, f"(={r1[0]})")
    check("schedule: loop returns to 100", r2[0] == 100 * 1024, f"(={r2[0]})")


def test_seed_decision_sequence_identical():
    """Same seed -> identical decision sequence for the same packet sequence."""
    from beantester import BeanCore

    def run(seed):
        core = BeanCore()
        core.set_params(20, 10, 10, 100, 50, 0, 0)   # loss/corrupt/dup + latency/jitter
        rng = random.Random(seed)
        out = []
        for i in range(60):
            d = core.decide(200 + i, i % 2 == 0, 5000 + (i % 3), i * 0.01, rng,
                            remote_ip="93.184.216.34", remote_port=443, is_tcp=True)
            out.append((d.drop, d.corrupt, tuple(round(r, 4) for r in d.releases)))
        return out

    a, b, c = run(777), run(777), run(778)
    check("seed: identical seed => identical decisions", a == b)
    check("seed: different seed => different decisions", a != c)


def test_is_local_ip():
    from beantester import is_local_ip
    check("LAN: 192.168.x local", is_local_ip("192.168.1.10"))
    check("LAN: 10.x local", is_local_ip("10.0.0.5"))
    check("LAN: 172.16-31.x local", is_local_ip("172.20.1.1"))
    check("LAN: loopback local", is_local_ip("127.0.0.1"))
    check("LAN: 8.8.8.8 public", not is_local_ip("8.8.8.8"))
    check("LAN: 1.1.1.1 public", not is_local_ip("1.1.1.1"))
    check("LAN: missing IP treated as local (safe)", is_local_ip(None))


def test_host_identity():
    from beantester.utils import host_identity
    host, ipv4, ipv6 = host_identity()
    check("host_identity: hostname is a non-empty string",
          isinstance(host, str) and bool(host))
    check("host_identity: IPv4 is a non-empty string",
          isinstance(ipv4, str) and bool(ipv4))
    check("host_identity: IPv6 is a non-empty string",
          isinstance(ipv6, str) and bool(ipv6))


def test_lan_mode_gate():
    core = BeanCore()
    core.set_lan(True)
    rng = random.Random(1)
    pub = core.decide(200, True, 5000, 0.0, rng, remote_ip="8.8.8.8", remote_port=443)
    loc = core.decide(200, True, 5000, 0.0, rng, remote_ip="192.168.1.5", remote_port=443)
    check("LAN: internet traffic dropped", pub.drop and pub.reason == "lan",
          f"(drop={pub.drop}, reason={pub.reason})")
    check("LAN: local traffic passes", not loc.drop, f"(drop={loc.drop})")
    core.set_lan(False)
    off = core.decide(200, True, 5000, 0.0, rng, remote_ip="8.8.8.8", remote_port=443)
    check("LAN: disabled = internet passes", not off.drop, f"(drop={off.drop})")


def test_decision_scoped_reflects_targeting():
    """`scoped` says whether a packet passed the targeting gate (steps 1-2), i.e.
    whether the flow is in scope for impairment - the signal behind the "impaired?"
    column. Only process/destination targeting turns it off; every impairment path
    leaves it on."""
    core = BeanCore()
    rng = random.Random(0)

    # no targeting at all: every flow is in scope
    d = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.1.1.1", remote_port=80)
    check("scoped: no targeting -> in scope", d.scoped is True, f"(scoped={d.scoped})")

    # process targeting: excluded port is out of scope, matching port is in
    core.set_target(True, {9999})
    miss = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.1.1.1", remote_port=80)
    check("scoped: process targeting excludes -> out of scope",
          miss.scoped is False and miss.drop is False, f"(scoped={miss.scoped})")
    hit = core.decide(100, True, 9999, 0.0, rng, remote_ip="1.1.1.1", remote_port=80)
    check("scoped: matching process -> in scope", hit.scoped is True)
    core.set_target(False)

    # destination targeting: non-matching IP is out of scope, matching IP is in
    core.set_dest(True, ip="10.0.0.0/8")
    dmiss = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.1.1.1", remote_port=80)
    check("scoped: dest targeting excludes -> out of scope", dmiss.scoped is False)
    dhit = core.decide(100, True, 5000, 0.0, rng, remote_ip="10.1.2.3", remote_port=80)
    check("scoped: matching dest -> in scope", dhit.scoped is True)
    core.set_dest(False)

    # an impairment drop is still IN scope: it is being impaired, not merely seen
    core.set_lan(True)
    lan = core.decide(100, True, 5000, 0.0, rng, remote_ip="8.8.8.8", remote_port=80)
    check("scoped: an impairment drop stays in scope",
          lan.drop is True and lan.scoped is True, f"(drop={lan.drop}, scoped={lan.scoped})")


def test_is_local_ip_ipv6():
    from beantester import is_local_ip
    check("IPv6: ::1 loopback local", is_local_ip("::1"))
    check("IPv6: fe80:: link-local is local", is_local_ip("fe80::1"))
    check("IPv6: fc00::/7 unique-local is local", is_local_ip("fc00::1234"))
    check("IPv6: 2001:4860:4860::8888 public", not is_local_ip("2001:4860:4860::8888"))
    check("IPv6: garbage address treated as local (safe)", is_local_ip("nie-adres"))


def test_clamp01_and_num():
    from beantester import clamp01, _num
    check("clamp01: below range -> 0", clamp01(-5) == 0.0)
    check("clamp01: above range -> 1", clamp01(7) == 1.0)
    check("clamp01: in range unchanged", clamp01(0.5) == 0.5)
    check("_num: None -> 0", _num(None) == 0.0)
    check("_num: garbage -> 0", _num("abc") == 0.0)
    check("_num: numeric string parsed", _num("3.5") == 3.5)


def test_corrupt_packet_edge_cases():
    # empty payload -> nothing to flip, must return False (no exception)
    p_empty = FakePacket(payload=b"")
    check("corrupt: empty payload -> False", BeanCore.corrupt_packet(p_empty) is False)

    # object without a payload attribute -> handled, returns False
    class NoPayload:
        pass
    check("corrupt: missing payload -> False (no exception)",
          BeanCore.corrupt_packet(NoPayload()) is False)

    # exactly one bit flipped (payload length preserved, hamming distance == 1)
    p = FakePacket(payload=b"\x00" * 16)
    BeanCore.corrupt_packet(p, random.Random(5))
    diff_bits = sum(bin(a ^ b).count("1") for a, b in zip(b"\x00" * 16, p.payload))
    check("corrupt: exactly 1 bit flipped", diff_bits == 1 and len(p.payload) == 16,
          f"(bits={diff_bits}, len={len(p.payload)})")


def test_build_rst_fields_inbound_and_non_tcp():
    class T:  # minimal TCP header
        seq_num = 111; ack_num = 222
    class PIn:
        is_outbound = False; tcp = T()
        src_addr = "8.8.8.8"; dst_addr = "10.0.0.2"
        src_port = 443; dst_port = 5000
    f = BeanCore.build_rst_fields(PIn())
    ok = (f["direction_inbound"] and f["src_ip"] == "8.8.8.8" and f["dst_ip"] == "10.0.0.2"
          and f["src_port"] == 443 and f["dst_port"] == 5000 and f["seq_num"] == 111)
    check("RST fields: inbound packet uses seq_num", ok, f"({f})")

    class PNoTcp:
        is_outbound = True; tcp = None
        src_addr = "10.0.0.2"; dst_addr = "8.8.8.8"
        src_port = 5000; dst_port = 443
    check("RST fields: no TCP -> None", BeanCore.build_rst_fields(PNoTcp()) is None)


def test_rst_cooldown_expiry():
    core = BeanCore()
    core.set_rst(100, 1.0)                   # every TCP resets its flow, 1 s cooldown
    rng = random.Random(1)
    kw = dict(remote_ip="1.2.3.4", remote_port=80, is_tcp=True)
    first = core.decide(100, True, 5000, 0.0, rng, **kw)
    during = core.decide(100, True, 5000, 0.5, rng, **kw)
    after = core.decide(100, True, 5000, 2.0, rng, **kw)   # cooldown expired -> new RST
    check("RST cooldown: inside the window drop without another RST",
          during.drop and during.reason == "rst" and not during.emit_rst)
    check("RST cooldown: after expiry a new reset emits RST",
          first.emit_rst and after.drop and after.reason == "rst" and after.emit_rst)


def test_reset_now_expiry_and_scope():
    core = BeanCore()
    core.reset_now(1.0, now=0.0)             # manual reset window: 0-1 s
    rng = random.Random(1)
    # non-TCP traffic is not affected by RST logic even inside the window
    udp = core.decide(100, True, 6000, 0.5, rng, remote_ip="9.9.9.9", remote_port=53,
                      is_tcp=False)
    check("Reset now: does not touch non-TCP traffic", udp.drop is False)
    # a fresh TCP flow after the window passes normally
    late = core.decide(100, True, 6001, 2.0, rng, remote_ip="9.9.9.9", remote_port=443,
                       is_tcp=True)
    check("Reset now: TCP passes after the window expires", late.drop is False)


def test_nat_outbound_refreshes():
    core = BeanCore()
    core.set_nat(1.0)                        # mapping expires after 1 s idle
    rng = random.Random(1)
    kw = dict(remote_ip="1.2.3.4", remote_port=443, is_tcp=True)
    core.decide(100, True, 5000, 0.0, rng, **kw)             # create mapping
    # long idle, but the next packet is OUTBOUND -> never dropped, refreshes mapping
    out = core.decide(100, True, 5000, 5.0, rng, **kw)
    inn = core.decide(100, False, 5000, 5.2, rng, **kw)      # fresh again -> passes
    check("NAT: outbound after idle is not dropped", out.drop is False)
    check("NAT: outbound refreshes the mapping (inbound passes)", inn.drop is False)


def test_reset_buckets_clears_flow_state():
    core = BeanCore()
    core.set_rst(100, 30.0)                  # long cooldown to make state persistent
    rng = random.Random(1)
    kw = dict(remote_ip="4.4.4.4", remote_port=80, is_tcp=True)
    core.decide(100, True, 5000, 0.0, rng, **kw)             # flow enters reset state
    core.set_rst(0, 3.0)                                     # disable further RST
    still = core.decide(100, True, 5000, 1.0, rng, **kw)     # cooldown still active
    core.reset_buckets(2.0)                                  # clears buckets + flow state
    freed = core.decide(100, True, 5000, 2.5, rng, **kw)
    check("reset_buckets: before the reset the flow stays cut",
          still.drop and still.reason == "rst")
    check("reset_buckets: clears flow state (traffic resumes)", freed.drop is False)


def test_flow_table_is_bounded_in_size_not_only_in_age():
    """The flow table must have a CEILING, and must never rebuild in the hot path.

    It used to prune by AGE only (drop anything idle for 60 s), so its steady state
    was ``(new flows per second) x 60`` with no upper bound: measured at 3.2 million
    entries / 779 MB under a 50 000 flows/s churn. Worse, the prune REBUILT the dict
    from inside ``decide()`` under the lock - 1001 ms at that size, every 5 seconds,
    with the capture thread frozen the whole time.
    """
    from beantester.core import _FlowTable

    table = _FlowTable(limit=1000, rotate_s=30.0)
    for i in range(5000):
        table.set((i, "1.1.1.1", 80), float(i))
        table.maybe_rotate(0.0)

    check("the table never exceeds its ceiling", len(table) <= 1000,
          f"(len={len(table)})")
    check("recent flows are still there", table.get((4999, "1.1.1.1", 80)) == 4999.0)

    # rotation is a generation swap, not a rebuild: what falls out reads back as
    # None, which the NAT check treats as "never seen" - so the packet PASSES.
    # Eviction can cost a missed impairment; it can never invent one.
    check("an evicted flow reads back as unseen (fail-open)",
          table.get((0, "1.1.1.1", 80)) is None)

    table.clear()
    check("clear() empties both generations", len(table) == 0)


def test_no_flow_tracking_at_all_when_nat_is_off():
    """NAT is the table's ONLY reader, and NAT is off by default.

    Every packet used to write an entry that nothing would ever look at: 50 000
    packets left 50 000 entries behind, for nothing.
    """
    core = BeanCore()
    core.reset_buckets(0.0)
    core.nat_timeout_s = 0.0                    # the default
    rng = random.Random(0)
    for i in range(2000):
        core.decide(500, True, 1024 + i, 1.0, rng,
                    remote_ip=f"10.0.0.{i % 256}", remote_port=443, is_tcp=False)
    check("NAT off: nothing is tracked", len(core._flow_last) == 0,
          f"(len={len(core._flow_last)})")

    # ...but with NAT on it IS tracked, and it still works
    core.nat_timeout_s = 30.0
    core.decide(500, True, 5000, 100.0, rng,
                remote_ip="8.8.8.8", remote_port=443, is_tcp=False)
    check("NAT on: the flow is remembered", len(core._flow_last) == 1)

    # the same flow, seen again after the mapping has expired, inbound -> dropped
    d = core.decide(500, False, 5000, 100.0 + 31.0, rng,
                    remote_ip="8.8.8.8", remote_port=443, is_tcp=False)
    check("an expired NAT mapping drops the inbound packet",
          d.drop and d.reason == "nat", f"({d.reason})")


def test_flap_zero_period_safe():
    core = BeanCore()
    core.set_flap(True, 0.0, 50)             # enabled but period 0 -> must be a no-op
    rng = random.Random(1)
    try:
        d = core.decide(100, False, None, 1.0, rng)
        ok = d.drop is False
    except ZeroDivisionError:
        ok = False
    check("flapping: period 0 neither drops nor divides by zero", ok)


def test_schedule_zero_window_unlimited():
    core = BeanCore()
    core.set_schedule([(1.0, 0, 0), (1.0, 100, 0)])   # window 1: unlimited
    core.reset_buckets(0.0)
    rng = random.Random(1)
    d = core.decide(150000, False, None, 0.5, rng)    # big packet inside window 1
    check("schedule: window with 0 = unlimited (release=now)",
          abs(d.releases[0] - 0.5) < 1e-9, f"(rel={d.releases[0]})")


def test_set_schedule_clamps_invalid():
    core = BeanCore()
    core.set_schedule([(-1.0, -100, -5)])    # nonsense input must be sanitized
    dur, dn, up = core.schedule[0]
    check("schedule: negative values clamped (dur>0, rate>=0)",
          dur >= 0.01 and dn == 0 and up == 0, f"({core.schedule})")


def test_duplicate_release_order():
    core = BeanCore(); core.set_params(0, 0, 100, 50, 0, 0, 0)   # dup 100%, 50 ms latency
    rng = random.Random(1)
    d = core.decide(100, False, None, 0.0, rng)
    check("duplication: copy never precedes the original",
          len(d.releases) == 2 and d.releases[1] >= d.releases[0], f"({d.releases})")


def test_decision_defaults_and_flowkey():
    d = Decision(False, False, [0.0])
    check("Decision: defaults reason=None, emit_rst=False",
          d.reason is None and d.emit_rst is False)
    check("flowkey: missing component -> None",
          BeanCore._flowkey(None, "1.1.1.1", 80) is None
          and BeanCore._flowkey(5000, None, 80) is None
          and BeanCore._flowkey(5000, "1.1.1.1", None) is None)
    check("flowkey: complete data -> tuple",
          BeanCore._flowkey(5000, "1.1.1.1", 80) == (5000, "1.1.1.1", 80))


def test_corrupt_uses_rng():
    p1 = FakePacket(payload=b"AAAAAAAAAAAAAAAA")
    p2 = FakePacket(payload=b"AAAAAAAAAAAAAAAA")
    BeanCore.corrupt_packet(p1, random.Random(99))
    BeanCore.corrupt_packet(p2, random.Random(99))
    check("seed: corruption with the same rng is identical", p1.payload == p2.payload,
          f"({p1.payload} vs {p2.payload})")


def test_is_local_ip_garbage():
    from beantester import is_local_ip
    check("LAN: unparsable address treated as local (safe)",
          is_local_ip("not-an-ip") and is_local_ip("999.999.1.1"))


# --- destination targeting with filter expressions ------------------------- #


def test_dest_ip_list_and_exclusion():
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)              # 100% loss...
    core.set_dest(True, ip="1.2.3.4, 5.6.7.8, !5.6.7.8")  # ...for 1.2.3.4 only
    rng = random.Random(1)
    hit = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.2.3.4", remote_port=80)
    excluded = core.decide(100, True, 5000, 0.0, rng, remote_ip="5.6.7.8", remote_port=80)
    other = core.decide(100, True, 5000, 0.0, rng, remote_ip="9.9.9.9", remote_port=80)
    check("dest IP list: listed host impaired", hit.drop is True)
    check("dest IP list: excluded host passed", excluded.drop is False)
    check("dest IP list: unlisted host passed", other.drop is False)


def test_dest_ip_range_and_cidr():
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)
    core.set_dest(True, ip="10.0.0.1-10.0.0.50")
    rng = random.Random(1)
    inside = core.decide(100, True, 5000, 0.0, rng, remote_ip="10.0.0.25", remote_port=80)
    outside = core.decide(100, True, 5000, 0.0, rng, remote_ip="10.0.0.51", remote_port=80)
    check("dest IP range: inside impaired", inside.drop is True)
    check("dest IP range: outside passed", outside.drop is False)
    core.set_dest(True, ip="192.168.1.0/24")
    inside = core.decide(100, True, 5000, 0.0, rng, remote_ip="192.168.1.9", remote_port=80)
    outside = core.decide(100, True, 5000, 0.0, rng, remote_ip="192.168.2.9", remote_port=80)
    check("dest IP CIDR: inside impaired", inside.drop is True)
    check("dest IP CIDR: outside passed", outside.drop is False)


def test_dest_ipv6_expression():
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)
    core.set_dest(True, ip="2001:db8::/32")
    rng = random.Random(1)
    v6_hit = core.decide(100, True, 5000, 0.0, rng, remote_ip="2001:db8::1", remote_port=443)
    v6_miss = core.decide(100, True, 5000, 0.0, rng, remote_ip="2001:dead::1", remote_port=443)
    v4 = core.decide(100, True, 5000, 0.0, rng, remote_ip="10.0.0.1", remote_port=443)
    check("dest IPv6 CIDR: inside impaired", v6_hit.drop is True)
    check("dest IPv6 CIDR: outside passed", v6_miss.drop is False)
    check("dest IPv6 rule never matches IPv4", v4.drop is False)


def test_dest_port_list_range_and_comparison():
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)
    core.set_dest(True, port="80,443,8000-8100")
    rng = random.Random(1)
    kw = dict(remote_ip="1.1.1.1")
    for port in (80, 443, 8000, 8100):
        d = core.decide(100, True, 5000, 0.0, rng, remote_port=port, **kw)
        check(f"dest port list/range: {port} impaired", d.drop is True)
    for port in (22, 8101):
        d = core.decide(100, True, 5000, 0.0, rng, remote_port=port, **kw)
        check(f"dest port list/range: {port} passed", d.drop is False)
    core.set_dest(True, port=">1024")
    high = core.decide(100, True, 5000, 0.0, rng, remote_port=5000, **kw)
    low = core.decide(100, True, 5000, 0.0, rng, remote_port=80, **kw)
    check("dest port >1024: high port impaired", high.drop is True)
    check("dest port >1024: low port passed", low.drop is False)


def test_dest_port_exclusion_only():
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)
    core.set_dest(True, port="!53")
    rng = random.Random(1)
    kw = dict(remote_ip="1.1.1.1")
    dns = core.decide(100, True, 5000, 0.0, rng, remote_port=53, **kw)
    web = core.decide(100, True, 5000, 0.0, rng, remote_port=443, **kw)
    check("dest port !53: DNS passed", dns.drop is False)
    check("dest port !53: everything else impaired", web.drop is True)


def test_dest_ip_and_port_are_combined_with_and():
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)
    core.set_dest(True, ip="10.0.0.0/8", port="443")
    rng = random.Random(1)
    both = core.decide(100, True, 5000, 0.0, rng, remote_ip="10.1.2.3", remote_port=443)
    ip_only = core.decide(100, True, 5000, 0.0, rng, remote_ip="10.1.2.3", remote_port=80)
    port_only = core.decide(100, True, 5000, 0.0, rng, remote_ip="8.8.8.8", remote_port=443)
    check("dest: IP and port must both match", both.drop is True)
    check("dest: right IP, wrong port passes", ip_only.drop is False)
    check("dest: right port, wrong IP passes", port_only.drop is False)


def test_dest_legacy_single_values_still_work():
    """Old configs/scenarios pass a plain IP and an int port - keep working."""
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)
    core.set_dest(True, ip="1.2.3.4", port=443)
    rng = random.Random(1)
    hit = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.2.3.4", remote_port=443)
    miss = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.2.3.4", remote_port=80)
    check("legacy dest: exact IP+port impaired", hit.drop is True)
    check("legacy dest: other port passed", miss.drop is False)
    check("legacy dest: port 0 means 'any port'",
          BeanCore().set_dest(True, ip="1.2.3.4", port=0) is None)


def test_dest_bad_expression_raises():
    import pytest
    core = BeanCore()
    with pytest.raises(ValueError):
        core.set_dest(True, ip="999.1.1.1")
    with pytest.raises(ValueError):
        core.set_dest(True, port="2000-1000")


# --------------------------------------------------------------------------- #
# Blocking (firewall): pipeline step 2c
# --------------------------------------------------------------------------- #
def test_block_by_ip_drops_matching_only():
    core = BeanCore()                       # no other impairment: the drop is the block
    core.set_block(True, ip="1.2.3.4")
    rng = random.Random(1)
    hit = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.2.3.4", remote_port=80)
    other = core.decide(100, True, 5000, 0.0, rng, remote_ip="9.9.9.9", remote_port=80)
    check("block IP: matching dropped", hit.drop is True and hit.reason == "block")
    check("block IP: drop counts as impairment (scoped)", hit.scoped is True)
    check("block IP: other traffic passes", other.drop is False)


def test_block_by_port_ignores_empty_ip_field():
    """block_port alone blocks that port to ANY ip - the empty IP field must NOT
    turn into 'match everything' (the OR skip-empty rule)."""
    core = BeanCore()
    core.set_block(True, port="443")
    rng = random.Random(1)
    kw = dict(remote_ip="1.2.3.4")
    p443 = core.decide(100, True, 5000, 0.0, rng, remote_port=443, **kw)
    p80 = core.decide(100, True, 5000, 0.0, rng, remote_port=80, **kw)
    check("block port 443: matching dropped", p443.drop is True and p443.reason == "block")
    check("block port 443: other port passes (empty IP field ignored)", p80.drop is False)


def test_block_ip_and_port_combine_with_or():
    """Unlike destination targeting (AND), blocking is a firewall list: OR."""
    core = BeanCore()
    core.set_block(True, ip="10.0.0.0/8", port="443")
    rng = random.Random(1)
    ip_only = core.decide(100, True, 5000, 0.0, rng, remote_ip="10.1.2.3", remote_port=80)
    port_only = core.decide(100, True, 5000, 0.0, rng, remote_ip="8.8.8.8", remote_port=443)
    neither = core.decide(100, True, 5000, 0.0, rng, remote_ip="8.8.8.8", remote_port=80)
    check("block OR: blocked IP alone drops", ip_only.drop is True)
    check("block OR: blocked port alone drops", port_only.drop is True)
    check("block OR: neither passes", neither.drop is False)


def test_block_respects_process_targeting():
    """Block sits after the targeting gate: a process target scopes it, so a flow
    that is not the target passes even when its destination is on the block list."""
    core = BeanCore()
    core.set_target(True, {5000})           # only local port 5000 is in scope
    core.set_block(True, ip="1.2.3.4")
    rng = random.Random(1)
    targeted = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.2.3.4", remote_port=80)
    other = core.decide(100, True, 6001, 0.0, rng, remote_ip="1.2.3.4", remote_port=80)
    check("block within target: dropped", targeted.drop is True and targeted.reason == "block")
    check("block outside target: passed untouched", other.drop is False)


def test_block_inactive_passes_everything():
    core = BeanCore()
    core.set_block(False)
    rng = random.Random(1)
    d = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.2.3.4", remote_port=443)
    check("block off: nothing dropped", d.drop is False and d.reason is None)


def test_block_bad_expression_raises():
    import pytest
    core = BeanCore()
    with pytest.raises(ValueError):
        core.set_block(True, ip="999.1.1.1")
    with pytest.raises(ValueError):
        core.set_block(True, port="2000-1000")
