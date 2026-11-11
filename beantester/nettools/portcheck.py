"""Is a port free? What this machine answers when a program asks for it, and who has it.

A tester whose development server "will not start on 9010" is asking three things
at once: does another program hold that port, did Windows set it aside, or is it
free after all. This answers all three, per protocol and per IP version - Windows
sets ranges aside for TCP and for UDP separately (B-19: TCP 9001-9100 on the
developer machine, UDP untouched).

How, and why this way - measured 2026-09-24 on Windows 11 and on a Windows Server
2025 VM, loopback only (the Tools-tab design notes, section 17):

* **The system is asked on the LOOPBACK address** (127.0.0.1, ::1): ``bind``, then
  close. A port in a range Windows set aside answers WSAEACCES there exactly as on
  the wildcard address. Nothing listens: on the VM a bind on any address raised
  only the "bind permitted" audit event, while a LISTEN on 0.0.0.0 had Windows
  create two inbound block rules for the program by itself.
* **Who holds a port comes from the socket table** (``sockets.read``), not from the
  bind. A dual-stack server on ``[::]`` - how Node listens by default - is in the
  table on IPv4 and IPv6 and invisible to every bind, even with
  SO_EXCLUSIVEADDRUSE, even a listen. And a bind on loopback succeeds beside a
  server on 0.0.0.0 (Learn, "Using SO_REUSEADDR and SO_EXCLUSIVEADDRUSE").
* **TIME_WAIT holds nothing** on Windows: a bind succeeds beside it, so its rows
  are not owners. Where a bind DOES fail beside one (Linux), the port is closing.
* **Linux lists a dual-stack socket once**, under IPv6: the server on ``[::]`` and
  the connections it accepted from IPv4, which carry ``::ffff:127.0.0.1``. So an
  ``::ffff:`` address counts as IPv4, and on Linux an IPv4 bind refused beside a
  socket on ``[::]`` names that socket - one for IPv6 alone lets the bind through
  (MEASURED 2026-11-03, Ubuntu 26.04 and WSL, the release rig). Not beside an IPv4
  connection's TIME_WAIT, which refuses the bind by itself: the table cannot tell the
  two kinds of ``[::]`` apart (MEASURED 2026-11-04, the same rig). Windows lists a
  dual-stack socket under IPv4 too, so there a socket on ``[::]`` is never asked.
* WSAEACCES is not always a reservation (Learn: an exclusive socket of another
  program, a wildcard socket of another account) - but those are in the table,
  and a row there wins. Off Windows, EACCES is a port this account may not use
  (below 1024 on Linux), not a reservation.
* **A table that did not answer** (Windows reads four, and ``sockets.read`` names
  the ones that failed) cannot say "nobody holds this port". Free and Reserved both
  rest on exactly that, so a row of that table reads Unknown instead, and the check
  names the tables.
* **Every port of the machine** is 65535 ports x TCP and UDP x IPv4 and IPv6 =
  262 140 binds. MEASURED 2026-11-11 (``internal_tools/sondy/2026-11-11-ports-full-
  scan``): 12.2 s on Windows 11, 3.6 s on Linux (WSL), 35.5 s on a Windows Server
  2025 VM. So a check says how far it is and stops when asked (``Progress``), and
  ports next to each other that answered the same come back as one row
  (``Row.last``): the developer machine's 3323 ports that were not free are 105 rows.

Nothing here draws or translates; the port parser's message, which arrives in the
window's language, is the one exception nettools already names.
"""
import errno
import ipaddress
import socket
import sys
import time
from typing import NamedTuple

from .. import crashlog
from ..matchers import KIND_INT, PORT_BOUNDS, parse_matcher
from . import Refused, adapters, sockets

# What the "All ports" button types into the box.
ALL_PORTS = "1-65535"
PROTOCOLS = ("TCP", "UDP")
FAMILIES = (4, 6)
# What the parser's messages call the box the ports are typed in.
FIELD = "tools.portcheck.ports"

