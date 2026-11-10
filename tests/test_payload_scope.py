"""The payload-size scope: impairments that reach only packets carrying a given
number of bytes of data (decide() step 2).

``wire.payload_length`` reads the size from the bytes (tests/test_wire.py); these
tests are about what the core, the engine and the settings do with it. The rule
they hold in place is the one whose failure costs most: a scope that stops
narrowing impairs everything it was meant to spare, with every number on screen
looking healthy.
"""
import random

import pytest

from beantester import BeanEngine
from beantester.cli import build_arg_parser, config_from_args
from beantester.core import BeanCore
from beantester.fields import FIELDS, NARROWING_KEYS
from beantester.matchers import PAYLOAD_BOUNDS
from beantester.repro import settings_to_cli
from beantester.settings import (DEFAULT_SETTINGS, apply_settings, targeting_is_set,
                                 unbounded_impairment, validate_settings)
from beantester.summary import settings_summary
from fakes import FakeDivert, check, wait_until
from test_ice import (BINDING_REQUEST, HOME, PEER_LAN, PRIORITY, WirePacket, message, udp4,
                      udp6)
from test_wire import tcp4

STUN = message(BINDING_REQUEST, PRIORITY)


def scoped_core(udp=None, tcp=None):
    """A core that drops everything it reaches, so "in scope" reads as a drop."""
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)
    core.set_payload(udp=udp, tcp=tcp)
    return core


def judge(core, raw, is_tcp=False, remote=PEER_LAN, port=50001):
    return core.decide(len(raw) if raw is not None else 100, True, 50000, 1.0,
                       random.Random(1), remote_ip=remote, remote_port=port,
                       is_tcp=is_tcp, raw=raw)


def udp(size):
    return udp4(HOME, PEER_LAN, bytes(size), 50000, 50001)


def untouched(decision):
    return not decision.drop and not decision.scoped


# -- the core ----------------------------------------------------------------- #
def test_a_payload_scope_alone_spares_everything_else():
    """With no destination and no process target, the payload scope is the one test
    between a packet and every impairment of the session."""
    core = scoped_core(udp="64-1472")
    check("a keepalive below the range passes untouched", untouched(judge(core, udp(20))))
    check("a datagram above it passes untouched", untouched(judge(core, udp(1473))))
    for size in (64, 500, 1472):
        check(f"{size} bytes is impaired", judge(core, udp(size)).drop)
    check("both ends of the range are inside it, the next byte is not",
          [judge(core, udp(n)).drop for n in (63, 64, 1472, 1473)]
          == [False, True, True, False])


def test_filling_in_one_protocol_leaves_the_other_alone():
    core = scoped_core(udp=">=0")
    check("every datagram is in scope", judge(core, udp(0)).drop and judge(core, udp(9000)).drop)
    check("TCP passes untouched, data or not",
          untouched(judge(core, tcp4(bytes(500)), is_tcp=True))
          and untouched(judge(core, tcp4(b""), is_tcp=True)))
    core = scoped_core(tcp="!0")
    check("TCP with data is impaired", judge(core, tcp4(bytes(1)), is_tcp=True).drop)
    check("a bare acknowledgement passes untouched",
          untouched(judge(core, tcp4(b""), is_tcp=True)))
    check("and UDP passes untouched", untouched(judge(core, udp(500))))


def test_with_both_filled_in_each_packet_is_asked_its_own_protocol():
    core = scoped_core(udp="100", tcp="0")
    check("UDP by the UDP expression",
          judge(core, udp(100)).drop and untouched(judge(core, udp(0))))
    check("TCP by the TCP expression",
          judge(core, tcp4(b""), is_tcp=True).drop
          and untouched(judge(core, tcp4(bytes(100)), is_tcp=True)))


