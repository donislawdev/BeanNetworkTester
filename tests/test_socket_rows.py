"""The whole socket table for the Tools tab (``portmap.socket_rows``), and the
buffer walk it shares with the capture-side port map.

The walk (``_Native._fetch``) had no test of its own before it was shared: every
test of the port map fakes ``_table`` whole. Here the fake is one level lower - an
``iphlpapi`` that writes a real table into the caller's buffer with the same ctypes
structures - so growing the buffer, refusing an error code and casting the rows run
on every platform. ``ctypes.wintypes`` imports on Linux too (its DWORD is 8 bytes
there); the fake writes with those same types, so what it writes is what the walk
reads. That the structures match Windows' own layout is what the live test at the
bottom proves where it can.
"""
import ctypes
import sys
from ctypes import wintypes
from typing import NamedTuple

import pytest

from beantester import crashlog, portmap
from beantester.portmap import _AF_INET, _AF_INET6, SocketRow
from fakes import check

TCP4, TCP6 = ("tcp", _AF_INET), ("tcp", _AF_INET6)
UDP4, UDP6 = ("udp", _AF_INET), ("udp", _AF_INET6)


def _v4(text):
    """An address as the table stores it: a DWORD over the in_addr bytes."""
    return int.from_bytes(bytes(int(part) for part in text.split(".")), "little")


def _v6(text):
    import ipaddress
    return (ctypes.c_ubyte * 16)(*ipaddress.IPv6Address(text).packed)


def _port(number):
    """Network order in the low 16 bits - and junk above, which Learn warns of."""
    return portmap._swap16(number) | 0xABCD0000


class FakeIphlpapi:
    """Writes each table into the caller's buffer the way iphlpapi does."""

    def __init__(self, tables=None, refuse=None, grow_forever=False):
        self.native = None              # set by _native(): the row types live there
        self.tables = tables or {}      # (proto, family) -> [field dicts]
        self.refuse = refuse or {}      # (proto, family) -> an error code
        self.grow_forever = grow_forever
        self.calls = []                 # ((proto, family), buffer size offered)

    def _answer(self, key, buffer, size_ref):
        size = size_ref._obj            # byref() keeps what it points at here
        self.calls.append((key, size.value))
        if key in self.refuse:
            return self.refuse[key]
        if self.grow_forever:
            size.value += 4096          # the table outgrew every buffer offered
            return portmap._ERROR_INSUFFICIENT_BUFFER
        row_type = self.native.rows[key]
        rows = [row_type(**fields) for fields in self.tables.get(key, [])]
        payload = bytes(wintypes.DWORD(len(rows))) + b"".join(bytes(r) for r in rows)
        if size.value < len(payload):
            size.value = len(payload)
            return portmap._ERROR_INSUFFICIENT_BUFFER
        ctypes.memmove(buffer, payload, len(payload))
        return 0

    def GetExtendedTcpTable(self, buffer, size_ref, _order, family, _table_class, _reserved):
        return self._answer(("tcp", family), buffer, size_ref)

    def GetExtendedUdpTable(self, buffer, size_ref, _order, family, _table_class, _reserved):
        return self._answer(("udp", family), buffer, size_ref)


def _native(api):
    native = portmap._Native(iphlpapi=api)
    api.native = native
    return native


