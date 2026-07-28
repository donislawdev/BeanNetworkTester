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
150 000 calls a second on the synthetic path (a real WinDivert session was
measured an order of magnitude below that - see "What this actually sustains" in
``engine.py``, the one place that number lives). It therefore does no work beyond
a frozenset lookup: the reason below is about what a MISS used to cost, and four
syscalls in the packet path are unaffordable at either rate.

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
  the default in a real session since chunk 2c), the ORDER is in our favour rather
  than left to chance: the SOCKET_CONNECT event is delivered before the SYN reaches
  the NETWORK layer, measured 2026-07-28 in 10 runs out of 10, by 0.018-0.027 ms.
  So the port can be mapped before the first packet is judged - but note the size
  of that margin: it is the gap at the DRIVER, and whether the watcher's own
  handling fits inside a few tens of microseconds is NOT measured. This used to say
  "the race is closed", which claimed more than the number supports.
  ``set_table`` is how the engine points this at one or the other.
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
        surface (``snapshot`` / ``name_of`` / ``ancestors`` / ``refresh``, plus
        ``pid_for`` since ``owner_targeted`` exists - both real tables have always had
        it, but it is part of the contract now), which is why the swap is a
        one-line reference change. The resolved port set is left as
        it is until the next ``refresh()`` (the resolver runs those continuously), so
        the swap never blips the hot-path ``__contains__``.
        """
        with self._lock:
            self.table = table if table is not None else portmap.default_table()

    def owner_targeted(self, port):
        """Is this port a brand-new socket of a process we ALREADY target?

        Named ``syn_covers`` until UDP was covered too, which made the old name a
        lie about when it runs - see ``BeanCore.decide`` step 1 for the callers.

        ``__contains__`` answers from ``_ports``, a frozenset rebuilt on another
        thread, so the first packet of a fresh flow is judged BEFORE any rebuild
        it triggers - it was never in scope, however early the SOCKET event
        arrived. MEASURED end to end 2026-07-28: 20 fresh connections against a
        process target with ``--syn-drop 100``, 20 SYNs straight through,
        ``drop_syn`` 0. The live map knew each owner 0.02 ms before its SYN;
        nothing consumed that.

        This is the one place that does. ``BeanCore.decide`` calls it for a TCP
        SYN (once per connection) and for anything that is not TCP, and it costs
        a lock-free dict read plus a frozenset lookup, no lock of its own.

        **Why not on every miss.** Asking for ordinary TCP data as well was
        measured on the real code across three traffic mixes and three map sizes
        (400 / 10 000 / 100 000 ports, median of 5): it costs **+209 to +266 ns
        per packet** on a TCP-heavy mix, about 26% of ``decide()``, while the form
        above is free there - within noise of not asking at all. The map's SIZE
        barely matters (400 -> 100 000 ports moved ``decide()`` by ~35 ns), so
        this is about how OFTEN each variant asks, not about the lookup.

        ``_pids`` is what the last rebuild concluded, so every expression form
        (name, PID, list, range, ``!`` exclusion, ancestor match) is already
        resolved into it. This does not re-run the matcher.

        Two limits, both deliberate, both measured rather than assumed:

        * ``_pids`` is rebuilt from the pids owning CURRENTLY OPEN sockets, so a
          target that has none when a rebuild runs drops out of it and its next
          connection is uncovered again. Measured with ``--syn-drop 100`` over 20
          fresh connections: a probe holding its sockets open was caught **19 of
          20** (only its first, before it had any socket, escaped), while the same
          probe closing each connection before the next was caught **6 of 20**.
          So this covers a target that keeps sockets - a browser, an app under
          test - and keeps missing one that opens a connection, closes it and
          pauses. Covering that needs the matcher and a name lookup in the packet
          path, which is what convention 20 forbids.

          A RESTARTING target is the same mechanism from the other side, and it
          was measured separately (2026-07-28, same probe, three lives of four
          held connections each, ``--syn-drop 100``): ``OK FAIL FAIL FAIL`` in
          **3 lives out of 3**. A target that dies and comes back under a new pid
          therefore costs exactly ONE connection - the one it opens before it
          owns any socket - and then recovers on its own, with no restart of the
          session. That recovery belongs to the EXPRESSION, not to this code: by
          NAME the new pid is matched by the next rebuild, by PID nothing can
          match again, because the number the user typed no longer exists. Same
          probe, targeting the pid, killed and restarted: **5 of 5** fresh
          connections untouched.

          Closing the one-connection gap is not a tuning question. The SOCKET
          event beats the SYN by 0.018-0.027 ms; covering a brand-new process
          would mean resolving pid -> name and running the matcher inside that
          window, and a COLD name resolve is milliseconds. Moving it to the
          watcher thread does not help - the window is the same. The only design
          that closes it holds the SYN until the answer is in, i.e. adds delay
          inside a tool whose job is to inject a PRECISE amount of it.
        * ``_pids`` goes stale when the target exits, and until the next rebuild a
          socket Windows hands that pid number is treated as the target's.
          **MEASURED against the real socket table 2026-07-28** (seven rounds per
          transport, no traffic, so every rebuild is the routine tick and this is
          the UPPER bound): a dead process leaves ``_pids`` after a median of
          **309 ms** (TCP, 271-327) and **315 ms** (UDP, 290-325) - the 0.30 s
          tick, and no more. TIME_WAIT does not stretch it, which was worth
          checking rather than assuming, since a TCP socket can outlive its owner.
          A live session misses constantly, which wakes the resolver and only
          shortens this toward the 0.05 s floor. This used to be a design claim
          ("up to one resolver cycle") with nothing behind it.

          **Covering UDP widened what fits in that window, and that is the price
          of it:** it used to be one SYN per connection, and it is now every UDP
          datagram of such a socket. Ordinary TCP data is still never asked, so an
          established TCP connection cannot be dragged in this way. That is a
          DIFFERENT false positive from the stale ``_ports`` this code already
          lived with - named here rather than implied. Nothing narrows the bound
          further: verifying identity means ``create_time()`` in the packet path,
          which convention 20 forbids. Guarded both ways by
          ``test_targeting_socketwatch.py::test_a_recycled_pid_is_in_scope_until_the_next_rebuild_and_no_longer``.
        """
        if port is None:
            return False
        # `pid_for` is asked of the table by getattr because `set_table` accepts
        # anything with the read surface, and a table that predates this (or a
        # test double) would otherwise raise AttributeError ON THE CAPTURE THREAD.
        pid_for = getattr(self.table, "pid_for", None)
        if pid_for is None:
            return False
        pid = pid_for(port)
        return pid is not None and pid in self._pids

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