_KIND = {"TCP": socket.SOCK_STREAM, "UDP": socket.SOCK_DGRAM}
_LOOPBACK = {4: (socket.AF_INET, "127.0.0.1"), 6: (socket.AF_INET6, "::1")}

# What a failed bind means. The Windows numbers are Learn's (System Error Codes
# 9000-11999); Python reports some of them through errno as well, so both are here.
IN_USE_CODES = frozenset({errno.EADDRINUSE, 10048})                  # WSAEADDRINUSE
ACCESS_CODES = frozenset({errno.EACCES, 10013})                      # WSAEACCES
NO_FAMILY_CODES = frozenset({errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL,
                             10047, 10049})       # WSAEAFNOSUPPORT, WSAEADDRNOTAVAIL
WINDOWS = sys.platform.startswith("win")

# Verdicts. VERDICTS is also the table's default order: what stops a program first.
IN_USE, UNSEEN, RESERVED, DENIED, CLOSING, FAILED, UNREAD, FREE = (
    "in_use", "unseen", "reserved", "denied", "closing", "failed", "unread", "free")
VERDICTS = (IN_USE, UNSEEN, RESERVED, DENIED, CLOSING, FAILED, UNREAD, FREE)
# How ``sockets.read`` names a table that did not answer (``portmap``: "tcp/v4").
TABLE_NAMES = {f"{proto.lower()}/v{family}": (proto, family)
               for proto in PROTOCOLS for family in FAMILIES}

# How long binds wait for the socket table that says who holds their ports. The
# table comes AFTER the binds (``check``), and a short connection that held a port
# at its bind may be gone by the read - its row then reads "in use (owner not
# shown)". Once at the end of a 35 s check is too late for that, so the table is
# read about once a second: ~95 ms a read on the developer machine (2026-11-11),
# about a tenth of the time of a check of every port, and one read for a short one.
READ_EVERY_S = 1.0

# Where a holder waits for every network: a socket on one of these takes a
# connection on any of the machine's addresses. Compared with, never bound to.
WILDCARDS = frozenset({"0.0.0.0", "::"})  # noqa: S104

# A check of more binds than this asks first where Windows writes each bind to its
# Security log (``winenv.binds_audited``). MEASURED 2026-11-11 on the Server VM with
# "Filtering Platform Connection" success auditing on: one event 5158 per bind, in
# a log of 20 MB holding 32 117 records - every port is 262 140 events, which pushes
# the whole history out of it. 4000 binds (1000 ports) was the most one check made
# before every port could be checked.
AUDIT_ASK_BINDS = 4000


class Row(NamedTuple):
    """One port - or ports next to each other that answered the same - for one
    protocol and one IP version."""
    key: str
    port: int           # the first port
    last: int           # the last port: ``port`` when the row is one port
    proto: str
    family: int
    verdict: str
    code: int           # what bind answered: 0 when it bound, else the error number
    owners: tuple       # (pid, name) holding this port there; no TIME_WAIT, name "" if unknown
    # The local addresses the holders wait for connections on, the wildcard ones
    # first; () when nobody holds the port, or only connections do (``_listens``).
    listens: tuple = ()

    def size(self):
        """How many ports the row stands for."""
        return self.last - self.port + 1


class Check(NamedTuple):
    """One check of the machine."""
    rows: tuple
    asked: str              # the ports as typed
    protocols: tuple
    families: tuple         # the IP versions that were checked
    skipped_zero: bool      # the expression names port 0, which was left out
    unavailable: tuple      # IP versions this machine has no loopback address for
    checked_at: float
    elapsed_ms: int
    unread: tuple = ()      # (proto, family) checked whose socket table did not answer
    made: int = 0           # binds made: one per port, protocol and IP version
    planned: int = 0        # binds the check set out to make; more than ``made`` after Stop
    stopped_at: tuple | None = None     # (proto, family, port) of the last bind, after Stop
    # {address: (rank, adapter name)} for the addresses the rows listen on, from the
    # Adapters tab's reader (``with_adapter_names``); None when not read.
    names: dict | None = None

    @property
    def stopped(self):
        """Stop came before the last bind: the rows are only what was checked."""
        return self.made < self.planned


