"""Where a frozen build keeps the user's files, and how it adopts the old ones.

This guards a behaviour that had NO test at all until the files moved: their
location. ``tests/user_files.py`` redirects every store to a temp directory, which
is right for the rest of the suite and makes it blind to exactly this question -
so the location is pinned here, and only here.

What is being protected: a package manager owns the install directory. WinGet's
upgrade removes the extracted archive's directory recursively before installing
the new one, so anything written beside the executable is gone on the next
upgrade. The four files therefore live in the user's data directory, and an
older build's files are copied into it once.

The frozen cases run in a SUBPROCESS on purpose: ``paths`` decides the four
constants at import time, so faking ``sys.frozen`` in this process would either
do nothing or leave the rest of the suite reading a fake location.
"""
import json
import os
import subprocess
import sys

from fakes import ROOT, check

from beantester import paths

CHILD = """
import json, os, sys
sys.frozen = True                     # what PyInstaller sets
sys.executable = os.path.join(sys.argv[1], "BeanNetworkTester.exe")
sys.path.insert(0, sys.argv[2])
from beantester import paths
print(json.dumps({
    "data_dir": paths.user_data_dir(),
    "profiles": paths.PROFILE_FILE,
    "stats": paths.CSV_FILE,
    "connections": paths.CONNECTIONS_CSV_FILE,
    "ui": paths.UI_STATE_FILE,
    "adopted": paths.prepare_user_data(),
}))
"""


def _frozen_paths(tmp_path, exe_dir, **env):
    """Import ``paths`` as a frozen build would, in a throwaway interpreter."""
    script = tmp_path / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    environment = dict(os.environ)
    environment.pop(paths.DATA_DIR_ENV, None)
    environment["LOCALAPPDATA"] = str(tmp_path / "localappdata")
    environment.update(env)
    out = subprocess.run([sys.executable, str(script), str(exe_dir), ROOT],
                         capture_output=True, text=True, env=environment,
                         timeout=120)
    check("the frozen child ran", out.returncode == 0, f"({out.stderr[-400:]})")
    return json.loads(out.stdout)


# -- where the files live ------------------------------------------------------ #
def test_a_frozen_build_keeps_no_user_file_next_to_the_executable(tmp_path):
    exe_dir = tmp_path / "install" / "BeanNetworkTester"
    exe_dir.mkdir(parents=True)
    got = _frozen_paths(tmp_path, exe_dir)

    inside = [name for name in ("profiles", "stats", "connections", "ui")
              if os.path.dirname(got[name]) == str(exe_dir)]
    check("no user file is written next to the exe", not inside, f"({inside})")
    check("the data directory is under LOCALAPPDATA",
          got["data_dir"] == str(tmp_path / "localappdata" / "BeanNetworkTester"),
          f"({got['data_dir']})")


def test_every_user_file_lands_in_the_data_directory(tmp_path):
    exe_dir = tmp_path / "install"
    exe_dir.mkdir()
    got = _frozen_paths(tmp_path, exe_dir)

    stray = [name for name in ("profiles", "stats", "connections", "ui")
             if os.path.dirname(got[name]) != got["data_dir"]]
    check("all four files share the data directory", not stray, f"({stray})")


def test_the_data_directory_can_be_overridden_for_a_portable_copy(tmp_path):
    exe_dir = tmp_path / "install"
    exe_dir.mkdir()
    portable = tmp_path / "stick" / "data"
    got = _frozen_paths(tmp_path, exe_dir, **{paths.DATA_DIR_ENV: str(portable)})

    check("BEAN_DATA_DIR wins", got["data_dir"] == str(portable), f"({got['data_dir']})")
    check("the directory is created for the first write",
          os.path.isdir(portable), "(missing)")


def test_running_from_sources_still_uses_the_project_root():
    check("sources are unchanged", paths.user_data_dir() == paths.PROJECT_ROOT,
          f"({paths.user_data_dir()})")
    check("and nothing is migrated there", paths.migrate_user_files() == [],
          "(a source tree must never be written to by a migration)")


