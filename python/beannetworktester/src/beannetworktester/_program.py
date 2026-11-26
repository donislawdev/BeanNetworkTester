# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Which program a session runs, and with what rights.

The wheel for Windows x64 and the one for Linux x64 carry the release's own program,
unchanged, in ``program/BeanNetworkTester``: on Windows that is the signed exe. The
wheel for every other system carries none, and says so when a session starts.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping

# Set it to run another copy of the program: an installed BeanNetworkTester, or
# bean_network_tester.py from a checkout (a .py file runs with this Python). PATH is
# never searched - a different copy found there would be a different version, with
# other flags, and nothing would say so.
PROGRAM_ENV = "BEANNETWORKTESTER_PROGRAM"
SYSTEMS = ("Windows x64", "Linux x64")

_HERE = os.path.dirname(os.path.abspath(__file__))
_NAMES = {"win32": "BeanNetworkTester.exe", "linux": "BeanNetworkTester"}


class BadNetworkError(RuntimeError):
    """A session could not start, or could not stop the way it should."""


def _system(platform: str) -> str:
    return "linux" if platform.startswith("linux") else platform


def _sixty_four_bit_x86(machine: str) -> bool:
    return machine.lower() in ("amd64", "x86_64")


def program_command(*, env: Mapping[str, str] | None = None, platform: str | None = None,
                    machine: str | None = None, here: str | None = None) -> list[str]:
    """The command that starts the program, before its flags.

    Everything is passed in, so the tests can ask about a system they are not on.
    """
    env = os.environ if env is None else env
    given = env.get(PROGRAM_ENV)
    if given:
        if not os.path.isfile(given):
            raise BadNetworkError(f"{PROGRAM_ENV} is set to {given}, and there is no file there. "
                                  "Point it at the program, or unset it to use the one this "
                                  "package installs.")
        return [sys.executable, given] if given.endswith(".py") else [given]
    system = _system(sys.platform if platform is None else platform)
    if machine is None:
        import platform as _platform
        machine = _platform.machine()
    here = _HERE if here is None else here
    name = _NAMES.get(system)
    if name is None or not _sixty_four_bit_x86(machine):
        raise BadNetworkError(
            f"beannetworktester runs the network on Windows x64 and Linux x64 only, and this is "
            f"{system} {machine}. On a Mac, run the tests in a Linux x86_64 container or virtual "
            f"machine, or on a CI runner with Windows or Linux.")
    found = os.path.join(here, "program", "BeanNetworkTester", name)
    if os.path.isfile(found):
        return [found]
    if not os.path.isdir(os.path.join(here, "program")):
        raise BadNetworkError(
            "This install of beannetworktester has no program in it: pip took the wheel without "
            "one, which happens with a 32-bit Python or with an old pip that does not know the "
            "wheel's platform tag. Install it with a 64-bit Python and a current pip, or set "
            f"{PROGRAM_ENV} to the path of BeanNetworkTester.")
    raise BadNetworkError(
        f"The program of this install is not at {found}, where the package puts it: something "
        "removed it. Run pip install --force-reinstall beannetworktester, or set "
        f"{PROGRAM_ENV} to the path of BeanNetworkTester.")


def shipped_scenarios(command: list[str]) -> list[str]:
    """The folders the program keeps the scenarios it ships in: built, or a checkout."""
    folder = os.path.dirname(os.path.abspath(command[-1]))
    return [os.path.join(folder, "_internal", "scenarios"), os.path.join(folder, "scenarios")]


def _is_admin() -> bool:
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())   # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def _sudo_works() -> bool:
    if shutil.which("sudo") is None:
        return False
    try:
        done = subprocess.run(["sudo", "-n", "true"], stdin=subprocess.DEVNULL,  # noqa: S603, S607
                              capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def rights_prefix(*, simulate: bool, platform: str | None = None) -> list[str]:
    """What goes in front of the program so that it may capture: ``[]`` or sudo.

    A real capture needs administrator rights on Windows and root on Linux. Asked
    here, before anything starts, so a test fails with a sentence that says what to
    do, instead of with an exit code. ``simulate`` needs no rights at all.
    """
    if simulate:
        return []
    system = _system(sys.platform if platform is None else platform)
    if system == "win32":
        if _is_admin():
            return []
        raise BadNetworkError(
            "Slowing the network needs administrator rights on Windows. Run the tests from a "
            "terminal opened with Run as administrator. GitHub's Windows runners already run "
            "elevated.")
    if system == "linux":
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            return []
        if _sudo_works():
            return ["sudo", "-n"]
        raise BadNetworkError(
            "Slowing the network needs root on Linux. Run the tests as root, or as a user who "
            "may run sudo without a password, as on GitHub's Ubuntu runners. The program runs "
            "under sudo, and the tests themselves do not.")
    raise BadNetworkError(f"beannetworktester runs the network on {' and '.join(SYSTEMS)} only.")
