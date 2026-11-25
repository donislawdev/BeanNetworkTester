"""Tries the installed package on a runner the way its README tells people to use it.

Run by .github/workflows/pypi.yml in a fresh virtual environment that holds the wheel
pip picked from the release's wheels, and nothing from the checkout:

    python try_package.py install <version> <repo>     the package and its program
    python try_package.py session <repo> [--playwright]

``install`` says the package was installed (not imported from the checkout), that its
program is the release's (``--version``) and, on Windows, that it is signed with the
project's certificate. ``session`` serves two local web servers and runs a real pytest
file that uses the ``bad_network`` fixture: the server it aims at is slowed, the other
one is not, and the session stops with a summary. ``--playwright`` adds a page loaded
in Chromium. With BEANNETWORKTESTER_PROGRAM set (a pull request, whose release may be
older than the helper), the checkout's program runs instead of the packaged one.

Each judge is a function over numbers, so each can be shown to fail
(tests/test_helper_python.py).
"""

from __future__ import annotations

import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import threading
from pathlib import Path

LATENCY_MS = 200
# A new connection crosses the impairment at least once on the way there (the SYN or
# the request). 90 % of one crossing is the floor, far above loopback's noise.
SLOWED_MIN_MS = LATENCY_MS * 0.9
UNTOUCHED_MAX_MS = 50


# --- judges ---------------------------------------------------------------------- #


def judge_install(location: str, version_line: str, version: str, from_checkout: bool):
    """``version`` is the tag's without the v. A candidate's program carries the version
    it leads to (VERSION.txt holds three numbers), so 1.1.0-rc.1 says 1.1.0."""
    failures = []
    if "site-packages" not in location.replace("\\", "/"):
        failures.append(f"beannetworktester was imported from {location}, not from the install")
    core = version.split("-")[0]
    if not from_checkout and version_line.strip() != f"Bean Network Tester {core}":
        failures.append(f"the packaged program says {version_line.strip()!r}, not version "
                        f"{core}")
    return failures


def judge_signature(status: str, digest: str, pin: str):
    failures = []
    if status != "Valid":
        failures.append(f"the packaged exe's signature is {status!r}, not Valid")
    if digest.lower() != pin.lower():
        failures.append(f"the packaged exe is signed by a certificate whose SHA-256 is "
                        f"{digest}, not the project's {pin}")
    return failures


def judge_session(r: dict):
    """Milliseconds per request before, during and after, to the aim and to the control."""
    failures = []
    if r.get("slow_aim", 0) - r.get("base_aim", 0) < SLOWED_MIN_MS:
        failures.append(f"the server aimed at was not slowed: {r.get('base_aim')} -> "
                        f"{r.get('slow_aim')} ms, expected at least +{SLOWED_MIN_MS:g}")
    if r.get("slow_control", 1e9) - r.get("base_control", 0) > UNTOUCHED_MAX_MS:
        failures.append(f"a server the session did not aim at was slowed: "
                        f"{r.get('base_control')} -> {r.get('slow_control')} ms")
    if r.get("after_aim", 1e9) - r.get("base_aim", 0) > UNTOUCHED_MAX_MS:
        failures.append(f"the server was still slow after the session stopped: "
                        f"{r.get('after_aim')} ms")
    if r.get("stop_reason") != "stdin":
        failures.append(f"the session did not stop by its input closing: "
                        f"{r.get('stop_reason')!r}")
    if not r.get("in_scope"):
        failures.append("the summary counts no packet in scope")
    return failures


def judge_page(r: dict):
    failures = []
    if r.get("slow_page", 0) - r.get("base_page", 0) < SLOWED_MIN_MS:
        failures.append(f"the page in Chromium was not slowed: {r.get('base_page')} -> "
                        f"{r.get('slow_page')} ms")
    return failures


# --- install ---------------------------------------------------------------------- #


def _codesign_pin(repo: Path) -> str:
    text = (repo / "beantester" / "legal.py").read_text(encoding="utf-8")
    found = re.search(r'^CODESIGN_SHA256 = "([0-9a-f]{64})"', text, re.M)
    if not found:
        raise SystemExit("could not read CODESIGN_SHA256 out of beantester/legal.py")
    return found.group(1)


