"""The weekly red-run notice: when it opens an issue, and when it stays quiet.

The decision guarded here is not "did the run fail" - GitHub answers that - but
what the repository does about it. Opening an issue every Monday for a failure
somebody already read would train everyone to close them unread; swallowing a
DIFFERENT failure into the open issue about last week's would lose it. So the
title carries the failing job names, and matching is exact.

The other half is what must NOT open an issue: a cancelled run says nothing
about the code (a superseded run, a timeout), and a skipped job says even less.
Only a job that ran and failed counts.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import cron_issue                                          # noqa: E402
from fakes import check                                    # noqa: E402


def _needs(**results):
    """The shape `toJSON(needs)` produces: {job_id: {"result": ...}}."""
    return {job: {"result": result} for job, result in results.items()}


def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_a_green_run_says_nothing(tmp_path, capsys):
    path = _write(tmp_path, "n.json", _needs(tests="success", build="success"))
    code = cron_issue.main(["--needs", path])
    check("a green run exits 0", code == 0, f"(exit {code})")
    check("and asks for nothing", capsys.readouterr().out.strip() == "none")


def test_a_failure_asks_for_an_issue(tmp_path, capsys):
    path = _write(tmp_path, "n.json", _needs(tests="success", build="failure"))
    code = cron_issue.main(["--needs", path,
                            "--title-out", str(tmp_path / "t.txt"),
                            "--body-out", str(tmp_path / "b.md"),
                            "--run-url", "https://example.invalid/run/1",
                            "--commit", "abc1234"])
    check("it exits 0", code == 0, f"(exit {code})")
    check("and asks for an issue", capsys.readouterr().out.strip() == "create")
    title = (tmp_path / "t.txt").read_text(encoding="utf-8")
    check("the title names the failing job", "build" in title, f"({title})")
    check("and not the passing one", "tests" not in title, f"({title})")
    body = (tmp_path / "b.md").read_text(encoding="utf-8")
    check("the body carries the run link", "https://example.invalid/run/1" in body)
    check("and the commit", "abc1234" in body)


def test_a_cancelled_run_is_not_a_failure(tmp_path, capsys):
    """🔴 The one that must never fire.

    A cancelled job means a newer push superseded this run, or it hit the time
    limit. Neither says anything about the code, and an issue for it is noise
    that teaches people to close these unread.
    """
    path = _write(tmp_path, "n.json", _needs(tests="cancelled", build="skipped"))
    code = cron_issue.main(["--needs", path])
    check("a cancelled run exits 0", code == 0, f"(exit {code})")
    check("and opens nothing", capsys.readouterr().out.strip() == "none")


def test_the_same_failure_does_not_open_a_second_issue(tmp_path, capsys):
    path = _write(tmp_path, "n.json", _needs(build="failure"))
    open_issues = _write(tmp_path, "open.json",
                         [{"number": 7, "title": "Weekly CI run is red: build"}])
    code = cron_issue.main(["--needs", path, "--existing", open_issues])
    check("it exits 0", code == 0, f"(exit {code})")
    check("and skips, because an open issue says exactly this",
          capsys.readouterr().out.strip() == "skip")


def test_a_different_failure_is_not_swallowed_by_the_open_issue(tmp_path, capsys):
    """The other half of the rule above, and the one that loses information.

    Last week the build failed; this week the mutation registry did. Matching on
    the label alone would file the second under the first and nobody would see it.
    """
    path = _write(tmp_path, "n.json", _needs(mutations="failure"))
    open_issues = _write(tmp_path, "open.json",
                         [{"number": 7, "title": "Weekly CI run is red: build"}])
    code = cron_issue.main(["--needs", path, "--existing", open_issues,
                            "--title-out", str(tmp_path / "t.txt"),
                            "--body-out", str(tmp_path / "b.md")])
    check("it exits 0", code == 0, f"(exit {code})")
    check("and asks for a second issue", capsys.readouterr().out.strip() == "create")


def test_two_failures_are_one_issue_naming_both(tmp_path, capsys):
    path = _write(tmp_path, "n.json", _needs(build="failure", mutations="failure",
                                             tests="success"))
    cron_issue.main(["--needs", path, "--title-out", str(tmp_path / "t.txt"),
                     "--body-out", str(tmp_path / "b.md")])
    capsys.readouterr()
    title = (tmp_path / "t.txt").read_text(encoding="utf-8")
    check("the title names both, sorted", title.endswith("build, mutations"), f"({title})")


def test_an_unreadable_report_is_not_a_green_one(tmp_path, capsys):
    """The rule the semgrep gate and the audit gate already live by.

    A file that cannot be parsed must not read as "nothing failed" - that turns a
    broken workflow step into a clean bill of health.
    """
    path = tmp_path / "n.json"
    path.write_text("{not json", encoding="utf-8")
    code = cron_issue.main(["--needs", str(path)])
    check("it exits 2, not 0", code == 2, f"(exit {code})")
    check("and says nothing that could be mistaken for a verdict",
          capsys.readouterr().out.strip() == "")


def test_a_hand_fired_run_on_another_branch_says_so_in_the_title(tmp_path, capsys):
    """🔴 The reason the ref is in the title at all, and it is not cosmetic.

    The notice can be fired by hand, which is the only way to exercise this path
    without waiting for a red Monday. A hand-fired run can sit on any branch - so
    without the ref, an issue from a test run where `build` was deliberately red
    would carry exactly the title a genuine Monday failure of `build` produces.
    """
    path = _write(tmp_path, "n.json", _needs(build="failure"))
    cron_issue.main(["--needs", path, "--ref", "refs/heads/some-experiment",
                     "--title-out", str(tmp_path / "t.txt"),
                     "--body-out", str(tmp_path / "b.md")])
    capsys.readouterr()
    title = (tmp_path / "t.txt").read_text(encoding="utf-8")
    check("the title carries the branch", "some-experiment" in title, f"({title})")
    body = (tmp_path / "b.md").read_text(encoding="utf-8")
    check("and the body says it was not the schedule", "fired by hand" in body)


def test_the_weekly_title_is_unchanged_on_the_default_branch(tmp_path, capsys):
    """The other half: the ref must NOT leak into the title of a genuine run.

    Otherwise every weekly issue would carry a suffix, the dedup key would still
    work, and the titles would just be noisier for no reason.
    """
    path = _write(tmp_path, "n.json", _needs(build="failure"))
    cron_issue.main(["--needs", path, "--ref", "refs/heads/master",
                     "--title-out", str(tmp_path / "t.txt")])
    capsys.readouterr()
    title = (tmp_path / "t.txt").read_text(encoding="utf-8")
    check("a run on the default branch keeps the plain title",
          title == "Weekly CI run is red: build", f"({title})")


def test_a_test_issue_cannot_swallow_a_genuine_weekly_one(tmp_path, capsys):
    """The failure the two tests above exist to prevent, asserted end to end.

    An open issue from a hand-fired run must NOT make a real Monday failure of the
    same job report `skip` - that would lose the real one in silence, which is
    worse than the gap this notice closes.
    """
    open_issues = _write(tmp_path, "open.json",
                         [{"number": 9,
                           "title": "Weekly CI run is red: build (refs/heads/some-experiment)"}])
    path = _write(tmp_path, "n.json", _needs(build="failure"))
    cron_issue.main(["--needs", path, "--existing", open_issues,
                     "--ref", "refs/heads/master"])
    check("the genuine failure still asks for its own issue",
          capsys.readouterr().out.strip() == "create")
