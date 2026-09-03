"""GUI preferences: app/view settings that live in ``*_ui.json``, not the engine.

Why this is a separate registry from ``fields.FIELD_DEFS``
---------------------------------------------------------
The field registry describes the *traffic scenario*: every entry has an engine
default, a CLI flag, and travels inside a saved config file (a config "describes
the traffic, not the window"). Language, chart history, log length, the
close-confirm switch - these are none of that. They are preferences of the
*application*, they must survive a restart, and they must NOT be dragged into a
traffic config file or a ``--flag``. So they live where geometry, the collapsed
sections and the language already live: ``UiStateStore`` (``*_ui.json``).

This is still one-entry-per-setting, just for a different store: add a ``Pref``
here (plus its i18n keys) and the Settings window renders it, validates it and
persists it. ``App.pref(key)`` reads the live value; ``App.set_pref(key, v)``
writes it. Engine fields that happen to be view-only (``row_limit``,
``ui_only``) stay in ``FIELD_DEFS`` - they are session-scoped and travel with a
config; a Pref is the cross-restart, GUI-only kind.
"""
from typing import Any, NamedTuple, Optional, Tuple

from . import rates

NUMBER = "number"       # validated float/int, inclusive bounds
BOOL = "bool"           # checkbox
ACTION = "action"       # a button that runs App.<Pref.action>()
CHOICE = "choice"       # readonly combobox over Pref.choices


class Pref(NamedTuple):
    key: str                       # ui.json key is "pref.<key>"
    kind: str
    label: str                     # i18n key
    tip: str                       # i18n key (tooltip)
    default: Any = None
    bounds: Optional[Tuple[float, float]] = None
    unit_key: str = ""             # i18n key of the unit shown after a NUMBER
    hint: str = ""                 # i18n key of the greyed hint
    width: int = 8
    action: str = ""               # App method name for kind == ACTION
    # ``(stored value, label shown)`` pairs for kind == CHOICE, in the order the
    # dropdown lists them. The label is a LITERAL, not an i18n key, and that is
    # the same exception ``fields.Field.unit`` already carries: it is here for
    # choices whose labels are SYMBOLS rather than words - "KB/s", "Mbit/s" - which
    # read the same in every language and would otherwise cost three identical
    # translations each, in three files, for ever. A choice whose labels are WORDS
    # does not belong here: give it i18n keys instead, or it will ship English to
    # every reader. Guarded by tests/test_prefs.py.
    choices: Tuple[Tuple[str, str], ...] = ()
    # Id of a ``fields.Section`` that renders this pref through its ``extra``
    # builder, INSTEAD of a preference group. For the rare pref that belongs
    # beside a registry field rather than with the other preferences: "Show only
    # the targeted traffic" has to be read together with "Capture only the
    # targeted traffic", and those two live in different registries (one is a
    # ui.json preference, the other an engine field with a CLI flag - convention
    # 42 keeps them apart on purpose). Splitting them across two cards is what
    # made them look like two spellings of one switch.
    # Declared here rather than in a second list, so "where is this rendered"
    # has exactly one answer. A pref must be in a group OR name a section, never
    # both and never neither - guarded by tests/test_prefs.py.
    section: str = ""


PREFS = (
    # -- view -------------------------------------------------------------- #
    Pref("chart_seconds", NUMBER, "prefs.chart_seconds", "tips.chart_seconds",
         default=120, bounds=(10.0, 3600.0), unit_key="prefs.unit_seconds",
         hint="prefs.chart_seconds_hint", width=8),
    Pref("log_lines", NUMBER, "prefs.log_lines", "tips.log_lines",
         default=500, bounds=(50.0, 100000.0), unit_key="prefs.unit_lines",
         hint="prefs.log_lines_hint", width=10),
    # DISPLAY only, and that is forced rather than chosen: KB/s is what the CLI
    # flags, the config file, the schedule string, the shipped scenarios and the
    # NDJSON `down_kbps`/`up_kbps` fields all carry, and several of those are
    # frozen contracts. So this converts on the way to the screen and never on the
    # way to a file - you still TYPE a limit in KB/s, and the readout beside the
    # field says what that is in the unit you picked.
    #
    # A Pref rather than a registry field, by convention 42: it must survive a
    # restart and must NOT get a CLI flag or ride inside a traffic config, because
    # a config file describes the traffic and not the window looking at it.
    Pref("rate_unit", CHOICE, "prefs.rate_unit", "tips.rate_unit",
         default=rates.DEFAULT_UNIT,
         choices=tuple((key, label) for key, label, _ in rates.RATE_UNITS),
         width=10),
    # Default False = what the tool has always done: every captured packet is
    # counted and listed, and targeting only decides what gets IMPAIRED. Turning
    # it on narrows the VIEW, never the capture and never the impairment - the
    # engine keeps both totals either way, which is also why the machine-readable
    # outputs (NDJSON, the reproduction report) are untouched by this: they carry
    # `seen` AND `scoped_seen` regardless, so a pipeline never has to guess which
    # world a file came from.
    Pref("scope_view_to_target", BOOL, "prefs.scope_view", "tips.scope_view",
         default=False, section="scope"),
    # Default True: the box has always been there, and a preference is allowed to
    # take something away only when the user asks.
    #
    # Worded POSITIVELY on purpose. "Hide the search box" plus an unticked box is
    # a double negative to read, and it would make this the one switch in the
    # window where a tick means less rather than more.
    Pref("show_control_search", BOOL, "prefs.show_control_search",
         "tips.show_control_search", default=True),
    # -- behaviour --------------------------------------------------------- #
    Pref("confirm_close", BOOL, "prefs.confirm_close", "tips.confirm_close",
         default=True),
    Pref("restore_profile", BOOL, "prefs.restore_profile", "tips.restore_profile",
         default=False),
    Pref("reset_layout", ACTION, "prefs.reset_layout", "tips.reset_layout",
         action="reset_ui_layout"),
)

PREFS_BY_KEY = {p.key: p for p in PREFS}

# How the Settings window groups them (each is a card, like a Control section).
# Prefs that name a ``section`` are rendered there instead and must NOT appear
# here - see ``SECTION_PREFS`` below.
PREF_GROUPS = (
    ("prefs.group_view", ("rate_unit", "chart_seconds", "log_lines",
                          "show_control_search")),
    ("prefs.group_behaviour", ("confirm_close", "restore_profile", "reset_layout")),
)


def prefs_in_section(section_id):
    """Prefs rendered inside a registry section's ``extra`` builder, in order."""
    return tuple(p for p in PREFS if p.section == section_id)


def ui_key(key):
    """The UiStateStore key that backs a preference."""
    return f"pref.{key}"


def coerce(pref, raw):
    """Return ``raw`` as the pref's typed value, falling back to its default."""
    if pref.kind == BOOL:
        return bool(raw)
    if pref.kind == NUMBER:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return pref.default
        lo, hi = pref.bounds or (float("-inf"), float("inf"))
        value = min(max(value, lo), hi)
        return int(value) if float(value).is_integer() else value
    if pref.kind == CHOICE:
        # A value this build does not offer falls back to the default rather than
        # being kept: ui.json survives downgrades and hand-editing, and a stored
        # value nothing can render would leave the dropdown showing a blank while
        # every reader of the preference got a string it has no branch for.
        return raw if raw in {value for value, _ in pref.choices} else pref.default
    return raw
