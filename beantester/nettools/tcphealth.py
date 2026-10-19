"""TCP health: the connections a person watches, and what Windows measured for them.

A connection comes from a row menu - the socket table on this tab, or the
Connections page of a session (the owner's choice, 2026-10-19) - and stays on the
list until it is taken off, after it has ended too, with its last numbers. The
numbers are ``tcpestats``'s; this module keeps them over time and says them: the
counters as a difference from the first reading (Learn: counting is never turned
off, so a counter can hold what happened before anyone here watched), the round
trips as they are, and a minute of them for the chart.

Kept on the UI thread (``Watchlist``); a worker only ever gets a snapshot to work on
(``cycle``) and its answer is applied when it lands - so no lock, and a reading
that comes back for a connection taken off the list meanwhile is dropped.
"""
import collections
import ipaddress
import time
from typing import NamedTuple

from .. import crashlog, driver, portmap, tcpestats, tcprow
from .adapters import Detail, Words

HISTORY = 60                    # chart points: a minute at one reading a second
MAX_WATCHED = 20                # each costs two calls a second, ~50 us (measured)
# Seconds without a new round-trip measurement, while data went out, before the details
# say so. MEASURED 2026-10-19 (``tcpestats``): an open connection whose round trip
# jumped by 200 ms or more was measured no more for a whole session, and the smoothed
# value only looked current. Three readings: one without a measurement is ordinary (a
# quiet second).
STALE_S = 3
_U32, _U64 = 2 ** 32, 2 ** 64

# How asking to watch a connection can end besides being watched.
GONE = "gone"                   # a Connections row whose connection has closed
AMBIGUOUS = "ambiguous"         # the same port on two local addresses
UNREADABLE = "unreadable"       # the socket table did not answer
FULL = "full"                   # MAX_WATCHED already
WATCHING = "watching"           # on the list (also: it already was)

# What a row's state says. STARTING: asked, not answered yet. STOPPED: counting
# went away after it worked - the port was taken by a new connection, or another
# program turned counting off; the numbers after that would not be this connection's.
STARTING, STOPPED = "starting", "stopped"
# Read no more: the answer cannot change by asking again.
FINAL = frozenset({tcpestats.ENDED, tcpestats.NEEDS_ADMIN, tcpestats.REFUSED, STOPPED})


class Request(NamedTuple):
    """What a row menu asked to watch. From the socket table the connection is
    known; a Connections row names no local address, so it is a ``target`` looked
    up in the socket table on the worker, the way "Reset this connection" does."""
    process: str
    pid: object = None
    connection: object = None   # tcprow.Connection
    target: object = None       # tcprow.Target


def blocker():
    """Why no connection can be watched from this process: an i18n key, "" if one can
    (``diagnostics.cleanup_blocker``'s shape). Counting is turned on only with
    administrator rights (Learn, measured). ``driver.is_admin``, as the diagnostics
    ask it: this module is read by the Tools tab's quiet-tab guard, and ``winenv``
    carries the subprocess of the elevation prompt."""
    if tcpestats.supported() and not driver.is_admin():
        return "tools.tcphealth.needs_admin"
    return ""


def key_of(connection):
    return "|".join(str(part) for part in connection)


def endpoint(ip, port):
    """``192.0.2.1:443`` / ``[2001:db8::1]:443``."""
    return f"[{ip}]:{port}" if ":" in str(ip) else f"{ip}:{port}"


def watchable(proto, remote_ip, state=""):
    """A row the menu may offer: TCP with an address at the other end, in a state
    that has a connection behind it - a listener answers 1168, TIME_WAIT 50
    (measured 2026-10-19)."""
    if proto != "TCP" or state in ("LISTEN", "TIME_WAIT", "CLOSED", "DELETE_TCB"):
        return False
    try:
        address = ipaddress.ip_address(str(remote_ip).split("%")[0])
    except ValueError:
        return False
    return not address.is_unspecified


