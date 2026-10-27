"""The kernel's own list of this machine's TCP sockets on Linux - sock_diag over netlink.

What ``ss`` reads, and what "Reset this connection" needs there: the connection a
Connections row means, found by its ports and far address, and its id in the kernel's
words - with the cookie, the number the kernel gave that one socket. ``tcpreset`` hands
that id back to reset the connection; this module only asks for the list. It is
``tcprow``'s twin: a ``Socket`` carries the fields ``tcprow.matching`` reads, so a row
is found the same way on both systems.

The layouts are the kernel's (``include/uapi/linux``: ``netlink.h``, ``sock_diag.h``,
``inet_diag.h``), which never change: a netlink header, then ``inet_diag_req_v2`` out and
``inet_diag_msg`` back, each holding an ``inet_diag_sockid`` - ports and addresses in
network byte order, the interface and the cookie in the machine's own. The numbers are
the kernel's too, not Python's names: Python on Windows has no ``AF_NETLINK``, and the
type checker reads this file there.

MEASURED 2026-10-26 (``internal_tools`` probes ``2026-10-26-linux-reset``: Ubuntu 26.04.1
with kernel 7.0.0 and WSL with 6.18; ``tests/test_sockdiag.py`` holds that kernel's own
answers):

* The list needs no rights: an ordinary user gets every socket of the network namespace.
* A socket a program opened as IPv6 and connected to an IPv4 address (Java does that by
  default) is only in the IPv6 list, as ``::ffff:192.0.2.1``. Its packets carry
  ``192.0.2.1``, and so does its Connections row: the address is written that way here,
  while the id keeps the kernel's form - the kernel finds the socket by it.
* Both lists, asked for every state but LISTEN, took 0.2 ms in WSL and about 3 ms on the
  VM, where ``psutil.net_connections`` took 6.6 and 19 ms.
"""
import errno
import ipaddress
import socket
import struct
from typing import NamedTuple

AF_NETLINK = 16
NETLINK_SOCK_DIAG = 4
SOCK_DIAG_BY_FAMILY = 20
NLMSG_ERROR, NLMSG_DONE = 2, 3
NLM_F_REQUEST, NLM_F_ACK, NLM_F_DUMP = 0x1, 0x4, 0x300
MSG_TRUNC = 0x20
LINUX_AF_INET, LINUX_AF_INET6 = 2, 10
IPPROTO_TCP = 6
TCP_LISTEN = 10
EVERY_STATE = 0xFFFFFFFF
# A listener has no far end, so no Connections row can mean one.
CONNECTED = EVERY_STATE & ~(1 << TCP_LISTEN)
NO_COOKIE = (0xFFFFFFFF, 0xFFFFFFFF)    # INET_DIAG_NOCOOKIE: "any socket with this id"
SEQ = 1                                 # one request per socket: the number tells nothing apart
WAIT_S = 2.0                            # the kernel answers at once; a silence is a failure
BUFFER = 1 << 16                        # a dump datagram is at most 32 KiB (netlink_recvmsg)

# The kernel's TCP states (``include/net/tcp_states.h``) in ``portmap.TCP_STATES``' words,
# so a state reads the same on both systems. 12 is the kernel's own: a connection request
# not accepted yet.
STATES = {1: "ESTABLISHED", 2: "SYN_SENT", 3: "SYN_RECEIVED", 4: "FIN_WAIT_1",
          5: "FIN_WAIT_2", 6: "TIME_WAIT", 7: "CLOSED", 8: "CLOSE_WAIT", 9: "LAST_ACK",
          10: "LISTEN", 11: "CLOSING", 12: "NEW_SYN_RECV"}

_HEADER = struct.Struct("=IHHII")       # nlmsghdr: length, type, flags, seq, pid
_REQUEST = struct.Struct("=BBBBI")      # inet_diag_req_v2 up to its id: family, protocol,
                                        # extensions, pad, states
_PORTS = struct.Struct("!HH")           # inet_diag_sockid: source and destination port
_TAIL = struct.Struct("=III")           # ... its interface and the two halves of the cookie
_ERROR = struct.Struct("=i")            # nlmsgerr and NLMSG_DONE: a negative errno, or 0
SOCKID = 48
MESSAGE = 72                            # inet_diag_msg; attributes may follow it
_ID_AT = 4                              # family, state, timer, retransmits, then the id


