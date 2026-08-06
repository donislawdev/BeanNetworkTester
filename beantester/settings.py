"""Shared settings model + JSON config file (used by both the GUI and the CLI).

The shape of a setting (type, label, bounds, section, profile scope) lives in
``fields.FIELD_DEFS`` - this module only turns raw user input into a validated
settings dict and applies it to an engine.
"""
import difflib
import json
import socket

from . import crashlog
from . import fields as F
from . import portmap
from .jsonfile import write_json
from .fields import FIELD_DEFS, FIELDS
from .i18n import T, translate
from .matchers import KIND_PROCESS, parse_matcher, port_expression
from .processes import TARGET_FIELD
from .targeting import ports_shared_with_others
from .utils import number_string
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
    narrow_filter=False, # fold the destination into the DRIVER's filter (START-time only)
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


def armed_global_impairments(s):
    """Keys of impairments that are ON and damage every captured packet.

    Registry-derived (``fields.GLOBALLY_IMPAIRING_KEYS``), so an impairment added
    later is covered by declaring it once, in the table where it is defined.
    """
    return tuple(key for key in F.GLOBALLY_IMPAIRING_KEYS
                 if F.is_active(FIELDS[key], s.get(key, DEFAULT_SETTINGS[key])))


def targeting_is_set(s):
    """True when a targeting field names at least one thing to hit.

    Not a truth test on the fields, and not a truth test on the POSITIVE terms
    either - both readings have been wrong here, in opposite directions:

    * an expression made of nothing but exclusions (``!chrome.exe``) is non-empty
      and still covers the whole machine minus one application;
    * an expression whose positive term covers everything (``*``, ``re:.*``,
      ``>0``) reads as narrow to any truth test and bounds nothing. MEASURED:
      ``--target *`` silenced this warning while ``--loss 100`` alone raised it,
      so the expression that bounded nothing looked safer than no expression.

    ``Matcher.bounds_nothing`` answers both halves, and it is deliberately the
    only thing asked here - reaching for either half alone is how the second case
    got through.

    A malformed expression is treated as no scope at all - it is about to be
    rejected by validation anyway, and the safe reading of "I cannot tell what
    this narrows to" is "it narrows nothing".
    """
    expressions = {key: (kind, field, bounds)
                   for key, kind, field, bounds in MATCH_FIELDS}
    for key in F.NARROWING_KEYS:
        value = s.get(key, DEFAULT_SETTINGS[key])
        if key not in expressions:
            # a narrowing field that is not an expression (none today): its plain
            # on/off reading is the best answer available, and it is still an answer
            if F.is_active(FIELDS[key], value):
                return True
            continue
        text = setting_expression(key, value)
        if not text:
            continue
        try:
            matcher = parse_matcher(text, *expressions[key])
        except ValueError:
            continue
        if not matcher.bounds_nothing:
            return True
    return False


