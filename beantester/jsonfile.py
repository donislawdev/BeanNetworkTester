"""Crash-safe JSON persistence for the tool's user files.

Profiles, window state and config files are edited by hand (they live next to
the executable on purpose), they are deleted, they are copied between machines
and - if the process dies mid-write - they get truncated. None of that may take
the app down, and none of it may destroy data silently:

* **atomic writes** - the new content is written to a temporary file and then
  ``os.replace``d over the target, which is atomic on Windows and POSIX alike.
  A crash halfway through can no longer leave a half-written profile file.
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


def quarantine(path):
    """Move a broken file aside. Returns the backup path, or None."""
    try:
        if not os.path.exists(path):
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
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
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
    """Atomically write JSON. Returns an error message, or None on success."""
    tmp = f"{path}.tmp"
    try:
        # No makedirs(): a path whose directory does not exist is an ERROR, and the
        # CLI contract says so (exit code IO). Inventing the directory would turn a
        # typo in --save-config into a silent success.
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return None
    except OSError as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError as _exc:
            crashlog.note(_exc, "jsonfile")
        return str(e)
