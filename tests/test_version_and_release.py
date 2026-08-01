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


# --- the release itself, not the code in it --------------------------------- #
#
# Everything above guards the tree. These three guard the ACT of releasing, which
# until 0.4.0 had no mechanical enforcement at all: the rules existed in prose
# ("the owner closes a version by setting VERSION.txt", "the version in
# release.yml and in ci.yml's build job must be the SAME") and three of them had
# already been broken in practice. Prose is not a guard.


CHANGELOG_FILES = ("CHANGELOG.md", "CHANGELOG-INTERNAL.md")
DATED_VERSION_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]\s+-\s+\d{4}-\d{2}-\d{2}\b")


def _versions_in(name):
    """-> {heading -> [section headings]} for every `## [...]` block."""
    path = os.path.join(ROOT, name)
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    blocks, current = {}, None
    for line in lines:
        if line.startswith("## ["):
            current = line.strip()
            blocks[current] = []
        elif line.startswith("### ") and current:
            blocks[current].append(line.strip())
    return blocks


def test_version_txt_has_a_dated_section_in_both_changelogs():
    """VERSION.txt must name a released, DATED section in both changelogs.

    The failure this closes is silent by construction: `release.yml` checks the
    tag against VERSION.txt and nothing else, so a version bumped without its
    changelog section being opened and dated publishes a release whose notes
    describe a different version. Nothing on the way there is red.

    It holds during ordinary development too, because VERSION.txt carries the
    LAST released version while new entries collect under [Unreleased] - so this
    is safe to run on every commit, not only at release time.
    """
    version = _version_txt()
    for name in CHANGELOG_FILES:
        headings = [h for h in _versions_in(name) if DATED_VERSION_RE.match(h)]
        match = [h for h in headings
                 if DATED_VERSION_RE.match(h).group(1) == version]
        check(f"{name}: VERSION.txt {version} has a dated `## [{version}] - YYYY-MM-DD` section",
              len(match) == 1, f"(found {match or headings[:3]})")


def test_the_mutable_changelog_sections_have_no_duplicate_headings():
    """One `### Added` per version, not three.

    Scope is deliberate and narrow:

    * only `CHANGELOG.md`, because `CHANGELOG-INTERNAL.md` is a chronological
      technical log whose headings carry information a type vocabulary cannot
      (`### ADR 2026-07-29: Nuitka ...`), and normalising those would delete
      content;
    * only the sections still MUTABLE - `[Unreleased]` and the one matching
      VERSION.txt. Older versions are published release notes: `[0.3.0]` does
      carry a duplicate `### Changed`, and rewriting notes people have already
      read is worse than the duplicate.

    Why it exists: the duplicates were merged by hand twice (commits `61601ad`,
    `0aaa86a`) and came back both times, because the only structural guard
    (`test_breaking_sections_come_first`) builds the section list and then looks
    at exactly one index of it.
    """
    version = _version_txt()
    blocks = _versions_in("CHANGELOG.md")
    mutable = [h for h in blocks
               if h == "## [Unreleased]"
               or (DATED_VERSION_RE.match(h)
                   and DATED_VERSION_RE.match(h).group(1) == version)]
    check("CHANGELOG.md: there is a mutable section to check", bool(mutable),
          "(neither [Unreleased] nor the VERSION.txt version was found)")

    for heading in mutable:
        sections = blocks[heading]
        dupes = sorted({s for s in sections if sections.count(s) > 1})
        check(f"CHANGELOG.md {heading}: no section heading appears twice",
              not dupes, f"({dupes})")

        unknown = sorted(set(sections) - {"### BREAKING", "### Added", "### Changed",
                                          "### Fixed", "### Removed", "### Docs"})
        check(f"CHANGELOG.md {heading}: only convention 39's section names",
              not unknown, f"({unknown})")


def test_ci_and_release_freeze_the_same_python():
    """PyInstaller bakes the interpreter into the bundle, so `ci.yml`'s build job
    and `release.yml` must use the SAME one - otherwise CI smoke-tests one
    artefact and users download another.

    That sentence was in PROJECT_NOTES and nothing enforced it. Parsed by line
    scan rather than a YAML library on purpose: PyYAML is not in
    requirements-dev.txt, so importing it would make this test an error on a
    fresh CI checkout. The scan FAILS when it cannot find what it expects - a
    guard that silently passes when the file moves under it is not a guard.
    """
    def python_versions(path, inside_job=None):
        with open(os.path.join(ROOT, ".github", "workflows", path),
                  encoding="utf-8") as f:
            lines = f.read().splitlines()
        if inside_job is not None:
            starts = [i for i, ln in enumerate(lines)
                      if re.match(r"^  [A-Za-z0-9_-]+:\s*$", ln)]
            wanted = [i for i in starts if lines[i].strip() == f"{inside_job}:"]
            check(f"{path}: the {inside_job!r} job is still there", len(wanted) == 1,
                  f"(jobs found: {[lines[i].strip() for i in starts]})")
            begin = wanted[0]
            after = [i for i in starts if i > begin]
            lines = lines[begin:after[0] if after else len(lines)]
        found = re.findall(r'python-version:\s*"?([0-9][0-9.]*)"?', "\n".join(lines))
        check(f"{path}: a literal python-version is declared", bool(found),
              "(none found - did the key move or become a variable?)")
        return set(found)

    release = python_versions("release.yml")
    build = python_versions("ci.yml", inside_job="build")
    check("release.yml freezes exactly one Python", len(release) == 1, f"({release})")
    check("ci.yml's build job and release.yml freeze the SAME Python",
          release == build, f"(release={release} ci-build={build})")
