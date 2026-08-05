"""The live local_port -> pid map fed by SOCKET-layer events (chunk 2a).

This module is the replacement for polling the socket table: instead of a
snapshot taken a few times a second (which misses any connection that opens and
closes between two snapshots), the map is updated the instant a socket is
bound/connected/accepted/closed. These tests drive the map through its event
API directly - no WinDivert, no threads - plus one lifecycle test on an injected
fake source. The real Windows source is exercised by the smoke, not here.
"""
import threading
import time

from beantester.socketwatch import (ACCEPT, BIND, CLOSE, CONNECT, LISTEN,
                                     SocketEvent, SocketWatcher)
from fakes import check


def ev(kind, pid, port):
    return SocketEvent(kind, pid, port)


class _FakeNames:
    """Stands in for portmap's pid -> name / ancestors cache (no psutil)."""

    def __init__(self):
        self.calls = []

    def name_of(self, pid, cheap=False):
        self.calls.append(("name_of", pid, cheap))
        return {100: "chrome.exe"}.get(pid, "")

    def ancestors(self, pid, depth=8):
        self.calls.append(("ancestors", pid, depth))
        return [(1, "explorer.exe")]


class _FakeSource:
    """Yields queued events, then parks like a blocking recv() until close()."""

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


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


class _Clock:
    """A hand-driven clock.

    Every reconcile test below turns on WHICH came first - the event or the
    snapshot's collection - so that ordering has to be a fact of the test, not a
    race against the real ``time.monotonic()``. (Its resolution here is ~100 ns,
    but a test that would go red on a coarser clock is a test that reports the
    machine instead of the code.)
    """

    def __init__(self, t=1000.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def tick(self, dt=1.0):
        self.t += dt
        return self.t


def _watcher(clock=None):
    return SocketWatcher(names=_FakeNames(), clock=clock or time.monotonic)


# -- the map ------------------------------------------------------------------ #
def test_add_events_map_the_local_port_to_the_owning_pid():
    """Every "a socket now owns a port" event populates the map."""
    w = _watcher()
    w.apply(ev(CONNECT, 100, 5000))     # TCP outbound
    w.apply(ev(BIND, 101, 5001))        # UDP (QUIC binds, never connects)
    w.apply(ev(ACCEPT, 102, 5002))      # TCP inbound
    w.apply(ev(LISTEN, 103, 5003))      # a server socket
    check("all four add-events mapped their port", w.snapshot() ==
          {5000: 100, 5001: 101, 5002: 102, 5003: 103}, f"({w.snapshot()})")


def test_close_releases_the_port():
    w = _watcher()
    w.apply(ev(CONNECT, 100, 5000))
    w.apply(ev(CLOSE, 100, 5000))
    check("close removed the port", 5000 not in w.snapshot(), f"({w.snapshot()})")


def test_a_stale_close_does_not_evict_a_recycled_port():
    """Windows reuses ports and PIDs: a late CLOSE for the OLD owner must not
    evict the NEW one that has taken the same port number."""
    w = _watcher()
    w.apply(ev(CONNECT, 100, 5000))     # old owner
    w.apply(ev(CONNECT, 200, 5000))     # the port is reused by a different pid
    w.apply(ev(CLOSE, 100, 5000))       # a late close for the OLD owner arrives
    check("the port still belongs to the new owner", w.snapshot().get(5000) == 200,
          f"({w.snapshot()})")


def test_close_for_an_unknown_port_is_harmless():
    w = _watcher()
    w.apply(ev(CLOSE, 100, 5000))       # never added
    check("closing an unknown port does nothing", w.snapshot() == {}, f"({w.snapshot()})")


def test_junk_events_are_ignored_not_raised():
    """The hot path must never be handed a crash: port 0 (not yet assigned) and
    pid 0 (the idle process) are dropped, quietly."""
    w = _watcher()
    for bad in (ev(CONNECT, 100, 0), ev(CONNECT, 0, 5000), ev(CONNECT, -1, 5000)):
        w.apply(bad)
    check("no junk entered the map", w.snapshot() == {}, f"({w.snapshot()})")


# -- reconcile (bootstrap + safety net) --------------------------------------- #
def test_reconcile_bootstraps_and_prunes_only_after_a_two_pass_grace():
    """The snapshot seeds the map and catches missed CLOSEs - but a socket opened
    microseconds before the snapshot was taken (present via its event, absent from
    that snapshot) must survive one miss, or the safety net would evict live
    connections.

    Both later snapshots are collected AFTER the event on purpose: that is the
    residual case the grace exists for. A snapshot collected BEFORE the event is a
    different scenario entirely and is covered by
    ``test_a_port_an_event_touched_after_the_collection_is_never_counted_absent``.
    """
    clock = _Clock()
    w = _watcher(clock)
    w.reconcile({80: 1, 443: 2}, clock())             # bootstrap
    check("bootstrap added the snapshot", w.snapshot() == {80: 1, 443: 2})

    w.apply(ev(CONNECT, 9, 5000))                     # a fresh socket via its event
    check("event added the fresh port", w.snapshot().get(5000) == 9)

    # collected a hair AFTER the event, and it still missed the port: the socket
    # opened while the table walk was in flight
    w.reconcile({80: 1, 443: 2}, clock.tick())
    check("fresh port survives ONE absent snapshot", w.snapshot().get(5000) == 9,
          f"({w.snapshot()})")

    w.reconcile({80: 1, 443: 2}, clock.tick())        # still absent -> missed-CLOSE case
    check("absent-twice port is pruned", 5000 not in w.snapshot(), f"({w.snapshot()})")
    check("snapshot ports are always kept", w.snapshot() == {80: 1, 443: 2})


def test_reconcile_grace_resets_when_a_port_reappears():
    clock = _Clock()
    w = _watcher(clock)
    w.apply(ev(CONNECT, 9, 5000))
    w.reconcile({}, clock.tick())                     # absent once (on watch)
    w.reconcile({5000: 9}, clock.tick())              # reappears -> cleared
    w.reconcile({}, clock.tick())                     # absent once again, not twice running
    check("a port that reappeared is not pruned on a single later miss",
          w.snapshot().get(5000) == 9, f"({w.snapshot()})")


# -- reconcile: the snapshot is COMPLETE, not CURRENT (F2) --------------------- #
def test_a_newer_event_is_not_undone_by_an_older_snapshot():
    """The socket table is collected up to REFRESH_S before it is handed over, so
    it can still name the PREVIOUS owner of a recycled port. Merging it blindly put
    that owner back - measured 11 times in 25 s on a live session, on ordinary
    Windows background traffic (137/138/1900/67).

    Consequence if this regresses: engine._pid_for stamps the connection row with a
    process that does not own the socket, and targeting.owner_targeted - the gate
    for a TCP SYN and for EVERY UDP datagram - answers about the wrong process.
    """
    clock = _Clock()
    w = _watcher(clock)
    stale = clock()                                   # the table is walked HERE...
    clock.tick()
    w.apply(ev(CLOSE, 111, 50000))                    # ...and only then does the
    w.apply(ev(CONNECT, 222, 50000))                  #    port change hands
    check("the event stream has the live answer", w.pid_for(50000) == 222)

    w.reconcile({50000: 111}, stale)                  # the stale walk, handed over late
    check("an older snapshot does not revert the owner", w.pid_for(50000) == 222,
          f"(pid_for={w.pid_for(50000)})")


def test_a_port_known_only_from_a_connect_still_outranks_an_older_snapshot():
    """The stamp an ADD event leaves is load-bearing on its own.

    Written because a MUTANT SURVIVED: stripping the stamp from the ADD branch left
    the handover test above green, because that one is carried by the CLOSE's
    tombstone. This is the case where a CONNECT is the only thing that ever spoke
    about the port - the watcher saw the socket open while a table walk already in
    flight still named the previous owner (we never got the CLOSE, which is the
    documented "events can be missed under load" case).
    """
    clock = _Clock()
    w = _watcher(clock)
    stale = clock()                                   # the walk names the old owner
    clock.tick()
    w.apply(ev(CONNECT, 222, 50000))                  # the ONLY event for this port

    w.reconcile({50000: 111}, stale)
    check("a snapshot that predates the connect does not win",
          w.pid_for(50000) == 222, f"(pid_for={w.pid_for(50000)})")


def test_a_closed_port_is_not_resurrected_by_an_older_snapshot():
    """The same defect from its commonest side, and it does not need a recycled
    port - only a close. A CLOSE event removes the port; a snapshot collected
    before that close still lists it, and used to put it straight back. Measured on
    a live session: 1394 resurrections in 25 s across 896 connections, each leaving
    the map naming a pid that had already let the socket go.

    This is what the tombstone in ``_evidence`` is for: without a mark, "closed a
    moment ago" and "never seen" are the same absence.
    """
    clock = _Clock()
    w = _watcher(clock)
    w.apply(ev(CONNECT, 111, 50000))
    stale = clock.tick()                              # snapshot walked while it was open
    clock.tick()
    w.apply(ev(CLOSE, 111, 50000))
    check("the close removed the port", w.pid_for(50000) is None)

    w.reconcile({50000: 111}, stale)
    check("an older snapshot does not resurrect a closed port",
          w.pid_for(50000) is None, f"(pid_for={w.pid_for(50000)})")


def test_a_snapshot_taken_after_the_event_still_heals_a_stale_entry():
    """The guard against fixing this too hard.

    "Events always win" was the smaller change and it was rejected here: socket
    events CAN be missed under load, and if we then also miss the new owner's
    CONNECT, the map keeps a dead pid that the prune will never take (the port is
    in every snapshot, so it is never absent). The snapshot has to stay able to
    correct the map - just not with data older than what it is correcting.
    """
    clock = _Clock()
    w = _watcher(clock)
    w.apply(ev(CONNECT, 111, 50000))                  # ...and we miss its CLOSE, and
    clock.tick()                                      #    the new owner's CONNECT
    fresh = clock.tick()                              # a walk taken AFTER all that

    w.reconcile({50000: 222}, fresh)
    check("a snapshot newer than the event still heals the entry",
          w.pid_for(50000) == 222, f"(pid_for={w.pid_for(50000)})")


def test_a_port_an_event_touched_after_the_collection_is_never_counted_absent():
    """The stamp gates the PRUNE too, not only the merge.

    A snapshot cannot vouch for a socket that did not exist when it was walked, so
    its silence about that port says nothing and must not spend one of the two
    grace passes. Before this, the port's survival rested on WATCHDOG_TICK_S (0.2)
    and portmap.REFRESH_S (0.3) interleaving so that two stale reconciles never ran
    back to back - arithmetic that nothing stated and nothing tested.
    """
    clock = _Clock()
    w = _watcher(clock)
    stale = clock()                                   # walked before the socket existed
    clock.tick()
    w.apply(ev(CONNECT, 9, 5000))

    w.reconcile({}, stale)                            # three passes of the SAME old walk
    w.reconcile({}, stale)
    w.reconcile({}, stale)
    check("a port younger than the snapshot is not pruned by it",
          w.pid_for(5000) == 9, f"({w.snapshot()})")

    w.reconcile({}, clock.tick())                     # a walk that really did miss it
    w.reconcile({}, clock.tick())
    check("...but a snapshot newer than the event still prunes it after two passes",
          w.pid_for(5000) is None, f"({w.snapshot()})")


def test_the_evidence_map_does_not_grow_with_every_connection_ever_seen():
    """Tombstones are bounded, or a browser would leak one entry per closed socket.

    A tombstone is kept only while it can still veto a snapshot; once a snapshot
    collected AFTER the close has agreed the port is gone, it is dropped. So the
    steady state is (open sockets + one refresh interval of churn), not (every
    socket this session ever saw).
    """
    clock = _Clock()
    w = _watcher(clock)
    for i in range(500):                              # 500 short-lived connections
        w.apply(ev(CONNECT, 100, 6000 + i))
        w.apply(ev(CLOSE, 100, 6000 + i))
        clock.tick()
    w.apply(ev(CONNECT, 100, 5000))                   # one that stays open
    check("tombstones piled up while no snapshot had caught up",
          len(w._evidence) > 100, f"({len(w._evidence)})")

    w.reconcile({5000: 100}, clock.tick())            # a walk newer than every close
    check("the map itself holds only the live socket", w.snapshot() == {5000: 100},
          f"({w.snapshot()})")
    check("and the evidence map collapsed to it", set(w._evidence) == {5000},
          f"({len(w._evidence)} entries)")


# -- name resolution is delegated, not duplicated ----------------------------- #
def test_the_system_process_does_not_take_a_port_off_a_user_process():
    """MEASURED 2026-08-05, on a live session, and it happens constantly.

    The SOCKET layer delivers a SECOND connect for the same local port carrying
    ProcessId 4, in the middle of a connection a user process owns::

        BIND/pid116724, CONNECT/pid116724, CONNECT/pid4, CLOSE/pid116724

    Applied like any other add-event, that hands the port to System. Targeting
    drops it at its next rebuild (System does not match the target), the rest of
    the flow is never impaired, and the connection table shows "System" as the
    owner of a row belonging to the targeted application. Both symptoms, one
    cause: 2 to 4 of 12 fresh processes lost their scope this way in every run.

    Not a blanket ban on pid 4: System genuinely owns sockets (SMB on 139/445),
    and a port it holds first stays its own.
    """
    watcher = _watcher()
    watcher.apply(ev(CONNECT, 100, 5000))
    watcher.apply(ev(CONNECT, 4, 5000))                 # the kernel's second half
    check("the user process keeps its port", watcher.snapshot().get(5000) == 100,
          f"({watcher.snapshot()})")
    check("but the event is still counted", watcher.events == 2, f"({watcher.events})")

    watcher.apply(ev(LISTEN, 4, 445))                   # System's own socket
    check("a port System takes first is System's", watcher.snapshot().get(445) == 4,
          f"({watcher.snapshot()})")
    watcher.apply(ev(CONNECT, 4, 445))
    check("...and it may keep it", watcher.snapshot().get(445) == 4)


def test_refusing_the_system_event_leaves_the_snapshot_able_to_heal():
    """The refusal must not also block the safety net.

    An event this map does not act on leaves no evidence - that is the existing
    rule for unmodelled kinds, and it matters here: if the refusal stamped the
    port as "freshly known", a later snapshot could no longer correct the entry,
    and a genuinely stale owner would be frozen in.
    """
    clock = _Clock()
    watcher = _watcher(clock)
    watcher.apply(ev(CONNECT, 100, 5000))               # evidence: the real owner
    collected = clock.tick()                            # the poller walks the table HERE
    clock.tick()
    watcher.apply(ev(CONNECT, 4, 5000))                 # refused, and must leave no mark
    watcher.reconcile({5000: 777}, collected)
    check("a snapshot older than the refusal still heals the port",
          watcher.snapshot().get(5000) == 777, f"({watcher.snapshot()})")


def test_a_listener_is_told_about_each_socket_the_map_gains():
    """The map is not only a thing to be asked - it can tell.

    Targeting used to discover a new socket at its own next rebuild, up to 0.30 s
    after the event that announced it, and a short-lived connection was over by
    then. The engine hands `note_socket` in here so the discovery is driven by the
    event instead. Only ADD kinds: a CLOSE is not a socket the map GAINED, and
    telling a listener about one would be inviting it to act on the wrong half.
    """
    told = []
    watcher = SocketWatcher(names=_FakeNames())
    watcher.on_socket(lambda port, pid: told.append((port, pid)))

    watcher.apply(ev(CONNECT, 100, 5000))
    watcher.apply(ev(BIND, 101, 5001))
    watcher.apply(ev(CLOSE, 100, 5000))
    check("every gained socket is announced", told == [(5000, 100), (5001, 101)],
          f"({told})")

    watcher.on_socket(None)
    watcher.apply(ev(CONNECT, 102, 5002))
    check("detaching stops the calls", len(told) == 2, f"({told})")


def test_a_listener_that_throws_cannot_cost_the_map_an_event():
    """It runs on the watcher thread, between the driver and the packet path's map.
    A broken consumer must not be able to stop sockets being recorded."""
    watcher = SocketWatcher(names=_FakeNames())

    def boom(port, pid):
        raise RuntimeError("the listener is broken")

    watcher.on_socket(boom)
    raised = None
    try:
        watcher.apply(ev(CONNECT, 100, 5000))
    except Exception as exc:
        # apply() lets it out; the LOOP's crashlog.quiet is what swallows it, and
        # that is asserted separately. What must hold here is that the map was
        # already updated before the listener ever ran.
        raised = exc
    check("the map recorded the socket anyway", watcher.snapshot().get(5000) == 100,
          f"({watcher.snapshot()})")
    check("and the event was counted", watcher.events == 1, f"({watcher.events})")
    check("nothing escaped to the caller", raised is None, f"({raised!r})")


def test_name_and_ancestors_delegate_to_the_names_table():
    names = _FakeNames()
    w = SocketWatcher(names=names)
    check("name_of delegates", w.name_of(100) == "chrome.exe")
    check("ancestors delegate", w.ancestors(100) == [(1, "explorer.exe")])
    check("both calls went to the names table",
          [c[0] for c in names.calls] == ["name_of", "ancestors"], f"({names.calls})")


def test_refresh_is_a_noop_the_events_keep_it_live():
    """ProcessTargeting calls table.refresh(); on this table it must be free and
    must not clear the live map."""
    w = _watcher()
    w.apply(ev(CONNECT, 100, 5000))
    check("refresh returns False (nothing rebuilt)", w.refresh() is False)
    check("refresh left the live map intact", w.snapshot() == {5000: 100})


# -- the reader thread -------------------------------------------------------- #
def test_the_watcher_thread_applies_events_from_its_source():
    events = [ev(CONNECT, 100, 5000), ev(BIND, 100, 5001), ev(CLOSE, 100, 5000)]
    w = SocketWatcher(names=_FakeNames(), source_factory=lambda: _FakeSource(events))
    w.start()
    try:
        check("the watcher applied its events", _wait(lambda: w.events >= 3))
        check("connect+bind added, close removed", w.snapshot() == {5001: 100},
              f"({w.snapshot()})")
        check("the reader thread is alive", w.is_running())
    finally:
        w.stop()
    check("stop joined the thread", not w.is_running())


def test_stop_is_safe_without_a_start():
    w = _watcher()
    w.stop()                                          # must not raise
    check("still not running", not w.is_running())


def test_stop_does_not_record_the_close_induced_error_as_a_crash(monkeypatch):
    """stop() closes the source, and on real WinDivert the parked recv() then raises
    (WinError 995, "I/O aborted"). That is the NORMAL shutdown path, not a fault - it
    must not land in the crash log, or every STOP leaves a spurious entry."""
    from beantester import crashlog
    recorded = []
    monkeypatch.setattr(crashlog, "_once_seen", set())
    monkeypatch.setattr(crashlog, "record", lambda exc, **kw: recorded.append(kw))

    class _RaisingSource:
        def __init__(self):
            self._closed = threading.Event()

        def __iter__(self):
            self._closed.wait()                       # park like a blocking recv()
            raise OSError("[WinError 995] aborted")   # ...then raise, as pydivert does

        def close(self):
            self._closed.set()

    w = SocketWatcher(names=_FakeNames(), source_factory=_RaisingSource)
    w.start()
    _wait(w.is_running)
    w.stop()
    time.sleep(0.05)
    check("the close-induced error was NOT recorded as a crash", recorded == [],
          f"({recorded})")

    # ...but an error while NOT stopping still is: a socket stream that dies mid-run
    # is traffic sailing through unimpaired.
    recorded.clear()
    raised = threading.Event()

    class _DiesWhileRunning:
        def __iter__(self):
            raised.set()
            raise OSError("stream died")

        def close(self):
            pass

    w2 = SocketWatcher(names=_FakeNames(), source_factory=_DiesWhileRunning)
    w2.start()
    check("the failing source ran", raised.wait(timeout=5))
    time.sleep(0.05)
    check("a mid-run failure IS recorded", len(recorded) == 1, f"({recorded})")
    w2.stop()


# -- the lock-free read the capture thread depends on ------------------------- #
def test_pid_for_takes_no_lock_because_the_capture_thread_calls_it():
    """A lock here would let the packet path queue behind the watcher thread or a
    whole reconcile. Asserted mechanically rather than by reading the code: with a
    lock that refuses to be taken, ``pid_for`` must still answer.
    """
    w = _watcher()
    w.apply(ev(CONNECT, 100, 5000))              # while the real lock still works

    class _Explodes:
        def __enter__(self):
            raise AssertionError("pid_for must not take the lock")

        def __exit__(self, *exc):
            return False

    w._lock = _Explodes()
    check("pid_for answers without taking the lock", w.pid_for(5000) == 100)
    check("and still reports an unknown port as None", w.pid_for(9999) is None)


def test_reconcile_publishes_a_new_map_instead_of_mutating_in_place():
    """The identity swap is what makes the lock-free read safe across an O(n) pass:
    mutating in place would let a reader observe half a reconcile."""
    clock = _Clock()
    w = _watcher(clock)
    w.apply(ev(CONNECT, 100, 5000))
    before = w._ports
    w.reconcile({5000: 100, 80: 1}, clock.tick())
    check("reconcile published a NEW dict", w._ports is not before)
    check("with the merged content", w.snapshot() == {5000: 100, 80: 1},
          f"({w.snapshot()})")


def test_a_lock_free_reader_survives_writes_in_flight():
    """"Lock-free is safe here" is a SAFETY claim, so it is run in the conditions that
    would break it instead of being asserted in a docstring: one thread reading a port
    while another inserts, deletes and republishes the whole map underneath it. A torn
    read would surface as an exception, or as a value that is neither the pid nor None.
    """
    clock = _Clock()
    w = _watcher(clock)
    w.apply(ev(CONNECT, 100, 5000))
    errors, values, reads = [], set(), [0]
    stop = threading.Event()

    def reader():
        try:
            while not stop.is_set():
                values.add(w.pid_for(5000))      # a set, so this stays tiny
                reads[0] += 1
        except Exception as exc:                  # a torn read would land here
            errors.append(exc)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        for i in range(300):
            w.apply(ev(CONNECT, 100 + (i % 7), 6000 + i))     # inserts...
            w.apply(ev(CLOSE, 100 + (i % 7), 6000 + i))       # ...and deletes
            # the clock advances, so this also drives the tombstone rebuild - the
            # other O(n) pass a lock-free reader has to survive
            w.reconcile({5000: 100, 80: 1}, clock.tick())     # whole-map republish
    finally:
        stop.set()
        t.join(timeout=5)

    check("the lock-free reader never raised", not errors, f"({errors[:3]})")
    check("it actually kept reading", reads[0] > 0)
    check("and every value it saw was the real pid, never junk", values == {100},
          f"({values})")
