"""The port check's logic (``nettools/portcheck.py``): what a bind answer and the socket
table say together, which ports an expression names, and what the probe does.

Most tests stand in for the bind and the table, so every runner sees the same
answers. Three touch the real system, on loopback only: a port this test holds, a
port nobody holds, and a subprocess that shows the check does nothing but create
and bind sockets - the Tools tab's promise (``test_no_telemetry.py``).
"""
import errno
import json
import os
import socket
import subprocess
import sys

import pytest

from beantester.nettools import portcheck as pc
from beantester.nettools import sockets as sk
from fakes import ROOT, check

ALL = (pc.PROTOCOLS, pc.FAMILIES)


def sock(port, proto="TCP", family=4, state="LISTEN", pid=1234, proc="server.exe", ip=None):
    ip = ip or ("127.0.0.1" if family == 4 else "::1")
    return sk.Socket(f"{proto}|{ip}|{port}|{family}|{state}|{pid}", proto, family,
                     ip, port, "", None, state, pid, proc)


def run(text, answers=None, rows=(), protocols=pc.PROTOCOLS, families=pc.FAMILIES,
        calls=None, failed=(), progress=None, clock=lambda: 0.0):
    """``check`` with a stand-in bind (``answers``: (proto, family, port) -> code, else 0)
    and table (``failed``: the tables that did not answer). The clock stands still
    unless a test passes one: the table is read once, at the end."""
    calls = [] if calls is None else calls

    def bind(proto, family, port):
        calls.append(("bind", proto, family, port))
        return (answers or {}).get((proto, family, port), 0)

    def read():
        calls.append(("read",))
        return sk.Snapshot(tuple(rows), tuple(failed), 0.0, 0)

    return pc.check(pc.parse(text), protocols, families, bind=bind, read=read,
                    progress=progress, clock=clock)


def verdicts(result):
    """Per port, protocol and IP version - whatever rows the ports were folded into."""
    return {(r.port, r.proto, r.family): r.verdict for r in pc.unfold(result.rows)}


def test_a_held_port_names_its_holder_and_the_rest_are_free():
    result = run("8080", {("TCP", 4, 8080): 10048}, rows=[sock(8080, proc="node.exe")])
    seen = verdicts(result)
    check("the held one is in use", seen[(8080, "TCP", 4)] == pc.IN_USE, f"({seen})")
    row = next(r for r in result.rows if (r.proto, r.family) == ("TCP", 4))
    check("with who holds it", row.owners == ((1234, "node.exe"),), f"({row.owners})")
    check("and the bind's own answer kept", row.code == 10048, f"({row.code})")
    check("the other protocol and version are free",
          [seen[(8080, p, f)] for p, f in (("TCP", 6), ("UDP", 4), ("UDP", 6))] == [pc.FREE] * 3,
          f"({seen})")


def test_a_holder_no_bind_can_see_still_holds_the_port():
    """A dual-stack server on [::] - how Node listens by default. MEASURED 2026-09-24 on
    Windows 11, the holder in another process: in the table on IPv4 and IPv6, and every
    bind beside it succeeds, even with SO_EXCLUSIVEADDRUSE, even a listen."""
    rows = [sock(3000, family=4, proc="node.exe"), sock(3000, family=6, proc="node.exe")]
    seen = verdicts(run("3000", rows=rows))
    check("in use on both versions although every bind said yes",
          seen[(3000, "TCP", 4)] == seen[(3000, "TCP", 6)] == pc.IN_USE, f"({seen})")
    check("and only for its own protocol", seen[(3000, "UDP", 4)] == pc.FREE, f"({seen})")


def test_linux_lists_a_dual_stack_server_once_and_its_refusal_names_it(monkeypatch):
    """MEASURED 2026-11-03 (Ubuntu 26.04 and WSL, the release rig): a server on [::] that
    takes IPv4 too is in Linux's table once, under IPv6, and a bind on 127.0.0.1 beside it
    is refused. Its IPv4 row read "in use (owner not shown)" while the table knew the
    owner. One on [::] for IPv6 alone lets that bind through, and holds nothing on IPv4."""
    monkeypatch.setattr(pc, "WINDOWS", False)
    dual = [sock(3000, family=6, ip="::", proc="node"),
            sock(53, proto="UDP", family=6, state="", ip="::", proc="dnsd")]
    refused = {("TCP", 4, 3000): errno.EADDRINUSE, ("UDP", 4, 53): errno.EADDRINUSE}
    rows = {(r.port, r.proto, r.family): r for r in run("53, 3000", refused, rows=dual).rows}
    for where, name in (((3000, "TCP", 4), "node"), ((53, "UDP", 4), "dnsd")):
        check(f"{where}: in use, by the server on [::]", rows[where].verdict == pc.IN_USE
              and rows[where].owners == ((1234, name),), f"({rows[where]})")
    check("on IPv6 as before", rows[(3000, "TCP", 6)].verdict == pc.IN_USE, f"({rows})")
    check("and only for its own protocol", rows[(3000, "UDP", 4)].verdict == pc.FREE
          and not rows[(3000, "UDP", 4)].owners, f"({rows[(3000, 'UDP', 4)]})")

    alone = run("3000", rows=[sock(3000, family=6, ip="::", proc="nginx")]).rows
    v4 = next(r for r in alone if (r.proto, r.family) == ("TCP", 4))
    check("[::] for IPv6 alone (every bind worked): the IPv4 port is free, nobody named",
          v4.verdict == pc.FREE and not v4.owners, f"({v4})")
    elsewhere = run("3000", {("TCP", 4, 3000): errno.EADDRINUSE},
                    rows=[sock(3000, family=6, proc="web")])
    check("a socket on ::1 is not one on [::]: that refusal stays unexplained",
          verdicts(elsewhere)[(3000, "TCP", 4)] == pc.UNSEEN, f"({verdicts(elsewhere)})")


