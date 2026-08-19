"""Release hygiene: one version, present legal files, a valid VERSION.txt.

These guard the things that are easy to get subtly wrong at release time and
impossible to notice by looking: a version number that drifted between two files,
a licence that did not make it into the tree, a VERSION.txt in the wrong shape.
"""
import os
import re
import subprocess
import sys

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
                 "Python-LICENSE.txt", "PyInstaller-COPYING.txt",
                 "zlib-LICENSE.txt"):
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
    # CHANGELOG-INTERNAL.md is not in the repository (it is a maintainer file, kept
    # in the private notes repo), so no test here can read it. Its structure is
    # guarded by `.claude/hooks/check_notes.py`, which runs where the file exists.
    for name in ("CHANGELOG.md",):
        lines = open(os.path.join(ROOT, name), encoding="utf-8").read().splitlines()
        version, sections = None, []
        problems = []

        def close(version, sections):
            if version and "### BREAKING" in sections and sections[0] != "### BREAKING":
                # B023 is false here: one file, one iteration - the closure
                # cannot outlive the loop that made it.
                problems.append(f"{name} {version}: BREAKING is #{sections.index('### BREAKING') + 1}"  # noqa: B023
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


# Only the shipped changelog. The internal one is a maintainer file kept out
# of the repository, so its guards live in `.claude/hooks/check_notes.py`.
CHANGELOG_FILES = ("CHANGELOG.md",)
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


def test_version_txt_has_a_dated_section_in_the_changelog():
    """VERSION.txt must name a released, DATED section in the changelog.

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


def _mutable_headings(blocks):
    """The `## [...]` blocks still open to editing: [Unreleased] and VERSION.txt's.

    Everything older is a published release note. `[0.3.0]` carries a duplicate
    `### Changed` and entries far over the length cap below, and rewriting notes
    people have already read is worse than leaving them.
    """
    version = _version_txt()
    return [h for h in blocks
            if h == "## [Unreleased]"
            or (DATED_VERSION_RE.match(h)
                and DATED_VERSION_RE.match(h).group(1) == version)]


def test_no_user_facing_entry_grows_into_an_essay():
    """A CHANGELOG.md entry is at most 100 words. It is a release note, not an ADR.

    Convention 39 already says this file carries the EFFECT for a tester while
    CHANGELOG-INTERNAL.md carries the reasoning, and nothing enforced it: the
    [0.4.0] section reached **11 338 words across 92 entries, median 115, longest
    342** before it was rewritten to 4 023 / 67 / 65 / 93. The owner's verdict was
    the plain one - nobody will read that.

    100 rather than the ~40 most entries manage, because the handful that carry a
    behaviour change a reader must act on (what breaks, what to do instead) really
    do need the room, and a cap that forces those into three entries is worse than
    one long one. The cap is the ceiling, not the target.

    CHANGELOG.md only, and only the mutable sections - same scope, same reasons,
    as the duplicate-heading guard below.
    """
    path = os.path.join(ROOT, "CHANGELOG.md")
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    entry, offenders, entries = None, [], 0

    def close(entry):
        if not entry:
            return
        words = len(" ".join(entry).split())
        if words > 100:
            offenders.append((words, entry[0][:70]))

    mutable = set(_mutable_headings(_versions_in("CHANGELOG.md")))
    inside = False
    for line in lines:
        if line.startswith("## ["):
            close(entry) if inside else None
            entry, inside = None, line.strip() in mutable
        elif inside and re.match(r"^- ", line):
            close(entry)
            entry = [line]
            entries += 1
        elif inside and line.startswith("### "):
            close(entry)
            entry = None
        elif inside and entry is not None:
            entry.append(line)
    close(entry)

    check("CHANGELOG.md: the mutable section has entries to measure", entries > 0,
          "(none found - did the section markers change?)")
    check(f"CHANGELOG.md: no entry over 100 words ({entries} checked)",
          not offenders, f"({sorted(offenders, reverse=True)[:3]})")


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
    blocks = _versions_in("CHANGELOG.md")
    mutable = _mutable_headings(blocks)
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


def test_release_notes_extract_every_released_version():
    """`tools/release_notes.py` is what the release page shows, so it is load-bearing.

    It must produce a non-empty body for every version in CHANGELOG.md, must not
    repeat the `## [x.y.z]` heading (gh sets the title), and must refuse an
    unknown version loudly - an empty release body would publish happily and be
    noticed by users rather than by us.

    The encoding case is not hypothetical. `release.yml` runs on windows-latest,
    where stdout still defaults to the ANSI code page, and `[0.3.0]` contains
    U+25CF: writing it as str raised UnicodeEncodeError and would have failed the
    publish step. The tool writes UTF-8 bytes, and this test reads them back as
    bytes so a regression cannot hide behind the test's own decoding.
    """
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    try:
        import release_notes
    finally:
        sys.path.pop(0)

    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        text = f.read()
    versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, re.M)
    check("CHANGELOG.md declares released versions to extract", bool(versions),
          f"({versions})")

    for version in versions:
        body = release_notes.section(version, text)
        check(f"release notes for {version} are not empty", bool(body and body.strip()))
        check(f"release notes for {version} drop the version heading",
              not (body or "").lstrip().startswith("## ["))
        check(f"release notes for {version} stop before the next version",
              "## [" not in (body or ""))
        check(f"release notes for {version} survive a round trip through UTF-8",
              body.encode("utf-8").decode("utf-8") == body)

    check("an unknown version yields nothing rather than an empty-looking body",
          release_notes.section("99.99.99", text) is None)

    # Run the real process for EVERY version, not just VERSION.txt's.
    #
    # This is the half that matters and the half that was missing. The first
    # version of this test ran the subprocess once, for VERSION.txt - which is
    # 0.4.0, and 0.4.0 is pure ASCII. Reverting the UTF-8 byte write therefore
    # left the test GREEN: it never fed the process the character that breaks it.
    # Caught by mutation, and only after re-running the mutants from a clean
    # baseline, because release_notes.py was untracked and `git checkout` had been
    # silently restoring nothing.
    script = os.path.join(ROOT, "tools", "release_notes.py")
    non_ascii_seen = False
    for version in versions:
        out = subprocess.run([sys.executable, script, version], capture_output=True)
        check(f"release_notes.py exits 0 for {version}", out.returncode == 0,
              f"({out.returncode}, {out.stderr[-200:]!r})")
        check(f"release_notes.py writes decodable UTF-8 for {version}",
              bool(out.stdout) and out.stdout.decode("utf-8").strip(),
              f"({out.stdout[:80]!r})")
        if any(b > 127 for b in out.stdout):
            non_ascii_seen = True

    # Without this the encoding guard above can quietly stop guarding anything:
    # an all-ASCII changelog would pass it on every version while the console
    # encoding path goes untested. [0.3.0] carries U+25CF and is frozen history,
    # so this holds today - and says so out loud if it ever stops.
    check("at least one released section carries non-ASCII, so the encoding path is "
          "actually exercised", non_ascii_seen,
          "(every section is ASCII - this test no longer proves the Windows "
          "console-encoding fix)")

    missing = subprocess.run([sys.executable,
                              os.path.join(ROOT, "tools", "release_notes.py"), "99.99.99"],
                             capture_output=True)
    check("release_notes.py fails loudly on an unknown version",
          missing.returncode != 0 and not missing.stdout.strip(),
          f"(rc={missing.returncode}, stdout={missing.stdout[:80]!r})")


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


def test_both_workflows_install_the_same_pinned_builder():
    """PyInstaller decides whether the shipped exe starts, so its version is part
    of the artefact - and both workflows must take it from ONE pinned file.

    Paid for on 2026-08-17: `pyinstaller` was installed unpinned in both
    workflows, CI resolved 6.22.1 and this machine had 6.21.0, and only the older
    one mis-handles the DLL-embedded Tcl/Tk 9 library archive that Python 3.14
    ships. Result: the same commit produced a working exe on CI and one that died
    in PyInstaller's own tkinter run-time hook locally. The interpreter had a
    parity guard (above); the freezer had none.

    Checks the shape of the failure, not just the presence of a string: an
    unpinned install is rejected wherever it appears, so re-adding a bare
    `pyinstaller` to either workflow reddens this.
    """
    pin_file = "requirements-build.txt"
    with open(os.path.join(ROOT, pin_file), encoding="utf-8") as f:
        pins = [ln.strip() for ln in f
                if ln.strip() and not ln.lstrip().startswith("#")]
    check(f"{pin_file} pins exactly one package", len(pins) == 1, f"({pins})")
    check(f"{pin_file} pins it with == ", bool(re.match(r"^pyinstaller==\d", pins[0])),
          f"({pins[0]!r} - a range or a bare name is not a pin)")

    for path in ("ci.yml", "release.yml"):
        with open(os.path.join(ROOT, ".github", "workflows", path),
                  encoding="utf-8") as f:
            body = f.read()
        installs = re.findall(r"^\s*pip install .*$", body, re.MULTILINE)
        check(f"{path}: still has a pip install line", bool(installs),
              "(none found - did the step move or change shape?)")
        builder = [ln for ln in installs if f"-r {pin_file}" in ln]
        check(f"{path}: installs the builder from {pin_file}", bool(builder),
              f"(install lines: {installs})")
        loose = [ln for ln in installs
                 if re.search(r"(?<!-r )\bpyinstaller\b(?!==)", ln)
                 and pin_file not in ln]
        check(f"{path}: never installs pyinstaller unpinned", not loose,
              f"({loose} - put the version in {pin_file}, not on the command line)")


def test_the_downloads_tool_refuses_anything_that_is_not_owner_slash_name():
    """``--repo`` lands in the PATH of an api.github.com URL.

    Semgrep flagged the `urlopen` call (`dynamic-urllib-use-detected`) for the
    reason it usually flags one: a dynamic value could carry a `file://` scheme.
    It cannot here - the scheme is a literal - but the value does become part of
    the path, so `--repo ../../gists` would quietly ask a different endpoint the
    question and print whatever came back as if those were releases. Nobody is
    attacked by that (it is a maintainer's own tool), and it is still three lines
    to make the argument mean what its name says.
    """
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import downloads

    for good in ("donislawdev/BeanNetworkTester", "a/b", "Some.Owner/repo-name_1"):
        check(f"{good} is accepted as a repository", bool(downloads.REPO.match(good)))

    for bad in ("../../gists", "owner", "owner/name/extra", "owner/name?x=1",
                "https://example.test/o/n", "owner name", ""):
        rejected = True
        try:
            downloads.fetch_releases(bad)
        except ValueError:
            pass
        except Exception as exc:            # noqa: BLE001 - any other error means it TRIED
            rejected = False
            reason = exc
        else:
            rejected = False
            reason = "no error at all"
        check(f"{bad!r} is refused before it becomes a URL", rejected,
              "" if rejected else f"({reason})")


def test_the_release_attests_exactly_the_archive_it_publishes():
    """Two attestations, one subject, and the subject is the download.

    A release carries two signed statements about the zip: an SBOM attestation
    (what is inside it) and a build-provenance attestation (which repository,
    commit and workflow produced it). Both are worth nothing if they name a
    different file from the one `gh release create` uploads, and that mismatch is
    invisible on the release page - the attestation store simply ends up holding a
    statement about a digest nobody downloads.

    So this pins the shape rather than the wording: every `subject-path` in the
    workflow names the same variable the publish step uploads, and both actions
    are still there.
    """
    import re
    with open(os.path.join(ROOT, ".github", "workflows", "release.yml"),
              encoding="utf-8") as handle:
        text = handle.read()

    subjects = re.findall(r"subject-path:\s*(\S.*?)\s*$", text, re.MULTILINE)
    check("both attestations name a subject", len(subjects) == 2, f"({subjects})")
    check("both attest the same file", len(set(subjects)) == 1, f"({subjects})")

    publish = re.search(r"gh release create[^\n]*", text)
    check("the workflow publishes a release", publish is not None)
    uploaded = publish.group(0) if publish else ""
    # `subject-path: ${{ env.ASSET }}` against `gh release create ... "$ASSET" ...`
    name = subjects[0].strip("${} ").replace("env.", "").strip()
    check(f"the attested subject ({name}) is what gets uploaded",
          ("$" + name) in uploaded or ("${" + name + "}") in uploaded,
          f"({uploaded[:120]})")

    for action in ("actions/attest@", "actions/attest-build-provenance@"):
        check(f"{action} is still in the release workflow", action in text)


def test_every_pinned_runtime_requirement_carries_its_artefact_hashes():
    """A version pins a NUMBER. Hashes pin the BYTES.

    `pydivert==3.1.3` says which release to fetch, and says nothing about what
    comes back: an index or a publishing account that has been taken over can
    serve different bytes under the same version, and this particular wheel
    carries the WinDivert kernel driver that gets installed on a user's machine.
    With hashes present pip refuses anything that does not match.

    Measured while writing this (2026-08-19), because the failure mode is not the
    obvious one: corrupting the hash of ONE artefact does not fail the install -
    pip falls back to another artefact of the same version, which is why every
    artefact PyPI published for that version is listed. Corrupting them all is
    what produces "THESE PACKAGES DO NOT MATCH THE HASHES" and exit 1.

    This runs offline, so it checks the SHAPE rather than the values: the file
    that ships cannot quietly lose its hashes. Regenerate with
    `python tools/pin_hashes.py requirements.txt`.
    """
    import re
    path = os.path.join(ROOT, "requirements.txt")
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    pinned = {}
    current = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("--hash="):
            check("a hash line follows a requirement", current is not None, f"({stripped[:40]})")
            digest = stripped[len("--hash="):].rstrip(" \\")
            check(f"{current}: sha256 in the shape pip reads",
                  re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None, f"({digest[:24]})")
            pinned[current].append(digest)
            continue
        match = re.match(r"^([A-Za-z0-9._-]+)==", stripped)
        check(f"every requirement is pinned with == ({stripped[:40]})", match is not None)
        current = match.group(1) if match else None
        pinned[current] = []

    check("the file still names its requirements", len(pinned) >= 2, f"({sorted(pinned)})")
    bare = [name for name, hashes in pinned.items() if not hashes]
    check("every pinned requirement carries at least one hash", not bare, f"({bare})")
    # More than one, or pip's fallback to another artefact of the same version
    # would be an unhashed path back in through the front door.
    thin = [name for name, hashes in pinned.items() if len(hashes) < 2]
    check("each names every artefact, not just the one this machine picks",
          not thin, f"({thin})")


def test_the_dev_requirements_do_not_pull_in_the_hashed_file():
    """The two cannot share one `pip install`, and the reason is pip's, not ours.

    Hash-checking is turned on for the WHOLE install as soon as one requirement
    carries a hash. `requirements-dev.txt` deliberately tracks latest - that is
    what the weekly run watches - so including the hashed runtime file would
    demand hashes for pytest, hypothesis and everything underneath them.
    """
    with open(os.path.join(ROOT, "requirements-dev.txt"), encoding="utf-8") as handle:
        text = handle.read()
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    check("requirements-dev.txt does not include requirements.txt",
          not any(ln.startswith("-r requirements.txt") for ln in lines), f"({lines[:3]})")
    check("it still lists the test tooling", any("pytest" in ln for ln in lines), f"({lines})")
