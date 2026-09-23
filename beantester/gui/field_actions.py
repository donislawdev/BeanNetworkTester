"""Filling a Control-page field from somewhere else in the window.

Two places do this today - the right-click menu of the connection table (block
this address, leave this process alone) and the expression tester on the Tools
tab - and both must travel the SAME road into the form, or one of them will
eventually skip a step the other takes: the tk variable, the form's own copy of
the values, the dirty-state and summary refresh (``on_form_changed``), the log
line, and - during a session - the reminder that nothing reaches the engine until
the user presses Apply (convention 15).

It lives outside ``gui/app.py`` for the reason written in several places there:
that file sits on the size ratchet in ``tests/test_code_shape.py``. And outside
``gui/pages/conns.py``, where it was born, because a tool panel importing a PAGE
to reach a helper would be a sideways dependency between two things that should
not know about each other.
"""
from ..i18n import T
from ..matchers import add_term


def fill_field(app, key, value, log_key, **fmt):
    """Put ``value`` into the Control field ``key``, replacing what was there."""
    app.vars[key].set(value)
    app.form.set_values(app._settings_for_form())
    app.on_form_changed()
    app.log(f"{T(log_key, **fmt)}: {value}")
    if app.running:
        app.log(T("log.apply_needed"))


def append_to_field(app, key, term, log_key):
    """Add one term to an expression field, keeping what is already there.

    The row actions build a field up click by click - block this address, then
    that one - so they append. Replacing would throw away what the previous click
    put there, which is the opposite of what the second click means.
    ``matchers.add_term`` owns the syntax (convention 10): it drops repeats, keeps
    the comma escape of a regex intact and never leaves an empty term behind.
    """
    fill_field(app, key, add_term(app.vars[key].get(), term), log_key)
