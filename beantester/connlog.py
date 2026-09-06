"""The session's connection log: one row per flow, and the eviction that caps it.

Carved out of ``engine.py`` on 2026-09-06, the same way ``damage.py`` was: this is
a store with its own state (rows, its own lock, its own sampling RNG) and its own
cap policy, and it was reachable only as seven methods on ``BeanEngine`` - which
had grown to 72.

**Why it may live behind one more attribute lookup.** The connection log is on the
per-packet path, so the question was asked before the move rather than after:
MEASURED 2026-07-29, disabling the WHOLE connection log is **1.012x** end to end
(the number and its conditions are in PROJECT_NOTES, "Gorace sciezki"). A feature
worth 1.2% of the pipeline cannot lose anything measurable to one attribute hop,
and the same section records that every remaining lever in this pipeline is
<= 1.02x. What is NOT negotiable is what the lock does and does not cover, so both
of those rules travel here in full, in the docstrings that carry their
measurements.

**Owner resolution stays on the engine.** ``process_for`` and ``pid_for`` arrive as
callables rather than being moved in with the rows, and that is deliberate: they
read the port table and the live socket map, both of which the engine swaps at
start and stop. A second reference to those, kept here and updated separately,
would be a new way for the two to disagree - and their two failure domains are
pinned by ``tests/test_owner_attribution.py``, which reads ``engine.py``.
"""
import heapq
import random
import threading