def test_an_ipv4_address_written_the_ipv6_way_holds_ipv4(monkeypatch):
    """Linux lists the connections a dual-stack server accepted from IPv4 under IPv6, as
    ::ffff:127.0.0.1 - and their TIME_WAIT, which the server's own closes leave behind.
    MEASURED 2026-11-03 (the release rig): once that server stopped, its IPv4 port read
    "in use (owner not shown)" instead of closing."""
    monkeypatch.setattr(pc, "WINDOWS", False)
    mapped = "::ffff:127.0.0.1"
    talking = run("4000", {("TCP", 4, 4000): errno.EADDRINUSE},
                  rows=[sock(4000, family=6, ip=mapped, state="ESTABLISHED", pid=77, proc="app")])
    rows = {(r.port, r.proto, r.family): r for r in talking.rows}
    check("an accepted IPv4 connection holds IPv4", rows[(4000, "TCP", 4)].owners == ((77, "app"),),
          f"({rows[(4000, 'TCP', 4)]})")
    check("and not IPv6", rows[(4000, "TCP", 6)].verdict == pc.FREE, f"({rows[(4000, 'TCP', 6)]})")

    waiting = [sock(4001, family=6, ip=mapped, state="TIME_WAIT", pid=0, proc="")]
    closed = verdicts(run("4001", {("TCP", 4, 4001): errno.EADDRINUSE}, rows=waiting))
    check("its TIME_WAIT beside a refused IPv4 bind: closing", closed[(4001, "TCP", 4)] == pc.CLOSING,
          f"({closed})")
    serving = waiting + [sock(4001, family=6, ip="::", proc="node")]
    still = run("4001", {("TCP", 4, 4001): errno.EADDRINUSE}, rows=serving).rows
    v4 = next(r for r in still if (r.proto, r.family) == ("TCP", 4))
    check("while the server still listens, the port is in use by it, not closing",
          v4.verdict == pc.IN_USE and v4.owners == ((1234, "node"),), f"({v4})")


def test_an_ipv4_time_wait_explains_a_refusal_beside_a_server_on_any(monkeypatch):
    """An IPv4 connection's TIME_WAIT refuses the IPv4 bind by itself, and the table cannot
    tell [::] for both IP versions from [::] for IPv6 alone - MEASURED 2026-11-04 (the
    release rig): with one for IPv6 alone there, the IPv4 row named that server."""
    monkeypatch.setattr(pc, "WINDOWS", False)
    rows = [sock(4100, state="TIME_WAIT", pid=0, proc=""),
            sock(4100, family=6, ip="::", proc="nginx")]
    found = {(r.port, r.proto, r.family): r
             for r in run("4100", {("TCP", 4, 4100): errno.EADDRINUSE}, rows=rows).rows}
    v4 = found[(4100, "TCP", 4)]
    check("closing, and the server on [::] is not named for IPv4",
          v4.verdict == pc.CLOSING and not v4.owners, f"({v4})")
    check("it holds its own IPv6 port", found[(4100, "TCP", 6)].owners == ((1234, "nginx"),),
          f"({found[(4100, 'TCP', 6)]})")


def test_windows_never_names_a_socket_on_any_for_an_ipv4_refusal(monkeypatch):
    """Windows lists a server on [::] for both IP versions under IPv4 too (MEASURED
    2026-09-24), so an IPv4 refusal with no IPv4 row is never that server's - and the
    IPv4 table may be the one that did not answer."""
    monkeypatch.setattr(pc, "WINDOWS", True)
    for failed in ((), ("tcp/v4",)):
        result = run("3000", {("TCP", 4, 3000): 10048}, failed=failed,
                     rows=[sock(3000, family=6, ip="::", proc="web.exe")])
        v4 = next(r for r in result.rows if (r.proto, r.family) == ("TCP", 4))
        check(f"tables failed {failed}: in use, owner not shown",
              v4.verdict == pc.UNSEEN and not v4.owners, f"({v4})")


