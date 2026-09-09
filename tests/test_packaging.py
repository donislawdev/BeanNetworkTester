"""The Chocolatey, WinGet and MSI package sources, and the renderer that fills them.

These files are published under our name to feeds we do not control, so the cost of
a mistake is somebody else's moderation queue and, for the two lines that matter, a
user whose install does not work at all. The MSI raises that cost again: it is what
corporate deployment pushes to machines nobody will ever log into, and its
UpgradeCode is the one value here that cannot be corrected after the fact.

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


def test_the_chocolatey_icon_is_a_pinned_cdn_url(tmp_path, monkeypatch):
    """Not `github.com/.../raw/`, and not a branch. Both were wrong until 2026-09-05.

    Chocolatey's moderation held 0.5.0 back over the first half: it treats
    `github.com/<owner>/<repo>/raw/...` exactly as `raw.githubusercontent.com`, and
    neither is a CDN. The second half is the one nobody had complained about, and it
    is the one that bites later - an icon pinned to a BRANCH follows whatever that
    branch does next, under a package that is already approved and out of reach.
    """
    nuspec = _rendered(tmp_path, monkeypatch)["chocolatey/bean-network-tester.nuspec"]
    found = re.search(r"<iconUrl>(.*?)</iconUrl>", nuspec)
    check("the nuspec carries an icon at all", found is not None)
    url = found.group(1) if found else ""
    for host in ("raw.githubusercontent.com", "github.com"):
        check(f"the icon is not served from {host}", host not in url, f"({url})")
    check("the icon is pinned to the tag being packaged, not to a branch",
          f"@v{appinfo.__version__}/" in url, f"({url})")


# -- the MSI, whose mistakes are the ones that cannot be taken back ------------- #
def test_the_msi_upgrade_code_never_changes():
    """The one value in this repository that may never be regenerated.

    Windows Installer finds a machine's previous version through the UpgradeCode and
    through nothing else. A new one does not "reset" anything: every machine that
    already has the package keeps the old install, forever, beside the new one - and
    the correction would have to run on machines we cannot reach. So the literal is
    pinned here, and a regenerated GUID reddens instead of shipping.
    """
    check("the MSI UpgradeCode is the one this product was published with",
          bp.MSI_UPGRADE_CODE == "4BE626D0-E975-4E56-92B4-146EF6AEDF3C",
          f"({bp.MSI_UPGRADE_CODE})")


def test_the_msi_is_a_per_machine_install(tmp_path, monkeypatch):
    """Corporate deployment installs once, for everybody, from SYSTEM.

    A per-user MSI cannot be pushed by Group Policy or SCCM, which is the entire
    reason this package exists. This is also what makes ADR 2026-08-12 load-bearing
    rather than tidy: Program Files is read-only for ordinary users, so the profiles
    and exports have to live in %LOCALAPPDATA% or the program breaks for everyone
    who is not an administrator.
    """
    wxs = _rendered(tmp_path, monkeypatch)["msi/BeanNetworkTester.wxs"]
    check('the package installs per machine', 'Scope="perMachine"' in wxs)


def test_the_msi_replaces_the_previous_version_instead_of_joining_it(tmp_path, monkeypatch):
    """Without MajorUpgrade an MSI installs a SECOND copy and both stay listed.

    The schedule matters as much as the element. `afterInstallExecute` lays the new
    files down before the old product is removed; scheduling the removal first
    deletes files the new version shares and reinstalls none of them, which is the
    classic way an upgrade eats its own payload.
    """
    wxs = _rendered(tmp_path, monkeypatch)["msi/BeanNetworkTester.wxs"]
    check("the package upgrades in place", "<MajorUpgrade" in wxs)
    check("and lays the new files down before removing the old ones",
          'Schedule="afterInstallExecute"' in wxs)


def test_the_msi_keeps_the_exe_with_its_siblings(tmp_path, monkeypatch):
    """The same requirement `ArchiveBinariesDependOnPath` carries for WinGet.

    The exe cannot run without the `_internal` directory beside it, so the whole
    tree has to be harvested as it is. A harvest that flattened it, or that picked
    files one by one, would install something that starts and then cannot find its
    own language tables.
    """
    wxs = _rendered(tmp_path, monkeypatch)["msi/BeanNetworkTester.wxs"]
    check("the whole payload tree is harvested",
          re.search(r"<Files\s+Include=\"\$\(PayloadDir\)\\\*\*\"", wxs) is not None)


def test_the_msi_puts_the_command_line_on_the_system_path(tmp_path, monkeypatch):
    """A user-scoped PATH entry is invisible to the account that actually runs it.

    This tool reports outcomes as exit codes so it can run from a pipeline, and the
    thing running that pipeline is a service account or a scheduled task, not the
    person who installed it.
    """
    wxs = _rendered(tmp_path, monkeypatch)["msi/BeanNetworkTester.wxs"]
    found = re.search(r"<Environment[^>]*Name=\"PATH\"[^>]*>", wxs, re.S)
    check("the install directory is added to PATH", found is not None)
    check("and to the machine's PATH, not one account's",
          found is not None and 'System="yes"' in found.group(0))


def test_the_msi_closes_a_running_session_before_it_validates(tmp_path, monkeypatch):
    """An upgrade with a session running fails without this, and the order is the fix.

    Measured on Windows Server 2025, same starting point each time, a session holding
    the WinDivert driver throughout:

        Restart Manager on                       -> 1601, nothing installed
        Restart Manager off, close-app action    -> 3010, installed but wants a reboot
        Restart Manager off, close before validate -> 0

    Restart Manager cannot close this program - it is a console process with no window
    and no message loop, so there is nothing to ask, and it can only time out (thirty
    seconds, `Error: 351`). And InstallValidate is what decides a reboot is needed, so
    an action scheduled after it, which is where WiX puts CloseApplication by default,
    cannot change that answer. Hence a second action, scheduled Before InstallValidate.
    """
    wxs = _rendered(tmp_path, monkeypatch)["msi/BeanNetworkTester.wxs"]
    check("Restart Manager is turned off, so InstallValidate does not wait for it",
          'Id="MSIRESTARTMANAGERCONTROL" Value="Disable"' in wxs)
    check("a running session is closed",
          'Id="StopRunningSession"' in wxs)
    check("and it is closed BEFORE InstallValidate, which is what decides the reboot",
          re.search(r'<Custom\s+Action="StopRunningSession"\s+Before="InstallValidate"', wxs)
          is not None)
    check("closing is best effort and never fails the upgrade",
          re.search(r'Id="StopRunningSession"[^>]*Return="ignore"', wxs, re.S) is not None)


def test_a_reshipped_version_upgrades_instead_of_installing_beside_itself(
        tmp_path, monkeypatch):
    """Rebuilding one release under the same number is something this project does.

    A version sitting in moderation is corrected by shipping the same number again -
    the packaging runbook says so, and Chocolatey held 0.5.0 over exactly that. Each
    rebuild gets a fresh ProductCode, and MajorUpgrade ignores an equal version unless
    told otherwise: measured, that left two entries in Programs and Features side by
    side.
    """
    wxs = _rendered(tmp_path, monkeypatch)["msi/BeanNetworkTester.wxs"]
    check("a rebuild of the same version replaces the installed one",
          'AllowSameVersionUpgrades="yes"' in wxs)


def test_the_msi_version_is_the_one_being_released(tmp_path, monkeypatch):
    wxs = _rendered(tmp_path, monkeypatch)["msi/BeanNetworkTester.wxs"]
    check("the rendered package carries VERSION.txt's version",
          f'Version="{appinfo.__version__}"' in wxs)


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
