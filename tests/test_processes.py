"""Target-process resolution: one expression -> the ports of every matching process.

psutil is faked, so the tests run anywhere (the real lookup needs a live system).
"""
import sys
import threading
import time
import types

import pytest

from beantester import BeanEngine, apply_targeting, find_process_ports, parse_target
from fakes import check

PROCESSES = [
    (101, "chrome.exe"),
    (102, "chromedriver.exe"),
    (2500, "firefox.exe"),
    (2501, "firefox.exe"),
    (7, "init"),
]
# pid -> local ports it holds open
CONNECTIONS = {101: [5001, 5002], 102: [5003], 2500: [6001], 2501: [6002], 7: [22]}


class _Proc:
    def __init__(self, pid, name):
        self.info = {"pid": pid, "name": name}


class _Addr:
    def __init__(self, port):
        self.port = port


class _Conn:
    def __init__(self, pid, port):
        self.pid = pid
        self.laddr = _Addr(port)


@pytest.fixture
def fake_psutil():
    """Install a minimal psutil for the duration of one test.

    On Windows the port table uses a NATIVE iphlpapi path and never touches
    psutil, so faking psutil alone left the tests reading the real (empty) CI
    socket table and every assertion failed with ``[]``. The fixture therefore
    also (a) forces the psutil fallback by disabling the native factory, and
    (b) resets the process-wide cached table, which is otherwise shared across
    tests and would hold a stale (or native) mapping.
    """
    from beantester import portmap
    module = types.ModuleType("psutil")
    module.process_iter = lambda attrs=None: [_Proc(p, n) for p, n in PROCESSES]
    module.net_connections = lambda kind="inet": [
        _Conn(pid, port) for pid, ports in CONNECTIONS.items() for port in ports]
    # Real psutil resolves a name PER PID via psutil.Process(pid) (the individual
    # path tried first); the fixture provides Process to match that. process_iter is
    # the bulk fallback for PIDs that cannot be opened. Both are faked here.
    _created = {p: 1000.0 + p for p, _ in PROCESSES}

    class _Process:
        def __init__(self, pid):
            self._pid = int(pid)
            self._name = next((n for p, n in PROCESSES if p == self._pid), None)
            if self._name is None:
                raise RuntimeError("no such process")     # like psutil.NoSuchProcess

        def name(self):
            return self._name

        def ppid(self):
            return 1

        def create_time(self):
            return _created[self._pid]

    module.Process = _Process
    previous = sys.modules.get("psutil")
    sys.modules["psutil"] = module

    # Force the psutil fallback everywhere the native (Windows) path would win: the
    # socket table (_make_native) AND the process-name snapshot (_ALLOW_NATIVE_PROCESSES,
    # the toolhelp path), or the bulk fallback would read the REAL machine's processes
    # instead of the fake PROCESSES.
    native_factory = portmap._make_native
    native_procs = portmap._ALLOW_NATIVE_PROCESSES
    portmap._make_native = lambda: None
    portmap._ALLOW_NATIVE_PROCESSES = False
    portmap.reset_default_table()

    try:
        yield module
    finally:
        portmap._make_native = native_factory
        portmap._ALLOW_NATIVE_PROCESSES = native_procs
        portmap.reset_default_table()
        if previous is None:
            sys.modules.pop("psutil", None)
        else:
            sys.modules["psutil"] = previous


def test_single_name_is_still_a_substring(fake_psutil):
    ports, desc = find_process_ports("chrome")
    check("bare name keeps matching by substring", ports == {5001, 5002, 5003},
          f"({sorted(ports)})")
    check("description lists every matched process name",
          "chrome.exe" in desc and "chromedriver.exe" in desc, f"({desc})")


def test_single_pid_still_works(fake_psutil):
    ports, _ = find_process_ports("2500")
    check("bare PID matches exactly that process", ports == {6001}, f"({sorted(ports)})")


def test_comma_separated_names(fake_psutil):
    ports, _ = find_process_ports("chrome.exe, firefox.exe")
    check("a list of names sums their ports", ports == {5001, 5002, 6001, 6002},
          f"({sorted(ports)})")


def test_comma_separated_pids(fake_psutil):
    ports, _ = find_process_ports("101,2500")
    check("a list of PIDs sums their ports", ports == {5001, 5002, 6001},
          f"({sorted(ports)})")


def test_names_and_pids_mixed_in_one_field(fake_psutil):
    ports, _ = find_process_ports("firefox, 101")
    check("names and PIDs can be mixed", ports == {5001, 5002, 6001, 6002},
          f"({sorted(ports)})")


def test_exclusion(fake_psutil):
    ports, desc = find_process_ports("chrome, !chromedriver")
    check("exclusion removes the unwanted process", ports == {5001, 5002},
          f"({sorted(ports)})")
    check("excluded process is not described", "chromedriver" not in desc, f"({desc})")


def test_wildcard_and_regex(fake_psutil):
    ports, _ = find_process_ports("firefox*")
    check("wildcard matches both firefox instances", ports == {6001, 6002},
          f"({sorted(ports)})")
    ports, _ = find_process_ports("re:^chrome\\.exe$")
    check("regex can pin an exact name", ports == {5001, 5002}, f"({sorted(ports)})")


def test_pid_range_and_comparison(fake_psutil):
    ports, _ = find_process_ports("100-200")
    check("PID range matches both chrome processes", ports == {5001, 5002, 5003},
          f"({sorted(ports)})")
    ports, _ = find_process_ports(">1000")
    check("PID comparison matches the high PIDs", ports == {6001, 6002},
          f"({sorted(ports)})")


def test_no_match_returns_no_ports(fake_psutil):
    ports, desc = find_process_ports("nosuchprocess")
    check("nothing matched -> no ports", ports == set())
    check("nothing matched -> empty description", desc == "(none)", f"({desc})")


def test_empty_expression_targets_nothing(fake_psutil):
    ports, desc = find_process_ports("   ")
    check("an empty target expression resolves to no ports", ports == set() and desc == "(none)")


def test_bad_expression_raises_before_psutil(fake_psutil):
    with pytest.raises(ValueError):
        find_process_ports(">chrome")     # comparison on a name


