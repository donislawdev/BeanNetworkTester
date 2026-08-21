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
                if ln.strip() and not ln.lstrip().startswith("#")
                and not ln.strip().startswith("--hash=")]
    # Since 2026-08-19 this file pins the whole CLOSURE, not just the freezer:
    # pinning the top of the tree left seven packages free to move underneath
    # it, one of which decides what goes inside the bundle and ships monthly.
    unpinned = [p for p in pins if not re.match(r"^[A-Za-z0-9._-]+==\d", p.rstrip(" \\"))]
    check(f"{pin_file}: every package in the closure is pinned with ==",
          not unpinned, f"({unpinned} - a range or a bare name is not a pin)")
    check(f"{pin_file}: the freezer itself is still pinned there",
          any(re.match(r"^pyinstaller==\d", p) for p in pins), f"({pins[:3]})")

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


def test_the_release_never_publishes_an_unsigned_archive():
    """The build workflow opens a DRAFT and hands the archive over. It does not ship it.

    🔴 The reason is that the build is not finished when the build workflow ends. The
    executable inside is unsigned, and this runner cannot sign it: the key lives on a
    cryptographic card in a USB reader and cannot be exported, which is the whole
    value of it. So the archive leaves as a workflow ARTEFACT, `tools/sign_release.py`
    signs it where the card is, and the release stays a draft until a person looks at
    it.

    What this guards is the shape of that split, because every piece of it is one line
    somebody could "simplify" back into a single publish step:

    * `gh release create` must pass `--draft`, and must NOT carry the archive. An
      unsigned executable on a public release page, for as long as the ritual takes,
      is a file somebody downloads;
    * the archive must leave as an artefact instead, under the name the signing script
      fetches - a rename here strands the ritual with a clear-looking error much later;
    * no `SHA256SUMS.txt` is written here. These are not the bytes a user gets, and a
      checksum describing a file nobody has is worse than none.

    The provenance attestation stays, over the unsigned build, because that is the one
    thing this workflow can honestly say: it built these bytes from this commit.
    """
    path = os.path.join(ROOT, ".github", "workflows", "release.yml")
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    code = [ln.split("#", 1)[0] for ln in lines]
    body = "\n".join(code)

    # The WHOLE step, not just the `gh release create` line: the flags are assembled
    # in an array above it, so a guard reading one line reads the wrong thing - and
    # would have passed while `--draft` was missing.
    import re
    step = re.search(r"- name: Open the release as a DRAFT.*?(?=\n      - |\Z)",
                     body, re.S)
    check("the workflow still opens a release", step is not None)
    opening = step.group(0) if step else ""
    check("it opens it as a draft", "--draft" in opening, f"({opening[-200:]})")
    created = re.search(r"gh release create(?:[^\n]*\\\n)*[^\n]*", opening)
    created = created.group(0) if created else ""
    check("it does not publish the archive", "$ASSET" not in created,
          f"(an unsigned executable would sit on a public page: {created[:160]})")
    check("it writes no checksum over bytes nobody downloads",
          "SHA256SUMS.txt" not in body,
          "(the checksum belongs next to the signature, over the same bytes)")

    check("the build leaves as an artefact",
          "actions/upload-artifact@" in body, "(the signing script fetches it)")
    check("under the name the signing script fetches",
          "unsigned-build-" in body and "unsigned-build-%s" in
          _read_text(os.path.join(ROOT, "tools", "sign_release.py")),
          "(rename this on one side only and the ritual strands)")

    check("build provenance is still attested here",
          "actions/attest-build-provenance@" in body,
          "(this workflow DID build these bytes - that claim is true and worth making)")


