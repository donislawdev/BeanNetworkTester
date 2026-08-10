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
import os
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

# Quoting the conversation the work came out of. The rule is simple and the reason
# is not obvious until it is said out loud: a commit or a pull request may quote
# the PROGRAM - its interface text, its output, its code - and may not quote a
# PERSON. A maintainer describing a fault in a chat has not published anything;
# pasting their sentence into a pull request does it for them, in public, for
# good. It happened here (pull request #95, two sentences in the reporter's own
# words) and the language rule alone would not have stopped an English one.
#
# These are the TELLS, not a detector. A translated report with no attributive
# phrase reads like ordinary prose and no pattern will find it - which is why the
# rule sits in the convention as well, for the half a machine cannot do.
QUOTED_PERSON = (
    r"(?i)\bthe (owner|maintainer|reporter|user) (said|asked|wrote|reported|put it"
    r"|noticed|complained|pointed out)\b",
    r"(?i)\byou (asked me|said|reported|told me|complained|pointed out)\b",
    r"(?i)\bas (you|he|she|they) (said|put it|wrote|described it)\b",
    r"(?i)\b(his|her|their) (exact )?words\b",
    r"(?i)\b(quoting|quote from) (the )?(chat|conversation|discussion|report)\b",
)

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
#
# Case-insensitive because git trailers are, and because GitHub proves it: a
# squash merge rewrites "Co-Authored-By" as "Co-authored-by", so the first version
# of this line passed on every branch and then flagged the merge commit it had
# just approved. Only running it over master found that.
ALLOWED_LINE = re.compile(r"^co-authored-by: .+ <[^>]+>$", re.I)

# -- this machine's own strings, kept OUT of this file ------------------------ #
#
# The convention forbids addresses as well as paths and tokens, and this script
# did not check for them. MEASURED before adding it: a canary fed the scanner a
# path, an e-mail, a quoted person and a token - all four caught - and a LAN
# address, which sailed through. A guard the convention names and the code does
# not implement is worse than one nobody wrote down, because somebody relies on
# it.
#
# 🔴 The obvious fix - a pattern for private-range addresses - was measured and
# REJECTED. Those addresses are legitimate documentation: 36 tracked files carry
# one, including the CIDR examples in both READMEs, the help text, the error
# messages and this project's own test probes. A guard that fires on correct
# content is switched off within a week, and takes the true hits with it.
#
# So the split this needs is the one a leak-detector always needs: the ENGINE is
# public and knows only the shape of the check, while the LIST OF LITERALS lives
# outside version control and is read at run time. A literal here would put the
# very strings this script exists to keep out of the public tree INTO it.
PRIVATE_STRINGS = os.path.join("internal_tools", "private-strings.txt")


def private_strings(path):
    """Literal strings that must never reach public text, from outside git.

    Returns ``(strings, note)``. The note is printed whether or not the file is
    there: a missing list means this half of the check did not run, and a check
    that goes quiet when its input is absent looks exactly like a check that
    passed - which on a fresh clone would be every time.
    """
    if not os.path.exists(path):
        return (), ("no private-strings list at %s - the literal check did NOT "
                    "run (see the comment in this file)" % path)
    values = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                values.append(line.lower())
    return tuple(values), "private-strings list: %d entries from %s" % (
        len(values), path)


def offences(text, where, literals=()):
    """Every rule broken by one block of text, as readable lines."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        if ALLOWED_LINE.match(line.strip()):
            continue
        if DASHES.search(line):
            found.append(f"{where} line {number}: em or en dash - use '-'")
        if POLISH.search(line):
            found.append(f"{where} line {number}: not English")
        # Code spans are stripped for this check only. Naming a pattern is not
        # using it: a message explaining this very rule has to be able to write
        # `the owner said` down, and it was the first thing to trip the guard.
        # Deliberately NOT done for the language check - a quoted line of Polish
        # program output is still Polish in a public description, and putting it
        # in backticks is how that would be smuggled past.
        prose = re.sub(r"`[^`]*`", "", line)
        for pattern in QUOTED_PERSON:
            if re.search(pattern, prose):
                found.append(f"{where} line {number}: quotes a person, not the "
                             f"program - say what was found, not who said it")
                break
        for pattern, what in PRIVATE:
            if pattern.search(line):
                found.append(f"{where} line {number}: {what}")
        # The report names the LINE and never the value. A leak detector that
        # prints what it matched becomes the leak it was meant to prevent - and
        # its output goes into CI logs, which are as public as the commit.
        low = line.lower()
        if any(value in low for value in literals):
            found.append(f"{where} line {number}: a string from the private list "
                         f"(this machine's own; the value is deliberately not "
                         f"printed)")
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
    parser.add_argument("--private-strings", metavar="PATH", default=PRIVATE_STRINGS,
                        help="literals that must never reach public text "
                             "(outside git; default: %(default)s)")
    args = parser.parse_args()

    blocks = []
    if args.commits:
        blocks.extend(commit_messages(args.commits))
    if args.text_file:
        with open(args.text_file, encoding="utf-8", errors="replace") as handle:
            blocks.append((handle.read(), "description"))
    # Two different empties, and conflating them made this guard cry wolf. Being
    # ASKED for nothing is a usage error; being asked about a range that HOLDS
    # nothing is a clean result - a branch with no commits of its own carries no
    # public text, which is exactly what we wanted to hear. `preflight.py` ran
    # this on a fresh branch and reported FAIL, and a guard that fails for no
    # reason teaches people to skip it.
    if not blocks:
        if not (args.commits or args.text_file):
            parser.error("nothing to check: pass --commits or --text-file")
        print(f"public text: 0 block(s) in {args.commits or args.text_file!r} "
              f"- nothing to check, which is not a failure")
        return 0

    literals, note = private_strings(args.private_strings)
    print(note)

    found = []
    for text, where in blocks:
        found.extend(offences(text, where, literals))

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
