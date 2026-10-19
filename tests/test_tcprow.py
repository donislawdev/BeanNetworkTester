"""``beantester/tcprow.py``: one TCP connection the way iphlpapi names it - the
``MIB_TCPROW`` / ``MIB_TCP6ROW`` layouts from Microsoft Learn, and which socket table
row a Connections row means. Pure: no Windows call, so it all runs on Linux too.
"""
import ipaddress
import struct

from beantester import tcprow
from beantester.portmap import SocketRow
from beantester.tcprow import Connection, Target
from fakes import check

V6 = Connection("2001:db8::20", 52188, "2001:db8::7", 443)


def wanted_v6(state, local, local_scope, local_port, remote, remote_scope, remote_port):
    """MIB_TCP6ROW as Learn lays it out: state, then for each end the 16 address bytes,
    the scope id (as the socket table holds it) and the port in network byte order in
    the low two bytes of its DWORD."""
    return (struct.pack("<I", state) + ipaddress.IPv6Address(local).packed
            + struct.pack("<I", local_scope) + struct.pack(">HH", local_port, 0)
            + ipaddress.IPv6Address(remote).packed
            + struct.pack("<I", remote_scope) + struct.pack(">HH", remote_port, 0))


def test_an_ipv6_row_is_the_one_learn_describes():
    row = bytes(tcprow.row_for(V6, 5))
    check("52 bytes", len(row) == 52, f"({len(row)})")
    want = wanted_v6(5, "2001:db8::20", 0, 52188, "2001:db8::7", 0, 443)
    check("state, then each address, scope and port", row == want,
          f"({row.hex()} vs {want.hex()})")


def test_a_zone_becomes_the_scope_id_as_the_socket_table_read_it():
    row = bytes(tcprow.row_for(Connection("fe80::1%12", 50000, "fe80::2%12", 80)))
    want = wanted_v6(0, "fe80::1", 12, 50000, "fe80::2", 12, 80)
    check("scope 12 at both ends, not byte-swapped", row == want, f"({row.hex()})")


def test_an_ipv4_row_is_the_one_learn_describes():
    row = bytes(tcprow.row_for(Connection("192.0.2.10", 51000, "198.51.100.7", 443), 5))
    want = (struct.pack("<I", 5) + bytes([192, 0, 2, 10]) + struct.pack(">HH", 51000, 0)
            + bytes([198, 51, 100, 7]) + struct.pack(">HH", 443, 0))
    check("five DWORDs, network byte order", row == want, f"({row.hex()})")


def test_the_family_of_an_address_and_of_text_that_is_not_one():
    cases = {"192.0.2.1": 4, "2001:db8::1": 6, "fe80::1%12": 6, "::ffff:192.0.2.1": 6,
             "": 0, "not an address": 0, None: 0}
    for text, wanted in cases.items():
        check(f"{text!r}", tcprow.family(text) == wanted, f"({tcprow.family(text)})")


def test_a_connections_row_finds_its_socket_by_the_address_not_by_its_spelling():
    target = Target(52188, "2001:0db8:0000:0000:0000:0000:0000:0007", 443)
    mine = SocketRow("TCP", 6, "2001:db8::20", 52188, "2001:db8::7", 443, "ESTABLISHED", 1)
    near = (SocketRow("UDP", 6, "2001:db8::20", 52188, "2001:db8::7", 443, "", 1),
            SocketRow("TCP", 6, "2001:db8::20", 52188, "2001:db8::7", 444, "ESTABLISHED", 1),
            SocketRow("TCP", 6, "2001:db8::20", 52189, "2001:db8::7", 443, "ESTABLISHED", 1),
            SocketRow("TCP", 6, "2001:db8::20", 52188, "2001:db8::8", 443, "ESTABLISHED", 1),
            SocketRow("TCP", 4, "192.0.2.10", 52188, "garbage", 443, "ESTABLISHED", 1))
    check("the one row, whatever the spelling",
          tcprow.matching(near + (mine,), target) == [mine])
    linked = SocketRow("TCP", 6, "fe80::1%12", 50000, "fe80::2%12", 80, "ESTABLISHED", 1)
    check("a zone in the table does not hide the connection",
          tcprow.matching([linked], Target(50000, "fe80::2", 80)) == [linked])
    v4 = SocketRow("TCP", 4, "192.0.2.10", 51000, "192.0.2.1", 443, "ESTABLISHED", 1)
    check("an IPv4-mapped address is not the IPv4 one",
          tcprow.matching([v4], Target(51000, "::ffff:192.0.2.1", 443)) == [])
