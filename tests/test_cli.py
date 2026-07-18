"""CLI: parsing, precedence (defaults < file < preset < flags), English output.

Ported 1:1 from the original monolithic suite; every ``check(...)`` from the
270-assertion baseline is preserved as a pytest assertion.
"""
from beantester import BeanEngine
from fakes import check



def test_cli_advanced_flags():
    from beantester import build_arg_parser, config_from_args, apply_config
    args = build_arg_parser().parse_args(
        ["--dst-ip", "10.0.0.5", "--dst-port", "8080", "--syn-drop", "40", "--max-size", "1200"])
    cfg = config_from_args(args)
    sh = BeanEngine()
    apply_config(sh, cfg, log=lambda *_: None)
    c = sh.core
    ok = (c.dst_active and c.dst_ip == "10.0.0.5" and c.dst_port == "8080"
          and c.dst_ip_matcher.matches("10.0.0.5") and c.dst_port_matcher.matches(8080)
          and abs(c.syn_drop - 0.40) < 1e-9 and c.max_size == 1200)
    check("CLI: advanced flags configure the engine", ok,
          f"(ip={c.dst_ip} port={c.dst_port} syn={c.syn_drop} mtu={c.max_size})")


# --- tests for newer mechanisms (RST, NAT, spikes, schedule) --------------- #


def test_cli_parsing_and_override():
    from beantester import build_arg_parser, config_from_args, CLI_FILTERS
    args = build_arg_parser().parse_args(
        ["--preset", "Sieć 3G", "--loss", "7", "--down", "500", "--filter", "tcp"])
    cfg = config_from_args(args)
    s = cfg["settings"]
    check("CLI: --loss overrides preset", s["loss"] == 7, f"(loss={s['loss']})")
    check("CLI: --down overrides preset", s["down"] == 500, f"(down={s['down']})")
    check("CLI: preset value preserved (lat=150)", s["latency"] == 150, f"(lat={s['latency']})")
    check("CLI: 'tcp' filter mapped", cfg["filter"] == CLI_FILTERS["tcp"])


def test_cli_apply_config():
    from beantester import build_arg_parser, config_from_args, apply_config
    args = build_arg_parser().parse_args(
        ["--loss", "5", "--latency", "200", "--down", "100",
         "--flap-period", "8", "--flap-down", "25",
         "--rst-prob", "15", "--nat-timeout", "20", "--rate-schedule", "1:100:0,1:400:0"])
    cfg = config_from_args(args)
    sh = BeanEngine()
    apply_config(sh, cfg, log=lambda *_: None)
    c = sh.core
    ok = (abs(c.loss - 0.05) < 1e-9 and abs(c.latency_s - 0.2) < 1e-9
          and c.rate_down == 100 * 1024 and c.flap_enabled
          and abs(c.flap_period_s - 8) < 1e-9 and abs(c.flap_down - 0.25) < 1e-9
          and abs(c.rst_prob - 0.15) < 1e-9 and abs(c.nat_timeout_s - 20) < 1e-9
          and len(c.schedule) == 2)
    check("CLI: apply_config configures the engine (with RST/NAT/schedule)", ok)


def test_cli_config_precedence():
    from beantester import build_arg_parser, config_from_args, save_config_file, DEFAULT_SETTINGS
    import tempfile, os as _os
    s = dict(DEFAULT_SETTINGS); s.update(loss=3, down=222)
    path = _os.path.join(tempfile.gettempdir(), "ns_prec.json")
    save_config_file(path, s)
    # file sets loss=3, down=222; the --down 999 flag should win
    args = build_arg_parser().parse_args(["--config", path, "--down", "999"])
    cfg = config_from_args(args)
    check("CLI: --config loaded (loss=3)", cfg["settings"]["loss"] == 3)
    check("CLI: flag overrides file (down=999)", cfg["settings"]["down"] == 999)


def test_cli_english():
    from beantester import build_arg_parser, config_from_args, PRESETS
    p = build_arg_parser()
    check("CLI: parser description in English", "poor network conditions" in (p.description or ""))
    # English preset name maps to the canonical one
    cfg = config_from_args(p.parse_args(["--preset", "3G network", "--simulate"]))
    ref = PRESETS["presets.3g"]
    ok = (cfg["settings"]["latency"] == ref["lat"] and cfg["settings"]["down"] == ref["down"])
    check("CLI: English preset name works", ok, f"({cfg['settings'].get('latency')})")
    # Polish preset name still works (compatibility)
    cfg2 = config_from_args(p.parse_args(["--preset", "Sieć 3G", "--simulate"]))
    check("CLI: Polish preset name still works", cfg2["settings"]["latency"] == ref["lat"])


