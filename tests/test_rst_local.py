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
