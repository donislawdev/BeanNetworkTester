"""Bug reproduction: CLI command builder and the full repro report (JSON)."""
import json
import time

from .appinfo import TOOL_ID, command_name
from .damage import corruption_pct, impairment_loss_pct
from .i18n import translate
from .settings import DEFAULT_SETTINGS, setting_expression
from .utils import bytes_to_mb, number_string, to_number


def settings_to_cli(settings, seed=None, simulate=False):
    """Build the list of CLI arguments that reproduce the given settings."""
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
               ("duration", "--duration")]
    for key, flag in numeric:
        if to_number(g(key)) != to_number(DEFAULT_SETTINGS[key]):
            args += [flag, number_string(g(key))]
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
    # Whether the block answered or stayed silent decides what the application
    # under test DID, so a run that leaves it out cannot be reproduced from its
    # own command - which is the whole job of this line.
    if g("block_reject"):
        args += ["--block-reject"]
    if g("lan_mode"):
        args += ["--lan-mode"]
    if g("ipv4_only"):
        args += ["--ipv4-only"]
    if g("ipv6_only"):
        args += ["--ipv6-only"]
    if g("internet_only"):
        args += ["--internet-only"]
    # START-only, and it changes what the session even SAW - a command without it
    # re-runs a wider capture, so `packets` and every percentage derived from it
    # describe a different run. It was missing until the guard below went looking
    # (test_summary_repro_views.py::test_every_setting_with_a_flag_reaches_the_
    # reproduction_command); the repro REPORT has carried `narrowed` all along,
    # which is why nobody noticed the command did not.
    if g("narrow_filter"):
        args += ["--narrow-filter"]
    filt = g("filter")
    if filt and filt != "both":
        args += ["--filter", str(filt)]
    sd = seed if seed is not None else g("seed")
    if sd not in (None, -1, "", "-1"):
        args += ["--seed", str(int(sd))]
    if simulate:
        args += ["--simulate"]
    return args


def settings_to_cli_string(settings, seed=None, simulate=False):
    # filter expressions carry shell metacharacters (, ! > < * ? |), so quote
    # any argument that has one - the command must be copy-paste ready.
    # The program name follows the build: a frozen user has no
    # "python bean_network_tester.py" to paste (appinfo.command_name).
    def q(a):
        return f'"{a}"' if any(ch in a for ch in ' ,!<>*?|&$()') else a
    return f"{command_name()} " + " ".join(q(a) for a in settings_to_cli(settings, seed, simulate))


def build_repro_report(engine, settings):
    """Return the full data needed to reproduce the session (to save as JSON)."""
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
        connections=engine.connections_snapshot(limit=50),
        cli_command=settings_to_cli_string(settings, seed=seed),
    )


def save_repro_report(path, engine, settings):
    rep = build_repro_report(engine, settings)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    return rep
