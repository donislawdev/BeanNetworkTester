"""Targeting resolves against the live socket-event map (chunk 2c).

Before 2c, ProcessTargeting resolved against the polling PortTable, so a new
connection was targeted only at the next poll (up to a refresh interval late, and
never at all if it opened and closed in between). Now the engine points targeting
at the SocketWatcher when a session has one, so a connection is targeted the
instant its SOCKET event arrives. These tests prove the table swap (unit), the
end-to-end resolution through a watcher (integration), and the engine binding -
all without WinDivert.
"""
import contextlib
import threading
import time

import bean_network_tester as bnt
from beantester.engine import BeanEngine
from beantester.socketwatch import CONNECT, SocketEvent, SocketWatcher
from beantester.targeting import ProcessTargeting
from beantester.target_resolver import TargetResolver
from fakes import FakeDivert, check


def _wait(pred, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return False


def ev(kind, pid, port):
    return SocketEvent(kind, pid, port)


class _Names:
    def __init__(self, names):
        self._names = dict(names)

    def name_of(self, pid, cheap=False):
        return self._names.get(pid, "")

    def ancestors(self, pid, depth=8):
        return []


class _Source:
    def __init__(self, events):
        self._events = list(events)
        self._closed = threading.Event()

    def __iter__(self):
        for e in self._events:
            if self._closed.is_set():
                return
            yield e
        self._closed.wait()

    def close(self):
        self._closed.set()


class _FakePorts:
    """portmap.PortTable surface the engine touches (bootstrap + delegation)."""

    def __init__(self, ports):
        self._ports = dict(ports)

    def refresh(self, now=None, force=False):
        return True

    def refresh_if_stale(self, now=None, miss=False):
        return True

    def snapshot(self):
        return dict(self._ports)

    def collected(self):
        # see the same method on test_socketwatch_wiring._FakePorts
        return dict(self._ports), time.monotonic()

    def warm_names(self):
        pass

    def name_of(self, pid, cheap=False):
        return {100: "chrome.exe"}.get(pid, "")

    def ancestors(self, pid, depth=8):
        return []

    def process_for_port(self, port, now=None, allow_refresh=True):
        return self.name_of(self._ports.get(port))

    def pid_for(self, port):
        return self._ports.get(port)


# -- unit: the table swap ----------------------------------------------------- #
def test_set_table_swaps_which_map_targeting_resolves_against():
    class _T:
        def __init__(self, ports, names):
            self.ports, self._n = ports, names

        def refresh(self, now=None, force=False):
            return True

        def snapshot(self):
            return dict(self.ports)

        def name_of(self, pid, cheap=False):
            return self._n.get(pid, "")

        def ancestors(self, pid, depth=8):
            return []

    a = _T({5000: 1}, {1: "chrome.exe"})
    b = _T({6000: 2}, {2: "chrome.exe"})
    t = ProcessTargeting(bnt.parse_target("chrome"), table=a)
    t.refresh()
    check("resolves against table A", t.ports() == {5000}, f"({t.ports()})")
    t.set_table(b)
    t.refresh()
    check("after set_table it resolves against table B", t.ports() == {6000},
          f"({t.ports()})")


# -- integration: targeting via a live watcher -------------------------------- #
def test_a_connection_is_targeted_the_moment_its_socket_event_arrives():
    """The whole point of chunk 2: no poll, no race. A CONNECT event for a matching
    process puts its local port in scope, driven by the event, not a snapshot."""
    names = _Names({100: "chrome.exe"})
    source = _Source([ev(CONNECT, 100, 5000)])
    watcher = SocketWatcher(names=names, source_factory=lambda: source)
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=watcher)

    resolver = TargetResolver(interval=5.0, min_interval=0.02)
    watcher.start()
    resolver.retarget(targeting)
    resolver.start()
    try:
        # asking about the port both drives the miss-wake and is the assertion
        check("chrome's socket is targeted from its event",
              _wait(lambda: 5000 in targeting))
        check("an unrelated port is not targeted", 9999 not in targeting)
    finally:
        resolver.stop()
        watcher.stop()


