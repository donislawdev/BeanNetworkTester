"""``beantester/ice.py``: which UDP flows carry ICE, and the path the data takes.

Every packet here is built byte by byte. The STUN decoding is pinned to the test
vectors of RFC 5769 (sections 2.1-2.3), and the helpers that build the other messages
are checked against those vectors first, so a helper that drifted from the RFC fails
on its own instead of agreeing with a decoder that drifted the same way.
"""
import ipaddress
import random
import struct

from beantester import BeanEngine, crashlog, ice
from beantester.connlog import ConnectionLog
from beantester.ice import IceWatch
from beantester.settings import DEFAULT_SETTINGS, apply_settings
from fakes import FakeDivert, check, wait_until

# RFC 5769, 2.1: a Binding request with PRIORITY, ICE-CONTROLLED, USERNAME,
# MESSAGE-INTEGRITY and FINGERPRINT.
RFC_REQUEST = bytes.fromhex(
    "000100582112a442b7e7a701bc34d686fa87dfae"
    "802200105354554e20746573742063" "6c69656e74"
    "002400046e0001ff80290008932ff9b151263b36"
    "000600096576746a3a6836765920202000080014"
    "9aeaa70cbfd8cb56781ef2b5b2d3f249c1b571a2"
    "80280004e57a3bcf")
# RFC 5769, 2.2: the answer naming 192.0.2.1 port 32853.
RFC_RESPONSE_V4 = bytes.fromhex(
    "0101003c2112a442b7e7a701bc34d686fa87dfae"
    "8022000b7465737420766563746f7220"
    "002000080001a147e112a643"
    "000800142b91f599fd9e90c38c7489f92af9ba53f06be7d7"
    "80280004c07d4c96")
# RFC 5769, 2.3: the answer naming 2001:db8:1234:5678:11:2233:4455:6677 port 32853.
RFC_RESPONSE_V6 = bytes.fromhex(
    "010100482112a442b7e7a701bc34d686fa87dfae"
    "8022000b7465737420766563746f7220"
    "002000140002a1470113a9faa5d3f179bc25f4b5bed2b9d9"
    "00080014a382954e4be67bf11784c97c8292c275bfe3ed41"
    "80280004c8fb0b4c")
TXID = bytes.fromhex("b7e7a701bc34d686fa87dfae")
COOKIE = bytes.fromhex("2112a442")

# Message types as RFC 8489 section 5 and RFC 8656 write them: the class in bits 4
# and 8, the method in the rest.
BINDING_REQUEST, BINDING_INDICATION = 0x0001, 0x0011
BINDING_SUCCESS, BINDING_ERROR = 0x0101, 0x0111
ALLOCATE_REQUEST, ALLOCATE_SUCCESS = 0x0003, 0x0103
REFRESH_REQUEST, CREATE_PERMISSION, CHANNEL_BIND = 0x0004, 0x0008, 0x0009
SEND_INDICATION, DATA_INDICATION = 0x0016, 0x0017

# The far ends that have to be public are public resolvers: the documentation ranges
# (RFC 5737, RFC 3849) are not globally reachable, so the code rightly calls them
# this network, and these addresses are nobody's home connection.
HOME = "10.0.0.10"              # this machine
PUBLIC = "9.9.9.9"              # standing in for this network's public address
PEER_LAN = "10.0.0.20"
PEER_WAN = "8.8.8.8"
STUN_SERVER = "1.0.0.1"         # public resolvers standing in for STUN and TURN servers
TURN_SERVER = "1.1.1.1"
V6_HOME, V6_PEER = "2606:4700:4700::10", "2606:4700:4700::20"     # one /64
V6_ELSEWHERE = "2001:4860:4860::8888"

DTLS = bytes([22, 254, 253]) + bytes(40)        # a DTLS record (content type 22)
RTP = bytes([0x80, 0x6f]) + bytes(60)           # RTP version 2


def attribute(kind, value):
    return struct.pack(">HH", kind, len(value)) + value + bytes(-len(value) % 4)


def message(msg_type, *attributes, txid=TXID):
    body = b"".join(attributes)
    return struct.pack(">HH", msg_type, len(body)) + COOKIE + txid + body


def xor_mapped(ip, port=32853, txid=TXID):
    address = ipaddress.ip_address(ip)
    head = struct.pack(">BBH", 0, 1 if address.version == 4 else 2, port ^ 0x2112)
    if address.version == 4:
        return attribute(0x0020, head + (int(address) ^ 0x2112A442).to_bytes(4, "big"))
    mask = int.from_bytes(COOKIE + txid, "big")
    return attribute(0x0020, head + (int(address) ^ mask).to_bytes(16, "big"))


PRIORITY = attribute(0x0024, bytes.fromhex("6e0001ff"))


def channel_data(inner, channel=0x4000):
    return struct.pack(">HH", channel, len(inner)) + inner


def udp4(src, dst, payload, sport=50000, dport=3478, proto=17, ihl=5, frag=0,
         udp_length=None):
    udp = struct.pack(">HHHH", sport, dport,
                      8 + len(payload) if udp_length is None else udp_length, 0)
    options = bytes(4 * (ihl - 5))
    total = 4 * ihl + len(udp) + len(payload)
    head = struct.pack(">BBHHHBBH4s4s", 0x40 | ihl, 0, total, 1, frag, 64, proto, 0,
                       ipaddress.IPv4Address(src).packed, ipaddress.IPv4Address(dst).packed)
    return head + options + udp + payload


