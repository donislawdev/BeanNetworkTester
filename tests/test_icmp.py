"""``beantester/icmp.py``: one ICMP echo request, and reading what came back.

The reply buffers below are laid out as MEASURED on 2026-10-19 (64-bit Python, Windows
11): the first 40 bytes are copied from that run, so a reader that takes Learn's other
layout (``ICMP_ECHO_REPLY32``, the TTL at 20) reads the wrong byte here, on every
runner. The binding is a fake that answers as programmed; the live test at the bottom
pings this computer's own loopback address - the measurement's control, kept.
"""
import ctypes
import ipaddress
import struct
import sys

import pytest

from beantester import crashlog, icmp, icmpsock
from fakes import check

PAYLOAD = icmp.PAYLOAD

# A reply from 127.0.0.1: Address, Status 0, RTT 0, DataSize 32, then the Data pointer
# (8 bytes), the options (TTL 128 at byte 24) and their pointer. Copied from M1.
V4_REPLY_HEAD = bytes.fromhex("7f000001000000000000000020000000d877d4ab7b010000"
                              "8000000000000000f877d4ab7b010000")
V4_REPLY_BASE = 0x17BABD477D8 - 40          # the data sat right after the 40 bytes
# No reply within the wait: Status 11010 in the buffer, nothing else (M1).
V4_TIMEOUT = bytes.fromhex("00000000022b0000") + bytes(32)
# IPv6, nobody at fe80::1: Status 11010 at 28 - the packed address is 26 bytes (M1b).
V6_TIMEOUT = bytes.fromhex("0000000000000000000000000000000000000000000000000000"
                           "0000022b00000000000000000000")
# IPv6, a reply from this machine's own link-local address: address at 6, data at 36.
V6_REPLY = bytes.fromhex("000000000000fe80000000000000df2bcf0dad7daee000000000"
                         "00000000000000000000") + PAYLOAD
assert len(V6_REPLY) == 36 + len(PAYLOAD)


def test_an_ipv4_reply_is_read_with_the_native_layout():
    raw = V4_REPLY_HEAD + PAYLOAD
    echo = icmp.parse_v4(raw, V4_REPLY_BASE, 1, 0)
    check("the measured reply reads as a reply", echo == icmp.Echo(0, 0, 128, "127.0.0.1", False),
          f"({echo})")
    # The canary: Learn's 32-bit layout puts the TTL at 20, a byte of the pointer.
    check("the other layout would have read a pointer byte", raw[20] != 128 and raw[24] == 128)


def test_reply_data_that_came_back_different_is_said():
    raw = V4_REPLY_HEAD + b"x" * len(PAYLOAD)
    check("changed data", icmp.parse_v4(raw, V4_REPLY_BASE, 1, 0).changed)
    pointer_outside = V4_REPLY_HEAD + PAYLOAD
    echo = icmp.parse_v4(pointer_outside, V4_REPLY_BASE + 4096, 1, 0)
    check("a pointer outside the buffer is not read, and not called a change",
          echo.status == 0 and not echo.changed, f"({echo})")


def test_no_reply_takes_the_status_from_the_buffer_or_else_from_the_call():
    check("timed out (buffer)", icmp.parse_v4(V4_TIMEOUT, 0, 0, 11010) == icmp.Echo(11010))
    check("the call's error when the buffer has none",
          icmp.parse_v4(bytes(40), 0, 0, icmp.ERROR_NETWORK_UNREACHABLE)
          == icmp.Echo(icmp.ERROR_NETWORK_UNREACHABLE))
    check("IPv6: Status at 28", icmp.parse_v6(V6_TIMEOUT, 0, 0) == icmp.Echo(11010),
          f"({icmp.parse_v6(V6_TIMEOUT, 0, 0)})")
    check("IPv6 with no route: the call's error", icmp.parse_v6(bytes(40), 0, 1231)
          == icmp.Echo(1231))


def test_an_ipv6_reply_has_its_address_and_no_ttl():
    echo = icmp.parse_v6(V6_REPLY, 1, 0)
    check("reply", echo == icmp.Echo(0, 0, None, "fe80::df2b:cf0d:ad7d:aee0", False), f"({echo})")
    check("changed", icmp.parse_v6(V6_REPLY[:36] + b"y" * len(PAYLOAD), 1, 0).changed)


