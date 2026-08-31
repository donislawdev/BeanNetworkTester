"""Run a snippet of GUI test code against the fake tkinter, in a subprocess.

A subprocess keeps the fake tkinter modules out of the pytest interpreter (the
rest of the suite must see the real absence of Tk), while still giving each test
its own assertions and its own failure message.
"""
import os
import subprocess
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")

PRELUDE = """
import os, sys
sys.path.insert(0, {root!r})
sys.path.insert(0, {tests!r})
import fake_tk
fake_tk.SCREEN[:] = [{screen_w}, {screen_h}]
fake_tk.DPI[0] = {dpi}
tk = fake_tk.install()
fake_tk.single_monitor()      # one monitor, exactly the fake screen (see its docstring)

# user files (profiles / ui state / crash log) must never be written into the
# repo by a test - shared with smoke_gui.py so both stay isolated the same way
import user_files
user_files.redirect_to_temp()

import bean_network_tester as bnt
# The shipped languages, discovered once in fakes.py. A body that loops over them
# runs in THIS interpreter, not in pytest's, so it cannot see the module-level
# import the test file made - three of them said NameError the first time.
from fakes import LANGS
bnt.set_language({lang!r})
root = tk.Tk()
app = bnt.App(root)
"""


# Coverage has to be told to follow us into the subprocess, or every line the GUI
# tests exercise is reported as UNCOVERED - sortable_tree.py showed 15% while
# having seven dedicated tests. A gate built on that number would be a gate built
# on a lie. This is the documented mechanism (COVERAGE_PROCESS_START +
# coverage.process_startup()) and it costs nothing when coverage is not running.
COVERAGE_PRELUDE = """
import os
if os.environ.get("COVERAGE_PROCESS_START"):
    try:
        import coverage
        coverage.process_startup()
    except Exception:
        pass
"""


# Nothing may be swallowed behind a green GUI test.
#
# `crashlog.quiet`/`note` exist so a failure stops being invisible to US while
# staying invisible to the user (convention 30) - but no test ever read them
# back, so the swallowing was invisible to us too. A full run was recording 809
# faults: 526 of them one missing attribute on the tkinter double, which meant Tk
# font scaling never ran in a single GUI test while every one of them passed.
#
# The check lives HERE rather than in a test that scans crashes/ because the
# subprocess is where the fault happens: this way the failure carries the name of
# the test that caused it, and it keeps working now that the crash log is
# redirected to a temp dir per subprocess.
EPILOGUE = """
_allowed = {allowed!r}
_faults = [e for e in __import__("beantester.crashlog", fromlist=["x"]).recent(50)
           if not any(_frag in (e.get("message") or "") or _frag in (e.get("subsystem") or "")
                      for _frag in _allowed)]
assert not _faults, (
    "the GUI swallowed %d unexpected fault(s) - a green test that quietly lost a "
    "code path is the exact failure crashlog exists to prevent. Either fix the "
    "cause or, if the test injects it on purpose, name it in run_gui(allow_faults=...):"
    "\\n" + "\\n".join("  %s: %s (%s) x%s" % (e.get("subsystem"), e.get("type"),
                                              e.get("message"), e.get("count"))
                       for e in _faults))
"""


def run_gui(body, lang="pl", screen=(1920, 1080), dpi=96.0, allow_faults=()):
    """Build the App on the fake tkinter and execute ``body``; assert it passes.

    ``allow_faults`` lists message/subsystem fragments this test injects on
    purpose; anything else swallowed by ``crashlog`` fails the test (see EPILOGUE).
    """
    code = COVERAGE_PRELUDE
    code += PRELUDE.format(root=ROOT, tests=TESTS, lang=lang,
                           screen_w=screen[0], screen_h=screen[1], dpi=dpi)
    code += textwrap.dedent(body)
    code += EPILOGUE.format(allowed=tuple(allow_faults))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          cwd=ROOT, timeout=120, env=env)
    assert proc.returncode == 0, (
        f"\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")
    return proc.stdout