def test_the_signed_archive_is_attested_over_bytes_the_job_holds():
    """The second half of a release: a statement about the file a user downloads.

    The signature changes the bytes, so a statement made at build time verifies
    against nothing afterwards. `attest-release.yml` makes it after the signing,
    which raises the question this guards: how does a workflow attest something a
    person made on their own machine without lying?

    🔴 By downloading it. The job fetches the archive from the draft, so everything it
    attests is about bytes it is holding - the difference between an attestation and a
    rumour. The digest it was dispatched with is kept as a cross-check and the run
    stops when the two disagree, which is what "something moved between signing and
    publishing" looks like.

    Deliberately NOT here: build provenance. That belongs to the workflow that built
    something, and claiming it in the one document nobody should have to doubt would
    be false.

    The bundle is published as an ASSET, not left only in the attestation store, and
    the extension is part of what this guards: OpenSSF Scorecard's Signed-Releases
    check reads release assets by file extension and never opens that store (measured
    2026-08-19, `probes/releasesAreSigned`), and a user with no route to the API
    cannot use the store either.
    """
    path = os.path.join(ROOT, ".github", "workflows", "attest-release.yml")
    check("the attestation workflow exists", os.path.exists(path))
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    code = [ln.split("#", 1)[0] for ln in lines]
    body = "\n".join(code)

    check("it is asked for, not automatic", "workflow_dispatch:" in body)
    check("it fetches what was signed", "gh release download" in body)
    check("it attests bytes it holds, not a digest it was told",
          "subject-path:" in body and "subject-digest:" not in body,
          "(attesting a digest nobody checked is a rumour with a signature on it)")
    check("it cross-checks the digest it was dispatched with",
          "CLAIMED" in body and "exit 1" in body)
    check("it binds the SBOM to that same file", "sbom-path:" in body)
    check("it does not claim to have built it",
          "attest-build-provenance" not in body,
          "(a person signed it on their own machine - saying otherwise is false)")
    check("the bundle is published as an asset",
          ".sigstore.json" in body and "gh release upload" in body)


def test_the_signing_certificate_is_pinned_by_its_bytes():
    """"Signed" is a claim. "Signed by THIS certificate" is a measurement.

    A second code-signing certificate on the same machine - a renewal, a test one, one
    from another project - would sign a release just as happily, and the release page
    would look identical. So the certificate is pinned by the sha256 of its DER bytes,
    the signing script reads the certificate back OUT of the file it just signed, and
    it refuses to upload anything when the two disagree.

    Same shape as `WINDIVERT_SHA256`, and for the same reason: a version, a subject
    line or a file name is a label, and a digest is not.

    The certificate expires; a renewal issues a new one and this digest moves with it.
    The guard failing on that day is the point.
    """
    from beantester.legal import CODESIGN_SHA256
    import re
    check("the certificate is pinned as a sha256",
          re.fullmatch(r"[0-9a-f]{64}", CODESIGN_SHA256) is not None,
          f"({CODESIGN_SHA256[:24]}...)")

    script = _read_text(os.path.join(ROOT, "tools", "sign_release.py"))
    check("the signing script reads the pin rather than carrying its own copy",
          "from beantester.legal import CODESIGN_SHA256" in script)
    check("it compares what actually signed the file against the pin",
          "actual != CODESIGN_SHA256" in script)
    check("and refuses without uploading anything",
          "Nothing has been uploaded." in script,
          "(a mismatch caught after the upload is not caught)")
    check("it timestamps the signature",
          "/tr" in script and "time.certum.pl" in script,
          "(without a timestamp the signature dies when the certificate expires)")


