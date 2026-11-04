"""Which UDP flows carry ICE, and which one of them carries the data.

An ICE agent (RFC 8445; WebRTC is the common one) tries several paths to its peer at
once and keeps one: straight across this network, through this network's own public
address (a router that "hairpins" it back in), to the peer's public address, or
through a TURN relay. The Connections tab lists every one of those as an ordinary
UDP row, so which path won was a guess. This module answers it from bytes the
capture already holds: it reads the packets of each UDP flow until it knows what the
flow is, labels the flows that speak STUN, and once a second names the flow the data
actually went through. The same bytes answer a second question, for the scope that
impairs only part of a call: which part one datagram is (``call_part``).

It sends nothing, asks the operating system for nothing and imports nothing of this
package but ``utils``: it runs on the capture thread (``tests/test_hot_path.py``). It
has no lock of its own either. ``ConnectionLog`` is the only caller of ``IceWatch``
and makes every call with its lock held, so the rows and this state change together;
``call_part`` keeps no state, and ``BeanCore.decide`` calls it under the core's lock.

The facts it rests on, read in the RFCs rather than remembered:

* RFC 9443 (which updates RFC 7983), the first byte of a datagram on a shared port:
  0-3 STUN, 20-63 DTLS, 64-79 TURN ChannelData - but only to or from a TURN server,
  anywhere else that range is QUIC - and 128-191 RTP and RTCP.
* RFC 8489, STUN: a 20-byte header whose first two bits are zero, the magic cookie
  0x2112A442, and a length that leaves the header out and is a multiple of 4. The
  class sits in bits 4 and 8 of the message type and the method in the other twelve.
  Binding is method 1. XOR-MAPPED-ADDRESS (0x0020) is the address the ANSWERING side
  saw the request come from.
* RFC 8656, TURN: Allocate 3, Refresh 4, Send 6, Data 7, CreatePermission 8 and
  ChannelBind 9, all of them STUN methods. Send and Data carry the relayed datagram
  in a DATA attribute (0x0013); ChannelData carries it after a 4-byte header whose
  channel number is in 0x4000-0x4FFF.
* RFC 8445, ICE: every connectivity check is a Binding request carrying PRIORITY
  (0x0024). A plain "what is my address" query to a STUN server carries none.

What this cannot see: TURN over TCP or TLS. The STUN messages are inside a TCP stream
or encrypted, so those flows stay unlabelled rather than guessed at.
"""
import ipaddress

from .utils import canonical_ip, is_local_ip

COOKIE = b"\x21\x12\xa4\x42"
BINDING = 0x001
ALLOCATE = 0x003
SEND = 0x006
DATA = 0x007
TURN_METHODS = frozenset({ALLOCATE, 0x004, SEND, DATA, 0x008, 0x009})
# The TURN methods that get and keep the relay - Allocate, Refresh, CreatePermission
# and ChannelBind - against Send and Data, which only carry what the relay relays.
TURN_CONTROL = TURN_METHODS - {SEND, DATA}
READ_ATTRIBUTES = frozenset({BINDING, ALLOCATE, SEND, DATA})
REQUEST, INDICATION, SUCCESS, ERROR = 0, 1, 2, 3
XOR_MAPPED_ADDRESS = 0x0020
PRIORITY = 0x0024
DATA_ATTRIBUTE = 0x0013

# What the ICE column says about a flow. Tokens rather than words: they read the
# same in every language, like TCP and UDP in the Protocol column, so `ice:turn`
# finds the same rows everywhere, and the column's tooltip explains each one.
TURN = "TURN"   # carried a TURN method: the flow to a relay
STUN = "STUN"   # STUN but no connectivity check: an address query to a STUN server
LAN = "LAN"     # connectivity checks to an address on this network
NAT = "NAT"     # checks to this network's own public address (the router hairpins)
WAN = "WAN"     # checks to a public address that is not this network's

