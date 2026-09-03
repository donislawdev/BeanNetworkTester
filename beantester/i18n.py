"""i18n - translations loaded from ``lang/<code>.json`` files.

Only English slug keys (e.g. ``app.tabs.statistics``) appear in the code;
texts live in the JSON files. The lookup chain is: selected language ->
English fallback -> the key itself. Adding a language = adding a JSON file;
no code changes are needed.
"""
import os
import string
import threading

from .jsonfile import load_json
from .paths import lang_dir

FALLBACK_LANGUAGE = "en"

# Locales whose SCRIPT this project does not ship, and which must therefore not
# be answered by the language file that merely shares their code.
#
# One entry today, and it is the case that shows why the rule is needed at all:
# `lang/zh.json` is Simplified Chinese, and Simplified and Traditional are two
# scripts rather than two spellings of one - a Taiwanese or Hong Kong system
# asking for Chinese would be answered in characters it does not write, using
# mainland terminology it does not use. Every other unshipped locale falls back
# to English and this one now does the same, until a Traditional file exists to
# answer it properly.
#
# 🔴 It is matched against the WHOLE locale tag, not the language code, because
# by the time there is a code the region is gone: `code` is the part before the
# first underscore, so `zh_TW` and `zh_CN` are the same two letters. MEASURED
# before writing this: with only the Windows branch narrowed, `LANG=zh_TW.UTF-8`
# still selected Simplified - the environment path never reaches that branch.
UNSHIPPED_SCRIPT = ("zh_tw", "zh_hk", "zh_mo", "zh_hant", "(traditional)")

# The colon a form label ends with, in either width - the second (U+FF1A) is what
# a CJK label carries. Built from its code point, not typed, so the two cannot be
# mistaken for each other in a review. See field_name().
LABEL_COLONS = ":" + chr(0xFF1A)

_translations: dict[str, dict[str, str]] = {}   # language code -> {key: text}
_language_names: dict[str, str] = {}            # code -> name (from "_meta")
_LANG = None    # resolved lazily on first use (see _resolve_language)

# Guards the LAZY load only - never a lookup, and never load_languages() itself.
# See _ensure_loaded for both halves of why.
_load_lock = threading.Lock()


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
            # Same reader as every other JSON file the program opens, so a
            # translation file that is too big, too deeply nested or carries a
            # non-JSON constant is SKIPPED like any other broken one. It used to
            # be a bare json.load, and deep nesting there raised RecursionError
            # past this handler and out of startup - a stray file in lang/ could
            # stop the program, which is exactly what this except clause exists to
            # prevent (see the _meta note below, the same lesson one line down).
            data = load_json(os.path.join(directory, fname))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        meta = data.pop("_meta", None)
        if not isinstance(meta, dict):
            # ``or {}`` only rescued a FALSY _meta (null, 0, ""). A non-empty one
            # of the wrong type - "_meta": "en", a list, a number - sailed past it
            # and then died on meta.get(), outside this loop's try. That
            # AttributeError escaped load_languages(), which runs at startup, so a
            # single stray file in lang/ stopped the whole program: measured, even
            # ``--version`` exited 1 with a traceback. The docstring above promises
            # the opposite - a broken file is SKIPPED.
            meta = {}
        code = str(meta.get("code") or os.path.splitext(fname)[0]).strip().lower()
        if not code:
            continue
        names[code] = str(meta.get("name") or code)
        translations[code] = {str(k): str(v) for k, v in data.items()}
    # NAMES first, translations second, and the order is the point: `_translations`
    # is what every "have we loaded yet" check reads, so it has to be the LAST
    # thing published. Assigned the other way round, a reader that arrived between
    # the two stores saw a loaded catalogue beside an empty name map, and
    # available_languages() answered with codes where names belong.
    #
    # 🔴 NOT guarded by a test, and said out loud rather than left to look proven:
    # the window is two adjacent stores, so observing it needs a reader racing a
    # loader in a loop - a guard that would be slow, flaky, and green most of the
    # time for the wrong reason. The line above is cheap and correct; the claim
    # that it is TESTED would not be.
    _language_names = names
    _translations = translations
    return set(translations)


def _ensure_loaded():
    """Load the catalogue once, however many threads ask at the same time.

    The lazy branch used to be five copies of ``if not _translations:
    load_languages()``, unguarded, with readers on the engine's worker threads and
    the UI thread. Two of them would both scan ``lang/`` and both publish - the
    same answer twice over, at the cost of a second pass over every file.

    Both entry points happen to load eagerly today (``run_cli`` and
    ``App._build_ui`` each call ``set_language`` as one of their first statements,
    before any worker thread exists), so this is hardening rather than a bug being
    fixed. That is exactly the argument this project refuses to accept on its own:
    "nobody reaches it today" is a fact about the callers, not a property of the
    module.

    The fast path is unchanged - one truthiness test on a global - so ``T()`` pays
    nothing for this. The lock is taken only when there is nothing loaded yet, and
    it deliberately does NOT wrap ``load_languages`` itself: that one is public,
    tests call it directly to reload, and a lock around it would be a lock held
    across disk I/O for callers who are not racing anybody.
    """
    if _translations:
        return
    with _load_lock:
        if not _translations:       # somebody else may have loaded it while we
            load_languages()        # waited - checked again inside the lock


def loaded_language_codes():
    """Codes of the currently loaded languages (loads them on first use)."""
    _ensure_loaded()
    return list(_translations)


