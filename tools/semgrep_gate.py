#!/usr/bin/env python3
"""Decide a pull request from a Semgrep JSON report.

    semgrep scan --config p/default --json --output semgrep.json
    python tools/semgrep_gate.py semgrep.json

Why this exists rather than ``semgrep --severity ERROR --error``
---------------------------------------------------------------
Because that flag does not mean what it reads like. ``--severity`` accepts
exactly ``INFO``, ``WARNING`` and ``ERROR`` (semgrep 1.173.0, ``--help``), while
a rule may declare the newer scale - and rules in the registry do: two findings
in this repository's own report came back as ``MEDIUM``.

Measured 2026-08-19 with a probe rule carrying ``severity: HIGH``: unfiltered it
produced 19 findings, and with ``--severity ERROR`` it produced **zero**. So the
flag-based gate silently ignores exactly the severities it is asked to block.
Reading the report and deciding here is the only version that cannot lie.

What blocks
-----------
Any finding whose severity is ERROR, HIGH or CRITICAL. Everything else is
printed and passes, because a WARNING here is usually a rule seeing a shape it
cannot resolve (a dynamic import from a hardcoded table, a URL built from a
validated argument) and a gate that fires on those is a gate nobody reads.

A scan ERROR also blocks. A rule that failed to run is not a rule that found
nothing, and "the scan was green" must not mean "the scan did not happen".
"""
import argparse
import json
import sys

BLOCKING = ("ERROR", "HIGH", "CRITICAL")


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def split(report):
    """``(blocking, passing, scan_errors)`` out of a semgrep JSON report."""
    blocking, passing = [], []
    for result in report.get("results") or []:
        severity = str((result.get("extra") or {}).get("severity", "")).upper()
        (blocking if severity in BLOCKING else passing).append(result)
    errors = [e for e in report.get("errors") or []
              if str(e.get("level", "")).lower() == "error"]
    return blocking, passing, errors


def describe(result):
    extra = result.get("extra") or {}
    start = result.get("start") or {}
    message = " ".join(str(extra.get("message", "")).split())
    return "%s:%s  [%s] %s\n      %s" % (
        result.get("path", "?"), start.get("line", "?"),
        extra.get("severity", "?"), result.get("check_id", "?"), message[:300])


def report_lines(blocking, passing, errors):
    lines = []
    if errors:
        lines.append("scan errors (a rule that could not run is not a rule that passed):")
        lines += ["  %s: %s" % (e.get("type", "?"),
                                " ".join(str(e.get("message", "")).split())[:200])
                  for e in errors]
    if blocking:
        lines.append("blocking findings (%s):" % ", ".join(BLOCKING))
        lines += ["  " + describe(r) for r in blocking]
    if passing:
        lines.append("other findings (reported, not blocking):")
        lines += ["  " + describe(r) for r in passing]
    lines.append("semgrep: %d blocking, %d other, %d scan error(s)"
                 % (len(blocking), len(passing), len(errors)))
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", help="the JSON file semgrep --output wrote")
    args = parser.parse_args(argv)
    try:
        report = load(args.report)
    except (OSError, ValueError) as exc:
        # A missing or unparsable report is a failed gate, never a pass: it means
        # the scan step did not produce what this one was promised.
        print("semgrep gate: cannot read %s: %s" % (args.report, exc), file=sys.stderr)
        return 2
    blocking, passing, errors = split(report)
    for line in report_lines(blocking, passing, errors):
        print(line)
    return 1 if (blocking or errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
