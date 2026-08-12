"""The Chocolatey and WinGet package sources, and the renderer that fills them.

These files are published under our name to two feeds we do not control, so the
cost of a mistake is somebody else's moderation queue and, for the two lines that
matter, a user whose install does not work at all.

What is guarded here is what a reviewer cannot catch for us:

* no version number is typed into a package file (convention 34 - `VERSION.txt` is
  the only place a version may live, and a manifest with a stale one still parses);
* `ArchiveBinariesDependOnPath` stays set, because without it WinGet reaches the
  exe through a symlink and severs it from the `_internal` directory it needs;
* the nested path is the one the release actually builds, derived from `appinfo`
  rather than typed a second time;
* the Chocolatey scripts release the WinDivert driver before an upgrade, because
  the kernel holds the loaded `.sys` open and an open file cannot be deleted;
* the renderer refuses the two inputs that would look fine and be wrong: an unknown
  placeholder, and the previous release's `SHA256SUMS.txt`.
"""
import os
import re
import sys

import pytest
from fakes import ROOT, check

sys.path.insert(0, ROOT)
from beantester import appinfo                                    # noqa: E402
from tools import build_packages as bp                            # noqa: E402

# A real line from a real release, binary marker and all.
SUMS_LINE = ("94359ea633e2e9fbe10e02b81070208a7209de2c4c48b003d8ce4feb30876bed"
             "  *BeanNetworkTester-v{version}-windows-x64.zip\n")


def _sums(tmp_path, version):
    path = tmp_path / "SHA256SUMS.txt"
    path.write_text(SUMS_LINE.format(version=version), encoding="utf-8")
    return str(path)


def _rendered(tmp_path, monkeypatch):
    """Render into a throwaway directory and return {relative name: text}."""
    out = tmp_path / "out"
    monkeypatch.setattr(bp, "OUT_DIR", str(out))
    # A fixed date, so these tests answer "does it render" and not "is the changelog
    # closed for this version". The changelog reader has its own test below, which is
    # the one that should redden when a version is bumped before its section is dated.
    monkeypatch.setattr(bp, "release_date", lambda version: "2026-01-01")
    bp.build(_sums(tmp_path, appinfo.__version__))
    files = {}
    for base, _, names in os.walk(out):
        for name in names:
            path = os.path.join(base, name)
            files[os.path.relpath(path, out).replace(os.sep, "/")] = \
                open(path, encoding="utf-8").read()
    return files


def _sources():
    return [(rel, open(path, encoding="utf-8").read())
            for path, rel in bp.templates() if rel.endswith(bp.TEMPLATE_SUFFIX)]


# -- what must never be typed twice -------------------------------------------- #
def test_no_package_source_carries_a_version_number():
    offenders = [rel for rel, text in _sources()
                 if re.search(r"\b\d+\.\d+\.\d+\b", text.replace(bp.WINGET_SCHEMA, ""))]
    check("packaging sources hold no version literal", not offenders, f"({offenders})")


def test_every_placeholder_is_known_and_every_known_placeholder_is_used():
    table = set(bp.values(appinfo.__version__, "abc", "x-v1.zip"))
    used = set()
    for _, text in _sources():
        used |= {m.group(1) for m in bp.PLACEHOLDER.finditer(text)}
    check("no template uses a placeholder the renderer cannot fill",
          not used - table, f"({sorted(used - table)})")
    check("no renderer entry has stopped being used by any template",
          not table - used, f"({sorted(table - used)})")


# -- the two lines that decide whether an install works ------------------------- #
def test_the_winget_manifest_keeps_the_exe_with_its_siblings(tmp_path, monkeypatch):
    installer = _rendered(tmp_path, monkeypatch)["winget/installer.yaml"]
    check("ArchiveBinariesDependOnPath is set",
          "ArchiveBinariesDependOnPath: true" in installer)
    check("so the exe is not reached through a symlink",
          "PortableCommandAlias" not in installer,
          "(an alias implies the symlink this field exists to avoid)")


def test_the_nested_path_is_the_one_the_release_builds(tmp_path, monkeypatch):
    installer = _rendered(tmp_path, monkeypatch)["winget/installer.yaml"]
    expected = f"RelativeFilePath: {appinfo.TOOL_ID}/{appinfo.EXE_NAME}"
    check("the manifest points at the exe inside the archive's one directory",
          expected in installer, f"({expected})")


