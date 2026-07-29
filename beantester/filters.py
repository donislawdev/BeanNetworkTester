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


# -- narrowing the handle's filter to what could possibly be impaired ------------ #
def filter_compiles(text):
    """Would WinDivert accept this filter? ``False`` when it cannot be asked.

    ``WinDivertHelperCompileFilter`` is a DLL helper - no handle, no admin - so
    this is the driver's OWN parser, not a guess about its grammar. Off Windows
    (or without ``pydivert``) there is nothing to ask, and ``False`` is the honest
    answer: the caller then keeps the wide filter, which is the safe direction.

    ``pydivert`` is imported lazily on purpose - it is a win32-only dependency and
    importing this module must work on the whole CI matrix.
    """
    if not text:
        return False
    try:
        import ctypes
        from pydivert import windivert_dll as wd
        err, pos = ctypes.c_char_p(), ctypes.c_uint(0)
        buf = ctypes.create_string_buffer(64 * 1024)
        return bool(wd.WinDivertHelperCompileFilter(
            text.encode(), 0, buf, len(buf), ctypes.byref(err), ctypes.byref(pos)))
    except Exception:
        # A missing dll, a missing pydivert, a driver that will not answer: all of
        # them mean "cannot prove this filter is usable", and the caller must not
        # narrow on an unproven filter.
        return False


def narrowed_filter(base, dst_ip_matcher=None, dst_port_matcher=None):
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
