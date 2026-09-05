"""RST injection and SYN dropping, exercised locally (no WinDivert / admin).

Before this, ``rst_sent`` could never move off Windows: ``_send_rst`` hard-imported
pydivert, and synthetic traffic had no TCP layer, so neither the RST nor the SYN
path ran in tests or in ``--simulate``. The engine now builds the RST through the
divert's ``make_rst`` hook, and ``SyntheticDivert`` carries a real protocol mix.
"""
import time

from beantester import BeanEngine
from beantester.core import BeanCore
from beantester.synthetic import (SyntheticDivert, _SyntheticPacket, _SyntheticTCP,
                                  _SyntheticUDP, build_synthetic_rst)


def _tcp_packet(local_port, remote_port, is_outbound=True, size=120, syn=False):
    tcp = _SyntheticTCP(syn=syn, ack=not syn, seq_num=1000, ack_num=2000)
    p = _SyntheticPacket(raw=b"\x00" * size, is_outbound=is_outbound,
                         port=local_port, src_addr="10.0.0.2", dst_addr="8.8.8.8",
                         tcp=tcp)
    p.src_port, p.dst_port = local_port, remote_port
    return p


class RecordingTcpDivert:
    """Feeds a fixed TCP packet list, records every send, builds synthetic RSTs."""

    def __init__(self, packets):
        self.inbox = list(packets)
        self.i = 0
        self.sent = []
        self.closed = False

    def open(self):
        pass

    def recv(self):
        if self.i < len(self.inbox):
            p = self.inbox[self.i]
            self.i += 1
            return p
        while not self.closed:
            time.sleep(0.003)
        raise OSError("closed")

    def send(self, p, recalculate_checksum=True):
        self.sent.append(p)
        self.recalc = getattr(self, "recalc", [])
        self.recalc.append(recalculate_checksum)

    def make_rst(self, packet, fields):
        return build_synthetic_rst(packet, fields)

    def close(self):
        self.closed = True


