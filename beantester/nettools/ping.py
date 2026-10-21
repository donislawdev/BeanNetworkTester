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
once, at Start, by the system (``getaddrinfo``: on Windows the hosts file, its cache,
then its DNS servers; on Linux the sources its name service lists), and the address
it gave is shown, because a name with an IPv6 address first may not be pinged where
the person thinks.

What the numbers mean under a session (measured 2026-10-19, ``icmp.py``): a ping is
a request out and a reply in, so with the two-way traffic filter it carries the
latency twice and loses a packet twice as often - 20% of loss lost about a third of
the pings.

A run is cut into PARTS where the session started, its settings were applied, a
scenario stepped or it stopped (``engine.session_mark``, read by the window at each
request and each answer): the scene this tool is for is "ping, change the latency,
look", and totals over the whole run would average the time before the change with
the time after it. A ping whose request went before a change and whose answer came
after it is a row and counts in the run's totals, but in no part - half of its trip
was under the old settings.
"""
import collections
import ipaddress
import math
import re
import socket
import sys
import time
from typing import NamedTuple

from .. import icmp, icmpsock
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
# The data a ping carries, in bytes: ping.exe's 32, and at most its 65500 (``icmp.py``:
# up to 65501 went and came back whole, 65535 got no reply). A bigger ping shows what
# a speed limit or a packet size limit does: on the wire it is the data plus 28 bytes.
DEFAULT_SIZE = icmp.SIZE
MAX_SIZE = 65500
_SIZE = re.compile(r"[0-9]{1,5}\Z")
# How many pings a run sends before it stops by itself (ping.exe's -n); 0 = until Stop.
COUNTS = (0, 10, 100, 1000)
DEFAULT_COUNT = 0
# A part's state, by the kind of the session's last mark (``engine.MARK_KINDS``).
PART_KINDS = {None: "none", "START": "start", "CHANGE": "change", "SCENARIO": "scenario",
              "STOP": "stop"}
# The marks whose text says the settings in English (the engine's own event text); a
# STOP's text is the name of its reason, not words.
_SAID = frozenset({"start", "change", "scenario"})

# The "?" sheet's paragraph about what differs by system, between the shared ones
# (``gui/toolbox/ping.py``): Windows rounds the wait, Linux needs the right to send.
WINDOWS_HELP = ("tools.ping.help_windows",)
LINUX_HELP = ("tools.ping.help_linux",)


def platform_help() -> tuple[str, ...]:
    if sys.platform.startswith("win"):
        return WINDOWS_HELP
    return LINUX_HELP if sys.platform.startswith("linux") else ()


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
REPORT_PARTS = {"none": "no session", "start": "session running", "change": "changes applied",
                "scenario": "scenario step", "stop": "session stopped"}


class Target(NamedTuple):
    typed: str              # what the person typed, without the spaces around it
    name: str               # the name to look up (IDNA, ASCII); "" for an address
    address: str = ""       # what is pinged: given, or what the lookup answered


def _one_address(address, typed):
    if address.is_unspecified or address.is_multicast or (
            address.version == 4 and address == ipaddress.IPv4Address("255.255.255.255")):
        raise Refused("tools.ping.refused.not_one", typed=typed)
    scope = getattr(address, "scope_id", None)
    if scope is not None and not scope.isdigit() and not _interface(scope):
        # Windows numbers its zones (fe80::1%12); a name there would be pinged nowhere.
        # Linux names them too (fe80::1%eth0) - taken when an interface has that name.
        raise Refused("tools.ping.refused.bad_address", typed=typed)


def _interface(name):
    """Whether ``name`` is one of this Linux machine's interfaces (never on Windows)."""
    return sys.platform.startswith("linux") and icmpsock.zone_index(name) is not None


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


def parse_size(text):
    """The size typed, in whole bytes from 0 to ``MAX_SIZE`` - or ``Refused``. Digits
    only: no sign, no point, and no other script's digits that ``int`` would refuse."""
    typed = (text or "").strip()
    if not _SIZE.match(typed) or int(typed) > MAX_SIZE:
        raise Refused("tools.ping.refused.size", typed=typed, most=MAX_SIZE)
    return int(typed)


def _lookup(name):
    return socket.getaddrinfo(name, None)


def resolve(target, lookup=None):
    """The Target with the address to ping: the name looked up, the first answer in
    the order the system gives. On a worker - a lookup can take seconds."""
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


def send(target, wait_s, system=None, size=DEFAULT_SIZE):
    """One echo request of ``size`` bytes to the Target's address. On a worker."""
    return icmp.echo(ipaddress.ip_address(target.address), int(wait_s * 1000), system, size)


