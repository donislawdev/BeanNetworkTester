#!/usr/bin/env python3
"""Write an SPDX 2.3 SBOM for the build, from the licence registry.

Why the registry and not a scanner
----------------------------------
Both were measured on 2026-08-11 before this was written, and neither is
sufficient alone:

* a scanner (Syft) reading the BUILT BUNDLE finds CPython, Tcl and Tk with exact
  versions, and misses psutil, PyDivert and PyInstaller entirely, because
  PyInstaller strips ``.dist-info``. It sees ``WinDivert64.dll`` with no version,
  never sees ``WinDivert64.sys`` at all, and attaches **no licence to anything**;
* the registry (``beantester.legal.COMPONENTS``) carries the licences, the SPDX
  expressions and the source URLs - the half a scanner cannot infer - and is the
  list a human has actually reviewed.

So the SBOM is generated from the registry, and the scanner's job is to be its
GUARD: ``tools/sbom.py --audit-bundle`` fails when the built bundle contains a
component the registry does not know. That direction is the one that has already
paid - the same scan found zlib, libffi and 42 Microsoft runtime files shipping
in every release while every list claimed to be complete.

An SBOM that omits what it cannot see is worse than no SBOM: it is a document
that claims completeness. This one is only as complete as the registry, and the
registry now has three tests holding it to the bundle.

Usage:
    python tools/sbom.py                       # SPDX JSON to stdout
    python tools/sbom.py -o sbom.spdx.json     # ...or to a file
    python tools/sbom.py --audit-bundle dist/BeanNetworkTester   # guard mode
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beantester import appinfo, legal                              # noqa: E402

SPDX_VERSION = "SPDX-2.3"
DATA_LICENSE = "CC0-1.0"

# The one licence with no SPDX identifier: Microsoft distributes terms rather
# than a text to include, so SPDX requires it to be declared as a LicenseRef with
# the text spelled out here.
EXTRACTED = {
    "LicenseRef-Microsoft-Redistributable":
        "Microsoft Visual C++ runtime and Universal CRT files, redistributed "
        "under Microsoft's redistributable-code terms for Visual Studio. "
        "Microsoft publishes the terms rather than a licence text to bundle: "
        "https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files",
}


def _spdx_id(prefix, name):
    """``SPDXRef-...`` - the identifier grammar allows only letters, digits, . and -."""
    return "SPDXRef-%s-%s" % (prefix, re.sub(r"[^A-Za-z0-9.-]", "-", name).strip("-"))


def _package(name, version, url, spdx_expression):
    return {
        "SPDXID": _spdx_id("Package", name),
        "name": name,
        "versionInfo": version or "NOASSERTION",
        "downloadLocation": url or "NOASSERTION",
        # False, and deliberately: this describes COMPONENTS, not the individual
        # files they arrive as. Claiming otherwise would oblige us to list and
        # checksum every file, and a half-filled file list reads as a complete one.
        "filesAnalyzed": False,
        "licenseConcluded": spdx_expression or "NOASSERTION",
        "licenseDeclared": spdx_expression or "NOASSERTION",
        "copyrightText": "NOASSERTION",
    }


def build(namespace_seed=None):
    """The SBOM as a dict, ready for ``json.dump``."""
    version = appinfo.__version__
    root_id = _spdx_id("Package", appinfo.APP_NAME)
    created = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # The namespace must be unique per document. Seeded from the build when the
    # caller has something stable to offer (a tag), so two runs on the same tag
    # produce the same URI instead of a random one nobody can correlate.
    seed = namespace_seed or created
    digest = hashlib.sha256(("%s|%s" % (version, seed)).encode("utf-8")).hexdigest()[:16]

    packages = [{
        "SPDXID": root_id,
        "name": appinfo.APP_NAME,
        "versionInfo": version,
        "downloadLocation": "https://github.com/donislawdev/BeanNetworkTester",
        "filesAnalyzed": False,
        "licenseConcluded": "GPL-3.0-only",
        "licenseDeclared": "GPL-3.0-only",
        "copyrightText": "NOASSERTION",
    }]
    relationships = [{
        "spdxElementId": "SPDXRef-DOCUMENT",
        "relationshipType": "DESCRIBES",
        "relatedSpdxElement": root_id,
    }]

    rows = {name: version for name, version, _lic, _url in legal.component_rows()}
    for name, _module, _prose, url, spdx_expression in legal.COMPONENTS:
        reported = rows.get(name, "")
        packages.append(_package(
            name,
            "" if reported in ("bundled", "-", "present") else reported,
            url, spdx_expression))
        relationships.append({
            "spdxElementId": root_id,
            "relationshipType": "CONTAINS",
            "relatedSpdxElement": _spdx_id("Package", name),
        })

    used = {c[4] for c in legal.COMPONENTS}
    document = {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": DATA_LICENSE,
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "%s-%s" % (appinfo.APP_NAME, version),
        "documentNamespace":
            "https://github.com/donislawdev/BeanNetworkTester/spdx/%s-%s" % (version, digest),
        "creationInfo": {
            "created": created,
            "creators": ["Tool: beantester-sbom", "Organization: DonislawDev"],
            "comment": "Generated from beantester.legal.COMPONENTS, the reviewed "
                       "list of what this build ships. See tools/sbom.py for why "
                       "that is the source rather than a filesystem scan.",
        },
        "packages": packages,
        "relationships": relationships,
    }
    extracted = [{"licenseId": key, "extractedText": text}
                 for key, text in sorted(EXTRACTED.items()) if key in used]
    if extracted:
        document["hasExtractedLicensingInfo"] = extracted
    return document


# --------------------------------------------------------------------------- #
# guard mode: the scanner checks the registry, not the other way round
# --------------------------------------------------------------------------- #

# What a Syft scan of the bundle reports, mapped to the registry entry that
# accounts for it. Everything the scan can produce must land somewhere here, or
# the registry has a hole - which is exactly how zlib, libffi and the Microsoft
# runtime were found.
BUNDLE_PATTERNS = (
    (r"^api-ms-win-|^ucrtbase|^vcruntime140|c runtime|apiset stub", "Microsoft C Runtime"),
    (r"^python$|^python3", "Python"),
    (r"^tcl|^tk\b|^tk ", "Tcl/Tk"),
    (r"windivert", "WinDivert"),
    (r"^zlib", "zlib"),
    (r"libffi", "libffi"),
    # Arrives with Tcl 9 (bignum support), not with any requirement of ours. The
    # scan named it `\_internal\libtommath`, hence a substring match rather than
    # an anchored one - `re.search`, so the path prefix does not matter.
    (r"libtommath", "libtommath"),
    (r"^pydivert", "PyDivert"),
    (r"^psutil", "psutil"),
    (r"pyinstaller", "PyInstaller (bootloader)"),
    (r"^bean network tester$|^beannetworktester", None),      # the program itself
)


def audit_bundle(scan_json):
    """Names in a Syft scan that no registry entry accounts for."""
    with open(scan_json, encoding="utf-8") as handle:
        scan = json.load(handle)
    known = {name for name, *_ in legal.COMPONENTS}
    unaccounted = []
    for artifact in scan.get("artifacts", []):
        name = str(artifact.get("name", "")).strip()
        low = name.lower()
        for pattern, entry in BUNDLE_PATTERNS:
            if re.search(pattern, low):
                if entry is not None and entry not in known:
                    unaccounted.append("%s -> registry has no %r" % (name, entry))
                break
        else:
            unaccounted.append(name)
    return sorted(set(unaccounted))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", help="write here instead of stdout")
    parser.add_argument("--namespace-seed",
                        help="stable seed for the document namespace (e.g. the tag)")
    parser.add_argument("--audit-bundle", metavar="SYFT_JSON",
                        help="guard mode: fail when a Syft scan names something "
                             "the registry does not account for")
    args = parser.parse_args()

    if args.audit_bundle:
        missing = audit_bundle(args.audit_bundle)
        if missing:
            print("The built bundle contains components the licence registry does "
                  "not account for.\nAdd them to beantester/legal.py, "
                  "THIRD-PARTY-NOTICES.md and licenses/ before releasing:\n")
            for line in missing:
                print("  %s" % line)
            return 1
        print("bundle audit: every component maps to a registry entry")
        return 0

    text = json.dumps(build(args.namespace_seed), indent=2, sort_keys=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
        print("wrote %s (%d packages)" % (args.output, len(build()["packages"])))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
