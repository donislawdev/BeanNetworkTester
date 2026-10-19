"""``beantester/tcpestats.py``: what Windows' TCP stack measures for one connection.

The fake sits one level below the module: an ``iphlpapi`` whose four EStats calls
answer as programmed and WRITE through the pointers they are handed - the
``EnableCollection`` flag and the statistics - the way the DLL does. So every rule
measured on 2026-10-19 is a test that runs on the Linux runner too. The live test at
the bottom is that measurement's control, kept: a loopback connection this test
made counts exactly the bytes it sent.
"""
import ctypes
import socket
import sys

import pytest

from beantester import crashlog, tcpestats, winenv
from beantester.tcprow import Connection
from fakes import check

V4 = Connection("192.0.2.10", 51000, "198.51.100.7", 443)
V6 = Connection("2001:db8::20", 52188, "2001:db8::7", 443)


class FakeIphlpapi:
    """The four calls. ``answers[(call, kind)]`` is the code; ``counting[kind]`` the
    flag a read writes; ``path``/``data`` the fields it writes into the statistics."""

    def __init__(self, answers=None, counting=None, path=None, data=None):
        self.answers = answers or {}
        self.counting = {tcpestats.PATH: 1, tcpestats.DATA: 1} if counting is None else counting
        self.path = path if path is not None else {"CountRtt": 3, "SmoothedRtt": 214,
                                                   "SampleRtt": 231, "MinRtt": 18,
                                                   "MaxRtt": 402, "RttVar": 31, "CurRto": 342,
                                                   "PktsRetrans": 12, "BytesRetrans": 16488,
                                                   "Timeouts": 1, "FastRetran": 9,
                                                   "DupAcksIn": 27, "CurMss": 1460}
        self.data = data if data is not None else {"DataBytesOut": 2400, "DataBytesIn": 18100}
        self.calls = []

    def _set(self, name, ref, kind, rw, version, size, offset):
        self.calls.append((name, kind, len(bytes(ref._obj)), rw._obj.EnableCollection,
                           version, size, offset))
        return self.answers.get((name, kind), 0)

    def _get(self, name, ref, kind, rw, rwv, rws, ros, rosv, ross, rod, rodv, rods):
        self.calls.append((name, kind, len(bytes(ref._obj))))
        code = self.answers.get((name, kind), 0)
        if code == 0:
            rw._obj.EnableCollection = self.counting[kind]
            for field, value in (self.path if kind == tcpestats.PATH else self.data).items():
                setattr(rod._obj, field, value)
        return code

    def SetPerTcpConnectionEStats(self, *a):
        return self._set("Set", *a)

    def SetPerTcp6ConnectionEStats(self, *a):
        return self._set("Set6", *a)

    def GetPerTcpConnectionEStats(self, *a):
        return self._get("Get", *a)

    def GetPerTcp6ConnectionEStats(self, *a):
        return self._get("Get6", *a)


def system(lib, admin=True):
    return tcpestats._System(iphlpapi=lib, is_admin=lambda: admin)


def test_the_buffers_are_the_layouts_learn_describes():
    check("PATH_ROD: forty ULONGs", ctypes.sizeof(tcpestats._PathRod) == 160)
    check("SmoothedRtt is the 28th", tcpestats._PathRod.SmoothedRtt.offset == 27 * 4)
    check("DATA_ROD: the ULONG64s aligned as the C compiler does",
          ctypes.sizeof(tcpestats._DataRod) == 96
          and tcpestats._DataRod.ThruBytesAcked.offset == 72
          and tcpestats._DataRod.ThruBytesReceived.offset == 88)
    check("RW: one BOOLEAN", ctypes.sizeof(tcpestats._Rw) == 1)


def test_watching_turns_counting_on_for_both_kinds_and_reads_them():
    lib = FakeIphlpapi()
    got = tcpestats.watch(V4, system(lib))
    check("ok, with the numbers", got.state == tcpestats.OK and got.sample == tcpestats.Sample(
        214, 231, 18, 402, 31, 342, 16488, 1, 9, 27, 1460, 2400, 18100, 3), f"({got})")
    sets = [c for c in lib.calls if c[0] == "Set"]
    check("Set for PATH and DATA, TRUE, version 0, the RW's size, offset 0",
          sets == [("Set", tcpestats.PATH, 20, 1, 0, 1, 0), ("Set", tcpestats.DATA, 20, 1, 0, 1, 0)],
          f"({sets})")
    check("never turned off: no Set with FALSE", all(c[3] == 1 for c in sets))


def test_ipv6_goes_to_the_tcp6_calls_with_the_tcp6_row():
    lib = FakeIphlpapi()
    got = tcpestats.watch(V6, system(lib))
    check("ok", got.state == tcpestats.OK, f"({got})")
    check("Set6 and Get6 only, each with the 52-byte MIB_TCP6ROW",
          {c[0] for c in lib.calls} == {"Set6", "Get6"} and all(c[2] == 52 for c in lib.calls),
          f"({lib.calls})")


def test_a_reading_is_believed_only_while_both_kinds_count():
    """Measured: a read of a connection nobody turned counting on for answers 0, with
    the flag FALSE and random numbers in the statistics."""
    for kind in (tcpestats.PATH, tcpestats.DATA):
        counting = {tcpestats.PATH: 1, tcpestats.DATA: 1, kind: 0}
        lib = FakeIphlpapi(counting=counting, data={"DataBytesOut": 25895968444448860})
        got = tcpestats.read(V4, system(lib))
        check(f"flag FALSE on kind {kind}: not counting, and no numbers",
              got == tcpestats.Reading(tcpestats.NOT_COUNTING), f"({got})")


