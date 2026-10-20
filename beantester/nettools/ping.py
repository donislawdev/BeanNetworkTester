"""Ping: what the Tools tab's Ping is asked, what it keeps and what it says - no tkinter.

"Does my 200 ms of latency and 5% of loss really reach the traffic?" The question a
tester used to answer with ``ping -t`` in another window, asked from inside the
program that impairs. Sending one request is ``icmp.py``'s; this module decides TO
WHAT (``parse``, ``resolve``) and keeps what came back (``Run``).

What is sent, and where, is the promise this tool is held to (README, "Tools"):
echo requests to the address the person typed, from Start to Stop. So a text that
is not plainly an address or a host name is refused HERE, before anything could
send it anywhere: ``999.1.1.1`` and ``127.1`` are refused rather than handed to the
name lookup, which would put a DNS query for them on the wire. A name is looked up
once, at Start, by Windows (``getaddrinfo``: the hosts file, its cache, then its DNS
servers), and the address it gave is shown, because a name with an IPv6 address
first may not be pinged where the person thinks.

What the numbers mean under a session (measured 2026-10-19, ``icmp.py``): a ping is
a request out and a reply in, so with the two-way traffic filter it carries the
latency twice and loses a packet twice as often - 20% of loss lost about a third of
the pings.
"""
import collections
import ipaddress
import re
import socket
import time
from typing import NamedTuple

from .. import icmp
from . import Refused
from .adapters import Words

# The choices the window offers, in seconds. The wait is whole seconds because
# Windows keeps nothing finer (``icmp.py``: it waits in steps of half a second,
# rounded down). The fastest pace is five a second: a ping is a question, not a load.
EVERY_S = (0.2, 0.5, 1, 2, 5)
DEFAULT_EVERY_S = 1
WAIT_S = (1, 2, 4, 10, 30)
DEFAULT_WAIT_S = 4          # ping.exe's
KEPT = 3600                 # an hour at one a second; the totals count every ping
CHARTED = 60

MAX_NAME = 253
_LABEL = re.compile(r"(?!-)[A-Za-z0-9_-]{1,63}(?<!-)\Z")
# A last label that is a number is no host name (RFC 3696, 2: a top-level domain is
# never all digits) - it is an address the person mistyped.
_NUMERIC = re.compile(r"(?:[0-9]+|0x[0-9a-f]*)\Z", re.IGNORECASE)

REPLY, CHANGED, LOST, FAILED = "reply", "changed", "lost", "failed"
STATUS_WORDS = {
    icmp.IP_DEST_NET_UNREACHABLE: "net_unreachable",
    icmp.ERROR_NETWORK_UNREACHABLE: "net_unreachable",
    icmp.IP_DEST_HOST_UNREACHABLE: "host_unreachable",
    icmp.ERROR_HOST_UNREACHABLE: "host_unreachable",
    icmp.IP_TTL_EXPIRED_TRANSIT: "ttl_expired",
    icmp.IP_PACKET_TOO_BIG: "too_big",
    icmp.IP_GENERAL_FAILURE: "general",
}
# The same, for the copied report: it is in English like every report of the tab.
REPORT_WORDS = {REPLY: "reply", CHANGED: "reply came back changed", LOST: "no reply",
                "net_unreachable": "network unreachable",
                "host_unreachable": "host unreachable", "ttl_expired": "TTL expired in transit",
                "too_big": "packet too big", "general": "general failure"}


class Target(NamedTuple):
    typed: str              # what the person typed, without the spaces around it
    name: str               # the name to look up (IDNA, ASCII); "" for an address
    address: str = ""       # what is pinged: given, or what the lookup answered


def _one_address(address, typed):
    if address.is_unspecified or address.is_multicast or (
            address.version == 4 and address == ipaddress.IPv4Address("255.255.255.255")):
        raise Refused("tools.ping.refused.not_one", typed=typed)
    scope = getattr(address, "scope_id", None)
    if scope is not None and not scope.isdigit():
        # Windows numbers its zones (fe80::1%12); a name there would be pinged nowhere.
        raise Refused("tools.ping.refused.bad_address", typed=typed)