def _machine():
    """One of everything the table can hold, and everything the port map drops."""
    return {
        TCP4: [
            # a listener whose remote half holds junk: "no meaning" per Learn
            dict(dwState=2, dwLocalAddr=_v4("0.0.0.0"), dwLocalPort=_port(445),
                 dwRemoteAddr=_v4("1.2.3.4"), dwRemotePort=_port(99), dwOwningPid=4),
            dict(dwState=5, dwLocalAddr=_v4("10.0.0.2"), dwLocalPort=_port(50000),
                 dwRemoteAddr=_v4("93.184.216.34"), dwRemotePort=_port(443),
                 dwOwningPid=1234),
            # closing: no process owns it any more (measured: PID 0)
            dict(dwState=11, dwLocalAddr=_v4("127.0.0.1"), dwLocalPort=_port(13882),
                 dwRemoteAddr=_v4("127.0.0.1"), dwRemotePort=_port(5000), dwOwningPid=0),
            # a state Learn does not list
            dict(dwState=13, dwLocalAddr=_v4("10.0.0.2"), dwLocalPort=_port(50001),
                 dwRemoteAddr=_v4("10.0.0.9"), dwRemotePort=_port(80), dwOwningPid=77),
        ],
        TCP6: [dict(ucLocalAddr=_v6("::"), dwLocalScopeId=0, dwLocalPort=_port(135),
                    ucRemoteAddr=_v6("::"), dwRemoteScopeId=0, dwRemotePort=0,
                    dwState=2, dwOwningPid=900)],
        # one port, two processes (SO_REUSEADDR, mDNS): two rows, not one
        UDP4: [dict(dwLocalAddr=_v4("0.0.0.0"), dwLocalPort=_port(5353), dwOwningPid=100),
               dict(dwLocalAddr=_v4("0.0.0.0"), dwLocalPort=_port(5353), dwOwningPid=200)],
        UDP6: [dict(ucLocalAddr=_v6("fe80::1"), dwLocalScopeId=12, dwLocalPort=_port(546),
                    dwOwningPid=300)],
    }


def test_the_socket_table_keeps_every_row_the_port_map_drops():
    """Every socket, one row each - and the capture side's map is unchanged beside it.

    The two read the same buffer walk, so both are asserted on the same machine:
    the full table keeps the TIME_WAIT row (PID 0) and both owners of 5353, while
    the port map still skips PID 0 and still keeps the last owner of a shared port.
    """
    native = _native(FakeIphlpapi(_machine()))
    rows, failed = native.socket_rows()
    check("no table failed", failed == [], f"({failed})")
    check("every row, in table order", rows == [
        SocketRow("TCP", 4, "0.0.0.0", 445, "", None, "LISTEN", 4),
        SocketRow("TCP", 4, "10.0.0.2", 50000, "93.184.216.34", 443, "ESTABLISHED", 1234),
        SocketRow("TCP", 4, "127.0.0.1", 13882, "127.0.0.1", 5000, "TIME_WAIT", 0),
        SocketRow("TCP", 4, "10.0.0.2", 50001, "10.0.0.9", 80, "13", 77),
        SocketRow("TCP", 6, "::", 135, "", None, "LISTEN", 900),
        SocketRow("UDP", 4, "0.0.0.0", 5353, "", None, "", 100),
        SocketRow("UDP", 4, "0.0.0.0", 5353, "", None, "", 200),
        # The scope is taken as it is. Learn calls it network byte order; MEASURED
        # 2026-09-23 it is not - a socket bound to fe80::...%12 has 12 in its row.
        SocketRow("UDP", 6, "fe80::1%12", 546, "", None, "", 300),
    ], f"({rows})")

    owners = {}
    flat = native.port_pid_map(owners)
    check("the port map skips the socket no process owns, as it always did",
          flat == {445: 4, 50000: 1234, 50001: 77, 135: 900, 5353: 200, 546: 300},
          f"({flat})")
    check("...and still records the owner it could not keep", owners == {5353: {100, 200}},
          f"({owners})")


