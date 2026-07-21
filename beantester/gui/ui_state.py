"""Persistence of UI state (window geometry, active page, collapsed sections...).

Deliberately separate from ``ProfileStore``: a profile describes the *network*,
this describes the *window*. Corruption or an unwritable directory must never
break startup, so every failure degrades to the defaults.
"""
from ..jsonfile import read_json, write_json
from ..paths import UI_STATE_FILE

DEFAULTS = {
    "geometry": "",           # "WxH+X+Y", validated against the current screen
    "page": "control",
    "stats_page": "live",
    "language": "",
    "collapsed": [],          # ids of collapsed Control-page sections
    "log_height": 0,          # PanedWindow sash position (px)
    "conn_sort": {"col": "kb", "reverse": True},
    "event_sort": {"col": "t", "reverse": False},
    "profile": "",
}


class UiStateStore:
    """Small JSON-backed key/value store for window state."""

    def __init__(self, path=UI_STATE_FILE):
        self.path = path
        self.problem = None
        self.data = dict(DEFAULTS)
        self.data.update(self._load())

    def _load(self):
        data, error = read_json(self.path, expect=dict)
        if error:
            self.problem = error
            return {}
        clean, dropped = self._clean(data or {})
        if dropped:
            self.problem = f"window-state keys ignored: {', '.join(sorted(dropped))}"
        return clean

    @staticmethod
    def _clean(data):
        """Drop values whose TYPE is not the one ``DEFAULTS`` promises.

        ``read_json`` guarantees the file is a dict and nothing beyond that. Inside
        it, a hand edit - and these files are meant to be hand-edited, they live
        next to the executable - can leave any value any shape. Three of them used
        to stop the app from starting at all: a list under ``page`` (unhashable as
        a dict key), a list under ``conn_sort``, a string under ``event_sort``.
        The promise at the top of this module is the exact opposite, so it is now
        enforced instead of hoped for. Same shape as ``ProfileStore._clean``, which
        has always done this for the other user file.

        Only the TYPE is checked, deliberately. Measured: every wrong VALUE of the
        right type already degrades gracefully - an unknown page id, a nonsense
        geometry string, a negative sash position, a sort column that does not
        exist - so validating further would add rules that catch nothing.

        Unknown keys are KEPT. ``get`` only reads keys it knows, so they cost
        nothing, and dropping them would silently discard state written by a newer
        version of the app.
        """
        clean, dropped = {}, []
        for key, value in data.items():
            default = DEFAULTS.get(key)
            if default is not None and not isinstance(value, type(default)):
                dropped.append(str(key))
                continue
            clean[key] = value
        return clean, dropped

    def get(self, key, default=None):
        value = self.data.get(key, DEFAULTS.get(key, default))
        return DEFAULTS.get(key, default) if value is None else value

    def set(self, key, value):
        self.data[key] = value

    def update(self, **kw):
        self.data.update(kw)

    def persist(self):
        """Write the state; return an error message or None."""
        error = write_json(self.path, self.data)
        if error:
            self.problem = error
        return error
