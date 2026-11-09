"""The NAT and STUN tool's logic (``nettools/nat.py``): what was typed, the verdicts,
and every job against a router held in memory.

``FakeNat`` stands in for the network the way ``portmap._Native``'s stand-ins do: two
servers and a router with the behaviours the analysis measured (2026-11-04 and
2026-11-09) - a mapping per socket that is independent of the destination or not,
a hairpin that comes back from the public address or the local one or not at all,
and the owner's router, which drops a hairpin datagram that comes unasked and, after
a few of them, closes that pair for good. A datagram with a TTL of 1 dies at the
router (or is delivered here, sent to this computer's own address).

Two tests use the real sockets, on loopback only: the tool against a STUN and TURN
server written for the test, and the receive loop after an ICMP error (Windows
reports 10054 on the next receive).
"""
import socket
import sys
import threading

import pytest

from beantester import stun
from beantester.nettools import Refused
from beantester.nettools import nat

LOCAL, PUBLIC = "10.0.0.20", "203.0.113.7"
STUN_AT, TURN_AT = "192.0.2.1", "192.0.2.2"
NAMES = {"stun.test": STUN_AT, "turn.test": TURN_AT}


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    """The fake answers at once: the waits only cost the run time."""
    monkeypatch.setattr(nat, "TRIES_S", (0.02, 0.02, 0.02))
    monkeypatch.setattr(nat, "ROUND_S", 0.002)
    monkeypatch.setattr(nat, "SETTLE_S", 0.02)
    monkeypatch.setattr(nat, "OPEN_S", 0.002)
    monkeypatch.setattr(nat, "POLL_S", 0.001)


class FakeUdp:
    def __init__(self, net, family):
        self.net, self.family = net, family
        net.last_port += 1
        self.port = net.last_port
        self.inbox = []
        self.closed = False
        net.socks[self.port] = self

    def send(self, data, to, ttl=None):
        assert not self.closed
        self.net.send(self, bytes(data), (to[0], to[1]), ttl)

    def receive(self, timeout):
        return self.inbox.pop(0) if self.inbox else None

    def close(self):
        self.closed = True