def test_parse_target_exposes_the_compiled_matcher(fake_psutil):
    matcher = parse_target("chrome, !chromedriver")
    check("compiled target matcher is reusable",
          matcher.matches(101, "chrome.exe") and not matcher.matches(102, "chromedriver.exe"))
    ports, _ = find_process_ports(matcher)
    check("find_process_ports accepts a compiled matcher", ports == {5001, 5002})


def test_apply_targeting_points_the_engine_at_the_ports(fake_psutil):
    engine = BeanEngine()
    lines = []
    apply_targeting(engine, "chrome, !chromedriver", lines.append)
    check("engine targets the matched ports",
          engine.core.target_active and engine.core.target_ports == {5001, 5002},
          f"({engine.core.target_ports})")
    check("the resolution is logged", any("chrome.exe" in l for l in lines), f"({lines})")


def test_apply_targeting_disables_on_empty_expression(fake_psutil):
    engine = BeanEngine()
    engine.set_target(True, {1234})
    apply_targeting(engine, "", lambda *_: None)
    check("an empty target expression turns targeting off",
          engine.core.target_active is False)


def test_apply_targeting_logs_and_disables_on_a_bad_expression(fake_psutil):
    engine = BeanEngine()
    lines = []
    apply_targeting(engine, ">chrome", lines.append)
    check("a bad expression disables targeting rather than crashing a thread",
          engine.core.target_active is False)
    check("a bad expression is reported in the log", lines, f"({lines})")


# -- make_targeting: the LIVE targeting object used by the engine ------------ #
def test_make_targeting_returns_none_for_an_empty_expression(fake_psutil):
    from beantester.processes import make_targeting
    check("an empty expression means no targeting (every packet a candidate)",
          make_targeting("   ") is None)


def test_make_targeting_builds_a_live_set_of_the_matched_ports(fake_psutil):
    from beantester.processes import make_targeting
    targeting = make_targeting("chrome")        # substring: chrome.exe + chromedriver.exe
    check("make_targeting returns a live object for a real match", targeting is not None)
    ports = targeting.ports()
    check("the matched chrome ports are live", {5001, 5002, 5003} <= set(ports),
          f"(ports={sorted(ports)})")
    check("a chrome port is reported as targeted", 5001 in targeting)
    check("an unrelated firefox port is not targeted", 6001 not in targeting)


# -- port_process_map: best-effort local port -> process name --------------- #
def test_port_process_map_maps_ports_to_names(fake_psutil):
    from beantester.processes import port_process_map
    mapping = port_process_map()
    check("chrome port resolves to its process name",
          mapping.get(5001) == "chrome.exe", f"(got {mapping.get(5001)!r})")
    check("firefox port resolves to its process name",
          mapping.get(6001) == "firefox.exe", f"(got {mapping.get(6001)!r})")


# -- the native process-name snapshot (Windows only) ------------------------ #
@pytest.mark.skipif(not sys.platform.startswith("win"),
                    reason="toolhelp snapshot is Windows-only")
def test_toolhelp_snapshot_names_this_process_without_opening_it():
    """The whole point of the native path: name every process fast and WITHOUT an
    OpenProcess, so it can name a hardened process (Chrome) that psutil.Process()
    cannot. Here it must at least contain THIS process, named, with no start time."""
    import os
    from beantester.portmap import _toolhelp_process_table
    table = _toolhelp_process_table()
    check("the snapshot returned something", table is not None and len(table) > 5,
          f"({None if table is None else len(table)})")
    check("it contains this process", os.getpid() in table, f"(pid {os.getpid()})")
    name, ppid, created = table[os.getpid()]
    check("this process is named", name.lower().endswith(".exe"), f"({name!r})")
    check("the snapshot carries no start time (TTL takes over)", created is None)


# -- the per-PID handle read (Windows only) --------------------------------- #
@pytest.mark.skipif(not sys.platform.startswith("win"),
                    reason="the handle read is Windows-only")
def test_the_handle_read_agrees_with_an_independent_oracle_on_the_parent():
    """The PARENT pid, checked against something that is neither psutil nor toolhelp.

    ``ppid`` is load-bearing and had no guardian: it feeds ``PortTable.ancestors``,
    which is how ``targeting.py`` matches a process TREE, so a wrong parent silently
    stops a target from catching its children. Every existing targeting test drives a
    FAKE table with its own ``ancestors``, so all of them stay green no matter what
    this returns - the trap PROJECT_NOTES calls out about fixtures that cannot tell
    the variants apart.

    ``os.getppid()`` is the independent oracle: CPython asks the OS directly, so it
    shares no code with either resolver.
    """
    import os
    from beantester.portmap import _native_process_info, _psutil_process_info
    resolved = _native_process_info(os.getpid())
    check("the handle read answered for this process", resolved is not None)
    name, ppid, created = resolved
    check("it names this process", name.lower().endswith(".exe"), f"({name!r})")
    check("the parent matches the OS", ppid == os.getppid(),
          f"(handle said {ppid}, os.getppid() said {os.getppid()})")
    check("it carries a start time, so the recycle check stays verifiable",
          isinstance(created, float) and created > 0, f"({created!r})")
    # and it must agree with the path it replaced, or the connection log changes
    # meaning without anybody deciding that it should
    fallback = _psutil_process_info(os.getpid())
    check("name and parent match the psutil path it replaced",
          fallback is not None and fallback[0].lower() == name.lower()
          and fallback[1] == ppid, f"({fallback!r} vs {resolved!r})")


@pytest.mark.skipif(not sys.platform.startswith("win"),
                    reason="the handle read is Windows-only")
def test_a_process_that_will_not_name_itself_is_declined():
    """PID 4 (``System``) never yields an image name, so it must resolve to ``None``.

    A real standing example of the partial read rather than a race to reproduce. It
    exercises the FAILED-call route out; the succeeded-but-empty route has its own
    test below, because a mutant showed these are two different branches and this
    one alone does not cover both.
    """
    from beantester.portmap import _native_process_info
    check("the System process is declined, not cached nameless",
          _native_process_info(4) is None)