class Watch:
    """One watched connection: the first and the latest numbers, and a minute of
    round trips. Changed on the UI thread only."""

    def __init__(self, connection, process, pid, asked_at):
        self.connection = connection
        self.key = key_of(connection)
        self.process = process
        self.pid = pid
        self.asked_at = asked_at
        self.since = None           # time.time() of the first reading with numbers
        self.state = STARTING
        self.code = 0
        self.detail = ""
        self.first = self.previous = self.last = None
        self.history = collections.deque(maxlen=HISTORY)    # (at, smoothed, sample)
        # When Windows last measured a round trip, and the bytes sent by then.
        self.measured_at = None
        self.sent_when_measured = 0
        self.read_at = None

    @property
    def reading(self):
        """Still asked about on each read."""
        return self.state not in FINAL

    def take(self, reading, at):
        if not self.reading:
            return
        sample = reading.sample
        if reading.state == tcpestats.OK and self.last is not None and _went_back(
                self.last, sample):
            reading = tcpestats.Reading(STOPPED)
        if reading.state == tcpestats.NOT_COUNTING and self.last is not None:
            reading = tcpestats.Reading(STOPPED)
        self.state, self.code, self.detail = reading.state, reading.code, reading.detail
        if reading.state != tcpestats.OK:
            return
        if self.first is None:
            self.first, self.since = sample, at
        if self.last is None or sample.rtt_samples != self.last.rtt_samples:
            self.measured_at, self.sent_when_measured = at, sample.bytes_out
        self.previous, self.last, self.read_at = self.last, sample, at
        if sample.smoothed_rtt is not None:
            # A reading with no newest sample (the field still unset) draws the
            # smoothed value for both lines rather than a drop to zero.
            self.history.append((at, sample.smoothed_rtt,
                                 sample.smoothed_rtt if sample.sample_rtt is None
                                 else sample.sample_rtt))

    def since_watching(self, field, bits=_U32):
        """A counter's change since the first reading - modulo its width: Windows'
        32-bit counters wrap."""
        if self.last is None:
            return None
        return (getattr(self.last, field) - getattr(self.first, field)) % bits

    def unmeasured_for(self):
        """Whole seconds since Windows last measured a round trip, when data went out
        after it and that is ``STALE_S`` or more; else 0. A connection that only
        receives is not stale: Windows measures on THIS computer's data. Nor is one
        no longer read (ended, stopped): its last numbers are final, not old."""
        if self.state != tcpestats.OK or self.last is None or self.measured_at is None:
            return 0
        waited = round(self.read_at - self.measured_at)
        sent = self.last.bytes_out != self.sent_when_measured
        return waited if sent and waited >= STALE_S else 0

    def since_previous(self, field):
        if self.last is None or self.previous is None:
            return 0
        return (getattr(self.last, field) - getattr(self.previous, field)) % _U32


def _went_back(old, new):
    """A 64-bit byte counter never goes down on one connection: when it does, the
    same four numbers now name a new connection."""
    return new.bytes_out < old.bytes_out or new.bytes_in < old.bytes_in


class Watchlist:
    """The watched connections of one window, in the order they were asked for."""

    def __init__(self):
        self.watches = {}           # key -> Watch
        self.pending = []           # Requests not yet sent to a worker
        self.read_at = None         # time.time() of the last answer

    def ask(self, request):
        """Queue ``request``: WATCHING (queued, or watched already) or FULL."""
        if request.connection is not None and key_of(request.connection) in self.watches:
            return WATCHING
        if len(self.watches) + len(self.pending) >= MAX_WATCHED:
            return FULL
        self.pending.append(request)
        return WATCHING

    def remove(self, key):
        self.watches.pop(key, None)

    def to_read(self):
        return [w.connection for w in self.watches.values() if w.reading]

    def busy(self):
        """Something to ask Windows: a request to send or a connection to read."""
        return bool(self.pending or self.to_read())

    def apply(self, result, at=None):
        """The worker's answer (``cycle``): new watches first, then the readings.
        Returns the requests that did not end in a watch, for the log."""
        at = time.time() if at is None else at
        refused = []
        for request, connection, kind, reading in result.added:
            if kind != WATCHING:
                refused.append((request, kind))
                continue
            key = key_of(connection)
            if key not in self.watches:
                self.watches[key] = Watch(connection, request.process, request.pid, at)
            self.watches[key].take(reading, at)
        for key, reading in result.readings.items():
            watch = self.watches.get(key)
            if watch is not None:   # taken off the list while it was read
                watch.take(reading, at)
        self.read_at = at
        return refused


class Result(NamedTuple):
    added: tuple                # (request, connection or None, kind, Reading or None)
    readings: dict              # key -> tcpestats.Reading


