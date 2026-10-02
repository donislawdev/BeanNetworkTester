"""Target-process resolution: one expression -> the ports of every matching process.

psutil is faked, so the tests run anywhere (the real lookup needs a live system).
"""
import ctypes
import itertools
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


def test_an_apply_that_is_no_longer_live_changes_nothing(fake_psutil):
    """External review P2-12, after review of the fix: a scenario step can lose its
    session at ANY point of an apply, not only inside the slow resolve.

    ``live`` was asked only after the resolve, and by then the step had already
    put its impairment values in, published its target through ``target_for``,
    or - with no target in the step - switched the target off. Each of those
    landed in whatever session ran by then. Asked here with a step that is stale
    from the start, one door at a time.
    """
    from beantester.settings import DEFAULT_SETTINGS, apply_settings

    def stale():
        return False

    said = []                           # what the stale step says: nothing
    engine = BeanEngine()
    apply_settings(engine, dict(DEFAULT_SETTINGS, loss=50, target="chrome"), said.append,
                   live=stale)
    check("no impairment value from a stale step", engine.core.loss == 0,
          f"({engine.core.loss})")
    check("no target from a stale step", engine.targeting() is None,
          f"({engine.targeting()})")

    apply_targeting(engine, "chrome", said.append, live=stale)
    check("apply_targeting publishes nothing for a stale step",
          engine.targeting() is None and engine.core.target_active is False,
          f"({engine.targeting()})")

    running = apply_targeting(engine, "chrome", lambda *_: None)
    apply_targeting(engine, "", said.append, live=stale)
    check("nor switches the running session's target off",
          engine.targeting() is running and engine.core.target_active is True)
    check("and says nothing", not said, f"({said})")


def test_apply_targeting_logs_and_keeps_the_target_on_a_bad_expression(fake_psutil):
    """Rewritten on purpose (external review, P3-13).

    It used to be "a bad expression DISABLES targeting", and targeting off means
    every connection in the filter is impaired: the widest possible answer to an
    expression that could not be read. The engine now keeps the target it had.
    """
    engine = BeanEngine()
    lines = []
    apply_targeting(engine, ">chrome", lines.append)
    check("on a fresh engine a bad expression leaves targeting off, not a crash",
          engine.core.target_active is False)
    check("a bad expression is reported in the log", lines, f"({lines})")

    apply_targeting(engine, "chrome, !chromedriver", lambda *_: None)
    lines.clear()
    kept = apply_targeting(engine, ">chrome", lines.append)
    check("a bad expression does not switch targeting off",
          engine.core.target_active is True
          and engine.core.target_ports == {5001, 5002}, f"({engine.core.target_ports})")
    check("what is returned is the target still in force",
          kept is engine.targeting(), f"({kept!r})")
    check("and the problem is still logged", lines, f"({lines})")


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


class _Toolhelp:
    """kernel32 as Microsoft Learn documents the WIDE toolhelp calls, on any system.

    ``Process32FirstW`` fails unless ``dwSize`` is the size of the structure handed
    in; it and ``Process32NextW`` copy one process at a time into ``szExeFile``,
    a ``WCHAR[MAX_PATH]``, and return FALSE after the last. Only the W calls exist
    here: a fallback to the ANSI pair finds nothing to call.
    """
    SNAPSHOT = 77

    def __init__(self, processes, snapshot=SNAPSHOT):
        self.processes, self.snapshot, self.closed, self._next = processes, snapshot, [], 0
        # Plain functions, because the code under test sets restype and argtypes on them.
        self.CreateToolhelp32Snapshot = lambda flags, pid: self.snapshot
        self.Process32FirstW = lambda handle, ref: self._first(handle, ref)
        self.Process32NextW = lambda handle, ref: self._following(handle, ref)
        self.CloseHandle = lambda handle: self.closed.append(handle)

    def _first(self, handle, ref):
        entry = ref._obj
        fields = dict(type(entry)._fields_)
        if (entry.dwSize != ctypes.sizeof(entry) or fields["szExeFile"]._type_ is not ctypes.c_wchar
                or fields["szExeFile"]._length_ != 260):
            return False
        self._next = 0
        return self._following(handle, ref)

    def _following(self, handle, ref):
        if handle != self.snapshot or self._next >= len(self.processes):
            return False
        entry = ref._obj
        entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile = (
            self.processes[self._next])
        self._next += 1
        return True