def start_and_send(target, wait_s, system=None, lookup=None, wanted=None, size=DEFAULT_SIZE):
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
    return target, send(target, wait_s, system, size=size)


def kind_of(echo):
    if echo.status == icmp.IP_SUCCESS:
        return CHANGED if echo.changed else REPLY
    return LOST if echo.status == icmp.IP_REQ_TIMED_OUT else FAILED


def result_words(echo):
    """The Result column: ``Words`` in the window's language."""
    kind = kind_of(echo)
    if kind != FAILED:
        return Words(f"tools.ping.result.{kind}")
    if echo.said:
        # Before the numbers: Linux's said comes with a general status, whose word
        # would hide what it said (``icmp.from_answer``).
        return Words("tools.ping.result.linux", echo.said)
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
    part: int = 0           # the index of the run's part its request went in
    counted: bool = True    # False: the session changed while it was out (in no part)

    @property
    def kind(self):
        return kind_of(self.echo)


class Stats:
    """What a stretch of pings came to - the whole run, or one part of it.

    Kept as it goes, never from the rows (they keep only the last ``KEPT``):
    * jitter - how much the round trip moves from one reply to the next, the mean of
      the differences between consecutive replies (mtr's way; a lost ping between
      two replies does not part them);
    * the 95th percentile - the round trip 95% of the replies did not exceed, from a
      count of each whole millisecond (exact, and as small as the values are few);
    * the longest run of pings in a row with no reply - what a burst of loss is.
    """

    def __init__(self):
        self.sent = self.replies = self.changed = 0
        self.longest_loss = 0
        self._lost_now = 0
        self._low = self._high = self._last = None
        self._total = self._moved = self._steps = 0
        self._trips: collections.Counter = collections.Counter()

    def add(self, echo):
        self.sent += 1
        if echo.status != icmp.IP_SUCCESS:
            self._lost_now += 1
            self.longest_loss = max(self.longest_loss, self._lost_now)
            return
        self._lost_now = 0
        self.replies += 1
        self.changed += bool(echo.changed)
        rtt = echo.rtt_ms or 0
        self._total += rtt
        self._low = rtt if self._low is None else min(self._low, rtt)
        self._high = rtt if self._high is None else max(self._high, rtt)
        if self._last is not None:
            self._moved += abs(rtt - self._last)
            self._steps += 1
        self._last = rtt
        self._trips[rtt] += 1

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

    def average(self):
        """The mean round trip in ms (not rounded), or None before a reply."""
        return self._total / self.replies if self.replies else None

    def jitter(self):
        """Whole ms, or None before two replies."""
        return round(self._moved / self._steps) if self._steps else None

    def p95(self):
        """Whole ms (nearest rank), or None before a reply."""
        rank, seen = math.ceil(0.95 * self.replies), 0
        for rtt in sorted(self._trips):
            seen += self._trips[rtt]
            if seen >= rank:
                return rtt
        return None


class Part:
    """The pings sent under one state of the session: from the first ping after it
    started, its settings were applied, a scenario stepped or it stopped, to the
    last before the next such moment."""

    def __init__(self, mark, started):
        self.mark = mark            # the engine's session_mark() then; None = never a session
        self.started = started      # when its first ping went
        self.stats = Stats()

    @property
    def kind(self):
        """"none", "start", "change", "scenario" or "stop"."""
        return PART_KINDS.get(self.mark[1] if self.mark else None, "none")

    @property
    def settings(self):
        """The engine's words for what the session does in it (English), or ""."""
        return self.mark[2] if self.mark and self.kind in _SAID else ""


