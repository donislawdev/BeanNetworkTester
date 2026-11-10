"""The NAT and STUN tool: how this network's router treats a call. No tkinter.

One Start runs the jobs below, one worker run each: the panel checks Stop between
them, and a job asks ``wanted()`` before everything it sends and after each name
lookup, so Stop pressed during a slow job sends nothing more (the lesson of Ping's
first version). Over TCP and TLS it is asked once the connection is made and again
after the TLS handshake. A lookup, a connection or a handshake under way cannot be
cut short (``getaddrinfo`` has no timeout, the other two end within ``TCP_S``): a
slow resolver or server makes the stop late, and no request follows it.

1. ``addresses`` - one UDP socket asks the STUN server which address it sees (the
   public address, and whether the router kept this computer's port), then asks the
   TURN server, on its port and on a second one. One public port for all three is a
   mapping independent of the destination; another port means it depends on the
   address, or on the address and the port.
2. ``hairpin_together`` - two new sockets learn their public addresses and send to
   each other's in the same moment, ten rounds: does the router send a datagram
   meant for its own public address back in?
3. ``hairpin_first`` - two more new sockets, one side sending alone for a second
   first. A router may close the pair for good then (measured 2026-11-04: dead for
   over 35 s on the development network's router) - the race that sends two devices
   behind one router to a relay. New sockets, because that pair is spent.
4. ``turn`` - one Allocate WITHOUT credentials per transport (UDP, TCP and TLS): a
   TURN server answers it with 401, which shows it is there and reachable that way.
   Over TLS the server's certificate is checked against this computer's trusted
   roots, as a call app's TLS checks it: a certificate this computer does not trust
   is a row of its own, because a device that reads TLS on the way (a proxy or a
   firewall that inspects it) shows up exactly so.

Every socket lives inside one job, so nothing outlives a Stop.

Rules measured before this code (the analysis, 2026-11-09, on a Windows Server VM):

* Windows Firewall raises its prompt (event 5031) for a datagram that reaches a
  program's socket unasked. So a socket that may receive from somewhere it has not
  sent to first sends a datagram there with a TTL of 1: the firewall records the
  flow and the first router drops the datagram (``_open_way``).
* The hairpin jobs run only with a mapping independent of the destination: with any
  other, the port a hairpin datagram comes from is not known in advance, so the
  firewall cannot be told about it.
* The race's verdict is the rounds AFTER the lead: what the leading side sends alone
  arrives unasked, so "it did not arrive" there says nothing about the router.
* Windows reports an ICMP error for an earlier datagram (10054 port unreachable,
  10052 TTL expired - the answer to the TTL-1 datagram) on the NEXT receive of the
  socket; the receive loop takes it and waits on (``_Udp.receive``).

From the RFCs: every try of a request is the same request with the same
transaction ID (RFC 8489 section 5), and a TURN server answers a repeated Allocate
as the one it already answered (RFC 8656 section 7.2) - with a new ID it would say
437 about the relay the first try made, and that relay would stay on the server.

What it sends (the Tools tab's promise, README): a name lookup for each server, a
few STUN Binding requests to the two servers, a few dozen small datagrams to this
network's own public address, and one Allocate per TURN transport (on TCP and TLS, a
connection for that one request). Nothing before Start. The hairpin datagrams go
only to the public address the FIRST answer gave: a server that names another one
for the pair gets nothing sent there, and a "public" address on loopback or on the
link is no address at all.
"""
import errno
import ipaddress
import os
import socket
import time
from typing import NamedTuple

from .. import crashlog, stun
from ..i18n import translate
from . import Refused, ping

AREA = "nettools.nat"
OK, WARN, FAIL, SKIPPED = "ok", "warn", "fail", "skipped"

STUN_PORT = 3478
# The second port the mapping asks the TURN server on: Cloudflare's TURN answers
# Binding on UDP 3478, 443 and 53 (measured 2026-11-09).
SECOND_PORT = 443
# Each TURN transport the tool asks on, when no port was typed: the ways a call app is
# usually given a TURN server - turn: on UDP and TCP, turns: (TLS) on 5349 and 443.
TURN_TRANSPORTS = (("UDP", 3478), ("UDP", 443), ("TCP", 3478), ("TCP", 80),
                   ("TLS", 5349), ("TLS", 443))
# Where a TURN server speaks TLS rather than plain TCP: an answer that is not STUN
# there is no sign that the server is not one (the TLS row on that port says more).
TLS_PORTS = frozenset({443, 5349})
# A certificate the TLS handshake refused, by OpenSSL's verify code (X509_V_ERR_*):
# 9 not yet valid and 10 expired, 62 and 64 a name or an address it is not for. Any
# other code is a certificate this computer does not trust.
CERT_FAILURES = {9: "date", 10: "date", 62: "name", 64: "name"}
# What OpenSSL says when the other end does not speak TLS - it answered something
# else, or closed the connection on the handshake. Measured 2026-11-10 (OpenSSL 3.5,
# Windows and Linux): a STUN or HTTP answer is WRONG_VERSION_NUMBER (HTTP is
# RECORD_LAYER_FAILURE on Linux), a TURN server's plain TCP ports 3478 and 80 close
# the connection - UNEXPECTED_EOF_WHILE_READING.
NOT_TLS_REASONS = frozenset({"WRONG_VERSION_NUMBER", "RECORD_LAYER_FAILURE",
                             "UNEXPECTED_EOF_WHILE_READING", "PACKET_LENGTH_TOO_LONG",
                             "HTTP_REQUEST"})
