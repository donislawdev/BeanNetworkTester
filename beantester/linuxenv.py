"""Process-level Linux knobs for the window: asking for root through polkit.

The Windows twin is ``winenv`` and its UAC prompt. Here the window, started
without root, runs itself again through ``pkexec``, which shows the desktop's
own password dialog (GNOME's, measured on Ubuntu 26.04), and waits for that
copy. A dismissed or impossible request leaves the window to open here, without
root, as it did before this module existed. Every fact below was measured or
read in pkexec's own source; ``internal_tools/PROJEKT-linux-pkexec-2026-10-28.md``
holds the design and the measurements.

What pkexec does to the program it starts, and what follows from it:

* It keeps only a few variables and drops ``DISPLAY`` and ``XAUTHORITY``, so Tk
  in the copy cannot reach the screen ("no display name"). The copy takes them,
  and the working directory, from the process that asked - its parent, which
  belongs to the person pkexec names in ``PKEXEC_UID`` (``take_desktop``).
* It refuses to run at all (exit 127) when ``SHELL`` is not in ``/etc/shells``
  or a kept variable holds ``/``, ``%`` or ``..``, so it is handed only the
  locale variables that pass those rules (``pkexec_environment``).
* It sets ``PR_SET_PDEATHSIG`` to SIGTERM before it executes the program: the
  copy dies with the process that asked. That process waits, in the thread that
  started pkexec, for as long as the copy runs (``ask_for_root``).
* It closes every descriptor above 2, so the copy can answer only with its exit
  code: 126 dismissed, 127 anything else that stopped it (``NOT_STARTED``).
* Without ``--keep-cwd`` (polkit 121 and newer) it starts the program in root's
  home, where ``python -m beantester`` from a checkout cannot import itself.
"""
import os
import posixpath
import re
import shutil
import signal
import stat
import subprocess
import sys

from . import winenv

# What pkexec answers when the program did not run: 126 the person dismissed the
# dialog, 127 not authorised, no agent to ask through, or any other error. None of
# the program's own exit codes (exitcodes.py) is either.
NOT_STARTED = (126, 127)

# What the copy answers when it ran as root but its window could not reach the
# person's display: pkexec's own "did not run", so the person's process opens the
# window itself, without root, instead of leaving the person with no window at all.
NO_WINDOW = 127

# The variables pkexec keeps from its caller, apart from SHELL, TERM, COLORTERM,
# DISPLAY and XAUTHORITY: nothing of those is needed, and each is a way to be refused.
LOCALE_NAMES = ("LANG", "LANGUAGE", "LINGUAS", "LC_ALL", "LC_COLLATE", "LC_CTYPE",
                "LC_MESSAGES", "LC_MONETARY", "LC_NUMERIC", "LC_TIME")

# pkexec's own test for a kept variable (validate_environment_variable).
_SUSPICIOUS = ("/", "%", "..")

# host:display.screen, the host part empty for the local display. Anything else is
# not taken from the parent.
_DISPLAY = re.compile(r"[A-Za-z0-9._-]*:[0-9]+(\.[0-9]+)?")

# The most of a parent's environment that is read.
_ENVIRON_LIMIT = 1 << 20


def is_linux():
    return sys.platform.startswith("linux")


def wants_root(environ=None, euid=None, which=shutil.which):
    """True when the window should ask for root before it opens.

    Only on Linux, and never as root: root that still cannot capture (a container
    without CAP_BPF) would otherwise start copy after copy. Not with
    ``BEAN_NO_ELEVATE`` set, as on Windows; not without a display, where there is
    no window to ask from; not with the capabilities already there; and not
    without pkexec.
    """
    environ = os.environ if environ is None else environ
    if not is_linux() or winenv.elevation_disabled():
        return False
    if (os.geteuid() if euid is None else euid) == 0:
        return False
    if not environ.get("DISPLAY"):
        return False
    from . import capture_backend
    if capture_backend.current().has_capture_rights():
        return False
    return bool(which("pkexec"))


def pkexec_environment(environ=None):
    """What pkexec is started with: the locale variables it will not refuse."""
    environ = os.environ if environ is None else environ
    return {name: environ[name] for name in LOCALE_NAMES
            if environ.get(name) and not any(bad in environ[name] for bad in _SUSPICIOUS)}


def relaunch_command(argv, pkexec, keep_cwd):
    """The argv that starts this program again as root through pkexec, or None.

    ``winenv._relaunch_command`` repeats what this program was started with. From
    sources ``-B`` is added when it is not there: root leaves no cache folders in
    the person's checkout. ``python -m`` needs the working directory, which only
    ``--keep-cwd`` keeps; without it there is nothing to repeat.
    """
    program, args = winenv._relaunch_command(list(argv))
    if not winenv.is_frozen():
        head = args[:len(args) - len(argv)]
        if "-m" in head and not keep_cwd:
            return None
        if "-B" not in head:
            args = ["-B"] + args
    return ([pkexec, "--disable-internal-agent"] + (["--keep-cwd"] if keep_cwd else [])
            + [program] + args)


def _run(command, **kw):
    """The one place this module starts a process: pkexec, for its usage and for
    the copy (tests/test_no_telemetry.py SPAWN_ALLOWED)."""
    return subprocess.run(command, check=False, **kw)


