"""The decision path must not RETAIN anything per packet.

What this guards
----------------
"Zero allocations" has been written in the hot-path section of the notes for a long
time and nothing checked it. ``test_hot_path.py`` guards the neighbouring rule - no
syscalls on the packet threads - which is a different failure. This one catches the
class where ``decide()`` starts holding on to something once per packet: a cache
added for speed, a list that only ever grows, a per-flow object nobody frees. At the
measured real rate of ~14k packets a second that is tens of megabytes a minute, and
the symptom the user sees is not "slow" but a session that dies after an hour.

Two meters, because one of them has a hole
------------------------------------------
🔴 **Blocks alone are not enough, and this was found by mutation, not by thinking.**
The first version of this file counted ``sys.getallocatedblocks()`` only. A mutation
that made ``decide()`` append to an ever-growing list **SURVIVED it**: the appended
value was a small cached int, so no object was created and the list's array growth
cost about one block. Blocks see a retained NEW OBJECT; they are blind to a container
filling up with references to objects that already exist - which is the shape most
real leaks in this codebase would take.

So the gate reads both, and each covers the other's blind spot:

* ``sys.getallocatedblocks()`` - net objects retained. Measured for the mutation:
  7 against a baseline of 6, i.e. invisible.
* ``tracemalloc`` current (not peak) - bytes still held. Same mutation: **42 032
  against 208**, i.e. unmissable.

What it still does NOT catch, said out loud
-------------------------------------------
**Transient garbage.** Both meters are net, so an object allocated and freed inside
the same call nets to nothing - measured, not assumed. A future ``f"{a}:{b}"`` built
per packet would pass here. CPython has no cheap deterministic counter of total
allocations (Go's ``AllocsPerRun`` has no equivalent), and pretending otherwise would
be the guard that promises more than it measures. Churn stays a job for measurement
(rule 5), not for this gate.

Why the numbers are ceilings and not zero
-----------------------------------------
Measured across configurations (2026-10-02, CPython 3.14.7, three runs each, values
identical every time): **1-2 blocks and 64 bytes per 5000 calls**, the same with
duplication, latency, the NAT table, a destination target, a block, LAN mode,
Internet only and a throughput schedule armed. That is interpreter bookkeeping, not
per-packet retention, so the ceilings sit far above it and far below a real
regression: one retained reference per packet is 42 kB, one retained object is
+5000 blocks.

🔴 **The collection comes BEFORE the warm-up, and that order is load-bearing.** A
full collection also empties the interpreter's free lists, so a warm-up that ran
first left the measured window to refill them - and the refill read as retention.
MEASURED 2026-10-02 with the IP gates armed: 113-115 blocks and ~3.9 kB, CONSTANT for
1000, 5000 and 20 000 packets (the ints `ipaddress` makes while parsing), i.e. over
the block ceiling with nothing leaking at all. Collected first, the same runs read 1
block and 64 bytes, and the one-reference-per-packet canary still reads 42 kB.

🔴 **Every armed case proves it is armed before it is measured.** The first version
armed duplication and latency by assigning ``core.dup`` and ``core.latency_s``, and
from the day ``decide()`` began reading the per-direction values ``_recompute``
derives, those assignments armed nothing: two of the three cases measured plain
pass-through for months, green. Each case now arms through the setter the program
uses and shows one decision that only an armed gate gives.
"""
import gc
import random
import sys
import tracemalloc

from fakes import check

from beantester.core import BeanCore

CALLS = 5000
BLOCK_CEILING = 64      # measured floor 13, flat across configurations
BYTE_CEILING = 4096     # measured floor 608; a one-reference-per-packet leak is 42k


def _decide_many(core, rng, count):
    for i in range(count):
        core.decide(100, True, 5000 + (i % 50), i * 0.001, rng,
                    remote_ip="1.2.3.4", remote_port=443, is_tcp=True)


def _cost_of(core, count=CALLS):
    """(net blocks, net bytes) retained by ``count`` decisions, warmed and gc-quiet.

    Collected, THEN warmed: see the module docstring for what the other order
    measured instead.
    """
    rng = random.Random(7)
    gc.collect()
    gc.disable()
    _decide_many(core, rng, 200)          # fill every lazy structure first
    tracemalloc.start()
    try:
        blocks_before = sys.getallocatedblocks()
        bytes_before = tracemalloc.get_traced_memory()[0]
        _decide_many(core, rng, count)
        return (sys.getallocatedblocks() - blocks_before,
                tracemalloc.get_traced_memory()[0] - bytes_before)
    finally:
        tracemalloc.stop()
        gc.enable()


