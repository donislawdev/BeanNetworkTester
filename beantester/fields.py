"""Field registry - THE single source of truth for every settings field.

Adding a setting means adding ONE entry here (plus its i18n keys and, for now,
its argparse flag). Everything else is derived:

  * the Control page form (widgets, labels, units, live validation)  - ``gui/form.py``
  * reading/writing the widgets                                      - ``gui.App``
  * type coercion and range validation                               - ``settings.validate``
  * which fields a profile stores / warns about                      - ``PROFILE_FIELDS``
  * the filter-expression registry (``settings.MATCH_FIELDS``)       - view over this table

``SECTIONS`` describes how the fields are grouped on the Control page; the page
is a renderer of this table, not a hand-written form.

Layering: this module depends only on ``matchers`` (expression kinds) and
``processes`` (the target field's i18n key) - no tkinter, no i18n lookups at
import time.
"""
from typing import NamedTuple, Optional, Tuple

from .matchers import KIND_INT, KIND_IP, KIND_PROCESS, PORT_BOUNDS
from .processes import TARGET_FIELD

# -- field kinds ----------------------------------------------------------- #
NUMBER = "number"        # float, optional inclusive bounds
BOOL = "bool"            # checkbox
EXPR = "expr"            # filter expression (matchers.py)
CHOICE = "choice"        # combobox (traffic filter)
SCHEDULE = "schedule"    # "dur:down:up, ..." (settings.parse_schedule)
SEED = "seed"            # int, empty == -1 == "random"

PCT = (0.0, 100.0)
MS = (0.0, 600000.0)
RATE = (0.0, 10000000.0)          # KB/s, 0 = unlimited
SECONDS = (0.0, 86400.0)


class Field(NamedTuple):
    """One setting: how it is typed, validated, labelled and rendered."""
    key: str                       # settings key (== DEFAULT_SETTINGS key)
    kind: str
    label: str                     # i18n key of the field label
    section: str                   # SECTIONS id it belongs to
    unit: str = ""                 # literal unit shown after the entry ("ms", "%")
    unit_key: str = ""             # i18n key of the unit, when it needs translating
    bounds: Optional[Tuple[float, float]] = None
    expr_kind: str = ""            # KIND_* for kind == EXPR
    width: int = 8                 # entry width in characters
    tip: str = ""                  # i18n key of the tooltip
    hint: str = ""                 # i18n key of the greyed hint next to the entry
    in_profile: bool = False       # stored by a user profile / built-in preset
    span: bool = False             # takes a whole row in the section grid
    cli: str = ""                  # argparse flag (without "--")
    overridden_by: str = ""        # key of a field that makes this one inert
    override_note: str = ""        # i18n key explaining the override, shown in the form
    start_only: bool = False       # consumed by BeanEngine.start(): locked mid-session
    ui_only: bool = False          # the ENGINE never sees it: a view setting, applied live
    help_title: str = ""           # i18n key of the "?" help-sheet title (optional)
    help_body: str = ""            # i18n key of the "?" help-sheet body (optional)


