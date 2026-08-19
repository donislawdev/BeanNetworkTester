"""The weekly dependency audit: when it opens an issue, and when it stays quiet.

The decision this file guards is not "is there a vulnerability" - pip-audit
answers that - but what the repository does about it. Opening an issue every
Monday for a finding somebody already read would train everyone to close them
unread, and swallowing a NEW advisory into an old issue would lose it. So the
title carries the advisory ids, and matching is exact.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import audit_issue                                         # noqa: E402
from fakes import check                                    # noqa: E402


def _report(*rows):
    """A pip-audit JSON report: (name, version, [(id, [fixes]), ...])."""
    return {"dependencies": [
        {"name": name, "version": version,
         "vulns": [{"id": vid, "fix_versions": fixes} for vid, fixes in vulns]}
        for name, version, vulns in rows]}


def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_a_clean_audit_says_nothing(tmp_path, capsys):
    code = audit_issue.main(["--audit", _write(tmp_path, "a.json",
                                               _report(("psutil", "7.2.2", [])))])
    check("a clean report exits 0", code == 0, f"(exit {code})")
    check("and asks for nothing", capsys.readouterr().out.strip() == "none")


def test_a_finding_asks_for_an_issue(tmp_path, capsys):
    report = _report(("psutil", "7.2.2", [("GHSA-aaaa", ["7.2.3"])]))
    code = audit_issue.main(["--audit", _write(tmp_path, "a.json", report),
                             "--title-out", str(tmp_path / "t.txt"),
                             "--body-out", str(tmp_path / "b.md")])
    check("it exits 0", code == 0, f"(exit {code})")
    check("and asks for an issue", capsys.readouterr().out.strip() == "create")
    title = (tmp_path / "t.txt").read_text(encoding="utf-8")
    body = (tmp_path / "b.md").read_text(encoding="utf-8")
    check("the title names the package and the advisory",
          "psutil" in title and "GHSA-aaaa" in title, f"({title})")
    for expected in ("7.2.2", "GHSA-aaaa", "7.2.3", "pin_hashes.py"):
        check(f"the body carries {expected!r}", expected in body)


def test_a_finding_with_no_fix_says_so(tmp_path):
    report = _report(("pydivert", "3.1.3", [("PYSEC-1", [])]))
    audit_issue.main(["--audit", _write(tmp_path, "a.json", report),
                      "--body-out", str(tmp_path / "b.md")])
    body = (tmp_path / "b.md").read_text(encoding="utf-8")
    check("an advisory without a fix is not left blank", "no fix yet" in body, f"({body[:200]})")


def test_the_same_finding_does_not_open_a_second_issue(tmp_path, capsys):
    report = _report(("psutil", "7.2.2", [("GHSA-aaaa", ["7.2.3"])]))
    title = audit_issue.title_for(audit_issue.findings(report))
    existing = _write(tmp_path, "open.json", [{"number": 7, "title": title}])
    code = audit_issue.main(["--audit", _write(tmp_path, "a.json", report),
                             "--existing", existing])
    check("it exits 0", code == 0, f"(exit {code})")
    check("and skips, because the issue is already open",
          capsys.readouterr().out.strip() == "skip")


def test_a_new_advisory_is_not_swallowed_by_the_open_issue(tmp_path, capsys):
    """The failure that matters more than the duplicate: a second advisory
    arriving while the first issue is still open."""
    old = _report(("psutil", "7.2.2", [("GHSA-aaaa", ["7.2.3"])]))
    new = _report(("psutil", "7.2.2", [("GHSA-aaaa", ["7.2.3"]), ("GHSA-bbbb", [])]))
    existing = _write(tmp_path, "open.json",
                      [{"number": 7, "title": audit_issue.title_for(audit_issue.findings(old))}])
    code = audit_issue.main(["--audit", _write(tmp_path, "a.json", new),
                             "--existing", existing,
                             "--title-out", str(tmp_path / "t.txt"),
                             "--body-out", str(tmp_path / "b.md")])
    check("it exits 0", code == 0, f"(exit {code})")
    check("a new advisory opens its own issue",
          capsys.readouterr().out.strip() == "create")
    check("and the title carries both ids",
          "GHSA-bbbb" in (tmp_path / "t.txt").read_text(encoding="utf-8"))


def test_an_unreadable_report_is_not_a_clean_one(tmp_path, capsys):
    missing = audit_issue.main(["--audit", str(tmp_path / "nope.json")])
    check("a missing report fails loudly", missing == 2, f"(exit {missing})")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    code = audit_issue.main(["--audit", str(broken)])
    check("an unparsable report fails loudly", code == 2, f"(exit {code})")
    capsys.readouterr()
