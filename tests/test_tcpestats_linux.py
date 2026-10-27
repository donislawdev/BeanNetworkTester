"""TCP health on Linux (``tcpestats._Linux``): a connection found once in the kernel's list,
then read by the id the list gave - a real kernel's answers byte for byte.

The answers are ``test_sockdiag.py``'s: Ubuntu 26.04.1, kernel 7.0.0-38, recorded
2026-10-27 by ``internal_tools`` probe ``2026-10-27-linux-tcphealth`` in a namespace of
its own - a client 127.0.0.1:40172 to a listener on 127.0.0.1:53325 that sent 3000 bytes
and received 500, through its life. What the list does with the readings over time is
``test_nettools_tcphealth.py``'s.
"""
import socket
import sys
import time

import pytest

from beantester import crashlog, sockdiag, tcpestats
from beantester.tcprow import Connection
from fakes import check
from test_sockdiag import (CLIENT_REQUEST, CLOSE_WAIT_ANSWER, CLOSED_BY_ITS_PROGRAM_ANSWER,
                           GONE_ANSWER, HEALTH_DONE, HEALTH_LIST4, LIST4_REQUEST, LIST6_REQUEST,
                           LISTENER_ANSWER, LOOKUP_ACK, NOBODY_ANSWER, OPEN_ANSWER,
                           TIME_WAIT_ANSWER, kernel)

CLIENT = Connection("127.0.0.1", 40172, "127.0.0.1", 53325)
LIST = ((HEALTH_LIST4, HEALTH_DONE), (HEALTH_DONE,))


def linux(*answers):
    talk = kernel(*answers)
    return tcpestats._Linux(talk), talk


def watched():
    """The client watched: its reading and the handle in it."""
    system, _talk = linux(*LIST, (OPEN_ANSWER, LOOKUP_ACK))
    return tcpestats.watch(CLIENT, system)


def test_watching_finds_the_connection_in_the_list_and_reads_it_by_the_id_given():
    system, talk = linux(*LIST, (OPEN_ANSWER, LOOKUP_ACK))
    got = tcpestats.watch(CLIENT, system)
    check("both lists, then the lookup that kernel answered",
          talk.sent == [LIST4_REQUEST, LIST6_REQUEST, CLIENT_REQUEST],
          f"({[m.hex() for m in talk.sent]})")
    check("open", got.state == tcpestats.OK, f"({got})")
    sample = got.sample
    check("the numbers as ss read them, in whole milliseconds rounded down",
          (sample.smoothed_rtt, sample.min_rtt, sample.rtt_var, sample.rto, sample.mss)
          == (0, 0, 0, 201, 48128), f"({sample})")
    check("the bytes the client's socket sent and received",
          (sample.bytes_out, sample.bytes_in, sample.resent_bytes, sample.resent_segments,
           sample.timeouts) == (3000, 500, 0, 0, 0), f"({sample})")
    check("what Linux keeps no number for, said absent",
          sample.absent == tcpestats.LINUX_ABSENT and sample.widths == tcpestats.LINUX_WIDTHS)
    check("the handle: the list's id, cookie in it",
          got.handle == tcpestats.Handle(sockdiag.LINUX_AF_INET, CLIENT_REQUEST[-48:]),
          f"({got.handle})")


def test_a_reading_is_asked_by_the_handle_alone_and_ends_where_the_kernel_says_so():
    """Through the connection's life as that kernel answered: still read while the other
    side has it open (CLOSE_WAIT); ended once its program closed it, in TIME_WAIT, and
    once it is gone (ENOENT) - each final, the numbers before it staying."""
    handle = watched().handle
    system, talk = linux((CLOSE_WAIT_ANSWER, LOOKUP_ACK))
    check("CLOSE_WAIT: still open", tcpestats.read(CLIENT, system, handle).state == tcpestats.OK)
    check("one lookup, by the handle: no list read", talk.sent == [CLIENT_REQUEST],
          f"({[m.hex() for m in talk.sent]})")
    for name, answer in (("closed by its program", (CLOSED_BY_ITS_PROGRAM_ANSWER, LOOKUP_ACK)),
                         ("TIME_WAIT", (TIME_WAIT_ANSWER, LOOKUP_ACK)), ("gone", (GONE_ANSWER,))):
        got = tcpestats.read(CLIENT, linux(answer)[0], handle)
        check(f"{name}: ended", got.state == tcpestats.ENDED and got.sample is None, f"({got})")


