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


def test_the_note_on_sockets_without_a_program_says_who_may_see_it_here(monkeypatch):
    """Windows names the owner to an administrator; Linux names the program only to
    root (Ubuntu 26.04: 14 of 14 without one as a user, none under sudo), and the ones
    still without one under sudo are held from outside the system (WSL, 4 of 14)."""
    from beantester import paths
    monkeypatch.setattr(paths, "running_as_root", lambda: False)
    check("Windows: the administrator", sk.no_owner_note("win32") == sk.NO_OWNER)
    check("Linux, a user: root names them", sk.no_owner_note("linux") == sk.NO_OWNER_LINUX)
    monkeypatch.setattr(paths, "running_as_root", lambda: True)
    check("Linux, root: held from outside", sk.no_owner_note("linux") == sk.NO_OWNER_ROOT)
    for code in LANGS:
        with open(os.path.join(LANG_DIR, f"{code}.json"), encoding="utf-8") as f:
            texts = json.load(f)
        for key in (sk.NO_OWNER, sk.NO_OWNER_LINUX, sk.NO_OWNER_ROOT):
            check(f"lang/{code}.json: {key} says how many", "{count}" in texts.get(key, ""))
        check(f"lang/{code}.json: a user is told to use sudo", "sudo" in texts[sk.NO_OWNER_LINUX])
        check(f"lang/{code}.json: root is not", "sudo" not in texts[sk.NO_OWNER_ROOT])


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
    check("the newest view is the newest", again.made > first.made)


def test_a_clock_set_back_does_not_bring_an_older_view_back(machine, monkeypatch):
    """External review, P3-36: the newest view was the one with the latest
    ``time.time()``, so a clock set back between two views (NTP, a resumed
    virtual machine) put the OLDER one back on screen."""
    import itertools
    clock = itertools.count(2_000_000_000.0, -1_000_000.0)    # going back, every call
    monkeypatch.setattr(sk.time, "time", lambda: next(clock))
    first = sk.table(None, "", "local_port", False)
    again = sk.table(first.snapshot, "proto:udp", "local_port", False)
    check("the view made second is the newest, whatever the clock said",
          max((again, first), key=lambda v: v.made) is again)


# -- a read that follows another: what changed, and whose names are kept ------------- #
NEW_ROW = SocketRow("TCP", 4, "10.0.0.2", 50007, "198.51.100.7", 443, "ESTABLISHED", 1234)


class World:
    """The system as a test changes it between two reads, and a clock it moves."""

    def __init__(self):
        self.rows, self.failed, self.names = list(ROWS), [], dict(NAMES)
        self.asked = 0                      # process snapshots taken
        self.wall, self.monotonic = 1_000.0, 50.0

    def later(self, seconds):
        self.wall += seconds
        self.monotonic += seconds

    def drop(self, port):
        self.rows = [row for row in self.rows if row.local_port != port]


@pytest.fixture
def world(monkeypatch):
    w = World()

    def process_names():
        w.asked += 1
        return dict(w.names)

    monkeypatch.setattr(portmap, "socket_rows", lambda: (list(w.rows), list(w.failed)))
    monkeypatch.setattr(portmap, "process_names", process_names)
    monkeypatch.setattr(sk, "_clock", lambda: (w.wall, w.monotonic))
    return w


def at_port(snapshot, port):
    return [s for s in snapshot.sockets if s.local_port == port]


def test_the_first_read_of_a_window_marks_nothing(world):
    snap = sk.read()
    check("nothing appeared and nothing closed: it was all simply there",
          all(s.change == "" and s.at is None for s in snap.sockets))
    check("and it carries what the next read needs", snap.carry is not None)
    check("the read says when the table was read", snap.read_at == world.wall)


