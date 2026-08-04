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
from .presets import PRESETS, preset_to_settings, resolve_preset
from .repro import save_repro_report, settings_to_cli_string
from .scenario import load_scenario_file
from .settings import (DEFAULT_SETTINGS, apply_settings, build_matchers,
                       load_config_file, parse_schedule, save_config_file,
                       validate_ranges, warn_if_unbounded)
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


# Examples BEFORE the flag list, because that is the order a reader needs them in
# (clig.dev). The usage block alone runs to 24 lines of about fifty flags, and the
# first thing anyone wants from a tool that size is one line they can copy. Four,
# chosen to cover the four shapes a run comes in: harmless, aimed, timed and
# machine-readable - the last two being what a pipeline needs.
#
# Kept in the description rather than the epilog: the epilog holds the exit-code
# table, which is the reference half, and argparse prints the description ABOVE
# the flags and the epilog below them.
_DESCRIPTION = """Bean Network Tester - poor network conditions simulator.
Without arguments it launches the GUI.

Examples:
  %(prog)s --simulate --loss 20 --duration 10
      try it out. No driver, no real traffic, nothing to break.

  %(prog)s --target chrome.exe --latency 200 --duration 30
      impair one application for half a minute, and nothing else.

  %(prog)s --dst-ip 10.0.0.5 --dst-port 443 --loss 5 --duration 60
      impair one destination. Narrow beats broad: the rest of the
      machine, including this shell, keeps working.

  %(prog)s --preset 3g --duration 60 --format json --repro-out run.json
      a named link profile, machine-readable output, and a report that
      carries the command needed to repeat the run.

A run with impairment turned on, no target and no --duration affects every
connection on this machine until you stop it, and says so before it starts.
"""


