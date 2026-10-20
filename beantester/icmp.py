"""ICMP echo through Windows' own ICMP helper - the Tools tab's Ping.

The one place in the package that SENDS something of its own: an echo request to
the address the person typed, from the moment they press Start until they press
Stop (``nettools/ping.py`` decides when; this module sends one). It goes through
``IcmpSendEcho2`` / ``Icmp6SendEcho2`` (Iphlpapi.dll, Microsoft Learn), the calls
``ping.exe`` makes - no raw socket, no process. ``tests/test_no_telemetry.py`` names
this file as the one place either may be called (``WIRE_ALLOWED``).

MEASURED 2026-10-19 on this project's machine (Windows 11, 64-bit Python; replies
from loopback, a Linux peer in WSL and an address nobody holds), and the reason for
each rule below:

* The synchronous call (no event, no callback) fills the reply buffer with the
  NATIVE ``ICMP_ECHO_REPLY``: its ``Data`` pointer is 8 bytes at offset 16 and points
  INTO the buffer, and the TTL is at offset 24 (128 from loopback, 64 from Linux).
  Learn also documents ``ICMP_ECHO_REPLY32`` "on a 64-bit platform" - that one is
  what ``IcmpParseReplies`` returns, and reading this buffer with it gives a TTL of
  123 that is a byte of the pointer.
* ``ICMPV6_ECHO_REPLY``: the address (``IPV6_ADDRESS_EX``) is packed in 26 bytes,
  ``Status`` sits at 28, ``RoundTripTime`` at 32 and the echoed data from 36. A reply
  carries no hop limit, so IPv6 rows have no TTL.
* No reply: the call answers 0, and both ``GetLastError`` and the buffer's
  ``Status`` say 11010 (timed out). With no route at all (IPv6 here) it answers at
  once with 1231 and leaves the buffer empty - so the status is the buffer's, or
  the call's when the buffer has none.
* 🔴 Windows waits in steps of half a second: a timeout is rounded DOWN to a
  multiple of 500 ms, at least 500 (300 and 999 wait 500, 1200 waits 1000, 2750
  waits 2500), and the first call of a series may end earlier still. So the tool
  offers whole seconds only, which are kept exactly.
* No elevation is needed (v4 and v6 ran with a filtered token). A handle per call
  is cheap: 2500 create, send and close cycles took 1.2 s and left the process's
  handle count where it was.
* Through a session's impairments (narrow sessions to the WSL peer): 100 ms of
  latency made the round trip 201-203 ms with the two-way filter and 100-102 with
  the outbound one; loopback behaves the same; a process target never covers a
  ping (no port); ``--corrupt 100`` brought 9 of 10 replies back with different
  data and ``Status`` 0 - hence ``Echo.changed``.

MEASURED 2026-10-20 (the same peer, ``internal_tools`` probes ``2026-10-20-ping2``):

* Any size of data from 0 to 65501 bytes goes out and comes back whole; 65535 gets
  no reply (the IP packet would pass 64 KB). The tool offers up to ping.exe's 65500.
* On the wire a request is its data plus 28 bytes (IPv4 and ICMP headers):
  ``--max-size 1400`` let 1372 bytes of data through and lost 1373 and 4000.
* ``--dup 100`` never shows: the call answers 1 for each request although the peer
  answered both copies (30 packets for 10 pings). Windows hands over the first
  reply and drops the others, so a ping cannot show duplication.
"""
import ctypes
import ipaddress
import struct
import sys
from typing import NamedTuple

from . import crashlog

# What a request carries: ping.exe's 32 bytes, so a capture shows the same thing; a
# request of another size repeats them (``payload``), as ping.exe does.
PAYLOAD = b"abcdefghijklmnopqrstuvwabcdefghi"
SIZE = len(PAYLOAD)
# Room beside the echoed data for the reply structure, an ICMP error's 8 bytes and,
# for IPv6, an IO_STATUS_BLOCK (Learn's minimum) - with plenty to spare.
REPLY_ROOM = 512

