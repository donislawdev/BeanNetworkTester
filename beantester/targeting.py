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
* since 2026-08-04 the live socket map does not wait to be asked at all: it
  **pushes** each new socket in (``note_socket``), so a new connection of a
  process already targeted is in scope from its event, and a process nobody has
  judged yet is resolved by itself (``adopt_new_pids``) instead of at the next
  tick. MEASURED against the real driver, 12 fresh processes each opening one
  short connection: **4 of 12 were never in scope at all** before this, 1 of 96
  after (the residual that remained once the System-event bug below was found and
  fixed - see ``socketwatch.apply``),
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
        # A SECOND, deliberately tiny lock, held for microseconds and never across
        # anything that can block. `_lock` is held by refresh() for the whole walk
        # of the socket table (milliseconds), and the WATCHER thread must never
        # queue behind that: it is the thread that has to apply a SOCKET event
        # before the SYN it precedes by ~0.02 ms.
        self._ports_lock = threading.Lock()
        self._ports = frozenset()
        self._names = ()
        self._pids = frozenset()
        self._refreshes = 0
        # ``{port: pid}`` for every socket the live map handed us since the last
        # publish. Kept so a refresh that started BEFORE such an event cannot publish
        # a set computed without it - the same "an older snapshot must not undo a
        # newer event" rule the socket map itself lives by, one layer up. The OWNER
        # travels with the port because the rebuild has to be able to ask "is this
        # still ours?", and the answer belongs to the event, not to whatever the
        # table happens to say a moment later.
        self._late_owners = {}
        # pids the live map has seen that we have not judged yet, and the ones we
        # have judged as not ours. Both are cleared at every full rebuild, so
        # neither can grow beyond the churn of one refresh interval.
        self._pending_pids = frozenset()
        self._not_ours = frozenset()
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

    def _pid_matches(self, pid, name):
        """Does this pid belong to the target - itself, or through its tree?

        THE rule, in one place. It used to be inline in ``refresh``'s loop, and
        ``adopt_new_pids`` needs exactly the same answer: two copies of "what counts
        as the target" would drift at the first edit, and the drift would be silent
        (one path would impair a process the other does not).
        """
        if self._matches(pid, name):
            return True
        if self._excluded(pid, name):
            return False          # an explicit "!" wins over an inherited match
        for ancestor_pid, ancestor_name in self.table.ancestors(pid):
            if self._matches(ancestor_pid, ancestor_name):
                return True
        return False

    def refresh(self, now=None, force=True):
        """Rebuild the port set from the current socket table."""
        now = self.clock() if now is None else now
        with self._lock:
            # Emptied HERE, before the walk, and it used to be emptied at the end
            # of it. Two things follow, and both matter:
            #
            # * a walk that FAILS no longer leaves the dict behind. It is only ever
            #   cleared on success, so a socket table that kept hiccupping left
            #   this growing - and worse than growing, growing STALE: the rescue
            #   below keeps a port whose recorded owner is still targeted, so once
            #   a refresh finally succeeded it could put a port back in scope whose
            #   socket had closed long before, and which the OS may since have
            #   handed to somebody else. That breaks the "until the next rebuild"
            #   bound this class documents and that the recycled-pid guard pins.
            # * what survives the walk is now exactly what the walk could not have
            #   seen - a port noted BEFORE the collection started is in the fresh
            #   snapshot already if its socket is still open, and if it is not, it
            #   has no business being rescued.
            #
            # The bound is therefore TEMPORAL (one walk) rather than numeric, which
            # is what a ceiling like MAX_PENDING_PIDS below is approximating: the
            # dict is keyed by PORT, so it could never exceed the port space, and
            # a count would only start dropping legitimate rescues in a burst.
            with self._ports_lock:
                self._late_owners = {}
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
                if self._pid_matches(pid, name):
                    pids.add(pid)
                    names.add(name or str(pid))
            resolved = frozenset(port for port, pid in port_pid.items() if pid in pids)
            with self._ports_lock:
                # A late port is rescued only if the owner its EVENT named still
                # matches. Merging them blindly kept a port whose pid this very walk
                # had just dropped, so a recycled pid stayed in scope for two
                # rebuilds instead of one - silently doubling the exposure this class
                # documents as "until the next rebuild".
                #
                # INSIDE the lock, and that is not tidiness either: the watcher
                # thread writes this dict, so reading it outside was a
                # "dictionary changed size during iteration" waiting for a busy
                # machine. Caught by test_concurrency_chaos.py::
                # test_the_live_map_pushes_into_targeting_while_the_resolver_rebuilds
                # within seconds - it is a dict of the churn of one interval, so the
                # comprehension is short and the lock stays a microsecond affair.
                late = frozenset(port for port, owner in self._late_owners.items()
                                 if owner in pids)
                # REPLACED, never unioned: a pid that no longer matches has to fall
                # out here, and that is the whole bound on the recycled-pid window
                # (test_targeting_socketwatch.py::
                #  test_a_recycled_pid_is_in_scope_until_the_next_rebuild_and_no_longer).
                self._pids = frozenset(pids)
                # ...but a port the live map handed us WHILE this walk was running is
                # newer than the walk, so it survives it - if it is still ours (see
                # `late` above). It is part of _ports from here on, and the next
                # walk empties the dict again before it starts.
                self._ports = resolved | late
                self._pending_pids = frozenset()
                self._not_ours = frozenset()
            self._names = tuple(sorted(n for n in names if n))
            self._refreshes += 1
            return self._ports

    # -- what the live socket map tells us, as it happens ---------------------- #
    # A ceiling on the queue below, because it is fed by every socket event on the
    # machine and a burst of new processes must not turn into an unbounded queue of
    # OS lookups. Whatever spills is picked up by the routine rebuild, which is
    # where all of this lived before.
    MAX_PENDING_PIDS = 256

    def note_socket(self, port, pid):
        """A socket-layer ADD event: one new socket, its owner, right now.

        THE WATCHER THREAD CALLS THIS, once per socket event on the machine. It
        must not block, must not touch the OS and must not raise - it sits between
        the driver and the map that the packet path reads.

        Two cases, and they are different problems:

        * **a process we already target opens a socket.** Its port goes into scope
          immediately instead of at the next rebuild. ``owner_targeted`` already
          covers the SYN of such a flow, but only if the event beat the SYN by the
          0.02 ms it usually has - and when it loses that race NOTHING asks again,
          because ordinary TCP data deliberately never consults the live map
          (``BeanCore.decide`` step 1). So the flow used to stay unimpaired until a
          rebuild, up to 0.30 s later, which for a browser's short-lived connection
          means for ever. This is the path that closes that.
        * **a pid we have never judged.** Deciding needs a name lookup and the
          matcher, which is OS work and cannot happen here. The pid is queued and
          the resolver is woken; see ``adopt_new_pids``. MEASURED 2026-08-04 on why
          this matters: 12 fresh processes each opening one short connection, target
          by name, **4 of 12 were never in scope at all** - the process appeared and
          finished between two rebuilds.
        """
        if pid in self._pids:
            with self._ports_lock:
                if port not in self._ports:
                    self._ports = self._ports | {port}
                self._late_owners[port] = pid
            return
        if pid in self._not_ours or pid in self._pending_pids:
            return
        with self._ports_lock:
            if len(self._pending_pids) < self.MAX_PENDING_PIDS:
                self._pending_pids = self._pending_pids | {pid}
        wake = self._on_miss
        if wake is not None:
            wake()

    def adopt_new_pids(self):
        """Judge the pids the live map has just seen. RESOLVER THREAD. Returns
        whether anything was adopted.

        One name lookup and one matcher run per NEW pid - not a walk of the whole
        socket table, which is what a full ``refresh`` costs and what the miss floor
        exists to rate-limit. That is the point: a brand-new process can be adopted
        in the milliseconds after its first socket event instead of waiting for the
        next tick, without making the tick itself any cheaper to trigger.
        """
        with self._ports_lock:
            pending, self._pending_pids = self._pending_pids, frozenset()
        if not pending:
            return False
        with self._lock:              # serialise with refresh(): same table reads
            matched, names, judged = set(), set(), set()
            for pid in pending:
                name = self.table.name_of(pid)
                if self._pid_matches(pid, name):
                    matched.add(pid)
                    names.add(name or str(pid))
                elif name:
                    judged.add(pid)
                # An EMPTY name is "I could not tell", not "not ours", and the two
                # must not share an answer (the same distinction driver.py draws
                # between NO_ACCESS and "not installed"). A process that has just
                # started does not always resolve on the first ask, and caching that
                # as a refusal would ignore every later socket it opens until the
                # next full rebuild - which is the exact window this path exists to
                # close. Left unjudged, it is asked again at its next socket.
            if not matched:
                with self._ports_lock:
                    self._not_ours = self._not_ours | judged
                return False
            # Their ports, from the live map - including sockets this pid opened
            # while we were deciding.
            owners = {port: owner for port, owner in self.table.snapshot().items()
                      if owner in matched}
            ports = frozenset(owners)
            with self._ports_lock:
                self._pids = self._pids | matched
                self._ports = self._ports | ports
                for port in ports:
                    self._late_owners[port] = owners[port]
                self._not_ours = self._not_ours | judged
            self._names = tuple(sorted(set(self._names) | names))
        return True

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

        Two limits, both deliberate, both measured rather than assumed. The FIRST
        of them is what ``note_socket``/``adopt_new_pids`` were added for in
        2026-08: they do not make this function cleverer, they make ``_pids``
        (and ``_ports``) arrive sooner, which is where both limits come from.

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

          Closing the one-connection gap for the FIRST PACKET is not a tuning
          question, and that has not changed. The SOCKET event beats the SYN by
          0.018-0.027 ms; deciding a brand-new pid inside that window means a
          name resolve and the matcher, and a COLD name resolve is milliseconds.
          Moving it to the watcher thread does not help - the window is the same.
          The only design that closes it holds the SYN until the answer is in,
          i.e. adds delay inside a tool whose job is to inject a PRECISE amount
          of it.

          What DID change (2026-08-04) is everything after that first packet.
          The answer used to arrive at the next rebuild, so a connection that
          finished sooner was never impaired at all; ``adopt_new_pids`` now
          resolves the new pid off the event, in the milliseconds after it.
          MEASURED with fresh processes each opening ONE short connection
          (0.15 s): **4 of 12 were never in scope** before, and **1 of 96 across
          eight runs** after.

          Getting from "2 of 82" to that took finding a second, older bug, and
          the instrumentation is what found it: recording when the live map
          announced each socket, when its port entered scope AND WHEN IT LEFT
          showed ports falling out of scope 15-32 ms into a 240 ms connection.
          The cause was not here at all - the SOCKET layer hands the same port a
          second CONNECT carrying ProcessId 4, and the map applied it (see
          ``socketwatch.apply``). The rig lives in
          ``internal_tools/probe_scope_gap.py``.
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


