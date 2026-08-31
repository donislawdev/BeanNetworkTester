#!/usr/bin/env python3
"""Decide a pull request from GitHub's dependency review data.

    gh api "repos/$REPO/dependency-graph/compare/$BASE...$HEAD" > deps.json
    python tools/dependency_gate.py deps.json

Why this exists next to `actions/dependency-review-action`
----------------------------------------------------------
The action already fails a pull request that ADDS a dependency with a known
vulnerability, and it does that well. It cannot do the other half. Its own
documentation is explicit: *"If we can't detect the license for a dependency we
will inform you, but the action won't fail."*

For a GPL-3.0 project that ships a binary, an unidentified licence is not an
informational note - it is the one case where nobody can say whether the thing
may be distributed at all. So the same data is read here and an unknown licence
blocks, exactly like a denied one. The REST field is documented as "string or
null", and `null` is what "not determined" looks like.

Scope
-----
Only dependencies that the pull request ADDS (`change_type == "added"`).
Removing something never creates an obligation, and re-checking what is already
in the tree would make every pull request answer for decisions taken years ago.
"""
import argparse
import json
import sys

# SPDX identifiers a GPL-3.0 project may distribute alongside its own code.
#
# GPL-2.0-only is deliberately ABSENT: it is famously incompatible with GPL-3.0,
# and a dependency under it would be exactly the kind of thing that looks fine in
# a list of "open source licences" and is not. Anything not named here is a
# decision for a person, which is what blocking means.
ALLOWED = frozenset({
    "0BSD", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0", "ISC",
    "MIT", "MIT-0", "MPL-2.0", "PSF-2.0", "Python-2.0", "Unlicense", "Zlib",
    "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later",
    "GPL-3.0-only", "GPL-3.0-or-later",
})

# Packages whose licence GitHub cannot resolve and which a person has already
# looked at. A name here is a decision with a reason, not a way to make a red
# build green - and it names the package, never a whole ecosystem.
EXCEPTIONS = {
    # PyPI declares "GPL-2.0-only AND GPL-2.0-or-later" for PyInstaller, and the
    # rule above is right to stop on the first half. What that expression
    # describes is a mixed source tree, not the terms this project distributes
    # under, and the difference is the whole reason the exception exists:
    #
    #   * PyInstaller is a BUILD tool. It is never imported by the program and
    #     never installed on a user's machine - it runs on a runner, in a job
    #     whose output is an executable;
    #   * the one piece of it that DOES reach a user is the bootloader, and that
    #     carries the PyInstaller bootloader exception, which explicitly permits
    #     building and distributing a program under the licence of that program's
    #     own choosing. THIRD-PARTY-NOTICES.md has said so, in those terms, since
    #     before this gate existed.
    #
    # So the blocking answer here would be right about the metadata and wrong
    # about the obligation. Recorded on 2026-08-31, when the 6.22.2 bump was the
    # first version to declare the expression this way.
    "pyinstaller": "build tool, and the shipped bootloader carries the "
                   "PyInstaller bootloader exception (THIRD-PARTY-NOTICES.md)",
}


# 🔴 GitHub Actions are dependencies in this data too, and GitHub reports
# `license: null` for every one of them - measured on the first real run, where
# this gate blocked `actions/checkout`, `actions/upload-artifact`,
# `github/codeql-action` and `ossf/scorecard-action` while every pip package came
# back with a real licence.
#
# They are skipped, and the reason is not convenience. An action is CI machinery
# that never reaches a user, so it creates no distribution obligation - the thing
# an unknown licence is dangerous for. Keeping them would mean blocking every
# pull request that touches a workflow, for ever, and a gate that always fires is
# a gate people learn to bypass. What actions ARE checked for lives elsewhere and
# is stricter: every one must be pinned to a commit SHA
# (tests/test_repo_conventions.py), and OpenSSF Scorecard grades them weekly.
SKIPPED_ECOSYSTEMS = frozenset({"actions"})


def added(review):
    return [d for d in review
            if str(d.get("change_type", "")) == "added"
            and str(d.get("ecosystem", "")).lower() not in SKIPPED_ECOSYSTEMS]


def verdict(dependency):
    """``("ok" | "unknown" | "denied", licence)`` for one added dependency."""
    licence = dependency.get("license")
    name = str(dependency.get("name", "?"))
    if name in EXCEPTIONS:
        return "ok", licence
    if licence is None or not str(licence).strip():
        return "unknown", licence
    # A compound expression ("MIT OR Apache-2.0") passes only if every part is
    # allowed. Being generous with an OR would mean accepting the worse half.
    parts = [p.strip("() ") for p in str(licence).replace(" AND ", " OR ").split(" OR ")]
    if all(part in ALLOWED for part in parts if part):
        return "ok", licence
    return "denied", licence


def split(review):
    blocked, passed = [], []
    for dependency in added(review):
        state, licence = verdict(dependency)
        row = (state, str(dependency.get("name", "?")),
               str(dependency.get("version", "?")), licence,
               str(dependency.get("scope", "?")))
        (passed if state == "ok" else blocked).append(row)
    return blocked, passed


def report_lines(blocked, passed):
    lines = []
    if blocked:
        lines.append("blocked - a licence that is denied or could not be determined:")
        for state, name, version, licence, scope in blocked:
            lines.append("  %-8s %s %s  licence=%s  scope=%s"
                         % (state, name, version, licence, scope))
        lines.append("")
        lines.append("An unknown licence blocks on purpose: this project is GPL-3.0 and ships a")
        lines.append("binary, so 'we could not tell' is the one answer nobody can act on. Record")
        lines.append("the decision in tools/dependency_gate.py (ALLOWED or EXCEPTIONS).")
    if passed:
        lines.append("allowed (%d): %s" % (
            len(passed), ", ".join("%s %s (%s)" % (n, v, lic) for _s, n, v, lic, _sc in passed)))
    lines.append("dependency gate: %d blocked, %d allowed" % (len(blocked), len(passed)))
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("review", help="JSON from the dependency review API")
    args = parser.parse_args(argv)
    try:
        with open(args.review, encoding="utf-8") as handle:
            review = json.load(handle)
    except (OSError, ValueError) as exc:
        # A gate that cannot read its input has not passed anything. The API
        # answers 403 for some repository shapes, and that must look like a
        # failure rather than an empty list of problems.
        print("dependency gate: cannot read %s: %s" % (args.review, exc), file=sys.stderr)
        return 2
    if not isinstance(review, list):
        print("dependency gate: expected a list of dependencies, got %s"
              % type(review).__name__, file=sys.stderr)
        return 2
    blocked, passed = split(review)
    for line in report_lines(blocked, passed):
        print(line)
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
