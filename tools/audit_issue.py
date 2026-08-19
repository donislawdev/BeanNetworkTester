#!/usr/bin/env python3
"""Turn a pip-audit report into an issue - once per set of advisories.

    pip-audit --path <site-packages> -f json -o audit.json
    gh issue list --label security-scan --state open --json number,title > open.json
    python tools/audit_issue.py --audit audit.json --existing open.json \\
           --title-out title.txt --body-out body.md

Prints one word for the workflow to act on:

    none     nothing vulnerable in the audited set
    create   something is, and no open issue already says so
    skip     something is, and an open issue already says exactly that

Why an issue at all
-------------------
The weekly run deliberately does NOT open an issue when it goes red - that was
decided on 2026-08-17, and the reasoning holds: a red cron usually means
something drifted, and drift is read when somebody looks. A published advisory
against a version we ship is a different animal. It has a clock on it, it does
not resolve itself, and the person who needs to see it is not necessarily
looking at Actions that week.

Why the title carries the advisory ids
--------------------------------------
So the same finding cannot open fifty-two issues a year, and a NEW finding is
not swallowed by an old one. Matching on the package alone would do the second;
matching on nothing would do the first.
"""
import argparse
import json
import sys


def findings(report):
    """``(name, version, [advisory ...])`` for every vulnerable dependency."""
    out = []
    for dependency in report.get("dependencies") or []:
        vulns = dependency.get("vulns") or []
        if not vulns:
            continue
        out.append((dependency.get("name", "?"), dependency.get("version", "?"),
                    sorted(vulns, key=lambda v: str(v.get("id", "")))))
    return sorted(out)


def advisory_ids(rows):
    ids = {str(v.get("id", "?")) for _name, _version, vulns in rows for v in vulns}
    return sorted(ids)


def title_for(rows):
    ids = advisory_ids(rows)
    packages = sorted({name for name, _v, _x in rows})
    return "Vulnerable dependency: %s (%s)" % (", ".join(packages), ", ".join(ids))


def body_for(rows, run_url=""):
    lines = ["`pip-audit` found published advisories against versions this repository pins.",
             "",
             "| package | pinned version | advisory | fixed in |",
             "|---|---|---|---|"]
    for name, version, vulns in rows:
        for vuln in vulns:
            fixed = ", ".join(str(f) for f in (vuln.get("fix_versions") or [])) or "no fix yet"
            lines.append("| `%s` | %s | %s | %s |"
                         % (name, version, vuln.get("id", "?"), fixed))
    lines += ["",
              "The versions are pinned with hashes, so a fix means editing the pin and",
              "regenerating the hashes:",
              "",
              "```",
              "python tools/pin_hashes.py requirements.txt",
              "python tools/pin_hashes.py requirements-build.txt",
              "```",
              ""]
    if run_url:
        lines += ["Found by " + run_url, ""]
    lines.append("This issue was opened by the weekly dependency audit. Closing it without a")
    lines.append("pin change means deciding the advisory does not apply - say so in a comment,")
    lines.append("because the next run will open it again otherwise.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--audit", required=True, help="pip-audit JSON report")
    parser.add_argument("--existing", help="`gh issue list --json number,title` output")
    parser.add_argument("--title-out", help="write the issue title here")
    parser.add_argument("--body-out", help="write the issue body here")
    parser.add_argument("--run-url", default="", help="link back to the workflow run")
    args = parser.parse_args(argv)

    try:
        with open(args.audit, encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, ValueError) as exc:
        # Same rule as the semgrep gate: a report that cannot be read is not a
        # clean report. Fail loudly rather than reporting "none".
        print("audit_issue: cannot read %s: %s" % (args.audit, exc), file=sys.stderr)
        return 2

    rows = findings(report)
    if not rows:
        print("none")
        return 0

    title = title_for(rows)
    existing = []
    if args.existing:
        try:
            with open(args.existing, encoding="utf-8") as handle:
                existing = json.load(handle) or []
        except (OSError, ValueError) as exc:
            print("audit_issue: cannot read %s: %s" % (args.existing, exc), file=sys.stderr)
            return 2
    if any(str(issue.get("title", "")).strip() == title for issue in existing):
        print("skip")
        return 0

    if args.title_out:
        with open(args.title_out, "w", encoding="utf-8") as handle:
            handle.write(title)
    if args.body_out:
        with open(args.body_out, "w", encoding="utf-8") as handle:
            handle.write(body_for(rows, args.run_url))
    print("create")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