# How long a flow is read. Every number bounds work on the capture thread, and a
# flow whose budget (row["ice_n"]) reaches zero is never read again. A packet that
# is not ICE signalling spends one, unless it is the media that makes a flow a path
# (which ends the reading); see IceWatch.observe for the rest.
#
# A new UDP flow is read for ONE packet: the first datagram of every ICE flow is
# STUN (a connectivity check, or an Allocate to a relay), and a call that was going
# before the session started opens with what a call carries, which buys PROBE_CALL.
# It was 4 first, and the count of CALLS is what costs: MEASURED 2026-11-04 in the
# engine (CPython 3.15.2, ``internal_tools`` probes ``2026-11-04-ice-path``, a new UDP
# flow every two packets), one call to an EMPTY probe per packet took 4.7% off
# the pipeline's ceiling - a call costs ~1 us there, against ~50 ns in a loop of its
# own - while one call per flow took nothing measurable.
PROBE_FIRST = 1
# A flow whose FIRST packet is media (DTLS or RTP) or a TURN ChannelData frame that
# carries media or STUN: a call that was going when the session started - every
# start empties the connection log - straight to the peer or through a relay. Its
# first STUN is the next consent check (RFC 7675: every 5 s, each interval drawn from
# 0.8-1.2 of it, from BOTH ends), and ~800 packets a second of 1080p video both ways
# would use up a thousand packets in a second, so it is read for 8192 - about ten
# seconds of such a call. It is read only while every packet fits a call (media, a
# carrying frame, STUN): the first that does not ends it. A random first byte looks
# like media 42% of the time (108 of 256 values), and such a flow is dropped at its
# next packet of another kind (58% each) instead of being read for the budget.
PROBE_CALL = 8192
PROBE_ICE = 256     # after the first STUN message
# ICE signalling spends no budget, so a relay that only carries keepalives is still
# read when the call moves onto it half an hour later. This is its own ceiling: about
# a day of one message a second, or seven seconds of a STUN flood at the ~14k
# packets a second this tool sustains.
SIGNAL_MAX = 100_000
PUBLIC_MAX = 16     # this network's public addresses, as STUN answers told them

# Which part of a call one datagram is (``call_part``), for the scope that impairs
# only some of a call (``BeanCore.set_call_parts``). Bits, so a session asks for
# any mix of the first three; the fourth is an answer only, never asked for.
CALL_CHECKS = 1         # STUN that is not TURN's: connectivity and consent checks
CALL_TURN_CONTROL = 2   # TURN's own requests and answers: getting and keeping a relay
CALL_MEDIA = 4          # DTLS and RTP/RTCP, straight or carried by a relay
CALL_LOOKS_MEDIA = 8    # media by its first byte alone: the flow decides (see call_part)

# The path timeline, on the watchdog thread.
TICK_S = 1.0
WINDOW_TICKS = 3        # bytes delivered over the last three ticks...
ACTIVE_BYTES = 1500     # ...at least this many make a flow a path with data on it.
                        # Consent checks are ~100 B a second; any media is far more.
SWITCH_TICKS = 2        # a new path has to lead this many ticks in a row
QUIET_S = 5.0           # no path with data for this long: say the data stopped


def _start(raw):
    """Where the UDP payload of ``raw`` starts, or -1 when it has none to read.

    -1 for anything that is not plainly UDP: an IPv4 fragment after the first (no
    UDP header in it), an IPv6 packet with an extension header (not walked: a guess
    is worse than no label), a UDP length that does not fit the packet - which is
    also what the first fragment of a split datagram looks like - and an empty
    payload. Reads lengths before every index, so it does not raise on any bytes.

    An offset, not a slice, and nothing allocated: most packets read here are
    turned down on their first byte. A memoryview and a tuple for each of them are
    objects the cycle collector counts, and with 200 000 rows alive a collection is
    not cheap. ``_end`` gives the end only for the packets that need it.
    """
    size = len(raw)
    if size < 29:
        return -1
    version = raw[0] >> 4
    if version == 4:
        head = (raw[0] & 0x0F) * 4
        if head < 20 or raw[9] != 17 or (raw[6] & 0x1F) or raw[7]:
            return -1
    elif version == 6:
        head = 40
        if raw[6] != 17:
            return -1
    else:
        return -1
    if size <= head + 8:
        return -1
    length = (raw[head + 4] << 8) | raw[head + 5]
    if length <= 8 or head + length > size:
        return -1
    return head + 8


