"""ICMP echo on Linux - one request through the system's ping socket, or a raw one.

What ``icmp.py`` asks of Linux for the Tools tab's Ping (Windows has its ICMP helper
there): send ONE echo request, wait for its answer, and say what came back in the
kernel's own terms (``Answer``). ``icmp.py`` puts that into the words both systems'
answers are said in. ``tests/test_no_telemetry.py`` names this file as the one
place on Linux that opens an ICMP socket.

Two kinds of socket, tried in this order - the order the system's own ``ping``
(iputils) tries them:

* ``SOCK_DGRAM`` with ``IPPROTO_ICMP`` - the "ping socket": no rights needed, but
  only for a group the setting ``net.ipv4.ping_group_range`` names (it covers
  ICMPv6 too). The kernel picks the identifier (the socket's port) and hands this
  socket only the replies carrying it.
* ``SOCK_RAW`` - root or CAP_NET_RAW. It sees every ICMP message this host
  receives, so a reply is taken only with this request's identifier and number.

MEASURED 2026-10-21 (``internal_tools`` probes ``2026-10-21-linux-ping``: WSL Ubuntu
24.04.5 and a VM with Ubuntu 26.04.1, replies and every error from three network
namespaces - client, router, far end), and the reason for each rule below:

* Ubuntu 24.04 ships ``ping_group_range = 1 0``: the ping socket is refused to
  EVERYONE, root included (EACCES), and its ``ping`` gets CAP_NET_RAW from a file
  capability instead. 26.04 opens the range through systemd's ``50-default.conf``.
  A new network namespace starts at ``1 0`` again. Hence the raw socket after it:
  without it Ping would not work under sudo on 24.04.
* A ping socket's reply has no IP header (ICMP header, then the data); a raw IPv4
  socket's has one (IPv6: none). The TTL comes as ancillary data (``IP_RECVTTL``).
* An ICMP error for the request is queued on the socket (``IP_RECVERR``): its type,
  code and sender (``sock_extended_err`` and ``SO_EE_OFFENDER``), and the request
  itself, which tells whose it is. A raw socket gets the same entry, and the error
  datagram as well. The queued error also makes the waiting ``recvmsg`` fail at
  once, which is what wakes the wait (no ``select``); the queue is then read without
  waiting (``_read_errors``).
  TTL 1: type 11 code 0 from the router. No route at the router: type 3 code 0
  (IPv6 type 1 code 0). No route here: ``sendto`` fails at once, ENETUNREACH.
  Nobody at an address on the link: after about 3 s, type 3 code 1 (IPv6 type 1
  code 3) from THIS machine's address. A smaller MTU on the way: type 3 code 4
  (IPv6 type 2) for the first big request - the kernel then keeps the path's MTU and
  splits the next one, which comes back.
* The round trip is taken from the kernel's receive time (``SO_TIMESTAMPNS``): the
  time Python reads after waking was up to 10 ms later on the VM. Windows measures
  its own round trips too.
* Through a real session (eBPF, narrow, in a namespace): 100 ms of latency made the
  round trip about 210 ms with the two-way filter and about 103 with the outbound
  one; ``--corrupt 100`` brought the reply back with other data; with ``--dup 100``
  the socket of the request saw its first reply - what Windows shows too.
* Sizes: 0 to 65507 bytes of data come back whole over IPv4; 65508 is refused by
  ``sendto`` (EMSGSIZE).

A socket per request, closed before ``echo`` returns: nothing is left open between
two pings, and a late reply or a copy reaches a closed socket, never the next row.
Python names only some of the options below, and 3.12 none of the first three - so
they are the kernel's numbers (``include/uapi``), which never change.
"""
import errno
import ipaddress
import platform
import random
import socket
import struct
import time
from typing import Any, NamedTuple, Protocol, cast

DGRAM, RAW = "dgram", "raw"
KINDS = (DGRAM, RAW)

