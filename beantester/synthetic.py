"""Synthetic traffic source for ``--simulate`` mode (no WinDivert / admin).

The synthetic stream now carries a realistic protocol mix (TCP, some of it SYN,
plus UDP and ICMP), so the TCP-only impairments - SYN dropping and RST injection
- can be exercised locally, off Windows. Packet construction for an injected RST
lives here too (``build_synthetic_rst``): the traffic source owns the packet type,
so the engine can build an RST of the right shape without importing pydivert.
"""
import random
import time


class _SyntheticTCP:
    """Minimal TCP header shaped like pydivert's ``packet.tcp``."""

    def __init__(self, syn=False, ack=False, rst=False, fin=False, psh=False,
                 seq_num=0, ack_num=0):
        self.syn = syn
        self.ack = ack
        self.rst = rst
        self.fin = fin
        self.psh = psh
        self.seq_num = seq_num
        self.ack_num = ack_num


class _SyntheticPacket:
    """Minimal packet object shaped like a pydivert packet."""

    def __init__(self, raw, is_outbound, port, src_addr, dst_addr,
                 tcp=None, udp=None, icmp=None, interface=(0, 0)):
        self.raw = raw
        self.is_outbound = is_outbound
        self.src_port = port
        self.dst_port = port
        self.src_addr = src_addr
        self.dst_addr = dst_addr
        self.tcp = tcp
        self.udp = udp
        self.icmp = icmp
        self.interface = interface
        self._payload = b"payload-data"

    @property
    def payload(self):
        return self._payload

    @payload.setter
    def payload(self, value):
        self._payload = value


class _SyntheticUDP:
    """Marker for a UDP packet (pydivert exposes a ``packet.udp`` object)."""


def build_synthetic_rst(packet, fields):
    """Build a synthetic RST packet from ``BeanCore.build_rst_fields`` output.

    Mirrors the real (pydivert) construction in ``BeanEngine._build_rst_packet``:
    an INBOUND TCP segment with only the RST flag set, addresses/ports taken from
    ``fields`` (already aimed at the local end). Returned to the engine, which
    hands it to ``divert.send`` and counts ``rst_sent`` - so the RST path is
    testable without WinDivert.
    """
    tcp = _SyntheticTCP(rst=True, seq_num=fields.get("seq_num", 0))
    rst = _SyntheticPacket(
        raw=b"\x00" * 40,
        is_outbound=False,
        port=fields.get("src_port", 0),
        src_addr=fields.get("src_ip"),
        dst_addr=fields.get("dst_ip"),
        tcp=tcp,
    )
    rst.src_port = fields.get("src_port", 0)
    rst.dst_port = fields.get("dst_port", 0)
    rst.payload = b""
    return rst


class SyntheticDivert:
    """Generates random fake traffic; drop-in replacement for WinDivert.

    Reproducible given a ``seed``: every draw comes from ``self._rng``, so two
    diverts with the same seed emit an identical packet sequence (the seed tests
    depend on this).
    """

    _REMOTE_ADDRS = ("93.184.216.34", "142.250.1.100", "1.1.1.1")

    def __init__(self, gen_kbps=2000, ports=(2000, 2001, 2002), seed=None):
        self._interval = 1500.0 / (gen_kbps * 1024) if gen_kbps > 0 else 0.001
        self._ports = list(ports)
        self._rng = random.Random(seed) if seed is not None else random
        self.closed = False

    def open(self):
        pass

    def _make_layer(self, rng, is_outbound):
        """Pick a protocol for the next packet: mostly TCP, some UDP, some ICMP.

        Only the chosen layer object is set; the engine detects the protocol by
        which of ``packet.tcp`` / ``packet.udp`` / ``packet.icmp`` is not ``None``
        (exactly like pydivert), so the others stay ``None``.
        """
        roll = rng.random()
        if roll < 0.70:
            # a TCP segment; ~12% of them are a bare SYN (new connection)
            is_syn = rng.random() < 0.12
            tcp = _SyntheticTCP(syn=is_syn, ack=not is_syn,
                                seq_num=rng.randrange(1, 2**31),
                                ack_num=rng.randrange(1, 2**31))
            return dict(tcp=tcp)
        if roll < 0.90:
            return dict(udp=_SyntheticUDP())
        return dict(icmp=object())

    def recv(self):
        if self.closed:
            raise OSError("closed")
        time.sleep(self._interval)
        rng = self._rng
        is_outbound = rng.random() < 0.4
        layer = self._make_layer(rng, is_outbound)
        return _SyntheticPacket(
            raw=b"\x00" * rng.randint(200, 1500),
            is_outbound=is_outbound,
            port=rng.choice(self._ports),
            src_addr="10.0.0.2",
            dst_addr=rng.choice(self._REMOTE_ADDRS),
            **layer,
        )

    def make_rst(self, packet, fields):
        """Build the RST packet the engine wants to inject (see build_synthetic_rst)."""
        return build_synthetic_rst(packet, fields)

    def send(self, packet):
        pass

    def close(self):
        self.closed = True
