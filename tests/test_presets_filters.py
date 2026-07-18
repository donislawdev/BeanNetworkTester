"""Preset ordering/resolution and GUI<->CLI filter alignment.

Ported 1:1 from the original monolithic suite; every ``check(...)`` from the
270-assertion baseline is preserved as a pytest assertion.
"""
from fakes import check



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


def test_resolve_preset_variants():
    import beantester as n
    check("presets: canonical id resolves", n.resolve_preset("presets.3g") == "presets.3g")
    check("presets: English name resolves", n.resolve_preset("3G network") == "presets.3g")
    check("presets: Polish name resolves", n.resolve_preset("Sieć 3G") == "presets.3g")
    check("presets: diacritics-insensitive match",
          n.resolve_preset("Idealna siec") == "presets.perfect"
          and n.resolve_preset("Lacze satelitarne") == "presets.satellite")
    check("presets: case-insensitive match", n.resolve_preset("terrible NETWORK") == "presets.terrible")
    check("presets: unknown name -> None", n.resolve_preset("no such preset") is None)