SOL_SOCKET = 1                  # Linux's (Windows numbers it 0xffff)
SOL_IP, SOL_IPV6 = 0, 41
IPPROTO_ICMP, IPPROTO_ICMPV6 = 1, 58
IP_TTL = 2
IP_RECVERR = 11
IP_RECVTTL = 12
IPV6_RECVERR = 25
SO_TIMESTAMPNS = 35             # asm-generic: see STAMPED
MSG_DONTWAIT = 0x40
MSG_ERRQUEUE = 0x2000
SO_EE_ORIGIN_ICMP, SO_EE_ORIGIN_ICMP6 = 2, 3
LINUX_AF_INET, LINUX_AF_INET6 = 2, 10           # sa_family in an offender's address
# The errors ``icmp.py`` has words for, by Linux's numbers.
ENETUNREACH, EHOSTUNREACH, EMSGSIZE = 101, 113, 90

ECHO_REQUEST = {4: 8, 6: 128}
ECHO_REPLY = {4: 0, 6: 129}
SEQ = 1                         # one request per socket: the number only tells it apart
# SO_TIMESTAMPNS is 35 on the machines that take the kernel's generic numbers; a few
# (alpha, mips, parisc, sparc) number their options otherwise, and there the option
# is not asked for - the round trip is then the time read after waking.
STAMPED = frozenset({"x86_64", "amd64", "aarch64", "arm64", "i386", "i686", "armv7l",
                     "armv8l", "riscv64", "ppc64le", "ppc64", "s390x"})
# Room for the ancillary data (a timestamp, the TTL, an extended error and its
# sender) and, around a reply's data, an IPv4 header with every option.
ANCILLARY = 256
AROUND_DATA = 128

_HEAD = struct.Struct("!BBHHH")             # type, code, checksum, identifier, number
_EXTENDED_ERR = struct.Struct("=IBBBBII")   # errno, origin, type, code, pad, info, data
_FAMILY = struct.Struct("=H")
_TTL = struct.Struct("=i")
_TIMESPEC = {16: struct.Struct("=qq"), 8: struct.Struct("=ii")}   # 64- and 32-bit longs


class Answer(NamedTuple):
    """What one request came to, in the kernel's terms. An error of 0, no reply and no
    ICMP error: nothing came back within the wait."""
    error: int = 0                  # errno: the request could not be made or sent
    replied: bool = False           # this request's echo reply came
    rtt_ns: int | None = None
    ttl: int | None = None          # IPv4 replies
    source: str = ""                # who answered: the address, or who sent the error
    data: bytes = b""               # the reply's data
    icmp: tuple[int, int] | None = None     # an ICMP error's (type, code)


class _Socket(Protocol):
    """The part of a socket used here (a test brings its own)."""
    def setsockopt(self, level: int, option: int, value: int, /) -> None: ...
    def settimeout(self, value: float | None, /) -> None: ...
    def sendto(self, data: bytes, address: Any, /) -> int: ...
    def recvmsg(self, size: int, ancillary: int = ..., flags: int = ..., /) -> Any: ...
    def getsockname(self) -> Any: ...
    def close(self) -> None: ...


def _open(family, kind) -> _Socket:
    proto = IPPROTO_ICMPV6 if family == socket.AF_INET6 else IPPROTO_ICMP
    sort = socket.SOCK_DGRAM if kind == DGRAM else socket.SOCK_RAW
    return cast(_Socket, socket.socket(family, sort, proto))


def kind(opener=_open):
    """The socket this process may ping through now - ``DGRAM``, ``RAW`` - or None.
    Asked when the Tools tab asks whether Ping is here: one socket opened and closed."""
    for each in KINDS:
        try:
            opener(socket.AF_INET, each).close()
        except OSError:
            continue
        return each
    return None


def zone_index(name):
    """The number of the interface ``name`` (``eth0``) - an IPv6 zone on the wire - or
    None when no interface has that name."""
    try:
        return socket.if_nametoindex(name)
    except (OSError, TypeError):
        return None


def errno_name(number):
    """``EPERM`` for 1: how Linux names an error (the number, when it has no name)."""
    return errno.errorcode.get(number, str(number))


def checksum(data):
    """The Internet checksum (RFC 1071) - a raw IPv4 socket's request carries its own;
    the kernel fills it in for a ping socket and for ICMPv6."""
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def request(version, kind, ident, sent):
    """The ICMP echo request carrying ``sent``."""
    head = _HEAD.pack(ECHO_REQUEST[version], 0, 0, ident, SEQ)
    if version == 4 and kind == RAW:
        head = _HEAD.pack(ECHO_REQUEST[version], 0, checksum(head + sent), ident, SEQ)
    return head + sent