def test_the_meter_can_actually_see_retention():
    """Prove the instrument before believing a zero from it.

    A gate whose measurement is stuck at zero passes forever and reads exactly like
    a clean hot path. This is the same reason the mutation runner carries a canary:
    an instrument that cannot report failure is not evidence. Retaining 5000 objects
    must show up as thousands of blocks.
    """
    if not hasattr(sys, "getallocatedblocks"):        # non-CPython: say so, loudly
        raise AssertionError("this interpreter has no getallocatedblocks; the hot "
                             "path allocation gate cannot run and must not be "
                             "reported as passing")
    gc.collect()
    gc.disable()
    tracemalloc.start()
    try:
        blocks_before = sys.getallocatedblocks()
        bytes_before = tracemalloc.get_traced_memory()[0]
        kept = [object() for _ in range(5000)]
        blocks = sys.getallocatedblocks() - blocks_before
        # The case that defeated the block meter: a container filling with
        # references to an object that ALREADY exists. No object is created, so
        # blocks barely move - only the bytes do.
        references = []
        bytes_before_refs = tracemalloc.get_traced_memory()[0]
        blocks_before_refs = sys.getallocatedblocks()
        for _ in range(5000):
            references.append(100)          # a cached small int: nothing new is made
        ref_blocks = sys.getallocatedblocks() - blocks_before_refs
        ref_bytes = tracemalloc.get_traced_memory()[0] - bytes_before_refs
        retained = tracemalloc.get_traced_memory()[0] - bytes_before
    finally:
        tracemalloc.stop()
        gc.enable()

    check("the block meter reports thousands when 5000 objects are retained "
          "(a meter stuck at zero would pass the gate below forever)",
          blocks >= 4000, f"(saw {blocks} for {len(kept)} objects)")
    check("the byte meter reports thousands when 5000 objects are retained",
          retained >= 4000, f"(saw {retained} bytes)")
    check("the byte meter catches a container of REFERENCES, which the block meter "
          "cannot see - this is the hole a surviving mutant exposed on 2026-08-02",
          ref_bytes >= 4000 and ref_blocks < 100,
          f"(refs: {ref_blocks} blocks, {ref_bytes} bytes)")


def test_the_decision_path_retains_nothing_per_packet():
    """A default engine judging 5000 packets holds on to nothing.

    Pass-through is the configuration the tool spends most of its life in and the
    one "collect, do not damage" promises is free (see test_passthrough.py).
    """
    blocks, retained = _cost_of(BeanCore())
    check(f"decide() retains at most {BLOCK_CEILING} blocks over {CALLS} packets "
          f"(one retained object per packet would be {CALLS})",
          blocks <= BLOCK_CEILING, f"(retained {blocks} blocks)")
    check(f"decide() retains at most {BYTE_CEILING} bytes over {CALLS} packets "
          f"(a container growing by one reference per packet is about 42 kB, and "
          f"the block count above cannot see it)",
          retained <= BYTE_CEILING, f"(retained {retained} bytes)")


def _one(core, remote_ip="1.2.3.4", remote_port=443, is_out=True, now=1.0):
    """One decision shaped like the measured ones, for proving a gate is armed."""
    return core.decide(100, is_out, 5000, now, random.Random(7),
                       remote_ip=remote_ip, remote_port=remote_port, is_tcp=True)


def _nat_expires(core):
    _one(core, now=1.0)                                  # outbound opens the mapping
    return _one(core, is_out=False, now=40.0).reason == "nat"


# label, how the program arms it, and one decision only the ARMED gate gives
ARMED_GATES = (
    ("duplication", lambda c: c.set_params(0, 0, 100, 0, 0, 0, 0),
     lambda c: len(_one(c).releases) == 2),
    ("latency", lambda c: c.set_params(0, 0, 0, 50, 0, 0, 0),
     lambda c: _one(c).releases[0] > 1.04),
    ("nat flow table", lambda c: c.set_nat(30), _nat_expires),
    ("destination target", lambda c: c.set_dest(True, "1.2.3.0/24, 2001:db8::/32", "443"),
     lambda c: _one(c).scoped and not _one(c, remote_ip="5.6.7.8").scoped),
    ("block", lambda c: c.set_block(True, "203.0.113.0/24", "25"),
     lambda c: _one(c, remote_ip="203.0.113.9").reason == "block" and not _one(c).drop),
    ("LAN mode", lambda c: c.set_lan(True), lambda c: _one(c).reason == "lan"),
    ("Internet only", lambda c: c.set_internet_only(True),
     lambda c: _one(c, remote_ip="192.168.1.10").reason == "internet_only"),
    ("throughput schedule",
     lambda c: (c.set_schedule([(1.0, 100, 100), (1.0, 200, 200)]), c.set_buffer(150)),
     lambda c: _one(c).releases[0] > 1.0),
)


def test_the_armed_gates_do_not_retain_per_packet_either():
    """Impairment on is still not a licence to keep a copy of every packet.

    Duplication is the one gate that legitimately hands a second packet onward, so
    it is the honest worst case to point this at. The address gates are here because
    they are where a cache "for speed" would live (performance review 2026-09-26,
    W-A2): a bounded one passes, one that keeps a value per packet does not.
    """
    for label, arm, armed in ARMED_GATES:
        proof = BeanCore()
        arm(proof)
        check(f"the {label} case really arms {label} (a disarmed case measures "
              f"plain pass-through and passes for that reason)", armed(proof))
        core = BeanCore()
        arm(core)
        blocks, retained = _cost_of(core)
        check(f"with {label} armed, decide() retains at most {BLOCK_CEILING} blocks",
              blocks <= BLOCK_CEILING, f"(retained {blocks} blocks)")
        check(f"with {label} armed, decide() retains at most {BYTE_CEILING} bytes",
              retained <= BYTE_CEILING, f"(retained {retained} bytes)")
