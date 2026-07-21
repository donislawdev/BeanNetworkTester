"""Shared settings model + JSON config file (used by both the GUI and the CLI).

The shape of a setting (type, label, bounds, section, profile scope) lives in
``fields.FIELD_DEFS`` - this module only turns raw user input into a validated
settings dict and applies it to an engine.
"""
import json

from . import crashlog
from . import fields as F
from .jsonfile import write_json
from .fields import FIELD_DEFS, FIELDS
from .i18n import T, translate
from .matchers import KIND_PROCESS, parse_matcher, port_expression
from .processes import TARGET_FIELD
from .validators import parse_number, parse_seed

DEFAULT_SETTINGS = dict(
    loss=0, corrupt=0, dup=0, latency=0, jitter=0, down=0, up=0,
    buffer=1000,         # link buffer (ms) for the speed limit; 0 = unbounded. See fields.py
    filter="both", target="", dst_ip="", dst_port="", lan_mode=False,
    block_ip="", block_port="",     # firewall: drop traffic to matching IP/port

    syn_drop=0, max_size=0, spike_prob=0, spike_ms=0,
    nat_timeout=0, rst_prob=0, rst_cooldown=3,
    flap_period=0, flap_down=0, rate_schedule="", seed=-1,
    duration=0,          # session length in seconds, 0 = until stopped (START-time only)
    row_limit=50000,     # most rows a table will show (0 = no limit); see fields.py
)

# Filter-expression fields: a VIEW over the field registry, not a second list.
# (settings key, matcher kind, i18n field label, numeric bounds) - the shape the
# GUI and the CLI have always consumed. New expression fields go into FIELD_DEFS.
MATCH_FIELDS = tuple((f.key, f.expr_kind, f.label, f.bounds)
                     for f in F.expression_fields())


def parse_schedule(text):
    """``'1:100:0, 2:400:128'`` -> ``[(1.0,100,0),(2.0,400,128)]``  (dur:down:up)."""
    steps = []
    for part in str(text or "").split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split(":")
        if len(bits) != 3:
            raise ValueError(translate("errors.bad_schedule_step", None, part=part))
        try:
            dur, dn, up = (float(bits[0]), float(bits[1]), float(bits[2]))
        except ValueError:
            raise ValueError(translate("errors.bad_schedule_step", None, part=part))
        steps.append((dur, dn, up))
    return steps


def setting_expression(key, value):
    """Text form of a filter-expression setting (normalises legacy numbers)."""
    if key in ("dst_port", "block_port"):
        return port_expression(value)
    return str(value or "").strip()


def build_matchers(s):
    """Compile every filter expression in a settings dict.

    Returns ``{settings key: Matcher}``; raises a translated ``ValueError`` on
    the first malformed expression, so the GUI and CLI can report it before the
    engine is touched.
    """
    out = {}
    for key, kind, field, bounds in MATCH_FIELDS:
        value = s.get(key, DEFAULT_SETTINGS[key])
        out[key] = parse_matcher(setting_expression(key, value), kind, field, bounds)
    return out


def validate_ranges(s, lang=None):
    """Check every numeric setting against the bounds declared in the registry.

    Raises a translated ``ValueError`` (``errors.field_range``) on the first
    out-of-range value. Shared by the GUI form and the CLI, so ``--loss 250``
    and a typed-in ``250`` fail the same way instead of being silently clamped
    deep inside ``BeanCore``.
    """
    for f in FIELD_DEFS:
        if f.kind != F.NUMBER or f.key not in s:
            continue
        parse_number(s[f.key], f.label, f.bounds, lang)
    return True