# The error codes a STUN server that is not a TURN server gives an Allocate: Bad
# Request and Unknown Attribute (it does not know REQUESTED-TRANSPORT).
NOT_TURN_CODES = frozenset({400, 420})

TRIES_S = (0.5, 1.0, 1.5)   # the wait after each try of a UDP request: 3 s in all
TCP_S = 3.0                 # connect, send and read one answer, in all
ROUNDS = 10                 # datagrams each way in a hairpin job
ROUND_S = 0.1
SETTLE_S = 1.0              # what may still arrive after the last round
OPEN_S = 0.2                # after the TTL-1 datagrams: their ICMP answers come back
POLL_S = 0.01               # one look at one socket of a pair
RECEIVE = 4096              # the biggest datagram read (stun.MAX_MESSAGE)
MAX_PORT = 65535
# What a receive reports for an EARLIER datagram - an ICMP error (on Windows 10054
# port unreachable and 10052 TTL expired, measured) - or for one too long for the
# buffer: taken, and the wait goes on. Any other error is the socket's own and is
# raised, instead of a loop spinning on it until the deadline.
PASSING_ERRORS = frozenset({errno.ECONNRESET, errno.ENETRESET, errno.EMSGSIZE,
                            errno.ECONNREFUSED, errno.EHOSTUNREACH, errno.ENETUNREACH})

# BY_DESTINATION: another public port for another server, and the second port of
# that server silent - whether the port matters as well is not known.
INDEPENDENT, BY_ADDRESS, BY_ADDRESS_AND_PORT, BY_DESTINATION, NO_NAT = (
    "independent", "address", "address_port", "destination", "no_nat")

# Detail keys the conclusion reads back from the rows.
DETAIL_NO_NAT = "tools.nat.detail.no_nat"
DETAIL_NO_STUN = "tools.nat.detail.no_stun"
# The mapping row's Result for each mapping that depends on the destination.
DEPENDENT_RESULTS = {BY_ADDRESS: "tools.nat.result.by_address",
                     BY_ADDRESS_AND_PORT: "tools.nat.result.by_address_port",
                     BY_DESTINATION: "tools.nat.result.by_destination"}


class Server(NamedTuple):
    typed: str          # what the person typed, without the spaces around it
    host: str           # the name to look up (IDNA, lower case), or the address
    port: int
    address: str = ""   # given, or what the lookup answered
    typed_port: bool = False    # the port was typed (not the default)


class Step(NamedTuple):
    """One row of the table: a test, what it found, and its words as i18n keys."""
    test: str           # "public", "mapping", "hairpin_together", "hairpin_first", "turn"
    state: str          # OK, WARN, FAIL or SKIPPED
    result: str         # i18n key of the Result column
    detail: str         # i18n key of the Details column
    args: tuple = ()    # (name, value) pairs for the test's name, result and detail


# -- what was typed --------------------------------------------------------------- #
EMPTY = {"stun": "tools.nat.refused.empty_stun", "turn": "tools.nat.refused.empty_turn"}


def _port(text, typed):
    # The length first: int() refuses a string of over 4300 digits with a ValueError.
    if (not text.isascii() or not text.isdigit() or len(text) > len(str(MAX_PORT))
            or not 1 <= int(text) <= MAX_PORT):
        raise Refused("tools.nat.refused.port", typed=typed)
    return int(text)


def parse_server(text, which, default_port=STUN_PORT):
    """A server box's text as a ``Server`` - a name or an address, ``:port`` after it
    (an IPv6 address in brackets then) - or ``Refused`` saying why it is not one.
    ``which`` is "stun" or "turn", for the empty box's sentence. UI thread: nothing
    here is slow and nothing is sent."""
    typed = (text or "").strip()
    if not typed:
        raise Refused(EMPTY[which])
    host, port_text, bracketed = typed, "", typed.startswith("[")
    if bracketed:
        close = typed.find("]")
        rest = typed[close + 1:] if close > 0 else "?"
        if rest and not rest.startswith(":"):
            raise Refused("tools.nat.refused.bad_server", typed=typed)
        host, port_text = typed[1:close], rest[1:]
        if rest == ":":
            raise Refused("tools.nat.refused.port", typed=typed)
    elif typed.count(":") == 1:
        host, port_text = typed.split(":")
        if not port_text:
            raise Refused("tools.nat.refused.port", typed=typed)
    port = _port(port_text, typed) if port_text else default_port
    # Ping's reading of a name or an address, in this tool's words.
    try:
        target = ping.parse(host)
    except Refused:
        raise Refused("tools.nat.refused.bad_server", typed=typed) from None
    if bracketed and ":" not in target.address:
        raise Refused("tools.nat.refused.bad_server", typed=typed)
    return Server(typed, target.name or target.address, port, target.address,
                  typed_port=bool(port_text))


def turn_transports(server):
    """The TURN transports to ask: the usual six, or a typed port on UDP, TCP and TLS."""
    if server.typed_port:
        return (("UDP", server.port), ("TCP", server.port), ("TLS", server.port))
    return TURN_TRANSPORTS


# -- the system ------------------------------------------------------------------- #
def _canonical(address):
    """An address as ``ipaddress`` writes it, without an IPv6 zone - how a source
    and a server are compared."""
    return str(ipaddress.ip_address(address.split("%")[0]))


def _here_only(address):
    """An address that never leaves this computer or its link (loopback,
    link-local), an IPv4 one written as IPv6 included: no router's public address."""
    found = ipaddress.ip_address(address)
    found = getattr(found, "ipv4_mapped", None) or found
    return found.is_loopback or found.is_link_local


