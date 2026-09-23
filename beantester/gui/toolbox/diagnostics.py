"""Tools tab: environment diagnostics. The checks are ``driver.doctor()``'s own.

"Why will START not work?" answered without a console: the same report as
``--doctor``, a button that unloads a WinDivert driver left behind, and the report
copied ready for the "Environment report" field of a bug report.

The work runs off the UI thread (``base.ToolJob``): the first check imports
pydivert and asks the service manager, 163 ms measured on the development machine,
which on the UI thread is a window that stops answering - and STOP lives in that
window. The check runs by itself the first time the tab is shown; after that only
when asked, and the status line says when the rows on screen were taken.
"""
from tkinter import ttk

from ...i18n import T
from ...nettools import diagnostics
from .. import dialogs
from ..clipboard import copy_confirmed
from ..labels import wrapping_label
from ..scrollable import ScrollableFrame
from ..theme import CHARS, space
from ..tooltip import add_tooltip
from .base import Poller, StatusLine, job

AREA = "gui.toolbox.diagnostics"

# The verdict word of a row and its colour. A state doctor() does not give today
# would be shown as it is, in the muted style (``_state_text``).
STATE_TEXT = {
    diagnostics.OK: ("tools.diagnostics.state.ok", "Good.TLabel"),
    diagnostics.WARN: ("tools.diagnostics.state.warn", "Status.Warn.TLabel"),
    diagnostics.FAIL: ("tools.diagnostics.state.fail", "Status.Bad.TLabel"),
}

CHECK, CLEAN = "check", "clean"


def check_name(name):
    """A check's name in the current language - doctor's own name if it has no key yet."""
    key = diagnostics.check_key(name)
    text = T(key)
    return name if text == key else text


def _state_text(state):
    key, style = STATE_TEXT.get(state, (None, "Muted.TLabel"))
    return (T(key) if key else state.upper()), style


