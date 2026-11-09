"""The call scope: impairments that reach only some parts of a call (decide() step 2).

``ice.call_part`` says from the bytes what a datagram is; these tests are about what
the core, the engine and the settings do with that answer. The rule they hold in
place is the one whose failure costs most: a scope that stops narrowing impairs
everything it was meant to spare, with every number on screen looking healthy.
"""
import random
import time

from beantester import BeanEngine, core as core_module
from beantester.cli import build_arg_parser, config_from_args
from beantester.core import BeanCore
from beantester.repro import settings_to_cli
from beantester.settings import (DEFAULT_SETTINGS, apply_settings, targeting_is_set,
                                 unbounded_impairment)
from beantester.summary import settings_summary
from fakes import FakeDivert, check, wait_until
from test_ice import (ALLOCATE_REQUEST, BINDING_REQUEST, DTLS, HOME, PEER_LAN, PRIORITY, RTP,
                      WirePacket, channel_data, message, udp4)

CHECK = message(BINDING_REQUEST, PRIORITY)
CONTROL = message(ALLOCATE_REQUEST)
QUIC = bytes([0xc3]) + bytes(40)            # a long header: no part of any call
FLOW = (50000, PEER_LAN, 50001)
LABELLED = {"ice": "LAN"}                   # a connection log row that carried STUN
UNLABELLED = {"ice": ""}                    # ...and one that never did


def scoped_core(checks=False, turn_control=False, media=False, rows=lambda key: LABELLED):
    """A core that drops everything it reaches, so "in scope" reads as a drop."""
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)
    core.set_call_parts(checks, turn_control, media)
    core.read_call_flows_from(rows)
    return core


def judge(core, payload, remote=PEER_LAN, is_tcp=False, raw=True):
    wire = udp4(HOME, remote, payload, 50000, 50001, proto=6 if is_tcp else 17)
    return core.decide(len(wire), True, 50000, 1.0, random.Random(1), remote_ip=remote,
                       remote_port=50001, is_tcp=is_tcp, raw=wire if raw else None)


def untouched(decision):
    return not decision.drop and not decision.scoped


# -- the core ----------------------------------------------------------------- #
def test_a_call_scope_alone_spares_everything_else():
    """With no destination set, the call scope is the one test between a packet and
    every impairment of the session."""
    core = scoped_core(media=True)
    check("QUIC passes untouched", untouched(judge(core, QUIC)))
    check("TCP passes untouched", untouched(judge(core, RTP, is_tcp=True)))
    check("the call's media is impaired", judge(core, RTP).drop)


def test_each_switch_reaches_its_own_part_only():
    packets = {"checks": CHECK, "turn_control": CONTROL, "media": DTLS}
    for switch in packets:
        core = scoped_core(**{switch: True})
        for part, payload in packets.items():
            dropped = judge(core, payload).drop
            check(f"{switch} on: {part} {'impaired' if part == switch else 'spared'}",
                  dropped is (part == switch), f"({dropped})")
    every = scoped_core(checks=True, turn_control=True, media=True)
    check("all three on: the whole call", all(judge(every, p).drop for p in packets.values()))
    check("and still nothing else", untouched(judge(every, QUIC)))


def test_media_counts_only_on_a_flow_that_has_carried_stun():
    """The first byte of DTLS and RTP is also QUIC with its fixed bit at random
    (RFC 9287), a VPN on DTLS, and ChannelData's range is QUIC's short header."""
    for row, says, wanted in ((LABELLED, "has carried STUN", True),
                              (UNLABELLED, "has not carried STUN", False),
                              (None, "is not in the log yet", False)):
        core = scoped_core(media=True, rows=lambda key, r=row: r)
        for what, payload in (("RTP", RTP), ("DTLS", DTLS), ("in a frame", channel_data(RTP))):
            dropped = judge(core, payload).drop
            check(f"{what}, the flow {says}", dropped is wanted, f"({dropped})")
    unwired = scoped_core(media=True, rows=None)
    check("with nobody to ask, no media is in scope", untouched(judge(unwired, RTP)))


def test_only_media_asks_about_the_flow_and_tcp_is_not_even_read(monkeypatch):
    asked, read = [], []
    real = core_module.call_part
    monkeypatch.setattr(core_module, "call_part", lambda raw: read.append(1) or real(raw))
    core = scoped_core(checks=True, turn_control=True, media=True,
                       rows=lambda key: asked.append(key) or LABELLED)
    for payload in (CHECK, CONTROL, QUIC, channel_data(CHECK)):
        judge(core, payload)
    check("STUN, TURN and the rest prove themselves", asked == [], f"({asked})")
    judge(core, RTP)
    check("media asks once, by the connection log's key", asked == [FLOW], f"({asked})")
    read.clear()
    judge(core, RTP, is_tcp=True)
    check("TCP is never parsed", read == [], f"({len(read)})")


def test_a_packet_without_its_bytes_is_no_part_of_a_call():
    core = scoped_core(checks=True, turn_control=True, media=True)
    check("untouched", untouched(judge(core, CHECK, raw=False)))


