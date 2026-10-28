"""tools/ci_linux_pkexec_smoke.py: its verdicts name every broken thing, and a machine
that cannot run it skips - which CI's ``--require`` turns into a failure.

The real run is CI's (the Linux job); here only the judging, which runs anywhere.
"""
import os
import sys

from fakes import ROOT, check

sys.path.insert(0, os.path.join(ROOT, "tools"))

import ci_linux_pkexec_smoke as smoke                       # noqa: E402

PERSON = {"uid": 1001, "gid": 118, "display": ":99",
          "xauthority": "/tmp/xvfb-run.Ab/Xauthority", "cwd": "/w/repo"}


def good(keep=True):
    return {"euid": 0, "pkexec_uid": "1001", "sudo_uid": None, "display_before": None,
            "cwd_before": "/w/repo" if keep else "/root", "root_home": "/root",
            "tk_before": "TclError: no display name and no $DISPLAY environment variable",
            "taken": ["DISPLAY", "XAUTHORITY", "cwd"], "display_after": ":99",
            "xauthority_after": "/tmp/xvfb-run.Ab/Xauthority", "cwd_after": "/w/repo",
            "tk_after": "ok", "invoking_user": [1001, 118]}


def test_a_copy_that_did_its_job_passes():
    check("with --keep-cwd", smoke.judge_child("G", 0, good(), PERSON, True) == [])
    check("without it", smoke.judge_child("G", 0, good(False), PERSON, False) == [])


def test_every_broken_copy_is_named():
    cases = {"euid": 1001, "pkexec_uid": "0", "display_before": ":99", "tk_before": "ok",
             "display_after": None, "xauthority_after": None,
             "tk_after": "TclError: couldn't connect to display", "cwd_after": "/root",
             "invoking_user": None}
    for field, value in cases.items():
        failures = smoke.judge_child("G", 0, dict(good(), **{field: value}), PERSON, True)
        check(f"{field}={value!r} is named, alone", len(failures) == 1, f"({failures})")
    kept = smoke.judge_child("G", 0, dict(good(), cwd_before="/root"), PERSON, True)
    check("with --keep-cwd the copy starts in the person's folder", len(kept) == 1, f"({kept})")
    fallback = smoke.judge_child("G", 0, dict(good(False), cwd_before="/w/repo"), PERSON, False)
    check("without it in root's home - else the fallback was not what ran",
          len(fallback) == 1, f"({fallback})")
    check("no report", smoke.judge_child("G", 127, None, PERSON, True)
          == ["G: the copy did not report (ask_for_root answered 127)"])


def test_a_refusal_must_be_one_and_be_quick():
    check("refused at once: fine", smoke.judge_refusal(None, 0.05) == [])
    check("ran without the rule: the canary fires", len(smoke.judge_refusal(0, 0.05)) == 1)
    check("refused, but slowly", len(smoke.judge_refusal(None, 30)) == 1)


def test_a_machine_that_cannot_run_it_skips_and_ci_turns_that_into_a_failure(monkeypatch, capsys):
    reason = smoke.skip_reason
    asked = []

    def sudo(answer):
        return lambda: asked.append(answer) or answer

    check("Linux, a person, a display, pkexec, sudo: runs",
          reason("linux", 1001, ":99", "/usr/bin/pkexec", sudo(True)) is None)
    for args, said in ((("win32", None, ":0", "x"), "not Linux"),
                       (("linux", 0, ":0", "x"), "already root"),
                       (("linux", 1001, None, "x"), "no DISPLAY"),
                       (("linux", 1001, ":0", None), "pkexec")):
        asked.clear()
        got = reason(*args, sudo(True))
        check(f"{args}: skips, saying {said!r}, without asking sudo",
              said in (got or "") and not asked, f"({got}, {asked})")
    check("no sudo -n", "sudo" in (reason("linux", 1001, ":0", "x", sudo(False)) or ""))
    monkeypatch.setattr(sys, "platform", "win32")
    check("a skip is exit 0", smoke.main([]) == 0)
    check("and with --require exit 1", smoke.main(["--require"]) == 1)
    check("saying why", "SKIP: not Linux" in capsys.readouterr().out)
