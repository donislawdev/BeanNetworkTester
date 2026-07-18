"""Property-based tests for the filter mini-language (``beantester/matchers.py``).

The example-based tests in ``test_matchers.py`` check the cases we thought of.
These check the INVARIANTS - the things that must hold for every input, including
the ones nobody thought of. That matters here more than anywhere else in the tool:

* ``matches()`` runs inside the capture thread, once per packet. If it can raise,
  it can kill the capture thread - and a dead capture thread with an open divert
  is the "I suddenly have no internet" failure the whole fail-open design exists
  to prevent.
* the mini-language is the ONE parser every filter field goes through
  (convention 10), so a hole in it is a hole in every field, present and future.

Hypothesis explores the input space; a failure is reported with a minimal example
and pinned into ``.hypothesis`` so it is re-run for free from then on.
"""
import ipaddress

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from beantester.matchers import (KIND_INT, KIND_IP, KIND_PROCESS, PORT_BOUNDS,
                                 Matcher, parse_matcher, split_terms)

# Deliberately unconstrained: the point is to feed the parser text a USER could
# type, including nonsense.
expressions = st.text(
    alphabet=st.sampled_from(list("0123456789.:!,-*?/><=abcxyzABC \\[](){}^$|+re:"),),
    min_size=0, max_size=30)

ports = st.one_of(st.none(), st.integers(min_value=-10, max_value=70000),
                  st.text(max_size=6))
ips = st.one_of(st.none(), st.ip_addresses().map(str), st.text(max_size=12))
pids = st.one_of(st.none(), st.integers(min_value=-5, max_value=100000))
names = st.text(max_size=15)

KINDS = [(KIND_INT, PORT_BOUNDS), (KIND_IP, None), (KIND_PROCESS, None)]

SLOW = settings(max_examples=300, deadline=None)


def _parse(text, kind, bounds):
    """Parse, or tell the caller the expression was rejected (which is allowed)."""
    try:
        return parse_matcher(text, kind, "fields.port", bounds=bounds)
    except ValueError:
        return None


# -- 1) the parser only ever fails in the documented way ---------------------- #
@SLOW
@given(text=expressions, which=st.integers(0, 2))
def test_parsing_only_ever_raises_valueerror(text, which):
    """A malformed expression is a translated ``ValueError`` - never a crash.

    Anything else (TypeError, re.error, IndexError...) reaches the GUI as a raw
    traceback and the CLI as a non-coded exit.
    """
    kind, bounds = KINDS[which]
    try:
        parse_matcher(text, kind, "fields.port", bounds=bounds)
    except ValueError:
        pass
    except Exception as exc:                       # pragma: no cover - the bug
        pytest.fail(f"{type(exc).__name__} for {text!r} ({kind}): {exc}")


# -- 2) matches() is total: it NEVER raises ----------------------------------- #
@SLOW
@given(text=expressions, port=ports, ip=ips, pid=pids, name=names,
       which=st.integers(0, 2))
def test_matches_never_raises_whatever_it_is_asked(text, port, ip, pid, name, which):
    """The hot path must be total. A packet with no port, an address from the
    other family, a name that is not a string - none of it may throw."""
    kind, bounds = KINDS[which]
    matcher = _parse(text, kind, bounds)
    assume(matcher is not None)
    try:
        if kind == KIND_PROCESS:
            matcher.matches(pid, name)
            matcher.excluded(pid, name)
        elif kind == KIND_IP:
            matcher.matches(ip)
            matcher.excluded(ip)
        else:
            matcher.matches(port)
            matcher.excluded(port)
    except Exception as exc:                       # pragma: no cover - the bug
        pytest.fail(f"matches() raised {type(exc).__name__} for {text!r}: {exc}")


# -- 3) an empty expression matches everything -------------------------------- #
@given(text=st.sampled_from(["", "   ", ",", " , , "]), port=ports,
       which=st.integers(0, 2))
def test_an_empty_expression_matches_everything(text, port, which):
    kind, bounds = KINDS[which]
    matcher = _parse(text, kind, bounds)
    assume(matcher is not None)
    assert matcher.is_empty
    assert not matcher                             # falsy when empty
    assert matcher.matches(port) if kind != KIND_PROCESS else matcher.matches(1, "x")


# -- 4) negation subtracts: "!x" never matches x, whatever else is in the term - #
@SLOW
@given(value=st.integers(*PORT_BOUNDS), extra=st.integers(*PORT_BOUNDS))
def test_an_exclusion_always_wins_over_a_positive(value, extra):
    """``a,!a`` must not match ``a`` - "positives OR, negatives AND-NOT"."""
    assume(value != extra)
    both = parse_matcher(f"{value},{extra},!{value}", KIND_INT, bounds=PORT_BOUNDS)
    assert not both.matches(value), "an explicit exclusion must win"
    assert both.matches(extra)
    assert both.excluded(value)
    assert not both.excluded(extra)


