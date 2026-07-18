"""Summaries, CLI command builder, repro reports and table view helpers.

Ported 1:1 from the original monolithic suite; every ``check(...)`` from the
270-assertion baseline is preserved as a pytest assertion.
"""
import os
import time

from beantester import BeanEngine
from beantester.synthetic import SyntheticDivert
from fakes import FakeDivert, FakePacket, check



def test_settings_summary():
    from beantester import settings_summary
    empty = settings_summary({}, "pl")
    check("summary PL: empty = 'brak zakłóceń'", "brak zakłóceń" in empty, f"({empty})")
    s = settings_summary({"latency": 100, "loss": 5, "down": 500, "target": "chrome.exe"}, "pl")
    ok = ("+100 ms pingu" in s and "5% strat" in s and "500 KB/s" in s and "chrome.exe" in s)
    check("summary PL: describes active options in Polish", ok, f"({s})")


# --- tests: bug reproduction (effective seed, events, report) -------------- #


def test_settings_summary_en():
    from beantester import settings_summary
    s = settings_summary({"latency": 100, "loss": 5, "down": 500, "target": "chrome.exe"}, "en")
    ok = ("+100 ms ping" in s and "5% loss" in s and "download <= 500 KB/s" in s
          and "process only 'chrome.exe'" in s and s.startswith("Active:"))
    check("summary EN: correct English description", ok, f"({s})")
    empty = settings_summary({}, "en")
    check("summary EN: no impairments", "no impairments" in empty, f"({empty})")


def test_settings_summary_lan():
    from beantester import settings_summary
    pl = settings_summary({"lan_mode": True}, "pl")
    en = settings_summary({"lan_mode": True}, "en")
    check("summary PL: LAN mode", "tryb LAN" in pl, f"({pl})")
    check("summary EN: LAN mode", "LAN mode" in en, f"({en})")


def test_settings_to_cli_roundtrip():
    from beantester import (settings_to_cli, build_arg_parser, config_from_args,
                           DEFAULT_SETTINGS)
    s = dict(DEFAULT_SETTINGS)
    s.update(loss=7, latency=250, down=384, rst_prob=15, nat_timeout=30,
             rate_schedule="1:100:0,2:400:0", dst_ip="10.0.0.5", dst_port=443,
             block_ip="1.2.3.4", block_port="8080,9090",
             filter="tcp", seed=42)
    argv = settings_to_cli(s, seed=42)
    parsed = config_from_args(build_arg_parser().parse_args(argv))["settings"]
    ok = (parsed["loss"] == 7 and parsed["latency"] == 250 and parsed["down"] == 384
          and parsed["rst_prob"] == 15 and parsed["nat_timeout"] == 30
          and parsed["rate_schedule"] == "1:100:0,2:400:0"
          and parsed["dst_ip"] == "10.0.0.5" and parsed["dst_port"] == "443"
          and parsed["block_ip"] == "1.2.3.4" and parsed["block_port"] == "8080,9090"
          and parsed["filter"] == "tcp" and parsed["seed"] == 42)
    check("CLI command: reproduces the same settings", ok, f"({parsed})")


def test_settings_to_cli_minimal():
    from beantester import settings_to_cli, DEFAULT_SETTINGS
    argv = settings_to_cli(dict(DEFAULT_SETTINGS), seed=None)
    check("CLI command: no impairments = no redundant flags", argv == [], f"({argv})")


def test_settings_to_cli_prefix_and_name():
    """The program name follows the BUILD: sources vs the shipped executable.

    A frozen user has no ``python bean_network_tester.py`` to paste, so both the
    repro command and argparse's usage line come from ``appinfo`` (which asks
    ``paths.is_frozen()``), not from a hard-coded string.
    """
    from beantester import build_arg_parser, settings_to_cli_string
    from beantester.appinfo import EXE_NAME, LAUNCHER
    cmd = settings_to_cli_string({"loss": 5}, seed=123)
    check("cli string: run-from-sources prefix",
          cmd.startswith(f"python {LAUNCHER}"), f"({cmd[:40]})")
    check("cli: prog names this build",
          build_arg_parser().prog in (LAUNCHER, EXE_NAME),
          f"({build_arg_parser().prog})")


def test_build_repro_report():
    from beantester import DEFAULT_SETTINGS, build_repro_report
    sh = BeanEngine(); sh.set_seed(777)
    sh.start("test", divert=SyntheticDivert(gen_kbps=3000, seed=1))
    sh.set_params(20, 0, 0, 0, 0, 0, 0)
    sh.log_event("BUG", "tu")
    time.sleep(0.3)
    settings = dict(DEFAULT_SETTINGS, loss=20, seed=777)
    rep = build_repro_report(sh, settings)
    sh.stop()
    ok = (rep["seed"] == 777 and rep["cli_command"].startswith("python bean_network_tester.py")
          and "--seed 777" in rep["cli_command"] and "--loss 20" in rep["cli_command"]
          and "effective_loss_pct" in rep["metrics"]
          and any(e["type"] == "BUG" for e in rep["events"])
          and any(e["type"] == "START" for e in rep["events"]))
    check("repro report: complete data + CLI command", ok,
          f"(seed={rep['seed']}, cli={rep['cli_command']})")


