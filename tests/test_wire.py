"""``wire.payload_length``: how many bytes of data a captured packet carries.

Two properties carry the weight. It may never raise - it runs inside ``decide()``,
where an exception ends the session - and it may never report a size for a packet
it cannot read, because the caller impairs by that size: a wrong number damages
traffic the session was told to spare.
"""
import struct

from hypothesis import given, settings
from hypothesis import strategies as st

from beantester.wire import MIN_PACKET, payload_length
from fakes import check
from test_ice import HOME, PEER_LAN, udp4, udp6

HOME6, PEER6 = "fd00::1", "fd00::2"
MORE_FRAGMENTS = 0x2000


def tcp4(payload, options=0, ihl=5, frag=0, offset=None):
    """An IPv4 TCP segment: ``options`` extra 32-bit words in the TCP header."""
    words = 5 + options if offset is None else offset
    tcp = struct.pack(">HHIIBBHHH", 50000, 443, 1, 1, words << 4, 0x10, 65535, 0, 0)
    tcp += bytes(4 * options)
    total = 4 * ihl + len(tcp) + len(payload)
    head = struct.pack(">BBHHHBBH4s4s", 0x40 | ihl, 0, total, 1, frag, 64, 6, 0,
                       bytes(4), bytes(4))
    return head + bytes(4 * (ihl - 5)) + tcp + payload


def tcp6(payload, options=0, next_header=6):
    tcp = struct.pack(">HHIIBBHHH", 50000, 443, 1, 1, (5 + options) << 4, 0x10, 65535, 0, 0)
    tcp += bytes(4 * options) + payload
    return struct.pack(">IHBB16s16s", 0x60000000, len(tcp), next_header, 64,
                       bytes(16), bytes(16)) + tcp


def test_udp_reports_what_the_datagram_carries():
    for size in (0, 1, 20, 100, 1472, 1473, 9000):
        data = bytes(size)
        check(f"IPv4, {size} bytes", payload_length(udp4(HOME, PEER_LAN, data), False) == size)
        check(f"IPv6, {size} bytes", payload_length(udp6(HOME6, PEER6, data), False) == size)
    check("IPv4 options are not data",
          payload_length(udp4(HOME, PEER_LAN, bytes(64), ihl=8), False) == 64)
    check("an empty datagram is zero, not unreadable",
          payload_length(udp4(HOME, PEER_LAN, b""), False) == 0)


def test_tcp_reports_what_the_segment_carries():
    for size in (0, 1, 536, 1460):
        data = bytes(size)
        check(f"IPv4, {size} bytes", payload_length(tcp4(data), True) == size)
        check(f"IPv6, {size} bytes", payload_length(tcp6(data), True) == size)
        check(f"IPv4, {size} bytes behind TCP options",
              payload_length(tcp4(data, options=3), True) == size)
        check(f"IPv4, {size} bytes behind IP options",
              payload_length(tcp4(data, ihl=7), True) == size)
    check("a bare acknowledgement is zero, not unreadable", payload_length(tcp4(b""), True) == 0)
    check("IPv6 with TCP options", payload_length(tcp6(bytes(10), options=10), True) == 10)


def test_the_buffer_the_driver_hands_over_is_read_as_it_is():
    """pydivert's ``raw`` is a memoryview; a copy per packet would be an allocation
    on the capture thread."""
    check("UDP", payload_length(memoryview(bytearray(udp4(HOME, PEER_LAN, bytes(77)))), False) == 77)
    check("TCP", payload_length(memoryview(bytearray(tcp4(bytes(77)))), True) == 77)


