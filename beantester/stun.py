"""STUN and TURN messages for the NAT and STUN tool: written and read, nothing sent.

The tool (``nettools/nat.py``) asks a STUN server which address this computer has and
a TURN server whether it answers; this module turns those questions into bytes and
the answers back into facts. Pure - bytes in, values out, no socket - so every rule
here is tested on the RFC's own bytes (RFC 5769) on both CI runners.

``ice.py`` reads STUN too, for another job: it classifies captured datagrams on the
capture thread and stays a leaf that costs one call per packet. The constants are
its own, imported from there (one source); the reading here is the tool's - whole
and bounded - and never runs on the capture thread.

The facts it rests on, read in the RFCs rather than remembered:

* RFC 8489, STUN: a 20-byte header - the message type (the first two bits zero), the
  length WITHOUT the header (a multiple of 4), the magic cookie 0x2112A442 and a
  96-bit transaction ID - then attributes, each a type, a length and a value padded
  to 4 bytes (the padding may be any bytes; RFC 5769 pads with spaces).
* XOR-MAPPED-ADDRESS (0x0020): the port XORed with the cookie's top 16 bits, an IPv4
  address with the cookie, an IPv6 address with the cookie and the transaction ID.
  MAPPED-ADDRESS (0x0001) is the same without the XOR, from servers older than RFC
  5389. The first byte of either is reserved and ignored.
* ERROR-CODE (0x0009): the class (the hundreds, 3 to 6) in the low 3 bits of its
  third byte, the number (0 to 99) in the fourth, then a reason phrase. The phrase is
  the server's text and is never read here: the tool says a code in its own words.
* FINGERPRINT (0x8028) is the last attribute: the CRC-32 of the message before it,
  with the header's length already counting it, XORed with 0x5354554E. A message
  whose fingerprint does not match is not taken (RFC 8489, 14.7).
* RFC 8656, TURN: Allocate (method 3) carries REQUESTED-TRANSPORT (0x0019) - the
  protocol number, 17 for UDP, and three reserved bytes. Without credentials a
  server answers 401 (Unauthenticated): that is how the tool learns a TURN server is
  there without an account. A Refresh (method 4) with LIFETIME (0x000D) 0 gives an
  allocation back at once - for the server that hands one out without a login.

Bytes from the network are untrusted. ``decode`` takes a message only when it is one
whole, well-formed message: it never raises, reads no attribute past the end, and
refuses anything longer than ``MAX_MESSAGE`` - the most the tool reads at a time.
"""
import ipaddress
import os
import zlib
from typing import NamedTuple

from .ice import ALLOCATE, BINDING, COOKIE, ERROR, REQUEST, SUCCESS, XOR_MAPPED_ADDRESS

HEADER = 20
MAGIC = int.from_bytes(COOKIE, "big")
MAX_MESSAGE = 4096

REFRESH = 0x004
MAPPED_ADDRESS = 0x0001
ERROR_CODE = 0x0009
LIFETIME = 0x000D
REQUESTED_TRANSPORT = 0x0019
FINGERPRINT = 0x8028
FINGERPRINT_XOR = 0x5354554E

UDP_PROTOCOL = 17
IPV4, IPV6 = 0x01, 0x02

__all__ = ["ALLOCATE", "BINDING", "ERROR", "Message", "REFRESH", "REQUEST", "SUCCESS",
           "allocate_request", "binding_request", "decode", "encode", "error_code",
           "mapped_address", "release_request", "stream_length", "transaction_id"]


class Message(NamedTuple):
    method: int         # BINDING, ALLOCATE...
    kind: int           # REQUEST, INDICATION, SUCCESS or ERROR (ice.py's numbers)
    transaction: bytes  # the 12-byte transaction ID
    attributes: tuple   # ((type, value), ...) in the order sent, padding left out


def transaction_id():
    """A new transaction ID: 96 random bits (RFC 8489 asks for them to be random)."""
    return os.urandom(12)


def message_type(method, kind):
    """The 16-bit message type: the class bits (4 and 8) between the method's."""
    return ((method & 0x000F) | ((method & 0x0070) << 1) | ((method & 0x0F80) << 2)
            | ((kind & 0b01) << 4) | ((kind & 0b10) << 7))


def _attribute(kind, value):
    value = bytes(value)
    return (kind.to_bytes(2, "big") + len(value).to_bytes(2, "big") + value
            + b"\0" * (-len(value) % 4))


def encode(method, kind, transaction, attributes=(), fingerprint=False):
    """One message. The tool's own requests go without a FINGERPRINT - the shape
    measured against the default servers (2026-11-09: every transport answered)."""
    body = b"".join(_attribute(kind_, value) for kind_, value in attributes)
    length = len(body) + (8 if fingerprint else 0)
    message = (message_type(method, kind).to_bytes(2, "big") + length.to_bytes(2, "big")
               + COOKIE + bytes(transaction) + body)
    if fingerprint:
        crc = (zlib.crc32(message) ^ FINGERPRINT_XOR) & 0xFFFFFFFF
        message += _attribute(FINGERPRINT, crc.to_bytes(4, "big"))
    return message