def _end(raw, start):
    """The end of the payload that starts at ``start`` (from the UDP length)."""
    return start - 8 + ((raw[start - 4] << 8) | raw[start - 3])


def stun(payload):
    """``(method, kind, check, mapped, carried)`` for a STUN message, else ``None``.

    ``kind`` is the class (REQUEST, INDICATION, SUCCESS, ERROR). ``check`` is whether
    it carries PRIORITY - an ICE connectivity check. ``mapped`` is the address in
    XOR-MAPPED-ADDRESS as canonical text, or ``None``. ``carried`` is the first byte
    of the DATA attribute - what a Send or Data indication relays - or -1. Attributes
    are read only for the methods that carry one of those (``READ_ATTRIBUTES``).

    The length has to match the datagram exactly (one message per datagram over UDP),
    on top of the cookie, so random bytes pass for STUN less often than once in 2^34.
    """
    size = len(payload)
    if size < 20 or payload[0] & 0xC0 or payload[4:8] != COOKIE:
        return None
    if size & 3 or ((payload[2] << 8) | payload[3]) + 20 != size:
        return None
    bits = (payload[0] << 8) | payload[1]
    method = (bits & 0x000F) | ((bits & 0x00E0) >> 1) | ((bits & 0x3E00) >> 2)
    kind = ((bits & 0x0100) >> 7) | ((bits & 0x0010) >> 4)
    if method not in READ_ATTRIBUTES:
        return method, kind, False, None, -1
    found = _attributes(payload)
    if found is None:
        return None
    return (method, kind) + found


def _attributes(payload):
    """``(has PRIORITY, XOR-MAPPED-ADDRESS, first byte of DATA)``, or ``None`` when an
    attribute runs past the end - a real message never does, so it was not one."""
    check, mapped, carried = False, None, -1
    at, end = 20, len(payload)
    while at < end:
        kind = (payload[at] << 8) | payload[at + 1]
        size = (payload[at + 2] << 8) | payload[at + 3]
        value = at + 4
        at = value + ((size + 3) & ~3)
        if at > end:
            return None
        if kind == PRIORITY:
            check = True
        elif kind == XOR_MAPPED_ADDRESS:
            mapped = _xor_address(payload[value:value + size], payload)
        elif kind == DATA_ATTRIBUTE and size:
            carried = payload[value]
    return check, mapped, carried


def _xor_address(value, payload):
    """Decode XOR-MAPPED-ADDRESS: IPv4 is XORed with the cookie, IPv6 with the cookie
    and the transaction ID (bytes 4-19 of the header). The port is not needed."""
    if len(value) == 8 and value[1] == 0x01:
        return str(ipaddress.IPv4Address(int.from_bytes(value[4:8], "big") ^ 0x2112A442))
    if len(value) == 20 and value[1] == 0x02:
        mask = int.from_bytes(payload[4:20], "big")
        return str(ipaddress.IPv6Address(int.from_bytes(value[4:20], "big") ^ mask))
    return None


def _looks_like_media(first):
    """DTLS (20-63) or RTP/RTCP (128-191) by the first byte, RFC 9443."""
    return 20 <= first <= 63 or 128 <= first <= 191


def _channel_framed(raw, at):
    """The UDP payload at ``at`` is one TURN ChannelData frame that carries what a call
    carries: its Length (RFC 8656 section 12.4: the data alone, header and padding left
    out) matches the datagram, with or without the padding to four that UDP may add
    (section 12.5), and the data starts with STUN, DTLS or RTP. The caller has seen
    the first byte in 64-79, channel numbers 0x4000-0x4FFF.

    QUIC's short header shares that first byte for a quarter of its packets or more
    (RFC 9000/9001: 0b01 and a spin bit, the five low bits masked), but where the
    Length would stand is its connection ID - the same in every packet of a flow while
    the sizes change - so it passes about four times in 65 536. Only the lengths are
    read; the headers before ``at`` are not checked here.
    """
    if len(raw) < at + 5:
        return False
    size = ((raw[at - 4] << 8) | raw[at - 3]) - 8   # the UDP payload, by the UDP length
    length = (raw[at + 2] << 8) | raw[at + 3]
    if not length or (size != length + 4 and size != ((length + 3) & ~3) + 4):
        return False
    inner = raw[at + 4]
    return inner < 4 or 20 <= inner <= 63 or 128 <= inner <= 191


