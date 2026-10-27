"""Netlink, the kernel's own message socket on Linux: one request out, its answer back.

The transport under the two modules that ask the kernel's tables: ``sockdiag`` (the
TCP socket list, and the destroy behind "Reset this connection") and ``rtnetlink``
(the adapters, their addresses and the routes). Each says what to ask; this sends it
and reads the answer to its end, so the rules for a datagram that does not add up live
in one place.

The layouts are the kernel's (``include/uapi/linux/netlink.h``), which never change: a
16-byte header (length, type, flags, sequence, port) in the machine's byte order,
messages padded to 4 bytes, and attributes inside them as length, type and value. The
numbers are written out, not taken from Python: Python on Windows has no
``AF_NETLINK``, and the type checker reads this file there.

A request is answered in one of two ways: a list (``NLM_F_DUMP``) ends in NLMSG_DONE,
and anything else ends in NLMSG_ERROR - an acknowledgement is an error of 0, and it
only comes when the request asks for one (``NLM_F_ACK``). A request that asks for
neither is answered with its reply and nothing after it, so the read below would wait
out its timeout: MEASURED 2026-10-27 on a route lookup (``internal_tools`` probes
``2026-10-27-linux-adapters``).
"""
import errno
import socket
import struct
from typing import NamedTuple

AF_NETLINK = 16
NETLINK_ROUTE, NETLINK_SOCK_DIAG = 0, 4
NLMSG_ERROR, NLMSG_DONE = 2, 3
NLM_F_REQUEST, NLM_F_ACK, NLM_F_DUMP = 0x1, 0x4, 0x300
NLM_F_DUMP_INTR = 0x10                  # the table changed while it was listed
MSG_TRUNC = 0x20
SEQ = 1                                 # one request per socket: the number tells nothing apart
WAIT_S = 2.0                            # the kernel answers at once; a silence is a failure
BUFFER = 1 << 16                        # a dump datagram is at most 32 KiB (netlink_recvmsg)
KERNEL = 0                              # the port the kernel sends from

HEADER = struct.Struct("=IHHII")        # nlmsghdr: length, type, flags, seq, port
_ERROR = struct.Struct("=i")            # nlmsgerr and NLMSG_DONE: a negative errno, or 0
_ATTRIBUTE = struct.Struct("=HH")       # rtattr / nlattr: length, type
_TYPE = 0x3FFF                          # an attribute's type without the NESTED and BYTEORDER bits


class Replies(list):
    """The ``(type, payload)`` pairs of one answer. ``interrupted``: a message of the list
    said the table changed while the kernel walked it (NLM_F_DUMP_INTR) - the list may
    then miss an entry or hold one twice."""
    interrupted = False


def message(kind, flags, body):
    """``body`` in its netlink header."""
    return HEADER.pack(HEADER.size + len(body), kind, flags, SEQ, 0) + body


def opener(protocol):
    """What opens a socket of ``protocol`` for one request."""
    def open_socket():
        nl = socket.socket(AF_NETLINK, socket.SOCK_RAW, protocol)
        nl.settimeout(WAIT_S)
        return nl
    return open_socket


def messages(data):
    """The netlink messages in one datagram, as ``(type, flags, payload)``."""
    out = []
    offset = 0
    while offset + HEADER.size <= len(data):
        length, kind, flags = HEADER.unpack_from(data, offset)[:3]
        if length < HEADER.size or offset + length > len(data):
            raise OSError(errno.EBADMSG, "netlink: a message longer than its datagram")
        out.append((kind, flags, data[offset + HEADER.size:offset + length]))
        offset += (length + 3) & ~3
    return out


def exchange(request, open_socket):
    """Send one request; the kernel's answer up to the message that ends it, as
    ``Replies``. A socket per request, closed before this returns."""
    with open_socket() as nl:
        nl.sendto(request, (KERNEL, 0))
        replies = Replies()
        while not replies or replies[-1][0] not in (NLMSG_DONE, NLMSG_ERROR):
            data, _ancillary, flags, sender = nl.recvmsg(BUFFER)
            if flags & MSG_TRUNC:
                raise OSError(errno.EMSGSIZE, "netlink: an answer longer than the buffer")
            if sender[0] != KERNEL:
                raise OSError(errno.EBADMSG, f"netlink: an answer from port {sender[0]}, "
                                             "not the kernel")
            for kind, message_flags, payload in messages(data):
                replies.interrupted |= bool(message_flags & NLM_F_DUMP_INTR)
                replies.append((kind, payload))
        return replies


def error_of(replies):
    """The errno a request's answer ends in: 0 when the kernel did it."""
    kind, payload = replies[-1]
    if kind not in (NLMSG_ERROR, NLMSG_DONE) or len(payload) < _ERROR.size:
        raise OSError(errno.EBADMSG, f"netlink: an answer that ends in type {kind}")
    return -_ERROR.unpack_from(payload)[0]


class Attribute(NamedTuple):
    kind: int
    value: bytes


def attributes(data, offset=0):
    """The attributes of one message from ``offset`` on. One that claims more bytes than
    are there is an error, never a shorter value."""
    out = []
    while offset + _ATTRIBUTE.size <= len(data):
        length, kind = _ATTRIBUTE.unpack_from(data, offset)
        if length < _ATTRIBUTE.size or offset + length > len(data):
            raise OSError(errno.EBADMSG, "netlink: an attribute longer than its message")
        out.append(Attribute(kind & _TYPE, bytes(data[offset + _ATTRIBUTE.size:offset + length])))
        offset += (length + 3) & ~3
    return out


def attribute(kind, value):
    """One attribute, padded, for a request."""
    raw = _ATTRIBUTE.pack(_ATTRIBUTE.size + len(value), kind) + value
    return raw + bytes(-len(raw) % 4)
