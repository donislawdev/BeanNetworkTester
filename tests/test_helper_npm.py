"""The npm test helper (npm/beannetworktester): its own node tests, run here so CI runs them
on Windows and Linux, and its README and setting names held to the program's parser. Also the
licence of both test packages, this one and the Python one."""
import hashlib
import json
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
    # The files by name: Node 24 takes a folder after --test for a module to load, and fails.
    files = sorted(p.relative_to(HELPER).as_posix() for p in (HELPER / "test").glob("*.test.js"))
    check("there are node tests to run", files, "(none in test/)")
    done = subprocess.run([node, "--test", "--test-reporter=tap", *files], cwd=str(HELPER),
                          env=env, capture_output=True, text=True, timeout=600)
    check("node --test passed", done.returncode == 0, f"({done.stdout[-1500:]}{done.stderr[-500:]})")
    # The tests that need the program run here, where it is; only a test of another
    # system's own files may skip.
    skipped = set(re.findall(r"^\s*ok \d+ - (.+?) # SKIP", done.stdout, re.M))
    other_system = {"a link or a FIFO at the lock path is refused at once"} \
        if sys.platform == "win32" else set()
    check("the tests that need the program ran, not skipped", skipped <= other_system,
          f"({sorted(skipped - other_system)})")
    check("canary: the reader finds a test that passed",
          re.search(r"^\s*ok \d+ - a session waits for the capture", done.stdout, re.M),
          f"({done.stdout[-400:]})")


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


# The official text, as mozilla.org serves it (https://www.mozilla.org/media/MPL/2.0/index.txt,
# read 2026-11-26): a reworded or cut copy is not the licence the packages declare.
MPL_2_0_SHA256 = "3f3d9e0024b1921b067d6f7f88deb4a60cbe7a78e76c64e3f1d7fc3b779b9d04"
# Exhibit A of the MPL. The repository's own LICENSE is the GPL, so each file of the two
# packages says which licence it is under.
MPL_NOTICE = ("This Source Code Form is subject to the terms of the Mozilla Public",
              "License, v. 2.0. If a copy of the MPL was not distributed with this",
              "file, You can obtain one at https://mozilla.org/MPL/2.0/.")
PACKAGES = (Path(ROOT) / "python" / "beannetworktester", HELPER)


def _without_the_notice(folder):
    """The source files of a package folder, and the ones that do not open with the notice."""
    seen, missing = [], []
    for path in sorted(folder.rglob("*")):
        if {"node_modules", "__pycache__"} & set(path.parts) or not path.is_file():
            continue
        mark = {".py": "#", ".js": "//", ".ts": "//"}.get(path.suffix)
        if mark is None:
            continue
        seen.append(path)
        head = path.read_text(encoding="utf-8").splitlines()[:len(MPL_NOTICE)]
        if head != [f"{mark} {line}" for line in MPL_NOTICE]:
            missing.append(path.relative_to(folder).as_posix())
    return seen, missing


def test_both_packages_are_mpl_and_every_file_says_so(tmp_path):
    python = (PACKAGES[0] / "pyproject.toml").read_text(encoding="utf-8")
    check("the Python package declares MPL-2.0",
          re.search(r'(?m)^license = "MPL-2\.0"$', python) is not None)
    npm = json.loads((HELPER / "package.json").read_text(encoding="utf-8"))
    check("the npm package declares MPL-2.0", npm["license"] == "MPL-2.0", f"({npm['license']})")
    for folder in PACKAGES:
        digest = hashlib.sha256((folder / "LICENSE").read_bytes()).hexdigest()
        check(f"{folder.parent.name}: LICENSE is the MPL-2.0 text", digest == MPL_2_0_SHA256,
              f"({digest})")
        seen, missing = _without_the_notice(folder)
        check(f"{folder.parent.name}: source files were read", len(seen) >= 6, f"({len(seen)})")
        check(f"{folder.parent.name}: every source file opens with the notice", not missing,
              f"({missing})")
    (tmp_path / "kept.py").write_text("".join(f"# {line}\n" for line in MPL_NOTICE),
                                      encoding="utf-8")
    (tmp_path / "lost.js").write_text("'use strict';\n", encoding="utf-8")
    check("canary: a file without the notice is named",
          _without_the_notice(tmp_path)[1] == ["lost.js"])
