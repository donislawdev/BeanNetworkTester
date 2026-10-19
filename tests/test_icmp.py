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

from beantester import crashlog, icmp
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

    def echo4(self, address, timeout_ms):
        self.calls.append(("v4", str(address), timeout_ms))
        if self.fail:
            raise self.fail
        return 1, 0, V4_REPLY_HEAD + PAYLOAD, V4_REPLY_BASE

    def echo6(self, address, timeout_ms):
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
    lib = FakeIphlpapi()
    system = icmp._System(lib)
    system.echo4(ipaddress.IPv4Address("192.0.2.10"), 4000)
    system.echo6(ipaddress.IPv6Address("2001:db8::1"), 1000)
    check("each request opened and closed its own handle", lib.closed == [42, 42])
    handle, event, apc, dest, size, reply_size, timeout = lib.sent[0]
    check("synchronous: no event, no callback", event is None and apc is None)
    check("the address in network order, 32 bytes, the wait", (
        dest == struct.unpack("<I", ipaddress.IPv4Address("192.0.2.10").packed)[0]
        and size == 32 and reply_size == icmp.REPLY_BYTES and timeout == 4000), f"({lib.sent})")
    raising = FakeIphlpapi(raises=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        icmp._System(raising).echo4(ipaddress.IPv4Address("192.0.2.10"), 1000)
    check("closed when the request raised too", raising.closed == [42])
    nothing = FakeIphlpapi(handle=None)
    with pytest.raises(OSError):
        icmp._System(nothing).echo4(ipaddress.IPv4Address("192.0.2.10"), 1000)
    check("no handle, nothing to close", nothing.closed == [] and nothing.sent == [])


def test_off_windows_there_is_no_binding():
    if sys.platform.startswith("win"):
        check("the binding loads here", icmp._iphlpapi() is not None)
    else:
        check("off Windows: None", icmp._iphlpapi() is None)
        check("and unsupported", not icmp.supported())


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