def _read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _check_every_requirement_carries_hashes(filename):
    """Shared by the two hash-checked files: every line pinned, every pin hashed.

    Offline on purpose - it reads the SHAPE, not the values, so it says the same
    thing on a runner with no network as it does here.
    """
    import re
    with open(os.path.join(ROOT, filename), encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    pinned = {}
    current = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("--hash="):
            check(f"{filename}: a hash line follows a requirement",
                  current is not None, f"({stripped[:40]})")
            digest = stripped[len("--hash="):].rstrip(" \\")
            check(f"{filename}: {current}: sha256 in the shape pip reads",
                  re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None, f"({digest[:24]})")
            pinned[current].append(digest)
            continue
        match = re.match(r"^([A-Za-z0-9._-]+)==", stripped)
        check(f"{filename}: every requirement is pinned with == ({stripped[:40]})",
              match is not None)
        current = match.group(1) if match else None
        pinned[current] = []

    check(f"{filename} still names its requirements", len(pinned) >= 2, f"({sorted(pinned)})")
    bare = [name for name, hashes in pinned.items() if not hashes]
    check(f"{filename}: every pinned requirement carries at least one hash",
          not bare, f"({bare})")
    # More than one, or pip's fallback to another artefact of the same version
    # would be an unhashed path back in through the front door.
    thin = [name for name, hashes in pinned.items() if len(hashes) < 2]
    check(f"{filename}: each names every artefact, not just the one this machine picks",
          not thin, f"({thin})")


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
    _check_every_requirement_carries_hashes("requirements.txt")


def test_the_analysis_tools_carry_their_artefact_hashes_too():
    """Same shape, second file - and here the closure is the point.

    `requirements-lint.txt` used to pin three tools by version alone. Since
    2026-08-19 it is hash-checked, which is all-or-nothing in pip: the moment one
    requirement carries a hash, EVERY package the install resolves needs one. So
    the file holds the whole closure (13 packages, resolved for Python 3.14 and
    measured identical on manylinux2014_x86_64 and win_amd64), not just the three
    names a person chose.

    That is what this guards. Losing a transitive line does not loosen a pin -
    it breaks the install outright, on every job at once, which is a confusing
    failure to meet for the first time on a runner. Regenerate with
    `python tools/pin_hashes.py requirements-lint.txt`.

    semgrep and pip-audit are deliberately NOT here: they live in
    requirements-scan.txt, pinned by version and not by hash, for the reasons
    written in that file. See test_the_scanners_are_pinned_by_version_at_least.
    """
    _check_every_requirement_carries_hashes("requirements-lint.txt")


def test_the_scanners_are_pinned_by_version_at_least():
    """The file we chose NOT to hash still has to pin.

    requirements-scan.txt is the one place here that answers "pinned by version,
    not by bytes", and the reason is written there: the two scanners' closures are
    tens of packages, and neither can put a byte into a release. That is a decision
    about hashes - it is not permission to let the versions float, which would put
    the semgrep engine and the pip-audit database back on "green yesterday, red
    today with no commit behind it".
    """
    import re
    with open(os.path.join(ROOT, "requirements-scan.txt"), encoding="utf-8") as handle:
        lines = [ln.strip() for ln in handle.read().splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
    check("requirements-scan.txt still names its scanners", len(lines) >= 2, f"({lines})")
    loose = [ln for ln in lines if not re.match(r"^[A-Za-z0-9._-]+==\d", ln)]
    check("every scanner is pinned with ==", not loose, f"({loose})")
    for tool in ("semgrep", "pip-audit"):
        check(f"{tool} is still pinned in requirements-scan.txt",
              any(ln.startswith(tool + "==") for ln in lines), f"({lines})")


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


def _workflow_paths():
    import glob
    return sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")))


def test_no_workflow_bootstraps_pip_from_the_index():
    """`pip install --upgrade pip` was the one unverified link in a hash-checked chain.

    Every install in these workflows that matters is `--require-hashes`, and the
    program doing the checking was itself fetched from the index, unpinned, one line
    earlier. A poisoned pip is then the thing verifying our hashes, and it is the
    last place anybody would look. Removed in five places on 2026-08-19; the pip that
    checks them is the one `setup-python` shipped with the interpreter, and that
    action is pinned by SHA.

    🔴 This guard exists because the SCANNER cannot see most of them. OpenSSF
    Scorecard skips steps that run in a Windows shell (`checks/raw/
    shell_download_validate.go`: "Skip unsupported shells. We don't support Windows
    shells"), and three of the five were in `windows-latest` jobs - so it reported
    two and stayed quiet about the rest. Fixing only what a scanner names is how a
    repository ends up green and unchanged.
    """
    offenders = []
    for path in _workflow_paths():
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle.read().splitlines(), 1):
                code = line.split("#", 1)[0]
                if "pip install" in code and "--upgrade" in code and "pip" in code.split("--upgrade")[1]:
                    offenders.append(f"{os.path.basename(path)}:{number}")
    check("no workflow upgrades pip from the index before checking hashes",
          not offenders, f"({offenders})")


def test_every_install_of_a_hashed_file_asks_pip_to_check_the_hashes():
    """The flag is not decoration: without it the hashes are advisory.

    pip does turn hash-checking on by itself when a requirement carries a hash, so
    dropping `--require-hashes` would still verify what is written down - and would
    silently stop being an error the day a line loses its hash block. The flag makes
    that an install failure instead of a quiet downgrade, which is the same reason
    it is what OpenSSF Scorecard looks for (`isUnpinnedPipInstall`, read 2026-08-19:
    the flag is the ONLY thing that makes a pip command count as pinned).
    """
    import re
    hashed = ("requirements.txt", "requirements-build.txt", "requirements-lint.txt")
    seen, bare = 0, []
    for path in _workflow_paths():
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle.read().splitlines(), 1):
                code = line.split("#", 1)[0]
                if not re.search(r"\bpip install\b", code):
                    continue
                names = [f for f in hashed if f"-r {f}" in code]
                if not names:
                    continue
                seen += 1
                if "--require-hashes" not in code:
                    bare.append(f"{os.path.basename(path)}:{number} {names}")
    check("the hashed files are still installed by these workflows", seen >= 5, f"({seen})")
    check("every install of a hashed file passes --require-hashes", not bare, f"({bare})")


