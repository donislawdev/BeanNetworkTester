"""The SBOM must describe the same build the licence report describes.

An SBOM is a claim about what a user received, published as a release asset and
signed. Two ways it can go wrong, and only one of them is obvious:

* it can be malformed - caught the moment anything tries to read it;
* it can be WELL-FORMED AND INCOMPLETE, which is worse, because a document that
  claims to be a bill of materials and omits a component is more misleading than
  no document at all.

So the tests below spend most of their effort on the second: every registry entry
reaches the SBOM, every SPDX identifier is a real one, and the licence the SBOM
declares is the licence the registry declares.
"""
import json
import os
import re
import subprocess
import sys

from beantester import appinfo, legal
from fakes import ROOT, check

sys.path.insert(0, os.path.join(ROOT, "tools"))
import sbom                                                        # noqa: E402


def test_the_document_has_the_shape_spdx_requires():
    doc = sbom.build()
    check("declares SPDX 2.3", doc["spdxVersion"] == "SPDX-2.3", f"({doc['spdxVersion']})")
    check("carries the data licence SPDX mandates", doc["dataLicense"] == "CC0-1.0")
    check("the document has the reserved id", doc["SPDXID"] == "SPDXRef-DOCUMENT")
    check("the namespace is absolute",
          doc["documentNamespace"].startswith("https://"), f"({doc['documentNamespace']})")
    check("creation info names a creator",
          bool(doc["creationInfo"]["creators"]), f"({doc['creationInfo']})")
    check("the created stamp is UTC and second-resolution",
          re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", doc["creationInfo"]["created"]),
          f"({doc['creationInfo']['created']})")

    for package in doc["packages"]:
        check(f"{package['name']}: the SPDXID obeys the identifier grammar",
              re.match(r"^SPDXRef-[A-Za-z0-9.-]+$", package["SPDXID"]),
              f"({package['SPDXID']})")
        for field in ("name", "versionInfo", "downloadLocation",
                      "licenseConcluded", "licenseDeclared", "copyrightText"):
            check(f"{package['name']}: {field} is present",
                  field in package and package[field] != "", f"({package})")


def test_every_registry_component_reaches_the_sbom():
    """The failure this exists for: a component added to the registry and not to
    the SBOM would leave a signed document quietly claiming it is not there."""
    doc = sbom.build()
    named = {p["name"] for p in doc["packages"]}
    for name, *_ in legal.COMPONENTS:
        check(f"{name} is in the SBOM", name in named, f"({sorted(named)})")
    check("the program itself is described too", appinfo.APP_NAME in named)

    root = [p for p in doc["packages"] if p["name"] == appinfo.APP_NAME][0]
    describes = [r for r in doc["relationships"] if r["relationshipType"] == "DESCRIBES"]
    check("exactly one DESCRIBES relationship", len(describes) == 1, f"({describes})")
    check("and it points at the program", describes[0]["relatedSpdxElement"] == root["SPDXID"])
    contains = {r["relatedSpdxElement"] for r in doc["relationships"]
                if r["relationshipType"] == "CONTAINS"}
    check("every component is CONTAINED by the program",
          len(contains) == len(legal.COMPONENTS), f"({len(contains)})")


def test_the_declared_licences_are_real_spdx_and_match_the_registry():
    """A licence expression that is not a real SPDX id is worse than NOASSERTION:
    it looks authoritative to a tool that cannot check it."""
    doc = sbom.build()
    by_name = {p["name"]: p for p in doc["packages"]}
    # Hand-curated on purpose: the point is to catch an INVENTED identifier, and a
    # list fetched at test time would need the network. Each entry was read off the
    # official SPDX list before being added here - "Unlicense" (full name "The
    # Unlicense", active, OSI-approved) checked at spdx.org/licenses on 2026-08-17
    # when Tcl 9 brought libtommath into the bundle.
    known_ids = {
        "GPL-3.0-only", "LGPL-3.0-only", "GPL-2.0-only", "LGPL-3.0-or-later",
        "GPL-2.0-or-later", "BSD-3-Clause", "PSF-2.0", "TCL", "Zlib", "MIT",
        "Unlicense",
    }
    known_exceptions = {"Bootloader-exception"}

    for name, _module, _prose, _url, expression in legal.COMPONENTS:
        package = by_name[name]
        check(f"{name}: the SBOM declares the registry's expression",
              package["licenseDeclared"] == expression, f"({package['licenseDeclared']})")
        for token in re.split(r"\s+(?:OR|AND|WITH)\s+", expression):
            token = token.strip("()")
            if token.startswith("LicenseRef-"):
                declared = {e["licenseId"]
                            for e in doc.get("hasExtractedLicensingInfo", [])}
                check(f"{name}: {token} is defined in the document",
                      token in declared, f"({sorted(declared)})")
                continue
            check(f"{name}: {token} is a real SPDX identifier",
                  token in known_ids or token in known_exceptions, f"({expression})")


