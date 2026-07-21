"""The packet threads must never reach the operating system (audit item #8).

The rule this file enforces is one sentence: **nothing on the capture or inject
thread may ask the OS a question.** Those two threads are the tool's hot path.
A stalled capture thread means WinDivert keeps diverting into a queue nobody
drains, so the user silently loses connectivity while the UI says "running" -
the failure the whole fail-open design exists to prevent (convention 20). A
stalled inject thread means the delays this tool exists to inject stop being the
delays it was told to inject.

That invariant already had a guard, but a narrow one.
``test_target_resolver.py::test_the_capture_thread_never_touches_the_socket_table``
injects a counting fake table and checks which threads made it look. It is worth
keeping - it is fast and deterministic - but it has two limits, and the first one
has already bitten this project once:

* **it watches an object, so it can watch the WRONG object.** An earlier version
  gave the counting table only to the targeting and left the engine on
  ``portmap.default_table()``, so it passed while ``_log_conn`` ->
  ``_process_for`` -> ``process_for_port`` rebuilt the real table about sixteen
  times a second on the capture thread. A live run caught what the test could not.
* **it only knows about the socket table.** Targeting is one route to the OS;
  ``_log_conn`` is a second, independent one. A third would be invisible to it.

So this file watches the ROUTES instead of an object. ``portmap`` is the only
module in the package that touches ``psutil`` or ``iphlpapi``, and it does so
through five entry points; wrapping all five catches any caller, including one
nobody has written yet. Threads are compared by IDENTITY against the engine's own
handles rather than by name substring, so it does not depend on how CPython
happens to name a thread.

Measured while writing this, on a real session with traffic and targeting active
(the numbers are the point of the test, not decoration):

    5232x  _psutil_created         from bean-target-resolver
    1431x  _psutil_process_info    from bean-target-resolver
     448x  _psutil_created         from the watchdog
     212x  _Native._table          from bean-target-resolver
       3x  _psutil_process_table   from bean-target-resolver
       0x  anything                from the capture or inject thread

The work is real and it is heavy - and all of it happens somewhere the user's
packets do not wait for it. That is the whole design, asserted.

**This found no bug.** The invariant holds today; the value is that it keeps
holding when somebody adds the next lookup.

Verified by mutation, with the negative recorded rather than glossed over:

* **caught:** ``_process_for`` reopening the socket-table refresh
  (``allow_refresh=True``) - the exact regression that has already happened twice
  here. The failure names both ends of it:
  ``[('_Native._table', 'Thread-1 (_capture_loop)')]``.
* **not caught:** a name lookup on the capture thread that HITS the warm info
  cache. That is the guard's boundary rather than a hole in it - it watches trips
  to the OS, and a cache hit is not one. But it means a regression that only
  misses the cache occasionally (a brand-new PID, say) will only be caught
  occasionally. If that ever matters, the way to close it is to run the session
  with the info cache expiring, not to widen this test.

The Linux route is covered too, and not by waiting for CI to run it. ``PortTable``
reads the socket table through ``psutil`` whenever ``_make_native`` returns
``None``, which is precisely what a non-Windows platform makes it do; substituting
that exercises the fallback on any machine. Measured with the substitution in
place: the native calls vanish, ``_psutil_port_pid_map`` fires about a dozen times
in five seconds, and the packet threads still touch nothing. See
``test_the_psutil_socket_table_path_is_just_as_clean``.

Deliberately NOT a wall-clock budget. The suite's existing timing assertions
(``test_failsafe``'s "start did not block the UI thread", ``test_target_resolver``'s
"stop did not wait for the scan") all separate outcomes that differ by an order of
magnitude. "The hot path costs under N microseconds" has no such separation: on a
shared CI runner it measures the runner, and the first thing anybody does with a
test like that is widen the bound until it stops failing.
"""
import contextlib
import threading
import time

from beantester import portmap
from beantester.engine import BeanEngine
from beantester.settings import DEFAULT_SETTINGS, apply_settings
from beantester.synthetic import SyntheticDivert
from fakes import check

# Every route out of the package and into the operating system. They are module
# level functions called through module globals, so replacing the attribute is
# enough - production picks up the replacement at call time.
OS_FUNCTIONS = ("_psutil_port_pid_map", "_psutil_process_table",
                "_psutil_created", "_psutil_process_info")


@contextlib.contextmanager
def os_calls_recorded():
    """Record ``(function name, calling thread)`` for every trip to the OS."""
    calls = []
    lock = threading.Lock()
    originals = {name: getattr(portmap, name) for name in OS_FUNCTIONS}
    native_table = portmap._Native._table

    def wrap(name, original):
        def spy(*a, **kw):
            with lock:
                calls.append((name, threading.current_thread()))
            return original(*a, **kw)
        return spy

    def native_spy(self, *a, **kw):
        with lock:
            calls.append(("_Native._table", threading.current_thread()))
        return native_table(self, *a, **kw)

    for name, original in originals.items():
        setattr(portmap, name, wrap(name, original))
    portmap._Native._table = native_spy
    try:
        yield calls
    finally:
        for name, original in originals.items():
            setattr(portmap, name, original)
        portmap._Native._table = native_table


