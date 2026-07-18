"""Runs the GUI smoke script (fake tkinter) in a subprocess.

A subprocess keeps the fake tkinter modules out of this interpreter's
``sys.modules`` so the rest of the suite is unaffected.
"""
import os
import subprocess
import sys

from fakes import ROOT, check


def test_gui_smoke_script():
    # The smoke script prints translated text in Polish; force UTF-8 for the
    # child's output AND for our decoding of it, so a cp1252 Windows console
    # cannot turn a passing run into a UnicodeEncodeError (or a decode error here).
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "smoke_gui.py")],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=ROOT, timeout=120, env=env)
    check("GUI smoke script passes", proc.returncode == 0,
          f"\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")
