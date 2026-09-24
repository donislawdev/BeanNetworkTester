"""The socket table's logic (``nettools/sockets.py``): naming, keys, search, order.

No window and no system: ``portmap.socket_rows`` and ``portmap.process_names`` are
stood in for, so the rows are the same on every machine. What the system really
returns is ``tests/test_socket_rows.py``'s business.
"""
import json
import os

import pytest

from beantester import portmap
from beantester.i18n import T
from beantester.nettools import sockets as sk
from beantester.portmap import SocketRow
from fakes import LANG_DIR, LANGS, check

ROWS = [
    SocketRow("TCP", 4, "0.0.0.0", 445, "", None, "LISTEN", 4),
    SocketRow("TCP", 4, "10.0.0.2", 50000, "93.184.216.34", 443, "ESTABLISHED", 1234),
    SocketRow("TCP", 4, "127.0.0.1", 13882, "127.0.0.1", 5000, "TIME_WAIT", 0),
    SocketRow("TCP", 6, "::", 135, "", None, "LISTEN", 900),
    SocketRow("UDP", 4, "0.0.0.0", 5353, "", None, "", 100),
    SocketRow("UDP", 4, "0.0.0.0", 5353, "", None, "", 100),       # the same, twice
    SocketRow("UDP", 6, "fe80::1%12", 546, "", None, "", 300),
    SocketRow("TCP", 4, "10.0.0.2", 8080, "", None, "LISTEN", None),  # another account's
]
NAMES = {0: "[System Process]", 4: "System", 1234: "chrome.exe", 900: "svchost.exe",
         100: "mdns.exe", 300: "dhcp.exe"}


@pytest.fixture
def machine(monkeypatch):
    read = []

    def socket_rows():
        read.append("table")
        return list(ROWS), ["udp/v6"]

    def process_names():
        read.append("names")
        return dict(NAMES)

    monkeypatch.setattr(portmap, "socket_rows", socket_rows)
    monkeypatch.setattr(portmap, "process_names", process_names)
    return read


def test_a_read_names_each_row_after_the_table_and_keeps_what_failed(machine):
    snap = sk.read()
    check("the table first, the names after it", machine == ["table", "names"], f"({machine})")
    check("every row", len(snap.sockets) == len(ROWS), f"({len(snap.sockets)})")
    check("what failed is carried", snap.failed == ("udp/v6",), f"({snap.failed})")
    by_pid = {s.pid: s.proc for s in snap.sockets}
    check("rows are named by their PID", by_pid[1234] == "chrome.exe" and by_pid[4] == "System")
    check("PID 0 is nobody's, not the snapshot's '[System Process]'", by_pid[0] == "",
          f"({by_pid[0]!r})")
    check("an owner the system would not say has no name", by_pid[None] == "")
    check("and is counted, so the panel can say why", sk.without_owner(snap) == 1)


@pytest.mark.parametrize("reason", sorted(sk.UNREADABLE_KEYS))
def test_a_table_nobody_may_read_becomes_a_reason_the_window_can_say(monkeypatch, reason):
    def refused():
        raise portmap.SocketTableUnavailable(reason, "the program's own words")

    monkeypatch.setattr(portmap, "socket_rows", refused)
    with pytest.raises(sk.Unreadable) as caught:
        sk.read()
    key = caught.value.user_key
    check("a key the window can say", key == sk.UNREADABLE_KEYS[reason], f"({key})")
    check("and the language files know it", T(key) != key, f"({key})")
    check("the program's words kept for the crash log",
          str(caught.value) == "the program's own words", f"({caught.value})")


def test_a_missing_psutil_says_how_to_get_it_in_every_language():
    """Only a run from source can lack psutil (the exe carries it), and whoever runs
    it needs the command, not just the reason. The command reads the same in every
    language, so every language file is held to it."""
    key = sk.UNREADABLE_KEYS["missing"]
    for code in LANGS:
        with open(os.path.join(LANG_DIR, f"{code}.json"), encoding="utf-8") as f:
            text = json.load(f).get(key, "")
        check(f"lang/{code}.json names the command", "pip install psutil" in text,
              f"({text})")


