#!/usr/bin/env python3
"""The container image: which release it is made of, and a try-out before anything is pushed.

Both commands are run by ``.github/workflows/docker.yml``:

* ``decide`` answers which release the run is about and whether its image may be
  pushed. Only a stable release is: a tag ``vX.Y.Z`` with nothing after it, on a
  release that is published and not marked as a pre-release. A release candidate is
  built and tried like a pull request, and nothing is pushed.
* ``try IMAGE TAG`` runs the image on the runner's own kernel the way the README and
  the site tell people to, and judges what it measured:

  - ``--version`` names the release, and no arguments print the help (the window
    has no screen in a container);
  - ``--doctor`` refuses without the three capabilities and passes with them;
  - a sidecar in another container's network adds the latency to that container's
    traffic to one address and leaves another address alone, ``docker stop`` ends
    it cleanly, and the traffic is normal at once afterwards;
  - ``--target`` reaches a program in another container with ``--pid container:``;
  - ``--target`` reaches a program on the host with ``--network host --pid host``
    and the two extra options (narrowed to 127.0.0.1, so the runner's own
    connection can never match).

Each judge is a function over numbers and text, so each can be shown to fail
(``tests/test_ci_docker_image.py``). Standard library only: it runs on the runner's
system Python.

    python3 tools/ci_docker_image.py decide --event release --tag v1.1.0 --latest v1.1.0 \\
        --draft false --prerelease false >> "$GITHUB_OUTPUT"
    python3 -u tools/ci_docker_image.py try beannetworktester:try v1.1.0
"""
import argparse
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request

# What a capture needs on top of Docker's defaults (CAP_NET_RAW is one of them), and
# what reaching a program on the host needs on top of that: reading another process's
# sockets is ptrace-checked, and AppArmor's docker-default profile refuses it even
# with SYS_PTRACE (measured on Ubuntu 26.04, Docker 29.1.3, 2026-11-25). The README
# and the site page print these same options; the tests hold them together.
CAPTURE_CAPS = ("BPF", "PERFMON", "NET_ADMIN")
HOST_EXTRA = ("--cap-add", "SYS_PTRACE", "--security-opt", "apparmor=unconfined")

# One small image for both helpers: nginx is the far end (and the program --target
# names), busybox gives the other container ping and wget. Plain alpine has no web
# server (busybox's httpd lives in busybox-extras there). By digest, like every other
# thing a workflow pulls.
HELPER = ("nginx:1.30.6-alpine@sha256:"
          "901e593c95dc85f5a729f5765516321366ef4ac401821431d408897e95287d0a")
HELPER_PROGRAM = "nginx"

LATENCY_MS = 100
# Ping crosses the impairment twice (the request and the reply). 90 % of that is
# the floor; a container network answers in well under a millisecond otherwise.
DELAYED_MIN_MS = 2 * LATENCY_MS * 0.9
NORMAL_MS = 50
STOP_EXIT = 143            # 128 + SIGTERM: the program's own clean stop
STOP_WITHIN_S = 10
GETS = 5
# A fresh HTTP connection crosses the impairment at least four times (SYN, SYN-ACK,
# the request, the reply), so five of them add two seconds; half of that is plenty
# above the noise of `docker exec`.
TARGET_ADDED_S = GETS * 4 * LATENCY_MS / 1000 / 2
HOST_GET_MIN_S = 2 * LATENCY_MS / 1000 * 0.9

TAG = re.compile(r"v\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?")
STABLE = re.compile(r"v\d+\.\d+\.\d+")


def decide(event, tag, latest, draft, prerelease):
    """``{"tag", "version", "latest", "publish", "notice"}`` - or ``ValueError`` saying why not.

    ``draft`` and ``prerelease`` are the API's answers for ``tag`` ("true"/"false").
    """
    if event not in ("release", "workflow_dispatch", "pull_request"):
        raise ValueError(f"{event!r} is not an event this workflow runs on")
    if not TAG.fullmatch(tag or ""):
        raise ValueError(f'"{tag}" is not a release tag, for example v1.1.0')
    if draft != "false":
        raise ValueError(f"{tag} is not published yet, and an image is only ever made of "
                         "what people can download")
    stable = bool(STABLE.fullmatch(tag)) and prerelease == "false"
    publish = event != "pull_request"
    notice = ""
    if not stable:
        if event == "workflow_dispatch":
            raise ValueError(f"{tag} is not a stable release, and only stable releases become "
                             "images. Run this workflow with the tag of one, such as v1.1.0.")
        if publish:
            notice = (f"{tag} is not a stable release, so its image is built and tried and "
                      "nothing is pushed. Only stable releases become images.")
        publish = False
    return {"tag": tag, "version": tag[1:], "latest": "true" if tag == latest else "false",
            "publish": "true" if publish else "false", "notice": notice}


