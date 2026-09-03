"""Keeps the targeted port set fresh - on its own thread, never on the capture one.

Why this module exists
----------------------
``ProcessTargeting`` answers "does this local port belong to the targeted
process?". Answering it means reading the OS socket table and resolving PIDs to
process names, which costs four ``iphlpapi`` calls, an O(n) dict copy, a
``psutil.Process()`` per distinct PID and - whenever a protected PID refuses to
open - a whole ``psutil.process_iter()``.

All of that used to happen inside ``ProcessTargeting.__contains__``, i.e. inside
``BeanCore.decide()``, i.e. on the CAPTURE THREAD, while holding ``core._lock``.
And it was the normal case rather than an edge one: targeting exists to narrow
traffic to a single application, so every packet from every *other* application
is a miss, and a miss is what triggered the rebuild. With a target set, that was
a steady ~20 Hz of syscalls in the packet path.

A stalled capture thread is the one failure this tool must not have. WinDivert
keeps diverting packets into a queue nobody is draining, so the user quietly
loses connectivity - while the UI cheerfully reports "running". The whole
fail-open design (convention 20), the watchdog, and moving eviction and table
sorting off the hot path all exist to prevent exactly that. Targeting was the
last place still doing it.

Shape
-----
Deliberately the same shape as :mod:`beantester.scenario_runner`: a small class
that owns one background thread, with its lifecycle driven explicitly by
``BeanEngine`` (``start`` / ``stop``), rather than a leaf object that
self-starts a hidden daemon. Two differences, both on purpose:

* **``stop()`` joins.** The resolver holds OS handles; it must stop touching them
  the moment the session ends, not "eventually". (``ScenarioRunner.stop()`` only
  sets a flag.)
* **It waits on an ``Event``, not a ``sleep``.** A packet for an unknown port
  wakes it immediately, so a brand-new connection starts being impaired within
  tens of milliseconds instead of at the next tick.

ONE resolver per engine, with a swappable target: retargeting is a reference
swap, not a thread restart. Applying settings repeatedly - which the GUI does on
every "Apply", and the concurrency tests do hundreds of times - must not churn
threads.
"""
import threading
import time

from . import crashlog, portmap

REFRESH_S = portmap.REFRESH_S            # routine rebuild when nothing asks sooner
MIN_INTERVAL_S = portmap.MISS_REFRESH_S  # floor between miss-driven rebuilds