def parse(text):
    """What was typed, as a Target - or ``Refused`` saying why it is not one. UI thread:
    nothing here is slow and nothing is sent."""
    typed = (text or "").strip()
    if not typed:
        raise Refused("tools.ping.refused.empty")
    try:
        address = ipaddress.ip_address(typed)
    except ValueError:
        address = None
    if address is not None:
        _one_address(address, typed)
        return Target(typed, "", str(address))
    name = typed[:-1] if typed.endswith(".") else typed
    if ":" in name or "%" in name or _NUMERIC.match(name.rsplit(".", 1)[-1]):
        raise Refused("tools.ping.refused.bad_address", typed=typed)
    try:
        ascii_name = name.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise Refused("tools.ping.refused.bad_name", typed=typed) from None
    if len(ascii_name) > MAX_NAME or not all(_LABEL.match(label)
                                             for label in ascii_name.split(".")):
        raise Refused("tools.ping.refused.bad_name", typed=typed)
    return Target(typed, ascii_name)


def _lookup(name):
    return socket.getaddrinfo(name, None)


def resolve(target, lookup=None):
    """The Target with the address to ping: the name looked up, the first answer in
    the order Windows gives. On a worker - a lookup can take seconds."""
    if target.address:
        return target
    try:
        answers = (lookup or _lookup)(target.name)
    except (OSError, UnicodeError):
        raise Refused("tools.ping.refused.not_found", name=target.typed) from None
    for family, _kind, _proto, _canonical, where in answers:
        if family == socket.AF_INET:
            return target._replace(address=str(ipaddress.IPv4Address(where[0])))
        if family == socket.AF_INET6:
            address = ipaddress.IPv6Address(where[0])
            scope = where[3] if len(where) > 3 else 0
            if scope and address.scope_id is None:
                address = ipaddress.IPv6Address(f"{address}%{scope}")
            return target._replace(address=str(address))
    raise Refused("tools.ping.refused.not_found", name=target.typed)


def send(target, wait_s, system=None):
    """One echo request to the Target's address. On a worker."""
    return icmp.echo(ipaddress.ip_address(target.address), int(wait_s * 1000), system)


def start_and_send(target, wait_s, system=None, lookup=None, wanted=None):
    """The first request of a run: the lookup (when a name was typed), then the ping.
    One worker run, so the address is known before anything is drawn. Returns
    ``(target, echo)``.

    ``wanted()`` is asked before the lookup and again before the ping: Stop pressed
    while the request waited for the worker, or while a lookup took its seconds,
    sends nothing after it - the echo comes back ``None``."""
    if wanted is not None and not wanted():
        return target, None
    target = resolve(target, lookup)
    if wanted is not None and not wanted():
        return target, None
    return target, send(target, wait_s, system)


def kind_of(echo):
    if echo.status == icmp.IP_SUCCESS:
        return CHANGED if echo.changed else REPLY
    return LOST if echo.status == icmp.IP_REQ_TIMED_OUT else FAILED


def result_words(echo):
    """The Result column: ``Words`` in the window's language."""
    kind = kind_of(echo)
    if kind != FAILED:
        return Words(f"tools.ping.result.{kind}")
    slug = STATUS_WORDS.get(echo.status)
    return Words(f"tools.ping.result.{slug}") if slug else Words("tools.ping.result.code",
                                                                  echo.status)


def rtt_number(value):
    """Whole milliseconds, as Windows counts them: its 0 is under one, not none."""
    return "< 1" if value == 0 else str(value)


class Result(NamedTuple):
    seq: int
    sent: float             # time.time() when the request went out
    echo: icmp.Echo

    @property
    def kind(self):
        return kind_of(self.echo)