class _Udp:
    """One UDP socket of a job, bound to one address of this computer."""

    def __init__(self, family, address):
        self.family = family
        self.sock = socket.socket(family, socket.SOCK_DGRAM)
        try:
            # The address the routing table picks towards the server (``Run._socket``):
            # every datagram leaves from it, so the router sees ONE internal endpoint -
            # what a NAT mapping is defined for (RFC 4787) - and the answers and the
            # hairpin datagrams come back to it. Never every address: the socket would
            # take datagrams on any network this computer is on. Measured on a Windows
            # Server VM with firewall auditing (2026-11-10): a whole run bound this way
            # raised no firewall prompt (no event 5031) and made no rule, and gave the
            # rows the wildcard bind gave there the day before.
            self.sock.bind((address, 0))
        except OSError:
            self.sock.close()
            raise
        self.port = self.sock.getsockname()[1]

    def send(self, data, to, ttl=None):
        if ttl is None:
            self.sock.sendto(data, to)
            return
        option = ((socket.IPPROTO_IPV6, socket.IPV6_UNICAST_HOPS)
                  if self.family == socket.AF_INET6 else (socket.IPPROTO_IP, socket.IP_TTL))
        before = self.sock.getsockopt(*option)
        self.sock.setsockopt(*option, ttl)
        try:
            self.sock.sendto(data, to)
        finally:
            self.sock.setsockopt(*option, before)

    def receive(self, timeout):
        """``(data, (address, port))`` that arrived within ``timeout`` s, or None.

        An error reported for an earlier datagram (``PASSING_ERRORS``: 10054 and
        10052 on Windows) - or a datagram too long for the buffer (10040) - is taken
        and the wait goes on; the deadline still bounds it. Any other error is
        raised: a socket that fails every receive would otherwise spin a core until
        the deadline. A timeout on the socket rather than ``select``: no limit on
        the descriptor's number (Linux's ``select`` stops at 1024)."""
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            self.sock.settimeout(left)
            try:
                data, source = self.sock.recvfrom(RECEIVE)
            except TimeoutError:
                return None
            except OSError as error:
                if error.errno not in PASSING_ERRORS:
                    raise
                continue
            return data, (_canonical(source[0]), source[1])
        return None

    def close(self):
        self.sock.close()


def _read(conn, size, deadline):
    """``size`` bytes from a stream before ``deadline``; None when it closes first."""
    data = b""
    while len(data) < size:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError
        conn.settimeout(left)
        chunk = conn.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def _connect(conn, address, port, timeout):
    """Connect a stream socket: None, or what failed ("refused", "no_connection")."""
    conn.settimeout(timeout)
    try:
        conn.connect((address, port))
    except ConnectionRefusedError:
        return "refused"
    except OSError:
        return "no_connection"
    return None


def _ask_stream(conn, data, deadline, wanted):
    """Send one request on a connected stream (TCP, or TLS over it) and read one STUN
    message back: ``(what, answer bytes)`` as ``_Net.tcp_ask`` says them. ``wanted()``
    is asked first: a Stop pressed while the connection was being made sends nothing."""
    if not wanted():
        return "stopped", b""
    try:
        conn.sendall(data)
        head = _read(conn, stun.HEADER, deadline)
        total = stun.stream_length(head) if head else None
        if total is None:
            return "not_stun", b""
        rest = _read(conn, total - stun.HEADER, deadline)
    except OSError:
        return "no_answer", b""
    return ("answer", head + rest) if rest is not None else ("not_stun", b"")


class _Net:
    """The system's resolver and sockets - what the tests replace (``portmap._Native``)."""

    @staticmethod
    def lookup(name, port):
        return [(family, where[0]) for family, _kind, _proto, _canonical_name, where
                in socket.getaddrinfo(name, port, type=socket.SOCK_DGRAM)]

    @staticmethod
    def udp(family, address):
        return _Udp(family, address)

    @staticmethod
    def route_source(family, address):
        """This computer's address towards ``address``: a connected UDP socket only
        asks the routing table, nothing is sent (``utils._route_source_ip``'s way,
        written here so the tab's promise reads only this tool's sockets)."""
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as probe:
                probe.connect((address, STUN_PORT))
                return _canonical(probe.getsockname()[0])
        except (OSError, ValueError):
            return None

    @staticmethod
    def tcp_ask(family, address, port, data, timeout, wanted):
        """One request on a new TCP connection: ``(what, answer bytes)`` - what is
        "answer", "refused", "no_connection", "no_answer", "not_stun", or "stopped"
        when ``wanted()`` says no once the connection is made (nothing is sent then).
        Every read is bounded (``stun.MAX_MESSAGE``) and the whole exchange takes
        ``timeout`` s at most. Closing the connection ends an allocation made on it
        (RFC 8656)."""
        deadline = time.monotonic() + timeout
        with socket.socket(family, socket.SOCK_STREAM) as conn:
            failed = _connect(conn, address, port, timeout)
            return (failed, b"") if failed else _ask_stream(conn, data, deadline, wanted)

    @staticmethod
    def tls_ask(family, address, port, name, data, timeout, wanted):
        """``tcp_ask`` inside TLS, to ``name`` - the server's name as typed: the name the
        handshake sends (SNI) and the one its certificate must be for. The certificate
        is checked against this computer's trusted roots, as a call app's TLS checks it
        (``ssl.create_default_context``, the one way this package makes a TLS context:
        tests/test_no_telemetry.py). Besides ``tcp_ask``'s answers, what is "untrusted",
        "name" or "date" (the certificate), "reset" (cut during the handshake),
        "not_tls", "tls_failed", or "no_tls" when this system has no TLS library this
        program can load. ``wanted()`` is asked before the handshake as well, which
        sends the name. ``ssl`` is imported here, so opening the NAT and STUN panel does
        not load OpenSSL: the first TLS row does."""
        try:
            import ssl
        except ImportError:
            return "no_tls", b""
        deadline = time.monotonic() + timeout
        with socket.socket(family, socket.SOCK_STREAM) as raw:
            failed = _connect(raw, address, port, timeout)
            if failed:
                return failed, b""
            if not wanted():
                return "stopped", b""
            raw.settimeout(max(deadline - time.monotonic(), POLL_S))
            try:
                conn = ssl.create_default_context().wrap_socket(raw, server_hostname=name)
            except ssl.SSLCertVerificationError as error:
                return CERT_FAILURES.get(error.verify_code, "untrusted"), b""
            except ssl.SSLError as error:
                not_tls = isinstance(error, ssl.SSLEOFError) or error.reason in NOT_TLS_REASONS
                return ("not_tls" if not_tls else "tls_failed"), b""
            except (ConnectionResetError, ConnectionAbortedError):
                return "reset", b""
            except OSError:
                return "no_answer", b""
            with conn:
                return _ask_stream(conn, data, deadline, wanted)


