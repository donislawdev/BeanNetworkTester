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
import heapq
import time

from beantester.engine import BeanEngine
from fakes import FakeDivert, FakePacket, check


def _stop_after_the_first_pop(monkeypatch, entries):
    """Queue ``entries`` and end the session the instant the injector pops one.

    The pop happens under the queue's lock, so ending the session right there is
    exactly STOP landing between the pop and the send - the state the loop checks
    for. Rewritten 2026-10-01 (external review, P3-7a): the test this replaces
    bumped the counter ITSELF ("what the loop now does") and so proved nothing
    about the loop.
    """
    engine = BeanEngine()
    engine.start("test", divert=FakeDivert([]))
    real_pop = heapq.heappop
    popped = []

    def pop_then_end(heap):
        entry = real_pop(heap)
        if heap is engine._heap and not popped:
            popped.append(entry)
            engine._session.live = False
        return entry

    monkeypatch.setattr(heapq, "heappop", pop_then_end)
    now = time.monotonic()
    for offset, packet, copy in entries:
        engine._enqueue(now + offset, packet, copy=copy)
    deadline = time.time() + 5
    while time.time() < deadline and not popped:
        time.sleep(0.01)
    time.sleep(0.1)                     # let the loop take its branch
    engine.stop()
    return engine.stats_snapshot(), popped


def test_a_packet_popped_after_the_session_ended_is_recorded_not_lost(monkeypatch):
    """The pop happened; the send cannot. It has to land in a counter."""
    stats, popped = _stop_after_the_first_pop(
        monkeypatch, [(-1.0, FakePacket(port=6100), False)])

    check("the injector popped the packet", len(popped) == 1, f"({popped})")
    check("the packet is accounted for at shutdown", stats["drop_shutdown"] == 1,
          f"(drop_shutdown={stats['drop_shutdown']})")


def test_a_duplicate_copy_popped_after_the_session_ended_is_not_a_lost_packet(
        monkeypatch):
    """External review, P3-7a: the loop threw the copy flag away, so a stranded
    COPY counted as a second lost packet - while stop()'s own sweep, which reads
    the flag, counts the original once. The copy leaves first here (it is due
    first); the original is still queued and is stop()'s to count."""
    packet = FakePacket(port=6200)
    stats, popped = _stop_after_the_first_pop(
        monkeypatch, [(5.0, packet, False), (-1.0, packet, True)])

    check("the copy was the one popped", popped and popped[0][3] is True, f"({popped})")
    check("one packet lost, counted once", stats["drop_shutdown"] == 1,
          f"(drop_shutdown={stats['drop_shutdown']})")


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