def test_an_ended_connection_answers_1168_or_50_and_anything_else_is_a_failure():
    for code in (1168, 50):
        lib = FakeIphlpapi(answers={("Get", tcpestats.PATH): code})
        check(f"read {code}: ended", tcpestats.read(V4, system(lib)) ==
              tcpestats.Reading(tcpestats.ENDED, code=code))
        lib = FakeIphlpapi(answers={("Set", tcpestats.PATH): code})
        check(f"turned on {code}: ended", tcpestats.watch(V4, system(lib)) ==
              tcpestats.Reading(tcpestats.ENDED, code=code))
    lib = FakeIphlpapi(answers={("Get", tcpestats.DATA): 87})
    got = tcpestats.read(V4, system(lib))
    check("87: failed, with the number", got.state == tcpestats.FAILED and got.code == 87,
          f"({got})")


def test_a_refusal_to_count_is_named_by_the_token_not_by_the_number():
    """Measured: 5 without administrator rights for an open connection AND for one
    that is not there - so the number cannot say which."""
    lib = FakeIphlpapi(answers={("Set", tcpestats.PATH): 5})
    check("5 without rights: needs administrator", tcpestats.watch(V4, system(lib, False)) ==
          tcpestats.Reading(tcpestats.NEEDS_ADMIN, code=5))
    check("5 with them: refused", tcpestats.watch(V4, system(lib, True)) ==
          tcpestats.Reading(tcpestats.REFUSED, code=5))
    check("and nothing was read after a refusal", not [c for c in lib.calls if c[0] == "Get"])


def test_round_trips_are_unknown_until_windows_measured_one():
    """Measured: right after counting is turned on CountRtt is 0, the round-trip fields
    read 0 and SampleRtt 0xFFFFFFFF - no measurement, not 0 ms."""
    lib = FakeIphlpapi(path={"CountRtt": 0, "SmoothedRtt": 0, "SampleRtt": 0xFFFFFFFF,
                             "MinRtt": 0, "MaxRtt": 0, "CurRto": 300, "CurMss": 65495})
    sample = tcpestats.read(V4, system(lib)).sample
    check("no round trip yet", (sample.smoothed_rtt, sample.sample_rtt, sample.min_rtt,
                                sample.max_rtt, sample.rtt_var) == (None,) * 5, f"({sample})")
    check("the timer and the segment size are still said", (sample.rto, sample.mss) ==
          (300, 65495))
    lib = FakeIphlpapi(path={"CountRtt": 4, "SmoothedRtt": 50, "SampleRtt": 0xFFFFFFFF})
    sample = tcpestats.read(V4, system(lib)).sample
    check("measured, but the newest field unset", sample.smoothed_rtt == 50
          and sample.sample_rtt is None, f"({sample})")


def test_what_cannot_be_asked_ends_in_a_reading_never_a_raise(monkeypatch):
    noted = []
    monkeypatch.setattr(crashlog, "note", lambda exc, area: noted.append(area))

    class Broken(FakeIphlpapi):
        def GetPerTcpConnectionEStats(self, *a):
            raise OSError("the call failed on purpose")
    got = tcpestats.read(V4, system(Broken()))
    check("FAILED with the program's words", got.state == tcpestats.FAILED
          and "failed on purpose" in got.detail, f"({got})")
    got = tcpestats.watch(Connection("not an address", 1, "198.51.100.7", 2), system(Broken()))
    check("a row that cannot be built too", got.state == tcpestats.FAILED, f"({got})")
    check("both noted for the crash log", noted == ["tcpestats", "tcpestats"], f"({noted})")


def test_the_binding_declares_the_four_calls():
    class Lib:
        pass
    lib = Lib()
    for name in ("GetPerTcpConnectionEStats", "GetPerTcp6ConnectionEStats",
                 "SetPerTcpConnectionEStats", "SetPerTcp6ConnectionEStats"):
        setattr(lib, name, type(name, (), {"argtypes": None, "restype": None}))
    tcpestats._declared(lib)
    check("Get: a row pointer, the kind, three buffers with version and size",
          len(lib.GetPerTcpConnectionEStats.argtypes) == 11
          and lib.GetPerTcp6ConnectionEStats.argtypes[0]._type_.__name__ == "Tcp6Row")
    check("Set: a row pointer, the kind, the RW, version, size, offset",
          len(lib.SetPerTcpConnectionEStats.argtypes) == 6
          and lib.SetPerTcpConnectionEStats.restype is ctypes.c_uint32)


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="EStats is Windows'")
def test_a_real_loopback_connection_counts_exactly_the_bytes_it_sent():  # pragma: no cover
    """The measurement's control, kept: counting turned on, 12 345 bytes sent, and
    Windows counted exactly those - or, without administrator rights, says so."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.create_connection(server.getsockname(), timeout=5)
    peer, _ = server.accept()
    server.close()
    try:
        connection = Connection("127.0.0.1", client.getsockname()[1], "127.0.0.1",
                                client.getpeername()[1])
        got = tcpestats.watch(connection)
        if not winenv.is_admin():
            check("no rights: said", got.state == tcpestats.NEEDS_ADMIN, f"({got})")
            return
        check("counting on", got.state == tcpestats.OK, f"({got})")
        client.sendall(b"x" * 12345)
        received = 0
        while received < 12345:
            received += len(peer.recv(65536))
        got = tcpestats.read(connection)
        check("exactly the bytes sent", got.sample.bytes_out == 12345, f"({got})")
    finally:
        client.close()
        peer.close()