def test_the_release_workflow_grants_write_on_the_job_not_the_whole_file():
    """A permission belongs to the job that uses it, never to the file.

    release.yml is the only workflow that can publish an asset under this project's
    name, and it held `contents: write` at the top - inherited by every job added to
    that file later, by an author with no reason to scroll up. Named by OpenSSF
    Scorecard (Token-Permissions, 0/10) and moved onto the single `release` job on
    2026-08-19. ci.yml, pages.yml and scorecard.yml already worked this way.

    Read as text: PyYAML is deliberately not a test dependency (same choice as
    test_site.py and the CI-jobs guard in test_readme_guards.py).
    """
    path = os.path.join(ROOT, ".github", "workflows", "release.yml")
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    top, inside = [], False
    for line in lines:
        if line.startswith("permissions:"):
            inside = True
            continue
        if inside:
            if line.startswith(" "):
                top.append(line.strip())
                continue
            if not line.strip():
                continue
            break
    check("release.yml still declares top-level permissions", bool(top), f"({top})")
    granted = [entry for entry in top
               if not entry.startswith("#") and entry.endswith(": write")]
    check("release.yml grants nothing writable at the top level", not granted, f"({granted})")

    body = "\n".join(lines)
    for scope in ("contents: write", "id-token: write", "attestations: write"):
        check(f"the release job still asks for {scope}",
              f"      {scope}" in body, "(a six-space indent is the job's own block)")