def test_bytes_to_mb():
    from beantester import bytes_to_mb
    check("MB: 1 MB = 1048576 B", bytes_to_mb(1048576) == 1.0)
    check("MB: 1.5 MB", bytes_to_mb(1572864) == 1.5)
    check("MB: 0 for garbage input", bytes_to_mb("x") == 0.0)


def test_repro_report_has_data_usage():
    from beantester import DEFAULT_SETTINGS, build_repro_report
    sh = BeanEngine(); sh.set_seed(9)
    sh.start("test", divert=SyntheticDivert(gen_kbps=4000, seed=1))
    time.sleep(0.4)
    rep = build_repro_report(sh, dict(DEFAULT_SETTINGS, seed=9))
    sh.stop()
    m = rep["metrics"]
    ok = ("downloaded_mb" in m and "uploaded_mb" in m and "total_mb" in m and "offered_mb" in m
          and m["total_mb"] >= 0)
    check("report: contains data usage (MB)", ok, f"({ {k: m[k] for k in ('downloaded_mb','uploaded_mb','total_mb')} })")


def test_save_repro_report_roundtrip():
    import json
    import tempfile

    from beantester import save_repro_report
    sh = BeanEngine()
    sh.start("test", divert=FakeDivert([FakePacket(size=100, is_outbound=True, port=5000)]))
    time.sleep(0.05)
    sh.stop()
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    try:
        save_repro_report(path, sh, {"loss": 5, "seed": 42})
        with open(path, encoding="utf-8") as f:
            rep = json.load(f)
    finally:
        os.remove(path)
    check("repro file: English keys",
          {"tool", "session", "settings", "counters", "metrics", "events", "connections", "cli_command"} <= set(rep),
          f"({sorted(rep)})")
    check("repro file: tool = BeanNetworkTester", rep["tool"] == "BeanNetworkTester")
    check("repro file: cli_command uses the new name",
          rep["cli_command"].startswith("python bean_network_tester.py"))
    check("repro file: metrics in English",
          {"packets", "downloaded_mb", "uploaded_mb", "total_mb"} <= set(rep["metrics"]))


def test_filter_sort_connections():
    from beantester import filter_sort_connections
    conns = [dict(dir="out", remote_ip="1.1.1.1", remote_port=443, local_port=5000, packets=10, bytes=5000),
             dict(dir="in", remote_ip="8.8.8.8", remote_port=53, local_port=6000, packets=99, bytes=100),
             dict(dir="out", remote_ip="10.0.0.5", remote_port=443, local_port=7000, packets=2, bytes=99999)]
    by_bytes = [c["bytes"] for c in filter_sort_connections(conns, sort_col="bytes", reverse=True)]
    check("connections: sorted by bytes descending", by_bytes == [99999, 5000, 100], f"({by_bytes})")
    by_pk = [c["packets"] for c in filter_sort_connections(conns, sort_col="packets", reverse=False)]
    check("connections: sorted by packets ascending", by_pk == [2, 10, 99], f"({by_pk})")
    ip = [c["remote_ip"] for c in filter_sort_connections(conns, query="443")]
    check("connections: filter by port 443", set(ip) == {"1.1.1.1", "10.0.0.5"}, f"({ip})")
    ip2 = [c["remote_ip"] for c in filter_sort_connections(conns, query="8.8")]
    check("connections: filter by IP", ip2 == ["8.8.8.8"], f"({ip2})")
    allc = filter_sort_connections(conns, query="")
    check("connections: empty filter = all", len(allc) == 3)


def test_sort_events():
    from beantester import sort_events
    evs = [(0.0, "10:00:00", "START", "a"),
           (5.0, "10:00:05", "ZMIANA", "b"),
           (2.0, "10:00:02", "BLAD", "c")]
    check("events: sorted by time ascending", [e[0] for e in sort_events(evs, "t", False)] == [0.0, 2.0, 5.0])
    check("events: sorted by time descending", [e[0] for e in sort_events(evs, "t", True)] == [5.0, 2.0, 0.0])
    check("events: sorted by type alphabetically",
          [e[2] for e in sort_events(evs, "type", False)] == ["BLAD", "START", "ZMIANA"])


def test_nice_ceiling():
    from beantester import nice_ceiling
    check("axis scale: 47 -> 50", nice_ceiling(47) == 50)
    check("axis scale: 380 -> 500", nice_ceiling(380) == 500)
    check("axis scale: 1500 -> 2000", nice_ceiling(1500) == 2000)
    check("axis scale: 0.4 -> 0.5", nice_ceiling(0.4) == 0.5)
    check("axis scale: 0 -> 1 (no division by zero)", nice_ceiling(0) == 1.0)