def _fake_native_api(name_value, ppid=4321, ticks=133_000_000_000_000_000, ok=True):
    """A stand-in for the bound ctypes surface, so the parsing can be driven directly.

    The five entry points live in one injectable tuple precisely so this is possible:
    it makes the branches reachable without a process in the right state, and it runs
    the parsing on EVERY platform rather than only where the API exists.
    """
    class _Field:
        def __init__(self, v=0):
            self.value = v

    class _Basic:
        def __init__(self):
            self.InheritedFromUniqueProcessId = ppid
            self.UniqueProcessId = 999

    class _Filetime:
        def __init__(self):
            self.dwHighDateTime = ticks >> 32
            self.dwLowDateTime = ticks & 0xFFFFFFFF

    class _Ctypes:
        byref = staticmethod(lambda x: x)
        sizeof = staticmethod(lambda x: 48)
        create_unicode_buffer = staticmethod(lambda n: _Field(name_value))

    class _Wintypes:
        ULONG = _Field
        DWORD = _Field
        FILETIME = _Filetime

    class _K32:
        OpenProcess = staticmethod(lambda *a: 1234)
        CloseHandle = staticmethod(lambda *a: 1)
        GetProcessTimes = staticmethod(lambda *a: 1)
        QueryFullProcessImageNameW = staticmethod(lambda *a: 1 if ok else 0)

    class _Ntdll:
        NtQueryInformationProcess = staticmethod(lambda *a: 0)

    return (_Ctypes, _Wintypes, _K32, _Ntdll, _Basic)


def test_a_name_that_comes_back_empty_is_declined_not_cached(monkeypatch):
    """The succeeded-but-EMPTY name must fall through, never reach the cache.

    A process that has just exited still answers NtQueryInformationProcess and
    GetProcessTimes while its image name comes back blank (measured under churn: pid
    45336, identical parent and start time across two reads, name 'cmd.exe' then '').
    Caching that would blank the connection log's process column - the exact bug the
    column was added to fix.

    Written after a mutant SURVIVED: deleting the empty-name guard changed nothing
    the PID 4 test could see, because PID 4 leaves by the failed-call branch instead.
    """
    from beantester import portmap
    monkeypatch.setattr(portmap, "_ALLOW_NATIVE_PROCESSES", True)

    monkeypatch.setattr(portmap, "_NATIVE_INFO_API", [_fake_native_api("")])
    check("an empty name resolves to nothing at all",
          portmap._native_process_info(45336) is None)

    monkeypatch.setattr(portmap, "_NATIVE_INFO_API",
                        [_fake_native_api(r"C:\Windows\System32\cmd.exe")])
    resolved = portmap._native_process_info(45336)
    check("a real name resolves", resolved is not None, f"({resolved!r})")
    check("...to its basename, not the full path", resolved[0] == "cmd.exe",
          f"({resolved[0]!r})")
    check("...with the parent the API reported", resolved[1] == 4321,
          f"({resolved[1]})")
    # 133e15 FILETIME ticks = 2022-06-18T04:26:40Z, checked two ways (the epoch shift
    # by hand, and datetime from the 1601 base). Pinned because that shift is the one
    # piece of arithmetic here and off-by-a-constant would look perfectly plausible.
    check("...and a start time converted off the FILETIME epoch",
          abs(resolved[2] - 1655526400.0) < 1.0, f"({resolved[2]!r})")

    monkeypatch.setattr(portmap, "_NATIVE_INFO_API",
                        [_fake_native_api("cmd.exe", ok=False)])
    check("a failed name call is declined too",
          portmap._native_process_info(45336) is None)


def test_the_native_policy_gate_is_read_per_call_not_cached(monkeypatch):
    """``_ALLOW_NATIVE_PROCESSES`` must gate every call, not just the first one.

    This is a REGRESSION TEST, not a hypothetical: the first version of the handle
    read checked the flag while BINDING the ctypes entry points and cached the
    result, so a test switching the flag off afterwards was ignored and got real
    machine processes back inside its fake world. Caching a policy decision fails in
    both directions - bound while the flag was off, the native route would then stay
    off for the rest of the process.
    """
    import os
    from beantester import portmap
    monkeypatch.setattr(portmap, "_ALLOW_NATIVE_PROCESSES", False)
    check("the native read declines while the flag is off",
          portmap._native_process_info(os.getpid()) is None)
    monkeypatch.undo()
    if sys.platform.startswith("win"):
        check("...and answers again once it is back on",
              portmap._native_process_info(os.getpid()) is not None)


@pytest.mark.skipif(not sys.platform.startswith("win"),
                    reason="the handle read is Windows-only")
def test_a_cold_binding_does_not_push_other_threads_onto_the_slow_path(monkeypatch):
    """Threads arriving while the ctypes surface is being bound must WAIT, not degrade.

    Two threads reach this from the first moments of a session - the watchdog warming
    names and the resolver matching a target - so the bind window lands exactly where
    the whole change exists to save time. Silently taking the psutil route there costs
    9 ms a lookup instead of 0.03 ms, which is what was being fixed.

    A regression test for a fault a LOCK DID NOT FIX. Publishing an "in progress"
    marker in the shared slot defeated it invisibly: the fast path reads that slot
    unlocked and ``False is not None``, so every other thread read it as "unavailable"
    and returned without ever queueing on the lock. Measured before: exactly 200 of
    1600 calls took the native route, 3 trials of 3 and then 5 of 5 - one thread's
    worth, every time. After: 1600 of 1600, 5 trials of 5.
    """
    import os
    import threading
    from beantester import portmap

    monkeypatch.setattr(portmap, "_NATIVE_INFO_API", [None])      # never bound yet
    threads_n, per_thread = 8, 50
    resolved, failures = [], []
    barrier = threading.Barrier(threads_n)

    def hammer():
        barrier.wait()                    # everybody hits the cold slot together
        try:
            for _ in range(per_thread):
                resolved.append(portmap._native_process_info(os.getpid()) is not None)
        except Exception as exc:          # noqa: BLE001 - the point is to report it
            failures.append(repr(exc))

    workers = [threading.Thread(target=hammer) for _ in range(threads_n)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)

    check("no thread raised while the surface was being bound", not failures,
          f"({failures[:2]})")
    check("every thread got an answer", len(resolved) == threads_n * per_thread,
          f"({len(resolved)} of {threads_n * per_thread})")
    check("and none of them was pushed onto the psutil path by the bind",
          all(resolved), f"({sum(resolved)} of {len(resolved)} took the handle route)")