def test_a_socket_that_appears_is_marked_with_its_time_and_only_for_a_while(world):
    first = sk.read()
    world.rows.append(NEW_ROW)
    world.later(2)
    second = sk.read(first)
    (new,) = at_port(second, 50007)
    check("marked", new.change == sk.NEW, f"({new.change!r})")
    check("with the time of the read that found it", new.at == 1_002.0, f"({new.at})")
    check("and nothing else is", all(s.change == "" and s.at is None
                                     for s in second.sockets if s is not new))
    world.later(sk.MARK_S - 0.5)
    (still,) = at_port(sk.read(second), 50007)
    check("still marked just inside the time", still.change == sk.NEW)
    world.later(0.5)
    third = sk.read(sk.read(second))
    (old,) = at_port(third, 50007)
    check("no longer marked at the time", old.change == "", f"({old.change!r})")
    check("but it keeps the time it appeared", old.at == 1_002.0, f"({old.at})")


def test_a_socket_that_closes_stays_listed_for_a_while_marked_closed(world):
    first = sk.read()
    world.drop(50000)
    world.later(2)
    second = sk.read(first)
    gone = second.sockets[-1]
    check("after the open sockets, the one that closed",
          gone.local_port == 50000 and gone.change == sk.CLOSED, f"({gone})")
    check("with the time of the read that missed it", gone.at == 1_002.0, f"({gone.at})")
    check("and what it was: its program and its last state",
          (gone.proc, gone.state) == ("chrome.exe", "ESTABLISHED"))
    check("every open socket is still there, unmarked",
          len(second.sockets) == len(ROWS)
          and all(s.change == "" for s in second.sockets[:-1]))
    world.later(sk.MARK_S - 0.5)
    third = sk.read(second)
    (kept,) = at_port(third, 50000)
    check("still listed just inside the time, its time not moved",
          kept.change == sk.CLOSED and kept.at == 1_002.0, f"({kept})")
    world.later(0.5)
    check("gone at the time", at_port(sk.read(third), 50000) == [])


def test_a_closed_socket_without_a_program_is_not_counted_as_one_without(world):
    first = sk.read()
    check("one socket without a program", sk.without_owner(first) == 1)
    world.drop(8080)
    world.later(1)
    second = sk.read(first)
    check("it is listed as closed", at_port(second, 8080)[0].change == sk.CLOSED)
    check("and the note counts open sockets only", sk.without_owner(second) == 0)


def test_a_row_that_turns_up_in_time_wait_is_not_a_new_socket(world):
    """A connection that closes leaves a TIME_WAIT row under PID 0 - another key, so
    another row. Marked new, a closed connection would read as an opened one."""
    first = sk.read()
    world.rows.append(SocketRow("TCP", 4, "10.0.0.2", 50009, "198.51.100.7", 443,
                                "TIME_WAIT", 0))
    world.later(1)
    (remnant,) = at_port(sk.read(first), 50009)
    check("not marked", remnant.change == "", f"({remnant.change!r})")
    check("but it has the time it turned up", remnant.at == 1_001.0, f"({remnant.at})")


def udp4(row):
    return (row.proto, row.family) == ("UDP", 4)


def test_a_table_that_did_not_answer_closes_nothing_and_its_return_is_not_news(world):
    first = sk.read()
    world.rows.append(SocketRow("UDP", 4, "0.0.0.0", 9999, "", None, "", 100))
    world.later(1)
    second = sk.read(first)               # 9999 appears before its table fails
    check("9999 appeared", at_port(second, 9999)[0].at == 1_001.0)
    world.failed = ["udp/v4"]
    world.rows = [row for row in world.rows if not udp4(row)] + [NEW_ROW]
    world.drop(445)                       # this one really closed, in a table that answered
    world.later(sk.MARK_S)                # longer than 9999 stays marked
    third = sk.read(second)
    closed_at = 1_001.0 + sk.MARK_S
    check("what the missing table held is not called closed",
          not [s for s in third.sockets if udp4(s)], f"({third.sockets})")
    check("what closed in a table that answered is said at once",
          [(s.change, s.at) for s in at_port(third, 445)] == [(sk.CLOSED, closed_at)])
    check("what appeared in a table that answered is marked",
          at_port(third, 50007)[0].change == sk.NEW)
    world.failed = []
    world.rows = [row for row in ROWS if row.local_port != 445] + [
        NEW_ROW, SocketRow("UDP", 4, "0.0.0.0", 9999, "", None, "", 100)]
    world.later(2)
    fourth = sk.read(third)
    back = {s.local_port: s.at for s in fourth.sockets if udp4(s)}
    check("the table that came back brings no news",
          all(s.change == "" for s in fourth.sockets if udp4(s)), f"({back})")
    check("and its sockets keep when they appeared", back == {5353: None, 9999: 1_001.0},
          f"({back})")
    check("445 was said once, and stays said", [s.at for s in at_port(fourth, 445)] == [closed_at])


