"""Loss that arrives in RUNS, not one packet at a time: the two-state chain.

Real links do not lose packets one at a time. A microwave oven, a lift, a
handover between transmitters - each takes the link away for a stretch, and 5%
of loss spread evenly is something TCP shrugs off while 5% arriving in three
runs of twenty collapses the window and drives the reconnect path, which is the
code a tester actually wants to exercise. ``beantester.core.burst_loss_params``
turns "this much loss, in runs this long" into the transition probabilities of
Gilbert's two-state channel, and ``BeanCore._loses`` walks it.

What these tests are here to hold down, in the order it would hurt to lose it:

* **the default is byte for byte what it was.** With no run length set, step 8
  makes the same single draw it always made, in the same place in the RNG
  sequence - otherwise every stored ``Reproduce:`` command would replay into a
  different session.
* **the numbers mean what they say.** The delivered loss lands on the field that
  asked for it, and a run is as long as the field that asked for it - including
  under two-way traffic, which is where a single shared chain would silently
  deliver half.
* **the impossible corner is loud, not quiet.** Some loss/length pairs cannot
  exist. They are clamped, and ``achievable`` reports what the pair really does.
* **the chain is re-derived from BOTH of its inputs.** ``p`` depends on the loss
  as well as the run length, so changing only the loss has to move it.
"""
import random

from fakes import check

from beantester.core import BeanCore, burst_loss_params

PACKETS = 200000


def _core(loss=0.0, burst=0.0):
    core = BeanCore()
    core.set_params(loss, 0, 0, 0, 0, 0, 0)
    core.set_loss_burst(burst)
    core.reset_buckets(0.0)
    return core


def _drops(core, packets=PACKETS, seed=7, alternate=False):
    """Run packets through decide(); return (dropped, {direction: [run lengths]}).

    ``alternate`` sends every other packet the other way, which is what the
    default two-way traffic filter hands the engine.
    """
    rng = random.Random(seed)
    runs = {True: [], False: []}
    current = {True: 0, False: 0}
    dropped = 0
    for i in range(packets):
        outbound = bool(i % 2) if alternate else True
        decision = core.decide(1200, outbound, 5000, i * 0.001, rng,
                               remote_ip="1.2.3.4", remote_port=443, is_tcp=True)
        if decision.drop:
            dropped += 1
            current[outbound] += 1
        elif current[outbound]:
            runs[outbound].append(current[outbound])
            current[outbound] = 0
    for direction, length in current.items():
        if length:
            runs[direction].append(length)
    return dropped, runs


def _mean(values):
    return sum(values) / len(values) if values else 0.0


# --------------------------------------------------------------------------- #
# The arithmetic, on its own - it is a pure function and it is where the model
# lives, so it is worth pinning without an engine anywhere near it.
# --------------------------------------------------------------------------- #
def test_no_run_length_means_the_independent_draw():
    for loss, burst in ((0.05, 0.0), (0.05, 1.0), (0.05, 0.5), (0.0, 20.0)):
        check(f"loss={loss} burst={burst} stays independent",
              burst_loss_params(loss, burst) is None,
              f"(got {burst_loss_params(loss, burst)})")


def test_the_transition_probabilities_follow_the_two_fields():
    p, r, achievable = burst_loss_params(0.05, 20.0)
    check("r is one over the mean run length", abs(r - 0.05) < 1e-12, f"(r={r})")
    # p = loss * r / (1 - loss) = 0.05 * 0.05 / 0.95
    check("p is derived from the loss and r", abs(p - (0.05 * 0.05 / 0.95)) < 1e-12,
          f"(p={p})")
    check("an achievable pair delivers exactly what was asked",
          achievable == 0.05, f"(achievable={achievable})")


def test_a_pair_that_cannot_exist_is_clamped_and_says_so():
    """90% loss cannot arrive in runs of five - there is no room between them."""
    p, r, achievable = burst_loss_params(0.9, 5.0)
    check("the good state is squeezed to a single packet", p == 1.0, f"(p={p})")
    # the most a run length of 5 can carry is (1/r) / (1/r + 1) = 1 / (1 + r)
    check("achievable reports the most that run length can carry",
          abs(achievable - 1.0 / 1.2) < 1e-12, f"(achievable={achievable})")
    check("and it is BELOW what was asked for", achievable < 0.9,
          f"(achievable={achievable})")


