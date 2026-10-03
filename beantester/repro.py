"""Bug reproduction: CLI command builder and the full repro report (JSON)."""
import json
import math
import os
import re
import string
import time

from .appinfo import TOOL_ID, command_name
from .damage import corruption_pct, impairment_loss_pct
from .i18n import translate
from .paths import temp_beside
from .settings import DEFAULT_SETTINGS, setting_expression
from .utils import bytes_to_mb, number_string, to_number
from . import crashlog

# Settings whose flag takes a WHOLE number (`type=int` in cli.build_arg_parser).
# The field itself is a number like any other, so the form and a config file can
# hold 1400.5 - and `--max-size 1400.5` is then refused by argparse (exit 2). The
# core truncates it anyway (core.set_advanced), so the whole part is the setting.
WHOLE_NUMBER_FLAGS = frozenset({"max_size"})

# How many connection rows a report carries: the most recently active flows. The
# CLI reads it to size the one snapshot it takes at the end of a run.
REPORT_CONNECTIONS = 50

# What an argument may hold and still be pasted into cmd.exe and PowerShell alike
# without quotes. Everything else is quoted - a list of the characters that break
# a shell is the list that goes missing (`^` did: cmd drops it, so `re:^edge`
# arrived as `re:edge` and matched msedge.exe too).
_BARE = frozenset(string.ascii_letters + string.digits + "-_.:/\\+=")


def settings_to_cli(settings, seed=None, simulate=False, scenario=None, loop=False):
    """Build the list of CLI arguments that reproduce the given settings.

    ``scenario`` is the scenario file as it was named when the session ran, and
    ``loop`` whether it looped; both come from the engine (see session_command).
    """
    g = lambda k: settings.get(k, DEFAULT_SETTINGS[k])
    args = []
    numeric = [("loss", "--loss"), ("loss_burst", "--loss-burst"),
               ("corrupt", "--corrupt"), ("dup", "--dup"),
               ("latency", "--latency"), ("jitter", "--jitter"),
               ("down", "--down"), ("up", "--up"), ("buffer", "--buffer"),
               ("syn_drop", "--syn-drop"), ("max_size", "--max-size"),
               ("spike_prob", "--spike-prob"), ("spike_ms", "--spike-ms"),
               ("nat_timeout", "--nat-timeout"), ("rst_prob", "--rst-prob"),
               ("rst_cooldown", "--rst-cooldown"),
               ("flap_period", "--flap-period"), ("flap_down", "--flap-down"),
               ("duration", "--duration"),
               # The upload half. These go out whenever they DIFFER from the
               # default, exactly like every line above - and `--asym` below
               # decides whether the run reads them, so a command carrying a
               # value without the switch reproduces a symmetric session, which
               # is what that session was.
               ("loss_up", "--loss-up"), ("corrupt_up", "--corrupt-up"),
               ("dup_up", "--dup-up"), ("latency_up", "--latency-up"),
               ("jitter_up", "--jitter-up"),
               ("spike_prob_up", "--spike-prob-up"),
               ("spike_ms_up", "--spike-ms-up")]
    for key, flag in numeric:
        value = g(key)
        if key in WHOLE_NUMBER_FLAGS and math.isfinite(to_number(value)):
            value = int(to_number(value))
        if to_number(value) != to_number(DEFAULT_SETTINGS[key]):
            args += [flag, number_string(value)]
    if str(g("rate_schedule")).strip():
        args += ["--rate-schedule", str(g("rate_schedule")).strip()]
    if str(g("target")).strip():
        args += ["--target", str(g("target")).strip()]
    dst_ip = setting_expression("dst_ip", g("dst_ip"))
    if dst_ip:
        args += ["--dst-ip", dst_ip]
    dst_port = setting_expression("dst_port", g("dst_port"))
    if dst_port:
        args += ["--dst-port", dst_port]
    block_ip = setting_expression("block_ip", g("block_ip"))
    if block_ip:
        args += ["--block-ip", block_ip]
    block_port = setting_expression("block_port", g("block_port"))
    if block_port:
        args += ["--block-port", block_port]
    # The plain on/off switches, as a table rather than seven identical branches
    # - the shape `settings_summary` took for the same reason, and the same
    # reason it matters here: the complexity ratchet counts the branches, so the
    # seventh switch would have cost something it should not. Order is the order
    # they were emitted in, because a repro command is compared by eye against
    # older ones.
    #
    # Each line still carries WHY it has to be in the command at all:
    #  * block_reject - whether the block answered or stayed silent decides what
    #    the application under test DID, so a run without it is not the same run;
    #  * asym - which half of the numbers above the session actually applied.
    #    Without it a command carrying seven upload values replays them as a
    #    symmetric run, and that difference is the point of the session;
    #  * narrow_filter - START-only, and it changes what the session even SAW, so
    #    `packets` and every percentage from it describe a different run. It was
    #    missing until the guard below went looking (test_summary_repro_views.py
    #    ::test_every_setting_with_a_flag_reaches_the_reproduction_command); the
    #    repro REPORT has carried `narrowed` all along, which is why nobody
    #    noticed the command did not.
    for key, flag in (("block_reject", "--block-reject"), ("asym", "--asym"),
                      ("lan_mode", "--lan-mode"), ("ipv4_only", "--ipv4-only"),
                      ("ipv6_only", "--ipv6-only"),
                      ("internet_only", "--internet-only"),
                      ("narrow_filter", "--narrow-filter")):
        if g(key):
            args.append(flag)
    filt = g("filter")
    if filt and filt != "both":
        args += ["--filter", str(filt)]
    sd = seed if seed is not None else g("seed")
    if sd not in (None, -1, "", "-1"):
        args += ["--seed", str(int(sd))]
    # The scenario is what changed the settings over time, so a command without it
    # replays the first step for the whole run (external review, P1-3).
    if scenario:
        args += ["--scenario", str(scenario)]
        if loop:
            args += ["--loop"]
    if simulate:
        args += ["--simulate"]
    return args