def test_the_walk_grows_its_buffer_and_remembers_the_size():
    """A table larger than the first buffer answers 122 with the size it needs; the
    walk tries again with that, and the next walk starts from it."""
    many = [dict(dwLocalAddr=_v4("0.0.0.0"), dwLocalPort=_port(1024 + n), dwOwningPid=n + 1)
            for n in range(800)]       # 800 x 12 B > 8192
    api = FakeIphlpapi({UDP4: many})
    native = _native(api)
    rows, failed = native.socket_rows()
    offered = [size for key, size in api.calls if key == UDP4]
    check("the table that did not fit was asked twice: small, then big enough",
          len(offered) == 2 and offered[0] == 8192 and offered[1] > 8192, f"({offered})")
    check("and every row arrived", len([r for r in rows if r.proto == "UDP"]) == 800 and not failed,
          f"({len(rows)}, {failed})")

    api.calls.clear()
    native.port_pid_map()
    offered = [size for key, size in api.calls if key == UDP4]
    check("the next walk starts from the size that worked", len(offered) == 1, f"({offered})")


class _GrowingIphlpapi(FakeIphlpapi):
    """A udp/v4 table that gains ``per_call`` rows before every call answers - a load
    test opening sockets while the table is read."""

    def __init__(self, start, per_call):
        super().__init__({UDP4: [self._row(n) for n in range(start)]})
        self.per_call = per_call

    @staticmethod
    def _row(n):
        return dict(dwLocalAddr=_v4("0.0.0.0"), dwLocalPort=_port(1024 + n), dwOwningPid=n + 1)

    def _answer(self, key, buffer, size_ref):
        if key == UDP4:
            rows = self.tables[UDP4]
            rows.extend(self._row(len(rows) + n) for n in range(self.per_call))
        return super()._answer(key, buffer, size_ref)


def _asked(api, key):
    return [size for called, size in api.calls if called == key]


def test_a_table_that_grows_while_it_is_read_is_still_read_in_one_walk():
    """External review P2-11. The table grows between the call that reports its
    size and the call that fills it, and a buffer of exactly the reported size
    then fails again: a table that gained rows before every call was given up
    after six tries. MEASURED on loopback with ~11 000 rows a second added: every
    read walked the table TWICE, because the size remembered no longer fitted,
    and a walk that fails costs what one that succeeds does. Room on every
    attempt, the first one included."""
    api = _GrowingIphlpapi(start=800, per_call=20)      # 800 x 12 B > 8192
    native = _native(api)
    rows, failed = native.socket_rows()
    udp = [r for r in rows if r.proto == "UDP" and r.family == 4]
    check("a table that grew before every call is still read", "udp/v4" not in failed,
          f"({failed}, {_asked(api, UDP4)})")
    check("all of it, as it was when it answered", len(udp) == len(api.tables[UDP4]),
          f"({len(udp)} of {len(api.tables[UDP4])})")
    check("on the second try - the first was the default guess",
          len(_asked(api, UDP4)) == 2, f"({_asked(api, UDP4)})")

    api.calls.clear()
    native.socket_rows()
    check("the next read of a table that grew again is ONE walk",
          len(_asked(api, UDP4)) == 1, f"({_asked(api, UDP4)})")


def test_the_size_remembered_is_what_the_table_needed_not_the_buffer():
    """The buffer is bigger than the table on purpose (the room above). Remembering
    ITS size would add the room again on every read - a quarter more each time, a
    few times a second - so what is remembered is the table's own size, from its
    rows. The fake writes nothing back on success, which is all the documentation
    promises; Windows writes the table's size (measured), not the buffer's."""
    api = FakeIphlpapi(_machine())
    native = _native(api)
    for _ in range(5):
        native.port_pid_map()
    offered = _asked(api, TCP4)
    check("the first read offers the default guess", offered[0] == 8192, f"({offered})")
    check("and every later one the same buffer, not a growing one",
          len(set(offered[1:])) == 1 and offered[1] < 8192, f"({offered})")