# IP_STATUS (Learn, ICMP_ECHO_REPLY) and the call's own errors this tool names.
IP_SUCCESS = 0
IP_DEST_NET_UNREACHABLE = 11002
IP_DEST_HOST_UNREACHABLE = 11003
IP_PACKET_TOO_BIG = 11009
IP_REQ_TIMED_OUT = 11010
IP_TTL_EXPIRED_TRANSIT = 11013
IP_GENERAL_FAILURE = 11050
ERROR_NETWORK_UNREACHABLE = 1231
ERROR_HOST_UNREACHABLE = 1232
AF_INET6 = 23                   # winsock2.h; not socket.AF_INET6: this module imports no socket

# Where the measured layouts keep what is read (see the module's docstring).
_V4_HEAD = struct.Struct("<IIIHH")      # Address, Status, RoundTripTime, DataSize, Reserved
_V4_DATA_POINTER = 16
_V4_TTL = 24
_V6_ADDRESS = slice(6, 22)
_V6_STATUS_RTT = struct.Struct("<II")
_V6_STATUS = 28
_V6_DATA = 36


class Echo(NamedTuple):
    """What one echo request came to."""
    status: int                 # 0 = a reply; else an IP_STATUS or the call's error code
    rtt_ms: int | None = None   # whole milliseconds, as Windows counts; None without a reply
    ttl: int | None = None      # IPv4 replies only
    reply_from: str = ""        # who answered - a router may answer for the address
    changed: bool = False       # the reply's data are not what was sent


class _SockaddrIn6(ctypes.Structure):
    _fields_ = [("sin6_family", ctypes.c_ushort), ("sin6_port", ctypes.c_ushort),
                ("sin6_flowinfo", ctypes.c_uint32), ("sin6_addr", ctypes.c_ubyte * 16),
                ("sin6_scope_id", ctypes.c_uint32)]