def _drain(engine, n, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = engine.stats_snapshot()
        if s["seen"] >= n and s["queue"] == 0:
            break
        time.sleep(0.02)
    time.sleep(0.1)


def test_rst_injection_counts_and_shape():
    # 300 distinct TCP flows, RST probability 100%: every flow's first packet is
    # cut AND gets an RST injected - so drop_rst and rst_sent both move, locally.
    pkts = [_tcp_packet(5000, 6000 + i, is_outbound=True) for i in range(300)]
    div = RecordingTcpDivert(pkts)
    eng = BeanEngine()
    eng.set_rst(100, 3.0)
    eng.start("test", divert=div)
    _drain(eng, 300)
    eng.stop()
    s = eng.stats_snapshot()

    assert s["drop_rst"] >= 300, s["drop_rst"]
    assert s["rst_sent"] >= 300, s["rst_sent"]      # was permanently 0 off Windows
    assert div.sent, "no RST was injected"
    rst = div.sent[0]
    assert rst.tcp is not None and rst.tcp.rst is True
    assert rst.is_outbound is False                 # aimed at the local end
    # ports are swapped relative to the observed outbound packet
    assert (rst.src_port, rst.dst_port) == (6000, 5000)


def test_an_injected_rst_is_always_recomputed():
    """An RST is BUILT here, not captured, so nothing has ever computed its
    checksums and no hardware-offload flag applies to it.

    The engine skips the recomputation for packets it did not edit - that is
    worth a measured 1.122x and is what makes an unimpaired session pass traffic
    through byte for byte (see tests/test_checksums.py). This packet is the
    exception, and the failure mode if it is ever folded into the same rule is
    nasty to read: the local stack drops the segment on arrival, so the symptom
    is "RST does not reset the connection", with `rst_sent` happily counting up.
    """
    pkts = [_tcp_packet(5100, 6100, is_outbound=True)]
    div = RecordingTcpDivert(pkts)
    eng = BeanEngine()
    eng.set_rst(100, 3.0)
    eng.start("test", divert=div)
    _drain(eng, 1)
    eng.stop()

    assert div.sent, "no RST was injected"
    assert getattr(div, "recalc", []), "nothing recorded the recalculation flag"
    # the dropped packet never reaches send(), so every send here IS an RST
    assert all(p.tcp is not None and p.tcp.rst for p in div.sent), div.sent
    assert all(div.recalc), div.recalc


def test_rst_cooldown_sends_once_then_drops_silently():
    # One flow, many packets: the first triggers an RST, the rest are cut during
    # the cooldown WITHOUT a second RST (drop_rst keeps counting, rst_sent stops).
    pkts = [_tcp_packet(5000, 6000, is_outbound=True) for _ in range(50)]
    div = RecordingTcpDivert(pkts)
    eng = BeanEngine()
    eng.set_rst(100, 30.0)          # long cooldown so all 50 land inside it
    eng.start("test", divert=div)
    _drain(eng, 50)
    eng.stop()
    s = eng.stats_snapshot()

    assert s["drop_rst"] == 50, s["drop_rst"]
    assert s["rst_sent"] == 1, s["rst_sent"]        # exactly one RST for the flow
    # ONE connection was reset, and it then swallowed 50 packets for its cooldown.
    assert s["rst_reset"] == 1, s["rst_reset"]

    # This is the session that tells the three numbers apart, so the repro report's
    # naming is asserted HERE rather than in a run where they all happen to be 0:
    # `connections_reset` used to be drop_rst, and would read 50 for one reset.
    from beantester import DEFAULT_SETTINGS, build_repro_report
    m = build_repro_report(eng, dict(DEFAULT_SETTINGS))["metrics"]
    assert m["connections_reset"] == 1, m["connections_reset"]
    assert m["rst_packets_dropped"] == 50, m["rst_packets_dropped"]
    assert m["rst_sent"] == 1, m["rst_sent"]


def _raw_tcp_ack(sport=54321, dport=39854, seq=1000, ack=2000):
    """A minimal, valid IPv4+TCP ACK - enough for _build_rst_packet to work on."""
    import struct

    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 40, 1, 0, 64, 6, 0,
                     bytes([127, 0, 0, 1]), bytes([127, 0, 0, 1]))
    tcp = struct.pack(">HHIIBBHHH", sport, dport, seq, ack, 0x50, 0x10, 8192, 0, 0)
    return bytearray(ip + tcp)


def test_a_loopback_rst_is_injected_the_way_loopback_packets_travel():
    """Loopback has no inbound path to aim an RST at.

    MEASURED (2026-07-28, real driver, own echo server): sniffing 127.0.0.1 TCP
    showed every packet presented exactly once as `outbound=1, loopback=1` - both
    directions of the conversation, the server's replies included. An RST injected
    as INBOUND there goes onto a path the stack never reads, and the connection
    just went silent for the cooldown: `TIMED OUT after 26 exchanges`, twice, with
    `rst=5/1`. Injected the way real loopback packets travel it resets in 6.5 s
    with WinError 10054 and `rst=1/1`.

    An ordinary connection keeps INBOUND, which is measured to work (DNS over TCP
    to 8.8.8.8:53, reset at 6.6 s). Conditional on pydivert, a win32-only
    dependency - the same shape as the driver-queue ABI check.
    """
    import importlib.util

    if importlib.util.find_spec("pydivert") is None:
        return
    import pydivert
    from beantester.core import BeanCore

    eng = BeanEngine()                    # no divert: takes the real pydivert path
    src = pydivert.Packet(memoryview(_raw_tcp_ack()), (0, 0),
                          pydivert.Direction.OUTBOUND)
    fields = BeanCore.build_rst_fields(src)
    assert fields, "the probe packet is not usable as an RST source"

    src.is_loopback = True
    rst = eng._build_rst_packet(src, fields)
    assert rst is not None, "no RST was built for a loopback packet"
    assert rst.is_loopback is True, "the RST is not marked as loopback"
    assert rst.direction == pydivert.Direction.OUTBOUND, (
        "a loopback RST must travel the way loopback packets do", rst.direction)

    src.is_loopback = False
    plain = eng._build_rst_packet(src, fields)
    assert plain.is_loopback is False, plain.is_loopback
    assert plain.direction == pydivert.Direction.INBOUND, (
        "an ordinary RST must still be aimed at the local end", plain.direction)