def test_a_table_that_fails_is_recorded_every_time_and_so_is_none_answering(monkeypatch):
    """External review P2-11. A failing table was recorded ONCE per process
    (``crashlog.once``), so a later session's failure left no trace; and when none
    of the four answered, the caller dropped to psutil - ten times slower - for the
    rest of the program without a word. The crash log counts repeats."""
    recorded = []
    monkeypatch.setattr(crashlog, "record",
                        lambda exc, **kw: recorded.append((kw.get("subsystem"), str(exc))))
    native = _native(FakeIphlpapi(_machine(), refuse={TCP6: 87}))
    native.port_pid_map()
    native.port_pid_map()
    check("a table that failed twice is recorded twice",
          [subsystem for subsystem, _ in recorded] == ["portmap.native.tcp/v6"] * 2,
          f"({recorded})")

    recorded.clear()
    silent = _native(FakeIphlpapi(refuse={TCP4: 5, TCP6: 5, UDP4: 5, UDP6: 5}))
    check("none answering is a None for the caller", silent.port_pid_map() is None)
    check("and it is recorded, naming all four",
          [subsystem for subsystem, _ in recorded]
          == ["portmap.native.tcp/v4.tcp/v6.udp/v4.udp/v6"], f"({recorded})")


def test_a_table_that_keeps_outgrowing_its_buffer_is_a_failed_table():
    api = FakeIphlpapi(grow_forever=True)
    rows, failed = _native(api).socket_rows()
    check("nothing is invented", rows == [], f"({rows})")
    check("all four are named as failed", failed == ["tcp/v4", "tcp/v6", "udp/v4", "udp/v6"],
          f"({failed})")
    check("each was given six tries and no more",
          len([key for key, _size in api.calls if key == TCP4]) == 6, f"({api.calls})")


def test_an_empty_table_is_an_answer_and_an_error_code_is_not(monkeypatch):
    """0 rows is a table that answered. Any code but 0 and 122 is a table that did
    not - and when some answer, the caller gets their rows and the names of the
    others, not a fallback that throws the answers away."""
    tables = _machine()
    tables[UDP4] = []
    api = FakeIphlpapi(tables, refuse={TCP6: 87})
    monkeypatch.setattr(portmap, "_make_native", lambda: _native(api))

    def no_fallback():
        raise AssertionError("three tables answered; psutil must not be asked")

    monkeypatch.setattr(portmap, "_psutil_socket_rows", no_fallback)
    rows, failed = portmap.socket_rows()
    check("the refusing table is named", failed == ["tcp/v6"], f"({failed})")
    check("the empty one is not", "udp/v4" not in failed)
    check("the others' rows are all here",
          {(r.proto, r.family) for r in rows} == {("TCP", 4), ("UDP", 6)}, f"({rows})")


def test_when_no_native_table_answers_psutil_is_asked(monkeypatch):
    api = FakeIphlpapi(refuse={TCP4: 5, TCP6: 5, UDP4: 5, UDP6: 5})
    monkeypatch.setattr(portmap, "_make_native", lambda: _native(api))
    rows = [SocketRow("TCP", 4, "127.0.0.1", 80, "", None, "LISTEN", 1)]
    monkeypatch.setattr(portmap, "_psutil_socket_rows", lambda: rows)
    check("psutil's rows, with nothing marked missing", portmap.socket_rows() == (rows, []))

    monkeypatch.setattr(portmap, "_make_native", lambda: None)      # off Windows
    check("and off Windows it is the only way", portmap.socket_rows() == (rows, []))


# -- the psutil path ------------------------------------------------------------ #
class _Addr(NamedTuple):
    ip: str
    port: int


class _Conn(NamedTuple):
    laddr: object
    raddr: object
    status: str
    pid: object


class FakePsutil:
    class AccessDenied(Exception):
        pass

    def __init__(self, tcp=(), udp=(), deny=False):
        self.tcp, self.udp, self.deny = list(tcp), list(udp), deny

    def net_connections(self, kind):
        if self.deny:
            raise self.AccessDenied("(pid=None)")
        return self.tcp if kind == "tcp" else self.udp