def binding_request(transaction):
    """"Which address do you see me at?" - to a STUN server."""
    return encode(BINDING, REQUEST, transaction)


def allocate_request(transaction):
    """An Allocate with no credentials: a TURN server answers it with 401."""
    return encode(ALLOCATE, REQUEST, transaction,
                  ((REQUESTED_TRANSPORT, bytes((UDP_PROTOCOL, 0, 0, 0))),))


def release_request(transaction):
    """A Refresh with a lifetime of 0: the allocation an Allocate got is given back."""
    return encode(REFRESH, REQUEST, transaction, ((LIFETIME, bytes(4)),))


def decode(data):
    """The ``Message`` in ``data``, or ``None`` when ``data`` is not exactly one
    well-formed message. Never raises."""
    data = bytes(data)
    size = len(data)
    if size < HEADER or size > MAX_MESSAGE or data[0] & 0xC0 or data[4:8] != COOKIE:
        return None
    length = int.from_bytes(data[2:4], "big")
    # One message, whole: a datagram carries one, and the stream reader cuts one
    # out by ``stream_length``. A multiple of 4 leaves room for every 4-byte header.
    if length & 3 or HEADER + length != size:
        return None
    bits = int.from_bytes(data[0:2], "big")
    method = (bits & 0x000F) | ((bits & 0x00E0) >> 1) | ((bits & 0x3E00) >> 2)
    kind = ((bits & 0x0100) >> 7) | ((bits & 0x0010) >> 4)
    found = []
    at = HEADER
    while at < size:
        kind_ = int.from_bytes(data[at:at + 2], "big")
        value_size = int.from_bytes(data[at + 2:at + 4], "big")
        after = at + 4 + ((value_size + 3) & ~3)
        if after > size:
            return None
        value = data[at + 4:at + 4 + value_size]
        if kind_ == FINGERPRINT:
            want = (zlib.crc32(data[:at]) ^ FINGERPRINT_XOR) & 0xFFFFFFFF
            if after != size or value_size != 4 or int.from_bytes(value, "big") != want:
                return None
        found.append((kind_, value))
        at = after
    return Message(method, kind, data[8:20], tuple(found))


def stream_length(head):
    """How many bytes the message that starts with ``head`` (its first 20) takes on a
    TCP stream, or ``None`` when that is not a STUN header or it is too long."""
    head = bytes(head)
    if len(head) < HEADER or head[0] & 0xC0 or head[4:8] != COOKIE:
        return None
    length = int.from_bytes(head[2:4], "big")
    if length & 3 or HEADER + length > MAX_MESSAGE:
        return None
    return HEADER + length


def _value(message, kind):
    for kind_, value in message.attributes:
        if kind_ == kind:
            return value
    return None


def mapped_address(message):
    """``(address, port)`` the server saw the request come from, or ``None``.

    XOR-MAPPED-ADDRESS first; MAPPED-ADDRESS only from a server that sent no XOR one.
    The address is canonical text (``ipaddress``), as ``ice.py`` writes it.
    """
    xored = _value(message, XOR_MAPPED_ADDRESS)
    if xored is not None:
        return _address(xored, MAGIC.to_bytes(4, "big") + message.transaction)
    plain = _value(message, MAPPED_ADDRESS)
    if plain is not None:
        return _address(plain, bytes(16))
    return None


def _address(value, mask):
    """Decode an address attribute; ``mask`` is what it was XORed with (zeros for none).

    The tool sends to the address it gets here (the hairpin jobs), so one that no
    request can have come from - port 0, an unspecified, multicast or broadcast
    address - is no answer at all."""
    if len(value) < 4:
        return None
    port = int.from_bytes(value[2:4], "big") ^ int.from_bytes(mask[:2], "big")
    address: ipaddress.IPv4Address | ipaddress.IPv6Address
    if value[1] == IPV4 and len(value) == 8:
        address = ipaddress.IPv4Address(int.from_bytes(value[4:8], "big")
                                        ^ int.from_bytes(mask[:4], "big"))
    elif value[1] == IPV6 and len(value) == 20:
        address = ipaddress.IPv6Address(int.from_bytes(value[4:20], "big")
                                        ^ int.from_bytes(mask, "big"))
    else:
        return None
    if (not port or address.is_unspecified or address.is_multicast
            or address == ipaddress.IPv4Address("255.255.255.255")):
        return None
    return str(address), port


def error_code(message):
    """The ERROR-CODE of an error answer as a number (401, 438...), or ``None`` when
    there is none or it is not one RFC 8489 allows (class 3 to 6, number below 100)."""
    value = _value(message, ERROR_CODE)
    if value is None or len(value) < 4:
        return None
    hundreds, number = value[2] & 0x07, value[3]
    if not 3 <= hundreds <= 6 or number > 99:
        return None
    return hundreds * 100 + number