def udp6(src, dst, payload, sport=50000, dport=3478, next_header=17):
    udp = struct.pack(">HHHH", sport, dport, 8 + len(payload), 0) + payload
    head = struct.pack(">IHBB16s16s", 0x60000000, len(udp), next_header, 64,
                       ipaddress.IPv6Address(src).packed, ipaddress.IPv6Address(dst).packed)
    return head + udp


class Flow:
    """One flow fed the way ``ConnectionLog.log`` feeds it: the packet is counted on
    the row first, and ``observe`` runs only while the row's budget is above zero."""

    def __init__(self, watch, remote, port=3478, local=HOME, v6=False):
        self.watch, self.remote, self.port, self.local, self.v6 = watch, remote, port, local, v6
        self.key = (50000, remote, port)
        self.row = dict(remote_ip=remote, remote_port=port, packets=0, bytes=0, sent=0,
                        ice="", ice_n=ice.PROBE_FIRST)
        self.reads = 0

    def out(self, payload):
        return self._feed(payload, True)

    def back(self, payload):
        return self._feed(payload, False)

    def _feed(self, payload, is_out):
        src, dst = (self.local, self.remote) if is_out else (self.remote, self.local)
        build = udp6 if self.v6 else udp4
        raw = build(src, dst, payload, *((50000, self.port) if is_out else (self.port, 50000)))
        self.row["packets"] += 1
        if self.row["ice_n"] > 0:
            self.reads += 1
            self.watch.observe(self.row, self.key, raw, is_out)
        return self

    @property
    def label(self):
        return self.row["ice"]

    @property
    def done(self):
        return self.row["ice_n"] == 0


# -- the helpers against the RFC, before anything trusts them --------------- #
def test_the_helpers_build_what_rfc_5769_shows():
    check("XOR-MAPPED-ADDRESS for 192.0.2.1:32853",
          xor_mapped("192.0.2.1") == bytes.fromhex("002000080001a147e112a643"))
    check("XOR-MAPPED-ADDRESS for the IPv6 sample",
          xor_mapped("2001:db8:1234:5678:11:2233:4455:6677") == bytes.fromhex(
              "002000140002a1470113a9faa5d3f179bc25f4b5bed2b9d9"))
    check("the PRIORITY attribute of the sample request", PRIORITY in RFC_REQUEST)
    check("the request's header", message(BINDING_REQUEST)[:4] == bytes.fromhex("00010000"))


# -- STUN decoding ------------------------------------------------------------ #
def test_the_rfc_5769_request_is_a_connectivity_check():
    got = ice.stun(memoryview(RFC_REQUEST))
    check("Binding request with PRIORITY", got == (ice.BINDING, ice.REQUEST, True, None, -1),
          f"({got})")


def test_the_rfc_5769_answers_name_the_mapped_address():
    v4 = ice.stun(memoryview(RFC_RESPONSE_V4))
    v6 = ice.stun(memoryview(RFC_RESPONSE_V6))
    check("IPv4", v4 == (ice.BINDING, ice.SUCCESS, False, "192.0.2.1", -1), f"({v4})")
    check("IPv6, XORed with the transaction ID too",
          v6 == (ice.BINDING, ice.SUCCESS, False, "2001:db8:1234:5678:11:2233:4455:6677", -1),
          f"({v6})")


def test_every_class_and_turn_method_as_the_rfcs_number_them():
    cases = {BINDING_REQUEST: (1, ice.REQUEST), BINDING_INDICATION: (1, ice.INDICATION),
             BINDING_SUCCESS: (1, ice.SUCCESS), BINDING_ERROR: (1, ice.ERROR),
             ALLOCATE_REQUEST: (3, ice.REQUEST), ALLOCATE_SUCCESS: (3, ice.SUCCESS),
             REFRESH_REQUEST: (4, ice.REQUEST), SEND_INDICATION: (6, ice.INDICATION),
             DATA_INDICATION: (7, ice.INDICATION), CREATE_PERMISSION: (8, ice.REQUEST),
             CHANNEL_BIND: (9, ice.REQUEST)}
    for msg_type, (method, kind) in cases.items():
        got = ice.stun(memoryview(message(msg_type)))
        check(f"0x{msg_type:04x}", got is not None and got[:2] == (method, kind), f"({got})")
    check("every TURN method is one",
          {m for m, _ in cases.values()} - {1} == set(ice.TURN_METHODS))


def test_a_relayed_datagram_is_read_from_the_data_attribute():
    got = ice.stun(memoryview(message(SEND_INDICATION, attribute(0x0013, DTLS))))
    check("its first byte", got is not None and got[4] == 22, f"({got})")
    empty = ice.stun(memoryview(message(DATA_INDICATION, attribute(0x0013, b""))))
    check("an empty DATA carries nothing", empty is not None and empty[4] == -1, f"({empty})")


