"""The leak guard has to be shown ABLE TO FAIL, or it is just a green tick.

``tools/check_public_text.py`` stands between this project and the one surface
it cannot take back: a pushed commit message. It runs in CI and it had reported
"clean" many times - which proves it RAN, not that it LOOKS.

MEASURED 2026-08-06, the first time anybody fed it something known-bad: it caught
a user-profile path, an e-mail address, a quoted person and a token shape, and it
let a LAN address straight through, while the convention it enforces names
addresses among the forbidden things. A scanner nobody has watched fail is
indistinguishable from a scanner that reads nothing.

So the canary lives here, permanently, rather than as a script somebody runs
once. Each case is a string this project would genuinely be sorry to publish.

The tests never write a real private value into this file - that is the same
mistake the scanner exists to prevent, and a leak detector containing what it
hunts for has been reported flagging its own source.

That is not theoretical here: the first version of this file spelled out two
example e-mail addresses, and ``test_repo_conventions.py`` rejected it on the
first run. Every address below is therefore ASSEMBLED at run time, the same way
``check_public_text.py`` builds the dash characters it hunts for. A test about
not writing forbidden strings down may not write them down.
"""
import os
import subprocess
import sys

from fakes import ROOT, check

SCANNER = os.path.join(ROOT, "tools", "check_public_text.py")

# Assembled, never spelled out - see the module docstring.
AT = chr(64)


def _scan(text, tmp_path, private=None):
    """Run the scanner over one block of text. Returns (exit code, output)."""
    probe = tmp_path / "block.md"
    probe.write_text(text, encoding="utf-8")
    argv = [sys.executable, SCANNER, "--text-file", str(probe)]
    if private is not None:
        argv += ["--private-strings", str(private)]
    out = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    return out.returncode, (out.stdout or "") + (out.stderr or "")


# The four shapes the scanner already knew about, plus the two it did not. Every
# one is written as a SHAPE here, never as a real value from this machine.
CAUGHT_CASES = {
    "a user-profile path": "Fixed it on " + "C:" + chr(92) + "Users" + chr(92)
                           + "someone" + chr(92) + "Desktop and it works.",
    "an email address": "Reported by nobody" + AT + "example.invalid privately.",
    "a token shape": "Set the key to ghp_" + "A" * 20,
    "a quoted person": "The owner said this does not work, please fix it.",
    "an em dash": "Two things " + chr(0x2014) + " one message.",
    # Diacritics are the tell the scanner actually uses - see the case below for
    # what that does NOT cover.
    "a Polish sentence": "Poprawione zgodnie ze zg" + chr(0x142) + "oszeniem.",
}


def test_the_scanner_catches_every_shape_it_claims_to(tmp_path):
    """One case per rule the module docstring advertises."""
    for label, text in CAUGHT_CASES.items():
        code, output = _scan(text, tmp_path)
        check(f"caught: {label}", code != 0, f"({output.strip()[:90]!r})")


def test_the_scanner_passes_text_that_is_actually_fine(tmp_path):
    """The other half. A guard that fails everything is as useless as one that
    fails nothing, and it is the version that gets switched off."""
    code, output = _scan(
        "Declare full prototypes for the window manager calls.\n"
        "Measured 5098 KB/s against a 5000 KB/s limit.\n"
        "Co-authored-by: Someone <someone" + AT + "example.invalid>\n"
        "Signed-off-by: Someone <someone" + AT + "example.invalid>\n", tmp_path)
    check("clean text passes", code == 0, f"({output.strip()[:120]!r})")


def test_a_bot_sign_off_does_not_stop_a_dependency_bump(tmp_path):
    """The trailer Dependabot writes, in the shape it writes it.

    Every commit it authors ends with a sign-off naming a GitHub address, so the
    address rule stopped a required check on a line neither we nor the bot can
    edit - measured on the merge commit of an earlier bump, which reported "an
    email address" for exactly that line and nothing else.

    The address is assembled rather than spelled out, like every other one in this
    file: the rule that a leak detector may not contain what it hunts for does not
    get an exception for the address that made us widen it.
    """
    trailer = ("Signed-off-by: dependabot[bot] <support" + AT + "github.com>")
    code, output = _scan(
        "chore(deps): bump the github-actions group with 2 updates\n\n"
        + trailer + "\n"
        "Co-authored-by: dependabot[bot] <49699333+dependabot[bot]"
        + AT + "users.noreply.github.com>\n", tmp_path)
    check("a bot sign-off passes", code == 0, f"({output.strip()[:120]!r})")


