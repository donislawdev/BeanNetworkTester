"""``tools/ci_docker_image.py`` and the files it works with: only a stable release
is pushed, every judge passes what a good image measured and names each way a bad
one goes wrong (a try-out that cannot fail proves nothing), and the Dockerfile and
the workflow agree with the package they are made of."""
import os
import re
import sys

from fakes import ROOT, check

sys.path.insert(0, os.path.join(ROOT, "tools"))

import ci_docker_image as image                                # noqa: E402

DOCKERFILE = os.path.join(ROOT, ".github", "docker", "Dockerfile")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "docker.yml")

# busybox ping's last line, as the helper container printed it (2026-11-25).
PING_NORMAL = "round-trip min/avg/max = 0.069/0.688/3.761 ms\n"
PING_DELAYED = "round-trip min/avg/max = 200.622/200.859/201.410 ms\n"
PING_NONE = "5 packets transmitted, 0 packets received, 100% packet loss\n"
DOCTOR_FAIL = ("OK   python             3.15.2\nFAIL privileges         root, but without "
               "CAP_BPF, CAP_PERFMON, CAP_NET_ADMIN and CAP_NET_RAW\n")
DOCTOR_OK = "OK   python             3.15.2\nOK   privileges         root\n"


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _decide(event="release", tag="v1.1.0", latest="v1.1.0", draft="false", prerelease="false"):
    return image.decide(event, tag, latest, draft, prerelease)


def _refused(**kwargs):
    try:
        _decide(**kwargs)
    except ValueError as exc:
        return str(exc)
    return None


def test_only_a_stable_published_release_is_pushed():
    stable = _decide()
    check("a stable release is pushed", stable["publish"] == "true", f"({stable})")
    check("and becomes latest when it is the latest", stable["latest"] == "true")
    check("its version has no v", stable["version"] == "1.1.0")
    older = _decide(event="workflow_dispatch", tag="v1.0.0", latest="v1.1.0")
    check("an older stable release run by hand is pushed", older["publish"] == "true")
    check("and never takes latest", older["latest"] == "false", f"({older})")

    candidate = _decide(tag="v1.1.0-rc.1")
    check("a release candidate is not pushed", candidate["publish"] == "false", f"({candidate})")
    check("and the run says why", "only stable releases" in candidate["notice"].lower())
    marked = _decide(tag="v1.1.0", prerelease="true")
    check("a release marked as a pre-release is not pushed", marked["publish"] == "false")
    pull = _decide(event="pull_request", tag="v1.1.0-rc.1", latest="v1.0.0")
    check("a pull request pushes nothing", pull["publish"] == "false", f"({pull})")
    check("and says nothing about it", pull["notice"] == "")
    pull_stable = _decide(event="pull_request")
    check("not even when it tries a stable release", pull_stable["publish"] == "false")


def test_what_cannot_become_an_image_stops_the_run():
    check("a candidate asked for by hand is refused",
          "stable" in (_refused(event="workflow_dispatch", tag="v1.1.0-rc.1") or ""))
    check("a draft is refused", "not published" in (_refused(draft="true") or ""))
    check("an unknown draft answer is refused", _refused(draft="") is not None)
    for tag in ("1.1.0", "v1.1", "latest", "v1.1.0; rm -rf /", ""):
        check(f"{tag!r} is not a release tag", _refused(tag=tag) is not None)
    check("an event the workflow does not run on", _refused(event="push") is not None)


def test_ping_summaries_are_read_and_a_silent_ping_is_none():
    check("normal", image.parse_ping(PING_NORMAL) == (0.069, 0.688))
    check("delayed", image.parse_ping(PING_DELAYED) == (200.622, 200.859))
    check("no answer", image.parse_ping(PING_NONE) is None)