def _family(address):
    return socket.AF_INET6 if ":" in address else socket.AF_INET


def lookup(server, net):
    """``server`` with its address, or None when the name gives none. IPv4 first: NAT
    is an IPv4 matter, and a name with both is asked the way a call would try it."""
    if server.address:
        return server
    try:
        answers = net.lookup(server.host, server.port)
    except (OSError, UnicodeError):
        return None
    for family in (socket.AF_INET, socket.AF_INET6):
        for found, address in answers:
            if found == family:
                return server._replace(address=_canonical(address))
    return None


# -- the verdicts, as data --------------------------------------------------------- #
def mapping_verdict(first, second, third):
    """How the router maps one socket: the public ``(address, port)`` the STUN server
    saw (``first``), the TURN server on its port (``second``) and on the second port
    (``third``, None when that port did not answer).

    One port for two addresses is independent even without ``third``: a mapping
    that depends on the address, or on the address and the port, changes with the
    address. Another port for the other address with ``third`` missing says only
    that it depends on the destination - whether on the port too was not seen."""
    if second != first:
        if third is None:
            return BY_DESTINATION
        return BY_ADDRESS if third == second else BY_ADDRESS_AND_PORT
    if third is None or third == first:
        return INDEPENDENT
    return BY_ADDRESS_AND_PORT


def conclusion(rows, transports=()):
    """The plain-words answer drawn from a run's rows: a tuple of i18n keys.

    ``transports`` are the run's TURN transports (``Run.transports``): "no TURN" is
    said only when EVERY one of them was checked and failed. A run stopped half way
    has rows "not checked" there, and a run still going has none yet - one failed
    transport says nothing about the others."""
    by = {row.test: row for row in rows if row.test != "turn"}
    public, mapping = by.get("public"), by.get("mapping")
    together, first = by.get("hairpin_together"), by.get("hairpin_first")
    keys = []
    if public is None or public.state == SKIPPED:
        pass
    elif public.state == FAIL:
        # Only a server that said nothing is a sign that UDP is blocked here; a name
        # that was not found or a socket the system refused say so in their row.
        if public.detail == DETAIL_NO_STUN:
            keys.append("tools.nat.conclusion.no_stun")
    elif public.detail == DETAIL_NO_NAT:
        keys.append("tools.nat.conclusion.no_nat")
    elif mapping is None or mapping.state in (SKIPPED, FAIL):
        keys.append("tools.nat.conclusion.unknown")
    elif mapping.state == WARN:
        keys.append("tools.nat.conclusion.dependent")
    elif together is None or together.state in (SKIPPED, FAIL):
        keys.append("tools.nat.conclusion.independent")
    elif together.state != OK:
        keys.append("tools.nat.conclusion.no_hairpin")
    elif first is not None and first.state == OK:
        keys.append("tools.nat.conclusion.hairpin")
    elif first is not None and first.state == WARN:
        keys.append("tools.nat.conclusion.together_only")
    else:
        keys.append("tools.nat.conclusion.together")
    turn = _turn_conclusion(rows, transports)
    return tuple(keys) + ((turn,) if turn else ())


def _all_failed(states):
    """True when there are rows and every one was checked and failed."""
    return bool(states) and all(state == FAIL for state in states)


def _turn_conclusion(rows, transports):
    """What the TURN rows say together, as an i18n key, or None. Each claim needs
    every transport it is about checked and failed: "only over TLS" needs every UDP
    and every TCP transport failed and a TLS one answering. A row not there yet, or
    "not checked", is not a failure."""
    turn = {row.args[:2]: row.state for row in rows if row.test == "turn"}
    states = {}
    for kind, port in transports:
        states.setdefault(kind, []).append(turn.get(_turn_args(kind, port)))
    if _all_failed([state for found in states.values() for state in found]):
        return "tools.nat.conclusion.no_turn"
    if not _all_failed(states.get("UDP", [])):
        return None
    if _all_failed(states.get("TCP", [])) and OK in states.get("TLS", ()):
        return "tools.nat.conclusion.turn_tls_only"
    if any(OK in states.get(kind, ()) for kind in ("TCP", "TLS")):
        return "tools.nat.conclusion.turn_no_udp"
    return None