def test_what_is_not_stun_is_none():
    good = bytearray(RFC_RESPONSE_V4)
    cases = {
        "wrong cookie": bytes(good[:4]) + b"\x21\x12\xa4\x43" + bytes(good[8:]),
        "first two bits set": bytes([good[0] | 0x40]) + bytes(good[1:]),
        "one byte too many": bytes(good) + b"\x00",
        "four bytes past the length it says": bytes(good) + bytes(4),
        "length says 4 more": bytes(good[:2]) + struct.pack(">H", 0x40) + bytes(good[4:]),
        "length not a multiple of 4": message(BINDING_REQUEST) + b"\x00\x00",
        "a header cut short": bytes(good[:19]),
        "an attribute running past the end": message(
            BINDING_REQUEST, struct.pack(">HH", 0x0024, 8) + bytes(4)),
    }
    for name, data in cases.items():
        check(name, ice.stun(memoryview(data)) is None)


def test_no_prefix_of_a_real_message_is_stun_and_none_raises():
    for size in range(len(RFC_REQUEST)):
        check(f"{size} bytes", ice.stun(memoryview(RFC_REQUEST[:size])) is None)


def test_random_bytes_never_pass_for_stun_and_never_raise():
    rng = random.Random(5769)
    for _ in range(20000):
        size = rng.choice((20, 24, 48, 96, 140))
        data = bytes([rng.randrange(4)]) + rng.randbytes(size - 1)
        check("random", ice.stun(memoryview(data)) is None)


def test_a_message_with_random_attributes_never_raises():
    rng = random.Random(8489)
    for _ in range(5000):
        body = rng.randbytes(4 * rng.randrange(1, 24))
        for msg_type in (BINDING_SUCCESS, ALLOCATE_SUCCESS, SEND_INDICATION):
            ice.stun(memoryview(struct.pack(">HH", msg_type, len(body)) + COOKIE + TXID + body))


# -- the UDP payload of an IP packet ---------------------------------------- #
def udp_payload(raw):
    """The payload ``ice._start`` and ``ice._end`` find, or ``None`` for none."""
    start = ice._start(raw)
    return None if start < 0 else bytes(raw[start:ice._end(raw, start)])


def test_the_udp_payload_of_ipv4_and_ipv6():
    check("IPv4", udp_payload(udp4(HOME, PEER_LAN, b"abcd")) == b"abcd")
    check("IPv4 with options", udp_payload(udp4(HOME, PEER_LAN, b"abcd", ihl=7)) == b"abcd")
    check("IPv6", udp_payload(udp6("2001:db8::1", "2001:db8::2", b"abcd")) == b"abcd")
    check("empty: nothing to read", udp_payload(udp4(HOME, PEER_LAN, b"")) is None)
    check("the UDP length decides, not trailing bytes",
          udp_payload(udp4(HOME, PEER_LAN, b"abcd") + b"pad") == b"abcd")


def test_what_is_not_plainly_udp_has_no_payload():
    cases = {
        "TCP": udp4(HOME, PEER_LAN, b"abcd", proto=6),
        "a later fragment": udp4(HOME, PEER_LAN, b"abcd", frag=0x0010),
        "a first fragment, the datagram longer than the packet":
            udp4(HOME, PEER_LAN, b"abcd", frag=0x2000, udp_length=1400),
        "a UDP length under its own header": udp4(HOME, PEER_LAN, b"abcd", udp_length=4),
        "IPv6 with a hop-by-hop header": udp6("2001:db8::1", "2001:db8::2", b"abcd", next_header=0),
        "a synthetic packet (all zeros)": bytes(200),
        "an IPv4 header length under 20": bytes([0x44]) + udp4(HOME, PEER_LAN, b"abcd")[1:],
    }
    for name, raw in cases.items():
        check(name, udp_payload(raw) is None)


def test_no_cut_of_a_packet_raises():
    watch = IceWatch()
    for raw in (udp4(HOME, PEER_LAN, RFC_REQUEST), udp6("2001:db8::1", "2001:db8::2", RFC_REQUEST)):
        for size in range(len(raw)):
            udp_payload(raw[:size])
            row = dict(remote_ip=PEER_LAN, remote_port=1, packets=1, bytes=0, sent=0, ice="",
                       ice_n=ice.PROBE_FIRST)
            watch.observe(row, (1, PEER_LAN, 1), raw[:size], True)


# -- labels ------------------------------------------------------------------ #
def test_an_address_query_to_a_stun_server_is_stun():
    watch = IceWatch()
    flow = Flow(watch, STUN_SERVER).out(message(BINDING_REQUEST)).back(
        message(BINDING_SUCCESS, xor_mapped(PUBLIC)))
    check("STUN", flow.label == ice.STUN, f"({flow.label!r})")


def test_checks_on_this_network_are_lan_and_the_flow_is_done_at_its_media():
    watch = IceWatch()
    flow = Flow(watch, PEER_LAN, 50001).out(message(BINDING_REQUEST, PRIORITY))
    check("LAN at the first check", flow.label == ice.LAN, f"({flow.label!r})")
    check("still read: no media yet", not flow.done)
    flow.out(DTLS)
    check("done once DTLS moved", flow.done)


def test_a_request_from_the_peer_is_a_check_without_priority():
    flow = Flow(IceWatch(), PEER_LAN, 50001).back(message(BINDING_REQUEST))
    check("LAN", flow.label == ice.LAN, f"({flow.label!r})")


