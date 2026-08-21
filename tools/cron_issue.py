#!/usr/bin/env python3
"""Turn a red WEEKLY run into an issue - once per set of failing jobs.

    gh issue list --label ci-cron --state open --json number,title > open.json
    python tools/cron_issue.py --needs needs.json --existing open.json \\
           --title-out title.txt --body-out body.md --run-url "$RUN_URL"

Prints one word for the workflow to act on, exactly like ``audit_issue.py``:

    none     nothing in the run failed (the caller asked anyway)
    create   something failed, and no open issue already says so
    skip     something failed, and an open issue already says exactly that

Why this exists, and why it reverses a decision
-----------------------------------------------
On 2026-08-17 the owner decided a red cron would be read by hand
(``gh run list --workflow CI --branch master``) rather than announced. That was
reversed on 2026-08-21, by the owner, for one reason: **a cron is very easy to
miss.** Nothing arrives when it goes red, the run is not attached to any pull
request anybody is looking at, and a week later it is off the first page.

The exception carved out for advisories (``audit_issue.py``) had already made
the same argument for a narrower case. This generalises it, and the two stay
separate on purpose: different labels, different titles, different bodies. An
advisory against a shipped version and a runner that could not install a package
are not the same problem and must not deduplicate against each other.

Why the title carries the failing job names
-------------------------------------------
So one stuck job cannot open fifty-two issues a year, and a DIFFERENT failure
next week is not swallowed by the open issue about the old one. Matching on
nothing but the label would do the second; matching on the run id would do the
first.

What this deliberately does NOT do
-----------------------------------
It never closes anything. A green run afterwards means the same jobs passed
once, which is not the same as "the cause is gone" - the apt mirror that hung
three runs in a row on 2026-08-19 would have closed and reopened the issue twice
by itself. Closing stays a human act, and the issue body says so.
"""
import argparse
import json
import sys

# A cancelled run is not a failed one, and neither is a skipped job. Only these
# two count: GitHub reports "failure" for a job that ran and failed, and
# "cancelled" separately (a superseded run, or the 6-hour limit) - which says
# nothing about the code and must never open an issue.
FAILING = ("failure",)


def failed_jobs(needs):
    """Sorted ids of the jobs that ran and failed."""
    out = []
    for job_id, data in (needs or {}).items():
        if str((data or {}).get("result", "")).strip() in FAILING:
            out.append(str(job_id))
    return sorted(out)


def title_for(jobs):
    return "Weekly CI run is red: %s" % ", ".join(jobs)


def body_for(jobs, run_url="", commit=""):
    lines = ["The scheduled run of the CI workflow failed. Nothing in a pull request",
             "caused this - the schedule asks whether the world moved under versions",
             "that did not.", ""]
    lines.append("**Jobs that failed:** " + ", ".join("`%s`" % j for j in jobs))
    if commit:
        lines.append("**Commit:** `%s`" % commit)
    if run_url:
        lines.append("**Run:** %s" % run_url)
    lines += [
        "",
        "### The first question is whether this is us",
        "",
        "A weekly run fails for two quite different reasons and they look alike in",
        "the summary. Read the log before filing this as a defect:",
        "",
        "* **The world moved.** An unpinned development dependency released a new",
        "  version, the runner image changed, or the interpreter patch moved. That is",
        "  what this schedule exists to catch, and the fix is in this repository.",
        "* **The runner had a bad day.** A package mirror that stops answering looks",
        "  exactly like a hang in our own step - on 2026-08-19 that burned a job's",
        "  whole budget three runs in a row and nothing in the repository had changed.",
        "",
        "### This issue does not close itself",
        "",
        "A later green run means these jobs passed once, not that the cause is gone.",
        "Close it when you know which of the two it was.",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--needs", required=True,
                        help="`toJSON(needs)` from the workflow, written to a file")
    parser.add_argument("--existing", help="`gh issue list --json number,title` output")
    parser.add_argument("--title-out", help="write the issue title here")
    parser.add_argument("--body-out", help="write the issue body here")
    parser.add_argument("--run-url", default="", help="link back to the workflow run")
    parser.add_argument("--commit", default="", help="the commit the run was on")
    args = parser.parse_args(argv)

    try:
        with open(args.needs, encoding="utf-8") as handle:
            needs = json.load(handle)
    except (OSError, ValueError) as exc:
        # The same rule as the semgrep gate and the audit gate: a report that
        # cannot be read is not a clean report. Fail loudly rather than "none".
        print("cron_issue: cannot read %s: %s" % (args.needs, exc), file=sys.stderr)
        return 2

    jobs = failed_jobs(needs)
    if not jobs:
        print("none")
        return 0

    title = title_for(jobs)
    existing = []
    if args.existing:
        try:
            with open(args.existing, encoding="utf-8") as handle:
                existing = json.load(handle) or []
        except (OSError, ValueError) as exc:
            print("cron_issue: cannot read %s: %s" % (args.existing, exc), file=sys.stderr)
            return 2
    if any(str(issue.get("title", "")).strip() == title for issue in existing):
        print("skip")
        return 0

    if args.title_out:
        with open(args.title_out, "w", encoding="utf-8") as handle:
            handle.write(title)
    if args.body_out:
        with open(args.body_out, "w", encoding="utf-8") as handle:
            handle.write(body_for(jobs, args.run_url, args.commit))
    print("create")
    return 0


if __name__ == "__main__":
    sys.exit(main())
