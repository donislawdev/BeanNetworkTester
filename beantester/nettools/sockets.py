"""The socket table: every TCP and UDP socket on this machine, with its state and
its process - what ``netstat -ano`` shows, and without a session.

The connection table answers only once a session runs, and only about traffic
that crossed the driver: a program that listens and has not been spoken to yet is
invisible to it. "Which port does my application listen on before I break
anything?" and "who is holding 8080?" are answered here.

The rows come from ``portmap.socket_rows`` - the one module that asks the system
for sockets - and the names from ONE process snapshot taken right after it. The
search is the connection table's (``views.compile_query``) with this table's
columns, so the window has one search language (convention 10). Nothing here
draws or translates.

A read can be handed the read before it (``read(previous)``), and then it also
says what CHANGED: a socket that was not there is stamped with the time it
appeared, and one that has gone stays for a few seconds, marked closed. That is
what lets the table refresh itself and still be read: nothing vanishes or turns
up without saying so. What one read hands the next is a ``Carry``, a value like
the rest - no object lives between reads, so a read is still a function of its
arguments and the worker shares nothing with the window.

🔴 Windows has no notice of "the socket table changed" (IP Helper announces
address, route and interface changes only - Learn, read 2026-11-10), so a table
that keeps itself current reads on a timer. MEASURED 2026-11-10 on this project's
development machine (``internal_tools`` probes ``2026-11-10-sockets-monitor``):
of a 73 ms read of 212 sockets, 71 ms was the process snapshot - the same through
either system call, and the same at 15 000 sockets. So a read that follows
another keeps the names it was given (``_names``) and asks for the processes only
when a PID it has not named turns up, and at most every ``NAMES_EVERY_S``
otherwise. Without the snapshot a read is about 6 us a socket: 2 ms for an
ordinary machine, 90 ms for 15 000 sockets. ``read_every_ms`` keeps even that to
a twentieth of the time between two reads.

A connection that opens and closes between two reads is never seen. That is what
reading on a timer costs, and the window's help says so.
"""
import ipaddress
import itertools
import sys
import time
from typing import NamedTuple

from .. import paths, portmap
from ..matchers import KIND_INT, KIND_IP, KIND_PROCESS
from ..views import compile_query

# What the table sorts by until the person clicks a header: "which port" is the
# question it is opened with.
DEFAULT_SORT = ("local_port", False)


class Socket(NamedTuple):
    """One row of the table: a ``portmap.SocketRow`` with its process named."""
    key: str                    # unique within a read (see _sockets)
    proto: str
    family: int
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int | None
    state: str
    pid: int | None
    proc: str                   # "" when no process owns it or it could not be named
    change: str = ""            # NEW or CLOSED while the table should point at it
    at: float | None = None     # time.time() it appeared or closed; None = there
                                # since the first read of this window


# How a row that changed is marked (``Socket.change``); the window colours by it.
NEW, CLOSED = "new", "closed"
# How long a socket that appeared stays marked, and one that closed stays listed.
# Long enough to be seen at the slowest pace offered (5 s: two reads).
MARK_S = 10.0
# The most closed sockets kept on show. A program that drops ten thousand
# connections at once must not double the table for ten seconds.
MAX_CLOSED = 2000
# The longest a read goes on trusting the names an earlier one was given. A PID
# given to another program while it still holds sockets from one read to the next
# would keep the old name; this is how long, at most.
NAMES_EVERY_S = 30.0


class Carry(NamedTuple):
    """What one read hands the next (``Snapshot.carry``). Never changed once made."""
    names: dict                 # pid -> name, for the PIDs of that read's table
    named_at: float             # time.monotonic() of the process snapshot behind them
    last: dict                  # key -> Socket, the open sockets of that read
    seen: dict                  # key -> (time.time(), time.monotonic()) it appeared
    closed: tuple               # ((Socket, time.monotonic() it closed), ...)


class Snapshot(NamedTuple):
    """One read of the machine."""
    sockets: tuple              # the open sockets, then the ones that just closed
    failed: tuple               # the tables that did not answer ("tcp/v6"...)
    read_at: float              # time.time() when the table was read
    elapsed_ms: int
    carry: Carry | None = None  # for the read after this one


class View(NamedTuple):
    """A snapshot as the person asked to see it."""
    snapshot: Snapshot
    rows: list                  # the sockets the query keeps, in the sort's order
    query: str
    sort: tuple                 # (column, reverse)
    made: int                   # a count, not a clock: the newest view is the one shown


# Which view is newest, counted rather than timed. It was ``time.time()``, and a
# clock set back (NTP, a resumed virtual machine) brought an older view back to the
# screen (external review, P3-36). ``monotonic`` cannot go back but can tie: on
# Windows it moves in steps of about 16 ms, and two views made within one step
# compared equal. ``next`` on a count is one C call, safe across the workers.
_MADE = itertools.count(1)