def test_two_identical_sockets_are_two_rows_with_two_keys(machine):
    """One process can hold two UDP sockets on the same address and port. The table
    finds rows by key through a dict, so the same key would send a click on one to
    the other."""
    keys = [s.key for s in sk.read().sockets]
    check("no key twice", len(keys) == len(set(keys)), f"({keys})")
    twins = [s for s in sk.read().sockets if s.local_port == 5353]
    check("the twins are both there", len(twins) == 2 and twins[0].key != twins[1].key)
    check("and a read gives the same keys again", keys == [s.key for s in sk.read().sockets])


@pytest.mark.parametrize("query, expected", [
    ("", {445, 50000, 13882, 135, 5353, 546, 8080}),
    ("chrome", {50000}),                      # plain text: every column
    ("time_wait", {13882}),
    ("proc:svchost", {135}),
    ("proc:1234", {50000}),                   # the process kind reads a PID too
    ("pid:>1000", {50000}),
    ("proto:udp", {5353, 546}),
    ("state:listen", {445, 135, 8080}),
    ("state:!listen", {50000, 13882, 5353, 546}),
    ("ip:93.184.216.0/24", {50000}),          # ip: and port: are the OTHER end
    ("port:443", {50000}),
    ("lip:127.0.0.1", {13882}),               # lip: and lport: are this computer
    ("lip:fe80::/10", {546}),                 # a zone does not stop a match
    ("lport:5000-9000", {5353, 8080}),
    ("lport:445 proto:tcp", {445}),           # terms are ANDed
    ("lip:10.0.", set()),                     # half-typed: nothing yet, no error
    ("nosuch:thing", set()),                  # an unknown qualifier is plain text
])
def test_the_search_is_the_connection_tables_language_on_these_columns(machine, query, expected):
    kept = {s.local_port for s in sk.view(sk.read(), query)}
    check(f"{query!r}", kept == expected, f"({sorted(kept)})")


def test_a_column_sorts_by_value_with_empty_cells_last_both_ways(machine):
    snap = sk.read()
    ports = [s.local_port for s in sk.view(snap, "", "local_port")]
    check("ports by number", ports == sorted(ports), f"({ports})")
    remote = [s.remote_ip for s in sk.view(snap, "", "remote_ip")]
    check("addresses by number, not by text: 93.x before 127.x",
          remote[:2] == ["93.184.216.34", "127.0.0.1"], f"({remote})")
    check("and the rows with no remote end last", set(remote[2:]) == {""}, f"({remote})")
    for reverse in (False, True):
        pids = [s.pid for s in sk.view(snap, "", "pid", reverse)]
        check(f"an unknown PID last (reverse={reverse})", pids[-1] is None, f"({pids})")
        states = [s.state for s in sk.view(snap, "", "state", reverse)]
        check(f"UDP's empty state last (reverse={reverse})", states[-1] == "", f"({states})")
    local = [s.local_ip for s in sk.view(snap, "", "local_ip")]
    check("IPv4 before IPv6", local.index("::") > local.index("127.0.0.1"), f"({local})")
    check("an unknown column falls back to the default",
          [s.local_port for s in sk.view(snap, "", "no-such-column")] == sorted(ports))


def test_the_workers_job_reads_only_when_it_has_no_snapshot(machine):
    first = sk.table(None, "state:listen", "local_port", False)
    check("a read, then the view", machine == ["table", "names"]
          and [s.local_port for s in first.rows] == [135, 445, 8080], f"({first.rows})")
    again = sk.table(first.snapshot, "proto:udp", "local_port", True)
    check("a view of the same read asks nothing", machine == ["table", "names"])
    check("and says what it answers", (again.query, again.sort) == ("proto:udp", ("local_port", True))
          and [s.local_port for s in again.rows] == [5353, 5353, 546], f"({again.rows})")
    check("the newest view is the newest", again.made_at >= first.made_at)
