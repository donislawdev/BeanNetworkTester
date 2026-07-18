"""Settings model, config file round-trips and timeline scenarios.

Ported 1:1 from the original monolithic suite; every ``check(...)`` from the
270-assertion baseline is preserved as a pytest assertion.
"""
from beantester import BeanEngine
from fakes import check



def test_config_file_roundtrip():
    from beantester import save_config_file, load_config_file, apply_settings, DEFAULT_SETTINGS
    import tempfile, os as _os
    s = dict(DEFAULT_SETTINGS)
    s.update(loss=5, latency=200, down=100, rst_prob=10, nat_timeout=30,
             spike_prob=20, spike_ms=250, rate_schedule="1:100:0,2:400:128", dst_ip="10.0.0.9")
    path = _os.path.join(tempfile.gettempdir(), "ns_cfg_test.json")
    save_config_file(path, s)
    loaded = load_config_file(path)
    check("config: save+load consistent", loaded["rate_schedule"] == "1:100:0,2:400:128"
          and loaded["rst_prob"] == 10 and loaded["dst_ip"] == "10.0.0.9")
    sh = BeanEngine()
    apply_settings(sh, loaded, log=lambda *_: None)
    c = sh.core
    ok = (abs(c.loss - 0.05) < 1e-9 and abs(c.rst_prob - 0.10) < 1e-9
          and abs(c.nat_timeout_s - 30) < 1e-9 and abs(c.spike_s - 0.25) < 1e-9
          and len(c.schedule) == 2 and c.dst_active and c.dst_ip == "10.0.0.9")
    check("config: apply_settings restores the engine", ok)


# --- tests: reproducibility (seed) and scenarios --------------------------- #


def test_parse_schedule():
    from beantester import parse_schedule
    steps = parse_schedule("1:100:0, 2:400:128")
    check("parse_schedule: 2 steps", len(steps) == 2, f"({steps})")
    check("parse_schedule: values", steps[0] == (1.0, 100, 0) and steps[1] == (2.0, 400, 128), f"({steps})")
    check("parse_schedule: empty = []", parse_schedule("") == [] and parse_schedule(None) == [])
    bad = False
    try:
        parse_schedule("1:2")           # too few fields
    except ValueError:
        bad = True
    check("parse_schedule: invalid format raises ValueError", bad)


def test_apply_settings_maps_engine():
    from beantester import BeanEngine, apply_settings
    sh = BeanEngine()
    s = dict(loss=10, corrupt=5, dup=2, latency=100, jitter=20, down=100, up=50,
             syn_drop=30, max_size=1000, spike_prob=40, spike_ms=250, nat_timeout=5,
             rst_prob=15, rst_cooldown=3, flap_period=8, flap_down=25,
             dst_ip="1.2.3.4", dst_port=443, lan_mode=True, rate_schedule="", target="",
             block_ip="203.0.113.0/24", block_port="8080")
    apply_settings(sh, s)
    c = sh.core
    check("apply: loss", abs(c.loss - 0.10) < 1e-9, f"({c.loss})")
    check("apply: corrupt", abs(c.corrupt - 0.05) < 1e-9)
    check("apply: dup", abs(c.dup - 0.02) < 1e-9)
    check("apply: latency_s", abs(c.latency_s - 0.1) < 1e-9)
    check("apply: jitter_s", abs(c.jitter_s - 0.02) < 1e-9)
    check("apply: rate_down (B/s)", c.rate_down == 100 * 1024, f"({c.rate_down})")
    check("apply: rate_up (B/s)", c.rate_up == 50 * 1024)
    check("apply: syn_drop", abs(c.syn_drop - 0.30) < 1e-9)
    check("apply: max_size", c.max_size == 1000)
    check("apply: spike_prob", abs(c.spike_prob - 0.40) < 1e-9)
    check("apply: spike_s", abs(c.spike_s - 0.25) < 1e-9)
    check("apply: nat_timeout_s", c.nat_timeout_s == 5)
    check("apply: rst_prob", abs(c.rst_prob - 0.15) < 1e-9)
    check("apply: rst_cooldown_s", c.rst_cooldown_s == 3)
    check("apply: flap_enabled", c.flap_enabled is True)
    check("apply: flap_down", abs(c.flap_down - 0.25) < 1e-9)
    # dst_ip/dst_port are filter expressions now; a legacy int port still works
    check("apply: dst_active/ip/port", c.dst_active and c.dst_ip == "1.2.3.4"
          and c.dst_port == "443" and c.dst_port_matcher.matches(443))
    check("apply: lan_only", c.lan_only is True)
    check("apply: block_active/ip/port", c.block_active
          and c.block_ip == "203.0.113.0/24" and c.block_port == "8080"
          and c.block_ip_matcher.matches("203.0.113.9")
          and c.block_port_matcher.matches(8080))