class Unreadable(Exception):
    """No socket table could be read, for a reason the person can act on.

    ``user_key`` names the reason in the window's language (``gui/toolbox/base.py``
    shows it); the message stays the program's own words, for the crash log.
    """

    def __init__(self, user_key, detail):
        super().__init__(detail)
        self.user_key = user_key


# ``portmap.SocketTableUnavailable.reason`` -> what the person is told.
UNREADABLE_KEYS = {"denied": "tools.sockets.error_denied",
                   "missing": "tools.sockets.error_missing"}


def read(previous=None, fresh_names=True):
    """Read every socket and name its process. Runs on a worker; may raise.

    ``previous`` is the snapshot read before this one, when the caller has it: the
    answer then also says what changed since (``_changes``). ``fresh_names=False``
    lets the read keep the names ``previous`` was given (``_names``) - for a table
    that reads itself; a read somebody asked for names everything again.

    ``Unreadable`` when no table can be read at all: an empty table would say "no
    sockets", which nobody here could know. Anything else that fails is the
    program's own fault and travels as it is.
    """
    started = time.perf_counter()
    try:
        rows, failed = portmap.socket_rows()
    except portmap.SocketTableUnavailable as exc:
        raise Unreadable(UNREADABLE_KEYS.get(exc.reason, ""), str(exc)) from exc
    now = _clock()
    carry = previous.carry if previous is not None else None
    # Named AFTER the table is read, so a process that exited in between leaves
    # its rows without a name - which is true - instead of the table outliving the
    # names it was given. A PID reused inside those few milliseconds is the one
    # case left: named after its new owner. Accepted; it cannot be told apart.
    names, named_at = _names(rows, None if fresh_names else carry, now[1])
    shown, carry = _changes(list(_sockets(rows, names)), carry, frozenset(failed), now)
    return Snapshot(tuple(shown), tuple(failed), now[0],
                    round((time.perf_counter() - started) * 1000),
                    carry._replace(names=names, named_at=named_at))


def _clock():
    """``(time.time(), time.monotonic())`` of a read: the first is what the window
    shows, the second what a wait is measured with - a clock set back (NTP, a
    resumed virtual machine) must neither keep a row marked for an hour nor drop
    it at once."""
    return time.time(), time.monotonic()


def _names(rows, carry, monotonic):
    """``(names, named_at)`` for the PIDs of ``rows``: ``carry``'s while they will
    do, one process snapshot otherwise (``carry`` None = always the snapshot).

    The names kept are only those of PIDs still in the table, so a PID whose
    sockets have all gone is forgotten, and named again if it comes back - by then
    it may be another program. A PID the snapshot does not know (its process
    exited while its socket lingers) is kept as "", or every read would take the
    snapshot again for it.

    PID 0 owns nothing and is never named: the snapshot calls it "[System
    Process]", and a row in TIME_WAIT is not that process's socket. So it is left
    out here, the one place a row gets its name (``_sockets``).
    """
    pids = {row.pid for row in rows if row.pid}
    if (carry is not None and pids <= carry.names.keys()
            and 0 <= monotonic - carry.named_at < NAMES_EVERY_S):
        return {pid: carry.names[pid] for pid in pids}, carry.named_at
    table = portmap.process_names()
    if not table and carry is not None:
        # The snapshot failed (it answers empty, and says so in the crash log).
        # The names known so far stay, the others are asked for on the next read.
        return {pid: carry.names[pid] for pid in pids if pid in carry.names}, carry.named_at
    return {pid: table.get(pid, "") for pid in pids}, monotonic


def _changes(live, carry, failed, now):
    """``(shown, carry)``: ``live`` with what changed since ``carry`` marked, the
    sockets that just closed after them, and what the next read needs.

    ``now`` is the read's ``_clock()``.

    ``failed`` names the tables that did not answer (``portmap.table_of``). Their
    sockets are missing from ``live`` without having closed, so they are kept as
    the last read had them: not called closed, and not marked new when their table
    answers again. That is per table - one that keeps failing (IPv6 turned off)
    must not stop the others from saying what closed, nor make every read remember
    more than the one before.
    """
    wall, monotonic = now
    current = {socket.key: socket for socket in live}
    if carry is None:
        # The first read: everything was simply there.
        return live, Carry({}, monotonic, current, {}, ())
    unread = {key: socket for key, socket in carry.last.items()
              if key not in current and _table(socket) in failed}
    known = current.keys() | unread.keys()
    seen = {key: at for key, at in carry.seen.items() if key in known}
    for key in current.keys() - carry.last.keys() - seen.keys():
        seen[key] = now
    closed = [(socket, at) for socket, at in carry.closed
              if monotonic - at < MARK_S and socket.key not in current]
    arrived = _arrivals(current, carry.last)
    closed += [(socket._replace(change=CLOSED, at=wall), monotonic)
               for key, socket in carry.last.items()
               if key not in known and not _reshaped(socket, arrived)]
    closed = closed[-MAX_CLOSED:]
    shown = [_marked(socket, seen.get(socket.key), monotonic) for socket in live]
    shown += [socket for socket, _at in closed]
    return shown, Carry({}, monotonic, {**unread, **current}, seen, tuple(closed))