def test_the_call_scope_and_the_destination_have_to_agree():
    core = scoped_core(media=True)
    core.set_dest(True, "10.0.0.99")
    check("media to another address is spared", untouched(judge(core, RTP)))
    check("media to the destination is impaired", judge(core, RTP, remote="10.0.0.99").drop)
    check("and not what else goes there", untouched(judge(core, QUIC, remote="10.0.0.99")))
    core.set_ip_family(ipv6_only=True)
    check("nor what the family leaves out", untouched(judge(core, RTP, remote="10.0.0.99")))


def test_the_scope_gate_follows_every_setter():
    """decide() reads one flag for all of step 2; each setter keeps it."""
    core = scoped_core()
    check("nothing aimed: QUIC is impaired", judge(core, QUIC).drop)
    core.set_call_parts(media=True)
    check("the call scope spares it", untouched(judge(core, QUIC)))
    core.set_dest(True, "10.0.0.0/8")
    core.set_dest(False)
    check("a destination switched off leaves the call scope standing",
          untouched(judge(core, QUIC)))
    core.set_ip_family(ipv4_only=True)
    core.set_ip_family()
    check("so does a family switched off", untouched(judge(core, QUIC)))
    core.set_call_parts()
    check("the call scope off: QUIC is impaired again", judge(core, QUIC).drop)
    core.set_dest(True, "10.0.0.99")
    check("a destination alone narrows as before", untouched(judge(core, QUIC)))
    core.set_dest(False)
    core.set_ip_family(ipv6_only=True)
    check("and so does a family", untouched(judge(core, QUIC)))


def test_the_core_knows_whether_a_ticked_part_has_passed():
    """``call_met``: what the GUI's "nothing ticked has passed yet" line reads. Set
    only by a packet the call scope lets in; started again by a NEW choice of parts
    and by a new session, never by applying the same parts again."""
    core = scoped_core(checks=True)
    check("nothing has passed at first", core.call_met is False)
    judge(core, QUIC)
    judge(core, RTP)
    check("QUIC and media are no checks", core.call_met is False)
    judge(core, CHECK, is_tcp=True)
    check("nor is STUN over TCP", core.call_met is False)
    core.set_dest(True, "10.9.9.9")
    judge(core, CHECK)
    check("nor a check the destination turned down", core.call_met is False)
    core.set_dest(False)
    core.set_target(True, {40000})                  # a process that owns another port
    judge(core, CHECK)
    check("nor a check the target process turned down", core.call_met is False)
    core.set_target(False, set())
    judge(core, CHECK)
    check("a check in scope is", core.call_met is True)
    core.set_call_parts(checks=True)
    check("the same parts applied again keep it", core.call_met is True)
    core.set_call_parts(checks=True, media=True)
    check("other parts start the question again", core.call_met is False)
    judge(core, CHECK)
    core.reset_buckets(0.0)
    check("and so does a new session", core.call_met is False)


def test_the_engine_answers_none_without_a_call_scope():
    engine = BeanEngine()
    check("no call scope: no answer", engine.call_parts_met() is None)
    engine.set_call_parts(media=True)
    check("a call scope that met nothing: False", engine.call_parts_met() is False)
    engine.core.call_met = True
    check("and then True", engine.call_parts_met() is True)


def test_the_call_scope_counts_as_targeting():
    core = BeanCore()
    check("off", not core.targeting_active())
    core.set_call_parts(turn_control=True)
    check("on", core.targeting_active())


# -- through the engine ------------------------------------------------------- #
def flow_packet(payload, remote_port=50001):
    return WirePacket(payload, remote_port=remote_port)


def wait_seen(engine, count):
    check(f"{count} packets seen",
          wait_until(lambda: engine.stats_snapshot()["seen"] >= count))


class OpenDivert(FakeDivert):
    """``FakeDivert`` that keeps looking at its inbox, so a test can add packets to a
    session that is already running."""

    def recv(self):
        while not self.closed:
            if self.i < len(self.inbox):
                self.i += 1
                return self.inbox[self.i - 1]
            time.sleep(0.003)
        raise OSError("closed")


def test_through_the_engine_a_call_loses_its_media_and_keeps_its_checks():
    # The VPN sends twice: its first packet comes before the connection log has a row
    # for it, and only the second asks about a flow the log knows and never saw STUN on.
    packets = [flow_packet(CHECK), flow_packet(DTLS), flow_packet(RTP), flow_packet(CHECK),
               flow_packet(RTP),
               flow_packet(DTLS, remote_port=443),     # a VPN on DTLS: never carried STUN
               flow_packet(DTLS, remote_port=443),
               flow_packet(QUIC, remote_port=444)]
    engine = BeanEngine()
    engine.set_seed(7)
    apply_settings(engine, dict(DEFAULT_SETTINGS, call_media=True, loss=100))
    divert = FakeDivert(packets)
    engine.start("test", divert=divert)
    try:
        wait_seen(engine, len(packets))
        stats = engine.stats_snapshot()
    finally:
        engine.stop()
    check("the three media packets of the call were lost", stats["drop_loss"] == 3,
          f"({stats['drop_loss']})")
    check("and only they were in scope", stats["scoped_seen"] == 3, f"({stats['scoped_seen']})")
    check("the checks, the VPN and QUIC went through", len(divert.sent) == 5,
          f"({len(divert.sent)})")