def call_part(raw):
    """Which part of a call the datagram ``raw`` is, from its bytes alone.

    ``CALL_CHECKS`` for a STUN message that is not TURN's own: Binding (connectivity
    and consent checks, keepalives, the question to a STUN server) and any other
    method, a vendor's ping included. ``CALL_TURN_CONTROL`` for Allocate, Refresh,
    CreatePermission and ChannelBind, answers and errors included. A Send or Data
    indication is what it carries (the first byte of its DATA), and so is a ChannelData
    frame with a whole STUN message in it. These prove themselves: random bytes pass
    for STUN less often than once in 2^34 (``stun``).

    ``CALL_LOOKS_MEDIA`` for DTLS or RTP by the first byte, straight or in a frame,
    which proves nothing: QUIC's short header lands in the frame's range, RFC 9287 lets
    QUIC set its fixed bit at random and so reach every other range, and VPNs run on
    DTLS. The caller asks whether the flow has carried STUN before it calls that media.

    0 for anything else, and for what cannot be read - TCP (a relay over TCP or TLS
    keeps its messages inside a stream), a fragment, an IPv6 extension header: what
    cannot be identified is no part of a call, so a scope that asked for one leaves it
    alone. Never raises, on any bytes: it runs inside ``BeanCore.decide``, where an
    exception would end the session.
    """
    start = _start(raw)
    if start < 0:
        return 0
    first = raw[start]
    # Media first and with no function called: it is most of what a call sends, and a
    # call costs ~1 us on the capture thread (memory: capture-thread-call-cost).
    if 20 <= first <= 63 or 128 <= first <= 191:
        return CALL_LOOKS_MEDIA
    if first < 4:
        message = stun(memoryview(raw)[start:_end(raw, start)])
        if message is None:
            return 0
        method, carried = message[0], message[4]
        if method in TURN_CONTROL:
            return CALL_TURN_CONTROL
        if method == SEND or method == DATA:
            # -1 when there is no DATA, which is neither
            return (CALL_CHECKS if 0 <= carried < 4
                    else CALL_MEDIA if _looks_like_media(carried) else 0)
        return CALL_CHECKS
    if 64 <= first <= 79:
        if not _channel_framed(raw, start):
            return 0
        if raw[start + 4] >= 4:
            return CALL_LOOKS_MEDIA     # the frame carries DTLS or RTP (_channel_framed)
        end = start + 4 + ((raw[start + 2] << 8) | raw[start + 3])
        return CALL_CHECKS if stun(memoryview(raw)[start + 4:end]) is not None else 0
    return 0


def _same_prefix(raw):
    """An IPv6 packet whose two ends share a /64: one link, global addresses or not.

    WebRTC often pairs two hosts on the same network by their GLOBAL IPv6 addresses,
    which a scope test alone would call the internet. Source and destination are the
    two ends whichever way the packet goes, so the direction does not matter.
    """
    return len(raw) >= 40 and raw[0] >> 4 == 6 and raw[8:16] == raw[24:32]


def endpoint(ip, port):
    """``ip:port``, with an IPv6 address in brackets."""
    return f"[{ip}]:{port}" if ":" in str(ip) else f"{ip}:{port}"


def describe(row):
    """``LAN 192.168.1.20:50000`` - a path as the event log names it."""
    return f"{row['ice']} {endpoint(row['remote_ip'], row['remote_port'])}"


