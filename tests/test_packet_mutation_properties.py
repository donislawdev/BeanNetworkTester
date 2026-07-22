"""Property-based tests for the two functions that MUTATE or FORGE a packet:
``BeanCore.corrupt_packet`` and ``BeanCore.build_rst_fields``.

The pipeline (``decide``) only ever DECIDES a packet's fate; these two are the
only places the tool reaches into the bytes on the wire. The example tests in
``test_core.py`` pin one case each (a 16-byte zero payload, one inbound and one
outbound RST). What no example reaches is the whole input space, and both
functions have a property that only shows up across it:

* **``corrupt_packet`` runs on the CAPTURE THREAD**, once per corrupted packet.
  An exception there kills capture with the divert still open, and WinDivert then
  queues the user's packets into a void - the machine loses connectivity while the
  UI says "running" (convention 20). So it must be TOTAL (never raise, whatever the
  packet), and its one documented effect - flip a single bit of the payload - has to
  hold for every payload, not just the one in the example.
* **``build_rst_fields`` forges a packet that is injected onto the user's LIVE
  connection** to tear it down. If it aims the RST at the wrong endpoint or carries
  the wrong sequence number it resets nothing, or resets the wrong socket. The
  endpoint/seq logic flips on packet direction, which is exactly the kind of
  two-branch swap an example test can get right by luck.

These are a regression net, not a bug hunt: at the time of writing both functions
survived every example below.
"""
import random
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from beantester.core import BeanCore
from fakes import FakePacket, check

SLOW = settings(max_examples=300, deadline=None)

payloads = st.binary(min_size=1, max_size=2000)
seeds = st.integers(min_value=0, max_value=2**32 - 1)


def _bit_difference(a, b):
    """Total number of differing bits between two equal-length byte strings."""
    return sum(bin(x ^ y).count("1") for x, y in zip(a, b))


# --------------------------------------------------------------------------- #
# corrupt_packet: flip exactly one bit of the payload, and never do worse
# --------------------------------------------------------------------------- #
@SLOW
@given(payload=payloads, seed=seeds)
def test_corruption_flips_exactly_one_bit_and_keeps_the_length(payload, seed):
    """The documented effect - "flip a random bit in the payload" - stated as a
    property over every payload, not the single 16-byte example in test_core.py.

    Length preserved AND Hamming distance exactly 1: corruption must damage the
    payload without truncating or growing it (a length change would be a different
    packet, not a corrupted one).
    """
    pkt = FakePacket(payload=payload)
    ok = BeanCore.corrupt_packet(pkt, random.Random(seed))
    after = pkt.payload
    check("a non-empty payload reports corruption", ok is True)
    check("corruption preserves the payload length",
          len(after) == len(payload), f"({len(after)} vs {len(payload)})")
    check("corruption flips exactly one bit",
          _bit_difference(payload, after) == 1,
          f"({_bit_difference(payload, after)} bits changed)")


@SLOW
@given(payload=payloads, seed=seeds)
def test_corruption_is_deterministic_for_a_given_seed(payload, seed):
    """Same payload + same RNG state -> same corruption.

    Reproducibility is a headline promise of this tool (every session has a
    concrete seed). If the same seed corrupted a packet two different ways, a
    re-run of a saved seed would not reproduce the run it claims to.
    """
    a = FakePacket(payload=payload)
    b = FakePacket(payload=payload)
    BeanCore.corrupt_packet(a, random.Random(seed))
    BeanCore.corrupt_packet(b, random.Random(seed))
    check("same payload + same seed -> identical corruption",
          a.payload == b.payload, f"({a.payload!r} vs {b.payload!r})")


@SLOW
@given(payload=payloads, seed=seeds)
def test_corruption_touches_nothing_but_the_payload(payload, seed):
    """Corruption is payload-only: a flipped bit must not move a port or an
    address, or it would be re-routing the packet, not damaging its contents."""
    pkt = FakePacket(payload=payload)
    before = (pkt.src_port, pkt.dst_port, pkt.src_addr, pkt.dst_addr, pkt.is_outbound)
    BeanCore.corrupt_packet(pkt, random.Random(seed))
    after = (pkt.src_port, pkt.dst_port, pkt.src_addr, pkt.dst_addr, pkt.is_outbound)
    check("corruption leaves every header field alone", before == after,
          f"(before={before}, after={after})")


