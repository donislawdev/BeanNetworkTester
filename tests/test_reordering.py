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


class RefusingCopies(FakeDivert):
    """A diverter that takes each packet ONCE: the duplicate copy is refused."""

    def send(self, p, recalculate_checksum=True):
        if any(p is q for _, q in self.sent):
            raise OSError("the driver refused the copy")
        super().send(p, recalculate_checksum=recalculate_checksum)


def _run(releases, divert=None, engine=None, expect=None):
    """Queue ``(offset, packet)`` pairs in order, wait for delivery, return stats.

    ``releases`` is queued in list order, so the first entry is the packet that
    ARRIVED first - which is the whole variable these tests turn. A third item,
    ``True``, queues that entry as a duplicate COPY (pipeline step 12).
    """
    fake = divert if divert is not None else FakeDivert([])
    engine = engine if engine is not None else BeanEngine()
    engine.start("test", divert=fake)
    try:
        now = time.monotonic()
        for offset, packet, *copy in releases:
            engine._enqueue(now + offset, packet, copy=bool(copy and copy[0]))
        deadline = time.time() + 10
        while time.time() < deadline:
            s = engine.stats_snapshot()
            done = len(releases) if expect is None else expect
            if s["queue"] == 0 and len(fake.sent) + s["drop_send"] >= done:
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


def test_a_duplicate_copy_is_not_counted_as_overtaken():
    """External review, P3-7b: a copy leaves after its original, so the packet that
    arrived next usually goes out before it - and every copy read as a packet
    overtaken. Measured 877 "reordered" for 878 copies with duplication alone and
    no delay set. A late duplicate is not a reorder of anything."""
    first, second = FakePacket(port=1001), FakePacket(port=1002)
    stats, sent = _run([(0.05, first), (0.40, first, True), (0.10, second)])

    check("the copy left last", sent == [first, second, first], f"(sent {len(sent)})")
    check("a copy leaving late is not a reorder", stats["reordered"] == 0,
          f"(reordered={stats['reordered']})")


def test_a_copy_the_driver_refused_is_not_a_lost_packet():
    """External review, P3-7a and NOWE-2-4: the injector threw the copy flag away,
    so a refused COPY was counted in ``drop_send`` and charged to the row - twice
    the packets at 100% duplication (seen 200, drop_send 400) - and the warning
    fired for it, quoting that number. The application got the packet once, which
    is the packet."""
    engine = BeanEngine()
    warned = []
    engine._warn_send_failed = warned.append
    packet = FakePacket(port=1003)
    stats, sent = _run([(0.05, packet), (0.20, packet, True)],
                       divert=RefusingCopies([]), engine=engine, expect=1)

    check("the original was delivered", sent == [packet], f"(sent {len(sent)})")
    check("a refused copy is not a lost packet", stats["drop_send"] == 0,
          f"(drop_send={stats['drop_send']})")
    check("and nothing warns about a loss that did not happen", warned == [],
          f"(warned {warned})")


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
