"""Persistence of user-defined profiles (JSON file next to the app).

A profile stores the 7 link-characteristic fields a preset stores (see
``presets.settings_to_preset``). The file is the user's - it can be edited,
deleted or corrupted between two runs, and none of that may break startup or
destroy the rest of the profiles.
"""
from ..jsonfile import read_json, write_json
from ..paths import PROFILE_FILE
from ..presets import PRESET_TO_SETTING

VALUE_KEYS = tuple(PRESET_TO_SETTING)          # loss, corrupt, dup, lat, jit, down, up


class ProfileStore:
    """Loads/saves the user's own presets. Failures never break the app."""

    def __init__(self, path=PROFILE_FILE):
        self.path = path
        self.problem = None          # last load/save error, for the log
        self.profiles = self._load()

    def _load(self):
        data, error = read_json(self.path, expect=dict)
        if error:
            # the broken file was moved aside; start clean rather than overwrite it
            self.problem = error
            return {}
        if not data:
            return {}
        clean, dropped = {}, []
        for name, values in data.items():
            entry = self._clean(values)
            if entry is None:
                dropped.append(str(name))
            else:
                clean[str(name)] = entry
        if dropped:
            self.problem = f"invalid profiles skipped: {', '.join(sorted(dropped))}"
        return clean

    @staticmethod
    def _clean(values):
        """A profile is 7 numbers; anything else is not a profile."""
        if not isinstance(values, dict):
            return None
        out = {}
        for key in VALUE_KEYS:
            try:
                out[key] = float(values.get(key, 0) or 0)
            except (TypeError, ValueError):
                return None
        return out

    def persist(self):
        """Write profiles to disk; return an error message or None on success."""
        error = write_json(self.path, self.profiles)
        if error:
            self.problem = error
        return error

    # -- dict-like convenience ------------------------------------------------ #
    def names(self):
        return list(self.profiles)

    def get(self, name):
        return self.profiles.get(name)

    def set(self, name, values):
        self.profiles[name] = values

    def delete(self, name):
        self.profiles.pop(name, None)

    def __contains__(self, name):
        return name in self.profiles

    def __bool__(self):
        return bool(self.profiles)
