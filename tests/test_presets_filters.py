"""Preset ordering/resolution and GUI<->CLI filter alignment.

Ported 1:1 from the original monolithic suite; every ``check(...)`` from the
270-assertion baseline is preserved as a pytest assertion.
"""
from fakes import LANGS, check



def test_filters_and_presets():
    import beantester as n
    check("filters: GUI and CLI have the same number of entries", len(n.FILTERS) == len(n.CLI_FILTERS))
    # index alignment (the GUI mapping relies on it)
    aligned = all(n.FILTERS[name] == list(n.CLI_FILTERS.values())[i]
                  for i, name in enumerate(n.FILTERS))
    check("filters: GUI<->CLI aligned by index", aligned)
    for key in ("both", "out", "in", "tcp", "udp", "ping"):
        check(f"CLI filter '{key}' exists", key in n.CLI_FILTERS)
    for key in ("dns", "http", "https", "web"):
        # port presets were removed: the destination Port field owns ports now
        check(f"port preset '{key}' is gone", key not in n.CLI_FILTERS)


def test_every_filter_covers_ipv4_and_ipv6():
    """``ip`` is IPv4-only in WinDivert: an IPv6 packet used to bypass the tool."""
    from beantester import FILTER_DEFS
    for key, _, expression in FILTER_DEFS:
        v6 = "ipv6" in expression or "icmpv6" in expression
        check(f"filter '{key}' is not IPv4-only", v6, f"({expression})")
        check(f"filter '{key}' covers ICMPv6 whenever it covers ICMP",
              ("icmp" not in expression) or ("icmpv6" in expression), f"({expression})")


def test_every_preset_has_a_name_in_every_language():
    """A preset without a translation shows its raw id in the picker.

    ``fields.py`` has had this guard since forever
    (``test_field_registry.py::test_labels_and_tips_exist_in_every_language``);
    ``PRESETS`` never did, so five presets could be added, render as
    "presets.leo" in the dropdown and in ``--preset``, and leave the suite
    entirely green. Nothing else links this registry to the language files.

    It reads the FILES, not ``translate()``: a key missing from Polish falls
    back to the English text, which is not equal to the key, so a check written
    through ``translate`` passes while the Polish picker quietly shows English.
    Verified by mutation - deleting the Polish `presets.leo` line does not move
    a ``translate``-based check at all.
    """
    import json as _json
    import os as _os
    from beantester.presets import PRESETS
    from fakes import ROOT
    for lang in LANGS:
        path = _os.path.join(ROOT, "lang", f"{lang}.json")
        with open(path, encoding="utf-8") as f:
            names = _json.load(f)
        missing = [k for k in PRESETS if not str(names.get(k, "")).strip()]
        check(f"presets: every id has a {lang} name", not missing, f"({missing})")


def test_presets_exist():
    import beantester as n
    for p in ("presets.lte", "presets.5g", "presets.dsl", "presets.modem56k",
              "presets.roaming"):
        check(f"preset '{p}' exists", p in n.PRESETS)


def test_preset_order_best_to_worst():
    from beantester import PRESETS
    keys = list(PRESETS)
    check("presets: best at the top", keys[0] == "presets.perfect", f"({keys[0]})")
    check("presets: worst at the bottom", keys[-1] == "presets.terrible", f"({keys[-1]})")
    # roughly increasing "severity": normalized latency+loss should not drop drastically
    idx = {k: i for i, k in enumerate(keys)}
    check("presets: 5G before 3G", idx["presets.5g"] < idx["presets.3g"])
    check("presets: LTE before 3G", idx["presets.lte"] < idx["presets.3g"])
    check("presets: perfect before terrible", idx["presets.perfect"] < idx["presets.terrible"])


def test_no_preset_sets_a_run_length_it_cannot_use():
    """A run length shapes the loss, so without loss it is a knob that cannot move.

    Silent in every other way: the preset would look configured, the summary
    would say nothing, and the field would sit there describing a link the
    program never produces. It is the same class as a `spike_ms` with no
    `spike_prob`, and cheap enough to make mechanical.
    """
    from beantester.presets import PRESETS, preset_to_settings
    for key in PRESETS:
        settings = preset_to_settings(key)
        if settings["loss_burst"]:
            check(f"{key} sets a run length and has loss for it to shape",
                  settings["loss"] > 0,
                  f"(run={settings['loss_burst']}, loss={settings['loss']})")


def test_the_wireless_presets_lose_in_runs_and_the_wired_ones_do_not():
    """The mechanism split, pinned so a later tidy-up cannot quietly erase it.

    Loss on a radio link comes from fading, interference and handovers, which
    take the channel away for a stretch. Loss on a wired link is queue overflow,
    and tail drop on one flow is close to independent. That distinction is the
    whole reason only some of these presets carry a run length, and nothing else
    in the tree records it.
    """
    from beantester.presets import preset_to_settings
    for key in ("presets.weak_wifi", "presets.cafe", "presets.metro",
                "presets.inflight", "presets.3g", "presets.roaming",
                "presets.satellite"):
        check(f"{key} loses in runs", preset_to_settings(key)["loss_burst"] > 0,
              f"(run={preset_to_settings(key)['loss_burst']})")
    for key in ("presets.dsl", "presets.modem56k", "presets.bufferbloat",
                "presets.distant", "presets.perfect"):
        check(f"{key} keeps its loss independent",
              preset_to_settings(key)["loss_burst"] == 0,
              f"(run={preset_to_settings(key)['loss_burst']})")


def test_resolve_preset_variants():
    import beantester as n
    check("presets: canonical id resolves", n.resolve_preset("presets.3g") == "presets.3g")
    check("presets: English name resolves", n.resolve_preset("3G network") == "presets.3g")
    check("presets: Polish name resolves", n.resolve_preset("Sieć 3G") == "presets.3g")
    check("presets: diacritics-insensitive match",
          n.resolve_preset("Idealna siec") == "presets.perfect"
          # a name with a STROKE letter, which NFD does not decompose - see
          # fold_name. "Lacze satelitarne" used to be the example here; the
          # preset was renamed to say geostationary, so the case moved to
          # another name carrying an "l with stroke" rather than being dropped.
          and n.resolve_preset("Odlegly serwer (inny kontynent)") == "presets.distant")
    check("presets: case-insensitive match", n.resolve_preset("terrible NETWORK") == "presets.terrible")
    check("presets: unknown name -> None", n.resolve_preset("no such preset") is None)
