"""Filesystem locations: project root, bundled resources and user-facing files.

The tool can run in three layouts:
  * from sources        - resources live in the project root (parent of the package),
  * as a PyInstaller exe - bundled resources live in ``sys._MEIPASS``, while files
    the user cares about (profiles, CSV) are written into the user's data directory,
  * installed package    - resources may live inside the package directory.

The user files used to sit next to the executable. They no longer do, and the
reason is package managers - see ``user_data_dir``.
"""
import os
import shutil
import sys
import tempfile

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)

# An override for a genuinely portable copy (a stick, a shared folder). Everything
# else is derived, so this is the ONLY knob.
DATA_DIR_ENV = "BEAN_DATA_DIR"

# The files a user would miss. The NAMES are unchanged - both READMEs document
# them and a repro command may name them - only the directory moved.
PROFILE_NAME = "bean_network_tester_profiles.json"
STATS_CSV_NAME = "bean_network_tester_stats.csv"
CONNECTIONS_CSV_NAME = "bean_network_tester_connections.csv"
UI_STATE_NAME = "bean_network_tester_ui.json"

# What migration carries. Derived from the names above rather than repeated: a new
# user file that is added below and forgotten here would simply never be adopted,
# and nothing would say so.
USER_FILE_NAMES = (PROFILE_NAME, STATS_CSV_NAME, CONNECTIONS_CSV_NAME, UI_STATE_NAME)


def is_frozen():
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def executable_dir():
    """Directory holding the running executable (meaningful when frozen)."""
    return os.path.dirname(os.path.abspath(sys.executable))


def _local_app_data():
    """``%LOCALAPPDATA%``, with a fallback for a profile that does not set it."""
    base = os.environ.get("LOCALAPPDATA") or ""
    if not base:
        base = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return base


def user_data_dir():
    """Directory for the files the user would miss: profiles, window state, CSV.

    A frozen build writes into ``%LOCALAPPDATA%\\<TOOL_ID>``, NOT next to the
    executable, because a package manager owns the install directory:

    * WinGet records the extracted archive's top-level directory as one entry and
      an upgrade removes every recorded entry before installing the new ones -
      ``remove_all`` on that directory, with no diffing and no hook a manifest
      could use. Our zip has exactly one top-level directory, so everything
      written beside the exe is gone on the next ``winget upgrade``.
    * Chocolatey keeps files it never installed, but its package folder grants
      plain users read and execute only, so a non-elevated run cannot save there
      at all.

    The answer deliberately does NOT depend on whether the executable's directory
    happens to be writable. Probing for that would make the location depend on
    ELEVATION - the GUI elevates itself, ``--simulate`` does not - and the same
    install would then keep two sets of profiles without saying so.

    ``BEAN_DATA_DIR`` overrides everything. Running from sources is unchanged.
    """
    override = os.environ.get(DATA_DIR_ENV, "").strip()
    if override:
        return os.path.abspath(override)
    if not is_frozen():
        return PROJECT_ROOT
    # Imported here rather than at module scope: appinfo reads VERSION.txt through
    # resource_path (below), so a top-level import would run appinfo against a
    # half-initialised paths module.
    from .appinfo import TOOL_ID
    return os.path.join(_local_app_data(), TOOL_ID)


def ensure_data_dir():
    """Create the data directory. Returns an error message, or None.

    It has to happen here because neither writer will do it: ``write_json``
    refuses to invent a directory on purpose (a typo in ``--save-config`` must not
    become a silent success) and the CSV export is a plain ``open``.
    """
    try:
        os.makedirs(user_data_dir(), exist_ok=True)
    except OSError as e:
        return str(e)
    return None


def directory_is_writable(path):
    """True when THIS process can create a file in ``path``. ``None`` if it cannot tell.

    A probe, not an ACL walk. Reading the access list would mean deciding which
    principals count as "an ordinary user", and that judgement is the question, not
    the answer - while a write that SUCCEEDS is the answer, for exactly the token
    doing the asking. Which is why the caller has to care whether it is elevated:
    the same probe answers a different question then.
    """
    if not os.path.isdir(path):
        return None
    probe = os.path.join(path, f".bnt-write-probe-{os.getpid()}")
    try:
        with open(probe, "w"):
            pass
    except OSError:
        return False                  # the answer, not a fault: nothing to record
    try:
        os.remove(probe)
    except OSError as _exc:
        # We just created it, so failing to remove it IS a surprise - and a probe
        # that leaves litter behind should not do it quietly (convention 30).
        # Imported here, not at the top: crashlog imports this module.
        from . import crashlog
        crashlog.note(_exc, "paths")
    return True


