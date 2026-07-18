"""Target-process resolution: one expression -> the ports of every matching process.

psutil is faked, so the tests run anywhere (the real lookup needs a live system).
"""
import sys
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