class Run:
    """One run, Start to Stop: the target, the pace, what came back and the totals.

    The totals count every ping of the run; the rows keep the last ``KEPT``.
    """

    def __init__(self, target, every_s=DEFAULT_EVERY_S, wait_s=DEFAULT_WAIT_S, started=None):
        self.target = target
        self.every_s = every_s
        self.wait_s = wait_s
        self.started = time.time() if started is None else started
        self.results = collections.deque(maxlen=KEPT)
        self.sent = self.replies = self.changed = 0
        self._low = self._high = None
        self._total = 0

    def add(self, sent_at, echo):
        result = Result(self.sent + 1, sent_at, echo)
        self.sent += 1
        self.results.append(result)
        if echo.status == icmp.IP_SUCCESS:
            self.replies += 1
            self.changed += bool(echo.changed)
            rtt = echo.rtt_ms or 0
            self._total += rtt
            self._low = rtt if self._low is None else min(self._low, rtt)
            self._high = rtt if self._high is None else max(self._high, rtt)
        return result

    @property
    def lost(self):
        return self.sent - self.replies

    def lost_pct(self):
        return 100.0 * self.lost / self.sent if self.sent else 0.0

    def round_trips(self):
        """``(lowest, average, highest)`` in ms over the replies, or None before one."""
        if not self.replies:
            return None
        return self._low, round(self._total / self.replies), self._high

    def chart(self):
        """The last ``CHARTED`` round trips, oldest first; None where none came back."""
        last = list(self.results)[-CHARTED:]
        return [r.echo.rtt_ms if r.echo.status == icmp.IP_SUCCESS else None for r in last]

    def next_at(self, sent_at, answered_at):
        """When the next request goes: a pace after the last one went, and never
        before its answer came - one request is out at a time, so a reply always
        belongs to the row it is shown on."""
        return max(sent_at + self.every_s, answered_at)


def answered_by_other(echo, target):
    """A reply from an address that is not the one pinged (a router saying "TTL
    expired" or "unreachable" for it) - the window and the report both say who."""
    return bool(echo.reply_from) and echo.reply_from != target.address.split("%")[0]


def _report_result(result, target):
    echo = result.echo
    kind = result.kind
    if kind == FAILED:
        words = REPORT_WORDS.get(STATUS_WORDS.get(echo.status, ""),
                                 f"Windows answered {echo.status}")
    else:
        words = REPORT_WORDS[kind]
    at =time.strftime("%H:%M:%S", time.localtime(result.sent))
    parts = [f"{result.seq:>5}", at]
    if echo.rtt_ms is not None:
        parts.append(f"{rtt_number(echo.rtt_ms)} ms")
    if echo.ttl is not None:
        parts.append(f"TTL {echo.ttl}")
    parts.append(words)
    if answered_by_other(echo, target):
        parts.append(f"from {echo.reply_from}")
    return "  ".join(parts)


def report(run):
    """The run as text for the clipboard - in English, like the tab's other reports."""
    target = run.target
    named = f"{target.typed} ({target.address})" if target.name else target.address
    at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run.started))
    lines = [f"Ping {named}: every {run.every_s:g} s, waiting up to {run.wait_s} s, "
             f"started {at}"]
    lines += [_report_result(result, target) for result in run.results]
    lines.append(f"sent {run.sent}, replies {run.replies}, lost {run.lost} "
                 f"({run.lost_pct():.1f}%)" + (f", {run.changed} came back changed"
                                              if run.changed else ""))
    trips = run.round_trips()
    if trips:
        low, avg, high = trips
        lines.append(f"round trip: lowest {rtt_number(low)}, average {rtt_number(avg)}, "
                     f"highest {rtt_number(high)} ms")
    if len(run.results) < run.sent:
        lines.append(f"(the first {run.sent - len(run.results)} pings are not listed)")
    return "\n".join(lines)
