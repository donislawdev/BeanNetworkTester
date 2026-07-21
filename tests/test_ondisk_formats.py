"""What the tool does with a user file that is broken (audit item #10).

Four formats live on disk and belong to the user: the config file (``--config``,
"Save/Load file"), a scenario, ``profiles.json`` and ``bean_network_tester_ui.json``.
They are edited by hand on purpose - they sit next to the executable - they are
copied between machines, they are written by other tools, and a process killed
mid-write truncates them. ``jsonfile`` exists precisely for that. Nothing fuzzed
it, and the gap was not theoretical:

* a config file that was valid JSON but not an OBJECT (``[1, 2, 3]``, ``"x"``,
  ``42``, ``null``) reached ``data.items()`` and left the CLI with a raw
  ``AttributeError`` traceback and exit 1 - two contracts broken at once, the
  comment right above that code ("never a raw traceback") and convention 18
  (every way of ending has a code from ``exitcodes.py``; a bad config is
  ``CONFIG(3)``);
* ``ui.json`` holding a valid dict with the wrong TYPE under ``page``,
  ``conn_sort`` or ``event_sort`` stopped the GUI from starting at all, against
  a module docstring promising that corruption "must never break startup";
* ``--dry-run`` reported "Configuration is valid" for a scenario file it had
  never opened.

The invariants below are what those three have in common: **a broken user file
may cost you your settings, never your program.**

``profiles.json`` is the format that already got this right - ``ProfileStore._clean``
validates every entry, drops what it cannot use and says so - and it is the shape
the others now follow.
"""
import io
import json
import os

from beantester import exitcodes
from beantester.cli import run_cli
from beantester.gui.ui_state import DEFAULTS, UiStateStore
from fakes import check
from gui_harness import run_gui


