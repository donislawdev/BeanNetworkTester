"""The npm test helper (npm/beannetworktester): its own node tests, run here so CI runs them
on Windows and Linux, and its README and setting names held to the program's parser."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from beantester.cli import build_arg_parser
from fakes import ROOT, check

HELPER = Path(ROOT) / "npm" / "beannetworktester"
LAUNCHER = os.path.join(ROOT, "bean_network_tester.py")
PROGRAM_DESTS = {a.dest for a in build_arg_parser()._actions}


def _snake(name):
    return re.sub(r"[A-Z]", lambda m: "_" + m.group(0).lower(), name)


def test_the_node_tests_pass_on_the_checkouts_program():
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("CI has no node, so the npm helper's tests did not run")
        pytest.skip("no node on this machine")
    env = dict(os.environ, BEANNETWORKTESTER_PROGRAM=LAUNCHER,
               BEANNETWORKTESTER_PYTHON=sys.executable, BEAN_NO_ELEVATE="1")
    done = subprocess.run([node, "--test", "test/"], cwd=str(HELPER), env=env,
                          capture_output=True, text=True, timeout=600)
    check("node --test passed", done.returncode == 0, f"({done.stdout[-1500:]}{done.stderr[-500:]})")
    check("and ran the session test, not skipped it",
          re.search(r"(?:# skip|skipped) 0$", done.stdout, re.M), f"({done.stdout[-400:]})")


def test_the_names_the_helper_reserves_are_the_programs_own():
    source = (HELPER / "lib" / "aim.js").read_text(encoding="utf-8")
    block = re.search(r"const RESERVED = new Set\(\[(.*?)\]\);", source, re.S).group(1)
    names = re.findall(r"'(\w+)'", block)
    check("the set was read", len(names) >= 10, f"({names})")
    missing = [n for n in names if _snake(n) not in PROGRAM_DESTS]
    check("every reserved name is a program option", not missing, f"({missing})")
    check("canary: a made-up name would be caught", _snake("stopOnStdinKlose") not in PROGRAM_DESTS)


def test_every_setting_the_npm_readme_names_is_a_program_flag():
    text = (HELPER / "README.md").read_text(encoding="utf-8")
    named = set(re.findall(r"`(\w+): ", text)) | set(re.findall(r"\b(\w+): \d", text))
    own = {"server", "process", "duration", "simulate", "wait", "startTimeout", "timeout", "name",
           "host", "port"}
    stray = sorted(n for n in named - own if _snake(n) not in PROGRAM_DESTS)
    check("no setting the program does not have", not stray, f"({stray})")
    check("canary: the scan finds the table", {"latency", "flapDown", "rstProb"} <= named,
          f"({sorted(named)})")


def test_the_npm_readme_links_only_to_pages_the_site_has():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import build_site
    registry = build_site.load_registry(ROOT)
    pages = {p["languages"]["en"]["dir_path"].strip("/")
             for p in build_site.load_pages(ROOT, registry) if "en" in p["languages"]}
    linked = re.findall(r"https://beannetworktester\.donislawdev\.com/([\w/-]*)",
                        (HELPER / "README.md").read_text(encoding="utf-8"))
    check("the README links to the site", len(linked) >= 2, f"({linked})")
    check("every link reaches an English page",
          all(path.strip("/") in pages for path in linked), f"({linked})")


def test_the_package_and_the_python_one_carry_the_same_systems():
    program = (HELPER / "lib" / "program.js").read_text(encoding="utf-8")
    systems = set(re.findall(r"'(win32-x64|linux-x64|[a-z0-9]+-[a-z0-9]+)': '@beannetworktester/", program))
    check("Windows x64 and Linux x64", systems == {"win32-x64", "linux-x64"}, f"({systems})")
    python = (Path(ROOT) / "python" / "beannetworktester" / "src" / "beannetworktester" /
              "_program.py").read_text(encoding="utf-8")
    check("the Python package says the same", 'SYSTEMS = ("Windows x64", "Linux x64")' in python)
