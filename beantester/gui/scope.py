"""What the numbers on screen COVER - one verdict, read by every surface.

Three independent facts decide the answer, and each is set somewhere else:

* **what is CAPTURED** - the driver's filter. Normally the "Traffic to modify"
  choice; with "Capture only the targeted traffic" on, the destination
  expressions are folded into it too, so the driver never hands the rest over
  (``BeanEngine.capture_narrowed()`` - a START-time fact, fixed for the session).
* **what is IMPAIRED** - ``BeanCore.decide()`` steps 1 and 2: the process target
  and the destination target.
* **what is SHOWN** - the ``scope_view_to_target`` preference, which swaps the
  counters for their scoped twins (``App.SCOPED_TWIN``).

The notes on Statistics and Connections answer "what do these numbers cover?",
so they depend on all three - and they used to read only the third. With the
capture narrowed both notes stated the exact opposite of the truth ("ALL
captured traffic ... targeting decides what gets impaired, not what gets
listed") while the checkbox's own tooltip, one window away, promised that the
two tabs "then show only that traffic". Two shipped sentences about one
session, contradicting each other, and nothing could go red over it: prose has
no guardian (PROJECT_NOTES rule 5). Both READMEs carried the same pair.

So this module fixes the CLASS rather than the sentence. The state is derived
once, here, and every surface renders from it - the same move
``App.scoped_stat`` already made for the counters, for the same reason: a
setting must not mean one thing on one tab and something else on the next.

Why the process target gets its own state instead of a hedge in the wording:
with the capture narrowed and NO process target, everything captured is also
impaired, and a sentence like "your targeting still decides what gets impaired
inside it" would be true, useless, and would hint at a narrowing that is not
happening. With a process target it is the whole point - the tool captures the
destination's traffic from every process and impairs one process's share.

Pure (no tkinter, no engine): ``gui/__init__`` is lazy, so this imports and
unit-tests headlessly, like ``scaling`` and ``rates``.
"""
from typing import NamedTuple, Optional

# The four answers - and the whole set. A surface maps these to its own wording
# through a table keyed by all of STATES, so a fifth state goes red at its
# consumers instead of silently falling through to "everything".
ALL = "all"                         # everything the traffic filter passed
CAPTURE = "capture"                 # the driver was narrowed to the destination
CAPTURE_PROCESS = "capture_process"  # ...and a process target narrows it further
VIEW = "view"                       # the view preference is doing the narrowing

STATES = (ALL, CAPTURE, CAPTURE_PROCESS, VIEW)


def keys_for_states(mapping: dict[str, str]) -> dict[str, str]:
    """Freeze a ``state -> i18n key`` table, refusing an incomplete one.

    Each surface keeps its own table, because each says this in its own words -
    but a table missing a state would fall back to whatever ``.get()`` returned,
    which is precisely how "ALL captured traffic" came to sit over narrowed
    figures. Checked when the module is imported, so a state added later breaks
    the build instead of one screen, and an obsolete key cannot linger either.
    """
    missing = [s for s in STATES if s not in mapping]
    unknown = [s for s in mapping if s not in STATES]
    if missing or unknown:
        raise ValueError("coverage table: missing=%s unknown=%s"
                         % (missing, unknown))
    return dict(mapping)


class Coverage(NamedTuple):
    """The verdict, plus the raw facts behind it.

    The raw flags travel with it because other surfaces ask a DIFFERENT question
    of the same facts: the start-time log line reports the narrowing on its own
    ("you asked for it and did / did not get it"), which is not the same as
    "what do these numbers cover" and must not be derived from ``state``.
    """
    state: str
    capture_narrowed: bool
    view_scoped: bool
    process_target: bool


def coverage(capture_narrowed: bool, view_scoped: bool,
             process_target: bool) -> "Coverage":
    """Derive what the on-screen numbers cover. Pure; the single decider.

    ``view_scoped`` wins over ``capture_narrowed`` because it is the stronger
    claim about the same numbers: with it on, every counter with a twin IS its
    scoped twin, so the figures cover exactly what targeting selected no matter
    how wide or narrow the capture behind them was. Ordering it the other way
    would describe the capture while showing scoped figures.

    Booleans are coerced rather than trusted: the callers read a preference
    store, an engine attribute and a core flag, and one of them returning ``None``
    before the first session must not produce a fourth, unnamed state.
    """
    capture_narrowed = bool(capture_narrowed)
    view_scoped = bool(view_scoped)
    process_target = bool(process_target)
    if view_scoped:
        state = VIEW
    elif capture_narrowed:
        state = CAPTURE_PROCESS if process_target else CAPTURE
    else:
        state = ALL
    return Coverage(state, capture_narrowed, view_scoped, process_target)


def capture_scope_note(settings: dict, capture_narrowed: bool) -> Optional[str]:
    """i18n key of the line to log about the capture's scope, or ``None``.

    Asked for and got it, or asked for and did NOT: both have to be said, and
    only the second is easy to miss. "Capture only the targeted traffic"
    silently does nothing when the destination cannot be expressed as a driver
    filter - a wildcard, an ``re:`` pattern, only a process target, no
    destination at all, or a port list too long for the driver's grammar - and
    the fallback is the safe direction, so nothing else about the session looks
    unusual. The CLI has warned about this since the option shipped; the window
    said nothing at all, which left the one interface where the checkbox is
    actually visible as the one that never mentioned the outcome.

    A key rather than a logged line, and here rather than in the App: this
    module is where "what do the numbers cover?" is decided for every surface,
    and the answer stops depending on which one is asking.
    """
    if not settings.get("narrow_filter"):
        return None
    return "log.narrow_applied" if capture_narrowed else "log.narrow_no_effect"
