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
        # Our own files must not need the warning a user's file gets:
        # failing-dns.json set "filter" in a step, which does nothing there
        # (external review P3-12).
        check(f"{name} loads without a warning", scenario.warnings == [],
              f"({scenario.warnings})")


def _loss_of_first_step(scenario):
    return scenario.steps[0]["settings"]["loss"]


def test_the_names_a_repro_command_writes_open_from_any_folder(tmp_path, monkeypatch):
    """The exe is on PATH after every install, so a copied command runs anywhere.

    A repro command names a shipped scenario from the program's folder -
    ``scenarios\\x.json`` from the sources, ``_internal\\scenarios\\x.json`` from
    the exe - and from any other folder that name found nothing. Both shapes open
    from either build (a report travels between installs), and the scenario keeps
    the name as given, so the command it repeats is the one that was pasted.
    """
    shipped = load_scenario_file(os.path.join(SCENARIO_DIR, "cafe-wifi.json"))
    monkeypatch.chdir(tmp_path)
    for name in ("scenarios/cafe-wifi.json", "scenarios\\cafe-wifi.json",
                 "./scenarios/cafe-wifi.json", "_internal\\scenarios\\cafe-wifi.json"):
        scenario = load_scenario_file(name)
        check(f"{name} opens from another folder", scenario.steps == shipped.steps)
        check(f"{name} is kept as the scenario's name", scenario.source == name,
              f"({scenario.source!r})")


def test_a_file_in_the_working_folder_still_wins(tmp_path, monkeypatch):
    """A relative path means the working folder first, as for every other file."""
    mine = tmp_path / "scenarios"
    mine.mkdir()
    (mine / "cafe-wifi.json").write_text(
        '{"steps": [{"at": 0, "settings": {"loss": 9}}]}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    scenario = load_scenario_file(os.path.join("scenarios", "cafe-wifi.json"))
    check("the working folder's file is the one loaded",
          _loss_of_first_step(scenario) == 9, f"({scenario.steps[0]})")


def test_only_the_names_the_command_writes_fall_back(tmp_path, monkeypatch):
    """Any other missing path fails as before, and the error names what was typed."""
    monkeypatch.chdir(tmp_path)
    for name in ("cafe-wifi.json", "foo/scenarios/cafe-wifi.json",
                 "../scenarios/cafe-wifi.json", "scenarios/sub/cafe-wifi.json",
                 "_internal/cafe-wifi.json", "scenarios/no-such-scenario.json",
                 str(tmp_path / "scenarios" / "cafe-wifi.json")):
        try:
            load_scenario_file(name)
        except OSError as e:
            check(f"{name}: the error names the path as typed", e.filename == name,
                  f"({e.filename!r})")
        else:
            check(f"{name} must not open a shipped scenario", False)


def test_the_command_path_and_its_reading_are_one_round_trip(tmp_path, monkeypatch):
    """What ``command_path`` writes is what ``load_scenario_file`` finds again.

    The two halves live in two modules (the GUI names the file, the CLI reads it),
    so this pins them together - for the sources and for the exe's layout, where
    the scenarios sit in ``_internal`` next to the executable.
    """
    from beantester import paths
    from beantester.gui.session_repro import command_path

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    name = command_path(os.path.join(paths.scenarios_dir(), "cafe-wifi.json"))
    monkeypatch.chdir(elsewhere)
    check("sources: the command's name opens from another folder",
          load_scenario_file(name).source == name, f"({name!r})")

    exe_dir = tmp_path / "install"
    bundled = exe_dir / "_internal" / "scenarios"
    bundled.mkdir(parents=True)
    (bundled / "cafe-wifi.json").write_text(
        '{"steps": [{"at": 0, "settings": {"loss": 7}}]}', encoding="utf-8")
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "executable_dir", lambda: str(exe_dir))
    monkeypatch.setattr(paths, "scenarios_dir", lambda: str(bundled))
    name = command_path(str(bundled / "cafe-wifi.json"))
    check("exe: the command names the bundled folder",
          name == os.path.join("_internal", "scenarios", "cafe-wifi.json"), f"({name!r})")
    scenario = load_scenario_file(name)
    check("exe: the command's name opens the bundled file from another folder",
          _loss_of_first_step(scenario) == 7, f"({scenario.steps[0]})")


def test_old_example_scenario_is_gone():
    """example_scenario.json was removed in favour of the scenarios/ directory."""
    check("example_scenario.json no longer ships",
          not os.path.exists(os.path.join(ROOT, "example_scenario.json")))
