"""``beantester/tcpreset.py``: "Reset this connection" on the Connections page - which
connection a row means, the MIB_TCPROW handed to SetTcpEntry, and what each answer
is called.

The fake sits one level below the module: an ``iphlpapi`` whose SetTcpEntry keeps the
bytes it was handed, and a socket table of ``portmap.SocketRow`` - so it all runs on
the Linux runner too. The live test at the bottom resets a loopback connection it
opened itself, on Windows with administrator rights: the measurement of 2026-10-14,
kept as a test.

Linux (``_Linux``): the fake is the kernel's side of netlink - the two lists as
``inet_diag_msg``, and the answer to SOCK_DESTROY. ``test_sockdiag.py`` holds a real
kernel's answers, which prove the layout these are built in; the real kernel resets
in ``tools/ci_linux_capture_smoke.py``, as root on the Linux runner.
"""
import ctypes
import ipaddress
import socket
import struct
import sys

import pytest

from beantester import crashlog, portmap, sockdiag, tcpreset, winenv
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


def system(rows=(OPEN,), code=0, admin=True, failed=()):
    """A fake system; ``rows`` answers as ``portmap.socket_rows`` does."""
    lib = FakeIphlpapi(code)
    return lib, tcpreset._System(iphlpapi=lib, rows=lambda: (list(rows), list(failed)),
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
    """Windows' rule, asked of Windows' system whichever runner this is on."""
    cases = {("TCP", "198.51.100.7"): True, ("TCP", "127.0.0.1"): True,
             ("UDP", "198.51.100.7"): False, ("ICMP", "198.51.100.7"): False,
             ("TCP", "2001:db8::1"): False, ("TCP", "::ffff:198.51.100.7"): False,
             ("TCP", ""): False, ("TCP", None): False, ("IP", "198.51.100.7"): False}
    for (proto, ip), wanted in cases.items():
        check(f"{proto} {ip!r}", tcpreset.resettable(proto, ip, tcpreset._System) is wanted)


def test_linux_offers_tcp_over_both_families_and_this_machine_asks_its_own(monkeypatch):
    cases = {("TCP", "198.51.100.7"): True, ("TCP", "2001:db8::1"): True,
             ("TCP", "fe80::1%2"): True, ("UDP", "2001:db8::1"): False,
             ("TCP", ""): False, ("TCP", None): False}
    for (proto, ip), wanted in cases.items():
        check(f"Linux: {proto} {ip!r}", tcpreset.resettable(proto, ip, tcpreset._Linux) is wanted)
    for platform, system in (("linux", tcpreset._Linux), ("win32", tcpreset._System)):
        monkeypatch.setattr(sys, "platform", platform)
        check(f"{platform}: its own system", tcpreset._system_class() is system)
        check(f"{platform}: and its rule for IPv6", tcpreset.resettable("TCP", "2001:db8::1")
              is (system is tcpreset._Linux))


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
    monkeypatch.setattr(tcpreset, "_system_class", lambda: tcpreset._System)    # any runner
    got = tcpreset.reset(TARGET)
    check("a binding that will not load is a FAILED too", got.kind == tcpreset.FAILED
          and "iphlpapi would not load" in got.detail, f"({got})")
    check("Windows was asked nothing", lib.rows == [])


def test_a_table_that_did_not_answer_is_said_and_not_taken_for_closed():
    """Review of #265. ``portmap.socket_rows`` names the tables that would not answer
    while others did. With the IPv4 TCP one among them a missing row says nothing,
    and "already closed" would be a guess; any other table costs nothing."""
    lib, sys_ = system(rows=(), failed=("tcp/v4",))
    check("the IPv4 TCP table failed: unreadable, not gone",
          tcpreset.reset(TARGET, sys_) == Outcome(tcpreset.UNREADABLE))
    check("and Windows was asked nothing", lib.rows == [])
    lib, sys_ = system(failed=("udp/v6", "tcp/v6"))
    check("another table failed: the reset goes ahead",
          tcpreset.reset(TARGET, sys_) == Outcome(tcpreset.RESET) and len(lib.rows) == 1)


def test_the_binding_declares_the_call_and_reads_the_real_table_by_default(monkeypatch):
    """The prototype, checked off Windows too (``test_native_prototypes`` walks the
    real DLL on Windows only), and the default table read is portmap's own."""
    class Lib:
        class SetTcpEntry:
            argtypes = restype = None
    lib = tcpreset._declared(Lib())
    check("a pointer to the 20-byte row, a DWORD back",
          lib.SetTcpEntry.argtypes == [ctypes.POINTER(tcpreset._TcpRow)]
          and lib.SetTcpEntry.restype is ctypes.c_uint32, f"({lib.SetTcpEntry.argtypes})")
    monkeypatch.setattr(portmap, "socket_rows", lambda: ([OPEN], ["tcp/v4"]))
    got = tcpreset.reset(TARGET, tcpreset._System(iphlpapi=FakeIphlpapi(),
                                                  is_admin=lambda: True))
    check("portmap's answer, failed tables included", got == Outcome(tcpreset.UNREADABLE),
          f"({got})")


# -- Linux ---------------------------------------------------------------------------- #
COOKIE = (41, 7)


def kernel_socket(state=1, local=LOCAL, local_port=51000, remote="198.51.100.7",
                  remote_port=443, family=sockdiag.LINUX_AF_INET, cookie=COOKIE):
    """One ``inet_diag_msg``: family, state, timer, retransmits, the id, then the five
    numbers nothing here reads."""
    af = socket.AF_INET if family == sockdiag.LINUX_AF_INET else socket.AF_INET6
    sid = (struct.pack("!HH", local_port, remote_port)
           + socket.inet_pton(af, local).ljust(16, b"\0")
           + socket.inet_pton(af, remote).ljust(16, b"\0") + struct.pack("=III", 0, *cookie))
    return bytes([family, state, 0, 0]) + sid + bytes(20)


class Kernel:
    """``talk`` for ``tcpreset._Linux``: the IPv4 and the IPv6 list, then ``answer`` (an
    errno) to every SOCK_DESTROY. ``refuse``: a family whose list is refused."""

    def __init__(self, v4=(), v6=(), answer=0, refuse=None):
        self.lists = {sockdiag.LINUX_AF_INET: v4, sockdiag.LINUX_AF_INET6: v6}
        self.answer = answer
        self.refuse = refuse
        self.sent = []

    def __call__(self, message):
        self.sent.append(message)
        kind, family = struct.unpack_from("=H", message, 4)[0], message[16]
        if kind == tcpreset.SOCK_DESTROY:
            return [(sockdiag.NLMSG_ERROR, struct.pack("=i", -self.answer) + message[:16])]
        if family == self.refuse:
            return [(sockdiag.NLMSG_ERROR, struct.pack("=i", -13) + message[:16])]
        return ([(sockdiag.SOCK_DIAG_BY_FAMILY, payload) for payload in self.lists[family]]
                + [(sockdiag.NLMSG_DONE, bytes(4))])

    def destroys(self):
        return [m for m in self.sent if struct.unpack_from("=H", m, 4)[0] == tcpreset.SOCK_DESTROY]


def test_linux_resets_the_one_socket_by_its_id_with_the_cookie_in_it():
    """🔴 Measured 2026-10-26: by its numbers alone the kernel takes the LISTENER on the
    port when the connection has gone - it took a server down. The cookie names the
    one socket the list showed."""
    near = (kernel_socket(local_port=51001, cookie=(1, 0)),
            kernel_socket(remote="198.51.100.8", cookie=(2, 0)),
            kernel_socket(remote_port=444, cookie=(3, 0)))
    kernel = Kernel(v4=near + (kernel_socket(),))
    got = tcpreset.reset(TARGET, tcpreset._Linux(kernel))
    check("reset", got == Outcome(tcpreset.RESET), f"({got})")
    sent = kernel.destroys()
    check("one destroy", len(sent) == 1, f"({len(sent)})")
    request = sent[0]
    check("asked to answer (an acknowledgement, or why not)",
          struct.unpack_from("=H", request, 6)[0] == sockdiag.NLM_F_REQUEST | sockdiag.NLM_F_ACK)
    check("in the list the socket is in", request[16] == sockdiag.LINUX_AF_INET)
    check("its ports and addresses",
          request[24:28] == struct.pack("!HH", 51000, 443)
          and request[28:32] == ipaddress.IPv4Address(LOCAL).packed
          and request[44:48] == ipaddress.IPv4Address("198.51.100.7").packed)
    check("and its cookie", request[-8:] == struct.pack("=II", *COOKIE), f"({request[-8:].hex()})")


def test_linux_finds_a_socket_opened_as_ipv6_for_an_ipv4_address():
    """Java's default: the socket is in the IPv6 list as ``::ffff:198.51.100.7``, its
    row says 198.51.100.7 - and the destroy goes to the list it is in."""
    mapped = kernel_socket(local="::ffff:" + LOCAL, remote="::ffff:198.51.100.7",
                           family=sockdiag.LINUX_AF_INET6)
    kernel = Kernel(v6=(mapped,))
    got = tcpreset.reset(TARGET, tcpreset._Linux(kernel))
    check("reset", got == Outcome(tcpreset.RESET), f"({got})")
    check("through the IPv6 list", [m[16] for m in kernel.destroys()] == [sockdiag.LINUX_AF_INET6])


def test_linux_resets_an_ipv6_connection():
    target = Target(51000, "2001:db8::7", 443)
    kernel = Kernel(v6=(kernel_socket(local="2001:db8::2", remote="2001:db8::7",
                                      family=sockdiag.LINUX_AF_INET6),))
    check("reset", tcpreset.reset(target, tcpreset._Linux(kernel)) == Outcome(tcpreset.RESET))


def test_linux_resets_only_where_the_other_end_gets_a_reset():
    """Linux destroys a socket in any state; the far end gets a reset only in these
    (``tcp_need_reset``) - a connection still opening was dropped and nobody told."""
    states = {1: "ESTABLISHED", 2: "SYN_SENT", 3: "SYN_RECEIVED", 4: "FIN_WAIT_1",
              5: "FIN_WAIT_2", 6: "TIME_WAIT", 8: "CLOSE_WAIT", 9: "LAST_ACK",
              11: "CLOSING", 12: "NEW_SYN_RECV"}
    resets = {"ESTABLISHED", "SYN_RECEIVED", "FIN_WAIT_1", "FIN_WAIT_2", "CLOSE_WAIT"}
    for number, name in states.items():
        kernel = Kernel(v4=(kernel_socket(state=number),))
        got = tcpreset.reset(TARGET, tcpreset._Linux(kernel))
        if name in resets:
            check(f"{name}: reset", got == Outcome(tcpreset.RESET) and kernel.destroys(), f"({got})")
        else:
            check(f"{name}: refused, nothing sent", got == Outcome(tcpreset.REFUSED, name)
                  and not kernel.destroys(), f"({got})")


def test_linux_names_each_answer_of_the_kernel():
    cases = {0: Outcome(tcpreset.RESET),
             2: Outcome(tcpreset.GONE),                         # closed since the list
             1: Outcome(tcpreset.NEEDS_ADMIN, "ESTABLISHED", 1),
             95: Outcome(tcpreset.FAILED, "ESTABLISHED", 95,
                         detail="SOCK_DESTROY answered errno 95")}
    for answer, wanted in cases.items():
        got = tcpreset.reset(TARGET, tcpreset._Linux(Kernel(v4=(kernel_socket(),), answer=answer)))
        check(f"errno {answer}", got == wanted, f"({got})")


def test_linux_guesses_nothing_and_reads_no_missing_list_as_closed():
    two = (kernel_socket(), kernel_socket(local="192.0.2.11", cookie=(9, 0)))
    kernel = Kernel(v4=two)
    check("two local addresses: ambiguous",
          tcpreset.reset(TARGET, tcpreset._Linux(kernel)) == Outcome(tcpreset.AMBIGUOUS))
    check("none in the lists: gone", tcpreset.reset(TARGET, tcpreset._Linux(Kernel()))
          == Outcome(tcpreset.GONE))
    for family in (sockdiag.LINUX_AF_INET, sockdiag.LINUX_AF_INET6):
        refused = Kernel(v4=(kernel_socket(),), refuse=family)
        check(f"list {family} refused: unreadable, not gone",
              tcpreset.reset(TARGET, tcpreset._Linux(refused)) == Outcome(tcpreset.UNREADABLE))
        check("and nothing destroyed", not refused.destroys() and not kernel.destroys())


def test_linux_has_a_reset_when_its_kernel_destroys_sockets(monkeypatch):
    """Asked with a destroy that names no socket: ENOENT where the kernel can (26.04),
    EOPNOTSUPP where it was built without (WSL) - measured, as root and not."""
    monkeypatch.setattr(sys, "platform", "linux")
    for answer, wanted in ((2, True), (95, False), (1, False)):
        kernel = Kernel(answer=answer)
        monkeypatch.setattr(sockdiag, "exchange", kernel)
        check(f"errno {answer}", tcpreset.supported() is wanted)
        check("the request names nobody: no ports, no addresses, cookie 0",
              kernel.sent == [sockdiag.request(tcpreset.SOCK_DESTROY,
                                               sockdiag.NLM_F_REQUEST | sockdiag.NLM_F_ACK,
                                               sockdiag.LINUX_AF_INET, bytes(48))])

    def no_netlink(_message):
        raise PermissionError(1, "netlink refused to this process")
    monkeypatch.setattr(sockdiag, "exchange", no_netlink)
    check("no netlink at all: no reset", tcpreset.supported() is False)
    monkeypatch.setattr(sys, "platform", "darwin")
    check("another system: none", tcpreset.supported() is False)


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
