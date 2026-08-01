#!/usr/bin/env python3
"""Print one version's section of CHANGELOG.md, ready to publish or paste.

`release.yml` feeds this to `gh release create --notes-file`, so the GitHub
release page shows the curated notes instead of a list of merged pull request
titles. The same output is what you paste into a blog post or a forum thread.

The point is that there is no second copy to drift: CHANGELOG.md is the source,
and the release page, the blog post and the file all say the same words. That
matters more here than it looks - nobody proof-reads a release page against a
changelog, so a second copy would be wrong within one release and stay wrong.

Usage:
    python tools/release_notes.py            # the version in VERSION.txt
    python tools/release_notes.py 0.3.0      # any released version

Stdlib only, on purpose: the release job installs the runtime requirements and
PyInstaller, not the dev extras, so anything else would fail at publish time -
the one moment nobody wants a surprise.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
VERSION_FILE = os.path.join(ROOT, "VERSION.txt")


def section(version, text):
    """The body of `## [version] ...`, without the heading. None when absent."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith("## [")]
    for n, start in enumerate(starts):
        if re.match(r"^## \[%s\]" % re.escape(version), lines[start]):
            end = starts[n + 1] if n + 1 < len(starts) else len(lines)
            body = lines[start + 1:end]
            while body and not body[0].strip():
                body.pop(0)
            while body and not body[-1].strip():
                body.pop()
            return "\n".join(body)
    return None


def main(argv):
    if len(argv) > 1:
        version = argv[1]
    else:
        with open(VERSION_FILE, encoding="utf-8") as fh:
            version = fh.read().strip()

    with open(CHANGELOG, encoding="utf-8") as fh:
        found = section(version, fh.read())

    if found is None:
        # Loud, not empty. An empty release body would publish happily and be
        # noticed by users rather than by us.
        sys.stderr.write(
            "release_notes: no '## [%s]' section in CHANGELOG.md\n" % version)
        return 1

    # Write UTF-8 bytes rather than str. `release.yml` runs on windows-latest,
    # where stdout still defaults to the ANSI code page on this Python, so a
    # single non-ASCII character in the notes crashes the publish step with a
    # UnicodeEncodeError. Found the real way: [0.3.0] contains U+25CF, and
    # printing it raised while 0.4.0 (all ASCII) looked fine.
    out = getattr(sys.stdout, "buffer", None)
    if out is None:                       # a stream without one (a test harness)
        sys.stdout.write(found + "\n")
    else:
        out.write((found + "\n").encode("utf-8"))
        out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
