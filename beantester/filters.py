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

And one table it keeps beside the list: ``FILTER_ADMITS``, what each filter lets
through, which is how a setting the chosen filter leaves nothing to act on gets
said out loud (``fields.Field.needs``).
"""
from typing import Any, Dict, FrozenSet, List, NamedTuple, Optional, Tuple

_ALL_IP = "(ip or ipv6)"
_ALL_PROTO = "(tcp or udp or icmp or icmpv6)"

FILTER_DEFS: List[Tuple[str, str, str]] = [
    ("both", "filters.both", f"{_ALL_IP} and {_ALL_PROTO}"),
    # Everything the first one takes except a program on this machine talking to
    # another one on it: a local development server, a database, IPC. Second, so
    # the two "all traffic" entries stand together. Every reader keeps the KEY,
    # never the position (ui.json, config files, scenarios, the repro command), and
    # the default is entry 0, so the order is free to choose.
    ("no-loopback", "filters.no_loopback",
     f"not loopback and {_ALL_IP} and {_ALL_PROTO}"),
    ("out",  "filters.out",  f"outbound and {_ALL_IP} and {_ALL_PROTO}"),
    ("in",   "filters.in",   f"inbound and {_ALL_IP} and {_ALL_PROTO}"),
    ("tcp",  "filters.tcp",  f"{_ALL_IP} and tcp"),
    ("udp",  "filters.udp",  f"{_ALL_IP} and udp"),
    ("ping", "filters.ping", "icmp or icmpv6"),
    ("loopback", "filters.loopback", f"loopback and {_ALL_IP} and {_ALL_PROTO}"),
]

FILTERS: Dict[str, str] = {name: wd for _, name, wd in FILTER_DEFS}
CLI_FILTERS: Dict[str, str] = {key: wd for key, _, wd in FILTER_DEFS}

# Explicit lookups instead of the old index gymnastics
# (``list(CLI_FILTERS)[list(FILTERS).index(name)]``), which silently depended on
# both dicts keeping the same insertion order.
_BY_CLI: Dict[str, Tuple[str, str, str]] = {
    key: (key, name, wd) for key, name, wd in FILTER_DEFS}
_BY_I18N: Dict[str, Tuple[str, str, str]] = {
    name: (key, name, wd) for key, name, wd in FILTER_DEFS}
DEFAULT_FILTER: str = FILTER_DEFS[0][0]


def cli_key_for(i18n_key: str, default: str = DEFAULT_FILTER) -> str:
    """i18n filter key -> CLI key (``filters.both`` -> ``both``)."""
    entry = _BY_I18N.get(i18n_key)
    return entry[0] if entry else default


def i18n_key_for(cli_key: str, default: str = FILTER_DEFS[0][1]) -> str:
    """CLI filter key -> i18n key (``both`` -> ``filters.both``)."""
    entry = _BY_CLI.get(cli_key)
    return entry[1] if entry else default


def windivert_for(cli_key: str) -> str:
    """CLI filter key -> WinDivert filter expression."""
    entry = _BY_CLI.get(cli_key)
    return entry[2] if entry else CLI_FILTERS[DEFAULT_FILTER]


def i18n_keys() -> List[str]:
    """Filter i18n keys in canonical order (drives the GUI combobox)."""
    return [name for _, name, _ in FILTER_DEFS]


# -- what each filter lets through ----------------------------------------------- #
# Three things a setting can depend on, and the answer each filter gives. A setting
# declares what it needs (``fields.Field.needs``) and ``settings.apply_settings``
# says so when the chosen filter lets none of it through: a session that changes
# nothing reads as a broken tool, not as a filter doing what it was told.
TCP, UDP, ICMP = "tcp", "udp", "icmp"                 # protocol
INBOUND, OUTBOUND = "inbound", "outbound"             # direction
LOOPBACK, NETWORK = "loopback", "network"             # this machine to itself, or not
PORTS = "ports"                                       # derived: TCP or UDP
TRAITS = frozenset({TCP, UDP, ICMP, INBOUND, OUTBOUND, LOOPBACK, NETWORK, PORTS})


class Admits(NamedTuple):
    """What a filter EXPRESSION lets through, as three independent sets.

    Independent because every filter here is a product of the three - measured
    with the driver's own evaluator on Windows and on Linux, 2026-11-13 - and
    ``tests/test_filter_needs.py`` holds each declaration to exactly that product,
    so a filter added later that is not one fails there instead of being described
    wrongly here.

    It describes the expression, not what the driver does with it: Windows hands
    over BOTH halves of a loopback conversation as outbound (measured, see the RST
    builder in ``core.py``), and that trap has a warning of its own
    (``log.loopback_all_upload``) rather than a second one from this table.
    """
    protocols: FrozenSet[str]
    directions: FrozenSet[str]
    paths: FrozenSet[str]

    def lets_through(self, trait: str) -> bool:
        if trait == PORTS:
            return bool(self.protocols & {TCP, UDP})
        return trait in self.protocols or trait in self.directions or trait in self.paths


_EVERY_PROTOCOL = frozenset({TCP, UDP, ICMP})
_BOTH_WAYS = frozenset({INBOUND, OUTBOUND})
_EVERY_PATH = frozenset({LOOPBACK, NETWORK})

# Keyed by CLI key, like the readers of FILTER_DEFS above.
FILTER_ADMITS: Dict[str, Admits] = {
    "both": Admits(_EVERY_PROTOCOL, _BOTH_WAYS, _EVERY_PATH),
    "no-loopback": Admits(_EVERY_PROTOCOL, _BOTH_WAYS, frozenset({NETWORK})),
    "out": Admits(_EVERY_PROTOCOL, frozenset({OUTBOUND}), _EVERY_PATH),
    "in": Admits(_EVERY_PROTOCOL, frozenset({INBOUND}), _EVERY_PATH),
    "tcp": Admits(frozenset({TCP}), _BOTH_WAYS, _EVERY_PATH),
    "udp": Admits(frozenset({UDP}), _BOTH_WAYS, _EVERY_PATH),
    "ping": Admits(frozenset({ICMP}), _BOTH_WAYS, _EVERY_PATH),
    "loopback": Admits(_EVERY_PROTOCOL, _BOTH_WAYS, frozenset({LOOPBACK})),
}


# -- narrowing the handle's filter to what could possibly be impaired ------------ #
def filter_compiles(text: str) -> bool:
    """Would the capture driver accept this filter? ``False`` when it cannot be asked.

    Asked of the driver's OWN parser, never of a guess about its grammar - which
    parser that is belongs to the platform's capture backend
    (``capture_backend.WinDivertBackend.filter_compiles`` says how and why). A
    ``False`` keeps the wide filter, which is the safe direction.

    Imported lazily: ``capture_backend`` is a layer above this module, and
    importing ``filters`` must stay free of it.
    """
    from .capture_backend import current
    return current().filter_compiles(text)


def narrowed_filter(base: str, dst_ip_matcher: Optional[Any] = None,
                    dst_port_matcher: Optional[Any] = None) -> Tuple[str, bool]:
    """``base`` AND the destination expressions, when that can be PROVEN safe.

    Returns ``(filter_text, narrowed)``. ``narrowed`` is False whenever anything
    at all stood in the way, and then ``filter_text`` is ``base`` untouched.

    Why this is worth doing: the filter runs IN THE DRIVER, so a packet the
    destination target could never match need not be handed to this process at
    all. Measured 2026-07-28 - 1944 packets diverted with 0 impairable - almost
    every recv/send pair the tool performed was for traffic it was never going to
    touch.

    ACCEPTED 2026-07-29 on a real capture, and it turned out to be a CORRECTNESS
    fix rather than only a speed one. A flood to the targeted destination plus a
    decoy flood the target does not cover:

        wide    28 050 sent to the target -> 15 768 in scope, 15 768 delivered
        narrow  27 950 sent to the target -> 27 950 in scope, 27 950 delivered

    Without narrowing the driver was overloaded by traffic the tool was never
    going to touch and **discarded 43% of the TARGETED traffic before the tool
    saw it** - so the session both impaired less than it claimed and reported
    numbers computed over the survivors. Narrowed, nothing was lost. The
    driver-wait warning fired in the wide runs (52 and 184 ms) and in neither
    narrowed one, which is the same overload seen from the other end.

    The impairment itself is unchanged: with ``--loss 100`` the narrowed run
    dropped 27 900 of 27 900 and the receiver got nothing, exactly as the wide run
    did. That was the regression worth fearing - a narrowing that also stopped the
    impairing would have looked like a win in every counter.

    Three gates, and each one falls back rather than guessing:

    1. ``matchers.windivert_fragment`` returns ``None`` unless the fragment is a
       provable SUPERSET of the matcher (see its docstring - under-capture is a
       silent regression, over-capture is free).
    2. The result must COMPILE, asked of the driver's own parser. The grammar has
       a length limit - 200 ORed terms compile, 1000 do not (checked) - and an
       expression can be perfectly valid here and too big for it.
    3. Both destination fields are ANDed with ``base``, matching ``decide()``,
       where an IP and a port expression both have to pass. Compiling only one of
       them is still correct: one fewer conjunct is a WIDER filter.
    """
    from .matchers import windivert_fragment          # local: keeps imports flat

    parts = []
    for matcher in (dst_ip_matcher, dst_port_matcher):
        fragment = windivert_fragment(matcher)
        if fragment:
            parts.append(fragment)
    if not parts:
        return base, False
    candidate = "(%s) and %s" % (base, " and ".join(parts))
    if not filter_compiles(candidate):
        return base, False
    return candidate, True
