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
* both package managers put the program in the Start Menu: WinGet by installing the
  MSI FIRST (a portable package cannot have a Start Menu entry at all) while keeping
  the zip for the installs that already came from it, Chocolatey by a shortcut its
  scripts make and take away - never touching an entry another install owns;
* the renderer refuses the inputs that would look fine and be wrong: an unknown
  placeholder, the previous release's `SHA256SUMS.txt`, and a sums file without the
  MSI for a manifest that installs it.
"""
import os
import re
import shutil
import sys

import pytest
from fakes import ROOT, check

sys.path.insert(0, ROOT)
from beantester import appinfo                                    # noqa: E402
from tools import build_packages as bp                            # noqa: E402

# Real lines from a real release, binary marker and all. The MSI line is missing
# from a release candidate's file and from the one sign_release.py holds before it
# builds the MSI, which is what `msi=False` stands for.
SUMS_LINE = ("94359ea633e2e9fbe10e02b81070208a7209de2c4c48b003d8ce4feb30876bed"
             "  *BeanNetworkTester-v{version}-windows-x64.zip\n")
SUMS_MSI_LINE = ("854736d5fed824aa73e42f998d531baa6303e6ebbf62e4413ee9f0626833130d"
                 " *BeanNetworkTester-v{version}-windows-x64.msi\n")


def _sums(tmp_path, version, msi=True):
    path = tmp_path / "SHA256SUMS.txt"
    text = SUMS_LINE + (SUMS_MSI_LINE if msi else "")
    path.write_text(text.format(version=version), encoding="utf-8")
    return str(path)


def _read_tree(out):
    files = {}
    for base, _, names in os.walk(out):
        for name in names:
            path = os.path.join(base, name)
            files[os.path.relpath(path, out).replace(os.sep, "/")] = \
                open(path, encoding="utf-8").read()
    return files


def _rendered(tmp_path, monkeypatch, msi=True, only=None):
    """Render into a throwaway directory and return {relative name: text}."""
    out = tmp_path / "out"
    monkeypatch.setattr(bp, "OUT_DIR", str(out))
    # A fixed date, so these tests answer "does it render" and not "is the changelog
    # closed for this version". The changelog reader has its own test below, which is
    # the one that should redden when a version is bumped before its section is dated.
    monkeypatch.setattr(bp, "release_date", lambda version: "2026-01-01")
    bp.build(_sums(tmp_path, appinfo.__version__, msi=msi), only=only)
    return _read_tree(out)


def _code(text):
    """The lines that DO something - comments explain, and must not satisfy a check."""
    return [line for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def _winget_installers(installer):
    """(root lines, [installer entries as lists of lines]) of a rendered manifest.

    Text, not a YAML parser: the repository carries no YAML library, and the shapes
    asked about here - which entry comes first, what sits at the root - are visible in
    the indentation this template is written with.
    """
    lines = _code(installer)
    start = lines.index("Installers:")
    root = lines[:start] + [line for line in lines[start:] if not line.startswith(("-", " "))]
    entries = []
    for line in lines[start + 1:]:
        if line.startswith("- "):
            entries.append([line])
        elif line.startswith(" ") and entries:
            entries[-1].append(line)
    return root, entries


def _field(entry, name):
    for line in entry:
        stripped = line.lstrip("- ").strip()
        if stripped.startswith(name + ":"):
            return stripped.split(":", 1)[1].strip()
    return None


def _sources():
    return [(rel, open(path, encoding="utf-8").read())
            for path, rel in bp.templates() if rel.endswith(bp.TEMPLATE_SUFFIX)]


# -- what must never be typed twice -------------------------------------------- #
def test_no_package_source_carries_a_version_number():
    offenders = [rel for rel, text in _sources()
                 if re.search(r"\b\d+\.\d+\.\d+\b", text.replace(bp.WINGET_SCHEMA, ""))]
    check("packaging sources hold no version literal", not offenders, f"({offenders})")


def test_every_placeholder_is_known_and_every_known_placeholder_is_used():
    table = set(bp.values(appinfo.__version__, "abc", "x-v1.zip", msi=("def", "x-v1.msi")))
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


# -- the Start Menu entry: a program nobody can find is not installed ----------- #
def test_a_fresh_winget_install_gets_the_msi(tmp_path, monkeypatch):
    """The MSI is the only installer that gives the program a Start Menu entry.

    Until this was fixed the manifest carried the zip alone, and a portable package
    cannot have a Start Menu entry at all - no schema field, no code in winget's
    portable installer (microsoft/winget-cli#2299, open since 2022). Everyone who
    installed with winget could start the program from a console and nowhere else.

    FIRST, not merely present: clients since v1.29.240 prefer msi/wix over portable
    when the user set no preference (winget-cli#6123), and older ones keep the first
    applicable installer when nothing else separates two. Measured 2026-10-03 on
    Windows 11 and Windows Server 2025 (winget v1.29.380): a fresh install picks it.
    """
    _, entries = _winget_installers(_rendered(tmp_path, monkeypatch)["winget/installer.yaml"])
    check("the manifest offers two installers", len(entries) == 2, f"({len(entries)})")
    first = entries[0] if entries else []
    check("the first one is the MSI", _field(first, "InstallerType") == "wix",
          f"({_field(first, 'InstallerType')})")
    check("installed for the whole computer, as the MSI itself is built",
          _field(first, "Scope") == "machine", f"({_field(first, 'Scope')})")
    msi = (f"/v{appinfo.__version__}/"
           f"BeanNetworkTester-v{appinfo.__version__}-windows-x64.msi")
    check("it downloads this release's MSI", (_field(first, "InstallerUrl") or "").endswith(msi),
          f"({_field(first, 'InstallerUrl')})")
    check("and checks it against this release's own hash",
          _field(first, "InstallerSha256") == SUMS_MSI_LINE.split()[0].upper(),
          f"({_field(first, 'InstallerSha256')})")


def test_winget_recognises_its_msi_by_the_code_that_never_changes(tmp_path, monkeypatch):
    """Every build gets a fresh ProductCode; the UpgradeCode is the product's identity.

    Measured on Windows Server 2025: after installing, winget looked for the new
    Programs-and-Features entry with `Include:UpgradeCode='{...}'[Exact]` and found
    it. Exact means the registry's spelling, braces included.
    """
    _, entries = _winget_installers(_rendered(tmp_path, monkeypatch)["winget/installer.yaml"])
    msi = entries[0] if entries else []
    check("the MSI entry names the pinned UpgradeCode, braces and all",
          _field(msi, "UpgradeCode") == "'{" + bp.MSI_UPGRADE_CODE + "}'",
          f"({_field(msi, 'UpgradeCode')})")


def test_existing_winget_installs_keep_their_upgrade_path(tmp_path, monkeypatch):
    """Dropping the zip would strand everyone who installed before the MSI came first.

    An upgrade only considers installers of the kind already installed, and portable
    is compatible with nothing but portable. Measured with a manifest carrying the MSI
    alone: upgrading a portable install ends in "No applicable installer found"
    (0x8A150010). With both entries it upgrades as portable - same machine, same day.
    """
    root, entries = _winget_installers(
        _rendered(tmp_path, monkeypatch)["winget/installer.yaml"])
    check("the zip is still offered", len(entries) >= 2)
    zip_entry = entries[1] if len(entries) >= 2 else []
    check("as the second installer", _field(zip_entry, "InstallerType") == "zip",
          f"({_field(zip_entry, 'InstallerType')})")
    check("unpacked as the portable it always was",
          _field(zip_entry, "NestedInstallerType") == "portable")
    check("with the exe kept beside _internal",
          _field(zip_entry, "ArchiveBinariesDependOnPath") == "true")
    # At the root these would be inherited by EVERY installer, the MSI included.
    portable_only = ("InstallerType", "NestedInstallerType", "NestedInstallerFiles",
                     "ArchiveBinariesDependOnPath")
    leaked = [line for line in root if line.split(":", 1)[0] in portable_only]
    check("nothing portable-only sits at the root, where the MSI would inherit it",
          not leaked, f"({leaked})")


def test_a_sums_file_without_the_msi_cannot_make_the_winget_manifest(tmp_path, monkeypatch):
    """A release candidate has no MSI, and a manifest without one would be half a fix.

    Refused by NAME, so the reader looks for the missing line and not for a typo -
    and refused before anything is written: the renderer used to write each package
    as it went, so a refusal half-way left a render that looked finished.
    """
    out = tmp_path / "out"
    monkeypatch.setattr(bp, "OUT_DIR", str(out))
    monkeypatch.setattr(bp, "release_date", lambda version: "2026-01-01")
    with pytest.raises(SystemExit) as refused:
        bp.build(_sums(tmp_path, appinfo.__version__, msi=False))
    check("the refusal says the MSI line is missing", ".msi" in str(refused.value),
          f"({refused.value})")
    check("and names the way out for the render before signing",
          "--only msi" in str(refused.value), f"({refused.value})")
    check("and nothing was written", not _read_tree(out), f"({sorted(_read_tree(out))})")


def test_the_render_before_signing_needs_no_msi(tmp_path, monkeypatch):
    """`tools/sign_release.py` renders the MSI's source BEFORE the MSI exists.

    So the very command it runs is executed here, on the sums file it holds at that
    moment - the zip's line alone. Without `--only msi` the WinGet manifest would
    refuse, and phase B of a release would stop with the card in the reader.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sign_release", os.path.join(ROOT, "tools", "sign_release.py"))
    ritual = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ritual)

    class _Stop(Exception):
        pass

    calls = []

    def capture(argv, **kw):
        calls.append(argv)
        raise _Stop

    monkeypatch.setattr(ritual, "run", capture)
    sums = _sums(tmp_path, appinfo.__version__, msi=False)
    with pytest.raises(_Stop):
        ritual.build_msi(str(tmp_path), str(tmp_path), f"v{appinfo.__version__}", sums)
    argv = calls[0] if calls else []
    check("the ritual's first command is the renderer",
          any(str(part).endswith("build_packages.py") for part in argv), f"({argv})")

    out = tmp_path / "out"
    monkeypatch.setattr(bp, "OUT_DIR", str(out))
    monkeypatch.setattr(bp, "release_date", lambda version: "2026-01-01")
    script = [str(part) for part in argv]
    index = next((i for i, part in enumerate(script) if part.endswith("build_packages.py")), 0)
    bp.main(script[index + 1:])
    check("and on the zip's line alone it renders the MSI's source, and only that",
          sorted(_read_tree(out)) == ["msi/BeanNetworkTester.wxs"], f"({sorted(_read_tree(out))})")


def test_two_lines_for_one_asset_are_refused(tmp_path):
    """Two zip lines means two sums files were concatenated; neither is chosen."""
    path = tmp_path / "SHA256SUMS.txt"
    path.write_text(SUMS_LINE.format(version="1.0.0") + SUMS_LINE.format(version="1.0.1"),
                    encoding="utf-8")
    with pytest.raises(SystemExit) as refused:
        bp.parse_sums(str(path))
    check("the refusal names both files", "1.0.0" in str(refused.value)
          and "1.0.1" in str(refused.value), f"({refused.value})")


def test_the_chocolatey_package_adds_a_start_menu_entry(tmp_path, monkeypatch):
    """Chocolatey puts a shim on PATH and nothing in the Start Menu by itself.

    Measured on Windows Server 2025 from the public feed: 0.7.0 installed, zero new
    shortcuts. The entry points at the exe where it lies, beside `_internal` - the
    shim is a console program and would open a console window first.
    """
    files = _rendered(tmp_path, monkeypatch)
    install = _code(files["chocolatey/tools/chocolateyinstall.ps1"])
    exe = f"Join-Path $toolsDir '{appinfo.TOOL_ID}\\{appinfo.EXE_NAME}'"
    check("the target is the exe inside the unpacked archive",
          any(line.startswith("$exe = ") and exe in line for line in install), f"({exe})")
    check("the entry is made", any("Install-ChocolateyShortcut" in line for line in install))
    check("for every user of the computer, as Chocolatey installs",
          any("GetFolderPath('CommonPrograms')" in line for line in install))
    check("pointing at that exe", any(line.strip() == "-TargetPath $exe `" for line in install))
    uninstall = _code(files["chocolatey/tools/chocolateyuninstall.ps1"])
    check("and the uninstall takes it away again",
          any(line.strip().startswith("Remove-Item -LiteralPath $shortcut") for line in uninstall))


def test_the_start_menu_entry_has_one_name_for_every_installer(tmp_path, monkeypatch):
    """One program, one entry - and the foreign-entry rule below depends on it.

    The Chocolatey scripts recognise the MSI's entry because it is the SAME file. An
    entry with a name of its own would sit beside the MSI's as a second "Bean Network
    Tester", and neither package would know about the other.
    """
    files = _rendered(tmp_path, monkeypatch)
    wxs = files["msi/BeanNetworkTester.wxs"]
    check("the MSI's entry is named after the program",
          re.search(r'<Shortcut\s[^>]*Name="' + re.escape(appinfo.APP_NAME) + '"', wxs, re.S)
          is not None)
    name = f"'{appinfo.APP_NAME}.lnk'"
    for script in ("chocolateyinstall.ps1", "chocolateyuninstall.ps1"):
        code = _code(files[f"chocolatey/tools/{script}"])
        check(f"{script} uses the same file name",
              any(line.startswith("$shortcut = ") and line.endswith(name) for line in code),
              f"({name})")


def test_neither_chocolatey_script_touches_an_entry_it_does_not_own(tmp_path, monkeypatch):
    """With the MSI installed too, the Start Menu entry is the MSI's.

    Overwriting it would hand it to Chocolatey, and Chocolatey's uninstall would then
    delete the only entry the MSI has. Measured on Windows Server 2025: with the MSI
    installed, a Chocolatey install and uninstall both leave its entry pointing at
    Program Files; an entry whose target is gone is replaced.

    These are text checks on the shape that measurement proved, and the mutation
    registry holds the proof that they can fail.
    """
    files = _rendered(tmp_path, monkeypatch)
    install = _code(files["chocolatey/tools/chocolateyinstall.ps1"])
    ours = "$target.StartsWith($toolsDir + '\\', [System.StringComparison]::OrdinalIgnoreCase)"
    check("the install asks whether an existing entry is its own",
          any(ours in line for line in install))
    check("and whether its target still exists",
          any("Test-Path -LiteralPath $target" in line for line in install))
    branch = [line.strip() for line in install]
    guarded = ("if ($owner) {" in branch and "} else {" in branch
               and "Install-ChocolateyShortcut `" in branch
               and branch.index("if ($owner) {") < branch.index("} else {")
               < branch.index("Install-ChocolateyShortcut `"))
    check("and makes the entry only when nobody else owns it", guarded)

    uninstall = _code(files["chocolatey/tools/chocolateyuninstall.ps1"])
    removal = [i for i, line in enumerate(uninstall) if "Remove-Item" in line]
    guard = [i for i, line in enumerate(uninstall) if line.strip().startswith("if (") and ours in line]
    check("the uninstall removes the entry only when it points into this package",
          len(removal) == 1 and len(guard) == 1 and guard[0] == removal[0] - 1,
          f"(guard {guard}, removal {removal})")


def test_an_apostrophe_in_the_tagline_cannot_break_the_install_script(tmp_path, monkeypatch):
    """The tagline is website copy, and it lands inside a single-quoted PowerShell string.

    One "don't" in it would have been a syntax error in Chocolatey's install - the
    install would fail before it unpacked anything.
    """
    real = bp._read_json

    def with_apostrophe(*parts):
        data = real(*parts)
        if parts[-1] == "en.json":
            data = dict(data, **{"site.tagline": "Don't trust the network"})
        return data

    monkeypatch.setattr(bp, "_read_json", with_apostrophe)
    install = _rendered(tmp_path, monkeypatch)["chocolatey/tools/chocolateyinstall.ps1"]
    check("the apostrophe is written twice, PowerShell's escape inside single quotes",
          "-Description 'Don''t trust the network'" in install)


@pytest.mark.skipif(not shutil.which("powershell.exe"),
                    reason="Windows PowerShell 5.1 exists on Windows only")
def test_the_rendered_chocolatey_scripts_parse_in_windows_powershell(tmp_path, monkeypatch):
    """Chocolatey runs package scripts with Windows PowerShell 5.1, so 5.1 parses them.

    This is the one place convention 46 points the other way: the shell is not ours
    to choose. A parse error here is an install that fails on every machine, and the
    text checks above cannot see one.
    """
    import subprocess

    files = _rendered(tmp_path, monkeypatch)
    for name in ("chocolateyinstall.ps1", "chocolateyuninstall.ps1",
                 "chocolateybeforemodify.ps1"):
        path = tmp_path / "out" / "chocolatey" / "tools" / name
        command = ("$e = $null; $t = $null; "
                   "[System.Management.Automation.Language.Parser]::ParseFile("
                   f"'{path}', [ref]$t, [ref]$e) | Out-Null; "
                   "$e | ForEach-Object { $_.Message }")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                                 "-Command", command],
                                capture_output=True, text=True, timeout=120)
        check(f"{name} exists", f"chocolatey/tools/{name}" in files)
        check(f"{name} parses without errors",
              result.returncode == 0 and not result.stdout.strip(),
              f"(exit {result.returncode}: {result.stdout.strip()} {result.stderr.strip()})")


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