def cycle(requests, connections, watch=None, read=None, rows=None):
    """On the WORKER: find and turn on what was asked, read what is watched.

    One socket table read for all the Connections rows in this cycle, and none
    when there are none. The functions are injectable (tests)."""
    watch, read = watch or tcpestats.watch, read or tcpestats.read
    table = None
    added = []
    for request in requests:
        connection, kind = request.connection, WATCHING
        if connection is None:
            if table is None:
                table = _table(rows or portmap.socket_rows)
            connection, kind = _find(table, request.target)
        added.append((request, connection, kind,
                      watch(connection) if kind == WATCHING else None))
    return Result(tuple(added), {key_of(c): read(c) for c in connections})


def _table(socket_rows):
    """The socket table, or None. Any failure is None: the cycle also reads what is
    already watched, and one row menu's lookup must not cost those readings."""
    try:
        rows, failed = socket_rows()
    except portmap.SocketTableUnavailable:
        return None
    except Exception as exc:
        crashlog.note(exc, "nettools.tcphealth")
        return None
    # One of the TCP tables did not answer: a missing row would say nothing.
    return None if any(name.startswith("tcp/") for name in failed) else rows


def _find(table, target):
    if table is None:
        return None, UNREADABLE
    found = tcprow.matching(table, target)
    if not found:
        return None, GONE
    if len(found) > 1:
        return None, AMBIGUOUS
    row = found[0]
    return tcprow.Connection(row.local_ip, row.local_port, row.remote_ip, row.remote_port), \
        WATCHING


# -- what the list and the details say ---------------------------------------------- #
STATE_WORDS = {STARTING: "tools.tcphealth.state.starting", tcpestats.OK: "tools.tcphealth.state.open",
               tcpestats.ENDED: "tools.tcphealth.state.ended",
               tcpestats.NOT_COUNTING: "tools.tcphealth.state.not_counting",
               STOPPED: "tools.tcphealth.state.stopped",
               tcpestats.NEEDS_ADMIN: "tools.tcphealth.state.needs_admin",
               tcpestats.REFUSED: "tools.tcphealth.state.refused",
               tcpestats.FAILED: "tools.tcphealth.state.failed"}


def state_words(watch):
    return Words(STATE_WORDS.get(watch.state, "tools.tcphealth.state.failed"), watch.code)


def rtt_number(value):
    """A round trip's number: Windows counts whole milliseconds, so its 0 is a round
    trip under one (0.4 ms to a WSL peer, measured), not none - ``< 1``."""
    return "< 1" if value == 0 else str(value)


def ms(value):
    """A round trip: ``214 ms``, ``< 1 ms``, or ``Words`` for "not measured yet"."""
    return Words("tools.tcphealth.value.no_rtt") if value is None else f"{rtt_number(value)} ms"


def process_text(watch):
    if watch.process:
        return watch.process
    return f"PID {watch.pid}" if watch.pid else "?"


def cells(watch):
    """One list row: program, local, remote, state, RTT, bytes resent since watching
    (in bytes: Windows never fills the segment count - ``tcpestats``)."""
    c = watch.connection
    last = watch.last
    resent = watch.since_watching("resent_bytes")
    return (process_text(watch), endpoint(c.local_ip, c.local_port),
            endpoint(c.remote_ip, c.remote_port), state_words(watch),
            ms(last.smoothed_rtt) if last else "", "" if resent is None else f"{resent} B")


def tag_of(watch):
    """The list row's colour: the caution colour while the round trip is not measured
    (the details' smoothed row says for how long)."""
    return "stale" if watch.unmeasured_for() else ""


def sort_key(watch, column):
    """What the list sorts by in ``cells`` column ``column``: the round trip and the
    resent bytes as numbers (unmeasured first), the rest as text."""
    if column == 4:
        last = watch.last
        return -1 if last is None or last.smoothed_rtt is None else last.smoothed_rtt
    if column == 5:
        resent = watch.since_watching("resent_bytes")
        return -1 if resent is None else resent
    if column == 3:
        return watch.state
    return str(cells(watch)[column]).casefold()


def _counter(watch, field, unit=""):
    """A counter since watching, and how much it grew since the last read in brackets:
    ``4800 B (+400)``. No words - in the Note column they were cut at the smallest
    window (133 px shown, measured 2026-10-19)."""
    step = watch.since_previous(field)
    return f"{watch.since_watching(field)}{unit}" + (f" (+{step})" if step else "")