class ConnectionLog:
    """Flow rows for one session: ``flowkey -> dict``.

    Threading, and it is not uniform - each rule is measured where it is written:

    * ``log``, ``charge``, ``snapshot`` and ``trim`` take the lock.
    * ``credit_delivered`` deliberately does NOT - see its docstring.
    """

    # A connection row is ~350 B, so the cap IS the memory budget: 200k flows is
    # roughly 70-100 MB, which is what a long capture on a busy machine needs if
    # the tables are to show the session honestly instead of an arbitrary slice.
    MAX_CONNS = 200_000
    EVICT_KEEP = 0.9                    # trim back to this fraction of the cap
    EVICT_SAMPLES = 2000                # stamps sampled to estimate the cutoff

    def __init__(self, process_for, pid_for):
        self.rows = {}                  # connection log: flowkey -> stats
        self._lock = threading.Lock()
        # Sampling RNG for trim(). Deliberately NOT the engine's seeded RNG: that
        # one drives the packet decisions, so drawing from it here would make a
        # session's impairments depend on how often the table happened to be
        # trimmed - i.e. it would silently break reproducibility.
        self._rng_evict = random.Random(0)
        self._process_for = process_for
        self._pid_for = pid_for

    def __len__(self):
        return len(self.rows)

    def clear(self):
        with self._lock:
            self.rows.clear()

    def snapshot(self, limit=200):
        """Rows of the connection log.

        ``limit=<int>``  the ``limit`` most recently active flows, newest first.
                         Uses ``heapq.nlargest``: O(n log limit), not a full sort
                         of a table that may hold 200 000 rows.
        ``limit=None``   every flow, UNSORTED - a pointer copy, cheap (see below).
                         This is what the virtualised tables ask for: they sort by
                         the column the user picked anyway, so sorting here as well
                         was the same work done twice per refresh.

        The copy is taken under the lock; any sorting happens outside it. A sort
        under the lock would stall the CAPTURE thread, and a stalled capture
        thread means WinDivert is queueing the user's packets into a void. THAT is
        why the sort is outside - not the cost of the copy, which is small:

        Measured 2026-07-21 (Win11 AMD64, CPython 3.14.6, synthetic rows, median of
        7): the pointer copy is **0.7 ms at the 200k cap** and 2.4 ms at 500k, while
        a full sort of the same 200k rows through ``views.filter_sort_connections``
        is ~29 ms. An earlier revision of this docstring claimed ~25 ms for the copy
        and ~100 ms for the sort; neither reproduced.
        """
        with self._lock:
            values = list(self.rows.values())
        if limit is None:
            return values
        return heapq.nlargest(limit, values, key=lambda c: c["last"])

    def trim(self):
        """Evict the oldest flows once the log outgrows its cap.

        Runs on the WATCHDOG thread, never on the capture thread, and does the
        expensive part without the lock. The old version sorted the whole table
        from inside ``log()`` - i.e. on the capture thread, under the lock.
        At the previous 2000-row cap nobody could feel it; at 200 000 it is a
        ~300 ms freeze of the capture thread, and a frozen capture thread means
        WinDivert is quietly queueing (and then dropping) the user's packets.

        Measured at the cap: sorting = ~300 ms, a sampled cutoff = ~6 ms (no lock)
        plus a scan-and-delete = ~16 ms (lock held). The cutoff is an estimate,
        so the table lands near - not exactly on - ``EVICT_KEEP``; for dropping
        stale flows that is entirely good enough.
        """
        with self._lock:
            if len(self.rows) <= self.MAX_CONNS:
                return
            # a pointer copy, not a deep copy: cheap even at 200k
            values = list(self.rows.values())
        # ---- outside the lock: estimate the activity cutoff from a sample ----
        target_drop = len(values) - int(self.MAX_CONNS * self.EVICT_KEEP)
        if target_drop <= 0:
            return
        sample = [values[self._rng_evict.randrange(len(values))]["last"]
                  for _ in range(min(self.EVICT_SAMPLES, len(values)))]
        sample.sort()
        index = int(len(sample) * target_drop / len(values))
        cutoff = sample[min(index, len(sample) - 1)]
        # ---- lock again, only for the cheap part -----------------------------
        with self._lock:
            doomed = [k for k, c in self.rows.items() if c["last"] <= cutoff]
            # The cutoff is a SAMPLED estimate and the comparison is inclusive, so
            # rows sharing one timestamp all fall on the same side of it. With
            # enough ties that is far more than the estimate intended - and with
            # every row on one stamp it is the WHOLE table. Measured against a
            # 1000-row cap: 1200 rows trimmed to 0 instead of 900.
            #
            # Not reachable from ordinary traffic on this machine (time.monotonic()
            # resolves to ~100 ns here, so a 1200-row burst still produced 865
            # distinct stamps and trimmed correctly), but it costs one max() to
            # make the estimate incapable of emptying the log, and a coarser clock
            # is a platform property this code should not have to rely on.
            allowed = max(0, len(self.rows) - int(self.MAX_CONNS * self.EVICT_KEEP))
            for key in doomed[:allowed]:
                self.rows.pop(key, None)

    def log(self, key, remote_ip, remote_port, local_port, is_out, size, now,
            proto="IP", dropped=False, scoped=False):
        if key is None:
            return
        with self._lock:
            c = self.rows.get(key)
            if c is None:
                # NO eviction here: trimming is the watchdog's job (trim()).
                # Doing it on the capture thread meant a new flow could pay for a
                # full sort of the table while holding the lock.
                # bytes/bytes_in/bytes_out are what this flow OFFERED (captured);
                # sent/sent_in/sent_out are what actually went back on the wire.
                # The two used to be one set of numbers under headings the session
                # panel used for delivered - a row could read 5 122 600 B received
                # while the application got 409 600 B.
                c = dict(remote_ip=remote_ip, remote_port=remote_port,
                         local_port=local_port, proto=proto, packets=0, bytes=0,
                         bytes_in=0, bytes_out=0, sent=0, sent_in=0, sent_out=0,
                         dropped=0, first=now, last=now,
                         dir="", scoped=bool(scoped),
                         proc=self._process_for(local_port),
                         pid=self._pid_for(local_port))
                self.rows[key] = c
            elif not c["proc"]:
                # the socket may not have been in the table yet when the flow
                # appeared - try again while packets keep coming, otherwise the
                # row would stay a "?" forever (resolve the pid on the same retry)
                c["proc"] = self._process_for(local_port)
                if not c.get("pid"):
                    c["pid"] = self._pid_for(local_port)
            c["packets"] += 1
            c["bytes"] += size
            if is_out:
                c["bytes_out"] += size
            else:
                c["bytes_in"] += size
            if dropped:
                c["dropped"] += 1
            # scoped is STICKY: once a flow has been in impairment scope it stays
            # marked, for the life of the session's connection log. It is the audit
            # answer to "was this connection impaired", not "is its port in the
            # target set right now" - those differ the instant a socket closes, and
            # a browser closes hundreds a minute. A live check flipped every
            # finished flow to "not impaired" the moment it closed (its ephemeral
            # port left the socket table), so a run that impaired all of chrome read
            # as a table full of "no". The row highlight
            # (gui/pages/conns.py::_tag_of) reads this same stored record, so the
            # colour and the "impaired?" column can never disagree.
            c["scoped"] = c["scoped"] or bool(scoped)
            c["last"] = now
            c["dir"] = "out" if is_out else "in"
            c["proto"] = proto

    def credit_delivered(self, key, size, is_out):
        """Credit bytes that actually went back on the wire to their flow's row.

        Returns whether that row is SCOPED, so the caller can add the same bytes to
        the session's scoped totals - the flag lives on the row, and the engine owns
        the stats dict, so this is the seam between them. False when there was no
        row to credit.

        Called from the INJECT thread, once per delivered packet, and deliberately
        WITHOUT the lock - the same reasoning as ``SocketWatcher.pid_for`` (see
        convention 20): taking a maintenance lock on a per-packet path puts that
        path in the queue behind the watchdog's trimming. Measured with the lock:
        160.4k -> 152.0k pkt/s on the synthetic path, a 5% regression bought for
        nothing.

        Safe because ``sent``/``sent_in``/``sent_out`` have exactly ONE writer -
        this thread. The capture thread creates the row (with these at 0) BEFORE
        the packet is queued, and never touches them again; readers only ever read
        them, and an int rebind is atomic, so a reader sees the old value or the
        new one, never a torn one. Any other counter shared with the capture thread
        still goes through ``charge()``, which does take the lock.

        A row can be missing when the watchdog trimmed the flow while its packet
        sat in the delay queue. Then there is nothing to credit, and the row is
        gone from the table anyway.
        """
        if key is None:
            return False
        c = self.rows.get(key)
        if c is None:
            return False
        c["sent"] += size
        if is_out:
            c["sent_out"] += size
        else:
            c["sent_in"] += size
        return bool(c.get("scoped"))

    def charge(self, key, field, n=1):
        """Add to one counter on one flow's row (no row = nothing to charge).

        For losses discovered AFTER the capture thread has moved on: a queue that
        overflowed, a session that ended with packets still parked, an injection
        that failed. Those never reached the row before, so a flow could show
        `dropped=0` in a session that threw 5 500 of its packets away.
        """
        if key is None:
            return
        with self._lock:
            c = self.rows.get(key)
            if c is not None:
                c[field] += n
