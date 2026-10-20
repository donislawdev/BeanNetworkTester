#!/usr/bin/env python3
"""A real capture on Linux (experimental, eBPFDivert): the impairment arrives, and only where it was aimed.

Why this exists
---------------
Linux capture goes through a second driver, pydivert's eBPFDivert, chosen by
``beantester/capture_backend.py``. Everything else in the suite drives it through
stand-ins, and a stand-in cannot tell whether the kernel really held, dropped or
let past a packet. This runs the real command line, as a user would, on a real
kernel - GitHub's ubuntu runner in CI.

What it checks, and why each needs two signals
----------------------------------------------
A UDP echo far end with two ports: the TARGET the session aims at and a BYSTANDER
it must not touch. Every phase measures both, because "impaired" and "the far end
went away" look the same from one side.

* before any session: both ports answer fast (the control - without it a slow
  machine would pass the latency phase by itself);
* ``--latency 50 --narrow-filter``: the target's round trip grows by both
  directions' 50 ms, the bystander's does not, and the filter was narrowed;
* ``--loss 100``: the target goes silent, the bystander keeps answering;
* after: both are fast again - the session took nothing with it.

What bounds the damage (convention 6)
-------------------------------------
Every packet the tool can see is inside a network namespace this script builds
(``bntci``, joined to the root namespace by a veth pair) and deletes again, also
when a phase fails. The sessions run INSIDE it, with ``--dst-ip``, ``--dst-port``
and ``--duration``, so the machine's own interfaces are never handed to the tool.

Not Linux, not root, or no eBPFDivert -> SKIP and exit 0, unless ``--require`` is
given, which CI passes: there a check that cannot run must fail, not pass quietly.
"""
import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NS = "bntci"
HOST, PEER = "10.233.0.1", "10.233.0.2"
TARGET_PORT, BYSTANDER_PORT = 47101, 47102
LATENCY_MS = 50
ROUNDS = 12

# Run INSIDE the namespace: one UDP echo per round, the round trip in ms or None.
CLIENT = (
    "import json, socket, sys, time\n"
    "host, port, rounds = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])\n"
    "s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
    "s.settimeout(float(sys.argv[4]))\n"
    "out = []\n"
    "for i in range(rounds):\n"
    "    t0 = time.perf_counter()\n"
    "    s.sendto(b'bnt%d' % i, (host, port))\n"
    "    try:\n"
    "        s.recvfrom(64)\n"
    "        out.append(round((time.perf_counter() - t0) * 1000, 2))\n"
    "    except OSError:\n"
    "        out.append(None)\n"
    "    time.sleep(0.05)\n"
    "print(json.dumps(out))\n")


# -- the judges: pure, so a test can prove they fail ------------------------------ #
def _answered(rtts):
    return [r for r in rtts if r is not None]


def _median(rtts):
    got = _answered(rtts)
    return statistics.median(got) if got else None


def judge_latency(before, during, bystander, after, latency_ms=LATENCY_MS):
    """Failures (empty = pass) for the latency phase and the controls around it."""
    fast = latency_ms / 2
    added = 2 * latency_ms                       # each direction carries the latency
    failures = []
    for name, rtts in (("before", before), ("during", during), ("bystander", bystander),
                       ("after", after)):
        if len(_answered(rtts)) < 0.8 * len(rtts) or not rtts:
            failures.append(f"{name}: only {len(_answered(rtts))} of {len(rtts)} answered")
    m = {name: _median(r) for name, r in (("before", before), ("during", during),
                                          ("bystander", bystander), ("after", after))}
    if m["before"] is not None and m["before"] >= fast:
        failures.append(f"before: {m['before']} ms - the machine is too slow to tell")
    if m["during"] is not None and not 0.9 * added <= m["during"] <= added + 100:
        failures.append(f"during: {m['during']} ms, expected about {added} ms")
    if m["bystander"] is not None and m["bystander"] >= fast:
        failures.append(f"bystander: {m['bystander']} ms - the session reached past its target")
    if m["after"] is not None and m["after"] >= fast:
        failures.append(f"after: {m['after']} ms - the session left something behind")
    return failures


def judge_loss(target, bystander):
    """Failures (empty = pass) for the --loss 100 phase."""
    failures = []
    if _answered(target):
        failures.append(f"target: {len(_answered(target))} of {len(target)} answered under --loss 100")
    if not bystander or len(_answered(bystander)) < len(bystander):
        failures.append(f"bystander: {len(_answered(bystander))} of {len(bystander)} answered")
    return failures


def skip_reason(platform, euid, library_loaded):
    """Why this machine cannot run the check, or None."""
    if not platform.startswith("linux"):
        return "not Linux"
    if euid != 0:
        return "not root (the capture needs it)"
    if not library_loaded:
        return "pydivert's libebpfdivert is not loaded"
    return None


# -- the machine ---------------------------------------------------------------- #
def _ip(*args):
    subprocess.run(["ip", *args], check=True, capture_output=True, text=True)


