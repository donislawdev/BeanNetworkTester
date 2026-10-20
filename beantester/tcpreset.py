"""Reset one TCP connection of this machine - the Connections page's row menu.

The tester picks a connection and breaks it NOW, to see what the program does about
it: reconnect, retry, tell its user. ``rst_prob`` and "Reset TCP now" break
connections at random or all of them for a few seconds, and only while a session
runs; this is one chosen connection, at once, idle or not, and after STOP too.

How: ``SetTcpEntry`` with ``MIB_TCP_STATE_DELETE_TCB`` - Microsoft Learn: "the only
state to which a TCP connection can be set". MEASURED 2026-10-14 on this project's
machines: on an open connection both ends get a TCP reset at once - the program that
owned the socket gets WSAECONNRESET (10054) on its next call, and Windows SENDS a RST
to the far end (there 1 ms later, over a real adapter and over loopback alike).
During a session that RST is a packet like any other: with 100% loss on its path it
was dropped, and the far end saw nothing.

What it cannot do, documented and measured:

* IPv6. There is no IPv6 form - Learn has only ``SetTcpEntry``, which takes the IPv4
  ``MIB_TCPROW``, and ``iphlpapi.dll`` exports no ``SetTcp6Entry`` - so an IPv6 row
  is offered nothing (``resettable``).
* A connection still opening (SYN_SENT) or already closing (TIME_WAIT), or one that
  is gone: ``SetTcpEntry`` answered 317 to all three in an ELEVATED process.
* Without administrator rights it answered 317 too. Learn documents 317 as "running
  non-elevated", which is one of its meanings and not the only one, so the reason
  is taken from the process's token (``winenv.is_admin``), never from the number.

A Connections row names the local PORT and the far end, while the call needs the
local ADDRESS as well, so the socket table is read at the click (~1 ms for 178
sockets, measured) and the one connection that matches is the one reset. None: it
has closed since the row was drawn. More than one: the same port on two local
addresses - nothing is guessed.

``tests/test_no_telemetry.py`` lists ``SetTcpEntry`` among the functions that put
something on the wire, with this module as the one place allowed to call it. The row
layout and the search in the socket table are ``tcprow``'s, shared with "TCP health".
"""
import ctypes
import sys
from typing import NamedTuple

from . import crashlog, portmap, tcprow, winenv

MIB_TCP_STATE_DELETE_TCB = 12
# portmap.socket_rows' name for the one table a reset reads (its ``failed`` list).
IPV4_TCP = "tcp/v4"

# How a reset ended. RESET is the one that did something.
RESET = "reset"
GONE = "gone"                   # no such connection in the table any more
AMBIGUOUS = "ambiguous"         # more than one matches: nothing is guessed
REFUSED = "refused"             # Windows said no; ``state`` says what the table showed
NEEDS_ADMIN = "needs_admin"
UNREADABLE = "unreadable"       # the socket table could not be read
NOT_IPV4 = "not_ipv4"           # IPv6, or not an address at all
FAILED = "failed"               # anything else; ``detail`` is the program's own words


class Outcome(NamedTuple):
    kind: str
    state: str = ""             # the TCP state the table showed (REFUSED, NEEDS_ADMIN)
    code: int = 0               # what SetTcpEntry answered
    detail: str = ""            # FAILED: the exception, program text


Target = tcprow.Target          # what the Connections page builds from a row
_TcpRow = tcprow.TcpRow


def row_for(local_ip, target):
    """The ``MIB_TCPROW`` that deletes ``target``'s TCB on ``local_ip``."""
    return tcprow.row_for(tcprow.Connection(local_ip, *target), MIB_TCP_STATE_DELETE_TCB)


def resettable(proto, remote_ip):
    """A Connections row Windows can reset: TCP over IPv4 (there is no IPv6 form)."""
    if proto != "TCP":
        return False
    return tcprow.family(remote_ip) == 4


def supported():
    """``SetTcpEntry`` is Windows'. Asked through ``capabilities``, like every tool's API.

    Without it a reset on Linux reached ``None.SetTcpEntry``: an ``AttributeError``
    reported as FAILED and recorded as a fault of the program (measured 2026-10-20 on
    Ubuntu 26.04 and in WSL, as root and not).
    """
    return sys.platform.startswith("win")


# -- the binding --------------------------------------------------------------------- #
def _iphlpapi():
    """iphlpapi with ``SetTcpEntry``'s prototype; None off Windows."""
    if not sys.platform.startswith("win"):
        return None
    return _declared(ctypes.WinDLL("iphlpapi.dll"))  # pragma: no cover - Windows only (the DLL)


def _declared(lib):
    """``lib`` with the prototype of the one call made here (Microsoft Learn)."""
    lib.SetTcpEntry.argtypes = [ctypes.POINTER(_TcpRow)]
    lib.SetTcpEntry.restype = ctypes.c_uint32
    return lib


class _System:
    """What a reset asks of Windows. Everything is injectable, so it runs in tests
    anywhere. ``rows`` answers as ``portmap.socket_rows`` does: ``(rows, failed)``."""

    def __init__(self, iphlpapi=None, rows=None, is_admin=None):
        self.iphlpapi = iphlpapi if iphlpapi is not None else _iphlpapi()
        self.rows = rows or portmap.socket_rows
        self.is_admin = is_admin or winenv.is_admin

    def delete(self, row):
        return int(self.iphlpapi.SetTcpEntry(ctypes.byref(row)))


def _reset(target, system):
    if not resettable("TCP", target.remote_ip):
        return Outcome(NOT_IPV4)
    try:
        rows, failed = system.rows()
    except portmap.SocketTableUnavailable:
        return Outcome(UNREADABLE)
    if IPV4_TCP in failed:
        # The one table this needs did not answer while others did: a missing row
        # says nothing about the connection, and "already closed" would be a guess.
        return Outcome(UNREADABLE)
    found = tcprow.matching(rows, target)
    if not found:
        return Outcome(GONE)
    if len(found) > 1:
        return Outcome(AMBIGUOUS)
    code = system.delete(row_for(found[0].local_ip, target))
    if code == 0:
        return Outcome(RESET)
    return Outcome(REFUSED if system.is_admin() else NEEDS_ADMIN, found[0].state, code)


def reset(target, system=None):
    """Reset the connection ``target`` names. On a worker; never raises - a click
    has to end in a sentence, not in a traceback on a thread nobody watches."""
    try:
        return _reset(target, system or _System())
    except Exception as exc:
        crashlog.note(exc, "tcpreset")
        return Outcome(FAILED, detail=f"{type(exc).__name__}: {exc}")
