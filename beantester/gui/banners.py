"""The red lines under the summary strip: a session that is not doing what it looks like.

Three of them, on the ROOT (so on every page), each packed only while it has
something to say:

* **rights** - this window cannot capture (not elevated, not root). Known before
  anything runs, so it is packed when the window is built. It used to be only a
  line in the log at the bottom (easy to miss) and a dialog after the click.
* **engine** - the TOOL is dropping the user's packets (a queue overflow), so the
  measured loss is partly ours. A number in a table on a page the user might never
  open, until it became a banner: a run whose numbers are WRONG must not look like a
  run that went fine (``App._drain_engine_warning`` decides it on the tick).
* **reach** - the running session impairs every connection on this computer and
  nothing ends it: no target narrows it and no run time stops it. The start-time
  warning said so once, in the log, and the window then showed "Running" over a
  browser, a messenger and a remote desktop all being impaired (UX audit
  2026-11-13, UX-GUI-003). Its words are the warning's, and the decision is the
  same ``settings.unbounded_impairment``, read from what the session was GIVEN
  (START and "Apply changes", ``session_repro``) - never from the form, where an
  edit nobody applied changes nothing yet.

Carved out of ``gui/app.py``, which sits on the file-size ratchet, and out of
``_build_ui``, which sits on the function one. The labels are App attributes
(``admin_warning``, ``engine_warning``, ``reach_warning``), declared where
``_build_ui`` calls ``build``. They are plain labels, not
``labels.wrapping_label``: their container is the persistent root, where a
per-label ``<Configure>`` binding would pile up one per rebuild, so the App's single
root handler wraps them (``wrap``).
"""
from tkinter import ttk

from .. import capture_backend, crashlog
from ..i18n import T
from ..settings import unbounded_impairment
from . import session_repro
from .scaling import scaled
from .theme import space

AREA = "gui.banners"
# The wrap before the first resize tells the App the real width (design pixels).
FIRST_WRAP = 600


def _label(root):
    return ttk.Label(root, text="", style="Bad.TLabel", justify="left", anchor="w",
                     wraplength=scaled(FIRST_WRAP))


def build(app):
    """The three banners of a fresh build (a language change rebuilds them all)."""
    app.admin_warning = None
    if not app._is_admin:
        app.admin_warning = _label(app.root)
        app.admin_warning.config(text=T(capture_backend.current().rights_banner()))
        app.admin_warning.pack(side="top", fill="x", padx=space("window"),
                               pady=(0, space("tight")))
    app.engine_warning = _label(app.root)
    app._shown_engine_warning = None
    app.reach_warning = _label(app.root)


def show(app, label, text):
    """Put ``text`` on ``label`` right under the summary strip, or take it away ("")."""
    with crashlog.quiet(AREA):
        if text:
            label.config(text=text)
            if not label.winfo_ismapped():
                # `after=summary_holder`, NOT `before=app.nb`: the notebook lives
                # inside its own holder, so it is not a sibling here and pack()
                # refuses - silently, since this is wrapped. The banner then
                # existed, reported itself as mapped, and drew nothing.
                label.pack(side="top", fill="x", padx=space("window"),
                           pady=(0, space("tight")), after=app.summary_holder)
        else:
            label.config(text="")
            label.pack_forget()


def wrap(app, width):
    """Every banner wraps at ``width`` (the root's own <Configure> handler calls it)."""
    for banner in (app.admin_warning, app.engine_warning, app.reach_warning):
        if banner is not None:
            banner.config(wraplength=width)


def reach_text(running, settings):
    """The reach banner's words for a session, "" when it has nothing to say."""
    if not running or settings is None or not unbounded_impairment(settings):
        return ""
    return T("warn.global_impairment")


def refresh_reach(app):
    """Re-decide the reach banner. Called when the session's settings change hands -
    START, "Apply changes", STOP and a rebuild - not on the tick: nothing else
    changes them, so there is no repeat to skip."""
    if app.reach_warning is not None:
        show(app, app.reach_warning, reach_text(app.running, session_repro.settings_of(app)))
