"""The port scan's logic (``nettools/portscan.py``): what is scanned, at what pace,
what an answer means, and what it says.

Most tests stand in for the sockets and the clock (``FakeNet``), so the pace, the Stop
and the second round are measured in exact numbers on every runner. A few touch the
real system on loopback only: a held TCP port and a UDP echo here, a closed port next
to them, and a subprocess under an audit hook that shows the scan connects to the
typed address and nowhere else - the Tools tab's promise (``test_no_telemetry.py``).
"""
import errno
import ipaddress
import json
import socket
import struct
import subprocess
import sys
import threading

import pytest

from beantester.nettools import Refused, adapters, portscan as ps
from beantester.adapters import AddressRow
from fakes import ROOT, check


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeNet:
    """Answers per port: ``script[(proto, port)]`` or ``script[port]`` = (Answer or None,
    after_s). None is silence; ``after_s`` 0 answers at once (a refusal the system knows
    straight away). Like the real selector, ``answers`` reports every socket still
    waiting, whatever protocol it was asked on."""

    REFUSED = (ps.Answer(ps.CLOSED, 10061), 0)

    def __init__(self, clock, script=None):
        self.clock = clock
        self.script = script or {}
        self.default = self.REFUSED
        self.waiting = {}           # (proto, port) -> (due, answer)
        self.started = []           # (time, proto, port)
        self.most_waiting = 0
        self.closed = False
        self.flows = ()

    def start(self, proto, port, wait_s):
        self.started.append((self.clock.now, proto, port))
        answer, after = self.script.get((proto, port), self.script.get(port, self.default))
        if answer is not None and after == 0:
            return answer
        self.waiting[(proto, port)] = (self.clock.now + after, answer)
        self.most_waiting = max(self.most_waiting, len(self.waiting))
        return None

    def answers(self, proto, timeout):
        due = [d for d, a in self.waiting.values() if a is not None and d <= self.clock.now + timeout]
        self.clock.now = min(due) if due and min(due) > self.clock.now else (
            self.clock.now if due else self.clock.now + timeout)
        out = [(k, a) for k, (d, a) in self.waiting.items() if a is not None and d <= self.clock.now]
        for key, _answer in out:
            del self.waiting[key]
        return [(port, answer) for (_proto, port), answer in out]

    def give_up(self, proto, port):
        self.waiting.pop((proto, port), None)
        return ps.Answer(ps.SILENT)

    def close(self):
        self.closed = True


def a_plan(ports, pace=ps.NEAR, protocols=(ps.TCP,), own=False, address="192.0.2.10"):
    return ps.Plan(ps.ping.Target(address, "", address), tuple(ports), protocols, pace, own,
                   False)


def run(ports, script=None, pace=ps.NEAR, protocols=(ps.TCP,), progress=None, **kw):
    clock = Clock()
    net = FakeNet(clock, script, **kw)
    result = ps.scan(a_plan(ports, pace, protocols), progress, net=net, clock=clock)
    return result, net, clock


def states(result):
    return {(port, row.proto): row.state for row in result.rows
            for port in range(row.port, row.last + 1)}


# -- what was typed ------------------------------------------------------------- #
@pytest.mark.parametrize("text, key", [
    ("", "empty"), ("999.1.1.1", "bad_address"), ("0.0.0.0", "not_one"),
    ("224.0.0.1", "not_one"), ("a..b", "bad_name"), ("fe80::1", "zone"),
])
def test_what_is_not_one_computer_is_refused_in_the_scans_words(text, key):
    with pytest.raises(Refused) as caught:
        ps.parse_target(text)
    check(f"{text!r} refused as {key}", caught.value.user_key == f"tools.portscan.refused.{key}",
          f"({caught.value.user_key})")


def test_an_address_and_a_name_are_taken():
    check("an address", ps.parse_target(" 192.168.1.50 ").address == "192.168.1.50", "")
    target = ps.parse_target("printer.local")
    check("a name, looked up later", (target.name, target.address) == ("printer.local", ""),
          f"({target})")
    check("a link-local address with its adapter", ps.parse_target("fe80::1%12").address
          == "fe80::1%12", "")


