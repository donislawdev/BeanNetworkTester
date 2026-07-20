"""Release hygiene: one version, present legal files, a valid VERSION.txt.

These guard the things that are easy to get subtly wrong at release time and
impossible to notice by looking: a version number that drifted between two files,
a licence that did not make it into the tree, a VERSION.txt in the wrong shape.
"""
import os
import re

from fakes import ROOT, check

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _version_txt():
    with open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8") as f:
        return f.read().strip()


def test_version_txt_is_well_formed():
    version = _version_txt()
    check("VERSION.txt is a single x.y.z line", bool(VERSION_RE.match(version)),
          f"({version!r})")


def test_appinfo_reads_version_txt():
    from beantester import appinfo
    check("appinfo.__version__ matches VERSION.txt",
          appinfo.__version__ == _version_txt(),
          f"(appinfo={appinfo.__version__!r} file={_version_txt()!r})")
    check("appinfo did not fall back to 0.0.0", appinfo.__version__ != "0.0.0")


def test_no_hardcoded_version_literals():
    """The version lives in VERSION.txt. No source file may carry an x.y.z literal
    that could drift from it (pyproject uses dynamic version; the spec reads
    appinfo). A stray '1.5.1' left in a module is exactly the bug that made the
    tool disagree with itself about its own version.
    """
    import glob
    version = _version_txt()
    literal = re.compile(r"\b\d+\.\d+\.\d+\b")
    offenders = []
    # appinfo defines the fallback constant, VERSION.txt is the source; skip both.
    for path in glob.glob(os.path.join(ROOT, "beantester", "**", "*.py"),
                          recursive=True):
        src = open(path, encoding="utf-8").read()
        for match in literal.findall(src):
            if match == version:
                offenders.append(f"{os.path.relpath(path, ROOT)}: {match}")
    check("no module hard-codes the current version number", not offenders,
          f"({offenders})")


def test_legal_files_are_present():
    for name in ("LICENSE", "THIRD-PARTY-NOTICES.md"):
        check(f"{name} ships with the project",
              os.path.exists(os.path.join(ROOT, name)))
    licenses = os.path.join(ROOT, "licenses")
    check("licenses/ directory ships", os.path.isdir(licenses))
    for text in ("LGPL-3.0.txt", "GPL-2.0.txt", "psutil-LICENSE.txt",
                 "Python-LICENSE.txt", "PyInstaller-COPYING.txt"):
        check(f"licenses/{text} is present",
              os.path.exists(os.path.join(licenses, text)))


def test_license_is_gplv3():
    """The project is released under the GNU GPL v3 (free & open source, copyleft).

    LICENSE must be the verbatim GPLv3 text so GitHub detects it and the copyleft
    terms actually apply. It is no longer the old proprietary no-resale licence.
    """
    text = open(os.path.join(ROOT, "LICENSE"), encoding="utf-8").read()
    check("LICENSE is the GNU General Public License",
          "GNU GENERAL PUBLIC LICENSE" in text)
    check("LICENSE is version 3", "Version 3" in text)
    check("LICENSE is no longer MIT", "MIT License" not in text)
    check("LICENSE is no longer the proprietary no-resale licence",
          "Bean Network Tester License" not in text
          and "may not be sold" not in text.lower())


def test_no_stale_license_references_in_metadata():
    pyproject = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    check("pyproject no longer declares the MIT classifier",
          "MIT License" not in pyproject)
    check("pyproject no longer declares the proprietary classifier",
          "Other/Proprietary License" not in pyproject)
    check("pyproject declares the GPLv3 classifier",
          "GNU General Public License v3 (GPLv3)" in pyproject)
    # The spec is git-ignored by pattern (*.spec) and re-included by an exception
    # (!BeanNetworkTester.spec). If that exception is not honoured - or the file was
    # never force-added - it goes missing on a fresh checkout, which is a real
    # problem (the build job needs it), but it must fail with a READABLE message,
    # not a raw FileNotFoundError from deep inside a test.
    spec_path = os.path.join(ROOT, "BeanNetworkTester.spec")
    check("BeanNetworkTester.spec is present in the checkout "
          "(it is git-ignored by *.spec; it must be force-added: "
          "git add -f BeanNetworkTester.spec)",
          os.path.exists(spec_path))
    if os.path.exists(spec_path):
        spec = open(spec_path, encoding="utf-8").read()
        check("the exe metadata no longer says MIT", "MIT License" not in spec)


def test_breaking_sections_come_first():
    """Convention 39: `### BREAKING` must be the FIRST section of its version.

    The point of the rule is that a reader scanning a release sees the contract
    breakage before anything else. This guard exists because the rule was broken two
    chunks after it was written down: a `Fixed` entry was inserted above `BREAKING`
    in both changelogs and nothing noticed - the em/en-dash guard reads changelog
    TEXT, never its structure.
    """
    for name in ("CHANGELOG.md", "CHANGELOG-INTERNAL.md"):
        lines = open(os.path.join(ROOT, name), encoding="utf-8").read().splitlines()
        version, sections = None, []
        problems = []

        def close(version, sections):
            if version and "### BREAKING" in sections and sections[0] != "### BREAKING":
                problems.append(f"{name} {version}: BREAKING is #{sections.index('### BREAKING') + 1}"
                                f" of {len(sections)} (first is {sections[0]!r})")

        for line in lines:
            if line.startswith("## "):
                close(version, sections)
                version, sections = line.strip(), []
            elif line.startswith("### ") and version:
                sections.append(line.strip())
        close(version, sections)

        check(f"{name}: every BREAKING section comes first in its version",
              not problems, f"({problems})")