def test_a_holder_counts_only_for_its_own_protocol_and_ip_version():
    rows = [sock(53, proto="UDP", family=4, state="", proc="dns.exe"),
            sock(443, family=6, proc="web.exe")]
    seen = verdicts(run("53, 443", rows=rows))
    check("a UDP socket does not hold TCP", seen[(53, "TCP", 4)] == pc.FREE, f"({seen})")
    check("it holds UDP", seen[(53, "UDP", 4)] == pc.IN_USE, f"({seen})")
    check("an IPv6 socket does not hold IPv4", seen[(443, "TCP", 4)] == pc.FREE, f"({seen})")


def test_time_wait_holds_nothing_and_a_refusal_beside_it_is_closing():
    """MEASURED 2026-09-24 on Windows: a bind succeeds beside TIME_WAIT (PID 0). On
    Linux the same bind fails - that port is closing, not held by anyone."""
    waiting = [sock(p, state="TIME_WAIT", pid=0, proc="") for p in (5000, 5001)]
    result = run("5000-5002", {("TCP", 4, 5001): errno.EADDRINUSE,
                               ("TCP", 4, 5002): errno.EADDRINUSE}, rows=waiting)
    seen = verdicts(result)
    check("TIME_WAIT beside a bind that worked: free", seen[(5000, "TCP", 4)] == pc.FREE,
          f"({seen})")
    check("TIME_WAIT beside a refusal: closing", seen[(5001, "TCP", 4)] == pc.CLOSING,
          f"({seen})")
    check("a refusal with nothing in the table: in use, owner not shown",
          seen[(5002, "TCP", 4)] == pc.UNSEEN, f"({seen})")
    check("a TIME_WAIT row is never an owner",
          all(not r.owners for r in result.rows), f"({[r.owners for r in result.rows]})")


def test_a_table_that_did_not_answer_cannot_say_free_or_reserved(monkeypatch):
    """Windows reads four socket tables and names the ones that failed. A row of such a
    table cannot read Free (a dual-stack server is invisible to a bind) or Reserved
    (another program's exclusive socket answers the same): both rest on the table
    naming nobody. What the bind alone proves stays as it was."""
    monkeypatch.setattr(pc, "WINDOWS", True)
    answers = {("TCP", 4, 3001): 10048, ("TCP", 4, 3002): 10013, ("TCP", 6, 3002): 10013,
               ("TCP", 4, 3003): 10022}
    result = run("3000-3003", answers, failed=("tcp/v4",),
                 rows=[sock(3000, family=6, ip="::", proc="node.exe")])
    seen = verdicts(result)
    check("a bind that worked: unknown, not free", seen[(3000, "TCP", 4)] == pc.UNREAD,
          f"({seen})")
    check("access refused: unknown, not reserved", seen[(3002, "TCP", 4)] == pc.UNREAD,
          f"({seen})")
    check("a refusal is in use whatever the table says", seen[(3001, "TCP", 4)] == pc.UNSEEN,
          f"({seen})")
    check("an answer this tool does not know stays one", seen[(3003, "TCP", 4)] == pc.FAILED,
          f"({seen})")
    check("the tables that answered keep their verdicts",
          (seen[(3000, "UDP", 4)], seen[(3002, "TCP", 6)], seen[(3000, "TCP", 6)])
          == (pc.FREE, pc.RESERVED, pc.IN_USE), f"({seen})")
    check("and the check names the one that did not", result.unread == (("TCP", 4),),
          f"({result.unread})")
    counted = (pc.not_free(result.rows), pc.unknown(result.rows))
    check("an unknown row is counted as unknown, not as not free", counted == (4, 2),
          f"({counted})")


def test_only_the_tables_that_were_checked_are_named_as_unread():
    failed = ("tcp/v4", "udp/v6")
    check("a protocol left out is not named",
          run("80", protocols=("TCP",), failed=failed).unread == (("TCP", 4),))
    check("nor an IP version this machine does not have",
          run("80", {("TCP", 6, 80): errno.EAFNOSUPPORT}, failed=failed).unread
          == (("TCP", 4),))
    check("every table named, in order", run("80", failed=("udp/v6", "tcp/v6", "tcp/v4")).unread
          == (("TCP", 4), ("TCP", 6), ("UDP", 6)))
    check("all answered: none", run("80").unread == ())