def test_total_loss_does_not_divide_by_zero():
    """``1 - loss`` is the denominator, so 100% is the input that would raise."""
    p, r, achievable = burst_loss_params(1.0, 5.0)
    check("total loss keeps the chain in the bad state", p == 1.0, f"(p={p})")
    check("and reports total loss", achievable == 1.0, f"(achievable={achievable})")
    check("r is still the run length", abs(r - 0.2) < 1e-12, f"(r={r})")


# --------------------------------------------------------------------------- #
# The packet path
# --------------------------------------------------------------------------- #
def test_the_default_path_is_the_draw_it_has_always_been():
    """A core that never heard of run lengths and one told 0 must agree exactly.

    Not "roughly": the same seed has to produce the same decision at the same
    index, because a stored reproduction command replays a session by seed and
    the number of draws step 8 makes is part of that sequence.
    """
    untouched = BeanCore()
    untouched.set_params(10, 0, 0, 0, 0, 0, 0)
    untouched.reset_buckets(0.0)
    told_zero = _core(loss=10, burst=0)

    a, _ = _drops(untouched, packets=20000)
    b, _ = _drops(told_zero, packets=20000)
    check("the same seed drops the same packets with and without the feature",
          a == b, f"(untouched={a}, told zero={b})")
    check("and it really was dropping something", a > 0, f"(dropped={a})")


def test_no_loss_means_the_chain_is_never_consulted():
    """Step 8's left half short-circuits, so a run length alone damages nothing.

    This is also why the pass-through path pays nothing for this feature: with
    no loss configured ``_loses`` is not called at all.
    """
    core = _core(loss=0, burst=20)
    dropped, _ = _drops(core, packets=20000)
    check("a run length with no loss drops nothing", dropped == 0,
          f"(dropped={dropped})")


def test_the_delivered_loss_matches_the_field_that_asked_for_it():
    """The tolerances here are MEASURED, and this comment is where they come from.

    Burst loss is far noisier per packet than independent loss, because the unit
    of randomness is the RUN, not the packet: 200 000 packets at 5% in runs of 20
    contain only about 500 runs. Measured over twelve seeds at this size the
    delivered loss spread 4.715% to 5.843% (sd 0.29) and the mean run length
    18.71 to 22.06 (sd 0.78). Pushed to 2 million packets the mean converges on
    the model - 4.9765% against a stationary 5.0000% - so the spread is the
    sample, not a bias.

    The seeds are fixed, so nothing here can flake: a tolerance is only wide
    enough that the test pins the RULE instead of one sample, and tight enough
    that a fifth of the loss going missing still turns it red.
    """
    delivered = []
    for seed in (7, 11, 23):
        dropped, runs = _drops(_core(loss=5, burst=20), seed=seed)
        share = 100.0 * dropped / PACKETS
        delivered.append(share)
        check(f"seed {seed}: 5% asked for in runs of 20 delivers about 5%",
              abs(share - 5.0) <= 1.2, f"(delivered {share:.3f}%)")
        check(f"seed {seed}: the runs are about as long as the field asked",
              abs(_mean(runs[True]) - 20.0) <= 3.0,
              f"(mean run {_mean(runs[True]):.2f})")
    check("and across seeds the average lands on the number that was asked for",
          abs(_mean(delivered) - 5.0) <= 0.8,
          f"(mean of {[f'{x:.3f}' for x in delivered]})")


def test_the_losses_actually_arrive_in_runs():
    """The whole point: consecutive drops, not the same total sprinkled evenly.

    Compared against the independent draw at the SAME loss rate, which is the
    honest control - a run length of 20 has to move the shape, not just the
    total.
    """
    bursty, _ = _drops(_core(loss=5, burst=20), packets=50000)
    _, even_runs = _drops(_core(loss=5, burst=0), packets=50000)
    _, bursty_runs = _drops(_core(loss=5, burst=20), packets=50000)
    check("independent loss almost never repeats",
          _mean(even_runs[True]) < 1.2, f"(mean run {_mean(even_runs[True]):.2f})")
    check("burst loss does, by more than an order of magnitude",
          _mean(bursty_runs[True]) > 10 * _mean(even_runs[True]),
          f"(bursty {_mean(bursty_runs[True]):.2f} vs even "
          f"{_mean(even_runs[True]):.2f})")
    check("and the longest run is long enough to matter to a TCP window",
          max(bursty_runs[True]) >= 20, f"(longest {max(bursty_runs[True])})")
    check("while the total is still what was asked", abs(bursty / 50000 - 0.05) < 0.01,
          f"(delivered {100.0 * bursty / 50000:.2f}%)")