def test_lan_mode_cli():
    from beantester import build_arg_parser, config_from_args
    cfg = config_from_args(build_arg_parser().parse_args(["--lan-mode", "--simulate"]))
    check("LAN CLI: flag sets lan_mode", cfg["settings"]["lan_mode"] is True)
    from beantester import settings_to_cli
    argv = settings_to_cli({"lan_mode": True})
    check("LAN CLI: reproduces --lan-mode", "--lan-mode" in argv, f"({argv})")


def test_cli_unknown_preset_exits():
    from beantester import build_arg_parser, config_from_args
    args = build_arg_parser().parse_args(["--preset", "definitely-not-a-preset"])
    failed = False
    try:
        config_from_args(args)
    except SystemExit:
        failed = True
    check("CLI: unknown preset exits with an error", failed)


# --- filter expressions through the CLI ------------------------------------ #


def test_cli_dst_port_accepts_an_expression():
    from beantester import build_arg_parser, config_from_args, apply_config
    args = build_arg_parser().parse_args(["--dst-port", "80,443,8000-8100,!8080"])
    cfg = config_from_args(args)
    sh = BeanEngine()
    apply_config(sh, cfg, log=lambda *_: None)
    m = sh.core.dst_port_matcher
    check("CLI: --dst-port list/range applies", m.matches(80) and m.matches(8100))
    check("CLI: --dst-port exclusion applies", not m.matches(8080))
    check("CLI: --dst-port rejects unlisted ports", not m.matches(22))
    check("CLI: destination targeting switched on", sh.core.dst_active is True)


def test_cli_dst_ip_accepts_range_cidr_and_ipv6():
    from beantester import build_arg_parser, config_from_args, apply_config
    args = build_arg_parser().parse_args(
        ["--dst-ip", "10.0.0.1-10.0.0.50, 192.168.1.0/24, 2001:db8::/32, !10.0.0.7"])
    cfg = config_from_args(args)
    sh = BeanEngine()
    apply_config(sh, cfg, log=lambda *_: None)
    m = sh.core.dst_ip_matcher
    check("CLI: --dst-ip range applies", m.matches("10.0.0.25"))
    check("CLI: --dst-ip CIDR applies", m.matches("192.168.1.9"))
    check("CLI: --dst-ip IPv6 CIDR applies", m.matches("2001:db8::1"))
    check("CLI: --dst-ip exclusion applies", not m.matches("10.0.0.7"))
    check("CLI: --dst-ip rejects the rest", not m.matches("8.8.8.8"))


def test_cli_target_accepts_an_expression():
    from beantester import build_arg_parser, config_from_args
    cfg = config_from_args(build_arg_parser().parse_args(
        ["--target", "chrome.exe,!chromedriver,re:^fire"]))
    check("CLI: --target keeps the expression verbatim",
          cfg["settings"]["target"] == "chrome.exe,!chromedriver,re:^fire",
          f"({cfg['settings']['target']})")


def test_cli_rejects_bad_expressions():
    from beantester import build_arg_parser, config_from_args
    p = build_arg_parser()
    bad = (["--dst-port", "80,abc"], ["--dst-port", "2000-1000"],
           ["--dst-port", "99999"], ["--dst-ip", "10.0.0.1-2001:db8::1"],
           ["--dst-ip", "re:["], ["--target", ">chrome"])
    for argv in bad:
        raised = False
        try:
            config_from_args(p.parse_args(argv))
        except SystemExit:
            raised = True
        check(f"CLI rejects {argv}", raised)


def test_cli_expression_survives_the_repro_command():
    from beantester import (build_arg_parser, config_from_args, settings_to_cli,
                            settings_to_cli_string, DEFAULT_SETTINGS)
    s = dict(DEFAULT_SETTINGS)
    s.update(dst_ip="10.0.0.1-10.0.0.50,!10.0.0.7", dst_port="80,443,!8080",
             target="chrome,!chromedriver", loss=5)
    argv = settings_to_cli(s, seed=7)
    parsed = config_from_args(build_arg_parser().parse_args(argv))["settings"]
    ok = (parsed["dst_ip"] == s["dst_ip"] and parsed["dst_port"] == s["dst_port"]
          and parsed["target"] == s["target"])
    check("CLI command reproduces the expressions verbatim", ok, f"({parsed})")
    cmd = settings_to_cli_string(s, seed=7)
    check("expressions are quoted in the copy-paste command",
          '"10.0.0.1-10.0.0.50,!10.0.0.7"' in cmd and '"80,443,!8080"' in cmd,
          f"({cmd})")