def test_a_table_that_keeps_failing_lets_the_others_be_read_as_ever(world):
    """IPv6 turned off: the same table fails at every read, for hours. The others must
    still say what closed, and the reads must not remember more and more."""
    first = sk.read()
    world.failed = ["udp/v6"]
    stays = [row for row in ROWS if (row.proto, row.family) != ("UDP", 6)]
    snap, told = first, []
    for n in range(50):
        world.rows = stays + [NEW_ROW._replace(local_port=40_000 + n)]
        world.later(1)
        snap = sk.read(snap)
        told += [s.local_port for s in snap.sockets
                 if s.change == sk.CLOSED and s.at == world.wall]
    check("each connection that closed is said, at the read after it",
          told == list(range(40_000, 40_049)), f"({told[:5]}...)")
    check("the missing table's socket is remembered and not called closed",
          546 in {s.local_port for s in snap.carry.last.values()}
          and not at_port(snap, 546), f"({at_port(snap, 546)})")
    check("what the reads remember: what is open now and that one, no more",
          len(snap.carry.last) == len(stays) + 2, f"({len(snap.carry.last)})")
    check("and appearance times only for those",
          snap.carry.seen.keys() <= snap.carry.last.keys(), f"({len(snap.carry.seen)})")


def test_a_socket_that_comes_back_is_one_row_and_new(world):
    first = sk.read()
    world.drop(50000)
    world.later(1)
    second = sk.read(first)
    world.rows = list(ROWS)
    world.later(1)
    third = sk.read(second)
    check("one row, not the closed one beside it",
          [s.change for s in at_port(third, 50000)] == [sk.NEW])
    keys = [s.key for s in third.sockets]
    check("no key twice", len(keys) == len(set(keys)))


BOUND = SocketRow("TCP", 4, "10.0.0.2", 51000, "", None, "CLOSED", 1234)
CONNECTED = SocketRow("TCP", 4, "10.0.0.2", 51000, "198.51.100.7", 443, "ESTABLISHED", 1234)


def test_a_socket_that_gets_its_far_end_did_not_close(world):
    """A program binds a port and then connects: the row without a far end goes and
    one with it appears. Seen on real Tk as "closed" beside "appeared" for the same
    program and port, which is one socket getting on with its life."""
    world.rows.append(BOUND)
    first = sk.read()
    world.rows[-1] = CONNECTED
    world.later(1)
    second = sk.read(first)
    check("one row for the port, the one that is there now, marked new",
          [(s.remote_ip, s.change) for s in at_port(second, 51000)]
          == [("198.51.100.7", sk.NEW)], f"({at_port(second, 51000)})")
    world.rows[-1] = BOUND                # and the other way: the far end let go
    world.later(1)
    third = sk.read(second)
    check("the same when it loses its far end",
          [(s.remote_ip, s.change) for s in at_port(third, 51000)] == [("", sk.NEW)],
          f"({at_port(third, 51000)})")


