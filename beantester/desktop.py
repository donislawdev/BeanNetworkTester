"""The Linux package's entry in the desktop's applications menu.

``BeanNetworkTester --install-desktop`` writes one Desktop Entry file into the
person's ``$XDG_DATA_HOME/applications`` (else ``~/.local/share/applications``),
and ``--remove-desktop`` removes that file again (owner decision 2026-10-28: a
command-line option, not a script in the archive and not a button).

What the entry is, and why:

* ``Exec`` is the program itself, not pkexec: the window asks for root on its
  own (``linuxenv``). The path is absolute, so a folder moved after this points
  at nothing; running the option again from the new place repairs it.
* ``StartupWMClass`` is the window's class. Tk's default is "Tk" (measured with
  xwininfo on the package), and GNOME shows a window whose class matches no entry
  as a program of its own in the dock, without the entry's name and icon - so the
  window's root is created with ``className=WINDOW_CLASS`` (``cli._run_gui``).
* Only the package (a frozen build on Linux): from sources ``Exec`` would be an
  interpreter in a virtual environment, which is a different question.
* Never as root: under ``sudo`` the file would be root's, in the person's folder.

Quoting follows the Desktop Entry Specification ("The Exec key"): the path goes in
double quotes with ``"``, `````, ``$`` and ``\\`` escaped by a backslash, ``%`` is
written ``%%``, and the value's own string escapes (``\\`` for a backslash) apply
on top. A path with a control character is refused rather than encoded.
"""
import os
import posixpath
import sys

from . import appinfo, crashlog, paths

ENTRY_ID = "com.donislawdev.BeanNetworkTester"   # reverse DNS, as the spec recommends
FILE_NAME = ENTRY_ID + ".desktop"
# Already in the form Tk gives a class: the first letter up, the rest down. MEASURED
# 2026-10-28 (xwininfo on the package): className "BeanNetworkTester" became the
# class "Beannetworktester", so an entry naming "BeanNetworkTester" matched nothing.
WINDOW_CLASS = "Beannetworktester"
ICON_NAME = "bean.png"
COMMENT = "Simulate a poor network: latency, loss, jitter, a narrow link"

_EXEC_ESCAPED = '"`$\\'


def applications_dir(environ=None):
    """``$XDG_DATA_HOME/applications`` (absolute only, as the XDG spec says), else
    ``~/.local/share/applications``."""
    environ = os.environ if environ is None else environ
    data_home = environ.get("XDG_DATA_HOME", "")
    if not posixpath.isabs(data_home):
        data_home = posixpath.join(environ.get("HOME") or os.path.expanduser("~"),
                                   ".local", "share")
    return posixpath.join(data_home, "applications")


def _refused(path):
    return any(ord(c) < 32 or ord(c) == 127 for c in path)


def exec_value(program):
    """``program`` as one quoted argument of an ``Exec`` key."""
    quoted = "".join("\\" + c if c in _EXEC_ESCAPED else c for c in program)
    return ('"' + quoted + '"').replace("\\", "\\\\").replace("%", "%%")


def string_value(text):
    """``text`` as a Desktop Entry string value (its backslash escape)."""
    return text.replace("\\", "\\\\")


def entry_text(program, icon):
    """The whole Desktop Entry file for ``program`` with ``icon``."""
    return "\n".join((
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.5",
        f"Name={appinfo.APP_NAME}",
        f"Comment={COMMENT}",
        f"Exec={exec_value(program)}",
        f"Icon={string_value(icon)}",
        "Terminal=false",
        "Categories=Network;",
        f"StartupWMClass={WINDOW_CLASS}",
        "",
    ))


def why_not():
    """Why this run cannot add or remove the entry, or None when it can."""
    if not sys.platform.startswith("linux"):
        return "the menu entry is for the Linux package; this is not Linux"
    if not paths.is_frozen():
        return ("the menu entry is for the Linux package (the .tar.gz); from sources, "
                "start bean_network_tester.py as the README says")
    if paths.running_as_root():
        return "run it without sudo: the entry belongs to you, and root's would stay root's"
    return None


def install(program=None, icon=None, environ=None):
    """Write the entry. Returns ``(path, None)``, or ``(None, why)`` when it was not
    written. ``program`` and ``icon`` default to this package's."""
    reason = why_not()
    if reason:
        return None, reason
    program = sys.executable if program is None else program
    icon = paths.resource_path(ICON_NAME) if icon is None else icon
    for path in (program, icon):
        if _refused(path):
            return None, f"the path {path!r} holds a control character; move the folder"
    folder = applications_dir(environ)
    target = posixpath.join(folder, FILE_NAME)
    temporary = target + ".tmp"
    try:
        paths.make_dirs(folder)
        # The person's umask decides who may read it, as for any file they make;
        # the menu needs no execute bit, and open() never sets one.
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(entry_text(program, icon))
        os.replace(temporary, target)
    except OSError as exc:
        with crashlog.quiet("desktop.temporary"):      # nothing half-written left behind
            if os.path.lexists(temporary):
                os.unlink(temporary)
        return None, f"cannot write {target}: {exc.strerror or exc}"
    return target, None


def remove(environ=None):
    """Remove the entry. Returns ``(path, None)`` when one was removed, ``(None,
    None)`` when there was none, ``(None, why)`` when it could not be."""
    reason = why_not()
    if reason:
        return None, reason
    target = posixpath.join(applications_dir(environ), FILE_NAME)
    try:
        os.unlink(target)
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"cannot remove {target}: {exc.strerror or exc}"
    return target, None