def test_the_snapshot_walks_every_process_through_the_wide_calls(monkeypatch):
    """The walk itself, on every system the suite runs on: each process once, its name
    as it is, the parent kept, the snapshot closed, and nothing for a snapshot the
    system refused. The Windows test below is the same claim on a real process."""
    from beantester import portmap
    processes = [(4, 0, "System"), (5000, 4, NOT_ANSI_NAME), (6000, 5000, "chrome.exe")]
    fake = _Toolhelp(processes)
    monkeypatch.setattr(portmap, "_ALLOW_NATIVE_PROCESSES", True)
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **_: fake, raising=False)
    table = portmap._toolhelp_process_table()
    check("every process, named as it is, with its parent and no start time",
          table == {pid: (name, ppid, None) for pid, ppid, name in processes}, f"({table})")
    check("the snapshot is closed once", fake.closed == [fake.SNAPSHOT], f"({fake.closed})")

    refused = _Toolhelp(processes, snapshot=ctypes.c_void_p(-1).value)
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **_: refused, raising=False)
    check("a snapshot the system refused gives no table",
          portmap._toolhelp_process_table() is None)


# Greek, Cyrillic, Japanese and Polish: no legacy ANSI code page holds all four, and
# thirty of them are more than the 260 bytes an ANSI entry has under the UTF-8 one.
NOT_ANSI_NAME = "bean_" + "Ωжあą" * 30 + ".exe"


@pytest.mark.skipif(not sys.platform.startswith("win"),
                    reason="toolhelp snapshot is Windows-only")
