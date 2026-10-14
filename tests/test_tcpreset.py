"""``beantester/tcpreset.py``: "Reset this connection" on the Connections page - which
connection a row means, the MIB_TCPROW handed to SetTcpEntry, and what each answer
is called.

The fake sits one level below the module: an ``iphlpapi`` whose SetTcpEntry keeps the
bytes it was handed, and a socket table of ``portmap.SocketRow`` - so it all runs on
the Linux runner too. The live test at the bottom resets a loopback connection it
opened itself, on Windows with administrator rights: the measurement of 2026-10-14,
kept as a test.
"""
import ctypes
import ipaddress
import socket
import struct
import sys

import pytest

from beantester import crashlog, portmap, tcpreset, winenv
from beantester.portmap import SocketRow
from beantester.tcpreset import Outcome, Target
from fakes import check

TARGET = Target(51000, "198.51.100.7", 443)
LOCAL = "192.0.2.10"
OPEN = SocketRow("TCP", 4, LOCAL, 51000, "198.51.100.7", 443, "ESTABLISHED", 1234)


class FakeIphlpapi:
    """SetTcpEntry as Windows answers it, keeping every row it was handed, as bytes."""

    def __init__(self, code=0):
        self.code = code
        self.rows = []

    def SetTcpEntry(self, ref):
        self.rows.append(bytes(ref._obj))
        return self.code


def system(rows=(OPEN,), code=0, admin=True):
    lib = FakeIphlpapi(code)
    return lib, tcpreset._System(iphlpapi=lib, rows=lambda: list(rows),
                                 is_admin=lambda: admin)


def wanted_row(local_ip, target):
    """MIB_TCPROW as Learn lays it out: state, then each address and port in network
    byte order, a port in the low two bytes of its DWORD."""
    return (struct.pack("<I", 12) + ipaddress.IPv4Address(local_ip).packed
            + struct.pack(">HH", target.local_port, 0)
            + ipaddress.IPv4Address(target.remote_ip).packed
            + struct.pack(">HH", target.remote_port, 0))


def test_the_row_is_the_one_learn_describes():
    row = bytes(tcpreset.row_for(LOCAL, TARGET))
    check("20 bytes: five DWORDs", len(row) == 20, f"({len(row)})")
    check("DELETE_TCB, then addresses and ports in network byte order",
          row == wanted_row(LOCAL, TARGET), f"({row.hex()} vs {wanted_row(LOCAL, TARGET).hex()})")


def test_only_tcp_over_ipv4_is_offered():
    cases = {("TCP", "198.51.100.7"): True, ("TCP", "127.0.0.1"): True,
             ("UDP", "198.51.100.7"): False, ("ICMP", "198.51.100.7"): False,
             ("TCP", "2001:db8::1"): False, ("TCP", "::ffff:198.51.100.7"): False,
             ("TCP", ""): False, ("TCP", None): False, ("IP", "198.51.100.7"): False}
    for (proto, ip), wanted in cases.items():
        check(f"{proto} {ip!r}", tcpreset.resettable(proto, ip) is wanted)


def test_the_one_matching_connection_is_reset_with_its_local_address():
    """The row names the local PORT; the table gives the local ADDRESS. Rows that
    differ in one part each are around it, and none of them is touched."""
    near = (SocketRow("TCP", 4, LOCAL, 51001, "198.51.100.7", 443, "ESTABLISHED", 1),
            SocketRow("TCP", 4, LOCAL, 51000, "198.51.100.8", 443, "ESTABLISHED", 1),
            SocketRow("TCP", 4, LOCAL, 51000, "198.51.100.7", 444, "ESTABLISHED", 1),
            SocketRow("UDP", 4, LOCAL, 51000, "198.51.100.7", 443, "", 1),
            SocketRow("TCP", 6, "2001:db8::2", 51000, "2001:db8::7", 443, "ESTABLISHED", 1))
    lib, sys_ = system(rows=near + (OPEN,))
    got = tcpreset.reset(TARGET, sys_)
    check("reset", got == Outcome(tcpreset.RESET), f"({got})")
    check("one call, the row Learn describes, with the table's local address",
          lib.rows == [wanted_row(LOCAL, TARGET)], f"({[r.hex() for r in lib.rows]})")


def test_none_is_gone_two_are_ambiguous_and_neither_calls_windows():
    lib, sys_ = system(rows=())
    check("closed since the row was drawn", tcpreset.reset(TARGET, sys_) ==
          Outcome(tcpreset.GONE))
    two = (OPEN, OPEN._replace(local_ip="192.0.2.11"))
    lib2, sys2 = system(rows=two)
    check("the same port on two local addresses: nothing is guessed",
          tcpreset.reset(TARGET, sys2) == Outcome(tcpreset.AMBIGUOUS))
    check("and Windows was asked nothing", lib.rows == [] and lib2.rows == [])


