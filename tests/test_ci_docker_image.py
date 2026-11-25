"""``tools/ci_docker_image.py`` and the files it works with: only a stable release
is pushed, every judge passes what a good image measured and names each way a bad
one goes wrong (a try-out that cannot fail proves nothing), and the Dockerfile and
the workflow agree with the package they are made of."""
import glob
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


def _decide(event="release", tag="v1.1.0", draft="false", prerelease="false"):
    return image.decide(event, tag, draft, prerelease)


def _refused(**kwargs):
    try:
        _decide(**kwargs)
    except ValueError as exc:
        return str(exc)
    return None


def test_only_a_stable_published_release_is_pushed():
    stable = _decide()
    check("a stable release is pushed", stable["publish"] == "true", f"({stable})")
    check("its version has no v", stable["version"] == "1.1.0")
    older = _decide(event="workflow_dispatch", tag="v1.0.0")
    check("an older stable release run by hand is pushed", older["publish"] == "true")

    candidate = _decide(tag="v1.1.0-rc.1")
    check("a release candidate is not pushed", candidate["publish"] == "false", f"({candidate})")
    check("and the run says why", "only stable releases" in candidate["notice"].lower())
    marked = _decide(tag="v1.1.0", prerelease="true")
    check("a release marked as a pre-release is not pushed", marked["publish"] == "false")
    pull = _decide(event="pull_request", tag="v1.1.0-rc.1")
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
        (image.judge_target(None, 2.2, normal), "request to the target failed"),
        (image.judge_target(0.3, None, normal), "request to the target failed"),
        (image.judge_host([0.01] * 5, [0.01] * 5), "was not slowed"),
        (image.judge_host([0.3] * 5, [0.3] * 5), "not the target was slowed"),
        (image.judge_host([], [0.01] * 5), "was not slowed"),
        (image.judge_host(None, [0.01] * 5), "on the host failed"),
        (image.judge_host([0.3] * 5, None), "on the host failed"),
    )
    for failures, word in cases:
        check(f"named: {word}", any(word in failure for failure in failures), f"({failures})")


def test_a_failed_request_is_no_measurement(monkeypatch):
    """A request that was refused or timed out took time as well. Counted, a slow
    failure would pass for a slowed request, and a fast one before the session would
    lower the baseline."""
    calls = []

    def answered(code):
        def fake(*args, **_):
            calls.append(args)
            return code, ""
        return fake

    monkeypatch.setattr(image, "docker", answered(1))
    check("a failed request gives no time", image.timed_gets("10.0.0.2") is None)
    script = calls[-1][-1]
    check("the loop stops at the first failure", "|| exit 1" in script, f"({script})")
    monkeypatch.setattr(image, "docker", answered(0))
    seconds = image.timed_gets("10.0.0.2")
    check("a request that worked is timed", isinstance(seconds, float) and seconds >= 0,
          f"({seconds})")


def _job(text, name):
    """The lines of one job of a workflow, from its key to the next job's."""
    found = re.search(rf"^  {name}:\n(.*?)(?=^  [\w-]+:\n|\Z)", text, re.M | re.S)
    return found.group(1) if found else ""


# The two jobs that write to the registry: publish behind decide's yes, and latest
# behind publish.
PUSHERS = ("publish", "latest")


def _push_outside_publish(text):
    """Jobs other than the two pushers that push, log in or attest: each would publish
    an image without the stable-only answer guarding it."""
    jobs = re.findall(r"^  ([\w-]+):\n", text.split("\njobs:\n", 1)[-1], re.M)
    return [name for name in jobs if name not in PUSHERS
            and re.search(r"docker push|docker login|attest-build-provenance", _job(text, name))]


def test_only_the_guarded_job_can_push():
    text = _read(WORKFLOW)
    check("the reader finds the jobs", len(re.findall(r"^  [\w-]+:\n", text, re.M)) >= 4)
    check("nothing but publish and latest pushes", _push_outside_publish(text) == [],
          f"({_push_outside_publish(text)})")
    publish = _job(text, "publish")
    check("publish runs only on decide's yes",
          "if: needs.which.outputs.publish == 'true'" in publish, f"({publish[:200]})")
    check("publish waits for the try-out", re.search(r"needs: \[which, image\]", publish))
    check("publish pushes", "docker push" in publish)
    check("publish leaves latest to its own job", ":latest" not in publish)
    canary = text.replace("      - name: keep the image that was tried",
                          "      - name: early\n        run: docker push x\n"
                          "      - name: keep the image that was tried")
    check("canary: a push in the try-out job is caught", _push_outside_publish(canary) == ["image"])


def _latest_problems(job):
    """What lets an older run, or a copy with another digest, end up as ``latest``."""
    problems = []
    if not re.search(r"^    needs: \[which, publish\]$", job, re.M):
        problems.append("it does not wait for publish, so it is not behind decide's yes")
    if re.search(r"^    if:", job, re.M):
        problems.append("a job-level if can run it when publish was skipped")
    if not re.search(r"^      group: image-latest$\n^      cancel-in-progress: false$", job, re.M):
        problems.append("it is not one run at a time across all tags")
    if 'releases/latest"' not in job:
        problems.append("it does not read the newest release when it runs")
    if "imagetools create --prefer-index=false" not in job:
        problems.append("the copy gets a digest of its own, without the attestation")
    if 'test "$moved" = "$digest"' not in job:
        problems.append("nothing checks that latest has the version's digest")
    return problems