@SLOW
@given(seed=seeds)
def test_an_empty_payload_is_reported_as_uncorrupted_and_left_alone(seed):
    """Nothing to flip: return False (so the engine does not count it as corrupted)
    and leave the empty payload as it was."""
    pkt = FakePacket(payload=b"")
    ok = BeanCore.corrupt_packet(pkt, random.Random(seed))
    check("an empty payload cannot be corrupted", ok is False)
    check("an empty payload is left untouched", pkt.payload == b"")


class _HostilePacket:
    """A packet whose payload cannot even be read - stands in for a foreign packet
    type or a driver quirk the capture thread might be handed."""

    @property
    def payload(self):
        raise RuntimeError("payload is unavailable")


@SLOW
@given(seed=seeds)
def test_corruption_never_raises_on_a_packet_it_cannot_handle(seed):
    """Totality on the hot path. corrupt_packet runs on the capture thread, where a
    raised exception leaves the divert open with nothing draining it (convention 20).
    Any packet it cannot corrupt must come back as a quiet False, never an exception.
    """
    ok = BeanCore.corrupt_packet(_HostilePacket(), random.Random(seed))
    check("an un-corruptable packet returns False instead of raising", ok is False)


# --------------------------------------------------------------------------- #
# build_rst_fields: forge an RST aimed at the LOCAL socket, spoofing the peer
# --------------------------------------------------------------------------- #
addrs = st.ip_addresses().map(str)
ports = st.integers(min_value=0, max_value=65535)
seqnums = st.integers(min_value=0, max_value=2**32 - 1)


def _tcp_packet(is_outbound, src_addr, dst_addr, src_port, dst_port, seq, ack):
    tcp = SimpleNamespace(seq_num=seq, ack_num=ack, syn=False, ack=False)
    return SimpleNamespace(is_outbound=is_outbound, tcp=tcp,
                           src_addr=src_addr, dst_addr=dst_addr,
                           src_port=src_port, dst_port=dst_port)


@SLOW
@given(is_outbound=st.booleans(), src_addr=addrs, dst_addr=addrs,
       src_port=ports, dst_port=ports, seq=seqnums, ack=seqnums)
def test_the_rst_is_addressed_to_the_local_end_and_spoofs_the_peer(
        is_outbound, src_addr, dst_addr, src_port, dst_port, seq, ack):
    """An RST is injected onto the user's live connection to reset it, so it must
    claim to travel FROM the remote peer TO the local socket - anything else resets
    the wrong flow, or nothing.

    Which endpoint is "local" is fixed by the direction of the OBSERVED packet:
    an outbound packet went local -> remote, an inbound one remote -> local. Whatever
    the direction, the forged RST must be sent from the remote endpoint to the local
    one, be marked inbound, and carry the sequence number the local end expects next
    (the ack we saw going out, or the seq we saw coming in). This states that as one
    invariant instead of two mirror-image branches.
    """
    pkt = _tcp_packet(is_outbound, src_addr, dst_addr, src_port, dst_port, seq, ack)
    f = BeanCore.build_rst_fields(pkt)

    if is_outbound:                          # observed local -> remote
        local, remote, expected_seq = (src_addr, src_port), (dst_addr, dst_port), ack
    else:                                    # observed remote -> local
        local, remote, expected_seq = (dst_addr, dst_port), (src_addr, src_port), seq

    check("the RST is marked inbound (peer -> local)",
          f["direction_inbound"] is True, f"({f})")
    check("the RST is sent FROM the remote peer",
          (f["src_ip"], f["src_port"]) == remote,
          f"(src=({f['src_ip']}, {f['src_port']}), remote={remote})")
    check("the RST is addressed TO the local socket",
          (f["dst_ip"], f["dst_port"]) == local,
          f"(dst=({f['dst_ip']}, {f['dst_port']}), local={local})")
    check("the RST carries the sequence the local end expects next",
          f["seq_num"] == expected_seq, f"({f['seq_num']} vs {expected_seq})")


@SLOW
@given(is_outbound=st.booleans(), src_addr=addrs, dst_addr=addrs,
       src_port=ports, dst_port=ports)
def test_a_non_tcp_packet_yields_no_rst_fields(is_outbound, src_addr, dst_addr,
                                               src_port, dst_port):
    """RST is a TCP concept. A UDP/ICMP packet (no ``tcp`` layer) must produce
    ``None`` so the engine never tries to forge and inject an RST for it."""
    pkt = SimpleNamespace(is_outbound=is_outbound, tcp=None,
                          src_addr=src_addr, dst_addr=dst_addr,
                          src_port=src_port, dst_port=dst_port)
    check("a non-TCP packet has no RST fields",
          BeanCore.build_rst_fields(pkt) is None)