class Run:
    """One run, Start to Stop: the target, what was asked, what came back, the totals
    and the parts.

    The totals count every ping of the run; the rows keep the last ``KEPT``.
    """

    def __init__(self, target, every_s=DEFAULT_EVERY_S, wait_s=DEFAULT_WAIT_S, started=None,
                 size=DEFAULT_SIZE, count=DEFAULT_COUNT):
        self.target = target
        self.every_s = every_s
        self.wait_s = wait_s
        self.size = size
        self.count = count
        self.started = time.time() if started is None else started
        self.results = collections.deque(maxlen=KEPT)
        self.total = Stats()
        self.parts: list[Part] = []

    def add(self, sent_at, echo, mark=None, answered_mark=None):
        """One answer. ``mark`` is the session's mark when its request went and
        ``answered_mark`` when the answer came; both None with no engine to ask."""
        if not self.parts or self.parts[-1].mark != mark:
            self.parts.append(Part(mark, sent_at))
        counted = answered_mark == mark
        result = Result(self.total.sent + 1, sent_at, echo, len(self.parts) - 1, counted)
        self.total.add(echo)
        if counted:
            self.parts[-1].stats.add(echo)
        self.results.append(result)
        return result

    # The run's totals, by the names the window and the report read.
    @property
    def sent(self):
        return self.total.sent

    @property
    def replies(self):
        return self.total.replies

    @property
    def changed(self):
        return self.total.changed

    @property
    def lost(self):
        return self.total.lost

    def lost_pct(self):
        return self.total.lost_pct()

    def round_trips(self):
        return self.total.round_trips()

    def done(self):
        """It sent the number of pings it was asked for (never, without a number)."""
        return bool(self.count) and self.total.sent >= self.count

    def _charted(self):
        return list(self.results)[-CHARTED:]

    def chart(self):
        """The last ``CHARTED`` round trips, oldest first; None where none came back."""
        return [r.echo.rtt_ms if r.echo.status == icmp.IP_SUCCESS else None
                for r in self._charted()]

    def chart_changes(self):
        """Where a part begins among the charted pings: the index in ``chart()`` of
        each ping that is the first of its part - but not the first charted one, whose
        part began before the chart does."""
        last = self._charted()
        return [i for i in range(1, len(last)) if last[i].part != last[i - 1].part]

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
    if kind == FAILED and echo.said:
        words = f"Linux answered {echo.said}"
    elif kind == FAILED:
        words = REPORT_WORDS.get(STATUS_WORDS.get(echo.status, ""),
                                 f"Windows answered {echo.status}")
    else:
        words = REPORT_WORDS[kind]
    at = time.strftime("%H:%M:%S", time.localtime(result.sent))
    cells = [f"{result.seq:>5}", at]
    if echo.rtt_ms is not None:
        cells.append(f"{rtt_number(echo.rtt_ms)} ms")
    if echo.ttl is not None:
        cells.append(f"TTL {echo.ttl}")
    cells.append(words)
    if answered_by_other(echo, target):
        cells.append(f"from {echo.reply_from}")
    if not result.counted:
        cells.append("(the session changed while it was out: in no part)")
    return "  ".join(cells)


def _clock(when):
    return time.strftime("%H:%M:%S", time.localtime(when))


def _part_heading(part):
    said = f": {part.settings}" if part.settings else ""
    return f"--- from {_clock(part.started)}, {REPORT_PARTS[part.kind]}{said}"


def _report_stats(stats):
    """``stats`` in two lines of words, the second only with a reply."""
    lines = [f"sent {stats.sent}, replies {stats.replies}, lost {stats.lost} "
             f"({stats.lost_pct():.1f}%)"
             + (f", at most {stats.longest_loss} lost in a row" if stats.lost else "")
             + (f", {stats.changed} came back changed" if stats.changed else "")]
    trips = stats.round_trips()
    if trips:
        low, avg, high = trips
        jitter = stats.jitter()
        lines.append(f"round trip: lowest {rtt_number(low)}, average {rtt_number(avg)}, "
                     f"highest {rtt_number(high)} ms"
                     + (f", jitter {rtt_number(jitter)} ms" if jitter is not None else "")
                     + f", 95% within {rtt_number(stats.p95())} ms")
    return lines


def report(run):
    """The run as text for the clipboard - in English, like the tab's other reports:
    what was asked, the rows with a line where each part begins, then each part's
    numbers and the run's."""
    target = run.target
    named = f"{target.typed} ({target.address})" if target.name else target.address
    at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run.started))
    asked = f", {run.count} pings" if run.count else ""
    lines = [f"Ping {named}: {run.size} bytes every {run.every_s:g} s, waiting up to "
             f"{run.wait_s} s{asked}, started {at}"]
    shown = None
    for result in run.results:
        if result.part != shown:
            lines.append(_part_heading(run.parts[result.part]))
            shown = result.part
        lines.append(_report_result(result, target))
    if len(run.parts) > 1:
        for part in run.parts:
            lines.append(f"part from {_clock(part.started)}, {REPORT_PARTS[part.kind]}:")
            lines += ["  " + line for line in _report_stats(part.stats)]
        lines.append("the whole run:")
    lines += _report_stats(run.total)
    if len(run.results) < run.sent:
        lines.append(f"(the first {run.sent - len(run.results)} pings are not listed)")
    return "\n".join(lines)
