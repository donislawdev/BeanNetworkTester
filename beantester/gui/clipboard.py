"""Copying to the clipboard - and saying so only when it worked.

One road for every "Copy" button that puts a whole text on the clipboard (the
Statistics panels, the Tools tab's report): ``App.copy_to_clipboard`` writes, and
the clipboard is then READ BACK before the log says "copied". That method logs its
own failure and returns nothing, so a success line printed blindly next to it
would contradict the error the user just read - the read-back is what makes the
confirmation true.

The connection table and the event log copy their selected ROWS through the table
widget itself (``gui/widgets/sortable_tree.py``): a selection, a keyboard shortcut
and no App to log to - a different job, not a copy of this one.
"""
from ..i18n import T
from .. import crashlog


def copy_confirmed(app, text, logged, area="gui.clipboard"):
    """Put ``text`` on the clipboard; log ``copied: <logged>`` once it is there.

    Returns True when the read-back matched. ``logged`` is what the log line
    names - the text itself for a single value, a short description for a
    report that would flood the log.
    """
    if not text:
        return False
    app.copy_to_clipboard(text)
    with crashlog.quiet(area):
        if app.root.clipboard_get() == text:
            app.log("%s: %s" % (T("log.copied"), logged))
            return True
    return False
