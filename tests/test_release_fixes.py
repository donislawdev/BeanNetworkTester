"""Regressions for the bugs fixed on the way to the first public release (1.3).

Every test here maps to something that was reported (or found) during the
pre-release audit. Read them as "this must never come back".
"""
import json
import os
import tempfile
import time

import pytest

import beantester as bnt
from beantester import portmap
from beantester.engine import BeanEngine
from beantester.scenario import load_scenario_file, parse_scenario
from beantester.summary import settings_summary
from beantester.targeting import ProcessTargeting
from fakes import FakeDivert, FakePacket, check


# -- the preview strip used to round fractions away --------------------------- #
def test_summary_keeps_fractions():
    bnt.set_language("en")
    s = dict(bnt.DEFAULT_SETTINGS, loss=0.5, corrupt=0.2, latency=0.4, down=0.9)
    text = settings_summary(s, "en")
    check("0.5% loss is not printed as 0%", "0.5% loss" in text, f"({text})")
    check("0.2% corruption survives", "0.2%" in text, f"({text})")
    check("0.9 KB/s is not rounded up to 1", "0.9 KB/s" in text, f"({text})")


def test_summary_does_not_advertise_limits_a_schedule_replaces():
    bnt.set_language("en")
    text = settings_summary(dict(bnt.DEFAULT_SETTINGS, down=256, up=128,
                                 rate_schedule="5:500:500"), "en")
    check("the constant limit is not shown next to a schedule",
          "256" not in text and "128" not in text, f"({text})")
    check("the schedule is shown", "throughput" in text.lower(), f"({text})")


# -- the session clock kept running after STOP -------------------------------- #
def test_the_session_clock_freezes_on_stop():
    engine = BeanEngine()
    engine.start("test", divert=FakeDivert([]))
    time.sleep(0.05)
    engine.stop()
    first = engine.session_info()
    time.sleep(0.15)
    second = engine.session_info()
    check("elapsed stops growing after STOP", first["elapsed"] == second["elapsed"],
          f"({first['elapsed']} -> {second['elapsed']})")
    check("the session reports when it stopped", bool(second["stop"]))
    check("now_ref is frozen too", engine.now_ref() == engine.now_ref())


# -- link outages were counted as packet loss --------------------------------- #
def test_a_link_outage_is_not_counted_as_loss():
    engine = BeanEngine()
    engine.core.set_flap(True, 10.0, 100.0)      # the link is down all the time
    engine.start("test", divert=FakeDivert([FakePacket(size=100) for _ in range(5)]))
    time.sleep(0.2)
    engine.stop()
    st = engine.stats_snapshot()
    check("outage drops have their own counter", st["drop_flap"] == 5, f"({st})")
    check("outage drops are not reported as loss", st["drop_loss"] == 0, f"({st})")


# -- scenarios: any JSON used to load as an empty scenario --------------------- #
def test_a_random_json_is_not_a_scenario():
    for data in ({"foo": "bar"}, [], {"steps": []}, "nope", {"steps": [{"loss": 5}]},
                 {"steps": [{"at": 1, "settings": {"nosuch": 1}}]},
                 {"steps": [{"at": 1, "action": "explode"}]},
                 {"steps": [{"at": 1}]}):
        with pytest.raises(ValueError):
            parse_scenario(data)


def test_a_real_scenario_still_loads():
    scenario = parse_scenario({"loop": True,
                               "steps": [{"at": 2, "settings": {"loss": 5}},
                                         {"at": 4, "action": "reset_tcp"}]})
    check("steps are kept", len(scenario.steps) == 2)
    check("loop is kept", scenario.loop is True)
    check("a shipped example scenario is valid",
          len(load_scenario_file(os.path.join(
              os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
              "scenarios", "cafe-wifi.json")).steps) >= 1)


# -- persistence: a broken file must not be swallowed, nor overwritten --------- #
def test_a_broken_profile_file_is_quarantined_and_reported():
    from beantester.gui.profiles import ProfileStore
    path = os.path.join(tempfile.mkdtemp(), "profiles.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ this is not json")
    store = ProfileStore(path)
    check("a broken profile file does not crash the app", store.names() == [])
    check("the problem is reported, not swallowed", bool(store.problem))
    backups = [n for n in os.listdir(os.path.dirname(path)) if "corrupt" in n]
    check("the broken file is kept, not clobbered", len(backups) == 1, f"({backups})")