def test_a_check_to_this_networks_public_address_is_nat():
    watch = IceWatch()
    Flow(watch, STUN_SERVER).out(message(BINDING_REQUEST)).back(
        message(BINDING_SUCCESS, xor_mapped(PUBLIC)))
    flow = Flow(watch, PUBLIC, 50001).out(message(BINDING_REQUEST, PRIORITY))
    check("NAT", flow.label == ice.NAT, f"({flow.label!r})")


def test_a_check_to_someone_elses_public_address_is_wan():
    watch = IceWatch()
    Flow(watch, STUN_SERVER).out(message(BINDING_REQUEST)).back(
        message(BINDING_SUCCESS, xor_mapped(PUBLIC)))
    flow = Flow(watch, PEER_WAN, 50001).out(message(BINDING_REQUEST, PRIORITY))
    check("WAN", flow.label == ice.WAN, f"({flow.label!r})")


def test_a_public_address_learned_late_turns_wan_into_nat_even_on_a_finished_flow():
    watch = IceWatch()
    hairpin = Flow(watch, PUBLIC, 50001).out(message(BINDING_REQUEST, PRIORITY)).out(DTLS)
    check("WAN before the address is known", hairpin.label == ice.WAN)
    check("and no longer read", hairpin.done)
    Flow(watch, STUN_SERVER).out(message(BINDING_REQUEST)).back(
        message(BINDING_SUCCESS, xor_mapped(PUBLIC)))
    check("NAT once the answer named it", hairpin.label == ice.NAT, f"({hairpin.label!r})")


def test_an_answer_from_the_allocate_names_the_public_address_too():
    watch = IceWatch()
    Flow(watch, TURN_SERVER).out(message(ALLOCATE_REQUEST)).back(
        message(ALLOCATE_SUCCESS, xor_mapped(PUBLIC)))
    flow = Flow(watch, PUBLIC, 50001).out(message(BINDING_REQUEST, PRIORITY))
    check("NAT", flow.label == ice.NAT, f"({flow.label!r})")


def test_only_an_answer_that_came_in_names_this_networks_address():
    watch = IceWatch()
    # this machine answering the peer's check: the address in it is the PEER's
    Flow(watch, PEER_WAN, 50001).back(message(BINDING_REQUEST, PRIORITY)).out(
        message(BINDING_SUCCESS, xor_mapped(PEER_WAN)))
    flow = Flow(watch, PEER_WAN, 50002).out(message(BINDING_REQUEST, PRIORITY))
    check("still WAN", flow.label == ice.WAN, f"({flow.label!r})")


def test_the_public_addresses_have_a_ceiling():
    watch = IceWatch()
    for n in range(ice.PUBLIC_MAX + 1):
        Flow(watch, STUN_SERVER, 3478 + n).back(
            message(BINDING_SUCCESS, xor_mapped(f"9.9.9.{100 + n}")))
    kept = Flow(watch, f"9.9.9.{100 + ice.PUBLIC_MAX - 1}", 50001).out(
        message(BINDING_REQUEST, PRIORITY))
    over = Flow(watch, f"9.9.9.{100 + ice.PUBLIC_MAX}", 50001).out(
        message(BINDING_REQUEST, PRIORITY))
    check("the last one that fit", kept.label == ice.NAT, f"({kept.label!r})")
    check("the one over the ceiling", over.label == ice.WAN, f"({over.label!r})")


def test_a_shared_address_space_and_link_local_are_this_network():
    for remote in ("100.64.0.9", "169.254.10.2", "10.1.2.3"):
        flow = Flow(IceWatch(), remote, 50001).out(message(BINDING_REQUEST, PRIORITY))
        check(remote, flow.label == ice.LAN, f"({flow.label!r})")


def test_ipv6_on_one_link_is_lan_even_on_global_addresses():
    same = Flow(IceWatch(), V6_PEER, 50001, local=V6_HOME, v6=True)
    same.out(message(BINDING_REQUEST, PRIORITY))
    other = Flow(IceWatch(), V6_ELSEWHERE, 50001, local=V6_HOME, v6=True)
    other.out(message(BINDING_REQUEST, PRIORITY))
    inbound = Flow(IceWatch(), V6_PEER, 50001, local=V6_HOME, v6=True)
    inbound.back(message(BINDING_REQUEST, PRIORITY))
    link = Flow(IceWatch(), "fe80::20", 50001, local="fe80::10", v6=True)
    link.out(message(BINDING_REQUEST, PRIORITY))
    check("same /64", same.label == ice.LAN, f"({same.label!r})")
    check("same /64, the peer asking", inbound.label == ice.LAN, f"({inbound.label!r})")
    check("another /64", other.label == ice.WAN, f"({other.label!r})")
    check("link-local", link.label == ice.LAN, f"({link.label!r})")


