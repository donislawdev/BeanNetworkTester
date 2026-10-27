"""Reset one TCP connection of this machine - the Connections page's row menu.

The tester picks a connection and breaks it NOW, to see what the program does about
it: reconnect, retry, tell its user. ``rst_prob`` and "Reset TCP now" break
connections at random or all of them for a few seconds, and only while a session
runs; this is one chosen connection, at once, idle or not, and after STOP too.

How, on Windows: ``SetTcpEntry`` with ``MIB_TCP_STATE_DELETE_TCB`` - Microsoft Learn: "the only
state to which a TCP connection can be set". MEASURED 2026-10-14 on this project's
machines: on an open connection both ends get a TCP reset at once - the program that
owned the socket gets WSAECONNRESET (10054) on its next call, and Windows SENDS a RST
to the far end (there 1 ms later, over a real adapter and over loopback alike).
During a session that RST is a packet like any other: with 100% loss on its path it
was dropped, and the far end saw nothing.

What it cannot do on Windows, documented and measured:

* IPv6. There is no IPv6 form - Learn has only ``SetTcpEntry``, which takes the IPv4
  ``MIB_TCPROW``, and ``iphlpapi.dll`` exports no ``SetTcp6Entry`` - so there an IPv6
  row is offered nothing (``resettable``).
* A connection still opening (SYN_SENT) or already closing (TIME_WAIT), or one that
  is gone: ``SetTcpEntry`` answered 317 to all three in an ELEVATED process.
* Without administrator rights it answered 317 too. Learn documents 317 as "running
  non-elevated", which is one of its meanings and not the only one, so the reason
  is taken from the process's token (``winenv.is_admin``), never from the number.

A Connections row names the local PORT and the far end, while the call needs the
local ADDRESS as well (on Linux the socket's id), so the socket table is read at the
click (~1 ms for 178 sockets on Windows, measured) and the one connection that matches
is the one reset. None: it
has closed since the row was drawn. More than one: the same port on two local
addresses - nothing is guessed.

On Linux the kernel resets a connection itself: SOCK_DESTROY, sent through sock_diag
to the socket's id in the kernel's own list (``sockdiag``). MEASURED 2026-10-26
(``internal_tools`` probes ``2026-10-26-linux-reset``, Ubuntu 26.04.1 with kernel 7.0.0,
WSL with 6.18), and the reason for each rule:

* On an open connection the program that owned the socket gets ECONNABORTED (103) at
  once, even while it waits in ``recv``, and the far end a reset (ECONNRESET). IPv6
  too, and a socket a program opened as IPv6 for an IPv4 address (``sockdiag``).
* 🔴 The kernel looks a connection up by its addresses and ports, and when there is
  no such connection it takes the LISTENER on that local port: a server-side
  connection that had just closed, destroyed by its numbers alone, took the server
  down - every new connection was refused. So the request always carries the
  socket's cookie from the list; for a socket that has gone the kernel then answers
  ENOENT and touches nothing.
* It destroys a socket in any state, a reset to the far end only in the states of
  ``RESETS`` (``tcp_need_reset``): a connection still opening was dropped and nobody
  was sent anything. So the rule Windows applies by itself is applied here.
* Without CAP_NET_ADMIN (root has it; so does a program given the capture's three
  capabilities) the list reads and the destroy answers EPERM. A kernel built without
  ``CONFIG_INET_DIAG_DESTROY`` - WSL's - answers EOPNOTSUPP to every destroy, and to
  one that names no socket at all, which is how ``supported`` asks.

``tests/test_no_telemetry.py`` lists ``SetTcpEntry`` and ``SOCK_DESTROY`` among the
names that put something on the wire, with this module as the one place allowed to use
them. The row layout and the search in the socket table are ``tcprow``'s, shared with
"TCP health"; the kernel's list is ``sockdiag``'s.
"""
import ctypes
import sys
from typing import NamedTuple

from . import crashlog, portmap, sockdiag, tcprow, winenv

MIB_TCP_STATE_DELETE_TCB = 12
# portmap.socket_rows' name for the one table a reset reads (its ``failed`` list).
IPV4_TCP = "tcp/v4"

# How a reset ended. RESET is the one that did something.
RESET = "reset"
GONE = "gone"                   # no such connection in the table any more
AMBIGUOUS = "ambiguous"         # more than one matches: nothing is guessed
REFUSED = "refused"             # not in a state it is reset in; ``state`` says which
NEEDS_ADMIN = "needs_admin"
UNREADABLE = "unreadable"       # the socket table could not be read
NOT_IPV4 = "not_ipv4"           # a family this system cannot reset, or not an address
FAILED = "failed"               # anything else; ``detail`` is the program's own words

# Linux: the kernel's numbers (``include/uapi/linux/sock_diag.h``, ``errno-base.h``).
SOCK_DESTROY = 21
EPERM, ENOENT = 1, 2
# The states in which the kernel sends the far end a reset (``tcp_need_reset``), in
# ``sockdiag.STATES``' words. Linux would also drop a connection still opening, or a
# TIME_WAIT entry, and tell nobody: refused here, as Windows refuses them itself.
RESETS = frozenset({"ESTABLISHED", "CLOSE_WAIT", "FIN_WAIT_1", "FIN_WAIT_2", "SYN_RECEIVED"})
# A destroy that names no socket: port 0 is never bound, and 0 is no socket's cookie
# (the kernel numbers them from 1). ENOENT: this kernel destroys sockets. EOPNOTSUPP:
# it was built without (WSL). Neither needs rights - a destroy is refused for those
# only once a socket is found.
NOBODY = sockdiag.sockid(cookie=(0, 0))