def temp_beside(path):
    """A temp file NO other writer will pick, in the same directory as ``path``.

    Every atomic write in this program is "write a temp file, then ``os.replace``
    it over the target", and the temp name was ``<target>.tmp`` in all three
    places that do it. That name is a FUNCTION OF THE TARGET, so two writers of
    one file are two writers of one temp file: the second truncates what the
    first is still writing, and the first then publishes the result as the user's
    profiles, settings or window state. Nothing stops that - the program has no
    single-instance lock, and the mutex in ``driver.py`` guards the DRIVER, not
    these files. Two copies running at once is an ordinary thing to do.

    The same DIRECTORY, not the system temp dir: ``os.replace`` is only atomic
    within one filesystem, and that is the whole point of the dance.

    What it costs, said out loud because it is a real trade and not a free win:
    the old name healed itself, since the next write reused it. A unique one
    cannot, so a process killed between the create and the replace leaves a stray
    ``.tmp`` behind for good. That is a corrupt user file traded for a stray one,
    which is the right way round - and where a leftover would do more than sit
    there (``crashes/``, which has to be EMPTY before it can be removed), the
    caller sweeps by prefix instead of relying on one known name.

    One more consequence, decided rather than overlooked: on POSIX ``mkstemp``
    creates the file 0600, and ``os.replace`` carries that mode onto the target, so
    a config file that used to be 0644 becomes owner-only. On Windows - where a
    real capture session can only run - the mode is not what decides access at all,
    and everywhere else these files sit in the user's own data directory, so the
    change is a tightening in a private place. Copying the old file's mode across
    would buy nothing and add a failure path to a function that must not have one.
    """
    directory, name = os.path.split(path)
    # No makedirs: a missing directory is the CALLER's error to report, and
    # mkstemp raising OSError here is how it finds out (see jsonfile.write_json).
    fd, tmp = tempfile.mkstemp(dir=directory or ".", prefix=name + ".", suffix=".tmp")
    os.close(fd)
    return tmp


def _same_directory(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def migrate_user_files(source=None, target=None):
    """Adopt user files left beside a frozen executable. Returns problems, never raises.

    Two decisions worth keeping:

    * it COPIES rather than moves, so rolling back to an older build still finds
      the files where that build looks for them;
    * it only takes a file the target does NOT have, so a stale copy beside the
      exe can never overwrite newer data.

    Nothing is parsed on the way: a corrupt file is copied as it is, and the store
    that reads it quarantines it exactly as it would have done before the move.
    """
    explicit = source is not None or target is not None
    if not explicit and not is_frozen():
        return []                       # from sources the two are the same directory
    source = executable_dir() if source is None else source
    target = user_data_dir() if target is None else target
    if _same_directory(source, target):
        return []

    problems = []
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as e:
        return [str(e)]

    for name in USER_FILE_NAMES:
        src = os.path.join(source, name)
        dst = os.path.join(target, name)
        # isfile(), not exists(): a DIRECTORY carrying one of these names is what
        # Scoop's persist leaves behind, and it must be skipped rather than copied.
        if os.path.exists(dst) or not os.path.isfile(src):
            continue
        # Two copies of the program launched together both migrate, and they used
        # to do it through one `<dst>.tmp`: the loser's half-copy became the
        # user's adopted profile file. See temp_beside.
        tmp = None
        try:
            tmp = temp_beside(dst)
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)        # atomic, so a half-copy is never readable
        except OSError as e:
            problems.append(f"{name}: {e}")
            try:
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)
            except OSError as _exc:
                # The leftover is harmless, the silence would not be (convention 30).
                # Imported here because crashlog imports this module.
                from . import crashlog
                crashlog.note(_exc, "paths")
    return problems


def prepare_user_data():
    """Make the data directory usable. Returns a list of problems (empty = fine).

    One call for the two things that must happen before any store reads a file.
    """
    error = ensure_data_dir()
    if error:
        return [error]
    return migrate_user_files()


def _resource_bases():
    """Candidate directories to search for bundled resources, in order."""
    bundle = getattr(sys, "_MEIPASS", None)
    return [b for b in (bundle, PROJECT_ROOT, PACKAGE_DIR) if b]


def resource_path(name):
    """Path to a bundled resource (icon, etc.); first existing candidate wins."""
    for base in _resource_bases():
        candidate = os.path.join(base, name)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(PROJECT_ROOT, name)


def lang_dir():
    """Directory containing the ``lang/<code>.json`` translation files."""
    for base in _resource_bases():
        candidate = os.path.join(base, "lang")
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(PROJECT_ROOT, "lang")


def scenarios_dir():
    """Directory holding the bundled example ``scenarios/*.json``.

    When frozen these ship under ``_internal/scenarios`` (or ``sys._MEIPASS``),
    a location the user would never think to browse to - so the scenario file
    dialog opens here instead of wherever the OS last left it.
    """
    for base in _resource_bases():
        candidate = os.path.join(base, "scenarios")
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(PROJECT_ROOT, "scenarios")


PROFILE_FILE = os.path.join(user_data_dir(), PROFILE_NAME)
CSV_FILE = os.path.join(user_data_dir(), STATS_CSV_NAME)
# Snapshot of the connection table (overwritten each export, unlike the appended
# stats CSV): the user asks for "the connections as they are now".
CONNECTIONS_CSV_FILE = os.path.join(user_data_dir(), CONNECTIONS_CSV_NAME)
# Window geometry, active page, collapsed sections, table sorting, language...
UI_STATE_FILE = os.path.join(user_data_dir(), UI_STATE_NAME)