def ports_shared_with_others(pids, table=None):
    """``{port: frozenset(other pids)}`` - target ports that other processes hold too.

    Why this exists, and why it only WARNS. A socket table row is ``(protocol,
    family, local port) -> pid``, and :mod:`beantester.portmap` collapses all four
    tables into ``port -> pid``, so a port several processes hold keeps one of them.
    That is not a rounding error, it decides what gets impaired - MEASURED
    2026-07-30 against the real table:

    * targeting ``Spotify.exe`` left port 1900 (SSDP) and 5353 (mDNS) OUT of its
      port set, so its own traffic there was never touched;
    * targeting ``msedge.exe`` put 5353 IN, together with svchost's, Spotify's and
      adb's traffic on the same port - three processes impaired that nobody asked
      for;
    * and on 5353 the winner is not even stable: across 40 walks 0.25 s apart it
      was Spotify 32 times, adb 6, msedge 2, so scope flickers at the resolver's
      rebuild rate.

    It is not fixable by a better key. Three of the four shared ports found were
    several processes on the SAME protocol and family (``SO_REUSEADDR`` multicast:
    DHCP, SSDP, mDNS), where the local port genuinely does not identify the owner -
    see the ADR in PROJECT_NOTES. What CAN be fixed is the silence, which is this.

    ``table`` defaults to the polling table on purpose, even in a session where
    targeting resolves against the live ``SocketWatcher``: this asks about the
    OPERATING SYSTEM's socket table, not about how the tool learned a mapping.
    Returns ``{}`` for a table that cannot answer (a test double, a non-Windows
    fallback) - a missing diagnostic must never break the thing it describes.
    """
    if not pids:
        return {}
    table = table if table is not None else portmap.default_table()
    getter = getattr(table, "shared_ports", None)
    if getter is None:
        return {}
    targeted = set(pids)
    out = {}
    for port, owners in getter().items():
        others = frozenset(owners) - targeted
        if others and (set(owners) & targeted):
            out[port] = others
    return out


def resolve_ports(matcher, table=None):
    """One-shot resolution: ``(ports, description)`` for a compiled matcher.

    Used by the CLI/GUI when they only want to *report* what an expression
    resolves to right now (``find_process_ports``).
    """
    targeting = ProcessTargeting(matcher, table=table)
    targeting.refresh()
    return targeting.ports(), targeting.describe()