def settings_from_raw(raw, lang=None):
    """Turn a raw (mostly string) input dict into a validated settings dict.

    This is the ONE conversion used by the GUI form, so the widgets never carry
    parsing rules themselves. Raises a translated ``ValueError``.
    """
    s = dict(DEFAULT_SETTINGS)
    for f in FIELD_DEFS:
        if f.key not in raw:
            continue
        value = raw[f.key]
        if f.kind == F.NUMBER:
            s[f.key] = parse_number(value, f.label, f.bounds, lang)
        elif f.kind == F.BOOL:
            s[f.key] = bool(value)
        elif f.kind == F.SEED:
            s[f.key] = parse_seed(value, lang)
        elif f.kind == F.SCHEDULE:
            s[f.key] = str(value or "").strip()
        elif f.kind == F.EXPR:
            s[f.key] = setting_expression(f.key, value)
        else:
            s[f.key] = str(value or "").strip()
    validate_settings(s, lang)
    return s


def validate_settings(s, lang=None):
    """Raise a translated ``ValueError`` if any setting is malformed."""
    build_matchers(s)
    sched = str(s.get("rate_schedule", "") or "").strip()
    if sched:
        parse_schedule(sched)
    validate_ranges(s, lang)
    return True


def apply_targeting(engine, target, log=lambda *_: None, announce=True):
    """Resolve the target-process expression and point the engine at its ports.

    Shared by ``apply_settings`` and the GUI's target refresher so the lookup,
    its logging and its error handling live in exactly one place.

    Returns the live :class:`~beantester.targeting.ProcessTargeting` (iterable,
    ``len()``-able), or ``None`` when targeting is off / could not be resolved.
    The object keeps re-resolving itself while the session runs, so a connection
    the target opens a second from now is impaired too - the old code handed the
    engine a frozen set of ports and everything opened afterwards escaped it.
    """
    matcher = target if hasattr(target, "matches") else None
    if matcher is None:
        expr = str(target or "").strip()
        if not expr:
            engine.set_target(False)
            return None
        try:
            matcher = parse_matcher(expr, KIND_PROCESS, TARGET_FIELD)
        except ValueError as e:
            log(f"{T('log.targeting_error')}: {e}")
            engine.set_target(False)
            return None
    if matcher.is_empty:
        engine.set_target(False)
        return None
    try:
        targeting = engine.target_for(matcher)
    except ImportError:
        log(T("log.targeting_requires_psutil"))
        engine.set_target(False)
        return None
    except Exception as e:                                   # pragma: no cover
        log(f"{T('log.targeting_error')}: {e}")
        return None
    if announce:
        # ONE synchronous resolve, and only on the announcing path - the explicit
        # "the user applied settings" one. It is needed because the log line below
        # reports what was actually matched, and an unresolved target would always
        # read as "matches nothing" - the very message this project made loud on
        # purpose. The periodic path passes announce=False and never blocks:
        # keeping the port set fresh is the resolver thread's job from then on.
        #
        # Outside the try above, and swallowed: a failed resolve must NOT abort the
        # install. Aborting left the engine holding a new targeting object that the
        # core had never been pointed at - two halves disagreeing about what is
        # being impaired. A stale announcement is a far smaller problem, and the
        # resolver corrects it within a tick.
        with crashlog.quiet("settings.targeting"):
            targeting.refresh()
    engine.set_target(True, targeting)
    if announce:
        if targeting.matched:
            log(f"{T('log.targeting')}: {targeting.describe()} "
                f"({len(targeting.pids())} {T('log.processes')}, "
                f"{len(targeting)} {T('log.ports')})")
        else:
            # Loud on purpose: an unmatched target means NOTHING is impaired,
            # and a run in which nothing broke used to look exactly like a run
            # in which everything held up.
            log(T("log.targeting_none"))
    return targeting