def build_arg_parser():
    p = argparse.ArgumentParser(
        prog=program_name(),
        # One line, not the 24 argparse generates from about fifty flags. Those
        # 24 lines sat above every readable thing in --help, and above the message
        # on a typo too - so the one sentence saying what was wrong arrived at the
        # bottom of a wall nobody reads. The flags are listed in full immediately
        # below, which is where a list belongs (clig.dev).
        usage="%(prog)s [options]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=_DESCRIPTION,
        epilog=exitcodes.HELP_TABLE)
    p.add_argument("--version", action="version",
                   version=f"{APP_NAME} {__version__}")
    p.add_argument("--license", action="store_true",
                   help="print the licence and the third-party notices, then exit")
    p.add_argument("--gui", action="store_true",
                   help="open the GUI (only valid on its own - the GUI has its "
                        "own controls, so it takes no settings flags)")
    p.add_argument("--config", help="load settings from a JSON file")
    p.add_argument("--save-config", help="save effective settings to a JSON file and exit")
    p.add_argument("--preset", metavar="PRESET",
                   help="load a preset by canonical id or by its name in any UI "
                        "language (the README lists them)")
    p.add_argument("--filter", choices=list(CLI_FILTERS), default=None,
                   help="which traffic to capture at all (IPv4 and IPv6). Ports are "
                        "filtered with --dst-port, not here")
    p.add_argument("--loss", type=float, help="packet loss [%%]")
    p.add_argument("--corrupt", type=float, help="corruption [%%]")
    p.add_argument("--dup", type=float, help="duplication [%%]")
    p.add_argument("--latency", type=float, help="latency [ms]")
    p.add_argument("--jitter", type=float, help="jitter [ms]")
    p.add_argument("--down", type=float, help="download limit [KB/s]")
    p.add_argument("--up", type=float, help="upload limit [KB/s]")
    p.add_argument("--buffer", type=float,
                   help="link buffer for the speed limit [ms], 0 = unlimited. It "
                        "bounds the queueing delay a rate-limited link builds up "
                        "before it drops (bufferbloat)")
    p.add_argument("--target",
                   help="target processes: name/PID, comma-separated list, range, "
                        "wildcard, re: pattern, ! to exclude "
                        "(e.g. 'chrome.exe,!chromedriver' or 're:^fire')")
    p.add_argument("--dst-ip",
                   help="affect only traffic to/from these remote IPs, IPv4 and IPv6: "
                        "address, list, range a-b, CIDR, wildcard, comparison, re: "
                        "pattern, ! to exclude (e.g. '10.0.0.1-10.0.0.50,!10.0.0.7')")
    p.add_argument("--dst-port",
                   help="affect only these remote ports: number, list, range a-b, "
                        "comparison (>1024), wildcard, re: pattern, ! to exclude "
                        "(e.g. '80,443,8000-8100' or '!53')")
    p.add_argument("--lan-mode", action="store_true",
                   help="LAN mode: cut the internet (public addresses), keep the local network")
    p.add_argument("--narrow-filter", action="store_true",
                   help="push --dst-ip/--dst-port into the WinDivert filter, so the "
                        "driver never hands over traffic that could not be impaired "
                        "(much faster at high packet rates). Applied at START only, "
                        "and then statistics and connections cover the narrowed "
                        "traffic only - the summary says when it took effect")
    p.add_argument("--block-ip",
                   help="block (drop) all traffic to these remote IPs, IPv4 and IPv6: "
                        "address, list, range a-b, CIDR, wildcard, re: pattern, "
                        "! to exclude")
    p.add_argument("--block-port",
                   help="block (drop) all traffic to these remote ports: number, list, "
                        "range a-b, comparison (>1024), wildcard, re: pattern, ! to exclude "
                        "(blocks on IP OR port, for example '--block-port 443')")
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
                   help="run time [s], 0 = until Ctrl+C - or, with a --scenario "
                        "that has a timeline, until that timeline runs out "
                        "(also settable in the GUI)")
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
            # The translated message already says "in the config file" and which
            # setting - so this prefix carries the PATH and nothing else. It used
            # to say "invalid config file", which put the word "invalid" and the
            # words "config file" on the line twice each.
            _fail(exitcodes.CONFIG, f"{args.config!r}: {e}")
        except OSError as e:
            _fail(exitcodes.CONFIG, f"cannot read config file {args.config!r}: {e}")
    if args.preset:
        canon = resolve_preset(args.preset)
        if canon is None:
            _fail(exitcodes.CONFIG, f"unknown preset: {args.preset!r} "
                                    f"(canonical ids: {', '.join(PRESETS)})")
        # Through the SHARED mapping, not a copy of it. This used to hand-write
        # the seven classic keys, which meant the GUI (which has always gone
        # through preset_to_settings) and the CLI applied different subsets of
        # the same preset: a profile field the copy did not know about reached
        # one front end and not the other, under the same preset name. Since a
        # preset may now name only the fields it means something by, the copy
        # would also KeyError on the first partial preset.
        s.update(preset_to_settings(PRESETS[canon]))

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
        # "-" for traffic that has no ports (ICMP). Those rows exist in the log
        # now, and formatting None with a width spec is a TypeError, not a blank:
        # this line would take the whole --log-conns run down with it.
        r_port = c.get("remote_port")
        l_port = c.get("local_port")
        r_port = "-" if r_port is None else r_port
        l_port = "-" if l_port is None else l_port
        log.info(f"  {c.get('dir', '?'):3} {c['remote_ip']}:{r_port:<6} "
                 f"local:{l_port:<6} packets={c['packets']:<6} bytes={c['bytes']}")


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
def _targeting_state(engine):
    """``(matched, description)`` of the live process target, or ``None``.

    ``matched`` is a plain bool on the live ``ProcessTargeting`` - no lock, no
    syscall, no socket table - so the report loop can afford to ask on every
    pass. ``getattr`` because ``run_cli(engine=...)`` is a public seam and an
    injected engine need not carry targeting at all.
    """
    getter = getattr(engine, "targeting", None)
    targeting = getter() if callable(getter) else None
    if targeting is None:
        return None
    return bool(targeting.matched), targeting.describe()


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
    # The verdict as it stands at the start; apply_settings has already logged
    # it. From here only CHANGES are reported. A target that dies mid-run was
    # invisible from the CLI: the run kept going, impaired nothing and exited 0,
    # which is exactly the "nothing broke" / "everything held up" confusion this
    # tool shouts about in the GUI. MEASURED 2026-07-28: targeting a PID, then
    # restarting that process, left 5 of 5 fresh connections untouched and the
    # only targeting line in the whole run was the one printed at start.
    # Sampled, not continuous: a verdict that flips and flips back between two
    # passes is not seen, and that is the honest limit of polling here.
    verdict = _targeting_state(engine)
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
        state = _targeting_state(engine)
        if state is not None and verdict is not None and state[0] != verdict[0]:
            if state[0]:
                log.info(f"the process target matches again: {state[1]}")
            else:
                log.warn("the process target no longer matches any process - "
                         "nothing is being impaired from here on")
        verdict = state
        if deadline is not None and now >= deadline - 1e-9:
            return "duration"
        # A scenario's timeline is an ending too, and without --duration it is the
        # ONLY one the run has. It used to be nobody's: the runner thread ended,
        # logged "Scenario finished." and left the session going forever - a CI
        # job that hangs to its timeout, with no summary and (on a real run) the
        # driver still loaded. Asked of the runner rather than derived from
        # `scen.duration` here, so the tail past the last step stays in one place.
        if cfg.get("stop_on_scenario") and engine.scenario_finished():
            return "scenario_done"
        if not engine.is_running():         # the engine's own watchdog stopped it
            return engine.stop_reason or "fault"


