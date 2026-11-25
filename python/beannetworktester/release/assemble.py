"""Lays out the wheels a release puts on PyPI.

beannetworktester gets one wheel for Windows x64 and one for Linux x64, each with the
release's own program inside, unchanged (on Windows the signed exe), and one wheel
with no program, which pip takes on every other system. .github/workflows/pypi.yml
runs this on the archives it downloaded from the release and checked, and nothing
here fetches or publishes anything.

Written with zipfile rather than a build backend: the program has to keep its files
and its execute bit exactly as the release has them, which a backend for Python code
does not do, and nothing else is needed.

    python assemble.py version <version>                                  as PyPI writes it
    python assemble.py build <version> <windows.zip> <linux.tar.gz> <out> the three wheels
"""

from __future__ import annotations

import base64
import hashlib
import re
import stat
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
REPO = PACKAGE.parent.parent
SOURCE = PACKAGE / "src" / "beannetworktester"

# The program's folder in both archives, and its executable in each.
TOP = "BeanNetworkTester"
PROGRAMS = {"win_amd64": f"{TOP}/BeanNetworkTester.exe", "linux": f"{TOP}/BeanNetworkTester"}
# The Linux package is built on Ubuntu 24.04 (release.yml), whose C library is glibc
# 2.39, so the wheel says it needs at least that. A guard holds this to release.yml.
LINUX_TAG = "manylinux_2_39_x86_64"
INSIDE = "beannetworktester/program/"

VERSION_SHAPE = re.compile(r"^(\d+\.\d+\.\d+)(?:-rc\.(\d+))?$")
# Every entry of every wheel carries this date, so the same release gives the same
# bytes. The zip format starts in 1980.
STAMP = (1980, 1, 1, 0, 0, 0)


def fail(message: str) -> None:
    raise SystemExit(f"assemble: {message}")


def pep440(version: str) -> str:
    """1.1.0 stays 1.1.0, 1.1.0-rc.1 is 1.1.0rc1, anything else is refused."""
    found = VERSION_SHAPE.match((version or "").removeprefix("v"))
    if not found:
        fail(f"{version!r} is not a release version, such as 1.1.0 or 1.1.0-rc.1")
    core, rc = found.groups()
    return core if rc is None else f"{core}rc{int(rc)}"


def _project() -> dict:
    with open(PACKAGE / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)["project"]


def metadata(project: dict, version: str, readme: str) -> bytes:
    lines = [
        "Metadata-Version: 2.4",
        f"Name: {project['name']}",
        f"Version: {version}",
        f"Summary: {project['description']}",
        f"Author: {', '.join(a['name'] for a in project.get('authors', []))}",
        f"License-Expression: {project['license']}",
        "License-File: LICENSE",
        f"Keywords: {','.join(project.get('keywords', []))}",
        *(f"Classifier: {c}" for c in project.get("classifiers", [])),
        *(f"Project-URL: {label}, {url}" for label, url in project.get("urls", {}).items()),
        f"Requires-Python: {project['requires-python']}",
        "Description-Content-Type: text/markdown",
    ]
    for line in lines:
        if "\n" in line or "\r" in line:
            fail(f"a metadata field holds a line break: {line!r}")
    return ("\n".join(lines) + "\n\n" + readme).encode("utf-8")


def entry_points(project: dict) -> bytes:
    text = "".join(f"[{group}]\n" + "".join(f"{k} = {v}\n" for k, v in entries.items()) + "\n"
                   for group, entries in project.get("entry-points", {}).items())
    return text.encode("utf-8")


