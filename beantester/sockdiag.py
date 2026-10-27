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

TCP health reads one socket at a time (``lookup``): the socket's id from the list, its
``tcp_info`` asked for. MEASURED 2026-10-27 (``internal_tools`` probes
``2026-10-27-linux-tcphealth``, the same VM and WSL with 6.18):

* ``tcp_info`` is 280 bytes on both, the same bytes ``getsockopt(TCP_INFO)`` gives the
  socket's own program, and every field read here equals what ``ss -tin`` printed. An
  older kernel sends a shorter one - fields are only ever added at its end - so a field
  is read only when it is inside the length (``tcp_info``).
* An ordinary user gets it for root's sockets too.
* 🔴 Asked for by its addresses and ports alone, a connection that has gone is answered
  by the LISTENER on its local port, with the listener's numbers. With the cookie the
  answer is ENOENT, also for a new connection that took the same ports.
* A socket in TIME_WAIT, or one its program has closed (an orphan in FIN_WAIT2), is
  answered without ``tcp_info``: the kernel keeps none for it.
* One lookup took about 0.1 ms, a new netlink socket included.
"""
import errno
import ipaddress
import struct
from typing import NamedTuple

from . import netlink

# The transport's numbers, under the names tcpreset and the tests read them by.
NETLINK_SOCK_DIAG = netlink.NETLINK_SOCK_DIAG
NLMSG_ERROR, NLMSG_DONE = netlink.NLMSG_ERROR, netlink.NLMSG_DONE
NLM_F_REQUEST, NLM_F_ACK, NLM_F_DUMP = netlink.NLM_F_REQUEST, netlink.NLM_F_ACK, netlink.NLM_F_DUMP
MSG_TRUNC = netlink.MSG_TRUNC
SOCK_DIAG_BY_FAMILY = 20
LINUX_AF_INET, LINUX_AF_INET6 = 2, 10
IPPROTO_TCP = 6
TCP_LISTEN = 10
EVERY_STATE = 0xFFFFFFFF
# A listener has no far end, so no Connections row can mean one.
CONNECTED = EVERY_STATE & ~(1 << TCP_LISTEN)
NO_STATES = 0                           # a list of nothing: "is sock_diag for TCP here?"
NO_COOKIE = (0xFFFFFFFF, 0xFFFFFFFF)    # INET_DIAG_NOCOOKIE: "any socket with this id"
# The attribute of an answer that holds the socket's ``struct tcp_info``, and the bit that
# asks for it (``idiag_ext``: bit N-1 for attribute N).
INET_DIAG_INFO = 2
INFO = 1 << (INET_DIAG_INFO - 1)

# The kernel's TCP states (``include/net/tcp_states.h``) in ``portmap.TCP_STATES``' words,
# so a state reads the same on both systems. 12 is the kernel's own: a connection request
# not accepted yet.
STATES = {1: "ESTABLISHED", 2: "SYN_SENT", 3: "SYN_RECEIVED", 4: "FIN_WAIT_1",
          5: "FIN_WAIT_2", 6: "TIME_WAIT", 7: "CLOSED", 8: "CLOSE_WAIT", 9: "LAST_ACK",
          10: "LISTEN", 11: "CLOSING", 12: "NEW_SYN_RECV"}

_REQUEST = struct.Struct("=BBBBI")      # inet_diag_req_v2 up to its id: family, protocol,
                                        # extensions, pad, states
_PORTS = struct.Struct("!HH")           # inet_diag_sockid: source and destination port
_TAIL = struct.Struct("=III")           # ... its interface and the two halves of the cookie
SOCKID = 48
MESSAGE = 72                            # inet_diag_msg; attributes may follow it
_ID_AT = 4                              # family, state, timer, retransmits, then the id

# ``struct tcp_info`` (``include/uapi/linux/tcp.h``): the fields TCP health reads, at the
# offsets that header gives them, in the machine's own byte order. Times in microseconds.
TCP_INFO_FIELDS = {
    "rto": (8, "I"), "snd_mss": (16, "I"), "rtt": (68, "I"), "rttvar": (72, "I"),
    "total_retrans": (100, "I"), "bytes_received": (128, "Q"), "min_rtt": (148, "I"),
    "bytes_sent": (200, "Q"), "bytes_retrans": (208, "Q"), "total_rto": (240, "H")}
_TCP_INFO = {name: (at, struct.Struct("=" + kind)) for name, (at, kind) in TCP_INFO_FIELDS.items()}


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


def request(kind, flags, family, sid, states=EVERY_STATE, extensions=0):
    """One ``inet_diag_req_v2`` for TCP, in its netlink header. ``extensions``: the
    attributes asked for besides the message (``INFO``)."""
    body = _REQUEST.pack(family, IPPROTO_TCP, extensions, 0, states) + sid
    return netlink.message(kind, flags, body)


_open = netlink.opener(NETLINK_SOCK_DIAG)


def exchange(message, opener=_open):
    """Send one request; the kernel's answer as ``(type, payload)`` pairs, up to the one
    that ends it - NLMSG_DONE after a list, NLMSG_ERROR otherwise (an acknowledgement is
    an error of 0). ``netlink.exchange`` over a sock_diag socket."""
    return netlink.exchange(message, opener)


error_of = netlink.error_of


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


def lists(talk=exchange):
    """Whether this kernel lists TCP sockets with their ``tcp_info``: a list of no state at
    all, which needs no rights and walks nothing. A kernel without sock_diag's TCP part
    refuses it; one without sock_diag at all fails to open the socket (OSError)."""
    return error_of(talk(request(SOCK_DIAG_BY_FAMILY, NLM_F_REQUEST | NLM_F_DUMP, LINUX_AF_INET,
                                 sockid(), NO_STATES, INFO))) == 0


class Found(NamedTuple):
    """The kernel's answer for one socket: its state, and its ``tcp_info`` - None for a
    socket that keeps none (TIME_WAIT, or one whose program has closed it)."""
    state: str
    info: bytes | None


def lookup(kernel_family, sid, talk=exchange):
    """The one socket ``sid`` names, with its ``tcp_info``: ``(0, Found)``, or the errno the
    kernel answered and None - ENOENT when there is no such socket. ``sid`` carries the
    cookie the list gave: without it a connection that has gone is answered by the
    listener on its port."""
    replies = talk(request(SOCK_DIAG_BY_FAMILY, NLM_F_REQUEST | NLM_F_ACK, kernel_family, sid,
                           EVERY_STATE, INFO))
    error = error_of(replies)
    if error:
        return error, None
    answers = [payload for kind, payload in replies if kind == SOCK_DIAG_BY_FAMILY]
    if len(answers) != 1:
        raise OSError(errno.EBADMSG, f"sock_diag: {len(answers)} sockets for one id")
    info = [a.value for a in netlink.attributes(answers[0], MESSAGE) if a.kind == INET_DIAG_INFO]
    return 0, Found(_socket(answers[0]).state, info[0] if info else None)


def tcp_info(raw):
    """The fields of ``TCP_INFO_FIELDS`` that ``raw`` holds, by name: a field past the end
    of an older kernel's shorter struct is left out, never read as 0."""
    return {name: shape.unpack_from(raw, at)[0] for name, (at, shape) in _TCP_INFO.items()
            if at + shape.size <= len(raw)}