# -- adopting the files an older build left behind ----------------------------- #
def _dirs(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    source.mkdir()
    target.mkdir()
    return source, target


def test_a_file_the_target_does_not_have_is_adopted(tmp_path):
    source, target = _dirs(tmp_path)
    (source / paths.PROFILE_NAME).write_text('{"slow": {}}', encoding="utf-8")

    problems = paths.migrate_user_files(str(source), str(target))

    check("no problems", problems == [], f"({problems})")
    check("the profile arrived",
          (target / paths.PROFILE_NAME).read_text(encoding="utf-8") == '{"slow": {}}')
    check("the original is left in place (a rollback still finds it)",
          (source / paths.PROFILE_NAME).exists())


def test_a_stale_copy_never_overwrites_newer_data(tmp_path):
    source, target = _dirs(tmp_path)
    (source / paths.PROFILE_NAME).write_text("OLD", encoding="utf-8")
    (target / paths.PROFILE_NAME).write_text("NEW", encoding="utf-8")

    paths.migrate_user_files(str(source), str(target))

    check("the file already in the data directory wins",
          (target / paths.PROFILE_NAME).read_text(encoding="utf-8") == "NEW")


def test_a_corrupt_file_is_copied_verbatim_rather_than_parsed(tmp_path):
    source, target = _dirs(tmp_path)
    (source / paths.UI_STATE_NAME).write_text("", encoding="utf-8")

    problems = paths.migrate_user_files(str(source), str(target))

    check("a zero-byte file is not a migration problem", problems == [], f"({problems})")
    check("it arrives as it was, for the store to quarantine",
          (target / paths.UI_STATE_NAME).read_text(encoding="utf-8") == "")


def test_a_directory_carrying_a_user_file_name_is_skipped(tmp_path):
    # What Scoop's persist leaves behind when it persists a file that does not
    # exist yet. Copying it would raise, and raising here would break startup.
    source, target = _dirs(tmp_path)
    (source / paths.UI_STATE_NAME).mkdir()

    problems = paths.migrate_user_files(str(source), str(target))

    check("no problem is reported", problems == [], f"({problems})")
    check("and nothing was created in the data directory",
          not (target / paths.UI_STATE_NAME).exists())


def test_migrating_a_directory_onto_itself_does_nothing(tmp_path):
    source, _ = _dirs(tmp_path)
    (source / paths.PROFILE_NAME).write_text("{}", encoding="utf-8")

    problems = paths.migrate_user_files(str(source), str(source).upper()
                                        if os.name == "nt" else str(source))

    check("same directory = no work", problems == [], f"({problems})")


def test_a_failed_copy_is_reported_and_leaves_no_half_written_file(tmp_path, monkeypatch):
    source, target = _dirs(tmp_path)
    (source / paths.PROFILE_NAME).write_text("{}", encoding="utf-8")

    def boom(src, dst):
        with open(dst, "w", encoding="utf-8") as f:
            f.write("half")             # the temp file exists when it fails
        raise OSError("disk full")

    monkeypatch.setattr(paths.shutil, "copyfile", boom)
    problems = paths.migrate_user_files(str(source), str(target))

    check("the failure is reported, not swallowed", len(problems) == 1, f"({problems})")
    check("the file name is in the message", paths.PROFILE_NAME in problems[0],
          f"({problems})")
    leftovers = sorted(p.name for p in target.iterdir())
    check("no half-written file and no .tmp is left", leftovers == [], f"({leftovers})")


def test_an_unusable_data_directory_does_not_stop_the_program(tmp_path, monkeypatch):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("I am a file", encoding="utf-8")
    monkeypatch.setattr(paths, "user_data_dir", lambda: str(blocked))

    problems = paths.prepare_user_data()

    check("startup gets a problem to log instead of an exception",
          len(problems) == 1 and problems[0], f"({problems})")


def test_the_write_probe_answers_for_the_token_that_asks(tmp_path):
    """`directory_is_writable` is a probe, not a reading of the access list.

    Reading the ACL would mean deciding which principals count as "an ordinary
    user" - which is the question, not the answer. A write that succeeds is the
    answer, for exactly the token doing the asking, and that is what `--doctor`
    needs: it runs unelevated, so what it can write is what the user can write.

    The two portable cases are here. "Not writable" is not: `chmod` genuinely
    blocks a write on POSIX while on Windows it only toggles the read-only bit and
    the directory stays writable, so a test for it would assert one thing on one
    runner and nothing on the other. `test_driver_windows.py` covers that half
    where it matters, by giving `doctor()` the answer instead of the filesystem.
    """
    check("a directory this process owns is writable",
          paths.directory_is_writable(str(tmp_path)) is True)
    check("a path that is not a directory cannot be answered, not guessed",
          paths.directory_is_writable(str(tmp_path / "nope")) is None)

    leftovers = [p.name for p in tmp_path.iterdir()]
    check("the probe leaves nothing behind", not leftovers, f"({leftovers})")


def test_a_directory_that_refuses_the_write_is_answered_false(monkeypatch):
    """The refusal is the interesting answer, and the filesystem cannot be asked
    for it portably: ``chmod`` genuinely blocks a write on POSIX, while on Windows
    it only toggles the read-only bit and the directory stays writable. So the
    refusal is injected at the one call that can produce it, and the assertion is
    that it becomes ``False`` - not an exception, and not the ``None`` that means
    "there is nothing here to check"."""
    def refuse(*_a, **_kw):
        raise PermissionError("Access is denied")

    monkeypatch.setattr("builtins.open", refuse)
    answer = paths.directory_is_writable(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.undo()

    check("a directory that refuses the write is not writable", answer is False,
          f"({answer!r})")