def _skipped(test, detail, args=()):
    return Step(test, SKIPPED, "tools.nat.result.not_checked", detail, args)


def _turn_args(transport, port):
    return (("transport", transport), ("port", port))


def _endpoint(found, first):
    """A public ``(address, port)`` as the mapping row writes it: the port alone when
    the address is the first answer's, else both."""
    return str(found[1]) if found[0] == first[0] else f"{found[0]} {found[1]}"


def _hairpin_words(arrived, sources, lead):
    """The row of a hairpin job from what each socket received in the rounds."""
    test = "hairpin_first" if lead else "hairpin_together"
    low = min(arrived)
    args = (("n", low), ("a", arrived[0]), ("b", arrived[1]), ("of", ROUNDS))
    if low:
        detail = {"public": "tools.nat.detail.hairpin_ok",
                  "lan": "tools.nat.detail.hairpin_lan"}.get(sources, "tools.nat.detail.hairpin_other")
        return Step(test, OK, "tools.nat.result.works", detail, args)
    if max(arrived):
        return Step(test, WARN, "tools.nat.result.one_way", "tools.nat.detail.hairpin_one_way",
                    args)
    detail = "tools.nat.detail.hairpin_after_first" if lead else "tools.nat.detail.hairpin_none"
    return Step(test, WARN, "tools.nat.result.fails", detail, args)


def _turn_words(message, transport, port, ms):
    """The row of a TURN transport from its answer (a decoded message)."""
    args = _turn_args(transport, port) + (("ms", ms),)
    if message.kind == stun.SUCCESS:
        return Step("turn", OK, "tools.nat.result.answers", "tools.nat.detail.turn_open", args)
    code = stun.error_code(message)
    if code == 401:
        return Step("turn", OK, "tools.nat.result.answers", "tools.nat.detail.turn_answers", args)
    if code is None or code in NOT_TURN_CODES:
        return Step("turn", FAIL, "tools.nat.result.not_turn", "tools.nat.detail.stun_not_turn",
                    args + (("code", code if code is not None else "-"),))
    return Step("turn", OK, "tools.nat.result.answers", "tools.nat.detail.turn_code",
                args + (("code", code),))


# A TCP or TLS transport that gave no TURN answer: (Result, Details) by what happened
# (``_Net.tcp_ask`` and ``_Net.tls_ask``). "tls" is a TCP port where TURN usually
# speaks TLS; anything not named is something that is not a TURN server.
STREAM_WORDS = {
    "refused": ("tools.nat.result.refused", "tools.nat.detail.refused"),
    "no_connection": ("tools.nat.result.no_answer", "tools.nat.detail.no_connection"),
    "no_answer": ("tools.nat.result.no_answer", "tools.nat.detail.no_answer"),
    "not_stun": ("tools.nat.result.not_turn", "tools.nat.detail.not_turn"),
    "tls": ("tools.nat.result.not_turn", "tools.nat.detail.not_turn_tls"),
    "untrusted": ("tools.nat.result.certificate", "tools.nat.detail.tls_untrusted"),
    "name": ("tools.nat.result.certificate", "tools.nat.detail.tls_name"),
    "date": ("tools.nat.result.certificate", "tools.nat.detail.tls_date"),
    "reset": ("tools.nat.result.cut", "tools.nat.detail.tls_reset"),
    "not_tls": ("tools.nat.result.no_tls", "tools.nat.detail.not_tls"),
    "tls_failed": ("tools.nat.result.tls_failed", "tools.nat.detail.tls_failed"),
}


def _relay_left(message):
    """Whether an Allocate answer leaves a relay of ours on the server: a success,
    or 437 - this 5-tuple has one already, which on a new socket only an earlier
    try of ours made (a server that does not take a repeated request as the one it
    answered)."""
    return message.kind == stun.SUCCESS or stun.error_code(message) == 437


class _Heard:
    """What a hairpin pair received, kept small: each round datagram once per socket
    (``ROUNDS`` at most) and the kinds of address they came from. Anything else - a
    duplicate, a stranger's datagram, a TTL-1 one delivered here - is dropped as it
    arrives, so a flood costs time, never memory."""

    def __init__(self, token, public, local):
        self.rounds = frozenset(token + b":P%d" % i for i in range(ROUNDS))
        self.public, self.local = public, local
        self.got = (set(), set())       # a session that duplicates must not make 11 of 10
        self.kinds = set()

    def take(self, index, found):
        data, source = found
        if data not in self.rounds:
            return
        self.got[index].add(data)
        # A datagram for socket ``index`` comes from the other one's public address.
        if source == tuple(self.public[1 - index]):
            self.kinds.add("public")
        elif source[0] == self.local:
            self.kinds.add("lan")
        else:
            self.kinds.add("other")

    def arrived(self):
        return [len(got) for got in self.got]

    def source(self):
        """Where the counted datagrams came from: "public", "lan" or "other"."""
        return next((kind for kind in ("public", "lan", "other") if kind in self.kinds), "")