# -- port resolution fails LOUDLY (for us), quietly (for the user) ---------- #
#
# All three of these used to swallow. An empty map, a blank process name and a
# partial socket table are all legitimate answers on a quiet machine, so a lookup
# that had STOPPED WORKING was indistinguishable from one with nothing to report.
# That is how "the process column is all ?" becomes a bug report nobody can act on.


def _spy_on_crashlog(monkeypatch):
    """Capture what would be recorded, without touching the crash directory."""
    from beantester import crashlog
    recorded = []
    monkeypatch.setattr(crashlog, "_once_seen", set())   # once() dedupes per process
    monkeypatch.setattr(crashlog, "record",
                        lambda exc, **kw: recorded.append(kw))
    return recorded


def test_port_process_map_records_a_failure_instead_of_swallowing_it(monkeypatch):
    from beantester import portmap
    from beantester.processes import port_process_map

    class _Broken:
        def refresh_if_stale(self, *a, **k):
            raise RuntimeError("socket table exploded")

    recorded = _spy_on_crashlog(monkeypatch)
    monkeypatch.setattr(portmap, "default_table", lambda: _Broken())

    mapping = port_process_map()
    check("the caller still gets a usable empty map", mapping == {}, f"({mapping!r})")
    check("the failure was recorded, not swallowed", len(recorded) == 1, f"({recorded})")
    check("it is attributed to its subsystem",
          recorded[0].get("subsystem") == "processes.port_map", f"({recorded})")


def test_a_partial_socket_table_is_reported_not_silently_trusted(monkeypatch):
    """One table of four failing used to leave `ok` True and cache a map with holes.

    A hole means sockets the tool cannot see, and traffic the user asked to impair
    sailing through untouched - which looks exactly like "the application coped".
    """
    from beantester.portmap import _AF_INET6, _Native

    native = _Native.__new__(_Native)        # no Windows needed: _table is faked
    native._sizes = {}
    recorded = _spy_on_crashlog(monkeypatch)
    seen = []

    def fake_table(proto, family, out, owners=None):
        seen.append((proto, family))
        if proto == "udp" and family == _AF_INET6:
            return False                     # this one stops answering
        out[1000 + len(seen)] = 4000 + len(seen)
        return True

    monkeypatch.setattr(native, "_table", fake_table)
    result = native.port_pid_map()

    check("all four tables are attempted", len(seen) == 4, f"({seen})")
    check("a partial map is still returned (psutil is an order slower)", result)
    check("the gap was recorded", len(recorded) == 1, f"({recorded})")
    check("the record names the table that failed",
          "udp/v6" in str(recorded[0].get("subsystem", "")), f"({recorded})")


def test_a_port_several_processes_hold_is_recorded_instead_of_silently_collapsed():
    """The flat ``port -> pid`` map keeps ONE owner. Now it says which it dropped.

    MEASURED on a real machine (2026-07-30, 50 samples): 4 of 127 port numbers had
    conflicting owners, and udp/v4:5353 had FIVE at once. The map cannot represent
    that - three of those four were several processes on the same protocol and
    family (SO_REUSEADDR: DHCP, SSDP, mDNS), where the local port genuinely does
    not identify the owner. So the collapse stays and stops being SILENT.
    """
    from beantester.portmap import _AF_INET, _AF_INET6, _Native, _put

    # Driven through the REAL row-installing rule. An earlier version of this test
    # gave the fake table its own copy of that rule, so it asserted its own
    # reimplementation: deleting the recording from portmap left it green.
    rows = {("tcp", _AF_INET): [(80, 10), (5353, 11)],
            ("udp", _AF_INET): [(5353, 12), (5353, 13)],   # two owners, one table
            ("udp", _AF_INET6): [(5353, 14), (443, 15)]}   # ...and a third across

    def fake_table(proto, family, out, owners=None):
        for port, pid in rows.get((proto, family), ()):
            _put(out, owners, port, pid)
        return True

    native = _Native.__new__(_Native)
    native._sizes = {}
    native._table = fake_table
    owners = {}
    flat = native.port_pid_map(owners)

    check("the flat map is UNCHANGED - last row still wins", flat[5353] == 14,
          f"({flat.get(5353)})")
    check("every owner of the shared port was recorded",
          owners.get(5353) == {11, 12, 13, 14}, f"({owners.get(5353)})")
    check("a port with one owner is not reported as shared",
          80 not in owners and 443 not in owners, f"({sorted(owners)})")

    # ...and the same rule is what the psutil fallback uses, so the two paths
    # cannot disagree about which ports are shared.
    out, seen = {}, {}
    for port, pid in [(7000, 1), (7000, 2), (7001, 3)]:
        _put(out, seen, port, pid)
    check("the shared rule keeps the last owner", out == {7000: 2, 7001: 3}, f"({out})")
    check("...and remembers the one it evicted", seen == {7000: {1, 2}}, f"({seen})")
    check("a caller that does not ask for collisions still gets the map",
          [_put(out, None, 8000, 9), out.get(8000)][1] == 9)


def test_shared_ports_are_published_with_the_map_they_belong_to():
    """A shared-port list from an older walk beside a newer map would name
    processes that no longer own anything, so it is installed under the same lock
    and the same generation guard as ``_ports``."""
    from beantester import portmap

    table = portmap.PortTable()

    class _Native:
        def port_pid_map(self, owners=None):
            if owners is not None:
                owners[5353] = {11, 12}
            return {5353: 12, 80: 10}

    table._native = _Native()
    table.native = True
    table.refresh(force=True)

    check("the map is the flat one", table.snapshot() == {5353: 12, 80: 10},
          f"({table.snapshot()})")
    check("and the collisions it hid are readable",
          table.shared_ports() == {5353: frozenset({11, 12})},
          f"({table.shared_ports()})")
    check("shared_ports hands out a copy, not the live dict",
          table.shared_ports() is not table._shared)


