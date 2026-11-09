"""The STUN codec of the NAT and STUN tool (``beantester/stun.py``).

The answers it reads are the RFC's own bytes - RFC 5769, "Test Vectors for Session
Traversal Utilities for NAT (STUN)", sections 2.1 to 2.3, copied from the RFC text -
not bytes written for this test: a codec checked only against its own encoder agrees
with itself and nothing else. Each vector carries a FINGERPRINT, so a byte copied
wrong here would fail the CRC before any assertion about it.
"""
import random

from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from beantester import ice, stun

TRANSACTION = bytes.fromhex("b7e7a701bc34d686fa87dfae")

# RFC 5769, 2.1: a Binding request (SOFTWARE, PRIORITY, ICE-CONTROLLED, USERNAME
# padded with spaces, MESSAGE-INTEGRITY, FINGERPRINT).
REQUEST_2_1 = bytes.fromhex(
    "00010058" "2112a442" "b7e7a701" "bc34d686" "fa87dfae"
    "80220010" "5354554e" "20746573" "7420636c" "69656e74"
    "00240004" "6e0001ff"
    "80290008" "932ff9b1" "51263b36"
    "00060009" "6576746a" "3a683676" "59202020"
    "00080014" "9aeaa70c" "bfd8cb56" "781ef2b5" "b2d3f249" "c1b571a2"
    "80280004" "e57a3bcf")

# RFC 5769, 2.2: a Binding success answer, mapped address 192.0.2.1 port 32853.
RESPONSE_2_2 = bytes.fromhex(
    "0101003c" "2112a442" "b7e7a701" "bc34d686" "fa87dfae"
    "8022000b" "74657374" "20766563" "746f7220"
    "00200008" "0001a147" "e112a643"
    "00080014" "2b91f599" "fd9e90c3" "8c7489f9" "2af9ba53" "f06be7d7"
    "80280004" "c07d4c96")

# RFC 5769, 2.3: the same answer for 2001:db8:1234:5678:11:2233:4455:6677 port 32853.
RESPONSE_2_3 = bytes.fromhex(
    "01010048" "2112a442" "b7e7a701" "bc34d686" "fa87dfae"
    "8022000b" "74657374" "20766563" "746f7220"
    "00200014" "0002a147" "0113a9fa" "a5d3f179" "bc25f4b5" "bed2b9d9"
    "00080014" "a382954e" "4be67bf1" "1784c97c" "8292c275" "bfe3ed41"
    "80280004" "c8fb0b4c")

VECTORS = (REQUEST_2_1, RESPONSE_2_2, RESPONSE_2_3)


def test_the_rfc_5769_answers_decode_to_the_addresses_the_rfc_states():
    v4 = stun.decode(RESPONSE_2_2)
    assert v4 is not None, "the fingerprint of the RFC's IPv4 answer did not check out"
    assert (v4.method, v4.kind, v4.transaction) == (stun.BINDING, stun.SUCCESS, TRANSACTION)
    assert stun.mapped_address(v4) == ("192.0.2.1", 32853)

    v6 = stun.decode(RESPONSE_2_3)
    assert v6 is not None, "the fingerprint of the RFC's IPv6 answer did not check out"
    assert stun.mapped_address(v6) == ("2001:db8:1234:5678:11:2233:4455:6677", 32853)
    assert stun.error_code(v4) is None, "a success answer carries no error code"


def test_the_rfc_5769_request_decodes_attribute_by_attribute():
    message = stun.decode(REQUEST_2_1)
    assert message is not None
    assert (message.method, message.kind) == (stun.BINDING, stun.REQUEST)
    kinds = [kind for kind, _value in message.attributes]
    assert kinds == [0x8022, ice.PRIORITY, 0x8029, 0x0006, 0x0008, stun.FINGERPRINT], kinds
    values = dict(message.attributes)
    assert values[0x0006] == b"evtj:h6vY", "the padding is not part of the value"
    assert values[0x8022] == b"STUN test client"
    assert stun.mapped_address(message) is None


def test_a_changed_byte_or_a_cut_message_is_not_taken():
    """The fingerprint covers every byte before it; a cut message is not one."""
    for vector in VECTORS:
        for at in range(len(vector) - 8):           # every byte before FINGERPRINT
            changed = bytearray(vector)
            changed[at] ^= 0x01
            assert stun.decode(bytes(changed)) is None, (vector[:4].hex(), at)
        for cut in range(len(vector)):
            assert stun.decode(vector[:cut]) is None, (vector[:4].hex(), cut)
        assert stun.decode(vector + b"\0\0\0\0") is None, "one message per datagram"


