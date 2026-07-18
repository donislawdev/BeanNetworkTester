"""Command-line mode (always English) and the GUI/CLI entry-point dispatcher.

Designed to be driven by CI/CD, which means three promises:

  * **every outcome has its own exit code** (``exitcodes.py``) - a missing
    scenario file or a run that impaired nothing can no longer end green,
  * **channels are separated**: human logs (``[bean] ...``) go to stderr, data
    goes to stdout - as text lines, or as NDJSON with ``--format json``,
  * **the run is deterministic**: ``--duration`` stops at the deadline (not at
    the next report tick), and ``--seed`` makes the whole session reproducible.

``run_cli`` takes its clock and its sleep function as arguments so the report
loop can be unit-tested in milliseconds instead of wall-clock seconds.
"""
import argparse
import json
import sys
import time

from . import appinfo, clilog, driver, exitcodes, winenv
from .appinfo import APP_NAME, command_name, program_name, __version__
from .clilog import LOG_PREFIX, CliLog
from . import crashlog
from .engine import BeanEngine
from .fields import BOOL, FIELD_DEFS
from .filters import CLI_FILTERS
from .paths import is_frozen
from .presets import PRESETS, resolve_preset
from .repro import save_repro_report, settings_to_cli_string
from .scenario import load_scenario_file
from .settings import (DEFAULT_SETTINGS, apply_settings, build_matchers,
                       load_config_file, parse_schedule, save_config_file,
                       validate_ranges)
from .synthetic import SyntheticDivert
from .utils import bytes_to_mb


class CliError(SystemExit):
    """A CLI failure carrying its exit code (never a raw traceback).

    ``SystemExit.code`` is the number a CI job sees; ``str(...)`` is the human
    message (which ``run_cli`` prints to stderr as ``[bean] error: ...``).
    """

    def __init__(self, code, message):
        self.code = int(code)
        self.message = str(message)
        super().__init__(self.code)

    def __str__(self):
        return self.message


class _Terminated(Exception):
    """SIGTERM / console close - the job was cancelled, stop cleanly."""


def _fail(code, message):
    raise CliError(code, message)