def test_simulate_mode_exercises_rst():
    eng = BeanEngine()
    eng.set_rst(80, 3.0)
    eng.start("test", divert=SyntheticDivert(gen_kbps=6000, seed=3))
    _drain(eng, 2000)
    eng.stop()
    s = eng.stats_snapshot()
    assert s["drop_rst"] > 0, "no TCP flow was reset in simulate mode"
    assert s["rst_sent"] > 0, "RST never injected/counted in simulate mode"


def test_simulate_mode_exercises_syn_drop():
    eng = BeanEngine()
    eng.set_advanced(100, 0)        # drop every SYN
    eng.start("test", divert=SyntheticDivert(gen_kbps=6000, seed=4))
    _drain(eng, 2000)
    eng.stop()
    s = eng.stats_snapshot()
    assert s["drop_syn"] > 0, "no SYN packets were generated/dropped in simulate mode"


def _udp_packet(local_port, remote_port):
    """The same conversation over UDP, where a reset does not exist."""
    p = _SyntheticPacket(raw=b"\x00" * 120, is_outbound=True, port=local_port,
                         src_addr="10.0.0.2", dst_addr="8.8.8.8",
                         udp=_SyntheticUDP())
    p.src_port, p.dst_port = local_port, remote_port
    return p


def _blocked_run(packet, reject):
    """One packet against a block on port 6000. Returns (stats, injected)."""
    div = RecordingTcpDivert([packet])
    eng = BeanEngine()
    eng.set_block(True, None, "6000", reject)
    eng.start("test", divert=div)
    _drain(eng, 1)
    eng.stop()
    return eng.stats_snapshot(), div.sent


def test_a_blocked_connection_is_refused_only_when_the_mode_is_on():
    """The whole point of the mode: silence, or an answer, from the same block.

    Both halves are asserted in one test on purpose. "It sends a reset" is only
    interesting next to "it did not before" - a test that checked the mode ON
    alone would pass just as happily if the block sent a reset unconditionally,
    which would change what every existing block does.
    """
    quiet, quiet_sent = _blocked_run(_tcp_packet(5000, 6000, syn=True), False)
    loud, loud_sent = _blocked_run(_tcp_packet(5000, 6000, syn=True), True)

    assert quiet["drop_block"] >= 1 and loud["drop_block"] >= 1, (quiet, loud)
    assert quiet_sent == [], "a block with the mode off answered anyway"
    assert len(loud_sent) == 1, loud_sent
    assert loud_sent[0].tcp.rst is True
    assert loud["rst_sent"] >= 1, loud["rst_sent"]


def test_every_forged_reset_is_counted_under_its_own_cause():
    """A refusal is not a connection torn down, and they may not share a number.

    `rst_reset` ships to the user as `connections_reset` in the stats CSV and in
    the reproduction report, and it means an ESTABLISHED connection was cut and
    put in cooldown. A blocked connection is refused at the door and has no
    cooldown at all. One number for both would make both unreadable.
    """
    blocked, _ = _blocked_run(_tcp_packet(5000, 6000, syn=True), True)
    assert blocked["block_rejected"] >= 1, blocked["block_rejected"]
    assert blocked["rst_reset"] == 0, blocked["rst_reset"]

    # ...and the other cause still lands where it always did.
    div = RecordingTcpDivert([_tcp_packet(5000, 7000) for _ in range(3)])
    eng = BeanEngine()
    eng.set_rst(100, 3.0)
    eng.start("test", divert=div)
    _drain(eng, 3)
    eng.stop()
    reset = eng.stats_snapshot()
    assert reset["rst_reset"] >= 1, reset["rst_reset"]
    assert reset["block_rejected"] == 0, reset["block_rejected"]