def test_the_requests_are_the_bytes_the_rfcs_describe():
    tid = bytes(range(12))
    assert stun.binding_request(tid) == bytes.fromhex("000100002112a442") + tid
    # RFC 8656: Allocate is method 3; REQUESTED-TRANSPORT 0x0019 carries 17 (UDP)
    # and three reserved bytes; no credentials, so no USERNAME or MESSAGE-INTEGRITY.
    assert stun.allocate_request(tid) == (bytes.fromhex("000300082112a442") + tid
                                          + bytes.fromhex("0019000411000000"))
    # RFC 8656: Refresh is method 4; LIFETIME 0x000D of 0 gives the allocation back
    assert stun.release_request(tid) == (bytes.fromhex("000400082112a442") + tid
                                         + bytes.fromhex("000d000400000000"))
    for request in (stun.binding_request(tid), stun.allocate_request(tid),
                    stun.release_request(tid)):
        message = stun.decode(request)
        assert message is not None and message.transaction == tid
        assert message.kind == stun.REQUEST
    # the message types of RFC 8489 and RFC 8656, by their numbers
    assert stun.message_type(stun.BINDING, stun.SUCCESS) == 0x0101
    assert stun.message_type(stun.BINDING, stun.ERROR) == 0x0111
    assert stun.message_type(stun.ALLOCATE, stun.ERROR) == 0x0113
    assert stun.message_type(0x0FFF, stun.REQUEST) == 0x3EEF, "every method bit lands"


def test_an_answer_written_with_a_fingerprint_reads_back():
    tid = stun.transaction_id()
    assert len(tid) == 12 and tid != stun.transaction_id()
    xored = bytes((0, stun.IPV4)) + (32853 ^ 0x2112).to_bytes(2, "big") + \
        (int.from_bytes(bytes((192, 0, 2, 1)), "big") ^ stun.MAGIC).to_bytes(4, "big")
    answer = stun.encode(stun.BINDING, stun.SUCCESS, tid,
                         ((ice.XOR_MAPPED_ADDRESS, xored),), fingerprint=True)
    message = stun.decode(answer)
    assert message is not None and stun.mapped_address(message) == ("192.0.2.1", 32853)
    assert message.attributes[-1][0] == stun.FINGERPRINT


