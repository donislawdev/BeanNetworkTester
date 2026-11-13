"""The capture driver's OWN filter evaluator, for tests that must not trust a reading.

``WinDivertHelperEvalFilter`` on Windows and eBPFDivert's
``ebpfdivert_helper_eval_filter`` on Linux - the same WinDivert code, built into
libebpfdivert - answer whether a filter admits a packet. A test asking them checks
the filter against the code the driver runs, not one reading of the filter
language against another.

``outbound``, ``loopback`` and the address family live in WINDIVERT_ADDRESS, not
in the packet, and the evaluator reads them from there (verified 2026-07-28 on 40
real packets, and again 2026-11-13 on every filter of ``filters.FILTER_DEFS``), so
a synthetic packet with the bits set in a synthetic address means what it says.
"""
import ctypes
import struct
import sys

import pytest


def evaluator():
    """``evaluates(text, raw, outbound=1, loopback=0) -> bool``, or a skip.

    Skips only where there is nothing to ask: no ``pydivert``, or a Linux one whose
    libebpfdivert did not load.
    """
    pytest.importorskip("pydivert")
    from pydivert.windivert_dll import WinDivertAddress

    if sys.platform.startswith("linux"):
        from pydivert.bpf import libebpfdivert
        if libebpfdivert is None:
            pytest.skip("pydivert is installed, but its libebpfdivert did not load")

        def ask(text, buf, size, addr):
            # 1 = admits, 0 = does not, anything else is an error - which must not
            # read as "admits", or a broken evaluator would hide every violation
            return libebpfdivert.ebpfdivert_helper_eval_filter(
                text.encode(), buf, size, ctypes.byref(addr)) == 1
    else:
        from pydivert import windivert_dll as w

        def ask(text, buf, size, addr):
            return bool(w.WinDivertHelperEvalFilter(text.encode(), buf, size,
                                                    ctypes.byref(addr)))

    def evaluates(text, raw, outbound=1, loopback=0):
        addr = WinDivertAddress()
        addr.Outbound = outbound
        addr.Loopback = loopback
        addr.IPv6 = 1 if raw[0] >> 4 == 6 else 0
        return ask(text, ctypes.create_string_buffer(raw, len(raw)), len(raw), addr)

    return evaluates


# -- synthetic packets ---------------------------------------------------------- #
def ipv4(protocol, body, src="10.0.0.1", dst="8.8.8.8"):
    total = 20 + len(body)
    return struct.pack(">BBHHHBBH4s4s", 0x45, 0, total, 1, 0, 64, protocol, 0,
                       bytes(int(x) for x in src.split(".")),
                       bytes(int(x) for x in dst.split("."))) + body


def ipv6(next_header, body):
    src = bytes(15) + b"\x01"
    dst = bytes([0x20, 0x01, 0x48, 0x60]) + bytes(11) + b"\x88"
    return struct.pack(">IHBB", 6 << 28, len(body), next_header, 64) + src + dst + body


def udp_body(src_port=50000, dst_port=53, payload=b"abcd"):
    return struct.pack(">HHHH", src_port, dst_port, 8 + len(payload), 0) + payload


def tcp_syn_body(src_port=50000, dst_port=443):
    return struct.pack(">HHIIBBHHH", src_port, dst_port, 1, 0, 5 << 4, 0x02, 65535, 0, 0)


def echo_body(icmp_type):
    """An echo request: type 8 for ICMP, 128 for ICMPv6."""
    return struct.pack(">BBHHH", icmp_type, 0, 0, 1, 1) + b"abcd"


# One packet per (protocol, family): the protocol names are filters.TCP/UDP/ICMP.
PACKETS = (("tcp", ipv4(6, tcp_syn_body())), ("udp", ipv4(17, udp_body())),
           ("icmp", ipv4(1, echo_body(8))), ("tcp", ipv6(6, tcp_syn_body())),
           ("udp", ipv6(17, udp_body())), ("icmp", ipv6(58, echo_body(128))))