def available_languages():
    """``[(code, display name), ...]`` with the fallback (English) listed first."""
    _ensure_loaded()
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
    _ensure_loaded()
    text = str(loc).lower().replace("-", "_")
    code = text.split(".")[0].split("_")[0]
    tag = text
    if code not in _translations:
        # getlocale() returns Windows-style names ('Polish_Poland' -> 'polish'),
        # not the POSIX 'pl_PL', so the plain split above misses them. Map those
        # names back to an ISO code via locale.locale_alias ('polish' ->
        # 'pl_PL.ISO8859-2' -> 'pl'). Env vars keep taking the fast path above.
        try:
            import locale
            alias = locale.locale_alias.get(code) or locale.locale_alias.get(text)
            if not alias and " (" in code and code.endswith(")"):
                # Windows spells the script in brackets ('Chinese (Simplified)'),
                # which no alias key matches. The first letter of the bracket is
                # not a guess: locale_alias names exactly these two that way, and
                # MEASURED over the whole table they are the ONLY keys shaped
                # <language>-<one letter> - 'chinese-s' -> zh_CN and 'chinese-t'
                # -> zh_TW. Every other bracketed Windows name ('Serbian (Latin)'
                # -> 'serbian-l', 'Uzbek (Latin)' -> 'uzbek-l') builds a key that
                # does not exist, so it stays unmatched and English answers, which
                # is what happened before this line existed.
                language, variant = code[:-1].split(" (", 1)
                alias = locale.locale_alias.get(f"{language}-{variant[:1]}")
        except Exception:
            alias = None
        if alias:
            tag = f"{text} {alias.lower()}"
            code = alias.lower().split(".")[0].split("_")[0]
    if any(mark in tag for mark in UNSHIPPED_SCRIPT):
        return FALLBACK_LANGUAGE
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
    _ensure_loaded()
    lang = str(lang or "").strip().lower()
    _LANG = lang if lang in _translations else FALLBACK_LANGUAGE


def current_language():
    return _resolve_language()


class _PlainFieldsOnly(string.Formatter):
    """Substitutes ``{name}`` and nothing else - no attributes, no indexing.

    ``str.format`` walks attributes: ``"{x.__class__.__mro__}".format(x=1)`` is a
    perfectly valid template. The text being walked comes out of
    ``lang/<code>.json``, and this module's own docstring calls adding one of those
    the way to add a language - "no code changes are needed". So the first
    translation somebody contributes is untrusted input by any honest reading, and
    it was being handed a language feature nobody needs.

    MEASURED 2026-08-26, both halves: a poisoned string rendered the internals of
    its argument into a GUI label, and a template naming an attribute that does not
    exist raised ``AttributeError`` - which ``translate`` did not catch, so one
    stray character in a translation file could take the program down in whatever
    window happened to render it.

    The rule is as strict as it is because the files say it can be: every one of
    the 222 placeholders across both shipped language files is a plain name. No
    positional field, no attribute, no index, no format spec. Nothing legitimate
    is refused here - that was checked before the rule was chosen, not after.
    """

    def get_field(self, field_name, args, kwargs):
        if not field_name.isidentifier():
            raise ValueError(f"unsupported placeholder: {field_name!r}")
        return kwargs[field_name], field_name


_FORMATTER = _PlainFieldsOnly()


def translate(key, lang=None, **fmt):
    """Translate a key: requested language -> English fallback -> the key itself.

    Non-string input passes through unchanged. Optional keyword arguments are
    substituted into ``{name}`` placeholders; a malformed template never raises.
    """
    if not isinstance(key, str):
        return key
    _ensure_loaded()
    text = _translations.get(lang or _resolve_language(), {}).get(key)
    if text is None:
        text = _translations.get(FALLBACK_LANGUAGE, {}).get(key, key)
    if fmt:
        # The untranslated text is a better answer than a crash OR than a leak:
        # anything this formatter refuses comes back with its braces showing,
        # which is visibly wrong to the translator and harmless to the user.
        try:
            return _FORMATTER.vformat(text, (), fmt)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return text
    return text


def T(key, **fmt):
    """Translate a key in the current UI language."""
    return translate(key, None, **fmt)


def field_name(key, lang=None):
    """A field label for use INSIDE a sentence: the same text, without its colon.

    A field label is written for the form, where it stands to the left of the box
    you type in and ends with a colon ("Latency:"). Every other reader puts that
    same string into running text - an error message names the field, the profile
    warning lists several - and there the colon is punctuation from a different
    sentence: ``Field 'Latency:' must be between 0 and 600000.``

    So the colon belongs to the label and stripping it belongs HERE, in one place,
    rather than in each message. The GUI's own short form builds on this and drops
    the parenthetical too, which only a compact list wants.

    Both widths are stripped. A CJK label ends in the full-width colon (U+FF1A),
    which is correct there - it carries its own spacing, which is why the Chinese
    prefixes have no trailing space where English does - and ``rstrip(":")`` walks
    straight past it. No shipped label needs this today; it is here because the
    one that does would fail silently, mid-sentence, in a language whose reader
    is least likely to be the person reading this file.
    """
    return str(translate(key, lang)).rstrip().rstrip(LABEL_COLONS).rstrip()


def event_kind_label(kind, lang=None):
    """Human-readable label for a canonical event kind (START, CHANGE, ...)."""
    key = "events.kind_" + str(kind).lower()
    out = translate(key, lang)
    return str(kind) if out == key else out

