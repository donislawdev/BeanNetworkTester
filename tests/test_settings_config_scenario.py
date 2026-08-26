"""Settings model, config file round-trips and timeline scenarios.

Ported 1:1 from the original monolithic suite; every ``check(...)`` from the
270-assertion baseline is preserved as a pytest assertion.
"""
import json

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


def test_a_misspelled_setting_in_a_config_file_is_an_error_not_a_silent_default(tmp_path):
    """A typo used to be dropped in silence - the worst possible outcome.

    ``{"loss": 10, "latancy": 300}`` loaded clean, ``--dry-run`` answered
    "Configuration is valid", and the run then went out with latency 0. In a
    pipeline that is a green job that impaired less than it was asked to, and
    nothing anywhere says so. The scenario loader closed exactly this hole for
    step keys and settings names; the config file is the same rule one file over,
    and it is the one people hand-write (README recipe 2 exists to validate them).

    This REPLACES ``test_config_file_unknown_keys_ignored``, which pinned the old
    behaviour - and whose own check message already called it "rejected" while
    the code was ignoring it.
    """
    from beantester import DEFAULT_SETTINGS, load_config_file
    path = tmp_path / "typo.json"
    path.write_text(json.dumps({"loss": 10, "latancy": 300}), encoding="utf-8")
    raised = ""
    try:
        load_config_file(str(path))
    except ValueError as e:
        raised = str(e)
    check("config: a misspelled setting is an error", raised, "(loaded clean)")
    check("config: the error names the offending key", "latancy" in raised,
          f"({raised!r})")
    check("config: and points at the key that was meant", "latency" in raised,
          f"({raised!r})")

    many = tmp_path / "many.json"
    many.write_text(json.dumps({"loss": 7, "zzz": 1, "evil": "x"}), encoding="utf-8")
    raised = ""
    try:
        load_config_file(str(many))
    except ValueError as e:
        raised = str(e)
    check("config: every unknown key is listed, not just the first",
          "zzz" in raised and "evil" in raised, f"({raised!r})")

    good = tmp_path / "good.json"
    good.write_text(json.dumps({"loss": 7}), encoding="utf-8")
    loaded = load_config_file(str(good))
    check("config: a valid partial file still fills the rest with defaults",
          set(loaded) == set(DEFAULT_SETTINGS) and loaded["loss"] == 7)


def test_every_file_this_tool_writes_still_loads(tmp_path):
    """The strictness above must never reject the tool's own output.

    ``save_config_file`` writes exactly the ``DEFAULT_SETTINGS`` key set, so this
    holds by construction today - and this test is what keeps it holding when a
    setting is renamed or dropped, which is the one way the new rule could bite
    a user who did nothing wrong.
    """
    from beantester import (DEFAULT_SETTINGS, load_config_file,
                            save_config_file)
    path = str(tmp_path / "written.json")
    save_config_file(path, dict(DEFAULT_SETTINGS))
    loaded = load_config_file(path)
    check("config: a file this tool wrote round-trips",
          set(loaded) == set(DEFAULT_SETTINGS), f"({sorted(loaded)})")


def test_load_missing_files_raise():
    from beantester import load_config_file, load_scenario_file
    for fn, name in ((load_config_file, "config"), (load_scenario_file, "scenario")):
        raised = False
        try:
            fn("/nie/istnieje/plik_%s.json" % name)
        except (FileNotFoundError, OSError):
            raised = True
        check(f"load_{name}_file: missing file raises an exception", raised)


def test_a_scenario_step_rejects_a_bad_duration():
    """``duration`` reached the engine straight off the unvalidated dict.

    ``scenario_runner`` does ``float(step.get("duration", 3.0))`` on the SCENARIO
    THREAD, so a string killed the timeline mid-run while the session carried on
    - the file looked ignored rather than broken. A negative value was a reset
    that reset nothing.
    """
    import pytest
    from beantester.scenario import parse_scenario
    for bad in ("soon", -5, None, [3]):
        with pytest.raises(ValueError):
            parse_scenario([{"at": 1, "action": "reset_tcp", "duration": bad}])
    ok = parse_scenario([{"at": 1, "action": "reset_tcp", "duration": 8}])
    check("scenario: a valid duration still passes", ok.steps[0]["duration"] == 8)


def test_a_scenario_step_rejects_a_duration_with_nothing_to_apply_to():
    import pytest
    from beantester.scenario import parse_scenario
    with pytest.raises(ValueError):
        parse_scenario([{"at": 1, "settings": {"loss": 5}, "duration": 8}])


