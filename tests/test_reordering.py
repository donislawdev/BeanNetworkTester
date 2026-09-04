"""The ``reordered`` counter: did the tool actually change the order of packets?

Why this counter needs a guard of its own. Configuring jitter or a latency spike
does NOT mean anything was reordered - whether a delayed packet is overtaken
depends on how far apart the packets were, which is a property of the traffic
rather than of the settings. So a run where nothing ever overtook anything reads
exactly like a run where the application coped, and the only thing that can tell
them apart is a number. That is the same hole ``loss_bursts`` was added to close
for losses arriving in runs.

These tests drive ``BeanEngine._enqueue`` directly rather than going through
``decide()``. That is deliberate: the question here is what the INJECTOR counts
given a known release order, and driving the decision pipeline would make the
test depend on a random draw to produce the very ordering it wants to assert on.
The decision side is covered by ``test_core.py``.

The release offsets below are generous (hundreds of ms for the "late" packet)
for one reason worth stating: the heap pops by release time, so the ORDER under
test is deterministic no matter how loaded the machine is - the single way this
could go wrong is the injector sending the late packet before the early one has
been queued at all, which needs a stall longer than that offset between two
adjacent statements.
"""
import time

from beantester import BeanEngine

from fakes import FakeDivert, FakePacket, check


class RefusingDivert(FakeDivert):
    """A diverter that refuses ONE packet, so a failed send can be observed."""

    def __init__(self, packets, refuse):
        super().__init__(packets)
        self.refuse = refuse

    def send(self, p, recalculate_checksum=True):
        if p is self.refuse:
            raise OSError("the driver refused this one")
        super().send(p, recalculate_checksum=recalculate_checksum)


def _run(releases, divert=None):
    """Queue ``(offset, packet)`` pairs in order, wait for delivery, return stats.

    ``releases`` is queued in list order, so the first entry is the packet that
    ARRIVED first - which is the whole variable these tests turn.
    """
    fake = divert if divert is not None else FakeDivert([])
    engine = BeanEngine()
    engine.start("test", divert=fake)
    try:
        now = time.monotonic()
        for offset, packet in releases:
            engine._enqueue(now + offset, packet)
        deadline = time.time() + 10
        while time.time() < deadline:
            s = engine.stats_snapshot()
            if s["queue"] == 0 and len(fake.sent) + s["drop_send"] >= len(releases):
                break
            time.sleep(0.01)
        time.sleep(0.05)
        return engine.stats_snapshot(), [p for _, p in fake.sent]
    finally:
        engine.stop()


def test_a_packet_that_is_overtaken_is_counted_as_reordered():
    """The point of the counter: one packet leaves after one that arrived later."""
    first = FakePacket(port=1001)
    second = FakePacket(port=1002)
    stats, sent = _run([(0.40, first), (0.05, second)])

    check("the packet that arrived second was sent first",
          sent == [second, first], f"(sent {len(sent)} packets)")
    check("one reorder is counted", stats["reordered"] == 1,
          f"(reordered={stats['reordered']})")


def test_packets_that_keep_their_order_are_not_counted():
    """The other half, and the one that stops the counter being always-on.

    Without this, a counter that simply incremented per packet would pass the
    test above and be worthless.
    """
    first = FakePacket(port=1001)
    second = FakePacket(port=1002)
    stats, sent = _run([(0.05, first), (0.30, second)])

    check("the order was kept", sent == [first, second], f"(sent {len(sent)})")
    check("nothing is counted as reordered", stats["reordered"] == 0,
          f"(reordered={stats['reordered']})")


def test_the_two_directions_are_judged_separately():
    """A design decision, pinned: the high-water mark is PER DIRECTION.

    An inbound packet overtaking an outbound one is not a reorder anybody can
    observe - they are different conversations. With one shared mark this reads
    as a reorder, so the mistake would be invisible except as a counter that
    ticks up on ordinary two-way traffic.
    """
    outbound = FakePacket(port=1001, is_outbound=True)
    inbound = FakePacket(port=1002, is_outbound=False)
    stats, sent = _run([(0.40, outbound), (0.05, inbound)])

    check("the inbound packet went out first", sent == [inbound, outbound],
          f"(sent {len(sent)})")
    check("crossing directions is not a reorder", stats["reordered"] == 0,
          f"(reordered={stats['reordered']})")


def test_a_packet_the_driver_refused_does_not_make_the_next_one_look_overtaken():
    """Counted after send(), not before - and this is what makes the difference.

    The refused packet arrived LAST and was released FIRST. If the counter marked
    it as sent before the driver had taken it, the packet behind it would be
    judged against a packet that never reached the stack and reported as
    overtaken by it.
    """
    arrived_first = FakePacket(port=1001)
    arrived_second = FakePacket(port=1002)
    fake = RefusingDivert([], refuse=arrived_second)
    stats, sent = _run([(0.40, arrived_first), (0.05, arrived_second)], divert=fake)

    check("only the accepted packet was sent", sent == [arrived_first],
          f"(sent {len(sent)})")
    check("the refused packet was counted as a failed send",
          stats["drop_send"] == 1, f"(drop_send={stats['drop_send']})")
    check("nothing is reported as overtaken", stats["reordered"] == 0,
          f"(reordered={stats['reordered']})")


def test_a_restarted_session_does_not_inherit_the_previous_high_water_mark():
    """Second sessions start clean, or every early packet reads as overtaken.

    ``reset_stats`` zeroes the counter itself; the mark the counter is judged
    against has to go with it. Missing that, the numbering carries on across the
    restart while the mark stays high, so the next session reports reordering it
    never did.
    """
    engine = BeanEngine()

    first_run = FakeDivert([])
    engine.start("test", divert=first_run)
    now = time.monotonic()
    engine._enqueue(now + 0.40, FakePacket(port=1001))
    engine._enqueue(now + 0.05, FakePacket(port=1002))
    deadline = time.time() + 10
    while time.time() < deadline and len(first_run.sent) < 2:
        time.sleep(0.01)
    check("the first session did reorder", engine.stats_snapshot()["reordered"] == 1,
          f"(reordered={engine.stats_snapshot()['reordered']})")
    engine.stop()

    second_run = FakeDivert([])
    engine.start("test", divert=second_run)
    try:
        now = time.monotonic()
        engine._enqueue(now + 0.05, FakePacket(port=2001))
        engine._enqueue(now + 0.30, FakePacket(port=2002))
        deadline = time.time() + 10
        while time.time() < deadline and len(second_run.sent) < 2:
            time.sleep(0.01)
        time.sleep(0.05)
        stats = engine.stats_snapshot()
    finally:
        engine.stop()

    check("the second session sent two packets in order",
          len(second_run.sent) == 2, f"(sent {len(second_run.sent)})")
    check("the second session reports no reordering", stats["reordered"] == 0,
          f"(reordered={stats['reordered']})")