def details(watch):
    """The rows of the details table: who and where, then what was measured."""
    c = watch.connection
    out = [Detail("process", Words("tools.tcphealth.item.process"),
                  process_text(watch) + (f" (PID {watch.pid})" if watch.process and watch.pid
                                         else "")),
           Detail("local", Words("tools.tcphealth.item.local"), endpoint(c.local_ip, c.local_port)),
           Detail("remote", Words("tools.tcphealth.item.remote"),
                  endpoint(c.remote_ip, c.remote_port), address=c.remote_ip.split("%")[0]),
           Detail("state", Words("tools.tcphealth.item.state"), state_words(watch))]
    last = watch.last
    if last is None:
        return out
    sent, received = (watch.since_watching("bytes_out", _U64),
                      watch.since_watching("bytes_in", _U64))
    unmeasured = watch.unmeasured_for()
    # The Note column says one thing: that the round trip is not measured. What a row
    # means is the help's - every other note was cut at the smallest window.
    out += [Detail("srtt", Words("tools.tcphealth.item.srtt"), ms(last.smoothed_rtt),
                   (Words("tools.tcphealth.note.not_measured", unmeasured),) if unmeasured
                   else (), tag="stale" if unmeasured else ""),
            Detail("sample", Words("tools.tcphealth.item.sample"), ms(last.sample_rtt)),
            Detail("range", Words("tools.tcphealth.item.range"),
                   Words("tools.tcphealth.value.no_rtt")
                   if last.min_rtt is None or last.max_rtt is None
                   else f"{rtt_number(last.min_rtt)} / {rtt_number(last.max_rtt)} ms"),
            Detail("rttvar", Words("tools.tcphealth.item.rttvar"), ms(last.rtt_var)),
            Detail("rto", Words("tools.tcphealth.item.rto"), f"{last.rto} ms"),
            Detail("resent_bytes", Words("tools.tcphealth.item.resent_bytes"),
                   _counter(watch, "resent_bytes", " B")),
            Detail("timeouts", Words("tools.tcphealth.item.timeouts"),
                   _counter(watch, "timeouts")),
            Detail("fast_resends", Words("tools.tcphealth.item.fast_resends"),
                   _counter(watch, "fast_resends")),
            Detail("dupacks", Words("tools.tcphealth.item.dupacks"),
                   _counter(watch, "duplicate_acks")),
            Detail("mss", Words("tools.tcphealth.item.mss"), f"{last.mss} B"),
            Detail("data", Words("tools.tcphealth.item.data"), f"{sent} / {received} B"),
            Detail("since", Words("tools.tcphealth.item.since"),
                   time.strftime("%H:%M:%S", time.localtime(watch.since)))]
    return out


def chart(watch, now=None):
    """(smoothed, sample, seconds the points span) for the RTT chart."""
    points = list(watch.history) if watch is not None else []
    now = time.time() if now is None else now
    span = round(now - points[0][0]) if points else 0
    return [p[1] for p in points], [p[2] for p in points], span


# -- the report (English, like the other tools') ------------------------------------- #
def _rtt(value):
    return "-" if value is None else f"{rtt_number(value)} ms"


def report_lines(watchlist):
    at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(watchlist.read_at or time.time()))
    lines = [f"TCP health: {len(watchlist.watches)} connections, read {at}"]
    for watch in watchlist.watches.values():
        c = watch.connection
        lines.append(f"{process_text(watch)} {endpoint(c.local_ip, c.local_port)} -> "
                     f"{endpoint(c.remote_ip, c.remote_port)}: {watch.state}"
                     + (f" ({watch.code})" if watch.code else ""))
        last = watch.last
        if last is None:
            continue
        unmeasured = watch.unmeasured_for()
        lines.append(f"  round trip: smoothed {_rtt(last.smoothed_rtt)}, last "
                     f"{_rtt(last.sample_rtt)}, lowest {_rtt(last.min_rtt)}, highest "
                     f"{_rtt(last.max_rtt)}, variation {_rtt(last.rtt_var)}, resend timer "
                     f"{last.rto} ms, segment size {last.mss} B, measured {last.rtt_samples} "
                     "times" + (f", none for {unmeasured} s while data went out"
                                if unmeasured else ""))
        lines.append(
            "  since watching ("
            + time.strftime("%H:%M:%S", time.localtime(watch.since)) + "): resent "
            f"{watch.since_watching('resent_bytes')} B, timeouts "
            f"{watch.since_watching('timeouts')}, fast resends "
            f"{watch.since_watching('fast_resends')}, duplicate ACKs "
            f"{watch.since_watching('duplicate_acks')}, sent "
            f"{watch.since_watching('bytes_out', _U64)} B, received "
            f"{watch.since_watching('bytes_in', _U64)} B")
    return lines


def report(watchlist):
    return "\n".join(report_lines(watchlist))