def _table(socket):
    """The table ``socket`` was read from, named the way a failed one is."""
    return portmap.table_of(socket.proto, socket.family)


def _place(socket):
    """Where a socket sits on this machine, and whose it is: what stays the same
    while the rest of its row changes."""
    return socket.proto, socket.local_ip, socket.local_port, socket.pid


def _arrivals(current, last):
    """``{place: bare}`` for each place (``_place``) where a socket appeared since
    ``last`` - ``bare`` when one of those has no far end. All ``_reshaped`` needs,
    so a server's port that swaps ten thousand clients in one read costs ten
    thousand steps, not ten thousand times ten thousand."""
    arrived = {}
    for key in current.keys() - last.keys():
        socket = current[key]
        place = _place(socket)
        arrived[place] = arrived.get(place, False) or not socket.remote_ip
    return arrived


def _reshaped(gone, arrived):
    """Did ``gone``'s row go because the same socket now has another row?

    A row's key holds its far end, and a socket gets one while it lives: a program
    binds a port and then connects, so the row without a far end goes and one with
    it appears. SEEN 2026-11-10 on real Tk, within seconds: "LISTEN, closed" beside
    "ESTABLISHED, appeared" for the same program and port. That is one socket
    getting on with its life, and "closed" would be false.

    So a row that went is not called closed when a row has just appeared at the
    same place and one of the two has no far end. Two rows that both have one are
    two connections of a server's port - one client left, another came - and are
    told as that.
    """
    bare = arrived.get(_place(gone))
    return bare is not None and (bare or not gone.remote_ip)


def _marked(socket, appeared, monotonic):
    """``socket`` with the time it appeared, and NEW for MARK_S after it.

    A row that turns up in TIME_WAIT is not a new socket: it is what a connection
    that just closed leaves behind (under PID 0, so under another key). It gets
    its time and no mark - marked, a closed connection would read as an opened one.
    """
    if appeared is None:
        return socket
    wall, at = appeared
    fresh = 0 <= monotonic - at < MARK_S and socket.state != "TIME_WAIT"
    return socket._replace(change=NEW if fresh else "", at=wall)


def _sockets(rows, names):
    """``Socket`` per row, each with a key no other row of this read has.

    Two rows can be identical in every column: one process may hold two UDP
    sockets on the same address and port (SO_REUSEADDR). The table finds a row by
    its key through a dict, so a duplicate key would send a click on one to the
    other - the numbering of repeats keeps them apart.
    """
    seen = {}
    for row in rows:
        base = (f"{row.proto}|{row.local_ip}|{row.local_port}|{row.remote_ip}|"
                f"{row.remote_port}|{row.pid}")
        repeat = seen.get(base, 0)
        seen[base] = repeat + 1
        # No name for PID 0 or for an owner the system would not say: ``_names``.
        name = names.get(row.pid, "")
        yield Socket(f"{base}|{repeat}", row.proto, row.family, row.local_ip,
                     row.local_port, row.remote_ip, row.remote_port, row.state,
                     row.pid, name)


NO_OWNER, NO_OWNER_LINUX, NO_OWNER_ROOT = ("tools.sockets.note_no_pid",
                                          "tools.sockets.note_no_pid_linux",
                                          "tools.sockets.note_no_pid_root")


def no_owner_note(platform=None):
    """What the note on sockets without a program says here. Windows names their
    owner to an administrator. Linux names the program only to root - measured
    2026-10-27 on Ubuntu 26.04: 14 of 14 sockets without one as a user, none under
    sudo - and the ones still without one under sudo are held from outside this
    system (WSL: its DNS on the tunnel address and a second chrony socket, for which
    ``ss`` as root names no process either) or by no process any more: a closing
    connection that its program has already closed. TIME_WAIT is PID 0, so not
    counted (``portmap._psutil_row``); FIN_WAIT_2 and LAST_ACK cannot be told from
    their state, so both Linux texts say "may"."""
    if not (sys.platform if platform is None else platform).startswith("linux"):
        return NO_OWNER
    return NO_OWNER_ROOT if paths.running_as_root() else NO_OWNER_LINUX