def test_a_refusal_is_named_by_the_token_not_by_the_number():
    """317 came back for TIME_WAIT, SYN_SENT and a gone connection ELEVATED, and for
    an open one without the rights (measured 2026-10-14)."""
    closing = OPEN._replace(state="TIME_WAIT")
    cases = {(317, True): Outcome(tcpreset.REFUSED, "TIME_WAIT", 317),
             (317, False): Outcome(tcpreset.NEEDS_ADMIN, "TIME_WAIT", 317),
             (5, True): Outcome(tcpreset.REFUSED, "TIME_WAIT", 5),
             (5, False): Outcome(tcpreset.NEEDS_ADMIN, "TIME_WAIT", 5)}
    for (code, admin), wanted in cases.items():
        _lib, sys_ = system(rows=(closing,), code=code, admin=admin)
        got = tcpreset.reset(TARGET, sys_)
        check(f"code {code}, admin {admin}", got == wanted, f"({got})")


def test_what_cannot_be_asked_ends_in_an_outcome_never_a_raise(monkeypatch):
    noted = []
    monkeypatch.setattr(crashlog, "note", lambda exc, area: noted.append(area))

    def unread():
        raise AssertionError("the table must not be read for an IPv6 row")
    lib = FakeIphlpapi()
    ipv6 = tcpreset._System(iphlpapi=lib, rows=unread, is_admin=lambda: True)
    check("IPv6: refused before anything is read", tcpreset.reset(
        Target(51000, "2001:db8::7", 443), ipv6) == Outcome(tcpreset.NOT_IPV4))

    def unavailable():
        raise portmap.SocketTableUnavailable("denied")
    table = tcpreset._System(iphlpapi=lib, rows=unavailable, is_admin=lambda: True)
    check("no socket table", tcpreset.reset(TARGET, table) == Outcome(tcpreset.UNREADABLE))

    def broken():
        raise RuntimeError("a fault in the table read")
    got = tcpreset.reset(TARGET, tcpreset._System(iphlpapi=lib, rows=broken,
                                                  is_admin=lambda: True))
    check("anything else: FAILED with the program's words", got == Outcome(
        tcpreset.FAILED, detail="RuntimeError: a fault in the table read"), f"({got})")
    check("and noted for the crash log", noted == ["tcpreset"], f"({noted})")

    def no_library():
        raise OSError("iphlpapi would not load")
    monkeypatch.setattr(tcpreset, "_iphlpapi", no_library)
    got = tcpreset.reset(TARGET)
    check("a binding that will not load is a FAILED too", got.kind == tcpreset.FAILED
          and "iphlpapi would not load" in got.detail, f"({got})")
    check("Windows was asked nothing", lib.rows == [])


def test_the_binding_declares_the_call_and_reads_the_whole_table(monkeypatch):
    """The prototype, checked off Windows too (``test_native_prototypes`` walks the
    real DLL on Windows only), and the table read: a table that would not answer
    alongside the others costs nothing - the rows are still the rows."""
    class Lib:
        class SetTcpEntry:
            argtypes = restype = None
    lib = tcpreset._declared(Lib())
    check("a pointer to the 20-byte row, a DWORD back",
          lib.SetTcpEntry.argtypes == [ctypes.POINTER(tcpreset._TcpRow)]
          and lib.SetTcpEntry.restype is ctypes.c_uint32, f"({lib.SetTcpEntry.argtypes})")
    monkeypatch.setattr(portmap, "socket_rows", lambda: ([OPEN], ["udp6"]))
    check("the rows, whatever else failed", tcpreset._socket_rows() == [OPEN])


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="SetTcpEntry is Windows'")
def test_a_real_loopback_connection_is_reset_at_both_ends():  # pragma: no cover - Windows
    """The measurement, kept: an open connection this test made, reset through the
    real table and the real call - both ends then get WSAECONNRESET."""
    if not winenv.is_admin():
        pytest.skip("SetTcpEntry needs administrator rights (Learn); this shell has none")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.create_connection(server.getsockname(), timeout=5)
    peer, _ = server.accept()
    server.close()
    try:
        client.sendall(b"hello")
        peer.recv(16)
        target = Target(client.getsockname()[1], "127.0.0.1", client.getpeername()[1])
        got = tcpreset.reset(target)
        check("reset", got == Outcome(tcpreset.RESET), f"({got})")
        for end in (client, peer):                  # the owner, then the far end
            end.settimeout(2)
            with pytest.raises(ConnectionResetError):
                end.recv(16)
        check("and it is gone from the table", tcpreset.reset(target) ==
              Outcome(tcpreset.GONE))
    finally:
        client.close()
        peer.close()
