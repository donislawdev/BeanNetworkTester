"""The licensing surface: ``--license``, and the texts it must actually find.

Why this file exists (measured 2026-08-01): ``legal.cli_report``, ``license_text``
and ``notices_text`` were called by NO test. What was tested is that ``LICENSE``
and ``THIRD-PARTY-NOTICES.md`` EXIST in the tree (``os.path.exists`` from the repo
root) - but the code reads them through ``resource_path()``, which is a different
resolution, and ``legal._read`` answers an ``OSError`` with an empty string.

So the failure mode was: the files ship, the paths stop resolving (a frozen build,
a renamed constant), ``--license`` prints an empty licence, and the whole suite
stays green. That is an LGPL obligation towards the holder of the BINARY failing
silently - convention 35 calls that a blocker, not a formality.

``--doctor`` had a runtime test; ``--license``, the flag with legal weight, did not.
"""
import io
import json

from beantester import appinfo, exitcodes, legal
from beantester.cli import run_cli
from fakes import check


def cli(argv):
    out, err = io.StringIO(), io.StringIO()
    code = run_cli(argv, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


# -- the texts resolve at run time, not just on disk ------------------------- #


def test_the_licence_and_notices_resolve_through_resource_path():
    """``_read`` swallows an OSError into "", so an unresolvable path is silent."""
    licence = legal.license_text()
    notices = legal.notices_text()
    check("LICENSE is readable through resource_path (not an empty fallback)",
          len(licence) > 1000, f"({len(licence)} chars)")
    check("LICENSE really is the GPL text the project claims",
          "GNU GENERAL PUBLIC LICENSE" in licence)
    check("THIRD-PARTY-NOTICES is readable through resource_path",
          len(notices) > 200, f"({len(notices)} chars)")


def test_every_shipped_component_is_named_with_a_version_and_a_source():
    """The obligation is not "a licence exists" - it is naming the exact version
    the user was given, so they can fetch that source and replace it."""
    rows = legal.component_rows()
    names = [name for name, *_ in rows]
    for required in ("WinDivert", "PyDivert", "psutil", "Python"):
        check(f"{required} is declared", required in names, f"({names})")
    for name, version, licence, url in rows:
        check(f"{name} carries a version", bool(str(version).strip()))
        check(f"{name} carries a licence", bool(str(licence).strip()))
        check(f"{name} carries a source URL", str(url).startswith("http"), f"({url})")


def test_the_declared_windivert_version_matches_the_driver_we_ship():
    """The LGPL obligation is to name the EXACT version the user was given.

    Until 2026-08-11 the report said "bundled", which is true and useless to
    somebody trying to fetch that source and rebuild it. The number is pinned in
    `legal.WINDIVERT_VERSION` because it is a property of the build, and this test
    is what stops it rotting: it reads the version resource of the driver in the
    INSTALLED pydivert and requires the two to agree.

    Note which file is asked. `WinDivert64.dll` carries NO version resource at all
    - only `WinDivert64.sys` does - which is also why a bundle scanner reports the
    DLL with an unknown version.
    """
    import os
    import sys as _sys

    from beantester import legal as _legal

    found = _windivert_binaries()
    if found is None or not _sys.platform.startswith("win"):
        return                      # Linux runner: the Windows-only dep is absent
    relative, _names = found
    import pydivert
    root = os.path.dirname(os.path.dirname(os.path.abspath(pydivert.__file__)))
    driver = os.path.join(root, relative.replace("/", os.sep), "WinDivert64.sys")
    if not os.path.exists(driver):
        return

    import ctypes
    import ctypes.wintypes as wintypes
    version_dll = ctypes.WinDLL("version")
    size = version_dll.GetFileVersionInfoSizeW(driver, None)
    check("the driver carries a version resource at all", size > 0, f"({size})")
    if not size:
        return
    buffer = ctypes.create_string_buffer(size)
    version_dll.GetFileVersionInfoW(driver, 0, size, buffer)
    block = ctypes.c_void_p()
    length = wintypes.UINT()

    # 🔴 The STRING block, not the numeric one. A version resource carries both,
    # and for this driver they DISAGREE: VS_FIXEDFILEINFO says 2.0.0.0 while
    # StringFileInfo says "2.2", which is the version WinDivert is released and
    # documented under. The first draft of this test read the numeric field and
    # reported a mismatch that did not exist - the instrument, not the data.
    version_dll.VerQueryValueW(buffer, "\\VarFileInfo\\Translation",
                               ctypes.byref(block), ctypes.byref(length))
    codes = ctypes.cast(block, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
    key = "\\StringFileInfo\\%04x%04x\\FileVersion" % (codes[0], codes[1])
    text = ctypes.c_wchar_p()
    found_string = version_dll.VerQueryValueW(buffer, key,
                                              ctypes.byref(text), ctypes.byref(length))
    check("the driver's version resource carries a FileVersion string",
          bool(found_string) and bool(text.value), f"({key})")
    if not found_string:
        return
    reported = str(text.value).strip()

    check("the declared WinDivert version is the one on disk",
          reported == _legal.WINDIVERT_VERSION,
          f"(driver says {reported!r}, registry says {_legal.WINDIVERT_VERSION!r})")


def test_the_registry_and_the_notices_describe_the_same_set():
    """Three lists have to agree, and until 2026-08-11 they silently did not.

    `legal.COMPONENTS` is what `--license` reports, THIRD-PARTY-NOTICES.md is what
    the user reads, and `licenses/` is what they can open. Scanning the BUILT
    BUNDLE with Syft found three components shipping in every release so far that
    no list mentioned: zlib, libffi and the Microsoft C runtime. All permissive or
    redistributable, so nothing was breached - the defect was the CLAIM of
    completeness, which is the kind that survives review because each file looks
    fine on its own.

    This test cannot see the bundle, so it cannot find the next unlisted DLL. What
    it does is cheaper and still worth having: it stops the three lists drifting
    apart once somebody adds a component to one of them.
    """
    import os
    from fakes import ROOT

    notices = open(os.path.join(ROOT, "THIRD-PARTY-NOTICES.md"),
                   encoding="utf-8").read()
    for name, *_ in legal.COMPONENTS:
        # The notices head each component with "## <name>", sometimes followed by
        # the file names - so match the start, not the whole line.
        stem = name.split(" (")[0]
        check(f"the notices have a section for {stem}",
              ("## " + stem) in notices, f"({stem})")

    texts = sorted(f for f in os.listdir(os.path.join(ROOT, "licenses"))
                   if f.endswith(".txt"))
    for text in texts:
        check(f"licenses/{text} is referenced by the notices",
              text in notices, f"({text} ships but nothing points at it)")
    report = legal.cli_report()
    check("report opens with the licence itself",
          "GNU GENERAL PUBLIC LICENSE" in report)
    for name, _version, _lic, url in legal.component_rows():
        check(f"report names {name}", name in report)
        check(f"report names the source of {name}", url in report)
    check("report states there is no telemetry (convention 36)",
          "Telemetry: none" in report, f"({report[-200:]!r})")


# -- the flag ---------------------------------------------------------------- #


def test_license_flag_prints_the_report_to_stdout_and_exits_ok():
    code, out, err = cli(["--license"])
    check("--license exits OK", code == exitcodes.OK, f"(code={code})")
    check("the report goes to STDOUT (it is data, not log)",
          "GNU GENERAL PUBLIC LICENSE" in out, f"({out[:120]!r})")
    check("nothing of it leaks into stderr", "GENERAL PUBLIC" not in err)


def test_license_flag_never_touches_the_driver():
    """A licence audit must work on a machine with no WinDivert and no admin."""
    code, out, _ = cli(["--license"])
    check("--license succeeds without a driver", code == exitcodes.OK)
    check("and without opening a session", "packets" not in out.lower())


def test_license_as_json_is_one_parsable_record_with_every_component():
    """A corporate licence audit is a script more often than a person, so the
    machine-readable shape is part of the NDJSON contract, not a nicety."""
    code, out, _ = cli(["--license", "--format", "json"])
    check("--license --format json exits OK", code == exitcodes.OK, f"(code={code})")
    lines = [l for l in out.splitlines() if l.strip()]
    check("exactly one NDJSON record", len(lines) == 1, f"({len(lines)} lines)")

    record = json.loads(lines[0])
    check("the record names itself", record.get("event") == "license", f"({record.get('event')})")
    check("it carries the project licence",
          record.get("license") == appinfo.LICENSE_NAME, f"({record.get('license')})")
    check("it states no telemetry", record.get("telemetry") is False)

    shipped = {c["name"] for c in record.get("components", [])}
    expected = {name for name, *_ in legal.COMPONENTS}
    check("every component in the registry reaches the JSON", shipped == expected,
          f"(missing={sorted(expected - shipped)}, extra={sorted(shipped - expected)})")
    for component in record["components"]:
        check(f"{component['name']} carries source + licence in JSON",
              component.get("source", "").startswith("http")
              and bool(component.get("license")), f"({component})")


# -- the replacement instructions have to point at the real files ------------ #


def _windivert_binaries():
    """Where the WinDivert files sit inside the installed pydivert package.

    Returns ``(relative directory, {filenames})`` using forward slashes, or
    ``None`` when pydivert is absent (it is a Windows-only dependency, so the
    Linux runner has nothing to check).

    Read from the INSTALLED package rather than from a path typed here, because
    the whole failure this guards is the package moving its files while our
    instructions stay where they were.
    """
    import os
    try:
        import pydivert
    except ImportError:
        return None
    root = os.path.dirname(os.path.dirname(os.path.abspath(pydivert.__file__)))
    found = {}
    for dirpath, _dirnames, filenames in os.walk(os.path.dirname(pydivert.__file__)):
        for name in filenames:
            if name.lower().startswith("windivert") and name.lower().endswith((".dll", ".sys")):
                rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
                found.setdefault(rel, set()).add(name)
    return next(iter(found.items())) if len(found) == 1 else (None, found)


def test_the_notices_name_the_windivert_files_that_are_really_shipped():
    r"""An LGPL right you cannot follow the directions to is not much of a right.

    Convention 35 exists because these libraries have to be REPLACEABLE by the
    holder of the binary, and the notices are the instructions for doing it.
    Measured 2026-08-04: they named ``WinDivert.dll`` in ``_internal\pydivert\``
    while the build ships ``WinDivert64.dll`` in
    ``_internal\pydivert\windivert_dll\`` - wrong filename, wrong folder. Nobody
    noticed because nothing compared the document with the package.

    PyInstaller lays a collected package out exactly as it is installed, so the
    installed tree is the authority here and no PyInstaller import is needed.
    """
    result = _windivert_binaries()
    if result is None:
        return                      # pydivert is Windows-only; nothing shipped here
    rel_dir, names = result
    check("pydivert keeps its WinDivert files in one place", bool(rel_dir),
          f"(found in several: {names})")

    notices = legal.notices_text()
    check("notices: the text is readable at all", len(notices) > 500,
          f"({len(notices)} chars)")

    windows_dir = "_internal\\" + rel_dir.replace("/", "\\")
    check(f"notices: name the folder the files are really in ({windows_dir})",
          windows_dir in notices, "(the replacement instructions point elsewhere)")
    for name in sorted(names):
        check(f"notices: name the file that is really shipped ({name})",
              name in notices, "(a user would look for a file that is not there)")
    # ...and do not still name a file that no longer exists
    stale = [n for n in ("WinDivert.dll", "WinDivert32.dll")
             if n not in names and n in notices]
    check("notices: no longer name a WinDivert file this build does not ship",
          not stale, f"({stale})")


def test_the_written_offer_lasts_as_long_as_the_licence_demands():
    """GPLv3 section 6(b), which LGPLv3 incorporates: an offer of source must be
    "valid for at least three years".

    Ours said "for as long as this release is distributed", which is shorter than
    the licence allows an offer to be. The offer is belt and braces - section 6(d)
    is already satisfied by naming the exact version and where its source lives -
    but a promise printed in a public document is one somebody may rely on, so it
    has to be at least what the licence requires.
    """
    notices = legal.notices_text()
    check("notices: the written offer names the three-year floor",
          "three years" in notices,
          "(an offer weaker than GPLv3 section 6(b) allows)")