def without_owner(snapshot):
    """How many sockets the system would not name a process for (another account's,
    and on Linux also one held from outside it or by no process any more)."""
    return sum(1 for socket in snapshot.sockets
               if socket.pid is None and socket.change != CLOSED)


# -- a table that reads itself ------------------------------------------------------- #
# The paces the window offers, in seconds, and the one it starts with.
EVERY_S = (1, 2, 5)
DEFAULT_EVERY_S = 2
# A read may take at most one part in this many of the time between two reads: 5%
# of one core, however large the table is.
BUSY_FACTOR = 20
# After a read that failed the next one waits twice as long each time, up to this.
RETRY_CAP_MS = 30_000
# This many reads failing in a row turn the reading off: whatever is wrong is not
# passing, and the window says so instead of asking for ever.
FAILURES_TO_STOP = 5


def read_every_ms(chosen_s, last_ms, failures=0):
    """Milliseconds from the end of one read to the start of the next.

    The pace the person chose, stretched when one read takes more than a twentieth
    of it (``last_ms`` is what the last one took), and longer still after each
    failure in a row - never shorter than without the failures.
    """
    pace = max(int(chosen_s * 1000), int(last_ms) * BUSY_FACTOR)
    if failures:
        pace = max(pace, min(pace * 2 ** failures, RETRY_CAP_MS))
    return pace


# -- search ------------------------------------------------------------------------ #
# The connection table's qualifiers where the meaning is the same - `ip:` and
# `port:` are the REMOTE end there and here - plus what only this table has: the
# local address and the TCP state.
SEARCH_FIELDS = {
    "proc":  (KIND_PROCESS, lambda s, m: (s.pid, s.proc)),
    "pid":   (KIND_INT, lambda s, m: s.pid),
    "proto": (KIND_PROCESS, lambda s, m: s.proto),
    "state": (KIND_PROCESS, lambda s, m: s.state),
    "ip":    (KIND_IP, lambda s, m: s.remote_ip or None),
    "port":  (KIND_INT, lambda s, m: s.remote_port),
    "lip":   (KIND_IP, lambda s, m: s.local_ip),
    "lport": (KIND_INT, lambda s, m: s.local_port),
}


def _blob(s, _m):
    """What plain text is searched in: every column, the way it is shown."""
    remote_port = "" if s.remote_port is None else s.remote_port
    pid = "" if s.pid is None else s.pid
    return (f"{s.proc} {s.proto} {s.state} {s.local_ip}:{s.local_port} "
            f"{s.remote_ip}:{remote_port} {pid}").lower()


def _ip_key(text, cache):
    """An address as something that sorts by number: v4 before v6, then the value."""
    if not text:
        return None
    key = cache.get(text)
    if key is None:
        address = ipaddress.ip_address(text.split("%")[0])
        key = cache[text] = (address.version, int(address))
    return key


# Per column, the value to sort by. None sorts LAST in both directions: an empty
# cell is not the smallest value, it is no value.
_SORT_KEYS = {
    "proto": lambda s, c: (s.proto, s.family),
    "local_ip": lambda s, c: _ip_key(s.local_ip, c),
    "local_port": lambda s, c: s.local_port,
    "remote_ip": lambda s, c: _ip_key(s.remote_ip, c),
    "remote_port": lambda s, c: s.remote_port,
    "state": lambda s, c: s.state or None,
    "pid": lambda s, c: s.pid,
    "proc": lambda s, c: s.proc.lower() or None,
    "change": lambda s, c: s.at,
}
COLUMNS = tuple(_SORT_KEYS)


def sort(sockets, column, reverse=False):
    """``sockets`` in the order of one column, empty cells last. Stable."""
    key = _SORT_KEYS.get(column, _SORT_KEYS[DEFAULT_SORT[0]])
    cache = {}
    keyed = [(key(s, cache), s) for s in sockets]
    present = [pair for pair in keyed if pair[0] is not None]
    present.sort(key=lambda pair: pair[0], reverse=reverse)
    return [s for _k, s in present] + [s for k, s in keyed if k is None]


def view(snapshot, query="", column=DEFAULT_SORT[0], reverse=False):
    """The sockets ``query`` keeps, sorted. The search box's rules: see views.py."""
    tests = compile_query(query, fields=SEARCH_FIELDS, blob=_blob, bools=())
    kept = [s for s in snapshot.sockets if all(t(s, None) for t in tests)]
    return sort(kept, column, reverse)


def table(snapshot, query, column, reverse, previous=None, fresh_names=True):
    """The worker's whole job: read (when ``snapshot`` is None), then filter and sort.

    ``previous`` and ``fresh_names`` are ``read``'s, for a read that follows another.
    """
    if snapshot is None:
        snapshot = read(previous, fresh_names)
    return View(snapshot, view(snapshot, query, column, reverse), query,
                (column, reverse), next(_MADE))