def test_no_packet_thread_ever_reaches_the_operating_system():
    """A real session, targeting on, every route to the OS watched.

    The target deliberately matches NOTHING. That is not laziness about picking a
    process: with no matching port, every packet is a miss, so the resolver is
    woken continuously and the OS surface gets hammered - which is exactly the
    pressure this guard should run under. It also makes the test independent of
    which processes happen to exist on the machine, so it means the same thing on
    a CI runner as it does here.
    """
    portmap.reset_default_table()        # do not inherit another test's cache
    engine = BeanEngine()
    settings = dict(DEFAULT_SETTINGS)
    settings.update(loss=10, target="no_such_process_anywhere_xyz")

    with os_calls_recorded() as calls:
        apply_settings(engine, settings, lambda *_: None)
        engine.start("true", divert=SyntheticDivert(seed=7))
        capture, inject = engine._t_cap, engine._t_inj
        try:
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if engine.stats_snapshot()["seen"] > 500:
                    break
                time.sleep(0.02)
            seen = engine.stats_snapshot()["seen"]
        finally:
            engine.stop()

    packet_threads = {id(t) for t in (capture, inject) if t is not None}
    offenders = sorted({(name, thread.name) for name, thread in calls
                        if id(thread) in packet_threads})

    check("the packet threads existed to be watched", len(packet_threads) == 2,
          f"({packet_threads})")
    check("traffic actually flowed", seen > 100, f"({seen})")
    # Without this the test would pass just as happily if the whole surface were
    # never called - a guard that only proves nothing happened proves nothing.
    check("the OS surface was actually exercised", len(calls) > 5,
          f"({len(calls)} calls - the resolver should be busy under a miss storm)")
    check("no packet thread reached the operating system", not offenders,
          f"({offenders})")


def test_the_psutil_socket_table_path_is_just_as_clean():
    """The same guarantee on the route Linux takes - forced, not waited for.

    ``PortTable`` reads the socket table through ``iphlpapi`` when ``_make_native``
    succeeds and through ``psutil.net_connections`` when it does not. On Windows
    the first always wins, so ``_psutil_port_pid_map`` was watched by the test
    above and never once fired: the Linux behaviour was covered only by the ubuntu
    leg of CI, and only by accident of which platform ran it.

    ``_make_native`` returning ``None`` is exactly what a non-Windows platform
    does, so substituting it exercises that route on any machine. Measured here:
    the native calls disappear entirely, ``_psutil_port_pid_map`` fires about a
    dozen times in five seconds, and the packet threads still touch nothing.
    """
    real_make_native = portmap._make_native
    portmap._make_native = lambda: None                  # what Linux looks like
    portmap.reset_default_table()
    try:
        table = portmap.default_table()
        engine = BeanEngine()
        settings = dict(DEFAULT_SETTINGS)
        settings.update(loss=10, target="no_such_process_anywhere_xyz")

        with os_calls_recorded() as calls:
            apply_settings(engine, settings, lambda *_: None)
            engine.start("true", divert=SyntheticDivert(seed=7))
            capture, inject = engine._t_cap, engine._t_inj
            try:
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    if engine.stats_snapshot()["seen"] > 500:
                        break
                    time.sleep(0.02)
            finally:
                engine.stop()
    finally:
        portmap._make_native = real_make_native
        portmap.reset_default_table()                    # leave no fallback table

    packet_threads = {id(t) for t in (capture, inject) if t is not None}
    offenders = sorted({(name, thread.name) for name, thread in calls
                        if id(thread) in packet_threads})
    fallback_calls = [name for name, _ in calls if name == "_psutil_port_pid_map"]
    native_calls = [name for name, _ in calls if name == "_Native._table"]

    # Conclusiveness first: without these the test would pass on a machine where
    # the substitution silently did nothing, which is the whole point of it.
    check("the table really took the psutil route", table.native is False,
          f"(native={table.native})")
    check("the psutil socket-table lookup actually ran", fallback_calls,
          f"({len(calls)} calls, none of them _psutil_port_pid_map)")
    check("and the native one did not", not native_calls,
          f"({len(native_calls)} native calls leaked through)")
    check("no packet thread reached the operating system", not offenders,
          f"({offenders})")


def test_the_recorder_sees_what_it_claims_to_see():
    """The guard above is only worth its runtime if the recorder really records.

    A wrapper that silently failed to install - a renamed function, a call routed
    around the module global - would leave the guard permanently, invisibly green.
    So: call the surface directly and confirm it comes back tagged with this
    thread.
    """
    with os_calls_recorded() as calls:
        portmap._psutil_created(1)
        names = [name for name, _ in calls]
        threads = {thread is threading.current_thread() for _, thread in calls}

    check("the call was recorded", "_psutil_created" in names, f"({names})")
    check("it was tagged with the calling thread", threads == {True}, f"({threads})")
    check("the wrappers were removed again",
          portmap._psutil_created.__name__ != "spy",
          f"({portmap._psutil_created!r})")
