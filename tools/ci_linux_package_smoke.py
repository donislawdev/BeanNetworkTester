#!/usr/bin/env python3
"""The Linux package as a person gets it: the frozen bundle runs, and says the right things.

Run by CI on the bundle it just built, as an ordinary user under Xvfb (the
capture itself is ``ci_linux_capture_smoke.py --program``, which needs root).
Each phase is a judge over what the program printed, so each can be shown to
fail (``tests/test_ci_linux_package_smoke.py``):

* ``--version``, a simulated session and a configuration error answer 0, 0 and 3,
  as the Windows exe's smoke asks;
* the session's "Reproduce:" line names the program itself - no ``.exe``, no
  interpreter, no ``sudo`` for ``--simulate`` (it said ``BeanNetworkTester.exe``);
* ``--doctor`` puts the user files in ``$XDG_CONFIG_HOME/BeanNetworkTester``
  (it said ``~/AppData/Local``);
* the window opens on the display, and says nothing on stderr: a bundled
  fontconfig older than the system's printed a warning per rule it rejected.

    xvfb-run -a python tools/ci_linux_package_smoke.py dist/BeanNetworkTester/BeanNetworkTester
"""
import os
import re
import subprocess
import sys
import tempfile
import time

WINDOW_TITLE = "Bean Network Tester"
WINDOW_WAIT_S = 30
CONFIG_ERROR = 3

# What a clean start must never print (each was seen: tools/linux_bundle.py, cli.py).
NOISE = ("Fontconfig", "Traceback", "symbol lookup error", "No tkinter", "could not open")


def judge_codes(version, simulated, bad):
    failures = []
    if version != 0:
        failures.append(f"--version answered {version}, not 0")
    if simulated != 0:
        failures.append(f"a simulated session answered {simulated}, not 0")
    if bad != CONFIG_ERROR:
        failures.append(f"a configuration error answered {bad}, not {CONFIG_ERROR}")
    return failures


def judge_repro(output):
    """The "Reproduce:" line of a ``--simulate`` session."""
    found = re.search(r"Reproduce: (\S+)(.*)", output)
    if not found:
        return ["the session printed no Reproduce: line"]
    program, rest = found.group(1), found.group(2)
    failures = []
    if program == "sudo":
        failures.append("a simulation is reproduced under sudo")
    if not (program.startswith("~/") or program == "./BeanNetworkTester"):
        failures.append(f"the program is named {program!r}, not from ~ or its own folder")
    if ".exe" in program or "python" in program:
        failures.append(f"the program is named {program!r}")
    if "--simulate" not in rest:
        failures.append("the Reproduce: line lost --simulate")
    return failures


def judge_doctor(output, config_home):
    want = f"user files: {config_home}/BeanNetworkTester"
    if want not in output:
        line = next((l for l in output.splitlines() if "user files" in l), "no such line")
        return [f"--doctor: expected '{want}', got '{line.strip()}'"]
    return []


def judge_window(seen, stderr):
    failures = [] if seen else [f"no window named {WINDOW_TITLE!r} in {WINDOW_WAIT_S} s"]
    noisy = [line for line in stderr.splitlines() if any(word in line for word in NOISE)]
    if noisy:
        failures.append(f"the window printed {len(noisy)} line(s) like {noisy[0]!r}")
    return failures


def _run(program, *args, env=None, timeout=60):
    done = subprocess.run([program, *args], capture_output=True, text=True,
                          env=env, timeout=timeout, check=False)
    return done.returncode, done.stdout + done.stderr


def window_seen(title=WINDOW_TITLE):
    """True when the display has a top-level window of that title (xwininfo)."""
    tree = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True,
                          text=True, timeout=10, check=False).stdout
    return f'"{title}"' in tree


def _window_phase(program, env):
    started = subprocess.Popen([program], env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, text=True)
    seen = False
    try:
        deadline = time.monotonic() + WINDOW_WAIT_S
        while time.monotonic() < deadline and started.poll() is None:
            if window_seen():
                seen = True
                time.sleep(2)               # what a start prints comes in its first seconds
                break
            time.sleep(0.5)
    finally:
        started.terminate()
        try:
            _out, err = started.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            started.kill()
            _out, err = started.communicate()
    return judge_window(seen, err or "")


def run_phases(program, scratch):
    env = {**os.environ, "LANG": "C.UTF-8", "BEAN_NO_ELEVATE": "1",
           "BEAN_DATA_DIR": os.path.join(scratch, "data")}
    version, _ = _run(program, "--version", env=env)
    simulated, output = _run(program, "--simulate", "--duration", "2", "--interval", "1",
                             "--seed", "42", env=env)
    bad, _ = _run(program, "--simulate", "--loss", "250", env=env)
    failures = judge_codes(version, simulated, bad)
    failures += judge_repro(output)
    config_home = os.path.join(scratch, "config")
    doctor_env = {k: v for k, v in env.items() if k != "BEAN_DATA_DIR"}
    doctor_env["XDG_CONFIG_HOME"] = config_home
    _code, report = _run(program, "--doctor", env=doctor_env)
    failures += judge_doctor(report, config_home)
    failures += _window_phase(program, env)
    return failures


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: ci_linux_package_smoke.py <the bundle's executable>", file=sys.stderr)
        return 2
    if not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"):
        print("FAIL: needs Linux and a display (run it under xvfb-run)")
        return 1
    with tempfile.TemporaryDirectory(prefix="bnt-package-") as scratch:
        failures = run_phases(os.path.abspath(argv[0]), scratch)
    for failure in failures:
        print("FAIL:", failure)
    print("OK" if not failures else f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
