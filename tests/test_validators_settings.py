"""Numeric validation, the raw->settings conversion and the UI state store.

``loss = 250`` used to sail through the GUI and the CLI and be silently clamped
to 100% deep inside ``BeanCore``; a bad number in a config file produced a
traceback. One validator, three entry points.
"""
import json
import os
import tempfile

import pytest

from beantester.cli import build_arg_parser, config_from_args
from beantester.gui.ui_state import UiStateStore
from beantester.presets import PRESETS, preset_to_settings, settings_to_preset
from beantester.settings import (DEFAULT_SETTINGS, settings_from_raw,
                                 validate_ranges)
from beantester.validators import parse_number, parse_seed
from fakes import check


# -- numbers ----------------------------------------------------------------- #
def test_parse_number_accepts_and_rejects():
    check("number: plain value", parse_number("12.5", "fields.loss", (0, 100)) == 12.5)
    check("number: comma decimal separator", parse_number("2,5", "fields.loss", (0, 100)) == 2.5)
    with pytest.raises(ValueError) as e:
        parse_number("abc", "fields.loss", (0, 100))
    check("number: translated 'must be a number'", "Utrata" in str(e.value), f"({e.value})")


def test_parse_number_enforces_bounds():
    with pytest.raises(ValueError) as e:
        parse_number("250", "fields.loss", (0, 100))
    check("number: out-of-range is rejected with a range message",
          "zakresie" in str(e.value) and "100" in str(e.value), f"({e.value})")
    with pytest.raises(ValueError):
        parse_number("-1", "fields.latency", (0, 600000))
    check("number: NaN/inf rejected", True)
    with pytest.raises(ValueError):
        parse_number("inf", "fields.loss", (0, 100))


def test_parse_seed():
    check("seed: empty means random", parse_seed("") == -1 and parse_seed(None) == -1)
    check("seed: integer kept", parse_seed("777") == 777)
    with pytest.raises(ValueError):
        parse_seed("abc")


def test_validate_ranges_on_a_settings_dict():
    check("ranges: defaults are valid", validate_ranges(dict(DEFAULT_SETTINGS)))
    with pytest.raises(ValueError):
        validate_ranges(dict(DEFAULT_SETTINGS, flap_down=900))


def test_cli_rejects_an_out_of_range_flag():
    from beantester import exitcodes
    with pytest.raises(SystemExit) as e:
        config_from_args(build_arg_parser().parse_args(["--loss", "250"]))
    check("CLI: --loss 250 is an error, not a silent clamp",
          "between" in str(e.value), f"({e.value})")
    check("CLI: a bad value exits with the CONFIG code",
          e.value.code == exitcodes.CONFIG, f"({e.value.code})")
    cfg = config_from_args(build_arg_parser().parse_args(["--loss", "25"]))
    check("CLI: a valid value still passes", cfg["settings"]["loss"] == 25.0)


# -- raw -> settings (the GUI's only conversion) ------------------------------ #
def test_settings_from_raw_types_everything():
    raw = {"loss": "5", "lan_mode": True, "seed": "", "dst_port": "443",
           "rate_schedule": " 1:100:0 ", "target": " chrome.exe "}
    s = settings_from_raw(raw)
    check("raw: numbers become floats", s["loss"] == 5.0)
    check("raw: booleans stay booleans", s["lan_mode"] is True)
    check("raw: empty seed becomes the -1 sentinel", s["seed"] == -1)
    check("raw: expression fields stay strings", s["dst_port"] == "443")
    check("raw: expressions are trimmed", s["target"] == "chrome.exe")
    check("raw: untouched keys keep their defaults", s["jitter"] == DEFAULT_SETTINGS["jitter"])


def test_settings_from_raw_rejects_bad_input():
    with pytest.raises(ValueError):
        settings_from_raw({"loss": "abc"})
    with pytest.raises(ValueError):
        settings_from_raw({"dst_port": "99999"})       # outside PORT_BOUNDS
    with pytest.raises(ValueError):
        settings_from_raw({"rate_schedule": "1:2"})


def test_preset_mapping_is_shared_by_gui_and_cli():
    """The GUI and the CLI each used to carry their own lat/jit -> latency/jitter map."""
    for key, preset in PRESETS.items():
        s = preset_to_settings(preset)
        check(f"preset {key}: mapped to model keys",
              s["latency"] == preset["lat"] and s["jitter"] == preset["jit"])
        check(f"preset {key}: round-trips back", settings_to_preset(s) == dict(preset))
    check("preset: resolvable by name too",
          preset_to_settings("presets.3g")["down"] == PRESETS["presets.3g"]["down"])


def test_every_preset_is_within_the_declared_bounds():
    for key, preset in PRESETS.items():
        validate_ranges(dict(DEFAULT_SETTINGS, **preset_to_settings(preset)))
    check("presets: all inside the field bounds", True)


# -- UI state store ----------------------------------------------------------- #
def test_ui_state_round_trip():
    path = os.path.join(tempfile.mkdtemp(), "ui.json")
    store = UiStateStore(path)
    store.set("page", "connections")
    store.set("geometry", "800x600+10+10")
    store.set("collapsed", ["advanced"])
    check("ui state: persists without error", store.persist() is None)
    again = UiStateStore(path)
    check("ui state: restored", again.get("page") == "connections"
          and again.get("geometry") == "800x600+10+10"
          and again.get("collapsed") == ["advanced"])


def test_ui_state_survives_a_corrupt_file():
    path = os.path.join(tempfile.mkdtemp(), "ui.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ not json")
    store = UiStateStore(path)
    check("ui state: a corrupt file degrades to the defaults",
          store.get("page") == "control" and store.get("conn_sort")["col"] == "kb")
    check("ui state: the corrupt file is reported, not swallowed", bool(store.problem))
    backups = [n for n in os.listdir(os.path.dirname(path)) if "corrupt" in n]
    check("ui state: the corrupt file is kept aside", len(backups) == 1, f"({backups})")


def test_the_default_sort_column_exists_in_the_table():
    """It used to default to "bytes" - a column the connection table does not have,
    so no header ever showed a sort arrow."""
    from beantester.gui.ui_state import DEFAULTS
    columns = ("proc", "proto", "remote_ip", "remote_port", "local_port",
               "packets", "kb", "dur", "idle")
    check("conn_sort default is a real column",
          DEFAULTS["conn_sort"]["col"] in columns, f"({DEFAULTS['conn_sort']})")


def test_ui_state_defaults_are_json_serialisable():
    json.dumps(UiStateStore(os.path.join(tempfile.mkdtemp(), "ui.json")).data)
    check("ui state: defaults are serialisable", True)
