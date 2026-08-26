"""Crash-safe JSON persistence (``beantester/jsonfile.py``).

This module is the data-integrity net under every user file: profiles, window
state and config. Its two promises are the ones worth pinning:

* an **atomic** write never leaves a half-written or ``.tmp`` file behind, and
* a **broken** file is quarantined (renamed aside) rather than silently clobbered
  by the next save, so the user can get their data back.

These are pure filesystem operations, so the tests use a real ``tmp_path`` and no
mocks - the behaviour under test IS the filesystem behaviour.
"""
import json
import os

from beantester.jsonfile import MAX_BYTES, quarantine, read_json, write_json
from fakes import ROOT, check


def test_write_then_read_round_trips(tmp_path):
    path = str(tmp_path / "profile.json")
    data = {"name": "home", "loss": 0, "nested": {"a": [1, 2, 3]}}
    err = write_json(path, data)
    check("write reports success", err is None, f"(err={err!r})")
    back, read_err = read_json(path)
    check("read reports success", read_err is None, f"(err={read_err!r})")
    check("data survives the round trip", back == data, f"(got {back!r})")


def test_write_preserves_non_ascii(tmp_path):
    """Config/profile names can be Polish; the write must not mangle them."""
    path = str(tmp_path / "pl.json")
    data = {"opis": "Słabe WiFi w kawiarni - zażółć gęślą jaźń"}
    write_json(path, data)
    back, _ = read_json(path)
    check("Polish text survives the write", back == data, f"(got {back!r})")
    raw = open(path, encoding="utf-8").read()
    check("non-ascii stored as text, not \\u escapes", "Słabe" in raw, f"(raw={raw!r})")


def test_write_is_atomic_and_leaves_no_tmp(tmp_path):
    path = str(tmp_path / "state.json")
    write_json(path, {"x": 1})
    leftovers = [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]
    check("no .tmp file remains after a successful write", not leftovers,
          f"(found {leftovers})")


def test_write_overwrites_existing_content(tmp_path):
    path = str(tmp_path / "state.json")
    write_json(path, {"v": 1})
    write_json(path, {"v": 2})
    back, _ = read_json(path)
    check("second write replaces the first", back == {"v": 2}, f"(got {back!r})")


def test_read_missing_file_is_not_an_error(tmp_path):
    data, err = read_json(str(tmp_path / "nope.json"))
    check("missing file returns no data", data is None, f"(data={data!r})")
    check("missing file is not reported as an error", err is None, f"(err={err!r})")


def test_broken_json_is_quarantined_not_clobbered(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text("{ this is not valid json ", encoding="utf-8")

    data, err = read_json(str(path))
    check("broken file yields no data", data is None, f"(data={data!r})")
    check("broken file is reported", bool(err), f"(err={err!r})")

    check("the broken file was moved aside", not path.exists())
    backups = list(tmp_path.glob("profiles.corrupt-*.json"))
    check("a quarantine copy exists", len(backups) == 1, f"(found {backups})")
    check("the quarantine keeps the original (broken) bytes",
          backups[0].read_text(encoding="utf-8").startswith("{ this is not valid"))


def test_type_mismatch_is_quarantined(tmp_path):
    """A profiles file must be a dict; a list where a dict is expected is corrupt
    input, not a silent success."""
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    data, err = read_json(str(path), expect=dict)
    check("wrong top-level type yields no data", data is None, f"(data={data!r})")
    check("wrong type is reported", bool(err), f"(err={err!r})")
    check("wrong-type file is quarantined", not path.exists())
    check("a quarantine copy exists for the type mismatch",
          len(list(tmp_path.glob("cfg.corrupt-*.json"))) == 1)


def test_expect_none_accepts_any_json_type(tmp_path):
    path = tmp_path / "list.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    data, err = read_json(str(path), expect=None)
    check("expect=None accepts a list", data == [1, 2, 3], f"(data={data!r})")
    check("expect=None does not quarantine a valid file", err is None and path.exists())


def test_write_to_missing_directory_fails_cleanly(tmp_path):
    """The CLI contract: a --save-config to a bad path is an error (exit code IO),
    never a silent success and never a stray .tmp. write_json must NOT invent the
    directory (that would turn a typo into a 'success')."""
    target = tmp_path / "does_not_exist" / "out.json"
    err = write_json(str(target), {"x": 1})
    check("a bad path returns an error string", isinstance(err, str) and err,
          f"(err={err!r})")
    check("the target file was not created", not target.exists())
    check("the missing directory was not invented", not target.parent.exists())
    leftovers = list(tmp_path.rglob("*.tmp"))
    check("no .tmp file is left behind on failure", not leftovers, f"(found {leftovers})")


def test_the_writer_refuses_a_value_the_reader_would_reject(tmp_path):
    """The two halves have to agree, or the program writes its own corrupt file.

    ``json.dump`` emits ``Infinity`` and ``NaN`` happily - they are a Python
    extension, not JSON - while ``load_json`` refuses them. Left as it was, one
    stray non-finite float would produce a file this program then reported as
    broken and quarantined, which is the least explainable bug report there is.
    """
    path = str(tmp_path / "state.json")
    error = write_json(path, {"latency": float("inf")})

    check("a non-finite value is refused", bool(error), f"(error={error!r})")
    check("and nothing is left behind", not os.path.exists(path)
          and not [p for p in os.listdir(tmp_path) if p.endswith(".tmp")],
          f"(files: {sorted(os.listdir(tmp_path))})")


def test_a_directory_carrying_the_name_of_a_data_file_is_not_renamed_aside(tmp_path):
    """Quarantine moves a broken FILE aside. A directory with that name is not a
    broken file - it is what a Scoop persist leaves behind (``paths.migrate_user_files``
    skips it for the same reason). Renaming it would break the user's install to
    punish it for not being what we expected."""
    path = tmp_path / "bean_network_tester_profiles.json"
    path.mkdir()

    backup = quarantine(str(path))
    check("a directory is not quarantined", backup is None, f"({backup!r})")
    check("and it is still where the user put it", path.is_dir(),
          f"(files: {sorted(p.name for p in tmp_path.iterdir())})")


def test_the_size_limit_is_far_above_the_files_this_program_writes():
    """The limit must be something only a hostile file ever meets.

    Measured rather than guessed: the largest JSON this repository ships is a
    translation file. If one ever grows past a tenth of the limit, the number here
    is no longer a safety net but a wall the next language will hit - and this test
    is where that gets noticed, not a user's bug report.
    """
    lang = os.path.join(ROOT, "lang")
    biggest = max(os.path.getsize(os.path.join(lang, name))
                  for name in os.listdir(lang) if name.endswith(".json"))

    check("the biggest shipped file is nowhere near the limit",
          biggest * 10 < MAX_BYTES, f"(biggest {biggest} B, limit {MAX_BYTES} B)")


def test_quarantine_of_a_missing_file_returns_none(tmp_path):
    check("quarantining a nonexistent file is a no-op",
          quarantine(str(tmp_path / "ghost.json")) is None)


def test_quarantine_moves_the_file_and_returns_the_backup(tmp_path):
    path = tmp_path / "ui.json"
    path.write_text("garbage", encoding="utf-8")
    backup = quarantine(str(path))
    check("quarantine returns a backup path", backup is not None, f"(backup={backup!r})")
    check("the original is gone", not path.exists())
    check("the backup exists and keeps the bytes",
          os.path.exists(backup) and open(backup, encoding="utf-8").read() == "garbage")
    check("the backup is named as a corrupt copy", ".corrupt-" in os.path.basename(backup))