def test_a_relay_is_turn_and_is_done_only_at_the_media_it_carries():
    watch = IceWatch()
    relay = Flow(watch, TURN_SERVER).out(message(ALLOCATE_REQUEST))
    check("TURN at the Allocate", relay.label == ice.TURN, f"({relay.label!r})")
    relay.out(channel_data(message(BINDING_REQUEST, PRIORITY)))
    check("a check through the relay is not data", not relay.done)
    for _ in range(ice.PROBE_ICE + 10):
        relay.out(channel_data(message(BINDING_REQUEST, PRIORITY)))
    check("and spends no budget: the relay is still read", not relay.done)
    relay.out(message(SEND_INDICATION, attribute(0x0013, message(BINDING_REQUEST, PRIORITY))))
    check("nor is one in a Send indication", not relay.done)
    relay.back(channel_data(DTLS))
    check("done at DTLS inside ChannelData", relay.done)


def test_media_in_a_send_indication_finishes_a_relay():
    relay = Flow(IceWatch(), TURN_SERVER).out(message(ALLOCATE_REQUEST)).out(
        message(SEND_INDICATION, attribute(0x0013, RTP)))
    check("done", relay.done)


def test_turn_outranks_the_checks_that_came_first():
    flow = Flow(IceWatch(), TURN_SERVER).out(message(BINDING_REQUEST, PRIORITY))
    check("WAN first", flow.label == ice.WAN)
    flow.out(message(ALLOCATE_REQUEST))
    flow.out(message(BINDING_REQUEST, PRIORITY))
    check("then TURN, and it stays", flow.label == ice.TURN, f"({flow.label!r})")


def test_the_channeldata_range_is_quic_on_a_flow_without_turn():
    flow = Flow(IceWatch(), PEER_LAN, 50001).out(message(BINDING_REQUEST, PRIORITY))
    for _ in range(ice.PROBE_ICE + 10):
        flow.out(channel_data(DTLS))        # first byte 0x40: QUIC here, RFC 9443
    check("never media: the budget ran out instead",
          flow.done and flow.reads == ice.PROBE_ICE + 1, f"({flow.reads})")
    check("and the label stayed", flow.label == ice.LAN, f"({flow.label!r})")


def test_dtls_and_rtp_mean_nothing_without_stun():
    flow = Flow(IceWatch(), PEER_LAN, 50001)
    for _ in range(ice.PROBE_MEDIA + 10):
        flow.out(RTP)
    check("no label", flow.label == "")
    check("read for the media budget, then never", flow.reads == ice.PROBE_MEDIA,
          f"({flow.reads})")


def test_a_flow_that_is_not_ice_is_read_for_its_first_packet_only():
    flow = Flow(IceWatch(), "1.1.1.1", 53)
    for _ in range(20):
        flow.out(bytes([0x7a, 0x01]) + bytes(30))   # a DNS query's first bytes
    check("one read", flow.reads == ice.PROBE_FIRST == 1, f"({flow.reads})")
    check("no label", flow.label == "")


def test_only_the_first_packet_can_buy_the_media_budget():
    # a budget of ten, whatever PROBE_FIRST is: the rule is about the first PACKET
    flow = Flow(IceWatch(), "1.1.1.1", 53)
    flow.row["ice_n"] = 10
    flow.out(bytes([0x7a]) + bytes(30))
    for _ in range(20):
        flow.out(RTP)
    check("ten reads, not the media budget", flow.reads == 10, f"({flow.reads})")


def test_ipv4_with_options_takes_the_full_way_to_the_same_answers():
    """The short way reads fixed offsets (IPv4 without options, IPv6); a header with
    options goes through the full parse and must come to the same answers."""
    watch = IceWatch()
    key = (50000, PEER_LAN, 50001)
    row = dict(remote_ip=PEER_LAN, remote_port=50001, packets=1, bytes=0, sent=0, ice="",
               ice_n=ice.PROBE_FIRST)
    watch.observe(row, key, udp4(HOME, PEER_LAN, message(BINDING_REQUEST, PRIORITY), ihl=7),
                  True)
    check("a check is LAN", row["ice"] == ice.LAN, f"({row['ice']!r})")
    media = dict(row, ice="", ice_n=ice.PROBE_FIRST)
    watch.observe(media, (50002, PEER_LAN, 50001), udp4(HOME, PEER_LAN, RTP, ihl=7), True)
    check("a first packet that looks like media buys the budget",
          media["ice_n"] == ice.PROBE_MEDIA - 1, f"({media['ice_n']})")
    media["packets"] = 2
    for _ in range(20):
        watch.observe(media, (50002, PEER_LAN, 50001), udp4(HOME, PEER_LAN, RTP, ihl=7), True)
    check("and only the first", media["ice_n"] == ice.PROBE_MEDIA - 21, f"({media['ice_n']})")


def test_a_call_that_was_going_is_labelled_at_its_next_consent_check():
    flow = Flow(IceWatch(), PEER_LAN, 50001)
    for _ in range(300):
        flow.out(RTP)
    flow.out(message(BINDING_REQUEST, PRIORITY))
    check("LAN", flow.label == ice.LAN, f"({flow.label!r})")
    flow.out(RTP)
    check("done", flow.done)


