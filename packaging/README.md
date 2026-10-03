# Package sources: Chocolatey, WinGet and the MSI

These are **templates**, not packages. Every `{{PLACEHOLDER}}` is filled by
`tools/build_packages.py` from the one place that owns the value: the version from
`VERSION.txt`, the checksum and the archive's name from the release's own
`SHA256SUMS.txt`, the URLs from `site/site.json`, and the name, publisher, licence
and copyright from `beantester/appinfo.py`. Nothing here is typed twice, which is
why nothing here can go stale on its own.

    python tools/build_packages.py --sums SHA256SUMS.txt

The rendered files land in `build/packaging/` and are not tracked. A full render needs
both lines of a final release's `SHA256SUMS.txt`, the zip's and the MSI's, because the
WinGet manifest installs the MSI; without the MSI line the renderer refuses and writes
nothing. The one render that happens before the MSI exists - inside the signing
ritual, to build the MSI from its source - is `--only msi`.

## The order these steps have to happen in

🔴 **The first published manifest must point at a release that keeps user files in
`%LOCALAPPDATA%`.** Builds up to 0.4.0 wrote profiles, window state and the CSV
exports next to the executable, and a WinGet upgrade deletes the extracted directory
before installing the new one - so publishing an older version first would destroy
the files of everyone who installed it, on their very first upgrade, before the
version that knows how to migrate them ever ran. Publish with the release that
carries the move, not before it.

1. Tag and publish the release the normal way (PROJECT_NOTES, "Wydanie").
2. Download that release's `SHA256SUMS.txt` and render:
   `python tools/build_packages.py --sums SHA256SUMS.txt`.
3. Chocolatey: `choco pack build/packaging/chocolatey/bean-network-tester.nuspec`,
   then `choco install bean-network-tester -s . -y` on a machine you can break, then
   `choco push` with an API key. Moderation is a validator, an automated verifier
   that installs it in a VM, and a human.
4. WinGet: `winget validate --manifest build/packaging/winget`, then
   `winget install --manifest build/packaging/winget` locally, then open a pull
   request against `microsoft/winget-pkgs` with the three files under
   `manifests/d/DonislawDev/BeanNetworkTester/<version>/`.

**Submitting is a human step and stays one.** Neither of these is wired into
`release.yml`: a bad manifest is public and moderated, and the cost of catching it
after the fact is somebody else's review time.

**The MSI is the exception, and not because it is special.** It is built and signed by
`tools/sign_release.py` during the release itself, because it carries the executable:
building it anywhere else would either wrap an unsigned program in a signed installer,
or require the signing card to be somewhere it will never be. It is never submitted on
its own: it is an asset on the release, and the WinGet manifest points at it.

## What each package has to get right

**Chocolatey.** It downloads the release archive rather than embedding it, so the
package carries no binaries and owes no `VERIFICATION.txt`. `chocolateybeforemodify.ps1`
releases the WinDivert driver before an upgrade or an uninstall, because the kernel
holds `WinDivert64.sys` open while it is loaded and an open file cannot be deleted.
Its package folder is read-only for plain users, which is one of the two reasons the
program stopped keeping user files in its own directory. Its `iconUrl` is a CDN address
pinned to the release tag, and both halves are load-bearing: moderation refuses
`github.com/<owner>/<repo>/raw/...` exactly as it refuses `raw.githubusercontent.com`,
and an icon pointing at a branch would keep changing under a package that is already
approved.

Chocolatey itself puts a shim on `PATH` and nothing in the Start Menu, so
`chocolateyinstall.ps1` makes the Start Menu entry and `chocolateyuninstall.ps1` takes
it away. The entry has the MSI's name on purpose - one program, one entry - and neither
script touches an entry that points somewhere else: with the MSI installed as well,
that entry is the MSI's, and deleting it on a Chocolatey uninstall would leave the MSI
without one. An entry whose target is gone belongs to nobody and is replaced.

**WinGet.** The manifest offers **two installers, and their order is the fix**. A
portable package cannot have a Start Menu entry: the manifest schema has no field for
one, winget's portable installer creates none, and
[microsoft/winget-cli#2299](https://github.com/microsoft/winget-cli/issues/2299) has
asked for it since 2022. So the MSI comes first. Clients from v1.29.240 prefer msi/wix
over portable when the user has set no preference
([microsoft/winget-cli#6123](https://github.com/microsoft/winget-cli/pull/6123)), and
older ones keep the first applicable installer when nothing else separates two - either
way a fresh install gets the MSI. Its `AppsAndFeaturesEntries` carries the UpgradeCode,
braces included, which is what winget matches the installed MSI against from one
release to the next; the ProductCode changes with every build.

The zip stays second, for the installs that already came from it: an upgrade only
considers installers of the kind already installed, and portable is compatible with
nothing but portable. Measured with the MSI alone, upgrading a portable install ends in
"No applicable installer found". `--scope user` gets the zip too.

For the zip, `ArchiveBinariesDependOnPath: true` is the line that matters. The default
for a portable inside an archive is a symlink, and this executable cannot be reached
through one - it needs the `_internal` directory beside it. The field puts the
directory holding the nested file on `PATH` instead, which is what winget's source
does with it rather than what the field's one-line description implies. It sits inside
the zip's entry, not at the root, where the MSI would inherit it.

**The MSI.** Three things carry it. `UpgradeCode` is the identity of the product and can
never be regenerated - Windows Installer finds a machine's previous version through that
GUID and nothing else, so a new one would strand the old install on every machine that
already has it, unreachable. `Scope="perMachine"` is what Group Policy, SCCM and Intune
need, and it is only safe because user files already live in `%LOCALAPPDATA%`: Program
Files is read-only for ordinary users. And a running session has to be closed **before**
`InstallValidate`, not before `InstallFiles` where WiX puts `CloseApplication` by default -
Restart Manager cannot close a console process that has no window to ask, so it waits
thirty seconds and fails the upgrade, and `InstallValidate` is what decides a reboot is
needed. Measured: Restart Manager on gives 1601, off gives 3010, off plus an early close
gives 0.

Neither manifest can keep a file safe on its own: WinGet portables take no scripts at
all, and that is why the program itself had to stop writing into the directory the
package manager owns. The MSI is the one of the three that behaves like Chocolatey here -
a file it did not install survives both an upgrade and an uninstall.
