"""The strip under the title: what the session does now, and what is waiting.

Three states, each its own sentence (``summary.settings_summary`` builds them):

* **stopped** - "Preview: ..." - what START would apply.
* **running, nothing waiting** - "Active: ..." - what the session runs with.
* **running, an edit not applied** - TWO sentences: "Active: X. After Apply
  changes: Y." It was one, "Not applied yet: <the whole form>", which mixed the
  +200 ms that had been running since START with the 10% loss that was only
  typed - nobody could tell which half was live (UX audit 2026-11-13,
  UX-GUI-004). X is the record of what START and "Apply changes" gave the session
  (``session_repro``); Y is the form as Apply would send it: the keys a session
  takes only at START keep the session's value, exactly as ``applied.after_apply``
  keeps them for the button.

A field the form refuses (red) is described at its default, and the strip says so:
neither START nor Apply runs with it, so "250% loss" or "+-5 ms ping" described a
session that cannot happen (UX-GUI-013).

Out of ``gui/app.py``, which sits on the file-size ratchet: ``App._refresh_summary``
asks ``text`` and puts the answer on the widget.
"""
from ..i18n import T
from ..settings import DEFAULT_SETTINGS
from ..summary import settings_summary
from . import session_repro
from .applied import START_ONLY_KEYS
from .scaling import line_height
from .theme import space

# The strip's height is fixed, in lines of its text: a strip that grew with its text
# resized the notebook under it and the page jumped - while typing, mid-session. Two
# lines held one sentence; the two sentences of a long setup during a session took
# both lines at 1441 px wide (measured 2026-11-13) and a narrower window cut the
# second one off, which is the sentence that says what is waiting.
STRIP_LINES = 3


def height():
    """The strip's fixed height in pixels."""
    return line_height() * STRIP_LINES + space("tight")


def _described(app):
    """The form's raw values, every field it refuses read as its default, and
    whether there was one."""
    raw = app._raw_settings()
    form = getattr(app, "form", None)
    refused = form.refused_keys() if form is not None else frozenset()
    if not refused:
        return raw, False
    return {key: (DEFAULT_SETTINGS[key] if key in refused else value)
            for key, value in raw.items()}, True


def _sentences(app, raw):
    lang = app._lang
    if not app.running:
        return settings_summary(raw, lang, prefix_key="summary.prefix_preview")
    session = session_repro.settings_of(app)
    if not app._is_dirty():
        return settings_summary(raw if session is None else session, lang)
    if session is None:     # an engine this window did not start: only the form is known
        return settings_summary(raw, lang, prefix_key="summary.prefix_pending")
    after =dict(raw, **{key: session[key] for key in START_ONLY_KEYS if key in session})
    return (settings_summary(session, lang) + " "
            + settings_summary(after, lang, prefix_key="summary.prefix_pending"))


def text(app):
    """The strip's sentence(s) for the window as it stands."""
    raw, skipped = _described(app)
    said = _sentences(app, raw)
    return said + " " + T("summary.skips_refused") if skipped else said
