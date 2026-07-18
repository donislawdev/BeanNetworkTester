#!/usr/bin/env python3
"""Build Bean Network Tester into a shippable folder.

Run it from the repository root:

    python build.py

What it does, and why each step is here rather than left to PyInstaller:

1. Read and VALIDATE ``VERSION.txt`` first. It is the only place a version number
   lives (see ``beantester/appinfo.py``). A malformed file stops the build with a
   clear message instead of a cryptic traceback deep inside the spec.

2. Run PyInstaller against ``BeanNetworkTester.spec`` (onedir, console subsystem,
   asInvoker - the three choices documented in the spec).

3. Copy the human-facing files NEXT TO the exe. PyInstaller 6 puts everything in
   ``datas`` inside ``dist/BeanNetworkTester/_internal/``. A CHANGELOG or a LICENCE
   the user has to go spelunking for is one they never read - and the LGPL notice
   is an obligation, not a nicety. So ``CHANGELOG.md``, ``LICENSE``,
   ``THIRD-PARTY-NOTICES.md``, ``licenses/`` and ``scenarios/`` are placed right
   beside ``BeanNetworkTester.exe`` where a person will actually find them.

4. ASSERT the package is complete. A release missing its licence, its notices or
   its scenarios is a bad release; better to fail the build than to ship it.

5. Write ``SHA256SUMS.txt`` and (optionally) zip the folder, so the download on
   the website can be verified. An unsigned exe that asks for Administrator and
   loads a network driver WILL trip SmartScreen; a published checksum is the
   cheapest way for a cautious user to trust the file.

This is deliberately plain Python with no third-party dependencies beyond
PyInstaller itself, so the same script runs locally and in CI.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist", "BeanNetworkTester")
EXE = os.path.join(DIST, "BeanNetworkTester.exe")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# Files/dirs copied next to the exe (source path relative to ROOT).
SHIP_BESIDE_EXE = ["CHANGELOG.md", "LICENSE", "THIRD-PARTY-NOTICES.md",
                   "licenses", "scenarios"]
# What the finished package MUST contain (relative to DIST).
REQUIRED_IN_PACKAGE = ["BeanNetworkTester.exe", "CHANGELOG.md", "LICENSE",
                       "THIRD-PARTY-NOTICES.md", "licenses", "scenarios"]


def fail(message):
    print(f"build.py: ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_version():
    path = os.path.join(ROOT, "VERSION.txt")
    try:
        with open(path, encoding="utf-8") as f:
            version = f.read().strip()
    except OSError:
        fail("VERSION.txt is missing. Create it with a single line like 0.2.0")
    if not VERSION_RE.match(version):
        fail(f"VERSION.txt must be a single x.y.z line, got {version!r}")
    return version


def run_pyinstaller():
    print("build.py: running PyInstaller...")
    try:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                        "BeanNetworkTester.spec"], cwd=ROOT, check=True)
    except FileNotFoundError:
        fail("PyInstaller is not installed. Run: pip install pyinstaller")
    except subprocess.CalledProcessError as exc:
        fail(f"PyInstaller failed (exit {exc.returncode})")


def copy_beside_exe():
    for name in SHIP_BESIDE_EXE:
        src = os.path.join(ROOT, name)
        dst = os.path.join(DIST, name)
        if not os.path.exists(src):
            fail(f"cannot ship {name!r}: it does not exist in the repo")
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        print(f"build.py: placed {name} next to the exe")


def verify_package():
    missing = [name for name in REQUIRED_IN_PACKAGE
               if not os.path.exists(os.path.join(DIST, name))]
    if missing:
        fail(f"the package is incomplete, missing: {', '.join(missing)}")
    # The WinDivert driver must travel with the app, never in %TEMP% - and its
    # presence is also what makes the LGPL library replaceable in place.
    hits = []
    for dirpath, _dirs, files in os.walk(DIST):
        hits += [f for f in files if f.lower().startswith("windivert")]
    if not hits:
        print("build.py: WARNING: no WinDivert* files found in the bundle "
              "(expected on a non-Windows build host; required on Windows).")
    print("build.py: package contents verified")


def write_checksums():
    lines = []
    for dirpath, _dirs, files in os.walk(DIST):
        for name in sorted(files):
            if name in ("SHA256SUMS.txt",):
                continue
            path = os.path.join(dirpath, name)
            digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
            rel = os.path.relpath(path, DIST).replace(os.sep, "/")
            lines.append(f"{digest}  {rel}")
    out = os.path.join(DIST, "SHA256SUMS.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    # The exe's own hash is the one people check; surface it.
    if os.path.exists(EXE):
        exe_hash = hashlib.sha256(open(EXE, "rb").read()).hexdigest()
        print(f"build.py: BeanNetworkTester.exe SHA-256:\n  {exe_hash}")


def make_zip(version):
    zip_path = os.path.join(ROOT, "dist", f"BeanNetworkTester-{version}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _dirs, files in os.walk(DIST):
            for name in files:
                path = os.path.join(dirpath, name)
                arc = os.path.join("BeanNetworkTester",
                                   os.path.relpath(path, DIST))
                z.write(path, arc)
    print(f"build.py: wrote {os.path.relpath(zip_path, ROOT)}")


def main():
    version = read_version()
    print(f"build.py: building Bean Network Tester {version}")
    run_pyinstaller()
    if not os.path.isdir(DIST):
        fail(f"expected build output at {DIST}, but it is not there")
    copy_beside_exe()
    verify_package()
    write_checksums()
    if "--zip" in sys.argv:
        make_zip(version)
    print(f"build.py: done. Package: {DIST}")


if __name__ == "__main__":
    main()
