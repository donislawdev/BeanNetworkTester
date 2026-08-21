#!/usr/bin/env python3
"""Sign a release build with the hardware card, then hand it back to the workflow.

    python tools/sign_release.py v0.5.0-rc.2
    python tools/sign_release.py v0.5.0-rc.2 --dry-run   # everything except sign/upload

Why this exists as a step a person runs
---------------------------------------
The signing key lives on a cryptographic card in a USB reader. It cannot be
exported - that is the whole value of it - so no GitHub-hosted runner can ever
reach it. A self-hosted runner could, and this is a PUBLIC repository, where a
self-hosted runner is a machine strangers can aim a pull request at. So the build
happens where builds belong and the signature happens where the card is, and this
script is the seam between them.

What it does, in order, and what it refuses
-------------------------------------------
1. downloads the unsigned build the release workflow produced for this tag;
2. **verifies that build's provenance attestation** before touching it. Signing
   something you did not check is how a supply chain gets a signature on it;
3. signs the executable with the card, with an RFC 3161 timestamp - **without a
   timestamp the signature dies when the certificate expires**, and this one expires
   after a year;
4. reads the certificate back OUT of the signed file and refuses to go on unless it
   hashes to ``legal.CODESIGN_SHA256``. A second code-signing certificate on the
   same machine - a renewal, a test one, one from another project - is exactly the
   accident this catches;
5. repacks the archive, writes ``SHA256SUMS.txt`` over what it just made;
6. uploads both to the DRAFT release and asks the workflow to attest the signed
   bytes, so the ``.sigstore.json`` a user verifies describes the file they hold;
7. **waits for that attestation and confirms the draft is complete** - four assets,
   the published checksums naming the digest that was actually signed, and the
   release still a draft. Until this existed the script ended at "dispatched, go
   look", and a draft missing one file looks almost exactly like a finished one.

Nothing here publishes. The release stays a draft until a person looks at it and
presses the button - and pressing it runs ``verify-release.yml``, which downloads
the published assets and re-checks them the way a user would.
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beantester.legal import CODESIGN_SHA256          # noqa: E402

REPO = "donislawdev/BeanNetworkTester"
ATTEST_WORKFLOW = "attest-release.yml"
TIMESTAMP_URL = "http://time.certum.pl/"


def run(argv, **kw):
    """Run a command, echo it, and stop the ritual on a non-zero exit."""
    print("  $ %s" % " ".join(argv))
    result = subprocess.run(argv, text=True, capture_output=True, **kw)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit("sign_release: '%s' failed (%d)"
                         % (argv[0], result.returncode))
    return result.stdout


def powershell(script):
    """Run a PowerShell snippet, preferring pwsh 7 and falling back to 5.1.

    Convention 46: `pwsh` first everywhere, because 5.1 is the one that is merely
    always present. The fallback stays because a machine may not have seven.
    """
    for exe in ("pwsh", "powershell"):
        if shutil.which(exe):
            return run([exe, "-NoProfile", "-NonInteractive", "-Command", script])
    raise SystemExit("sign_release: neither pwsh nor powershell is on PATH")


def find_signtool():
    """The newest x64 signtool.exe from the Windows SDK, or a clear refusal."""
    kits = r"C:\Program Files (x86)\Windows Kits\10\bin"
    found = []
    for version in sorted(os.listdir(kits)) if os.path.isdir(kits) else []:
        candidate = os.path.join(kits, version, "x64", "signtool.exe")
        if os.path.exists(candidate):
            found.append(candidate)
    if not found:
        raise SystemExit(
            "sign_release: no signtool.exe under %s - install the Windows SDK "
            "('Windows SDK Signing Tools' is enough)" % kits)
    return found[-1]


WARN_DAYS = 90


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def expiry_notice(not_after, now):
    """Lines to print about the certificate's remaining life - and a refusal if none.

    🔴 The card's certificate expires on a known date (2027-08-19 for the current
    one), and until 2026-08-21 the script PRINTED that date and drew no conclusion
    from it. The first release after expiry would therefore have failed in the middle
    of the ritual, at the signing step, with the card already in the reader - the
    worst possible moment to discover a certificate problem.

    Renewal issues a NEW certificate, so `legal.CODESIGN_SHA256` moves with it. The
    warning says so, because a session that renews the certificate and does not know
    that will next meet the pin as a refusal it cannot explain.

    Pure, so it can be checked without a card: `now` is passed in.
    """
    if not not_after:
        return ["  🔴 the store did not report an expiry date - check the card by hand"]
    try:
        when = datetime.datetime.fromisoformat(str(not_after))
    except ValueError:
        return ["  🔴 could not read the expiry date %r - check the card by hand"
                % (not_after,)]
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    days = (when - now).days
    if days < 0:
        raise SystemExit(
            "sign_release: the pinned certificate EXPIRED %d days ago (%s).\n"
            "Signing with it now produces a signature Windows will reject. Renew the\n"
            "certificate, then move legal.CODESIGN_SHA256 to the new one's SHA-256 -\n"
            "a renewal is a different certificate, not the same one with a new date."
            % (-days, when.date()))
    if days <= WARN_DAYS:
        return ["  🔴 WARNING: %d days left on this certificate (%s)." % (days, when.date()),
                "     Renewing issues a NEW certificate, so legal.CODESIGN_SHA256 has to",
                "     move with it or the next release refuses to sign at all."]
    return ["  %d days left on the certificate" % days]


EXPECTED_ASSETS = (".zip", "SHA256SUMS.txt", ".spdx.json", ".sigstore.json")


def _gh_json(*args):
    """gh, parsed, without ending the ritual on failure - for polling."""
    result = subprocess.run(["gh"] + list(args), text=True, capture_output=True)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout or "null")
    except ValueError:
        return None


def confirm_draft(tag, digest, wait_seconds):
    """Is the draft actually complete and describing the bytes we just signed?

    🔴 This step exists because the script used to end at "dispatched, go look". The
    upload and the dispatch are two calls, phase C is a third thing entirely, and a
    half-finished draft looks almost exactly like a finished one - three assets
    instead of four. On 2026-08-20 that difference (six rows in the web UI instead of
    seven) took a person and a session several minutes to explain, on a release that
    was in fact fine. On a release that was NOT fine it would have been published.

    Waits for phase C rather than assuming it: attesting takes well under a minute,
    but "well under a minute" is not "already done" at the moment the dispatch
    returns.

    Returns (ok, lines_to_print) and never raises, so the caller decides.
    """
    deadline = time.monotonic() + max(0, wait_seconds)
    lines, assets = [], []
    while True:
        data = _gh_json("release", "view", tag, "--repo", REPO,
                        "--json", "assets,isDraft")
        assets = [a.get("name", "") for a in (data or {}).get("assets", [])]
        missing = [kind for kind in EXPECTED_ASSETS
                   if not any(name.endswith(kind) for name in assets)]
        if not missing:
            break
        if time.monotonic() >= deadline:
            lines.append("  waited %ds and the draft is still missing: %s"
                         % (wait_seconds, ", ".join(missing)))
            lines.append("  assets present: %s" % (", ".join(sorted(assets)) or "none"))
            lines.append("  '%s' attaches the .sigstore.json - check its run log."
                         % ATTEST_WORKFLOW)
            return False, lines
        time.sleep(5)

    for name in sorted(assets):
        lines.append("  asset  %s" % name)

    # The digest is checked against what the RELEASE carries, not against the local
    # file we made - those are the same bytes only if the upload really landed.
    where = os.path.join(ROOT, "build", "signing", tag, "confirm")
    shutil.rmtree(where, ignore_errors=True)
    os.makedirs(where, exist_ok=True)
    got = subprocess.run(["gh", "release", "download", tag, "--repo", REPO,
                          "--pattern", "SHA256SUMS.txt", "--dir", where],
                         text=True, capture_output=True)
    if got.returncode != 0:
        lines.append("  could not download SHA256SUMS.txt back from the draft")
        return False, lines
    with open(os.path.join(where, "SHA256SUMS.txt"), encoding="utf-8") as handle:
        published = handle.read()
    if digest not in published:
        lines.append("  🔴 SHA256SUMS.txt on the release does NOT name the digest we signed")
        lines.append("     signed:    %s" % digest)
        lines.append("     published: %s" % published.strip())
        return False, lines
    lines.append("  checksums on the release name the digest we signed (%s...)" % digest[:16])
    if (_gh_json("release", "view", tag, "--repo", REPO, "--json", "isDraft") or
            {}).get("isDraft") is False:
        lines.append("  🔴 this release is NOT a draft any more - it is already public")
        return False, lines
    lines.append("  PASS: four assets, digests agree, still a draft")
    return True, lines


def signing_thumbprint():
    """The SHA-1 thumbprint of the certificate whose DER bytes hash to our pin.

    🔴 Two digests, one source of truth. `signtool /sha1` selects by SHA-1 because
    that is the only selector it takes; the repository pins SHA-256 because that is
    the digest worth pinning. Resolving one to the other here means the two can
    never drift apart in a config file.
    """
    script = (
        "$out = @(); "
        "Get-ChildItem Cert:\\CurrentUser\\My, Cert:\\LocalMachine\\My "
        "-ErrorAction SilentlyContinue | ForEach-Object { "
        "  $h = [System.Security.Cryptography.SHA256]::Create()"
        ".ComputeHash($_.RawData); "
        "  $out += [pscustomobject]@{ "
        "    sha256 = (($h | ForEach-Object { $_.ToString('x2') }) -join ''); "
        "    thumb = $_.Thumbprint; subject = $_.Subject; notAfter = $_.NotAfter } "
        "}; $out | ConvertTo-Json -Compress"
    )
    raw = powershell(script).strip() or "[]"
    entries = json.loads(raw)
    if isinstance(entries, dict):
        entries = [entries]
    for entry in entries:
        if entry.get("sha256") == CODESIGN_SHA256:
            print("  certificate: %s" % entry.get("subject", "").split(",")[0])
            print("  expires:     %s" % entry.get("notAfter"))
            for line in expiry_notice(entry.get("notAfter"), now=_now()):
                print(line)
            return entry["thumb"]
    raise SystemExit(
        "sign_release: the pinned certificate (%s...) is not in the Windows store. "
        "Plug in the card reader and check proCertum can see it; if the certificate "
        "was renewed, legal.CODESIGN_SHA256 has to move with it."
        % CODESIGN_SHA256[:16])


def certificate_of(path):
    """The sha256 of the certificate that actually signed ``path``."""
    script = (
        "$s = Get-AuthenticodeSignature -LiteralPath '%s'; "
        "if ($s.Status -ne 'Valid') { Write-Error ('signature status: ' + $s.Status); exit 1 }; "
        "$h = [System.Security.Cryptography.SHA256]::Create()"
        ".ComputeHash($s.SignerCertificate.RawData); "
        "(($h | ForEach-Object { $_.ToString('x2') }) -join '')" % path
    )
    return powershell(script).strip()


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tag", help="the release tag, e.g. v0.5.0-rc.2")
    parser.add_argument("--dry-run", action="store_true",
                        help="do everything except sign, upload and dispatch")
    parser.add_argument("--work", default=os.path.join(ROOT, "build", "signing"),
                        help="scratch directory (default: build/signing)")
    parser.add_argument("--wait", type=int, default=300, metavar="SECONDS",
                        help="how long to wait for the attestation workflow to "
                             "finish attaching its bundle (default: 300)")
    args = parser.parse_args(argv)

    if os.name != "nt":
        raise SystemExit("sign_release: the card lives on Windows; run this there")

    work = os.path.join(args.work, args.tag)
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work)
    print("working in %s" % work)

    print("\n[1/7] fetching the build this tag produced")
    run(["gh", "run", "download", "--repo", REPO, "--name",
         "unsigned-build-%s" % args.tag, "--dir", work])
    archives = [f for f in os.listdir(work) if f.endswith(".zip")]
    if len(archives) != 1:
        raise SystemExit("sign_release: expected one archive in the artefact, got %r"
                         % archives)
    archive = os.path.join(work, archives[0])

    print("\n[2/7] verifying what the workflow says it built")
    run(["gh", "attestation", "verify", archive, "--repo", REPO])

    print("\n[3/7] unpacking")
    unpacked = os.path.join(work, "unpacked")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(unpacked)
    exes = [os.path.join(base, name)
            for base, _dirs, names in os.walk(unpacked)
            for name in names if name.lower().endswith(".exe")]
    if len(exes) != 1:
        raise SystemExit("sign_release: expected one .exe in the archive, got %r"
                         % [os.path.basename(e) for e in exes])
    exe = exes[0]
    print("  %s (%d bytes, unsigned)" % (os.path.basename(exe), os.path.getsize(exe)))

    print("\n[4/7] signing with the card")
    thumbprint = signing_thumbprint()
    signtool = find_signtool()
    command = [signtool, "sign", "/sha1", thumbprint, "/fd", "sha256",
               "/tr", TIMESTAMP_URL, "/td", "sha256", "/v", exe]
    if args.dry_run:
        print("  DRY RUN, would run: %s" % " ".join(command))
    else:
        run(command)
        run([signtool, "verify", "/pa", "/v", exe])
        actual = certificate_of(exe)
        if actual != CODESIGN_SHA256:
            raise SystemExit(
                "sign_release: the file was signed by a DIFFERENT certificate\n"
                "  expected %s\n  got      %s\nNothing has been uploaded."
                % (CODESIGN_SHA256, actual))
        print("  signed by the pinned certificate, timestamped")

    print("\n[5/7] repacking and checksumming")
    signed = os.path.join(work, archives[0])
    if not args.dry_run:
        os.remove(archive)
        with zipfile.ZipFile(signed, "w", zipfile.ZIP_DEFLATED) as zf:
            for base, _dirs, names in os.walk(unpacked):
                for name in names:
                    full = os.path.join(base, name)
                    zf.write(full, os.path.relpath(full, unpacked))
        sums = os.path.join(work, "SHA256SUMS.txt")
        with open(sums, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("%s *%s\n" % (sha256_of(signed), archives[0]))
        print("  %s" % sha256_of(signed))

    print("\n[6/7] handing it back to the workflow")
    if args.dry_run:
        print("  DRY RUN, would upload the archive and SHA256SUMS.txt to the draft")
        print("  DRY RUN, would dispatch %s with the digest" % ATTEST_WORKFLOW)
        print("\ndry run finished - nothing was signed, uploaded or published")
        return 0
    run(["gh", "release", "upload", args.tag, signed, sums,
         "--repo", REPO, "--clobber"])
    run(["gh", "workflow", "run", ATTEST_WORKFLOW, "--repo", REPO,
         "-f", "tag=%s" % args.tag, "-f", "digest=%s" % sha256_of(signed)])

    print("\n[7/7] confirming the draft is complete")
    ok, lines = confirm_draft(args.tag, sha256_of(signed), args.wait)
    for line in lines:
        print(line)
    if not ok:
        raise SystemExit(
            "sign_release: the draft is NOT complete. Nothing was published, so "
            "nothing is broken - but do not press publish until the missing piece "
            "is there. Re-running this script is safe (the upload uses --clobber).")
    print("\nDone. The release is still a DRAFT.")
    print("Read the draft, then publish it. Publishing runs 'Verify the published "
          "release', which re-checks the bytes the way a user would.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
