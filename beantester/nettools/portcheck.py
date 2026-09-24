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
* WSAEACCES is not always a reservation (Learn: an exclusive socket of another
  program, a wildcard socket of another account) - but those are in the table,
  and a row there wins. Off Windows, EACCES is a port this account may not use
  (below 1024 on Linux), not a reservation.

Nothing here draws or translates; the port parser's message, which arrives in the
window's language, is the one exception nettools already names.
"""
import errno
import socket
import sys
import time
from typing import NamedTuple

from ..matchers import KIND_INT, PORT_BOUNDS, parse_matcher
from . import Refused, sockets

# More ports than this in one check is refused rather than run: 1000 ports x TCP and
# UDP x IPv4 and IPv6 is 4000 binds, ~0.3 s on the worker (83 us each, measured) -
# and a table a person can still read.
MAX_PORTS = 1000
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
IN_USE, UNSEEN, RESERVED, DENIED, CLOSING, FAILED, FREE = (
    "in_use", "unseen", "reserved", "denied", "closing", "failed", "free")
VERDICTS = (IN_USE, UNSEEN, RESERVED, DENIED, CLOSING, FAILED, FREE)


class Row(NamedTuple):
    """One port, one protocol, one IP version."""
    key: str
    port: int
    proto: str
    family: int
    verdict: str
    code: int           # what bind answered: 0 when it bound, else the error number
    owners: tuple       # (pid, name) holding this port there; no TIME_WAIT, name "" if unknown


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
    if len(wanted) > MAX_PORTS:
        raise Refused("tools.portcheck.error_too_many", count=len(wanted), limit=MAX_PORTS)
    return wanted, zero


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


def verdict(code, owners, closing):
    """What one bind answer and the socket table say together."""
    if owners:
        return IN_USE           # the table names a holder, whatever bind said
    if code == 0:
        return FREE
    if code in IN_USE_CODES:
        return CLOSING if closing else UNSEEN
    if code in ACCESS_CODES:
        return RESERVED if WINDOWS else DENIED
    return FAILED


def check(matcher, protocols, families, bind=probe, read=sockets.read):
    """The worker's whole job: ask the system for every port, then read who holds them.

    The binds come FIRST and the table after, so a holder that starts in between is
    in the table and the answer errs towards "in use", never towards "free".
    ``sockets.Unreadable`` travels as it is: "free" without the table is a claim
    this code cannot make (a dual-stack server is invisible to a bind).
    """
    started = time.perf_counter()
    wanted, zero = ports(matcher)
    codes, unavailable = {}, []
    for family in families:
        answers = _ask_family(bind, family, protocols, wanted)
        if answers is None:
            unavailable.append(family)
        else:
            codes.update(answers)
    live, closing = _holders(read())
    rows = [_row(where, code, live, closing) for where, code in codes.items()]
    return Check(tuple(sort(rows)), str(matcher), tuple(protocols),
                 tuple(f for f in families if f not in unavailable), zero,
                 tuple(unavailable), time.time(),
                 round((time.perf_counter() - started) * 1000))


def _ask_family(bind, family, protocols, wanted):
    """``{(port, proto, family): code}``, or None when the machine has no such IP version.

    The first answer that says so ends the version: a machine without IPv6 would
    otherwise say it once per port.
    """
    answers = {}
    for proto in protocols:
        for port in wanted:
            code = bind(proto, family, port)
            if code in NO_FAMILY_CODES:
                return None
            answers[(port, proto, family)] = code
    return answers


def _holders(snapshot):
    """``(live, closing)``: owners by ``(port, proto, family)``, and where only TIME_WAIT sits."""
    live, closing = {}, set()
    for s in snapshot.sockets:
        where = (s.local_port, s.proto, s.family)
        if s.state == "TIME_WAIT":
            closing.add(where)
        else:
            live.setdefault(where, set()).add((s.pid, s.proc))
    return live, closing


def _row(where, code, live, closing):
    port, proto, family = where
    owners = tuple(sorted(live.get(where, ()), key=lambda o: (o[0] is None, o[0] or 0, o[1])))
    return Row(f"{port}|{proto}|{family}", port, proto, family,
               verdict(code, owners, where in closing), code, owners)


def not_free(rows):
    """How many rows a program could not simply take."""
    return sum(1 for row in rows if row.verdict != FREE)


# Per column, the value to sort by. None sorts LAST in both directions: an empty
# cell is not the smallest value, it is no value.
_SORT_KEYS = {
    "port": lambda r: r.port,
    "proto": lambda r: r.proto,
    "family": lambda r: r.family,
    "verdict": lambda r: VERDICTS.index(r.verdict),
    # By name, then PID: a holder the system would not name sorts among its PIDs.
    "holder": lambda r: (r.owners[0][1].lower(), r.owners[0][0] or 0) if r.owners else None,
}
COLUMNS = tuple(_SORT_KEYS)
DEFAULT_SORT = ("verdict", False)


def sort(rows, column=DEFAULT_SORT[0], reverse=False):
    """``rows`` in the order of one column, ties by port, protocol and IP version.

    On the UI thread when a header is clicked: at most ``MAX_PORTS`` x 4 rows.
    """
    key = _SORT_KEYS.get(column, _SORT_KEYS[DEFAULT_SORT[0]])
    base = sorted(rows, key=lambda r: (r.port, r.proto, r.family))
    present = [r for r in base if key(r) is not None]
    present.sort(key=key, reverse=reverse)      # stable: ties keep the port order
    return present + [r for r in base if key(r) is None]