def test_the_same_address_in_prose_is_still_caught(tmp_path):
    """What the widening must NOT buy: an address anywhere but in a trailer.

    A rule relaxed by shape has to be shown to still refuse the shape next door,
    or "we allow trailers" quietly becomes "we allow addresses".
    """
    code, output = _scan(
        "Write to support" + AT + "github.com if the bump looks wrong.\n", tmp_path)
    check("the same address in a sentence is caught", code != 0,
          f"({output.strip()[:120]!r})")
    code, output = _scan(
        "Signed-off-by: someone" + AT + "example.invalid\n", tmp_path)
    check("a sign-off without the angle brackets is not a trailer", code != 0,
          f"({output.strip()[:120]!r})")


def test_a_literal_from_the_private_list_is_caught_without_being_printed(tmp_path):
    """The half that was missing, and the constraint that comes with it.

    The report must name the line and NEVER the value: its output goes into CI
    logs, which are exactly as public as the commit it is guarding.
    """
    secret = "10.77.77.77"                      # invented here, not a real one
    listing = tmp_path / "private.txt"
    listing.write_text("# comment ignored\n\n%s\n" % secret, encoding="utf-8")

    code, output = _scan("Measured against the peer at %s over the LAN.\n" % secret,
                         tmp_path, private=listing)
    check("a private literal is caught", code != 0, f"({output.strip()[:90]!r})")
    check("and the value itself is NOT printed back", secret not in output,
          "the report repeated the very string it exists to keep out of public text")


def test_a_missing_private_list_is_announced_rather_than_silent(tmp_path):
    """On a fresh clone the list is absent - and a check that goes quiet when its
    input is missing looks exactly like a check that passed."""
    code, output = _scan("Nothing wrong here.\n", tmp_path,
                         private=tmp_path / "does-not-exist.txt")
    check("a clean block still passes", code == 0)
    check("but the missing list is said out loud",
          "did NOT run" in output, f"({output.strip()[:120]!r})")


def test_an_empty_commit_range_is_a_clean_result_not_a_usage_error(tmp_path):
    """Two different empties, and conflating them made the guard cry wolf.

    `preflight.py` runs `--commits origin/master..HEAD`. On a branch with no
    commits of its own that range is empty, and the scanner used to answer
    "nothing to check: pass --commits or --text-file" with exit 2 - a usage error
    naming a flag that HAD been passed. Preflight reported FAIL on a clean tree,
    and a guard that fails for no reason is a guard people learn to skip.

    Being asked for nothing is still a usage error. Being asked about a range
    that holds nothing is a clean answer.
    """
    empty = subprocess.run(
        [sys.executable, SCANNER, "--commits", "HEAD..HEAD"],
        capture_output=True, text=True, cwd=ROOT)
    check("an empty range exits clean", empty.returncode == 0,
          f"(code={empty.returncode}, {(empty.stdout + empty.stderr).strip()[:120]!r})")
    check("and says why it had nothing to do",
          "0 block(s)" in empty.stdout, f"({empty.stdout.strip()[:120]!r})")

    asked_for_nothing = subprocess.run(
        [sys.executable, SCANNER], capture_output=True, text=True, cwd=ROOT)
    check("but passing no source at all is still a usage error",
          asked_for_nothing.returncode == 2, f"(code={asked_for_nothing.returncode})")


def test_polish_written_without_diacritics_goes_straight_through(tmp_path):
    """A KNOWN gap, pinned so it stays known.

    The language check is a diacritics detector, which the scanner's own comment
    says. This test exists because the first version of the canary above quietly
    assumed otherwise: it wrote its Polish case without diacritics, passed
    nothing to the scanner that the scanner could see, and would have reported
    the rule as covered.

    Pinning the gap does two things a comment cannot. It makes the limit
    checkable rather than believed, and if someone later widens the detector this
    test goes red and asks them to say so on purpose.
    """
    code, _ = _scan("Poprawione zgodnie ze zgloszeniem uzytkownika.\n", tmp_path)
    check("Polish without diacritics is NOT caught (the guard is partial here)",
          code == 0,
          "the language check got wider - that may be good, but the docstring "
          "and this test have to be updated together")


def test_the_canary_itself_would_notice_a_gutted_scanner(tmp_path):
    """The check on the check: an empty rule set must fail this file, not pass it.

    Without this, every assertion above could be satisfied by a scanner that
    happens to exit non-zero for an unrelated reason.
    """
    code, output = _scan(CAUGHT_CASES["an email address"], tmp_path)
    check("the failure names the offending line", "line 1" in output,
          f"({output.strip()[:120]!r})")
    check("and says why it matters", "cannot be edited away" in output,
          f"({output.strip()[:120]!r})")
