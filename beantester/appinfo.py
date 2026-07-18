"""Application identity constants shared by the GUI, CLI and reports.

The VERSION lives in ONE place: ``VERSION.txt`` in the project root (and, in a
frozen build, next to the bundled resources). Nothing else may carry a version
literal - the .spec reads it from here for the exe metadata, pyproject reads the
file directly, and ``--version`` prints it. Bumping a release is therefore a
one-line edit of a text file plus a build, and there is no second copy left to
drift. ``tests/test_repo_conventions.py`` fails the build if a copy appears.
"""
import re

APP_NAME = "Bean Network Tester"     # human-readable window / product name
AUTHOR = "DonislawDev"               # shown in the GUI, the exe metadata and --version
SUPPORT_URL = "https://donislawdev.com/support/"   # voluntary support for the project
TOOL_ID = "BeanNetworkTester"        # machine-readable id used in reports
LAUNCHER = "bean_network_tester.py"  # entry script name (running from sources)
EXE_NAME = "BeanNetworkTester.exe"   # the shipped executable - CLI *and* GUI
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


def command_name():
    """How the user invokes this build: the exe when frozen, the script otherwise.

    Reproduction commands and ``--help`` must be copy-paste ready, and a frozen
    build has no ``python bean_network_tester.py`` to offer.
    """
    from .paths import is_frozen
    return EXE_NAME if is_frozen() else f"python {LAUNCHER}"


def program_name():
    """``prog`` for argparse (no ``python `` prefix - argparse adds no shell)."""
    from .paths import is_frozen
    return EXE_NAME if is_frozen() else LAUNCHER