def test_a_listener_answering_for_a_connection_is_never_its_numbers():
    """The cookie keeps the listener out (measured: without it the listener answers for
    a connection that has gone); a LISTEN answer is still ended, never read."""
    got = tcpestats.read(CLIENT, linux((LISTENER_ANSWER, LOOKUP_ACK))[0], watched().handle)
    check("ended, no numbers", got.state == tcpestats.ENDED and got.sample is None, f"({got})")


def test_a_connection_not_in_the_list_or_named_twice_is_not_guessed_at():
    got = tcpestats.watch(Connection("127.0.0.1", 40173, "127.0.0.1", 53325), linux(*LIST)[0])
    check("not there: ended, nothing looked up", got.state == tcpestats.ENDED and got.handle is None,
          f"({got})")
    twice = HEALTH_LIST4[:124] * 2
    got = tcpestats.watch(CLIENT._replace(local_port=53325, remote_port=40172),
                          linux((twice, HEALTH_DONE), (HEALTH_DONE,))[0])
    check("two sockets with its numbers: a failure that says so",
          got.state == tcpestats.FAILED and "2 sockets" in got.detail, f"({got})")


def test_a_socket_opened_as_ipv6_is_found_by_either_spelling():
    """psutil (the Sockets tab) writes a socket opened as IPv6 for an IPv4 address as
    ``::ffff:127.0.0.1``, the kernel's list and a Connections row as ``127.0.0.1``."""
    system = linux(*LIST, (OPEN_ANSWER, LOOKUP_ACK))[0]
    got = tcpestats.watch(Connection("::ffff:127.0.0.1", 40172, "::ffff:127.0.0.1", 53325), system)
    check("found", got.state == tcpestats.OK, f"({got})")


def test_what_the_kernel_refuses_is_said_in_its_words_and_never_raised(monkeypatch):
    noted = []
    monkeypatch.setattr(crashlog, "note", lambda exc, area: noted.append(area))
    refused = NOBODY_ANSWER[:16] + bytes.fromhex("f3ffffff") + NOBODY_ANSWER[20:]  # -13
    got = tcpestats.read(CLIENT, linux((refused,))[0], watched().handle)
    check("another errno: a failure with it", got.state == tcpestats.FAILED and got.code == 13
          and "errno 13" in got.detail, f"({got})")
    got = tcpestats.watch(CLIENT, linux((refused,))[0])
    check("a list the kernel refused: a failure, not 'ended'",
          got.state == tcpestats.FAILED and "refused" in got.detail, f"({got})")
    check("neither is a fault of the program", noted == [], f"({noted})")

    def broken(_message):
        raise RuntimeError("a fault in the talk on purpose")
    got = tcpestats.read(CLIENT, tcpestats._Linux(broken), watched().handle)
    check("a fault: a failure, noted", got.state == tcpestats.FAILED and noted == ["tcpestats"],
          f"({got}, {noted})")


def test_linux_is_asked_whether_it_lists_and_never_needs_rights(monkeypatch):
    def no_socket(_message):
        raise OSError(97, "Address family not supported by protocol")
    check("no sock_diag at all: cannot list", tcpestats._Linux(no_socket).can_list() is False)
    check("a list of nothing answered: can", tcpestats._Linux(kernel((HEALTH_DONE,))).can_list())
    monkeypatch.setattr(tcpestats.sys, "platform", "linux")
    monkeypatch.setattr(tcpestats._Linux, "can_list", lambda self: True)
    check("a kernel that lists: supported", tcpestats.supported() is True)
    monkeypatch.setattr(tcpestats._Linux, "can_list", lambda self: False)
    check("one that does not: not", tcpestats.supported() is False)
    check("rights: none needed", tcpestats.needs_rights() is False)
    monkeypatch.setattr(tcpestats.sys, "platform", "win32")
    check("Windows: supported, rights needed",
          tcpestats.supported() is True and tcpestats.needs_rights() is True)