def test_latest_follows_the_newest_release_one_run_at_a_time():
    """Two releases published close together run at the same time. ``latest`` read at
    the start of each run would let the older one, finishing last, take it back, so
    the job reads the newest release inside a group that holds one run at a time, and
    copies that release's image under its digest (the one its attestation names)."""
    job = _job(_read(WORKFLOW), "latest")
    check("the workflow has a latest job", job != "")
    check("it moves latest safely", _latest_problems(job) == [], f"({_latest_problems(job)})")
    canaries = (
        (job.replace("--prefer-index=false ", ""), "digest of its own"),
        (job.replace("group: image-latest", "group: image-${{ github.ref }}"), "one run at a time"),
        (job.replace("needs: [which, publish]", "needs: [which, image]"), "behind decide's yes"),
    )
    for broken, named in canaries:
        check(f"canary: {named}", any(named in p for p in _latest_problems(broken)))


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


def _image_name():
    name = re.search(r"^  IMAGE: (\S+)$", _read(WORKFLOW), re.M).group(1)
    check("the workflow names its image", name == "ghcr.io/donislawdev/beannetworktester",
          f"({name})")
    return name


def _docs():
    """Every page that tells people how to run the image: the README in each language
    and the site's Docker guide in each language, as ``(path, text)``."""
    paths = sorted(glob.glob(os.path.join(ROOT, "README*.md")))
    paths += sorted(glob.glob(os.path.join(ROOT, "site", "pages", "docker", "*.html")))
    docs = [(os.path.relpath(path, ROOT).replace(os.sep, "/"), _read(path)) for path in paths]
    # A glob that finds nothing passes every check below.
    check("every language of both is found", len(docs) >= 30, f"({len(docs)})")
    return docs


def test_the_readme_and_the_site_print_what_the_try_out_runs():
    """The options people copy are the ones CI proves on every release, and the image
    they pull is the one the workflow pushes - in every language."""
    name = _image_name()
    for doc, text in _docs():
        missing = _docs_missing(text, name)
        check(f"{doc} prints every option the try-out uses", not missing, f"(missing {missing})")
    canary = _read(os.path.join(ROOT, "README.md")).replace("--cap-add SYS_PTRACE", "--cap-add X")
    check("canary: a dropped option is caught", "--cap-add SYS_PTRACE" in _docs_missing(canary, name))


def test_the_documented_image_check_asks_for_what_the_workflow_attests():
    """``attest-build-provenance`` makes SLSA build provenance, so that is the predicate
    each page's command has to ask for, of the image the workflow pushes."""
    workflow = _read(WORKFLOW)
    check("the workflow attests build provenance", "actions/attest-build-provenance@" in workflow)
    name = _image_name()
    for doc, text in _docs():
        commands = [line for line in text.splitlines() if "gh attestation verify oci://" in line]
        check(f"{doc} shows how to check an image", len(commands) == 1, f"({commands})")
        for command in commands:
            for part in (f"oci://{name}:", "--owner donislawdev",
                         "--predicate-type https://slsa.dev/provenance/v1"):
                check(f"{doc}: it names {part}", part in command, f"({command})")


FLAG = r"(?<![\w-])--[a-z][a-z0-9-]*"


def _not_the_programs(text, name, known):
    """Flags that reach the program but are not its own: whatever follows the image in
    a ``docker run`` line, and the arguments of a Compose ``command:``. A Docker option
    written after the image goes to the program, which refuses it."""
    wrong = []
    for line in text.splitlines():
        at = line.find(f"{name}:")
        if at >= 0 and "oci://" not in line:
            wrong += [flag for flag in re.findall(FLAG, line[at:]) if flag not in known]
        if re.search(r"command:\s*\[", line):
            wrong += [flag for flag in re.findall(r'"(--[a-z][a-z0-9-]*)"', line)
                      if flag not in known]
    return wrong


def test_what_follows_the_image_is_the_programs_own():
    """The pages name Docker's options too (and the site's flag test lets the Docker
    page name them), so this holds the side of the image each one is on."""
    from beantester import build_arg_parser
    known = set(re.findall(FLAG, build_arg_parser().format_help()))
    check("the help lists the command line's flags", len(known) >= 40, f"({len(known)})")
    name = _image_name()
    seen = 0
    for doc, text in _docs():
        seen += sum(1 for line in text.splitlines() if f"{name}:" in line or "command: [" in line)
        wrong = _not_the_programs(text, name, known)
        check(f"{doc}: only the program's flags follow the image", not wrong, f"({wrong})")
    check("the pages run the image at all", seen >= 60, f"({seen})")
    readme = _read(os.path.join(ROOT, "README.md"))
    after = readme.replace(f"{name}:1.1.0 --dst-ip", f"{name}:1.1.0 --cap-add BPF --dst-ip")
    check("canary: a Docker option after the image is caught",
          _not_the_programs(after, name, known) == ["--cap-add"])
    compose = readme.replace('command: ["--latency"', 'command: ["--privileged", "--latency"')
    check("canary: a Docker option in a Compose command is caught",
          _not_the_programs(compose, name, known) == ["--privileged"])


def test_a_change_to_the_image_is_tried_before_it_merges():
    text = _read(WORKFLOW)
    paths = re.search(r"pull_request:\n\s+paths:\n((?:\s+- .*\n)+)", text)
    listed = re.findall(r'- "([^"]+)"', paths.group(1)) if paths else []
    for needed in (".github/docker/**", ".github/workflows/docker.yml", "tools/ci_docker_image.py"):
        check(f"a pull request touching {needed} tries the image", needed in listed, f"({listed})")