def test_only_ports_the_TARGET_holds_are_reported_as_shared():
    """The warning has to be about the user's target, not about the machine.

    A global "4 ports are shared" tells a tester nothing they can act on. What
    matters is "the process you aimed at shares one, so the result there is a coin
    toss" - measured: targeting Spotify left its own 5353 out of scope, while
    targeting msedge pulled svchost, Spotify and adb in with it.
    """
    from beantester.targeting import ports_shared_with_others

    class _Table:
        def shared_ports(self):
            return {5353: frozenset({11, 12, 13}),   # the target is one of three
                    1900: frozenset({77, 78})}        # nothing to do with us

    shared = ports_shared_with_others({11, 99}, _Table())
    check("the target's shared port is reported", 5353 in shared, f"({shared})")
    check("...naming the OTHERS, not the target itself",
          shared[5353] == frozenset({12, 13}), f"({shared.get(5353)})")
    check("a port shared between two strangers is not our business",
          1900 not in shared, f"({shared})")
    check("no target, nothing to say", ports_shared_with_others(set(), _Table()) == {})
    check("a table that cannot answer degrades to silence, not an error",
          ports_shared_with_others({11}, object()) == {})


#: pid -> name for the shared-port fakes. 11 and 14 are deliberately the SAME
#: program under two pids - that is the case the warning used to report as a
#: stranger, and a fixture that cannot tell them apart cannot catch it.
_SHARED_PORT_NAMES = {11: "msedge.exe", 12: "svchost.exe", 13: "adb.exe",
                      14: "msedge.exe"}


class _SharedTable:
    def __init__(self, shared, winners):
        self._shared, self._winners = shared, winners

    def refresh_if_stale(self, now=None, miss=False):
        return False

    def shared_ports(self):
        return self._shared

    def snapshot(self):
        return dict(self._winners)

    def name_of(self, pid, cheap=False):
        return _SHARED_PORT_NAMES.get(pid, "")


class _SharedTargeting:
    def __init__(self, pids=(11,), names=("msedge.exe",)):
        self._pids, self._names = set(pids), list(names)

    def pids(self):
        return set(self._pids)

    def names(self):
        return list(self._names)


def _shared_warning(shared, winners, targeting=None):
    """Run the warning against a fake OS and return the lines it produced."""
    import pytest as _pytest
    from beantester import i18n, portmap, settings
    lines = []
    mp = _pytest.MonkeyPatch()
    previous = i18n.current_language()
    try:
        i18n.set_language("en")               # assertions read the English text
        mp.setattr(portmap, "default_table",
                   lambda: _SharedTable(shared, winners))
        settings._warn_about_shared_ports(targeting or _SharedTargeting(),
                                          lines.append)
    finally:
        mp.undo()
        i18n.set_language(previous)
    return lines


def test_a_target_sharing_a_port_is_said_out_loud_once():
    """...and a target that shares nothing stays quiet, or the line becomes noise."""
    noisy = _shared_warning({5353: frozenset({11, 12, 13})}, {5353: 11})
    quiet = _shared_warning({1900: frozenset({77, 78})}, {1900: 77})

    check("a shared target port is announced", len(noisy) == 2, f"({noisy})")
    check("and the line names the port and who else has it",
          "5353" in noisy[0] and "svchost.exe" in noisy[0] and "adb.exe" in noisy[0],
          f"({noisy})")
    check("the port carries its service name, not a bare number",
          "mDNS" in noisy[0], f"({noisy[0]!r})")
    check("and the other ports are accounted for once, at the end",
          "unaffected" in noisy[-1], f"({noisy[-1]!r})")
    check("a target that shares nothing says nothing", quiet == [], f"({quiet})")


def test_the_targets_own_program_is_not_reported_as_a_stranger():
    """A second process of the SAME program must not read as somebody else's.

    Reported from a real session: targeting ``chrome`` produced "other processes have
    this port open too (... chrome.exe ...)", which reads as targeting being broken.
    It is not - ``ports_shared_with_others`` subtracts by PID, and ``ProcessTargeting``
    only ever sees pids that WON a port in the collapsed map, so a second pid of the
    same program that lost every collapse survives the subtraction. Measured against
    the real table: targeting ``msedge`` matched pid 55120 while pid 47664 - also
    ``msedge.exe`` - came back listed as a stranger.
    """
    lines = _shared_warning({5353: frozenset({11, 12, 14})}, {5353: 11})
    check("the warning was said", lines, f"({lines})")
    body = lines[0]
    check("the sibling process is still named", "msedge.exe" in body, f"({body!r})")
    check("...but marked as the target's own program rather than a stranger",
          "msedge.exe (same program as your target)" in body, f"({body!r})")
    check("a genuinely different program carries no such mark",
          "svchost.exe (same" not in body, f"({body!r})")


def test_the_warning_says_which_of_the_two_outcomes_applies():
    """It used to offer both ("may break theirs, or miss the target's") while the
    tool already knew which one. The collapse WINNER decides it: in the target set
    means the port is in scope and everyone on it gets impaired, otherwise the
    target's own traffic there is skipped."""
    hits = _shared_warning({5353: frozenset({11, 12})}, {5353: 11})[0]
    misses = _shared_warning({5353: frozenset({11, 12})}, {5353: 12})[0]

    check("the target owning the port is told its neighbours get broken too",
          "their traffic gets broken too" in hits, f"({hits!r})")
    check("...and is not also told the opposite", "skipped" not in hits, f"({hits!r})")
    check("losing the port is told the target's traffic is skipped",
          "will be skipped" in misses, f"({misses!r})")
    check("...and names who holds it instead", "svchost.exe" in misses,
          f"({misses!r})")
    check("...and is not also told its neighbours get broken",
          "gets broken too" not in misses, f"({misses!r})")