def test_a_connections_row_is_looked_up_in_the_kernels_list_on_linux(monkeypatch):
    """psutil would write a dual-stack socket as ``::ffff:`` and the row would not find
    it; the kernel's list writes the address the row has."""
    monkeypatch.setattr(tcpestats.sys, "platform", "linux")
    system = tcpestats._Linux(kernel(*LIST))
    monkeypatch.setattr(tcpestats, "_Linux", lambda: system)
    rows, failed = tcpestats.socket_rows()
    check("the kernel's list", failed == [] and {(r.local_port, r.remote_port) for r in rows}
          == {(40172, 53325), (53325, 40172)}, f"({rows})")
    monkeypatch.setattr(tcpestats.sys, "platform", "win32")
    monkeypatch.setattr(tcpestats.portmap, "socket_rows", lambda: (["windows"], []))
    check("Windows: the socket table", tcpestats.socket_rows() == (["windows"], []))


def test_linux_has_its_own_sheet_tips_and_legend_and_windows_keeps_its_keys():
    """The "?" sheet is about what Windows measures and when; two column tips and the
    Stop tip name Windows; Linux keeps no newest single round trip to chart."""
    from beantester.gui.toolbox import tcphealth as panel
    check("Windows: today's sheet, tips, Stop tip and both lines",
          (panel.help_key("win32"), panel.tips("win32"), panel.stop_tip("win32"),
           panel.legend_lines("win32"))
          == ("tools.tcphealth.help_body", panel.TIPS, "tips.tools_tcphealth_stop",
              panel.LEGEND) and len(panel.LEGEND) == 2)
    linux_tips = panel.tips("linux")
    check("Linux: its own sheet, the state and resent tips, its Stop tip",
          panel.help_key("linux") == "tools.tcphealth.help_linux"
          and {k for k in panel.TIPS if panel.TIPS[k] != linux_tips[k]} == {"state", "resent"}
          and panel.stop_tip("linux") == "tips.tools_tcphealth_stop_linux")
    check("Linux: the smoothed line alone",
          [key for _style, key in panel.legend_lines("linux")] == ["tools.tcphealth.legend_smoothed"])


def test_the_linux_words_have_a_text_in_every_language():
    import json
    import os
    keys = {"tools.tcphealth.help_linux", "tools.tcphealth.item.lowest",
            "tools.tcphealth.item.resent_segments", "tips.tools_tcphealth_col_state_linux",
            "tips.tools_tcphealth_col_resent_linux", "tips.tools_tcphealth_stop_linux"}
    for lang in ("en", "pl", "zh"):
        with open(os.path.join(os.path.dirname(__file__), "..", "lang", f"{lang}.json"),
                  encoding="utf-8") as f:
            texts = json.load(f)
        missing = sorted(k for k in keys if not texts.get(k))
        check(f"{lang}: every Linux word has a text", not missing, f"({missing})")
        check(f"{lang}: the Linux sheet never says Windows",
              "Windows" not in texts["tools.tcphealth.help_linux"])


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="sock_diag is Linux's")
def test_a_real_loopback_connection_counts_exactly_the_bytes_it_sent():  # pragma: no cover - Linux
    """On this runner's kernel, without rights: watched, the bytes its socket sent and
    received; closed, ended."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.create_connection(server.getsockname(), timeout=5)
    peer, _ = server.accept()
    try:
        client.sendall(b"x" * 12345)
        got = 0
        while got < 12345:
            got += len(peer.recv(65536))
        peer.sendall(b"y" * 678)
        got = 0
        while got < 678:
            got += len(client.recv(65536))
        time.sleep(0.2)
        connection = Connection(*client.getsockname(), *client.getpeername())
        reading = tcpestats.watch(connection)
        check("open", reading.state == tcpestats.OK, f"({reading})")
        check("its bytes, exactly", (reading.sample.bytes_out, reading.sample.bytes_in)
              == (12345, 678), f"({reading.sample})")
        client.close()
        peer.close()
        time.sleep(0.2)
        check("closed: ended", tcpestats.read(connection, handle=reading.handle).state
              == tcpestats.ENDED)
    finally:
        for sock in (client, peer, server):
            sock.close()
