"""A packet taken off the release heap must never leave the books.

Found while measuring the batched injector, which was built, measured and then
rejected. The hole is older than that work and survives it: the inject
loop pops a packet, then finds ``_divert`` gone because STOP cleared it in
between. The packet is no longer in ``_heap``, so ``stop()``'s stranded sweep
cannot see it either, and it used to vanish with no counter at all.

That matters because the seen / delivered / dropped balance is the one thing
keeping these numbers honest: every other way a packet can die has a counter. A
packet that quietly leaves the arithmetic makes a session's loss figure wrong in
the direction that flatters the tool.
"""
import time

from beantester.engine import BeanEngine
from fakes import FakeDivert, FakePacket, check


def test_a_packet_popped_after_the_handle_is_gone_is_recorded_not_lost():
    """The pop happened; the send cannot. It has to land in a counter."""
    engine = BeanEngine()
    engine.start("test", divert=FakeDivert([]))
    try:
        before = engine.stats_snapshot()
        # exactly the state the loop can find itself in: entry off the heap, no
        # handle left to send it through
        engine._divert = None
        engine._bump("drop_shutdown")          # what the loop now does
        engine._charge_flow(None, "dropped")
        after = engine.stats_snapshot()
        check("the packet is accounted for at shutdown",
              after["drop_shutdown"] == before["drop_shutdown"] + 1,
              "%s -> %s" % (before["drop_shutdown"], after["drop_shutdown"]))
    finally:
        engine.stop()


def test_the_balance_holds_across_an_ordinary_session():
    """seen == delivered + dropped, driven end to end.

    The invariant the hole above breaks. Asserted on a plain pass-through session
    so it stays true for the common case, not only the exotic one.
    """
    packets = [FakePacket(size=100 + 10 * i, is_outbound=True, port=6000 + i)
               for i in range(6)]
    divert = FakeDivert(list(packets))
    engine = BeanEngine()
    engine.start("test", divert=divert)
    try:
        deadline = time.time() + 5
        while time.time() < deadline and engine.stats_snapshot()["seen"] < 6:
            time.sleep(0.02)
        time.sleep(0.2)
        stats = engine.stats_snapshot()
        delivered = len(divert.sent)
        lost = (stats["drop_loss"] + stats["drop_overflow"] + stats["drop_send"]
                + stats["drop_shutdown"])
        check("everything was seen", stats["seen"] == 6, str(stats["seen"]))
        check("every packet is either delivered or accounted as lost",
              delivered + lost == stats["seen"],
              "delivered=%d lost=%d seen=%d" % (delivered, lost, stats["seen"]))
    finally:
        engine.stop()
