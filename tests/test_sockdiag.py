"""``beantester/sockdiag.py``: the kernel's own list of TCP sockets on Linux.

The fixtures are a real kernel's answers, byte for byte: Ubuntu 26.04.1, kernel
7.0.0-38, recorded 2026-10-26 by ``internal_tools`` probe ``2026-10-26-linux-reset``
(``reset_probe.py goldenns``) inside a network namespace of its own. In it, three
connections: an IPv4 client (127.0.0.1:46112 to a listener on 127.0.0.1:46669), a
client opened as IPv6 for that IPv4 listener (``::ffff:127.0.0.1``, port 46124) and an
IPv6 client (::1:58668 to ::1:58121). The ports and addresses below are what Python's
own sockets said of themselves there (``getsockname``, ``getpeername``) - not what this
module reads. And the requests are the ones that kernel answered: the list, a destroy
naming no socket (ENOENT), and the destroy of the IPv4 client by its id (done).
"""
import socket
import sys

import pytest

from beantester import portmap, sockdiag, tcpreset
from fakes import check

LIST4_REQUEST = bytes.fromhex(
    "4800000014000103010000000000000002060000fffbffff00000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000ffffffffffffffff")
LIST4 = bytes.fromhex(
    "7c000000140002000100000028c5000002010000b64db42c7f000001000000000000000000000000"
    "7f000001000000000000000000000000000000000120000000000000000000000000000000000000"
    "00000000b54a0300050008000000000008000f00000000000c001500938800000000000006001600"
    "520000007c000000140002000100000028c5000002010000b420b64d7f0000010000000000000000"
    "000000007f0000010000000000000000000000000000000002200000000000000000000000000000"
    "0000000000000000b24a0300050008000000000008000f00000000000c0015009388000000000000"
    "06001600520000007c000000140002000100000028c5000002010000b64db4207f00000100000000"
    "00000000000000007f00000100000000000000000000000000000000032000000000000000000000"
    "000000000000000000000000b34a0300050008000000000008000f00000000000c00150093880000"
    "000000000600160052000000")
DONE = bytes.fromhex("14000000030002000100000028c5000000000000")
LIST6_REQUEST = bytes.fromhex(
    "480000001400010301000000000000000a060000fffbffff00000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000ffffffffffffffff")
LIST6 = bytes.fromhex(
    "7c000000140002000100000028c500000a010000b42cb64d00000000000000000000ffff7f000001"
    "00000000000000000000ffff7f000001000000000520000000000000000000000000000000000000"
    "00000000b44a0300050008000000000008000f00000000000c001500938800000000000006001600"
    "120000007c000000140002000100000028c500000a010000e52ce309000000000000000000000000"
    "00000001000000000000000000000000000000010000000006200000000000000000000000000000"
    "0000000000000000b74a0300050008000000000008000f00000000000c0015009388000000000000"
    "06001600120000007c000000140002000100000028c500000a010000e309e52c0000000000000000"
    "00000000000000010000000000000000000000000000000100000000072000000000000000000000"
    "000000000000000000000000b84a0300050008000000000008000f00000000000c00150093880000"
    "000000000600160012000000")
NOBODY_REQUEST = bytes.fromhex(
    "4800000015000500010000000000000002060000ffffffff00000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000")
NOBODY_ANSWER = bytes.fromhex(
    "5c000000020000000100000028c50000feffffff4800000015000500010000000000000002060000"
    "ffffffff000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000")
DESTROY_REQUEST = bytes.fromhex(
    "4800000015000500010000000000000002060000ffffffffb420b64d7f0000010000000000000000"
    "000000007f000001000000000000000000000000000000000220000000000000")
DESTROY_ANSWER = bytes.fromhex(
    "24000000020000010100000028c500000000000048000000150005000100000000000000")

# (local, local port, remote, remote port) of each socket, as Python's sockets said.
IN_V4 = {("127.0.0.1", 46112, "127.0.0.1", 46669),     # the IPv4 client
         ("127.0.0.1", 46669, "127.0.0.1", 46112),     # the listener's side of it
         ("127.0.0.1", 46669, "127.0.0.1", 46124)}     # ... and of the IPv6-opened client
IN_V6 = {("127.0.0.1", 46124, "127.0.0.1", 46669),     # the client opened as IPv6
         ("::1", 58668, "::1", 58121),
         ("::1", 58121, "::1", 58668)}


class FakeNetlink:
    """A netlink socket that answers with the datagrams it was given, one per read."""

    def __init__(self, *datagrams, flags=0):
        self.datagrams = list(datagrams)
        self.flags = flags
        self.sent = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.closed = True

    def sendto(self, data, address):
        self.sent.append((data, address))

    def recvmsg(self, _size):
        return self.datagrams.pop(0), [], self.flags, (0, 0)


def kernel(*answers):
    """``talk`` for ``tcp_sockets`` and ``tcpreset._Linux``: each request gets the next
    answer (a tuple of datagrams), through the real ``exchange``. Keeps the requests."""
    sent = []
    queue = list(answers)

    def talk(message):
        sent.append(message)
        return sockdiag.exchange(message, opener=lambda: FakeNetlink(*queue.pop(0)))
    talk.sent = sent
    return talk


def ends(sockets):
    return {(s.local_ip, s.local_port, s.remote_ip, s.remote_port) for s in sockets}