class Progress:
    """How far a running check is, and the Stop that ends it.

    The worker writes it and the window reads it, each attribute written whole (an
    int, a tuple), so a read sees the old value or the new one. ``stop`` may come
    from any thread: the worker looks before every bind, then reads the socket
    table for the binds it made, so the rows it returns are true as far as they go.
    """

    def __init__(self):
        self.made = 0           # binds made so far
        self.planned = 0        # binds this check makes; 0 until the ports are listed
        self.at = None          # (proto, family, port) of the latest bind
        self.stopped = False

    def stop(self):
        self.stopped = True

    def percent(self):
        return min(100, self.made * 100 // self.planned) if self.planned else 0


def parse(text):
    """The typed ports as a matcher, in the Control page's port language.

    Raises ``ValueError`` with a message in the window's language. Cheap - the UI
    thread asks it before starting the worker; the ports are listed on the worker.
    """
    return parse_matcher(text, KIND_INT, FIELD, PORT_BOUNDS)


def ports(matcher):
    """``(ports, skipped_zero)``: the ports from 1 to 65535 the matcher names, in order.

    Port 0 is never checked: a program that binds it is handed any free port, so
    "is 0 free" has no answer. The bounds of the port language allow 0, so it is
    left out here and said.
    """
    wanted = tuple(port for port in range(1, 65536) if matcher.matches(port))
    zero = matcher.matches(0)
    if not wanted:
        raise Refused("tools.portcheck.error_zero" if zero else "tools.portcheck.error_none")
    return wanted, zero


def planned(matcher, protocols, families):
    """How many binds a check of these ports would make; 0 for ports the check refuses
    (the worker says why). Lists the ports, so the UI thread asks it only when the
    answer changes what happens (``AUDIT_ASK_BINDS``)."""
    try:
        return len(ports(matcher)[0]) * len(protocols) * len(families)
    except Refused:
        return 0


def probe(proto, family, port):
    """0 when the system hands this port out on the loopback address, else the error.

    ``bind`` and close - no listen, no connect, nothing sent. Runs on the worker.
    """
    address_family, address = _LOOPBACK[family]
    try:
        sock = socket.socket(address_family, _KIND[proto])
    except OSError as exc:
        return _code(exc)
    with sock:
        try:
            sock.bind((address, port))
        except OSError as exc:
            return _code(exc)
    return 0


def _code(exc):
    return getattr(exc, "winerror", None) or exc.errno or -1


def verdict(code, owners, closing, unread=False):
    """What one bind answer and the socket table say together; ``unread``: that
    table did not answer, so nobody can say that no program holds the port."""
    if owners:
        return IN_USE           # the table names a holder, whatever bind said
    said = _bound(code, closing)
    # Free and Reserved rest on the table naming nobody: a dual-stack server is
    # invisible to a bind, another program's exclusive socket answers WSAEACCES.
    return UNREAD if unread and said in (FREE, RESERVED) else said


def _bound(code, closing):
    if code == 0:
        return FREE
    if code in IN_USE_CODES:
        return CLOSING if closing else UNSEEN
    if code in ACCESS_CODES:
        return RESERVED if WINDOWS else DENIED
    return FAILED


def _table(read=None):
    """The socket table, read again and again through one check: each read after the
    first keeps the process names the one before it was given, and asks the system
    for its processes only when a PID it has not named turns up (``sockets.read``'s
    ``fresh_names``). MEASURED 2026-11-10: 71 ms of a 73 ms read was that process
    snapshot - and a check of every port reads the table about thirty times."""
    last = [None]

    def again():
        last[0] = (read or sockets.read)(last[0], fresh_names=last[0] is None)
        return last[0]
    return again


def check(matcher, protocols, families, bind=probe, read=None, progress=None,
          clock=time.monotonic):
    """The worker's whole job: ask the system for every port, then read who holds them.

    The binds come FIRST and the table after, so a holder that starts in between is
    in the table and the answer errs towards "in use", never towards "free". The
    table is read once the binds waiting for it are ``READ_EVERY_S`` old, and once
    more at the end - after Stop too, for the binds made before it.
    ``sockets.Unreadable`` travels as it is: "free" without the table is a claim
    this code cannot make (a dual-stack server is invisible to a bind). For the same
    reason a table that failed while the others answered makes its rows Unknown.
    """
    started = time.perf_counter()
    progress = Progress() if progress is None else progress
    wanted, zero = ports(matcher)
    progress.planned = len(wanted) * len(protocols) * len(families)
    answers = _Answers(_table() if read is None else read, clock)
    unavailable = []
    for family in families:
        made = progress.made
        if _ask_family(bind, family, protocols, wanted, answers, progress) is None:
            unavailable.append(family)
            answers.drop(family)
            progress.made = made
            progress.planned -= len(wanted) * len(protocols)
        if progress.stopped:
            break
    answers.resolve()
    checked = tuple(f for f in families if f not in unavailable)
    stopped = progress.made < progress.planned
    return Check(tuple(sort(answers.rows)), str(matcher), tuple(protocols), checked, zero,
                 tuple(unavailable), time.time(),
                 round((time.perf_counter() - started) * 1000), tuple(sorted(answers.unread)),
                 progress.made, progress.planned, progress.at if stopped else None)


def _ask_family(bind, family, protocols, wanted, answers, progress):
    """Bind every port on one IP version, until Stop; None when the machine has no
    such IP version.

    The first answer that says so ends the version: a machine without IPv6 would
    otherwise say it once per port.
    """
    for proto in protocols:
        for port in wanted:
            if progress.stopped:
                return True
            code = bind(proto, family, port)
            if code in NO_FAMILY_CODES:
                return None
            progress.made += 1
            progress.at = (proto, family, port)
            answers.add(port, proto, family, code)
    return True


class _Answers:
    """The binds waiting for the socket table, and the rows they became."""

    def __init__(self, read, clock):
        self._read = read
        self._clock = clock
        self._waiting = []      # (port, proto, family, code), in the order bound
        self._since = None      # clock() at the oldest bind waiting
        self.rows = []
        self.unread = set()     # (proto, family) of rows whose table did not answer

    def add(self, port, proto, family, code):
        now = self._clock()
        if self._since is None:
            self._since = now
        self._waiting.append((port, proto, family, code))
        if now - self._since >= READ_EVERY_S:
            self.resolve()

    def drop(self, family):
        """An IP version this machine turned out not to have: none of its rows."""
        self._waiting = [a for a in self._waiting if a[2] != family]
        self.rows = [row for row in self.rows if row.family != family]
        self.unread = {table for table in self.unread if table[1] != family}

    def resolve(self):
        """Read the socket table and turn the binds waiting for it into rows."""
        if not self._waiting:
            return
        snapshot = self._read()
        held = _holders(snapshot)
        failed = {TABLE_NAMES[name] for name in snapshot.failed}
        for port, proto, family, code in self._waiting:
            unread = (proto, family) in failed
            if unread:
                self.unread.add((proto, family))
            _fold(self.rows, _row((port, proto, family), code, held, unread))
        self._waiting, self._since = [], None


def _fold(rows, row):
    """Add ``row``, or widen the row before it to take it in: the next port of the
    same protocol and IP version, with the same answer, holders and addresses."""
    last = rows[-1] if rows else None
    if (last is not None and row.port == last.last + 1
            and (row.proto, row.family, row.verdict, row.code, row.owners, row.listens)
            == (last.proto, last.family, last.verdict, last.code, last.owners, last.listens)):
        rows[-1] = last._replace(last=row.port)
    else:
        rows.append(row)


def unfold(rows):
    """One row per port, for a reader that asks about ports one by one (the rig)."""
    for row in rows:
        for port in range(row.port, row.last + 1):
            yield row._replace(key=f"{port}|{row.proto}|{row.family}", port=port, last=port)


def _holders(snapshot):
    """``(live, closing, native_closing, wide)``: the sockets holding each
    ``(port, proto, family)``, where TIME_WAIT sits, where an IPv4 socket's own sits
    (not an ``::ffff:`` one), and the sockets on the IPv6 wildcard address by
    ``(port, proto)``."""
    live, closing, native_closing, wide = {}, set(), set(), {}
    for s in snapshot.sockets:
        if s.change == sockets.CLOSED:
            continue        # gone since the read before: a read after another lists those
        family = _version(s)
        where = (s.local_port, s.proto, family)
        if s.state == "TIME_WAIT":
            closing.add(where)
            if s.family == 4:
                native_closing.add(where)
            continue
        live.setdefault(where, []).append(s)
        if family == 6 and s.local_ip == "::":
            wide.setdefault((s.local_port, s.proto), []).append(s)
    return live, closing, native_closing, wide


def _version(s):
    """The IP version a socket holds its port on: 4 for an IPv4 address written the
    IPv6 way (``::ffff:127.0.0.1``), which is where Linux lists them."""
    if s.family == 6 and s.local_ip.startswith("::ffff:") and "." in s.local_ip:
        return 4
    return s.family


def _row(where, code, held, unread):
    live, closing, native_closing, wide = held
    port, proto, family = where
    found = live.get(where, ())
    if (not WINDOWS and not found and family == 4 and code in IN_USE_CODES
            and where not in native_closing):
        # Refused, and the table names no IPv4 holder: a socket on [::] that takes IPv4
        # too, listed under IPv6 alone. Asked before the TIME_WAIT such a server's own
        # closed connections leave beside it (::ffff:), never beside an IPv4 socket's,
        # which explains the refusal while [::] may be for IPv6 alone.
        found = wide.get((port, proto), ())
    owners = tuple(sorted({(s.pid, s.proc) for s in found},
                          key=lambda o: (o[0] is None, o[0] or 0, o[1])))
    return Row(f"{port}|{proto}|{family}", port, port, proto, family,
               verdict(code, owners, where in closing, unread), code, owners, _listens(found))


def _listens(found):
    """The local addresses the holders wait for connections on, the wildcard ones
    first. A socket with a far end is a connection and waits for nobody; UDP has no
    far end in the table, so a UDP socket waits - the rule of the Sockets tab's
    "Listening" choice (``sockets._SHOWN``)."""
    places = {s.local_ip for s in found if not s.remote_ip}
    return tuple(sorted(places, key=lambda ip: (ip not in WILDCARDS, ip)))


# -- the Listens on column ------------------------------------------------------- #
ANYWHERE, ADAPTER, ADDRESS, THIS_COMPUTER, CONNECTION = (
    "any", "adapter", "address", "loopback", "connection")


def listens_on(row, names=None):
    """Where the row's holders wait, as ``(kind, value)`` pairs in the column's order.

    ``(ANYWHERE, "")`` alone when one waits on a wildcard address - it takes a
    connection on any of them. Otherwise each adapter by name (``names``, from
    ``adapter_names``, in the Adapters tab's order), an address no adapter has as
    itself, and ``(THIS_COMPUTER, "")`` last for the loopback addresses.
    ``((CONNECTION, ""),)`` when only connections hold the port, () when nothing does.
    Where the holder waits, not who can reach it: a firewall is not in this table
    (MEASURED 2026-11-11: port 445 here and 47001 on the Server VM wait on every
    address and answer nobody from the network).
    """
    if not row.owners:
        return ()
    if not row.listens:
        return ((CONNECTION, ""),)
    if any(ip in WILDCARDS for ip in row.listens):
        return ((ANYWHERE, ""),)
    names = names or {}
    found, loopback = {}, False
    for ip in row.listens:
        bare = _bare(ip)
        if _is_loopback(bare):
            loopback = True
        elif bare in names:
            rank, name = names[bare]
            found[(ADAPTER, name)] = (0, rank, name)
        else:
            found[(ADDRESS, ip)] = (1, 0, ip)
    pairs = sorted(found, key=found.__getitem__)
    return tuple(pairs + [(THIS_COMPUTER, "")] if loopback else pairs)


def _bare(ip):
    """An address the way an adapter lists it: no IPv6 zone, an IPv4 address written
    the IPv6 way (``::ffff:192.168.1.5``, how Linux lists them) as IPv4."""
    ip = ip.split("%")[0]
    return ip[7:] if ip.startswith("::ffff:") and "." in ip else ip


def _is_loopback(ip):
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def adapter_names(read=None):
    """``{address: (rank, adapter name)}`` for every address of every adapter, in the
    Adapters tab's order; {} when they cannot be read - the column then shows the
    bare address, which is still true."""
    if read is None and not adapters.supported():
        return {}
    try:
        snapshot = (read or adapters.read)()
    except (adapters.Unreadable, OSError):
        return {}
    except Exception as exc:
        # The names only label the addresses: the check itself stands, so a fault
        # here goes to the crash log and the column shows the addresses.
        crashlog.note(exc, "nettools.portcheck")
        return {}
    names = {}
    for rank, adapter in enumerate(snapshot.adapters):
        for address in adapter.row.addresses:
            names.setdefault(_bare(address.ip), (rank, adapter.row.name))
    return names


def with_adapter_names(result, read=None):
    """The check with ``names`` filled in, read only when a row waits on an address
    of one adapter: most holders wait on every address or on loopback alone, and
    those need no adapter."""
    wanted = any(not _is_loopback(_bare(ip)) for row in result.rows for ip in row.listens
                 if ip not in WILDCARDS)
    return result._replace(names=adapter_names(read) if wanted else {})


def not_free(rows):
    """How many ports - per protocol and IP version - a program could not simply take.
    Not the Unknown ones: whether a program could take those is what is not known
    (``unknown``)."""
    return sum(row.size() for row in rows if row.verdict not in (FREE, UNREAD))


def unknown(rows):
    """How many ports may be free or taken: their socket table did not answer."""
    return sum(row.size() for row in rows if row.verdict == UNREAD)


def checked(rows):
    """How many ports - per protocol and IP version - the rows stand for."""
    return sum(row.size() for row in rows)


# Per column, the value to sort by. None sorts LAST in both directions: an empty
# cell is not the smallest value, it is no value.
_SORT_KEYS = {
    "port": lambda r: r.port,
    "proto": lambda r: r.proto,
    "family": lambda r: r.family,
    "verdict": lambda r: VERDICTS.index(r.verdict),
    # By name, then PID: a holder the system would not name sorts among its PIDs.
    "holder": lambda r: (r.owners[0][1].lower(), r.owners[0][0] or 0) if r.owners else None,
    # The addresses as the system lists them, a holder with none (a connection) after.
    "listens": lambda r: ((0, r.listens) if r.listens else (1, ())) if r.owners else None,
}
COLUMNS = tuple(_SORT_KEYS)
DEFAULT_SORT = ("verdict", False)


def sort(rows, column=DEFAULT_SORT[0], reverse=False):
    """``rows`` in the order of one column, ties by port, protocol and IP version.

    On the UI thread when a header is clicked. Every port of a machine is a few
    hundred rows once folded (105 not free on the developer machine, 2026-11-11);
    the measured worst, 262 140 unfolded rows, sorted in 0.1 s.
    """
    key = _SORT_KEYS.get(column, _SORT_KEYS[DEFAULT_SORT[0]])
    base = sorted(rows, key=lambda r: (r.port, r.proto, r.family))
    present = [r for r in base if key(r) is not None]
    present.sort(key=key, reverse=reverse)      # stable: ties keep the port order
    return present + [r for r in base if key(r) is None]
