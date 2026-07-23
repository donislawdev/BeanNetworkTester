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
happens". Measured (spike, 2026-07-22): ``SOCKET_CONNECT`` arrives ~0.1 ms
*before* the outbound SYN reaches the NETWORK layer, so the mapping is ready
before the connection's first packet - the race the polling design could only
shrink is closed at the source. (``FLOW_ESTABLISHED`` was measured ~28 ms LATER,
i.e. after the handshake, which is why the SOCKET layer, not the FLOW layer, is
the source here.)

Scope of this module (chunk 2a): the map and its event handling, in isolation.
It is NOT wired into the engine or targeting yet (2b/2c). The event SOURCE is
injected, so the map is fully testable without WinDivert; the real Windows source
lives here too but is exercised by the smoke, not the unit tests.

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
# (and its tests) never touch pydivert. remote_ip/remote_port are carried for the
# connection log later (2c); the map itself keys on local_port only.
SocketEvent = namedtuple(
    "SocketEvent", "kind pid proto local_port remote_ip remote_port outbound")


def _ipv4(addr):
    """WinDivert stores the IPv4 address in ``addr[0]``, MSB = first octet.

    Verified against a known local IP in the 2026-07-22 spike: the naive
    low-byte-first decode produced ``192.168.1.29`` reversed as ``29.1.168.192``,
    so the octets are read high-to-low here.
    """
    try:
        v = int(addr[0]) & 0xFFFFFFFF
    except Exception:
        return ""
    return ".".join(str((v >> s) & 0xFF) for s in (24, 16, 8, 0))


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
        self._suspect = set()            # ports absent from the last snapshot (grace)
        self._source = None
        self._thread = None
        self._stopping = threading.Event()
        self._events = 0                 # applied-event counter (tests/diagnostics)
        self._reconciles = 0

    # -- the map --------------------------------------------------------------- #
    def apply(self, ev):
        """Fold one socket event into the map. Never raises on junk input."""
        port, pid = ev.local_port, ev.pid
        if not port or not pid or pid <= 0:
            return                        # no local port yet, or the idle/System 0
        with self._lock:
            if ev.kind in _ADD:
                self._ports[port] = pid
            elif ev.kind == CLOSE:
                # pid-checked: a late CLOSE for a port the OS has already handed to
                # a DIFFERENT process must not evict the new owner. Windows reuses
                # both PIDs and ports, so "same port" is not "same socket".
                if self._ports.get(port) == pid:
                    del self._ports[port]
            self._events += 1

    def reconcile(self, port_pid):
        """Merge a socket-table snapshot in (bootstrap + safety net).

        The snapshot (``portmap`` -> ``GetExtendedTcp/UdpTable``) is the complete,
        current list of OPEN sockets, so it is authoritative for what should be in
        the map; the events keep it live between snapshots. Ports the snapshot no
        longer lists are pruned only after being absent for TWO reconciles running,
        which spares a socket opened microseconds before the snapshot was taken
        (present via its event, not yet in that snapshot) from being evicted by it.
        """
        with self._lock:
            for port, pid in port_pid.items():
                if port and pid and pid > 0:
                    self._ports[port] = pid
            absent = set(self._ports) - set(port_pid)
            doomed = absent & self._suspect          # absent twice running
            for port in doomed:
                self._ports.pop(port, None)
            self._suspect = absent - doomed          # first-time absentees wait one pass
            self._reconciles += 1

    def snapshot(self):
        with self._lock:
            return dict(self._ports)

    def pid_for(self, port):
        if port is None:
            return None
        with self._lock:
            return self._ports.get(int(port))

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

    # -- lifecycle (driven by BeanEngine in 2b) -------------------------------- #
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
            yield SocketEvent(
                kind=int(pkt.event), pid=int(sock.ProcessId),
                proto=int(sock.Protocol), local_port=int(sock.LocalPort),
                remote_ip=_ipv4(sock.RemoteAddr), remote_port=int(sock.RemotePort),
                outbound=bool(pkt.is_outbound))

    def close(self):
        with crashlog.quiet("socketwatch.source.close"):
            self._handle.close()


def windivert_socket_source():
    """Factory for the real source (default). Raises off Windows / without pydivert."""
    return _WinDivertSocketSource()