def _signature(exe: str) -> tuple[str, str]:
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:EXE; $s.Status.ToString(); "
              "$h = [System.Security.Cryptography.SHA256]::Create().ComputeHash("
              "$s.SignerCertificate.RawData); ($h | ForEach-Object { $_.ToString('x2') }) -join ''")
    done = subprocess.run(["pwsh", "-NoProfile", "-Command", script], capture_output=True,  # noqa: S603, S607
                          text=True, env=dict(os.environ, EXE=exe), check=False)
    lines = done.stdout.split()
    return (lines[0], lines[1]) if len(lines) >= 2 else (done.stdout + done.stderr, "")


def install(version: str, repo: Path) -> list[str]:
    import beannetworktester
    from beannetworktester._program import PROGRAM_ENV, program_command
    from_checkout = bool(os.environ.get(PROGRAM_ENV))
    command = program_command()
    version_line = "" if from_checkout else subprocess.run(  # noqa: S603
        [*command, "--version"], capture_output=True, text=True, check=False).stdout
    failures = judge_install(beannetworktester.__file__, version_line, version, from_checkout)
    if sys.platform == "win32" and not from_checkout:
        failures += judge_signature(*_signature(command[0]), _codesign_pin(repo))
    print(f"package: {beannetworktester.__file__}\nprogram: {command}\n{version_line.strip()}")
    return failures


# --- session ---------------------------------------------------------------------- #


class _Quiet(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><title>try</title><p>ok</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _serve() -> str:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


TEST_FILE = '''
import json, statistics, time, urllib.request

AIM, CONTROL, OUT = {aim!r}, {control!r}, {out!r}
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({{}}))


def ms(url, n=5):
    times = []
    for _ in range(n):
        start = time.monotonic()
        with OPENER.open(url + "/", timeout=30) as reply:
            reply.read()
        times.append((time.monotonic() - start) * 1000)
    return round(statistics.median(times), 1)


def _save(**values):
    try:
        with open(OUT, encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        data = {{}}
    data.update(values)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_the_server_aimed_at_is_slowed_and_nothing_else(bad_network):
    base_aim, base_control = ms(AIM), ms(CONTROL)
    session = bad_network(server=AIM, latency={latency}, duration=120)
    slow_aim, slow_control = ms(AIM), ms(CONTROL)
    summary = session.stop()
    _save(base_aim=base_aim, base_control=base_control, slow_aim=slow_aim,
          slow_control=slow_control, after_aim=ms(AIM), stop_reason=summary["stop_reason"],
          in_scope=summary["counters"]["scoped_seen"])
'''

PAGE_TEST = '''

def test_a_page_in_chromium_is_slowed(bad_network):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        def load():
            page = browser.new_page()
            start = time.monotonic()
            page.goto(AIM + "/", wait_until="load")
            took = (time.monotonic() - start) * 1000
            page.close()
            return round(took, 1)
        base = load()
        bad_network(server=AIM, latency={latency}, duration=120)
        _save(base_page=base, slow_page=load())
        browser.close()
'''


def session(repo: Path, playwright: bool) -> list[str]:
    aim, control = _serve(), _serve()
    work = Path(tempfile.mkdtemp(prefix="bnt-try-"))
    out = work / "results.json"
    body = TEST_FILE.format(aim=aim, control=control, out=str(out), latency=LATENCY_MS)
    if playwright:
        body += PAGE_TEST.format(latency=LATENCY_MS)
    (work / "test_try.py").write_text(textwrap.dedent(body), encoding="utf-8")
    report = work / "report.xml"
    done = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-v",  # noqa: S603
                           f"--junitxml={report}", "test_try.py"], cwd=work, check=False)
    failures = [] if done.returncode == 0 else [f"pytest ended with {done.returncode}"]
    results = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    print(json.dumps(results, indent=2))
    failures += judge_session(results)
    if playwright:
        failures += judge_page(results)
    if 'name="bad_network"' not in (report.read_text(encoding="utf-8")
                                    if report.exists() else ""):
        failures.append("the JUnit report holds no bad_network property")
    return failures


def main(argv: list[str]) -> int:
    if argv[:1] == ["install"] and len(argv) == 3:
        failures = install(argv[1], Path(argv[2]))
    elif argv[:1] == ["session"] and len(argv) in (2, 3):
        failures = session(Path(argv[1]), argv[2:] == ["--playwright"])
    else:
        print("usage: try_package.py install <version> <repo> | session <repo> [--playwright]")
        return 2
    for failure in failures:
        print(f"::error::{failure}", file=sys.stderr)
    print("the package did what its README says" if not failures
          else f"{len(failures)} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
