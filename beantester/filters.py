"""Traffic filters - single source of truth: (CLI key, i18n key, WinDivert filter).

``FILTERS`` (keyed by i18n name) and ``CLI_FILTERS`` (keyed by CLI key) are
index-aligned by construction; the GUI mapping between them relies on it.

Two rules this file exists to enforce:

* **Every filter covers IPv4 AND IPv6.** In the WinDivert filter language ``ip``
  means *IPv4 only* (IPv6 is ``ipv6``, and ICMPv6 is ``icmpv6``). The original
  filters all started with ``ip and ...``, so every IPv6 packet went straight
  past the tool: not impaired, not counted, not shown in the connection table -
  which, on a dual-stack machine, is most of a browser's traffic.
* **No port-based presets here.** "HTTP only", "DNS only" etc. used to live in
  this list and quietly fought with the destination *Port* field (two places
  deciding about ports, with different semantics). Ports belong to the port
  field, which understands lists, ranges and exclusions anyway.
"""

_ALL_IP = "(ip or ipv6)"
_ALL_PROTO = "(tcp or udp or icmp or icmpv6)"

FILTER_DEFS = [
    ("both", "filters.both", f"{_ALL_IP} and {_ALL_PROTO}"),
    ("out",  "filters.out",  f"outbound and {_ALL_IP} and {_ALL_PROTO}"),
    ("in",   "filters.in",   f"inbound and {_ALL_IP} and {_ALL_PROTO}"),
    ("tcp",  "filters.tcp",  f"{_ALL_IP} and tcp"),
    ("udp",  "filters.udp",  f"{_ALL_IP} and udp"),
    ("ping", "filters.ping", "icmp or icmpv6"),
    ("loopback", "filters.loopback", f"loopback and {_ALL_IP} and {_ALL_PROTO}"),
]

FILTERS = {name: wd for _, name, wd in FILTER_DEFS}
CLI_FILTERS = {key: wd for key, _, wd in FILTER_DEFS}

# Explicit lookups instead of the old index gymnastics
# (``list(CLI_FILTERS)[list(FILTERS).index(name)]``), which silently depended on
# both dicts keeping the same insertion order.
_BY_CLI = {key: (key, name, wd) for key, name, wd in FILTER_DEFS}
_BY_I18N = {name: (key, name, wd) for key, name, wd in FILTER_DEFS}
DEFAULT_FILTER = FILTER_DEFS[0][0]


def cli_key_for(i18n_key, default=DEFAULT_FILTER):
    """i18n filter key -> CLI key (``filters.both`` -> ``both``)."""
    entry = _BY_I18N.get(i18n_key)
    return entry[0] if entry else default


def i18n_key_for(cli_key, default=FILTER_DEFS[0][1]):
    """CLI filter key -> i18n key (``both`` -> ``filters.both``)."""
    entry = _BY_CLI.get(cli_key)
    return entry[1] if entry else default


def windivert_for(cli_key):
    """CLI filter key -> WinDivert filter expression."""
    entry = _BY_CLI.get(cli_key)
    return entry[2] if entry else CLI_FILTERS[DEFAULT_FILTER]


def i18n_keys():
    """Filter i18n keys in canonical order (drives the GUI combobox)."""
    return [name for _, name, _ in FILTER_DEFS]
