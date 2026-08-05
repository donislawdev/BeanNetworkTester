"""Live ``local_port -> pid`` map, fed by WinDivert SOCKET-layer events.

Why this exists (it replaces polling for the fresh-connection case)
------------------------------------------------------------------
Targeting by process has to answer "does this local port belong to the target?"
for every packet. The old answer came from POLLING the OS socket table
(``GetExtendedTcpTable``, see :mod:`beantester.portmap`): a snapshot taken a few
times a second. A snapshot is always a little behind reality, so a connection
that opens AND closes between two snapshots is never seen - its whole life slips
through unimpaired. Measured against Chrome, a large share of short-lived
connections escaped exactly this way.

WinDivert 2.2 exposes a SOCKET layer that delivers an event the moment a socket
is bound / connected / accepted / closed, carrying the owning ``ProcessId``. A
**sniff-only** handle (``SNIFF | RECV_ONLY`` - it cannot drop or modify anything)
turns "guess the owner from a stale snapshot" into "be told the owner as it
happens".

**Re-measured 2026-07-28** (Win11, elevated, three sniff-only handles compared on
one clock - the QPC stamp WinDivert puts on every event - across 10 outbound TCP
connections to 8.8.8.8:53):

* ``SOCKET_CONNECT`` came before the outbound SYN in **10 runs out of 10**, by
  **0.018-0.027 ms, median 0.020**. The ORDER is what this design rests on, and it
  holds. The margin does not: an earlier note here said "~0.1 ms", five times what
  this machine shows.
* ``FLOW_ESTABLISHED`` came **37.7-41.3 ms after** the SYN, median 38.7 - i.e.
  after the handshake, which is why the SOCKET layer and not the FLOW layer is the
  source here. That number is **the round trip to the peer, not a property of the
  FLOW layer**: ping to the same host measured 23-47 ms on this link, and an
  earlier note quoting "~28 ms" was quoting somebody's network.

What this does NOT establish, and used to be claimed here: that "the race is
closed at the source". The tens of microseconds above are the gap between the two
events AT THE DRIVER. Whether this module's own handling - thread wake, parse,
dict insert - finishes inside that gap has not been measured. Ordering is
guaranteed; comfortable slack is not.

Scope of this module: the map and its event handling. ``BeanEngine`` owns its
lifecycle (created and stopped with the session) and points ``ProcessTargeting``
at it, so in a real session this - not the poller - is what targeting resolves
against. The event SOURCE is injected, so the map is fully testable without
WinDivert; the real Windows source lives here too but is exercised by the smoke,
not the unit tests.

What it is NOT
--------------
* **Not a name resolver.** ``pid -> (name, ppid)`` and the process TREE stay in
  :mod:`beantester.portmap`'s cache, composed in rather than duplicated: resolving
  a name is a psutil call and has nothing to do with how we learned the pid. That
  is why this class exposes the same read surface targeting already uses on
  ``PortTable`` (``snapshot`` / ``name_of`` / ``ancestors`` / ``refresh``) - so it
  can stand in as the table a ``ProcessTargeting`` resolves against.
* **Not the whole story alone.** Socket events can be missed under extreme load,
  and connections open BEFORE the handle are never announced. Both are covered by
  ``reconcile()`` (seeded from a ``portmap`` snapshot): the events are the live
  signal, the snapshot is the safety net. ``reconcile`` prunes a port the snapshot
  no longer lists only after it has been absent for TWO passes, so a socket opened
  microseconds before the snapshot was taken is not evicted by it.

  **The snapshot is COMPLETE, not CURRENT, and the difference is load-bearing.**
  It is collected up to ``portmap.REFRESH_S`` before it is handed over and applied
  up to a watchdog tick later, so it always describes a slightly older world than
  the event stream does. An earlier version of this module merged it
  unconditionally and called it "authoritative", which read "complete" as "newest"
  and let it undo work the events had already done.

  MEASURED on a live session (2026-07-29, real SOCKET handle, 887 connections in
  25 s, 123 reconciles): **919 writes the old rule would have made are refused by
  this one**, each a snapshot entry for a port an event had touched 0-170 ms AFTER
  that snapshot was walked. Some put back a port a CLOSE had removed, some named
  the previous owner of a port that had changed hands (port 67 was seen going
  ``3040 -> 4616`` and being reverted). Every one is a window in which
  ``engine._pid_for`` and ``targeting.owner_targeted`` answer with a pid that is
  not the owner - the second of those being the gate for a TCP SYN and for every
  UDP datagram. The count is the difference between the two rules, taken directly;
  an earlier attempt to count "resurrections" by watching ports come back was
  discarded because it cannot tell a resurrected socket from the same process
  reopening a recycled port, and it over-reported by roughly a third.

  So every entry carries the time of the evidence behind it (``_evidence``), and a
  snapshot entry is applied only when the snapshot was COLLECTED after that. The
  three cases fall out of the one rule instead of being tuned: a newer event beats
  an older snapshot, a CLOSE is not undone by an older snapshot, and a snapshot
  taken *after* the last event still heals an entry whose CLOSE we missed - which
  is the reason the simpler rule ("events always win") was rejected. ``_evidence``
  also holds TOMBSTONES for closed ports, because "closed just now" and "never
  seen" are only distinguishable if the close left a mark.
"""
import threading
import time
from collections import namedtuple

