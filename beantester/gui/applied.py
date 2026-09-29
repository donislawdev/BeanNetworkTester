"""What "Apply changes" compares the form with: the settings the session runs with.

The button lights up ("dirty") when the form differs from a fingerprint of what
the running session was given. Pure functions over the raw form values, so the
rule is testable without Tk - and kept out of ``gui/app.py``, which sits on the
file-size ratchet in tests/test_code_shape.py.
"""
from ..fields import FIELD_DEFS, UI_ONLY_KEYS

# Taken by a session at START and never by "Apply changes" (the traffic filter,
# "Run time", the narrowed capture, the seed): see ``after_apply``.
START_ONLY_KEYS = frozenset(f.key for f in FIELD_DEFS if f.start_only)


def signature(raw):
    """Fingerprint of the settings THE ENGINE would receive.

    ui_only fields (row_limit) are excluded on purpose: nothing sends them to
    the engine and the tables re-read them on every refresh, so including them
    made "Apply changes" light up for a change that was already live.
    """
    return tuple(sorted((k, str(v)) for k, v in raw.items()
                        if k not in UI_ONLY_KEYS))


def after_apply(applied, raw):
    """The fingerprint once "Apply changes" has sent ``raw`` to the session.

    ``applied`` is the fingerprint before it - START's, or the last Apply's. The
    keys a session takes only at START keep the value they had there: Apply does
    not send them, and taking them from the form marked a filter as applied that
    the engine never used (external review P2-16c, owner decision D-7). A form
    that differs there stays "dirty" until the next START, which is the truth.
    """
    kept = {k: v for k, v in (applied or ()) if k in START_ONLY_KEYS}
    return signature(dict(raw, **kept))