def unbounded_impairment(s):
    """True when a run would damage all traffic, with nothing to bound it.

    The condition behind the start-time warning: something is armed that hits
    every packet, no targeting field says WHERE, and no duration says WHEN it
    ends. Blocking is deliberately not enough to clear it - a block bounds its
    own damage and nothing else, so ``--loss 50 --block-ip 10.0.0.1`` is still a
    machine-wide loss run.

    Total by construction: it reads through ``DEFAULT_SETTINGS`` for missing keys
    (an older config file), and ``fields.is_active`` never raises on a value that
    has not been validated yet. A warning that could abort a start would be worse
    than the mode it warns about.
    """
    if not armed_global_impairments(s):
        return False
    if targeting_is_set(s):
        return False
    try:
        duration = float(s.get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return duration <= 0


def warn_if_unbounded(s, log):
    """Say the start-time warning through ``log``, if the run has earned it.

    Both interfaces call this rather than each testing the condition and picking
    their own words: one sentence, one condition, so the window and the command
    line cannot drift into telling the user different things about the same run.
    """
    if unbounded_impairment(s):
        log(T("warn.global_impairment"))


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


def range_errors(s, lang=None):
    """EVERY out-of-range value, as a list of messages. Empty when all are fine.

    The same question as :func:`validate_ranges` asked for the other kind of
    channel, and the difference is not a preference:

    * a form is typed into LIVE, so it reports the field under the cursor and
      nothing else - a list of complaints about fields the user has not reached
      yet is noise;
    * a command line arrives FINISHED. Reporting one problem per run means the
      user fixes it, runs again, and learns about the next one - which is the
      cheapest way to make somebody give up on a tool.

    ``validate_ranges`` keeps raising on the first, unchanged, because that is
    what the form wants and what its callers already expect.
    """
    found = []
    for f in FIELD_DEFS:
        if f.kind != F.NUMBER or f.key not in s:
            continue
        try:
            parse_number(s[f.key], f.label, f.bounds, lang)
        except ValueError as exc:
            found.append(str(exc))
    return found


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


# A port several programs hold at once is almost always a DISCOVERY protocol, and a
# bare number tells a tester nothing: "5353" reads as a fault, "5353 (mDNS)" reads as
# the ordinary state it is. Not hypothetical - that is exactly how this warning was
# read when it fired (2026-08-01).
#
# The name comes from the MACHINE'S OWN services file through socket.getservbyport,
# not from a table invented here, so it cannot drift from what the OS believes. The
# overlay covers only what that file leaves unhelpful, CHECKED on this machine:
# 5353 is absent from it altogether (the lookup raises - mDNS is IANA / RFC 6762),
# and DHCP is registered under its historical BOOTP names ("bootps" / "bootpc").
_PORT_LABELS = {5353: "mDNS", 67: "DHCP", 68: "DHCP"}


def describe_port(port):
    """``"5353 (mDNS)"`` when the port names a known service, ``"49664"`` when not."""
    try:
        number = int(port)
    except (TypeError, ValueError):
        return str(port)
    label = _PORT_LABELS.get(number)
    if label is None:
        for protocol in ("udp", "tcp"):
            try:
                # Upper-cased because a services file is lower-case by convention
                # ("ssdp", "llmnr") and these are protocol acronyms - left alone they
                # read as a typo next to the overlay's canonical "mDNS".
                label = socket.getservbyport(number, protocol).upper()
                break
            except (OSError, OverflowError, ValueError):
                continue
    return f"{number} ({label})" if label else str(number)


def _warn_about_shared_ports(targeting, log):
    """Say so when the target holds a port other programs hold at the same time.

    The tool decides what to impair from the LOCAL PORT, and the operating
    system's socket table lets several processes own one (``SO_REUSEADDR``: mDNS,
    SSDP, DHCP). On those ports the answer is a coin toss - measured, targeting
    Spotify left its own port 5353 out of scope while targeting msedge pulled
    svchost, Spotify and adb in. Nothing here can fix that; what it can do is stop
    the tool from reporting a clean result over it.

    Two things this used to get wrong, both reported from a real session:

    * **it called the target's own program an "other process".** The subtraction in
      ``ports_shared_with_others`` is by PID, and ``ProcessTargeting`` only ever sees
      PIDs that WON a port in the collapsed map (``targeting.py:117``), so a second
      process of the same program that lost every collapse survives it and prints
      under the target's own name. Measured: targeting ``msedge`` matched pid 55120
      while pid 47664 - also ``msedge.exe`` - came back as somebody else. Those are
      now marked inline rather than silently listed among strangers.
    * **it offered both outcomes when it knew which one applied.** "may break theirs
      as well, or miss the target's" are not equally likely on a given port: if the
      port's collapse WINNER is in the target set the port is in scope and everyone
      on it gets impaired, and if it is not, the target's traffic there is skipped.
      One line each, and the tool says which.

    Said ONCE, on the announcing path (an explicit "apply"), never per resolver
    tick. Best-effort throughout: a diagnostic that raised would break the very
    thing it is describing.
    """
    with crashlog.quiet("settings.shared_ports"):
        # The POLLING table, whatever targeting itself resolves against: the
        # question is about the OS socket table, not about how we learned a port.
        table = portmap.default_table()
        table.refresh_if_stale()
        targeted = targeting.pids()
        shared = ports_shared_with_others(targeted, table)
        if not shared:
            return
        # One read of the winners, so a rebuild between the two calls cannot pair a
        # port with an owner from a different walk.
        winners = table.snapshot()
        own_programs = {str(name).lower() for name in targeting.names()}
        said = False
        for port in sorted(shared):
            winner = winners.get(port)
            if winner is None:
                # The map moved under us and this port is gone from it. A stale
                # diagnostic is worse than none, so say nothing about this one.
                continue
            who = set()
            for pid in shared[port]:
                name = table.name_of(pid) or str(pid)
                if name.lower() in own_programs:
                    name = f"{name} ({T('log.shared_port_same_app')})"
                who.add(name)
            in_scope = winner in targeted
            log(T("log.shared_port_hits" if in_scope else "log.shared_port_misses",
                  port=describe_port(port), who=", ".join(sorted(who)),
                  winner=table.name_of(winner) or str(winner)))
            said = True
        if said:
            log(T("log.shared_port_footer"))


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
            _warn_about_shared_ports(targeting, log)
        else:
            # Loud on purpose: an unmatched target means NOTHING is impaired,
            # and a run in which nothing broke used to look exactly like a run
            # in which everything held up.
            log(T("log.targeting_none"))
    return targeting


def _destination_is_frozen(engine, dst_ip, dst_port):
    """Is this a MID-SESSION destination change against a narrowed driver filter?

    Only then - and only when the value actually differs from what the engine is
    running with. Re-applying the SAME destination is what every "Apply changes"
    does, and refusing that would spam the log and block unrelated edits.

    ``getattr`` throughout because ``apply_settings`` is handed engine doubles in
    the tests and by ``ScenarioRunner``; an object without these attributes simply
    is not running a narrowed capture.
    """
    if not getattr(engine, "is_running", lambda: False)():
        return False
    info = getattr(engine, "session_info", None)
    if not callable(info) or not info().get("narrowed"):
        return False
    core = getattr(engine, "core", None)
    if core is None:                                        # pragma: no cover
        return False
    return (str(getattr(core, "dst_ip", "")) != str(dst_ip)
            or str(getattr(core, "dst_port", "")) != str(dst_port))


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
    # With the driver filter narrowed, the destination fields are START-ONLY, and
    # this is the one place that can enforce it. The handle's filter is fixed when
    # it opens, so accepting a new destination here would leave the DRIVER holding
    # the old, narrower filter while decide() judged by the new one: traffic the
    # user just asked to impair would never arrive, and every counter would read
    # healthy. Refusing out loud is the only honest option - silently applying half
    # of it is the failure mode this whole audit exists to remove.
    if _destination_is_frozen(engine, dst_ip, dst_port):
        log(T("log.dest_frozen_while_narrowed"))
    else:
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


def _expected_shape(key, lang=None):
    """Plain-language description of what a numeric setting accepts.

    Read from the registry, so a field whose bounds change says the new ones
    without anybody remembering this message exists.

    Under ``fields.`` and not ``errors.`` on purpose: these are sentence
    FRAGMENTS, pasted into a message that supplies the capital letter and the
    full stop. Keeping them out of the ``errors.`` namespace is what lets
    ``test_every_error_reads_like_a_sentence`` run without an exception list.
    """
    field = FIELDS.get(key)
    bounds = field.bounds if field is not None else None
    if not bounds:
        return translate("fields.expects_number", lang)
    return translate("fields.expects_number_range", lang,
                     min=number_string(bounds[0]), max=number_string(bounds[1]))


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
            # Say what the setting DOES take, not just that this is not it. The
            # registry already knows - the form has been telling people "must be
            # between 0 and 100" for as long as it has existed, while the config
            # loader said only "invalid" for the very same value.
            raise ValueError(translate("errors.bad_config_value", None,
                                       field=key, value=repr(value),
                                       expected=_expected_shape(key)))
    return str(value)


def load_config_file(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        # Valid JSON of the wrong shape. Without this check the next statement
        # reaches ``data.items()`` and raises AttributeError - and the CLI catches
        # ValueError and OSError, so the user got a raw Python traceback and exit
        # RUNTIME(1) where the contract says CONFIG(3), against a comment in
        # ``cli.py`` promising "a clear CLI error, never a raw traceback".
        # A settings file that is a JSON ARRAY is not exotic: it is what anything
        # writing one-entry-per-line produces.
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    # A name this build does not know used to be dropped in silence, which is the
    # worst of the three possible answers: `{"loss": 10, "latancy": 300}` loaded
    # clean, --dry-run called the file valid, and the run went out with latency 0.
    # Nothing anywhere said so. ``scenario.py`` closed exactly this hole for its
    # own keys; this is the same rule one file over, and this is the file people
    # hand-write (the README has a recipe for validating them in a pipeline).
    #
    # The cost, stated plainly because it is real: a file from a NEWER build that
    # carries a setting this one lacks now fails instead of loading the part it
    # understands. That trade goes the other way for ``ui.json``, where unknown
    # keys are kept on purpose - but that file is written by the program and read
    # key by key, so a typo cannot happen and forward compatibility is the only
    # thing at stake. Here a typo is the common case. Anything this tool wrote
    # loads either way: ``save_config_file`` emits exactly the known key set.
    unknown = [k for k in data if k not in DEFAULT_SETTINGS]
    if unknown:
        close = difflib.get_close_matches(unknown[0], DEFAULT_SETTINGS, n=1)
        if len(unknown) == 1 and close:
            raise ValueError(translate("errors.config_unknown_setting_hint", None,
                                       field=unknown[0], suggestion=close[0]))
        raise ValueError(translate("errors.config_unknown_setting", None,
                                   field=", ".join(sorted(unknown))))
    s = dict(DEFAULT_SETTINGS)
    s.update({k: _coerce_setting(k, v) for k, v in data.items()})
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