def test_sort_events_malformed_rows():
    from beantester import sort_events
    evs = [(0.0, "10:00:00", "START", "a"),
           ("zle", "10:00:01"),                       # too short + non-numeric t
           (2.0, "10:00:02", "BLAD", "c")]
    try:
        out = sort_events(evs, "t", False)
        ok = len(out) == 3
        out2 = sort_events(evs, "opis", False)        # missing column in short row
        ok = ok and len(out2) == 3
    except Exception:
        ok = False
    check("events: malformed rows do not break sorting", ok)


def test_filter_sort_connections_missing_keys():
    from beantester import filter_sort_connections
    conns = [dict(remote_ip="1.1.1.1", bytes=100),
             dict(remote_ip="2.2.2.2"),               # missing 'bytes'
             dict(bytes="zle")]                       # non-numeric value
    try:
        out = filter_sort_connections(conns, sort_col="bytes", reverse=True)
        ok = len(out) == 3 and out[0]["bytes"] == 100
        out2 = filter_sort_connections(conns, query="1.1", sort_col="proc")
        ok = ok and len(out2) == 1
    except Exception:
        ok = False
    check("connections: missing/garbage data does not break the filter", ok)


def test_repro_report_events_in_english():
    from beantester import build_repro_report, DEFAULT_SETTINGS
    sh = BeanEngine()
    sh.start("test", divert=FakeDivert([FakePacket(size=100, port=5000)]))
    sh.log_event("RESET", "events.manual_reset")
    time.sleep(0.05)
    rep_ = build_repro_report(sh, dict(DEFAULT_SETTINGS))
    sh.stop()
    descs = [e["description"] for e in rep_["events"]]
    check("repro report: event descriptions rendered in English",
          "manual TCP connection reset (RST)" in descs, f"({descs})")


def test_summary_shows_expression_dest():
    from beantester import settings_summary
    s = dict(dst_ip="10.0.0.1-10.0.0.50,!10.0.0.7", dst_port="80,443")
    out = settings_summary(s, "en")
    check("summary keeps the IP expression readable",
          "10.0.0.1-10.0.0.50,!10.0.0.7" in out, f"({out})")
    check("summary keeps the port expression readable", "80,443" in out, f"({out})")
    only_port = settings_summary(dict(dst_port="!53"), "en")
    check("summary handles a port-only destination",
          "!53" in only_port and "any IP" in only_port, f"({only_port})")


def test_summary_shows_blocking():
    from beantester import settings_summary
    out = settings_summary(dict(block_ip="203.0.113.0/24", block_port="443"), "en")
    check("summary names the block IP expression", "203.0.113.0/24" in out, f"({out})")
    check("summary names the block port", "443" in out, f"({out})")
    only_port = settings_summary(dict(block_port="8080"), "en")
    check("summary handles a port-only block", "8080" in only_port and "any IP" in only_port,
          f"({only_port})")


def test_repro_command_includes_expression_ports():
    from beantester import settings_to_cli, DEFAULT_SETTINGS
    s = dict(DEFAULT_SETTINGS)
    s.update(dst_port="80,443,!8080")
    argv = settings_to_cli(s)
    check("a non-numeric port expression still reaches the CLI command",
          "--dst-port" in argv and "80,443,!8080" in argv, f"({argv})")


def test_human_duration_survives_a_long_weekend():
    """The session clock used to be "{minutes}m {seconds}s", which reads 4320m 0s
    after three days - and three days is exactly what a soak run looks like."""
    from beantester.utils import human_duration

    check("seconds", human_duration(45) == "0m 45s", f"({human_duration(45)})")
    check("minutes", human_duration(605) == "10m 5s", f"({human_duration(605)})")
    check("hours", human_duration(3725) == "1h 2m 5s", f"({human_duration(3725)})")
    check("days", human_duration(3 * 86400 + 3600) == "3d 1h 0m",
          f"({human_duration(3 * 86400 + 3600)})")
    check("a week is still readable", "7d" in human_duration(7 * 86400))
    check("nonsense does not crash", human_duration(None) == "0m 0s")
    check("negative does not crash", human_duration(-5) == "0m 0s")


def test_settings_to_cli_covers_every_numeric_field():
    # Guards against the "hand-written repro list forgot a field" bug: every NUMBER
    # field that has a CLI flag and reaches the engine (not ui_only) must appear in
    # the reproduce command when its value differs from the default. --buffer was
    # missing exactly this way.
    from beantester import settings_to_cli, DEFAULT_SETTINGS
    from beantester.fields import FIELD_DEFS, NUMBER
    for f in FIELD_DEFS:
        if f.kind != NUMBER or not f.cli or f.ui_only:
            continue
        lo, hi = f.bounds
        default = float(DEFAULT_SETTINGS[f.key])
        val = default + 1 if default + 1 <= hi else default - 1
        assert lo <= val <= hi and val != default, (f.key, val)
        argv = settings_to_cli({**DEFAULT_SETTINGS, f.key: val})
        check(f"repro command includes --{f.cli}", f"--{f.cli}" in argv,
              f"(field {f.key!r} value {val} produced {argv})")