def _plan_the_end_of_the_scenario(log, cfg, scen, engine):
    """Decide whether the scenario's own end may stop this run, and say so.

    ``--duration`` is the user speaking and always wins; this only fills the gap
    where there is no deadline at all. A scenario can end the run when it has a
    timeline to run out of - which a looping one never does, and a single-step
    one does not have (``Scenario.duration`` is the ``at`` of the last step, so
    one step at 0 is duration 0 and would end the session inside a tenth of a
    second: settings, not a timeline).

    Where the run therefore cannot end by itself, that is said out loud. It has
    always been true and was never mentioned - the log said "Running. Ctrl+C to
    stop." and left the reader to discover the rest at the job timeout.
    """
    if cfg["duration"]:
        return
    if not callable(getattr(engine, "scenario_finished", None)):
        # An injected engine (public seam) may be a double that predates this
        # call. Falling back is right - crashing somebody's harness is not - but
        # falling back SILENTLY would quietly restore the hang.
        why = "this engine cannot report when a scenario ends"
    elif scen.loop:
        why = "it repeats"
    elif not scen.duration:
        why = "it has a single step, so there is no timeline"
    else:
        cfg["stop_on_scenario"] = True
        log.info(f"No --duration: this run will stop when the scenario ends "
                 f"(about {scen.duration:g}s).")
        return
    log.warn(f"this scenario will not stop the run on its own ({why}) and there "
             f"is no --duration, so the session keeps going until you stop it.")


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

    # Said BEFORE the divert opens, while stopping still costs nothing. This is
    # the mode our own documentation calls the most dangerous, and until now the
    # tool started it in silence: measured, `--lat 5` alone impaired 11 844
    # packets of a live machine for 202 s before anyone noticed. A
    # warning, not a refusal - refusing would break every pipeline that already
    # runs this way. Nothing to warn about in --simulate: there is no real traffic.
    if not cfg["simulate"]:
        warn_if_unbounded(cfg["settings"], log.warn)

    # Loaded BEFORE the capture starts, exactly like --dry-run does it. A scenario
    # file that cannot be read is knowable without touching the driver, and the
    # old order proved it: the run opened the divert, printed "Start.", impaired
    # traffic and only then said the file was broken. Failures from RUNNING the
    # scenario still land below, where the session can report them properly.
    scen = None
    if cfg["scenario"]:
        try:
            scen = load_scenario_file(cfg["scenario"])
        except Exception as e:
            _fail(exitcodes.SCENARIO, f"scenario error in {cfg['scenario']!r}: {e}")

    try:
        log.debug("opening the divert...")
        engine.start(cfg["filter"], divert=divert, duration=cfg["duration"],
                     narrow=bool(cfg["settings"].get("narrow_filter")))
    except ImportError:
        _fail(exitcodes.RUNTIME,
              "pydivert is missing. Install it:  pip install pydivert  (or use --simulate)")
    except Exception as e:
        _fail(exitcodes.RUNTIME, f"cannot start the capture: {e}")

    # Asked for and got it, or asked for and did NOT: both have to be said. A user
    # who turned this on wanted the throughput, and silently falling back to the
    # wide filter would leave them believing they had it. The fallback is not a
    # fault - a wildcard or re: destination simply cannot be expressed in the
    # driver's language, and capturing everything is the safe answer.
    if cfg["settings"].get("narrow_filter"):
        info = engine.session_info()
        if info.get("narrowed"):
            log.info("Driver filter narrowed to the destination - statistics and "
                     "connections now cover that traffic only.")
            log.debug(f"effective driver filter: {info.get('filter')}")
        else:
            log.warn("--narrow-filter had no effect: the destination could not be "
                     "expressed as a driver filter (a wildcard or re: pattern, or "
                     "no destination set). Capturing everything, as usual.")

    scenario_failed = None
    cfg["stop_on_scenario"] = False
    if scen is not None:
        try:
            scen.loop = scen.loop or cfg["loop"]
            engine.start_scenario(scen, cfg["settings"], log=log.info)
            log.debug(f"scenario: {len(scen.steps)} steps, "
                      f"{scen.duration:.0f}s, loop={scen.loop}")
            _plan_the_end_of_the_scenario(log, cfg, scen, engine)
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
        except Exception as exc:
            # Anything unforeseen in the session is STILL a coded exit (the CI
            # contract, convention 18). It used to escape run_cli outright: a
            # traceback on stderr, no summary record at all, and CPython's own
            # exit 1 - the same number as RUNTIME, so a job could not tell an
            # unhandled bug from a driver that would not open.
            # Caught HERE and not only at the top of run_cli because at this
            # point the engine is alive and the counters are readable, so the
            # run can still hand back a complete summary instead of a truncated
            # NDJSON file. CliError is a SystemExit and passes straight through
            # to its own handler, as before.
            crashlog.record(exc, "cli")
            log.error(f"unexpected failure in the session: "
                      f"{type(exc).__name__}: {exc}")
            code, stop_reason = exitcodes.RUNTIME, "fault"
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

    # --min-packets guards the CAPTURE FILTER (`seen`); this guards the TARGET.
    # They are different failures: traffic can flow all run while the targeted
    # process never matches, and the run then impairs nothing and still exits 0.
    # Only when there WAS traffic - with `seen` at 0 the filter is the story and
    # --min-packets is the flag that tells it, so saying both would point at the
    # wrong thing. Not an assertion: a target with no traffic of its own is a
    # legitimate run, and turning that into a failure would break the exit-code
    # contract for everyone already running one.
    target = str(cfg["settings"].get("target") or "").strip()
    scoped = stats.get("scoped_seen", 0)
    if target and stats["seen"] and not scoped:
        log.warn(f"the process target {target!r} caught nothing: 0 of "
                 f"{stats['seen']} captured packets were in scope, so this run "
                 f"impaired nothing")

    down_mb, up_mb = bytes_to_mb(stats["bytes_in"]), bytes_to_mb(stats["bytes_out"])
    # ADDITIVE to the NDJSON schema, and load-bearing: with the filter narrowed,
    # `packets` below no longer counts every packet on the machine, so two reports
    # with the same key can describe two different worlds. A consumer must be able
    # to tell them apart without being told out of band.
    session = engine.session_info() if hasattr(engine, "session_info") else {}
    record = dict(event="summary", exit_code=code, exit_name=exitcodes.name_of(code),
                  stop_reason=stop_reason, seed=eff, elapsed_s=elapsed,
                  capture_narrowed=bool(session.get("narrowed")),
                  duration_s=cfg["duration"], packets=stats["seen"],
                  downloaded_mb=down_mb, uploaded_mb=up_mb,
                  total_mb=round(down_mb + up_mb, 2), counters=stats,
                  fault=engine.fault, repro_command=repro, repro_report=report_path)
    if cfg["log_conns"]:
        record["connections"] = _conn_records(engine)
    lines = [f"Data usage: downloaded {down_mb} MB, uploaded {up_mb} MB, "
             f"total {round(down_mb + up_mb, 2)} MB."]
    if target:
        # Text channel only: the JSON summary already carries `scoped_seen` in
        # `counters`, and the NDJSON schema is a frozen contract (see "Public
        # contracts"). A human reading the text run had no way to see how much
        # of the captured traffic the target actually accounted for.
        lines.append(f"In scope: {scoped} of {stats['seen']} captured packets "
                     f"(process target {target!r}).")
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
        # --gui reaching the CLI runner means it was combined with something else:
        # main() sends a bare --gui straight to the GUI. It used to be accepted and
        # then ignored, so `--gui --loss 30 --duration 600` promised a window and
        # instead ran a headless ten-minute impairment - no window, no STOP button,
        # on a tool whose whole job is to break the user's own network.
        if args.gui:
            _fail(exitcodes.USAGE,
                  "--gui cannot be combined with other options: it opens the GUI, "
                  "which has its own controls. Launch the GUI with no arguments, or "
                  "drop --gui to run these settings from the command line.")
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
            # What this gate checks is the CONFIGURATION: every value, every
            # expression, the schedule, and the scenario file. What it does NOT
            # check is the MACHINE - it never asks about Administrator rights or
            # about pydivert, so on a box without them it answers OK about a
            # command that will exit PERMISSION(7) or RUNTIME(1). That is on
            # purpose: validating a config on a build agent and running it on
            # another machine is a normal thing to do, and widening the check
            # would break it. The success line names --doctor for the other half,
            # so the pair answers the question this one alone cannot.
            #
            # The scenario is part of the configuration and used to be loaded
            # only once the session started, so --dry-run reported "Configuration
            # is valid" about a file it had never opened: a truncated, empty or
            # non-object scenario passed the check with exit OK and then failed
            # the real run with SCENARIO(4).
            if cfg["scenario"]:
                try:
                    scen = load_scenario_file(cfg["scenario"])
                except Exception as e:
                    _fail(exitcodes.SCENARIO,
                          f"scenario error in {cfg['scenario']!r}: {e}")
                log.debug(f"scenario: {len(scen.steps)} steps, "
                          f"{scen.duration:.0f}s, loop={scen.loop or cfg['loop']}")
            _log_effective_settings(log, cfg)
            # A preview that stays quiet about the dangerous shape is a preview
            # that misleads: "Configuration is valid" is about each value, and the
            # warning is about the SHAPE - impairment armed, nothing aimed at,
            # nothing to end it. This is the cheapest place a user can find that
            # out, since --dry-run touches neither the driver nor the traffic.
            if not cfg["simulate"]:
                warn_if_unbounded(cfg["settings"], log.warn)
            log.info("Configuration is valid (--dry-run: nothing was started). "
                     "This checks the settings, not the machine - run --doctor "
                     "for Administrator rights and the WinDivert driver.")
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
    except Exception as exc:
        # Last resort. The session has its own handler (which can still emit a
        # summary); this one covers everything outside it - loading a config,
        # building the result, a bug in this module - where there is nothing
        # left to report. The promise it keeps is the narrow one from the class
        # docstring above: an exit CODE, never a raw traceback.
        crashlog.record(exc, "cli")
        # Worded to name its PHASE. A fault in something the summary also needs
        # (the counters, say) trips the session handler first and then this one,
        # and two identical "unexpected failure" lines read like two separate
        # bugs instead of one fault and the report it took down with it.
        log.error(f"unexpected failure while finishing the run: "
                  f"{type(exc).__name__}: {exc}")
        return exitcodes.RUNTIME
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
