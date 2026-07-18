"""Filesystem locations: project root, bundled resources and user-facing files.

The tool can run in three layouts:
  * from sources        - resources live in the project root (parent of the package),
  * as a PyInstaller exe - bundled resources live in ``sys._MEIPASS``, while files
    the user cares about (profiles, CSV) are written next to the executable,
  * installed package    - resources may live inside the package directory.
"""
import os
import sys

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)


def is_frozen():
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def app_dir():
    """Directory for user-facing output files (profiles, CSV stats).

    Next to the executable when frozen (a onefile exe unpacks itself into a
    temporary directory, which would silently swallow saved profiles),
    otherwise the project root.
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return PROJECT_ROOT


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


PROFILE_FILE = os.path.join(app_dir(), "bean_network_tester_profiles.json")
CSV_FILE = os.path.join(app_dir(), "bean_network_tester_stats.csv")
# Snapshot of the connection table (overwritten each export, unlike the appended
# stats CSV): the user asks for "the connections as they are now".
CONNECTIONS_CSV_FILE = os.path.join(app_dir(), "bean_network_tester_connections.csv")
# Window geometry, active page, collapsed sections, table sorting, language...
UI_STATE_FILE = os.path.join(app_dir(), "bean_network_tester_ui.json")