def test_what_cannot_be_read_is_never_in_scope():
    """"!0" means "everything except 0" - and an unreadable packet is not 0 bytes, so
    an exclusion-only expression is the one that would let it in."""
    for expression in (">=0", "!0", "!5000"):
        core = scoped_core(udp=expression, tcp=expression)
        label = f"udp/tcp {expression!r}"
        check(f"{label}: no bytes at all (a caller without them)", untouched(judge(core, None)))
        check(f"{label}: ICMP", untouched(judge(core, udp4(HOME, PEER_LAN, bytes(40), proto=1))))
        check(f"{label}: a fragment",
              untouched(judge(core, udp4(HOME, PEER_LAN, bytes(40), frag=0x2000))))
        check(f"{label}: all zeros (what --simulate sends)", untouched(judge(core, bytes(120))))
        check(f"{label}: zeros asked as TCP",
              untouched(judge(core, bytes(120), is_tcp=True)))
        check(f"{label}: IPv6 behind an extension header",
              untouched(judge(core, udp6("fd00::1", "fd00::2", bytes(40), next_header=0),
                              remote="fd00::2")))
    check("a readable IPv6 datagram is in scope",
          judge(scoped_core(udp="40"), udp6("fd00::1", "fd00::2", bytes(40)), remote="fd00::2").drop)


def test_the_scope_gate_follows_the_payload_setter():
    """decide() reads one flag for all of step 2; this setter keeps it too."""
    core = scoped_core()
    check("nothing aimed: everything is impaired",
          judge(core, udp(20)).drop and not core.targeting_active())
    core.set_payload(udp="64-1472")
    check("the scope spares the keepalive", untouched(judge(core, udp(20))))
    check("and counts as targeting", core.targeting_active())
    core.set_dest(True, "10.0.0.0/8")
    core.set_dest(False)
    check("a destination switched off leaves it standing", untouched(judge(core, udp(20))))
    core.set_call_parts(media=True)
    core.set_call_parts()
    check("so does a call scope switched off", untouched(judge(core, udp(20))))
    core.set_payload()
    check("cleared: the keepalive is impaired again",
          judge(core, udp(20)).drop and not core.targeting_active())
    core.set_payload(udp="", tcp="  ")
    check("blank expressions are no scope either", judge(core, udp(20)).drop)


def test_the_payload_scope_narrows_together_with_the_others():
    core = scoped_core(udp="64-1472")
    core.set_dest(True, "203.0.113.0/24")
    there = "203.0.113.7"
    check("the right size to another address passes untouched", untouched(judge(core, udp(100))))
    check("the wrong size to the right address passes untouched",
          untouched(judge(core, udp4(HOME, there, bytes(20), 50000, 50001), remote=there)))
    check("the right size to the right address is impaired",
          judge(core, udp4(HOME, there, bytes(100), 50000, 50001), remote=there).drop)
    core.set_dest(False)
    core.set_ip_family(ipv6_only=True)
    check("with IPv6 only, an IPv4 datagram of the right size passes untouched",
          untouched(judge(core, udp(100))))


def test_a_call_scope_still_decides_last_and_still_knows_what_it_met():
    """The call scope sets ``call_met`` on the packet that IS in scope, so it has to
    stay the last test of the step: a STUN check the payload scope turned down must
    not read as a call the session reached."""
    core = scoped_core(udp=str(len(STUN) + 1))          # one byte off: nothing matches
    core.set_call_parts(checks=True)
    wire = udp4(HOME, PEER_LAN, STUN, 50000, 50001)
    check("the check passes untouched", untouched(judge(core, wire)))
    check("and the call was not met", core.call_met is False)
    core.set_payload(udp=str(len(STUN)))
    check("with its size in scope the check is impaired", judge(core, wire).drop)
    check("and the call was met", core.call_met is True)


def test_the_expressions_take_the_shared_syntax_and_its_bounds():
    low, high = PAYLOAD_BOUNDS
    for good in ("0", "64-1472", "!0", ">=64", "0, 64-1472", f"{high}", "<100, !20", "*"):
        scoped_core(udp=good, tcp=good)
    for bad in (str(high + 1), "1472-64", "64-", "-1", "abc"):
        with pytest.raises(ValueError):
            scoped_core(udp=bad)
        with pytest.raises(ValueError):
            scoped_core(tcp=bad)
    check("the bounds are the ones the fields declare",
          FIELDS["payload_udp"].bounds == FIELDS["payload_tcp"].bounds == (low, high) == (0, 65535))