def test_a_split_call_counts_in_scope_only_the_packets_that_were():
    """Checks and media share the call's flow. The row's flag said "in scope" for
    the whole flow, and the delivered "in scope" totals were credited by that flag,
    so with only the checks in scope every media byte counted as targeted traffic.
    The row counts its packets in scope and the totals follow each packet."""
    call = [flow_packet(CHECK), flow_packet(DTLS), flow_packet(RTP), flow_packet(CHECK),
            flow_packet(RTP)]
    other = flow_packet(QUIC, remote_port=444)
    total = sum(len(p.raw) for p in call) + len(other.raw)
    checks = 2 * len(flow_packet(CHECK).raw)
    engine = BeanEngine()
    engine.set_seed(7)
    apply_settings(engine, dict(DEFAULT_SETTINGS, call_checks=True))
    divert = FakeDivert(call + [other])
    engine.start("test", divert=divert)
    try:
        wait_seen(engine, len(call) + 1)
        check("everything was delivered", wait_until(
            lambda: engine.stats_snapshot()["bytes_in"]
            + engine.stats_snapshot()["bytes_out"] >= total))
        stats = engine.stats_snapshot()
        rows = {row["remote_port"]: row for row in engine.connections_snapshot(limit=None)}
    finally:
        engine.stop()
    row = rows[50001]
    check("the call's row is in scope", row["scoped"] is True, f"({row})")
    check("for its two checks, not its five packets",
          (row["packets"], row["scoped_packets"]) == (5, 2), f"({row})")
    check("QUIC beside it had none in scope",
          (rows[444]["scoped"], rows[444]["scoped_packets"]) == (False, 0), f"({rows[444]})")
    scoped = stats["bytes_in_scoped"] + stats["bytes_out_scoped"]
    check("the delivered bytes in scope are the checks' alone", scoped == checks,
          f"({scoped} B, the checks are {checks} B of {total})")


def test_a_call_scope_switched_on_mid_session_knows_the_calls_already_going():
    """The ICE labels are written whether or not a call scope is on, so a scenario
    that kills the media at t=30 kills it at once, not at the next consent check."""
    engine = BeanEngine()
    engine.set_seed(7)
    apply_settings(engine, dict(DEFAULT_SETTINGS))
    divert = OpenDivert([flow_packet(CHECK), flow_packet(RTP)])
    engine.start("test", divert=divert)
    try:
        wait_seen(engine, 2)
        apply_settings(engine, dict(DEFAULT_SETTINGS, call_media=True, loss=100))
        divert.inbox += [flow_packet(RTP), flow_packet(QUIC, remote_port=444)]
        wait_seen(engine, 4)
        stats = engine.stats_snapshot()
    finally:
        engine.stop()
    check("the next media packet was lost, and only it", stats["drop_loss"] == 1,
          f"({stats['drop_loss']})")
    check("QUIC beside it went through", len(divert.sent) == 3, f"({len(divert.sent)})")


# -- settings, CLI, reproduction, summary ------------------------------------ #
def test_a_call_scope_bounds_a_session():
    """Only the packets of calls: no warning about damaging all traffic."""
    for key in ("call_checks", "call_turn_control", "call_media"):
        s = dict(DEFAULT_SETTINGS, loss=50, **{key: True})
        check(f"{key} is targeting", targeting_is_set(s))
        check(f"{key}: not unbounded", not unbounded_impairment(s))
    check("without it the warning stands", unbounded_impairment(dict(DEFAULT_SETTINGS, loss=50)))


def test_the_three_flags_reach_the_settings_and_come_back_in_the_command():
    flags = ["--call-checks", "--call-turn-control", "--call-media"]
    keys = ["call_checks", "call_turn_control", "call_media"]
    for flag, key in zip(flags, keys, strict=True):
        settings = config_from_args(build_arg_parser().parse_args([flag, "--loss", "5"]))[
            "settings"]
        check(f"{flag} sets {key} alone",
              [k for k in keys if settings[k]] == [key], f"({[k for k in keys if settings[k]]})")
        check(f"{flag} is in the reproduction command",
              flag in settings_to_cli(settings) and
              not any(f in settings_to_cli(settings) for f in flags if f != flag))


def test_the_summary_names_the_parts_once():
    s = dict(DEFAULT_SETTINGS, call_checks=True, call_media=True)
    text = settings_summary(s, lang="en")
    check("one phrase for both", "call only: checks, media" in text, f"({text})")
    check("nothing without a call scope",
          "call only" not in settings_summary(dict(DEFAULT_SETTINGS), lang="en"))