# -- one run ---------------------------------------------------------------------- #
class Run:
    """One Start: its servers, the jobs still to run, and what the jobs found.

    Only the worker touches it while a job runs; the panel reads it between jobs
    (``ToolJob`` runs one at a time and delivers each answer on the UI thread). The
    one exception is ``stop``, a flag the running job reads before each send.
    """

    def __init__(self, stun_server, turn_server, net=None):
        self.stun, self.turn = stun_server, turn_server
        self.net = net or _Net()
        self.started = time.time()
        self.token = os.urandom(6).hex().encode()   # this run's datagrams, and no others
        self.transports = turn_transports(turn_server)
        self.jobs = (("addresses",), ("hairpin", False), ("hairpin", True)) + tuple(
            ("turn", transport, port) for transport, port in self.transports)
        self.next = 0
        self.rows = []
        self.stopped = False
        self.stun_at = self.turn_at = None
        self.public = self.local = None             # (address, port), address
        self.mapping = None
        # The UDP flows this run sent on, as the connection log keys them (local port,
        # remote address, remote port): what the panel asks the session about.
        self.flows = set()

    def done(self):
        return self.stopped or self.next >= len(self.jobs)

    def step(self, wanted=None):
        """WORKER: run the next job; keep its rows and return them (``()`` when Stop
        came first). ``wanted()`` is the panel's own say on top of ``stop``."""
        def ask():
            return not self.stopped and (wanted is None or wanted())
        if self.done() or not ask():
            return ()
        job = self.jobs[self.next]
        self.next += 1
        expected = self._expected(job)
        if job[0] == "addresses":
            rows = self._addresses(ask)
        elif job[0] == "hairpin":
            rows = self._hairpin(job[1], ask)
        else:
            rows = self._turn(job[1], job[2], ask)
        found = []
        try:
            found.extend(rows)
        except OSError:
            # The system would not give a socket or would not send (no route, no IPv6
            # on this computer): the job's rows say so instead of the run failing.
            have = {(row.test, self._key(row)) for row in found}
            missing = [entry for entry in expected if entry not in have]
            for index, (test, args) in enumerate(missing):
                found.append(Step(test, FAIL, "tools.nat.result.no_answer",
                                  "tools.nat.detail.send_failed", args) if not index
                             else _skipped(test, "tools.nat.detail.needs_public", args))
        self.rows.extend(found)
        return tuple(found)

    def stop(self):
        """Any thread: the running job sends nothing more and no job starts."""
        self.stopped = True

    @staticmethod
    def _key(row):
        return row.args[:2] if row.test == "turn" else ()

    @staticmethod
    def _expected(job):
        """The rows a job gives, as ``(test, args)``."""
        if job[0] == "addresses":
            return [("public", ()), ("mapping", ())]
        if job[0] == "hairpin":
            return [("hairpin_first" if job[1] else "hairpin_together", ())]
        return [("turn", _turn_args(job[1], job[2]))]

    def not_checked(self):
        """The rows no job gave, as "not checked (stopped)" - after a Stop, once the
        job that was running has delivered its rows."""
        have = {(row.test, self._key(row)) for row in self.rows}
        return tuple(_skipped(test, "tools.nat.detail.stopped", args)
                     for job in self.jobs for test, args in self._expected(job)
                     if (test, args) not in have)

    # -- asking a server ---------------------------------------------------------- #
    def _exchange(self, sock, address, port, build, method, wanted):
        """``(message, ms)``: an answer to our request, from that server only, or None
        after every try. Every try sends the same request, transaction ID included
        (the module's docstring: RFC 8489 and 8656). The time runs from the first
        try - which try was answered cannot be told - so it is how long a client
        waited. A send the system refuses raises."""
        address = _canonical(address)
        transaction = stun.transaction_id()
        request = build(transaction)
        began = time.monotonic()
        for wait in TRIES_S:
            if not wanted():
                return None
            sock.send(request, (address, port))
            self.flows.add((sock.port, address, port))
            deadline = time.monotonic() + wait
            while (left := deadline - time.monotonic()) > 0:
                got = sock.receive(left)
                if got is None:
                    break
                data, source = got
                if source != (address, port):
                    continue
                message = stun.decode(data)
                if (message is None or message.method != method
                        or message.transaction != transaction
                        or message.kind not in (stun.SUCCESS, stun.ERROR)):
                    continue
                return message, round((time.monotonic() - began) * 1000)
        return None

    def _mapped(self, sock, server, port, wanted):
        """``(public (address, port) or None, whether the server answered at all)``.

        An answer that is an error, or carries no usable address of this socket's
        family, gives no address: the tool would send to it."""
        answer = self._exchange(sock, server.address, port, stun.binding_request,
                                stun.BINDING, wanted)
        if answer is None:
            return None, False
        found = stun.mapped_address(answer[0]) if answer[0].kind == stun.SUCCESS else None
        if found is not None and _family(found[0]) != sock.family:
            found = None
        if found is not None and found[0] != self.local and _here_only(found[0]):
            # A lying or broken server: the hairpin pair would send to a service of
            # this computer or of its link. This computer's own address is kept - on
            # loopback, or with no NAT on a link-local network, that is the answer.
            found = None
        return found, True

    def _no_address(self, test, answered):
        """The row of a STUN question that gave no address."""
        if answered:
            return Step(test, FAIL, "tools.nat.result.no_address", "tools.nat.detail.no_address")
        return Step(test, FAIL, "tools.nat.result.no_answer", DETAIL_NO_STUN,
                    (("s", f"{sum(TRIES_S):g}"),))

    def _socket(self, family, toward):
        """``(socket, this computer's address)``: a socket bound to the address the
        routing table picks towards ``toward``. No route there is an OSError, which
        ``step`` turns into the job's rows like any other refusal of the system."""
        local = self.net.route_source(family, toward)
        if local is None:
            raise OSError(errno.ENETUNREACH, "no route to the server")
        return self.net.udp(family, local), local

    # -- the jobs ----------------------------------------------------------------- #
    def _addresses(self, wanted):
        # Stop is read after each lookup (the module's docstring): the rows of a run
        # stopped here say "not checked".
        self.stun_at = lookup(self.stun, self.net)
        if not wanted():
            return
        self.turn_at = lookup(self.turn, self.net)
        if not wanted():
            return
        if self.stun_at is None:
            yield Step("public", FAIL, "tools.nat.result.not_found", "tools.nat.detail.not_found",
                       (("name", self.stun.typed),))
            yield _skipped("mapping", "tools.nat.detail.needs_public")
            return
        family = _family(self.stun_at.address)
        sock, self.local = self._socket(family, self.stun_at.address)
        try:
            yield from self._public_and_mapping(sock, family, wanted)
        finally:
            sock.close()

    def _public_and_mapping(self, sock, family, wanted):
        first, answered = self._mapped(sock, self.stun_at, self.stun_at.port, wanted)
        if not wanted():
            return
        if first is None:
            yield self._no_address("public", answered)
            yield _skipped("mapping", "tools.nat.detail.needs_public")
            return
        self.public = first
        args = (("address", first[0]), ("port", first[1]), ("local", self.local),
                ("local_port", sock.port))
        if first[0] == self.local:
            self.mapping = NO_NAT
            yield Step("public", OK, "tools.nat.result.address", DETAIL_NO_NAT, args)
            yield _skipped("mapping", "tools.nat.detail.no_nat_mapping")
            return
        kept = "tools.nat.detail.port_kept" if first[1] == sock.port else "tools.nat.detail.port_changed"
        yield Step("public", OK, "tools.nat.result.address", kept, args)
        yield from self._mapping(sock, family, first, wanted)

    def _mapping(self, sock, family, first, wanted):
        if self.turn_at is None:
            yield Step("mapping", FAIL, "tools.nat.result.not_found", "tools.nat.detail.not_found",
                       (("name", self.turn.typed),))
            return
        if _family(self.turn_at.address) != family:
            yield _skipped("mapping", "tools.nat.detail.other_family")
            return
        if _canonical(self.turn_at.address) == _canonical(self.stun_at.address):
            # Asked twice at one address, any router gives the same port: the answer
            # would say "independent" without having looked.
            yield _skipped("mapping", "tools.nat.detail.same_server")
            return
        second, _answered = self._mapped(sock, self.turn_at, self.turn_at.port, wanted)
        if not wanted():
            return
        if second is None:
            yield _skipped("mapping", "tools.nat.detail.second_silent",
                           (("name", self.turn.typed),))
            return
        other = SECOND_PORT if self.turn_at.port != SECOND_PORT else STUN_PORT
        third, _answered = self._mapped(sock, self.turn_at, other, wanted)
        if not wanted():
            return
        self.mapping = mapping_verdict(first, second, third)
        args = (("first", _endpoint(first, first)), ("second", _endpoint(second, first)),
                ("third", _endpoint(third, first) if third else "-"), ("other", other))
        if self.mapping == INDEPENDENT:
            detail = ("tools.nat.detail.independent" if third else
                      "tools.nat.detail.independent_address")
            yield Step("mapping", OK, "tools.nat.result.independent", detail, args)
        else:
            result = DEPENDENT_RESULTS[self.mapping]
            detail = "tools.nat.detail.dependent" if third else "tools.nat.detail.dependent_partial"
            yield Step("mapping", WARN, result, detail, args)

    def _hairpin_blocker(self, lead):
        """Why this hairpin job cannot tell anything here, as a detail key - or None."""
        if self.public is None:
            return "tools.nat.detail.needs_public"
        if self.mapping == NO_NAT:
            return "tools.nat.detail.no_nat_hairpin"
        if self.mapping is None:
            return "tools.nat.detail.needs_mapping"
        if self.mapping != INDEPENDENT:
            return "tools.nat.detail.dependent_hairpin"
        together = next((row for row in self.rows if row.test == "hairpin_together"), None)
        if lead and (together is None or together.state != OK):
            return "tools.nat.detail.together_failed"
        return None

    def _hairpin(self, lead, wanted):
        test = "hairpin_first" if lead else "hairpin_together"
        blocker = self._hairpin_blocker(lead)
        if blocker:
            yield _skipped(test, blocker)
            return
        family = _family(self.stun_at.address)
        socks = []
        try:
            # On the address the first job's socket had: its answer is the public
            # address the pair must see again.
            socks.append(self.net.udp(family, self.local))
            socks.append(self.net.udp(family, self.local))
            yield from self._pair(test, socks, lead, wanted)
        finally:
            for sock in socks:
                sock.close()

    def _pair(self, test, socks, lead, wanted):
        public = []
        for sock in socks:
            found, answered = self._mapped(sock, self.stun_at, self.stun_at.port, wanted)
            if not wanted():
                return
            if found is None:
                yield self._no_address(test, answered)
                return
            public.append(found)
        if any(found[0] != self.public[0] for found in public):
            # Only the address the first answer gave gets the datagrams.
            yield _skipped(test, "tools.nat.detail.other_address")
            return
        a, b = socks
        heard = _Heard(self.token, public, self.local)
        self.flows.update(((a.port, *public[1]), (b.port, *public[0])))
        self._open_way(socks, public)
        self._drain(socks, heard, OPEN_S)
        if lead:
            # b alone: a has sent nothing to b but the TTL-1 datagrams the router
            # dropped - for the router, these come unasked.
            for i in range(ROUNDS):
                if not wanted():
                    return
                b.send(self.token + b":L%d" % i, public[0])
                self._drain(socks, heard, ROUND_S)
        for i in range(ROUNDS):
            if not wanted():
                return
            a.send(self.token + b":P%d" % i, public[1])
            b.send(self.token + b":P%d" % i, public[0])
            self._drain(socks, heard, ROUND_S)
        self._drain(socks, heard, SETTLE_S)
        yield _hairpin_words(heard.arrived(), heard.source(), lead)

    def _open_way(self, socks, public):
        """Each socket tells this computer's firewall about every address the other
        one's datagrams can come from - its public one, and its local one for a router
        that hairpins with the source unchanged - with datagrams the first router drops
        (TTL 1). To the local address they are delivered here, and not counted."""
        for me, other in ((0, 1), (1, 0)):
            socks[me].send(self.token + b":o", public[other], ttl=1)
            socks[me].send(self.token + b":o", (self.local, socks[other].port), ttl=1)

    @staticmethod
    def _drain(socks, heard, wait):
        """Hand what reaches ``socks`` for ``wait`` s to ``heard`` (``_Heard``), a
        short look at each socket in turn."""
        deadline = time.monotonic() + wait
        while (left := deadline - time.monotonic()) > 0:
            for index, sock in enumerate(socks):
                found = sock.receive(min(left, POLL_S))
                if found is not None:
                    heard.take(index, found)

    def _turn(self, transport, port, wanted):
        args = _turn_args(transport, port)
        if self.turn_at is None:
            yield Step("turn", FAIL, "tools.nat.result.not_found", "tools.nat.detail.not_found",
                       args + (("name", self.turn.typed),))
            return
        family = _family(self.turn_at.address)
        if transport == "UDP":
            yield from self._turn_udp(family, port, args, wanted)
            return
        if not wanted():
            return
        transaction = stun.transaction_id()
        request = stun.allocate_request(transaction)
        began = time.monotonic()
        if transport == "TLS":
            what, data = self.net.tls_ask(family, self.turn_at.address, port, self.turn.host,
                                          request, TCP_S, wanted)
        else:
            what, data = self.net.tcp_ask(family, self.turn_at.address, port, request, TCP_S,
                                          wanted)
        if what == "stopped":
            return              # the rows of a run stopped here say "not checked"
        ms = round((time.monotonic() - began) * 1000)
        if what == "answer":
            message = stun.decode(data)
            if (message is not None and message.method == stun.ALLOCATE
                    and message.transaction == transaction
                    and message.kind in (stun.SUCCESS, stun.ERROR)):
                yield _turn_words(message, transport, port, ms)
                return
            what = "not_stun"
        if what == "no_tls":
            yield _skipped("turn", "tools.nat.detail.no_tls_here", args)
            return
        if what == "not_stun" and transport == "TCP" and port in TLS_PORTS:
            what = "tls"
        result, detail = STREAM_WORDS.get(what, STREAM_WORDS["not_stun"])
        yield Step("turn", FAIL, result, detail,
                   args + (("s", f"{TCP_S:g}"), ("name", self.turn.host)))

    def _turn_udp(self, family, port, args, wanted):
        sock, _local = self._socket(family, self.turn_at.address)
        try:
            answer = self._exchange(sock, self.turn_at.address, port, stun.allocate_request,
                                    stun.ALLOCATE, wanted)
            if answer is not None and _relay_left(answer[0]):
                # A relay handed out without a login: given back at once, from the
                # socket it belongs to, instead of left on the server for minutes.
                # Best effort: the answer is what the row reports either way.
                with crashlog.quiet(AREA):
                    sock.send(stun.release_request(stun.transaction_id()),
                              (_canonical(self.turn_at.address), port))
        finally:
            sock.close()
        if answer is not None:
            yield _turn_words(answer[0], "UDP", port, answer[1])
        elif wanted():
            yield Step("turn", FAIL, "tools.nat.result.no_answer", "tools.nat.detail.no_answer",
                       args + (("s", f"{sum(TRIES_S):g}"),))


