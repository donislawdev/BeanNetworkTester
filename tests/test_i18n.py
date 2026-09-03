"""i18n system: file discovery, fallback chain, placeholders, translated exceptions.

Ported 1:1 from the original monolithic suite; every ``check(...)`` from the
270-assertion baseline is preserved as a pytest assertion.
"""
import os
import string
import time

from beantester import BeanEngine
from fakes import LANG_DIR, LANGS, check

_FORMATTER = string.Formatter()

# The ASCII semicolon and the full-width one a CJK keyboard produces (U+FF1B).
# The second is built from its code point rather than typed, the way
# ``tools/check_public_text.py`` builds the dashes it hunts for: the two are one
# pixel apart in a review, and a guard that spells its own target out invites a
# copy of it into the file next door.
SEMICOLONS = (";", chr(0xFF1B))


def _placeholders(value):
    return {name for _, name, _, _ in _FORMATTER.parse(value)
            if name is not None}



def test_i18n():
    import beantester as n
    orig = n.current_language()
    n.set_language("en")
    check("i18n: translates a known key (EN)", n.T("app.tabs.statistics") == "Statistics",
          f"({n.T('app.tabs.statistics')})")
    check("i18n: unknown key passes through", n.T("no.such.key") == "no.such.key")
    n.set_language("pl")
    check("i18n: translates a known key (PL, diacritics)",
          n.T("app.tabs.connections") == "Połączenia", f"({n.T('app.tabs.connections')})")
    n.set_language("zh")
    check("i18n: translates a known key (ZH)",
          n.T("app.tabs.connections") == "连接", f"({n.T('app.tabs.connections')})")
    check("i18n: detect returns an available code",
          n.detect_language() in dict(n.available_languages()))
    n.set_language(orig)