def test_signalling_spends_no_budget_but_has_a_ceiling_of_its_own(monkeypatch):
    flow = Flow(IceWatch(), TURN_SERVER).out(message(ALLOCATE_REQUEST))
    for _ in range(ice.PROBE_ICE * 3):
        flow.out(message(REFRESH_REQUEST))
    check("still read after many keepalives", not flow.done)
    monkeypatch.setattr(ice, "SIGNAL_MAX", 50)
    quick = Flow(IceWatch(), TURN_SERVER).out(message(ALLOCATE_REQUEST))
    for _ in range(100):
        quick.out(message(REFRESH_REQUEST))
    check("never read past the ceiling", quick.done and quick.reads == 50, f"({quick.reads})")


def test_a_packet_without_a_udp_payload_spends_budget():
    watch = IceWatch()
    row = dict(remote_ip=PEER_LAN, remote_port=1, packets=1, sent=0, ice="", ice_n=1)
    watch.observe(row, (1, PEER_LAN, 1), bytes(200), True)
    check("spent", row["ice_n"] == 0)


def test_prune_and_clear_forget_what_they_should():
    watch = IceWatch()
    gone = Flow(watch, PEER_LAN, 50001).out(message(BINDING_REQUEST, PRIORITY)).out(DTLS)
    kept = Flow(watch, TURN_SERVER).out(message(ALLOCATE_REQUEST)).back(channel_data(DTLS))
    watch.prune({kept.key: kept.row})
    check("a gone row's flow is forgotten", gone.key not in watch._flows)
    check("and is no path", set(watch._paths) == {kept.key})
    Flow(watch, STUN_SERVER).back(message(BINDING_SUCCESS, xor_mapped(PUBLIC)))
    watch.clear()
    after = Flow(watch, PUBLIC, 50001).out(message(BINDING_REQUEST, PRIORITY))
    check("a new session knows no public address", after.label == ice.WAN, f"({after.label!r})")
    check("nor any flow", set(watch._flows) == {after.key})


# -- the timeline ------------------------------------------------------------ #
def lan_path(watch):
    return Flow(watch, PEER_LAN, 50001).out(message(BINDING_REQUEST, PRIORITY)).out(DTLS)


def turn_path(watch):
    return Flow(watch, TURN_SERVER).out(message(ALLOCATE_REQUEST)).back(channel_data(DTLS))


def wan_path(watch, port=50002):
    return Flow(watch, PEER_WAN, port).out(message(BINDING_REQUEST, PRIORITY)).out(DTLS)


def run(watch, seconds, start=1):
    """Tick once a second; ``seconds`` is a list of {flow: bytes delivered}."""
    events = []
    for n, delivered in enumerate(seconds, start=start):
        for flow, size in delivered.items():
            flow.row["sent"] += size
        text = watch.tick(float(n))
        if text:
            events.append((n, text))
    return events


def test_the_first_path_is_named_once_it_has_led_twice():
    watch = IceWatch()
    lan = lan_path(watch)
    events = run(watch, [{lan: 5000}] * 6)
    check("one event, at the second tick", events == [(2, "ICE path: LAN 10.0.0.20:50001")],
          f"({events})")


def test_a_move_to_the_relay_is_named_with_both_ends():
    watch = IceWatch()
    lan, relay = lan_path(watch), turn_path(watch)
    events = run(watch, [{lan: 5000}] * 4 + [{relay: 5000}] * 6)
    check("named", [t for _, t in events] == [
        "ICE path: LAN 10.0.0.20:50001",
        "ICE path: LAN 10.0.0.20:50001 -> TURN 1.1.1.1:3478"], f"({events})")


def test_checks_and_keepalives_never_make_a_path():
    watch = IceWatch()
    lan = lan_path(watch)
    events = run(watch, [{lan: 400}] * 20)
    check("no event", events == [], f"({events})")


def test_a_path_this_session_blocks_carries_nothing():
    watch = IceWatch()
    lan, relay = lan_path(watch), turn_path(watch)
    events = []
    for second in range(1, 5):
        lan.row["bytes"] += 50000       # offered every second, and never delivered
        relay.row["bytes"] += 5000
        relay.row["sent"] += 5000
        text = watch.tick(float(second))
        if text:
            events.append(text)
    check("the relay is the path", events == ["ICE path: TURN 1.1.1.1:3478"],
          f"({events})")


def test_two_paths_with_data_do_not_flip_on_a_lead_under_twice():
    watch = IceWatch()
    lan, wan = lan_path(watch), wan_path(watch)
    events = run(watch, [{lan: 5000}] * 3 + [{lan: 5000, wan: 9000}] * 10)
    check("the first path stays", [t for _, t in events] == [
        "ICE path: LAN 10.0.0.20:50001"], f"({events})")


def test_a_path_has_to_lead_twice_in_a_row():
    watch = IceWatch()
    lan, relay, wan = lan_path(watch), turn_path(watch), wan_path(watch)
    events = run(watch, [{lan: 5000}] * 4 + [{relay: 25000}, {wan: 30000}, {}])
    check("the relay led once, the WAN path twice", [t for _, t in events] == [
        "ICE path: LAN 10.0.0.20:50001",
        "ICE path: LAN 10.0.0.20:50001 -> WAN 8.8.8.8:50002"], f"({events})")


