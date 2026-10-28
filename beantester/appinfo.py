"""Application identity constants shared by the GUI, CLI and reports.

The VERSION lives in ONE place: ``VERSION.txt`` in the project root (and, in a
frozen build, next to the bundled resources). Nothing else may carry a version
literal - the .spec reads it from here for the exe metadata, pyproject reads the
file directly, and ``--version`` prints it. Bumping a release is therefore a
one-line edit of a text file plus a build, and there is no second copy left to
drift. ``tests/test_repo_conventions.py`` fails the build if a copy appears.
"""
import re
import sys

APP_NAME = "Bean Network Tester"     # human-readable window / product name
AUTHOR = "DonislawDev"               # shown in the GUI, the exe metadata and --version
SUPPORT_URL = "https://donislawdev.com/support/"   # voluntary support for the project
# The project's source, releases and issues. The same address as `repo_url` in
# site/site.json, which the website and the package manifests are built from -
# tests/test_release_fixes.py holds the two together.
REPO_URL = "https://github.com/donislawdev/BeanNetworkTester"
TOOL_ID = "BeanNetworkTester"        # machine-readable id used in reports
LAUNCHER = "bean_network_tester.py"  # entry script name (running from sources)
EXE_NAME = "BeanNetworkTester.exe"   # the shipped executable - CLI *and* GUI
LINUX_EXE_NAME = "BeanNetworkTester"  # the same in the Linux .tar.gz
VERSION_FILE = "VERSION.txt"         # the only place a version number may live

LICENSE_NAME = "GNU General Public License v3.0"   # free & open source, copyleft (see LICENSE)
LICENSE_FILE = "LICENSE"
NOTICES_FILE = "THIRD-PARTY-NOTICES.md"
COPYRIGHT = "Copyright (C) 2026 DonislawDev"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
FALLBACK_VERSION = "0.0.0"           # VERSION.txt missing = a broken build, and it says so


def _read_version():
    """Read and validate ``VERSION.txt``.

    A malformed or missing file must not raise on import (the crash logger, which
    reports such things, imports this module). It yields ``0.0.0`` instead, which
    is loud enough to notice and is asserted against in ``build.py`` and in the
    convention tests.
    """
    from .paths import resource_path
    try:
        with open(resource_path(VERSION_FILE), encoding="utf-8") as f:
            text = f.read().strip()
    except OSError:
        return FALLBACK_VERSION
    return text if VERSION_RE.match(text) else FALLBACK_VERSION


__version__ = _read_version()


def command_name(simulate=False):
    """How the user invokes this build: the exe when frozen, the script otherwise -
    on Linux the way its README starts it (``linux_command``).

    Reproduction commands and ``--help`` must be copy-paste ready, and a frozen
    build has no ``python bean_network_tester.py`` to offer. ``simulate``: the
    command runs ``--simulate``, which on Linux needs no root.
    """
    from .paths import is_frozen
    if sys.platform.startswith("linux"):
        return linux_command(simulate)
    if is_frozen():
        return EXE_NAME
    return f"python {LAUNCHER}"


def exe_name():
    """The shipped executable's file name on this system."""
    return LINUX_EXE_NAME if sys.platform.startswith("linux") else EXE_NAME


def linux_command(simulate=False, executable=None, checkout=None, home=None, frozen=None):
    """The program as Linux runs it, the README's way: from the ``.tar.gz``
    ``sudo ~/BeanNetworkTester/BeanNetworkTester``, from a checkout
    ``sudo .venv/bin/python -B bean_network_tester.py``.

    MEASURED 2026-10-27 on Ubuntu 26.04: there is no ``python`` there, only
    ``python3``, for a user or under sudo, so the command the window copied ended
    in "command not found"; a capture needs root, so without ``sudo`` it ended with
    exit code 7; and pydivert lives in the virtual environment, which the system's
    ``python3`` is not. So ``sudo`` and ``-B`` (root leaves no cache folders in the
    checkout) unless the command is a simulation, and the interpreter running now,
    named with no path from this machine - a report carrying the command is shared:
    relative to the checkout when it is inside it, from ``~`` when it is in the
    person's home, else ``python3``. The frozen program the same way: from ``~``,
    else ``./BeanNetworkTester``, which runs from its own folder.
    """
    from . import paths
    executable = sys.executable if executable is None else executable
    home = _persons_home() if home is None else home
    if paths.is_frozen() if frozen is None else frozen:
        program = (home and _inside(executable, home, "~/")) or "./" + LINUX_EXE_NAME
        return " ".join(([] if simulate else ["sudo"]) + [program])
    checkout = paths.PROJECT_ROOT if checkout is None else checkout
    interpreter = (_inside(executable, checkout, "")
                   or (home and _inside(executable, home, "~/")) or "python3")
    return " ".join(([] if simulate else ["sudo"]) + [interpreter]
                    + ([] if simulate else ["-B"]) + [LAUNCHER])


def _inside(path, base, prefix):
    """``path`` as ``prefix`` + its place under ``base``, or None when it is not under it."""
    import posixpath
    import shlex
    if not path or not base:
        return None
    place = posixpath.relpath(posixpath.abspath(path), posixpath.abspath(base))
    if place == posixpath.pardir or place.startswith(posixpath.pardir + "/"):
        return None
    return prefix + shlex.quote(place)


def _persons_home():
    """The home of the person running the program: under sudo theirs, not root's."""
    import os

    from . import paths
    person = paths.invoking_user()
    return paths.home_of(person[0]) if person else os.path.expanduser("~")


def version_line():
    """What ``--version`` prints - and the first line of the Tools tab's report.

    The bug report template asks for this line by name, so the report a person
    copies from the window has to start with exactly what the command prints.
    """
    return f"{APP_NAME} {__version__}"


def program_name():
    """``prog`` for argparse (no ``python `` prefix - argparse adds no shell)."""
    from .paths import is_frozen
    return exe_name() if is_frozen() else LAUNCHER
