"""Property-based tests for the decision pipeline (``beantester/core.py``).

The example tests in ``test_core.py`` pin one step each: this one is 100% loss,
that one an expired NAT mapping, the next an oversized packet. They cover the
cases somebody thought of. But ``decide()`` is a TWELVE-step pipeline over
twenty-odd interacting fields, and what no example test reaches is the
INTERACTION - what a step does while five other steps are armed, in a
configuration nobody wrote down.

Why this function and not another:

* ``decide()`` runs on the CAPTURE THREAD, once per packet, up to 150 000 times a
  second, holding ``core._lock``. An exception there kills the capture thread
  while the divert handle stays open, and WinDivert then queues the user's
  packets into a void: the machine loses connectivity while the UI still says
  "running". That is the exact failure FAIL-OPEN exists to prevent (convention 20).
* Everything downstream consumes its output. The engine injects from
  ``releases``, the statistics split drops by ``reason``, the connections view
  colours rows by ``scoped``. An incoherent ``Decision`` is a lost or doubled
  packet, or a damage counter attributed to the wrong mechanism.

**These are a regression net, not a bug hunt.** At the time of writing the
pipeline survived every attempt to falsify the properties below: 3000 Hypothesis
examples across the full settings space and 300-seed sweeps per gate found
nothing. They are here because the pipeline GROWS - step 2c (blocking) was added
after the pipeline was first documented - and a step inserted at the wrong
position is invisible to example tests that each arm a single knob.

One trap for whoever extends this file: ``set_schedule()`` reads
``time.monotonic()`` directly, so a core carrying a schedule is only
deterministic once ``reset_buckets(t)`` has run after it. Production always does
(``BeanEngine.start``), and so does ``_core()`` below. A property test that skips
it will flake, rarely, on the schedule position.
"""
import random

from hypothesis import given, settings
from hypothesis import strategies as st

from beantester.core import BeanCore
from fakes import check

# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
pct = st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False)
ms = st.floats(min_value=0, max_value=5000, allow_nan=False, allow_infinity=False)
kbps = st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False)

# Filter expressions are SAMPLED, not generated: the mini-language has its own
# property suite (test_matchers_properties.py). Here they only need to be real
# enough to switch the targeting gates on.
ip_exprs = st.sampled_from(["", "8.8.8.8", "10.0.0.0/8", "!8.8.8.8",
                            "1.2.3.4, 5.6.7.8", "2001:db8::/32"])
port_exprs = st.sampled_from(["", "443", "80,443", "8000-8100", ">1024", "!53"])

impairments = st.fixed_dictionaries({
    "loss": pct, "corrupt": pct, "dup": pct,
    "latency_ms": ms, "jitter_ms": ms,
    "down": kbps, "up": kbps,
    "buffer_ms": st.floats(min_value=0, max_value=10_000,
                           allow_nan=False, allow_infinity=False),
    "syn_drop": pct,
    "max_size": st.integers(min_value=0, max_value=70_000),
    "spike_prob": pct, "spike_ms": ms,
    "nat_timeout": st.floats(min_value=0, max_value=100,
                             allow_nan=False, allow_infinity=False),
    "rst_prob": pct,
    "rst_cooldown": st.floats(min_value=0, max_value=30,
                              allow_nan=False, allow_infinity=False),
    # flap_enabled is generated INDEPENDENTLY of the period on purpose. Production
    # ties them together (``apply_settings`` passes ``flap_period > 0`` as the
    # flag), so a core that is "flapping with a zero period" only ever arrives
    # through the setter - and that is precisely the combination that used to
    # divide by zero.
    "flap_enabled": st.booleans(),
    "flap_period": st.floats(min_value=0, max_value=60,
                             allow_nan=False, allow_infinity=False),
    "flap_down": pct,
    "lan": st.booleans(),
    "target_ports": st.one_of(st.none(),
                              st.sets(st.integers(0, 65535), max_size=4)),
    "dst_ip": ip_exprs, "dst_port": port_exprs,
    "block_ip": ip_exprs, "block_port": port_exprs,
    "schedule": st.lists(
        st.tuples(st.floats(min_value=0, max_value=10,
                            allow_nan=False, allow_infinity=False), kbps, kbps),
        max_size=4),
})

packets = st.fixed_dictionaries({
    "size": st.integers(min_value=0, max_value=70_000),
    "is_outbound": st.booleans(),
    "local_port": st.one_of(st.none(), st.integers(min_value=0, max_value=65535)),
    "now": st.floats(min_value=0.0, max_value=1e6,
                     allow_nan=False, allow_infinity=False),
    "remote_ip": st.one_of(st.none(), st.ip_addresses().map(str)),
    "remote_port": st.one_of(st.none(), st.integers(min_value=0, max_value=65535)),
    "is_syn": st.booleans(),
    "is_tcp": st.booleans(),
})