# -- reading what came (pure: the tests feed it the bytes measured on the VM) ------ #
def parse_reply(raw, version, kind):
    """``(type, identifier, number, data)`` of a datagram, or None when it is too short
    to be ICMP. A raw IPv4 socket's datagram starts with the IP header."""
    start = 0
    if version == 4 and kind == RAW:
        if not raw or raw[0] >> 4 != 4:
            return None
        start = (raw[0] & 0x0F) * 4
    if len(raw) < start + _HEAD.size:
        return None
    kind_of, _code, _sum, ident, seq = _HEAD.unpack_from(raw, start)
    return kind_of, ident, seq, bytes(raw[start + _HEAD.size:])


def received(ancillary):
    """``(ttl, kernel receive time in ns)`` from a reply's ancillary data; None where
    it had none."""
    ttl = stamp = None
    for level, kind, blob in ancillary:
        if level == SOL_SOCKET and kind == SO_TIMESTAMPNS and len(blob) in _TIMESPEC:
            seconds, nanoseconds = _TIMESPEC[len(blob)].unpack_from(blob)
            stamp = seconds * 1_000_000_000 + nanoseconds
        elif level == SOL_IP and kind == IP_TTL and len(blob) >= _TTL.size:
            ttl = _TTL.unpack_from(blob)[0]
    return ttl, stamp


def _sender(raw):
    """The address in a ``sockaddr_in`` / ``sockaddr_in6`` as Linux lays them out."""
    if len(raw) < _FAMILY.size:
        return ""
    family = _FAMILY.unpack_from(raw)[0]
    if family == LINUX_AF_INET and len(raw) >= 8:
        return str(ipaddress.IPv4Address(bytes(raw[4:8])))
    if family == LINUX_AF_INET6 and len(raw) >= 24:
        return str(ipaddress.IPv6Address(bytes(raw[8:24])))
    return ""


def queued_error(ancillary):
    """The Answer an entry of the error queue says, from its ancillary data; None when
    it carries no extended error."""
    for level, kind, blob in ancillary:
        if (level, kind) in ((SOL_IP, IP_RECVERR), (SOL_IPV6, IPV6_RECVERR)) \
                and len(blob) >= _EXTENDED_ERR.size:
            number, origin, icmp_type, icmp_code, _pad, _info, _data = \
                _EXTENDED_ERR.unpack_from(blob)
            sender = _sender(blob[_EXTENDED_ERR.size:])
            if origin in (SO_EE_ORIGIN_ICMP, SO_EE_ORIGIN_ICMP6):
                return Answer(source=sender, icmp=(icmp_type, icmp_code))
            return Answer(number or -1, source=sender)
    return None


def _is_this_request(raw, ident):
    """Whether the request an error queue entry carries is the one sent."""
    if len(raw) < _HEAD.size:
        return False
    _kind, _code, _sum, got_ident, seq = _HEAD.unpack_from(raw)
    return got_ident == ident and seq == SEQ


def _host(source):
    """The address a datagram came from, without the zone Python appends to a
    link-local one (``icmp.py`` compares it with the address pinged)."""
    return str(source[0]).split("%")[0] if source else ""


def _from_target(source, address):
    """Whether a reply came from the address pinged (the zone aside). An echo reply
    always does - a router answers through an ICMP error, which the error queue
    carries - so one with this request's identifier from another host is another
    program's: a raw socket sees every reply this host gets, and a ping socket is
    handed replies by their identifier alone, which a raw pinger may share."""
    try:
        return ipaddress.ip_address(_host(source)) == \
            ipaddress.ip_address(str(address).split("%")[0])
    except ValueError:
        return False


# -- one request ------------------------------------------------------------------- #
def _target(address):
    if address.version == 4:
        return str(address), 0
    zone = address.scope_id or ""
    scope = int(zone) if zone.isdigit() else (zone_index(zone) or 0)
    return str(address).split("%")[0], 0, 0, scope


