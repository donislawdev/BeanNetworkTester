"""Human-readable, translated one-line summary of the active impairments."""
from .i18n import translate
from .settings import DEFAULT_SETTINGS, parse_schedule, setting_expression
from .utils import number_string, to_number


def settings_summary(s, lang=None, prefix_key="summary.prefix"):
    """Return a readable description of the active impairments in the given language.

    ``prefix_key`` lets the GUI say *what* the description refers to: the running
    session (``summary.prefix``), an unstarted form (``summary.prefix_preview``)
    or edits that have not been applied yet (``summary.prefix_pending``).
    """
    g = lambda k: s.get(k, DEFAULT_SETTINGS[k])
    tr = lambda key, **kw: translate(key, lang, **kw)
    # number_string, NOT "%.0f": rounding to whole units turned "0.5% loss" into
    # "0% loss" (and 0.9 KB/s into 1 KB/s) - the preview strip contradicted the
    # very fields it was describing.
    num = lambda k: number_string(g(k))
    parts = []
    if to_number(g("latency")):
        parts.append(tr("summary.latency", v=num("latency")))
    if to_number(g("jitter")):
        parts.append(tr("summary.jitter", v=num("jitter")))
    if to_number(g("loss")):
        parts.append(tr("summary.loss", v=num("loss")))
    if to_number(g("corrupt")):
        parts.append(tr("summary.corrupt", v=num("corrupt")))
    if to_number(g("dup")):
        parts.append(tr("summary.dup", v=num("dup")))
    sched = str(g("rate_schedule")).strip()
    scheduled = False
    if sched:
        try:
            scheduled = bool(parse_schedule(sched))
        except ValueError:
            scheduled = False
    # the schedule REPLACES the constant limits (BeanCore._current_rates), so
    # printing "download <= 256 KB/s" next to "variable throughput" described a
    # limit the engine was not applying
    if not scheduled:
        if to_number(g("down")):
            parts.append(tr("summary.down", v=num("down")))
        if to_number(g("up")):
            parts.append(tr("summary.up", v=num("up")))
    if to_number(g("spike_prob")) and to_number(g("spike_ms")):
        parts.append(tr("summary.spikes", ms=num("spike_ms"), p=num("spike_prob")))
    if to_number(g("syn_drop")):
        parts.append(tr("summary.syn", v=num("syn_drop")))
    if to_number(g("max_size")):
        parts.append(tr("summary.mtu", v=num("max_size")))
    if to_number(g("nat_timeout")):
        parts.append(tr("summary.nat", v=num("nat_timeout")))
    if to_number(g("rst_prob")):
        parts.append(tr("summary.rst", v=num("rst_prob")))
    if to_number(g("flap_period")) and to_number(g("flap_down")):
        parts.append(tr("summary.flap", v=num("flap_period")))
    if g("lan_mode"):
        parts.append(tr("summary.lan"))
    if scheduled:
        parts.append(tr("summary.schedule"))
    if str(g("target")).strip():
        parts.append(tr("summary.target", v=str(g("target")).strip()))
    dst_ip = setting_expression("dst_ip", g("dst_ip"))
    dst_port = setting_expression("dst_port", g("dst_port"))
    if dst_ip or dst_port:
        tgt = dst_ip or tr("summary.any_ip")
        parts.append(tr("summary.dest", v=tgt) + (f":{dst_port}" if dst_port else ""))
    block_ip = setting_expression("block_ip", g("block_ip"))
    block_port = setting_expression("block_port", g("block_port"))
    if block_ip or block_port:
        tgt = block_ip or tr("summary.any_ip")
        parts.append(tr("summary.block", v=tgt) + (f":{block_port}" if block_port else ""))
    seed = g("seed")
    if seed not in (None, -1, "", "-1"):
        parts.append(tr("summary.seed", v=seed))
    if not parts:
        return tr("summary.none")
    return tr(prefix_key) + ", ".join(parts) + "."