def _record_hash(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def write_wheel(out: Path, version: str, tag: str, files: list[tuple[str, bytes, bool]],
                info: list[tuple[str, bytes]]) -> Path:
    """One wheel. ``files`` are installed as they are, ``info`` goes into the .dist-info."""
    stem = f"beannetworktester-{version}"
    dist_info = f"{stem}.dist-info"
    wheel_text = ("Wheel-Version: 1.0\nGenerator: beannetworktester release/assemble.py\n"
                  f"Root-Is-Purelib: {'true' if tag == 'any' else 'false'}\n"
                  f"Tag: py3-none-{tag}\n")
    entries = sorted(files) + [(f"{dist_info}/{name}", data, False) for name, data in info]
    entries.append((f"{dist_info}/WHEEL", wheel_text.encode(), False))
    names = [name for name, _, _ in entries]
    if len(set(names)) != len(names):
        fail(f"the wheel for {tag} would hold one name twice")
    record = "".join(f"{name},{_record_hash(data)},{len(data)}\n" for name, data, _ in entries)
    record += f"{dist_info}/RECORD,,\n"
    entries.append((f"{dist_info}/RECORD", record.encode(), False))
    path = out / f"{stem}-py3-none-{tag}.whl"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as wheel:
        for name, data, executable in entries:
            entry = zipfile.ZipInfo(name, date_time=STAMP)
            entry.compress_type = zipfile.ZIP_DEFLATED
            # Made on Unix whatever system writes it: an entry marked as made on
            # MS-DOS is installed by uv without its execute bit, where pip keeps it.
            entry.create_system = 3
            entry.external_attr = ((0o755 if executable else 0o644) | stat.S_IFREG) << 16
            wheel.writestr(entry, data)
    return path


def code() -> list[tuple[str, bytes, bool]]:
    files = [(f"beannetworktester/{path.name}", path.read_bytes(), False)
             for path in sorted(SOURCE.iterdir())
             if path.is_file() and (path.suffix == ".py" or path.name == "py.typed")]
    if not any(name.endswith("/__init__.py") for name, _, _ in files):
        fail(f"{SOURCE} holds no __init__.py")
    return files


def windows_program(archive: Path) -> list[tuple[str, bytes, bool]]:
    files = []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            if not info.filename.startswith(TOP + "/"):
                fail(f"{archive.name} holds {info.filename} outside {TOP}/")
            files.append((INSIDE + info.filename, z.read(info),
                          info.filename == PROGRAMS["win_amd64"]))
    _has_program(files, PROGRAMS["win_amd64"], archive)
    return files


def linux_program(archive: Path) -> list[tuple[str, bytes, bool]]:
    files = []
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if member.issym() or member.islnk():
                fail(f"{archive.name} holds a link, {member.name}, and a wheel cannot hold one")
            if member.isdir():
                continue
            if not member.isfile() or not member.name.startswith(TOP + "/"):
                fail(f"{archive.name} holds {member.name}, which is not a file inside {TOP}/")
            handle = tar.extractfile(member)
            if handle is None:
                fail(f"{archive.name}: {member.name} cannot be read")
            files.append((INSIDE + member.name, handle.read(), bool(member.mode & 0o111)))
    _has_program(files, PROGRAMS["linux"], archive)
    return files


def _has_program(files: list[tuple[str, bytes, bool]], program: str, archive: Path) -> None:
    if not any(name == INSIDE + program and executable for name, _, executable in files):
        fail(f"{archive.name} has no executable {program}")


def build(version: str, windows_zip: Path, linux_tgz: Path, out: Path) -> list[Path]:
    """The three wheels of a release, Windows first, the one without a program last."""
    wheel_version = pep440(version)
    out.mkdir(parents=True, exist_ok=False)
    project = _project()
    info = [("METADATA", metadata(project, wheel_version,
                                  (PACKAGE / "README.md").read_text(encoding="utf-8"))),
            ("entry_points.txt", entry_points(project)),
            ("licenses/LICENSE", (REPO / "LICENSE").read_bytes())]
    ours = code()
    return [write_wheel(out, wheel_version, "win_amd64", ours + windows_program(windows_zip), info),
            write_wheel(out, wheel_version, LINUX_TAG, ours + linux_program(linux_tgz), info),
            write_wheel(out, wheel_version, "any", ours, info)]


def main(argv: list[str]) -> None:
    if argv[:1] == ["version"] and len(argv) == 2:
        print(pep440(argv[1]))
    elif argv[:1] == ["build"] and len(argv) == 5:
        for path in build(argv[1], Path(argv[2]), Path(argv[3]), Path(argv[4])):
            print(path)
    else:
        fail("usage: assemble.py version <version> | "
             "build <version> <windows.zip> <linux.tar.gz> <out>")


if __name__ == "__main__":
    main(sys.argv[1:])