def test_access_denied_is_a_reservation_on_windows_only(monkeypatch):
    """WSAEACCES on a port nobody holds is a range Windows set aside (KB 3039044,
    measured). Off Windows, EACCES is a port this account may not use."""
    answers = {("TCP", 4, 9010): 10013, ("TCP", 4, 9011): errno.EACCES,
               ("TCP", 4, 9012): 10013}
    rows = [sock(9012, proc="exclusive.exe")]
    monkeypatch.setattr(pc, "WINDOWS", True)
    seen = verdicts(run("9010-9012", answers, rows=rows))
    check("both spellings of access denied read as reserved on Windows",
          seen[(9010, "TCP", 4)] == seen[(9011, "TCP", 4)] == pc.RESERVED, f"({seen})")
    check("but a row in the table wins: someone holds it",
          seen[(9012, "TCP", 4)] == pc.IN_USE, f"({seen})")
    monkeypatch.setattr(pc, "WINDOWS", False)
    seen = verdicts(run("9010-9012", answers, rows=rows))
    check("off Windows it is not allowed, not reserved",
          seen[(9010, "TCP", 4)] == seen[(9011, "TCP", 4)] == pc.DENIED, f"({seen})")


def test_an_answer_this_tool_does_not_know_is_not_checked_and_keeps_its_number():
    result = run("9000", {("UDP", 6, 9000): 10055})
    row = next(r for r in result.rows if (r.proto, r.family) == ("UDP", 6))
    check("not free, not in use: not checked", row.verdict == pc.FAILED, f"({row.verdict})")
    check("the number the system gave", row.code == 10055, f"({row.code})")


@pytest.mark.parametrize("code", [10047, 10049, errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL])
def test_a_machine_without_an_ip_version_is_said_once_not_per_port(code):
    calls = []
    answers = {(p, 6, port): code for p in pc.PROTOCOLS for port in range(7000, 7010)}
    result = run("7000-7009", answers, calls=calls)
    check("that version is named as unavailable", result.unavailable == (6,),
          f"({result.unavailable})")
    check("and only the other one counts as checked", result.families == (4,),
          f"({result.families})")
    check("it has no rows", all(r.family == 4 for r in result.rows), "")
    asked = [c for c in calls if c[0] == "bind" and c[2] == 6]
    check("the first answer ended it", len(asked) == 1, f"({len(asked)} binds on IPv6)")
    check("and the check did not stop: what it set out to do shrank with it",
          (result.made, result.planned, result.stopped) == (20, 20, False),
          f"({result.made}, {result.planned})")


def test_the_system_is_asked_first_and_the_table_read_after():
    """A holder that starts in between is then in the table: the answer errs towards
    "in use", never towards "free"."""
    calls = []
    run("100, 200", calls=calls)
    check("one read, after every bind", [c[0] for c in calls][-1] == "read"
          and [c[0] for c in calls].count("read") == 1, f"({calls})")


def test_a_socket_table_that_cannot_be_read_fails_the_whole_check():
    def refused():
        raise sk.Unreadable("tools.sockets.error_denied", "the table refused on purpose")
    with pytest.raises(sk.Unreadable):
        pc.check(pc.parse("80"), *ALL, bind=lambda *a: 0, read=refused)


def test_the_ports_an_expression_names():
    check("a list and a range, in order",
          pc.ports(pc.parse("443, 80, 8000-8002")) == ((80, 443, 8000, 8001, 8002), False),
          f"({pc.ports(pc.parse('443, 80, 8000-8002'))})")
    wanted, zero = pc.ports(pc.parse("0, 80"))
    check("port 0 is left out and said", (wanted, zero) == ((80,), True), f"({wanted}, {zero})")
    every, zero = pc.ports(pc.parse(pc.ALL_PORTS))
    check("every port, as the All ports button types it",
          (len(every), every[0], every[-1], zero) == (65535, 1, 65535, False), f"({len(every)})")
    check("and everything but one", len(pc.ports(pc.parse("!80"))[0]) == 65534, "")
    for text, key in (("0", "tools.portcheck.error_zero"), ("re:^$", "tools.portcheck.error_none")):
        with pytest.raises(pc.Refused) as caught:
            pc.ports(pc.parse(text))
        check(f"{text!r} is refused with its reason", caught.value.user_key == key,
              f"({caught.value.user_key})")
    with pytest.raises(ValueError):
        pc.parse("9100-9000")          # the port language's own message, already translated


def test_a_check_of_every_port_reaches_the_last_one():
    """The range is named to 65535 (above); this is the check going all the way there:
    the last bind is port 65535, and a holder on it is a row of its own."""
    calls = []
    result = run(pc.ALL_PORTS, {("TCP", 4, 65535): 10048}, rows=[sock(65535)],
                 protocols=("TCP",), families=(4,), calls=calls)
    binds = [c for c in calls if c[0] == "bind"]
    check("every port was bound, the last one last",
          (len(binds), binds[-1]) == (65535, ("bind", "TCP", 4, 65535)), f"({len(binds)})")
    check("and the check says it finished",
          (result.made, result.planned, result.stopped) == (65535, 65535, False),
          f"({result.made}, {result.planned})")
    shape = sorted((r.port, r.last, r.verdict) for r in result.rows)
    check("the free ports are one row and the held last port its own",
          shape == [(1, 65534, pc.FREE), (65535, 65535, pc.IN_USE)], f"({shape})")
    check("the binds a check would make", pc.planned(pc.parse("80, 443"), *ALL) == 8, "")
    check("none for ports it refuses (the worker says why)",
          pc.planned(pc.parse("0"), *ALL) == 0, "")


