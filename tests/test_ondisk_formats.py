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

from beantester import exitcodes, i18n
from beantester.cli import run_cli
from beantester.gui.ui_state import DEFAULTS, UiStateStore
from beantester.jsonfile import read_json
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


# --------------------------------------------------------------------------- #
# the scenario file (--scenario), and what --dry-run is worth
# --------------------------------------------------------------------------- #
def test_dry_run_actually_opens_the_scenario_it_calls_valid(tmp_path):
    """``--dry-run`` is the gate a pipeline runs before the real command.

    It used to load the scenario only once the session had started, so every
    broken scenario file - truncated, empty, a bare list - passed ``--dry-run``
    with "Configuration is valid" and exit OK, then failed the real run with
    SCENARIO(4). The check that exists to catch exactly this reported the
    opposite of the truth.
    """
    for label, text in BROKEN_JSON.items():
        path = tmp_path / f"scen_{label.replace(' ', '_')}.json"
        path.write_text(text, encoding="utf-8")
        code, out, err = cli(["--scenario", str(path), "--simulate", "--dry-run"])

        check(f"{label}: --dry-run rejects it", code == exitcodes.SCENARIO,
              f"(code={code}, stderr={err!r})")
        check(f"{label}: it does NOT claim the configuration is valid",
              "valid" not in out.lower(), f"({out!r})")


def test_dry_run_and_a_real_run_agree_about_a_scenario(tmp_path):
    """The property behind the fix: the gate and the gated must give the same
    verdict, or the gate is worse than not having one."""
    broken = tmp_path / "broken.json"
    broken.write_text('{"steps": ', encoding="utf-8")
    # The real schema: {"at": seconds, "settings": {...}}. Written out rather than
    # guessed - the first draft of this test invented a shape, --dry-run rejected
    # it correctly, and for a moment that looked like the fix rejecting good files.
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"steps": [{"at": 0, "settings": {"loss": 5}}]}),
                    encoding="utf-8")

    dry_broken, _, _ = cli(["--scenario", str(broken), "--simulate", "--dry-run"])
    run_broken, _, _ = cli(["--scenario", str(broken), "--simulate", "--duration", "1"])
    dry_good, _, _ = cli(["--scenario", str(good), "--simulate", "--dry-run"])

    check("a broken scenario fails the dry run", dry_broken == exitcodes.SCENARIO,
          f"({dry_broken})")
    check("and it fails the real run the same way", run_broken == exitcodes.SCENARIO,
          f"({run_broken})")
    check("the two agree", dry_broken == run_broken,
          f"(dry={dry_broken}, run={run_broken})")
    check("a good scenario still passes the dry run", dry_good == exitcodes.OK,
          f"({dry_good})")

    # And the strongest form: the scenarios we ship must survive their own gate.
    shipped = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "scenarios")
    for name in sorted(os.listdir(shipped)):
        if not name.endswith(".json"):
            continue
        code, _, err = cli(["--scenario", os.path.join(shipped, name),
                            "--simulate", "--dry-run"])
        check(f"shipped scenario {name} passes --dry-run", code == exitcodes.OK,
              f"(code={code}, stderr={err!r})")


# --------------------------------------------------------------------------- #
# lang/*.json - the one on-disk format with its own json.load
# --------------------------------------------------------------------------- #
def test_a_broken_language_file_is_skipped_not_fatal(tmp_path):
    """``load_languages`` promises a broken file "is skipped so it can never
    break app startup". A ``_meta`` of the wrong type broke exactly that.

    ``meta = data.pop("_meta", None) or {}`` rescued a FALSY value - ``null``,
    ``0``, ``""`` - and nothing else. ``"_meta": "en"``, a list or a number sailed
    past it and died on ``meta.get()``, which sits outside the per-file ``try``.
    The AttributeError escaped ``load_languages``, which runs at startup: measured
    with one such file dropped into the real ``lang/``, even ``--version`` exited 1
    with a traceback. One stray file, no program.
    """
    good = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "lang", "en.json")

    # A file that does not parse into a dict has nothing usable in it: skip it.
    unusable = {
        "truncated": '{"a": ',
        "a bare list": "[1, 2, 3]",
        "empty file": "",
        "not json at all": "<html>",
    }
    # A file that DOES parse but whose _meta is the wrong type is not a broken
    # translation file - it is a translation file with unusable metadata, which is
    # the same position as one carrying no ``_meta`` at all (it is optional, and
    # then the filename supplies the code). Keep the translations, drop the
    # metadata. Discarding the whole file would throw away a translator's work
    # over a typo in one field.
    bad_meta = {
        "_meta is a string": '{"_meta": "en", "x": "y"}',
        "_meta is a list": '{"_meta": [1, 2], "x": "y"}',
        "_meta is a number": '{"_meta": 7, "x": "y"}',
        "_meta is a bool": '{"_meta": true, "x": "y"}',
    }

    def load_with(label, text):
        folder = tmp_path / label.replace(" ", "_").replace('"', "")
        folder.mkdir()
        (folder / "en.json").write_text(open(good, encoding="utf-8").read(),
                                        encoding="utf-8")
        (folder / "zz.json").write_text(text, encoding="utf-8")
        return i18n.load_languages(str(folder))

    for label, text in unusable.items():
        codes = load_with(label, text)
        check(f"{label}: the good language still loaded", "en" in codes,
              f"(codes={sorted(codes)})")
        check(f"{label}: the unusable one was skipped", "zz" not in codes,
              f"(codes={sorted(codes)})")

    for label, text in bad_meta.items():
        codes = load_with(label, text)
        check(f"{label}: it did not take the program down", "en" in codes,
              f"(codes={sorted(codes)})")
        check(f"{label}: the translations survive, keyed by the file name",
              "zz" in codes, f"(codes={sorted(codes)})")
        i18n.set_language("zz")
        check(f"{label}: and they actually translate", i18n.translate("x") == "y",
              f"({i18n.translate('x')!r})")


