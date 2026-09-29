"""Timeline scenarios: change settings live while a session runs.

The file is USER input (and often a file someone else wrote), so it is
validated the same way the settings form is: a JSON that is not a scenario must
say so. It used to be accepted silently - any random ``.json`` loaded as a
scenario with **zero steps**, which then ran a session that did nothing while
the UI happily reported "scenario loaded".
"""
import difflib
import os

from .fields import RESET_S
from .i18n import translate
from .jsonfile import load_json
from .paths import shipped_scenario
from .settings import DEFAULT_SETTINGS, NOT_APPLIED_LIVE, validated_patch
from .validators import parse_bool, parse_number

# The actions a step may carry. ``scenario_runner`` reads THIS tuple rather than
# listing them again - it used to carry its own copy, which would have accepted a
# name the validator here rejects.
ACTIONS = ("reset_tcp",)
MAX_STEPS = 1000

# Everything a step and a file may contain. Anything else is a typo, and a typo
# here is SILENT: a misspelled "duraton" left the reset running for the default
# 3 s, a misspelled "lop" turned looping off, and both looked like the tool
# ignoring the file. Unknown SETTINGS names have been a hard error since this
# module was written - these are the same rule, one level up.
STEP_KEYS = ("at", "settings", "action", "duration")
FILE_KEYS = ("steps", "loop")

# How long an action may hold the connections down (owner decision D-26): the
# bound of the "RST cooldown" field, the other number that says how long a reset
# lasts. Any length used to be accepted, and a reset still running when a session
# ended carried into the next one (external review P3-3).
MAX_ACTION_S = RESET_S[1]


def _err(key, **fmt):
    return ValueError(translate(key, None, **fmt))


def _validate_step(index, step, warnings):
    """Return a normalised step, or raise a translated ``ValueError``.

    ``warnings`` collects what loads but will not do what it says.
    """
    where = index + 1
    if not isinstance(step, dict):
        raise _err("errors.scenario_step_type", step=where)
    if "at" not in step:
        raise _err("errors.scenario_step_at", step=where)
    try:
        # parse_number, not float(): it is the one place that refuses NaN and
        # Infinity, and "at" was the last number in the program that skipped it.
        # `float("Infinity")` passed the `>= 0` test below, so the step validated
        # cleanly and then never fired - a scenario that looked right and quietly
        # did not do what it said.
        at = parse_number(step["at"], bounds=(0, None))
    except ValueError as exc:
        raise _err("errors.scenario_step_at", step=where) from exc

    settings = step.get("settings")
    if settings is not None:
        if not isinstance(settings, dict):
            raise _err("errors.scenario_step_settings", step=where)
        unknown = [k for k in settings if k not in DEFAULT_SETTINGS]
        if unknown:
            # The same help the config loader has given since it learned to
            # (settings.load_config_file): one misspelling gets the correction it
            # was probably reaching for. It is the same class of mistake made in
            # the same kind of file, and answering it two different ways was an
            # accident of which loader was written first.
            close = difflib.get_close_matches(unknown[0], DEFAULT_SETTINGS, n=1)
            if len(unknown) == 1 and close:
                raise _err("errors.scenario_unknown_setting_hint", step=where,
                           field=unknown[0], suggestion=close[0])
            raise _err("errors.scenario_unknown_setting", step=where,
                       field=", ".join(sorted(unknown)))
        # The NAMES were checked above; this checks the VALUES, and it is the
        # half that was missing. They went from the file straight into
        # `apply_settings` on the runner's background thread: out-of-range
        # numbers were applied to the engine as they stood, and a value of the
        # wrong TYPE killed the timeline mid-session. Doing it HERE means the
        # complaint arrives when the file is opened - naming the step - instead
        # of in the fifth minute of a run, on a thread with nobody to tell.
        try:
            settings = validated_patch(settings)
        except ValueError as exc:
            # The inner message is a finished sentence of its own ("Field 'Loss:'
            # must be between 0 and 100."), and this one supplies the full stop -
            # so its own is stripped rather than printed twice.
            raise _err("errors.scenario_step_value", step=where,
                       error=str(exc).rstrip(". ")) from exc
        # Loaded and then ignored: a step applies settings the way "Apply changes"
        # does, and that cannot change these - a session takes them at START, or
        # (row_limit) only the window's tables read them. Said, not refused - these
        # are users' files, and a refusal would break them (external review P3-12,
        # owner decision D-27).
        ignored = [k for k in settings if k in NOT_APPLIED_LIVE]
        if ignored:
            warnings.append(translate("log.scenario_step_cannot_change", None, step=where,
                                      field=", ".join(sorted(ignored))))

    action = step.get("action")
    if action is not None and str(action) not in ACTIONS:
        raise _err("errors.scenario_unknown_action", step=where, action=action,
                   allowed=", ".join(ACTIONS))

    if settings is None and action is None:
        raise _err("errors.scenario_step_empty", step=where)

    # How long a reset holds the connections down. It reached the engine as
    # ``float(step.get("duration", 3.0))`` straight off the unvalidated dict, so
    # a string blew up on the scenario THREAD (killing the timeline mid-run,
    # with the session still going) and a negative number was a reset that reset
    # nothing.
    if "duration" in step:
        if action is None:
            raise _err("errors.scenario_duration_without_action", step=where)
        duration = _action_duration(step["duration"], where)

    unknown = [k for k in step if k not in STEP_KEYS]
    if unknown:
        raise _err("errors.scenario_unknown_key", step=where,
                   field=", ".join(sorted(unknown)))

    out = dict(step)
    out["at"] = at
    # The converted values, not the raw ones: what the engine gets is what was
    # validated. Only when the step HAD them - `settings_at` and the runner both
    # ask "is this key in the step", so inventing one would change what it means.
    if settings is not None:
        out["settings"] = settings
    if "duration" in step:
        out["duration"] = duration
    return out