def test_the_kernels_own_list_reads_as_the_sockets_said_of_themselves():
    talk = kernel((LIST4, DONE), (LIST6, DONE))
    found = sockdiag.tcp_sockets(talk)
    check("one list per family, each the request that kernel answered",
          talk.sent == [LIST4_REQUEST, LIST6_REQUEST],
          f"({[m.hex() for m in talk.sent]})")
    v4 = [s for s in found if s.kernel_family == sockdiag.LINUX_AF_INET]
    v6 = [s for s in found if s.kernel_family == sockdiag.LINUX_AF_INET6]
    check("the IPv4 list", ends(v4) == IN_V4, f"({ends(v4)})")
    check("the IPv6 list, the IPv6-opened client written as the IPv4 address it reached",
          ends(v6) == IN_V6, f"({ends(v6)})")
    check("every one TCP and open", {(s.proto, s.state) for s in found} == {("TCP", "ESTABLISHED")})
    check("the id is the kernel's, the mapped address in it",
          [s.sockid[4:20].hex() for s in v6 if s.local_port == 46124]
          == ["00000000000000000000ffff7f000001"])


def test_a_socket_is_destroyed_by_the_id_the_list_gave_and_the_kernel_says_done():
    """The request ``tcpreset`` sends for the IPv4 client is byte for byte the one that
    kernel destroyed it by - its cookie in it - and its answer reads as done."""
    found = sockdiag.tcp_sockets(kernel((LIST4, DONE), (LIST6, DONE)))
    client = [s for s in found if s.local_port == 46112]
    talk = kernel((DESTROY_ANSWER,))
    code = tcpreset._Linux(talk).destroy(client[0].kernel_family, client[0].sockid)
    check("the request that kernel acknowledged", talk.sent == [DESTROY_REQUEST],
          f"({talk.sent[0].hex()})")
    check("and its answer: done", code == 0, f"({code})")


def test_the_destroy_that_names_no_socket_is_the_one_the_kernel_answered_enoent():
    talk = kernel((NOBODY_ANSWER,))
    check("ENOENT: this kernel destroys sockets", tcpreset._Linux(talk).can_destroy() is True)
    check("the request: ports 0, addresses 0, cookie 0", talk.sent == [NOBODY_REQUEST],
          f"({talk.sent[0].hex()})")


def test_an_answer_is_read_to_its_end_across_datagrams_and_the_socket_closed():
    nl = FakeNetlink(LIST4, DONE)
    replies = sockdiag.exchange(b"request", opener=lambda: nl)
    check("three sockets, then DONE", [kind for kind, _ in replies]
          == [sockdiag.SOCK_DIAG_BY_FAMILY] * 3 + [sockdiag.NLMSG_DONE])
    check("sent to the kernel (port 0)", nl.sent == [(b"request", (0, 0))])
    check("and closed", nl.closed)
    check("DONE ends in no error", sockdiag.error_of(replies) == 0)


def test_what_does_not_add_up_is_an_error_never_a_shorter_list():
    cut = FakeNetlink(LIST4, flags=sockdiag.MSG_TRUNC)
    with pytest.raises(OSError, match="longer than the buffer"):
        sockdiag.exchange(b"r", opener=lambda: cut)
    check("closed after an error too", cut.closed)
    with pytest.raises(OSError, match="longer than its datagram"):
        sockdiag.exchange(b"r", opener=lambda: FakeNetlink(LIST4[:200]))
    with pytest.raises(OSError, match="longer than its datagram"):     # a length of 0
        sockdiag.exchange(b"r", opener=lambda: FakeNetlink(bytes(20)))
    with pytest.raises(OSError, match="ends in type"):
        sockdiag.error_of([(sockdiag.SOCK_DIAG_BY_FAMILY, LIST4[16:124])])
    with pytest.raises(OSError, match="in 40 bytes"):
        sockdiag._socket(LIST4[16:56])


def test_a_list_the_kernel_refuses_is_an_error_for_both_families():
    """An error in place of the list - in the IPv6 one as much as in the first - is
    raised: a socket missing from a list that was not read says nothing."""
    refused = NOBODY_ANSWER[:16] + bytes.fromhex("f3ffffff") + NOBODY_ANSWER[20:]  # -13
    for answers in (((refused,),), ((LIST4, DONE), (refused,))):
        with pytest.raises(OSError, match="refused the list") as raised:
            sockdiag.tcp_sockets(kernel(*answers))
        check("with the kernel's errno", raised.value.errno == 13, f"({raised.value.errno})")


def test_the_states_read_in_the_socket_tables_words():
    words = set(portmap.TCP_STATES.values())
    check("every state but the kernel's own NEW_SYN_RECV is a portmap word",
          set(sockdiag.STATES.values()) - words == {"NEW_SYN_RECV"},
          f"({set(sockdiag.STATES.values()) - words})")
    check("the states a reset sends a reset in are among them", tcpreset.RESETS <= words)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="sock_diag is Linux's")
def test_a_loopback_connection_of_this_process_is_in_the_real_list():  # pragma: no cover - Linux
    """The list needs no rights (measured as a user): a connection this test opens is in
    it, with the ends its sockets give - on this runner's kernel, not a recording."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.create_connection(server.getsockname(), timeout=5)
    peer, _ = server.accept()
    try:
        here = client.getsockname() + client.getpeername()
        found = [s for s in sockdiag.tcp_sockets()
                 if (s.local_ip, s.local_port, s.remote_ip, s.remote_port) == here]
        check("the client, open", [s.state for s in found] == ["ESTABLISHED"], f"({found})")
        check("from the IPv4 list", found[0].kernel_family == sockdiag.LINUX_AF_INET)
    finally:
        for sock in (client, peer, server):
            sock.close()