def test_profiles_are_written_atomically_and_validated():
    from beantester.gui.profiles import ProfileStore
    path = os.path.join(tempfile.mkdtemp(), "profiles.json")
    store = ProfileStore(path)
    store.set("mine", {k: 1.0 for k in ("loss", "corrupt", "dup", "lat", "jit",
                                        "down", "up")})
    check("saving works", store.persist() is None)
    check("no temporary file is left behind", not os.path.exists(path + ".tmp"))

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"good": {"loss": 1, "corrupt": 0, "dup": 0, "lat": 0, "jit": 0,
                            "down": 0, "up": 0},
                   "junk": "not a profile"}, f)
    reloaded = ProfileStore(path)
    check("a valid profile survives", "good" in reloaded)
    check("a junk entry is dropped", "junk" not in reloaded)
    check("dropping it is reported", bool(reloaded.problem))


# -- targeting: the live port set ---------------------------------------------- #
class _FakeTable:
    """A socket table under the test's control."""

    def __init__(self, ports=None, info=None):
        self.ports = dict(ports or {})           # port -> pid
        self._info = dict(info or {})            # pid -> (name, ppid)
        self.refreshes = 0

    def refresh(self, now=None, force=False):
        self.refreshes += 1
        return True

    def snapshot(self):
        return dict(self.ports)

    def name_of(self, pid):
        return self._info.get(pid, ("", None))[0]

    def ancestors(self, pid, depth=8):
        chain, current = [], self._info.get(pid, ("", None))[1]
        while current and len(chain) < depth:
            name, parent = self._info.get(current, ("", None))
            chain.append((current, name))
            current = parent
        return chain


def _targeting(expression, table):
    return ProcessTargeting(bnt.parse_target(expression), table=table)


def test_targeting_follows_the_process_tree():
    """chrome.exe (the browser process) owns no sockets - its child does."""
    table = _FakeTable(ports={5001: 200, 5002: 201, 6000: 300},
                       info={100: ("chrome.exe", 1),      # browser process, no sockets
                             200: ("chrome.exe", 100),    # network service
                             201: ("chrome.exe", 100),
                             300: ("firefox.exe", 1)})
    by_pid = _targeting("100", table)             # the PID of the browser window
    by_pid.refresh()
    check("a PID covers the whole process tree", by_pid.ports() == {5001, 5002},
          f"({by_pid.ports()})")
    check("other processes are untouched", 6000 not in by_pid.ports())


def test_an_explicit_exclusion_beats_an_inherited_match():
    table = _FakeTable(ports={5001: 200, 5003: 202},
                       info={100: ("chrome.exe", 1),
                             200: ("chrome.exe", 100),
                             202: ("chromedriver.exe", 100)})
    targeting = _targeting("chrome, !chromedriver", table)
    targeting.refresh()
    check("the parent does not pull an excluded child back in",
          targeting.ports() == {5001}, f"({targeting.ports()})")


def test_an_unknown_port_forces_an_early_refresh():
    """A brand-new connection must not run unimpaired until the next scan."""
    clock = [100.0]
    table = _FakeTable(ports={5001: 200}, info={200: ("chrome.exe", 1)})
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table,
                                 clock=lambda: clock[0])
    targeting.refresh(now=clock[0])
    before = targeting.refreshes

    # the app opens a socket right now; the cached set knows nothing about it
    table.ports[5002] = 200
    clock[0] += 0.06                    # less than the routine interval (0.30 s)
    check("the new port is picked up on the miss", 5002 in targeting)
    check("which cost exactly one extra refresh",
          targeting.refreshes == before + 1, f"({targeting.refreshes})")

    # ...but a miss storm cannot turn into a rebuild per packet
    refreshes = targeting.refreshes
    for _ in range(50):
        assert 9999 not in targeting
    check("misses are rate limited", targeting.refreshes == refreshes,
          f"({targeting.refreshes} vs {refreshes})")


def test_targeting_reports_when_it_matches_nothing():
    table = _FakeTable(ports={5001: 200}, info={200: ("firefox.exe", 1)})
    targeting = _targeting("chrome", table)
    targeting.refresh()
    check("nothing matched", targeting.matched is False)
    check("and it says so", targeting.describe() == "(none)")


