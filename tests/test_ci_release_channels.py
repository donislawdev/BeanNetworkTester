"""The channels fed from a published release: the stable-only rule they share
(tools/ci_release_channel.py) and the guards of pypi.yml, plus the judges of the
package try-out (tools/ci_test_helpers.py).

The image channel's own guards live in tests/test_ci_docker_image.py.
"""
import ast
import os
import re
import socket
import sys
from pathlib import Path

import pytest

from fakes import ROOT, check

sys.path.insert(0, os.path.join(ROOT, "tools"))
import ci_release_channel as channel  # noqa: E402
import ci_test_helpers as try_package  # noqa: E402

WORKFLOWS = Path(ROOT) / ".github" / "workflows"
HELPER = Path(ROOT) / "python" / "beannetworktester"


# --- one rule, every channel ---------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(channel.CHANNELS))
def test_only_a_stable_release_is_published_on_every_channel(name):
    def ask(event, tag, prerelease="false", draft="false"):
        return channel.decide(event, tag, draft, prerelease, name)

    check("a stable release publishes", ask("release", "v1.1.0")["publish"] == "true")
    check("by hand too", ask("workflow_dispatch", "v1.1.0")["publish"] == "true")
    check("a pull request never", ask("pull_request", "v1.1.0")["publish"] == "false")
    rc = ask("release", "v1.1.0-rc.1", prerelease="true")
    check("a candidate is tried, not published, and says so",
          rc["publish"] == "false" and "not a stable release" in rc["notice"], f"({rc})")
    check("a stable-looking tag marked pre-release is held too",
          ask("release", "v1.1.0", prerelease="true")["publish"] == "false")
    for bad in (("workflow_dispatch", "v1.1.0-rc.1"), ("release", "1.1.0"), ("push", "v1.1.0")):
        with pytest.raises(ValueError):
            ask(*bad)
    with pytest.raises(ValueError, match="not published yet"):
        ask("release", "v1.1.0", draft="true")


def test_each_channel_says_what_it_holds_back():
    notices = {name: channel.decide("release", "v1.1.0-rc.1", "false", "true", name)["notice"]
               for name in channel.CHANNELS}
    check("three different sentences", len(set(notices.values())) == 3, f"({notices})")
    check("PyPI's names PyPI", "PyPI" in notices["pypi"] and "npm" in notices["npm"])
    with pytest.raises(ValueError, match="not a channel"):
        channel.decide("release", "v1.1.0", "false", "false", "ftp")


def test_the_cli_writes_only_outputs_to_stdout(capsys):
    code = channel.main(["decide", "--channel", "pypi", "--event", "release", "--tag",
                         "v1.1.0-rc.1", "--draft", "false", "--prerelease", "true"])
    out, err = capsys.readouterr()
    check("exit 0", code == 0)
    # The three the workflow reads, so an empty stdout cannot pass as "only outputs".
    check("the workflow's three outputs, and a release candidate is not published",
          out.splitlines() == ["tag=v1.1.0-rc.1", "version=1.1.0-rc.1", "publish=false"],
          f"({out!r})")
    check("stdout is key=value lines for $GITHUB_OUTPUT",
          all(re.fullmatch(r"\w+=\S*", line) for line in out.splitlines()), f"({out!r})")
    check("the notice goes to stderr", "::notice::" in err and "::notice::" not in out)


# --- pypi.yml ----------------------------------------------------------------------- #


def _job(text, name):
    found = re.search(rf"^  {name}:\n(.*?)(?=^  [\w-]+:\n|\Z)", text, re.M | re.S)
    return found.group(1) if found else ""


DISPATCH_REF = "ref: ${{ github.event_name == 'workflow_dispatch' && needs.which.outputs.tag || '' }}"


def _built_from_the_branch(text):
    """Jobs that check the repository out after ``which`` without the tag a run by hand
    publishes: they would pack the branch it was started from under the tag's version.
    A release event checks the tag out anyway, and a pull request its own tree."""
    jobs = re.findall(r"^  ([\w-]+):\n", text.split("\njobs:\n", 1)[-1], re.M)
    return [f"{name} builds the branch a run by hand started from, not its tag"
            for name in jobs if name != "which" and "actions/checkout@" in _job(text, name)
            and DISPATCH_REF not in _job(text, name)]


