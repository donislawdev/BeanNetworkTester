"""The Semgrep gate: which severities stop a pull request, and which do not.

The gate exists because ``semgrep --severity ERROR --error`` does not do what it
reads like - the flag knows INFO/WARNING/ERROR only, while registry rules also
carry the newer LOW/MEDIUM/HIGH/CRITICAL scale, so a HIGH rule is filtered OUT by
a filter asked to keep the worst findings. That was measured with a probe rule
before this file was written; what is guarded here is the decision that replaced
it, on reports shaped exactly like semgrep's own.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import semgrep_gate                                        # noqa: E402
from fakes import check                                    # noqa: E402


def _finding(severity, path="beantester/x.py", line=1, check_id="rule.id"):
    return {"check_id": check_id, "path": path, "start": {"line": line},
            "extra": {"severity": severity, "message": "something happened"}}


def _report(findings=(), errors=()):
    return {"results": list(findings), "errors": list(errors)}


def _write(tmp_path, report):
    path = tmp_path / "semgrep.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return str(path)


def test_the_new_severity_names_block_as_well_as_the_old_one():
    """The whole reason this file exists: HIGH and CRITICAL are not ERROR, and a
    gate that only knows ERROR passes them through."""
    for severity in ("ERROR", "HIGH", "CRITICAL"):
        blocking, passing, _ = semgrep_gate.split(_report([_finding(severity)]))
        check(f"{severity} blocks", len(blocking) == 1 and not passing,
              f"({len(blocking)} blocking, {len(passing)} passing)")
    # ...and the ones that must not, including the value that actually appeared in
    # this repository's own report.
    for severity in ("MEDIUM", "WARNING", "LOW", "INFO"):
        blocking, passing, _ = semgrep_gate.split(_report([_finding(severity)]))
        check(f"{severity} does not block", not blocking and len(passing) == 1,
              f"({len(blocking)} blocking, {len(passing)} passing)")


def test_severity_is_read_case_insensitively():
    """Nothing promises the case of that field, and a gate that misses "high"
    because it expected "HIGH" fails open - the direction that never gets noticed."""
    blocking, passing, _ = semgrep_gate.split(_report([_finding("high")]))
    check("lower-case high still blocks", len(blocking) == 1 and not passing)


def test_a_scan_error_is_a_failed_gate_not_a_clean_one():
    """A rule that could not run is not a rule that found nothing."""
    report = _report(errors=[{"level": "error", "type": "SemgrepError",
                              "message": "rule validation failed"}])
    blocking, passing, errors = semgrep_gate.split(report)
    check("the scan error is collected", len(errors) == 1 and not blocking and not passing)


def test_a_warning_level_scan_note_is_not_an_error(tmp_path):
    report = _report([_finding("WARNING")],
                     errors=[{"level": "warn", "type": "Note", "message": "skipped a file"}])
    code = semgrep_gate.main([_write(tmp_path, report)])
    check("a warning finding and a warn-level note pass", code == 0, f"(exit {code})")


def test_the_exit_code_is_the_verdict(tmp_path):
    clean = semgrep_gate.main([_write(tmp_path, _report())])
    check("an empty report passes", clean == 0, f"(exit {clean})")

    mixed = _report([_finding("WARNING"), _finding("HIGH", line=7)])
    code = semgrep_gate.main([_write(tmp_path, mixed)])
    check("one HIGH among warnings fails", code == 1, f"(exit {code})")


def test_a_missing_or_broken_report_fails_the_gate(tmp_path):
    """The failure mode that would otherwise be silent: the scan step wrote
    nothing, and a gate reading nothing decides everything is fine."""
    missing = semgrep_gate.main([str(tmp_path / "not-written.json")])
    check("a missing report is not a pass", missing == 2, f"(exit {missing})")

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    code = semgrep_gate.main([str(broken)])
    check("an unparsable report is not a pass", code == 2, f"(exit {code})")


def test_the_printed_report_names_every_finding(tmp_path):
    """CI shows the log and nothing else, so the log has to carry the verdict."""
    report = _report([_finding("HIGH", path="a.py", line=3, check_id="rules.bad"),
                      _finding("WARNING", path="b.py", line=9, check_id="rules.meh")],
                     errors=[{"level": "error", "type": "SemgrepError", "message": "boom"}])
    text = "\n".join(semgrep_gate.report_lines(*semgrep_gate.split(report)))
    for expected in ("a.py:3", "rules.bad", "b.py:9", "rules.meh", "SemgrepError",
                     "1 blocking, 1 other, 1 scan error"):
        check(f"the report says {expected!r}", expected in text, f"({text[:200]})")