def build_namespace():
    teardown_namespace()
    _ip("netns", "add", NS)
    _ip("link", "add", f"{NS}-h", "type", "veth", "peer", "name", f"{NS}-c")
    _ip("link", "set", f"{NS}-c", "netns", NS)
    _ip("addr", "add", f"{HOST}/30", "dev", f"{NS}-h")
    _ip("link", "set", f"{NS}-h", "up")
    _ip("-n", NS, "addr", "add", f"{PEER}/30", "dev", f"{NS}-c")
    _ip("-n", NS, "link", "set", f"{NS}-c", "up")
    _ip("-n", NS, "link", "set", "lo", "up")


def teardown_namespace():
    subprocess.run(["ip", "netns", "del", NS], capture_output=True)
    subprocess.run(["ip", "link", "del", f"{NS}-h"], capture_output=True)


def start_far_end():
    """UDP echo on both ports, in THIS process, in the root namespace."""
    for port in (TARGET_PORT, BYSTANDER_PORT):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((HOST, port))

        def echo(s=sock):
            while True:
                data, addr = s.recvfrom(64)
                s.sendto(data, addr)
        threading.Thread(target=echo, daemon=True).start()


def in_namespace(*argv):
    return ["ip", "netns", "exec", NS, *argv]


def measure(port, rounds=ROUNDS, timeout=1.0):
    """Round trips from inside the namespace: ``rounds * (timeout + 0.05)`` s at worst."""
    r = subprocess.run(in_namespace(sys.executable, "-c", CLIENT, HOST, str(port), str(rounds),
                                    str(timeout)),
                       capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout.strip() or "[]")


def run_session(args, during):
    """The real CLI inside the namespace; ``during()`` runs once the session is up."""
    p = subprocess.Popen(in_namespace(sys.executable, "-m", "beantester", *args), cwd=ROOT,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env={**os.environ, "LANG": "C.UTF-8"})
    lines, up = [], threading.Event()

    def read():
        for line in p.stdout:
            lines.append(line.rstrip())
            if "Running" in line:
                up.set()
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    if not up.wait(20):
        p.kill()
        return None, lines, None
    result = during()
    code = p.wait(60)
    reader.join(5)
    return result, lines, code


def _session_failures(name, result, lines, code):
    if result is None:
        return [f"{name} session never said it was running: {lines[-5:]}"]
    return [f"{name} session: exit {code}"] if code != 0 else []


def _latency_phase():
    before = measure(TARGET_PORT)
    # 12 rounds of ~100 ms + 12 of a few ms: about 2.5 s of an 8 s session.
    result, lines, code = run_session(
        ["--dst-ip", HOST, "--dst-port", str(TARGET_PORT), "--latency", str(LATENCY_MS),
         "--narrow-filter", "--duration", "8"],
        lambda: (measure(TARGET_PORT), measure(BYSTANDER_PORT)))
    failures = _session_failures("latency", result, lines, code)
    if result is None:
        return failures
    during, bystander = result
    after = measure(TARGET_PORT)
    failures += judge_latency(before, during, bystander, after)
    if not any("narrowed" in line for line in lines):
        failures.append("latency session: the driver filter was not narrowed")
    print("latency:", json.dumps({"before": _median(before), "during": _median(during),
                                  "bystander": _median(bystander), "after": _median(after)}))
    return failures


def _loss_phase():
    # 6 rounds at 0.3 s each, at worst 2.1 s, inside a 6 s session: a round that
    # outlived the session would be answered by an unimpaired path and read as a leak.
    result, lines, code = run_session(
        ["--dst-ip", HOST, "--dst-port", str(TARGET_PORT), "--loss", "100", "--duration", "6"],
        lambda: (measure(TARGET_PORT, rounds=6, timeout=0.3),
                 measure(BYSTANDER_PORT, rounds=6, timeout=0.3)))
    failures = _session_failures("loss", result, lines, code)
    if result is None:
        return failures
    target, bystander = result
    failures += judge_loss(target, bystander)
    print("loss:", json.dumps({"target_answered": len(_answered(target)),
                               "bystander_answered": len(_answered(bystander))}))
    return failures


def main(argv=None, environment=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--require", action="store_true",
                        help="fail instead of skipping when this machine cannot run the check")
    args = parser.parse_args(argv)
    if environment is None:
        try:
            from pydivert import bpf
            loaded = bpf.libebpfdivert is not None
        except ImportError:
            loaded = False
        environment = (sys.platform, os.geteuid() if hasattr(os, "geteuid") else -1, loaded)
    reason = skip_reason(*environment)
    if reason:
        print(("FAIL" if args.require else "SKIP") + f": {reason}")
        return 1 if args.require else 0

    failures = []
    build_namespace()
    try:
        start_far_end()
        failures += _latency_phase()
        failures += _loss_phase()
    except Exception as exc:                      # a phase that could not run is a failure
        failures.append(f"{type(exc).__name__}: {exc}")
    finally:
        teardown_namespace()
    for failure in failures:
        print("FAIL:", failure)
    print("OK" if not failures else f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
