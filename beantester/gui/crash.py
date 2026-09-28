"""Everything the GUI tells the crash logger, in one place.

Two things go from the App to :mod:`beantester.crashlog`, and they are opposites,
which is why they belong side by side rather than scattered through ``app.py``:

* **the report context** - rich, expensive, and PULLED at the moment a Python-level
  failure is recorded (``crashlog.set_context_provider``). It carries the seed and
  the settings, because a crash report should be one step away from a REPRO rather
  than something to read. It is pulled on WHICHEVER thread failed, so it reads only
  plain data: the form comes from a copy the main thread takes every tick, never
  from a Tk variable (see ``context``).
* **the breadcrumb** - three facts, cheap, and PUSHED to disk before anything goes
  wrong. A hard (C-level) crash writes a stack and nothing else: ``faulthandler``
  cannot ask a provider, so whatever the tool was doing has to already be on disk.
  The reported crash is exactly that shape - an access violation inside ``tkinter
  mainloop`` with no Python frame above it - and its report says nothing about
  which page was open or whether a session was running.

They live here rather than on ``App`` because ``gui/app.py`` sits ON the size
ratchet in ``tests/test_code_shape.py`` (it was exactly at the ceiling), and that
guard's answer is to put code where it belongs rather than to raise the number -
the same reasoning that moved the Connections row actions onto their own page.
This is not GUI logic; it is what the GUI hands to the crash logger.

Both reach into App attributes on purpose. This is the App's own package, and the
alternative - widening five private attributes into a public surface so one
neighbour can read them - would freeze more, not less.
"""
import weakref

from .. import crashlog
from ..repro import settings_to_cli_string
from ..settings import settings_from_raw

# The raw form as the MAIN thread last read it, per App - the only way a report
# written on another thread may learn what the form held. Kept here and not on
# App, because App sits exactly on both class ratchets in tests/test_code_shape.py
# (attributes and methods). Weak, so a test that builds many Apps keeps none alive.
_FORMS: weakref.WeakKeyDictionary[object, dict] = weakref.WeakKeyDictionary()


def install(app):
    """Make every crash from now on carry this App's state. Call once, at build."""
    crashlog.set_context_provider(lambda: context(app))


def context(app):
    """App state attached to every crash report (see crashlog.set_context_provider).

    The point is that a crash report should be one step away from a REPRO, not just
    something to read: the seed and the settings are what make the failure happen
    again.

    This runs on whichever thread recorded the fault, so it touches PLAIN data only
    - and each of the three things it no longer does deadlocked the program
    (reproduced 2026-09-28): it read the form through Tk variables (a worker's Tcl
    call waits for the main loop, which may be waiting on the crash log); it took
    the engine's statistics lock (``last_snapshot`` is the same numbers, one tick
    old, lock-free); and on an invalid field it recorded that error into the crash
    log whose lock its caller held. An invalid field is now a fact in the report.

    A real failure in here is still recorded, and that is safe now: the logger
    holds no lock while this runs, and a fault recorded from inside it is written
    without asking this function again (``crashlog._collect_context``). What is
    filled in before the failure stays in the report.
    """
    state = {"page": app._page_id, "running": app.running}
    with crashlog.quiet("gui.crash"):
        _fill(app, state)
    return state


def _fill(app, state):
    state["seed"] = app.engine.effective_seed()
    if app.last_snapshot is not None:
        state["counters"] = dict(app.last_snapshot)
    state["log_tail"] = list(app._log_lines[-crashlog.MAX_LOG_TAIL:])
    state["open_windows"] = app.windows.open_ids()
    raw = _FORMS.get(app)
    if raw is None:
        return                      # a fault before the first tick read the form
    try:
        settings = settings_from_raw(raw, app._lang)
    except ValueError as exc:       # what a user mid-typing leaves in a field
        state["settings_error"] = str(exc)
        state["form"] = raw
        return
    state["settings"] = settings
    state["repro_command"] = settings_to_cli_string(settings, seed=state["seed"])


def leave_breadcrumb(app):
    """Put the three facts a NATIVE crash report cannot carry on disk.

    Called from the App's TICK rather than from the three places that change this
    state (page switch, start/stop, window open/close), and that is not laziness:
    the tick is the one call site that cannot be forgotten when a fourth piece of
    state appears. It is affordable only because the de-duplication lives in
    ``crashlog.breadcrumb``, so an unchanged state costs a dict comparison and
    touches no disk - writing 1.4 times a second for the life of the process is
    precisely the unbounded-disk failure ``crashlog``'s own docstring names.

    Deliberately SMALL. The seed and the settings belong to ``context`` above, not
    to a file rewritten whenever the user changes tab.

    The same tick also copies the raw form for ``context`` - in memory, no disk -
    for the same reason: it is the main thread, and it cannot be forgotten. The
    read is the cheap one (no parsing, no regex); the parsing happens only when a
    report is actually written.
    """
    crashlog.breadcrumb(page=app._page_id, running=app.running,
                        windows=app.windows.open_ids())
    with crashlog.quiet("gui.crash"):   # a broken read must not cost the tick its rest
        _FORMS[app] = app._raw_settings()