def test_the_snapshot_names_a_process_whose_name_is_not_ansi(monkeypatch):
    """A name outside the system code page is the name, not ``?`` and not cut off.

    The snapshot used the ANSI entry points, which convert the name first: under
    code page 1252 a character it lacks became ``?``, and under UTF-8 a long name
    overran the field. Targeting such a process by name then missed it, and the
    snapshot overwrote the right name the handle read had cached. A copy of
    ``cmd.exe`` under this name is the process: it waits on its piped input and
    starts nothing.
    """
    import os
    import shutil
    import subprocess
    import tempfile
    from beantester import portmap
    try:
        ansi = NOT_ANSI_NAME.encode("mbcs")
    except UnicodeEncodeError:
        ansi = None
    check("an ANSI entry could not carry this name on this machine",
          ansi is None or len(ansi) >= 260, f"({None if ansi is None else len(ansi)} bytes)")
    monkeypatch.setattr(portmap, "_ALLOW_NATIVE_PROCESSES", True)
    # A short directory: the full path must stay inside MAX_PATH for CreateProcess.
    root = tempfile.mkdtemp(prefix="bean")
    exe = os.path.join(root, NOT_ANSI_NAME)
    shutil.copyfile(os.path.join(os.environ["SystemRoot"], "System32", "cmd.exe"), exe)
    proc = subprocess.Popen([exe, "/d", "/q"], stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        table = portmap._toolhelp_process_table()
        handle = portmap._native_process_info(proc.pid)
    finally:
        proc.stdin.close()              # end of input: the copy exits by itself
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        shutil.rmtree(root, ignore_errors=True)
    check("the snapshot holds the process", table is not None and proc.pid in table)
    name = table[proc.pid][0]
    check("under its whole name", name == NOT_ANSI_NAME, f"({name!r})")
    check("which the handle read agrees with", handle is not None and handle[0] == name,
          f"({handle!r})")
    verified = {proc.pid: (handle[0], handle[1], handle[2], 0.0)}
    check("so the snapshot leaves the verified entry alone",
          proc.pid not in portmap._snapshot_entries(verified, table, 1.0))


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


def _targeting_on(table, expr="myapp", **kw):
    from beantester.targeting import ProcessTargeting
    return ProcessTargeting(parse_target(expr), table=table, **kw)


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


# -- a pid typed as a NUMBER names a process, not the number (review P2-9) ----- #
#
# Windows hands a freed pid to a new process after 19-36 s (measured with 300
# processes). A target written as `1234` followed the NUMBER, so whoever got it
# next was impaired, and so were that process's children. Start times here are
# relative to the real clock: `time.time() + 3600` is a process that started
# after the target was set.


def test_a_pid_typed_as_a_number_is_not_handed_to_its_next_holder(monkeypatch):
    world = _World()
    table = world.install(monkeypatch)
    now = time.time()
    world.procs[1234] = ("target.exe", 1); world.created[1234] = now - 60
    world.ports[5000] = 1234
    targeting = _targeting_on(table, "1234")
    targeting.refresh()
    check("the target is in scope while it lives", targeting.ports() == {5000},
          f"({sorted(targeting.ports())})")

    # it exits; the number goes to an innocent process, which starts a child
    world.procs = {1234: ("innocent.exe", 1), 2000: ("innocent-child.exe", 1234)}
    world.created = {1234: now + 3600, 2000: now + 3601}
    world.ports = {7000: 1234, 7001: 2000}
    targeting.refresh()
    check("the next holder of the number is not the target",
          7000 not in targeting.ports(), f"({sorted(targeting.ports())})")
    check("nor is its child", 7001 not in targeting.ports(),
          f"({sorted(targeting.ports())})")
    check("and no pid is taken for the target", targeting.pids() == set(),
          f"({sorted(targeting.pids())})")

    by_name = _targeting_on(table, "1234, innocent")
    by_name.refresh()
    check("a name written next to the number still catches it",
          by_name.ports() == {7000, 7001}, f"({sorted(by_name.ports())})")


def test_a_pid_excluded_by_number_stays_with_the_process_it_named(monkeypatch):
    """`app, !1234` spares one child of the app, which the tree would pull in. A
    new child of the same app that later gets the number is not that child."""
    world = _World()
    table = world.install(monkeypatch)
    now = time.time()
    world.procs = {1300: ("app.exe", 1), 1234: ("helper.exe", 1300)}
    world.created = {1300: now - 120, 1234: now - 60}
    world.ports = {5000: 1234, 5001: 1300}
    targeting = _targeting_on(table, "app, !1234")
    targeting.refresh()
    check("the excluded child is left alone", targeting.ports() == {5001},
          f"({sorted(targeting.ports())})")

    # the helper exits, and a new child of the app gets its number
    world.procs[1234] = ("worker.exe", 1300); world.created[1234] = now + 3600
    world.ports = {5001: 1300, 7000: 1234}
    targeting.refresh()
    check("the exclusion went with the process it named", 7000 in targeting.ports(),
          f"({sorted(targeting.ports())})")


def test_a_pid_nobody_held_when_the_target_was_set_matches_nobody_later(monkeypatch):
    """A typo, or a process that was already gone: the number names nobody, and
    the first process to get it later must not become the target."""
    world = _World()
    table = world.install(monkeypatch)
    targeting = _targeting_on(table, "4321")
    targeting.refresh()
    check("nothing to match yet", targeting.ports() == set(),
          f"({sorted(targeting.ports())})")

    world.procs[4321] = ("somebody.exe", 1); world.created[4321] = time.time() + 3600
    world.ports[7002] = 4321
    targeting.refresh()
    check("the process that gets the number later is not the target",
          targeting.ports() == set(), f"({sorted(targeting.ports())})")


def test_what_the_identity_check_leaves_as_it_was(monkeypatch):
    """Green before the fix as well: the mutations prove what each check guards."""
    world = _World()
    table = world.install(monkeypatch)
    world.procs = {1234: ("myapp.exe", 1), 1500: ("late.exe", 1)}
    world.created = {1500: time.time() + 3600}    # 1234: cannot tell when it started
    world.ports = {7003: 1234, 7004: 1500}

    unknown = _targeting_on(table, "1234")
    unknown.refresh()
    check("a pid whose start time cannot be told is matched as before",
          unknown.ports() == {7003}, f"({sorted(unknown.ports())})")
    for expr in ("1000-2000", ">1000"):
        numbers = _targeting_on(table, expr)
        numbers.refresh()
        check(f"{expr!r} is about numbers, so a later process is in it",
              7004 in numbers.ports(), f"({sorted(numbers.ports())})")
    mixed = _targeting_on(table, "1500, 1000-2000")
    mixed.refresh()
    check("...except a number also typed as a pid, while a later process holds it",
          mixed.ports() == {7003}, f"({sorted(mixed.ports())})")


def test_the_moment_a_target_was_set_is_read_once(monkeypatch):
    """The wall clock moves on during a session; the target's moment does not.
    Comparing with "now" instead finds every running process older than that -
    the old behaviour by another route. So this clock MOVES at every read."""
    world = _World()
    table = world.install(monkeypatch)
    ticks = itertools.count(1500.0, 1000.0)           # 1500, 2500, 3500, ...
    world.procs = {1234: ("first.exe", 1), 1235: ("close.exe", 1)}
    world.created = {1234: 1000.0, 1235: 1500.5}      # 1235: inside the slack
    world.ports = {5000: 1234, 5001: 1235}
    targeting = _targeting_on(table, "1234, 1235", wall=lambda: next(ticks))
    targeting.refresh()
    check("a process started a moment after the target was set still counts",
          targeting.ports() == {5000, 5001}, f"({sorted(targeting.ports())})")

    world.procs[1234] = ("second.exe", 1); world.created[1234] = 2000.0
    targeting.refresh()
    targeting.refresh()
    check("a process started after that moment is not the target, however late",
          targeting.ports() == {5001}, f"({sorted(targeting.ports())})")


def test_applying_the_same_pid_again_does_not_hand_it_to_its_next_holder(monkeypatch):
    """Decision D-38 (T), kept after review. Every Apply and every scenario step
    sends the target again (`apply_settings` -> `apply_targeting`), and the engine
    reuses the targeting object while the text holds. Taking that as "the target
    was set again" would make whoever got the number the target at the next change
    of ANY setting. A new text is a new moment, and that is how to re-aim."""
    world = _World()
    table = world.install(monkeypatch)
    now = time.time()
    world.procs[1234] = ("target.exe", 1); world.created[1234] = now - 300
    world.ports = {5000: 1234}
    engine = BeanEngine()
    engine._ports = table
    first = apply_targeting(engine, "1234")
    check("the target is in scope", first.ports() == {5000}, f"({sorted(first.ports())})")
    first._set_at = now - 120              # it was set two minutes ago...

    # ...the target exited since, and the number went to an innocent process
    world.procs[1234] = ("innocent.exe", 1); world.created[1234] = now - 30
    world.ports = {7000: 1234}
    again = apply_targeting(engine, "1234")
    check("the same text keeps the same target", again is first)
    check("an Apply does not hand the number to its next holder",
          again.ports() == set(), f"({sorted(again.ports())})")

    apply_targeting(engine, "innocent")
    aimed = apply_targeting(engine, "1234")
    check("a new text is a new moment: the number's holder now is the target",
          aimed is not first and aimed.ports() == {7000}, f"({sorted(aimed.ports())})")


def test_a_parent_younger_than_its_child_is_not_its_parent(monkeypatch):
    """A ppid is the number the parent HAD. Its launcher long gone, a backup
    agent's parent number went to a new chrome, and a target of `chrome` took the
    agent in (review P2-9). A time the cache does not hold never breaks the chain:
    Chrome's hardened children are named only by the snapshot, which has none."""
    from beantester import portmap
    world = _World()
    table = world.install(monkeypatch)
    world.procs = {500: ("backup_agent.exe", 900), 900: ("chrome.exe", 4),
                   501: ("helper.exe", 901), 901: ("chrome.exe", 4),
                   502: ("tab.exe", 902), 902: ("chrome.exe", 4),
                   503: ("gpu.exe", 903), 903: ("chrome.exe", 4)}
    world.created = {500: 100.0, 900: 200.0,      # 900: a NEW chrome took the number
                     901: 50.0,                   # 501: its start time is unknown
                     502: 100.0, 902: 50.0,      # a real parent, older than its child
                     503: 100.0}                 # 903: its start time is unknown
    world.ports = {6000: 500, 6001: 501, 6002: 502, 6003: 503}
    check("the walk stops at a younger 'parent'", table.ancestors(500) == [],
          f"({table.ancestors(500)})")
    for child, parent in ((501, 901), (503, 903), (502, 902)):
        chain = [pid for pid, _ in table.ancestors(child)]
        check(f"{child} keeps its parent {parent}", chain[:1] == [parent], f"({chain})")

    targeting = _targeting_on(table, "chrome")
    targeting.refresh()
    check("a target of chrome leaves the stranger's child alone",
          6000 not in targeting.ports(), f"({sorted(targeting.ports())})")
    check("...and keeps chrome's own", {6001, 6002, 6003} <= targeting.ports(),
          f"({sorted(targeting.ports())})")

    asked = []
    stamp = portmap._psutil_created
    monkeypatch.setattr(portmap, "_psutil_created", lambda pid: asked.append(pid) or stamp(pid))
    table.info(500)
    table.info(900)
    by_info, asked[:] = len(asked), []
    table.ancestors(500)
    check("the walk takes start times from the cache, not from the OS",
          len(asked) == by_info, f"({asked} vs {by_info} for info alone)")
    check("no pid, no chain - and no error", table.ancestors(None) == [])


def test_a_snapshot_does_not_strip_a_verified_start_time(monkeypatch):
    """The toolhelp snapshot names processes that will not open, and carries no
    start times. Written over a verified entry, it stripped the stamp the recycle
    check runs on and renewed the entry for 30 s: once the number was recycled,
    `name_of` kept answering with the old name (review P2-9)."""
    from beantester import portmap
    world = _World()
    table = world.install(monkeypatch)
    table.clock = itertools.count(1000.0, 5.0).__next__     # every read is later
    world.procs[100] = ("chrome.exe", 4); world.created[100] = 1111.0
    table.info(100)
    written = table._info[100][3]

    world.procs[100] = ("CHROME.EXE", 4)          # the snapshot's spelling
    world.procs[777] = ("hardened.exe", 4)        # will not open: the snapshot runs
    monkeypatch.setattr(portmap, "_psutil_process_info", lambda pid: None)
    monkeypatch.setattr(portmap, "_psutil_process_table", lambda: {
        p: (n, pp, None) for p, (n, pp) in world.procs.items()})
    check("the process that will not open is named by the snapshot",
          table.name_of(777) == "hardened.exe", f"({table.name_of(777)!r})")
    check("the verified entry keeps its start time", table._info[100][2] == 1111.0,
          f"({table._info[100]})")
    check("...and its age: a snapshot does not renew it",
          table._info[100][3] == written, f"({table._info[100][3]} vs {written})")

    world.procs[100] = ("notepad.exe", 4); world.created[100] = 2222.0   # recycled
    check("so a recycled number is noticed", table.name_of(100) == "notepad.exe",
          f"({table.name_of(100)!r})")


def test_a_snapshot_still_replaces_an_entry_about_another_process(monkeypatch):
    """The other half of keeping a verified entry: never when the snapshot shows a
    DIFFERENT process under the number - by its name, or by a start time that
    proves it - and an entry nobody could verify is refreshed as it always was."""
    from beantester import portmap
    world = _World()
    table = world.install(monkeypatch)
    table.clock = itertools.count(1000.0, 5.0).__next__
    world.procs = {100: ("chrome.exe", 4), 200: ("svc.exe", 4), 300: ("old.exe", 4)}
    world.created = {100: 1111.0, 200: 1111.0}       # 300: cannot tell when it started
    for pid in (100, 200, 300):
        table.info(pid)
    unverified = table._info[300][3]

    world.procs.update({100: ("notepad.exe", 4), 777: ("hardened.exe", 4)})
    world.created[200] = 2222.0
    monkeypatch.setattr(portmap, "_psutil_process_info", lambda pid: None)
    table.info(777)                                   # will not open: the snapshot runs
    check("another name under the number replaces the entry",
          table._info[100][0] == "notepad.exe", f"({table._info[100]})")
    check("so does a start time that proves another process",
          table._info[200][2] == 2222.0, f"({table._info[200]})")
    check("an entry nobody could verify is refreshed as before",
          table._info[300][3] > unverified, f"({table._info[300][3]} vs {unverified})")


def test_created_of_answers_for_the_process_holding_the_number_now(monkeypatch):
    world = _World()
    table = world.install(monkeypatch)
    world.procs[100] = ("chrome.exe", 4); world.created[100] = 1111.0
    table.info(100)                                 # the cache remembers chrome
    check("the start time of the process", table.created_of(100) == 1111.0,
          f"({table.created_of(100)})")
    world.procs[100] = ("notepad.exe", 4); world.created[100] = 2222.0   # recycled
    check("the current holder's, not the one the cache remembers",
          table.created_of(100) == 2222.0, f"({table.created_of(100)})")

    world.procs[300] = ("hardened.exe", 4)          # resolved without a start time...
    table.info(300)
    world.created[300] = 3333.0                     # ...which psutil CAN tell
    check("an entry without a stamp asks psutil", table.created_of(300) == 3333.0,
          f"({table.created_of(300)})")
    check("nothing to tell about a pid nobody holds", table.created_of(4242) is None)
    check("nor about no pid", table.created_of(None) is None)


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


def test_a_refresh_that_failed_does_not_make_the_old_map_look_new(monkeypatch):
    """External review P3-19: one stamp paced the refreshes AND dated the map. A
    refresh that failed stamped the OLD map with the time of the failed attempt, so
    ``SocketWatcher.reconcile`` weighed it as newer than the events received since:
    a socket that closed in between came back from the dead. The failure still
    paces the next attempt - a broken lookup is not hammered."""
    from beantester import portmap
    from beantester.socketwatch import CLOSE, CONNECT, SocketEvent, SocketWatcher

    answers, calls = iter([{8080: 500}]), []

    def lookup(owners=None):
        calls.append(1)
        return next(answers, None)          # one good walk, then only failures

    monkeypatch.setattr(portmap, "_psutil_port_pid_map", lookup)
    table = portmap.PortTable()
    table._native, table.native = None, False
    table.refresh(now=10.0, force=True)
    table.refresh(now=50.0, force=True)     # this one fails
    ports, at = table.collected()
    check("P3-19: the map keeps the time it was collected", (ports, at) == ({8080: 500}, 10.0),
          f"({ports}, {at})")
    check("the failed attempt still paces the next one",
          table.refresh(now=50.1) is False and table.refresh_if_stale(now=50.1) is False
          and len(calls) == 2, f"({len(calls)} lookups)")

    class _Names:
        def name_of(self, pid, cheap=False):
            return ""

        def ancestors(self, pid, depth=8):
            return []

    clock = [30.0]
    watcher = SocketWatcher(names=_Names(), source_factory=lambda: None,
                            clock=lambda: clock[0])
    watcher.apply(SocketEvent(CONNECT, 500, 8080))
    clock[0] = 40.0
    watcher.apply(SocketEvent(CLOSE, 500, 8080))    # after the good walk
    watcher.reconcile(*table.collected())
    check("so a socket that closed since stays closed", watcher.pid_for(8080) is None,
          f"({watcher.pid_for(8080)})")


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