def test_a_router_answering_for_the_address_is_named():
    raw = bytearray(V4_REPLY_HEAD + PAYLOAD)
    struct.pack_into("<II", raw, 0, struct.unpack("<I", ipaddress.IPv4Address(
        "198.51.100.1").packed)[0], icmp.IP_TTL_EXPIRED_TRANSIT)
    echo = icmp.parse_v4(bytes(raw), V4_REPLY_BASE, 1, 0)
    check("TTL expired, from the router, no round trip", echo == icmp.Echo(
        icmp.IP_TTL_EXPIRED_TRANSIT, None, None, "198.51.100.1", False), f"({echo})")


class FakeSystem:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def echo4(self, address, timeout_ms, sent=PAYLOAD):
        self.calls.append(("v4", str(address), timeout_ms))
        if self.fail:
            raise self.fail
        return 1, 0, V4_REPLY_HEAD + PAYLOAD, V4_REPLY_BASE

    def echo6(self, address, timeout_ms, sent=PAYLOAD):
        self.calls.append(("v6", str(address), address.scope_id, timeout_ms))
        return 0, 0, V6_TIMEOUT


def test_echo_picks_the_family_and_never_raises(monkeypatch):
    noted = []
    monkeypatch.setattr(crashlog, "note", lambda exc, area: noted.append(area))
    system = FakeSystem()
    check("v4", icmp.echo(ipaddress.ip_address("192.0.2.10"), 4000, system).status == 0)
    check("v6 with its zone", icmp.echo(ipaddress.ip_address("fe80::1%12"), 1000, system)
          == icmp.Echo(11010))
    check("the wait and the zone reach the call", system.calls == [
        ("v4", "192.0.2.10", 4000), ("v6", "fe80::1%12", "12", 1000)], f"({system.calls})")
    failing = FakeSystem(OSError(87, "no ICMP handle"))
    check("a failing call is an Echo with its code", icmp.echo(
        ipaddress.ip_address("192.0.2.10"), 1000, failing) == icmp.Echo(87))
    check("and is recorded", noted == ["icmp"], f"({noted})")


class FakeIphlpapi:
    """The five calls, recording handles; IcmpSendEcho2 answers as programmed."""

    def __init__(self, handle=42, raises=None):
        self.handle, self.raises, self.closed, self.sent = handle, raises, [], []

    def IcmpCreateFile(self):
        return self.handle

    def Icmp6CreateFile(self):
        return self.handle

    def IcmpCloseHandle(self, handle):
        self.closed.append(handle)
        return 1

    def IcmpSendEcho2(self, handle, event, apc, context, dest, data, size, options, reply,
                      reply_size, timeout):
        self.sent.append((handle, event, apc, dest, size, reply_size, timeout))
        if self.raises:
            raise self.raises
        return 0

    def Icmp6SendEcho2(self, handle, event, apc, context, source, dest, data, size, options,
                       reply, reply_size, timeout):
        self.sent.append((handle, event, apc, size, reply_size, timeout))
        return 0