def test_a_port_that_left_the_map_is_not_described_from_stale_data():
    """The winner is read from one snapshot. If a rebuild lands between the two
    reads the port is simply gone, and a stale diagnostic is worse than none."""
    lines = _shared_warning({5353: frozenset({11, 12})}, {})
    check("nothing is claimed about a port with no known owner", lines == [],
          f"({lines})")


def test_known_ports_are_named_and_unknown_ones_are_left_alone():
    """"5353" reads as a fault. "5353 (mDNS)" reads as the ordinary state it is.

    The names come from the machine's own services file, so this asserts the SHAPE
    plus the two entries the overlay carries because that file is unhelpful for
    them - mDNS is absent from it on Windows, and DHCP is registered under its
    historical BOOTP names.
    """
    from beantester.settings import describe_port
    check("mDNS is named even though Windows omits it from services",
          describe_port(5353) == "5353 (mDNS)", f"({describe_port(5353)!r})")
    check("DHCP is named, not left as bootps", describe_port(67) == "67 (DHCP)",
          f"({describe_port(67)!r})")
    check("an ephemeral port stays a bare number", describe_port(49664) == "49664",
          f"({describe_port(49664)!r})")
    check("a nonsense port never raises", describe_port(None) == "None",
          f"({describe_port(None)!r})")
    check("out-of-range never raises", describe_port(999999) == "999999",
          f"({describe_port(999999)!r})")


def test_the_shared_port_warning_is_actually_wired_into_apply_targeting():
    """The unit test above proves the SENTENCE; this proves it is SAID.

    Written because a mutant survived: deleting the call from ``apply_targeting``
    left the direct-call test perfectly green. A diagnostic nobody invokes is the
    same as no diagnostic, and it fails exactly the way this project hates - the
    session looks clean.
    """
    from beantester import portmap, settings

    class _Table:
        def refresh_if_stale(self, now=None, miss=False):
            return False

        def shared_ports(self):
            return {5353: frozenset({11, 12})}

        def snapshot(self):
            return {5353: 11}

        def name_of(self, pid, cheap=False):
            return {11: "myapp.exe", 12: "svchost.exe"}.get(pid, "")

    class _Targeting:
        matched = True

        def pids(self):
            return {11}

        def names(self):
            return ["myapp.exe"]

        def describe(self):
            return "myapp.exe"

        def refresh(self, *a, **k):
            return frozenset({5353})

        def __len__(self):
            return 1

    class _Engine:
        def target_for(self, _matcher):
            return _Targeting()

        def set_target(self, *_a, **_k):
            pass

    import pytest as _pytest
    mp = _pytest.MonkeyPatch()
    lines = []
    try:
        mp.setattr(portmap, "default_table", lambda: _Table())
        settings.apply_targeting(_Engine(), "myapp.exe", lines.append)
    finally:
        mp.undo()

    check("applying a target announced what it matched",
          any("myapp.exe" in ln for ln in lines), f"({lines})")
    check("...and warned that one of its ports is shared",
          any("5353" in ln and "svchost.exe" in ln for ln in lines), f"({lines})")


def test_every_socket_table_failing_falls_back_to_psutil(monkeypatch):
    """Nothing answered at all: return None so refresh() tries psutil instead."""
    from beantester.portmap import _Native

    native = _Native.__new__(_Native)
    native._sizes = {}
    _spy_on_crashlog(monkeypatch)
    monkeypatch.setattr(native, "_table", lambda *a: False)

    check("no usable map -> None, so the psutil fallback runs",
          native.port_pid_map() is None)


def test_engine_records_a_broken_port_table_instead_of_going_quiet(monkeypatch):
    """The capture thread keeps going (a blank name beats a dead session), but the
    reason no longer disappears. ``once()``, not ``note()``: this is the hot path."""
    class _Broken:
        # The engine reads the PID (the live socket map first, this poller second) and
        # then the NAME from the cache with cheap=True - it does not call
        # process_for_port() any more. The signatures MATTER: a fake missing the
        # ``cheap`` keyword would raise TypeError instead, and the test would pass
        # while exercising the wrong failure entirely.
        def pid_for(self, port):
            raise RuntimeError("boom")

        def name_of(self, pid, cheap=False):
            raise RuntimeError("boom")

    recorded = _spy_on_crashlog(monkeypatch)
    engine = BeanEngine()
    engine._ports = _Broken()

    check("a failed name lookup still yields a blank", engine._process_for(1234) == "")
    check("a failed pid lookup still yields None", engine._pid_for(1234) is None)
    check("both failures were recorded", len(recorded) == 2, f"({recorded})")
    check("recorded as hot-path, so they cost one traceback each",
          all(kw.get("source") == "hot-path" for kw in recorded), f"({recorded})")


# -- PID reuse: a pid is a number the OS hands out, not an identity ---------- #
#
# Windows recycles PIDs, and targeting matches on the process NAME, so a cached
# name that outlives its process is not a cosmetic problem. Both directions were
# reproduced against the real port table before these guards existed:
#   * the target restarts onto a recycled pid  -> it is NOT impaired
#   * an innocent process inherits the old pid -> it IS impaired
# The second one matters most: this tool breaks networking, and breaking an
# application the user never named is the worst thing it can do quietly.


class _World:
    """A controllable OS: ports, processes, and each process's start time."""

    def __init__(self):
        self.ports = {}          # port -> pid
        self.procs = {}          # pid  -> (name, ppid)
        self.created = {}        # pid  -> start time (absent = "cannot tell")

    def install(self, monkeypatch):
        from beantester import portmap
        # the bulk fallback must use this fake table, not the real toolhelp snapshot
        monkeypatch.setattr(portmap, "_ALLOW_NATIVE_PROCESSES", False)
        monkeypatch.setattr(portmap, "_psutil_port_pid_map",
                            lambda owners=None: dict(self.ports))
        monkeypatch.setattr(portmap, "_psutil_created",
                            lambda pid: self.created.get(int(pid)))
        monkeypatch.setattr(portmap, "_psutil_process_info", lambda pid: (
            (self.procs[int(pid)][0], self.procs[int(pid)][1], self.created.get(int(pid)))
            if int(pid) in self.procs else None))
        monkeypatch.setattr(portmap, "_psutil_process_table", lambda: {
            p: (n, pp, self.created.get(p)) for p, (n, pp) in self.procs.items()})
        table = portmap.PortTable()
        table._native = None
        return table


