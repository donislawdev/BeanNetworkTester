"""Check text that becomes public the moment it is pushed: commits and the PR body.

WHY THIS IS NOT A TEST IN ``tests/``
    The suite scans FILES. A commit message and a pull-request description are
    just as public, are read by just as many people, and live in the repository
    history forever - a message cannot be edited away, because the commit that
    carried it stays. Nothing in ``tests/`` can see either of them, so the two
    conventions that govern them (English only, plain hyphens) had no guard at
    all: they were held up by remembering, every time, which is the definition of
    a rule this project does not trust.

WHAT IT CHECKS
    The same three things the repository files are already held to:

    * plain hyphens only, never an em dash or an en dash (convention 33)
    * English only - Polish diacritics are the reliable tell (convention 43)
    * nothing private to a machine: user paths, addresses, credential shapes
      (convention 45)

WHAT IT DELIBERATELY DOES NOT CHECK
    Whether the message is any good. Nothing mechanical can tell a description
    that explains a change from one that restates its diff, and pretending
    otherwise would put a green tick on the half that matters least.

USAGE
    python tools/check_public_text.py --commits <base>..<head>
    python tools/check_public_text.py --text-file body.txt

    Exits 0 when clean, 1 with the offending lines named. Both forms are used by
    the CI workflow: the commit range for the branch, the text file for the pull
    request description.
"""
import argparse
import re
import subprocess
import sys

# An em dash or an en dash. Convention 33: this project uses the plain hyphen
# everywhere, and the reason it is worth enforcing is that the two are almost
# indistinguishable in a diff.
# Built from code points rather than written out: this file is repository text and
# is scanned by the very rule it enforces (convention 33), so spelling the two
# characters here would make the guard illegal under its own guard. That is
# exactly how it was first written, and the suite caught it.
DASHES = re.compile("[" + chr(0x2013) + chr(0x2014) + "]")

# Polish diacritics. Not a language detector and not meant to be: the commits and
# the pull requests of this project are written in English while the conversation
# behind them is in Polish, and the way that rule breaks is a sentence quoted
# straight from the conversation.
POLISH = re.compile("[" + "".join(chr(c) for c in (
    0x105, 0x107, 0x119, 0x142, 0x144, 0xF3, 0x15B, 0x17C, 0x17A,
    0x104, 0x106, 0x118, 0x141, 0x143, 0xD3, 0x15A, 0x17B, 0x179)) + "]")

PRIVATE = (
    (re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]"), "a Windows user-profile path"),
    (re.compile(r"/home/[a-z][\w.-]*/"), "a Linux home path"),
    (re.compile(r"/Users/[A-Za-z][\w.-]*/"), "a macOS home path"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}"), "an email address"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), "a GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}"), "an AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
)

# Co-author trailers carry an address by design. Matched by SHAPE rather than by
# spelling the address out: a literal here would be an address in the public tree,
# which is the thing this script exists to keep out of it.
ALLOWED_LINE = re.compile(r"^Co-Authored-By: .+ <[^>]+>$")


def offences(text, where):
    """Every rule broken by one block of text, as readable lines."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        if ALLOWED_LINE.match(line.strip()):
            continue
        if DASHES.search(line):
            found.append(f"{where} line {number}: em or en dash - use '-'")
        if POLISH.search(line):
            found.append(f"{where} line {number}: not English")
        for pattern, what in PRIVATE:
            if pattern.search(line):
                found.append(f"{where} line {number}: {what}")
    return found


def commit_messages(revision_range):
    """``(subject+body, label)`` for each commit in the range."""
    out = subprocess.run(
        ["git", "log", "--format=%H%x00%B%x1e", revision_range],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        print(f"cannot read {revision_range}: {out.stderr.strip()}", file=sys.stderr)
        raise SystemExit(1)
    for record in out.stdout.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, body = record.partition("\x00")
        yield body, f"commit {sha[:8]}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commits", metavar="RANGE",
                        help="a git revision range, e.g. origin/master..HEAD")
    parser.add_argument("--text-file", metavar="PATH",
                        help="a file holding one block of text (a PR description)")
    args = parser.parse_args()

    blocks = []
    if args.commits:
        blocks.extend(commit_messages(args.commits))
    if args.text_file:
        with open(args.text_file, encoding="utf-8", errors="replace") as handle:
            blocks.append((handle.read(), "description"))
    if not blocks:
        parser.error("nothing to check: pass --commits or --text-file")

    found = []
    for text, where in blocks:
        found.extend(offences(text, where))

    if found:
        print("This text becomes public and stays public. Fix before pushing:\n")
        for line in found:
            print(f"  {line}")
        print("\nA pushed commit message cannot be edited away: the commit that "
              "carried it stays in the history.")
        return 1
    print(f"public text: {len(blocks)} block(s) checked, clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