def test_the_reset_that_answers_a_syn_acknowledges_it():
    """RFC 793: a bare RST is discarded in SYN_SENT, and this was MEASURED.

    2026-07-28: the shape below without an ACK left the client hanging until its
    own timeout while `rst_sent` reported success. 2026-09-05, against the LAN
    peer: with the ACK it ends the connect with WinError 10061, three runs of
    three, and in the same time a genuinely closed port takes.
    """
    syn = _tcp_packet(5000, 6000, syn=True)
    fields = BeanCore.build_rst_fields(syn)
    assert fields["ack_num"] == syn.tcp.seq_num + 1, fields
    assert fields["seq_num"] == 0, fields
    rst = build_synthetic_rst(syn, fields)
    assert rst.tcp.ack is True and rst.tcp.ack_num == syn.tcp.seq_num + 1

    # A conversation already under way keeps the shape that was measured working
    # for it: no ACK, and the packet's own ack_num as the sequence.
    live = _tcp_packet(5000, 6000)
    fields = BeanCore.build_rst_fields(live)
    assert fields["ack_num"] is None, fields
    assert fields["seq_num"] == live.tcp.ack_num, fields
    assert build_synthetic_rst(live, fields).tcp.ack is False


def test_what_the_refusal_deliberately_does_not_answer():
    """Two shapes that would forge a reset nobody receives, so they must not.

    An inbound SYN is somebody connecting TO this machine: the reset is aimed at
    the local end, which has no such connection yet, so it would be discarded and
    only the counters would move. UDP has no reset at all - its refusal is an ICMP
    port-unreachable this tool does not build. Both limits are in the tooltip,
    because an option that does nothing in someone's setup has to say so.
    """
    # Coming IN, the remote end is the SOURCE, so the blocked port has to be the
    # source port for the block to match at all - the first draft of this test put
    # it on the destination and measured a packet nothing blocked.
    inbound, inbound_sent = _blocked_run(
        _tcp_packet(6000, 5000, is_outbound=False, syn=True), True)
    assert inbound["drop_block"] >= 1, inbound
    assert inbound_sent == [], "an inbound SYN was answered with a reset"
    assert inbound["block_rejected"] == 0, inbound["block_rejected"]

    udp, udp_sent = _blocked_run(_udp_packet(5000, 6000), True)
    assert udp["drop_block"] >= 1, udp
    assert udp_sent == [], "a UDP packet was answered with a TCP reset"
    assert udp["block_rejected"] == 0, udp["block_rejected"]


class FailingRstDivert(RecordingTcpDivert):
    """Every injection fails - a busy driver, or a handle that went away."""

    def send(self, p, recalculate_checksum=True):
        raise OSError("driver busy")


def test_a_reset_that_cannot_be_injected_is_reported_once_not_per_packet():
    """The refuse mode has no cooldown, so a failing injection repeats per SYN.

    MEASURED 2026-09-05 against the LAN peer: five SYN retransmits, five resets, in
    two seconds, for ONE connect(). The RST feature could only ever fail slowly - it
    holds a flow in cooldown for seconds - so this path had no rate limit, and with
    a client reconnecting in a loop it would be a log line per packet, applied on
    the GUI's UI thread. The engine already learned that above OVERFLOW_WARN_S.

    The counters are asserted next to the log for a reason: "we tried to refuse" and
    "the refusal reached the stack" are different facts, and a session where the
    driver refuses every injection must show the gap rather than hide it.
    """
    lines = []
    div = FailingRstDivert([_tcp_packet(5000 + i, 6000, syn=True) for i in range(4)])
    eng = BeanEngine(log_fn=lines.append)
    eng.set_block(True, None, "6000", True)
    eng.start("test", divert=div)
    _drain(eng, 4)
    eng.stop()
    s = eng.stats_snapshot()

    assert s["block_rejected"] >= 4, s["block_rejected"]   # every one was attempted
    assert s["rst_sent"] == 0, s["rst_sent"]               # ...and none arrived
    complaints = [line for line in lines if "driver busy" in line]
    assert len(complaints) == 1, complaints