def test_one_client_leaving_and_another_arriving_are_told_as_that(world):
    """Two rows that both have a far end are two connections of a server's port."""
    world.rows.append(CONNECTED)
    first = sk.read()
    world.rows[-1] = CONNECTED._replace(remote_ip="203.0.113.9")
    world.later(1)
    second = sk.read(first)
    told = sorted((s.remote_ip, s.change) for s in at_port(second, 51000))
    check("one closed, one new", told == [("198.51.100.7", sk.CLOSED),
                                         ("203.0.113.9", sk.NEW)], f"({told})")


@pytest.mark.parametrize("arrival, why", [
    (None, "nothing arrived"),
    (CONNECTED._replace(local_port=51001), "at another port"),
    (CONNECTED._replace(pid=4), "another program's"),
    (CONNECTED._replace(local_ip="127.0.0.1"), "at another address"),
    (CONNECTED._replace(proto="UDP", remote_ip="", remote_port=None, state=""),
     "of another protocol"),
])
def test_a_bound_socket_that_went_closed_unless_it_is_the_one_that_arrived(world, arrival, why):
    world.rows.append(BOUND)
    first = sk.read()
    world.rows.pop()
    if arrival is not None:
        world.rows.append(arrival)
    world.later(1)
    second = sk.read(first)
    gone = [s for s in second.sockets if s.change == sk.CLOSED]
    check(f"closed: what arrived was {why}",
          [(s.local_port, s.remote_ip) for s in gone] == [(51000, "")], f"({gone})")


def test_only_so_many_closed_sockets_stay_listed(world, monkeypatch):
    monkeypatch.setattr(sk, "MAX_CLOSED", 3)
    first = sk.read()
    world.rows = []
    world.later(1)
    second = sk.read(first)
    check("the newest three of them", len(second.sockets) == 3
          and all(s.change == sk.CLOSED for s in second.sockets), f"({len(second.sockets)})")


def test_a_clock_set_back_neither_keeps_a_mark_nor_drops_it(world):
    first = sk.read()
    world.rows.append(NEW_ROW)
    world.later(1)
    second = sk.read(first)
    world.wall -= 3600                    # the clock goes back an hour
    world.monotonic += 2                  # two seconds pass
    third = sk.read(second)
    check("still marked two seconds later", at_port(third, 50007)[0].change == sk.NEW)
    world.monotonic += sk.MARK_S
    check("and not after the time, whatever the clock says",
          at_port(sk.read(third), 50007)[0].change == "")


def test_a_read_that_follows_another_keeps_the_names_it_was_given(world):
    """The process snapshot was 71 of a read's 73 ms (measured 2026-11-10), so a
    table that reads itself asks for it only when it has a reason."""
    first = sk.read()
    check("the first read names every process", world.asked == 1)
    second = sk.read(first, fresh_names=False)
    check("the next one asks nobody", world.asked == 1, f"({world.asked})")
    check("and its rows are named all the same",
          at_port(second, 50000)[0].proc == "chrome.exe")
    sk.read(second)
    check("a read somebody asked for names them again", world.asked == 2)

    world.rows.append(SocketRow("UDP", 4, "0.0.0.0", 9999, "", None, "", 4321))
    world.names[4321] = "new.exe"
    third = sk.read(second, fresh_names=False)
    check("a PID never named is a reason", world.asked == 3)
    check("and it is named", at_port(third, 9999)[0].proc == "new.exe")

    world.later(sk.NAMES_EVERY_S - 1)
    fourth = sk.read(third, fresh_names=False)
    check("inside the time the names are trusted", world.asked == 3, f"({world.asked})")
    world.later(1)
    sk.read(fourth, fresh_names=False)
    check("at the time they are asked for again", world.asked == 4, f"({world.asked})")