class Outcome(NamedTuple):
    kind: str
    state: str = ""             # the TCP state the table showed (REFUSED, NEEDS_ADMIN)
    code: int = 0               # what SetTcpEntry or SOCK_DESTROY answered
    detail: str = ""            # FAILED: the exception, program text


Target = tcprow.Target          # what the Connections page builds from a row
_TcpRow = tcprow.TcpRow


def row_for(local_ip, target):
    """The ``MIB_TCPROW`` that deletes ``target``'s TCB on ``local_ip``."""
    return tcprow.row_for(tcprow.Connection(local_ip, *target), MIB_TCP_STATE_DELETE_TCB)


def resettable(proto, remote_ip, system=None):
    """A Connections row this system can reset: TCP over the families it takes - IPv4
    on Windows (there is no IPv6 form), IPv4 and IPv6 on Linux. ``system``: a system
    class or one of its objects; this machine's when left out."""
    if proto != "TCP":
        return False
    return tcprow.family(remote_ip) in (system or _system_class()).FAMILIES


def supported():
    """Windows has ``SetTcpEntry``; Linux has SOCK_DESTROY when its kernel was built with
    it (``_Linux.can_destroy``). Asked through ``capabilities``, like every tool's API.

    Without the question a reset on Linux reached ``None.SetTcpEntry``: an
    ``AttributeError`` reported as FAILED and recorded as a fault of the program
    (measured 2026-10-20 on Ubuntu 26.04 and in WSL, as root and not).
    """
    if sys.platform.startswith("win"):
        return True
    return sys.platform.startswith("linux") and _Linux().can_destroy()


# -- Windows ------------------------------------------------------------------------- #
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
    FAMILIES = (4,)             # SetTcpEntry takes MIB_TCPROW: IPv4 only

    def __init__(self, iphlpapi=None, rows=None, is_admin=None):
        self.iphlpapi = iphlpapi if iphlpapi is not None else _iphlpapi()
        self.rows = rows or portmap.socket_rows
        self.is_admin = is_admin or winenv.is_admin

    def delete(self, row):
        return int(self.iphlpapi.SetTcpEntry(ctypes.byref(row)))

    def end(self, found, target):
        """Reset the one connection found. Windows refuses the states it does not reset."""
        code = self.delete(row_for(found.local_ip, target))
        if code == 0:
            return Outcome(RESET)
        return Outcome(REFUSED if self.is_admin() else NEEDS_ADMIN, found.state, code)


# -- Linux --------------------------------------------------------------------------- #
class _Linux:
    """What a reset asks of Linux: the kernel's list (``sockdiag``) and SOCK_DESTROY for
    the one socket found in it. ``talk`` sends one request as ``sockdiag.exchange``
    does - a test brings its own."""
    FAMILIES = (4, 6)

    def __init__(self, talk=None):
        self.talk = talk or sockdiag.exchange

    def rows(self):
        try:
            return sockdiag.tcp_sockets(self.talk), []
        except OSError as exc:
            raise portmap.SocketTableUnavailable("missing", str(exc)) from exc

    def destroy(self, kernel_family, sid):
        """SOCK_DESTROY for the socket ``sid`` names; the errno it answered, 0 = done."""
        return sockdiag.error_of(self.talk(sockdiag.request(
            SOCK_DESTROY, sockdiag.NLM_F_REQUEST | sockdiag.NLM_F_ACK, kernel_family, sid)))

    def can_destroy(self):
        try:
            return self.destroy(sockdiag.LINUX_AF_INET, NOBODY) == ENOENT
        except OSError:
            return False        # no sock_diag at all, or netlink refused to this process

    def end(self, found, _target):
        """Reset the one socket found, by its id with the cookie in it - never by its
        numbers alone, which can find the listener on the port."""
        if found.state not in RESETS:
            return Outcome(REFUSED, found.state)
        code = self.destroy(found.kernel_family, found.sockid)
        if code in (0, ENOENT):
            return Outcome(RESET if code == 0 else GONE)    # ENOENT: closed since the read
        if code == EPERM:
            return Outcome(NEEDS_ADMIN, found.state, code)
        return Outcome(FAILED, found.state, code, detail=f"SOCK_DESTROY answered errno {code}")


def _system_class():
    """The system a reset asks here. Off Windows and Linux it is never reached:
    ``supported`` says no first."""
    return _Linux if sys.platform.startswith("linux") else _System


def _reset(target, system):
    if not resettable("TCP", target.remote_ip, system):
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
    return system.end(found[0], target)


def reset(target, system=None):
    """Reset the connection ``target`` names. On a worker; never raises - a click
    has to end in a sentence, not in a traceback on a thread nobody watches."""
    try:
        return _reset(target, system or _system_class()())
    except Exception as exc:
        crashlog.note(exc, "tcpreset")
        return Outcome(FAILED, detail=f"{type(exc).__name__}: {exc}")