def test_ports_next_to_each_other_with_the_same_answer_are_one_row():
    """Every port of a machine is 262 140 binds and, MEASURED 2026-11-11, 105 rows that
    are not free on the developer machine once the neighbours are folded together."""
    answers = {("TCP", 4, 8003): 10013, ("TCP", 4, 8004): 10013}
    rows = [sock(8006, proc="a.exe"), sock(8007, proc="a.exe"), sock(8008, proc="b.exe")]
    result = run("8000-8008, 9000, 9002", answers, rows=rows, protocols=("TCP",), families=(4,))
    got = sorted((r.port, r.last, r.verdict, r.owners) for r in result.rows)
    check("a run is one row, broken by a new answer, a new holder or a gap", got == [
        (8000, 8002, pc.FREE, ()), (8003, 8004, pc.RESERVED if pc.WINDOWS else pc.DENIED, ()),
        (8005, 8005, pc.FREE, ()), (8006, 8007, pc.IN_USE, ((1234, "a.exe"),)),
        (8008, 8008, pc.IN_USE, ((1234, "b.exe"),)), (9000, 9000, pc.FREE, ()),
        (9002, 9002, pc.FREE, ())], f"({got})")
    check("the counts count ports, not rows",
          (pc.not_free(result.rows), pc.checked(result.rows)) == (5, 11),
          f"({pc.not_free(result.rows)}, {pc.checked(result.rows)})")
    wide = next(r for r in result.rows if r.port == 8000)
    check("a row knows how many ports it stands for", wide.size() == 3, f"({wide})")
    check("and unfolds into one row per port, keyed as one",
          [(r.port, r.last, r.key) for r in pc.unfold([wide])]
          == [(8000, 8000, "8000|TCP|4"), (8001, 8001, "8001|TCP|4"), (8002, 8002, "8002|TCP|4")])
    other = run("8000-8001", rows=[sock(8001, family=6)], protocols=("TCP",)).rows
    check("never across IP versions", {(r.port, r.last, r.family) for r in other}
          == {(8000, 8001, 4), (8000, 8000, 6), (8001, 8001, 6)}, f"({other})")


def test_a_long_check_reads_the_table_as_it_goes():
    """A connection that held a port at its bind can be gone by the end of a 35 s check
    (the Server VM, MEASURED 2026-11-11): read only then, its refused bind would name
    nobody. So the table is read once the binds waiting for it are a second old."""
    now = [0.0]

    def clock():
        now[0] += 0.4               # each bind takes 0.4 s by this clock
        return now[0]

    reads = []

    def read():
        reads.append(1)
        # The holder of 7001 is in the table only at the first read: a short connection.
        held = (sock(7001, state="ESTABLISHED", proc="short.exe"),) if len(reads) == 1 else ()
        return sk.Snapshot(held, (), 0.0, 0)

    calls = []

    def bind(proto, family, port):
        calls.append(port)
        return 10048 if port == 7001 else 0

    result = pc.check(pc.parse("7001-7006"), ("TCP",), (4,), bind=bind,
                      read=lambda: (calls.append("read"), read())[1], clock=clock)
    check("read once the oldest bind waiting is a second old, and once more at the end",
          calls == [7001, 7002, 7003, 7004, "read", 7005, 7006, "read"], f"({calls})")
    first = next(r for r in result.rows if r.port == 7001)
    check("the short connection is named for the port it held", first.verdict == pc.IN_USE
          and first.owners == ((1234, "short.exe"),), f"({first})")


def test_a_socket_gone_since_the_last_read_holds_nothing():
    """A read that follows another (``sockets.read`` with ``previous``, how a long check
    reads the table) also lists the sockets that closed since, marked CLOSED."""
    gone = sock(6100, proc="old.exe")._replace(change=sk.CLOSED)
    seen = verdicts(run("6100", rows=[gone], protocols=("TCP",), families=(4,)))
    check("a closed socket is not a holder", seen[(6100, "TCP", 4)] == pc.FREE, f"({seen})")
    asked = []

    def read(previous, fresh_names=True):
        asked.append((previous, fresh_names))
        return len(asked)
    again = pc._table(read)
    again(), again(), again()
    check("the first read names every process, the next ones keep its names",
          asked == [(None, True), (1, False), (2, False)], f"({asked})")