def test_a_good_image_passes_every_judge():
    normal, delayed = (0.07, 0.6), (200.6, 200.9)
    check("version", image.judge_version("Bean Network Tester 1.1.0\n", "v1.1.0") == [])
    check("a candidate prints its base version",
          image.judge_version("Bean Network Tester 1.1.0\n", "v1.1.0-rc.1") == [])
    check("help", image.judge_help(0, "usage: BeanNetworkTester [options]\n  --latency MS\n") == [])
    check("doctor", image.judge_doctor(1, DOCTOR_FAIL, 0, DOCTOR_OK) == [])
    check("sidecar", image.judge_sidecar(normal, delayed, normal, normal) == [])
    check("stop", image.judge_stop(143, 0.4) == [])
    check("target", image.judge_target(0.3, 2.2, normal) == [])
    check("host", image.judge_host([0.31, 0.26, 0.23, 0.24, 0.21],
                                   [0.014, 0.008, 0.011, 0.012, 0.011]) == [])


def test_every_way_a_bad_image_goes_wrong_is_named():
    normal, delayed = (0.07, 0.6), (200.6, 200.9)
    cases = (
        (image.judge_version("Bean Network Tester 1.0.0\n", "v1.1.0"), "release is 1.1.0"),
        (image.judge_help(1, "The window needs libfontconfig.so.1"), "no help"),
        (image.judge_help(0, ""), "no help"),
        (image.judge_doctor(0, DOCTOR_OK, 0, DOCTOR_OK), "without the capabilities"),
        (image.judge_doctor(1, DOCTOR_FAIL, 1, DOCTOR_FAIL), "with BPF, PERFMON, NET_ADMIN"),
        (image.judge_sidecar(normal, normal, normal, normal), "added no latency"),
        (image.judge_sidecar(normal, delayed, delayed, normal), "outside --dst-ip"),
        (image.judge_sidecar(normal, delayed, normal, delayed), "after docker stop"),
        (image.judge_sidecar(delayed, delayed, normal, normal), "slow before"),
        (image.judge_sidecar(normal, None, normal, normal), "no ping answer during"),
        (image.judge_stop(137, 10.2), "not a clean stop"),
        (image.judge_stop(143, 12.0), "not a clean stop"),
        (image.judge_target(0.3, 0.35, normal), "added 0.05 s"),
        (image.judge_target(0.3, 2.2, delayed), "no program answers"),
        (image.judge_target(0.3, 2.2, None), "no program answers"),
        (image.judge_host([0.01] * 5, [0.01] * 5), "was not slowed"),
        (image.judge_host([0.3] * 5, [0.3] * 5), "not the target was slowed"),
        (image.judge_host([], [0.01] * 5), "was not slowed"),
    )
    for failures, word in cases:
        check(f"named: {word}", any(word in failure for failure in failures), f"({failures})")


def _job(text, name):
    """The lines of one job of a workflow, from its key to the next job's."""
    found = re.search(rf"^  {name}:\n(.*?)(?=^  [\w-]+:\n|\Z)", text, re.M | re.S)
    return found.group(1) if found else ""


def _push_outside_publish(text):
    """Jobs other than ``publish`` that push, log in or attest: each would publish an
    image without the stable-only answer guarding it."""
    jobs = re.findall(r"^  ([\w-]+):\n", text.split("\njobs:\n", 1)[-1], re.M)
    return [name for name in jobs if name != "publish"
            and re.search(r"docker push|docker login|attest-build-provenance", _job(text, name))]


def test_only_the_guarded_job_can_push():
    text = _read(WORKFLOW)
    check("the reader finds the jobs", len(re.findall(r"^  [\w-]+:\n", text, re.M)) >= 3)
    check("nothing but publish pushes", _push_outside_publish(text) == [],
          f"({_push_outside_publish(text)})")
    publish = _job(text, "publish")
    check("publish runs only on decide's yes",
          "if: needs.which.outputs.publish == 'true'" in publish, f"({publish[:200]})")
    check("publish waits for the try-out", re.search(r"needs: \[which, image\]", publish))
    check("publish pushes", "docker push" in publish)
    canary = text.replace("      - name: keep the image that was tried",
                          "      - name: early\n        run: docker push x\n"
                          "      - name: keep the image that was tried")
    check("canary: a push in the try-out job is caught", _push_outside_publish(canary) == ["image"])