FIELD_DEFS = (
    # -- traffic ----------------------------------------------------------- #
    Field("filter", CHOICE, "frames.traffic", "traffic",
          tip="tips.filter", span=True, cli="filter", start_only=True),
    Field("lan_mode", BOOL, "fields.lan_mode", "traffic",
          tip="tips.lan_mode", span=True, cli="lan-mode"),

    # -- target process ---------------------------------------------------- #
    Field("target", EXPR, TARGET_FIELD, "target_process", expr_kind=KIND_PROCESS,
          width=34, tip="tips.target_process", hint="fields.target_example",
          span=True, cli="target"),

    # -- speed limit ------------------------------------------------------- #
    # A throughput schedule REPLACES the constant limits (BeanCore._current_rates
    # takes its rates from the schedule steps). That was documented but invisible:
    # the two fields sat there looking live while the engine ignored them.
    Field("down", NUMBER, "fields.download", "speed_limit", unit="KB/s",
          bounds=RATE, tip="tips.down_limit", in_profile=True, cli="down",
          overridden_by="rate_schedule", override_note="fields.schedule_overrides"),
    Field("up", NUMBER, "fields.upload", "speed_limit", unit="KB/s",
          bounds=RATE, tip="tips.up_limit", in_profile=True, cli="up",
          overridden_by="rate_schedule", override_note="fields.schedule_overrides"),
    # The link buffer for the speed limit: how much queueing delay a rate-limited
    # link may build up before it drops (bufferbloat), in ms. 0 = unbounded. NOT
    # in_profile (like the other advanced impairments): only the seven classic
    # preset fields are stored in a profile. It applies to the constant limits AND
    # to a schedule, so it is NOT overridden_by the schedule.
    Field("buffer", NUMBER, "fields.buffer", "speed_limit", unit="ms",
          bounds=MS, width=8, tip="tips.buffer", hint="fields.buffer_hint",
          span=True, cli="buffer",
          help_title="dialogs.buffer_help_title", help_body="dialogs.buffer_help"),

    # -- latency ----------------------------------------------------------- #
    Field("latency", NUMBER, "fields.latency", "latency", unit="ms",
          bounds=MS, tip="tips.latency", in_profile=True, cli="latency"),
    Field("jitter", NUMBER, "fields.jitter", "latency", unit="ms",
          bounds=MS, tip="tips.jitter", in_profile=True, cli="jitter"),

    # -- impairments ------------------------------------------------------- #
    Field("loss", NUMBER, "fields.loss", "impairments", unit="%",
          bounds=PCT, width=6, tip="tips.loss", in_profile=True, cli="loss"),
    Field("corrupt", NUMBER, "fields.corruption", "impairments", unit="%",
          bounds=PCT, width=6, tip="tips.corrupt", in_profile=True, cli="corrupt"),
    Field("dup", NUMBER, "fields.duplication", "impairments", unit="%",
          bounds=PCT, width=6, tip="tips.dup", in_profile=True, cli="dup"),

    # -- flapping ---------------------------------------------------------- #
    Field("flap_period", NUMBER, "fields.period", "flapping", unit="s",
          bounds=SECONDS, width=6, tip="tips.flap", cli="flap-period"),
    Field("flap_down", NUMBER, "fields.flap_down_pct", "flapping", unit="%",
          bounds=PCT, width=6, tip="tips.flap", cli="flap-down"),

    # -- destination ------------------------------------------------------- #
    Field("dst_ip", EXPR, "fields.ip", "destination", expr_kind=KIND_IP,
          width=26, tip="tips.dest", span=True, cli="dst-ip"),
    Field("dst_port", EXPR, "fields.port", "destination", expr_kind=KIND_INT,
          bounds=PORT_BOUNDS, width=18, tip="tips.dest", span=True, cli="dst-port"),

    # -- blocking (firewall) ---------------------------------------------- #
    # Drop traffic to matching destinations outright. IP OR port (each takes part
    # only when non-empty), applied after the targeting gate - see BeanCore.decide
    # step 2c. Same expression fields as destination targeting; distinct because
    # this DROPS rather than merely scoping what gets impaired.
    Field("block_ip", EXPR, "fields.ip", "block", expr_kind=KIND_IP,
          width=26, tip="tips.block", span=True, cli="block-ip"),
    Field("block_port", EXPR, "fields.port", "block", expr_kind=KIND_INT,
          bounds=PORT_BOUNDS, width=18, tip="tips.block", span=True, cli="block-port"),

    # -- advanced ---------------------------------------------------------- #
    Field("syn_drop", NUMBER, "fields.syn_drop", "advanced", unit="%",
          bounds=PCT, width=6, tip="tips.syn", cli="syn-drop"),
    Field("max_size", NUMBER, "fields.max_size", "advanced",
          unit_key="fields.unit_b_off", bounds=(0.0, 65535.0), width=8,
          tip="tips.mtu", cli="max-size"),
    Field("spike_prob", NUMBER, "fields.spike_prob", "advanced", unit="%",
          bounds=PCT, width=6, tip="tips.spike", cli="spike-prob"),
    Field("spike_ms", NUMBER, "fields.spike_ms", "advanced", unit="ms",
          bounds=MS, width=8, tip="tips.spike", cli="spike-ms"),
    Field("nat_timeout", NUMBER, "fields.nat_timeout", "advanced",
          unit_key="fields.unit_s_off", bounds=SECONDS, width=6,
          tip="tips.nat", cli="nat-timeout"),
    Field("rst_prob", NUMBER, "fields.rst", "advanced", unit="%",
          bounds=PCT, width=6, tip="tips.rst", cli="rst-prob"),
    Field("rst_cooldown", NUMBER, "fields.rst_cooldown", "advanced", unit="s",
          bounds=(0.0, 3600.0), width=6, tip="tips.rst_cooldown", cli="rst-cooldown"),

    # -- schedule ---------------------------------------------------------- #
    Field("rate_schedule", SCHEDULE, "fields.schedule", "schedule", width=34,
          tip="tips.schedule", span=True, cli="rate-schedule"),

    # -- session ----------------------------------------------------------- #
    # Applied at START only, exactly like "filter" - so, exactly like "filter",
    # the widget is LOCKED while a session runs. Editing a deadline the engine is
    # already counting against does nothing, and a field that quietly does nothing
    # is worse than a disabled one.
    Field("duration", NUMBER, "fields.duration", "session", unit="s",
          bounds=SECONDS, width=8, tip="tips.duration", hint="fields.duration_hint",
          span=True, cli="duration", start_only=True),

    # -- tables ------------------------------------------------------------ #
    # How many rows a table will show at most. The tables are virtualised (only
    # the visible slice is rendered), so this is NOT a rendering budget any more -
    # it is a guard on the pure-Python filter+sort that still runs over the whole
    # model. 0 = no limit. It used to be a hard-coded 400, which quietly turned
    # "here are your connections" into "here are 400 of your connections".
    #
    # ui_only: this one never reaches the engine (apply_settings does not read it)
    # and the tables re-read it on every refresh, so typing a new value ALREADY
    # applied it. Leaving it in the dirty signature lit up "Apply changes" and
    # promised to apply something that was applied a keystroke ago - a button that
    # lies about the state of the session is worse than no button. It is an
    # exception, but a DECLARED one: when the settings window arrives, it takes
    # every field marked ui_only and nothing else has to change.
    Field("row_limit", NUMBER, "fields.row_limit", "tables",
          unit_key="fields.unit_rows_off", bounds=(0.0, 1000000.0), width=10,
          tip="tips.row_limit", hint="fields.row_limit_hint", span=True,
          cli="row-limit", ui_only=True),

    # -- reproduction ------------------------------------------------------ #
    Field("seed", SEED, "fields.seed", "repro", width=12, tip="tips.seed",
          hint="fields.seed_hint", cli="seed"),
)

