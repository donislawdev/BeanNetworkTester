"""Regression tests for the stability / validation fixes from the audit.

The flow-table guards this file used to hold now live beside the rest of the
flow-table tests in ``test_core.py`` - the subject owns them, not the audit that
happened to find them.

Covered:
* destination IP matching is format-insensitive (IPv6 shorthand),
* ``parse_schedule`` reports every malformed step consistently,
* ``settings_summary`` never claims an unparsable schedule is active,
* the CLI rejects a malformed schedule / destination IP up front,
* ``set_schedule`` restarts the cycle position.
"""
import random
import time

from fakes import check

from beantester import (BeanCore, canonical_ip, config_from_args,
                        build_arg_parser, load_config_file, parse_schedule,
                        settings_summary)
from beantester import i18n


def test_dest_ip_matches_regardless_of_formatting():
    core = BeanCore()
    core.set_dest(True, "2001:0db8:0000:0000:0000:0000:0000:0001", None)
    rng = random.Random(0)
    # remote given in shorthand form -> same address -> flow is affected
    matched = core.decide(100, True, 5000, 0.0, rng,
                          remote_ip="2001:db8::1", remote_port=80)
    other = core.decide(100, True, 5000, 0.0, rng,
                        remote_ip="8.8.8.8", remote_port=80)
    check("matching remote enters the pipeline (reason not a pass-through)",
          matched.reason is None)
    check("non-matching remote is passed through untouched",
          other.reason is None and other.releases == [0.0], f"({other})")


def test_canonical_ip_helper():
    check("valid IPv4 canonicalized", canonical_ip("1.2.3.4") == "1.2.3.4")
    check("IPv6 shorthand canonicalized",
          canonical_ip("2001:0db8::0001") == "2001:db8::1")
    check("garbage -> None", canonical_ip("nope") is None)
    check("empty -> None", canonical_ip("") is None)


def test_parse_schedule_reports_all_malformed_steps():
    for bad in ("x:1:2", "1:100", "1:2:3:4", "1:a:2"):
        raised = False
        try:
            parse_schedule(bad)
        except ValueError as e:
            raised = True
            check(f"error message names the bad step {bad!r}", bad in str(e), f"({e})")
        check(f"malformed schedule {bad!r} raises", raised)
    check("valid multi-step schedule parses",
          parse_schedule("1:100:0, 2:400:128") == [(1.0, 100.0, 0.0), (2.0, 400.0, 128.0)])


def test_summary_hides_unparsable_schedule():
    word = i18n.translate("summary.schedule", "en")
    good = settings_summary({"rate_schedule": "1:100:0"}, "en")
    bad = settings_summary({"rate_schedule": "totally-bad"}, "en")
    check("valid schedule shown in summary", word in good, f"({good})")
    check("invalid schedule not shown in summary", word not in bad, f"({bad})")


def test_cli_rejects_bad_schedule_and_ip():
    p = build_arg_parser()
    for argv in (["--rate-schedule", "1:bad"], ["--dst-ip", "999.1.1.1"]):
        raised = False
        try:
            config_from_args(p.parse_args(argv))
        except SystemExit:
            raised = True
        check(f"CLI rejects {argv}", raised)
    # a valid combination must not raise
    config_from_args(p.parse_args(
        ["--rate-schedule", "1:100:0,2:400:0", "--dst-ip", "1.2.3.4"]))


def test_set_schedule_resets_cycle_start():
    core = BeanCore()
    before = time.monotonic()
    core.set_schedule([(1.0, 100, 0), (1.0, 400, 0)])
    check("set_schedule restarts the cycle position",
          core._sched_start >= before, f"({core._sched_start} < {before})")


def test_config_file_values_are_type_checked(tmp_path):
    """Regression: a config file with a string where a number is expected used
    to crash the CLI with a raw TypeError traceback deep in apply_settings."""
    import json
    good = tmp_path / "good.json"
    bad = tmp_path / "bad.json"
    good.write_text(json.dumps({"loss": "12.5", "lan_mode": 1}), encoding="utf-8")
    bad.write_text(json.dumps({"loss": "abc"}), encoding="utf-8")

    s = load_config_file(str(good))
    check("numeric strings are coerced to numbers", s["loss"] == 12.5)
    check("truthy values are coerced to bools", s["lan_mode"] is True)

    raised = False
    try:
        load_config_file(str(bad))
    except ValueError as e:
        raised = True
        check("error message names the offending key", "loss" in str(e), f"({e})")
    check("non-numeric value raises a ValueError", raised)

    p = build_arg_parser()
    for argv in (["--config", str(bad)],
                 ["--config", str(tmp_path / "missing.json")]):
        raised = False
        try:
            config_from_args(p.parse_args(argv))
        except SystemExit:
            raised = True
        check(f"CLI exits cleanly for {argv}", raised)


def test_flap_phase_is_session_relative():
    """Regression: the outage window used to follow the absolute monotonic
    clock, so 'seeded reproduction' runs diverged on flapping. The phase must
    be relative to the session start."""
    core = BeanCore()
    core.set_flap(True, 10.0, 30)           # period 10 s, first 30% down
    rng = random.Random(1)
    core.reset_buckets(1003.0)              # session starts at an odd time
    d1 = core.decide(100, True, 1000, 1003.5, rng,
                     remote_ip="8.8.8.8", remote_port=80)
    check("0.5 s into the session is inside the down window", d1.drop is True)
    d2 = core.decide(100, True, 1000, 1007.0, rng,
                     remote_ip="8.8.8.8", remote_port=80)
    check("4 s into the session is outside the down window", d2.drop is False)

    core2 = BeanCore()
    core2.set_flap(True, 10.0, 30)
    core2.reset_buckets(500.25)             # different absolute start time
    d3 = core2.decide(100, True, 1000, 500.75, rng,
                      remote_ip="8.8.8.8", remote_port=80)
    check("same session-relative time gives the same flap state", d3.drop is True)