class TargetResolver:
    """Rebuilds one ``ProcessTargeting``'s port set on a background thread."""

    def __init__(self, interval=REFRESH_S, min_interval=MIN_INTERVAL_S):
        self.interval = float(interval)
        self.min_interval = float(min_interval)
        self._last_rebuild = 0.0
        self._targeting = None
        self._thread = None
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._rebuilds = 0

    # -- lifecycle (driven by BeanEngine) -------------------------------------- #
    def start(self):
        """Start the thread if it is not already running. Idempotent."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping.clear()
            self._thread = threading.Thread(target=self._loop, name="bean-target-resolver",
                                            daemon=True)
            self._thread.start()

    # Long enough that an IDLE resolver is always joined (it is parked in wait(),
    # so it exits in microseconds), short enough that a scan in flight can never
    # hold STOP up. Measured on a normal desktop: a cold resolve is 1.7 SECONDS
    # (25 PIDs own sockets but the info cache holds 346 - the expensive part is one
    # full psutil.process_iter()), against 1.4 ms once warm. Joining that would have
    # meant a 1.6 s STOP, and STOP is the control this tool may never make slow: it
    # is how the user undoes the damage they just did to their own network.
    #
    # Not joining is safe. stop() has already cleared _targeting and set _stopping,
    # so a straggler finishes at most one more scan - into an object nobody reads
    # any more - and then exits at its next loop check. It is a daemon either way.
    JOIN_S = 0.25

    def stop(self, timeout=JOIN_S):
        """Stop the thread, waiting only briefly - never for a scan in flight."""
        with self._lock:
            thread, self._thread = self._thread, None
            previous, self._targeting = self._targeting, None
            # Signalled INSIDE the lock, together with taking the thread. Setting
            # it afterwards left a window where a concurrent start() could clear
            # _stopping, spawn a fresh thread, and then have this set() kill it on
            # its first loop check. BeanEngine serialises start/stop under its own
            # lock so it cannot happen there today, but a threading primitive
            # should not depend on its caller to be safe.
            self._stopping.set()
            self._wake.set()                # unblock an idle wait()
        if previous is not None:
            # Detach, so a packet arriving late cannot poke the event of a resolver
            # that is no longer listening. Harmless either way, but a dangling
            # callback into a dead worker is the kind of thing that becomes a real
            # bug the next time somebody touches this.
            previous.on_miss(None)
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def retarget(self, targeting):
        """Point the resolver at a new targeting (``None`` = nothing to resolve).

        A reference swap, not a thread restart - see the module docstring.
        """
        with self._lock:
            previous, self._targeting = self._targeting, targeting
        if previous is not None and previous is not targeting:
            previous.on_miss(None)          # an orphan must not keep waking us
        if targeting is not None:
            targeting.on_miss(self._wake.set)
        self._wake.set()

    # -- introspection (tests, diagnostics) ------------------------------------ #
    def is_running(self):
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def rebuilds(self):
        return self._rebuilds

    # -- the worker ------------------------------------------------------------- #
    def _loop(self):
        while not self._stopping.is_set():
            targeting = self._targeting
            if targeting is None:
                self._wake.wait()           # nothing to resolve: sleep for free
                self._wake.clear()
                continue

            # BEFORE the floor, deliberately. The floor below rate-limits rebuilds
            # driven by PACKET misses, which arrive continuously - every packet of
            # every other application is one. A pid the live SOCKET map has never
            # seen is a different signal entirely: it happens once per new process,
            # and answering it costs one name lookup rather than a walk of the whole
            # socket table. Making it wait behind the packet floor is what left a
            # freshly spawned process unimpaired for up to 50 ms, and a process that
            # finished inside that window unimpaired for ever (measured: 4 of 12).
            #
            # Guarded like the rebuild below, and for the same reason: this asks the
            # OS for a process name, so it can fail the way any socket-table call
            # can. Unguarded, one such failure would end this THREAD, and a resolver
            # that has quietly died leaves the port set frozen for the rest of the
            # session - a session that looks like it is impairing and is not.
            try:
                targeting.adopt_new_pids()
            except Exception as exc:
                crashlog.note(exc, "targeting.adopt")   # note, not once: see below

            # THE FLOOR, and it is not optional. Targeting narrows traffic to one
            # application, so every packet from every OTHER application is a miss:
            # misses arrive CONTINUOUSLY, not occasionally. Without a minimum gap
            # the wake-up is re-armed as fast as it is consumed and this thread
            # scans the socket table without pause. Measured before this guard
            # existed: 63 rebuilds a second against a 0.3 s routine tick, bounded
            # only by the GIL. This is the ``miss_interval`` that used to live in
            # ``__contains__`` - same 0.05 s, enforced in one place instead of on
            # the capture thread.
            #
            # The cost of the floor is the worst-case delay before a brand-new
            # socket (a freshly spawned child process, say) starts being impaired:
            # up to min_interval. That is the trade the old code made too.
            since = time.monotonic() - self._last_rebuild
            if since < self.min_interval:
                # Waited on the DOORBELL, not on a plain sleep. The floor still
                # holds - no full rebuild happens before it expires - but a pid the
                # live map has just seen gets its cheap adoption at the top of the
                # loop instead of queueing behind a limit meant for packet misses.
                # Sleeping on `_stopping` here made a brand-new process wait the
                # whole floor, which is the 50 ms this was supposed to remove.
                # stop() sets both, so shutdown is just as prompt as before.
                self._wake.wait(timeout=self.min_interval - since)
                self._wake.clear()
                continue

            # Clear BEFORE consuming and rebuilding: a miss arriving while we are
            # inside refresh() sets the flag again AND re-arms the event, so the
            # wait below returns at once and the next pass picks it up. The FLAG is
            # the durable signal; the event is only a doorbell, so losing one to a
            # race costs nothing.
            self._wake.clear()
            targeting.consume_miss()
            try:
                targeting.refresh()
                self._rebuilds += 1
            except Exception as exc:
                # The session must not die because a socket table hiccupped; the
                # port set simply goes stale until the next pass. But it stops
                # being invisible.
                #
                # `note`, not `once`, and the difference is not stylistic. `once`
                # keys on the SUBSYSTEM NAME alone, so the first failure here would
                # silence every LATER one - including a different fault entirely,
                # which is the one worth reading. The cost argument that puts
                # `once` in the packet path does not apply: this line runs only
                # when something has ALREADY failed, at most once per
                # `min_interval`, so the traceback it builds is paid for out of a
                # budget that is otherwise unspent. Repeats stay cheap on disk
                # because `record` de-duplicates them by fingerprint.
                crashlog.note(exc, "targeting.resolver")
            self._last_rebuild = time.monotonic()
            self._wake.wait(timeout=self.interval)