def test_apply_settings_bad_schedule_fallback():
    from beantester import apply_settings
    logs = []
    sh = BeanEngine()
    apply_settings(sh, dict(loss=5, rate_schedule="1:2"), log=logs.append)
    check("apply: invalid schedule -> empty (no exception)", sh.core.schedule == [])
    check("apply: invalid schedule logged", any("armonogram" in m for m in logs),
          f"({logs})")
    check("apply: remaining settings applied despite the error", abs(sh.core.loss - 0.05) < 1e-9)


def test_config_file_unknown_keys_ignored():
    from beantester import load_config_file, DEFAULT_SETTINGS
    import tempfile, os as _os, json as _json
    path = _os.path.join(tempfile.gettempdir(), "ns_cfg_extra.json")
    with open(path, "w", encoding="utf-8") as f:
        _json.dump({"loss": 7, "nieznany_klucz": 123, "evil": "x"}, f)
    loaded = load_config_file(path)
    _os.remove(path)
    check("config: unknown keys rejected",
          "nieznany_klucz" not in loaded and "evil" not in loaded, f"({sorted(loaded)})")
    check("config: missing keys filled with defaults",
          set(loaded) == set(DEFAULT_SETTINGS) and loaded["loss"] == 7)


def test_load_missing_files_raise():
    from beantester import load_config_file, load_scenario_file
    for fn, name in ((load_config_file, "config"), (load_scenario_file, "scenario")):
        raised = False
        try:
            fn("/nie/istnieje/plik_%s.json" % name)
        except (FileNotFoundError, OSError):
            raised = True
        check(f"load_{name}_file: missing file raises an exception", raised)


def test_scenario_settings_at():
    from beantester import Scenario
    sc = Scenario([{"at": 0, "settings": {"loss": 0, "latency": 0}},
                   {"at": 5, "settings": {"latency": 200}},
                   {"at": 10, "settings": {"loss": 50}}])
    base = {"loss": 0, "latency": 0}
    check("scenario: t=3 initial state", sc.settings_at(3, base) == {"loss": 0, "latency": 0})
    check("scenario: t=7 latency 200", sc.settings_at(7, base)["latency"] == 200)
    r = sc.settings_at(12, base)
    check("scenario: t=12 cumulative (lat200 + loss50)", r["latency"] == 200 and r["loss"] == 50)


def test_scenario_block_step_applies_and_clears():
    """A scenario can turn a block on, then a later step clears it (cumulative
    settings): this is exactly what the shipped blocked-endpoint.json does."""
    from beantester import Scenario, DEFAULT_SETTINGS
    sc = Scenario([{"at": 0, "settings": {"latency": 10}},
                   {"at": 20, "settings": {"block_ip": "203.0.113.0/24"}},
                   {"at": 40, "settings": {"block_ip": ""}}])
    base = dict(DEFAULT_SETTINGS)
    check("scenario: no block before its step", sc.settings_at(10, base)["block_ip"] == "")
    check("scenario: block active mid-run",
          sc.settings_at(30, base)["block_ip"] == "203.0.113.0/24")
    check("scenario: block cleared by a later step", sc.settings_at(45, base)["block_ip"] == "")


def test_scenario_events():
    from beantester import Scenario
    sc = Scenario([{"at": 10, "action": "reset_now", "duration": 3}])
    check("scenario: action within (9,11]", len(sc.events_between(9, 11)) == 1)
    check("scenario: no action before", len(sc.events_between(0, 9)) == 0)
    check("scenario: no action after", len(sc.events_between(11, 20)) == 0)


def test_scenario_file_roundtrip():
    from beantester import load_scenario_file
    import tempfile, os as _os, json as _json
    data = {"loop": True, "steps": [{"at": 0, "settings": {"latency": 0}},
                                    {"at": 5, "settings": {"latency": 300}},
                                    {"at": 10, "action": "reset_now", "duration": 2}]}
    path = _os.path.join(tempfile.gettempdir(), "ns_scen.json")
    with open(path, "w") as f:
        _json.dump(data, f)
    sc = load_scenario_file(path)
    check("scenario file: loaded with loop", sc.loop and len(sc.steps) == 3 and sc.duration == 10)


def test_scenario_unsorted_and_empty():
    from beantester import Scenario
    sc = Scenario([{"at": 10, "settings": {"loss": 50}},
                   {"at": 0, "settings": {"loss": 0}},
                   {"at": 5, "settings": {"latency": 200}}])
    ats = [float(s["at"]) for s in sc.steps]
    check("scenario: steps sorted by time", ats == [0, 5, 10], f"({ats})")
    check("scenario: duration = last step", sc.duration == 10)
    empty = Scenario([])
    base = {"loss": 1}
    check("scenario: empty has duration 0 and returns a base copy",
          empty.duration == 0.0 and empty.settings_at(5, base) == base
          and empty.settings_at(5, base) is not base)


def test_scenario_events_boundaries():
    from beantester import Scenario
    sc = Scenario([{"at": 10, "action": "reset_now"}])
    check("scenario: t0 exclusive - (10,11] misses at=10, (9,10] catches it",
          len(sc.events_between(10, 11)) == 0 and len(sc.events_between(9, 10)) == 1)