class FakeNat:
    """Two servers and a router, in memory (see the module's docstring)."""

    def __init__(self, mapping=nat.INDEPENDENT, hairpin="public", lead_kills=True,
                 no_nat=False, silent=(), udp_turn="401", tcp=None, duplicate=False,
                 keep_port=False, refuse_udp=False):
        self.mapping, self.hairpin, self.lead_kills = mapping, hairpin, lead_kills
        self.no_nat, self.silent, self.udp_turn = no_nat, set(silent), udp_turn
        self.tcp = {3478: "401", 80: "401"} if tcp is None else tcp
        self.duplicate, self.keep_port, self.refuse_udp = duplicate, keep_port, refuse_udp
        self.public = LOCAL if no_nat else PUBLIC
        self.last_port = 50000
        self.socks = {}
        self.ports = {}             # (local port, mapping key) -> public port
        self.last_public = 8741
        self.state = set()          # (local port, (address, port)) sent through the router
        self.unasked = {}           # (from port, to port) -> unasked hairpin datagrams
        self.dead = set()
        self.log = []               # (local port, to, ttl, data)
        self.received = []          # what the servers got: (server, request)
        self.on_send = None

    # -- the _Net interface ------------------------------------------------------- #
    def lookup(self, name, port):
        if name not in NAMES:
            raise socket.gaierror(11001, "not found")
        return [(socket.AF_INET, NAMES[name])]

    def udp(self, family):
        if self.refuse_udp:
            raise OSError(10047, "address family not supported")
        return FakeUdp(self, family)

    def route_source(self, family, address):
        return LOCAL

    def tcp_ask(self, family, address, port, data, timeout):
        mode = self.tcp.get(port, "no_connection")
        request = stun.decode(data)
        self.received.append(("tcp", port, request))
        if mode in ("refused", "no_connection", "no_answer", "not_stun"):
            return mode, b""
        if mode == "garbage":
            return "answer", b"\x01\x13\x00\x00" + stun.COOKIE + bytes(12)
        return "answer", self._allocate_answer(request, mode)

    # -- the wire ----------------------------------------------------------------- #
    def _public_port(self, sock, to):
        key = {nat.INDEPENDENT: None, nat.BY_ADDRESS: to[0]}.get(self.mapping, to)
        if self.no_nat or (self.keep_port and key is None):
            return sock.port
        if (sock.port, key) not in self.ports:
            self.last_public += 1
            self.ports[(sock.port, key)] = self.last_public
        return self.ports[(sock.port, key)]

    def _allocate_answer(self, request, mode):
        if mode == "success":
            return stun.encode(stun.ALLOCATE, stun.SUCCESS, request.transaction)
        code = int(mode)
        value = bytes((0, 0, code // 100, code % 100)) + b"words of the server"
        return stun.encode(stun.ALLOCATE, stun.ERROR, request.transaction,
                           ((stun.ERROR_CODE, value),))

    def send(self, sock, data, to, ttl):
        self.log.append((sock.port, to, ttl, data))
        if self.on_send:
            self.on_send(self)
        if ttl == 1:
            if to[0] == LOCAL and to[1] in self.socks:       # this computer: delivered
                self._deliver(self.socks[to[1]], data, (LOCAL, sock.port))
            return                                           # the router drops it
        self.state.add((sock.port, to))
        server = {STUN_AT: "stun", TURN_AT: "turn"}.get(to[0])
        if server:
            self._serve(server, sock, data, to)
        elif to[0] == self.public:
            self._hairpin(sock, data, to)

    def _deliver(self, sock, data, source):
        sock.inbox.append((data, source))
        if self.duplicate:
            sock.inbox.append((data, source))

    def _serve(self, server, sock, data, to):
        request = stun.decode(data)
        self.received.append((server, to[1], request))
        if (server, to[1]) in self.silent or request is None:
            return
        if request.method == stun.BINDING:
            port = self._public_port(sock, to)
            value = bytes((0, stun.IPV4)) + (port ^ 0x2112).to_bytes(2, "big") + \
                (int.from_bytes(socket.inet_aton(self.public), "big") ^ stun.MAGIC).to_bytes(4, "big")
            answer = stun.encode(stun.BINDING, stun.SUCCESS, request.transaction,
                                 ((0x0020, value),))
        elif request.method == stun.ALLOCATE and server == "turn":
            answer = self._allocate_answer(request, self.udp_turn)
        else:
            return
        self._deliver(sock, answer, to)

    def _hairpin(self, sock, data, to):
        if self.hairpin == "none":
            return
        target = next((self.socks[local] for (local, _key), public in self.ports.items()
                       if public == to[1]), None)
        if target is None:
            return
        mine = self._public_port(sock, to)
        pair = frozenset((sock.port, target.port))
        if pair in self.dead:
            return
        if (target.port, (self.public, mine)) not in self.state:
            # unasked: the owner's router drops it, and after a few closes the pair
            count = self.unasked.get(pair, 0) + 1
            self.unasked[pair] = count
            if self.lead_kills and count >= 3:
                self.dead.add(pair)
            return
        source = (self.public, mine) if self.hairpin == "public" else (LOCAL, sock.port)
        self._deliver(target, data, source)

    def sends(self, prefix=b""):
        return [entry for entry in self.log if entry[3].startswith(prefix)]


def run_all(net, stun_text="stun.test", turn_text="turn.test"):
    run = nat.Run(nat.parse_server(stun_text, "stun"), nat.parse_server(turn_text, "turn"), net)
    while not run.done():
        run.step()
    return run


def by_test(run):
    return {(row.test, row.args[:2] if row.test == "turn" else ()): row for row in run.rows}


def test_what_was_typed_becomes_a_server():
    s = nat.parse_server("  stun.cloudflare.com:3478 ", "stun")
    assert (s.host, s.port, s.address, s.typed_port) == ("stun.cloudflare.com", 3478, "", True)
    assert nat.parse_server("turn.cloudflare.com", "turn").port == nat.STUN_PORT
    assert nat.parse_server("turn.cloudflare.com", "turn").typed_port is False
    assert nat.parse_server("192.0.2.1:19302", "stun")[1:4] == ("192.0.2.1", 19302, "192.0.2.1")
    assert nat.parse_server("[2001:db8::1]:3478", "stun").address == "2001:db8::1"
    assert nat.parse_server("[2001:db8::1]", "stun").port == nat.STUN_PORT
    assert nat.parse_server("2001:db8::1", "stun").address == "2001:db8::1", "bare IPv6"
    assert nat.turn_transports(nat.parse_server("turn.test", "turn")) == nat.TURN_TRANSPORTS
    assert nat.turn_transports(nat.parse_server("turn.test:5000", "turn")) == (
        ("UDP", 5000), ("TCP", 5000))


@pytest.mark.parametrize("text, which, key", [
    ("", "stun", "tools.nat.refused.empty_stun"),
    ("   ", "turn", "tools.nat.refused.empty_turn"),
    ("stun.test:0", "stun", "tools.nat.refused.port"),
    ("stun.test:65536", "stun", "tools.nat.refused.port"),
    ("stun.test:34x", "stun", "tools.nat.refused.port"),
    ("stun.test:٣", "stun", "tools.nat.refused.port"),
    ("stun.test:", "stun", "tools.nat.refused.port"),
    ("[2001:db8::1]:", "stun", "tools.nat.refused.port"),
    (":3478", "stun", "tools.nat.refused.bad_server"),
    ("[2001:db8::1", "stun", "tools.nat.refused.bad_server"),
    ("[2001:db8::1]x", "stun", "tools.nat.refused.bad_server"),
    ("[stun.test]:3478", "stun", "tools.nat.refused.bad_server"),
    ("not a name", "stun", "tools.nat.refused.bad_server"),
    ("0.0.0.0", "stun", "tools.nat.refused.bad_server"),
])
def test_what_is_not_one_server_is_refused_before_anything_is_sent(text, which, key):
    with pytest.raises(Refused) as refused:
        nat.parse_server(text, which)
    assert refused.value.user_key == key


def test_the_mapping_verdict_from_three_answers():
    a, b, c = ("203.0.113.7", 1), ("203.0.113.7", 2), ("203.0.113.7", 3)
    assert nat.mapping_verdict(a, a, a) == nat.INDEPENDENT
    assert nat.mapping_verdict(a, a, None) == nat.INDEPENDENT, "a silent second port"
    assert nat.mapping_verdict(a, b, b) == nat.BY_ADDRESS
    assert nat.mapping_verdict(a, b, None) == nat.BY_ADDRESS
    assert nat.mapping_verdict(a, b, c) == nat.BY_ADDRESS_AND_PORT
    assert nat.mapping_verdict(a, a, b) == nat.BY_ADDRESS_AND_PORT
    assert nat.mapping_verdict(a, ("198.51.100.9", 1), None) == nat.BY_ADDRESS


def test_the_owners_router_two_devices_meet_only_when_they_start_together():
    """The case the tool was made for (measured 2026-11-04 and 2026-11-09)."""
    net = FakeNat()
    run = run_all(net)
    rows = by_test(run)
    assert rows[("public", ())].state == nat.OK
    assert rows[("public", ())].detail == "tools.nat.detail.port_changed"
    assert dict(rows[("public", ())].args)["address"] == PUBLIC
    assert rows[("mapping", ())].result == "tools.nat.result.independent"
    assert rows[("mapping", ())].detail == "tools.nat.detail.independent"
    together, first = rows[("hairpin_together", ())], rows[("hairpin_first", ())]
    assert (together.state, together.detail) == (nat.OK, "tools.nat.detail.hairpin_ok")
    assert dict(together.args)["n"] >= 8, together.args
    assert (first.state, first.detail) == (nat.WARN, "tools.nat.detail.hairpin_after_first")
    for transport, port in nat.TURN_TRANSPORTS:
        row = rows[("turn", (("transport", transport), ("port", port)))]
        assert (row.state, row.detail) == (nat.OK, "tools.nat.detail.turn_answers"), row
    assert nat.conclusion(run.rows) == ("tools.nat.conclusion.together_only",)
    # the server's own words are never part of a row
    assert not any("words of the server" in str(row) for row in run.rows)


def test_a_router_that_keeps_the_pair_lets_one_side_go_first():
    run = run_all(FakeNat(lead_kills=False))
    assert by_test(run)[("hairpin_first", ())].state == nat.OK
    assert nat.conclusion(run.rows) == ("tools.nat.conclusion.hairpin",)


def test_the_firewall_is_told_before_anything_can_come_unasked():
    """Windows Firewall prompts for a datagram that reaches a socket unasked (event
    5031, measured 2026-11-09): each socket of a pair sends a TTL-1 datagram to the
    other's public address before the other sends it anything."""
    net = FakeNat()
    run = run_all(net)
    checked = 0
    for at, (port, to, _ttl, data) in enumerate(net.log):
        if to[0] != PUBLIC or not data.startswith((run.token + b":P", run.token + b":L")):
            continue
        receiver = next(local for (local, _key), public in net.ports.items() if public == to[1])
        sender_public = (PUBLIC, net.ports[(port, None)])
        told = [entry for entry in net.log[:at] if entry[0] == receiver and entry[2] == 1
                and entry[1] == sender_public and entry[3] == run.token + b":o"]
        assert told, (data, "the receiving socket told its firewall about the sender first")
        checked += 1
    assert checked >= 3 * nat.ROUNDS, "both hairpin jobs, both directions and the lead"


def test_the_pair_sends_only_to_the_public_address_the_first_answer_gave():
    """The hairpin datagrams go where a server says this network is: a server that
    names another address for the pair gets nothing sent there."""
    class Moving(FakeNat):
        def _serve(self, server, sock, data, to):
            if len(self.received) >= 3:          # after the addresses job's three questions
                self.public = "198.51.100.66"
            super()._serve(server, sock, data, to)
    net = Moving()
    run = run_all(net)
    assert by_test(run)[("hairpin_together", ())].detail == "tools.nat.detail.other_address"
    assert not [entry for entry in net.log if entry[1][0] == "198.51.100.66"]


def test_an_answer_with_no_usable_address_is_said_as_that():
    """An IPv6 address answered to an IPv4 socket is no address to send to."""
    class Six(FakeNat):
        def _serve(self, server, sock, data, to):
            request = stun.decode(data)
            v6 = (bytes((0, stun.IPV6)) + (1234).to_bytes(2, "big")
                  + bytes((0x20, 1, 0xd, 0xb8)) + bytes(12))        # 2001:db8::
            sock.inbox.append((stun.encode(stun.BINDING, stun.SUCCESS, request.transaction,
                                           ((stun.MAPPED_ADDRESS, v6),)), to))
    run = run_all(Six())
    row = by_test(run)[("public", ())]
    assert (row.state, row.result, row.detail) == (
        nat.FAIL, "tools.nat.result.no_address", "tools.nat.detail.no_address")
    assert nat.conclusion(run.rows) == (), "an answer came: it is no sign of blocked UDP"


def test_a_mapping_that_depends_on_the_destination_sends_no_hairpin_at_all():
    for mapping, result in ((nat.BY_ADDRESS, "tools.nat.result.by_address"),
                            (nat.BY_ADDRESS_AND_PORT, "tools.nat.result.by_address_port")):
        net = FakeNat(mapping=mapping)
        run = run_all(net)
        rows = by_test(run)
        assert (rows[("mapping", ())].state, rows[("mapping", ())].result) == (nat.WARN, result)
        for test in ("hairpin_together", "hairpin_first"):
            assert rows[(test, ())].detail == "tools.nat.detail.dependent_hairpin"
        assert not [entry for entry in net.log if entry[1][0] == PUBLIC], \
            "nothing goes to the public address: where it would come from is unknown"
        assert nat.conclusion(run.rows) == ("tools.nat.conclusion.dependent",)


def test_no_nat_says_so_and_skips_the_rest_of_the_stun_steps():
    net = FakeNat(no_nat=True)
    net.route_source = lambda family, address: LOCAL
    run = run_all(net)
    rows = by_test(run)
    assert rows[("public", ())].detail == nat.DETAIL_NO_NAT
    assert rows[("mapping", ())].detail == "tools.nat.detail.no_nat_mapping"
    assert rows[("hairpin_together", ())].detail == "tools.nat.detail.no_nat_hairpin"
    assert nat.conclusion(run.rows) == ("tools.nat.conclusion.no_nat",)


def test_a_hairpin_from_the_local_address_and_one_that_never_comes_back():
    lan = by_test(run_all(FakeNat(hairpin="lan")))
    assert lan[("hairpin_together", ())].detail == "tools.nat.detail.hairpin_lan"
    run = run_all(FakeNat(hairpin="none"))
    rows = by_test(run)
    assert rows[("hairpin_together", ())].detail == "tools.nat.detail.hairpin_none"
    assert rows[("hairpin_first", ())].detail == "tools.nat.detail.together_failed"
    assert nat.conclusion(run.rows) == ("tools.nat.conclusion.no_hairpin",)


def test_a_duplicated_datagram_counts_once():
    run = run_all(FakeNat(duplicate=True))
    together = dict(by_test(run)[("hairpin_together", ())].args)
    assert together["a"] <= nat.ROUNDS and together["b"] <= nat.ROUNDS, together


def test_the_port_kept_and_a_silent_second_port():
    run = run_all(FakeNat(keep_port=True, silent={("turn", 443)}))
    rows = by_test(run)
    assert rows[("public", ())].detail == "tools.nat.detail.port_kept"
    assert rows[("mapping", ())].detail == "tools.nat.detail.independent_address", \
        "a silent second port is not a port-dependent mapping"
    assert rows[("mapping", ())].state == nat.OK


def test_a_silent_stun_server_still_lets_the_turn_server_be_asked():
    net = FakeNat(silent={("stun", 3478)})
    run = run_all(net)
    rows = by_test(run)
    assert (rows[("public", ())].state, rows[("public", ())].detail) == (
        nat.FAIL, nat.DETAIL_NO_STUN)
    assert rows[("mapping", ())].detail == "tools.nat.detail.needs_public"
    assert rows[("hairpin_together", ())].detail == "tools.nat.detail.needs_public"
    assert rows[("turn", (("transport", "UDP"), ("port", 3478)))].state == nat.OK
    assert nat.conclusion(run.rows) == ("tools.nat.conclusion.no_stun",)
    tries = [entry for entry in net.received if entry[0] == "stun"]
    assert len(tries) == len(nat.TRIES_S), "three tries, then on"


def test_one_address_in_both_boxes_is_not_called_independent():
    run = run_all(FakeNat(), "stun.test", "stun.test")
    rows = by_test(run)
    assert rows[("mapping", ())].detail == "tools.nat.detail.same_server"
    assert nat.conclusion(run.rows) == ("tools.nat.conclusion.unknown",)


def test_names_that_are_not_found():
    run = run_all(FakeNat(), "nowhere.test", "elsewhere.test")
    rows = by_test(run)
    assert rows[("public", ())].result == "tools.nat.result.not_found"
    assert dict(rows[("public", ())].args)["name"] == "nowhere.test"
    assert all(row.result == "tools.nat.result.not_found"
               for (test, _a), row in rows.items() if test == "turn")
    assert "tools.nat.conclusion.no_stun" not in nat.conclusion(run.rows), \
        "a name that was not found is not a blocked UDP"


def test_each_turn_answer_says_what_it_is():
    net = FakeNat(udp_turn="420", tcp={3478: "success", 80: "refused", 443: "not_stun"})
    run = run_all(net)
    rows = by_test(run)

    def turn(transport, port):
        return rows[("turn", (("transport", transport), ("port", port)))]
    assert (turn("UDP", 3478).state, turn("UDP", 3478).detail) == (
        nat.FAIL, "tools.nat.detail.stun_not_turn"), "420: STUN, not TURN"
    assert turn("TCP", 3478).detail == "tools.nat.detail.turn_open"
    assert turn("TCP", 80).detail == "tools.nat.detail.refused"
    tls = run_all(FakeNat(tcp={443: "not_stun"}), turn_text="turn.test:443")
    assert by_test(tls)[("turn", (("transport", "TCP"), ("port", 443)))].detail == \
        "tools.nat.detail.not_turn_tls"
    garbage = run_all(FakeNat(tcp={3478: "garbage", 80: "438"}))
    rows = by_test(garbage)
    assert rows[("turn", (("transport", "TCP"), ("port", 3478)))].detail == "tools.nat.detail.not_turn"
    row = rows[("turn", (("transport", "TCP"), ("port", 80)))]
    assert (row.state, row.detail, dict(row.args)["code"]) == (
        nat.OK, "tools.nat.detail.turn_code", 438)


def test_a_relay_handed_out_without_a_login_is_given_back():
    net = FakeNat(udp_turn="success")
    run = run_all(net)
    assert by_test(run)[("turn", (("transport", "UDP"), ("port", 3478)))].detail == \
        "tools.nat.detail.turn_open"
    released = [request for server, _port, request in net.received
                if server == "turn" and request and request.method == stun.REFRESH]
    assert len(released) == 2, "one Refresh with lifetime 0 for each UDP allocation"
    assert all(dict(r.attributes)[stun.LIFETIME] == bytes(4) for r in released)


def test_nothing_more_is_sent_after_stop_and_the_rest_says_so():
    net = FakeNat()
    run = nat.Run(nat.parse_server("stun.test", "stun"), nat.parse_server("turn.test", "turn"),
                  net)
    stop_after = []

    def stopper(fake):
        if len(fake.sends(run.token + b":P")) == 4 and not stop_after:
            stop_after.append(len(fake.log))
            run.stop()                               # pressed while the round runs
    net.on_send = stopper
    while not run.done():
        run.step()
    assert run.step() == ()
    late = [entry for entry in net.log[stop_after[0]:] if entry[3].startswith(run.token + b":P")]
    assert len(late) <= 1, "at most the other half of the round that was going"
    assert len(net.log) <= stop_after[0] + 1
    rows = run.rows + list(run.not_checked())
    tests = [(row.test, row.args[:2] if row.test == "turn" else ()) for row in rows]
    assert len(tests) == len(set(tests)) == 4 + len(nat.TURN_TRANSPORTS), tests
    stopped = [row for row in run.not_checked() if row.detail == "tools.nat.detail.stopped"]
    assert {row.test for row in stopped} >= {"hairpin_together", "hairpin_first", "turn"}


def test_a_socket_the_system_refuses_is_a_row_and_the_run_goes_on():
    run = run_all(FakeNat(refuse_udp=True))
    rows = by_test(run)
    assert (rows[("public", ())].state, rows[("public", ())].detail) == (
        nat.FAIL, "tools.nat.detail.send_failed")
    assert rows[("mapping", ())].detail == "tools.nat.detail.needs_public"
    assert rows[("turn", (("transport", "TCP"), ("port", 3478)))].state == nat.OK
    assert len(run.rows) == 4 + len(nat.TURN_TRANSPORTS)


def test_answers_from_another_address_or_to_another_question_are_not_taken():
    run = nat.Run(nat.parse_server("stun.test", "stun"), nat.parse_server("turn.test", "turn"),
                  FakeNat())

    class Silent(FakeNat):
        def _serve(self, server, sock, data, to):
            request = stun.decode(data)
            value = bytes((0, stun.IPV4)) + (1234 ^ 0x2112).to_bytes(2, "big") + bytes(4)
            # from the right server but to another question, and from a stranger
            sock.inbox.append((stun.encode(stun.BINDING, stun.SUCCESS, bytes(12),
                                           ((0x0020, value),)), to))
            sock.inbox.append((stun.encode(stun.BINDING, stun.SUCCESS, request.transaction,
                                           ((0x0020, value),)), ("198.51.100.1", to[1])))
    quiet = Silent()
    sock = quiet.udp(socket.AF_INET)
    assert run._mapped(sock, nat.Server("x", STUN_AT, 3478, STUN_AT), 3478,
                       lambda: True) == (None, False)


def test_the_conclusion_from_the_rows():
    def step(test, state, detail="d"):
        return nat.Step(test, state, "r", detail)
    ok_public = step("public", nat.OK)
    independent = step("mapping", nat.OK)
    assert nat.conclusion([]) == ()
    assert nat.conclusion([step("public", nat.FAIL, nat.DETAIL_NO_STUN)]) == (
        "tools.nat.conclusion.no_stun",)
    assert nat.conclusion([step("public", nat.FAIL, "tools.nat.detail.not_found")]) == ()
    assert nat.conclusion([step("public", nat.OK, nat.DETAIL_NO_NAT)]) == (
        "tools.nat.conclusion.no_nat",)
    assert nat.conclusion([ok_public]) == ("tools.nat.conclusion.unknown",)
    assert nat.conclusion([ok_public, step("mapping", nat.WARN)]) == (
        "tools.nat.conclusion.dependent",)
    assert nat.conclusion([ok_public, independent]) == ("tools.nat.conclusion.independent",)
    assert nat.conclusion([ok_public, independent, step("hairpin_together", nat.FAIL)]) == (
        "tools.nat.conclusion.independent",), "no STUN answer for the pair is not a no"
    assert nat.conclusion([ok_public, independent, step("hairpin_together", nat.WARN)]) == (
        "tools.nat.conclusion.no_hairpin",)
    together = step("hairpin_together", nat.OK)
    assert nat.conclusion([ok_public, independent, together]) == (
        "tools.nat.conclusion.together",)
    assert nat.conclusion([ok_public, independent, together,
                           step("hairpin_first", nat.SKIPPED)]) == ("tools.nat.conclusion.together",)
    turn_fail = nat.Step("turn", nat.FAIL, "r", "d", (("transport", "UDP"), ("port", 1)))
    turn_ok = nat.Step("turn", nat.OK, "r", "d", (("transport", "TCP"), ("port", 1)))
    assert nat.conclusion([ok_public, turn_fail])[-1] == "tools.nat.conclusion.no_turn"
    assert "tools.nat.conclusion.no_turn" not in nat.conclusion([ok_public, turn_fail, turn_ok])


def test_the_report_is_english_and_carries_every_row():
    run = run_all(FakeNat())
    text = nat.report(run, run.rows)
    assert text.startswith("NAT and STUN, started ")
    assert "STUN server: stun.test (192.0.2.1)" in text
    assert "Public address: 203.0.113.7 - This computer is 10.0.0.20." in text
    assert "TURN, TCP 80: Answers - " in text
    assert "Conclusion: Devices behind this router reach each other" in text
    assert len(text.splitlines()) == 3 + len(run.rows) + 1


# -- the real sockets, on loopback ------------------------------------------------ #
class LoopServer:
    """A STUN and TURN server on 127.0.0.1 (UDP and TCP, one port): Binding answers
    with the address it saw, Allocate with 401."""

    def __init__(self):
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.port = self.udp.getsockname()[1]
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp.bind(("127.0.0.1", self.port))
        self.tcp.listen(4)
        self.stop = False
        self.threads = [threading.Thread(target=self._udp, daemon=True),
                        threading.Thread(target=self._tcp, daemon=True)]
        for thread in self.threads:
            thread.start()

    @staticmethod
    def answer(data, source):
        request = stun.decode(data)
        if request is None:
            return None
        if request.method == stun.BINDING:
            value = bytes((0, stun.IPV4)) + (source[1] ^ 0x2112).to_bytes(2, "big") + \
                (int.from_bytes(socket.inet_aton(source[0]), "big") ^ stun.MAGIC).to_bytes(4, "big")
            return stun.encode(stun.BINDING, stun.SUCCESS, request.transaction,
                               ((0x0020, value),), fingerprint=True)
        return stun.encode(stun.ALLOCATE, stun.ERROR, request.transaction,
                           ((stun.ERROR_CODE, bytes((0, 0, 4, 1))),))

    def _udp(self):
        self.udp.settimeout(0.1)
        while not self.stop:
            try:
                data, source = self.udp.recvfrom(4096)
            except OSError:
                continue
            reply = self.answer(data, source)
            if reply:
                self.udp.sendto(reply, source)

    def _tcp(self):
        self.tcp.settimeout(0.1)
        while not self.stop:
            try:
                conn, source = self.tcp.accept()
            except OSError:
                continue
            with conn:
                conn.settimeout(2)
                data = conn.recv(4096)
                reply = self.answer(data, source)
                if reply:
                    conn.sendall(reply)

    def close(self):
        self.stop = True
        for thread in self.threads:
            thread.join(2)
        self.udp.close()
        self.tcp.close()


def test_the_real_sockets_against_a_server_on_loopback():
    """The system's sockets, resolver and route as the program uses them: on loopback
    the mapped address IS this computer's, so the run says "no NAT" - and the TURN
    server answers 401 on UDP and on TCP."""
    server = LoopServer()
    try:
        address = f"127.0.0.1:{server.port}"
        run = nat.Run(nat.parse_server(address, "stun"), nat.parse_server(address, "turn"))
        while not run.done():
            run.step()
    finally:
        server.close()
    rows = by_test(run)
    assert rows[("public", ())].detail == nat.DETAIL_NO_NAT, rows[("public", ())]
    for transport in ("UDP", "TCP"):
        row = rows[("turn", (("transport", transport), ("port", server.port)))]
        assert (row.state, row.detail) == (nat.OK, "tools.nat.detail.turn_answers"), row


def test_the_receive_loop_takes_an_icmp_error_and_waits_on():
    """Windows reports "port unreachable" for an earlier datagram on the NEXT receive
    (10054); the receive loop takes it and waits out its time, raising nothing."""
    closed = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()
    if sys.platform == "win32":
        # the calibration: a plain receive after that send does raise here, so the
        # loop below is shown the error and not merely silence
        raw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        raw.bind(("127.0.0.1", 0))
        raw.settimeout(1.0)
        try:
            raw.sendto(b"x", ("127.0.0.1", port))
            with pytest.raises(ConnectionResetError):
                raw.recvfrom(64)
        finally:
            raw.close()
    sock = nat._Udp(socket.AF_INET)
    try:
        sock.send(b"x", ("127.0.0.1", port))
        assert sock.receive(0.2) is None
        sock.send(b"x", ("127.0.0.1", sock.port), ttl=1)     # to itself: delivered here
        got = sock.receive(1.0)
        assert got is not None and got[0] == b"x" and got[1] == ("127.0.0.1", sock.port)
        assert sock.sock.getsockopt(socket.IPPROTO_IP, socket.IP_TTL) != 1, "TTL put back"
    finally:
        sock.close()
