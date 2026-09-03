"""Crash-safe JSON persistence for the tool's user files.

Profiles, window state and config files are edited by hand (they live in one
directory of the user's own, see ``paths.user_data_dir``), they are deleted, they
are copied between machines and - if the process dies mid-write - they get
truncated. None of that may take the app down, and none of it may destroy data
silently:

* **atomic writes** - the new content is written to a temporary file and then
  ``os.replace``d over the target, which is atomic on Windows and POSIX alike.
  A crash halfway through can no longer leave a half-written profile file. The
  temporary file is unique per writer (``paths.temp_beside``), because two copies
  of the program saving at once used to share one, and the name it shared was
  derived from the target.
* **quarantine instead of overwrite** - a file that cannot be parsed is renamed
  to ``<name>.corrupt-<timestamp>`` before the app starts fresh, so a broken
  file is recoverable rather than clobbered by the first save.
* **every failure is reported** - the caller gets an error string to put in the
  log instead of a silent empty dict.
"""
import json
import os
import time
from . import crashlog
from .paths import temp_beside

# The biggest file any of these formats produces, with room to grow. MEASURED on
# this repository 2026-08-26: the largest JSON the program reads is `lang/pl.json`
# at 52 KB, a scenario is under 1 KB, and window state is 414 bytes. The worst
# LEGITIMATE case is bigger than any of those - a thousand-step scenario (the
# `scenario.MAX_STEPS` cap) or hundreds of saved profiles - and still lands around
# 300 KB. Four megabytes is roughly seventy-five times the largest real file and
# thirteen times that worst case, which is the point: the limit must never be the
# thing a user meets, only the thing a hostile file meets.
MAX_BYTES = 4 * 1024 * 1024


def _reject_constant(name):
    """``json`` calls this for ``NaN`` / ``Infinity`` / ``-Infinity``.

    Those three are not JSON - the format has no way to write them, and Python's
    parser accepts them anyway as an extension. Nothing this program stores can be
    one of them (``validators.parse_number`` refuses both, deliberately and with a
    comment, on every other input path), so a file that carries one was not written
    by this program.
    """
    raise ValueError(f"{name} is not a value a JSON file may carry")


def load_json(path):
    """Parse a JSON file. ``ValueError`` for the CONTENT, ``OSError`` for the FILE.

    The one place every reader goes through, because before this there were four
    of them catching four different sets of exceptions - not by decision, but
    because they were written at different times. That is what let a 240 KB file
    of nothing but brackets take the program down: ``json`` answers deep nesting
    with ``RecursionError``, which is neither ``OSError`` nor ``ValueError``, so it
    walked straight past every one of those loaders and out of ``App.__init__``.
    Worse, it walked past the QUARANTINE too - the mechanism whose entire job is to
    stop one broken file from bricking the program - so the next start failed the
    same way, and the one after that.

    Split by kind on purpose: the caller decides what a bad file MEANS (the CLI
    turns it into exit code CONFIG, the language loader skips the file, the profile
    store quarantines it), but nobody has to know how many ways a parser can fail.

    The size is checked with ``getsize`` and not by reading: a reader that has to
    read half a gigabyte to find out it is too big has already paid the price it
    was trying to avoid. The gap between the check and the read is knowingly left -
    these files live in the user's own directory, and the threat here is a file
    that was SENT to them, not an attacker racing the process on their disk.
    """
    size = os.path.getsize(path)                     # OSError if it is not there
    if size > MAX_BYTES:
        raise ValueError(f"file is too large: {size} bytes, the limit is {MAX_BYTES}")
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f, parse_constant=_reject_constant)
        except RecursionError as exc:
            # Reachable from a file of pure brackets. The stack has already unwound
            # by the time this runs, so the process is in a normal state again.
            raise ValueError("nesting is too deep to read") from exc
        except MemoryError as exc:
            # Bounded by MAX_BYTES above, so this is the tail case - a small file
            # that still expands badly. Converted rather than left to escape,
            # because the reference to the half-built object dies with the frame.
            raise ValueError("not enough memory to read this file") from exc


def quarantine(path):
    """Move a broken file aside. Returns the backup path, or None."""
    try:
        # isfile, not exists: a DIRECTORY carrying one of these names is what a
        # Scoop persist leaves behind (see paths.migrate_user_files, which skips it
        # for the same reason). Renaming that to `.corrupt-<stamp>` would break the
        # user's install to punish it for not being a file.
        if not os.path.isfile(path):
            return None
        root, ext = os.path.splitext(path)
        backup = f"{root}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}{ext or ''}"
        os.replace(path, backup)
        return backup
    except OSError:
        return None


def read_json(path, expect=dict):
    """Read a JSON file.

    Returns ``(data, error)``:
      * ``(data, None)``            - success,
      * ``(None, None)``            - the file simply does not exist,
      * ``(None, "message")``       - unreadable/broken (already quarantined).
    """
    if not os.path.exists(path):
        return None, None
    try:
        data = load_json(path)
    except (OSError, ValueError) as e:
        backup = quarantine(path)
        detail = f"{e}"
        if backup:
            detail += f" -> {os.path.basename(backup)}"
        return None, detail
    if expect is not None and not isinstance(data, expect):
        backup = quarantine(path)
        detail = f"unexpected content ({type(data).__name__})"
        if backup:
            detail += f" -> {os.path.basename(backup)}"
        return None, detail
    return data, None


def write_json(path, data, indent=2):
    """Atomically write JSON. Returns an error message, or None on success.

    ``allow_nan=False`` so the WRITER refuses exactly what the READER refuses. The
    default writes ``Infinity`` and ``NaN`` happily, which would let this program
    produce a file that ``load_json`` then rejects - a corrupt-file report about a
    file we wrote ourselves, which is the worst kind of bug report to receive.

    ``TypeError`` is caught alongside the other two because it is the SAME event
    from the caller's side: a value ``json`` will not write. ``allow_nan=False``
    raises ``ValueError`` for a non-finite float, and anything json has no rule
    for at all (a set, a widget, a ``datetime``) raises ``TypeError`` - which used
    to walk straight out of here, past the temp-file cleanup, and take down
    whatever was saving. The reader's half already made this decision (see
    ``load_json``); this is the writer catching up with it.
    """
    tmp = None
    try:
        # No makedirs(): a path whose directory does not exist is an ERROR, and the
        # CLI contract says so (exit code IO). Inventing the directory would turn a
        # typo in --save-config into a silent success. `temp_beside` does not
        # create it either, so a bad path still fails here rather than succeeding.
        tmp = temp_beside(path)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return None
    except (OSError, TypeError, ValueError) as e:
        try:
            # `tmp` can still be None: temp_beside is the first thing that can
            # fail, and it fails for the commonest reason of all - no directory.
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except OSError as _exc:
            crashlog.note(_exc, "jsonfile")
        return str(e)