def test_stop_ends_the_check_and_keeps_what_was_checked():
    progress = pc.Progress()
    calls = []

    def bind(proto, family, port):
        calls.append(("bind", port))
        if port == 3:
            progress.stop()          # Stop pressed while the third bind runs
        return 10013 if port == 2 else 0

    def read():
        calls.append(("read",))
        return sk.Snapshot((), (), 0.0, 0)

    result = pc.check(pc.parse("1-10"), ("TCP", "UDP"), (4,), bind=bind, read=read,
                      progress=progress)
    check("no bind after Stop", [c for c in calls if c[0] == "bind"]
          == [("bind", 1), ("bind", 2), ("bind", 3)], f"({calls})")
    check("and the table read for the binds made", calls[-1] == ("read",), f"({calls})")
    check("the rows are what was checked", pc.checked(result.rows) == 3
          and {(r.port, r.last) for r in result.rows} == {(1, 1), (2, 2), (3, 3)},
          f"({result.rows})")
    check("it says it stopped, where, and how far it got",
          (result.stopped, result.stopped_at, result.made, result.planned)
          == (True, ("TCP", 4, 3), 3, 20),
          f"({result.stopped}, {result.stopped_at}, {result.made}, {result.planned})")
    check("its progress said so too", (progress.made, progress.planned, progress.percent())
          == (3, 20, 15), f"({progress.made}, {progress.planned})")

    early = pc.Progress()
    early.stop()
    calls.clear()
    none = pc.check(pc.parse("1-10"), ("TCP",), (4,), bind=bind, read=read, progress=early)
    check("Stop before the first bind: nothing bound, nothing read, nothing shown",
          (calls, none.rows, none.stopped, none.stopped_at) == ([], (), True, None),
          f"({calls}, {none})")
    whole = run("1-3")
    check("a check that ran to the end did not stop",
          (whole.stopped, whole.stopped_at, whole.made, whole.planned) == (False, None, 12, 12),
          f"({whole.stopped}, {whole.made}, {whole.planned})")


def test_problems_come_first_then_the_port_order():
    rows = run("10, 20", {("TCP", 4, 20): 10013}, rows=[sock(10, family=6, proc="b.exe")],
               protocols=("TCP",)).rows
    check("the default order: what stops a program first",
          [(r.port, r.family, r.verdict) for r in rows]
          == [(10, 6, pc.IN_USE), (20, 4, pc.RESERVED if pc.WINDOWS else pc.DENIED),
              (10, 4, pc.FREE), (20, 6, pc.FREE)], f"({[(r.port, r.family) for r in rows]})")
    by_port = pc.sort(rows, "port", reverse=True)
    check("by port, reversed", [r.port for r in by_port] == [20, 20, 10, 10],
          f"({[r.port for r in by_port]})")
    by_name = pc.sort(rows, "holder")
    check("rows without a holder sort last", by_name[0].owners == ((1234, "b.exe"),),
          f"({by_name[0]})")
    check("counted", pc.not_free(rows) == 2, f"({pc.not_free(rows)})")


def placed(found, names=None, port=6000, proto="TCP", family=4):
    row = next(r for r in run(str(port), rows=found).rows
               if (r.proto, r.family) == (proto, family))
    return pc.listens_on(row, names)


def connected(port, ip="127.0.0.1", proc="client.exe"):
    return sk.Socket(f"c{port}{ip}", "TCP", 4, ip, port, "10.0.0.9", 443, "ESTABLISHED",
                     55, proc)


def test_listens_on_says_where_the_holder_waits():
    """Where, not who can reach it: MEASURED 2026-11-11, port 445 here and 47001 on the
    Server VM wait on every address while the firewall lets nobody from the network in -
    so the column is named after the address, and says nothing it cannot know."""
    names = {"192.168.1.5": (0, "Ethernet"), "172.20.0.1": (1, "vEthernet (WSL)")}
    check("a wildcard address: every network, whatever else is there",
          placed([sock(6000, ip="0.0.0.0"), sock(6000, ip="127.0.0.1", pid=2)])
          == ((pc.ANYWHERE, ""),))
    check("loopback alone: this computer",
          placed([sock(6000, ip="127.0.0.1")]) == ((pc.THIS_COMPUTER, ""),))
    check("adapters by name, in the Adapters tab's order, this computer last",
          placed([sock(6000, ip="127.0.0.1", pid=3), sock(6000, ip="172.20.0.1", pid=2),
                  sock(6000, ip="192.168.1.5")], names)
          == ((pc.ADAPTER, "Ethernet"), (pc.ADAPTER, "vEthernet (WSL)"),
              (pc.THIS_COMPUTER, "")), "")
    check("an address no adapter has stays itself, after the named ones",
          placed([sock(6000, ip="10.9.9.9"), sock(6000, ip="192.168.1.5", pid=2)], names)
          == ((pc.ADAPTER, "Ethernet"), (pc.ADDRESS, "10.9.9.9")))
    check("without names every address is itself",
          placed([sock(6000, ip="192.168.1.5")]) == ((pc.ADDRESS, "192.168.1.5"),))
    check("only connections hold it: a connection, not a server",
          placed([connected(6000)]) == ((pc.CONNECTION, ""),))
    check("a server with its connections: the server's address",
          placed([sock(6000, ip="0.0.0.0"), connected(6000)]) == ((pc.ANYWHERE, ""),))
    check("UDP has no far end: a UDP socket waits",
          placed([sock(6000, proto="UDP", state="", ip="192.168.1.5")], names, proto="UDP")
          == ((pc.ADAPTER, "Ethernet"),))
    check("nobody holds it: nothing", placed([]) == ())
    v6 = [sock(6000, family=6, ip="fe80::1%12"), sock(6000, family=6, ip="::1", pid=2)]
    check("an IPv6 zone is not part of the adapter's address",
          placed(v6, {"fe80::1": (0, "Wi-Fi")}, family=6)
          == ((pc.ADAPTER, "Wi-Fi"), (pc.THIS_COMPUTER, "")))


