"""Regression tests for the stability / validation fixes from the audit.

Covered:
* flow bookkeeping tables stay bounded without RST/NAT (memory-leak fix),
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


def test_flow_tables_bounded_without_rst():
    """With RST and NAT disabled the flow tables must not grow without bound."""
    core = BeanCore()                       # rst_prob = 0, nat_timeout = 0
    rng = random.Random(1)
    for i in range(12000):                  # 12000 distinct flows
        core.decide(100, True, 1000 + i, float(i), rng,
                    remote_ip="8.8.8.8", remote_port=80, is_tcp=True)
    # the prune is throttled (runs at most every few seconds), so the table
    # may briefly exceed the threshold by one throttle window of new flows
    check("flow_last stays bounded", len(core._flow_last) <= 4100,
          f"(size={len(core._flow_last)})")


def test_flow_table_stays_bounded_under_heavy_churn():
    """Regression, twice over.

    First: the O(n) table rebuild used to run for EVERY packet, then (after the
    first fix) once every 5 s - but it was still a REBUILD, and at 3.2 million
    entries that is a 1001 ms freeze of the capture thread. It is now a generation
    swap: O(1).

    Second: the table was bounded by AGE only, so under churn it had no ceiling at
    all. It now has one, and a session that opens flows as fast as it can must not
    push past it.
    """
    from beantester.core import MAX_FLOWS

    core = BeanCore()
    core.reset_buckets(0.0)
    core.nat_timeout_s = 30.0               # the only thing that makes it track
    rng = random.Random(1)

    # 500 000 brand-new flows inside ONE simulated second. This is the case that
    # matters: the size check used to live in _prune(), which is throttled to once
    # a second, so a whole second of churn could land between two checks. Measured
    # at 150 000 flows/s the table peaked at 299 999 against a 200 000 ceiling -
    # and the old version of this test never noticed, because it only ever pushed
    # 60 000 flows through, which cannot reach the ceiling however it is enforced.
    now = 1000.0
    peak = 0
    for i in range(500_000):
        now += 0.000002                     # ~2 us apart: 500k flows in ~1 second
        core.decide(100, True, 1024 + (i % 60000), now, rng,
                    remote_ip=f"10.{i // 65536 % 256}.{i // 256 % 256}.{i % 256}",
                    remote_port=443)
        if i % 5000 == 0:
            peak = max(peak, len(core._flow_last))
    peak = max(peak, len(core._flow_last))

    check("the flow table has a ceiling and respects it EVEN inside one second",
          peak <= MAX_FLOWS, f"(peak={peak:,} vs ceiling {MAX_FLOWS:,})")
    check("and it is a _FlowTable, not a bare dict that rebuilds itself",
          not isinstance(core._flow_last, dict))


def test_rotation_is_o1_not_a_rebuild():
    """The whole point: no O(n) work may happen inside decide()'s lock.

    "Swap the dict instead of rebuilding it" was only *most* of the answer. Moving
    the reference is O(1), but DROPPING the last reference to a 200 000-entry dict
    is O(n) in CPython's teardown: ~7 ms here, up to 22 ms measured in the engine.
    That is still a stall in the packet path, in a tool whose entire job is to
    inject a precise amount of latency. So a retired generation is handed to the
    watchdog (``drain_retired``) and freed there.
    """
    import time

    from beantester.core import _FlowTable

    table = _FlowTable(limit=400_000, rotate_s=1.0)
    for i in range(200_000):
        table.set((i, "1.1.1.1", 80), 1.0)

    # the ceiling rotated it on the way in, so a full generation is already retired
    t0 = time.perf_counter()
    table.maybe_rotate(10.0)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    check("retiring a generation is O(1) - nothing is freed on this thread",
          elapsed_ms < 1.0,
          f"({elapsed_ms:.2f} ms - a rebuild of this table used to cost ~30 ms, "
          f"and freeing it inline cost ~7 ms)")
    check("the new generation starts empty", len(table._new) == 0)

    # and the retired dicts are waiting for whoever is not the capture thread
    retired = table.drain_retired()
    check("the retired generations are handed over, not dropped", retired,
          f"({len(retired)} generation(s))")
    check("draining twice gives nothing the second time", table.drain_retired() == [])


def test_the_size_ceiling_holds_inside_a_single_second():
    """The ceiling used to be checked only from the throttled prune (once a second),
    so a whole second of churn could land between two checks."""
    from beantester.core import _FlowTable

    table = _FlowTable(limit=1000, rotate_s=30.0)
    peak = 0
    for i in range(50_000):                 # 50x the ceiling, no time passing at all
        table.set((i, "1.1.1.1", 80), 1.0)
        peak = max(peak, len(table))
    check("the table never passes its ceiling, whatever the clock does",
          peak <= 1000, f"(peak={peak})")


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