def test_a_misspelled_scenario_key_is_an_error_not_a_silent_default():
    """The failure this whole validation exists for: a typo did NOTHING visible.

    ``"duraton"`` left the reset on its 3 s default and ``"lop"`` turned looping
    off, both without a word. Unknown SETTINGS names have been a hard error since
    this module was written; these are the same rule one level up.
    """
    import pytest
    from beantester.scenario import parse_scenario
    with pytest.raises(ValueError) as bad_step:
        parse_scenario([{"at": 1, "action": "reset_tcp", "duraton": 8}])
    check("scenario: the misspelled key is named in the message",
          "duraton" in str(bad_step.value), f"({bad_step.value})")

    with pytest.raises(ValueError) as bad_file:
        parse_scenario({"steps": [{"at": 1, "settings": {"loss": 5}}], "lop": True})
    check("scenario: the misspelled file key is named too",
          "lop" in str(bad_file.value), f"({bad_file.value})")


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
    sc = Scenario([{"at": 10, "action": "reset_tcp", "duration": 3}])
    check("scenario: action within (9,11]", len(sc.events_between(9, 11)) == 1)
    check("scenario: no action before", len(sc.events_between(0, 9)) == 0)
    check("scenario: no action after", len(sc.events_between(11, 20)) == 0)


def test_scenario_file_roundtrip():
    from beantester import load_scenario_file
    import tempfile, os as _os, json as _json
    data = {"loop": True, "steps": [{"at": 0, "settings": {"latency": 0}},
                                    {"at": 5, "settings": {"latency": 300}},
                                    {"at": 10, "action": "reset_tcp", "duration": 2}]}
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
    sc = Scenario([{"at": 10, "action": "reset_tcp"}])
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


def test_a_misspelled_scenario_setting_gets_the_same_help_as_a_config_one():
    """One class of mistake, one quality of answer.

    ``load_config_file`` has suggested a correction for a near-miss setting name
    since it learned to (``difflib``, settings.py); the scenario loader, reading
    the same names out of the same kind of JSON file, said only "unknown
    setting" - and which loader helped you depended on which one was written
    first. The unknown ACTION message had the matching gap: it named what you
    typed without naming what exists, and there is exactly one action to name.

    Both halves are asserted, because a suggestion that fires for EVERY typo is
    its own bug: a name close to nothing must still fail plainly.
    """
    import pytest
    from beantester.scenario import parse_scenario
    with pytest.raises(ValueError) as near:
        parse_scenario([{"at": 0, "settings": {"losss": 10}}])
    check("scenario: a near-miss setting is offered the correction",
          "loss" in str(near.value) and "?" in str(near.value), f"({near.value})")

    with pytest.raises(ValueError) as far:
        parse_scenario([{"at": 0, "settings": {"zzzzzzzz": 10}}])
    check("scenario: a name close to nothing still fails plainly",
          "zzzzzzzz" in str(far.value) and "?" not in str(far.value),
          f"({far.value})")

    with pytest.raises(ValueError) as action:
        parse_scenario([{"at": 0, "action": "reset_tpc"}])
    check("scenario: an unknown action names the ones that exist",
          "reset_tcp" in str(action.value), f"({action.value})")


def test_a_scenario_value_is_checked_when_the_file_is_opened():
    """The names were checked; the VALUES were not, and that is the half that hurt.

    A step's ``settings`` went from the file into ``apply_settings`` untouched, on
    the runner's background thread. Measured 2026-08-26: an out-of-range number
    was applied to the engine as it stood, a nested object was applied as an
    object, and a string where a number belongs raised on that thread - killing
    the timeline while the session kept impairing traffic.

    A scenario file and a typed-in value are two doors into the same engine. This
    asserts they now answer the same way, and that the answer arrives when the
    file is OPENED - naming the step - rather than in the fifth minute of a run.
    """
    import pytest
    from beantester.scenario import parse_scenario

    hostile = (
        ("a string where a number belongs", {"loss": "abc"}),
        ("a number outside the field's range", {"loss": 1e9}),
        ("a nested object", {"dst_port": {"nope": 1}}),
        ("a value the form would refuse", {"latency": -5}),
    )
    for label, patch in hostile:
        with pytest.raises(ValueError) as bad:
            parse_scenario([{"at": 0, "settings": patch}])
        check(f"scenario: {label} is refused at load", "1" in str(bad.value),
              f"(message does not name the step: {bad.value})")

    # ...and the values that are FINE keep working, in the shape the engine wants.
    sc = parse_scenario([{"at": 0, "settings": {"loss": "10"}}])
    check("scenario: a legitimate value survives, converted",
          sc.steps[0]["settings"] == {"loss": 10.0}, f"({sc.steps[0]!r})")
    check("scenario: and the step stays a PATCH, not a full settings dict",
          list(sc.steps[0]["settings"]) == ["loss"], f"({sc.steps[0]['settings']!r})")

    # The empty patch is the same rule at its limit, and the one that would do the
    # most damage if it were got wrong: `{}` becoming a full dict of defaults means
    # a step that says nothing would reset every setting the run had built up.
    empty = parse_scenario([{"at": 0, "settings": {}}, {"at": 1, "action": "reset_tcp"}])
    check("scenario: a step with no settings patches nothing",
          empty.steps[0]["settings"] == {}, f"({empty.steps[0]['settings']!r})")


