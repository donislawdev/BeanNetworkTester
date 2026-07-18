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

NUMBER = "number"       # validated float/int, inclusive bounds
BOOL = "bool"           # checkbox
ACTION = "action"       # a button that runs App.<Pref.action>()


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


PREFS = (
    # -- view -------------------------------------------------------------- #
    Pref("chart_seconds", NUMBER, "prefs.chart_seconds", "tips.chart_seconds",
         default=120, bounds=(10.0, 3600.0), unit_key="prefs.unit_seconds",
         hint="prefs.chart_seconds_hint", width=8),
    Pref("log_lines", NUMBER, "prefs.log_lines", "tips.log_lines",
         default=500, bounds=(50.0, 100000.0), unit_key="prefs.unit_lines",
         hint="prefs.log_lines_hint", width=10),
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
PREF_GROUPS = (
    ("prefs.group_view", ("chart_seconds", "log_lines")),
    ("prefs.group_behaviour", ("confirm_close", "restore_profile", "reset_layout")),
)


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
    return raw
