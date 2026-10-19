"""One TCP connection of this machine, the way iphlpapi names it.

Two tools take a connection by the same four numbers: "Reset this connection" on the
Connections page (``tcpreset``, ``SetTcpEntry``) and "TCP health" on the Tools tab
(``tcpestats``, the EStats calls). This is what they share - the row layouts, and
finding the connection a Connections row means in the socket table - and nothing here
calls Windows. That is why it is a module of its own: the Tools tab may import it,
while ``tcpreset`` it may not (``SetTcpEntry`` makes Windows SEND a reset,
``tests/test_no_telemetry.py``).

Layouts, Microsoft Learn: ``MIB_TCPROW`` - five DWORDs, addresses and ports in network
byte order; ``MIB_TCP6ROW`` - the state, an ``IN6_ADDR``, a scope id and a port for
each end, ports in network byte order. Learn says the scope ids are in network byte
order as well; ``portmap._ipv6`` MEASURED that they are not (2026-09-23), and the scope
written here is the one ``portmap`` read, taken as it is. The EStats calls do not look
at the state - measured 2026-10-19: 0, 1 and 12 found the same connection.
"""
import ctypes
import ipaddress
import struct
from typing import NamedTuple


class Target(NamedTuple):
    """The connection as a Connections row names it: no local address."""
    local_port: int
    remote_ip: str
    remote_port: int


class Connection(NamedTuple):
    """One connection by all four numbers - what a MIB row needs. An IPv6 address
    may carry its zone (``fe80::1%12``), the way ``portmap`` writes it."""
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int


class TcpRow(ctypes.Structure):
    """``MIB_TCPROW`` (Learn)."""
    _fields_ = [("dwState", ctypes.c_uint32), ("dwLocalAddr", ctypes.c_uint32),
                ("dwLocalPort", ctypes.c_uint32), ("dwRemoteAddr", ctypes.c_uint32),
                ("dwRemotePort", ctypes.c_uint32)]


class Tcp6Row(ctypes.Structure):
    """``MIB_TCP6ROW`` (Learn)."""
    _fields_ = [("State", ctypes.c_uint32), ("LocalAddr", ctypes.c_ubyte * 16),
                ("dwLocalScopeId", ctypes.c_uint32), ("dwLocalPort", ctypes.c_uint32),
                ("RemoteAddr", ctypes.c_ubyte * 16), ("dwRemoteScopeId", ctypes.c_uint32),
                ("dwRemotePort", ctypes.c_uint32)]


def _dword(raw):
    """Four bytes, as they must lie in memory, as the DWORD ctypes stores. Windows
    is little-endian on every processor it runs on."""
    return struct.unpack("<I", raw)[0]


def _port(port):
    """A port in network byte order, in the low half of its DWORD."""
    return _dword(struct.pack(">HH", port, 0))


def _scope(address):
    return int(address.scope_id) if address.scope_id else 0


def family(ip):
    """4 or 6 for an address, 0 for text that is not one."""
    try:
        return ipaddress.ip_address(str(ip)).version
    except ValueError:
        return 0


def row_for(connection, state=0):
    """The MIB row naming ``connection``: ``TcpRow`` for IPv4, ``Tcp6Row`` for IPv6."""
    local = ipaddress.ip_address(connection.local_ip)
    remote = ipaddress.ip_address(connection.remote_ip)
    if local.version == 4:
        return TcpRow(state, _dword(local.packed), _port(connection.local_port),
                      _dword(remote.packed), _port(connection.remote_port))
    row = Tcp6Row()
    row.State = state
    row.LocalAddr[:] = list(local.packed)
    row.RemoteAddr[:] = list(remote.packed)
    row.dwLocalScopeId, row.dwRemoteScopeId = _scope(local), _scope(remote)
    row.dwLocalPort, row.dwRemotePort = _port(connection.local_port), _port(connection.remote_port)
    return row


def _bare(ip):
    return ipaddress.ip_address(str(ip).split("%")[0])


def _same(a, b):
    """Two spellings of one address: IPv6 has many, and the socket table writes its
    own - with the zone, which a Connections row does not carry (two links with the
    same far address and ports is then two matches, and nothing is guessed). A
    different family is a different address: ``::ffff:192.0.2.1`` is not
    ``192.0.2.1`` to Windows' tables."""
    try:
        return _bare(a) == _bare(b)
    except ValueError:
        return False


def matching(rows, target):
    """The socket table's TCP rows for ``target`` (``portmap.SocketRow``s)."""
    return [row for row in rows
            if row.proto == "TCP" and row.local_port == target.local_port
            and _same(row.remote_ip, target.remote_ip) and row.remote_port == target.remote_port]
