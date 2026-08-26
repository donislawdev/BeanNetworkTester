"""Persistence of user-defined profiles (a JSON file in the user's data directory).

A profile stores the link-characteristic fields a preset stores (see
``presets.settings_to_preset``) - the field registry decides which those are.
The file is the user's - it can be edited, deleted or corrupted between two
runs, and none of that may break startup or destroy the rest of the profiles.

The format is FORWARD and BACKWARD compatible by construction: a file written
before the profile scope widened simply has fewer keys, and each missing one
falls back to that field's default (see ``_clean``); a file written after it is
read by an older build, which ignores the keys it does not know.
"""
from ..jsonfile import read_json, write_json
from ..paths import PROFILE_FILE
from ..presets import PRESET_DEFAULTS, PRESET_TO_SETTING

VALUE_KEYS = tuple(PRESET_TO_SETTING)          # short keys, in registry order


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
        """One number per profile field; anything else is not a profile.

        A field the file does not mention falls back to THAT FIELD'S DEFAULT,
        not to zero. The old blanket zero was right only while every profile
        field defaulted to zero: ``buffer`` defaults to 1000 ms and 0 means an
        UNBOUNDED link buffer there, so a zero-fill would have turned every
        profile written before the scope widened into the runaway token bucket
        the bounded buffer exists to prevent (``BeanCore.decide`` step 11).

        An explicit ``0`` in the file stays 0 - that is what "no cap on the
        queue" looks like when the user means it - so absence and zero must not
        collapse into each other. ``null`` and ``""`` count as absence.
        """
        if not isinstance(values, dict):
            return None
        out = {}
        for key in VALUE_KEYS:
            raw = values.get(key)
            if raw is None or raw == "":
                raw = PRESET_DEFAULTS[key]
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return None
            # float() accepts "inf" and "nan" - the two values every other door in
            # this program refuses by name (validators.parse_number, with its own
            # comment). A stored profile is not a place they can come from honestly:
            # the form cannot produce one, and since 2026-08-26 neither can the
            # reader (jsonfile rejects the JSON constants). This is the third lock
            # on the same door, because this one runs on a file somebody was sent.
            if value != value or value in (float("inf"), float("-inf")):
                return None
            out[key] = value
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
