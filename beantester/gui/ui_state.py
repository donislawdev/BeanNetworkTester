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
        return data or {}

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
