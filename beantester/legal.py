"""Licensing surface: the texts we must ship, and the versions we actually shipped.

Three consumers, one module: the "About" window, the ``--license`` CLI flag and the
convention tests. It exists because an LGPL obligation is not met by a file sitting
in a repository - it is met by a file the *user of the binary* can find and read,
and by naming the exact library version they were given, so they can fetch that
source and replace it.

Nothing here reaches the network. Reading a bundled text file is the whole job.
"""
import sys

from .appinfo import LICENSE_FILE, NOTICES_FILE
from .paths import resource_path

LICENSES_DIR = "licenses"

# The components we ship, in the order a reader cares about. ``module`` is the
# import name used to report the real version at run time (None = not a Python
# package, so the version is fixed or reported by other means).
COMPONENTS = (
    # (name, module, licence used, where the source lives)
    ("WinDivert", None, "LGPL-3.0 (dual LGPL-3.0 / GPL-2.0)",
     "https://github.com/basil00/WinDivert"),
    ("PyDivert", "pydivert", "LGPL-3.0-or-later (dual with GPL-2.0-or-later)",
     "https://github.com/ffalcinelli/pydivert"),
    ("psutil", "psutil", "BSD-3-Clause",
     "https://github.com/giampaolo/psutil"),
    ("Python", None, "PSF License",
     "https://www.python.org/downloads/source/"),
    ("Tcl/Tk", None, "Tcl/Tk licence (BSD-style)",
     "https://www.tcl-lang.org/software/tcltk/"),
    ("PyInstaller (bootloader)", None, "GPL-2.0+ with the bootloader exception",
     "https://github.com/pyinstaller/pyinstaller"),
)


def _module_version(name):
    """Version of an installed package, or ``-`` when it is not present here."""
    module = sys.modules.get(name)
    if module is None:
        try:
            import importlib
            module = importlib.import_module(name)
        except Exception:      # noqa: BLE001 - absence is an answer, not a failure
            return "-"
    return str(getattr(module, "__version__", "present"))


def _tk_version():
    try:
        import tkinter
        return str(tkinter.TkVersion)
    except Exception:          # noqa: BLE001 - a console build has no Tk
        return "-"


def component_rows():
    """``(name, version, licence, source_url)`` for every third-party component."""
    rows = []
    for name, module, licence, url in COMPONENTS:
        if module:
            version = _module_version(module)
        elif name == "Python":
            version = "%d.%d.%d" % sys.version_info[:3]
        elif name == "Tcl/Tk":
            version = _tk_version()
        else:
            version = "bundled"          # WinDivert ships inside PyDivert
        rows.append((name, version, licence, url))
    return rows


def _read(name):
    try:
        with open(resource_path(name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def license_text():
    """The Bean Network Tester licence, or an empty string if it is missing."""
    return _read(LICENSE_FILE)


def notices_text():
    """The third-party notices, or an empty string if they are missing."""
    return _read(NOTICES_FILE)


def licenses_dir():
    """Directory holding the full third-party licence texts."""
    return resource_path(LICENSES_DIR)


def cli_report():
    """Plain-text licensing report for ``--license`` (stdout is the data channel)."""
    lines = [license_text().rstrip(), "",
             "=" * 78, "THIRD-PARTY COMPONENTS IN THIS BUILD", "=" * 78, ""]
    width = max(len(name) for name, *_ in COMPONENTS)
    for name, version, licence, url in component_rows():
        lines.append("%-*s  %-10s  %s" % (width, name, version, licence))
        lines.append("%-*s  %-10s  source: %s" % (width, "", "", url))
    lines += ["",
              "Full licence texts: %s" % licenses_dir(),
              "Full notices:       %s" % resource_path(NOTICES_FILE),
              "",
              "Telemetry: none. This program sends no data anywhere."]
    return "\n".join(lines)
