"""What the session in this window ran with, and the two repro actions built on it.

"Save repro report" and "Copy CLI command" describe a SESSION: its seed, its
counters, its events. They used to take the settings from the FORM (external
review, P2-15), so an edit nobody applied went into the command next to the seed
of a session that never ran with it, a profile loaded after STOP replaced the
finished session's settings in its own report, and one field left mid-edit made
that report impossible to save. The settings are now recorded where they reach
the engine - a START that succeeded, and every "Apply changes" that did - and the
repro is built from that record (``repro.session_command`` adds what only the
engine knows: the seed, the scenario, a stand-in driver).

Carved out of ``gui/app.py`` like ``csv_export``: App sits on the file-size and
both class ratchets in tests/test_code_shape.py, so the record is kept here, per
App, and not as an attribute (the ``crash._FORMS`` shape). Weak, so a test that
builds many Apps keeps none alive. ``App.save_repro`` and ``App.copy_repro_cli``
stay as the names the buttons and the smoke script call.
"""
import os
import weakref
from tkinter import filedialog

from .. import paths
from ..i18n import T
from ..repro import save_repro_report, session_command, settings_to_cli_string
from ..scenario import load_scenario_file
from ..settings import apply_settings
from . import dialogs

# App -> the settings its current (or last) session runs with. Written on the main
# thread only; read on any thread by the crash report (a dict is replaced, never
# changed in place, so a reader holds a whole one).
_SESSIONS: weakref.WeakKeyDictionary[object, dict] = weakref.WeakKeyDictionary()


def started(app, settings):
    """A START succeeded with ``settings``: they describe the session from now on."""
    _SESSIONS[app] = dict(settings)


def apply(app, settings):
    """A live "Apply changes": ``settings`` to the engine, and into the record.

    While a scenario plays, its runner applies them and lays every later step
    over them (``BeanEngine.rebase_scenario``, owner decision D-6) - applied
    here instead, the next step put the START settings back. So the record takes
    them in either case (owner decision D-28): the command, these settings plus
    ``--scenario``, repeats the session as it runs from this Apply on.
    Not once STOP has begun: the window stays "running" until the stop finishes
    on its worker thread, but the engine has already ended the session, so an
    Apply in that gap describes a session that never ran.
    """
    engine = app.engine
    if not engine.rebase_scenario(settings, app.log):
        apply_settings(engine, settings, app.log)
    if engine.is_running():
        _SESSIONS[app] = dict(settings)


def settings_of(app):
    """The recorded session settings, or None before this window started one."""
    return _SESSIONS.get(app)


def _report_settings(app):
    # The form only when this window never started a session (the engine ran
    # without it - scripts, tests); then it is the only description there is.
    recorded = settings_of(app)
    return recorded if recorded is not None else app._settings_from_widgets()


def save(app):
    if app.engine.effective_seed() is None:
        app.log(T("log.start_first"))
        return
    path = filedialog.asksaveasfilename(title=T("dialogs.save_repro"),
                                        defaultextension=".json",
                                        filetypes=[("JSON", "*.json")])
    if not path:
        return
    try:
        report = save_repro_report(path, app.engine, _report_settings(app))
        app.log(f"{T('log.repro_saved_to')} {os.path.basename(path)}")
        app.log(f"{T('log.repro_command')}: {report['cli_command']}")
    except Exception as e:
        dialogs.show_error(app.root, T("log.error"),
                           f"{T('dialogs.report_not_saved')}: {e}")


def copy_command(app):
    try:
        recorded = settings_of(app)
        if recorded is None:
            # No session yet: the command the form WOULD run.
            cli = settings_to_cli_string(app._settings_from_widgets(),
                                         seed=app.engine.effective_seed())
        else:
            cli = session_command(app.engine, recorded)
        app.copy_to_clipboard(cli)
        app.log(f"{T('log.copied')}: {cli}")
    except Exception as e:
        app.log(f"{T('log.not_copied')}: {e}")


def read_scenario(path, log):
    """Load a scenario picked in the file dialog, named the way a command names it.

    ``log`` hears what loads but will not act (a step setting what a session
    takes only at START - external review P3-12), as the CLI's log does.
    """
    scenario = load_scenario_file(path)
    scenario.source = command_path(path)
    for warning in scenario.warnings:
        log(warning)
    return scenario


def command_path(path):
    """A scenario file as the repro command names it (owner decision 2026-09-29).

    The file dialog hands back an absolute path, which carries the Windows account
    name into every report somebody shares. A scenario that ships with the program
    is named from the program's folder instead, so it is short, carries no account
    name, and runs on any install: ``scenarios\\x.json`` from the sources,
    ``_internal\\scenarios\\x.json`` next to the frozen executable. The exe is on
    PATH after every install, so the command is run from other folders too;
    ``paths.shipped_scenario`` finds the file there. Any other file is named as it
    was chosen.
    """
    home = paths.executable_dir() if paths.is_frozen() else paths.PROJECT_ROOT
    here = os.path.abspath(path)
    shipped = os.path.normcase(os.path.abspath(paths.scenarios_dir()))
    # The same drive, asked first: across drives there is no relative name, and
    # relpath would raise for it.
    same_drive = (os.path.normcase(os.path.splitdrive(here)[0])
                  == os.path.normcase(os.path.splitdrive(os.path.abspath(home))[0]))
    if same_drive and os.path.normcase(os.path.dirname(here)) == shipped:
        return os.path.relpath(here, home)
    return path