def test_a_bad_expression_leaves_the_scope_as_it_was():
    """Never by switching the scope off: off means "impair everything", so a field
    that could not be read would widen the session to the whole machine."""
    engine = BeanEngine()
    apply_settings(engine, dict(DEFAULT_SETTINGS, loss=100, payload_udp="64-1472"))
    said = []
    apply_settings(engine, dict(DEFAULT_SETTINGS, loss=100, payload_udp="1472-64"), said.append)
    check("the apply said the filter was skipped", len(said) == 1, f"({said})")
    check("the keepalive is still spared", untouched(judge(engine.core, udp(20))))
    check("and the range is still impaired", judge(engine.core, udp(100)).drop)
    apply_settings(engine, dict(DEFAULT_SETTINGS, loss=100))
    check("an empty field switches the scope off", judge(engine.core, udp(20)).drop)


# -- through the engine ------------------------------------------------------- #
def test_through_the_engine_only_the_sizes_asked_for_are_lost():
    sizes = (0, 20, 64, 700, 1472, 1473)
    packets = [WirePacket(bytes(size)) for size in sizes]
    engine = BeanEngine()
    engine.set_seed(7)
    apply_settings(engine, dict(DEFAULT_SETTINGS, payload_udp="64-1472", loss=100))
    divert = FakeDivert(packets)
    engine.start("test", divert=divert)
    try:
        check("every packet was seen",
              wait_until(lambda: engine.stats_snapshot()["seen"] >= len(packets)))
        check("the rest were delivered", wait_until(lambda: len(divert.sent) >= 3))
        stats = engine.stats_snapshot()
    finally:
        engine.stop()
    check("the three in range were lost", stats["drop_loss"] == 3, f"({stats['drop_loss']})")
    check("and only they were in scope", stats["scoped_seen"] == 3, f"({stats['scoped_seen']})")
    delivered = sorted(len(p.raw) - 28 for _t, p in divert.sent)
    check("the others went through, byte for byte", delivered == [0, 20, 1473], f"({delivered})")


# -- settings, CLI, reproduction, summary ------------------------------------ #
def test_a_payload_scope_is_not_a_bound():
    """">=0" reaches every datagram on the machine, so the warning about damaging
    all traffic must stand - the reason the address-family pair is no bound."""
    for key in ("payload_udp", "payload_tcp"):
        s = dict(DEFAULT_SETTINGS, loss=50, **{key: "64-1472"})
        check(f"{key} does not count as narrowing", key not in NARROWING_KEYS)
        check(f"{key}: targeting is not set by it", not targeting_is_set(s))
        check(f"{key}: the run is still unbounded", unbounded_impairment(s))
        check(f"{key} alone impairs nothing",
              not unbounded_impairment(dict(DEFAULT_SETTINGS, **{key: "64-1472"})))


def test_the_two_flags_reach_the_settings_and_come_back_in_the_command():
    args = ["--payload-udp", "64-1472", "--payload-tcp", "!0", "--loss", "5"]
    settings = config_from_args(build_arg_parser().parse_args(args))["settings"]
    check("both reach the settings",
          (settings["payload_udp"], settings["payload_tcp"]) == ("64-1472", "!0"),
          f"({settings['payload_udp']!r}, {settings['payload_tcp']!r})")
    command = settings_to_cli(settings)
    check("and come back in the reproduction command, each with its value",
          command[command.index("--payload-udp") + 1] == "64-1472"
          and command[command.index("--payload-tcp") + 1] == "!0", f"({command})")
    again = config_from_args(build_arg_parser().parse_args(command))["settings"]
    check("which parses back to the same pair",
          (again["payload_udp"], again["payload_tcp"]) == ("64-1472", "!0"))
    check("neither is in the command of a session without them",
          not [a for a in settings_to_cli(dict(DEFAULT_SETTINGS, loss=5)) if "payload" in a])
    for flag in ("--payload-udp", "--payload-tcp"):
        with pytest.raises(SystemExit):
            config_from_args(build_arg_parser().parse_args([flag, "70000"]))