def test_the_generator_runs_as_a_script_and_writes_valid_json(tmp_path):
    """The release workflow calls it as a script, so that is what gets tested."""
    out = tmp_path / "sbom.spdx.json"
    run = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "sbom.py"),
                          "-o", str(out), "--namespace-seed", "v9.9.9"],
                         capture_output=True, text=True, cwd=ROOT)
    check("the script exits clean", run.returncode == 0, f"({run.stderr[-200:]})")
    check("it wrote the file", out.exists())
    doc = json.loads(out.read_text(encoding="utf-8"))
    check("the file parses as the document we built",
          doc["spdxVersion"] == "SPDX-2.3" and len(doc["packages"]) > 1)

    again = tmp_path / "again.json"
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "sbom.py"),
                    "-o", str(again), "--namespace-seed", "v9.9.9"],
                   capture_output=True, text=True, cwd=ROOT)
    second = json.loads(again.read_text(encoding="utf-8"))
    check("the same seed gives the same namespace, so two runs can be compared",
          doc["documentNamespace"] == second["documentNamespace"],
          f"({doc['documentNamespace']} vs {second['documentNamespace']})")


def test_the_bundle_guard_notices_a_component_the_registry_lacks(tmp_path):
    """Guard mode is the half that found zlib, libffi and the Microsoft runtime.

    It is fed a Syft scan and must object when the scan names something no
    registry entry accounts for. Tested with a synthetic scan rather than a real
    one, so it runs anywhere and does not need a build.
    """
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps({"artifacts": [
        {"name": "Python"}, {"name": "zlib"}, {"name": "WinDivert64"},
        {"name": "api-ms-win-core-file-l1-1-0.dll"}, {"name": "Bean Network Tester"},
    ]}), encoding="utf-8")
    check("a scan of known components is accepted", sbom.audit_bundle(str(clean)) == [],
          f"({sbom.audit_bundle(str(clean))})")

    dirty = tmp_path / "dirty.json"
    dirty.write_text(json.dumps({"artifacts": [
        {"name": "Python"}, {"name": "libcurl"}, {"name": "OpenSSL"},
    ]}), encoding="utf-8")
    found = sbom.audit_bundle(str(dirty))
    check("an unknown component is reported", "libcurl" in found and "OpenSSL" in found,
          f"({found})")


def test_the_sbom_names_the_pyinstaller_that_froze_the_build(monkeypatch):
    """The version of a build tool is knowable exactly where the build happens.

    `tools/sbom.py` runs in the release job minutes after PyInstaller froze the
    archive, so the installed distribution IS the one that made it. Until
    2026-08-12 this row said NOASSERTION, which was honest - nothing asked - and
    left the SBOM unable to name a component whose bootloader ships inside the
    binary under its own licence.

    Read through `importlib.metadata`, so asking the question never imports the
    build tool into `--license` on a developer's machine.
    """
    import importlib.metadata

    monkeypatch.setattr(importlib.metadata, "version", lambda name: "9.9.9")
    rows = {name: version for name, version, _lic, _url in legal.component_rows()}
    named = [n for n in rows if n.startswith("PyInstaller")]
    check("the registry still has exactly one PyInstaller row", len(named) == 1, f"({named})")
    check("it reports the installed version", rows[named[0]] == "9.9.9", f"({rows[named[0]]})")

    packages = {p["name"]: p["versionInfo"] for p in sbom.build()["packages"]}
    check("and the SBOM carries it", packages[named[0]] == "9.9.9", f"({packages[named[0]]})")


def test_a_build_tool_that_is_not_installed_is_not_invented(monkeypatch):
    """Inside the shipped executable there is no PyInstaller to ask.

    A build tool is not bundled with what it builds, so the SBOM's honest answer
    there is "no assertion" - the same answer this row gave before it could be
    resolved at all.

    The report the user of the binary reads keeps saying "bundled", which is the
    other half of the truth and easy to lose: the BOOTLOADER really is inside the
    executable, so "-" (this module's word for "not present here") would read as
    though the component were missing.
    """
    import importlib.metadata

    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    rows = {name: version for name, version, _lic, _url in legal.component_rows()}
    named = [n for n in rows if n.startswith("PyInstaller")][0]
    check("the report still says the component is in there",
          rows[named] == "bundled", f"({rows[named]})")

    packages = {p["name"]: p["versionInfo"] for p in sbom.build()["packages"]}
    check("and the SBOM says NOASSERTION, not a made-up version",
          packages[named] == "NOASSERTION", f"({packages[named]})")