def test_the_documented_verify_command_matches_what_we_actually_attest():
    """The README hands users a command. It has to be the command that works.

    🔴 Paid for on 2026-08-19, on a real release: the first version of that line was
    `gh attestation verify <zip> --bundle <bundle>` and it fails twice over. `gh`
    refuses without `--repo` or `--owner`, and then looks for a build-provenance
    attestation and reports "no attestations found with predicate type" - because the
    bundle we publish is the SBOM attestation, made after signing over the bytes a
    user downloads. Both are the tool being precise; the documentation was wrong.

    So this pins the two halves together: the predicate type the README tells people
    to ask for must be the one `attest-release.yml` actually produces. Change the
    workflow to attest something else and the README's command starts failing for
    every user, silently, because nothing here runs `gh`.
    """
    workflow = os.path.join(ROOT, ".github", "workflows", "attest-release.yml")
    with open(workflow, encoding="utf-8") as handle:
        yaml_body = handle.read()
    # An SBOM attestation is what `sbom-path` makes, and its predicate type is SPDX.
    makes_sbom = "sbom-path:" in yaml_body
    check("the attestation workflow still makes an SBOM attestation", makes_sbom,
          "(if this changed, the predicate type in both READMEs has to change with it)")

    for readme in ("README.md", "README.pl.md"):
        with open(os.path.join(ROOT, readme), encoding="utf-8") as handle:
            text = handle.read()
        line = [ln for ln in text.splitlines() if "gh attestation verify" in ln
                and "--bundle" in ln]
        check(f"{readme} documents the offline verify command", bool(line))
        command = line[0] if line else ""
        check(f"{readme}: it names the repository", "--repo " in command, f"({command[:120]})")
        check(f"{readme}: it names the predicate type",
              "--predicate-type " in command, f"({command[:120]})")
        if makes_sbom:
            check(f"{readme}: the predicate type is the SPDX one the workflow makes",
                  "https://spdx.dev/Document/v2.3" in command, f"({command[:160]})")

        # 🔴 EVERY documented command, not just the one with `--bundle`. Until
        # 2026-08-21 this test read the offline line only, and the ONLINE line above
        # it - `gh attestation verify <zip> -R <repo>` - shipped in 0.5.0 answering
        # HTTP 404 for every user, because `gh` defaults to looking for build
        # provenance and a hand-signed archive deliberately has none. A guard that
        # checks one of two commands is a guard that reports the wrong half is fine.
        online = [ln for ln in text.splitlines() if "gh attestation verify" in ln
                  and "--bundle" not in ln]
        check(f"{readme} documents the online verify command", bool(online))
        for command in online:
            check(f"{readme}: the online command names a predicate type",
                  "--predicate-type " in command,
                  f"(without it gh asks for SLSA provenance and gets 404: {command[:120]})")
            if makes_sbom:
                check(f"{readme}: the online command asks for the SPDX predicate",
                      "https://spdx.dev/Document/v2.3" in command, f"({command[:160]})")


def test_the_published_release_is_checked_by_a_workflow_not_by_a_person():
    """Something has to run the README's commands against what people download.

    🔴 Every other check in the release path looks at an artefact, a draft or a
    digest handed between workflows. None of them touches the published release
    page, which is the only thing a user ever sees - and that gap is exactly how a
    verify command shipped broken twice: once for `v0.5.0-rc.2` (missing `--repo`
    and `--predicate-type`) and once for `v0.5.0`, whose online command answered
    HTTP 404 because `gh` looks for build provenance a hand-signed archive does not
    have. Both were found by a person running the command by hand, afterwards.

    So this pins the workflow to the documentation: the job must run the SAME two
    commands the README hands users. If someone rewrites the README's command, this
    keeps passing only while the workflow moves with it.
    """
    path = os.path.join(ROOT, ".github", "workflows", "verify-release.yml")
    check("a workflow verifies the published release", os.path.exists(path),
          "(expected .github/workflows/verify-release.yml)")
    with open(path, encoding="utf-8") as handle:
        body = handle.read()

    check("it runs when a release is published", "types: [published]" in body,
          "(a draft is not what users download)")
    check("it downloads the published assets", "gh release download" in body)
    check("it compares the checksums users are told to compare",
          "sha256sum -c SHA256SUMS.txt" in body)

    for flag in ("--bundle", "--repo", "-R ", "--predicate-type",
                 "https://spdx.dev/Document/v2.3"):
        check(f"the workflow runs the documented command with {flag.strip()}",
              flag in body, "(it must run the README's command, not an equivalent)")

    # The half a checksum cannot speak for.
    check("it checks the Authenticode signature",
          "Get-AuthenticodeSignature" in body)
    check("it refuses a signature with no timestamp",
          "TimeStamperCertificate" in body,
          "(without one the signature dies when the certificate expires)")
    check("it compares the signing certificate against the pin",
          "CODESIGN_SHA256" in body,
          "(read out of beantester/legal.py, so the constant has one home)")
    check("it writes nothing", "contents: write" not in body,
          "(a verifier that can publish is not only a verifier)")


