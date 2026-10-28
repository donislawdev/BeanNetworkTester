#!/usr/bin/env python3
"""The window asking for root through pkexec on Linux, with the real pkexec and polkitd.

Why this exists
---------------
``beantester/linuxenv.py`` starts the window again as root through pkexec when it
opens without root, and the copy takes the person's display back from the process
that asked. Its tests hand every call to the system in; this runs the real thing on
GitHub's ubuntu runner (Ubuntu 24.04: polkit 124, which names the person only by
``PKEXEC_UID`` - the fallback ``paths.invoking_user`` needs there).

What it checks
--------------
* REFUSED - no rule yet, no agent to ask through: ``linuxenv.ask_for_root`` must
  answer None (pkexec's 127) within seconds. The canary: if pkexec ran without
  the rule, the phases below would prove nothing.
* ``linuxenv.wants_root`` says yes on this machine: not root, no capabilities, a
  display (Xvfb), pkexec there.
* GRANTED - a polkit rule lets this runner's user run pkexec without a password,
  standing in for the person typing it (the runner is thrown away after the job).
  The copy, run as root by the product's own ``ask_for_root``, reports: pkexec took
  ``DISPLAY`` away and Tk could not open (the problem is real here), then
  ``take_desktop`` gave back this process's display, X authority and folder, Tk
  opened, and ``invoking_user`` named this runner's user.
* The same once more as polkit 0.105 runs it, without ``--keep-cwd``: the copy
  starts in root's home and must enter this process's folder by itself.

Not Linux, root, no display, no pkexec or no ``sudo -n`` -> SKIP and exit 0, unless
``--require`` is given, which CI passes.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RULE = "/etc/polkit-1/rules.d/49-bnt-ci-pkexec.rules"
RULE_TEXT = """polkit.addRule(function (action, subject) {
    if (action.id == "org.freedesktop.policykit.exec" && subject.user == "%s") {
        return polkit.Result.YES;
    }
});
"""
REFUSAL_SECONDS = 10      # pkexec without an agent answers in milliseconds (measured: 19-76 ms)
RULE_WAIT_SECONDS = 15    # polkitd reads a new rule file by itself


# -- verdicts (pure, tested in tests/test_ci_linux_pkexec_smoke.py) ------------------ #
def skip_reason(platform, euid, display, pkexec, can_sudo):
    """Why this machine cannot run the check, or None. ``can_sudo`` is asked last
    and only on Linux: Windows 11 has a ``sudo`` of its own, which shows UAC."""
    if not platform.startswith("linux"):
        return "not Linux"
    if euid == 0:
        return "already root: there is nothing to ask for"
    if not display:
        return "no DISPLAY (run it under xvfb-run)"
    if not pkexec:
        return "pkexec is not installed"
    if not can_sudo():
        return "sudo -n cannot write the polkit rule"
    return None


def judge_refusal(code, seconds):
    failures = []
    if code is not None:
        failures.append(f"REFUSED: pkexec ran the copy without the rule (answered {code}) - "
                        "the granted phases would prove nothing")
    if seconds > REFUSAL_SECONDS:
        failures.append(f"REFUSED: pkexec took {seconds:.1f} s to refuse, not milliseconds")
    return failures


def judge_child(phase, code, report, person, keep_cwd):
    """``person``: uid, gid, display, xauthority and cwd of this process."""
    if code != 0 or report is None:
        return [f"{phase}: the copy did not report (ask_for_root answered {code})"]
    failures = []

    def want(name, got, expected):
        if got != expected:
            failures.append(f"{phase}: {name} is {got!r}, expected {expected!r}")

    want("euid", report.get("euid"), 0)
    want("PKEXEC_UID", report.get("pkexec_uid"), str(person["uid"]))
    want("DISPLAY before the take (pkexec drops it)", report.get("display_before"), None)
    if not str(report.get("tk_before", "")).startswith("TclError"):
        failures.append(f"{phase}: Tk opened before the take ({report.get('tk_before')!r}) - "
                        "the take is not what made it work")
    want("DISPLAY taken", report.get("display_after"), person["display"])
    want("XAUTHORITY taken", report.get("xauthority_after"), person["xauthority"])
    want("Tk after the take", report.get("tk_after"), "ok")
    want("folder before the take", report.get("cwd_before"),
         person["cwd"] if keep_cwd else report.get("root_home"))
    want("folder after the take", report.get("cwd_after"), person["cwd"])
    want("invoking_user", report.get("invoking_user"), [person["uid"], person["gid"]])
    return failures


# -- the copy pkexec starts -------------------------------------------------------- #
def child_report():
    """Run as root by pkexec: what the copy finds, before and after taking the desktop."""
    import pwd

    from beantester import linuxenv, paths
    report = {"euid": os.geteuid(), "pkexec_uid": os.environ.get("PKEXEC_UID"),
              "sudo_uid": os.environ.get("SUDO_UID"),
              "display_before": os.environ.get("DISPLAY"), "cwd_before": os.getcwd(),
              "root_home": pwd.getpwuid(0).pw_dir}
    report["tk_before"] = _tk()
    report["taken"] = linuxenv.take_desktop()
    report.update(display_after=os.environ.get("DISPLAY"),
                  xauthority_after=os.environ.get("XAUTHORITY"), cwd_after=os.getcwd(),
                  tk_after=_tk(), invoking_user=list(paths.invoking_user() or []) or None)
    return report


def _tk():
    try:
        import tkinter
        root = tkinter.Tk()
        root.update()
        root.destroy()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return "ok"


# -- the person's side ------------------------------------------------------------- #
def _sudo(*argv, stdin=None):
    return subprocess.run(["sudo", "-n", *argv], input=stdin, capture_output=True,
                          text=True, timeout=30, check=False)


def _rule_takes(pkexec):
    deadline = time.monotonic() + RULE_WAIT_SECONDS
    while time.monotonic() < deadline:
        done = subprocess.run([pkexec, "--disable-internal-agent", "/bin/true"],
                              env={}, capture_output=True, timeout=30, check=False)
        if done.returncode == 0:
            return True
        time.sleep(0.5)
    return False


def _ask(linuxenv, report_path):
    code = linuxenv.ask_for_root(["--child", report_path])
    try:
        with open(report_path, encoding="utf-8") as f:
            return code, json.load(f)
    except (OSError, ValueError):
        return code, None


def run_phases(pkexec):
    from beantester import linuxenv
    failures = []
    person = {"uid": os.getuid(), "gid": os.getgid(), "display": os.environ.get("DISPLAY"),
              "xauthority": os.environ.get("XAUTHORITY"), "cwd": os.getcwd()}
    work = tempfile.mkdtemp(prefix="bnt-pkexec-")
    _sudo("rm", "-f", RULE)
    started = time.monotonic()
    code = linuxenv.ask_for_root(["--child", os.path.join(work, "refused.json")])
    failures += judge_refusal(code, time.monotonic() - started)
    print(f"REFUSED: ask_for_root answered {code}", flush=True)
    if not linuxenv.wants_root():
        failures.append("wants_root says no on a runner without root, with a display and pkexec")
    import pwd
    _sudo("tee", RULE, stdin=RULE_TEXT % pwd.getpwuid(os.getuid()).pw_name)
    try:
        if not _rule_takes(pkexec):
            return failures + [f"polkitd did not take {RULE} within {RULE_WAIT_SECONDS} s"]
        for number, (phase, keep) in enumerate((("GRANTED", True),
                                                ("GRANTED, no --keep-cwd", False))):
            if not keep:
                # As polkit 0.105's pkexec (Ubuntu 22.04), which has no --keep-cwd.
                linuxenv._keeps_cwd = lambda *a: False
            code, report = _ask(linuxenv, os.path.join(work, f"granted-{number}.json"))
            print(f"{phase}: ask_for_root answered {code}, report {json.dumps(report)}", flush=True)
            failures += judge_child(phase, code, report, person, keep)
    finally:
        _sudo("rm", "-f", RULE)
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--require", action="store_true",
                        help="a machine that cannot run the check fails instead of skipping")
    parser.add_argument("--child", metavar="REPORT", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        with open(args.child, "w", encoding="utf-8") as f:
            json.dump(child_report(), f)
        return 0
    pkexec = shutil.which("pkexec") if sys.platform.startswith("linux") else None
    reason = skip_reason(sys.platform, getattr(os, "geteuid", lambda: None)(),
                         os.environ.get("DISPLAY"), pkexec,
                         lambda: bool(shutil.which("sudo")) and _sudo("true").returncode == 0)
    if reason:
        print(f"SKIP: {reason}")
        return 1 if args.require else 0
    failures = run_phases(pkexec)
    for failure in failures:
        print(f"FAIL {failure}")
    print("pkexec smoke: " + ("FAILED" if failures else "OK"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
