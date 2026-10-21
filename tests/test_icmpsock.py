"""``beantester/icmpsock.py``: one ICMP echo on Linux, and reading what the kernel said.

The ancillary data and the requests below are copied from the run on a VM with
Ubuntu 26.04 (2026-10-21, ``internal_tools`` probes ``2026-10-21-linux-ping``: a
client, a router and a far end in three network namespaces), so a reader that takes
another layout - the extended error's sender, the IPv6 address at another offset -
reads the wrong bytes on every runner. The socket is a fake that answers as
scripted; the live test at the bottom pings this machine's loopback on Linux.

🔴 The fake refuses an error-queue read while the socket still has a timeout: the
first version read it that way and an error that came after 5 ms was answered after
the whole wait (measured on the VM, 2000 ms; 8100 ms for a 5000 ms wait) - Python
waits for a socket with a timeout to be readable before the call, ``MSG_DONTWAIT``
or not.
"""
import ipaddress
import struct
import sys

import pytest

from beantester import icmpsock
from fakes import check

PAYLOAD = b"abcdefghijklmnopqrstuvwabcdefghi"
V4 = ipaddress.ip_address("10.78.0.2")
V6 = ipaddress.ip_address("fd00:78::2")
SENT_WALL = 1_800_000_000_000_000_000      # the fake clock's wall time at the send

# The error queue's ancillary data, as the kernel wrote it (VM, 2026-10-21):
# sock_extended_err (errno, origin, type, code, pad, info, data) and the sender.
TTL_EXPIRED = bytes.fromhex("71000000020b00000000000000000000020000000a4d00010000000000000000")
NET_UNREACHABLE = bytes.fromhex("65000000020300000000000000000000020000000a4d00010000000000000000")
HOST_UNREACHABLE = bytes.fromhex("71000000020301000000000000000000020000000a4d00020000000000000000")
FRAG_NEEDED = bytes.fromhex("5a000000020304000005000000000000020000000a4d00010000000000000000")
V6_TIME_EXCEEDED = bytes.fromhex("710000000303000000000000000000000a00000000000000"
                                 "fd000077000000000000000000000001" "00000000")
V6_NO_ROUTE = bytes.fromhex("650000000301000000000000000000000a00000000000000"
                            "fd000077000000000000000000000001" "00000000")
V6_ADDRESS_UNREACHABLE = bytes.fromhex("710000000301030000000000000000000a00000000000000"
                                       "fd000077000000000000000000000002" "00000000")
V6_TOO_BIG = bytes.fromhex("5a0000000302000000050000000000000a00000000000000"
                           "fd000077000000000000000000000001" "00000000")
STAMP = bytes.fromhex("62a3d86a000000007799751f00000000")       # a timespec, 64-bit
TTL_63 = struct.pack("=i", 63)
# The request a raw socket sent, as the error queue handed it back: the kernel took it,
# so its checksum (e26f) is the one the wire wanted.
RAW_REQUEST_HEAD = bytes.fromhex("0800e26f5a5a1092")
# An IPv4 header the VM's raw socket received (in a router's "TTL expired").
IP_HEADER = bytes.fromhex("4500003c41ca4000010123590a4d00020a4e0002")


def head(kind, ident, seq=icmpsock.SEQ, code=0):
    return struct.pack("!BBHHH", kind, code, 0, ident, seq)


