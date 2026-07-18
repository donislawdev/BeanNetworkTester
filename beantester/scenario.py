"""Timeline scenarios: change settings live while a session runs.

The file is USER input (and often a file someone else wrote), so it is
validated the same way the settings form is: a JSON that is not a scenario must
say so. It used to be accepted silently - any random ``.json`` loaded as a
scenario with **zero steps**, which then ran a session that did nothing while
the UI happily reported "scenario loaded".
"""
import json

from .i18n import translate
from .settings import DEFAULT_SETTINGS

ACTIONS = ("reset_tcp", "reset_now")      # "reset_now" = the pre-1.3 spelling
MAX_STEPS = 1000


def _err(key, **fmt):
    return ValueError(translate(key, None, **fmt))


def _validate_step(index, step):
    """Return a normalised step, or raise a translated ``ValueError``."""
    where = index + 1
    if not isinstance(step, dict):
        raise _err("errors.scenario_step_type", step=where)
    if "at" not in step:
        raise _err("errors.scenario_step_at", step=where)
    try:
        at = float(step["at"])
    except (TypeError, ValueError):
        raise _err("errors.scenario_step_at", step=where)
    if at < 0:
        raise _err("errors.scenario_step_at", step=where)

    settings = step.get("settings")
    if settings is not None:
        if not isinstance(settings, dict):
            raise _err("errors.scenario_step_settings", step=where)
        unknown = [k for k in settings if k not in DEFAULT_SETTINGS]
        if unknown:
            raise _err("errors.scenario_unknown_setting", step=where,
                       field=", ".join(sorted(unknown)))

    action = step.get("action")
    if action is not None and str(action) not in ACTIONS:
        raise _err("errors.scenario_unknown_action", step=where, action=action)

    if settings is None and action is None:
        raise _err("errors.scenario_step_empty", step=where)

    out = dict(step)
    out["at"] = at
    return out


class Scenario:
    """A sequence of events on a timeline.

    Step: ``{"at": seconds, "settings": {partial settings},
    "action": "reset_tcp", "duration": s}``. Settings are cumulative:
    each step patches the state from previous steps.
    """

    def __init__(self, steps, loop=False):
        self.steps = sorted(steps, key=lambda s: float(s.get("at", 0)))
        self.loop = bool(loop)
        self.duration = max((float(s.get("at", 0)) for s in self.steps), default=0.0)

    def settings_at(self, t, base=None):
        s = dict(base or DEFAULT_SETTINGS)
        for step in self.steps:
            if float(step.get("at", 0)) <= t and "settings" in step:
                s.update(step["settings"])
        return s

    def events_between(self, t0, t1):
        """One-shot actions within ``(t0, t1]``."""
        out = []
        for step in self.steps:
            at = float(step.get("at", 0))
            if "action" in step and t0 < at <= t1:
                out.append((at, step))
        return out


def parse_scenario(data):
    """Validate raw JSON data and build a :class:`Scenario`.

    Accepts a bare list of steps or ``{"steps": [...], "loop": bool}``.
    Raises a translated ``ValueError`` on anything else.
    """
    if isinstance(data, list):
        raw, loop = data, False
    elif isinstance(data, dict):
        if "steps" not in data:
            raise _err("errors.scenario_no_steps")
        raw, loop = data.get("steps"), bool(data.get("loop", False))
    else:
        raise _err("errors.scenario_not_a_scenario")
    if not isinstance(raw, list):
        raise _err("errors.scenario_no_steps")
    if not raw:
        raise _err("errors.scenario_empty")
    if len(raw) > MAX_STEPS:
        raise _err("errors.scenario_too_many", limit=MAX_STEPS)
    return Scenario([_validate_step(i, step) for i, step in enumerate(raw)], loop=loop)


def load_scenario_file(path):
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except ValueError as e:
            raise _err("errors.scenario_bad_json", error=e)
    return parse_scenario(data)