def _pypi_problems(text):
    """What would let something reach PyPI without the stable-only answer, the try-out,
    the owner's approval, or with a stored token."""
    problems = _built_from_the_branch(text)
    jobs = re.findall(r"^  ([\w-]+):\n", text.split("\njobs:\n", 1)[-1], re.M)
    for name in jobs:
        if name != "publish" and re.search(r"id-token: write|pypi-publish", _job(text, name)):
            problems.append(f"{name} can publish")
    publish = _job(text, "publish")
    if "if: needs.which.outputs.publish == 'true'" not in publish:
        problems.append("publish does not wait for decide's yes")
    if not re.search(r"^    needs: \[which, try\]$", publish, re.M):
        problems.append("publish does not wait for the try-out")
    if not re.search(r"^    environment:\n      name: pypi$", publish, re.M):
        problems.append("publish does not wait in the pypi environment for the owner")
    if "pypa/gh-action-pypi-publish@" not in publish:
        problems.append("publish does not publish")
    if "secrets." in text:
        problems.append("a stored secret is used: trusted publishing needs none")
    if "ci_release_channel.py decide --channel pypi" not in _job(text, "which"):
        problems.append("which does not ask the shared rule for the pypi channel")
    return problems


def test_only_the_guarded_job_publishes_to_pypi():
    text = (WORKFLOWS / "pypi.yml").read_text(encoding="utf-8")
    check("the reader finds the jobs", len(re.findall(r"^  [\w-]+:\n", text, re.M)) >= 4)
    check("no problem", _pypi_problems(text) == [], f"({_pypi_problems(text)})")
    canaries = {
        "a token in the try-out": text.replace("    timeout-minutes: 25\n",
                                               "    timeout-minutes: 25\n    permissions:\n"
                                               "      id-token: write\n"),
        "no approval": text.replace("      name: pypi\n", "      name: release\n"),
        "a secret": text + "\n# ${{ secrets.PYPI_TOKEN }}\n",
        "publish before the try-out": text.replace("needs: [which, try]", "needs: [which, wheels]"),
        "a run by hand that builds the branch": text.replace("          " + DISPATCH_REF + "\n",
                                                             "", 1),
    }
    for what, changed in canaries.items():
        check(f"canary: {what} is caught", _pypi_problems(changed) != [], f"({what})")


def test_the_try_out_covers_both_systems_and_the_oldest_python():
    text = (WORKFLOWS / "pypi.yml").read_text(encoding="utf-8")
    trying = _job(text, "try")
    check("Windows and Linux", "os: [windows-latest, ubuntu-24.04]" in trying)
    oldest = re.search(r'requires-python = ">=(\d+\.\d+)"',
                       (HELPER / "pyproject.toml").read_text(encoding="utf-8")).group(1)
    check("the oldest declared Python is tried", f'"{oldest}"' in trying, f"({oldest})")
    check("the README's install", "pip install --pre --no-index --find-links wheels "
          "beannetworktester" in trying)
    check("the session is tried", "ci_test_helpers.py session" in trying)


# --- npm.yml --------------------------------------------------------------------------- #


def _publishes(body):
    """A plain `npm publish` command (not "npm publishes" in a comment)."""
    return re.search(r"npm publish\s", body) is not None


