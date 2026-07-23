"""Process targeting: which LOCAL ports belong to the targeted processes.

Why this is not just "a set of ports"
-------------------------------------
The old implementation resolved the target expression into a plain ``set`` of
local ports every 2 seconds. Two things escaped it, and both were reported from
the field ("I target chrome and the browser keeps working"):

1. **New sockets.** A browser opens connections continuously; each one gets a
   fresh ephemeral port that is not in the set yet, so every packet of it was
   passed through untouched until the next scan - up to 2 seconds of perfectly
   healthy traffic.
2. **Child processes.** ``chrome.exe`` (the browser process) owns no sockets at
   all - its *network service* child does. Targeting the browser's PID resolved
   to zero ports, i.e. to nothing at all.

So targeting is a live object instead:

* its port set is rebuilt on a routine tick (300 ms by default, cheap thanks to
  :mod:`beantester.portmap`) by :class:`~beantester.target_resolver.TargetResolver`,
  which also owns the pacing - this class holds no timing knobs of its own,
* an **unknown port asks for an early rebuild**, which shrinks the "new socket
  slips through" window from seconds to tens of milliseconds,
* a socket belongs to the target when its owning process **or any of its
  ancestors** matches the expression - so a PID (or a name) covers the whole
  process tree. An explicitly EXCLUDED process (``!chromedriver``) is never
  pulled back in by its parent.

``BeanCore.decide()`` keeps its ``local_port not in target_ports`` test: this
class simply *is* the container it tests against (``__contains__``).

Who does the rebuilding, and where
----------------------------------
``__contains__`` runs in the PACKET PATH, inside ``BeanCore._lock``, at up to
150 000 calls a second. It therefore does no work beyond a frozenset lookup.

It used to call ``refresh()`` itself, which meant the capture thread paid for
four ``iphlpapi`` calls, an O(n) dict copy and a ``psutil.Process()`` per distinct
PID - occasionally a whole ``process_iter()`` - while holding the core lock. And
that was not a rare path: targeting exists to narrow traffic to one application,
so every packet from every OTHER application is a MISS, which made the rebuild a
steady 20 Hz whenever a target was set. A stalled capture thread is exactly the
failure WinDivert punishes: it keeps diverting into a queue nobody drains, so the
user loses connectivity while the UI still says "running".

Now a miss only sets a flag and wakes :class:`~beantester.target_resolver.TargetResolver`,
which rebuilds on its own thread. The flag is the reason the wake-up is free:
``Event.set()`` takes a lock, so it is called only on the FALSE -> TRUE transition,
at most once per resolver cycle, while the flag itself is a plain bool (atomic
under the GIL). ``refresh()`` stays public and synchronous for one-shot callers
(``resolve_ports``, ``make_targeting``) and for tests.

The race, and where it is (and is not) closed - documented on purpose, because a
"prawdziwie brzmiaca" claim that it is unclosable lived here for a long time and
was wrong (PROJECT_NOTES rule 6):

* against the **polling** port table (:class:`~beantester.portmap.PortTable`, the
  fallback when there is no real WinDivert), WinDivert hands us a packet, not a
  PID, so the mapping is a snapshot race - it can be made small, not closed, and
  the first packet of a brand-new connection may slip through;
* against the **live SOCKET-event map** (:class:`beantester.socketwatch.SocketWatcher`,
  the default in a real session since chunk 2c), the race is closed for outbound
  connections: the SOCKET_CONNECT event is delivered before the SYN reaches the
  NETWORK layer (measured ~0.1 ms ahead), so the port is already mapped when the
  first packet arrives. ``set_table`` is how the engine points this at one or the
  other.
"""
import threading
import time

from . import portmap


