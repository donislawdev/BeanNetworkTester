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
from types import MappingProxyType
from typing import Callable, Mapping, NamedTuple

from .. import capture_backend, crashlog, driver
from ..appinfo import version_line
from ..paths import user_data_dir
from . import adapters, proxy

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


class Found(NamedTuple):
    """What one report section's ``read`` gave."""
    value: object = None        # None: not read on this system, or the read failed
    error: str = ""             # why it failed, program text


class Diagnosis(NamedTuple):
    ok: bool            # no check failed: nothing here stops a session
    checks: tuple       # of Check, in doctor's order
    data_dir: str       # where this account's own files are - a line, not a check
    # What the sections that ask the system (``Section.read``) found, by section id.
    # Read with the checks, so the report is still built from what is already known,
    # at a click, on the UI thread.
    found: Mapping = MappingProxyType({})


def diagnose():
    """Run the checks and every section's read. Blocking: the first call imports
    pydivert (~160 ms measured); the adapters add ~3 ms and the proxy ~2 ms (measured
    2026-10-13 and 2026-10-14), so they are read with every check rather than when a
    box is ticked."""
    ok, rows = driver.doctor()
    found = {section.id: _found(section) for section in REPORT_SECTIONS if section.read}
    return Diagnosis(ok, tuple(Check(*row) for row in rows), user_data_dir(),
                     MappingProxyType(found))


def _found(section):
    """One section's read - its failure costs that section only. A failure the
    person can act on (it carries a ``user_key``) is an answer, not a fault, and stays
    out of the crash log."""
    try:
        return Found(section.read(), "")
    except Exception as exc:
        if getattr(exc, "user_key", None) is None:
            crashlog.note(exc, f"nettools.diagnostics.{section.id}")
        return Found(None, f"{type(exc).__name__}: {exc}")


def _read_adapters():
    return adapters.read() if adapters.supported() else None


def _read_proxy():
    return proxy.read() if proxy.supported() else None


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
        # No WinDivert service here; the platform's backend says why that is fine.
        return capture_backend.current().CLEANUP_BLOCKER
    if not driver.is_admin():
        return "tools.diagnostics.clean_needs_admin"
    return ""


CLEAN_TIP = "tips.tools_diagnostics_clean"


def cleanup_tip():
    """The cleanup button's tooltip, an i18n key: what it does, on Windows - and off
    Windows, where it can never do it, why not, in the words of the note under it.

    It said "Unloads a WinDivert driver" on Linux, over a greyed-out button and right
    above the note saying there is nothing to clean up there.
    """
    return CLEAN_TIP if driver.is_windows() else cleanup_blocker()


# -- the "?" sheet ----------------------------------------------------------------- #
# Its paragraphs on the rows only Windows gives (administrator, the WinDivert driver)
# and on cleaning that driver up. Off Windows the capture backend names its own
# (``CaptureBackend.DIAGNOSTICS_HELP``), as it does for the cleanup above.
WINDOWS_HELP = ("tools.diagnostics.help_windows",)


def platform_help():
    """The "?" sheet's paragraphs on this system's own rows, as i18n keys, in order.

    The rest of the sheet is the same everywhere or follows the report boxes
    (``gui/toolbox/diagnostics.py``). On Linux it used to be Windows' rows - the
    administrator, a WinDivert service "stop pending" - beside rows that said
    kernel, BTF and capture rights.
    """
    return WINDOWS_HELP if driver.is_windows() else capture_backend.current().DIAGNOSTICS_HELP


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
    # In the report only when the person asks for it (``report(include=...)``).
    optional: bool = False
    # () -> what ``lines`` needs from the system, run by ``diagnose()`` on the worker
    # and kept in ``Diagnosis.found[id]``; None for a section that asks nothing.
    read: Callable | None = None


def _program(_diagnosis):
    return [version_line()]


def _environment(diagnosis):
    return driver.format_doctor(diagnosis.checks, diagnosis.data_dir)


def _crash_log(_diagnosis):
    counts = crashlog.summary()
    return [f"crash log: {counts['errors']} error(s), {counts['swallowed']} swallowed, "
            f"{counts['distinct']} distinct, in this run"]


def _found_lines(diagnosis, section_id, what, lines):
    found = diagnosis.found.get(section_id, Found())
    if found.value is not None:
        return lines(found.value)
    if found.error:
        return [f"{what}: could not be read ({found.error})"]
    return [f"{what}: not read on this system"]


def _adapters(diagnosis):
    return _found_lines(diagnosis, "adapters", "network adapters", adapters.report_lines)


def _proxy(diagnosis):
    return _found_lines(diagnosis, "proxy", "proxy", proxy.report_lines)


# The report is a registry, not a function body: a tool that knows something about
# this machine adds a section here - with a ``read`` when it has to ask the system -
# and the copied text grows by itself. Every line comes from what ``diagnose()``
# found on the worker, so the text is built on the UI thread at a click.
#
# 🔴 A section that names this machine's network - addresses, MAC, DNS servers, a
# proxy - is OPTIONAL: the bug report template asks for this report in a PUBLIC
# issue (`.github/ISSUE_TEMPLATE/bug_report.yml`, "Environment report"). The person
# adds it with a tick box, which is off until ticked (the owner's decisions,
# 2026-10-13 for the adapters, 2026-10-14 for the proxy - a box of its own).
REPORT_SECTIONS = (
    Section("program", _program),              # exactly what --version prints
    Section("environment", _environment),      # exactly what --doctor prints
    Section("crash log", _crash_log),
    Section("adapters", _adapters, optional=True, read=_read_adapters),
    Section("proxy", _proxy, optional=True, read=_read_proxy),
)


def report(diagnosis, sections=REPORT_SECTIONS, include=()):
    """The text a person pastes into a bug report, one block per section.

    An optional section is in it only when its id is in ``include``.

    A section that fails costs its own block and nothing else: a report missing
    the one line that broke is still the report, while no report at all is what
    the person was trying to fix by pressing the button.
    """
    blocks = []
    for section in sections:
        if section.optional and section.id not in include:
            continue
        try:
            lines = [str(line) for line in section.lines(diagnosis)]
        except Exception as exc:
            crashlog.note(exc, "nettools.diagnostics")
            lines = [f"{section.id}: could not be read ({type(exc).__name__})"]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