def _npm_problems(text):
    """What would let a package reach npm without the stable-only answer, the try-out or
    the owner's approval, or with a token anywhere but the first release's staging."""
    problems = _built_from_the_branch(text)
    jobs = re.findall(r"^  ([\w-]+):\n", text.split("\njobs:\n", 1)[-1], re.M)
    for name in jobs:
        body = _job(text, name)
        real = [line for line in body.splitlines()
                if "npm stage publish" in line and "--dry-run" not in line]
        if name != "stage" and (real or "id-token: write" in body or _publishes(body)):
            problems.append(f"{name} can publish")
        if name != "stage" and "secrets." in body:
            problems.append(f"{name} uses a secret")
    stage = _job(text, "stage")
    if "if: needs.which.outputs.publish == 'true'" not in stage:
        problems.append("stage does not wait for decide's yes")
    if not re.search(r"^    needs: \[which, try\]$", stage, re.M):
        problems.append("stage does not wait for the try-out")
    if _publishes(stage) or "npm stage publish" not in stage:
        problems.append("stage publishes instead of staging for approval")
    if "--provenance" not in stage:
        problems.append("stage publishes no provenance")
    if set(re.findall(r"secrets\.(\w+)", text)) - {"NPM_TOKEN"}:
        problems.append("a secret other than the first release's NPM_TOKEN")
    if "if: needs.which.outputs.publish != 'true'" not in _job(text, "rehearse"):
        problems.append("the rehearsal does not run when nothing is published")
    # npm refuses to stage over a published version, dry run or not: a rehearsal that did
    # not skip one failed every pull request after the first stable release (#352).
    for name in ("rehearse", "stage"):
        if 'npm view "$name@$VERSION" version' not in _job(text, name):
            problems.append(f"{name} does not skip a version already on npm")
    if "ci_release_channel.py decide --channel npm" not in _job(text, "which"):
        problems.append("which does not ask the shared rule for the npm channel")
    return problems


def test_only_the_guarded_job_stages_on_npm():
    text = (WORKFLOWS / "npm.yml").read_text(encoding="utf-8")
    check("no problem", _npm_problems(text) == [], f"({_npm_problems(text)})")
    canaries = {
        "a real stage in the rehearsal": text.replace(
            '--dry-run --access public --tag "$tag"', '--access public --tag "$tag"'),
        "publish without approval": text.replace(
            'npm stage publish "./tarballs/$tarball" --access public --tag "$tag" --provenance',
            'npm publish "./tarballs/$tarball" --access public --tag "$tag" --provenance'),
        "staging before the try-out": text.replace("    needs: [which, try]\n    if: needs.which"
                                                   ".outputs.publish == 'true'",
                                                   "    needs: [which, packages]\n    if: needs."
                                                   "which.outputs.publish == 'true'"),
        "another secret": text + "\n# ${{ secrets.GH_PAT }}\n",
        "a run by hand that builds the branch": text.replace("          " + DISPATCH_REF + "\n",
                                                             "", 1),
        # The rehearsal comes first in the file, so the first match is its skip.
        "a rehearsal that stages over a published version": text.replace(
            'npm view "$name@$VERSION" version', 'npm view "$name" version', 1),
    }
    for what, changed in canaries.items():
        check(f"canary: {what} is caught", changed != text and _npm_problems(changed) != [],
              f"({what})")


def test_the_npm_try_out_covers_every_system_the_package_carries():
    text = (WORKFLOWS / "npm.yml").read_text(encoding="utf-8")
    tried = set(re.findall(r"system: ([\w-]+)", _job(text, "try")))
    program = (Path(ROOT) / "npm" / "beannetworktester" / "lib" / "program.js").read_text(
        encoding="utf-8")
    carried = set(re.findall(r"'([\w-]+)': '@beannetworktester/", program))
    # Two empty readings would agree with each other and prove nothing.
    check("the readers find systems on both sides", tried and carried, f"({tried} / {carried})")
    check("every system is tried on its own runner", tried == carried, f"({tried} / {carried})")
    engines = re.search(r'"node": ">=(\d+)"', (Path(ROOT) / "npm" / "beannetworktester" /
                                               "package.json").read_text(encoding="utf-8"))
    check("the oldest declared Node is tried",
          f'node-version: "{engines.group(1)}"' in _job(text, "try"), f"({engines.group(1)})")


# --- the try-out's judges ------------------------------------------------------------ #


GOOD = {"base_aim": 4, "slow_aim": 404, "base_control": 1, "slow_control": 11, "after_aim": 1,
        "stop_reason": "stdin", "in_scope": 30}


