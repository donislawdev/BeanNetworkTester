"""Who recomputes a packet's checksums, and who must not.

The rule is one sentence - recompute only when this tool edited the bytes - and
all three of its cases were unguarded before this file existed.

Why it matters in both directions:

* Recomputing an UNTOUCHED packet is not free and not neutral. WinDivert hands
  over the packet together with its checksum-valid flags, and outbound traffic
  routinely arrives carrying a PSEUDO checksum for the hardware to finish
  (measured on this machine: ``udp_checksum`` was 0 on 120 of 120 packets, over
  loopback and a real interface alike). Recomputing turned "pass the traffic
  through unchanged" into "pass it through with different bytes", and cost a
  measured 1.122x of throughput (8 of 8 paired windows in one session).
* NOT recomputing an edited one is a silent hole: the receiving stack discards
  the segment, so corruption would stop arriving at all and the tool would report
  it as delivered.
* An injected RST was never captured - it is built here - so nothing has ever
  computed its checksums and no offload flag applies. Sending it as-is produces a
  segment the stack drops, which looks like "RST does not reset anything" rather
  than like a checksum bug.
"""
import time

from beantester.engine import BeanEngine
from fakes import FakeDivert, FakePacket, check


def _run(packets, settings=None, expect=None, wait=1.5):
    """Drive the engine over `packets` and return the divert once `expect` sends
    have happened. `expect` is separate from len(packets) on purpose: with
    duplication one packet produces TWO sends, and a wait that stops at
    len(packets) would read the first one and call the test done."""
    eng = BeanEngine()
    eng.set_seed(7)
    if settings:
        eng.set_params(*settings)
    div = FakeDivert(packets)
    eng.start("test", divert=div)
    deadline = time.monotonic() + wait
    want = len(packets) if expect is None else expect
    while time.monotonic() < deadline and len(div.sent) < want:
        time.sleep(0.005)
    time.sleep(0.05)                     # let a stray extra send land, if any
    eng.stop()
    return div


def test_an_untouched_packet_is_re_injected_without_recomputing_its_checksums():
    """The default session promises byte-for-byte passthrough; recomputing broke
    that promise quietly, because the bytes that go out are then not the bytes
    that came in."""
    div = _run([FakePacket(size=120, port=4000) for _ in range(4)])
    check("every untouched packet went out", len(div.sent) == 4, f"({len(div.sent)})")
    check("and none of them was recomputed",
          div.recalc == [False] * 4, f"({div.recalc})")


def test_a_corrupted_packet_IS_recomputed():
    """Corruption edits the payload, so the checksum in the packet is now wrong.
    Left alone, the receiver drops the segment and the corruption never arrives -
    the tool would count damage it did not deliver."""
    div = _run([FakePacket(size=120, port=4100, payload=b"abcdefgh")
                for _ in range(4)],
               settings=(0, 100, 0, 0, 0, 0, 0))          # corrupt 100%
    check("the corrupted packets went out", len(div.sent) == 4, f"({len(div.sent)})")
    check("and every one of them was recomputed",
          div.recalc == [True] * 4, f"({div.recalc})")


def test_a_duplicate_of_a_corrupted_packet_is_recomputed_too():
    """Duplication (pipeline step 12) queues the SAME packet object a second time.
    The copy carries the same edited bytes, so it needs the same answer - and it
    is a separate call, on a separate queue entry, which is exactly where a flag
    carried per-entry can drift from the packet it describes."""
    div = _run([FakePacket(size=120, port=4200, payload=b"abcdefgh")],
               settings=(0, 100, 100, 0, 0, 0, 0),        # corrupt 100%, duplicate 100%
               expect=2)
    check("the packet and its duplicate both went out",
          len(div.sent) == 2, f"({len(div.sent)})")
    check("both were recomputed", div.recalc == [True, True], f"({div.recalc})")


# The RST half of the rule lives in tests/test_rst_local.py
# (test_an_injected_rst_is_always_recomputed), next to the fixture that can build
# a real TCP packet and a synthetic RST for it - a FakePacket has no TCP layer,
# so a "reset" test written here would pass without ever building one.