from . import crashlog, portmap

# WinDivert 2.2 socket-layer events (WINDIVERT_EVENT_SOCKET_*). A socket that
# binds / connects / accepts / listens now owns a local port; a close releases it.
BIND, CONNECT, LISTEN, ACCEPT, CLOSE = 3, 4, 5, 6, 7
_ADD = frozenset({BIND, CONNECT, LISTEN, ACCEPT})

# One socket-layer event, normalised away from the ctypes struct so the map logic
# (and its tests) never touch pydivert. An event carries only what this map is for:
# WHO owns a local port. It used to also carry proto / remote_ip / remote_port /
# outbound "for the connection log later", and nothing ever read them - because the
# NETWORK-layer packet the engine already holds is a strictly better source for all
# four (it even distinguishes ICMP, which the SOCKET layer does not). The one thing
# a packet cannot tell us is the owning pid, which is exactly what is left here.
SocketEvent = namedtuple("SocketEvent", "kind pid local_port")

# "no event has ever touched this port". Deliberately -inf and not 0.0: a
# ``PortTable`` that has never refreshed reports a collection time of 0.0, and
# with 0.0 as the default the bootstrap reconcile would compare 0.0 < 0.0, decide
# its own snapshot was too old, and seed nothing at all.
_NEVER = float("-inf")

# The System process. Windows pins it to 4 (and the Idle process to 0, which is
# already filtered as "no pid"), and the SOCKET layer reports it for the kernel's
# own half of an operation a user process started - see `apply`.
_SYSTEM_PID = 4


