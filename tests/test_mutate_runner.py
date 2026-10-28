"""The mutation runner's command line: a mistaken command is a usage error, never a run.

``tools/mutate.py`` is what CI runs to prove the registry's tests can fail. Its own
mistakes have to be loud for the same reason: a filter that matches nothing used
to crash on an empty run (``max()`` of nothing), ``--help`` was taken for a label
filter and crashed the same way, and a second word was dropped without a word.
None of these cases runs a single mutation, so every test here is instant.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import mutate                                               # noqa: E402
from fakes import check                                     # noqa: E402


def _main(capsys, *args):
    code = mutate.main(["mutate.py", *args])
    out, err = capsys.readouterr()
    return code, out, err


def test_a_label_filter_that_matches_nothing_is_a_usage_error(capsys, monkeypatch):
    ran = []
    monkeypatch.setattr(mutate, "apply_one", lambda entry: ran.append(entry) or ("caught", ""))
    code, _out, err = _main(capsys, "no such label anywhere")
    check("exit code 2, not a result", code == 2, f"({code})")
    check("it says which filter matched nothing", "no such label anywhere" in err, f"({err})")
    check("no mutation ran", not ran, f"({ran})")
    # --changed must not turn the same typo into "nothing guarded was touched"
    code, out, _err = _main(capsys, "no such label anywhere", "--changed", "origin/master")
    check("with --changed as well", code == 2 and "nothing guarded" not in out,
          f"({code}, {out})")


def test_help_prints_the_usage_instead_of_running(capsys, monkeypatch):
    ran = []
    monkeypatch.setattr(mutate, "apply_one", lambda entry: ran.append(entry) or ("caught", ""))
    for flag in ("--help", "-h"):
        code, out, _err = _main(capsys, flag)
        check(f"{flag} exits 0", code == 0, f"({code})")
        check(f"{flag} prints the usage", "python tools/mutate.py --changed" in out, f"({out})")
    check("and no mutation ran", not ran, f"({len(ran)} ran)")


def test_more_than_one_filter_or_an_unknown_option_is_refused(capsys, monkeypatch):
    ran = []
    monkeypatch.setattr(mutate, "apply_one", lambda entry: ran.append(entry) or ("caught", ""))
    for args in (("help", "button"), ("--chnaged", "origin/master"), ("-k", "gui")):
        code, _out, err = _main(capsys, *args)
        check(f"{args} is a usage error", code == 2 and "at most one label" in err,
              f"({code}, {err})")
    check("nothing ran", not ran, f"({ran})")


def test_an_entry_that_does_not_compile_fails_every_kind_of_run(capsys, monkeypatch):
    """A mutation that does not compile reddens every test, so it proves nothing. A
    --changed run passed with one (2026-10-27): only the canary's BROKEN was counted."""
    entry = mutate.MUTATIONS[0]
    monkeypatch.setattr(mutate, "apply_one", lambda e: ("BROKEN", "does not compile"))
    code, out, _err = _main(capsys, entry["label"])
    check("a filtered run fails and names the entry",
          code == 1 and "BROKEN ENTRIES" in out and entry["label"] in out, f"({code}, {out})")
    monkeypatch.setattr(mutate, "changed_files", lambda ref: {entry["file"]})
    code, out, _err = _main(capsys, "--changed", "origin/master")
    check("so does a --changed run", code == 1 and "BROKEN ENTRIES" in out, f"({code})")
    # The full run: the canary's BROKEN is the one it must have, and no other.
    monkeypatch.setattr(mutate, "apply_one", lambda e: (
        "BROKEN" if e is mutate.CANARY or e is entry else "caught", ""))
    code, out, _err = _main(capsys)
    check("a full run with one more BROKEN than the canary fails",
          code == 1 and "BROKEN ENTRIES" in out and "CANARY DID NOT FIRE" not in out,
          f"({code})")
    monkeypatch.setattr(mutate, "apply_one", lambda e: (
        "BROKEN" if e is mutate.CANARY else "caught", ""))
    code, out, _err = _main(capsys)
    check("and only the canary BROKEN passes", code == 0 and "BROKEN ENTRIES" not in out,
          f"({code})")


def test_a_filter_that_matches_still_runs_only_its_entries(capsys, monkeypatch):
    """The canary for this file: the refusals above must not refuse a good filter."""
    ran = []
    monkeypatch.setattr(mutate, "apply_one", lambda entry: ran.append(entry["label"]) or ("caught", "t"))
    label = mutate.MUTATIONS[0]["label"]
    code, out, _err = _main(capsys, label)
    check("exit 0", code == 0, f"({code}, {out})")
    check("the matching entries ran, the canary did not",
          ran and all(label in r for r in ran) and mutate.CANARY["label"] not in ran, f"({ran})")
