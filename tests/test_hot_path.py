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

So this file watches the ROUTES instead of an object. ``portmap`` and, since the
Tools tab's adapter list (2026-10-13), ``adapters`` are the only modules in the
package that touch ``psutil`` or ``iphlpapi``, and they do so through a handful of
entry points (``OS_FUNCTIONS``, ``NATIVE_METHODS``, ``ADAPTER_METHODS``); wrapping
every one catches any caller, including one nobody has written yet. A THIRD module
that loads iphlpapi is the one thing that would walk past all of them, so
``test_every_module_that_loads_iphlpapi_is_watched`` finds them by reading the
source. Threads are compared by IDENTITY against the engine's own
handles rather than by name substring, so it does not depend on how CPython
happens to name a thread.

Measured on a real session with traffic and targeting active (the numbers are the
point of the test, not decoration). Re-measured 2026-08-01, when the per-PID resolve
moved from psutil to a handle read (``portmap._process_info``):

    1210x  _psutil_created         from bean-target-resolver
     330x  _native_process_info    from bean-target-resolver
     330x  _psutil_process_info    from bean-target-resolver
     238x  _psutil_created         from MainThread
      70x  _native_process_info    from MainThread
      68x  _psutil_created         from the watchdog
      67x  _psutil_process_info    from MainThread
      40x  _Native._table          from bean-target-resolver
       0x  anything                from the capture or inject thread

The two resolve counts matching is not double work: this test points targeting at a
name nothing has, so the socket table keeps naming PIDs that have already EXITED
(checked: ``psutil.pid_exists`` is False for the frequent ones). Both routes decline
them, one after the other. Traced separately over 390 resolves, the handle answered
4, declined 386, and psutil then resolved 1 of those - which is the fallback earning
its place rather than shadowing the primary. Since 2026-10-03 a pid the kernel says
nobody holds (``OpenProcess`` error 87, ``portmap._open_failure``) no longer goes on to
psutil, so on today's code the two counts part ways (performance review R-3).

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
import glob
import os
import re
import threading
import time

from beantester import adapters, portmap, tcpreset
from beantester.engine import BeanEngine
from beantester.settings import DEFAULT_SETTINGS, apply_settings
from beantester.synthetic import SyntheticDivert
from fakes import ROOT, check

# Every route out of the package and into the operating system. They are module
# level functions called through module globals, so replacing the attribute is
# enough - production picks up the replacement at call time.
OS_FUNCTIONS = ("_psutil_port_pid_map", "_psutil_process_table",
                "_psutil_created", "_psutil_process_info", "_native_process_info",
                # The Tools tab's whole socket table (2026-09-23): read on a click by a
                # worker. Watched like the rest, so the day something on the packet
                # path reaches for it, this file says so.
                "_psutil_socket_rows")
# The two walks over iphlpapi's tables, methods of the native binding: the port map
# the capture side reads, and the full table of the Tools tab.
NATIVE_METHODS = ("_table", "socket_rows")
# The Tools tab's adapter list and its route lookup (``adapters._Native``): read on a
# click by a worker, never by a packet thread.
ADAPTER_METHODS = ("adapters", "best_interface")
# "Reset this connection" on the Connections page (``tcpreset._System``): one call, on
# a click, by a worker - never by a packet thread.
RESET_METHODS = ("delete",)

# Every module that loads iphlpapi, and the binding class whose methods are its only
# road to it. ``test_every_module_that_loads_iphlpapi_is_watched`` keeps this whole.
WATCHED_IPHLPAPI = {"beantester/portmap.py": portmap._Native,
                    "beantester/adapters.py": adapters._Native,
                    "beantester/tcpreset.py": tcpreset._System}
# `ctypes.WinDLL("iphlpapi.dll")`, `windll.iphlpapi` and `WinDLL('iphlpapi')`.
_LOADS_IPHLPAPI = re.compile(r"""(?:WinDLL|LoadLibrary\w*)\(\s*['"]iphlpapi|windll\.iphlpapi""",
                             re.IGNORECASE)


@contextlib.contextmanager
def os_calls_recorded():
    """Record ``(function name, calling thread)`` for every trip to the OS."""
    calls = []
    lock = threading.Lock()
    originals = {name: getattr(portmap, name) for name in OS_FUNCTIONS}
    native = {(portmap._Native, name, "_Native." + name): getattr(portmap._Native, name)
              for name in NATIVE_METHODS}
    native.update({(adapters._Native, name, "adapters." + name):
                   getattr(adapters._Native, name) for name in ADAPTER_METHODS})
    native.update({(tcpreset._System, name, "tcpreset." + name):
                   getattr(tcpreset._System, name) for name in RESET_METHODS})

    def wrap(name, original):
        def spy(*a, **kw):
            with lock:
                calls.append((name, threading.current_thread()))
            return original(*a, **kw)
        return spy

    for name, original in originals.items():
        setattr(portmap, name, wrap(name, original))
    for (owner, name, label), original in native.items():
        setattr(owner, name, wrap(label, original))
    try:
        yield calls
    finally:
        for name, original in originals.items():
            setattr(portmap, name, original)
        for (owner, name, _label), original in native.items():
            setattr(owner, name, original)


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

    # The adapter list's road too: a route lookup through a fake binding.
    class Routes:
        def GetBestInterfaceEx(self, _destination, _index):
            return 1231
    with os_calls_recorded() as calls:
        adapters._Native(iphlpapi=Routes()).best_interface(4)
        names = [name for name, _ in calls]
    check("the adapters' route lookup is recorded too", names == ["adapters.best_interface"],
          f"({names})")
    check("and unwrapped after", adapters._Native.best_interface.__name__ == "best_interface")

    # And the connection reset's: one SetTcpEntry through a fake binding.
    class Reset:
        def SetTcpEntry(self, _row):
            return 0
    with os_calls_recorded() as calls:
        tcpreset._System(iphlpapi=Reset(), rows=list, is_admin=bool).delete(
            tcpreset.row_for("192.0.2.10", tcpreset.Target(1, "192.0.2.20", 2)))
        names = [name for name, _ in calls]
    check("the connection reset is recorded too", names == ["tcpreset.delete"], f"({names})")
    check("and unwrapped after", tcpreset._System.delete.__name__ == "delete")


def _iphlpapi_loaders(root=ROOT):
    """The package modules whose source loads iphlpapi, as repo-relative paths."""
    found = set()
    for path in glob.glob(os.path.join(root, "beantester", "**", "*.py"), recursive=True):
        with open(path, encoding="utf-8") as handle:
            if _LOADS_IPHLPAPI.search(handle.read()):
                found.add(os.path.relpath(path, root).replace(os.sep, "/"))
    return found


def test_every_module_that_loads_iphlpapi_is_watched():
    """The recorder above wraps named methods. A third module that loads iphlpapi
    would reach the OS around every one of them, with this file green - so the set
    of modules is read from the source and must be the set the recorder knows."""
    loaders = _iphlpapi_loaders()
    check("the modules that load iphlpapi are the ones the recorder watches",
          loaders == set(WATCHED_IPHLPAPI), f"({sorted(loaders)} vs {sorted(WATCHED_IPHLPAPI)})")
    # The canary: a scan that finds nothing satisfies an equality with nothing.
    for shape in ('ctypes.WinDLL("iphlpapi.dll")', "lib = WinDLL('iphlpapi')",
                  "ctypes.windll.iphlpapi.GetIfTable2(p)"):
        check(f"the scan sees {shape}", _LOADS_IPHLPAPI.search(shape))
    check("and not a mention in prose", not _LOADS_IPHLPAPI.search("reads iphlpapi tables"))