def _action_duration(value, where):
    """How long a step's reset holds the connections down, or a translated error.

    Its own function so ``_validate_step`` stays out of the band near the
    complexity ceiling (``tests/test_code_shape.py``).
    """
    try:
        # Same reader as "at", for the same reason: `float("Infinity")` used to
        # pass `>= 0` and become a reset that never ends. Zero is refused too: a
        # reset that resets nothing looked like one that ran (external review
        # NOWE-2-3, owner decision D-26).
        duration = parse_number(value, bounds=(0, MAX_ACTION_S))
        if duration <= 0:
            raise ValueError(duration)
    except ValueError as exc:
        raise _err("errors.scenario_step_duration", step=where,
                   max=f"{MAX_ACTION_S:g}") from exc
    return duration


class Scenario:
    """A sequence of events on a timeline.

    Step: ``{"at": seconds, "settings": {partial settings},
    "action": "reset_tcp", "duration": s}``. Settings are cumulative:
    each step patches the state from previous steps.
    """

    def __init__(self, steps, loop=False, source=None, warnings=()):
        self.steps = sorted(steps, key=lambda s: float(s.get("at", 0)))
        self.loop = bool(loop)
        # Translated sentences about what loaded but will not act: the CLI and
        # the GUI each say them where they say the scenario loaded.
        self.warnings = list(warnings)
        self.duration = max((float(s.get("at", 0)) for s in self.steps), default=0.0)
        # The file it was read from, EXACTLY as the caller named it - the command
        # that repeats a session names it again (repro.session_command). Not made
        # absolute: that command goes into reports people share, and a relative
        # path typed by the user is the one they can run again. None when the
        # steps did not come from a file.
        self.source = source

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
        stray = [k for k in data if k not in FILE_KEYS]
        if stray:
            raise _err("errors.scenario_unknown_file_key",
                       field=", ".join(sorted(stray)))
        raw = data.get("steps")
        try:
            # The same switch rule as every settings switch: "loop": "false" used
            # to LOOP, and without --duration a CI run never ended (P1-2, D-21).
            loop = parse_bool(data.get("loop", False))
        except ValueError as exc:
            raise _err("errors.scenario_bad_loop", value=repr(data.get("loop"))) from exc
    else:
        raise _err("errors.scenario_not_a_scenario")
    if not isinstance(raw, list):
        raise _err("errors.scenario_no_steps")
    if not raw:
        raise _err("errors.scenario_empty")
    if len(raw) > MAX_STEPS:
        raise _err("errors.scenario_too_many", limit=MAX_STEPS)
    warnings = []
    steps = [_validate_step(i, step, warnings) for i, step in enumerate(raw)]
    return Scenario(steps, loop=loop, warnings=warnings)


def load_scenario_file(path):
    # load_json, not a bare json.load: it answers deep nesting, an oversized file
    # and the non-JSON constants (NaN / Infinity) with the same ValueError this
    # already turns into a translated message. OSError still travels untouched -
    # "cannot read the file" is a different sentence from "this is not a scenario".
    # A shipped scenario named the way a repro command names it opens from any
    # folder (paths.shipped_scenario), but only when the working folder has no such
    # file: that one is what a relative path means. ``source`` stays as given.
    found = path if os.path.exists(path) else (shipped_scenario(path) or path)
    try:
        data = load_json(found)
    except ValueError as e:
        raise _err("errors.scenario_bad_json", error=e) from e
    scenario = parse_scenario(data)
    scenario.source = path
    return scenario