def ask_for_root(argv, run=_run, which=shutil.which, environ=None):
    """Run this program again as root through pkexec and wait for it.

    Returns the copy's exit code, or None when it did not run (dismissed, not
    allowed, nothing to ask through, the copy could not open its window): the
    caller then opens the window itself, without root. A copy killed by a signal
    answers 128 + the signal, as a shell would.

    Ctrl+C in the terminal reaches the copy as well, so here it is waited through
    with a handler that does nothing - not SIG_IGN, which the copy would inherit
    (pkexec executes it with the dispositions it was given).
    """
    pkexec = which("pkexec")
    if not pkexec:
        return None
    env = pkexec_environment(environ)
    command = relaunch_command(argv, pkexec, _keeps_cwd(pkexec, env, run))
    if command is None:
        return None
    previous = signal.signal(signal.SIGINT, _wait_through)
    try:
        code = run(command, env=env).returncode
    except OSError:
        return None
    finally:
        signal.signal(signal.SIGINT, previous)
    if code in NOT_STARTED:
        print(f"pkexec did not start the window as root (exit {code}): "
              "it opens without administrator rights", file=sys.stderr)
        return None
    return 128 - code if code < 0 else code


def _wait_through(_signum, _frame):
    """Ctrl+C while the copy runs: the copy decides what it means."""


def _keeps_cwd(pkexec, env, run):
    """Whether this pkexec takes ``--keep-cwd`` - read from its usage, which names it
    from polkit 121 on, rather than from a version a distribution may have patched."""
    try:
        done = run([pkexec, "--help"], env=env, capture_output=True, text=True,
                   timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return "--keep-cwd" in (done.stdout or "") + (done.stderr or "")


def started_by_pkexec(environ=None):
    """True in the copy pkexec started: root, with ``PKEXEC_UID`` naming the person."""
    environ = os.environ if environ is None else environ
    return is_linux() and os.geteuid() == 0 and _uid(environ.get("PKEXEC_UID")) is not None


def take_desktop(environ=None, system=None, ppid=None):
    """In the copy pkexec started: the person's display, X authority and working
    directory, from the process that asked. Returns the names it set.

    Nothing is taken when ``DISPLAY`` is already there (sudo keeps it), outside
    pkexec, or when the parent does not belong to the person in ``PKEXEC_UID``.
    """
    environ = os.environ if environ is None else environ
    if not started_by_pkexec(environ) or environ.get("DISPLAY"):
        return []
    desktop = desktop_of_parent(environ, system or _System(),
                                os.getppid() if ppid is None else ppid)
    cwd = desktop.pop("cwd", None)
    environ.update(desktop)
    if cwd is not None:
        try:
            os.chdir(cwd)
        except OSError:
            cwd = None
    return sorted(desktop) + (["cwd"] if cwd is not None else [])


def desktop_of_parent(environ, system, ppid):
    """``{"DISPLAY", "XAUTHORITY", "cwd"}`` of the parent, those that pass, or {}.

    The parent must be the person's: its real uid is ``PKEXEC_UID``. ``DISPLAY``
    must look like one. ``XAUTHORITY`` must be a regular file of the person's at an
    absolute path - the parent's, else ``~/.Xauthority`` in the person's home,
    which is where pkexec itself would look. Hygiene rather than a boundary: the
    person has just typed an administrator's password.
    """
    uid = _uid(environ.get("PKEXEC_UID"))
    if uid is None or system.real_uid(ppid) != uid:
        return {}
    parent = system.environ(ppid)
    display = parent.get("DISPLAY", "")
    if not _DISPLAY.fullmatch(display):
        return {}
    found = {"DISPLAY": display}
    home = system.home_of(uid)
    for xauthority in (parent.get("XAUTHORITY"),
                       home and posixpath.join(home, ".Xauthority")):
        if xauthority and posixpath.isabs(xauthority) and system.owns_file(uid, xauthority):
            found["XAUTHORITY"] = xauthority
            break
    cwd = system.cwd(ppid)
    if cwd:
        found["cwd"] = cwd
    return found


def _uid(text):
    try:
        uid = int(text)
    except (TypeError, ValueError):
        return None
    return uid if uid >= 0 else None


class _System:
    """What the copy reads about the person: its parent's ``/proc`` entries and the
    person's files. ``root`` lets a test point it at a folder of its own."""

    def __init__(self, root="/proc"):
        self.root = root

    def real_uid(self, pid):
        try:
            with open(os.path.join(self.root, str(pid), "status"), encoding="ascii",
                      errors="replace") as f:
                status = f.read()
        except OSError:
            return None
        for line in status.splitlines():
            fields = line.split()
            if fields[:1] == ["Uid:"] and len(fields) > 1:
                return _uid(fields[1])
        return None

    def environ(self, pid):
        try:
            with open(os.path.join(self.root, str(pid), "environ"), "rb") as f:
                raw = f.read(_ENVIRON_LIMIT)
        except OSError:
            return {}
        found = {}
        for entry in raw.split(b"\0"):
            name, sep, value = entry.decode("utf-8", "replace").partition("=")
            if sep and name not in found:
                found[name] = value
        return found

    def cwd(self, pid):
        try:
            place = os.readlink(os.path.join(self.root, str(pid), "cwd"))
        except OSError:
            return None
        return place if os.path.isdir(place) else None

    @staticmethod
    def home_of(uid):
        from . import paths
        return paths.home_of(uid)

    @staticmethod
    def owns_file(uid, path):
        try:
            info = os.lstat(path)
        except OSError:
            return False
        return stat.S_ISREG(info.st_mode) and info.st_uid == uid