class DiagnosticsPanel:
    ID = "diagnostics"
    LABEL = "tools.diagnostics.tab"

    def __init__(self, app, parent):
        self.app = app
        self.job = job(app, self.ID)
        self.frame = ttk.Frame(parent)
        # Asked once: a running process does not gain or lose administrator rights.
        self.blocker = diagnostics.cleanup_blocker()

        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        self.check_btn = self._button(bar, "tools.diagnostics.check_again",
                                      "tips.tools_diagnostics_check", self.check)
        self.clean_btn = self._button(bar, "tools.diagnostics.clean",
                                      "tips.tools_diagnostics_clean", self.clean)
        self.copy_btn = self._button(bar, "tools.diagnostics.copy_report",
                                     "tips.tools_diagnostics_copy", self.copy_report)
        dialogs.help_button(bar, self.app.root, "tools.diagnostics.help_title",
                            "tools.diagnostics.help_body",
                            "tips.tools_diagnostics_help").pack(side="right")

        self.status = StatusLine(self.frame)
        self.status.label.pack(fill="x", padx=space("page"), pady=(space("row"), 0))
        # What the last cleanup said, or why there cannot be one from here.
        self.clean_note = wrapping_label(self.frame, T(self.blocker) if self.blocker else "")
        self.clean_note.pack(fill="x", padx=space("page"), pady=(space("hair"), 0))
        self.verdict = ttk.Label(self.frame, text="", style="Muted.TLabel")
        self.verdict.pack(anchor="w", padx=space("page"), pady=(space("row"), 0))

        # The rows scroll: nine checks whose details wrap to two or three lines
        # outgrow the tab at 1366x768. Labels only inside - no widget that scrolls
        # by itself (convention 14, gui/pages/control.py).
        self.scroll = ScrollableFrame(self.frame, top_margin=space("tight"))
        self.rows = None

        self.poller = Poller(self.frame, self.job, self._on_outcome)
        # What this window already knows is shown as it is; only a window that has
        # never checked asks now. A rebuild mid-run picks the answer up when it lands.
        diagnosis = self.job.value.get(CHECK)
        if diagnosis is not None:
            self._show_rows(diagnosis)
        for outcome in sorted(self.job.last.values(), key=lambda o: o.finished):
            self._show_outcome(outcome)     # the newest one is left on the status line
        if self.job.busy():
            self.status.working()
            self.poller.start()
        elif diagnosis is None:
            self.check()
        self._sync_buttons()

    # -- building ------------------------------------------------------------ #
    @staticmethod
    def _button(bar, text_key, tip_key, command):
        button = ttk.Button(bar, text=T(text_key), command=command)
        button.pack(side="left", padx=(0, space("inline")))
        add_tooltip(button, tip_key)
        return button

    # -- the page calls ------------------------------------------------------ #
    def refresh(self):
        """The tick: a session starting or stopping changes what may be pressed."""
        self._sync_buttons()

    def pending(self):
        """Take an answer that has arrived now, and say whether one is still due.

        The GUI render check calls this until it says no, so it measures the rows
        and not the empty tab a worker has yet to fill.
        """
        return self.poller.now()

    def teardown(self):
        self.poller.cancel()

    # -- acting -------------------------------------------------------------- #
    def check(self):
        self._run(CHECK, diagnostics.diagnose)

    def clean(self):
        """Unload the driver - after the person has read what that interrupts."""
        if not self._may_clean():
            return
        if not dialogs.ask_yes_no(self.app.root, T("tools.diagnostics.clean_title"),
                                  T("tools.diagnostics.clean_confirm")):
            return
        if not self._may_clean():           # a session may have begun meanwhile
            return
        # Read HERE, on the UI thread at the yes, and not by the worker when it gets
        # round to it: a START pressed in between is exactly what it must catch.
        seen = diagnostics.opens_so_far()
        self._run(CLEAN, lambda: diagnostics.clean_up(seen))

    def copy_report(self):
        diagnosis = self.job.value.get(CHECK)
        if diagnosis is None:
            return
        copy_confirmed(self.app, diagnostics.report(diagnosis),
                       T("tools.diagnostics.report_logged"), AREA)

    def _run(self, kind, work):
        self.job.run(kind, work)
        self.status.working()
        self._sync_buttons()
        self.poller.start()

    def _session_busy(self):
        # `_transition` is the start or stop in flight, which `running` does not
        # cover: the driver handle opens before `running` turns True and closes
        # after it turns False. A page reading App's own state, as the Settings
        # window reads `_raw_settings` - App has no line to spare for an accessor.
        return bool(self.app.running) or getattr(self.app, "_transition", None) is not None

    def _may_clean(self):
        return not self.blocker and not self._session_busy() and not self.job.busy()

    def _sync_buttons(self):
        busy = self.job.busy()
        self.check_btn.state(["disabled"] if busy else ["!disabled"])
        self.clean_btn.state(["!disabled"] if self._may_clean() else ["disabled"])
        has_rows = self.job.value.get(CHECK) is not None
        self.copy_btn.state(["!disabled"] if has_rows else ["disabled"])

    # -- showing ------------------------------------------------------------- #
    def _on_outcome(self, outcome):
        if outcome.kind == CHECK and not outcome.error:
            self._show_rows(outcome.value)
        self._show_outcome(outcome)
        if outcome.kind == CLEAN and not outcome.error:
            for line in outcome.value:
                self.app.log(f"{T('log.driver')}: {line}")
            self.check()                    # the driver row is stale now
        self._sync_buttons()

    def _show_outcome(self, outcome):
        self.status.show(outcome)
        if outcome.kind == CLEAN and not outcome.error:
            self.clean_note.config(text="\n".join(outcome.value))

    def _show_rows(self, diagnosis):
        # A new container every time, not new children in the old one: each
        # wrapping label binds <Configure> on its container and nothing unbinds it
        # (gui/labels.py), so refilling one frame would leave a dead handler per
        # row per "Check again" - bindings that die with the frame they are on.
        if self.rows is not None:
            self.rows.destroy()
        self.rows = ttk.Frame(self.scroll.body)
        self.rows.pack(fill="x", padx=space("page"), pady=(0, space("row")))
        key, style = (("tools.diagnostics.verdict_ok", "Good.TLabel") if diagnosis.ok
                      else ("tools.diagnostics.verdict_fail", "Status.Bad.TLabel"))
        self.verdict.config(text=T(key), style=style)
        for index, found in enumerate(diagnosis.checks):
            head = ttk.Frame(self.rows)
            head.pack(fill="x", pady=(space("row") if index else 0, 0))
            word, word_style = _state_text(found.state)
            ttk.Label(head, text=word, style=word_style, width=CHARS["state"]).pack(side="left")
            ttk.Label(head, text=check_name(found.name)).pack(side="left")
            # The program's own words, as --doctor prints them: a bug report quotes
            # these, and the "?" sheet explains them in the reader's language.
            wrapping_label(self.rows, found.detail).pack(fill="x", pady=(space("hair"), 0))
        wrapping_label(self.rows, T("about.data_dir", path=diagnosis.data_dir)).pack(
            fill="x", pady=(space("row"), 0))
