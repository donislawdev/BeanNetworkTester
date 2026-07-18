"""i18n - translations loaded from ``lang/<code>.json`` files.

Only English slug keys (e.g. ``app.tabs.statistics``) appear in the code;
texts live in the JSON files. The lookup chain is: selected language ->
English fallback -> the key itself. Adding a language = adding a JSON file;
no code changes are needed.
"""
import json
import os

from .paths import lang_dir

FALLBACK_LANGUAGE = "en"

_translations = {}        # language code -> {key: translated text}
_language_names = {}      # language code -> display name (from "_meta")
_LANG = None    # resolved lazily on first use (see _resolve_language)


def load_languages(directory=None):
    """(Re)load every ``<code>.json`` translation file from the lang directory.

    Each file maps translation keys to texts and may carry a ``"_meta"`` object
    with ``{"code": ..., "name": ...}``. A broken or unreadable file is skipped
    so it can never break app startup. Returns the set of loaded language codes.
    """
    global _translations, _language_names
    directory = directory or lang_dir()
    translations, names = {}, {}
    try:
        files = sorted(os.listdir(directory))
    except OSError:
        files = []
    for fname in files:
        if not fname.lower().endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, fname), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        meta = data.pop("_meta", None) or {}
        code = str(meta.get("code") or os.path.splitext(fname)[0]).strip().lower()
        if not code:
            continue
        names[code] = str(meta.get("name") or code)
        translations[code] = {str(k): str(v) for k, v in data.items()}
    _translations, _language_names = translations, names
    return set(translations)


def loaded_language_codes():
    """Codes of the currently loaded languages (loads them on first use)."""
    if not _translations:
        load_languages()
    return list(_translations)


def available_languages():
    """``[(code, display name), ...]`` with the fallback (English) listed first."""
    if not _translations:
        load_languages()
    codes = sorted(_translations, key=lambda c: (c != FALLBACK_LANGUAGE, c))
    return [(c, _language_names.get(c, c)) for c in codes]


def detect_language():
    """Pick the startup language from the system locale (best match, else English)."""
    loc = (os.environ.get("LANG") or os.environ.get("LC_ALL")
           or os.environ.get("LC_MESSAGES") or os.environ.get("LANGUAGE") or "")
    if not loc:
        # locale.getdefaultlocale() is deprecated (scheduled for removal), so
        # only the supported getlocale() is consulted besides the env vars
        try:
            import locale
            loc = locale.getlocale()[0] or ""
        except Exception:
            loc = ""
    if not _translations:
        load_languages()
    text = str(loc).lower().replace("-", "_")
    code = text.split(".")[0].split("_")[0]
    if code not in _translations:
        # getlocale() returns Windows-style names ('Polish_Poland' -> 'polish'),
        # not the POSIX 'pl_PL', so the plain split above misses them. Map those
        # names back to an ISO code via locale.locale_alias ('polish' ->
        # 'pl_PL.ISO8859-2' -> 'pl'). Env vars keep taking the fast path above.
        try:
            import locale
            alias = locale.locale_alias.get(code) or locale.locale_alias.get(text)
        except Exception:
            alias = None
        if alias:
            code = alias.lower().split(".")[0].split("_")[0]
    return code if code in _translations else FALLBACK_LANGUAGE


def _resolve_language():
    """Return the active language, detecting it lazily on first use.

    Detection scans the ``lang/`` directory, so doing it at import time made
    ``import beantester`` perform disk I/O as a side effect.
    """
    global _LANG
    if _LANG is None:
        _LANG = detect_language()
    return _LANG


def set_language(lang):
    """Switch the UI language; unknown codes fall back to English."""
    global _LANG
    if not _translations:
        load_languages()
    lang = str(lang or "").strip().lower()
    _LANG = lang if lang in _translations else FALLBACK_LANGUAGE


def current_language():
    return _resolve_language()


def translate(key, lang=None, **fmt):
    """Translate a key: requested language -> English fallback -> the key itself.

    Non-string input passes through unchanged. Optional keyword arguments are
    applied with ``str.format()``; a malformed template never raises.
    """
    if not isinstance(key, str):
        return key
    if not _translations:
        load_languages()
    text = _translations.get(lang or _resolve_language(), {}).get(key)
    if text is None:
        text = _translations.get(FALLBACK_LANGUAGE, {}).get(key, key)
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def T(key, **fmt):
    """Translate a key in the current UI language."""
    return translate(key, None, **fmt)


def event_kind_label(kind, lang=None):
    """Human-readable label for a canonical event kind (START, CHANGE, ...)."""
    key = "events.kind_" + str(kind).lower()
    out = translate(key, lang)
    return str(kind) if out == key else out

