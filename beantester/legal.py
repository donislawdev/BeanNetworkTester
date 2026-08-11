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

# The driver version we ship, from `WinDivert64.sys`'s own version resource. The
# LGPL obligation is to name the exact version the user was given, and until
# 2026-08-11 this said "bundled" - true, and useless to somebody trying to fetch
# that source and rebuild it.
WINDIVERT_VERSION = "2.2"

# The components we ship, in the order a reader cares about. ``module`` is the
# import name used to report the real version at run time (None = not a Python
# package, so the version is fixed or reported by other means).
COMPONENTS = (
    # (name, module, licence used, where the source lives)
    # WinDivert has no importable module, and its DLL carries no version resource -
    # only the DRIVER does. `WinDivert64.sys` reports FileVersion "2.2" (company
    # "Basil"), read from the shipped file on 2026-08-11. Pinned here rather than
    # read at run time because it is a property of the BUILD, and a test keeps it
    # honest: `test_license_surface.py` compares this string against the version
    # the installed pydivert's driver actually reports, so it cannot rot silently.
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
    # 🔴 The three below were found by SCANNING THE BUILT BUNDLE (Syft, 2026-08-11),
    # not by reading a manifest - they arrive with the CPython Windows runtime and
    # no requirements file mentions them. They shipped in every release so far while
    # this list claimed to be complete. Permissive or redistributable every one, so
    # nothing was breached; the defect was the claim, not the licences.
    ("zlib", None, "zlib licence",
     "https://www.zlib.net/"),
    ("libffi", None, "MIT-style (text inside Python-LICENSE.txt)",
     "https://github.com/libffi/libffi"),
    # 42 files, over half the bundle by count: ucrtbase, VCRUNTIME140(_1) and 39
    # `api-ms-win-*` ApiSet stubs. The stubs were nearly missed - they are easy to
    # read as Windows itself rather than as something we redistribute.
    ("Microsoft C Runtime", None,
     "Microsoft redistributable (ucrtbase, VCRUNTIME140, api-ms-win-* stubs)",
     "https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files"),
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


def _zlib_version():
    """The zlib the build links against.

    `ZLIB_VERSION` can carry a suffix - CPython 3.14 reports "1.3.1.zlib-ng",
    because the `zlib` MODULE is built against zlib-ng while `zlib1.dll` beside
    the exe is genuine zlib (its own strings say "deflate 1.3.1 Copyright
    1995-2024 Jean-loup Gailly and Mark Adler"). Both carry the zlib licence, so
    one entry covers them; the suffix is kept rather than trimmed, because it is
    the honest answer to "what is in this build".
    """
    try:
        import zlib
        return str(zlib.ZLIB_VERSION)
    except Exception:              # noqa: BLE001 - absence is an answer
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
        elif name == "zlib":
            version = _zlib_version()
        elif name == "WinDivert":
            version = WINDIVERT_VERSION
        else:
            version = "bundled"          # libffi and the MS runtime carry no version
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
