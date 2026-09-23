"""What every panel on the Tools tab is built from.

Twenty tools must read as siblings, and nobody reads this code line by line to
notice when the ninth one drifts. So the parts that make a panel LOOK and BEHAVE
like its neighbours live here once, and the panel files only say what is theirs.

Each piece arrives with the first panel that needs it (the expression tester,
2026-09-23, needs the two below). Work on a worker thread and the shared "Copy"
come with the first tool that has something slow to do or something to copy -
code with no user is code no test can prove, and prose that nobody checks. The
"?" help button is not here: it is the whole window's (``dialogs.help_button``).
"""
import weakref

from ... import crashlog

# The pause after the last key before a panel reacts to typing. The same quarter
# of a second the connection search waits (`gui/pages/conns.py`, measured there to
# stop a re-filter on every keystroke); a separate constant because the two are
# separate decisions that happen to agree today.
TYPING_DEBOUNCE_MS = 250

# What a person typed into a tool, per window, per tool. A language change and a
# layout reset rebuild every widget (`App._build_ui`), and the page objects with
# them - so anything kept on a panel dies there. Kept against the App instead, and
# WEAKLY, so it goes when the window does: the owner decided on 2026-09-23 that a
# tool's inputs outlive a rebuild but not the program (the same answer as the
# Control page's field search, 2026-08-18), which is why this is not in ui.json.
_INPUTS: "weakref.WeakKeyDictionary[object, dict[str, dict[str, str]]]" = \
    weakref.WeakKeyDictionary()


def remembered(app, tool_id):
    """The dict of inputs this tool keeps for this window (created empty)."""
    return _INPUTS.setdefault(app, {}).setdefault(tool_id, {})


class Debounce:
    """Run ``action`` once, a pause after the LAST call - and never after teardown.

    The shape of the connection search's debounce (``ConnsPage._schedule_search``),
    as an object, because every tool that reacts to typing needs the same three
    moves: schedule, act now (Enter), and put the timer away before a rebuild
    destroys the widget it is scheduled on - a timer firing into a destroyed
    widget raises in Tcl's background handler, where nothing reports it
    (``internal_tools/probe_lang_switch_timers.py``).
    """

    def __init__(self, widget, action, delay_ms=TYPING_DEBOUNCE_MS):
        self._widget = widget
        self._action = action
        self._delay_ms = delay_ms
        self._job = None

    def __call__(self, _event=None):
        """Schedule the action, replacing one already waiting."""
        self.cancel()
        try:
            self._job = self._widget.after(self._delay_ms, self._fire)
        except Exception as exc:
            # No widget to schedule on means no widget to show a result on either:
            # acting now would only draw into what is being torn down.
            crashlog.note(exc, "gui.toolbox")
            self._job = None

    def now(self, _event=None):
        """Act at once (Enter), dropping the one that was waiting."""
        self.cancel()
        self._action()

    def cancel(self):
        if self._job is not None:
            with crashlog.quiet("gui.toolbox"):
                self._widget.after_cancel(self._job)
            self._job = None

    def _fire(self):
        self._job = None
        self._action()