def _targeting_on(table, expr="myapp"):
    from beantester.targeting import ProcessTargeting
    return ProcessTargeting(parse_target(expr), table=table)


def test_a_target_restarting_onto_a_recycled_pid_is_still_impaired(monkeypatch):
    world = _World()
    table = world.install(monkeypatch)
    targeting = _targeting_on(table)

    world.procs[5000] = ("oldapp.exe", 1); world.created[5000] = 1000.0
    world.ports[9001] = 5000
    targeting.refresh()
    check("an unrelated process is not targeted", targeting.ports() == set(),
          f"({targeting.ports()})")

    # same pid number, different process: the target has restarted into it
    world.procs[5000] = ("myapp.exe", 1); world.created[5000] = 2000.0
    world.ports.clear(); world.ports[9002] = 5000
    targeting.refresh()
    check("the tool sees the new name", table.name_of(5000) == "myapp.exe",
          f"({table.name_of(5000)!r})")
    check("the restarted target IS impaired", 9002 in targeting.ports(),
          f"({sorted(targeting.ports())})")


def test_an_innocent_process_inheriting_the_pid_is_not_impaired(monkeypatch):
    world = _World()
    table = world.install(monkeypatch)
    targeting = _targeting_on(table)

    world.procs[6000] = ("myapp.exe", 1); world.created[6000] = 1000.0
    world.ports[9003] = 6000
    targeting.refresh()
    check("the target is impaired while it lives", 9003 in targeting.ports())

    world.procs[6000] = ("innocent.exe", 1); world.created[6000] = 2000.0
    world.ports.clear(); world.ports[9004] = 6000
    targeting.refresh()
    check("the tool sees the new name", table.name_of(6000) == "innocent.exe",
          f"({table.name_of(6000)!r})")
    check("a process the user never named is NOT impaired",
          9004 not in targeting.ports(), f"({sorted(targeting.ports())})")


def test_a_living_process_keeps_its_cached_entry(monkeypatch):
    """The other direction: verifying must not turn into re-resolving."""
    world = _World()
    table = world.install(monkeypatch)
    targeting = _targeting_on(table)
    world.procs[7000] = ("myapp.exe", 1); world.created[7000] = 1000.0
    world.ports[9005] = 7000
    targeting.refresh()

    entries = len(table._info)
    for _ in range(30):
        table.name_of(7000)
    check("the entry survives repeated reads", table._info.get(7000) is not None)
    check("and the cache does not churn", len(table._info) == entries,
          f"({len(table._info)} vs {entries})")


def test_an_unverifiable_environment_still_resolves_names(monkeypatch):
    """No start times available (the psutil fallback) must DEGRADE, not break.

    Treating "cannot tell" as "recycled" looked like the safe reading and was in
    fact a way to destroy the cache wholesale: every lookup would evict,
    re-resolve, fail to stamp, and evict again, so process names came back empty.
    Hardening must not degrade the environments it cannot harden - there, the TTL
    remains the only bound, exactly as before.
    """
    world = _World()
    table = world.install(monkeypatch)
    targeting = _targeting_on(table)
    world.procs[7100] = ("myapp.exe", 1)          # note: no start time at all
    world.ports[9006] = 7100
    targeting.refresh()

    check("names still resolve", table.name_of(7100) == "myapp.exe",
          f"({table.name_of(7100)!r})")
    check("the target is still impaired", 9006 in targeting.ports())
    for _ in range(50):
        table.name_of(7100)
    check("an unverifiable entry is kept, not evicted on every read",
          table._info.get(7100) is not None)


def test_the_info_cache_expires_below_the_old_512_threshold(monkeypatch):
    """`_expire_info` used to bail out under 512 entries - so on a normal machine
    (26-343) it never ran at all, and `info()` bumped the timestamp on every HIT,
    which made a busily-read entry immortal."""
    from beantester import portmap
    world = _World()
    table = world.install(monkeypatch)
    world.procs[7200] = ("myapp.exe", 1); world.created[7200] = 1000.0
    world.ports[9007] = 7200
    table.refresh(force=True)
    table.name_of(7200)
    stamp = table._info[7200][3]
    for _ in range(20):
        table.name_of(7200)
    check("a busily-read entry does not renew its own timestamp",
          table._info[7200][3] == stamp)

    monkeypatch.setattr(portmap, "INFO_TTL_S", 0.05)
    time.sleep(0.08)
    table.refresh(force=True)
    check("stale entries are swept even with a tiny cache",
          7200 not in table._info, f"({len(table._info)} entries)")


def test_a_pid_that_loses_every_socket_is_forgotten_at_once(monkeypatch):
    """A pid can only be handed to somebody else after its owner exits, and exiting
    closes its sockets - so this is the moment to forget the name, before the OS
    can reissue the number."""
    world = _World()
    table = world.install(monkeypatch)
    world.procs[8000] = ("myapp.exe", 1); world.created[8000] = 1000.0
    world.procs[8001] = ("other.exe", 1); world.created[8001] = 1000.0
    world.ports[9008] = 8000; world.ports[9009] = 8001
    table.refresh(force=True)
    table.name_of(8000); table.name_of(8001)

    del world.ports[9009]                      # 8001 exits; 8000 keeps its socket
    table.refresh(force=True)
    check("the departed pid was forgotten", 8001 not in table._info)
    check("the surviving pid kept its entry", 8000 in table._info)