class _FakeClock:
    """Virtual time, so a run that would sleep costs microseconds."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += max(0.0, float(seconds))


def cli(argv):
    """Run the CLI in-process; returns ``(code, stdout, stderr)``.

    In-process on purpose: an exception that escapes ``run_cli`` fails the test
    with its own traceback, which is exactly the failure being guarded against.
    """
    clock = _FakeClock()
    out, err = io.StringIO(), io.StringIO()
    code = run_cli(argv, sleep=clock.sleep, clock=clock, out=out, err=err)
    return code, out.getvalue(), err.getvalue()

# Shapes a JSON file arrives in when something went wrong. Valid JSON of the
# wrong type is the interesting half: the parser is happy, so nothing downstream
# is warned.
BROKEN_JSON = {
    "a list": "[1, 2, 3]",
    "a string": '"just a string"',
    "a number": "42",
    "null": "null",
    "a boolean": "true",
    "truncated": '{"loss": 1',
    "empty file": "",
    "utf-8 BOM": '﻿{"loss": 5}',
    "not json at all": "<html>nope</html>",
}

# A dict whose VALUES are the wrong type for their key. This is what a hand edit
# produces, and what read_json cannot catch: it checks the container, not what is
# in it.
POISONED_UI_STATE = {
    "geometry": {"a": 1},
    "page": [1, 2, 3],
    "stats_page": 42,
    "language": [],
    "collapsed": "control",
    "log_height": "big",
    "conn_sort": [1, 2],
    "event_sort": "kb",
    "profile": {},
}


# --------------------------------------------------------------------------- #
# ui.json
# --------------------------------------------------------------------------- #
def test_ui_state_drops_wrongly_typed_values_and_says_which(tmp_path):
    """Keep what is usable, drop what is not, and report it - never raise."""
    path = tmp_path / "ui.json"
    payload = dict(POISONED_UI_STATE)
    payload["page"] = [1, 2, 3]              # broken
    payload["language"] = []                 # broken
    payload["geometry"] = "800x600+0+0"      # GOOD: must survive
    payload["unknown_future_key"] = {"anything": True}
    path.write_text(json.dumps(payload), encoding="utf-8")

    store = UiStateStore(str(path))

    check("a usable value is kept", store.get("geometry") == "800x600+0+0",
          f"({store.get('geometry')!r})")
    check("a wrongly typed value falls back to its default",
          store.get("page") == DEFAULTS["page"], f"({store.get('page')!r})")
    check("the store says what it ignored", "page" in (store.problem or ""),
          f"({store.problem!r})")
    # Unknown keys are kept on purpose: `get` only reads keys it knows, and
    # dropping them would discard state written by a newer version of the app.
    check("an unknown key is preserved rather than discarded",
          store.data.get("unknown_future_key") == {"anything": True},
          f"({store.data.get('unknown_future_key')!r})")


def test_every_ui_state_value_can_be_the_wrong_type(tmp_path):
    """One key at a time, so a single tolerant key cannot hide an intolerant one."""
    for key, bad in POISONED_UI_STATE.items():
        path = tmp_path / f"ui_{key}.json"
        path.write_text(json.dumps({key: bad}), encoding="utf-8")
        store = UiStateStore(str(path))
        check(f"{key}: the wrong type does not survive into the store",
              store.get(key) == DEFAULTS[key],
              f"(got {store.get(key)!r}, expected the default {DEFAULTS[key]!r})")


def test_a_broken_ui_state_file_never_stops_the_app_from_starting():
    """The invariant the module docstring promises, asserted through a real App.

    Three of these used to raise on startup - a list under ``page`` is not even
    hashable as a dict key - so the window never appeared and the user had a
    traceback and no idea which file caused it.

    Every case is driven in ONE subprocess: building the App is the expensive
    part, and a fresh store per case is enough isolation.
    """
    run_gui("""
        import json
        import beantester.gui.ui_state as _ui

        POISON = %r
        path = _ui.UiStateStore.__init__.__defaults__[0]
        failures = []
        for key, bad in POISON.items():
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({key: bad}, fh)
            try:
                other = bnt.App(tk.Tk())
                other._tick()
            except Exception as exc:
                failures.append(f"{key}={bad!r}: {type(exc).__name__}: {exc}")
        assert not failures, "the app did not start: " + "; ".join(failures)
    """ % (POISONED_UI_STATE,))


# --------------------------------------------------------------------------- #
# the config file (--config)
# --------------------------------------------------------------------------- #
def test_a_broken_config_file_is_a_coded_error_not_a_traceback(tmp_path):
    """Convention 18: every way of ending has a code from ``exitcodes.py``.

    ``[1, 2, 3]``, ``"x"``, ``42``, ``null`` and ``true`` are all valid JSON, so
    ``json.load`` was happy and the type error surfaced one line later at
    ``data.items()`` - an AttributeError the CLI does not catch. The user got a
    Python traceback and exit RUNTIME(1) where a bad config file means CONFIG(3),
    and a CI/CD pipeline reading the exit code was told the tool had crashed
    rather than that its config was wrong.
    """
    for label, text in BROKEN_JSON.items():
        path = tmp_path / f"config_{label.replace(' ', '_')}.json"
        path.write_text(text, encoding="utf-8")
        code, out, err = cli(["--config", str(path), "--simulate", "--dry-run"])

        check(f"{label}: a bad config file is CONFIG(3)", code == exitcodes.CONFIG,
              f"(code={code}, stderr={err!r})")
        check(f"{label}: it explains itself on stderr", "error:" in err, f"({err!r})")
        check(f"{label}: stdout stays clean for the data channel", out == "",
              f"({out!r})")


def test_a_config_file_that_is_a_json_object_still_loads(tmp_path):
    """The other side of the check: the fix must not reject real config files."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"loss": 5, "duration": 1}), encoding="utf-8")
    code, out, err = cli(["--config", str(path), "--simulate", "--dry-run"])
    check("a well-formed config file is accepted", code == exitcodes.OK,
          f"(code={code}, stderr={err!r})")


def test_a_ui_state_file_that_is_not_json_at_all_is_quarantined(tmp_path):
    """The other half of the guarantee: unparseable content is moved aside, not
    overwritten, so the user can still get their window layout back."""
    for label, text in BROKEN_JSON.items():
        path = tmp_path / f"ui_{label.replace(' ', '_')}.json"
        path.write_text(text, encoding="utf-8")
        store = UiStateStore(str(path))

        check(f"{label}: the app still has usable state",
              store.get("page") == DEFAULTS["page"], f"({store.get('page')!r})")
        check(f"{label}: the failure is reported, not swallowed",
              bool(store.problem), f"({store.problem!r})")
        quarantined = [p for p in os.listdir(tmp_path)
                       if p.startswith(path.stem) and ".corrupt-" in p]
        check(f"{label}: the broken file was moved aside rather than clobbered",
              bool(quarantined), f"(files: {sorted(os.listdir(tmp_path))})")
