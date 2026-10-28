"""What the Linux bundle takes from the system instead of carrying - and the check
that a built bundle keeps to it.

``BeanNetworkTester.spec`` drops ``FROM_SYSTEM`` from what PyInstaller collects on
Linux, and CI runs ``check`` on the folder it built, so the list is in one place
and a bundle that drifts from it fails the build instead of a person's desktop.

Why these, MEASURED 2026-10-28 with a bundle built on Ubuntu 24.04 and run on
Ubuntu 26.04, Fedora 44 and Arch:

* A bundled fontconfig reads the SYSTEM's configuration files, and an older one
  rejects a newer system's: on Arch (fontconfig 2.18) the window printed 15
  "Fontconfig warning: ... invalid attribute 'xsi:nil'" lines and dropped those
  rules. freetype goes with it (a system fontconfig needs its own), and so do what
  the two read with: expat, libpng, brotli and bzip2 (PyInstaller collects
  freetype's libraries before the spec drops freetype - measured: libbz2 stayed).
  Every desktop has all of them.
* libXft stays: without it in the bundle, a system that does not have it (Fedora
  44 and Arch as installed, both measured) opened no window at all.
* libXau and libXdmcp: the system's libxcb - which PyInstaller never bundles -
  needs both (ldd on Ubuntu 26.04 and Arch), so every system that can show a
  window has them. libbsd and libmd came only with Ubuntu 24.04's libXdmcp.

``NOT_NEEDED_MODULES`` are standard modules the program never uses - no bz2, lzma
or zstd anywhere in it - which the standard library only imports when it can
(``shutil``, ``zipfile``). Left out on Linux, with the libraries they would bring -
and BLT, a Tk extension Ubuntu's python3-tk installs and PyInstaller then collected
(measured in an ubuntu:24.04 image); nothing here loads it.

``MUST_CARRY`` are the parts a bundle without them would ship broken: Tk and Xft
for the window, and pydivert's ``libebpfdivert.so`` for any capture.

    python tools/linux_bundle.py check dist/BeanNetworkTester
"""
import os
import sys

FROM_SYSTEM = ("libfontconfig.so", "libfreetype.so", "libexpat.so", "libpng16.so",
               "libbrotlicommon.so", "libbrotlidec.so", "libbz2.so",
               "libXau.so", "libXdmcp.so", "libbsd.so", "libmd.so")

NOT_NEEDED_MODULES = ("_bz2", "_lzma", "_zstd")
NOT_NEEDED_LIBRARIES = ("liblzma.so", "libzstd.so", "libBLT")

MUST_CARRY = ("libtk", "libXft.so", "libebpfdivert.so")


def taken_from_system(name):
    """True for a library file the bundle must not carry (by its file name)."""
    return os.path.basename(name).startswith(FROM_SYSTEM)


def not_needed(name):
    """True for a module or library the program never uses (by its file name)."""
    base = os.path.basename(name)
    return (base.startswith(NOT_NEEDED_LIBRARIES)
            or any(base.startswith(module + ".") for module in NOT_NEEDED_MODULES))


def libraries(folder):
    """The file names of every shared library under ``folder``."""
    found = []
    for _base, _dirs, files in os.walk(folder):
        found.extend(name for name in files if ".so" in name)
    return sorted(found)


def problems(folder):
    """What is wrong with the bundle in ``folder``: an empty list when nothing is."""
    if not os.path.isdir(folder):
        return [f"{folder}: no such folder"]
    names = libraries(folder)
    wrong = [f"carries {name}, which must come from the system"
             for name in names if taken_from_system(name)]
    wrong += [f"carries {name}, which the program never uses"
              for name in names if not_needed(name)]
    missing = [f"does not carry {part}" for part in MUST_CARRY
               if not any(name.startswith(part) for name in names)]
    return wrong + missing


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] != "check":
        print("usage: linux_bundle.py check <bundle folder>", file=sys.stderr)
        return 2
    found = problems(argv[1])
    for line in found:
        print(f"linux bundle: {line}", file=sys.stderr)
    if not found:
        print(f"linux bundle: {len(libraries(argv[1]))} libraries, none of them the "
              f"system's own, Tk, Xft and libebpfdivert present")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