def test_listens_on_reads_linux_addresses_written_the_ipv6_way(monkeypatch):
    monkeypatch.setattr(pc, "WINDOWS", False)
    mapped = [sock(6000, family=6, ip="::ffff:192.168.1.5"),
              sock(6001, family=6, ip="::ffff:127.0.0.1")]
    rows = {r.port: r for r in run("6000, 6001", rows=mapped).rows
            if (r.proto, r.family) == ("TCP", 4)}
    check("an IPv4 address written the IPv6 way is the adapter's",
          pc.listens_on(rows[6000], {"192.168.1.5": (0, "eth0")}) == ((pc.ADAPTER, "eth0"),))
    check("and loopback is this computer",
          pc.listens_on(rows[6001]) == ((pc.THIS_COMPUTER, ""),))
    dual = run("3000", {("TCP", 4, 3000): errno.EADDRINUSE},
               rows=[sock(3000, family=6, ip="::", proc="node")]).rows
    v4 = next(r for r in dual if (r.proto, r.family) == ("TCP", 4))
    check("a dual-stack server named for IPv4 waits on every network",
          pc.listens_on(v4) == ((pc.ANYWHERE, ""),), f"({v4})")


def test_the_addresses_rows_are_folded_by_where_the_holder_waits_too():
    rows = [sock(5000, ip="0.0.0.0"), sock(5001, ip="127.0.0.1")]
    result = run("5000-5001", rows=rows, protocols=("TCP",), families=(4,))
    check("same holder, another address: two rows",
          sorted((r.port, r.last, r.listens) for r in result.rows)
          == [(5000, 5000, ("0.0.0.0",)), (5001, 5001, ("127.0.0.1",))], f"({result.rows})")
    by = pc.sort(result.rows, "listens")
    check("sorted by the address", [r.port for r in by] == [5000, 5001], "")


class _Adapter:
    def __init__(self, name, *ips):
        self.row = type("R", (), {"name": name, "addresses": tuple(
            type("A", (), {"ip": ip})() for ip in ips)})()


def test_adapter_names_are_read_only_when_a_row_needs_one(monkeypatch):
    snapshot = type("S", (), {"adapters": (_Adapter("Ethernet", "192.168.1.5", "fe80::1%9"),
                                           _Adapter("Wi-Fi", "192.168.1.5"))})()
    reads = []

    def read():
        reads.append(1)
        return snapshot

    names = pc.adapter_names(read)
    check("each address to its first adapter, zones off",
          names == {"192.168.1.5": (0, "Ethernet"), "fe80::1": (0, "Ethernet")}, f"({names})")
    common = run("80, 81", rows=[sock(80, ip="0.0.0.0"), sock(81, ip="127.0.0.1")])
    reads.clear()
    check("every network or loopback alone: no adapter read",
          pc.with_adapter_names(common, read).names == {} and reads == [], f"({reads})")
    one = run("80", rows=[sock(80, ip="192.168.1.5")])
    check("an adapter's own address: read", pc.with_adapter_names(one, read).names == names
          and reads == [1], f"({reads})")

    def unreadable():
        raise pc.adapters.Unreadable("tools.adapters.error_not_ready", "not ready on purpose")
    check("adapters that cannot be read: no names, the check stands",
          pc.with_adapter_names(one, unreadable).names == {})
    noted = []
    monkeypatch.setattr(pc.crashlog, "note", lambda exc, area: noted.append((repr(exc), area)))

    def broken():
        raise KeyError("a fault of the reader")
    check("a fault in the reader: no names, the check stands, the fault recorded",
          pc.with_adapter_names(one, broken).names == {} and len(noted) == 1, f"({noted})")


def test_whether_windows_logs_every_bind_is_true_false_or_unknown():
    """``winenv.binds_audited``, the port check's question before a check of thousands
    of ports. Its real reads were MEASURED 2026-11-11 on a Windows Server VM, with the
    policy switched both ways by auditpol; here the system is stood in for, bit by bit."""
    from beantester import winenv
    for info, want in ((0, False), (1, True), (2, False), (3, True), (None, None)):
        asked = []
        got = winenv.binds_audited(lambda sub, info=info, asked=asked:
                                   (asked.append(sub), info)[1])
        check(f"AuditingInformation {info} -> {want}", got is want, f"({got})")
        check("about the subcategory behind event 5158",
              asked == [winenv.FILTERING_PLATFORM_CONNECTION], f"({asked})")
    check("the real question answers without raising, here",
          winenv.binds_audited() in (True, False, None))


