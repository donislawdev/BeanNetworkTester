"""Everything the GUI tells the crash logger, in one place.

Two things go from the App to :mod:`beantester.crashlog`, and they are opposites,
which is why they belong side by side rather than scattered through ``app.py``:

* **the report context** - rich, expensive, and PULLED at the moment a Python-level
  failure is recorded (``crashlog.set_context_provider``). It carries the seed and
  the settings, because a crash report should be one step away from a REPRO rather
  than something to read.
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
from .. import crashlog
from ..repro import settings_to_cli_string


def install(app):
    """Make every crash from now on carry this App's state. Call once, at build."""
    crashlog.set_context_provider(lambda: context(app))


def context(app):
    """App state attached to every crash report (see crashlog.set_context_provider).

    The point is that a crash report should be one step away from a REPRO, not just
    something to read: the seed and the settings are what make the failure happen
    again.
    """
    state = {"page": app._page_id, "running": app.running}
    try:
        state["seed"] = app.engine.effective_seed()
        state["counters"] = dict(app.engine.stats_snapshot())
        settings = app._settings_from_widgets()
        state["settings"] = settings
        state["repro_command"] = settings_to_cli_string(
            settings, seed=app.engine.effective_seed())
        state["log_tail"] = list(app._log_lines[-crashlog.MAX_LOG_TAIL:])
        state["open_windows"] = app.windows.open_ids()
    except Exception as _exc:
        crashlog.note(_exc, "gui.app")
    return state


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
    """
    crashlog.breadcrumb(page=app._page_id, running=app.running,
                        windows=app.windows.open_ids())