def test_data_that_stops_is_named_after_the_quiet_time():
    watch = IceWatch()
    lan = lan_path(watch)
    events = run(watch, [{lan: 5000}] * 3 + [{}] * 12)
    quiet = [(n, t) for n, t in events if "no data" in t]
    check("named once", [t for _, t in quiet] == [
        "ICE path: no data (was LAN 10.0.0.20:50001)"], f"({events})")
    # the data stopped after tick 3, the window is empty WINDOW_TICKS later, and
    # then QUIET_S runs
    check("after the window and the quiet time",
          quiet[0][0] == 3 + ice.WINDOW_TICKS + int(ice.QUIET_S), f"({quiet})")


def test_a_tick_sooner_than_a_second_does_nothing():
    watch = IceWatch()
    lan = lan_path(watch)
    run(watch, [{lan: 5000}])
    lan.row["sent"] += 5000
    check("ignored", watch.tick(1.5) is None and watch._held == 1)
    check("and took no sample", len(watch._paths[lan.key].history) == 2)


def test_a_path_whose_row_was_trimmed_goes_quiet():
    watch = IceWatch()
    lan = lan_path(watch)
    run(watch, [{lan: 5000}] * 3)
    watch.prune({})
    events = run(watch, [{}] * 8, start=4)
    check("named as stopped", [t for _, t in events] == [
        "ICE path: no data (was LAN 10.0.0.20:50001)"], f"({events})")


def test_an_ipv6_path_is_written_in_brackets():
    watch = IceWatch()
    flow = Flow(watch, V6_PEER, 50001, local=V6_HOME, v6=True)
    flow.out(message(BINDING_REQUEST, PRIORITY)).out(DTLS)
    events = run(watch, [{flow: 5000}] * 3)
    check("bracketed", [t for _, t in events] == ["ICE path: LAN [2606:4700:4700::20]:50001"],
          f"({events})")


def test_the_path_takes_the_nat_label_it_learned_while_active():
    watch = IceWatch()
    hairpin = Flow(watch, PUBLIC, 50001).out(message(BINDING_REQUEST, PRIORITY)).out(DTLS)
    relay = turn_path(watch)
    run(watch, [{hairpin: 5000}] * 3)
    Flow(watch, STUN_SERVER).back(message(BINDING_SUCCESS, xor_mapped(PUBLIC)))
    events = run(watch, [{relay: 5000}] * 6, start=4)
    check("the old end as it is known now", [t for _, t in events] == [
        "ICE path: NAT 9.9.9.9:50001 -> TURN 1.1.1.1:3478"], f"({events})")


# -- through the connection log ---------------------------------------------- #
class WirePacket:
    """A UDP packet the way pydivert holds one: ``raw`` is the whole datagram and the
    payload setter writes into it, so corrupting the payload corrupts ``raw`` too.
    ``fakes.FakePacket`` keeps the two apart, and on it a test of what the ICE column
    reads under corruption would pass whatever order the engine used."""

    def __init__(self, payload, local=HOME, remote=PEER_LAN, local_port=50000,
                 remote_port=50001):
        self.raw = memoryview(bytearray(udp4(local, remote, payload, local_port, remote_port)))
        self.is_outbound = True
        self.src_addr, self.dst_addr = local, remote
        self.src_port, self.dst_port = local_port, remote_port
        self.tcp = self.icmp = None
        self.udp = object()

    @property
    def payload(self):
        return self.raw[28:].tobytes()

    @payload.setter
    def payload(self, value):
        self.raw[28:] = value


LAN_KEY = (50000, PEER_LAN, 50001)


def new_log():
    return ConnectionLog(lambda port: "", lambda port: None)


def log_lan_call(log, now=1.0):
    for payload in (message(BINDING_REQUEST, PRIORITY), DTLS):
        packet = WirePacket(payload)
        log.log(LAN_KEY, PEER_LAN, 50001, 50000, True, len(packet.raw), now, "UDP",
                packet=packet)


def test_a_udp_row_is_labelled_through_the_connection_log():
    log = new_log()
    log_lan_call(log)
    row = log.rows[LAN_KEY]
    check("LAN", row["ice"] == ice.LAN, f"({row['ice']!r})")
    check("and read no more", row["ice_n"] == 0, f"({row['ice_n']})")


def test_a_tcp_row_is_never_read(monkeypatch):
    calls = []
    monkeypatch.setattr(IceWatch, "observe", lambda *args: calls.append(args))
    log = new_log()
    packet = WirePacket(message(BINDING_REQUEST, PRIORITY))
    for n in range(3):
        log.log((50000, PEER_LAN, 443), PEER_LAN, 443, 50000, True, 80, float(n), "TCP",
                packet=packet)
    row = log.rows[(50000, PEER_LAN, 443)]
    check("its budget is zero from the start", row["ice_n"] == 0 and row["ice"] == "")
    check("so it is never read", calls == [], f"({len(calls)} reads)")


def test_a_row_stays_under_the_key_count_that_doubles_it():
    log = new_log()
    log.log((1, PEER_LAN, 2), PEER_LAN, 2, 1, True, 10, 1.0, "UDP")
    keys = len(log.rows[(1, PEER_LAN, 2)])
    # MEASURED 2026-11-04: 18 and 20 keys cost the same, a 22nd costs 454 B more on
    # every row (the comment at the row's constructor in connlog.py has the numbers)
    check("at most 21 keys", keys <= 21, f"({keys})")


