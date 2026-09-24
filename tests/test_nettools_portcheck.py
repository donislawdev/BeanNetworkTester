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


def sock(port, proto="TCP", family=4, state="LISTEN", pid=1234, proc="server.exe"):
    return sk.Socket(f"{proto}|{port}|{family}|{state}|{pid}", proto, family,
                     "127.0.0.1" if family == 4 else "::1", port, "", None, state, pid, proc)


def run(text, answers=None, rows=(), protocols=pc.PROTOCOLS, families=pc.FAMILIES,
        calls=None):
    """``check`` with a stand-in bind (``answers``: (proto, family, port) -> code, else 0)."""
    calls = [] if calls is None else calls

    def bind(proto, family, port):
        calls.append(("bind", proto, family, port))
        return (answers or {}).get((proto, family, port), 0)

    def read():
        calls.append(("read",))
        return sk.Snapshot(tuple(rows), (), 0.0, 0)

    return pc.check(pc.parse(text), protocols, families, bind=bind, read=read)


def verdicts(result):
    return {(r.port, r.proto, r.family): r.verdict for r in result.rows}


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
    check("exactly the limit is taken", len(pc.ports(pc.parse("1-1000"))[0]) == pc.MAX_PORTS, "")
    for text, key, args in (("0", "tools.portcheck.error_zero", {}),
                            ("re:^$", "tools.portcheck.error_none", {}),
                            ("1-1001", "tools.portcheck.error_too_many",
                             {"count": 1001, "limit": pc.MAX_PORTS}),
                            ("!80", "tools.portcheck.error_too_many",
                             {"count": 65534, "limit": pc.MAX_PORTS})):
        with pytest.raises(pc.Refused) as caught:
            pc.ports(pc.parse(text))
        check(f"{text!r} is refused with its reason",
              (caught.value.user_key, caught.value.user_args) == (key, args),
              f"({caught.value.user_key}, {caught.value.user_args})")
    with pytest.raises(ValueError):
        pc.parse("9100-9000")          # the port language's own message, already translated


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