def test_the_app_still_speaks_when_every_language_file_is_broken(tmp_path):
    """Nothing loadable at all is still not a reason to fall over: the caller
    gets an empty set and translation falls back to the built-in text."""
    for name in ("en.json", "pl.json"):
        (tmp_path / name).write_text("not json at all", encoding="utf-8")

    codes = i18n.load_languages(str(tmp_path))
    check("nothing loaded, and that is reported honestly", codes == set(),
          f"({codes})")
    check("a translation still returns usable text",
          isinstance(i18n.translate("buttons.ok"), str)
          and i18n.translate("buttons.ok") != "",
          f"({i18n.translate('buttons.ok')!r})")


def test_a_missing_language_directory_is_not_fatal(tmp_path):
    codes = i18n.load_languages(str(tmp_path / "does-not-exist"))
    check("a missing lang directory loads nothing and raises nothing",
          codes == set(), f"({codes})")


# --------------------------------------------------------------------------- #
# the filesystem itself: not every failure is a parse failure
# --------------------------------------------------------------------------- #
def test_a_directory_where_a_file_belongs_is_reported_not_crashed(tmp_path):
    """``read_json`` catches ``OSError``, and this is the case that produces one
    without any content being involved: on Linux opening a directory raises
    ``IsADirectoryError``, on Windows ``PermissionError``. Both are OSError, and
    both must come back as a message rather than as an exception."""
    path = tmp_path / "ui.json"
    path.mkdir()
    data, error = read_json(str(path), expect=dict)

    check("a directory does not parse into data", data is None, f"({data!r})")
    check("and the caller is told why", bool(error), f"({error!r})")


def test_an_unreadable_file_is_moved_aside_rather_than_left_to_be_overwritten(tmp_path):
    """Unreadable is answered, not raised - and the file is preserved.

    Quarantining a file we could not READ looks heavy-handed until you follow
    what happens next: ``UiStateStore.persist()`` runs unconditionally (on close,
    and whenever window state changes), and ``write_json`` ends in
    ``os.replace``. Leave an unreadable file in place and the first save of the
    session overwrites it - destroying exactly the content nobody could read.
    Moving it to ``.corrupt-<timestamp>`` is what saves it.

    The platforms disagree about whether this can even be provoked: ``chmod``
    genuinely blocks reads on POSIX, while on Windows it only toggles the
    read-only bit and the file stays readable (and root ignores it everywhere).
    So the portable half is asserted always, and the quarantine half only when
    the platform actually denied the read.
    """
    path = tmp_path / "state.json"
    path.write_text('{"page": "control"}', encoding="utf-8")
    os.chmod(path, 0)
    try:
        data, error = read_json(str(path), expect=dict)
    finally:
        # The read may have renamed it, so restore whatever is actually there -
        # the first version of this chmod'd a fixed path and died with
        # FileNotFoundError on Linux, where the quarantine had already happened.
        for leftover in tmp_path.iterdir():
            try:
                os.chmod(leftover, 0o600)
            except OSError:
                pass

    check("an unreadable file is answered, not raised",
          (data is not None) or bool(error), f"(data={data!r}, error={error!r})")
    if error:                     # the platform really did deny the read
        moved = [p.name for p in tmp_path.iterdir() if ".corrupt-" in p.name]
        check("a file that could not be read is preserved, not left to be "
              "overwritten by the next save", moved,
              f"(files: {sorted(p.name for p in tmp_path.iterdir())})")


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