class ProcessTargeting:
    """The set of local ports owned by the processes matching an expression."""

    def __init__(self, matcher, table=None, clock=time.monotonic):
        # No interval/miss_interval here any more. They used to drive the rate
        # limiting inside __contains__; the pacing now lives entirely in
        # TargetResolver, and leaving dead knobs on the constructor would invite
        # somebody to tune something that controls nothing.
        self.matcher = matcher
        self.expression = getattr(matcher, "raw", str(matcher))
        self.table = table if table is not None else portmap.default_table()
        self.clock = clock
        self._lock = threading.RLock()
        self._ports = frozenset()
        self._names = ()
        self._pids = frozenset()
        self._refreshes = 0
        # Set by the packet path when it is asked about a port it does not know;
        # cleared by the resolver before each rebuild. A plain bool on purpose -
        # reads and writes are atomic under the GIL, so the hot path pays nothing.
        self._miss = False
        self._on_miss = None        # the resolver's wake-up, when one is attached

    # -- resolution ----------------------------------------------------------- #
    def _matches(self, pid, name):
        return bool(self.matcher.matches(pid, name))

    def _excluded(self, pid, name):
        excluded = getattr(self.matcher, "excluded", None)
        return bool(excluded(pid, name)) if excluded else False

    def refresh(self, now=None, force=True):
        """Rebuild the port set from the current socket table."""
        now = self.clock() if now is None else now
        with self._lock:
            self.table.refresh(force=force)
            port_pid = self.table.snapshot()
            pids, names = set(), set()
            for pid in set(port_pid.values()):
                # Names must resolve even for HARDENED processes (Chrome's network
                # service refuses OpenProcess), or targeting `chrome` by NAME matches
                # nothing while targeting its PID works. That is why the name lookup is
                # allowed its snapshot fallback - now a ~6 ms native toolhelp snapshot,
                # not the ~2 s psutil.process_iter that used to make the first
                # target-start crawl (see portmap._process_table).
                name = self.table.name_of(pid)
                if self._matches(pid, name):
                    pids.add(pid)
                    names.add(name or str(pid))
                    continue
                if self._excluded(pid, name):
                    continue      # an explicit "!" wins over an inherited match
                for ancestor_pid, ancestor_name in self.table.ancestors(pid):
                    if self._matches(ancestor_pid, ancestor_name):
                        pids.add(pid)
                        names.add(name or str(pid))
                        break
            self._pids = frozenset(pids)
            self._ports = frozenset(port for port, pid in port_pid.items()
                                    if pid in pids)
            self._names = tuple(sorted(n for n in names if n))
            self._refreshes += 1
            return self._ports

    def set_table(self, table):
        """Swap the socket table this resolves against (poller <-> live watcher).

        The engine points targeting at the live SOCKET-event map
        (:class:`beantester.socketwatch.SocketWatcher`) when a session has one, and
        back at the polling :class:`~beantester.portmap.PortTable` otherwise (no real
        WinDivert, or the SOCKET handle could not open). Both expose the same read
        surface (``snapshot`` / ``name_of`` / ``ancestors`` / ``refresh``), which is
        why the swap is a one-line reference change. The resolved port set is left as
        it is until the next ``refresh()`` (the resolver runs those continuously), so
        the swap never blips the hot-path ``__contains__``.
        """
        with self._lock:
            self.table = table if table is not None else portmap.default_table()

    # -- the container BeanCore tests against ---------------------------------- #
    def __contains__(self, port):
        """A frozenset lookup and nothing else. See "Who does the rebuilding".

        THE PACKET PATH CALLS THIS, inside ``BeanCore._lock``. It must not touch
        the socket table, psutil, or any lock of its own.
        """
        if port is None:
            return False
        if port in self._ports:
            return True
        # An unknown port is the interesting case: either traffic we do not care
        # about, or a connection the target opened microseconds ago. Only a fresh
        # scan can tell - so ask for one and get out of the way. The guard keeps
        # Event.set() (which takes a lock) to one call per resolver cycle instead
        # of one per packet.
        if not self._miss:
            self._miss = True
            wake = self._on_miss
            if wake is not None:
                wake()
        return False

    # -- resolver handshake ----------------------------------------------------- #
    def on_miss(self, callback):
        """Attach the resolver's wake-up (``None`` detaches it)."""
        self._on_miss = callback

    def consume_miss(self):
        """Take and clear the "somebody asked about an unknown port" flag.

        Called by the resolver BEFORE it rebuilds, so a miss that happens *during*
        the rebuild re-arms instead of being swallowed by it.
        """
        missed, self._miss = self._miss, False
        return missed

    @property
    def missed(self):
        return self._miss

    def __iter__(self):
        return iter(self._ports)

    def __len__(self):
        return len(self._ports)

    def __eq__(self, other):
        if isinstance(other, (set, frozenset)):
            return set(self._ports) == set(other)
        return NotImplemented

    def __hash__(self):                                   # pragma: no cover
        return hash(self._ports)

    def __repr__(self):                                   # pragma: no cover
        return f"<ProcessTargeting {self.expression!r} {len(self._ports)} ports>"

    # -- reporting -------------------------------------------------------------- #
    def ports(self):
        return set(self._ports)

    def pids(self):
        return set(self._pids)

    def names(self):
        return list(self._names)

    def describe(self):
        return ", ".join(self._names) if self._names else NO_PROCESS

    @property
    def matched(self):
        """True when at least one process (with a socket) matched."""
        return bool(self._pids)

    @property
    def refreshes(self):
        return self._refreshes


NO_PROCESS = "(none)"


def resolve_ports(matcher, table=None):
    """One-shot resolution: ``(ports, description)`` for a compiled matcher.

    Used by the CLI/GUI when they only want to *report* what an expression
    resolves to right now (``find_process_ports``).
    """
    targeting = ProcessTargeting(matcher, table=table)
    targeting.refresh()
    return targeting.ports(), targeting.describe()