def test_detect_language_maps_windows_locale_names(monkeypatch):
    """detect_language() understands Windows-style locale names, not just POSIX.

    On Windows the LANG/LC_* env vars are unset and locale.getlocale() returns
    names like 'Polish_Poland' (not POSIX 'pl_PL'); a naive split yields 'polish',
    which is no language code, so detection silently fell back to English on every
    non-English Windows box. Guard both the Windows-name path and the POSIX one.
    """
    import locale
    import beantester as n
    for var in ("LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setattr(locale, "getlocale", lambda *a: ("Polish_Poland", "1250"))
    check("detect: Windows 'Polish_Poland' -> pl", n.detect_language() == "pl",
          f"({n.detect_language()})")
    monkeypatch.setattr(locale, "getlocale", lambda *a: ("English_United States", "1252"))
    check("detect: Windows 'English_United States' -> en", n.detect_language() == "en",
          f"({n.detect_language()})")
    monkeypatch.setattr(locale, "getlocale",
                        lambda *a: ("Chinese (Simplified)_China", "936"))
    check("detect: Windows Simplified Chinese -> zh", n.detect_language() == "zh",
          f"({n.detect_language()})")
    # Traditional Chinese is a different SCRIPT, not a region of the shipped one,
    # so it takes the same English fallback as any language we do not ship. Both
    # roads are guarded because they are genuinely separate: the environment
    # variables below never reach the Windows-name branch above, and narrowing
    # only that branch left LANG=zh_TW.UTF-8 selecting Simplified.
    monkeypatch.setattr(locale, "getlocale",
                        lambda *a: ("Chinese (Traditional)_Taiwan", "950"))
    check("detect: Windows Traditional Chinese -> en fallback",
          n.detect_language() == "en", f"({n.detect_language()})")
    monkeypatch.setattr(locale, "getlocale",
                        lambda *a: ("Chinese (Traditional)_Hong Kong SAR", "950"))
    check("detect: Windows Traditional Chinese (Hong Kong) -> en fallback",
          n.detect_language() == "en", f"({n.detect_language()})")
    monkeypatch.setattr(locale, "getlocale", lambda *a: ("German_Germany", "1252"))
    check("detect: unshipped locale -> en fallback", n.detect_language() == "en")

    monkeypatch.setenv("LANG", "pl_PL.UTF-8")   # POSIX env var takes the fast path
    check("detect: POSIX env 'pl_PL.UTF-8' -> pl", n.detect_language() == "pl")

    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    check("detect: POSIX env 'zh_CN.UTF-8' -> zh", n.detect_language() == "zh")

    monkeypatch.setenv("LANG", "zh_SG.UTF-8")   # Singapore writes Simplified too
    check("detect: POSIX env 'zh_SG.UTF-8' -> zh", n.detect_language() == "zh",
          f"({n.detect_language()})")

    monkeypatch.setenv("LANG", "zh_TW.UTF-8")
    check("detect: POSIX env 'zh_TW.UTF-8' -> en fallback",
          n.detect_language() == "en", f"({n.detect_language()})")

    monkeypatch.setenv("LANG", "zh-Hant")       # the script named outright
    check("detect: POSIX env 'zh-Hant' -> en fallback",
          n.detect_language() == "en", f"({n.detect_language()})")


def test_field_name_strips_a_colon_of_either_width(monkeypatch):
    """The label a CJK language writes ends in U+FF1A, not in ':'.

    No shipped label needs this yet, which is exactly why it is worth a test: the
    day one does, the failure is a colon sitting in the middle of a sentence in a
    language nobody here reads, on a machine nobody here owns. The stripping lives
    in one place, so the guard can too - and a live language file would only prove
    today's data, not the rule.
    """
    from beantester import i18n
    label = "延迟" + chr(0xFF1A)      # a label ending in a full-width colon
    monkeypatch.setitem(i18n._translations, "xx", {"fields.probe": label})
    check("field_name strips a full-width colon",
          i18n.field_name("fields.probe", "xx") == "延迟",
          f"({i18n.field_name('fields.probe', 'xx')!r})")


def test_no_semicolons_in_ui_text():
    """People do not write semicolons in ordinary prose - a full stop or a comma
    (PROJECT_NOTES convention 1b).

    Unlike readability, this one IS mechanical and has no false positives, which
    is exactly why it is worth a test: 21 tooltips had drifted into semicolons
    before anybody looked. A semicolon joins two independent clauses, so the
    right replacement is almost always a full stop.

    The full-width form is checked for the same reason and was found the hard way:
    the loop was widened to Chinese while the search stayed ASCII, so the guard
    reported clean over 34 keys holding 35 of them. A test that covers a language
    it cannot read is worse than one that skips it - the skip is at least visible.
    """
    import json as _json
    for code in LANGS:
        with open(os.path.join(LANG_DIR, f"{code}.json"), encoding="utf-8") as f:
            data = _json.load(f)
        data.pop("_meta", None)
        offenders = sorted(k for k, v in data.items()
                           if isinstance(v, str)
                           and any(mark in v for mark in SEMICOLONS))
        check(f"i18n {code}: no semicolons in user-facing text", not offenders,
              f"({offenders[:6]})")


def test_i18n_coverage():
    """Language files stay in sync: same keys, no empty texts, EN differs from keys."""
    import json as _json
    import beantester as n
    langs = {}
    for code in LANGS:
        with open(os.path.join(LANG_DIR, f"{code}.json"), encoding="utf-8") as f:
            data = _json.load(f)
        data.pop("_meta", None)
        langs[code] = data
    english_keys = set(langs["en"])
    key_diffs = {code: sorted(english_keys ^ set(values))[:5]
                 for code, values in langs.items() if set(values) != english_keys}
    check("i18n files: every language matches the English key set",
          not key_diffs, f"(diffs={key_diffs})")
    empty = [k for d in langs.values() for k, v in d.items() if not str(v).strip()]
    check("i18n files: no empty translations", not empty, f"({empty[:5]})")
    same = [k for k, v in langs["en"].items() if v == k]
    check("i18n files: EN text never equals its key", not same, f"({same[:5]})")
    diacritics = set("ąćęłńóśżźĄĆĘŁŃÓŚŻŹ")
    has_pl = any(diacritics & set(v) for v in langs["pl"].values())
    check("i18n files: PL uses proper diacritics", has_pl)
    has_zh = any(any("\u4e00" <= char <= "\u9fff" for char in value)
                 for value in langs["zh"].values())
    check("i18n files: ZH uses Chinese characters", has_zh)
    placeholder_diffs = {
        code: [key for key, value in values.items()
               if _placeholders(value) != _placeholders(langs["en"][key])]
        for code, values in langs.items() if code != "en"
    }
    placeholder_diffs = {code: keys for code, keys in placeholder_diffs.items() if keys}
    check("i18n files: placeholders match English",
          not placeholder_diffs, f"(diffs={placeholder_diffs})")
    # everything referenced in code resolves through the files
    used = ["app.tabs.control", "frames.traffic", "stats.packets", "session.seed",
            "conns.remote_ip", "events.col_type", "filters.udp", "presets.5g",
            "log.ready", "dialogs.profile_name", "tips.filter", "summary.none",
            "errors.field_number", "events.kind_bug", "events.manual_reset"]
    n_orig = n.current_language()
    n.set_language("en")
    unresolved = [k for k in used if n.T(k) == k]
    n.set_language(n_orig)
    check("i18n: sampled UI keys resolve to text", not unresolved, f"({unresolved})")


def test_the_language_files_stay_sorted():
    """Keys in file order, so a new one has exactly one place to go.

    The note has said these files are sorted since they existed and NOTHING
    enforced it, which is this project's own definition of decoration. Found by
    running the check by hand on 2026-08-17 while removing an unused key: one pair
    was out of order (`log.driver_wait` before `log.driver_still_unloading`) and had
    been for however long, in both files identically.

    Why it is worth a guard rather than a shrug: the language files are edited in
    lockstep and diffed against each other constantly (`test_i18n_coverage` above
    compares their key sets), and a key inserted "roughly where it looks right"
    turns every later diff into a puzzle. `_meta` sorts before every dotted key on
    its own, so it needs no exception.
    """
    import json as _json
    for code in LANGS:
        with open(os.path.join(LANG_DIR, f"{code}.json"), encoding="utf-8") as f:
            keys = list(_json.load(f))
        out_of_order = [(a, b) for a, b in zip(keys, keys[1:], strict=False) if a > b]
        check(f"{code}.json keys are sorted", not out_of_order,
              f"(first offender: {out_of_order[:1]})")
        check(f"{code}.json opens with _meta", keys and keys[0] == "_meta",
              f"({keys[:1]})")


def test_app_name():
    import beantester
    check("application name = Bean Network Tester", beantester.APP_NAME == "Bean Network Tester",
          f"({beantester.APP_NAME})")


# --- CLI tests ------------------------------------------------------------- #


def test_lang_discovery_and_meta():
    import tempfile, os as _os, json as _json
    import beantester as n
    d = tempfile.mkdtemp(prefix="ns_lang_")
    _json.dump({"_meta": {"code": "en", "name": "English"}, "k.hello": "Hello"},
               open(_os.path.join(d, "en.json"), "w", encoding="utf-8"))
    _json.dump({"_meta": {"code": "de", "name": "Deutsch"}, "k.hello": "Hallo"},
               open(_os.path.join(d, "de.json"), "w", encoding="utf-8"))
    _json.dump({"k.hello": "Bonjour"},
               open(_os.path.join(d, "fr.json"), "w", encoding="utf-8"))   # no _meta
    open(_os.path.join(d, "xx.json"), "w").write("{ broken json !!")       # broken file
    open(_os.path.join(d, "notes.txt"), "w").write("not a language file")
    try:
        codes = n.load_languages(d)
        check("i18n discovery: JSON files loaded, broken one skipped",
              codes == {"en", "de", "fr"}, f"({sorted(codes)})")
        names = dict(n.available_languages())
        check("i18n discovery: _meta names used, filename is the fallback code",
              names.get("de") == "Deutsch" and names.get("fr") == "fr", f"({names})")
        check("i18n discovery: English listed first",
              n.available_languages()[0][0] == "en")
        n.set_language("de")
        check("i18n discovery: new language usable immediately",
              n.T("k.hello") == "Hallo")
    finally:
        n.load_languages()            # restore the real language files
        n.set_language("pl")


def test_a_cold_catalogue_is_loaded_once_however_many_threads_ask():
    """The lazy load used to be an unguarded check-then-act, in five places.

    Readers live on the engine's worker threads and on the UI thread, so two of
    them could both find the catalogue empty and both scan ``lang/`` - the same
    answer produced twice, at the cost of a second pass over every file.

    Both entry points happen to load eagerly today (``run_cli`` and
    ``App._build_ui`` call ``set_language`` among their first statements, before
    any worker exists), which is a fact about the CALLERS and not a property of
    this module. This pins the property.
    """
    import threading

    from beantester import i18n

    saved = (i18n._translations, i18n._language_names, i18n._LANG)
    loads, seen, ready = [], [], threading.Barrier(6)
    real_load = i18n.load_languages

    def slow_load(directory=None):
        loads.append(1)
        time.sleep(0.05)            # widen the window a racing reader would use
        return real_load(directory)

    i18n.load_languages = slow_load
    try:
        i18n._translations, i18n._language_names = {}, {}       # a cold module
        errors = []

        def reader():
            ready.wait(timeout=5)
            try:
                seen.append(i18n.T("app.name"))
            except Exception as exc:                # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        ready.wait(timeout=5)
        for t in threads:
            t.join(timeout=5)

        check("no reader failed on a half-loaded catalogue", not errors, f"({errors})")
        check("the catalogue was scanned once, not once per thread",
              len(loads) == 1, f"({len(loads)} loads for {len(threads)} readers)")
        check("and every reader got the same answer",
              len(set(seen)) == 1 and seen[0], f"({set(seen)})")
    finally:
        i18n.load_languages = real_load
        i18n._translations, i18n._language_names, i18n._LANG = saved


def test_fallback_chain():
    import tempfile, os as _os, json as _json
    import beantester as n
    d = tempfile.mkdtemp(prefix="ns_fb_")
    _json.dump({"_meta": {"code": "en", "name": "English"},
                "k.both": "Both EN", "k.only_en": "Only EN"},
               open(_os.path.join(d, "en.json"), "w", encoding="utf-8"))
    _json.dump({"_meta": {"code": "pl", "name": "Polski"}, "k.both": "Oba PL"},
               open(_os.path.join(d, "pl.json"), "w", encoding="utf-8"))
    try:
        n.load_languages(d)
        n.set_language("pl")
        check("fallback: key present in PL -> Polish text", n.T("k.both") == "Oba PL")
        check("fallback: key missing in PL -> English text", n.T("k.only_en") == "Only EN")
        check("fallback: key missing everywhere -> the key itself",
              n.T("k.nowhere") == "k.nowhere")
        n.set_language("xx")
        check("fallback: unknown language code -> English", n.current_language() == "en")
        check("fallback: explicit language via translate()",
              n.translate("k.both", "pl") == "Oba PL")
    finally:
        n.load_languages()
        n.set_language("pl")


def test_translate_placeholders():
    import beantester as n
    n.set_language("pl")
    msg = n.T("errors.field_number", name="Utrata")
    check("placeholders: value substituted", "Utrata" in msg and "{name}" not in msg,
          f"({msg})")
    check("placeholders: missing argument never raises",
          isinstance(n.T("errors.field_number"), str))
    check("placeholders: unused kwargs are harmless",
          "ping" in n.translate("summary.latency", "en", v=100, extra=1))


def test_a_translation_file_cannot_reach_inside_the_values_it_formats():
    """A language file is contributed input, and it was being handed `str.format`.

    "Adding a language = adding a JSON file; no code changes are needed" is this
    module's own docstring, so the first translation somebody sends is untrusted
    text - and `str.format` walks attributes. Measured before the fix:
    `{name.__class__.__mro__}` rendered the internals of the argument into the
    label, and `{name.nope}` raised AttributeError, which `translate` did not catch.
    One stray character in a translation could take the program down.

    The three cases are the three outcomes that matter: nothing leaks, nothing
    raises, and the thing translations actually do still works.
    """
    from beantester import i18n

    i18n.load_languages()
    poisoned = {
        "probe.leak": "leak: {name.__class__.__mro__}",
        "probe.missing_attr": "{name.no_such_attribute}",
        "probe.index": "{name[0]}",
        "probe.plain": "hello {name}",
    }
    i18n._translations.setdefault("en", {}).update(poisoned)
    try:
        leak = i18n.translate("probe.leak", "en", name="x")
        # Compared against the raw template, not searched for words: the template
        # ITSELF contains "__class__", so "no internals leaked" has to mean
        # "nothing was substituted at all" to be worth anything.
        check("i18n: a template cannot walk into the value it was given",
              leak == poisoned["probe.leak"] and "<class" not in leak, f"({leak})")

        for key in ("probe.missing_attr", "probe.index"):
            out = i18n.translate(key, "en", name="x")
            check(f"i18n: {key} does not raise, it comes back unrendered",
                  isinstance(out, str) and "{" in out, f"({out!r})")

        check("i18n: a plain placeholder still works",
              i18n.translate("probe.plain", "en", name="world") == "hello world")
    finally:
        for key in poisoned:
            i18n._translations["en"].pop(key, None)


def test_settings_summary_uses_current_language():
    import beantester as n
    orig = n.current_language()
    n.set_language("pl")
    pl = n.settings_summary({"loss": 5})
    n.set_language("en")
    en = n.settings_summary({"loss": 5})
    n.set_language(orig)
    check("summary: defaults to the current UI language",
          "strat" in pl and "loss" in en, f"(pl={pl}, en={en})")


def test_event_kind_labels():
    import beantester as n
    check("event kinds: translated for display",
          n.event_kind_label("BUG", "pl") == "BŁĄD"
          and n.event_kind_label("CHANGE", "pl") == "ZMIANA"
          and n.event_kind_label("BUG", "en") == "BUG")
    check("event kinds: unknown code passes through",
          n.event_kind_label("CUSTOM", "pl") == "CUSTOM")


def test_event_descriptions_translated_at_display():
    import beantester as n
    sh = BeanEngine()
    sh.log_event("RESET", "events.manual_reset")
    desc = sh.events_snapshot()[-1][3]
    check("events: stored as a key, translated at display",
          desc == "events.manual_reset"
          and n.translate(desc, "pl") == "ręczne zerwanie połączeń TCP (RST)"
          and n.translate(desc, "en") == "manual TCP connection reset (RST)")


def test_i18n_non_string_passthrough():
    import beantester as n
    orig = n.current_language()
    n.set_language("en")
    ok = n.T(123) == 123 and n.T(None) is None
    n.set_language(orig)
    check("i18n: non-string passes through unchanged", ok)




# --- i18n system tests (JSON files, fallback chain, placeholders) ----------- #


def test_translated_exceptions():
    import beantester as n
    n.set_language("pl")
    try:
        n.parse_schedule("1:2")
    except ValueError as e:
        msg_pl = str(e)
    check("exceptions: raised in the current UI language (PL)",
          "harmonogramu" in msg_pl, f"({msg_pl})")
    n.set_language("en")
    try:
        n.parse_schedule("1:2")
    except ValueError as e:
        msg_en = str(e)
    check("exceptions: English in EN mode (so the CLI stays English)",
          "Schedule step" in msg_en, f"({msg_en})")
    n.set_language("pl")
    # Through `field_name`, which is how every real caller builds it - the label
    # is "Utrata:" for the form, and a sentence naming the field drops the colon.
    check("exceptions: GUI field error translated with the field name",
          "Pole 'Utrata' musi" in n.T("errors.field_number",
                                      name=n.field_name("fields.loss")))
    n.set_language("en")
    check("exceptions: English field error",
          "must be a number" in n.T("errors.field_number", name="Loss"))
    n.set_language("pl")


# blame words: the message describes the INPUT, never the person who typed it
# (Nielsen Norman Group's error-message guidance).
# Deliberately whole words, and deliberately not "not valid" - "X is not a valid
# IP address" describes the value and tells the reader what shape was wanted,
# which is the opposite of blame.
BLAME = {
    "en": (r"\binvalid\b", r"\billegal\b", r"\bbad\b", r"\bwrong\b"),
    "pl": (r"nieprawid", r"niepoprawn", r"\bz[lł]y\b", r"\bz[lł]e\b",
           r"\bz[lł]a\b", r"b[lł][eę]dn"),
}


def _texts_of(code, prefix=""):
    import json as _json
    with open(os.path.join(LANG_DIR, f"{code}.json"), encoding="utf-8") as f:
        data = _json.load(f)
    return {k: v for k, v in data.items()
            if k.startswith(prefix) and isinstance(v, str) and k != "_meta"}


def test_no_message_blames_the_person_reading_it():
    """"Invalid value for 'loss'" told the user they were wrong and nothing else.

    The config loader said that about the very same value the form describes as
    "must be between 0 and 100" - so the tool already knew the useful sentence
    and used the useless one in the file path. Four texts across the two
    languages carried a blame word, and one of them ("bad schedule step") was
    also the only error starting in lower case.

    EVERY text, not just ``errors.*``. The first version of this guard scanned
    that namespace alone, which would have missed the very offender that started
    this: ``log.filter_skipped`` said "Invalid filter expression" and lives under
    ``log.``. Measured when the scope was widened - zero offenders in any
    namespace - so the wider rule costs nothing today and is the one that
    actually holds.

    Deliberately not banned: "is not a valid IP address". It describes the value
    and names the shape that was wanted, which is the opposite of blame. If a
    text ever genuinely needs one of these words, this test is where that
    argument gets made.
    """
    import re as _re
    for code, patterns in BLAME.items():
        texts = _texts_of(code)
        check(f"i18n {code}: the scan actually read the language file",
              len(texts) >= 200, f"({len(texts)} keys)")
        offenders = sorted(k for k, v in texts.items()
                           if any(_re.search(p, v, _re.I) for p in patterns))
        check(f"i18n {code}: no message blames the reader", not offenders,
              f"({offenders})")


def test_every_error_reads_like_a_sentence():
    """Capital letter at the front, terminal punctuation at the end.

    Not pedantry: these strings are shown on their own - under a field in the
    form, in a dialog, after ``[bean] error:`` - so a fragment reads as a
    truncation. Three were missing their full stop and one began lower case,
    which is what a namespace with no guardian looks like after a few years.
    """
    for code in ("en", "pl"):
        texts = _texts_of(code, "errors.")
        check(f"i18n {code}: the error namespace is not empty", len(texts) >= 20,
              f"({len(texts)} keys)")
        no_stop = sorted(k for k, v in texts.items()
                         if not v.rstrip().endswith((".", "?", "!")))
        check(f"i18n {code}: every error ends a sentence", not no_stop,
              f"({no_stop})")
        lower = sorted(k for k, v in texts.items()
                       if v[:1].islower())
        check(f"i18n {code}: every error starts a sentence", not lower,
              f"({lower})")