def timespec(ns):
    return struct.pack("=qq", ns // 1_000_000_000, ns % 1_000_000_000)


def stamp_at(ms):
    """The kernel's receive time ``ms`` after the send, as ancillary data."""
    return (icmpsock.SOL_SOCKET, icmpsock.SO_TIMESTAMPNS, timespec(SENT_WALL + int(ms * 1e6)))


class Clock:
    """Wall and monotonic time that move only when told (``step`` per monotonic read)."""

    def __init__(self, step_ns=1_000):
        self.mono = 0
        self.step = step_ns

    def time_ns(self):
        return SENT_WALL

    def monotonic_ns(self):
        self.mono += self.step
        return self.mono


class FakeSocket:
    """Answers ``recvmsg`` from a script: ("data", raw, ancillary, source),
    ("error", errno, [error-queue entries]) or ("timeout",)."""

    def __init__(self, script=(), name=("0.0.0.0", 21214), send_error=None):
        self.script = list(script)
        self.queue = []
        self.name = name
        self.send_error = send_error
        self.options, self.timeouts, self.sent = [], [], []
        self.closed = False

    def setsockopt(self, level, option, value):
        self.options.append((level, option, value))

    def settimeout(self, value):
        self.timeouts.append(value)

    def sendto(self, data, address):
        if self.send_error:
            raise OSError(self.send_error, "refused")
        self.sent.append((data, address))
        return len(data)

    def getsockname(self):
        return self.name

    def recvmsg(self, size, ancillary=0, flags=0):
        if flags & icmpsock.MSG_ERRQUEUE:
            assert self.timeouts and self.timeouts[-1] == 0, \
                f"the error queue read with a timeout ({self.timeouts}) waits for the socket"
            if not self.queue:
                raise BlockingIOError(11, "Resource temporarily unavailable")
            raw, anc = self.queue.pop(0)
            return raw, anc, flags, None
        step = self.script.pop(0) if self.script else ("timeout",)
        if step[0] == "timeout":
            raise TimeoutError("timed out")
        if step[0] == "error":
            self.queue.extend(step[2])
            raise OSError(step[1], "queued")
        return step[1], step[2], 0, step[3]

    def close(self):
        self.closed = True


def opener_of(*sockets, refuse=()):
    """An opener handing out ``sockets`` in turn; the kinds in ``refuse`` are refused."""
    handed, asked = list(sockets), []

    def opener(family, kind):
        asked.append((family, kind))
        if kind in refuse:
            raise PermissionError(13, "Permission denied")
        return handed.pop(0)
    opener.asked = asked
    return opener


def run(sock, address=V4, kinds=(icmpsock.DGRAM,), wait_ms=2000, sent=PAYLOAD, **kw):
    kw.setdefault("clock", Clock())
    kw.setdefault("stamped", True)
    return icmpsock.echo(address, wait_ms, sent, opener=opener_of(sock), kinds=kinds, **kw)


# -- what the kernel wrote ----------------------------------------------------------- #
def test_measured_error_queue_entries_read_as_the_kernel_said():
    cases = {
        TTL_EXPIRED: (4, (11, 0), "10.77.0.1"),
        NET_UNREACHABLE: (4, (3, 0), "10.77.0.1"),
        HOST_UNREACHABLE: (4, (3, 1), "10.77.0.2"),     # from this machine's own address
        FRAG_NEEDED: (4, (3, 4), "10.77.0.1"),
        V6_TIME_EXCEEDED: (6, (3, 0), "fd00:77::1"),
        V6_NO_ROUTE: (6, (1, 0), "fd00:77::1"),
        V6_ADDRESS_UNREACHABLE: (6, (1, 3), "fd00:77::2"),
        V6_TOO_BIG: (6, (2, 0), "fd00:77::1"),
    }
    for blob, (version, icmp, sender) in cases.items():
        level, kind = ((icmpsock.SOL_IP, icmpsock.IP_RECVERR) if version == 4
                       else (icmpsock.SOL_IPV6, icmpsock.IPV6_RECVERR))
        got = icmpsock.queued_error([(level, kind, blob)])
        check(f"{icmp} from {sender}", got == icmpsock.Answer(source=sender, icmp=icmp),
              f"({got})")
    local = bytearray(TTL_EXPIRED)
    local[4] = 1                                        # origin LOCAL: the kernel's errno
    check("an error this machine raised is its errno",
          icmpsock.queued_error([(0, icmpsock.IP_RECVERR, bytes(local))])
          == icmpsock.Answer(113, source="10.77.0.1"))
    check("no extended error: nothing",
          icmpsock.queued_error([(icmpsock.SOL_IP, icmpsock.IP_TTL, TTL_63)]) is None)


def test_a_reply_carries_its_ttl_and_the_kernels_receive_time():
    ttl, stamp = icmpsock.received([(icmpsock.SOL_SOCKET, icmpsock.SO_TIMESTAMPNS, STAMP),
                                    (icmpsock.SOL_IP, icmpsock.IP_TTL, TTL_63)])
    check("TTL 63", ttl == 63, f"({ttl})")
    check("the measured timespec", stamp == 0x6AD8A362 * 1_000_000_000 + 0x1F759977, f"({stamp})")
    _, stamp32 = icmpsock.received([(icmpsock.SOL_SOCKET, icmpsock.SO_TIMESTAMPNS,
                                     struct.pack("=ii", 5, 7))])
    check("a 32-bit machine's timespec", stamp32 == 5_000_000_007, f"({stamp32})")
    check("nothing asked for, nothing read", icmpsock.received([]) == (None, None))


def test_the_checksum_of_the_request_the_kernel_took():
    measured = struct.pack("!BBHHH", 8, 0, 0, 0x5A5A, 4242) + PAYLOAD
    check("RFC 1071 over the request gives what the wire carried",
          icmpsock.checksum(measured) == 0xE26F, f"({icmpsock.checksum(measured):#x})")
    request = icmpsock.request(4, icmpsock.RAW, 0x5A5A, PAYLOAD)
    check("a raw request checks out to zero", icmpsock.checksum(request) == 0)
    check("an odd length is padded", icmpsock.checksum(b"\x01") == 0xFEFF)
    for version, kind in ((4, icmpsock.DGRAM), (6, icmpsock.RAW), (6, icmpsock.DGRAM)):
        check(f"IPv{version} {kind}: the kernel fills the checksum in",
              icmpsock.request(version, kind, 7, PAYLOAD)[2:4] == b"\0\0")


def test_a_raw_ipv4_reply_is_read_after_its_ip_header():
    reply = IP_HEADER + head(0, 0x5A5A) + PAYLOAD
    check("type, identifier, number and data", icmpsock.parse_reply(reply, 4, icmpsock.RAW)
          == (0, 0x5A5A, icmpsock.SEQ, PAYLOAD))
    check("a ping socket's has no header",
          icmpsock.parse_reply(head(0, 9) + PAYLOAD, 4, icmpsock.DGRAM) == (0, 9, 1, PAYLOAD))
    check("IPv6 raw has none either",
          icmpsock.parse_reply(head(129, 9) + PAYLOAD, 6, icmpsock.RAW) == (129, 9, 1, PAYLOAD))
    check("too short to be ICMP", icmpsock.parse_reply(IP_HEADER + b"\0" * 7, 4, icmpsock.RAW)
          is None and icmpsock.parse_reply(b"", 4, icmpsock.RAW) is None)


# -- one request, end to end on a fake socket ---------------------------------------- #
def test_a_ping_socket_reply_is_taken_with_its_ttl_and_the_kernels_time():
    sock = FakeSocket([("data", head(0, 21214) + PAYLOAD,
                        [stamp_at(1.5), (icmpsock.SOL_IP, icmpsock.IP_TTL, TTL_63)],
                        ("10.78.0.2", 0))])
    answer = run(sock)
    check("the reply", answer == icmpsock.Answer(replied=True, rtt_ns=1_500_000, ttl=63,
                                                 source="10.78.0.2", data=PAYLOAD), f"({answer})")
    [(request, address)] = sock.sent
    check("an echo request, the identifier left to the kernel",
          request == head(8, 0) + PAYLOAD and address == ("10.78.0.2", 0), f"({request!r})")
    check("the error queue, the TTL and the receive time asked for", {
        (icmpsock.SOL_IP, icmpsock.IP_RECVERR, 1), (icmpsock.SOL_IP, icmpsock.IP_RECVTTL, 1),
        (icmpsock.SOL_SOCKET, icmpsock.SO_TIMESTAMPNS, 1)} == set(sock.options), f"({sock.options})")
    check("the socket closed", sock.closed)


def test_what_is_not_this_requests_reply_is_passed_over():
    """A raw socket sees every ICMP message: this request going out on loopback,
    another program's replies - and a late one of an earlier request."""
    sock = FakeSocket([
        ("data", IP_HEADER + head(8, 0x5A5A) + PAYLOAD, [], ("127.0.0.1", 0)),
        ("data", IP_HEADER + head(0, 0x1234) + PAYLOAD, [], ("127.0.0.1", 0)),
        ("data", IP_HEADER + head(0, 0x5A5A, seq=2) + PAYLOAD, [], ("127.0.0.1", 0)),
        ("data", IP_HEADER[:5], [], ("127.0.0.1", 0)),
        ("data", IP_HEADER + head(0, 0x5A5A) + PAYLOAD, [stamp_at(0.2)], ("127.0.0.1", 0))])
    answer = run(sock, ipaddress.ip_address("127.0.0.1"), kinds=(icmpsock.RAW,), ident=0x5A5A)
    check("the fifth datagram is the reply", answer.replied and answer.rtt_ns == 200_000
          and not sock.script, f"({answer}, {len(sock.script)} left)")
    check("the raw request carries its identifier and checksum",
          icmpsock.checksum(sock.sent[0][0]) == 0 and sock.sent[0][0][4:6] == b"\x5a\x5a")


def test_an_icmp_error_is_read_from_the_error_queue_at_once():
    ours = head(8, 21214) + PAYLOAD
    sock = FakeSocket([("error", 113, [(ours, [(icmpsock.SOL_IP, icmpsock.IP_RECVERR,
                                                TTL_EXPIRED)])])])
    answer = run(sock)
    check("TTL expired, from the router", answer == icmpsock.Answer(
        source="10.77.0.1", icmp=(11, 0)), f"({answer})")
    check("the queue was read without waiting", sock.timeouts[-1] == 0, f"({sock.timeouts})")


def test_another_programs_error_is_passed_over_and_an_empty_queue_is_the_error():
    other = head(8, 999) + PAYLOAD
    sock = FakeSocket([("error", 101, [(other, [(icmpsock.SOL_IP, icmpsock.IP_RECVERR,
                                                 NET_UNREACHABLE)])]), ("timeout",)])
    answer = run(sock, kinds=(icmpsock.RAW,), ident=0x5A5A)
    check("someone else's: the wait goes on, then no answer", answer == icmpsock.Answer(),
          f"({answer})")
    check("and the wait took up its timeout again", sock.timeouts[-1] not in (0, None),
          f"({sock.timeouts})")
    check("an error with nothing queued is the error itself",
          run(FakeSocket([("error", 13, [])])) == icmpsock.Answer(13))


def test_a_refused_send_and_no_answer_in_time():
    check("no route here: sendto's errno", run(FakeSocket(send_error=101))
          == icmpsock.Answer(101))
    check("nothing within the wait", run(FakeSocket([("timeout",)])) == icmpsock.Answer())
    late = FakeSocket([("data", head(0, 21214) + PAYLOAD, [], ("10.78.0.2", 0))])
    check("the wait already over: no answer, nothing read",
          run(late, clock=Clock(step_ns=3_000_000_000)) == icmpsock.Answer() and late.script)


def test_the_ping_socket_first_and_the_raw_one_when_it_is_refused():
    raw = FakeSocket([("data", IP_HEADER + head(0, 0x5A5A) + PAYLOAD, [], ("10.78.0.2", 0))])
    opener = opener_of(raw, refuse={icmpsock.DGRAM})
    answer = icmpsock.echo(V4, 2000, PAYLOAD, opener=opener, ident=0x5A5A, clock=Clock(),
                           stamped=False)
    check("refused, then raw", [k for _f, k in opener.asked] == [icmpsock.DGRAM, icmpsock.RAW]
          and answer.replied, f"({opener.asked}, {answer})")
    both = opener_of(refuse=set(icmpsock.KINDS))
    check("both refused: the first refusal", icmpsock.echo(V4, 2000, PAYLOAD, opener=both)
          == icmpsock.Answer(13))
    check("kind() asks in the same order",
          icmpsock.kind(opener_of(FakeSocket(), refuse={icmpsock.DGRAM})) == icmpsock.RAW
          and icmpsock.kind(opener_of(FakeSocket())) == icmpsock.DGRAM
          and icmpsock.kind(opener_of(refuse=set(icmpsock.KINDS))) is None)
    asked = FakeSocket()
    icmpsock.kind(opener_of(asked))
    check("and closes what it opened", asked.closed)


def test_the_kernels_time_is_believed_only_inside_the_wait():
    reply = head(0, 21214) + PAYLOAD
    before = FakeSocket([("data", reply, [stamp_at(-5)], ("10.78.0.2", 0))])
    answer = run(before, clock=Clock(step_ns=1_000_000))
    check("a receive time before the send: the time read here", answer.rtt_ns == 2_000_000,
          f"({answer.rtt_ns})")
    unstamped = FakeSocket([("data", reply, [stamp_at(1)], ("10.78.0.2", 0))])
    answer = run(unstamped, clock=Clock(step_ns=1_000_000), stamped=False)
    check("a machine that numbers its options otherwise: not asked, not read",
          answer.rtt_ns == 2_000_000 and not any(o[1] == icmpsock.SO_TIMESTAMPNS
                                                 for o in unstamped.options), f"({answer})")


def test_the_socket_is_closed_whatever_happens():
    class Broken(FakeSocket):
        def recvmsg(self, *args):
            raise ValueError("a bug")
    sock = Broken()
    with pytest.raises(ValueError):
        run(sock)
    check("closed after a fault too", sock.closed)
    refused = FakeSocket(send_error=1)
    run(refused)
    check("and after a refused send", refused.closed)


def test_an_ipv6_reply_has_no_ttl_and_a_zone_goes_as_its_interface_number(monkeypatch):
    sock = FakeSocket([("data", head(129, 21214) + PAYLOAD,
                        [(icmpsock.SOL_IP, icmpsock.IP_TTL, TTL_63)],
                        ("fd00:78::2", 0, 0, 0))], name=("::", 21214, 0, 0))
    answer = run(sock, V6)
    check("IPv6: a reply, no TTL", answer.replied and answer.ttl is None, f"({answer})")
    check("only the error queue asked for", sock.options[:1]
          == [(icmpsock.SOL_IPV6, icmpsock.IPV6_RECVERR, 1)], f"({sock.options})")
    check("an interface nobody has", icmpsock.zone_index("nope0") is None)
    zoned = FakeSocket([("data", head(129, 21214) + PAYLOAD, [], ("fe80::1%eth0", 0, 0, 3))],
                       name=("::", 21214, 0, 0))
    monkeypatch.setattr(icmpsock.socket, "if_nametoindex", lambda name: {"eth0": 3}[name])
    answer = run(zoned, ipaddress.ip_address("fe80::1%eth0"))
    check("a named zone goes as its number", zoned.sent[0][1] == ("fe80::1", 0, 0, 3),
          f"({zoned.sent})")
    check("and the answer's address is said without it", answer.source == "fe80::1",
          f"({answer.source})")
    check("a numbered zone as it is",
          icmpsock._target(ipaddress.ip_address("fe80::1%12")) == ("fe80::1", 0, 0, 12))
    check("an errno's name", icmpsock.errno_name(1) == "EPERM" and icmpsock.errno_name(99999)
          == "99999")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only: its sockets")
def test_a_live_ping_of_this_machine_reads_a_real_reply():  # pragma: no cover - Linux only
    """The control, on a Linux runner that lets this process ping (the ping socket for
    its group, or root): this machine's own loopback addresses answer with what was
    sent. The kernel's whole answer path is in CI's Linux capture check."""
    if icmpsock.kind() is None:
        pytest.skip("this process may not open an ICMP socket here")
    for address, ttl in (("127.0.0.1", 64), ("::1", None)):
        answer = icmpsock.echo(ipaddress.ip_address(address), 1000, PAYLOAD)
        check(f"{address}: a reply with the data sent", answer.replied
              and answer.data == PAYLOAD and answer.ttl == ttl, f"({answer})")