def test_release_refuses_a_tag_whose_commit_ci_never_passed():
    """`release.yml` builds and publishes; it does not test. So it has to ASK.

    Step 1 of the release recipe - "tag only a commit CI was green on" - was prose
    and nothing enforced it, which the notes said out loud. A red commit plus a tag
    published unproven code and the workflow would not have noticed.

    Keyed on the CI workflow by name on purpose: this repository carries a check that
    fails for a licensing reason of its own, so "every check is green" would block
    every release over something unrelated to the code.
    """
    with open(os.path.join(ROOT, ".github", "workflows", "release.yml"),
              encoding="utf-8") as handle:
        body = handle.read()
    check("the release workflow asks whether CI passed",
          "actions/runs?head_sha=" in body,
          "(it cannot re-run the tests, so it must read their result)")
    check("it looks at the CI workflow by name", 'select(.name == "CI")' in body)
    check("it has the permission that needs", "actions: read" in body)
    check("the gate runs before anything is built",
          body.index("actions/runs?head_sha=") < body.index("pyinstaller")
          if "pyinstaller" in body.lower() else True,
          "(failing after a build wastes the build and reads as a build failure)")


def test_the_signing_certificate_expiry_is_a_condition_not_a_note():
    """A date the script prints and draws no conclusion from is decoration.

    The card's certificate expires on a known day. Before 2026-08-21 the first
    release after it would have failed inside the signing step, with the card in the
    reader - the worst moment to learn about a certificate. The warning also has to
    mention the pin, because renewal issues a DIFFERENT certificate and
    `legal.CODESIGN_SHA256` has to move with it.
    """
    import datetime
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sign_release", os.path.join(ROOT, "tools", "sign_release.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    now = datetime.datetime(2026, 8, 21, tzinfo=datetime.timezone.utc)

    far = " ".join(module.expiry_notice("2027-08-19T15:26:42+02:00", now))
    check("a certificate with a year left does not shout", "WARNING" not in far, f"({far})")

    soon = " ".join(module.expiry_notice("2026-10-01T10:00:00+02:00", now))
    check("a certificate inside the warning window shouts", "WARNING" in soon, f"({soon})")
    check("...and says the pin moves with a renewal", "CODESIGN_SHA256" in soon, f"({soon})")

    for junk in (None, "not-a-date"):
        note = " ".join(module.expiry_notice(junk, now))
        check(f"an unreadable expiry ({junk!r}) is reported, not ignored",
              "check the card" in note, f"({note})")

    try:
        module.expiry_notice("2026-01-01T10:00:00+02:00", now)
        check("an EXPIRED certificate refuses to sign", False,
              "(it returned a note instead of refusing)")
    except SystemExit as exc:
        check("the refusal explains the renewal", "CODESIGN_SHA256" in str(exc),
              f"({str(exc)[:160]})")


def _ci_text():
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
        return f.read()


def _ci_job_ids(text):
    """Top-level job ids, which are the 2-space keys AFTER the `jobs:` line.

    Parsed rather than hard-coded, and started at `jobs:` on purpose: `on:` has
    2-space keys of its own (`push`, `schedule`), and counting those would make
    the guard below demand that the notice watch a trigger.
    """
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "jobs:")
    return [re.match(r"^  ([a-z][a-z0-9-]*):\s*$", ln).group(1)
            for ln in lines[start + 1:] if re.match(r"^  [a-z][a-z0-9-]*:\s*$", ln)]