def _error(code, phrase=b"Unauthenticated"):
    value = bytes((0, 0, code // 100, code % 100)) + phrase
    return stun.decode(stun.encode(stun.ALLOCATE, stun.ERROR, bytes(12),
                                   ((stun.ERROR_CODE, value),)))


def test_the_error_code_is_a_number_and_a_wrong_one_is_none():
    assert _error(401).kind == stun.ERROR
    assert stun.error_code(_error(401)) == 401
    assert stun.error_code(_error(438, b"")) == 438
    assert stun.error_code(_error(699)) == 699
    assert stun.error_code(_error(300)) == 300
    bad_class = stun.decode(stun.encode(stun.ALLOCATE, stun.ERROR, bytes(12),
                                        ((stun.ERROR_CODE, bytes((0, 0, 7, 1))),)))
    assert stun.error_code(bad_class) is None
    two = stun.decode(stun.encode(stun.ALLOCATE, stun.ERROR, bytes(12),
                                  ((stun.ERROR_CODE, bytes((0, 0, 2, 0))),)))
    assert stun.error_code(two) is None, "class 2 is not an error"
    big = stun.decode(stun.encode(stun.ALLOCATE, stun.ERROR, bytes(12),
                                  ((stun.ERROR_CODE, bytes((0, 0, 4, 100))),)))
    assert stun.error_code(big) is None, "the number stops at 99"
    short = stun.decode(stun.encode(stun.ALLOCATE, stun.ERROR, bytes(12),
                                    ((stun.ERROR_CODE, bytes((0, 0, 4))),)))
    assert stun.error_code(short) is None


def test_mapped_address_prefers_xor_and_reads_the_old_one_alone():
    tid = bytes(12)
    plain = bytes((0, stun.IPV4)) + (3478).to_bytes(2, "big") + bytes((198, 51, 100, 7))
    old = stun.decode(stun.encode(stun.BINDING, stun.SUCCESS, tid,
                                  ((stun.MAPPED_ADDRESS, plain),)))
    assert stun.mapped_address(old) == ("198.51.100.7", 3478)
    xored = stun.decode(RESPONSE_2_2)
    both = stun.decode(stun.encode(stun.BINDING, stun.SUCCESS, TRANSACTION,
                                   ((stun.MAPPED_ADDRESS, plain),) + tuple(
                                       a for a in xored.attributes
                                       if a[0] == ice.XOR_MAPPED_ADDRESS)))
    assert stun.mapped_address(both) == ("192.0.2.1", 32853)
    for value in (b"", plain[:3], bytes((0, 3)) + plain[2:], plain + b"\0\0\0\0"):
        message = stun.decode(stun.encode(stun.BINDING, stun.SUCCESS, tid,
                                          ((stun.MAPPED_ADDRESS, value),)))
        assert stun.mapped_address(message) is None, value.hex()


def test_an_address_no_request_can_come_from_is_no_answer():
    """The hairpin jobs send to the address an answer gives: port 0, an unspecified, a
    multicast or the broadcast address is refused before anything is sent there."""
    def answer(family, address, port):
        value = bytes((0, family)) + port.to_bytes(2, "big") + address
        return stun.decode(stun.encode(stun.BINDING, stun.SUCCESS, bytes(12),
                                       ((stun.MAPPED_ADDRESS, value),)))
    good = bytes((198, 51, 100, 7))
    assert stun.mapped_address(answer(stun.IPV4, good, 1)) == ("198.51.100.7", 1)
    for address, port in ((good, 0), (bytes(4), 3478), (bytes((224, 0, 0, 1)), 3478),
                          (bytes((255, 255, 255, 255)), 3478)):
        assert stun.mapped_address(answer(stun.IPV4, address, port)) is None, (address, port)
    assert stun.mapped_address(answer(stun.IPV6, bytes(16), 3478)) is None
    assert stun.mapped_address(answer(stun.IPV6, bytes((0xff, 2)) + bytes(14), 3478)) is None
    v6 = bytes((0x20, 0x01, 0x0d, 0xb8)) + bytes(11) + b"\x01"
    assert stun.mapped_address(answer(stun.IPV6, v6, 3478)) == ("2001:db8::1", 3478)


def test_what_is_not_a_stun_message_is_none():
    good = stun.binding_request(bytes(12))
    assert stun.decode(b"") is None
    assert stun.decode(b"\x80" + good[1:]) is None, "the first two bits are zero"
    assert stun.decode(good[:4] + b"\0\0\0\0" + good[8:]) is None, "no magic cookie"
    odd = bytearray(stun.allocate_request(bytes(12)))
    odd[3] = 6                                      # a length that is not a multiple of 4
    assert stun.decode(bytes(odd[:26])) is None
    runs_past = bytearray(stun.allocate_request(bytes(12)))
    runs_past[22:24] = (8).to_bytes(2, "big")       # an attribute longer than what is left
    assert stun.decode(bytes(runs_past)) is None
    long = stun.encode(stun.BINDING, stun.SUCCESS, bytes(12), ((0x8022, bytes(4080)),))
    assert len(long) > stun.MAX_MESSAGE and stun.decode(long) is None
    early = stun.encode(stun.BINDING, stun.SUCCESS, bytes(12), ((0x8022, b"abcd"),),
                        fingerprint=True)
    moved = early[:2] + (16).to_bytes(2, "big") + early[4:20] + early[28:] + early[20:28]
    assert stun.decode(moved) is None, "FINGERPRINT is the last attribute or wrong"


def test_stream_length_cuts_one_message_out_of_a_tcp_stream():
    assert stun.stream_length(RESPONSE_2_2[:20]) == len(RESPONSE_2_2)
    assert stun.stream_length(RESPONSE_2_2) == len(RESPONSE_2_2)
    assert stun.stream_length(RESPONSE_2_2[:19]) is None
    assert stun.stream_length(b"HTTP/1.1 400 Bad Request\r\n") is None
    too_long = bytes.fromhex("0101") + (stun.MAX_MESSAGE - 16).to_bytes(2, "big") + \
        RESPONSE_2_2[4:20]
    assert stun.stream_length(too_long) is None
    odd = bytes.fromhex("01010006") + RESPONSE_2_2[4:20]
    assert stun.stream_length(odd) is None


@hypothesis_settings(max_examples=400, deadline=None)
@given(st.binary(max_size=200))
def test_any_bytes_decode_to_a_message_or_none_and_never_raise(data):
    message = stun.decode(data)
    if message is not None:
        stun.mapped_address(message)
        stun.error_code(message)
    stun.stream_length(data)


def test_random_attributes_behind_a_real_header_never_raise():
    """Bytes that pass the header checks reach the attribute walk - where a bound
    that is off by one reads past the end."""
    rng = random.Random(5769)
    for _ in range(3000):
        body = bytes(rng.randrange(256) for _ in range(4 * rng.randrange(0, 20)))
        data = (bytes.fromhex("0111") + len(body).to_bytes(2, "big") + stun.COOKIE
                + bytes(12) + body)
        message = stun.decode(data)
        if message is not None:
            assert sum(4 + len(v) + (-len(v) % 4) for _k, v in message.attributes) == len(body)
            stun.mapped_address(message)
            stun.error_code(message)