def _quote(arg):
    """One argument as cmd.exe and PowerShell will both hand it to the program.

    Bare when every character is in ``_BARE``, double-quoted otherwise. A double
    quote INSIDE has no spelling both shells read the same way (cmd flips its
    quoting on it, PowerShell does not take ``\\"``), so in an expression with a
    ``re:`` term - the only term an address or a port can hold one in - it is
    written ``\\x22``, the same pattern with no quote in it; a process name cannot
    hold one on Windows, and anywhere else it is escaped the way
    CommandLineToArgvW reads it. What quotes do not stop - measured, and accepted (owner decision
    2026-09-29): cmd expands ``%NAME%`` inside them, PowerShell ``$name`` and a
    backtick. None of those has a place in a process name, an address or a port.
    """
    if arg and all(ch in _BARE for ch in arg):
        return arg
    if "re:" in arg.lower():
        # `\"` in a pattern is an escaped quote, `\\"` a backslash and a quote
        arg = re.sub(r'(\\*)"', lambda m: (m.group(1)[:-1] if len(m.group(1)) % 2
                                          else m.group(1)) + r"\x22", arg)
    else:
        arg = re.sub(r'(\\*)"', lambda m: m.group(1) * 2 + '\\"', arg)
    # a backslash that ends the argument would escape the closing quote
    return '"' + re.sub(r"(\\+)$", lambda m: m.group(1) * 2, arg) + '"'


def settings_to_cli_string(settings, seed=None, simulate=False, scenario=None, loop=False):
    # Copy-paste ready: every argument a shell would read its own way is quoted
    # (see _quote). The program name follows the build: a frozen user has no
    # "python bean_network_tester.py" to paste (appinfo.command_name).
    args = settings_to_cli(settings, seed, simulate, scenario, loop)
    return f"{command_name()} " + " ".join(_quote(a) for a in args)


def session_command(engine, settings):
    """The command that repeats the session ``engine`` ran with ``settings``.

    ``settings`` are what the session was STARTED and APPLIED with, which only the
    caller knows (the CLI's configuration, the GUI's record of START and Apply).
    The rest is the engine's: the seed, whether the driver was a stand-in, and the
    scenario. It is read from the engine rather than handed in by each caller,
    because a handed-in flag is one a caller forgets - ``--simulate`` reached the
    console line and was missing from the report of the same run, which pasted on
    an elevated machine impairs the real network (external review, P1-3).
    """
    # hasattr, as cli._report_session already asks: the CLI's engine stand-ins in
    # the tests have no session_info, and a real BeanEngine always does.
    info = engine.session_info() if hasattr(engine, "session_info") else {}
    return settings_to_cli_string(settings, seed=engine.effective_seed(),
                                  simulate=bool(info.get("simulated")),
                                  scenario=info.get("scenario"),
                                  loop=bool(info.get("scenario_loop")))