def test_a_pid_whose_sockets_all_went_is_named_again_when_it_comes_back(world):
    """By then the number may belong to another program."""
    first = sk.read()
    world.drop(50000)                     # the only socket of PID 1234
    second = sk.read(first, fresh_names=False)
    check("a PID leaving is no reason to ask", world.asked == 1)
    world.rows = list(ROWS)
    world.names[1234] = "other.exe"
    third = sk.read(second, fresh_names=False)
    check("it was forgotten, so it is asked for", world.asked == 2, f"({world.asked})")
    check("and has the name it has now", at_port(third, 50000)[0].proc == "other.exe")


def test_a_pid_nobody_can_name_does_not_cost_a_snapshot_at_every_read(world):
    world.rows.append(SocketRow("UDP", 4, "0.0.0.0", 9999, "", None, "", 7777))
    first = sk.read()
    second = sk.read(first, fresh_names=False)
    check("asked once, remembered as nameless", world.asked == 1, f"({world.asked})")
    check("and shown without a name", at_port(second, 9999)[0].proc == "")


def test_a_process_snapshot_that_fails_keeps_the_names_and_asks_again(world):
    first = sk.read()
    world.rows.append(SocketRow("UDP", 4, "0.0.0.0", 9999, "", None, "", 4321))
    names, world.names = world.names, {}          # the snapshot answers empty
    second = sk.read(first, fresh_names=False)
    check("the names it had are kept", at_port(second, 50000)[0].proc == "chrome.exe")
    check("the new PID has none yet", at_port(second, 9999)[0].proc == "")
    world.names = {**names, 4321: "new.exe"}
    third = sk.read(second, fresh_names=False)
    check("and is asked for at the next read", world.asked == 3, f"({world.asked})")
    check("which names it", at_port(third, 9999)[0].proc == "new.exe")


def test_the_workers_job_hands_the_read_before_it_on(world):
    first = sk.table(None, "", "local_port", False)
    world.rows.append(NEW_ROW)
    world.later(1)
    again = sk.table(None, "", "local_port", False, first.snapshot, False)
    check("so the answer says what changed",
          at_port(again.snapshot, 50007)[0].change == sk.NEW)
    check("and keeps the names", world.asked == 1, f"({world.asked})")


def test_the_change_column_sorts_by_time_with_unchanged_rows_last_both_ways(world):
    first = sk.read()
    world.rows.append(NEW_ROW)
    world.later(1)
    second = sk.read(first)
    world.drop(445)
    world.later(1)
    third = sk.read(second)
    for reverse, expected in ((True, [445, 50007]), (False, [50007, 445])):
        rows = sk.view(third, "", "change", reverse)
        check(f"by the time of the change (reverse={reverse})",
              [s.local_port for s in rows[:2]] == expected,
              f"({[s.local_port for s in rows[:2]]})")
        check(f"the rows that did not change last (reverse={reverse})",
              all(s.at is None for s in rows[2:]))


@pytest.mark.parametrize("chosen, last_ms, failures, expected", [
    (2, 0, 0, 2000),            # the pace chosen
    (1, 3, 0, 1000),            # an ordinary machine's read changes nothing
    (2, 100, 0, 2000),          # a twentieth exactly: still the pace chosen
    (2, 101, 0, 2020),          # more than a twentieth: stretched
    (1, 700, 0, 14000),         # a hundred thousand sockets
    (2, 3, 1, 4000),            # each failure in a row doubles the wait
    (2, 3, 2, 8000),
    (2, 3, 4, 30000),           # up to the cap
    (2, 3, 12, 30000),
    (1, 2000, 3, 40000),        # never shorter than without the failures
])
def test_the_time_between_two_reads(chosen, last_ms, failures, expected):
    got = sk.read_every_ms(chosen, last_ms, failures)
    check(f"{chosen} s chosen, a read of {last_ms} ms, {failures} failures", got == expected,
          f"({got})")


def test_the_paces_offered_include_the_one_the_window_starts_with():
    check("the default is one of the choices", sk.DEFAULT_EVERY_S in sk.EVERY_S)
    check("a mark outlasts the slowest pace, or a change could be missed",
          sk.MARK_S > max(sk.EVERY_S))
