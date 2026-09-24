"""What every panel on the Tools tab is built from.

Twenty tools must read as siblings, and nobody reads this code line by line to
notice when the ninth one drifts. So the parts that make a panel LOOK and BEHAVE
like its neighbours live here once, and the panel files only say what is theirs.

Each piece arrives with the first panel that needs it - code with no user is code
no test can prove, and prose that nobody checks. The expression tester
(2026-09-23) brought the remembered inputs and the typing pause; diagnostics (the
first tool with something slow to do) brought the worker, its poll and the status
line. The "?" help button and the shared "Copy" are not here: they belong to the
whole window (``dialogs.help_button``, ``gui/clipboard.py``).
"""
import time
import weakref
from typing import NamedTuple

from ...i18n import T
from ...nettools import Refused
from ..labels import wrapping_label
from ..model_worker import AsyncModel
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


# -- work off the UI thread ------------------------------------------------------ #
# How often a panel looks for its worker's answer while one is due: the connection
# table's catch-up poll (`ConnsPage.POLL_MS`), fast enough to feel instant and
# stopped as soon as nothing is due - so an idle tab costs no timer at all.
POLL_MS = 40


class Outcome(NamedTuple):
    """What one run of a tool's work came to - an answer, or why there is none."""
    kind: str           # what was asked ("check", "clean"...): one worker per panel
    value: object       # the answer; None when the work failed
    error: str          # "" on success, else the exception - program text
    elapsed_ms: int
    finished: float     # time.time() at the end: a result says how old it is
    # An i18n key for a failure the tool KNOWS and can put in words - the exception
    # carries it as `user_key` (e.g. nettools.sockets.Unreadable). "" for any other
    # failure, which the status line then shows as program text.
    error_key: str = ""
    # What that sentence says in numbers ("1001 ports, 1000 at most"), from the
    # exception's `user_args`, as sorted pairs so an Outcome stays immutable.
    error_args: tuple = ()


def _guarded(payload):
    """Runs on the WORKER: do the work, and turn ANY failure into an Outcome.

    ``AsyncModel`` answers a raising build by keeping the old model and saying
    nothing - right for a table mid-session, and for a tool it would mean a status
    line reading "working" for ever. BaseException for the reason the worker gives
    (``gui/model_worker.py::_run``): a build that ends any other way is the one
    that is never heard of again.
    """
    kind, work = payload
    started = time.perf_counter()
    error_key, error_args = "", ()
    try:
        value, error = work(), ""
    except BaseException as exc:
        # A refusal of what was asked is an answer for the person, not a fault of
        # the program (``nettools.Refused``). Anything else is recorded whole.
        if not isinstance(exc, Refused):
            crashlog.note(exc, "gui.toolbox")
        value, error = None, f"{type(exc).__name__}: {exc}"
        # Said in the window's language when the tool can name it; the crash log
        # above keeps the whole exception either way.
        error_key = str(getattr(exc, "user_key", "") or "")
        error_args = tuple(sorted((getattr(exc, "user_args", None) or {}).items()))
    return Outcome(kind, value, error, round((time.perf_counter() - started) * 1000),
                   time.time(), error_key, error_args)


class ToolJob:
    """One tool's worker in one window, and what it last answered.

    Kept against the App like ``remembered``, not on the panel: a language change
    rebuilds the panel while the work is still running, and the answer - a list of
    what the driver cleanup did, say - must reach the panel that exists when it
    arrives, not die with the one that asked. ``last`` holds the latest outcome of
    each kind and ``value`` the latest ANSWER, so a failed re-check does not wipe
    rows that were true a minute ago.

    The worker is ``gui/model_worker.AsyncModel`` unchanged: coalescing (a request
    made while one runs waits, the newest wins), stale results dropped, and the
    BaseException handling paid for there.
    """

    def __init__(self, name):
        self._model = AsyncModel(_guarded, name=name)
        self.last = {}          # kind -> Outcome
        self.value = {}         # kind -> the latest successful Outcome.value

    def run(self, kind, work):
        """Start ``work()`` on the worker (UI thread; never blocks)."""
        self._model.request((kind, work))

    def busy(self):
        """A run is in flight OR its answer has not been collected yet."""
        return self._model.busy()

    def collect(self):
        """UI thread: the Outcome that has arrived since the last call, or None."""
        outcome = self._model.poll()
        if outcome is not None:
            self.last[outcome.kind] = outcome
            if not outcome.error:
                self.value[outcome.kind] = outcome.value
        return outcome


_JOBS: "weakref.WeakKeyDictionary[object, dict[str, ToolJob]]" = weakref.WeakKeyDictionary()


def job(app, tool_id):
    """This tool's worker for this window (created on first use, kept across rebuilds)."""
    jobs = _JOBS.setdefault(app, {})
    if tool_id not in jobs:
        jobs[tool_id] = ToolJob("tool-" + tool_id)
    return jobs[tool_id]


class Poller:
    """Look for a job's answer every ``POLL_MS`` while one is due, and hand it over.

    The shape of the connection table's ``_poll_soon`` as an object, for the same
    reason ``Debounce`` is one: every tool with a worker needs the same three
    moves - start looking, look NOW (the render check will not wait for a timer),
    and put the timer away before a rebuild destroys the widget it is scheduled on.
    """

    def __init__(self, widget, job, on_outcome):
        self._widget = widget
        self._job = job
        self._on_outcome = on_outcome
        self._timer = None

    def start(self):
        """Look again in ``POLL_MS`` if an answer is due; do nothing otherwise."""
        self.cancel()
        if not self._job.busy():
            return
        with crashlog.quiet("gui.toolbox"):
            self._timer = self._widget.after(POLL_MS, self.now)

    def now(self):
        """Take an answer that has arrived, hand it over, and keep looking if one is due."""
        # Cancelled, not just forgotten: `pending()` calls this while a timer is
        # armed, and a forgotten one keeps re-arming beside the new one - a second
        # chain that `cancel()` cannot reach and a rebuild leaves firing into a
        # destroyed widget. From the timer itself this cancels an id that has
        # already fired, which Tk ignores.
        self.cancel()
        outcome = self._job.collect()
        if outcome is not None:
            self._on_outcome(outcome)
        self.start()
        return self._job.busy()

    def cancel(self):
        if self._timer is not None:
            with crashlog.quiet("gui.toolbox"):
                self._widget.after_cancel(self._timer)
            self._timer = None


class StatusLine:
    """The line under a tool's buttons: working, done at what time and how fast, or failed.

    The time of day is on it because a result outlives the moment it was taken - a
    panel rebuilt after a language change shows the last answer rather than
    asking again, and "done at 14:02:11" says how old that answer is.
    """

    def __init__(self, parent):
        self.label = wrapping_label(parent, "")

    def working(self):
        self.label.config(text=T("tools.common.working"), style="Muted.TLabel")

    def refused(self, text):
        """An input the tool will not run with, in a sentence already made for the
        person (the port language's parser writes it in the window's language)."""
        self.label.config(text=text, style="Status.Bad.TLabel")

    def show(self, outcome):
        if outcome.error:
            # A failure the tool can name is said in the window's language; any
            # other is shown as the program's own words, the way --doctor prints them.
            error = (T(outcome.error_key, **dict(outcome.error_args)) if outcome.error_key
                     else outcome.error)
            self.label.config(text=T("tools.common.failed", error=error),
                              style="Status.Bad.TLabel")
            return
        at = time.strftime("%H:%M:%S", time.localtime(outcome.finished))
        self.label.config(text=T("tools.common.done", time=at, ms=outcome.elapsed_ms),
                          style="Muted.TLabel")