def echo(address, timeout_ms, sent, opener=_open, kinds=KINDS, ident=None, clock=time,
         stamped=None):
    """Send ONE echo request carrying ``sent`` to ``address`` (an ``ipaddress`` object)
    and wait up to ``timeout_ms`` for its answer. On a worker. What the kernel says -
    a refused socket, a failed send - comes back as ``Answer.error``, never raised."""
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    sock, used, refused = None, None, 0
    for each in kinds:
        try:
            sock, used = opener(family, each), each
            break
        except OSError as exc:
            refused = refused or exc.errno or -1
    if sock is None:
        return Answer(refused or -1)
    try:
        stamped = (platform.machine().lower() in STAMPED) if stamped is None else stamped
        return _exchange(sock, used, address, timeout_ms, sent, ident, clock, stamped)
    finally:
        sock.close()


def _ask(sock, version, stamped):
    """The ancillary data asked for: the error queue, the TTL, the receive time."""
    if version == 6:
        sock.setsockopt(SOL_IPV6, IPV6_RECVERR, 1)
    else:
        sock.setsockopt(SOL_IP, IP_RECVERR, 1)
        sock.setsockopt(SOL_IP, IP_RECVTTL, 1)
    if not stamped:
        return False
    try:
        sock.setsockopt(SOL_SOCKET, SO_TIMESTAMPNS, 1)
    except OSError:
        return False
    return True


def _exchange(sock, kind, address, timeout_ms, sent, ident, clock, stamped):
    version = address.version
    stamped = _ask(sock, version, stamped)
    if kind == RAW:
        ident = random.getrandbits(16) if ident is None else ident
    wire_ident = ident if kind == RAW else 0        # the kernel numbers a ping socket's
    wait_ns = timeout_ms * 1_000_000
    sent_wall, sent_at = clock.time_ns(), clock.monotonic_ns()
    try:
        sock.sendto(request(version, kind, wire_ident, sent), _target(address))
    except OSError as exc:
        return Answer(exc.errno or -1)
    if kind == DGRAM:
        ident = sock.getsockname()[1]
    while True:
        left = sent_at + wait_ns - clock.monotonic_ns()
        if left <= 0:
            return Answer()
        sock.settimeout(left / 1e9)
        try:
            raw, ancillary, _flags, source = sock.recvmsg(len(sent) + AROUND_DATA, ANCILLARY)
        except TimeoutError:
            return Answer()
        except OSError as exc:
            # An error was queued for this socket (IP_RECVERR) - this request's, or on
            # a raw socket another program's. Its words are in the error queue.
            mine, seen = _read_errors(sock, ident)
            if mine is not None:
                return mine
            if not seen:
                return Answer(exc.errno or -1)
            continue
        got = parse_reply(raw, version, kind)
        if got is None or got[:3] != (ECHO_REPLY[version], ident, SEQ):
            continue                # another program's ICMP, or this request going out
        if not _from_target(source, address):
            continue                # the same identifier and number, from another host
        ttl, stamp = received(ancillary)
        rtt = stamp - sent_wall if stamped and stamp is not None else None
        if rtt is None or not 0 <= rtt <= wait_ns:
            rtt = max(0, clock.monotonic_ns() - sent_at)
        return Answer(replied=True, rtt_ns=rtt, ttl=ttl if version == 4 else None,
                      source=_host(source), data=got[3])


def _read_errors(sock, ident):
    """Every entry waiting in the error queue: ``(this request's Answer or None,
    whether there was any)``.

    Read with the socket's timeout at 0: on a socket with a timeout Python waits for
    it to be readable BEFORE the call, ``MSG_DONTWAIT`` or not, and an emptied queue
    then held the answer until the wait ran out - measured, an error that came after
    5 ms answered after the whole 2 s."""
    mine, seen = None, False
    sock.settimeout(0)
    while True:
        try:
            raw, ancillary, _flags, _source = sock.recvmsg(
                AROUND_DATA + ANCILLARY, ANCILLARY, MSG_ERRQUEUE | MSG_DONTWAIT)
        except OSError:
            return mine, seen       # the queue is empty (EAGAIN)
        seen = True
        if mine is None and _is_this_request(raw, ident):
            mine = queued_error(ancillary)
