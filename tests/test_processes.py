"""Target-process resolution: one expression -> the ports of every matching process.

psutil is faked, so the tests run anywhere (the real lookup needs a live system).
"""
import sys
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
    previous = sys.modules.get("psutil")
    sys.modules["psutil"] = module

    # Force the psutil fallback everywhere the native (Windows) path would win.
    native_factory = portmap._make_native
    portmap._make_native = lambda: None
    portmap.reset_default_table()

    try:
        yield module
    finally:
        portmap._make_native = native_factory
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

    def fake_table(proto, family, out):
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
        # the signature MATTERS: the engine reads with allow_refresh=False (it must
        # never make the capture thread rebuild the table). A fake missing the
        # keyword would raise TypeError instead, and the test would pass while
        # exercising the wrong failure entirely.
        def process_for_port(self, port, now=None, allow_refresh=True):
            raise RuntimeError("boom")

        def pid_for(self, port):
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
        monkeypatch.setattr(portmap, "_psutil_port_pid_map", lambda: dict(self.ports))
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