def test_the_new_flags_break_no_abbreviation():
    """``allow_abbrev`` is on, and a second flag with the same opening makes the short
    form ambiguous - argparse then refuses it with exit 2. ``--udp-payload`` and
    ``--tcp-payload`` would have done that to ``--u`` and ``--t``."""
    parser = build_arg_parser()
    check("--u is still --up", parser.parse_args(["--u", "100"]).up == 100)
    check("--t is still --target", parser.parse_args(["--t", "chrome"]).target == "chrome")
    check("--flap-p is still --flap-period",
          parser.parse_args(["--flap-p", "8"]).flap_period == 8)
    check("--flap-d is still --flap-down",
          parser.parse_args(["--flap-d", "25"]).flap_down == 25)
    check("--payload-u and --payload-t are unambiguous",
          parser.parse_args(["--payload-u", "1", "--payload-t", "2"]).payload_tcp == "2")


def test_a_config_file_value_is_validated_like_a_typed_one():
    with pytest.raises(ValueError):
        validate_settings(dict(DEFAULT_SETTINGS, payload_udp="65536"))
    with pytest.raises(ValueError):
        validate_settings(dict(DEFAULT_SETTINGS, payload_tcp="9-1"))
    validate_settings(dict(DEFAULT_SETTINGS, payload_udp="64-1472", payload_tcp="!0"))


def test_a_bare_zero_from_a_config_file_is_a_size_not_an_empty_field():
    """A port's 0 was the old "unset", so a numeric 0 there reads as empty. Here 0 is
    what a bare acknowledgement carries: read as empty it would switch the scope off
    and the session would impair every packet instead of only those."""
    for number in (0, 0.0):
        engine = BeanEngine()
        apply_settings(engine, {**DEFAULT_SETTINGS, "loss": 100, "payload_tcp": number})
        check(f"{number!r}: a bare acknowledgement is in scope",
              judge(engine.core, tcp4(b""), is_tcp=True).drop)
        check(f"{number!r}: a segment with data is spared",
              untouched(judge(engine.core, tcp4(bytes(100)), is_tcp=True)))
        check(f"{number!r}: the summary names it",
              "payload only: TCP 0" in settings_summary(
                  {**DEFAULT_SETTINGS, "payload_tcp": number}, lang="en"))
    engine = BeanEngine()
    apply_settings(engine, {**DEFAULT_SETTINGS, "loss": 100, "payload_udp": 100})
    check("any other bare number is that size",
          judge(engine.core, udp(100)).drop and untouched(judge(engine.core, udp(101))))
    with pytest.raises(ValueError):
        validate_settings({**DEFAULT_SETTINGS, "payload_udp": 1.5})


def test_a_number_too_large_for_anything_is_a_config_error():
    """JSON carries integers of any length. One past what a float can hold raised
    OverflowError on its way to the bounds check, which is a crash and not a message."""
    for key in ("payload_udp", "payload_tcp"):
        for huge in (10 ** 400, 65536, -1):
            with pytest.raises(ValueError):
                validate_settings({**DEFAULT_SETTINGS, key: huge})
        engine = BeanEngine()
        apply_settings(engine, {**DEFAULT_SETTINGS, "loss": 100, key: "64-1472"})
        said = []
        apply_settings(engine, {**DEFAULT_SETTINGS, "loss": 100, key: 10 ** 400}, said.append)
        check(f"{key}: a scenario step with it is skipped, out loud", len(said) == 1, f"({said})")
        check(f"{key}: and the scope stays as it was", engine.core.targeting_active())


def test_the_summary_names_the_scope_once():
    both = settings_summary(dict(DEFAULT_SETTINGS, payload_udp="64-1472", payload_tcp="!0"),
                            lang="en")
    check("one phrase for both fields", "payload only: UDP 64-1472, TCP !0" in both, f"({both})")
    one = settings_summary(dict(DEFAULT_SETTINGS, payload_tcp="0"), lang="en")
    check("one field, one name", "payload only: TCP 0" in one and "UDP" not in one, f"({one})")
    check("nothing without a payload scope",
          "payload" not in settings_summary(dict(DEFAULT_SETTINGS), lang="en"))