def test_scenario_file_list_format():
    from beantester import load_scenario_file
    import tempfile, os as _os, json as _json
    path = _os.path.join(tempfile.gettempdir(), "ns_scen_list.json")
    with open(path, "w", encoding="utf-8") as f:
        _json.dump([{"at": 0, "settings": {"loss": 1}}, {"at": 3, "settings": {"loss": 9}}], f)
    sc = load_scenario_file(path)
    _os.remove(path)
    check("scenario file: list format supported (no loop)",
          len(sc.steps) == 2 and sc.loop is False and sc.duration == 3)


# --- filter expressions in the settings model ------------------------------ #


def test_config_roundtrip_keeps_expressions():
    from beantester import save_config_file, load_config_file, DEFAULT_SETTINGS
    import tempfile, os as _os
    s = dict(DEFAULT_SETTINGS)
    s.update(target="chrome,!chromedriver", dst_ip="10.0.0.1-10.0.0.50,!10.0.0.7",
             dst_port="80,443,8000-8100",
             block_ip="203.0.113.0/24", block_port="8080,9090")
    path = _os.path.join(tempfile.mkdtemp(), "cfg.json")
    save_config_file(path, s)
    loaded = load_config_file(path)
    ok = (loaded["target"] == s["target"] and loaded["dst_ip"] == s["dst_ip"]
          and loaded["dst_port"] == s["dst_port"]
          and loaded["block_ip"] == s["block_ip"] and loaded["block_port"] == s["block_port"])
    check("config: expressions survive save/load unchanged", ok, f"({loaded})")


def test_config_accepts_a_legacy_numeric_port():
    from beantester import load_config_file
    import tempfile, os as _os, json as _json
    path = _os.path.join(tempfile.mkdtemp(), "legacy.json")
    _json.dump({"dst_ip": "1.2.3.4", "dst_port": 443}, open(path, "w"))
    loaded = load_config_file(path)
    check("config: an old int port becomes its expression", loaded["dst_port"] == "443",
          f"({loaded['dst_port']})")
    _json.dump({"dst_port": 0}, open(path, "w"))
    check("config: the old 0 sentinel still means 'no port'",
          load_config_file(path)["dst_port"] == "")


def test_apply_settings_with_expressions():
    from beantester import BeanEngine, apply_settings
    sh = BeanEngine()
    apply_settings(sh, dict(dst_ip="192.168.1.0/24", dst_port="!53", target=""))
    c = sh.core
    check("apply: dst expressions reach the core", c.dst_active is True)
    check("apply: IP CIDR matches", c.dst_ip_matcher.matches("192.168.1.9"))
    check("apply: port exclusion matches", not c.dst_port_matcher.matches(53))


def test_apply_settings_bad_expression_disables_dest_targeting():
    from beantester import BeanEngine, apply_settings
    sh = BeanEngine()
    lines = []
    apply_settings(sh, dict(dst_ip="999.1.1.1"), lines.append)
    check("apply: a bad expression disables destination targeting",
          sh.core.dst_active is False)
    check("apply: the problem is logged, not silently ignored", lines, f"({lines})")


def test_apply_settings_bad_expression_disables_blocking():
    from beantester import BeanEngine, apply_settings
    sh = BeanEngine()
    lines = []
    apply_settings(sh, dict(block_ip="999.1.1.1"), lines.append)
    check("apply: a bad block expression disables blocking, not a crash",
          sh.core.block_active is False)
    check("apply: the block problem is logged", lines, f"({lines})")


def test_apply_settings_with_block_expressions():
    from beantester import BeanEngine, apply_settings
    sh = BeanEngine()
    apply_settings(sh, dict(block_ip="203.0.113.0/24", block_port="!53", target=""))
    c = sh.core
    check("apply: block expressions reach the core", c.block_active is True)
    check("apply: block IP CIDR matches", c.block_ip_matcher.matches("203.0.113.9"))
    check("apply: block port exclusion matches", not c.block_port_matcher.matches(53))


def test_validate_settings_rejects_bad_expressions():
    import pytest
    from beantester import validate_settings, DEFAULT_SETTINGS
    s = dict(DEFAULT_SETTINGS)
    check("validate: a clean settings dict passes", validate_settings(s))
    s["dst_port"] = "80,abc"
    with pytest.raises(ValueError):
        validate_settings(s)
    s = dict(DEFAULT_SETTINGS)
    s["block_ip"] = "999.1.1.1"
    with pytest.raises(ValueError):
        validate_settings(s)


def test_build_matchers_covers_every_filter_field():
    from beantester import MATCH_FIELDS, build_matchers, DEFAULT_SETTINGS
    keys = {k for k, _, _, _ in MATCH_FIELDS}
    check("every filter field is declared in MATCH_FIELDS",
          keys == {"target", "dst_ip", "dst_port", "block_ip", "block_port"}, f"({keys})")
    matchers = build_matchers(dict(DEFAULT_SETTINGS))
    check("build_matchers compiles one matcher per field", set(matchers) == keys)
    check("empty defaults compile to empty matchers",
          all(m.is_empty for m in matchers.values()))