def test_the_engine_keeps_one_live_targeting_per_expression():
    engine = BeanEngine()
    matcher = bnt.parse_target("chrome")
    first = engine.target_for(matcher)
    second = engine.target_for(bnt.parse_target("chrome"))
    check("the same expression reuses the live object (and its caches)",
          first is second)
    third = engine.target_for(bnt.parse_target("firefox"))
    check("a new expression gets a new one", third is not first)
    engine.set_target(False)
    check("turning targeting off drops it", engine.targeting() is None)


def test_the_port_table_has_a_working_fallback():
    """Without the native path the table still resolves ports (psutil)."""
    table = portmap.PortTable()
    table._native = None
    table.native = False
    table.refresh(force=True)
    check("the fallback produces a mapping (or an empty one, never a crash)",
          isinstance(table.snapshot(), dict))


# -- filters ------------------------------------------------------------------- #
def test_ipv6_is_captured():
    for key, _, expression in bnt.FILTER_DEFS:
        check(f"filter '{key}' is not IPv4-only",
              "ipv6" in expression or "icmpv6" in expression, f"({expression})")


# -- the token bucket must charge for duplicates -------------------------------- #
def test_a_duplicate_is_charged_to_the_speed_limit():
    core = bnt.BeanCore()
    core.set_params(0, 0, 100, 0, 0, 1, 0)        # 1 KB/s down, every packet duplicated
    core.reset_buckets(0.0)

    class _AlwaysDup:
        @staticmethod
        def random():
            return 0.0

        @staticmethod
        def uniform(a, b):
            return 0.0

    decision = core.decide(1024, False, 5000, 0.0, _AlwaysDup())
    check("the packet is duplicated", len(decision.releases) == 2)
    check("both copies are paid for", core._bucket[False] >= 2.0,
          f"({core._bucket[False]})")


# -- the CSV column names are meant for humans ---------------------------------- #
def test_the_csv_has_readable_column_names():
    """Read as text: importing gui.app here would need tkinter, which the CLI does not."""
    source = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "beantester", "gui", "app.py"), encoding="utf-8").read()
    check("'seen' is not a column name", '"seen": "packets_seen"' in source)
    check("link outages have a name too", '"drop_flap": "dropped_link_outage"' in source)


# -- lenient preset names (Polish "ł" does not decompose) ------------------------ #
def test_preset_names_fold_stroke_letters():
    check("'Lacze satelitarne' resolves",
          bnt.resolve_preset("Lacze satelitarne") == "presets.satellite")
    check("'Slabe WiFi' resolves",
          bnt.resolve_preset("Slabe WiFi") == "presets.weak_wifi")


# -- the support link must be https, and the driver must not linger -------------- #
def test_the_support_link_is_https():
    check("the donate button opens an https URL",
          bnt.SUPPORT_URL.startswith("https://"), f"({bnt.SUPPORT_URL})")
    check("and it is the project's support page",
          bnt.SUPPORT_URL == "https://donislawdev.com/support/", f"({bnt.SUPPORT_URL})")


def test_the_driver_is_only_unloaded_when_it_was_actually_loaded():
    """A --simulate run never loads a driver, so exiting must not pay for one.

    When a real session DID load it, the kernel keeps WinDivert64.sys open - and
    the app's own folder cannot be deleted, even after its contents are gone
    (a deleted-but-open file leaves the directory in a pending-delete state).
    """
    from beantester import driver
    driver._DRIVER_USED[0] = False
    check("nothing to unload after a simulated run", driver.release_on_exit() == [])
    check("and the flag stays down", driver.driver_used() is False)

    driver.mark_driver_used()
    check("a real session arms the exit cleanup", driver.driver_used() is True)
    driver.release_on_exit()                 # off Windows this is a no-op...
    driver._DRIVER_USED[0] = False           # ...so disarm it by hand


def test_the_window_height_is_capped_too():
    from beantester.gui.scaling import max_window_size, min_window_size
    for screen in ((1920, 1080), (3840, 2160)):
        width, height = max_window_size(*screen)
        check("the cap fits on the screen",
              width <= screen[0] and height <= screen[1], f"({width}x{height})")
        check("the height is really capped, not just screen-limited",
              height <= 1000, f"({height})")
        check("the cap is above the minimum window",
              (width, height) >= min_window_size(), f"({width}x{height})")