def test_psutil_rows_speak_the_same_words_as_the_native_ones(monkeypatch):
    """psutil spells four states its own way; one search must find both paths' rows."""
    fake = FakePsutil(
        tcp=[_Conn(_Addr("10.0.0.2", 50000), _Addr("10.0.0.9", 443), "SYN_RECV", 10),
             _Conn(_Addr("10.0.0.2", 50001), _Addr("10.0.0.9", 443), "FIN_WAIT1", 11),
             _Conn(_Addr("10.0.0.2", 50002), _Addr("10.0.0.9", 443), "FIN_WAIT2", 12),
             _Conn(_Addr("10.0.0.2", 50003), _Addr("10.0.0.9", 443), "CLOSE", 13),
             _Conn(_Addr("::", 8080), (), "LISTEN", None),        # another account's
             _Conn(_Addr("10.0.0.2", 50004), _Addr("10.0.0.9", 443), "BOUND", 14)],
        udp=[_Conn(_Addr("0.0.0.0", 5353), (), "NONE", 20)])
    monkeypatch.setitem(sys.modules, "psutil", fake)
    rows = portmap._psutil_socket_rows()
    check("the states in the native path's words, an unknown one as psutil says it",
          [r.state for r in rows] == ["SYN_RECEIVED", "FIN_WAIT_1", "FIN_WAIT_2", "CLOSED",
                                      "LISTEN", "BOUND", ""], f"({rows})")
    listener = rows[4]
    check("a listener has no remote half, and an unknown owner stays unknown",
          listener == SocketRow("TCP", 6, "::", 8080, "", None, "LISTEN", None), f"({listener})")
    check("a UDP socket has no state", rows[-1] == SocketRow("UDP", 4, "0.0.0.0", 5353,
                                                              "", None, "", 20), f"({rows[-1]})")


def test_a_table_nobody_may_read_is_said_to_be_one(monkeypatch):
    """An empty list would read as "no sockets" - a claim about the machine."""
    monkeypatch.setitem(sys.modules, "psutil", FakePsutil(deny=True))
    with pytest.raises(portmap.SocketTableUnavailable) as denied:
        portmap._psutil_socket_rows()
    check("refused", denied.value.reason == "denied", f"({denied.value.reason})")

    monkeypatch.setitem(sys.modules, "psutil", None)                # import fails
    with pytest.raises(portmap.SocketTableUnavailable) as missing:
        portmap._psutil_socket_rows()
    check("nothing to ask", missing.value.reason == "missing", f"({missing.value.reason})")


def test_process_names_come_from_one_snapshot_and_touch_no_cache(monkeypatch):
    monkeypatch.setattr(portmap, "_process_table",
                        lambda: {4: ("System", 0, None), 1234: ("chrome.exe", 1, None)})
    table = portmap.default_table()
    before = dict(table._info)
    check("pid -> name", portmap.process_names() == {4: "System", 1234: "chrome.exe"})
    check("the targeting cache was not written", table._info == before)


# -- the real machine ------------------------------------------------------------ #
def test_the_real_socket_table_reads_as_sockets():
    """Whatever this machine holds today, every row must be a sane socket.

    It proves the one thing the fake cannot: that the structures match what
    iphlpapi really writes (on Windows) and what psutil really returns (elsewhere).
    A layout off by one field would show here as ports over 65535 or states that
    are not states.
    """
    try:
        rows, failed = portmap.socket_rows()
    except portmap.SocketTableUnavailable as exc:
        pytest.skip(f"this machine will not show its socket table ({exc.reason})")
    words = set(portmap.TCP_STATES.values())
    for row in rows:
        check("a protocol", row.proto in ("TCP", "UDP"), f"({row})")
        check("a port", 0 <= row.local_port <= 65535, f"({row})")
        check("a state that is a state",
              (row.state in words or row.state.isdigit()) if row.proto == "TCP"
              else row.state == "", f"({row})")
        if row.state == "LISTEN":
            check("a listener has no remote half", row.remote_ip == "" and
                  row.remote_port is None, f"({row})")
    if sys.platform == "win32":
        check("on Windows every table answers", failed == [], f"({failed})")
