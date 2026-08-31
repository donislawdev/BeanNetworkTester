"""Both address families are the default, and adding a way to choose one may not change that.

WHY THIS FILE EXISTS AT ALL
    Capturing IPv6 was not free here. The filters all began with ``ip and ...``,
    which in the WinDivert language means IPv4 ONLY, so every IPv6 packet went
    past the tool - not impaired, not counted, not listed - which on a dual-stack
    machine is most of a browser's traffic. ``filters.py`` was rewritten around
    that, and its module docstring still leads with the rule.

    The address-family switch is a way to ask for exactly the state that bug
    produced. That makes the DEFAULT worth a guard of its own rather than a
    shrug: everything here asserts what an untouched form does, and nothing here
    asserts what the new switch does (``test_core.py`` covers that).

    The filter strings are written out as literals rather than computed from the
    thing under test. A guard that builds its expectation the same way the code
    does agrees with the code by construction, including when the code is wrong -
    which is precisely the failure this file is here to catch.
"""
import random

from beantester.core import BeanCore
from beantester.filters import FILTER_DEFS, windivert_for
from beantester.repro import settings_to_cli
from beantester.settings import DEFAULT_SETTINGS, settings_from_raw
from beantester.summary import settings_summary
from fakes import check

# Every driver filter this program can ask for, spelled out. Both families in
# every one of them: `ip` is IPv4, `ipv6` is IPv6, and `ping` covers both through
# its two protocol names instead.
EXPECTED_FILTERS = {
    "both": "(ip or ipv6) and (tcp or udp or icmp or icmpv6)",
    "out": "outbound and (ip or ipv6) and (tcp or udp or icmp or icmpv6)",
    "in": "inbound and (ip or ipv6) and (tcp or udp or icmp or icmpv6)",
    "tcp": "(ip or ipv6) and tcp",
    "udp": "(ip or ipv6) and udp",
    "ping": "icmp or icmpv6",
    "loopback": "loopback and (ip or ipv6) and (tcp or udp or icmp or icmpv6)",
}


def _settings(**overrides):
    result = settings_from_raw(dict(overrides))
    return result[0] if isinstance(result, tuple) else result


def test_every_driver_filter_still_carries_both_families():
    """The one that would catch a family folded into the filter by accident."""
    check("the registry gained or lost no filter",
          sorted(key for key, _, _ in FILTER_DEFS) == sorted(EXPECTED_FILTERS),
          f"({sorted(key for key, _, _ in FILTER_DEFS)})")
    for key, expected in EXPECTED_FILTERS.items():
        check(f"filter {key!r} is unchanged, character for character",
              windivert_for(key) == expected, f"({windivert_for(key)!r})")


def test_the_default_settings_choose_neither_family():
    check("ipv4_only is off by default", DEFAULT_SETTINGS["ipv4_only"] is False)
    check("ipv6_only is off by default", DEFAULT_SETTINGS["ipv6_only"] is False)


def test_a_default_session_impairs_both_families():
    """The behaviour the switch exists to narrow, asserted from the other side."""
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)
    rng = random.Random(1)
    v4 = core.decide(100, True, 5000, 0.0, rng, remote_ip="1.2.3.4", remote_port=80)
    v6 = core.decide(100, True, 5000, 0.0, rng, remote_ip="2001:db8::1", remote_port=80)
    check("IPv4 is impaired by default", v4.drop is True and v4.scoped is True)
    check("IPv6 is impaired by default", v6.drop is True and v6.scoped is True)


def test_the_default_summary_and_repro_command_gained_nothing():
    """A field that says nothing at its default keeps the two things a user reads
    exactly as they were - the sentence under the title and the command they copy."""
    settings = _settings(loss=10)
    summary = settings_summary(settings, lang="en")
    check("no family fragment in the summary of a default form",
          "IPv4" not in summary and "IPv6" not in summary, f"({summary!r})")
    args = settings_to_cli(settings)
    check("no family flag in the reproduction command",
          "--ipv4-only" not in args and "--ipv6-only" not in args, f"({args})")
    # And the other direction, so this cannot pass by the flags never existing.
    armed = settings_to_cli(_settings(loss=10, ipv4_only=True))
    check("the flag does appear once it is asked for", "--ipv4-only" in armed,
          f"({armed})")
