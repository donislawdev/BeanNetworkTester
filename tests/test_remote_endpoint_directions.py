"""Every gate that judges the REMOTE end must judge it in BOTH directions.

The invariant: ``engine._capture_loop`` reads the remote endpoint as the packet's
DESTINATION when it is outbound and as its SOURCE when it is inbound. Five
features consume that value - destination IP, destination port, LAN mode, block
by IP, block by port - and each of them is meant to act on "who the other end
is", not on "which header field happens to hold it".

Why this file exists rather than one more case in an existing test. MUTATION,
2026-07-29: changing the inbound branch to read ``dst_addr`` - the exact
"simplification" someone would make while tidying that block - was caught by
**three tests, all of them about the CONNECTION LOG**. Not one test about
targeting, LAN mode or blocking noticed. The tool would have gone on impairing
outbound traffic and quietly stopped impairing everything coming back, with every
counter healthy, and the only red would have been in rows somebody could
plausibly have "fixed" by adjusting the expected output.

So the guard is table-driven on the CONSUMERS, not on one feature: adding a sixth
thing that reads the remote endpoint and forgetting the inbound case fails here
immediately. It is the same shape as ``GATES`` in ``test_core_properties.py``,
and for the same reason - enumerate what depends on the rule, or the rule is only
as guarded as whichever consumer somebody remembered.
"""
import time

from beantester.engine import BeanEngine
from fakes import FakeDivert, FakePacket, check

# Genuinely routable addresses, and that is not a detail: LAN mode gates on
# `is_local_ip`, which counts the TEST-NET documentation ranges (203.0.113.x,
# 198.51.100.x) as local because they are not globally routable. Reaching for one
# of those - the obvious choice for a test - makes LAN mode do nothing and looks
# like a bug in the gate. Checked, not assumed.
PEER = "8.8.8.8"
PEER_PORT = 4433
OTHER = "1.1.1.1"             # a different public peer, for the "not matched" side


def _run(configure, packets, counter):
    engine = BeanEngine()
    configure(engine)
    engine.start("test", divert=FakeDivert(list(packets)))
    deadline = time.time() + 5
    while time.time() < deadline and engine.stats_snapshot()["seen"] < len(packets):
        time.sleep(0.02)
    time.sleep(0.05)
    stats = engine.stats_snapshot()
    engine.stop()
    return stats[counter]


# The local end always uses this, and it must DIFFER from the peer's port. With
# both ports equal - which is what FakePacket did until this file needed
# otherwise - swapping the inbound branch's src/dst ports changes nothing, so a
# direction assertion passes while testing nothing. Verified by mutation.
LOCAL_PORT = 50001


def _outbound_to(peer, port=PEER_PORT):
    """The remote end is the DESTINATION here: peer port on dst, ours on src."""
    return FakePacket(size=200, is_outbound=True, src_port=LOCAL_PORT,
                      dst_port=port, dst_addr=peer, src_addr="10.0.0.2")


def _inbound_from(peer, port=PEER_PORT):
    """The remote end is the SOURCE here - the half that had no guard at all."""
    return FakePacket(size=200, is_outbound=False, src_port=port,
                      dst_port=LOCAL_PORT, src_addr=peer, dst_addr="10.0.0.2")


# (name, how to configure the engine, which counter should move)
CONSUMERS = (
    ("destination IP",
     lambda e: e.set_dest(True, PEER, ""), "drop_loss"),
    ("destination port",
     lambda e: e.set_dest(True, "", str(PEER_PORT)), "drop_loss"),
    ("LAN mode",
     lambda e: e.set_lan(True), "drop_lan"),
    ("block by IP",
     lambda e: e.set_block(True, PEER, ""), "drop_block"),
    ("block by port",
     lambda e: e.set_block(True, "", str(PEER_PORT)), "drop_block"),
)


def test_every_remote_endpoint_gate_fires_in_both_directions():
    """Outbound TO the peer and inbound FROM the peer must be treated alike."""
    for name, configure, counter in CONSUMERS:
        def setup(engine, configure=configure, counter=counter):
            configure(engine)
            if counter == "drop_loss":
                # destination targeting only SELECTS; something has to do damage
                engine.set_params(100, 0, 0, 0, 0, 0, 0)

        out = _run(setup, [_outbound_to(PEER)], counter)
        check("%s: an OUTBOUND packet to the peer is caught" % name, out == 1,
              "(%s=%s)" % (counter, out))

        inn = _run(setup, [_inbound_from(PEER)], counter)
        check("%s: an INBOUND packet from the peer is caught too" % name, inn == 1,
              "(%s=%s)" % (counter, inn))


def test_the_gates_still_let_a_different_peer_through_in_both_directions():
    """The mirror half: matching both directions must not mean matching everything.

    Without this, a gate that simply said "yes" would satisfy the test above.
    """
    for name, configure, counter in CONSUMERS:
        if name == "LAN mode":
            continue          # LAN mode gates on "is it public", not on which peer

        def setup(engine, configure=configure, counter=counter):
            configure(engine)
            if counter == "drop_loss":
                engine.set_params(100, 0, 0, 0, 0, 0, 0)

        other_port = PEER_PORT + 1
        out = _run(setup, [_outbound_to(OTHER, other_port)], counter)
        check("%s: an unrelated OUTBOUND packet is left alone" % name, out == 0,
              "(%s=%s)" % (counter, out))

        inn = _run(setup, [_inbound_from(OTHER, other_port)], counter)
        check("%s: an unrelated INBOUND packet is left alone" % name, inn == 0,
              "(%s=%s)" % (counter, inn))