def parse_ping(output):
    """``(min, avg)`` in ms from busybox ping's summary, or ``None`` when nothing came back."""
    found = re.search(r"min/avg/max = ([\d.]+)/([\d.]+)/([\d.]+) ms", output)
    return (float(found.group(1)), float(found.group(2))) if found else None


def judge_version(output, tag):
    base = tag[1:].split("-")[0]
    said = output.strip()
    if said != f"Bean Network Tester {base}":
        return [f"--version said {said!r}, and the release is {base}"]
    return []


def judge_help(code, output):
    if code != 0 or "--latency" not in output:
        return [f"with no arguments the image answered {code} and printed no help "
                f"({output.strip()[:120]!r})"]
    return []


def judge_doctor(code_without, out_without, code_with, out_with):
    failures = []
    if code_without != 1 or not re.search(r"^FAIL\s+privileges", out_without, re.M):
        failures.append(f"--doctor without the capabilities answered {code_without} and "
                        "no FAIL privileges row")
    if code_with != 0 or not re.search(r"^OK\s+privileges", out_with, re.M):
        failures.append(f"--doctor with {', '.join(CAPTURE_CAPS)} answered {code_with} and "
                        "no OK privileges row")
    return failures


def judge_sidecar(before, during, other, after):
    """Ping summaries ``(min, avg)`` to the impaired address and to another one."""
    failures = []
    for name, ping in (("before", before), ("during", during), ("to the other address", other),
                       ("after the stop", after)):
        if ping is None:
            failures.append(f"no ping answer {name}")
    if failures:
        return failures
    if before[1] >= NORMAL_MS:
        failures.append(f"the network is slow before anything ran ({before[1]} ms)")
    if during[0] < DELAYED_MIN_MS:
        failures.append(f"the sidecar added no latency: fastest ping {during[0]} ms, "
                        f"expected at least {DELAYED_MIN_MS:.0f}")
    if other[1] >= NORMAL_MS:
        failures.append(f"an address outside --dst-ip was slowed too ({other[1]} ms)")
    if after[1] >= NORMAL_MS:
        failures.append(f"traffic is still slow after docker stop ({after[1]} ms)")
    return failures


def judge_stop(code, seconds):
    if code != STOP_EXIT or seconds >= STOP_WITHIN_S:
        return [f"docker stop ended the image with {code} after {seconds:.1f} s, not a clean "
                f"stop ({STOP_EXIT}) within {STOP_WITHIN_S} s"]
    return []


def judge_target(baseline_s, during_s, ping_during):
    """``--target`` in another container: its HTTP is slowed, the kernel's ping is not."""
    failures = []
    if during_s - baseline_s < TARGET_ADDED_S:
        failures.append(f"--target with --pid container: added {during_s - baseline_s:.2f} s "
                        f"to {GETS} requests, expected at least {TARGET_ADDED_S:.1f}")
    if ping_during is None or ping_during[1] >= NORMAL_MS:
        failures.append(f"ping, which no program answers, was slowed by --target ({ping_during})")
    return failures


def judge_host(target_gets, control_gets):
    """Seconds per request to the targeted host program and to one that is not targeted."""
    failures = []
    if not target_gets or min(target_gets) < HOST_GET_MIN_S:
        failures.append(f"a program on the host was not slowed: {target_gets}, expected each "
                        f"at least {HOST_GET_MIN_S:.2f} s")
    if not control_gets or statistics.median(control_gets) >= NORMAL_MS / 1000:
        failures.append(f"a program that is not the target was slowed: {control_gets}")
    return failures


# --- running it -----------------------------------------------------------------------

NET, APP, PEER, SIDE = "bnt-try", "bnt-try-app", "bnt-try-peer", "bnt-try-side"


def docker(*args, timeout=120):
    done = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    return done.returncode, done.stdout + done.stderr


def caps(extra=()):
    out = []
    for cap in CAPTURE_CAPS:
        out += ["--cap-add", cap]
    return out + list(extra)


def ping(address):
    return parse_ping(docker("exec", APP, "ping", "-c", "5", "-W", "3", address)[1])


def timed_gets(address):
    script = f"for i in $(seq {GETS}); do wget -q -O /dev/null http://{address}/; done"
    start = time.monotonic()
    docker("exec", APP, "sh", "-c", script)
    return time.monotonic() - start


def targeting_line():
    """What the sidecar said about its target: the line that explains a failed --target."""
    lines = [line for line in docker("logs", SIDE)[1].splitlines() if "Targeting" in line]
    return lines[0] if lines else "(the sidecar printed no Targeting line)"


def stop(name):
    start = time.monotonic()
    docker("stop", "-t", "15", name)
    seconds = time.monotonic() - start
    code = docker("inspect", "-f", "{{.State.ExitCode}}", name)[1].strip()
    return int(code) if code.lstrip("-").isdigit() else None, seconds