def payload(size=SIZE):
    """The data of a request of ``size`` bytes: ping.exe's pattern, repeated."""
    return (PAYLOAD * (size // len(PAYLOAD) + 1))[:size]


def reply_bytes(size):
    """The reply buffer for a request of ``size`` bytes: the data comes back in it."""
    return REPLY_ROOM + size


# -- reading a reply (pure: the tests feed it bytes laid out as measured) ------------ #
def parse_v4(raw, base, count, error, sent=PAYLOAD):
    """The Echo in an IPv4 reply buffer at address ``base``; ``count`` replies, or 0
    and ``error`` (GetLastError)."""
    address, status, rtt, size, _reserved = _V4_HEAD.unpack_from(raw, 0)
    if not count:
        return Echo(status or error)
    pointer = struct.unpack_from("<Q", raw, _V4_DATA_POINTER)[0]
    start = pointer - base
    data = raw[start:start + size] if 0 <= start <= len(raw) - size else None
    return Echo(status, rtt if status == IP_SUCCESS else None,
                raw[_V4_TTL] if status == IP_SUCCESS else None,
                str(ipaddress.IPv4Address(struct.pack("<I", address))),
                status == IP_SUCCESS and data is not None and data != sent)


def parse_v6(raw, count, error, sent=PAYLOAD):
    """The Echo in an IPv6 reply buffer; ``count`` replies, or 0 and ``error``."""
    status, rtt = _V6_STATUS_RTT.unpack_from(raw, _V6_STATUS)
    if not count:
        return Echo(status or error)
    data = raw[_V6_DATA:_V6_DATA + len(sent)]
    return Echo(status, rtt if status == IP_SUCCESS else None, None,
                str(ipaddress.IPv6Address(bytes(raw[_V6_ADDRESS]))),
                status == IP_SUCCESS and data != sent)


# -- the binding --------------------------------------------------------------------- #
def _iphlpapi():
    """iphlpapi with the prototypes of the calls made here; None off Windows."""
    if not sys.platform.startswith("win"):
        return None
    # use_last_error: the error of a call that answered 0 is the only word on why.
    return _declared(ctypes.WinDLL("iphlpapi.dll",  # pragma: no cover - Windows only
                                   use_last_error=True))


def _declared(lib):
    """``lib`` with the prototypes of the calls made here (Microsoft Learn)."""
    for name in ("IcmpCreateFile", "Icmp6CreateFile"):
        getattr(lib, name).argtypes = []
        getattr(lib, name).restype = ctypes.c_void_p
    lib.IcmpCloseHandle.argtypes = [ctypes.c_void_p]
    lib.IcmpCloseHandle.restype = ctypes.c_int
    lib.IcmpSendEcho2.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                  ctypes.c_uint16, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_uint32, ctypes.c_uint32]
    lib.IcmpSendEcho2.restype = ctypes.c_uint32
    lib.Icmp6SendEcho2.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_void_p, ctypes.c_uint16, ctypes.c_void_p,
                                   ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
    lib.Icmp6SendEcho2.restype = ctypes.c_uint32
    return lib


def supported():
    return sys.platform.startswith("win")


_INVALID_HANDLE = ctypes.c_void_p(-1).value


class _System:
    """What an echo asks of Windows. Injectable, so it all runs in tests anywhere.

    A handle per request, closed before the method returns: nothing is left open
    between two pings, so stopping - or closing the program while a request waits -
    has no handle to close in flight.
    """

    def __init__(self, iphlpapi=None, last_error=None):
        self.iphlpapi = iphlpapi if iphlpapi is not None else _iphlpapi()
        # get_last_error exists on Windows only; elsewhere a fake brings its own.
        self.last_error = last_error or getattr(ctypes, "get_last_error", lambda: 0)

    def _open(self, create):
        handle = create()
        if not handle or handle == _INVALID_HANDLE:
            raise OSError(self.last_error(), "no ICMP handle")
        return handle

    @staticmethod
    def _buffers(sent):
        """The request's data and the reply buffer for it. The data buffer keeps a
        byte even for an empty request (0 bytes went out and back, measured)."""
        size = reply_bytes(len(sent))
        return (ctypes.create_string_buffer(sent, max(1, len(sent))),
                ctypes.create_string_buffer(size), size)

    def echo4(self, address, timeout_ms, sent=PAYLOAD):
        """One IPv4 request carrying ``sent``: ``(count, error, raw, base)``."""
        lib = self.iphlpapi
        handle = self._open(lib.IcmpCreateFile)
        try:
            data, reply, size = self._buffers(sent)
            count = lib.IcmpSendEcho2(handle, None, None, None,
                                      struct.unpack("<I", address.packed)[0], data,
                                      len(sent), None, reply, size, timeout_ms)
            error = self.last_error() if not count else 0
            return int(count), int(error), reply.raw, ctypes.addressof(reply)
        finally:
            lib.IcmpCloseHandle(handle)

    def echo6(self, address, timeout_ms, sent=PAYLOAD):
        """One IPv6 request carrying ``sent``: ``(count, error, raw)``."""
        lib = self.iphlpapi
        handle = self._open(lib.Icmp6CreateFile)
        try:
            data, reply, size = self._buffers(sent)
            source = _SockaddrIn6(sin6_family=AF_INET6)     # any address of this machine
            target = _SockaddrIn6(sin6_family=AF_INET6,
                                  sin6_scope_id=int(address.scope_id or 0))
            ctypes.memmove(target.sin6_addr, address.packed, 16)
            count = lib.Icmp6SendEcho2(handle, None, None, None, ctypes.byref(source),
                                       ctypes.byref(target), data, len(sent), None,
                                       reply, size, timeout_ms)
            error = self.last_error() if not count else 0
            return int(count), int(error), reply.raw
        finally:
            lib.IcmpCloseHandle(handle)


def echo(address, timeout_ms, system=None, size=SIZE):
    """Send ONE echo request of ``size`` bytes of data to ``address`` (an ``ipaddress``
    object; an IPv6 one may carry a numeric scope) and wait up to ``timeout_ms``. On a
    worker; never raises - a failure of the call itself comes back as an Echo with its
    error code, -1 when there is none."""
    try:
        system = system or _System()
        sent = payload(size)
        if address.version == 4:
            count, error, raw, base = system.echo4(address, timeout_ms, sent)
            return parse_v4(raw, base, count, error, sent)
        count, error, raw = system.echo6(address, timeout_ms, sent)
        return parse_v6(raw, count, error, sent)
    except Exception as exc:
        crashlog.note(exc, "icmp")
        return Echo(getattr(exc, "errno", None) or -1)