FIELDS = {f.key: f for f in FIELD_DEFS}


class Section(NamedTuple):
    """A group of fields on a form surface (one collapsible panel)."""
    id: str
    label: str                      # i18n key of the panel title
    fields: Tuple[str, ...] = ()
    toggle: str = ""                # i18n key of the "enable" checkbox ("" = none)
    columns: int = 2
    extra: str = ""                 # id of a page-specific extra-widget builder
    # Which surface renders this section. "control" = the Control page; "settings"
    # = the Settings window. The registry stays the single source of truth: a new
    # settings field is one entry marked surface="settings", and it renders itself
    # there (widget, label, unit, live validation) exactly like a Control field.
    surface: str = "control"


SECTIONS = (
    # Profiles sit at the TOP on purpose: "pick a preset -> START" is the first
    # thing a new user does (it is the on-ramp the README leads with), so the
    # preset picker must be the first thing they see - not the last section after
    # a dozen panels of NAT/MTU/RST jargon.
    Section("profiles", "frames.profiles", (), columns=1, extra="profiles"),
    Section("traffic", "frames.traffic", ("filter", "lan_mode"), columns=1),
    # No "enable" checkbox: an empty target already means "all traffic", so the
    # checkbox was a switch that did nothing but take a click (same for the two
    # sections below).
    Section("target_process", "frames.target_process", ("target",),
            columns=1, extra="target"),
    Section("speed_limit", "frames.speed_limit", ("down", "up", "buffer"), columns=2),
    Section("latency", "frames.latency", ("latency", "jitter"), columns=2),
    Section("impairments", "frames.impairments", ("loss", "corrupt", "dup"), columns=3),
    Section("flapping", "frames.flapping", ("flap_period", "flap_down"), columns=2),
    Section("destination", "frames.destination", ("dst_ip", "dst_port"), columns=1),
    Section("block", "frames.block", ("block_ip", "block_port"), columns=1),
    Section("advanced", "frames.advanced",
            ("syn_drop", "max_size", "spike_prob", "spike_ms",
             "nat_timeout", "rst_prob", "rst_cooldown"),
            columns=2, extra="advanced"),
    Section("schedule", "frames.schedule", ("rate_schedule",), columns=1),
    Section("session", "frames.session", ("duration",), columns=1),
    # Table row limit lives in the Settings window, not on the Control page: it is
    # a view preference (ui_only, applied live), not part of the traffic scenario.
    Section("tables", "frames.tables", ("row_limit",), columns=1, surface="settings"),
    Section("repro", "frames.repro", ("seed",), columns=1, extra="repro"),
)

# Sections split by surface. The Control page and the Settings window are both
# renderers of this one table (see gui/form.py::ControlForm(sections=...)).
CONTROL_SECTIONS = tuple(s for s in SECTIONS if s.surface == "control")
SETTINGS_SECTIONS = tuple(s for s in SECTIONS if s.surface == "settings")


# -- derived views (never hand-maintain these lists) ------------------------ #
def fields_of_kind(kind):
    return tuple(f for f in FIELD_DEFS if f.kind == kind)


def expression_fields():
    """Filter-expression fields, in registry order (drives MATCH_FIELDS)."""
    return fields_of_kind(EXPR)


PROFILE_FIELDS = tuple(f.key for f in FIELD_DEFS if f.in_profile)
# View settings the engine never receives (see Field.ui_only). They are applied the
# moment they are typed, so they must not make the form look "unapplied".
UI_ONLY_KEYS = frozenset(f.key for f in FIELD_DEFS if f.ui_only)
NON_PROFILE_FIELDS = tuple((f.key, f.label) for f in FIELD_DEFS if not f.in_profile)


def overriding_field(field):
    """The field that makes ``field`` inert, or None."""
    return FIELDS.get(field.overridden_by) if field.overridden_by else None


def off_value(field):
    """Value a field takes when its section's 'enable' toggle is unchecked."""
    if field.kind in (EXPR, SCHEDULE):
        return ""
    if field.kind == BOOL:
        return False
    return 0


def is_active(field, value):
    """True when the field carries a meaningful (non-off) value."""
    if field.kind in (EXPR, SCHEDULE, CHOICE):
        return bool(str(value or "").strip())
    if field.kind == BOOL:
        return bool(value)
    if field.kind == SEED:
        return str(value).strip() not in ("", "-1", "None")
    try:
        return float(value or 0) != 0.0
    except (TypeError, ValueError):
        return bool(str(value).strip())