def local_gets(port):
    # No proxy: a runner's proxy settings must not carry a request meant for 127.0.0.1.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    out = []
    for _ in range(GETS):
        start = time.monotonic()
        with opener.open(f"http://127.0.0.1:{port}/", timeout=10) as reply:
            reply.read()
        out.append(round(time.monotonic() - start, 3))
    return out


def try_containers(image):
    failures = []
    docker("network", "create", NET)
    docker("run", "-d", "--name", PEER, "--network", NET, HELPER)
    docker("run", "-d", "--name", APP, "--network", NET, HELPER, "sleep", "600")
    peer = docker("inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                  PEER)[1].strip()
    gateway = docker("network", "inspect", NET, "-f",
                     "{{(index .IPAM.Config 0).Gateway}}")[1].strip()
    if not peer or not gateway:
        return [f"the helper containers did not come up (peer {peer!r}, gateway {gateway!r})"]
    before = ping(peer)
    docker("run", "-d", "--name", SIDE, f"--network=container:{APP}", *caps(), image,
           "--latency", str(LATENCY_MS), "--dst-ip", peer, "--duration", "120")
    time.sleep(4)
    during, other = ping(peer), ping(gateway)
    code, seconds = stop(SIDE)
    after = ping(peer)
    print(f"sidecar: before {before}, during {during}, other {other}, after {after}, "
          f"stop {code} in {seconds:.1f} s")
    failures += judge_sidecar(before, during, other, after) + judge_stop(code, seconds)
    docker("rm", "-f", SIDE)

    baseline = timed_gets(peer)
    docker("run", "-d", "--name", SIDE, f"--network=container:{PEER}", f"--pid=container:{PEER}",
           *caps(), image, "--target", HELPER_PROGRAM, "--latency", str(LATENCY_MS),
           "--duration", "120")
    time.sleep(5)
    during_s, ping_during = timed_gets(peer), ping(peer)
    print(f"--target {HELPER_PROGRAM}: {GETS} requests {baseline:.2f} s -> {during_s:.2f} s, "
          f"ping {ping_during}")
    print(targeting_line())
    failures += judge_target(baseline, during_s, ping_during)
    stop(SIDE)
    return failures


def try_host(image, workdir):
    """A program on the runner itself, served on 127.0.0.1 only."""
    probe = os.path.join(workdir, "beanprobe")
    shutil.copy(os.path.realpath(sys.executable), probe)     # keeps the executable bit
    servers = [subprocess.Popen([probe, "-m", "http.server", "18099", "--bind", "127.0.0.1"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
               subprocess.Popen([sys.executable, "-m", "http.server", "18098", "--bind",
                                 "127.0.0.1"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    try:
        time.sleep(2)
        docker("run", "-d", "--name", SIDE, "--network=host", "--pid=host",
               *caps(HOST_EXTRA), image, "--target", "beanprobe", "--dst-ip", "127.0.0.1",
               "--latency", str(LATENCY_MS), "--duration", "120")
        time.sleep(5)
        target, control = local_gets(18099), local_gets(18098)
        print(f"host program: target {target}, control {control}")
        print(targeting_line())
        stop(SIDE)
        return judge_host(target, control)
    finally:
        for server in servers:
            server.terminate()
            server.wait(timeout=10)


def try_image(image, tag):
    failures = []
    code, out = docker("run", "--rm", "--network", "none", image, "--version")
    print(out.strip())
    failures += judge_version(out, tag)
    code, out = docker("run", "--rm", "--network", "none", image)
    failures += judge_help(code, out)
    without = docker("run", "--rm", "--network", "none", image, "--doctor")
    with_caps = docker("run", "--rm", "--network", "none", *caps(), image, "--doctor")
    print(with_caps[1].strip())
    failures += judge_doctor(without[0], without[1], with_caps[0], with_caps[1])
    workdir = tempfile.mkdtemp()
    try:
        failures += try_containers(image)
        docker("rm", "-f", SIDE)
        failures += try_host(image, workdir)
    finally:
        for name in (SIDE, APP, PEER):
            docker("rm", "-f", name)
        docker("network", "rm", NET)
        shutil.rmtree(workdir, ignore_errors=True)
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    which = sub.add_parser("decide")
    for name in ("event", "tag", "latest", "draft", "prerelease"):
        which.add_argument(f"--{name}", required=True)
    tried = sub.add_parser("try")
    tried.add_argument("image")
    tried.add_argument("tag")
    args = parser.parse_args(argv)
    if args.command == "decide":
        try:
            outputs = decide(args.event, args.tag, args.latest, args.draft, args.prerelease)
        except ValueError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 1
        if outputs["notice"]:
            print(f"::notice::{outputs['notice']}", file=sys.stderr)
        for key in ("tag", "version", "latest", "publish"):
            print(f"{key}={outputs[key]}")
        return 0
    failures = try_image(args.image, args.tag)
    for failure in failures:
        print(f"::error::{failure}", file=sys.stderr)
    print("the image did everything the README says it does" if not failures
          else f"{len(failures)} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