def test_the_image_is_the_package_unchanged_on_a_pinned_base():
    text = _read(DOCKERFILE)
    base = re.search(r"^FROM (\S+)", text, re.M)
    check("the Dockerfile has a base", base is not None)
    check("the base is pinned by digest",
          re.fullmatch(r"ubuntu:24\.04@sha256:[0-9a-f]{64}", base.group(1)), f"({base.group(1)})")
    spec = _read(os.path.join(ROOT, "BeanNetworkTester.spec"))
    name = re.search(r'^\s*name="(\w+)",\s*#\s*dist', spec, re.M).group(1)
    check("the image copies the package folder", f"COPY {name} /opt/" in text)
    check("and starts the program in it",
          f'ENTRYPOINT ["/opt/beannetworktester/{name}"]' in text, f"({name})")
    check("with no arguments it prints the help", 'CMD ["--help"]' in text)
    workflow = _read(WORKFLOW)
    check("the workflow unpacks the same folder", f"context/{name}/{name}" in workflow)


def _docs_missing(text, name):
    """What a page telling people how to run the image leaves out of what CI runs."""
    missing = [f"--cap-add {cap}" for cap in image.CAPTURE_CAPS if f"--cap-add {cap}" not in text]
    missing += [f"{a} {b}" for a, b in zip(image.HOST_EXTRA[::2], image.HOST_EXTRA[1::2], strict=True)
                if f"{a} {b}" not in text]
    if f"{name}:" not in text:
        missing.append(name)
    return missing


def test_the_readme_and_the_site_print_what_the_try_out_runs():
    """The options people copy are the ones CI proves on every release, and the image
    they pull is the one the workflow pushes."""
    workflow = _read(WORKFLOW)
    name = re.search(r"^  IMAGE: (\S+)$", workflow, re.M).group(1)
    check("the workflow names its image", name == "ghcr.io/donislawdev/beannetworktester", f"({name})")
    for doc in ("README.md", os.path.join("site", "pages", "docker", "en.html")):
        missing = _docs_missing(_read(os.path.join(ROOT, doc)), name)
        check(f"{doc} prints every option the try-out uses", not missing, f"(missing {missing})")
    canary = _read(os.path.join(ROOT, "README.md")).replace("--cap-add SYS_PTRACE", "--cap-add X")
    check("canary: a dropped option is caught", "--cap-add SYS_PTRACE" in _docs_missing(canary, name))


def test_the_documented_image_check_asks_for_what_the_workflow_attests():
    """``attest-build-provenance`` makes SLSA build provenance, so that is the predicate
    the README's command has to ask for, of the image the workflow pushes."""
    workflow = _read(WORKFLOW)
    check("the workflow attests build provenance", "actions/attest-build-provenance@" in workflow)
    commands = [line for line in _read(os.path.join(ROOT, "README.md")).splitlines()
                if "gh attestation verify oci://" in line]
    check("the README shows how to check an image", len(commands) == 1, f"({commands})")
    for command in commands:
        for part in ("oci://ghcr.io/donislawdev/beannetworktester:", "--owner donislawdev",
                     "--predicate-type https://slsa.dev/provenance/v1"):
            check(f"it names {part}", part in command, f"({command})")


def test_a_change_to_the_image_is_tried_before_it_merges():
    text = _read(WORKFLOW)
    paths = re.search(r"pull_request:\n\s+paths:\n((?:\s+- .*\n)+)", text)
    listed = re.findall(r'- "([^"]+)"', paths.group(1)) if paths else []
    for needed in (".github/docker/**", ".github/workflows/docker.yml", "tools/ci_docker_image.py"):
        check(f"a pull request touching {needed} tries the image", needed in listed, f"({listed})")