def test_owner_targeted_reads_the_live_map_without_waiting_for_a_rebuild():
    """`__contains__` answers from a set rebuilt on the resolver's thread, so the
    FIRST packet of a fresh connection is judged before any rebuild it triggers.
    Measured end to end 2026-07-28: 20 fresh connections against a process target
    with `--syn-drop 100` gave 20 established connections and `drop_syn` 0.

    `owner_targeted` is the one path that consults the live map instead, so it answers
    correctly with NO refresh having happened - which is what this asserts by
    never starting a resolver.

    Read it as the NAKED behaviour of these two methods: no resolver, and no
    listener wired either. In a real session the live map now also PUSHES
    (`note_socket`, wired by the engine), so a brand-new socket does not wait for
    the rebuild this test performs by hand - see
    `test_a_new_socket_of_a_targeted_process_is_in_scope_from_its_event`.
    """
    names = _Names({100: "chrome.exe", 200: "svchost.exe"})
    watcher = SocketWatcher(names=names,
                            source_factory=lambda: _Source([ev(CONNECT, 100, 5000),
                                                            ev(CONNECT, 200, 6000)]))
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=watcher)
    watcher.start()
    try:
        _wait(lambda: watcher.pid_for(5000) == 100)
        # no resolver: the rebuilt port set is still empty, as it is for every
        # brand-new socket at the moment its SYN is judged
        check("the rebuilt set knows nothing yet", 5000 not in targeting)
        check("...and owner_targeted cannot help until a rebuild names the pid",
              targeting.owner_targeted(5000) is False)

        targeting.refresh()          # what the resolver does on the miss above
        check("after the rebuild the fresh socket is covered",
              targeting.owner_targeted(5000) is True)
        check("another process's socket is not",
              targeting.owner_targeted(6000) is False)
    finally:
        watcher.stop()


def test_owner_targeted_survives_a_table_that_cannot_answer():
    """`set_table` takes anything with the read surface, and `pid_for` only became
    part of that contract with `owner_targeted`. This runs on the CAPTURE THREAD, so a
    table without it has to answer False - an AttributeError there would kill the
    capture thread and fail the session open (convention 20)."""
    class _NoPidFor:
        def snapshot(self):
            return {}

    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=_NoPidFor())
    targeting._pids = frozenset({100})
    check("a table without pid_for answers False instead of raising",
          targeting.owner_targeted(5000) is False)


def test_owner_targeted_says_no_for_portless_traffic():
    """ICMP reaches this now, and it did not before UDP was covered.

    Step 1 asks for a TCP SYN or for anything that is NOT TCP, and ICMP is not
    TCP - so every ping packet calls ``owner_targeted(None)`` on the CAPTURE
    THREAD. Previously only a TCP SYN could get here, so the ``port is None``
    guard sat on a path nothing ever took.

    It needs its own guard against the REAL class: mutating that line to
    ``return True`` was caught by NOTHING (checked 2026-07-28), because the core
    test drives a ``_FakePorts`` double with its own implementation. A portless
    packet answering True would drag every ping on the machine into scope while a
    process target is set - the exact false positive targeting exists to avoid.
    """
    class _Table:
        def snapshot(self):
            return {5000: 100}

        def pid_for(self, port):
            return {5000: 100}.get(port)

    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=_Table())
    targeting._pids = frozenset({100})
    check("a port we have is still covered", targeting.owner_targeted(5000) is True)
    check("portless traffic answers False, it does not fall through",
          targeting.owner_targeted(None) is False)


def test_a_recycled_pid_is_in_scope_until_the_next_rebuild_and_no_longer():
    """The recycled-PID window, pinned so its BOUND cannot drift unnoticed.

    ``owner_targeted`` trusts the pid the live map reports without verifying that
    it is still the same process - verifying means ``create_time()`` in the packet
    path, which convention 20 forbids. So between a target exiting and the next
    rebuild, a socket Windows hands that pid number is, as far as targeting is
    concerned, the target's.

    Until now that was a docstring claim and nothing more ("nieodtworzone" in the
    handoff). MEASURED against the real socket table 2026-07-28, seven rounds per
    transport: a dead process leaves ``_pids`` after a median of **309 ms** (TCP,
    271-327) and **315 ms** (UDP, 290-325) - the 0.30 s routine tick, with a live
    session's constant misses only shortening it. TIME_WAIT does NOT stretch it,
    which was worth checking rather than assuming, since a TCP socket can outlive
    its owner.

    This test owns both halves: the false positive is REAL (or the docs promise a
    hazard that does not exist), and it ENDS at the next rebuild (or the bound is
    fiction). Add identity verification one day and the first half fails, which is
    the intended way to be forced back to these docs.
    """
    class _Table:
        """Port 5000 belongs to chrome; after the swap, pid 100 is somebody else."""

        def __init__(self):
            self.ports = {5000: 100}
            self.names = {100: "chrome.exe"}

        def refresh(self, now=None, force=False):
            return True

        def snapshot(self):
            return dict(self.ports)

        def name_of(self, pid, cheap=False):
            return self.names.get(pid, "")

        def ancestors(self, pid, depth=8):
            return []

        def pid_for(self, port):
            return self.ports.get(port)

    table = _Table()
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.refresh()
    check("the target resolved", targeting.pids() == {100}, sorted(targeting.pids()))

    # chrome exits; Windows hands pid 100 to an unrelated process, which opens a
    # socket of its own. Nothing has rebuilt yet - this is the window.
    table.ports = {7000: 100}
    table.names = {100: "innocent.exe"}
    check("inside the window, a stranger's socket IS pulled into scope",
          targeting.owner_targeted(7000) is True)

    targeting.refresh()          # what the resolver does at its next tick
    check("the rebuild names the pid and drops it", targeting.pids() == set(),
          sorted(targeting.pids()))
    check("after the rebuild the stranger is out of scope again",
          targeting.owner_targeted(7000) is False)