class Socket(NamedTuple):
    """One TCP socket in the kernel's list. The first five fields are what
    ``tcprow.matching`` reads, named as ``portmap.SocketRow`` names them."""
    proto: str
    local_ip: str
    local_port: int
    remote_ip: str          # an IPv4 address mapped into IPv6 is written as the IPv4 one
    remote_port: int
    state: str
    kernel_family: int      # the list it is in: LINUX_AF_INET or LINUX_AF_INET6
    sockid: bytes           # inet_diag_sockid as the kernel sent it, the cookie in it


def sockid(sport=0, dport=0, src=b"", dst=b"", interface=0, cookie=NO_COOKIE):
    """An ``inet_diag_sockid``. ``src`` and ``dst`` are packed addresses, 4 or 16 bytes."""
    return (_PORTS.pack(sport, dport) + src.ljust(16, b"\0") + dst.ljust(16, b"\0")
            + _TAIL.pack(interface, *cookie))


def request(kind, flags, family, sid, states=EVERY_STATE):
    """One ``inet_diag_req_v2`` for TCP, in its netlink header."""
    body = _REQUEST.pack(family, IPPROTO_TCP, 0, 0, states) + sid
    return _HEADER.pack(_HEADER.size + len(body), kind, flags, SEQ, 0) + body


def _open():
    nl = socket.socket(AF_NETLINK, socket.SOCK_RAW, NETLINK_SOCK_DIAG)
    nl.settimeout(WAIT_S)
    return nl


def _messages(data):
    """The netlink messages in one datagram, as ``(type, payload)``."""
    out = []
    offset = 0
    while offset + _HEADER.size <= len(data):
        length, kind = _HEADER.unpack_from(data, offset)[:2]
        if length < _HEADER.size or offset + length > len(data):
            raise OSError(errno.EBADMSG, "sock_diag: a message longer than its datagram")
        out.append((kind, data[offset + _HEADER.size:offset + length]))
        offset += (length + 3) & ~3
    return out


def exchange(message, opener=_open):
    """Send one request; the kernel's answer as ``(type, payload)`` pairs, up to the one
    that ends it - NLMSG_DONE after a list, NLMSG_ERROR otherwise (an acknowledgement is
    an error of 0). A socket per request, closed before this returns."""
    with opener() as nl:
        nl.sendto(message, (0, 0))
        replies: list = []
        while not replies or replies[-1][0] not in (NLMSG_DONE, NLMSG_ERROR):
            data, _ancillary, flags, _sender = nl.recvmsg(BUFFER)
            if flags & MSG_TRUNC:
                raise OSError(errno.EMSGSIZE, "sock_diag: an answer longer than the buffer")
            replies.extend(_messages(data))
        return replies


def error_of(replies):
    """The errno a request's answer ends in: 0 when the kernel did it."""
    kind, payload = replies[-1]
    if kind not in (NLMSG_ERROR, NLMSG_DONE) or len(payload) < _ERROR.size:
        raise OSError(errno.EBADMSG, f"sock_diag: an answer that ends in type {kind}")
    return -_ERROR.unpack_from(payload)[0]


def _address(packed):
    address = ipaddress.ip_address(packed)
    return str(getattr(address, "ipv4_mapped", None) or address)


def _socket(payload):
    if len(payload) < MESSAGE:
        raise OSError(errno.EBADMSG, f"sock_diag: a socket in {len(payload)} bytes")
    family, state = payload[0], payload[1]
    sid = bytes(payload[_ID_AT:_ID_AT + SOCKID])
    sport, dport = _PORTS.unpack_from(sid)
    size = 4 if family == LINUX_AF_INET else 16
    return Socket("TCP", _address(sid[4:4 + size]), sport, _address(sid[20:20 + size]), dport,
                  STATES.get(state, str(state)), family, sid)


def tcp_sockets(talk=exchange):
    """Every TCP socket of this network namespace but its listeners, IPv4 and IPv6.
    Raises ``OSError`` when the kernel will not list one of the two: a missing socket
    would then say nothing about a connection."""
    found = []
    for family in (LINUX_AF_INET, LINUX_AF_INET6):
        replies = talk(request(SOCK_DIAG_BY_FAMILY, NLM_F_REQUEST | NLM_F_DUMP, family,
                               sockid(), CONNECTED))
        code = error_of(replies)
        if code:
            raise OSError(code, "sock_diag: the kernel refused the list")
        found += [_socket(payload) for kind, payload in replies if kind == SOCK_DIAG_BY_FAMILY]
    return found