def test_a_scenario_step_cannot_be_scheduled_at_infinity():
    """``at`` was the last number in the program that skipped ``parse_number``.

    ``float("Infinity")`` passed the ``>= 0`` check, so the step validated cleanly
    and then never fired: ``t0 < at <= t1`` is false for every t. A scenario that
    looked right and quietly did not do what it said. ``duration`` had the same
    hole - an ``Infinity`` there is a reset that never ends.
    """
    import pytest
    from beantester.scenario import parse_scenario

    for label, step in (("at=Infinity", {"at": float("inf"), "settings": {"loss": 1}}),
                        ("at=NaN", {"at": float("nan"), "settings": {"loss": 1}}),
                        ("duration=Infinity",
                         {"at": 0, "action": "reset_tcp", "duration": float("inf")})):
        with pytest.raises(ValueError):
            parse_scenario([step])
        check(f"scenario: {label} is refused", True)

    sc = parse_scenario([{"at": "2,5", "settings": {"loss": 1}}])
    check("scenario: a plain number still works, comma included",
          sc.steps[0]["at"] == 2.5, f"({sc.steps[0]['at']!r})")


def test_a_config_value_says_what_the_setting_takes(tmp_path):
    """"Invalid value for 'loss'" said the value was wrong and stopped there.

    The bounds are in the registry and the form has always used them ("must be
    between 0 and 100"). The config loader described the same rejected value
    with the word "invalid" and nothing else, so the interface that could not
    show you the field was also the one that would not tell you the range.
    """
    import json
    import pytest
    from beantester.settings import load_config_file
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"loss": "abc"}), encoding="utf-8")
    with pytest.raises(ValueError) as e:
        load_config_file(str(path))
    message = str(e.value)
    check("config: the message names the setting", "loss" in message, f"({message})")
    check("config: it names what the setting takes",
          "0" in message and "100" in message, f"({message})")
    check("config: it quotes back what was actually given",
          "abc" in message, f"({message})")


def test_both_lan_switches_at_once_are_allowed_and_said_out_loud():
    """LAN mode plus "Internet only" is the union of two impairments, so it is a
    legal request - and it cuts everything except loopback, which looks far more
    like a broken tool than like a tool doing as it was told.

    Refusing it was rejected: a run somebody meant would die on validation. Saying
    it once per apply is the same answer the shared-port warning gives, and the
    same one the engine gives for a destination frozen by a narrowed filter.
    """
    from beantester import DEFAULT_SETTINGS, apply_settings
    from beantester.i18n import T

    warning = T("log.lan_and_internet_only")

    def lines_for(**overrides):
        said = []
        apply_settings(BeanEngine(), dict(DEFAULT_SETTINGS, **overrides), said.append)
        return said

    check("both on: the run says so",
          warning in lines_for(lan_mode=True, internet_only=True))
    check("LAN mode alone: nothing to warn about",
          warning not in lines_for(lan_mode=True))
    check("Internet only alone: nothing to warn about",
          warning not in lines_for(internet_only=True))
    check("neither: nothing to warn about", warning not in lines_for())


def test_internet_only_reaches_the_engine_through_apply_settings():
    """The setting has to arrive at the core, not merely be stored."""
    from beantester import DEFAULT_SETTINGS, apply_settings
    engine = BeanEngine()
    apply_settings(engine, dict(DEFAULT_SETTINGS, internet_only=True),
                   lambda *_: None)
    check("internet only: armed on the core", engine.core.internet_only is True)
    apply_settings(engine, dict(DEFAULT_SETTINGS), lambda *_: None)
    check("internet only: disarmed again", engine.core.internet_only is False)