def test_the_cron_notice_watches_every_job_in_the_workflow():
    """A job left out of `needs` can fail every Monday for a year in silence.

    The weekly run announces itself through `cron-issue`, and that job can only
    see what it depends on. Adding a job to this workflow and forgetting this
    list would leave the new job unwatched by exactly the mechanism that exists
    because a cron is easy to miss - the same failure one level up.
    """
    text = _ci_text()
    jobs = _ci_job_ids(text)
    check("ci.yml still defines the weekly notice", "cron-issue" in jobs, f"({jobs})")

    needs = re.search(r"^  cron-issue:.*?^    needs: \[(.*?)\]", text, re.S | re.M)
    check("the notice declares what it watches", needs is not None)
    if not needs:
        return
    watched = {name.strip() for name in needs.group(1).split(",")}
    unwatched = sorted(set(jobs) - watched - {"cron-issue"})
    check("the notice depends on every other job in the workflow", not unwatched,
          f"({unwatched} - add them to `needs`, or they fail unannounced)")
    ghosts = sorted(watched - set(jobs))
    check("and on no job that no longer exists", not ghosts, f"({ghosts})")

    # 🔴 The invariant that keeps this from becoming an issue factory. The notice
    # answers to the schedule and to a hand-fired run - the second so the path can
    # be exercised at all - and to nothing else. On a pull request it would open
    # an issue per pull request.
    trigger = re.search(r"^  cron-issue:.*?^    if: >-\n((?:      .*\n)+)", text, re.S | re.M)
    check("the notice declares its triggers", trigger is not None)
    if not trigger:
        return
    events = trigger.group(1)
    check("the notice never fires on a pull request",
          "pull_request" not in events, f"({events.strip()})")
    check("and it can be fired by hand, or nothing could ever prove it works",
          "workflow_dispatch" in events, f"({events.strip()})")


def test_the_audit_job_answers_to_a_pull_request_that_moves_the_pins():
    """A tag can be cut days before the next cron, so the set must be checked when
    it CHANGES, not only when the calendar turns.

    Both halves are asserted: that the job runs on a pull request at all, and that
    the pull-request path FAILS rather than opening an issue. An issue is the right
    answer to "the world moved under a set nobody is touching"; it is the wrong
    answer to a change with an author and an open review.
    """
    text = _ci_text()
    audit = re.search(r"^  audit:.*?(?=^  [a-z][a-z0-9-]*:\s*$)", text, re.S | re.M)
    check("ci.yml still has an audit job", audit is not None)
    if not audit:
        return
    body = audit.group(0)
    # 🔴 The JOB-LEVEL trigger, not the job text. The first version of this check
    # looked for "pull_request" anywhere in the body and passed for a reason that
    # had nothing to do with the claim - the STEPS mention it too, in their own
    # conditions. Deleting the trigger left the guard green, and the mutation
    # registry is what said so (2026-08-21, SURVIVED).
    trigger = re.search(r"^    if: >-\n((?:      .*\n)+)", body, re.M)
    check("the audit job declares its triggers", trigger is not None)
    check("and one of them is a pull request",
          trigger is not None and "pull_request" in trigger.group(1),
          f"({trigger.group(1).strip() if trigger else None})")
    check("a pull request that pins something vulnerable fails the run",
          "Refuse a pull request that pins something vulnerable" in body)
    check("and the pull-request path never opens an issue",
          re.search(r"Open an issue if anything was found\n\s+if: github\.event_name != 'pull_request'",
                    body) is not None)


def test_the_release_audits_its_pins_before_it_builds():
    """"CI was green on this commit" never included this question.

    The audit job runs on the schedule and on a pull request that moves a
    requirements file. A tag push is neither, so a release could ship a set that
    an issue had already flagged, for as long as nobody read the issue.

    Order matters and is asserted: auditing after the build would still publish
    the artefact and only then complain.
    """
    with open(os.path.join(ROOT, ".github", "workflows", "release.yml"),
              encoding="utf-8") as f:
        text = f.read()
    audit_at = text.find("Refuse to build a release whose pins carry a published advisory")
    build_at = text.find("pyinstaller --noconfirm")
    check("release.yml audits the pinned set", audit_at != -1)
    check("release.yml still builds", build_at != -1)
    if audit_at == -1 or build_at == -1:
        return
    check("and it audits BEFORE it builds", audit_at < build_at,
          f"(audit at {audit_at}, build at {build_at})")
    check("audited by path, not from the requirement files (7 of 9 packages)",
          "--path audit-env" in text)
    check("the auditor lives in its own environment, so the release set stays "
          "exactly the hash-pinned bytes",
          "audit-tool/Scripts/pip-audit" in text)