def apply_settings(engine, s, log=lambda *_: None):
    """Configure the engine from a flat settings dict (shared by GUI and CLI).

    ``filter`` and ``duration`` are deliberately NOT applied here: both belong to
    the session and are consumed by ``BeanEngine.start()``. Applying them live
    (via "Apply changes" or a scenario step) would either re-open the divert or
    move a deadline the engine is already counting against.
    """
    g = lambda k: s.get(k, DEFAULT_SETTINGS[k])
    engine.set_params(g("loss"), g("corrupt"), g("dup"),
                      g("latency"), g("jitter"), g("down"), g("up"))
    engine.set_buffer(g("buffer"))
    dst_ip = setting_expression("dst_ip", g("dst_ip"))
    dst_port = setting_expression("dst_port", g("dst_port"))
    try:
        engine.set_dest(bool(dst_ip or dst_port), dst_ip, dst_port)
    except ValueError as e:
        # Tolerant like the schedule below: a bad expression disables destination
        # targeting instead of killing a scenario thread. The GUI and the CLI
        # validate up front (validate_settings), so a user never reaches this.
        log(f"{T('log.filter_skipped')}: {e}")
        engine.set_dest(False)
    engine.set_lan(bool(g("lan_mode")))
    block_ip = setting_expression("block_ip", g("block_ip"))
    block_port = setting_expression("block_port", g("block_port"))
    try:
        engine.set_block(bool(block_ip or block_port), block_ip, block_port)
    except ValueError as e:
        # Tolerant like destination above: a bad expression disables blocking
        # instead of killing a scenario thread. GUI and CLI validate up front.
        log(f"{T('log.filter_skipped')}: {e}")
        engine.set_block(False)
    engine.set_advanced(g("syn_drop"), g("max_size"))
    engine.set_spike(g("spike_prob"), g("spike_ms"))
    engine.set_nat(g("nat_timeout"))
    engine.set_rst(g("rst_prob"), g("rst_cooldown"))
    engine.set_flap(g("flap_period") > 0, g("flap_period"), g("flap_down"))
    try:
        engine.set_schedule(parse_schedule(g("rate_schedule")))
    except ValueError as e:
        log(f"{T('log.schedule_skipped')}: {e}")
        engine.set_schedule([])
    apply_targeting(engine, str(g("target")).strip(), log)


def _coerce_setting(key, value):
    """Coerce a config-file value to the type of its default.

    A config file is user input: a string where a number is expected must
    produce a clear, translated error instead of a TypeError deep inside
    ``apply_settings`` (which crashed the CLI with a raw traceback).

    Filter-expression fields are text by design and accept a bare number too
    (older config files stored ``dst_port`` as an int).
    """
    default = DEFAULT_SETTINGS[key]
    if key in {k for k, _, _, _ in MATCH_FIELDS}:
        return setting_expression(key, value)
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, (int, float)):
        try:
            if isinstance(value, bool):
                raise ValueError
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(translate("errors.bad_config_value", None,
                                       field=key, value=repr(value)))
    return str(value)


def load_config_file(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    s = dict(DEFAULT_SETTINGS)
    s.update({k: _coerce_setting(k, v) for k, v in data.items()
              if k in DEFAULT_SETTINGS})
    return s


def save_config_file(path, settings):
    s = dict(DEFAULT_SETTINGS)
    s.update({k: settings[k] for k in DEFAULT_SETTINGS if k in settings})
    error = write_json(path, s)
    if error:
        raise OSError(error)


def non_profile_active(s):
    """i18n labels of active settings a profile will NOT store.

    Derived from ``fields.FIELD_DEFS`` (``in_profile``) instead of the
    hand-written tuple the GUI used to carry - a new field can no longer be
    forgotten here and silently lost on profile save.
    """
    labels = []
    for key, label in F.NON_PROFILE_FIELDS:
        field = FIELDS[key]
        default = DEFAULT_SETTINGS[key]
        value = s.get(key, default)
        if field.kind == F.BOOL:
            active = bool(value) != bool(default)
        elif field.kind == F.NUMBER:
            try:
                active = float(value or 0) != float(default or 0)
            except (TypeError, ValueError):
                active = True
        elif field.kind == F.SEED:
            active = str(value).strip() not in ("", "-1", "None")
        else:
            active = str(value or "").strip() != str(default or "").strip()
        if active and label not in labels:
            labels.append(label)
    return labels