def test_each_direction_gets_a_run_of_the_length_that_was_asked_for():
    """One chain per direction, and this is the test that says why.

    With the default two-way filter a SHARED chain splits every run across both
    directions, so each side would see about half of the configured length -
    measured 10.4 at a 50/50 mix. Worse, the error follows the traffic mix
    rather than being a constant a reader could correct for. Anyone folding the
    two chains back into one turns this red.

    Measured over twelve seeds with the traffic split evenly: outbound runs
    averaged 19.15 to 22.06 and inbound 17.43 to 22.85 (the inbound half is
    noisier because it carries half the packets and so half the runs). The
    assertion is therefore the RULE - each direction is nowhere near half - with
    a floor well below anything observed, plus a tighter check on both
    directions pooled.
    """
    core = _core(loss=5, burst=20)
    dropped, runs = _drops(core, alternate=True)
    for direction, label in ((True, "outbound"), (False, "inbound")):
        mean = _mean(runs[direction])
        check(f"{label} sees a full-length run, not the half a shared chain gives",
              mean >= 15.0, f"(mean run {mean:.2f}, a shared chain measured 10.4)")
    pooled = _mean(runs[True] + runs[False])
    check("pooled, the runs are the length that was configured",
          abs(pooled - 20.0) <= 3.0, f"(mean run {pooled:.2f})")
    delivered = 100.0 * dropped / PACKETS
    check("and the total loss is still the number that was asked for",
          abs(delivered - 5.0) <= 1.2, f"(delivered {delivered:.3f}%)")


def test_an_impossible_pair_delivers_what_it_promised_to_deliver():
    """The clamp is not a silent cap: what comes out is what ``achievable`` said."""
    _p, _r, achievable = burst_loss_params(0.9, 5.0)
    core = _core(loss=90, burst=5)
    dropped, _ = _drops(core)
    delivered = dropped / PACKETS
    check("the run delivers the clamped figure, not the one that was typed",
          abs(delivered - achievable) < 0.01,
          f"(delivered {100 * delivered:.2f}%, achievable {100 * achievable:.2f}%)")


# --------------------------------------------------------------------------- #
# State: what happens between packets
# --------------------------------------------------------------------------- #
def test_changing_only_the_loss_re_derives_the_chain():
    """``p`` depends on BOTH fields, so the loss setter has to move it too.

    Without this the delivered loss would drift away from the field that asked
    for it the moment a session changed its loss without touching the run
    length - and nothing else in the suite would have noticed, because the
    chain would still be a perfectly valid chain for the OLD number.
    """
    core = _core(loss=5, burst=20)
    before = core._burst_p
    core.set_params(20, 0, 0, 0, 0, 0, 0)
    check("a new loss gives a new transition probability", core._burst_p != before,
          f"(p stayed {before})")
    expected, _r, _a = burst_loss_params(0.2, 20.0)
    check("and it is the one the new loss implies",
          abs(core._burst_p - expected) < 1e-12,
          f"(p={core._burst_p}, expected {expected})")


def test_re_applying_the_same_settings_does_not_cut_a_run_in_flight():
    """A scenario stepping an unrelated field calls every setter every time.

    Restarting the chain there would cut most runs short: at 50 packets a second
    a run of 20 lasts 400 ms, which is longer than a scenario step.
    """
    core = _core(loss=50, burst=50)
    rng = random.Random(3)
    for i in range(200):                       # get the chain into a bad run
        core.decide(1200, True, 5000, i * 0.001, rng, remote_ip="1.2.3.4",
                    remote_port=443, is_tcp=True)
        if core._loss_bad[True]:
            break
    check("the chain reached a bad run to test with", core._loss_bad[True], "")

    core.set_loss_burst(50)                    # same value, applied again
    check("re-applying the same run length leaves the run alone",
          core._loss_bad[True], "(the run was cut)")
    core.set_params(50, 0, 0, 0, 0, 0, 0)      # same loss, applied again
    check("re-applying the same loss leaves the run alone",
          core._loss_bad[True], "(the run was cut)")

    core.set_loss_burst(10)                    # a REAL change
    check("a real change does restart the chain", not core._loss_bad[True],
          "(the run survived a change it should not have)")


