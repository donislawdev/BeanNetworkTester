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

A text longer than the strip ends at a word with an ellipsis, and the strip's bubble
then carries all of it (``fit``).

Out of ``gui/app.py``, which sits on the file-size ratchet: ``App._refresh_summary``
asks ``text`` and hands it to ``fit``; the window's resize hands its width to ``wrap``.
"""
from .. import crashlog
from ..i18n import T
from ..settings import DEFAULT_SETTINGS
from ..summary import settings_summary
from . import session_repro
from .applied import START_ONLY_KEYS
from .scaling import line_height, scaled
from .theme import space
from .tooltip import tooltip_text

# The strip's height is fixed, in lines of its text: a strip that grew with its text
# resized the notebook under it and the page jumped - while typing, mid-session. Two
# lines held one sentence; the two sentences of a long setup during a session took
# both lines at 1441 px wide (measured 2026-11-13) and a narrower window cut the
# second one off, which is the sentence that says what is waiting.
STRIP_LINES = 3
# Every impairment, asymmetry, a target and a destination, with an edit waiting, took
# six lines at the window's smallest width (1441 px at 144 DPI, measured 2026-11-13):
# a strip that grows that far would push the page down by three lines mid-session.
ELLIPSIS = "\N{HORIZONTAL ELLIPSIS}"


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
    after = dict(raw, **{key: session[key] for key in START_ONLY_KEYS if key in session})
    return (settings_summary(session, lang) + " "
            + settings_summary(after, lang, prefix_key="summary.prefix_pending"))


def text(app):
    """The strip's sentence(s) for the window as it stands."""
    raw, skipped = _described(app)
    said = _sentences(app, raw)
    return said + " " + T("summary.skips_refused") if skipped else said


def _fits(label):
    return label.winfo_reqheight() <= height()


def fit(app):
    """Show the strip's text (``App._summary_text``): whole when it fits in
    ``STRIP_LINES``, else up to the last word that fits and an ellipsis - and then
    the whole of it in the strip's bubble, above what the bubble always says.

    The label measures itself the moment its text changes (0.16 ms a change on real
    Tk, 2026-11-13), so the longest prefix that fits is found by halving, a handful
    of changes, and only for a text that does not fit.
    """
    label = app.summary
    whole = app._summary_text or str(label.cget("text"))
    tip = getattr(label, "_bnt_tooltip", None)
    with crashlog.quiet("gui.summary_strip"):
        label.config(text=whole)
        cut = not _fits(label)
        if cut:
            words = whole.split(" ")
            low, high = 0, len(words) - 1
            while low < high:
                mid = (low + high + 1) // 2
                label.config(text=" ".join(words[:mid]) + ELLIPSIS)
                low, high = (mid, high) if _fits(label) else (low, mid - 1)
            label.config(text=" ".join(words[:low]) + ELLIPSIS)
        if tip is not None:
            tip.text = (f"{whole}\n\n" if cut else "") + tooltip_text("tips.summary")


def wrap(app):
    """Follow the strip's width (the window's resize): the lines wrap at it, and a
    text cut at the old width is cut again at the new one."""
    width = app.summary_holder.winfo_width()
    if not width or width <= scaled(80):
        return
    wraplength = width - scaled(8)
    if str(app.summary.cget("wraplength")) != str(wraplength):
        app.summary.config(wraplength=wraplength)
        fit(app)