# -- the copied results ----------------------------------------------------------- #
ROW_NAMES = {"public": "tools.nat.row.public", "mapping": "tools.nat.row.mapping",
             "hairpin_together": "tools.nat.row.hairpin_together",
             "hairpin_first": "tools.nat.row.hairpin_first", "turn": "tools.nat.row.turn"}


def words(row, lang=None):
    """``(test, result, detail)`` of a row in ``lang`` (the window's when None)."""
    args = dict(row.args)
    return (translate(ROW_NAMES[row.test], lang, **args),
            translate(row.result, lang, **args), translate(row.detail, lang, **args))


def report(run, rows):
    """The run as text for the clipboard - in English, like the tab's other reports.
    It carries this network's public address: copied only when the person asks."""
    at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run.started))
    lines = [f"NAT and STUN, started {at}",
             f"STUN server: {run.stun.typed}" + (f" ({run.stun_at.address})" if run.stun_at else ""),
             f"TURN server: {run.turn.typed}" + (f" ({run.turn_at.address})" if run.turn_at else "")]
    for row in rows:
        test, result, detail = words(row, "en")
        lines.append(f"{test}: {result} - {detail}")
    said = " ".join(translate(key, "en") for key in conclusion(rows, run.transports))
    if said:
        lines.append(f"Conclusion: {said}")
    if run.stopped:
        lines.append("(stopped before the end)")
    return "\n".join(lines)