def test_the_capture_thread_never_reaches_psutil_for_a_name(monkeypatch):
    """`allow_refresh=False` must mean "do not touch the OS", NAME lookup included.

    Two separate leaks lived here. Verifying an identity is a psutil call, so
    adding the reuse check put one back on the packet path (12 of them across a
    short run, once per new flow - and this tool gets pointed at load generators,
    where new flows arrive in thousands per second). And on a cache MISS the older
    code resolved from whatever thread asked, so the capture thread could trigger a
    5 ms lookup or even a 1.7 s `process_iter()`. Gating the socket-table rebuild
    alone left both open.
    """
    from beantester import portmap
    touched = []
    monkeypatch.setattr(portmap, "_psutil_created",
                        lambda pid: touched.append("verify"))
    monkeypatch.setattr(portmap, "_psutil_process_info",
                        lambda pid: touched.append("resolve"))
    monkeypatch.setattr(portmap, "_psutil_process_table",
                        lambda: touched.append("bulk") or {})

    table = portmap.PortTable()
    table._native = None
    table._info = {4242: ("app.exe", 1, 1000.0, time.monotonic())}
    table._ports = {5555: 4242}

    check("a cached name comes back", table.name_of(4242, cheap=True) == "app.exe")
    check("...without asking the OS", touched == [], f"({touched})")

    table._info.clear()
    check("an uncached name is blank rather than resolved",
          table.name_of(4242, cheap=True) == "")
    check("...still without asking the OS", touched == [], f"({touched})")

    # and the verified path, which runs on the resolver, DOES ask
    table._info = {4242: ("app.exe", 1, 1000.0, time.monotonic())}
    table.name_of(4242)
    check("the verified path checks identity", touched == ["verify"], f"({touched})")


def test_names_are_warmed_for_the_connection_log_without_a_target(monkeypatch):
    """The capture thread may only READ the name cache, so somebody must fill it.

    The resolver fills it for the PIDs it matches - but only while a target is set,
    and most sessions have none. Without this the connection log's process column
    came back empty, which is the exact bug the column was added to fix.
    """
    world = _World()
    table = world.install(monkeypatch)
    world.procs[8100] = ("app.exe", 1); world.created[8100] = 1000.0
    world.ports[9100] = 8100
    table.refresh(force=True)

    check("nothing is cached until somebody warms it", 8100 not in table._info)
    check("and a cheap read is honest about that",
          table.name_of(8100, cheap=True) == "")

    table.warm_names()
    check("warming resolves every socket-owning pid", table._info.get(8100) is not None)
    check("so the capture thread's cheap read now answers",
          table.name_of(8100, cheap=True) == "app.exe")


# -- the refresh lock: the capture thread waits on exactly what it holds ------- #
def test_the_socket_table_is_collected_without_holding_the_lock():
    """The CAPTURE THREAD takes this lock too - ``name_of(cheap=True)`` -> ``info()``
    in ``engine._process_for`` - so whatever ``refresh()`` holds it for, the packet
    path can be made to wait for, and a stalled capture thread means WinDivert is
    queueing the user's packets (convention 20).

    MEASURED 2026-07-25 (Win11, CPython 3.14, elevated): with the collection inside the
    lock the hold scaled with the socket table - 0.303 ms at 10 000 sockets, 3.555 ms at
    100 000 - and a network tester is exactly what gets pointed at 100 000 connections.
    With the collection and the departed-pid diff outside it, the hold is FLAT at
    ~0.018 ms whatever the size, which is a 188x shorter hold at the top of that range.

    Probed from ANOTHER thread on purpose: ``_lock`` is an RLock, so a same-thread
    acquire would succeed even while the lock was held and would prove nothing.
    """
    from beantester import portmap

    table = portmap.PortTable()
    probed = {}

    class _Native:
        def port_pid_map(self, owners=None):
            def probe():
                got = table._lock.acquire(timeout=1.0)
                probed["free"] = got
                if got:
                    table._lock.release()

            thread = threading.Thread(target=probe)
            thread.start()
            thread.join(timeout=3.0)
            return {5000: 1234}

    table._native = _Native()
    table.native = True
    check("the refresh installed the collected map", table.refresh(force=True) is True)
    check("the lock was FREE while the socket table was being collected",
          probed.get("free") is True, f"({probed})")


def test_collected_hands_over_the_map_and_when_it_was_gathered_together():
    """``collected()`` exists because ``SocketWatcher.reconcile`` has to weigh this
    data against what its own SOCKET events say, and cannot do that without knowing
    how old the data is.

    Two properties, and the second is the one that matters: the stamp must be the
    moment the collection STARTED, never later than that. A stamp that ran ahead of
    its own data would let a stale walk out-rank a fresh event, which is exactly the
    bug the caller uses this to avoid.
    """
    from beantester import portmap

    table = portmap.PortTable(clock=time.monotonic)
    before = time.monotonic()
    table.refresh(force=True)
    after = time.monotonic()

    ports, at = table.collected()
    check("the map is the same one snapshot() reports", ports == table.snapshot(),
          f"({len(ports)} vs {len(table.snapshot())})")
    check("the stamp is not newer than the moment the collection began",
          before <= at <= after, f"(before={before} at={at} after={after})")

    # ...and it does not drift on a call that decided not to refresh
    again, at_again = table.collected()
    check("a second call reports the same collection", at_again == at,
          f"({at_again} vs {at})")


def test_an_older_collection_does_not_overwrite_a_newer_map():
    """Collecting outside the lock lets two refreshes overlap, so a slow one must not
    move the map BACKWARDS when it finishes late.

    Each call takes a generation before it starts and installs only if nothing newer
    landed meanwhile. Driven by a gate rather than by sleeps, so it asserts the ordering
    rule instead of racing the scheduler.
    """
    from beantester import portmap

    table = portmap.PortTable()
    gate = threading.Event()
    stale, fresh = {1111: 11}, {2222: 22}

    class _Slow:
        def port_pid_map(self, owners=None):
            gate.wait(timeout=5.0)
            return dict(stale)

    class _Fast:
        def port_pid_map(self, owners=None):
            return dict(fresh)

    table._native = _Slow()
    table.native = True
    slow = threading.Thread(target=lambda: table.refresh(force=True))
    slow.start()
    time.sleep(0.05)                    # the slow call has taken its generation
    table._native = _Fast()             # the slow one already captured its own native
    check("the second refresh installed", table.refresh(force=True) is True)
    check("...and its map is the one in place", table.snapshot() == fresh,
          f"({table.snapshot()})")

    gate.set()                          # now let the STALE collection finish
    slow.join(timeout=5)
    check("the stale collection did not move the map backwards",
          table.snapshot() == fresh, f"({table.snapshot()})")