# -- what the live map TELLS targeting, rather than what targeting polls ------- #
class _EventTable:
    """A socket table whose contents a test can change under the code."""

    def __init__(self, ports=None, names=None):
        self.ports = dict(ports or {})
        self.names = dict(names or {})
        self.name_calls = []
        self.refreshes = 0

    def refresh(self, now=None, force=False):
        self.refreshes += 1
        return True

    def snapshot(self):
        return dict(self.ports)

    def name_of(self, pid, cheap=False):
        self.name_calls.append(pid)
        return self.names.get(pid, "")

    def ancestors(self, pid, depth=8):
        return []

    def pid_for(self, port):
        return self.ports.get(port)


def test_a_new_socket_of_a_targeted_process_is_in_scope_from_its_event():
    """The reported case: connections that come and go faster than a rebuild.

    ``owner_targeted`` covers the SYN of such a flow, but only when the socket
    event won its 0.02 ms head start - and when it loses, nothing asks again,
    because ordinary TCP data never consults the live map (a measured decision).
    The flow then stayed unimpaired until the next rebuild, up to 0.30 s away,
    which for a browser's short connection means unimpaired for its whole life.
    """
    table = _EventTable(ports={5000: 100}, names={100: "chrome.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.refresh()
    check("the process is targeted", targeting.pids() == {100})

    # a second socket of the SAME process, announced by the live map. No rebuild.
    table.ports[5001] = 100
    before = targeting.refreshes
    targeting.note_socket(5001, 100)
    check("the new socket is in scope immediately", 5001 in targeting)
    check("...without a rebuild having run", targeting.refreshes == before,
          f"({targeting.refreshes} vs {before})")


def test_a_socket_of_an_unrelated_process_is_not_pulled_in_by_its_event():
    """The same path must not become a way in for everybody else's traffic."""
    table = _EventTable(ports={5000: 100}, names={100: "chrome.exe", 200: "svchost.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.refresh()
    table.ports[6000] = 200
    targeting.note_socket(6000, 200)
    check("an unrelated process's socket stays out of scope", 6000 not in targeting)
    check("and it is queued for the resolver to judge, not judged here",
          targeting._pending_pids == frozenset({200}), f"({targeting._pending_pids})")


def test_a_brand_new_process_is_adopted_from_its_first_socket_event():
    """MEASURED 2026-08-04, before this existed: 12 fresh processes each opening
    one short connection against a name target, and **4 of 12 were never in scope
    at all** - the process appeared and finished between two rebuilds. Judging one
    pid costs a name lookup, so it does not need the rebuild's rate limit.
    """
    table = _EventTable(names={100: "chrome.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.refresh()
    check("nothing is targeted yet", targeting.pids() == set())

    # a process appears and connects - this is all the live map knows
    table.ports[5000] = 100
    targeting.note_socket(5000, 100)
    check("the packet path cannot know yet", 5000 not in targeting)

    adopted = targeting.adopt_new_pids()          # what the resolver does on the wake
    check("the resolver adopts it", adopted is True)
    check("the pid is targeted", targeting.pids() == {100}, f"({targeting.pids()})")
    check("and its socket is in scope", 5000 in targeting)
    check("its name reaches the description too", "chrome.exe" in targeting.describe(),
          f"({targeting.describe()})")


def test_the_resolver_adopts_a_new_pid_without_waiting_for_its_floor():
    """The wiring, not just the method: the resolver has to drain pending pids
    BEFORE its rate limit, or the whole point is lost.

    That floor exists for PACKET misses, which arrive continuously - every packet
    of every other application is one. A pid the live map has never seen arrives
    once per new process and costs one name lookup, so it must not queue behind
    them. The floor is pinned shut here (``_last_rebuild`` set to now, both
    intervals 60 s) so the routine rebuild cannot be what does the work.
    """
    table = _EventTable(names={100: "chrome.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    resolver = TargetResolver(interval=60.0, min_interval=60.0)
    resolver._last_rebuild = time.monotonic()
    resolver.retarget(targeting)
    resolver.start()
    try:
        table.ports[5000] = 100          # a process appears and connects
        targeting.note_socket(5000, 100)
        check("the resolver adopted it without a rebuild being due",
              _wait(lambda: 5000 in targeting), f"({sorted(targeting.ports())})")
        check("and no routine rebuild ran", targeting.refreshes == 0,
              f"({targeting.refreshes})")
    finally:
        resolver.stop()


def test_a_pid_that_does_not_match_is_judged_once_not_once_per_socket():
    """Every socket event on the machine reaches this path, and most of them belong
    to processes we will never target. Re-running the matcher for each would put
    the whole machine's socket churn on the resolver thread."""
    table = _EventTable(ports={6000: 200}, names={200: "svchost.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.note_socket(6000, 200)
    targeting.adopt_new_pids()
    calls = list(table.name_calls)
    for port in (6001, 6002, 6003):
        targeting.note_socket(port, 200)
    check("the second and later sockets of a ruled-out pid ask nothing",
          targeting._pending_pids == frozenset(), f"({targeting._pending_pids})")
    targeting.adopt_new_pids()
    check("...and no further name lookup happens",
          table.name_calls == calls, f"({table.name_calls} vs {calls})")


def test_a_pid_whose_name_will_not_resolve_yet_is_asked_again_not_written_off():
    """"I could not tell" is not "not ours", and caching it as one costs the whole
    window this path exists to close.

    A process that has just started does not always resolve its name on the first
    ask. Writing it off would ignore every later socket it opens until the next full
    rebuild - i.e. exactly the delay a fresh process was meant to stop paying.
    """
    table = _EventTable(ports={5000: 100}, names={})       # no name yet
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.note_socket(5000, 100)
    targeting.adopt_new_pids()
    check("a nameless pid is not written off", targeting._not_ours == frozenset(),
          f"({targeting._not_ours})")

    table.names[100] = "chrome.exe"                        # the name resolves now
    targeting.note_socket(5001, 100)
    check("its next socket asks again", targeting._pending_pids == frozenset({100}),
          f"({targeting._pending_pids})")
    targeting.adopt_new_pids()
    check("and the second ask adopts it", targeting.pids() == {100})

    table.names[200] = "svchost.exe"                       # a pid that DID answer
    targeting.note_socket(6000, 200)
    targeting.adopt_new_pids()
    check("a pid that answered and did not match is still cached",
          targeting._not_ours == frozenset({200}), f"({targeting._not_ours})")


def test_a_rebuild_in_flight_does_not_lose_a_socket_the_event_added():
    """The same rule the socket map lives by, one layer up: an older walk must not
    undo a newer event. A refresh reads the table, spends milliseconds resolving
    names, and then publishes - and a socket announced during that window is NEWER
    than everything the walk saw."""
    table = _EventTable(ports={5000: 100}, names={100: "chrome.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.refresh()

    seen = []

    def name_of(pid, cheap=False):
        # the event lands WHILE the walk is resolving names
        if not seen:
            seen.append(pid)
            targeting.note_socket(5001, 100)
        return {100: "chrome.exe"}.get(pid, "")

    table.name_of = name_of
    targeting.refresh()
    check("the port that arrived mid-walk survives the publish", 5001 in targeting,
          f"({sorted(targeting.ports())})")
    check("and the walk's own result is still there", 5000 in targeting)


def test_a_new_socket_of_the_target_joins_the_port_set_without_copying_it():
    """External review P3-22: every new socket of the target COPIED the whole port
    set, on the watcher thread and holding the GIL - measured 453 us per socket at
    60 000 ports, which halved the packets a second the capture thread could judge
    while a load generator opened 1 000 connections a second, and left the watcher
    behind at 3 000. Added in place it is O(1), and the set staying the SAME object
    is what proves nothing was copied. Adoption adds the same way."""
    table = _EventTable(ports={5000: 100}, names={100: "chrome.exe", 200: "chrome.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.refresh()
    live = targeting._ports

    targeting.note_socket(5001, 100)
    check("the new socket is in scope", 5001 in targeting)
    check("added to the set the packet path reads, not to a copy of it",
          targeting._ports is live)

    table.ports[6000] = 200                   # another process of the target
    targeting.note_socket(6000, 200)
    check("adopted", targeting.adopt_new_pids() is True)
    check("the adopted process's socket is in scope", 6000 in targeting)
    check("adoption adds in place too", targeting._ports is live)


def test_iterating_the_target_survives_a_socket_announced_meanwhile():
    """The watcher adds to the port set IN PLACE (P3-22), so a caller walking the
    target walks a copy: a set that grows under its iterator is a RuntimeError in
    the middle of somebody's report."""
    table = _EventTable(ports={5000: 100, 5001: 100}, names={100: "chrome.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.refresh()
    walked = []
    for port in targeting:
        walked.append(port)
        targeting.note_socket(7000 + len(walked), 100)    # the watcher, mid-walk
    check("the walk saw the set as it was", sorted(walked) == [5000, 5001], f"({walked})")
    check("and the sockets announced meanwhile are in scope",
          {7001, 7002} <= targeting.ports(), f"({sorted(targeting.ports())})")


def test_a_rebuild_never_changes_the_set_a_packet_may_be_holding():
    """The packet path reads the port set without a lock, so a packet can hold the
    set a rebuild is about to replace. A rebuild publishes a NEW set: emptying and
    refilling the old one in place would show that packet an empty target."""
    table = _EventTable(ports={5000: 100}, names={100: "chrome.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.refresh()
    held = targeting._ports                      # what a packet mid-lookup holds
    table.ports = {5001: 100}
    targeting.refresh()
    check("the rebuild published its own set", targeting.ports() == {5001},
          f"({sorted(targeting.ports())})")
    check("and left the one a packet may hold as it was", held == {5000}, f"({held})")


def test_what_a_rebuild_returns_cannot_change_the_target():
    """A rebuild returns nothing (D-46, kept after the review of PR 235). It used to
    return the port set, a frozenset nobody could change. The set is live now
    (P3-22), and handing IT out would let a caller change what the packet path
    impairs. A frozenset copy would restore the old return value at 402 us, in one
    C call holding the GIL, per rebuild at 60 000 ports - for a value no caller in
    the tree reads. ``ports()`` is the copy."""
    table = _EventTable(ports={5000: 100}, names={100: "chrome.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    returned = targeting.refresh()
    with contextlib.suppress(AttributeError):     # None or a frozenset: no add()
        returned.add(9999)                        # what a caller could do with it
    check("changing what a rebuild returned leaves the target as it was",
          targeting.ports() == {5000}, f"({sorted(targeting.ports())})")
    check("and a rebuild returns nothing", returned is None, f"({returned!r})")


def test_a_target_with_no_socket_at_the_walk_is_judged_again_when_it_opens_one():
    """External review P2-10(a). A target that owns no socket when the walk reads
    the table (between two connections) opens one while the walk resolves names.
    Its event puts the port in scope, the publish took it out again - the walk
    never saw that pid - and the pid left the target with nothing to queue it
    back. The connection stayed unimpaired until the next rebuild, 50-300 ms,
    which for a short one is its whole life.

    The walk still keeps no port it cannot vouch for (the recycled-pid bound), but
    it does not decide about a pid it never saw either: that pid is queued, the
    resolver's bell rings, and adoption judges it at once. A late owner the walk
    DID see and rule out stays out."""
    table = _EventTable(ports={5000: 100, 5001: 101},
                        names={100: "chrome.exe", 101: "chrome.exe", 900: "other.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.refresh()
    check("both are targeted", targeting.pids() == {100, 101}, f"({targeting.pids()})")
    bells = []
    targeting.on_miss(lambda: bells.append(1))

    # 100 is between two connections; the number 101 now belongs to somebody else
    table.ports = {40000: 900, 5001: 101}
    table.names[101] = "innocent.exe"
    walked = []

    def name_of(pid, cheap=False):
        if not walked:                          # both sockets announced mid-walk
            walked.append(pid)
            table.ports[6000] = 100
            targeting.note_socket(6000, 100)
            targeting.note_socket(7001, 101)
        return table.names.get(pid, "")

    table.name_of = name_of
    targeting.refresh()
    check("the events really landed mid-walk", walked, "(the interposition never ran)")
    check("P2-10: the pid the walk never saw is queued to be judged",
          targeting._pending_pids == frozenset({100}), f"({set(targeting._pending_pids)})")
    check("...and the resolver is rung for it", bells, "(no bell)")
    check("the pid the walk saw and ruled out stays out", 7001 not in targeting)
    check("adoption judges it", targeting.adopt_new_pids() is True)
    check("and the socket it opened mid-walk is in scope",
          6000 in targeting and targeting.pids() == {100},
          f"({sorted(targeting.ports())}, {targeting.pids()})")


def test_a_new_process_announced_while_a_walk_runs_is_still_judged():
    """External review P2-10(b). A brand-new process whose first socket lands
    while a walk runs is queued by its event - and the publish emptied the whole
    queue, judging nothing: the process stayed out until the next rebuild. The
    walk takes out of the queue only what it judged itself."""
    table = _EventTable(ports={5000: 100, 5002: 102},
                        names={100: "chrome.exe", 102: "chrome.exe", 300: "chrome.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.note_socket(5002, 102)            # queued BEFORE the walk, which sees it
    walked = []

    def name_of(pid, cheap=False):
        if not walked:
            walked.append(pid)
            table.ports[7000] = 300
            targeting.note_socket(7000, 300)
        return table.names.get(pid, "")

    table.name_of = name_of
    targeting.refresh()
    check("the event really landed mid-walk", walked, "(the interposition never ran)")
    check("P2-10: the process nobody judged is still queued, the judged one is not",
          targeting._pending_pids == frozenset({300}), f"({set(targeting._pending_pids)})")
    targeting.adopt_new_pids()
    check("adoption puts its first socket in scope", 7000 in targeting,
          f"({sorted(targeting.ports())})")


def test_a_table_swap_does_not_wait_for_a_walk_nor_change_the_one_under_way():
    """External review P3-20: the engine hands targeting back to the poller at
    STOP, and a resolver that outlived its join can still be walking. A swap under
    the walk's lock made STOP wait for that walk. The walk reads its table once, so
    it finishes where it started instead of mixing two tables' answers."""
    a = _EventTable(ports={5000: 100}, names={100: "chrome.exe"})
    b = _EventTable(ports={}, names={100: "innocent.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=a)
    in_walk, release = threading.Event(), threading.Event()

    def snapshot():
        # Held BEFORE any name is asked, so every name the walk reads comes after
        # the swap - the walk has to read them from its own table to stay on A.
        in_walk.set()
        release.wait(10)
        return dict(a.ports)

    a.snapshot = snapshot
    walker = threading.Thread(target=targeting.refresh, daemon=True)
    walker.start()
    try:
        check("the walk is under way", in_walk.wait(5))
        swapper = threading.Thread(target=targeting.set_table, args=(b,), daemon=True)
        swapper.start()
        swapper.join(2)
        check("P3-20: the swap does not wait for the walk", not swapper.is_alive())
    finally:
        release.set()
    walker.join(5)
    check("the walk finished on the table it started with",
          targeting.pids() == {100}, f"({targeting.pids()})")
    targeting.refresh()
    check("and the next walk reads the new one", targeting.pids() == set(),
          f"({targeting.pids()})")


def test_an_adopted_pid_still_falls_out_at_the_next_rebuild():
    """Adoption must not become a way to accumulate pids for ever - the recycled-pid
    bound is exactly "until the next rebuild", and a union would erase it."""
    table = _EventTable(ports={5000: 100}, names={100: "chrome.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.note_socket(5000, 100)
    targeting.adopt_new_pids()
    check("adopted", targeting.pids() == {100})

    table.names[100] = "innocent.exe"        # the pid now belongs to somebody else
    targeting.refresh()
    check("the rebuild drops it, exactly as it drops a polled one",
          targeting.pids() == set(), f"({targeting.pids()})")


def test_a_recycled_pid_reaches_further_through_the_push_path_but_not_further_in_time():
    """Windows hands a dead process's pid number to a new one, and this path now
    acts on pids sooner - so the exposure it opens has to be stated, not assumed.

    BEFORE the push path, a stranger holding the target's old pid was pulled in for
    its SYN only: `owner_targeted` answered from the live map, and the flow's
    ordinary TCP data never asked again, so nothing else of it was impaired until a
    rebuild (which drops the pid). NOW `note_socket` puts the port itself in scope,
    so the WHOLE flow is impaired for as long as `_pids` is stale.

    The BOUND is unchanged and is what this pins: the next rebuild ends it. Widening
    it further - or losing the end of it - is what this test exists to catch. There
    is no cheaper answer available here: verifying identity means `create_time()`,
    and this runs on the watcher thread, which has 0.02 ms to spare.
    """
    table = _EventTable(ports={5000: 100}, names={100: "chrome.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.refresh()
    check("the target resolved", targeting.pids() == {100})

    # chrome exits; the number goes to somebody else, who opens a socket
    table.ports = {7000: 100}
    table.names = {100: "innocent.exe"}
    targeting.note_socket(7000, 100)
    check("inside the window the stranger's socket IS in scope", 7000 in targeting)

    # 🔴 The rebuild, with the stranger's socket announced WHILE the walk is
    # resolving names - the same interposition as
    # test_a_rebuild_in_flight_does_not_lose_a_socket_the_event_added, and since
    # 2026-09-03 the ONLY way a port reaches the rescue at all: `_late_owners` is
    # emptied at the START of a walk now (it used to be emptied at the end, which
    # let it hoard entries across failed walks). Announcing before the walk, the
    # way this test used to, no longer reaches the owner check - it left the guard
    # green whatever that check did, which the mutation registry reported as
    # SURVIVED. This is the case the check exists for: the event names pid 100,
    # and this very walk is in the middle of deciding 100 is no longer ours.
    seen = []

    def name_of(pid, cheap=False):
        if not seen:
            seen.append(pid)
            targeting.note_socket(7000, 100)
        return table.names.get(pid, "")

    table.name_of = name_of
    targeting.refresh()          # the resolver's next tick
    check("the event really landed mid-walk", seen, "(the interposition never ran)")
    check("the rebuild drops the pid", targeting.pids() == set(), f"({targeting.pids()})")
    check("...and the stranger's port with it", 7000 not in targeting,
          f"({sorted(targeting.ports())})")


def test_a_failing_refresh_does_not_leave_late_owners_behind():
    """The late-port list was emptied only by a walk that SUCCEEDED.

    Two consequences, and the second is the one that matters. It grew, fed by
    every socket event of every process already targeted - and it grew STALE: the
    rescue in ``refresh`` keeps a port whose RECORDED owner is still targeted, so
    once a walk finally succeeded it could put back in scope a port whose socket
    had closed long before, and which the OS may since have handed to somebody
    else. That is the "until the next rebuild" bound this class documents, quietly
    stretched to "until a refresh happens to work".

    A socket table that keeps failing is not a hypothetical: the resolver loop
    catches exactly this and carries on by design, which is what makes the
    accumulation invisible.
    """
    table = _EventTable(ports={5000: 100}, names={100: "chrome.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.refresh()
    check("the target resolved", targeting.pids() == {100})

    def explode(now=None, force=False):
        raise OSError("the socket table hiccupped")

    table.refresh = explode
    for port in range(6000, 6060):          # the target keeps opening sockets
        targeting.note_socket(port, 100)
        try:
            targeting.refresh()             # ...and every rebuild fails
        except OSError:
            pass                            # the resolver loop swallows this

    check("a walk that failed does not hoard the ports noted before it",
          not targeting._late_owners, f"({len(targeting._late_owners)} left)")

    # And the staleness half: the sockets are long gone, the table is healthy
    # again, so the next successful walk must not rescue any of them.
    table.refresh = lambda now=None, force=False: True
    table.ports = {5000: 100}
    targeting.refresh()
    check("a port whose socket closed while refresh was failing is not rescued",
          sorted(targeting.ports()) == [5000], f"({sorted(targeting.ports())})")


def test_the_pending_queue_cannot_grow_without_a_bound():
    """It is fed by every socket event on the machine. A fork bomb, or simply a
    busy server, must not turn that into an unbounded queue of OS lookups."""
    table = _EventTable(names={})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    for pid in range(1, targeting.MAX_PENDING_PIDS + 50):
        targeting.note_socket(9000 + pid, pid)
    check("the queue stops at its ceiling",
          len(targeting._pending_pids) == targeting.MAX_PENDING_PIDS,
          f"({len(targeting._pending_pids)})")

    # A walk queues the owners it never saw on top of that (P2-10) - still capped.
    # Announced WHILE it runs: a walk empties the late ports noted before it.
    targeting._pids = frozenset(range(20000, 20010))
    walked = []

    def snapshot():
        walked.append(1)
        for pid in targeting._pids:
            targeting.note_socket(pid, pid)
        return {}

    table.snapshot = snapshot
    targeting.refresh()
    check("the sockets were announced mid-walk", walked, "(the interposition never ran)")
    check("a walk does not push it past the ceiling either",
          len(targeting._pending_pids) == targeting.MAX_PENDING_PIDS,
          f"({len(targeting._pending_pids)})")
    check("and what it cuts is not the owners it queued - they were targets",
          set(range(20000, 20010)) <= targeting._pending_pids,
          f"({len(set(range(20000, 20010)) & targeting._pending_pids)} of 10 kept)")


def test_a_target_that_restarts_under_a_new_pid_is_picked_up_from_its_event():
    """The lifecycle the field actually has: the app under test is closed and
    started again while the session runs.

    By NAME this must recover without touching the session - the new pid is a pid
    nobody has judged, which is the adoption path. (By PID it cannot recover, and
    that is the expression's property, not this code's - see owner_targeted.)
    """
    table = _EventTable(ports={5000: 100}, names={100: "chrome.exe"})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.refresh()
    check("the first life is targeted", targeting.pids() == {100})

    # it exits: no sockets, so the rebuild drops it entirely
    table.ports, table.names = {}, {}
    targeting.refresh()
    check("nothing is targeted between the two lives", targeting.pids() == set())

    # it comes back under a new pid and connects
    table.ports[5100] = 300
    table.names[300] = "chrome.exe"
    targeting.note_socket(5100, 300)
    targeting.adopt_new_pids()
    check("the new life is adopted", targeting.pids() == {300}, f"({targeting.pids()})")
    check("...and its connection is in scope", 5100 in targeting)


def test_a_pid_typed_as_a_number_is_checked_through_the_live_map_too():
    """A real session resolves against the watcher, so a start time has to reach
    targeting through it - or a later holder of a pid typed as a number (review
    P2-9) is judged by the number again, on the path that adopts it from its
    first socket event."""
    class _Stamped(_Names):
        def __init__(self, names, created):
            super().__init__(names)
            self._created = dict(created)

        def created_of(self, pid):
            return self._created.get(pid)

    later = time.time() + 3600                  # started after the target was set
    watcher = SocketWatcher(names=_Stamped({1234: "innocent.exe"}, {1234: later}),
                            source_factory=lambda: _Source([]))
    targeting = ProcessTargeting(bnt.parse_target("1234"), table=watcher)
    targeting.refresh()
    watcher.apply(ev(CONNECT, 1234, 7000))
    targeting.note_socket(7000, 1234)
    check("the watcher hands the start time through", watcher.created_of(1234) == later,
          f"({watcher.created_of(1234)})")
    check("so the new process is not adopted by its number",
          targeting.adopt_new_pids() is False and 7000 not in targeting,
          f"({sorted(targeting.ports())})")
    check("a name cache without start times cannot tell",
          SocketWatcher(names=_Names({})).created_of(1234) is None)


def test_a_process_already_running_when_the_session_starts_is_in_scope_at_once():
    """The other order, and the one a user hits most: the app is already open and
    THEN capture starts. Nothing announces those sockets - events only carry new
    ones - so the bootstrap snapshot is what has to cover them, before the first
    packet is judged."""
    eng = BeanEngine()
    eng._ports = _FakePorts({5000: 100})          # chrome is already connected
    targeting = eng.target_for(bnt.parse_target("chrome"))
    eng.set_target(True, targeting)
    eng.start("true", divert=FakeDivert([]), socket_source=_Source([]))
    try:
        check("the existing connection is in scope from the start",
              5000 in targeting, f"({sorted(targeting.ports())})")
    finally:
        eng.stop()


# -- engine binding ----------------------------------------------------------- #
def test_the_engine_wires_the_live_map_to_targeting_and_unwires_it():
    """Either end can be installed first (the GUI applies a target before START),
    so both paths have to do the wiring - and removing the target has to undo it,
    or the watcher keeps calling into an orphan."""
    eng = BeanEngine()
    eng._ports = _FakePorts({})
    targeting = eng.target_for(bnt.parse_target("chrome"))
    eng.set_target(True, targeting)                 # target first, no session yet
    eng.start("true", divert=FakeDivert([]), socket_source=_Source([]))
    try:
        check("start wired the map to the target",
              eng._socketwatch._on_socket == targeting.note_socket)
        eng.set_target(False)
        check("removing the target detaches the listener",
              eng._socketwatch._on_socket is None)
        again = eng.target_for(bnt.parse_target("firefox"))
        eng.set_target(True, again)
        check("installing one mid-session wires it up",
              eng._socketwatch._on_socket == again.note_socket)
    finally:
        eng.stop()


def test_engine_binds_targeting_to_the_watcher_when_present():
    eng = BeanEngine()
    eng._ports = _FakePorts({})
    targeting = eng.target_for(bnt.parse_target("chrome"))     # built before start
    check("built against the poller before start", targeting.table is eng._ports)
    eng.set_target(True, targeting)
    eng.start("true", divert=FakeDivert([]), socket_source=_Source([]))
    try:
        check("start rebound targeting to the live watcher",
              targeting.table is eng._socketwatch and eng._socketwatch is not None)
    finally:
        eng.stop()


def test_engine_keeps_targeting_on_the_poller_without_a_watcher():
    """Synthetic/simulate path: no watcher, so targeting stays on the poller."""
    eng = BeanEngine()
    eng._ports = _FakePorts({})
    targeting = eng.target_for(bnt.parse_target("chrome"))
    eng.set_target(True, targeting)
    eng.start("true", divert=FakeDivert([]))                   # no socket source
    try:
        check("no watcher on the synthetic path", eng._socketwatch is None)
        check("targeting stays on the poller", targeting.table is eng._ports)
    finally:
        eng.stop()