# -- 5) a range is closed on both ends (nmap/iptables semantics) -------------- #
@SLOW
@given(lo=st.integers(0, 65535), span=st.integers(0, 500), probe=st.integers(0, 65535))
def test_a_range_is_inclusive_on_both_ends(lo, span, probe):
    hi = min(65535, lo + span)
    matcher = parse_matcher(f"{lo}-{hi}", KIND_INT, bounds=PORT_BOUNDS)
    assert matcher.matches(probe) == (lo <= probe <= hi)
    assert matcher.matches(lo) and matcher.matches(hi)      # both ends included


# -- 6) term order never changes the answer ----------------------------------- #
@SLOW
@given(terms=st.lists(st.integers(*PORT_BOUNDS), min_size=2, max_size=5, unique=True),
       probe=st.integers(*PORT_BOUNDS))
def test_term_order_does_not_matter(terms, probe):
    forwards = parse_matcher(",".join(map(str, terms)), KIND_INT, bounds=PORT_BOUNDS)
    backwards = parse_matcher(",".join(map(str, reversed(terms))), KIND_INT,
                              bounds=PORT_BOUNDS)
    assert forwards.matches(probe) == backwards.matches(probe)


# -- 7) an IP rule never matches the other address family --------------------- #
@SLOW
@given(v4=st.ip_addresses(v=4).map(str), v6=st.ip_addresses(v=6).map(str))
def test_an_ip_rule_never_crosses_address_families(v4, v6):
    """A v4 rule must ignore v6 traffic and vice versa - the reason IPv6 used to
    sail straight past the tool."""
    assert parse_matcher(v4, KIND_IP).matches(v4)
    assert not parse_matcher(v4, KIND_IP).matches(v6)
    assert parse_matcher(v6, KIND_IP).matches(v6)
    assert not parse_matcher(v6, KIND_IP).matches(v4)


# -- 8) CIDR agrees with the standard library --------------------------------- #
@SLOW
@given(net=st.ip_addresses(v=4).map(lambda a: f"{a}/24"),
       probe=st.ip_addresses(v=4).map(str))
def test_cidr_agrees_with_ipaddress(net, probe):
    ours = parse_matcher(net, KIND_IP).matches(probe)
    theirs = ipaddress.ip_address(probe) in ipaddress.ip_network(net, strict=False)
    assert ours == theirs, f"{net} vs {probe}"


# -- 9) splitting round-trips the escape ------------------------------------- #
@SLOW
@given(text=expressions)
def test_split_terms_never_produces_an_empty_term(text):
    """An empty term is rejected by the parser, so the splitter must not invent one."""
    for term in split_terms(text):
        assert term.strip(), repr(text)


# -- 10) parsing is idempotent through the canonical form --------------------- #
@SLOW
@given(text=expressions, which=st.integers(0, 2))
def test_describe_reparses_to_the_same_matcher(text, which):
    """``describe()`` is the canonical text; feeding it back must not change meaning."""
    kind, bounds = KINDS[which]
    first = _parse(text, kind, bounds)
    assume(first is not None and not first.is_empty)
    second = _parse(first.describe(), kind, bounds)
    assert second is not None, f"describe() produced something unparseable: {first.describe()!r}"
    probes = [0, 1, 80, 443, 65535, None]
    for probe in probes:
        if kind == KIND_PROCESS:
            assert first.matches(probe, "chrome.exe") == second.matches(probe, "chrome.exe")
        elif kind == KIND_IP:
            assert first.matches("10.0.0.1") == second.matches("10.0.0.1")
        else:
            assert first.matches(probe) == second.matches(probe)


# -- 11) bounds are enforced, never silently clamped -------------------------- #
@SLOW
@given(port=st.integers(min_value=65536, max_value=10 ** 6))
def test_a_port_outside_its_bounds_is_an_error_not_a_clamp(port):
    with pytest.raises(ValueError):
        parse_matcher(str(port), KIND_INT, "fields.port", bounds=PORT_BOUNDS)


# -- 12) a compiled matcher is reusable and stateless ------------------------- #
@SLOW
@given(text=expressions, probe=st.integers(*PORT_BOUNDS))
def test_matching_is_stateless(text, probe):
    """The same matcher, asked twice, answers the same. (It is compiled once and
    then called for every packet of a session - for hours.)"""
    matcher = _parse(text, KIND_INT, PORT_BOUNDS)
    assume(matcher is not None)
    assert matcher.matches(probe) == matcher.matches(probe)
    assert isinstance(matcher, Matcher)
