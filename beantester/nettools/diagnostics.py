"""Environment diagnostics: why a session will not start, without opening a console.

Nothing here decides what the checks ARE. ``driver.doctor()`` is the one list,
read by ``--doctor`` and by the Tools tab alike, so a check added there appears in
both on the same day - two lists would drift, and the window would be the one
nobody looks at when they do. This module adds what only a window needs: a
stable i18n key for each check's NAME, the rule for when the driver may be
cleaned up from here, and the report a person copies into a bug report.

What stays English, on purpose: a check's ``detail`` and the whole report. They
are the program's own output, exactly as ``--doctor`` prints it, and the bug
report template asks for that output by name - a translated copy would be a
second report the maintainer has to read back into the first.
"""
from typing import Callable, NamedTuple

from .. import crashlog, driver
from ..appinfo import version_line
from ..paths import user_data_dir

# The states ``driver.doctor()`` gives a check. FAIL is the one a session cannot
# start past; WARN is worth reading and does not stop anything.
OK, WARN, FAIL = "ok", "warn", "fail"

# A check's name on screen. The slug is doctor's own name with its spaces made
# underscores ("windivert driver" -> tools.diagnostics.check.windivert_driver), so
# the name IS the key and nothing maps one to the other by hand.
# `tests/test_nettools_diagnostics.py` walks every name doctor() can give - both
# platforms, frozen or not - and reddens on one without a key.
CHECK_KEY = "tools.diagnostics.check.{slug}"


def check_key(name):
    """The i18n key that names one of doctor's checks."""
    return CHECK_KEY.format(slug=name.replace(" ", "_"))


class Check(NamedTuple):
    name: str           # doctor's own name - program text, and the key's slug
    state: str          # OK / WARN / FAIL
    detail: str         # program text, exactly as --doctor prints it


class Diagnosis(NamedTuple):
    ok: bool            # no check failed: nothing here stops a session
    checks: tuple       # of Check, in doctor's order
    data_dir: str       # where this account's own files are - a line, not a check


def diagnose():
    """Run the checks. Blocking: the first call imports pydivert (~160 ms measured)."""
    ok, rows = driver.doctor()
    return Diagnosis(ok, tuple(Check(*row) for row in rows), user_data_dir())


# -- cleaning up the driver ---------------------------------------------------- #
def cleanup_blocker():
    """Why the driver cannot be cleaned up from this process: an i18n key, "" if it can.

    Both answers hold for the life of the process - a running program does not
    gain or lose administrator rights - so a panel asks once. The session state is
    NOT here: it changes by the second and belongs to the window that runs it.
    ``driver.cleanup_driver`` refuses the same two cases on its own; this is the
    part that lets a button say why before anyone presses it.
    """
    if not driver.is_windows():
        return "tools.diagnostics.clean_windows_only"
    if not driver.is_admin():
        return "tools.diagnostics.clean_needs_admin"
    return ""


def opens_so_far():
    """What a cleanup asked for NOW must still find when it runs: read at the yes.

    The real diverts this process has opened (``driver.opens``). The cleanup runs
    later, on a worker, and stands down if a session opened one in between.
    """
    return driver.opens()


def clean_up(opens_seen):
    """Unload every leftover WinDivert service. Returns the report lines.

    ``release_own`` because a window that has run a session keeps its use marker,
    and without letting it go first the warning about ANOTHER instance could never
    fire (``driver.cleanup_driver``). ``opens_seen`` is ``opens_so_far()`` from the
    moment the person said yes - required, so no caller can leave it out.
    """
    return tuple(driver.cleanup_driver(release_own=True, opens_seen=opens_seen))


# -- the environment report ------------------------------------------------------ #
class Section(NamedTuple):
    id: str
    lines: Callable     # (Diagnosis) -> list of lines, program text


def _program(_diagnosis):
    return [version_line()]


def _environment(diagnosis):
    return driver.format_doctor(diagnosis.checks, diagnosis.data_dir)


def _crash_log(_diagnosis):
    counts = crashlog.summary()
    return [f"crash log: {counts['errors']} error(s), {counts['swallowed']} swallowed, "
            f"{counts['distinct']} distinct, in this run"]


# The report is a registry, not a function body, so the next tool that knows
# something about this machine (adapters, the system proxy) adds a section here
# and the copied text grows by itself. A section works from what is already
# known - today every line comes from the last check or from memory, so the text
# is built on the UI thread at a click. A section that has to ask the system is
# the day the report moves to the worker, not the day it grows a stall.
REPORT_SECTIONS = (
    Section("program", _program),              # exactly what --version prints
    Section("environment", _environment),      # exactly what --doctor prints
    Section("crash log", _crash_log),
)


def report(diagnosis, sections=REPORT_SECTIONS):
    """The text a person pastes into a bug report, one block per section.

    A section that fails costs its own block and nothing else: a report missing
    the one line that broke is still the report, while no report at all is what
    the person was trying to fix by pressing the button.
    """
    blocks = []
    for section in sections:
        try:
            lines = [str(line) for line in section.lines(diagnosis)]
        except Exception as exc:
            crashlog.note(exc, "nettools.diagnostics")
            lines = [f"{section.id}: could not be read ({type(exc).__name__})"]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