def test_a_probe_that_raises_never_reaches_the_capture_thread(monkeypatch):
    recorded = []
    monkeypatch.setattr(crashlog, "once", lambda subsystem, exc: recorded.append(subsystem))

    class Unreadable:
        @property
        def raw(self):
            raise RuntimeError("no bytes")

    log = new_log()
    log.log((1, PEER_LAN, 2), PEER_LAN, 2, 1, True, 10, 1.0, "UDP", packet=Unreadable())
    log.log((1, PEER_LAN, 2), PEER_LAN, 2, 1, True, 10, 2.0, "UDP", packet=Unreadable())
    row = log.rows[(1, PEER_LAN, 2)]
    check("both packets counted", row["packets"] == 2, f"({row['packets']})")
    check("the flow is not read again", row["ice_n"] == 0)
    check("the failure is recorded once", recorded == ["connlog.ice"], f"({recorded})")


def test_trim_and_clear_take_the_ice_state_with_the_rows():
    log = new_log()
    log.MAX_CONNS = 10
    log_lan_call(log, now=0.0)
    for n in range(20):
        log.log((n, PEER_WAN, 443), PEER_WAN, 443, n, True, 80, 100.0 + n, "TCP")
    log.trim()
    check("the oldest row went", LAN_KEY not in log.rows)
    check("and its ICE flow and path with it",
          LAN_KEY not in log._ice._flows and LAN_KEY not in log._ice._paths)
    log_lan_call(log, now=200.0)
    log.clear()
    check("clear forgets every flow", not log._ice._flows and not log._ice._paths)


def test_the_path_is_named_through_the_connection_log():
    log = new_log()
    log_lan_call(log)
    lines = []
    for second in range(1, 4):
        log.credit_delivered(LAN_KEY, 5000, True)
        lines.append(log.ice_tick(float(second)))
    check("named at the second tick", lines == [None, "ICE path: LAN 10.0.0.20:50001", None],
          f"({lines})")


# -- through the engine ------------------------------------------------------ #
def run_engine(packets, **settings):
    engine = BeanEngine()
    engine.set_seed(7)
    apply_settings(engine, dict(DEFAULT_SETTINGS, **settings))
    engine.start("test", divert=FakeDivert(packets))
    try:
        wait_until(lambda: engine.stats_snapshot()["seen"] == len(packets))
        return engine.stats_snapshot(), engine.connections_snapshot(None)
    finally:
        engine.stop()


def test_the_ice_column_reads_the_bytes_the_application_sent(monkeypatch):
    read = []
    real = IceWatch.observe

    def spy(self, row, key, raw, is_out):
        read.append(bytes(raw))
        return real(self, row, key, raw, is_out)

    monkeypatch.setattr(IceWatch, "observe", spy)
    packets = [WirePacket(message(BINDING_REQUEST, PRIORITY)), WirePacket(DTLS)]
    as_sent = [bytes(p.raw) for p in packets]
    stats, rows = run_engine(packets, corrupt=100)
    check("both packets were corrupted", stats["corrupted"] == 2, f"({stats['corrupted']})")
    check("the column read them before that", read == as_sent)
    check("so the flow is labelled", [r["ice"] for r in rows] == [ice.LAN], f"({rows})")


def test_a_dropped_packet_is_read_too():
    stats, rows = run_engine([WirePacket(message(BINDING_REQUEST, PRIORITY))], loss=100)
    check("dropped", stats["drop_loss"] == 1, f"({stats['drop_loss']})")
    check("and labelled: it is what the application sent", [r["ice"] for r in rows] == [ice.LAN],
          f"({rows})")


def test_the_watchdog_logs_the_path_as_an_event_that_is_no_session_mark(monkeypatch):
    lines = iter(["ICE path: LAN 10.0.0.20:50001"])
    engine = BeanEngine()
    monkeypatch.setattr(engine._conns_log, "ice_tick", lambda now: next(lines, None))
    engine.start("test", divert=FakeDivert([]))
    try:
        logged = wait_until(lambda: any(e[2] == "PATH" for e in engine.events_snapshot()))
        mark = engine.session_mark()
    finally:
        engine.stop()
    paths = [e[3] for e in engine.events_snapshot() if e[2] == "PATH"]
    check("logged once", logged and paths == ["ICE path: LAN 10.0.0.20:50001"], f"({paths})")
    # Ping splits its results at a mark (ping.PART_KINDS): a path change alters
    # nothing this session does to traffic, so it must not start a new part
    check("the mark is still the START", mark is not None and mark[1] == "START", f"({mark})")


def test_a_failing_timeline_leaves_the_watchdog_its_deadline(monkeypatch):
    noted = []
    monkeypatch.setattr(crashlog, "note",
                        lambda exc, subsystem, message="": noted.append(subsystem))
    engine = BeanEngine()

    def broken(now):
        raise RuntimeError("timeline")

    monkeypatch.setattr(engine._conns_log, "ice_tick", broken)
    engine.start("test", divert=FakeDivert([]), duration=0.6)
    stopped = wait_until(lambda: not engine.is_running(), timeout=5.0)
    if not stopped:
        engine.stop()
    check("the duration still ended the session", stopped)
    check("the failure was recorded", "engine.ice" in noted, f"({noted})")
