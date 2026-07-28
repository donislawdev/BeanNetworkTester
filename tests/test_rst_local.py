"""RST injection and SYN dropping, exercised locally (no WinDivert / admin).

Before this, ``rst_sent`` could never move off Windows: ``_send_rst`` hard-imported
pydivert, and synthetic traffic had no TCP layer, so neither the RST nor the SYN
path ran in tests or in ``--simulate``. The engine now builds the RST through the
divert's ``make_rst`` hook, and ``SyntheticDivert`` carries a real protocol mix.
"""
import time

from beantester import BeanEngine
from beantester.synthetic import (SyntheticDivert, _SyntheticPacket, _SyntheticTCP,
                                  build_synthetic_rst)


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

    def send(self, p):
        self.sent.append(p)

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
