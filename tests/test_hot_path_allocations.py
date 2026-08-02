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
Measured across configurations (2026-08-02, three runs each, gc collected then
disabled, values identical every time): the pass-through path costs **13 blocks and
608 bytes per 5000 calls** and does not move - not with 200 ports instead of 50, not
with the NAT flow table armed, not with latency. Duplication takes it to 15 blocks
and 656 bytes. Those are interpreter bookkeeping, not per-packet retention, so the
ceilings sit far above them and far below a real regression: one retained reference
per packet is 42 kB, one retained object is +5000 blocks.
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
    """(net blocks, net bytes) retained by ``count`` decisions, warmed and gc-quiet."""
    rng = random.Random(7)
    _decide_many(core, rng, 200)          # fill every lazy structure first
    gc.collect()
    gc.disable()
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


def test_the_armed_gates_do_not_retain_per_packet_either():
    """Impairment on is still not a licence to keep a copy of every packet.

    Duplication is the one gate that legitimately hands a second packet onward, so
    it is the honest worst case to point this at.
    """
    for label, arm in (("duplication", lambda c: setattr(c, "dup", 1.0)),
                       ("latency", lambda c: setattr(c, "latency_s", 0.05)),
                       ("nat flow table", lambda c: setattr(c, "nat_timeout_s", 30))):
        core = BeanCore()
        arm(core)
        blocks, retained = _cost_of(core)
        check(f"with {label} armed, decide() retains at most {BLOCK_CEILING} blocks",
              blocks <= BLOCK_CEILING, f"(retained {blocks} blocks)")
        check(f"with {label} armed, decide() retains at most {BYTE_CEILING} bytes",
              retained <= BYTE_CEILING, f"(retained {retained} bytes)")