class _Flow:
    """What one flow has shown so far. Only a flow that carried STUN gets one."""

    __slots__ = ("row", "turn", "check", "media", "where", "messages", "history")

    def __init__(self, row):
        self.row = row
        self.turn = self.check = self.media = False
        self.where = ""         # LAN, NAT or WAN, decided by the first check
        self.messages = 0       # ICE signalling read on this flow (SIGNAL_MAX)
        self.history = None     # `sent` at the last ticks, once a path candidate


class IceWatch:
    """The ICE label of every flow, and the path the data takes.

    ``ConnectionLog`` holds a row's remaining budget in ``row["ice_n"]`` and calls
    ``observe`` only while it is above zero, so a flow that is done - and every TCP
    or ICMP flow, which starts at zero - costs one dict read per packet. The label
    goes to ``row["ice"]``.

    A flow is done once its label is final and media has been seen on it: from then
    on it is a path candidate, and the timeline reads its delivered bytes instead.
    "Media" means DTLS or RTP, and on a relay only what the relay CARRIES: before a
    call starts, a relay carries the connectivity checks to the peer, and counting
    those as data would name the relay as the path before any data moved.

    A call that was going when the session started shows no STUN until its next
    consent check, so a flow that opens with what a call carries - media, or a
    ChannelData frame on the way to a relay - is read for longer (``PROBE_CALL``),
    and only while every packet still fits a call.
    """

    def __init__(self):
        self._reset()

    def _reset(self):
        self._flows = {}        # flowkey -> _Flow, for flows that carried STUN
        self._public = set()    # this network's public addresses (canonical text)
        self._wan = {}          # flowkey -> _Flow labelled WAN: may turn out NAT
        self._paths = {}        # flowkey -> _Flow that is done: the path candidates
        self._next_tick = 0.0
        self._active = None     # flowkey of the path with the data, or None
        self._shown = ""        # how that path was last described
        self._rival = None      # flowkey leading the active path, and for how long
        self._held = 0
        self._quiet_since = None

    def clear(self):
        """A new session: every flow, address and path is forgotten."""
        self._reset()

    def prune(self, rows):
        """Forget the flows whose rows are gone (``ConnectionLog.trim``). Walks the
        flows that carried STUN - a handful - not the rows that were dropped."""
        gone = [key for key in self._flows if key not in rows]
        for key in gone:
            del self._flows[key]
            self._wan.pop(key, None)
            self._paths.pop(key, None)

    # -- the packet path: one call per packet of a flow still being read ---- #
    def observe(self, row, key, raw, is_out):
        # THE SHORT WAY, with no header checked and no function called: an unlabelled
        # flow whose payload cannot start STUN or a ChannelData frame either buys the
        # call budget (its first packet is media), spends one (media again) or is done
        # (anything a call does not carry), whatever the headers say - a wrong verdict
        # (a fragment, an IPv6 extension header) reads a flow longer, within the budget,
        # or ends it sooner: only the label of a flow that sends such packets is at
        # stake, and calls send neither. The two fixed offsets are IPv4 without options
        # and IPv6 (28 and 48); anything else, and a frame that looks right (one call,
        # for the 64-79 bytes only), takes the full way below, which checks the headers.
        # MEASURED 2026-11-04 in the engine (CPython 3.15.2, a new UDP flow every two
        # packets, ``internal_tools`` probes ``2026-11-04-ice-path``): a Python
        # call costs ~1 us on the capture thread there, against ~50 ns in a loop of
        # its own, so the full way - three calls - for the 42% of random first bytes
        # that look like media took 10% off the pipeline's ceiling on its own.
        lead = raw[0] if raw else 0
        at = 28 if lead == 0x45 else 48 if lead >> 4 == 6 else 0
        if at and not row["ice"] and len(raw) > at:
            first = raw[at]
            framed = 64 <= first <= 79 and _channel_framed(raw, at)
            if first >= 4 and not framed:
                if not (20 <= first <= 63 or 128 <= first <= 191):
                    row["ice_n"] = 0                # nothing a call carries
                elif row["packets"] == 1:
                    row["ice_n"] = PROBE_CALL - 1   # this packet was the first of them
                else:
                    row["ice_n"] -= 1
                return
        start = _start(raw)
        if start < 0:
            row["ice_n"] -= 1       # unreadable: no evidence either way
            return
        first = raw[start]
        # A flow has a _Flow exactly when it carried STUN, and STUN labels the row at
        # once - so an unlabelled row skips the lookup (a tuple key is hashed anew on
        # every lookup, and most rows read here are never labelled).
        flow = self._flows.get(key) if row["ice"] else None
        message = stun(memoryview(raw)[start:_end(raw, start)]) if first < 4 else None
        if message is not None:
            self._on_stun(row, key, flow, message, raw, is_out)
        elif flow is not None:
            self._on_data(row, key, flow, raw, start, first)
        elif 64 <= first <= 79:
            self._on_channel(row, key, raw, start)
        elif not _looks_like_media(first):
            row["ice_n"] = 0                    # nothing a call carries (0-3: not STUN)
        elif row["packets"] == 1:
            row["ice_n"] = PROBE_CALL - 1       # this packet was the first of them
        else:
            row["ice_n"] -= 1

    def _on_channel(self, row, key, raw, start):
        """ChannelData on a flow with no label: the relay of a call that was going when
        the session started (RFC 9443 gives 64-79 to ChannelData only to or from a TURN
        server; anywhere else it is QUIC). A frame buys reading time, and only a STUN
        message inside one - the consent checks a call sends through its relay - makes
        the label. What that STUN says about addresses is not learned: an answer that
        came through the relay names the RELAY's address, not this network's."""
        if not _channel_framed(raw, start):
            row["ice_n"] = 0                    # 64-79 without a frame: QUIC, not a call
            return
        inner = raw[start + 4]
        end = start + 4 + ((raw[start + 2] << 8) | raw[start + 3])
        message = stun(memoryview(raw)[start + 4:end]) if inner < 4 else None
        if message is not None:
            flow = self._flows[key] = _Flow(row)
            flow.turn = True
            row["ice_n"] = PROBE_ICE
            self._signalled(row, flow)
            self._settle(row, key, flow, raw)
        elif inner < 4:
            row["ice_n"] = 0                    # STUN's range with no STUN in it
        elif row["packets"] == 1:
            row["ice_n"] = PROBE_CALL - 1       # this packet was the first of them
        else:
            row["ice_n"] -= 1

    def _on_stun(self, row, key, flow, message, raw, is_out):
        method, kind, check, mapped, carried = message
        if flow is None:
            flow = self._flows[key] = _Flow(row)
            # never less than a call that was going had left: a keepalive or a query
            # on it is no check, and its check is still to come
            row["ice_n"] = max(row["ice_n"], PROBE_ICE)
        self._signalled(row, flow)
        # Only an answer that came IN names this network's address. The answers this
        # machine sends name the PEER's address as this machine saw it.
        if mapped is not None and kind == SUCCESS and not is_out:
            self._learn(mapped)
        if method in TURN_METHODS:
            flow.turn = True
            flow.media = flow.media or _looks_like_media(carried)
        elif method == BINDING and kind == REQUEST and (check or not is_out):
            # A check either way. A request that comes IN is the peer's check even
            # without PRIORITY: STUN and TURN servers answer, they never ask.
            flow.check = True
        self._settle(row, key, flow, raw)

    def _on_data(self, row, key, flow, raw, start, first):
        """A packet that is not STUN, on a flow that carried STUN."""
        if flow.turn and 64 <= first <= 79 and _end(raw, start) - start > 4:
            first = raw[start + 4]      # ChannelData: what the relay carries
            if first < 4:
                self._signalled(row, flow)  # a check to the peer, through the relay
                return
        if _looks_like_media(first):
            flow.media = True
            self._settle(row, key, flow, raw)
            if row["ice"] == STUN:
                # media is no path on a flow that only asked a STUN server, so it
                # spends: a flow that never shows a check is not read for ever
                row["ice_n"] -= 1
        else:
            row["ice_n"] -= 1

    def _signalled(self, row, flow):
        flow.messages += 1
        if flow.messages >= SIGNAL_MAX:
            row["ice_n"] = 0

    def _settle(self, row, key, flow, raw):
        """Label the flow from what it has shown, and stop reading it once it is done.
        The flags only ever turn on, so a label only ever moves up: STUN, then LAN,
        NAT or WAN, then TURN."""
        if flow.turn:
            label = TURN
        elif flow.check:
            label = flow.where or self._where(key, flow, raw)
        else:
            label = STUN
        row["ice"] = label
        if flow.media and label != STUN and key not in self._paths:
            row["ice_n"] = 0
            flow.history = [row["sent"]]
            self._paths[key] = flow

    def _where(self, key, flow, raw):
        """LAN, NAT or WAN for the far end of a flow with connectivity checks."""
        remote = flow.row["remote_ip"]
        if _same_prefix(raw) or is_local_ip(remote):
            flow.where = LAN
        elif canonical_ip(remote) in self._public:
            flow.where = NAT
        else:
            flow.where = WAN
            self._wan[key] = flow
        return flow.where

    def _learn(self, address):
        """A public address of this network. A check to it that was labelled WAN
        before the answer arrived was a hairpin all along, so it becomes NAT now -
        a flow that is no longer read included."""
        if address in self._public or len(self._public) >= PUBLIC_MAX:
            return
        if is_local_ip(address):
            return
        self._public.add(address)
        hairpins = [k for k, f in self._wan.items() if canonical_ip(f.row["remote_ip"]) == address]
        for key in hairpins:
            flow = self._wan.pop(key)
            flow.where = NAT
            if flow.row["ice"] == WAN:
                flow.row["ice"] = NAT

    # -- the timeline: the watchdog thread, at most once a TICK_S ----------- #
    def tick(self, now):
        """The event log's line when the path with the data changed, else ``None``.

        The path is the candidate that delivered the most bytes over the last
        ``WINDOW_TICKS`` ticks, if that is at least ``ACTIVE_BYTES``. Delivered
        (``sent``), not offered: a path this session blocks carries nothing, and the
        timeline shows where the data really went.
        """
        if now < self._next_tick:
            return None
        self._next_tick = now + TICK_S
        if not self._paths and self._active is None:
            return None
        best, best_bytes, active_bytes = None, 0, 0
        for key, flow in self._paths.items():
            carried = _carried(flow)
            if key == self._active:
                active_bytes = carried
            if carried >= ACTIVE_BYTES and carried > best_bytes:
                best, best_bytes = key, carried
        if self._active in self._paths:
            # the label can still move from WAN to NAT under a path that is active
            self._shown = describe(self._paths[self._active].row)
        return self._decide(now, best, best_bytes, active_bytes)

    def _decide(self, now, best, best_bytes, active_bytes):
        if best is None:
            self._rival, self._held = None, 0
            return self._quiet(now)
        self._quiet_since = None
        # The active path keeps its place while it still carries data, unless the
        # leader carries more than twice as much: two calls side by side must not
        # make the path flip every tick.
        holds = active_bytes >= ACTIVE_BYTES and best_bytes <= 2 * active_bytes
        if best == self._active or holds:
            self._rival, self._held = None, 0
            return None
        if best != self._rival:
            self._rival, self._held = best, 0
        self._held += 1
        if self._held < SWITCH_TICKS:
            return None
        new = describe(self._paths[best].row)
        text = f"ICE path: {new}" if self._active is None else f"ICE path: {self._shown} -> {new}"
        self._active, self._shown = best, new
        self._rival, self._held = None, 0
        return text

    def _quiet(self, now):
        if self._active is None:
            return None
        if self._quiet_since is None:
            self._quiet_since = now
        if now - self._quiet_since < QUIET_S:
            return None
        text = f"ICE path: no data (was {self._shown})"
        self._active, self._shown, self._quiet_since = None, "", None
        return text


def _carried(flow):
    """Bytes the flow delivered over the last ``WINDOW_TICKS`` ticks, this one's
    sample taken now."""
    history = flow.history
    history.append(flow.row["sent"])
    if len(history) > WINDOW_TICKS + 1:
        del history[0]
    return history[-1] - history[0]