SLOW = settings(max_examples=300, deadline=None)
BURST = settings(max_examples=100, deadline=None)


def _core(s):
    """A core configured through the same setters the engine uses."""
    core = BeanCore()
    core.set_params(s["loss"], s["corrupt"], s["dup"], s["latency_ms"],
                    s["jitter_ms"], s["down"], s["up"])
    core.set_buffer(s["buffer_ms"])
    core.set_advanced(s["syn_drop"], s["max_size"])
    core.set_spike(s["spike_prob"], s["spike_ms"])
    core.set_nat(s["nat_timeout"])
    core.set_rst(s["rst_prob"], s["rst_cooldown"])
    core.set_flap(s["flap_enabled"], s["flap_period"], s["flap_down"])
    core.set_lan(s["lan"])
    core.set_target(s["target_ports"] is not None, s["target_ports"])
    core.set_dest(bool(s["dst_ip"] or s["dst_port"]), s["dst_ip"], s["dst_port"])
    core.set_block(bool(s["block_ip"] or s["block_port"]),
                   s["block_ip"], s["block_port"])
    core.set_schedule(s["schedule"])
    core.reset_buckets(0.0)         # also pins the schedule phase - see the docstring
    return core


def _decide(core, pkt, rng):
    return core.decide(pkt["size"], pkt["is_outbound"], pkt["local_port"],
                       pkt["now"], rng, remote_ip=pkt["remote_ip"],
                       remote_port=pkt["remote_port"], is_syn=pkt["is_syn"],
                       is_tcp=pkt["is_tcp"])


# --------------------------------------------------------------------------- #
# P1: decide() is TOTAL - it never raises, whatever it is handed
# --------------------------------------------------------------------------- #
@SLOW
@given(s=impairments, pkts=st.lists(packets, min_size=1, max_size=6))
def test_decide_never_raises(s, pkts):
    """An exception here kills the capture thread with the divert still open.

    The user then loses connectivity while the UI reports "running" - the failure
    the whole fail-open design exists to prevent. Every field is exercised at once
    because that is the state a real session is in.
    """
    core = _core(s)
    rng = random.Random(0)
    for pkt in pkts:
        try:
            _decide(core, pkt, rng)
        except Exception as exc:                     # pragma: no cover - the bug
            raise AssertionError(
                f"decide() raised {type(exc).__name__}: {exc}\n"
                f"  packet={pkt}\n"
                f"  settings={s}") from exc


# --------------------------------------------------------------------------- #
# P2: the Decision is structurally coherent
# --------------------------------------------------------------------------- #
def _incoherence(d, now):
    """Name the way this Decision contradicts itself, or None if it does not."""
    if d.drop and d.releases:
        return "dropped, yet carries release times"
    if not d.drop and not d.releases:
        return "not dropped, yet has nothing to release"
    if d.drop and d.corrupt:
        return "dropped AND corrupted"
    if len(d.releases) > 2:
        return f"{len(d.releases)} copies (at most the original + one duplicate)"
    if any(r < now - 1e-9 for r in d.releases):
        return "released before it arrived"
    if len(d.releases) == 2 and d.releases[1] < d.releases[0]:
        return "the duplicate precedes the original"
    if d.emit_rst and not d.drop:
        return "asks for an RST without dropping the packet"
    return None


@SLOW
@given(s=impairments, pkts=st.lists(packets, min_size=1, max_size=6))
def test_every_decision_is_structurally_coherent(s, pkts):
    """The engine acts on these fields directly, so they must never contradict.

    ``drop`` and ``releases`` are the same statement made twice: the engine
    injects one packet per release time and none at all for a drop. A Decision
    that is both is a packet vanishing or being sent twice.
    """
    core = _core(s)
    rng = random.Random(0)
    for pkt in pkts:
        d = _decide(core, pkt, rng)
        why = _incoherence(d, pkt["now"])
        check("decision is coherent", why is None,
              f"({why}: {d}, packet={pkt}, settings={s})")


# --------------------------------------------------------------------------- #
# P3: pipeline ORDER is a contract - an armed gate beats every later step
# --------------------------------------------------------------------------- #
# The deterministic gates, in pipeline order. Each entry arms EXACTLY its own
# gate on an otherwise maximally noisy core, so whatever comes out names the
# step that fired. If a step is ever moved, inserted or made conditional, the
# reason changes and this goes red.
GATES = ["lan", "block", "nat", "rst", "flap", "mtu", "syn"]

