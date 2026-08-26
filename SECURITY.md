For certifcate:
Project Link: https://github.com/donislawdev/BeanNetworkTester
Name: Dominik Babiarz
e-mail: dominik.babiarz[at]donislawdev.com

# Security Policy

## Supported versions

Bean Network Tester has a single active line of development. Security fixes are made
against the **latest release** and the `master` branch. Please confirm you can
reproduce an issue on the latest version before reporting it.

**Older releases receive nothing.** When a new version is published, the one before it
stops being supported that day: no security updates, no backports, no patched builds. The
supported version is whichever release is currently the latest, for as long as it is the
latest. There is no long-term support line and none is planned, so the upgrade path for a
security fix is always to move to the newest release.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private vulnerability reporting: open the **Security** tab of this
repository and choose **Report a vulnerability**. This keeps the report private until
a fix is available. If you cannot use that channel, reach the author through
https://donislawdev.com/.

Please include:

- the version (`BeanNetworkTester.exe --version`) and your Windows version,
- whether you ran the GUI or the CLI, and whether it was elevated (administrator),
- a clear description and the smallest steps to reproduce,
- the impact you believe it has.

You can expect an initial response within 14 days or fewer. Once a fix is ready it ships in
the next release, and the advisory is published crediting the reporter (unless you
prefer to remain anonymous).

## Secrets and credentials

The project uses as few of these as it can, and the release path deliberately keeps the
most sensitive one away from any machine we do not control.

**What exists.** One repository secret, read by one workflow: an OAuth token for the
code-review assistant. Everything else in CI runs on the per-job token GitHub issues for
the run, and nothing else is stored in the repository.

**How access is scoped.** Every workflow declares a read-only permission set at the top
(`contents: read`, or `read-all` in the one that only reads), so a job added to any of
them later is read-only unless somebody says otherwise. A write scope is raised on the
individual job that needs it and nowhere else: publishing a release, attesting a build,
deploying the project site, uploading a scorecard result, and opening an issue when the
dependency audit or the weekly run finds something. No workflow grants a write scope at
the top of the file, where a later job would inherit it without anyone deciding.

**The code-signing certificate never reaches CI.** It lives on a hardware token held by
the maintainer, and the release is split into separate phases precisely so that the build
happens on a runner while the signature happens on the maintainer's own machine. No
workflow in this repository can sign anything, and none is given the chance to.

**How the signing identity is checked.** The certificate's SHA-256 is pinned in the
source, as `CODESIGN_SHA256` in `beantester/legal.py`. The signing script reads the
certificate back out of the file it has just signed and refuses to go any further unless
it hashes to that pin, so a second code-signing certificate on the same machine cannot
sign a release by accident. The published release is checked against the same pin again
after it goes out.

**How it is rotated.** The current certificate expires on **2027-08-19**. The signing
script prints the remaining life on every run, warns inside the expiry window, and
refuses to sign at all once the date has passed, so the certificate cannot quietly lapse
in the middle of a release. Renewal issues a new certificate with a new fingerprint, and
the pin above is updated in the same change that first uses it.

**Rotating the repository secret** is manual, and happens when its issuer rotates the
token or when the workflow that reads it is removed.

## Scope: the nature of this tool

Bean Network Tester deliberately degrades network traffic and **loads a signed
kernel-mode driver (WinDivert)** to do so. Running it interrupts connectivity on the
machine by design - that is the tool working, not a vulnerability. Issues in the driver
itself belong upstream: https://github.com/basil00/WinDivert.

The program has **no telemetry and no network client** - it sends no data anywhere.

Reports that are in scope include, for example: a way to make the tool affect traffic
it was not told to target, a crash that corrupts a user's files (profiles, config,
CSV), or unsafe handling of the files it reads and writes.

## Where you install it matters

The program asks for administrator rights and then loads `WinDivert.dll` from its own
folder. So anything that can write to that folder **without** administrator rights can
leave a DLL there for the elevated copy to load. That is a property of every user-scope
install, not of this program in particular - but this program is the one that elevates,
so it is worth saying plainly.

Measured on 2026-08-26:

| How you installed it | Folder | Writable without admin rights |
|---|---|---|
| `winget install` (default) | `%LOCALAPPDATA%\Microsoft\WinGet\Packages\` | **yes** |
| `winget install --scope machine` | `%PROGRAMFILES%\WinGet\Packages\` | no |
| Chocolatey | `C:\ProgramData\chocolatey\lib\` | no |
| Zip unpacked in your profile | wherever you put it | **yes** |

If that matters on your machine, install with `winget install --scope machine`, use
Chocolatey, or unpack the zip somewhere only administrators can write.
`BeanNetworkTester.exe --doctor` tells you which of the two your copy is in - run it
**without** administrator rights, or it can only report that it could not tell.