def test_a_handle_per_request_closed_whatever_the_request_did():
    # The error is stood in for too: ctypes has get_last_error on Windows only, and a
    # binding that called it here went red on the Linux runner.
    lib = FakeIphlpapi()
    system = icmp._System(lib, last_error=lambda: icmp.IP_REQ_TIMED_OUT)
    v4 = system.echo4(ipaddress.IPv4Address("192.0.2.10"), 4000)
    v6 = system.echo6(ipaddress.IPv6Address("2001:db8::1"), 1000)
    check("a request that answered 0 says the error Windows gave",
          v4[:2] == (0, icmp.IP_REQ_TIMED_OUT) and v6[:2] == (0, icmp.IP_REQ_TIMED_OUT),
          f"({v4[:2]}, {v6[:2]})")
    check("each request opened and closed its own handle", lib.closed == [42, 42])
    handle, event, apc, dest, size, reply_size, timeout = lib.sent[0]
    check("synchronous: no event, no callback", event is None and apc is None)
    check("the address in network order, 32 bytes, the wait", (
        dest == struct.unpack("<I", ipaddress.IPv4Address("192.0.2.10").packed)[0]
        and size == 32 and reply_size == icmp.reply_bytes(32) and timeout == 4000),
          f"({lib.sent})")
    raising = FakeIphlpapi(raises=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        icmp._System(raising).echo4(ipaddress.IPv4Address("192.0.2.10"), 1000)
    check("closed when the request raised too", raising.closed == [42])
    nothing = FakeIphlpapi(handle=None)
    with pytest.raises(OSError) as refused:
        icmp._System(nothing, last_error=lambda: 87).echo4(ipaddress.IPv4Address("192.0.2.10"),
                                                           1000)
    check("no handle: an OSError with the error", refused.value.errno == 87, f"({refused.value})")
    check("no handle, nothing to close", nothing.closed == [] and nothing.sent == [])


def test_a_ping_of_any_size_carries_ping_exes_pattern_and_compares_all_of_it():
    """The size the person typed: the data is ping.exe's 32 bytes repeated, the reply
    buffer grows with it, and a change anywhere in what came back - its last byte
    too - is a change."""
    check("0 bytes: nothing", icmp.payload(0) == b"")
    check("32: ping.exe's", icmp.payload(32) == PAYLOAD)
    check("70: the pattern again, cut", icmp.payload(70) == PAYLOAD * 2 + PAYLOAD[:6])
    check("the largest offered", len(icmp.payload(65500)) == 65500)
    sent = icmp.payload(1372)
    head = bytearray(V4_REPLY_HEAD)
    struct.pack_into("<H", head, 12, len(sent))         # DataSize
    check("a big reply that came back whole",
          not icmp.parse_v4(bytes(head) + sent, V4_REPLY_BASE, 1, 0, sent).changed)
    check("its last byte different",
          icmp.parse_v4(bytes(head) + sent[:-1] + b"#", V4_REPLY_BASE, 1, 0, sent).changed)
    check("IPv6 too", icmp.parse_v6(V6_REPLY[:36] + sent[:-1] + b"#", 1, 0, sent).changed)
    lib = FakeIphlpapi()
    system = icmp._System(lib, last_error=lambda: icmp.IP_REQ_TIMED_OUT)
    icmp.echo(ipaddress.ip_address("192.0.2.10"), 1000, system, size=1372)
    icmp.echo(ipaddress.ip_address("2001:db8::1"), 1000, system, size=0)
    (_h, _e, _a, _d, size4, reply4, _t), (_h6, _e6, _a6, size6, reply6, _t6) = lib.sent
    check("the size reaches the call, and the reply buffer has room for all of it",
          size4 == 1372 and reply4 == icmp.reply_bytes(1372) and reply4 >= 1372 + 40,
          f"({lib.sent})")
    check("an empty request is 0 bytes", size6 == 0 and reply6 == icmp.reply_bytes(0),
          f"({lib.sent})")


def test_off_windows_there_is_no_binding():
    if sys.platform.startswith("win"):
        check("the binding loads here", icmp._iphlpapi() is not None)
    else:
        check("off Windows: None", icmp._iphlpapi() is None)
        check("and Ping only where this process may open an ICMP socket",
              icmp.supported() is (icmpsock.kind() is not None))


@pytest.mark.parametrize("platform, sockets, expected", [
    ("win32", None, True), ("linux", icmpsock.DGRAM, True), ("linux", icmpsock.RAW, True),
    ("linux", None, False), ("darwin", icmpsock.DGRAM, False)])
def test_ping_is_here_on_windows_and_on_a_linux_that_lets_this_process_send(
        monkeypatch, platform, sockets, expected):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(icmpsock, "kind", lambda: sockets)
    check(f"{platform}, {sockets}", icmp.supported() is expected)


def answer(**kw):
    return icmpsock.Answer(**kw)


def test_linux_answers_are_said_in_the_words_windows_answers_are():
    """The table the rest of the tool reads (``nettools/ping.py``): a Linux answer
    gets the number Windows gives the same ICMP message, so the Result column, the
    totals and the report need no second vocabulary."""
    reply = answer(replied=True, rtt_ns=1_999_999, ttl=63, source="198.51.100.2", data=PAYLOAD)
    check("a reply: whole ms, as Windows counts them",
          icmp.from_answer(reply, PAYLOAD, 4) == icmp.Echo(0, 1, 63, "198.51.100.2", False))
    check("changed data", icmp.from_answer(reply._replace(data=b"x" * 32), PAYLOAD, 4).changed)
    check("an IPv6 row has no TTL, as on Windows",
          icmp.from_answer(reply._replace(ttl=64), PAYLOAD, 6).ttl is None)
    words = {(4, (3, 0)): icmp.IP_DEST_NET_UNREACHABLE, (4, (3, 1)): icmp.IP_DEST_HOST_UNREACHABLE,
             (4, (3, 4)): icmp.IP_PACKET_TOO_BIG, (4, (11, 0)): icmp.IP_TTL_EXPIRED_TRANSIT,
             (6, (1, 0)): icmp.IP_DEST_NET_UNREACHABLE, (6, (1, 3)): icmp.IP_DEST_HOST_UNREACHABLE,
             (6, (2, 0)): icmp.IP_PACKET_TOO_BIG, (6, (2, 9)): icmp.IP_PACKET_TOO_BIG,
             (6, (3, 0)): icmp.IP_TTL_EXPIRED_TRANSIT}
    for (version, message), status in words.items():
        echo = icmp.from_answer(answer(icmp=message, source="192.0.2.1"), PAYLOAD, version)
        check(f"IPv{version} ICMP {message}", echo == icmp.Echo(status, reply_from="192.0.2.1"),
              f"({echo})")
    other = icmp.from_answer(answer(icmp=(3, 13), source="192.0.2.1"), PAYLOAD, 4)
    check("one the numbers do not name: said, under a general failure",
          other == icmp.Echo(icmp.IP_GENERAL_FAILURE, reply_from="192.0.2.1", said="ICMP 3/13"),
          f"({other})")
    check("IPv6's says so", icmp.from_answer(answer(icmp=(1, 1)), PAYLOAD, 6).said == "ICMPv6 1/1")
    for number, status in ((101, icmp.IP_DEST_NET_UNREACHABLE),
                           (113, icmp.IP_DEST_HOST_UNREACHABLE), (90, icmp.IP_PACKET_TOO_BIG)):
        check(f"errno {number}", icmp.from_answer(answer(error=number), PAYLOAD, 4)
              == icmp.Echo(status))
    check("an errno without words: its name", icmp.from_answer(answer(error=1), PAYLOAD, 4)
          == icmp.Echo(icmp.IP_GENERAL_FAILURE, said="EPERM"))
    check("nothing: timed out", icmp.from_answer(answer(), PAYLOAD, 4)
          == icmp.Echo(icmp.IP_REQ_TIMED_OUT))


def test_on_linux_an_echo_goes_through_the_sockets_and_a_given_system_is_kept(monkeypatch):
    asked = []

    def send(address, timeout_ms, sent):
        asked.append((str(address), timeout_ms, len(sent)))
        return answer(replied=True, rtt_ns=5_000_000, ttl=64, source=str(address), data=sent)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(icmpsock, "echo", send)
    echo = icmp.echo(ipaddress.ip_address("192.0.2.10"), 1000, size=1372)
    check("Linux: the sockets, with the size asked", asked == [("192.0.2.10", 1000, 1372)]
          and echo == icmp.Echo(0, 5, 64, "192.0.2.10", False), f"({asked}, {echo})")
    lib = FakeIphlpapi()
    icmp.echo(ipaddress.ip_address("192.0.2.10"), 1000, icmp._System(
        lib, last_error=lambda: icmp.IP_REQ_TIMED_OUT))
    check("a Windows binding handed in is asked, whatever runs the test",
          len(lib.sent) == 1 and len(asked) == 1, f"({lib.sent})")


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only: iphlpapi")
def test_a_live_ping_of_this_computer_reads_a_real_reply():  # pragma: no cover - Windows only
    """M1's control: this computer's own loopback address answers with what was sent,
    TTL 128, in under a millisecond or so."""
    echo = icmp.echo(ipaddress.ip_address("127.0.0.1"), 1000)
    check("a reply from 127.0.0.1", echo.status == 0 and echo.reply_from == "127.0.0.1",
          f"({echo})")
    check("the data came back unchanged, with Windows' TTL", not echo.changed and echo.ttl == 128,
          f"({echo})")
    check("the pointer size this layout was measured on", ctypes.sizeof(ctypes.c_void_p) == 8)