def test_the_chocolatey_scripts_release_the_driver_before_a_change(tmp_path, monkeypatch):
    files = _rendered(tmp_path, monkeypatch)
    before = files["chocolatey/tools/chocolateybeforemodify.ps1"]
    # Read the CODE, not the file. The first version of this check looked for the
    # flag anywhere in the text and passed on a script whose only mention of it was
    # the comment explaining why it is there - the mutation survived and said so.
    calls = [line for line in before.splitlines()
             if "$exe" in line and not line.strip().startswith("#")]
    check("the driver is released before an upgrade or uninstall",
          any("--cleanup-driver" in line for line in calls), f"({calls})")
    check("and a failure there cannot abort the operation",
          "$ErrorActionPreference = 'Continue'" in before and "try {" in before)


def test_the_download_is_checksummed(tmp_path, monkeypatch):
    install = _rendered(tmp_path, monkeypatch)["chocolatey/tools/chocolateyinstall.ps1"]
    check("the archive is verified against the release's own hash",
          "-Checksum64 '94359ea6" in install and "-ChecksumType64 'sha256'" in install)


# -- the inputs that would look fine and be wrong ------------------------------- #
def test_the_binary_marker_never_reaches_the_url(tmp_path, monkeypatch):
    """`sha256sum` writes `<hash>  *<file>`, and that star is not part of the name."""
    files = _rendered(tmp_path, monkeypatch)
    for name, text in files.items():
        for line in text.splitlines():
            if "://" in line:
                check(f"{name} has a clean URL", "*" not in line, f"({line.strip()})")


def test_nothing_unfilled_survives_rendering(tmp_path, monkeypatch):
    for name, text in _rendered(tmp_path, monkeypatch).items():
        check(f"{name} has no placeholder left", "{{" not in text)


def test_the_previous_releases_checksum_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(bp, "OUT_DIR", str(tmp_path / "out"))
    stale = _sums(tmp_path, "0.0.1")            # a real file, for the wrong release
    with pytest.raises(SystemExit) as refused:
        bp.build(stale)
    check("the mismatch names the asset", "0.0.1" in str(refused.value),
          f"({refused.value})")


def test_an_unknown_placeholder_is_an_error_not_an_empty_string():
    table = bp.values(appinfo.__version__, "abc", "x-v1.zip")
    with pytest.raises(SystemExit) as refused:
        bp.render("id: {{NOT_A_REAL_KEY}}", table, "made-up.yaml")
    check("the failure names the placeholder", "NOT_A_REAL_KEY" in str(refused.value),
          f"({refused.value})")


def test_the_release_date_comes_from_the_changelog():
    """One reader, not a second answer typed into a manifest.

    This is also the test that reddens if a version is bumped before its changelog
    section is dated - deliberately alone, so that failure names itself instead of
    taking the rendering tests down with it.
    """
    date = bp.release_date(appinfo.__version__)
    check("the date looks like a date", re.fullmatch(r"\d{4}-\d{2}-\d{2}", date), f"({date})")


def test_the_package_sources_are_tracked_by_git():
    """These files are not internal tooling, and three separate things need them.

    Chocolatey's moderation asks for `packageSourceUrl` to point at where the
    package source lives (rule CPMR0040, a Guideline), so a private path there
    would be a dead link - worse than the field being absent. The tests above read
    these files, and CI runs them on a fresh clone. And the whole point of a
    package source is that somebody other than us can see what the package does to
    their machine.

    So `packaging/` belongs where `tools/` is, not where `internal_tools/` is: the
    failure of getting this wrong does not show up here, where the files exist. It
    shows up on somebody else's clone, as a missing file rather than a reason.
    """
    import subprocess
    sources = [rel for _, rel in bp.templates()]
    check("there are package sources to check", len(sources) >= 6, f"({sources})")
    for relative in sorted(sources):
        path = f"packaging/{relative}".replace(os.sep, "/")
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", path],
                                 cwd=ROOT, capture_output=True, text=True)
        check(f"{path} is tracked by git", tracked.returncode == 0,
              "(ignored or untracked - a fresh clone and the Chocolatey moderators "
              "would both find nothing)")


def test_rendering_onto_another_drive_is_not_a_crash(monkeypatch):
    """Windows raises when two paths are on different drives, and CI is that case.

    The repository sits on one drive on the Windows runner and the temporary
    directory on another, so `os.path.relpath` - used only to print what was
    written - raised `ValueError` and took six tests with it. It passed on this
    machine, where both are on C:, and on Linux, where drives do not exist.
    """
    def different_drive(path, start):
        raise ValueError("path is on mount 'C:', start on mount 'D:'")

    monkeypatch.setattr(os.path, "relpath", different_drive)
    shown = bp.display_path(os.path.join("X:", "out", "installer.yaml"))
    check("it falls back to the absolute path instead of raising",
          shown.endswith("installer.yaml"), f"({shown})")
