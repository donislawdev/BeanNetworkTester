"""The scenarios that ship next to the exe must all be valid.

A tool whose own example scenario does not load is a bad first impression, and the
scenario file is USER input that is validated on load - so a broken shipped file
would greet the user with an error dialog. This test parses every file in
``scenarios/`` through the real validator, exactly as the app does.
"""
import glob
import os

from beantester.scenario import load_scenario_file
from fakes import ROOT, check

SCENARIO_DIR = os.path.join(ROOT, "scenarios")


def _files():
    return sorted(glob.glob(os.path.join(SCENARIO_DIR, "*.json")))


def test_scenarios_directory_is_not_empty():
    check("scenarios/ ships at least three example files", len(_files()) >= 3,
          f"({len(_files())} found)")


def test_every_shipped_scenario_parses():
    for path in _files():
        name = os.path.basename(path)
        try:
            scenario = load_scenario_file(path)
        except ValueError as exc:      # the same error the GUI would show the user
            check(f"{name} is a valid scenario", False, str(exc))
            continue
        check(f"{name} has steps", len(scenario.steps) >= 1)
        check(f"{name} has a positive duration", scenario.duration > 0,
              f"({scenario.duration}s)")


def test_old_example_scenario_is_gone():
    """example_scenario.json was removed in favour of the scenarios/ directory."""
    check("example_scenario.json no longer ships",
          not os.path.exists(os.path.join(ROOT, "example_scenario.json")))