class SocketWatcher:
    """A live ``local_port -> pid`` map maintained from socket-layer events."""

    def __init__(self, names=None, source_factory=None, clock=time.monotonic):
        # names: where pid -> (name, ppid) / ancestors lookups go. The default is
        # the one process-wide PortTable, so its psutil cache is warmed once for
        # the engine, the GUI and targeting together.
        self._names = names if names is not None else portmap.default_table()
        # source_factory() -> an object that is iterable (yields SocketEvent) and
        # has close(). Injected so the loop is testable without WinDivert; the real
        # source is windivert_socket_source (below), used only on a live session.
        self._source_factory = source_factory or windivert_socket_source
        self.clock = clock
        self._lock = threading.RLock()
        self._ports = {}                 # local_port -> pid (the live map)
        # local_port -> when an EVENT last said something about this port. Held for
        # ports in the map AND for recently closed ones (tombstones), so reconcile
        # can tell "closed since your snapshot" from "never seen". Read and written
        # under _lock only - never by pid_for, so the packet path pays nothing.
        self._evidence = {}
        self._suspect = set()            # ports absent from the last snapshot (grace)
        self._source = None
        self._thread = None
        self._stopping = threading.Event()
        self._events = 0                 # applied-event counter (tests/diagnostics)
        self._reconciles = 0
        # Told about every socket this map GAINS, so a consumer can act on the
        # event instead of discovering it at its own next poll. Injected by
        # BeanEngine (targeting.note_socket) rather than imported, so this module
        # keeps knowing nothing about targeting.
        self._on_socket = None

    # -- the map --------------------------------------------------------------- #
    def on_socket(self, callback):
        """Be told about each socket this map gains (``None`` detaches).

        One slot, set by the engine when it points targeting at this map. A plain
        attribute on purpose: the reader is the watcher thread, which reads it once
        per event, and a rebind is atomic.
        """
        self._on_socket = callback

    def apply(self, ev):
        """Fold one socket event into the map. Never raises on junk input."""
        port, pid = ev.local_port, ev.pid
        if not port or not pid or pid <= 0:
            return                        # no local port yet, or the idle/System 0
        with self._lock:
            if ev.kind in _ADD:
                if pid == _SYSTEM_PID and self._ports.get(port, _SYSTEM_PID) != _SYSTEM_PID:
                    # The System process does not take a port off a user process.
                    #
                    # MEASURED 2026-08-05, and it is not an edge case: the SOCKET
                    # layer delivers a SECOND connect for the same local port
                    # carrying ProcessId 4, in the middle of a live connection -
                    #     BIND/pid116724, CONNECT/pid116724, CONNECT/pid4, CLOSE...
                    # Applied blindly, that hands the port to System, targeting drops
                    # it at the next rebuild, and the rest of the flow is never
                    # impaired. It is also where the connection table's "System" rows
                    # came from. Reproduced by instrumentation in
                    # `internal_tools/probe_scope_gap.py`, which records every event
                    # per port; before this, 2-4 of 12 fresh processes lost their
                    # scope this way in every run.
                    #
                    # NO evidence is stamped, deliberately: we did not act, and
                    # claiming knowledge we did not use would stop the poller's
                    # snapshot from healing the entry (see reconcile). Same rule the
                    # unmodelled event kinds already follow.
                    self._events += 1
                    return
                self._ports[port] = pid
                self._evidence[port] = self.clock()
            elif ev.kind == CLOSE:
                # pid-checked: a late CLOSE for a port the OS has already handed to
                # a DIFFERENT process must not evict the new owner. Windows reuses
                # both PIDs and ports, so "same port" is not "same socket".
                if self._ports.get(port) == pid:
                    del self._ports[port]
                # Stamped even when the pid did NOT match, and even though the map
                # did not change: the driver still told us something current about
                # this port, and the stamp is about how fresh our knowledge is, not
                # about whether it moved. It is what stops an older snapshot from
                # resurrecting the socket this event just closed - the tombstone.
                self._evidence[port] = self.clock()
            # An event kind this map does not model leaves no evidence: blocking a
            # snapshot on the strength of something we did not act on would be
            # claiming knowledge we do not have.
            self._events += 1
        # OUTSIDE the lock, and after the map is already updated. Three reasons, and
        # the third is the one that would be expensive to rediscover: a listener must
        # not be able to delay an event reaching the map, a listener that throws must
        # not lose one, and holding ``_lock`` across a call into somebody else's code
        # would make the lock ORDER cyclic - targeting's adoption path holds its own
        # lock while reading this map (``snapshot``), so a listener called under
        # ``_lock`` would close the circle into a deadlock between the watcher and
        # the resolver.
        #
        # Guarded HERE and not left to the loop's own crashlog.quiet, even though
        # that would also catch it: this is somebody else's code running on OUR
        # thread, so its failure deserves its own name in the crash log rather than
        # arriving as "socketwatch.apply broke" - and `apply()` keeps its promise of
        # never raising, whoever calls it.
        if ev.kind in _ADD:
            listener = self._on_socket
            if listener is not None:
                with crashlog.quiet("socketwatch.listener"):
                    listener(port, pid)

    def reconcile(self, port_pid, collected_at):
        """Merge a socket-table snapshot in (bootstrap + safety net).

        ``collected_at`` is when the snapshot's DATA was gathered - not when this
        call happens. Ask ``portmap.PortTable.collected()`` for the pair; the two
        must come from one lock hold, or the stamp can run ahead of its own data.
        There is deliberately NO default: a caller that forgets it must fail loudly
        at the call, because both call sites sit inside exception handlers
        (``crashlog.quiet`` at bootstrap, the watchdog's ``except`` per tick) that
        would otherwise turn a missing argument into "the safety net silently
        stopped running" - which looks exactly like a healthy session.

        The snapshot (``portmap`` -> ``GetExtendedTcp/UdpTable``) is the COMPLETE
        list of open sockets as of ``collected_at``. Complete is not current: see
        the module docstring for what merging it unconditionally cost (1394
        resurrections and 11 owner reverts in 25 s, measured on a live session). So
        a snapshot entry is applied only when the snapshot was collected AFTER
        whatever an event last told us about that port, and a port an event touched
        since then does not count as "absent" either - the snapshot never had a
        chance to see it, so its silence says nothing.

        The two-pass grace SURVIVES that rule rather than being replaced by it. The
        collection itself takes time, so a socket opened during it can be newer than
        ``collected_at`` by microseconds and still be missing from the result; the
        grace is the belt to the stamp's braces. Ports the snapshot no longer lists
        are therefore pruned only after being absent - and legitimately absent - for
        TWO reconciles running.

        ``_evidence`` is rebuilt here rather than growing forever: a tombstone is
        kept while it can still veto a snapshot (its stamp is newer than this one),
        and dropped once a snapshot collected after the close has agreed the port is
        gone. Its size is therefore (open sockets + the churn of one refresh
        interval), not (every socket this session ever saw).

        The new state is built to the side and PUBLISHED BY REASSIGNMENT rather than
        mutated in place, because ``pid_for`` reads this map WITHOUT a lock from the
        capture thread: a reader has to see this pass either not at all or completely,
        never with half the snapshot folded in and half the prunes applied.
        """
        with self._lock:
            merged = dict(self._ports)
            evidence = self._evidence
            for port, pid in port_pid.items():
                if (port and pid and pid > 0
                        and evidence.get(port, _NEVER) < collected_at):
                    merged[port] = pid
            # Absent AND stale: a port an event touched after this snapshot was
            # collected is not missing from it, it is younger than it.
            absent = {port for port in merged
                      if port not in port_pid
                      and evidence.get(port, _NEVER) < collected_at}
            doomed = absent & self._suspect          # absent twice running
            for port in doomed:
                merged.pop(port, None)
            self._suspect = absent - doomed          # first-time absentees wait one pass
            self._evidence = {port: at for port, at in evidence.items()
                              if port in merged or at >= collected_at}
            self._ports = merged                     # atomic swap for lock-free readers
            self._reconciles += 1

    def snapshot(self):
        with self._lock:
            return dict(self._ports)

    def pid_for(self, port):
        """Owning pid for a local port (``None`` when unknown). Takes NO LOCK.

        The CAPTURE THREAD reads this (``engine._pid_for``), and a lock here would be
        precisely the thing this module must not do: the watcher thread holds ``_lock``
        on every socket event, and ``reconcile`` holds it across a whole snapshot
        merge, so the packet path would queue behind maintenance. A stalled capture
        thread means WinDivert is diverting into a queue nobody drains (convention 20).

        Lock-free is safe for the same reason it is in
        :meth:`beantester.portmap.PortTable.pid_for`, with one addition. The reference
        is read ONCE into a local, and a dict lookup on INT keys is C code that neither
        releases the GIL nor calls back into Python, so it cannot interleave with
        another thread's insert or delete: a reader sees the map either before or after
        that write, never mid-resize. ``reconcile`` then publishes a NEW dict by
        reassignment, so its O(n) pass is atomic to a reader instead of being observed
        halfway through. Verified under load, not assumed - see
        ``test_socketwatch.py::test_a_lock_free_reader_survives_writes_in_flight``.
        """
        if port is None:
            return None
        ports = self._ports            # one atomic reference read, then a C-level get
        return ports.get(int(port))

    # -- name resolution: delegated, never duplicated -------------------------- #
    def refresh(self, now=None, force=False):
        """No-op: the map is kept live by events, not by a periodic rebuild.

        Present so a ``ProcessTargeting`` can call ``table.refresh()`` on this
        object exactly as it does on a ``PortTable`` (the resolver still calls it;
        here it simply has nothing to do). The freshness the poller bought with
        this call is bought by the event stream instead.
        """
        return False

    def name_of(self, pid, cheap=False):
        return self._names.name_of(pid, cheap=cheap)

    def ancestors(self, pid, depth=8):
        return self._names.ancestors(pid, depth=depth)

    # -- lifecycle (driven by BeanEngine) -------------------------------------- #
    def start(self):
        """Open the event source and start the reader thread. Idempotent."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping.clear()
            self._source = self._source_factory()
            self._thread = threading.Thread(target=self._loop,
                                            name="bean-socket-watcher", daemon=True)
            self._thread.start()

    def stop(self, timeout=0.25):
        """Close the source (unblocking the reader) and join briefly."""
        with self._lock:
            self._stopping.set()
            source, self._source = self._source, None
            thread, self._thread = self._thread, None
        if source is not None:
            with crashlog.quiet("socketwatch.close"):
                source.close()
        if (thread is not None and thread.is_alive()
                and thread is not threading.current_thread()):
            thread.join(timeout=timeout)

    def is_running(self):
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def events(self):
        return self._events

    @property
    def reconciles(self):
        return self._reconciles

    def _loop(self):
        source = self._source
        if source is None:
            return
        try:
            for ev in source:
                if self._stopping.is_set():
                    break
                with crashlog.quiet("socketwatch.apply"):
                    self.apply(ev)
        except Exception as exc:
            # stop() closes the source to end this loop, and on Windows a blocked
            # recv() then raises (WinError 995, "I/O aborted"). That is the NORMAL
            # shutdown path, not a fault - recording it made every STOP leave a
            # spurious crash entry. Only an error while we are NOT stopping means the
            # socket stream really died, which is traffic the tester asked to impair
            # sailing through - worth one traceback. Mirrors the capture loop's
            # ``if self._running`` guard.
            if not self._stopping.is_set():
                crashlog.once("socketwatch.loop", exc)


# -- the real Windows source (smoke-tested, not unit-tested) ------------------- #
class _WinDivertSocketSource:
    """Sniff-only SOCKET-layer handle, yielding normalised ``SocketEvent``s.

    ``pydivert`` is imported lazily (win32-only dependency; ``import beantester``
    must not require it - layering contract). SNIFF | RECV_ONLY cannot drop or
    modify a packet, so opening this alongside the engine's impairing NETWORK
    handle changes nothing about the traffic.
    """

    FILTER = "tcp or udp"

    def __init__(self):
        import pydivert
        from pydivert.consts import Layer, Flag
        self._handle = pydivert.WinDivert(self.FILTER, layer=Layer.SOCKET,
                                          flags=Flag.SNIFF | Flag.RECV_ONLY)
        self._handle.open()

    def __iter__(self):
        for pkt in self._handle:
            sock = pkt.socket
            if sock is None:
                continue
            yield SocketEvent(kind=int(pkt.event), pid=int(sock.ProcessId),
                              local_port=int(sock.LocalPort))

    def close(self):
        with crashlog.quiet("socketwatch.source.close"):
            self._handle.close()


def windivert_socket_source():
    """Factory for the real source (default). Raises off Windows / without pydivert."""
    return _WinDivertSocketSource()