def build_repro_report(engine, settings, connections=None):
    """Return the full data needed to reproduce the session (to save as JSON).

    ``connections``: rows the caller already took, as
    ``engine.connections_snapshot(limit=n)`` returns them (newest first) with
    ``n >= REPORT_CONNECTIONS``; the report keeps the first ``REPORT_CONNECTIONS``.
    None takes its own snapshot. The CLI passes the ONE snapshot it takes at the
    end of a run, so the console listing, the JSON summary and this report show the
    same rows and a 200 000-row log is walked once, not three times (performance
    review W-D9: ~50 ms a walk at the cap).
    """
    info = engine.session_info()
    stats = engine.stats_snapshot()
    seed = engine.effective_seed()
    metrics = dict(
        packets=stats["seen"],
        packets_in_scope=stats.get("scoped_seen", stats["seen"]),
        downloaded_mb=bytes_to_mb(stats["bytes_in"]),
        uploaded_mb=bytes_to_mb(stats["bytes_out"]),
        total_mb=round(bytes_to_mb(stats["bytes_in"]) + bytes_to_mb(stats["bytes_out"]), 2),
        offered_mb=round(bytes_to_mb(stats.get("bytes_in_total", 0))
                         + bytes_to_mb(stats.get("bytes_out_total", 0)), 2),
        # Every impairment drop over the traffic that was in scope, not the
        # configured Loss over everything captured. Both parts moved; a report
        # from before this change is not comparable with one from after.
        effective_loss_pct=round(impairment_loss_pct(stats), 2),
        effective_corruption_pct=round(corruption_pct(stats), 2),
        # How many RUNS the loss arrived in. Zero with a run length configured
        # means the session was too short to see one, which is the difference
        # between a run that proved nothing and a tool that is broken.
        loss_runs=stats.get("loss_bursts", 0),
        # How many packets left this tool AFTER one that arrived later than they
        # did. Zero with jitter or a latency spike configured means the traffic
        # was too sparse for anything to overtake anything, not that the delay
        # was never applied - the same distinction loss_runs draws above.
        reordered=stats.get("reordered", 0),
        # connections_reset held drop_rst - the PACKETS a reset connection swallows
        # during its cooldown, which for a 30 s cooldown on a busy flow is thousands
        # against a handful of actual resets. The three RST numbers answer three
        # different questions and are now reported as three.
        connections_reset=stats.get("rst_reset", 0),
        rst_packets_dropped=stats["drop_rst"],
        rst_sent=stats["rst_sent"],
        syn_dropped=stats["drop_syn"],
        nat_expired=stats["drop_nat"],
        blocked=stats["drop_block"],
        # ...and how many of those blocked connections were REFUSED rather than
        # ignored. "23 packets blocked" does not say what the application under
        # test met, and that is the difference the report exists to preserve: a
        # refusal it handled in milliseconds, or a silence it sat out.
        blocked_refused=stats.get("block_rejected", 0),
        local_network_dropped=stats.get("drop_internet_only", 0),
        rate_dropped=stats["drop_rate"],
        peak_queue=stats.get("peak_queue", stats["queue"]),
    )
    return dict(
        tool=TOOL_ID,
        report_time=time.strftime("%Y-%m-%d %H:%M:%S"),
        session=info,
        seed=seed,
        settings=dict(settings),
        counters=stats,
        metrics=metrics,
        # descriptions stored as i18n keys are rendered in English so that
        # the whole report is shareable regardless of the UI language
        events=[dict(t=e[0], time=e[1], type=e[2],
                     description=translate(e[3], "en")) for e in engine.events_snapshot()],
        connections=(engine.connections_snapshot(limit=REPORT_CONNECTIONS)
                     if connections is None else connections[:REPORT_CONNECTIONS]),
        cli_command=session_command(engine, settings),
    )


def save_repro_report(path, engine, settings, connections=None):
    """Write the report atomically. RAISES on failure - both callers rely on that.

    ``connections``: see ``build_repro_report``.

    Deliberately not ``jsonfile.write_json``, which is the same write and would be
    the obvious reuse: it RETURNS an error string instead of raising, and both
    callers here catch. The CLI would then log "Repro report saved", set
    ``report_path`` and exit 0 over a file that was never written, which is a
    worse outcome than the duplication.

    Atomic for the reason in ``paths.temp_beside``: a temp name derived from the
    target is a name a second writer of that target picks too. Here the target is
    chosen by the user rather than fixed, so the collision is rarer than the one
    that motivated ``temp_beside`` - but a crash halfway through no longer leaves
    a truncated report sitting where a whole one is expected, which is the half
    that matters for an artefact people attach to bug reports.
    """
    rep = build_repro_report(engine, settings, connections)
    tmp = temp_beside(path)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Leave no half-written file behind, then let the caller see the failure.
        # BaseException, not Exception: an interrupt here is exactly when the
        # litter would be left, and the cleanup must not depend on how we left.
        with crashlog.quiet("repro.cleanup"):
            if os.path.exists(tmp):
                os.remove(tmp)
        raise
    return rep