def test_a_fragment_has_no_size_of_its_own():
    """The first fragment carries a UDP header whose length is the WHOLE datagram's,
    so reading it would report 9000 bytes for a packet carrying 1472."""
    first = udp4(HOME, PEER_LAN, bytes(1472), frag=MORE_FRAGMENTS, udp_length=9008)
    check("the first fragment", payload_length(first, False) == -1)
    check("the first fragment, even when its length field fits",
          payload_length(udp4(HOME, PEER_LAN, bytes(100), frag=MORE_FRAGMENTS), False) == -1)
    check("a later fragment", payload_length(udp4(HOME, PEER_LAN, bytes(100), frag=185), False) == -1)
    check("the last fragment (offset in the low byte only)",
          payload_length(udp4(HOME, PEER_LAN, bytes(100), frag=1), False) == -1)
    check("a TCP fragment", payload_length(tcp4(bytes(100), frag=MORE_FRAGMENTS), True) == -1)
    check("'do not fragment' is not a fragment",
          payload_length(udp4(HOME, PEER_LAN, bytes(100), frag=0x4000), False) == 100)


def test_what_cannot_be_read_says_so():
    udp = udp4(HOME, PEER_LAN, bytes(40))
    tcp = tcp4(bytes(40))
    check("asked as TCP, it is UDP", payload_length(udp, True) == -1)
    check("asked as UDP, it is TCP", payload_length(tcp, False) == -1)
    check("ICMP", payload_length(udp4(HOME, PEER_LAN, bytes(40), proto=1), False) == -1)
    check("IPv6 behind an extension header",
          payload_length(udp6(HOME6, PEER6, bytes(40), next_header=0), False) == -1)
    check("IPv6 TCP behind an extension header",
          payload_length(tcp6(bytes(40), next_header=43), True) == -1)
    check("neither IPv4 nor IPv6", payload_length(bytes([0x50]) + udp[1:], False) == -1)
    check("all zeros (what --simulate sends)", payload_length(bytes(200), False) == -1)
    check("empty", payload_length(b"", False) == -1)
    check("an IPv4 header length below the minimum",
          payload_length(bytes([0x44]) + udp[1:], False) == -1)
    for cut in range(MIN_PACKET):
        check(f"cut to {cut} bytes", payload_length(udp[:cut], False) == -1)


def test_a_length_that_does_not_fit_is_not_believed():
    check("a UDP length past the end of the packet",
          payload_length(udp4(HOME, PEER_LAN, bytes(10), udp_length=19), False) == -1)
    check("a UDP length below its own header",
          payload_length(udp4(HOME, PEER_LAN, bytes(10), udp_length=7), False) == -1)
    check("a UDP length shorter than the packet is the datagram's own",
          payload_length(udp4(HOME, PEER_LAN, bytes(10), udp_length=12), False) == 4)
    check("a TCP data offset past the end of the packet",
          payload_length(tcp4(bytes(4), offset=15), True) == -1)
    check("a TCP data offset below the minimum", payload_length(tcp4(bytes(4), offset=4), True) == -1)
    check("a TCP header cut short", payload_length(tcp4(b"")[:39], True) == -1)
    check("IP options that leave no room for the UDP header",
          payload_length(bytes([0x4F]) + udp4(HOME, PEER_LAN, b"")[1:], False) == -1)


@settings(max_examples=400, deadline=None)
@given(st.binary(max_size=120), st.booleans())
def test_arbitrary_bytes_never_raise_and_never_exceed_the_packet(raw, is_tcp):
    answer = payload_length(raw, is_tcp)
    assert -1 <= answer <= len(raw), (answer, len(raw))


@settings(max_examples=300, deadline=None)
@given(st.binary(min_size=1, max_size=80), st.integers(0, 59), st.integers(0, 255),
       st.booleans())
def test_a_damaged_real_packet_never_raises_either(data, index, value, is_tcp):
    """Random bytes rarely look like an IP header, so the branches past the version
    test are reached by damaging a packet that does."""
    raw = bytearray(tcp4(data) if is_tcp else udp4(HOME, PEER_LAN, data))
    raw[index % len(raw)] = value
    answer = payload_length(bytes(raw), is_tcp)
    assert -1 <= answer <= len(raw), (answer, len(raw))
