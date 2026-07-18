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
import os, sys, tempfile
sys.path.insert(0, {root!r})
sys.path.insert(0, {tests!r})
import fake_tk
fake_tk.SCREEN[:] = [{screen_w}, {screen_h}]
fake_tk.DPI[0] = {dpi}
tk = fake_tk.install()

# user files (profiles / ui state) must never be written into the repo by a test
_tmp = tempfile.mkdtemp()
import beantester.gui.ui_state as _ui
import beantester.gui.profiles as _pf
_ui.UiStateStore.__init__.__defaults__ = (os.path.join(_tmp, "ui.json"),)
_pf.ProfileStore.__init__.__defaults__ = (os.path.join(_tmp, "profiles.json"),)

import bean_network_tester as bnt
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


def run_gui(body, lang="pl", screen=(1920, 1080), dpi=96.0):
    """Build the App on the fake tkinter and execute ``body``; assert it passes."""
    code = COVERAGE_PRELUDE
    code += PRELUDE.format(root=ROOT, tests=TESTS, lang=lang,
                           screen_w=screen[0], screen_h=screen[1], dpi=dpi)
    code += textwrap.dedent(body)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          cwd=ROOT, timeout=120, env=env)
    assert proc.returncode == 0, (
        f"\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")
    return proc.stdout