def test_a_session_never_starts_inside_a_run():
    """``reset_buckets`` runs at every start, exactly like the token buckets."""
    core = _core(loss=90, burst=50)
    rng = random.Random(5)
    for i in range(200):
        core.decide(1200, True, 5000, i * 0.001, rng, remote_ip="1.2.3.4",
                    remote_port=443, is_tcp=True)
    core._loss_bad[True] = core._loss_bad[False] = True
    core.reset_buckets(10.0)
    check("both directions start the session in the good state",
          not core._loss_bad[True] and not core._loss_bad[False],
          f"({core._loss_bad})")


def test_the_run_counter_answers_did_this_fire_at_all():
    """A drop count cannot say whether the MODEL did anything.

    0.1% loss in runs of 1000 is one run per million packets, which on a quiet
    connection is hours: the settings look reasonable, nothing happens, and that
    reads exactly like a broken tool. So the runs are counted, and the count is
    the difference between "too short a session" and "this is not working".
    """
    core = _core(loss=5, burst=20)
    check("a fresh core has counted nothing", core.loss_bursts == 0,
          f"({core.loss_bursts})")
    dropped, runs = _drops(core, packets=50000)
    started = len(runs[True]) + len(runs[False])
    check("the counter matches the runs actually observed",
          abs(core.loss_bursts - started) <= 1,
          f"(counted {core.loss_bursts}, observed {started})")
    check("and it counted something at all", core.loss_bursts > 0,
          f"({core.loss_bursts} with {dropped} packets dropped)")

    # The one packet of slack above is real and worth naming: a run still in
    # progress when the window ends has been STARTED but not yet observed as
    # finished, so the two can differ by exactly one.
    quiet = _core(loss=5, burst=0)
    _drops(quiet, packets=20000)
    check("independent loss starts no runs at all", quiet.loss_bursts == 0,
          f"({quiet.loss_bursts})")


def test_the_run_counter_reaches_the_statistics_snapshot():
    """It is counted by the core and read by the engine, so the wiring is a
    separate question from the counting - and this is the half a scenario, the
    CSV, the repro report and the tile all depend on."""
    from beantester.engine import BeanEngine

    engine = BeanEngine()
    engine.set_params(50, 0, 0, 0, 0, 0, 0)
    engine.set_loss_burst(10)
    engine.core.reset_buckets(0.0)
    check("a stopped engine reports the counter at zero",
          engine.stats_snapshot()["loss_bursts"] == 0,
          f"({engine.stats_snapshot()['loss_bursts']})")

    rng = random.Random(4)
    for i in range(5000):
        engine.core.decide(1200, bool(i % 2), 5000, i * 0.001, rng,
                           remote_ip="1.2.3.4", remote_port=443, is_tcp=True)
    snapshot = engine.stats_snapshot()
    check("the engine reports what the core counted",
          snapshot["loss_bursts"] == engine.core.loss_bursts,
          f"(snapshot {snapshot['loss_bursts']}, core {engine.core.loss_bursts})")
    check("and it is not zero after a run of impaired traffic",
          snapshot["loss_bursts"] > 0, f"({snapshot['loss_bursts']})")


def test_turning_bursts_off_returns_to_the_independent_draw():
    core = _core(loss=10, burst=30)
    check("armed", core._burst_p is not None, "")
    core.set_loss_burst(0)
    check("disarmed", core._burst_p is None, f"(p={core._burst_p})")
    dropped, runs = _drops(core, packets=50000)
    check("and the losses stop clustering", _mean(runs[True]) < 1.2,
          f"(mean run {_mean(runs[True]):.2f})")
    check("while still losing about the configured share",
          abs(100.0 * dropped / 50000 - 10.0) < 1.0,
          f"(delivered {100.0 * dropped / 50000:.2f}%)")
