"""The licence gate: what a new dependency may be licensed under, and what
happens when nobody can tell.

The official dependency-review action covers vulnerabilities and says so about
licences it cannot resolve: it informs, and does not fail. For a GPL-3.0 project
that ships a binary, "we could not determine the licence" is the one answer
nobody can act on, so it blocks here.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dependency_gate                                     # noqa: E402
from fakes import check                                    # noqa: E402


def _dep(name="thing", version="1.0", licence="MIT", change="added", scope="runtime"):
    return {"change_type": change, "name": name, "version": version,
            "license": licence, "scope": scope, "manifest": "requirements.txt",
            "ecosystem": "pip", "vulnerabilities": []}


def _write(tmp_path, payload, name="deps.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_a_permissive_licence_passes():
    for licence in ("MIT", "Apache-2.0", "BSD-3-Clause", "MPL-2.0", "LGPL-3.0-or-later"):
        blocked, passed = dependency_gate.split([_dep(licence=licence)])
        check(f"{licence} passes", not blocked and len(passed) == 1,
              f"(blocked={blocked})")


def test_an_unknown_licence_blocks():
    """The case the official action explicitly does not fail on."""
    for licence in (None, "", "   "):
        blocked, _passed = dependency_gate.split([_dep(licence=licence)])
        check(f"licence={licence!r} blocks", len(blocked) == 1 and blocked[0][0] == "unknown",
              f"({blocked})")


def test_gpl2_only_blocks_because_it_cannot_be_shipped_with_gpl3():
    """The finding that looks like a false alarm and is not: GPL-2.0-only is
    incompatible with this project's own licence."""
    blocked, _passed = dependency_gate.split([_dep(licence="GPL-2.0-only")])
    check("GPL-2.0-only blocks", len(blocked) == 1 and blocked[0][0] == "denied", f"({blocked})")


def test_an_exception_is_a_named_package_with_a_reason_beside_it():
    """The escape hatch, and the two things that keep it from becoming a habit.

    An entry is a NAME, so it can never widen `ALLOWED` for everything else: the
    same licence on any other package still blocks, which is what separates "a
    person looked at this one" from "we stopped checking". And a name with no
    reason beside it is how a list like this rots - the next reader cannot tell a
    decision from a way somebody once made a red build green.
    """
    for name in dependency_gate.EXCEPTIONS:
        reason = str(dependency_gate.EXCEPTIONS[name] or "").strip()
        check(f"the exception for {name} carries a reason", len(reason) > 20,
              f"({reason!r})")

    licence = "GPL-2.0-only AND GPL-2.0-or-later"      # what PyPI declares for it
    blocked, passed = dependency_gate.split(
        [_dep(name="pyinstaller", licence=licence)])
    check("the named build tool passes", not blocked and len(passed) == 1,
          f"(blocked={blocked})")

    blocked, _passed = dependency_gate.split([_dep(name="something-else",
                                                   licence=licence)])
    check("the same licence on any other package still blocks",
          len(blocked) == 1 and blocked[0][0] == "denied", f"({blocked})")


def test_a_compound_expression_is_judged_by_its_worst_half():
    ok, _ = dependency_gate.split([_dep(licence="MIT OR Apache-2.0")])
    check("both halves allowed passes", not ok, f"({ok})")
    bad, _ = dependency_gate.split([_dep(licence="MIT OR GPL-2.0-only")])
    check("one bad half blocks", len(bad) == 1, f"({bad})")


def test_only_added_dependencies_are_judged():
    """A removed dependency creates no obligation, and re-judging the whole tree
    would make every pull request answer for decisions taken years ago."""
    blocked, passed = dependency_gate.split([_dep(licence=None, change="removed")])
    check("a removed dependency is ignored", not blocked and not passed,
          f"(blocked={blocked}, passed={passed})")


def test_the_exit_code_is_the_verdict(tmp_path):
    clean = dependency_gate.main([_write(tmp_path, [_dep()])])
    check("a permissive addition exits 0", clean == 0, f"(exit {clean})")
    dirty = dependency_gate.main([_write(tmp_path, [_dep(), _dep(name="mystery", licence=None)])])
    check("an unknown licence exits 1", dirty == 1, f"(exit {dirty})")


def test_a_gate_that_cannot_read_its_input_has_not_passed_anything(tmp_path):
    """The API answers 403 for some repository shapes. That must look like a
    failure, not like an empty list of problems."""
    missing = dependency_gate.main([str(tmp_path / "nope.json")])
    check("a missing file exits 2", missing == 2, f"(exit {missing})")

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    check("unparsable input exits 2", dependency_gate.main([str(broken)]) == 2)

    # A 403 body is a JSON OBJECT with a message - not the list the gate expects.
    forbidden = _write(tmp_path, {"message": "Forbidden"}, "403.json")
    check("an error object exits 2 rather than passing",
          dependency_gate.main([forbidden]) == 2)


def test_the_report_names_what_it_blocked_and_why(tmp_path, capsys):
    dependency_gate.main([_write(tmp_path, [_dep(name="mystery", licence=None),
                                            _dep(name="fine", licence="MIT")])])
    out = capsys.readouterr().out
    for expected in ("mystery", "unknown", "fine", "MIT", "1 blocked, 1 allowed"):
        check(f"the report says {expected!r}", expected in out, f"({out[:200]})")


def test_github_actions_are_not_judged_by_this_gate():
    """Measured on the first real run: GitHub reports `license: null` for EVERY
    action, while every pip package came back with a real licence.

    An action is CI machinery that never reaches a user, so it creates none of
    the distribution obligation an unknown licence is dangerous for. Keeping them
    would block every pull request that touches a workflow, for ever - and a gate
    that always fires is one people learn to bypass. Actions are held to a
    stricter rule elsewhere: pinned to a commit SHA, and graded weekly.
    """
    review = [_dep(name="actions/checkout", licence=None),
              _dep(name="mypy", licence="MIT")]
    review[0]["ecosystem"] = "actions"
    blocked, passed = dependency_gate.split(review)
    check("an action with no licence does not block", not blocked, f"({blocked})")
    check("and it is not counted as allowed either", len(passed) == 1, f"({passed})")

    # ...while a pip package with no licence still blocks, which is the point.
    unknown = [_dep(name="mystery", licence=None)]
    check("a package with no licence still blocks",
          len(dependency_gate.split(unknown)[0]) == 1)
