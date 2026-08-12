# Package sources: Chocolatey and WinGet

These are **templates**, not packages. Every `{{PLACEHOLDER}}` is filled by
`tools/build_packages.py` from the one place that owns the value: the version from
`VERSION.txt`, the checksum and the archive's name from the release's own
`SHA256SUMS.txt`, the URLs from `site/site.json`, and the name, publisher, licence
and copyright from `beantester/appinfo.py`. Nothing here is typed twice, which is
why nothing here can go stale on its own.

    python tools/build_packages.py --sums SHA256SUMS.txt

The rendered files land in `build/packaging/` and are not tracked.

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

## What each package has to get right

**Chocolatey.** It downloads the release archive rather than embedding it, so the
package carries no binaries and owes no `VERIFICATION.txt`. `chocolateybeforemodify.ps1`
releases the WinDivert driver before an upgrade or an uninstall, because the kernel
holds `WinDivert64.sys` open while it is loaded and an open file cannot be deleted.
Its package folder is read-only for plain users, which is one of the two reasons the
program stopped keeping user files in its own directory.

**WinGet.** `ArchiveBinariesDependOnPath: true` is the line that matters. The default
for a portable inside an archive is a symlink, and this executable cannot be reached
through one - it needs the `_internal` directory beside it. The field puts the
directory holding the nested file on `PATH` instead, which is what winget's source
does with it rather than what the field's one-line description implies.

Neither manifest can keep a file safe on its own: WinGet portables take no scripts at
all, and that is why the program itself had to stop writing into the directory the
package manager owns.