# -- the real system, loopback only ------------------------------------------------- #
def _real(text, protocols=("TCP",), families=(4,)):
    try:
        return pc.check(pc.parse(text), protocols, families)
    except sk.Unreadable as exc:            # no socket table here (psutil missing)
        pytest.skip(f"no socket table on this machine: {exc}")


def test_a_port_this_test_holds_is_in_use_by_this_process():
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        port = held.getsockname()[1]
        result = _real(str(port))
    row = result.rows[0]
    check("in use", row.verdict == pc.IN_USE, f"({row})")
    check("by this process", os.getpid() in [pid for pid, _name in row.owners], f"({row.owners})")
    check("and the bind itself was refused", row.code in pc.IN_USE_CODES, f"({row.code})")


def test_a_port_nobody_holds_is_free():
    with socket.socket() as gone:
        gone.bind(("127.0.0.1", 0))
        port = gone.getsockname()[1]
    row = _real(str(port)).rows[0]
    check("free", (row.verdict, row.code) == (pc.FREE, 0), f"({row})")


AUDIT = """
import json, socket, sys
sys.path.insert(0, {root!r})
events = []
sys.addaudithook(lambda event, args: events.append([event, repr(args[1:])[:120]])
                 if event.startswith("socket.") else None)
from beantester.nettools import portcheck as pc
checked, unavailable = [], []
try:
    result = pc.check(pc.parse("47001, 47002"), pc.PROTOCOLS, pc.FAMILIES)
    checked, unavailable = list(result.families), list(result.unavailable)
except Exception as exc:
    print("CHECK_FAILED " + repr(exc))
run = list(events)
# The canary: shown a way out, the same hook must report it. A UDP connect sends
# nothing - it only records a default peer.
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as way_out:
    way_out.connect(("127.0.0.1", 9))
print("BEGIN_JSON" + json.dumps({{"run": run, "all": events, "checked": checked,
                                 "unavailable": unavailable}}))
"""


def test_a_port_check_only_creates_and_binds_sockets_on_loopback():
    """Behind the Tools tab's quiet exception for this module: the audit hook sees every
    socket the check makes. Only `socket.__new__` and `socket.bind`, every bind on a
    loopback address - no connect, no sendto, nothing that listens on a network."""
    proc = subprocess.run([sys.executable, "-c", AUDIT.format(root=ROOT)], cwd=ROOT,
                          capture_output=True, text=True, timeout=120, check=False)
    out = proc.stdout
    assert "BEGIN_JSON" in out, (out[-800:], proc.stderr[-800:])
    if "CHECK_FAILED" in out:
        pytest.skip(out.split("CHECK_FAILED", 1)[1].split("\n")[0])
    seen = json.loads(out.split("BEGIN_JSON", 1)[1])
    kinds = sorted({event for event, _args in seen["run"]})
    check("the check raised only socket creation and bind",
          kinds == ["socket.__new__", "socket.bind"], f"({kinds})")
    binds = [args for event, args in seen["run"] if event == "socket.bind"]
    checked, missing = len(seen["checked"]), len(seen["unavailable"])
    check("an IP version was checked at all, or this proves nothing", checked > 0,
          f"({seen['unavailable']} unavailable)")
    # A version this machine has no loopback for (an IPv6-less container) ends at its
    # first attempt, which may or may not reach bind. Counted, not skipped: the IPv4
    # half still has to prove itself there.
    per_version = 2 * len(pc.PROTOCOLS)             # two ports, TCP and UDP
    check("one bind per port, protocol and checked version",
          per_version * checked <= len(binds) <= per_version * checked + missing,
          f"({len(binds)} binds, {checked} checked, {missing} unavailable)")
    check("every bind on a loopback address",
          all("'127.0.0.1'" in args or "'::1'" in args for args in binds), f"({binds})")
    check("the hook reports a way out when shown one",
          any(event == "socket.connect" for event, _args in seen["all"]), f"({seen['all'][-3:]})")


def test_the_probe_closes_every_socket_it_makes(monkeypatch):
    made = []

    class Fake:
        def __init__(self, *args):
            self.closed = False
            made.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.closed = True

        def bind(self, address):
            if address[1] == 2:
                raise OSError(errno.EADDRINUSE, "held on purpose")

    monkeypatch.setattr(pc.socket, "socket", Fake)
    check("a bind that worked", pc.probe("TCP", 4, 1) == 0, "")
    check("a bind that was refused", pc.probe("UDP", 6, 2) == errno.EADDRINUSE, "")
    check("both sockets closed", [s.closed for s in made] == [True, True], f"({made})")
