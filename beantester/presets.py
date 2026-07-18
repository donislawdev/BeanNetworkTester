"""Network presets, ordered best (top) -> worst (bottom).

The GUI list and the CLI ``--preset`` order follow this dict's key order.
Keys are canonical i18n ids (``presets.*``); display names come from the
language files, and ``resolve_preset`` accepts either form.
"""
import unicodedata

from .i18n import loaded_language_codes, translate

PRESETS = {
    # ordered best -> worst (top = best network, bottom = worst)
    "presets.perfect":   dict(loss=0,   corrupt=0,   dup=0,   lat=0,   jit=0,   down=0,     up=0),
    "presets.good_wifi": dict(loss=0.1, corrupt=0,   dup=0,   lat=15,  jit=5,   down=0,     up=0),
    "presets.5g":        dict(loss=0.1, corrupt=0,   dup=0,   lat=18,  jit=8,   down=20480, up=8192),
    "presets.lte":       dict(loss=0.3, corrupt=0,   dup=0,   lat=45,  jit=20,  down=6144,  up=2048),
    "presets.dsl":       dict(loss=0.5, corrupt=0,   dup=0,   lat=35,  jit=10,  down=1536,  up=256),
    "presets.weak_wifi": dict(loss=2,   corrupt=0.2, dup=0.5, lat=80,  jit=40,  down=2048,  up=1024),
    "presets.cafe":      dict(loss=3,   corrupt=0.3, dup=1,   lat=120, jit=90,  down=1024,  up=384),
    "presets.3g":        dict(loss=1,   corrupt=0,   dup=0,   lat=150, jit=60,  down=384,   up=128),
    "presets.roaming":   dict(loss=1.5, corrupt=0,   dup=0,   lat=300, jit=80,  down=512,   up=128),
    "presets.satellite": dict(loss=1,   corrupt=0,   dup=0,   lat=600, jit=100, down=1024,  up=256),
    "presets.modem56k":  dict(loss=0.5, corrupt=0,   dup=0,   lat=200, jit=30,  down=5,     up=4),
    "presets.terrible":  dict(loss=10,  corrupt=2,   dup=2,   lat=300, jit=150, down=256,   up=128),
}


# Letters with a STROKE are single codepoints, not base + combining mark, so NFD
# leaves them alone: Polish "ł" survived the fold, and ``--preset "Lacze
# satelitarne"`` (or a profile named "Slabe WiFi") resolved to nothing at all.
STROKE_LETTERS = str.maketrans({
    "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O",
    "ð": "d", "Ð": "D", "ħ": "h", "Ħ": "H", "ŧ": "t", "Ŧ": "T",
})


def fold_name(text):
    """Normalize a name for lenient matching (casefold + strip diacritics)."""
    decomposed = unicodedata.normalize("NFD", str(text).translate(STROKE_LETTERS))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold().strip()


def resolve_preset(name):
    """Resolve a preset given its canonical id or a translated name in any
    loaded language (diacritics-insensitive). Returns the id or None."""
    if name in PRESETS:
        return name
    wanted = fold_name(name)
    for key in PRESETS:
        for lang in loaded_language_codes():
            if fold_name(translate(key, lang)) == wanted:
                return key
    return None


# Presets use short keys (lat/jit/...) for historical reasons; the settings model
# uses the long ones. The mapping lives HERE, once - the GUI and the CLI used to
# each carry their own copy of it.
PRESET_TO_SETTING = {"loss": "loss", "corrupt": "corrupt", "dup": "dup",
                     "lat": "latency", "jit": "jitter", "down": "down", "up": "up"}


def preset_to_settings(preset):
    """``PRESETS`` entry (or preset id/name) -> settings-shaped dict."""
    if isinstance(preset, str):
        canon = resolve_preset(preset)
        if canon is None:
            return {}
        preset = PRESETS[canon]
    return {PRESET_TO_SETTING[k]: v for k, v in preset.items()
            if k in PRESET_TO_SETTING}


SETTING_TO_PRESET = {v: k for k, v in PRESET_TO_SETTING.items()}


def settings_to_preset(s):
    """Settings dict -> the 7-field shape a profile/preset is stored in."""
    return {short: s.get(long, 0) for long, short in SETTING_TO_PRESET.items()}