def build_arg_parser():
    p = argparse.ArgumentParser(
        prog=program_name(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Bean Network Tester - poor network conditions simulator. "
                    "Without arguments it launches the GUI.",
        epilog=exitcodes.HELP_TABLE)
    p.add_argument("--version", action="version",
                   version=f"{APP_NAME} {__version__}")
    p.add_argument("--license", action="store_true",
                   help="print the licence and the third-party notices, then exit")
    p.add_argument("--gui", action="store_true", help="force the GUI")
    p.add_argument("--config", help="load settings from a JSON file")
    p.add_argument("--save-config", help="save effective settings to a JSON file and exit")
    p.add_argument("--preset", metavar="PRESET",
                   help="load a preset (canonical id or its name in any UI language; "
                        "see README for the list)")
    p.add_argument("--filter", choices=list(CLI_FILTERS), default=None,
                   help="which traffic to capture at all (IPv4 and IPv6); ports are "
                        "filtered with --dst-port, not here")
    p.add_argument("--loss", type=float, help="packet loss [%%]")
    p.add_argument("--corrupt", type=float, help="corruption [%%]")
    p.add_argument("--dup", type=float, help="duplication [%%]")
    p.add_argument("--latency", type=float, help="latency [ms]")
    p.add_argument("--jitter", type=float, help="jitter [ms]")
    p.add_argument("--down", type=float, help="download limit [KB/s]")
    p.add_argument("--up", type=float, help="upload limit [KB/s]")
    p.add_argument("--buffer", type=float,
                   help="link buffer for the speed limit [ms], 0 = unlimited; "
                        "bounds the queueing delay a rate-limited link builds up "
                        "before it drops (bufferbloat)")
    p.add_argument("--target",
                   help="target processes: name/PID, comma-separated list, range, "
                        "wildcard, re: pattern, ! to exclude "
                        "(e.g. 'chrome.exe,!chromedriver' or 're:^fire')")
    p.add_argument("--dst-ip",
                   help="affect only traffic to/from these remote IPs: address, list, "
                        "range a-b, CIDR, wildcard, comparison, re: pattern, ! to exclude "
                        "(e.g. '10.0.0.1-10.0.0.50,!10.0.0.7'); IPv4 and IPv6")
    p.add_argument("--dst-port",
                   help="affect only these remote ports: number, list, range a-b, "
                        "comparison (>1024), wildcard, re: pattern, ! to exclude "
                        "(e.g. '80,443,8000-8100' or '!53')")
    p.add_argument("--lan-mode", action="store_true",
                   help="LAN mode: cut the internet (public addresses), keep the local network")
    p.add_argument("--block-ip",
                   help="block (drop) all traffic to these remote IPs: address, list, "
                        "range a-b, CIDR, wildcard, re: pattern, ! to exclude; IPv4 and IPv6")
    p.add_argument("--block-port",
                   help="block (drop) all traffic to these remote ports: number, list, "
                        "range a-b, comparison (>1024), wildcard, re: pattern, ! to exclude "
                        "(blocks on IP OR port; e.g. '--block-port 443')")
    p.add_argument("--syn-drop", type=float, help="dropped TCP SYN rate [%%]")
    p.add_argument("--max-size", type=int, help="MTU black hole: drop packets > N B")
    p.add_argument("--spike-prob", type=float, help="latency spike probability [%%]")
    p.add_argument("--spike-ms", type=float, help="latency spike size [ms]")
    p.add_argument("--nat-timeout", type=float, help="NAT mapping expiry after N s idle")
    p.add_argument("--rst-prob", type=float,
                   help="TCP connection reset (RST) probability [%%] - TCP only, "
                        "UDP has no reset")
    p.add_argument("--rst-cooldown", type=float,
                   help="how long to hold a reset TCP connection down [s]")
    p.add_argument("--rate-schedule", help="variable throughput: 'dur:down:up,...' (KB/s)")
    p.add_argument("--seed", type=int, help="RNG seed for reproducibility (identical randomization)")
    p.add_argument("--scenario", help="JSON scenario file on a timeline")
    p.add_argument("--loop", action="store_true", help="loop the scenario")
    p.add_argument("--flap-period", type=float, help="link outage period [s]")
    p.add_argument("--flap-down", type=float, help="fraction of the period down [%%]")
    # default=None (NOT 0): --duration is a setting now, so a flag that is not
    # given must not override a --config file with a zero
    p.add_argument("--duration", type=float, default=None,
                   help="run time [s], 0 = until Ctrl+C (also settable in the GUI)")
    p.add_argument("--row-limit", type=float, default=None,
                   help="most rows a GUI table will show, 0 = no limit "
                        "(the tables are virtualised, so this only bounds the "
                        "filter/sort work, not the rendering)")
    p.add_argument("--interval", type=float, default=2.0,
                   help="report every N seconds [s] (must be > 0)")
    p.add_argument("--log-conns", action="store_true", help="print observed connections at the end")
    p.add_argument("--repro-out", help="save a reproduction report (JSON) to a file at the end")
    p.add_argument("--simulate", action="store_true",
                   help="synthetic traffic instead of WinDivert (test without Windows/admin)")

    out = p.add_argument_group("output")
    out.add_argument("-v", "--verbose", action="count", default=0,
                     help="log what the tool is doing (effective settings, matchers, "
                          "resolved process ports, scenario steps, driver open/close)")
    out.add_argument("-q", "--quiet", action="store_true",
                     help="errors only: no log, no periodic reports")
    out.add_argument("--log-level", choices=sorted(clilog.LEVEL_NAMES),
                     help="explicit log level (overrides -v/-q)")
    out.add_argument("--log-file", help="also append the log to this file")
    out.add_argument("--format", choices=[clilog.TEXT, clilog.JSON], default=clilog.TEXT,
                     help="stdout format: human text, or NDJSON for CI (one JSON "
                          "object per report + a final summary)")

    ci = p.add_argument_group("CI/CD")
    ci.add_argument("--dry-run", action="store_true",
                    help="validate the configuration and exit (no driver, no traffic)")
    ci.add_argument("--print-config", action="store_true",
                    help="print the effective settings (after defaults < file < preset "
                         "< flags) as JSON and exit")
    ci.add_argument("--min-packets", type=int, default=0, metavar="N",
                    help="fail (exit %d) if fewer than N packets were captured - "
                         "catches a filter that matched nothing"
                         % exitcodes.ASSERTION)
    ci.add_argument("--fail-on-no-traffic", action="store_true",
                    help="shorthand for --min-packets 1")
    ci.add_argument("--doctor", action="store_true",
                    help="check the environment (admin, pydivert, WinDivert driver, "
                         "temp leftovers) and exit")
    ci.add_argument("--cleanup-driver", action="store_true",
                    help="unload a leftover WinDivert driver service (frees its locked "
                         ".sys file without a reboot) and exit")
    return p


def config_from_args(args):
    """Build ``(settings, control)`` from: defaults < file < preset < flags.

    Forces the CLI language to English first (convention 3): every message this
    function can raise - a bad expression, an out-of-range value, a broken
    schedule - is a CLI message, and the CLI is English regardless of the system
    or UI language.
    """
    from .i18n import set_language
    set_language("en")

    s = dict(DEFAULT_SETTINGS)
    if args.config:
        # Surface a bad config file as a clear CLI error (English, since
        # run_cli sets the language to "en"), never a raw traceback.
        try:
            s.update(load_config_file(args.config))
        except ValueError as e:
            _fail(exitcodes.CONFIG, f"invalid config file {args.config!r}: {e}")
        except OSError as e:
            _fail(exitcodes.CONFIG, f"cannot read config file {args.config!r}: {e}")
    if args.preset:
        canon = resolve_preset(args.preset)
        if canon is None:
            _fail(exitcodes.CONFIG, f"unknown preset: {args.preset!r} "
                                    f"(canonical ids: {', '.join(PRESETS)})")
        p = PRESETS[canon]
        s.update(loss=p["loss"], corrupt=p["corrupt"], dup=p["dup"],
                 latency=p["lat"], jitter=p["jit"], down=p["down"], up=p["up"])

    # The flag -> settings-key mapping is DERIVED from the field registry, not
    # hand-written. It used to be a literal dict here, which meant a new field had
    # to be added in three places (fields.FIELD_DEFS, the parser, and this map) and
    # only two of them were guarded by a test: a field could be declared, get its
    # widget and its --flag, and still be silently dropped on the way to the engine.
    # ``tests/test_field_registry.py`` now checks that this map covers the registry.
    for field in FIELD_DEFS:
        if not field.cli:
            continue
        value = getattr(args, field.cli.replace("-", "_"), None)
        if field.kind == BOOL:
            # store_true flags default to False, not None. Setting the key on a
            # False would let an absent flag overwrite a --config file's True -
            # the same precedence bug that once made --duration zero out a config.
            if value:
                s[field.key] = True
        elif value is not None:
            s[field.key] = value

    wd_filter = CLI_FILTERS.get(s["filter"], s["filter"])

    # Reject malformed optional inputs up front with a clear message instead of
    # silently ignoring them (CLI errors are always English by convention).
    sched = str(s.get("rate_schedule", "")).strip()
    if sched:
        try:
            parse_schedule(sched)
        except ValueError as e:
            _fail(exitcodes.CONFIG, str(e))
    try:
        build_matchers(s)          # --target / --dst-ip / --dst-port expressions
    except ValueError as e:
        _fail(exitcodes.CONFIG, str(e))
    try:
        validate_ranges(s)         # --loss 250 (and --duration -5) are mistakes
    except ValueError as e:
        _fail(exitcodes.CONFIG, str(e))

    interval = float(getattr(args, "interval", 2.0) or 0)
    if interval <= 0:
        # 0 used to mean "busy-loop at 100% CPU and spam the log"
        _fail(exitcodes.CONFIG, "--interval must be greater than 0")

    min_packets = int(getattr(args, "min_packets", 0) or 0)
    if getattr(args, "fail_on_no_traffic", False):
        min_packets = max(1, min_packets)

    return dict(settings=s, filter=wd_filter, simulate=args.simulate,
                duration=float(s["duration"]), interval=interval,
                log_conns=args.log_conns, save_config=args.save_config,
                scenario=args.scenario, loop=args.loop, repro_out=args.repro_out,
                min_packets=min_packets)


def apply_config(engine, cfg, log=print):
    apply_settings(engine, cfg["settings"], log)


# -- output helpers ---------------------------------------------------------- #
def _conn_records(engine, limit=30):
    return engine.connections_snapshot(limit=limit)


def _print_conns(engine, log):
    conns = _conn_records(engine)
    if not conns:
        log.info("No observed connections.")
        return
    log.info(f"Observed connections ({len(conns)}):")
    for c in conns:
        log.info(f"  {c.get('dir', '?'):3} {c['remote_ip']}:{c['remote_port']:<6} "
                 f"local:{c['local_port']:<6} packets={c['packets']:<6} bytes={c['bytes']}")


def _sample_record(elapsed, down, up, s):
    return dict(event="sample", t=round(elapsed, 1),
                down_kbps=round(down, 1), up_kbps=round(up, 1),
                packets=s["seen"], drop_loss=s["drop_loss"], drop_syn=s["drop_syn"],
                drop_nat=s["drop_nat"], drop_rst=s["drop_rst"], rst_sent=s["rst_sent"],
                drop_lan=s["drop_lan"], drop_block=s["drop_block"],
                corrupted=s["corrupted"],
                duplicated=s["duplicated"], drop_overflow=s["drop_overflow"],
                drop_rate=s["drop_rate"],
                queue=s["queue"])


def _sample_text(elapsed, down, up, s):
    return (f"[{elapsed:6.1f}s] down={down:7.1f} up={up:7.1f} KB/s | "
            f"pkts={s['seen']} loss={s['drop_loss']} syn={s['drop_syn']} "
            f"nat={s['drop_nat']} rst={s['drop_rst']}/{s['rst_sent']} "
            f"lan={s['drop_lan']} block={s['drop_block']} corrupt={s['corrupted']} "
            f"rate={s['drop_rate']} queue={s['queue']}")


def _emit_summary(log, record, lines):
    """The result: NDJSON object on stdout, or the classic ``[bean]`` lines."""
    if log.fmt == clilog.JSON:
        log.data(record, "")
    else:
        for line in lines:
            log.info(line)


def _install_signal_handlers():
    """Make SIGTERM (CI cancellation, docker stop) a clean, coded shutdown."""
    import signal

    def handler(_signum, _frame):
        raise _Terminated()

    for name in ("SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError) as _exc:
            crashlog.note(_exc, "cli")


def _log_effective_settings(log, cfg):
    log.debug("effective settings: "
              + json.dumps(cfg["settings"], sort_keys=True, ensure_ascii=False))
    log.debug(f"WinDivert filter: {cfg['filter']}")
    try:
        for key, matcher in build_matchers(cfg["settings"]).items():
            if not matcher.is_empty:
                log.debug(f"matcher {key}: {matcher.describe()}")
    except ValueError as _exc:
        crashlog.note(_exc, "cli")


# -- sub-commands (they never touch the driver) -------------------------------- #
def _run_license(log):
    """Print the licence and what we ship with it.

    The LGPL obligation is towards the person holding the BINARY, who has no
    repository to browse. So the binary itself must be able to say: here is the
    licence, here are the components, here are their versions, here is where their
    source lives. Machine-readable under ``--format json``, because a corporate
    licence audit is a script more often than a person.
    """
    from . import legal
    rows = legal.component_rows()
    log.data(dict(event="license",
                  license=appinfo.LICENSE_NAME,
                  copyright=appinfo.COPYRIGHT,
                  telemetry=False,
                  components=[dict(name=n, version=v, license=lic, source=url)
                              for n, v, lic, url in rows]),
             legal.cli_report())
    return exitcodes.OK


def _run_doctor(log):
    ok, checks = driver.doctor()
    if log.fmt == clilog.JSON:
        log.data(dict(event="doctor", ok=ok,
                      checks=[dict(check=c, state=st, detail=d) for c, st, d in checks]), "")
    else:
        for check, state, detail in checks:
            log.data(dict(), f"{state.upper():<4} {check:<18} {detail}")
    return exitcodes.OK if ok else exitcodes.RUNTIME


def _run_cleanup(log):
    for line in driver.cleanup_driver():
        log.info(line)
    return exitcodes.OK


# -- the session ---------------------------------------------------------------- #
def _report_loop(engine, cfg, log, sleep, clock, t0):
    """Report every ``interval`` and stop exactly at the deadline.

    The old loop slept a whole interval and only then looked at the clock, so
    ``--duration 3 --interval 2`` actually ran 4 s and ``--duration 1
    --interval 5`` ran 5 s. Now the sleep is clipped to whichever comes first.
    """
    duration, interval = cfg["duration"], cfg["interval"]
    deadline = (t0 + duration) if duration > 0 else None
    next_report = t0 + interval
    prev, prev_t = engine.stats_snapshot(), t0
    while True:
        now = clock()
        wake = next_report if deadline is None else min(next_report, deadline)
        if wake > now:
            sleep(wake - now)
        now = clock()
        if now >= next_report - 1e-9:
            s = engine.stats_snapshot()
            dt = max(1e-3, now - prev_t)
            down = (s["bytes_in"] - prev["bytes_in"]) / 1024.0 / dt
            up = (s["bytes_out"] - prev["bytes_out"]) / 1024.0 / dt
            elapsed = now - t0
            log.sample(_sample_record(elapsed, down, up, s),
                       _sample_text(elapsed, down, up, s))
            log.debug(f"queue={s['queue']} peak_queue={s['peak_queue']} "
                      f"overflow={s['drop_overflow']} duplicated={s['duplicated']}")
            prev, prev_t = s, now
            while next_report <= now:
                next_report += interval
        if deadline is not None and now >= deadline - 1e-9:
            return "duration"
        if not engine.is_running():         # the engine's own watchdog stopped it
            return engine.stop_reason or "fault"


def _run_session(args, cfg, log, sleep, clock, engine):
    if cfg["simulate"] and cfg["settings"].get("target"):
        log.warn("--target is ignored in --simulate mode.")
        cfg["settings"]["target"] = ""

    if not cfg["simulate"] and not winenv.is_admin():
        _fail(exitcodes.PERMISSION,
              "Administrator rights are required to open WinDivert. "
              "Run this from an elevated shell (or use --simulate).")

    engine = engine or BeanEngine(log_fn=log.info)
    seed = cfg["settings"].get("seed", -1)
    seed_val = None if seed in (None, -1, "") else int(seed)
    engine.set_seed(seed_val)
    apply_config(engine, cfg, log.info)
    _log_effective_settings(log, cfg)

    divert = SyntheticDivert(seed=seed_val) if cfg["simulate"] else None
    if cfg["simulate"]:
        log.info("SIMULATION mode (synthetic traffic, no WinDivert).")

    try:
        log.debug("opening the divert...")
        engine.start(cfg["filter"], divert=divert, duration=cfg["duration"])
    except ImportError:
        _fail(exitcodes.RUNTIME,
              "pydivert is missing. Install it:  pip install pydivert  (or use --simulate)")
    except Exception as e:
        _fail(exitcodes.RUNTIME, f"cannot start the capture: {e}")

    scenario_failed = None
    if cfg["scenario"]:
        try:
            scen = load_scenario_file(cfg["scenario"])
            scen.loop = scen.loop or cfg["loop"]
            engine.start_scenario(scen, cfg["settings"], log=log.info)
            log.debug(f"scenario: {len(scen.steps)} steps, "
                      f"{scen.duration:.0f}s, loop={scen.loop}")
        except Exception as e:                 # a broken scenario is a failed run
            scenario_failed = e
            log.error(f"scenario error: {e}")

    code = exitcodes.OK
    stop_reason = "user"
    t0 = clock()
    if scenario_failed is None:
        limit = f", stopping after {cfg['duration']:g}s" if cfg["duration"] else ""
        log.info(f"Running{limit}. Ctrl+C to stop.")
        try:
            stop_reason = _report_loop(engine, cfg, log, sleep, clock, t0)
        except KeyboardInterrupt:
            log.warn("Interrupted (Ctrl+C).")
            code, stop_reason = exitcodes.INTERRUPTED, "interrupted"
        except _Terminated:
            log.warn("Terminated (SIGTERM).")
            code, stop_reason = exitcodes.TERMINATED, "terminated"
        finally:
            engine.stop()
    else:
        engine.stop()
        code, stop_reason = exitcodes.SCENARIO, "scenario_error"

    if engine.fault and code == exitcodes.OK:
        code, stop_reason = exitcodes.RUNTIME, "fault"

    stats = engine.stats_snapshot()
    elapsed = round(clock() - t0, 1)
    eff = engine.effective_seed()
    repro = settings_to_cli_string(cfg["settings"], seed=eff,
                                   simulate=cfg["simulate"]) if eff is not None else None

    if cfg["log_conns"] and log.fmt == clilog.TEXT:
        _print_conns(engine, log)

    report_path = None
    if cfg["repro_out"]:
        try:
            save_repro_report(cfg["repro_out"], engine, cfg["settings"])
            report_path = cfg["repro_out"]
            log.info(f"Repro report saved: {cfg['repro_out']}")
        except OSError as e:                    # an unwritable artifact IS a failure
            log.error(f"cannot save the repro report {cfg['repro_out']!r}: {e}")
            if code == exitcodes.OK:
                code = exitcodes.IO

    if cfg["min_packets"] and stats["seen"] < cfg["min_packets"] and code == exitcodes.OK:
        log.error(f"only {stats['seen']} packet(s) captured, expected at least "
                  f"{cfg['min_packets']} - the traffic filter matched nothing?")
        code = exitcodes.ASSERTION

    down_mb, up_mb = bytes_to_mb(stats["bytes_in"]), bytes_to_mb(stats["bytes_out"])
    record = dict(event="summary", exit_code=code, exit_name=exitcodes.name_of(code),
                  stop_reason=stop_reason, seed=eff, elapsed_s=elapsed,
                  duration_s=cfg["duration"], packets=stats["seen"],
                  downloaded_mb=down_mb, uploaded_mb=up_mb,
                  total_mb=round(down_mb + up_mb, 2), counters=stats,
                  fault=engine.fault, repro_command=repro, repro_report=report_path)
    if cfg["log_conns"]:
        record["connections"] = _conn_records(engine)
    lines = [f"Data usage: downloaded {down_mb} MB, uploaded {up_mb} MB, "
             f"total {round(down_mb + up_mb, 2)} MB."]
    if eff is not None:
        lines += [f"Session seed: {eff}", f"Reproduce: {repro}"]
    lines.append(f"Finished: {exitcodes.name_of(code).lower()} "
                 f"(exit {code}, reason={stop_reason}).")
    _emit_summary(log, record, lines)
    return code


def run_cli(argv=None, sleep=time.sleep, clock=time.monotonic, engine=None,
            out=None, err=None):
    """Run the CLI. Returns the process exit code (see ``exitcodes``)."""
    # CLI is always English (regardless of the system language).
    from .i18n import set_language
    set_language("en")

    args = build_arg_parser().parse_args(argv)
    log = CliLog(level=clilog.level_from_args(args.quiet, args.verbose, args.log_level),
                 fmt=args.format, log_file=args.log_file, samples=not args.quiet,
                 out=out, err=err)
    _install_signal_handlers()
    try:
        if args.license:
            return _run_license(log)
        if args.doctor:
            return _run_doctor(log)
        if args.cleanup_driver:
            return _run_cleanup(log)

        cfg = config_from_args(args)

        if args.print_config:
            log.data(dict(event="config", settings=cfg["settings"]),
                     json.dumps(cfg["settings"], indent=2, sort_keys=True))
            return exitcodes.OK
        if cfg["save_config"]:
            try:
                save_config_file(cfg["save_config"], cfg["settings"])
            except OSError as e:
                _fail(exitcodes.IO,
                      f"cannot save the config file {cfg['save_config']!r}: {e}")
            log.info(f"Saved settings to {cfg['save_config']}")
            return exitcodes.OK
        if args.dry_run:
            _log_effective_settings(log, cfg)
            log.info("Configuration is valid (--dry-run: nothing was started).")
            return exitcodes.OK

        return _run_session(args, cfg, log, sleep, clock, engine)
    except CliError as e:
        log.error(f"error: {e.message}")
        return e.code
    except KeyboardInterrupt:
        log.warn("Interrupted (Ctrl+C).")
        return exitcodes.INTERRUPTED
    except _Terminated:
        log.warn("Terminated (SIGTERM).")
        return exitcodes.TERMINATED
    finally:
        # Unload the driver we loaded. A --simulate run never touched one, so this
        # is free where it does not matter; where it does, it is what makes the
        # tool's own directory deletable right after the process exits (the kernel
        # keeps WinDivert64.sys open - and locks the folder - while it is loaded).
        for line in driver.release_on_exit():
            log.debug(line)
        log.close()


def _run_gui(argv):
    """GUI mode from the same (console-subsystem) binary - see winenv.py."""
    if winenv.is_windows() and not winenv.is_admin():
        # capture needs an elevated token; ask for it before Tk exists. If the
        # user says no we keep going: the GUI still opens (and explains why a
        # session cannot start), it just cannot capture.
        if winenv.elevate_self(argv):
            return exitcodes.OK               # the elevated copy took over
    if is_frozen():
        winenv.detach_console()               # no black window behind the GUI
    try:
        import tkinter as tk

        from .gui import App
    except Exception:
        print(f"No tkinter. Use CLI mode, e.g.:  {command_name()} --simulate --loss 5",
              file=sys.stderr)
        return exitcodes.RUNTIME
    winenv.set_dpi_awareness()                # before the Tk root exists
    root = tk.Tk()
    App(root)
    root.mainloop()
    return exitcodes.OK


def main(argv=None):
    """No arguments -> GUI; any arguments (except ``--gui``) -> CLI."""
    # First thing, before anything has had a chance to fail: take over every failure
    # path (main thread, worker threads, and hard C-level crashes in the WinDivert
    # driver, which leave no Python traceback at all). A crash during start-up - the
    # kind a user cannot even describe - used to vanish completely.
    crashlog.install()
    argv = sys.argv[1:] if argv is None else argv
    if not argv or (len(argv) == 1 and argv[0] == "--gui"):
        return _run_gui(argv)
    return run_cli(argv)


# kept working for the previous module layout (docs, external scripts)
_set_dpi_awareness = winenv.set_dpi_awareness