# Impairments that must NOT be able to preempt a gate. All of them sit at step 7
# or later, so at 100% they are the strongest possible competition.
NOISE = dict(loss=100, corrupt=100, dup=100, latency_ms=1000, jitter_ms=500,
             down=1, up=1)


def _armed(gate, rst_cooldown, flap_period):
    """A core with maximum noise and exactly one deterministic gate armed."""
    core = BeanCore()
    core.set_params(NOISE["loss"], NOISE["corrupt"], NOISE["dup"],
                    NOISE["latency_ms"], NOISE["jitter_ms"],
                    NOISE["down"], NOISE["up"])
    core.set_buffer(50)
    core.set_spike(100, 2000)
    core.reset_buckets(0.0)
    if gate == "lan":
        core.set_lan(True)
    elif gate == "block":
        core.set_block(True, port="443")
    elif gate == "nat":
        core.set_nat(0.5)
    elif gate == "rst":
        core.set_rst(100, rst_cooldown)
    elif gate == "flap":
        core.set_flap(True, flap_period, 100)        # down for the whole period
    elif gate == "mtu":
        core.set_advanced(0, 10)                     # everything is oversized
    elif gate == "syn":
        core.set_advanced(100, 0)
    return core


@SLOW
@given(gate=st.sampled_from(GATES), seed=st.integers(0, 2**32 - 1),
       size=st.integers(min_value=1000, max_value=65535),
       rst_cooldown=st.floats(min_value=0.5, max_value=30,
                              allow_nan=False, allow_infinity=False),
       flap_period=st.floats(min_value=0.1, max_value=60,
                             allow_nan=False, allow_infinity=False))
def test_an_armed_gate_wins_over_every_later_step(gate, seed, size,
                                                  rst_cooldown, flap_period):
    """Whichever gate is armed names the drop, no matter how loud the rest is.

    This is the pipeline order stated as a testable claim. The order is part of
    the documented contract (see the ``core`` module docstring), and it is what
    decides which counter a drop lands in: a link outage reported as packet loss
    made the session panel's effective-loss figure wrong once already.
    """
    core = _armed(gate, rst_cooldown, flap_period)
    rng = random.Random(seed)
    kw = dict(remote_ip="8.8.8.8", remote_port=443, is_tcp=True, is_syn=True)
    now = 0.0
    if gate == "nat":
        core.decide(100, True, 5000, 0.0, rng, **kw)     # create the mapping...
        now = 5.0                                        # ...then let it expire
    d = core.decide(size, False, 5000, now, rng, **kw)
    check(f"{gate} gate decides the packet", d.drop and d.reason == gate,
          f"(drop={d.drop}, reason={d.reason}, expected {gate!r})")


@SLOW
@given(seed=st.integers(0, 2**32 - 1))
def test_an_earlier_gate_beats_a_later_one(seed):
    """Two gates armed at once: the earlier step in the pipeline must win."""
    core = BeanCore()
    core.set_lan(True)                  # step 2b
    core.set_advanced(0, 10)            # step 6 - would also drop this packet
    d = core.decide(9000, False, 5000, 0.0, random.Random(seed),
                    remote_ip="8.8.8.8", remote_port=443, is_tcp=True)
    check("LAN mode (2b) wins over the MTU black hole (6)",
          d.drop and d.reason == "lan", f"(reason={d.reason})")


# --------------------------------------------------------------------------- #
# P4: an unnamed drop is the signature of packet loss, and of nothing else
# --------------------------------------------------------------------------- #
@SLOW
@given(s=impairments, pkts=st.lists(packets, min_size=1, max_size=6))
def test_with_loss_off_every_drop_names_its_cause(s, pkts):
    """``reason=None`` is how step 8 (loss) identifies itself to the engine.

    The engine reads it to pick the counter (``drop_loss`` versus ``drop_flap``,
    ``drop_lan``, ``drop_rate``...), and ``test_passthrough`` asserts on those
    counters by name. If any other step ever returned an unnamed drop, its damage
    would be reported as packet loss and the pass-through guarantee would still
    look green.
    """
    s = dict(s, loss=0)
    core = _core(s)
    rng = random.Random(0)
    for pkt in pkts:
        d = _decide(core, pkt, rng)
        check("with loss off, a drop always names its cause",
              not (d.drop and d.reason is None),
              f"(unnamed drop: {d}, packet={pkt}, settings={s})")