def test_the_session_judge_passes_a_good_run_and_names_each_fault():
    check("a good run passes", try_package.judge_session(GOOD) == [])
    faults = {"not slowed": {"slow_aim": 90}, "control slowed": {"slow_control": 300},
              "still slow after": {"after_aim": 400}, "killed": {"stop_reason": "terminated"},
              "nothing in scope": {"in_scope": 0}}
    for what, change in faults.items():
        check(f"canary: {what}", len(try_package.judge_session({**GOOD, **change})) == 1,
              f"({try_package.judge_session({**GOOD, **change})})")
    check("no numbers at all fail", len(try_package.judge_session({})) >= 3)
    page = {"base_page": 60, "slow_page": 410, "aim_families": ["ipv4", "ipv6"],
            "page_families": ["ipv6"]}
    check("a page slowed passes", try_package.judge_page(page) == [])
    check("canary: a page not slowed",
          len(try_package.judge_page({**page, "slow_page": 70})) == 1)
    # Chromium takes ::1 for localhost on Linux; a run whose Chromium never reached the aim
    # over IPv6 did not try that, and passed on helpers that aimed at 127.0.0.1 alone. Only
    # Chromium's requests count: urllib and Node may take ::1 while the page took 127.0.0.1.
    for families in (["ipv4"], []):
        failures = try_package.judge_page({**page, "page_families": families})
        check(f"canary: Chromium over {families} only", len(failures) == 1, f"({failures})")
        check("the failure says what to check, in words",
              failures and "listens on ::" in failures[0] and "[" not in failures[0],
              f"({failures})")
    check("canary: no families recorded", len(try_package.judge_page(
        {"base_page": 60, "slow_page": 410})) == 1)


def test_the_try_servers_listen_on_both_families_as_localhost():
    url, server = try_package._serve()
    try:
        check("the aim is localhost, as in the READMEs", url.startswith("http://localhost:"), url)
        port = int(url.rsplit(":", 1)[1])
        # Chromium over IPv4, another client over IPv6: the case the page judge must not pass.
        for family, address, agent in ((socket.AF_INET, "127.0.0.1", b"HeadlessChrome/159.0"),
                                       (socket.AF_INET6, "::1", b"Python-urllib/3.15")):
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((address, port))
                s.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\nUser-Agent: " + agent
                          + b"\r\n\r\n")
                reply = b""
                while chunk := s.recv(4096):
                    reply += chunk
            check(f"answers over {address}", reply.startswith(b"HTTP/1.0 200"), repr(reply[:40]))
        check("each family noted", server.families == {"ipv4", "ipv6"}, f"({server.families})")
        check("Chromium's noted on their own", server.page_families == {"ipv4"},
              f"({server.page_families})")
        check("canary: so the page judge fails it", len(try_package.judge_page(
            {"base_page": 60, "slow_page": 410, "aim_families": sorted(server.families),
             "page_families": sorted(server.page_families)})) == 1)
    finally:
        server.shutdown()
        server.server_close()


def test_the_install_judge_wants_the_install_and_the_releases_program():
    site = "/v/lib/python3.15/site-packages/beannetworktester/__init__.py"
    check("installed and the right version",
          try_package.judge_install(site, "Bean Network Tester 1.1.0\n", "1.1.0", False) == [])
    check("a candidate says the version it leads to",
          try_package.judge_install(site, "Bean Network Tester 1.1.0", "1.1.0-rc.1", False) == [])
    check("canary: imported from the checkout",
          try_package.judge_install("/repo/python/beannetworktester/src/x.py",
                                    "Bean Network Tester 1.1.0", "1.1.0", False))
    check("canary: another version",
          try_package.judge_install(site, "Bean Network Tester 1.0.0", "1.1.0", False))
    pin = "ab" * 32
    check("signed by us", try_package.judge_signature("Valid", pin, pin) == [])
    check("canary: unsigned", try_package.judge_signature("NotSigned", pin, pin))
    check("canary: someone else's certificate", try_package.judge_signature("Valid", "cd" * 32, pin))


# --- the helper keeps to the oldest Python it declares ------------------------------ #


def test_the_helper_parses_as_python_3_10():
    oldest = tuple(int(n) for n in re.search(
        r'requires-python = ">=(\d+)\.(\d+)"',
        (HELPER / "pyproject.toml").read_text(encoding="utf-8")).groups())
    files = sorted((HELPER / "src" / "beannetworktester").glob("*.py"))
    check("the package has its modules", len(files) >= 5, f"({len(files)})")
    for path in files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=oldest)
    with pytest.raises(SyntaxError):
        ast.parse("match x:\n    case 1:\n        pass\n", feature_version=(3, 9))