def lookup_to(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return lambda _name: [(family, socket.SOCK_STREAM, 6, "", (address, 0))]


def snapshot(*addresses):
    rows = tuple(AddressRow(ip, ipaddress.ip_address(ip).version, prefix, 0, 0, 0)
                 for ip, prefix in addresses)

    class Row:
        pass

    row = Row()
    row.addresses = rows

    class Adapter:
        pass

    adapter = Adapter()
    adapter.row = row
    return lambda: adapters.Snapshot((adapter,), 0.0, 0, 1)


def test_the_pace_follows_where_the_computer_is():
    def pace_of(address, read):
        target = ps.parse_target(address)
        return ps.plan(target, ps.parse_ports("80"), (ps.TCP,), read=read)

    mine = snapshot(("192.168.1.29", 24), ("fe80::5%12", 64))
    near = pace_of("192.168.1.50", mine)
    check("an address in an adapter's prefix is near", (near.pace, near.own) == (ps.NEAR, False),
          f"({near.pace})")
    far = pace_of("192.168.2.50", mine)
    check("one outside every prefix is behind a router", far.pace == ps.FAR, f"({far.pace})")
    own = pace_of("192.168.1.29", mine)
    check("this computer's own address", (own.pace, own.own) == (ps.NEAR, True), "")
    check("loopback is this computer", pace_of("127.0.0.1", None).own, "")

    def unreadable():
        raise adapters.Unreadable("tools.adapters.error_changing", "on purpose")

    check("an adapter list that cannot be read: the slower pace",
          pace_of("192.168.1.50", unreadable).pace == ps.FAR, "")
    named = ps.plan(ps.parse_target("printer.local"), ps.parse_ports("80"), (ps.TCP,),
                    lookup=lookup_to("192.168.1.77"), read=mine)
    check("a name is looked up, then placed", (named.target.address, named.pace)
          == ("192.168.1.77", ps.NEAR), f"({named})")


def test_ports_the_scan_cannot_ask_are_refused_in_its_words():
    for text, key in (("0", "error_zero"), ("re:^$", "error_none")):
        with pytest.raises(Refused) as caught:
            ps.plan(ps.parse_target("192.0.2.1"), ps.parse_ports(text), (ps.TCP,), read=None)
        check(f"{text!r}", caught.value.user_key == f"tools.portscan.refused.{key}",
              f"({caught.value.user_key})")


def test_the_estimate_is_the_slowest_the_first_round_can_be():
    every = a_plan(range(1, 65536), ps.FAR)
    check("behind a router, every port silent: 32 at a time, 3 s each",
          ps.estimate_s(every) == 2048 * 3.0, f"({ps.estimate_s(every)})")
    check("near, 256 at a time, 1 s each",
          ps.estimate_s(a_plan(range(1, 65536), ps.NEAR)) == 256.0, "")
    check("a few ports behind a router: the rate, not the waiting",
          ps.estimate_s(a_plan(range(1, 101), ps.FAR._replace(at_once=1000))) == 5.0, "")


# -- the pace -------------------------------------------------------------------- #
def busiest_second(net):
    starts = [at for at, _proto, _port in net.started]
    return max(sum(1 for t in starts if s <= t < s + 1.0) for s in starts)


def test_behind_a_router_no_more_than_the_pace_allows():
    """The promise to the router between, in the owner's numbers (2026-11-11) rather
    than the module's constant, so a changed constant cannot carry the test with it:
    32 at once, 20 new a second, 3 s for a silent port, whatever the answers."""
    script = {port: (None, 0) for port in range(1, 201)}          # all silent
    result, net, clock = run(range(1, 201), script, ps.FAR)
    check("at most 20 new in any second", busiest_second(net) <= 20, f"({busiest_second(net)})")
    check("at most 32 waiting at once", net.most_waiting <= 32, f"({net.most_waiting})")
    check("every port asked, and silent", set(states(result).values()) == {ps.SILENT},
          f"({set(states(result).values())})")
    check("each silent port given its 3 s: 200 at 32 a time",
          clock.now - 100.0 >= 200 / 32 * 3.0 - 3.0, f"({clock.now - 100.0})")
    _quick, net, _clock = run(range(1, 201), None, ps.FAR)           # all refused at once
    check("answers that come at once do not lift the rate", busiest_second(net) <= 20,
          f"({busiest_second(net)})")


def test_a_near_computer_is_asked_as_fast_as_it_answers():
    script = {port: (ps.Answer(ps.CLOSED, 111), 0.001) for port in range(1, 1001)}
    result, net, clock = run(range(1, 1001), script, ps.NEAR)
    check("256 at once and no rate cap", net.most_waiting == ps.NEAR.at_once,
          f"({net.most_waiting})")
    check("all closed", set(states(result).values()) == {ps.CLOSED}, "")
    check("in about four rounds of a millisecond", clock.now - 100.0 < 0.1, f"({clock.now})")


def test_a_silent_port_waits_its_time_and_no_longer():
    script = {7: (None, 0), 8: (ps.Answer(ps.OPEN), 0.9), 9: (ps.Answer(ps.OPEN), 1.5)}
    result, _net, _clock = run((7, 8, 9), script, ps.NEAR)
    seen = states(result)
    check("silent", seen[(7, ps.TCP)] == ps.SILENT, f"({seen})")
    check("an answer inside the wait counts", seen[(8, ps.TCP)] == ps.OPEN, f"({seen})")
    check("an answer after it does not", seen[(9, ps.TCP)] == ps.SILENT, f"({seen})")


# -- Stop, giving up, the second round ------------------------------------------- #
def test_stop_ends_the_scan_and_keeps_what_was_answered():
    progress = ps.Progress()
    script = {port: (ps.Answer(ps.CLOSED, 111), 0.3) for port in range(1, 2001)}
    clock = Clock()
    net = FakeNet(clock, script)
    original = net.answers

    def answers(proto, timeout):
        out = original(proto, timeout)
        if progress.made >= 300:
            progress.stop()
        return out

    net.answers = answers
    result = ps.scan(a_plan(range(1, 2001)), progress, net=net, clock=clock)
    check("it says it stopped, and where", result.stopped and result.stopped_at[0] == ps.TCP,
          f"({result.stopped_at})")
    check("short of the end", 300 <= result.made < result.planned == 2000,
          f"({result.made}, {result.planned})")
    check("only answered ports are rows", sum(r.size() for r in result.rows) == result.made,
          f"({len(result.rows)})")
    check("the sockets put away", net.closed, "")
    early = ps.Progress()
    early.stop()
    none, _net, _clock = run(range(1, 10), None, progress=early)
    check("a Stop before the first port", (none.stopped, none.stopped_at, none.rows)
          == (True, (), ()), f"({none.stopped_at})")


def test_an_unreachable_computer_is_given_up_on():
    script = {port: (ps.Answer(ps.UNREACHABLE, 113), 0.5) for port in range(1, 65536)}
    result, net, _clock = run(range(1, 65536), script, ps.NEAR, protocols=(ps.TCP, ps.UDP))
    check("it stops asking after its first answers", len(net.started) == ps.NEAR.at_once,
          f"({len(net.started)})")
    check("and asks no UDP port of a computer that is not there",
          (result.gave_up, result.skipped) == ((ps.TCP,), (ps.UDP,))
          and all(proto == ps.TCP for _t, proto, _port in net.started),
          f"({result.gave_up}, {result.skipped})")
    said = ps.conclusions(result)
    # The count is the table's: the first wave's answers came together, all 256 of them.
    check("the conclusions name both",
          ("tools.portscan.say.unreachable", {"proto": ps.TCP, "count": ps.NEAR.at_once}) in said
          and ("tools.portscan.say.skipped", {"proto": ps.UDP, "by": ps.TCP}) in said, f"({said})")
    check("and so does the report",
          "UDP: not asked, the computer could not be reached" in ps.report(result), "")
    mixed = dict(script)
    mixed[3] = (ps.Answer(ps.OPEN), 0)
    result, net, _clock = run(range(1, 200), mixed, ps.NEAR)
    check("one other answer and it does not give up", result.gave_up == ()
          and len(net.started) == 199, f"({result.gave_up}, {len(net.started)})")


def test_a_computer_not_there_is_given_up_on_after_the_first_silence():
    """Linux gives up on the neighbour of an address nobody holds about 3 s after the
    first try, and the near pace waits 1 s a port: the first two waves read "no answer",
    the third hears "unreachable" at its last moment, and later tries fail at once.
    Silence must not keep the scan from stopping (measured 2026-11-12: it never stopped,
    3000 ports in 12.6 s)."""
    at_once = ps.NEAR.at_once
    after = {0: 3.0, 1: 2.0, 2: 1.0}            # until the neighbour fails, by wave
    script = {port: (ps.Answer(ps.UNREACHABLE, 113), after.get((port - 1) // at_once, 0))
              for port in range(1, 3001)}
    result, net, clock = run(range(1, 3001), script, ps.NEAR)
    check("it gives up", result.gave_up == (ps.TCP,), f"({result.gave_up})")
    check("once the third wave heard it, and not a port more",
          len(net.started) == 3 * at_once, f"({len(net.started)})")
    check("about when the neighbour failed", clock.now - 100.0 <= 3.0 + ps.POLL_S,
          f"({clock.now - 100.0:.2f} s)")
    seen = set(states(result).values())
    check("the ports read before it stay silent", seen == {ps.SILENT, ps.UNREACHABLE}, f"({seen})")
    instant = {port: (ps.Answer(ps.UNREACHABLE, 113), 0) for port in range(1, 3001)}
    result, net, _clock = run(range(1, 3001), instant, ps.NEAR)
    check("a neighbour failed already: refused at once, and it stops at the count",
          result.gave_up == (ps.TCP,) and len(net.started) == ps.GIVE_UP_AFTER,
          f"({result.gave_up}, {len(net.started)})")


def test_the_last_answers_of_a_round_can_give_up():
    """A range no bigger than one wave: every port waits, the answers come together and
    nothing is left to start - the round ends there, and it must still give up."""
    script = {port: (ps.Answer(ps.UNREACHABLE, 113), 0.5) for port in range(1, ps.GIVE_UP_AFTER + 1)}
    result, net, _clock = run(range(1, ps.GIVE_UP_AFTER + 1), script, ps.NEAR,
                              protocols=(ps.TCP, ps.UDP))
    check("TCP given up on, UDP not asked", (result.gave_up, result.skipped)
          == ((ps.TCP,), (ps.UDP,)) and all(proto == ps.TCP for _t, proto, _port in net.started),
          f"({result.gave_up}, {result.skipped}, {len(net.started)} started)")


def test_a_second_round_does_not_give_up_on_a_computer_that_answered():
    """"Not there" is about the whole protocol: when ports answered in the first round,
    a second round that hears "unreachable" (the computer went away in between) asks
    every port it was given, and the next protocol is still asked."""
    script = {port: (ps.Answer(ps.CLOSED, 111), 0) for port in range(1, 1001)}
    again = range(901, 1001)                    # 10 %: just few enough to be asked again
    script.update({(ps.TCP, port): (None, 0) for port in again})
    clock = Clock()
    net = FakeNet(clock, script)
    original_start = net.start
    asked = set()

    def start(proto, port, wait_s):
        if (proto, port) in asked and port in again:
            script[(proto, port)] = (ps.Answer(ps.UNREACHABLE, 113), 0)
        asked.add((proto, port))
        return original_start(proto, port, wait_s)

    net.start = start
    result = ps.scan(a_plan(range(1, 1001), protocols=(ps.TCP, ps.UDP)), net=net, clock=clock)
    check("every silent port asked again, and every one changed",
          result.again == (ps.Again(ps.TCP, 100, 100),), f"({result.again})")
    check("not given up on, and UDP asked", (result.gave_up, result.skipped) == ((), ())
          and sum(1 for _t, proto, _port in net.started if proto == ps.UDP) == 1000,
          f"({result.gave_up}, {result.skipped})")
    check("the second round's answers are in the table",
          states(result)[(950, ps.TCP)] == ps.UNREACHABLE, "")
    check("and no sentence says the computer is not there", not any(
        key == "tools.portscan.say.unreachable" for key, _args in ps.conclusions(result)), "")


def test_a_protocol_given_up_on_leaves_no_socket_waiting():
    """TCP gives up while some of its ports still wait: their sockets are given up then,
    in the round, not left for whatever comes after it."""
    script = {(ps.TCP, port): (ps.Answer(ps.OPEN), 0.5) for port in range(1, 17)}
    script.update({(ps.TCP, port): (ps.Answer(ps.UNREACHABLE, 113), 0) for port in range(17, 81)})
    result, net, _clock = run(range(1, 81), script, ps.NEAR, protocols=(ps.TCP, ps.UDP))
    check("TCP gave up with 16 ports still waiting", result.gave_up == (ps.TCP,)
          and len(net.started) == 80, f"({result.gave_up}, {len(net.started)})")
    check("none of them left waiting", net.waiting == {}, f"({sorted(net.waiting)})")


def test_a_few_silent_ports_are_asked_again_slower():
    """A busy host (macOS limits its RSTs): the silent minority gets a second round, at
    most 32 at once, and an answer there replaces the silence."""
    script = {port: (ps.Answer(ps.CLOSED, 61), 0) for port in range(1, 1001)}
    for port in range(1, 51):
        script[port] = (None, 0)
    clock = Clock()
    net = FakeNet(clock, script)
    original_start = net.start
    asked = []
    second_round = []           # how many wait, after each start of the second round

    def start(proto, port, wait_s):
        asked.append(port)
        again = asked.count(port) == 2
        if again and port <= 40:
            script[port] = (ps.Answer(ps.CLOSED, 61), 0.5)     # it answers the second time
        answer = original_start(proto, port, wait_s)
        if again:
            second_round.append(len(net.waiting))
        return answer

    net.start = start
    progress = ps.Progress()
    result = ps.scan(a_plan(range(1, 1001)), progress, net=net, clock=clock)
    check("the 50 silent ones asked again", result.again == (ps.Again(ps.TCP, 50, 40),),
          f"({result.again})")
    # The first round had 256 at once (a near computer); every one of the 50 waits in
    # the second, so 32 is that round's own limit, reached.
    check("32 at once then", max(second_round) == 32, f"({max(second_round)})")
    seen = states(result)
    check("the recovered ones read closed, the rest still silent",
          [seen[(p, ps.TCP)] for p in (1, 40, 41, 50)] == [ps.CLOSED, ps.CLOSED, ps.SILENT,
                                                          ps.SILENT], f"({seen[(41, ps.TCP)]})")
    check("the count includes the second round", (result.made, result.planned) == (1050, 1050),
          f"({result.made}, {result.planned})")


def test_a_firewall_that_drops_most_gets_no_second_round():
    script = {port: (None, 0) for port in range(1, 101)}
    script[22] = (ps.Answer(ps.OPEN), 0)
    result, net, _clock = run(range(1, 101), script, ps.NEAR)
    check("no second round when nearly everything is silent", result.again == ()
          and len(net.started) == 100, f"({result.again})")


# -- rows and what they say ------------------------------------------------------- #
def test_ports_next_to_each_other_with_the_same_answer_are_one_row():
    script = {22: (ps.Answer(ps.OPEN), 0), 30: (None, 0), 31: (None, 0)}
    result, _net, _clock = run(range(20, 40), script)
    shape = [(r.port, r.last, r.state, r.service) for r in result.rows]
    check("folded, a service of its own breaks a run", shape == [
        (20, 20, ps.CLOSED, ""), (21, 21, ps.CLOSED, "FTP"), (22, 22, ps.OPEN, "SSH"),
        (23, 23, ps.CLOSED, "Telnet"), (24, 24, ps.CLOSED, ""), (25, 25, ps.CLOSED, "SMTP"),
        (26, 29, ps.CLOSED, ""), (30, 31, ps.SILENT, ""), (32, 39, ps.CLOSED, "")], f"({shape})")
    check("counted in ports", ps.counts(result)[(ps.TCP, ps.CLOSED)] == 17, "")


def test_silence_reads_the_same_whoever_gave_up_first():
    """On Windows the system ends a silent try at the scan's own wait, so a silent
    port's answer is the system's time-out (10060) or the scan giving up - by chance.
    Both read "no answer", so next ports with either are one row (measured 2026-11-12:
    one scan of 300 silent ports split into dozens of rows that read the same)."""
    script = {port: (ps.classify(10060), ps.NEAR.wait_s) for port in range(30, 40, 2)}
    script.update({port: (None, 0) for port in range(31, 40, 2)})
    result, _net, _clock = run(range(30, 40), script)
    shape = [(r.port, r.last, r.state, r.code) for r in result.rows]
    check("one row of silence", shape == [(30, 39, ps.SILENT, 0)], f"({shape})")


def test_what_an_error_number_means():
    for code, state in ((0, ps.OPEN), (10061, ps.CLOSED), (errno.ECONNREFUSED, ps.CLOSED),
                        (10054, ps.CLOSED), (errno.EHOSTUNREACH, ps.UNREACHABLE),
                        (10065, ps.UNREACHABLE), (10060, ps.SILENT), (10013, ps.DENIED),
                        (errno.EACCES, ps.DENIED), (9999, ps.FAILED)):
        check(f"{code}", ps.classify(code).state == state, f"({ps.classify(code)})")


def test_the_conclusions_say_what_a_person_needs():
    silent = {port: (None, 0) for port in range(1, 11)}
    result, _net, _clock = run(range(1, 11), silent)
    keys = [key for key, _args in ps.conclusions(result)]
    check("nothing answered", keys == ["tools.portscan.say.all_silent"], f"({keys})")
    udp, _net, _clock = run(range(1, 11), None, protocols=(ps.UDP,))
    keys = [key for key, _args in ps.conclusions(udp._replace(udp_closed_seen=False))]
    check("UDP, and why no port reads closed here",
          keys == ["tools.portscan.say.udp", "tools.portscan.say.udp_no_closed"], f"({keys})")
    own = ps.scan(a_plan((1,), own=True), net=FakeNet(Clock()), clock=Clock())
    check("this computer's own address is said first",
          ps.conclusions(own)[0][0] == "tools.portscan.say.own", "")


def test_the_report_is_plain_english_with_every_row():
    script = {22: (ps.Answer(ps.OPEN), 0), 23: (ps.Answer(ps.DENIED, 10013), 0)}
    result, _net, _clock = run(range(20, 26), script)
    text = ps.report(result)
    for line in ("Port scan of 192.0.2.10", "TCP 22 open (SSH)",
                 "TCP 23 not allowed (Telnet, code 10013)", "TCP 24 closed", "same network"):
        check(f"says {line!r}", line in text, f"({text})")


# -- the ICMP the sniffer reads ---------------------------------------------------- #
def icmp4(target, port, proto=17):
    inner_ip = bytes([0x45, 0, 0, 28, 0, 0, 0, 0, 64, proto, 0, 0]) + bytes([10, 0, 0, 5]) + target
    inner_udp = struct.pack(">HHHH", 50000, port, 8, 0)
    icmp = bytes([3, 3, 0, 0, 0, 0, 0, 0]) + inner_ip + inner_udp
    outer = bytes([0x45, 0, 0, 20 + len(icmp), 0, 0, 0, 0, 64, 1, 0, 0]) + target + bytes([10, 0, 0, 5])
    return outer + icmp


def icmp6(target, port, proto=17):
    inner = bytes([0x60, 0, 0, 0, 0, 8, proto, 64]) + bytes(16) + target
    icmp = bytes([1, 4, 0, 0, 0, 0, 0, 0]) + inner + struct.pack(">HHHH", 50000, port, 8, 0)
    outer = bytes([0x60, 0, 0, 0, 0, len(icmp), 58, 64]) + target + bytes(16)
    return outer + icmp


def test_the_port_a_port_unreachable_is_about():
    v4 = ipaddress.ip_address("192.168.1.1").packed
    v6 = ipaddress.ip_address("fe80::1").packed
    check("IPv4", ps._closed_port(icmp4(v4, 5353), v4, False) == 5353, "")
    check("IPv6", ps._closed_port(icmp6(v6, 161), v6, True) == 161, "")
    other = ipaddress.ip_address("192.168.1.2").packed
    check("about another computer: not ours", ps._closed_port(icmp4(other, 53), v4, False)
          is None, "")
    check("about TCP: not a UDP port", ps._closed_port(icmp4(v4, 53, proto=6), v4, False)
          is None, "")
    check("cut short: nothing", ps._closed_port(icmp4(v4, 53)[:40], v4, False) is None, "")


def test_the_sniffer_is_opened_only_where_it_can_help(monkeypatch):
    opened = []
    monkeypatch.setattr(ps, "_Sniffer", lambda address: opened.append(address) or "sniffer")
    monkeypatch.setattr(ps, "WIN", True)
    monkeypatch.setattr(ps.winenv, "is_admin", lambda: True)
    check("UDP of another computer, elevated, Windows",
          ps.open_sniffer(a_plan((53,), protocols=(ps.UDP,))) == "sniffer", "")
    check("not for TCP alone", ps.open_sniffer(a_plan((53,))) is None, "")
    check("not for this computer", ps.open_sniffer(a_plan((53,), protocols=(ps.UDP,), own=True))
          is None, "")
    monkeypatch.setattr(ps.winenv, "is_admin", lambda: False)
    check("not without administrator rights",
          ps.open_sniffer(a_plan((53,), protocols=(ps.UDP,))) is None, "")
    check("opened once, for the scanned address", opened == ["192.0.2.10"], f"({opened})")


def test_a_sniffer_whose_sockets_cannot_be_made_is_closed_again(monkeypatch):
    """The sniffer holds a driver handle: when the scan's sockets cannot be made after
    it opened, the scan closes it before it fails."""
    closed = []

    class Sniffer:
        def close(self):
            closed.append(True)

    def no_sockets(address, sniffer):
        raise OSError(errno.EMFILE, "too many open files")

    monkeypatch.setattr(ps, "open_sniffer", lambda scan_plan: Sniffer())
    monkeypatch.setattr(ps, "_Net", no_sockets)
    with pytest.raises(OSError):
        ps.scan(a_plan((53,), protocols=(ps.UDP,)))
    check("the sniffer is closed", closed == [True], f"({closed})")


def test_the_ports_seen_refused_are_kept_in_place_and_asked_by_port():
    """What the sniffer's thread saw, read by the scan's thread: one set, added to in
    place (not copied whole for each message), asked only about the ports waiting."""
    seen = ps._Seen()
    kept = seen._ports
    for port in range(1, 1001):
        seen.add(port)
    check("the same set, grown in place", seen._ports is kept and len(kept) == 1000, "")
    check("only the ports asked about", seen.among({5, 999, 2000}) == {5, 999},
          f"({seen.among({5, 999, 2000})})")


def test_a_udp_port_the_sniffer_saw_refused_reads_closed():
    """With the sniffer, a UDP port whose ICMP "port unreachable" it copied is Closed,
    whether the message comes while the port waits or by the time it is given up on."""
    quiet = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    quiet.bind(("127.0.0.1", 0))        # takes the datagram and never answers
    port = quiet.getsockname()[1]

    class Sniffer:
        def closed_among(self, ports):
            return {p for p in ports if p == port}

    net = ps._Net("127.0.0.1", Sniffer())
    try:
        check("asked, and waiting", net.start(ps.UDP, port, 1.0) is None, "")
        got = net.answers(ps.UDP, 0)
        check("the sniffer's word is the answer", got == [(port, ps.Answer(ps.CLOSED))],
              f"({got})")
        check("and nothing waits for it any more", net.waiting == {}, f"({net.waiting})")
        net.start(ps.UDP, port, 1.0)
        check("given up on, it reads closed too",
              net.give_up(ps.UDP, port) == ps.Answer(ps.CLOSED), "")
    finally:
        net.close()
        quiet.close()


# -- the real system, loopback only ------------------------------------------------ #
def _servers():
    tcp = socket.socket()
    tcp.bind(("127.0.0.1", 0))
    tcp.listen(8)
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    udp.settimeout(10)
    accepted = []

    def echo():
        try:
            data, peer = udp.recvfrom(2048)
            udp.sendto(b"pong:" + data, peer)
        except OSError:
            pass

    threading.Thread(target=echo, daemon=True).start()
    return tcp, udp, accepted


def _free_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_a_real_scan_of_this_computer_tells_open_from_closed():
    tcp, udp, _accepted = _servers()
    try:
        held_tcp, held_udp = tcp.getsockname()[1], udp.getsockname()[1]
        free_tcp, free_udp = _free_port(socket.SOCK_STREAM), _free_port(socket.SOCK_DGRAM)
        tcp_plan = ps.Plan(ps.ping.Target("127.0.0.1", "", "127.0.0.1"),
                           tuple(sorted((held_tcp, free_tcp))), (ps.TCP,), ps.NEAR, True, False)
        result = ps.scan(tcp_plan)
        seen = states(result)
        check("the held TCP port is open", seen[(held_tcp, ps.TCP)] == ps.OPEN, f"({seen})")
        check("the free one closed, at once", seen[(free_tcp, ps.TCP)] == ps.CLOSED
              and result.elapsed_s < 1.0, f"({seen}, {result.elapsed_s})")
        conn, _peer = tcp.accept()
        conn.settimeout(5)
        try:
            ended = conn.recv(1)
        except ConnectionResetError:
            ended = "reset"
        check("the open connection ended with a reset, not a close that waits",
              ended == "reset", f"({ended!r})")
        conn.close()
        udp_plan = tcp_plan._replace(ports=tuple(sorted((held_udp, free_udp))),
                                     protocols=(ps.UDP,))
        result = ps.scan(udp_plan)
        rows = {row.port: row for row in result.rows}
        check("the UDP echo answers: open, with its reply's size",
              (rows[held_udp].state, rows[held_udp].reply) == (ps.OPEN, 5), f"({rows})")
        check("the free UDP port closed (loopback passes the ICMP)",
              rows[free_udp].state == ps.CLOSED, f"({rows[free_udp]})")
    finally:
        tcp.close()
        udp.close()


AUDIT = r"""
import json, socket, sys, threading
sys.path.insert(0, {root!r})
from beantester.nettools import portscan as ps
seen = []
def hook(event, args):
    if event == "socket.connect":
        sock, address = args
        kind = "TCP" if sock.type == socket.SOCK_STREAM else "UDP"
        seen.append((event, kind, list(address)[:2]))
    elif event.startswith("socket."):
        seen.append((event, None, None))
sys.addaudithook(hook)
held = socket.socket(); held.bind(("127.0.0.1", 0)); held.listen(4)
port = held.getsockname()[1]
plan = ps.Plan(ps.ping.Target("127.0.0.1", "", "127.0.0.1"), (port, port + 1), ("TCP", "UDP"),
               ps.NEAR, True, False)
start = len(seen)
ps.scan(plan)
run = seen[start:]
canary = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
canary.connect(("192.0.2.1", 9))
canary.close()
print("BEGIN_JSON" + json.dumps({{"run": run, "all": seen, "port": port}}))
"""


def test_a_scan_connects_only_to_the_address_typed():
    """Behind the Tools tab's sending entry for this module: under an audit hook, a scan
    of 127.0.0.1 makes sockets and connects them to 127.0.0.1 - nothing else, no name
    lookup, no datagram sent anywhere by address. The canary proves the hook would
    report a connect elsewhere."""
    proc = subprocess.run([sys.executable, "-c", AUDIT.format(root=ROOT)], cwd=ROOT,
                          capture_output=True, text=True, timeout=120, check=False)
    out = proc.stdout
    assert "BEGIN_JSON" in out, (out[-800:], proc.stderr[-800:])
    seen = json.loads(out.split("BEGIN_JSON", 1)[1])
    kinds = sorted({event for event, _kind, _address in seen["run"]})
    check("only sockets made and connected", kinds == ["socket.__new__", "socket.connect"],
          f"({kinds})")
    connects = [(kind, address) for event, kind, address in seen["run"]
                if event == "socket.connect"]
    port = seen["port"]
    check("one connect per port and protocol, to the ports typed",
          sorted((kind, address[1]) for kind, address in connects)
          == [("TCP", port), ("TCP", port + 1), ("UDP", port), ("UDP", port + 1)],
          f"({connects})")
    check("every one to the typed address",
          all(address[0] == "127.0.0.1" for _kind, address in connects), f"({connects})")
    check("the hook reports a connect elsewhere when shown one",
          ["UDP", ["192.0.2.1", 9]] in [[kind, address] for event, kind, address in seen["all"]
                                         if event == "socket.connect"],
          f"({seen['all'][-2:]})")


def test_the_box_says_how_many_ports_a_plain_list_names():
    """The default list of 71 ports read "21, 22, 23, ... 69, 8" in its box, so what
    would be scanned could not be seen (UX audit 2026-11-13, UX-GUI-017). A plain
    list is counted as the scan lists it - overlaps once, port 0 never; anything
    else would mean listing 65535 ports on every key, so it is not counted."""
    table = [(ps.COMMON_TEXT, 71), ("80, 443", 2), ("1-1024", 1024), ("80, 80", 1),
             ("0-10", 10), ("1-100, 50-150", 150), (" 22 ,", 1), ("65535", 1),
             ("!80", None), ("8*", None), ("re:^80", None), ("", None), ("0", None),
             ("70000", None), ("10-5", None), ("80-", None),
             # a digit int() refuses must not raise out of the key handler
             (chr(0xB2), None), ("80-" + chr(0xB3), None), (chr(0x2460), None),
             # a decimal digit of another script is a number to the scan too
             (chr(0x0668) + chr(0x0660), 1)]
    for text, want in table:
        assert ps.listed_count(text) == want, (text, ps.listed_count(text), want)
    arabic_eighty = chr(0x0668) + chr(0x0660)
    assert ps.parse_ports(arabic_eighty).matches(80), "the scan reads it as port 80"