@SLOW
@given(pkt=packets, seed=st.integers(0, 2**32 - 1))
def test_loss_is_the_step_that_drops_without_a_reason(pkt, seed):
    """The converse of the property above: loss really does drop unnamed."""
    core = BeanCore()
    core.set_params(100, 0, 0, 0, 0, 0, 0)      # nothing armed except 100% loss
    core.reset_buckets(0.0)
    d = _decide(core, pkt, random.Random(seed))
    check("100% loss drops without a reason", d.drop and d.reason is None,
          f"({d})")


# --------------------------------------------------------------------------- #
# P5: out of targeting scope means untouched - and leaves no trace behind
# --------------------------------------------------------------------------- #
@SLOW
@given(s=impairments, pkt=packets, seed=st.integers(0, 2**32 - 1))
def test_an_out_of_scope_packet_is_untouched_and_changes_no_state(s, pkt, seed):
    """Targeting narrows traffic to one application; everything else is only
    OBSERVED. Observation must not cost the observed flow anything, and it must
    not cost the TARGETED flow anything either.

    The second half is the part no example test covers: if an off-target packet
    charged the token bucket or wrote a flow entry, then merely watching a busy
    machine would eat the shaped link of the application under test, and the
    measurement would be wrong in a way nobody could see.
    """
    core = _core(s)
    # Point the core at a port this packet cannot have.
    off_target = 1 if pkt["local_port"] != 1 else 2
    core.set_target(True, {off_target})
    core.set_dest(False)
    before_bucket = dict(core._bucket)
    before_flows = (len(core._flow_last), len(core._reset_until))

    d = _decide(core, pkt, random.Random(seed))

    untouched = (d.scoped is False and d.drop is False and d.corrupt is False
                 and d.reason is None and d.emit_rst is False
                 and d.releases == [pkt["now"]])
    check("an out-of-scope packet passes untouched", untouched, f"({d})")
    check("an out-of-scope packet does not charge the link buffer",
          dict(core._bucket) == before_bucket,
          f"(before={before_bucket}, after={dict(core._bucket)})")
    check("an out-of-scope packet leaves no flow state behind",
          (len(core._flow_last), len(core._reset_until)) == before_flows,
          f"(before={before_flows}, "
          f"after={(len(core._flow_last), len(core._reset_until))})")


# --------------------------------------------------------------------------- #
# P6: a bounded buffer bounds the queueing delay
# --------------------------------------------------------------------------- #
@BURST
@given(rate_kbps=st.floats(min_value=1, max_value=5000,
                           allow_nan=False, allow_infinity=False),
       buffer_ms=st.floats(min_value=1, max_value=5000,
                           allow_nan=False, allow_infinity=False),
       size=st.integers(min_value=1, max_value=65535),
       count=st.integers(min_value=20, max_value=200),
       is_outbound=st.booleans())
def test_a_bounded_buffer_bounds_the_added_delay(rate_kbps, buffer_ms, size,
                                                 count, is_outbound):
    """Offer far more than the link can carry and no delivered packet may be
    scheduled further out than the buffer allows.

    The bound is ``max(buffer_s, size / rate)``, NOT ``buffer_s``: a packet
    arriving into an EMPTY buffer is always accepted, even when its own
    serialisation takes longer than the whole buffer. That is deliberate - it is
    what keeps a tiny buffer from blacking the link out completely
    (``test_bandwidth_buffer.test_empty_buffer_never_blacks_out_the_link``) - and
    stating the bound as plain ``buffer_s`` would make this test red against
    correct code.

    ``test_bandwidth_buffer`` pins this for one rate and one packet size; here it
    holds across the space.
    """
    core = BeanCore()
    down = 0 if is_outbound else rate_kbps
    up = rate_kbps if is_outbound else 0
    core.set_params(0, 0, 0, 0, 0, down, up)      # no latency: the delay IS the queue
    core.set_buffer(buffer_ms)
    core.reset_buckets(0.0)
    rng = random.Random(0)

    rate_bps = core.rate_up if is_outbound else core.rate_down
    bound = max(buffer_ms / 1000.0, size / rate_bps) + 1e-6
    interval = size / rate_bps / 8.0              # offer ~8x what the link carries

    worst = 0.0
    for i in range(count):
        now = i * interval
        d = core.decide(size, is_outbound, 1000, now, rng,
                        remote_ip="8.8.8.8", remote_port=443)
        if d.drop:
            check("an over-offered capped link only ever drops for 'rate'",
                  d.reason == "rate", f"(reason={d.reason})")
            continue
        worst = max(worst, d.releases[0] - now)
    check("queueing delay stays within the buffer", worst <= bound,
          f"(worst={worst:.6f}s, bound={bound:.6f}s, "
          f"rate={rate_bps} B/s, size={size} B, buffer={buffer_ms:.1f} ms)")
