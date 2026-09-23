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
"""
import ipaddress
import time
from typing import NamedTuple

from .. import portmap
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


class Snapshot(NamedTuple):
    """One read of the machine."""
    sockets: tuple
    failed: tuple               # the tables that did not answer ("tcp/v6"...)
    read_at: float              # time.time() when the read finished
    elapsed_ms: int


class View(NamedTuple):
    """A snapshot as the person asked to see it."""
    snapshot: Snapshot
    rows: list                  # the sockets the query keeps, in the sort's order
    query: str
    sort: tuple                 # (column, reverse)
    made_at: float              # time.time(): the newest view is the one shown


def read():
    """Read every socket and name its process. Runs on a worker; may raise.

    ``portmap.SocketTableUnavailable`` when no table can be read at all: an empty
    table would say "no sockets", which nobody here could know.
    """
    started = time.perf_counter()
    rows, failed = portmap.socket_rows()
    # Named AFTER the table is read, so a process that exited in between leaves
    # its rows without a name - which is true - instead of the table outliving the
    # names it was given. A PID reused inside those few milliseconds is the one
    # case left: named after its new owner. Accepted; it cannot be told apart.
    names = portmap.process_names()
    return Snapshot(tuple(_sockets(rows, names)), tuple(failed), time.time(),
                    round((time.perf_counter() - started) * 1000))


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
        # PID 0 owns nothing: the snapshot calls it "[System Process]", and a row
        # in TIME_WAIT is not that process's socket.
        name = names.get(row.pid, "") if row.pid else ""
        yield Socket(f"{base}|{repeat}", row.proto, row.family, row.local_ip,
                     row.local_port, row.remote_ip, row.remote_port, row.state,
                     row.pid, name)


def without_owner(snapshot):
    """How many sockets the system would not name a process for (another account's)."""
    return sum(1 for socket in snapshot.sockets if socket.pid is None)


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


def table(snapshot, query, column, reverse):
    """The worker's whole job: read (when ``snapshot`` is None), then filter and sort."""
    if snapshot is None:
        snapshot = read()
    return View(snapshot, view(snapshot, query, column, reverse), query,
                (column, reverse), time.time())
