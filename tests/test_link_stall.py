"""A link outage that HOLDS its packets and delivers them when it ends (decide()
step 5, ``BeanCore._outage``).

The packet "reaches the link" when the outage ends, and everything after step 5
reads that moment instead of the capture time. What these tests hold in place:
with holding off nothing changed; every packet of one outage gets the identical
release time, or the delay queue would let a later one overtake; latency and the
speed limit apply AFTER the stall; and one outage can hold only so much, because
the queue it fills also carries the traffic the session does not touch.
"""
import random
import re

from beantester import BeanEngine
from beantester.cli import build_arg_parser, config_from_args
from beantester.core import FLAP_HOLD_MAX, BeanCore
from beantester.fields import FIELDS, PARAMETER_KEYS, PROFILE_FIELDS
from beantester.i18n import load_languages, translate
from beantester.presets import PRESETS, preset_to_settings
from beantester.repro import settings_to_cli
from beantester.settings import DEFAULT_SETTINGS, apply_settings, unbounded_impairment
from beantester.summary import settings_summary
from fakes import FakeDivert, FakePacket, check, wait_until

START = 1000.0          # session start: far from zero, where float steps are coarser
PERIOD, DOWN_PCT = 10.0, 30.0
OUTAGE_END = START + 3.0


def stalling_core(hold=True, period=PERIOD, down_pct=DOWN_PCT, start=START):
    core = BeanCore()
    core.set_flap(True, period, down_pct, hold=hold)
    core.reset_buckets(start)
    return core


def judge(core, now, size=100, is_outbound=True, rng=None):
    return core.decide(size, is_outbound, 50000, now, rng or random.Random(1),
                       remote_ip="10.0.0.20", remote_port=50001)


# -- the core ----------------------------------------------------------------- #
def test_with_holding_off_an_outage_drops_exactly_what_it_always_did():
    """The phase used to be ``(now - start) % period`` inline; it is ``divmod`` in a
    helper now. A reproduction command from before this change must replay the same
    drops, so the old expression is the oracle here."""
    rng = random.Random(284)
    for _ in range(400):
        period = rng.uniform(0.05, 60.0)
        down = rng.uniform(0.0, 100.0)
        start = rng.uniform(0.0, 1e6)
        core = stalling_core(hold=False, period=period, down_pct=down, start=start)
        for _n in range(12):
            now = start + rng.uniform(0.0, 5 * period)
            expected = (now - start) % core.flap_period_s < core.flap_period_s * core.flap_down
            decision = judge(core, now)
            assert decision.drop == expected, (period, down, start, now)
            assert (decision.reason == "flap") == expected
            assert decision.drop or decision.releases == [now]
        assert core.flap_held == 0 and core.flap_refused == 0


def test_a_held_packet_leaves_when_the_outage_ends():
    core = stalling_core()
    for offset in (0.0, 0.001, 1.5, 2.999):
        decision = judge(core, START + offset)
        check(f"at +{offset} s it is held, not dropped",
              not decision.drop and decision.scoped and decision.reason is None)
        check(f"at +{offset} s it leaves when the outage ends",
              decision.releases == [OUTAGE_END], f"({decision.releases})")
    for offset in (3.0, 5.0, 9.999):
        check(f"at +{offset} s the link is up and nothing waits",
              judge(core, START + offset).releases == [START + offset])
    second = judge(core, START + PERIOD + 1.0)
    check("the next outage ends one period later",
          second.releases == [OUTAGE_END + PERIOD], f"({second.releases})")
    check("four packets were held in the first outage and one in the second",
          core.flap_held == 5, f"({core.flap_held})")


def test_every_packet_of_one_outage_gets_the_identical_release_time():
    """The delay queue orders by release time first and by arrival second. An end
    computed from each packet's own ``now`` rounds differently per packet (MEASURED:
    25 of 20 000 outages put a later packet ahead of an earlier one), so the end is
    computed from the cycle and must come out as ONE float."""
    rng = random.Random(7)
    for _ in range(300):
        period = rng.uniform(0.05, 30.0)
        down = rng.uniform(5.0, 100.0)
        start = rng.uniform(0.0, 1e6)
        core = stalling_core(period=period, down_pct=down, start=start)
        cycle = rng.randrange(0, 50)
        length = core.flap_period_s * core.flap_down
        moments = sorted(start + cycle * period + rng.uniform(0.0, length) * 0.999
                         for _n in range(40))
        ends = set()
        for now in moments:
            decision = judge(core, now)
            if decision.releases and decision.releases[0] != now:
                ends.add(decision.releases[0])
                assert decision.releases[0] >= now, (period, down, start, now)
        assert len(ends) <= 1, (period, down, start, sorted(ends))


# Outages where an end computed from each packet's own clock (``now + (down -
# phase)``) comes out EARLIER for the later of two packets: (session start, period,
# downtime percent, first packet, second packet). Found by search on 2026-11-10;
# random draws meet one in about 5000 outages, which is why they are written down.
ROUNDING_TRAPS = (
    (3058.09, 30.0, 50.0, 55588.269744137746, 55588.38538672782),
    (1010.259, 30.0, 25.0, 17394.46233003149, 17394.97918237945),
    (17945.743, 30.0, 10.0, 58655.7761502037, 58655.82921648419),
    (10063.507, 30.0, 25.0, 32083.54164182481, 32083.644667059052),
    (13643.535, 30.0, 10.0, 53063.5474400368, 53063.63742958647),
    (20590.853, 30.0, 25.0, 54701.23492046498, 54701.36204061582),
)


def test_the_end_of_an_outage_does_not_depend_on_which_packet_asks():
    """The same statement as the test above, on the outages known to break it: there
    a later packet would be released BEFORE an earlier one of the same outage."""
    for start, period, down, first, second in ROUNDING_TRAPS:
        core = stalling_core(period=period, down_pct=down, start=start)
        earlier, later = judge(core, first).releases[0], judge(core, second).releases[0]
        check(f"start {start}, period {period}: both are held", earlier > first and later > second)
        check(f"start {start}, period {period}: one release time for both",
              earlier == later, f"({earlier!r} and {later!r})")


def test_latency_is_added_after_the_stall():
    """Queue time and latency add up, on a real link and here: a packet stalled for
    two seconds on a 200 ms link arrives after 2.2 s, not after 2 s."""
    core = stalling_core()
    core.set_params(0, 0, 0, 200, 0, 0, 0)
    check("held for 2 s, then 200 ms of latency",
          judge(core, START + 1.0).releases == [OUTAGE_END + 0.2])
    check("with the link up it is the latency alone",
          judge(core, START + 4.0).releases == [START + 4.0 + 0.2])


def test_a_speed_limit_carries_the_burst_at_the_links_rate():
    """No "release over N ms" setting: the token bucket is charged from the moment
    the outage ends, so the burst leaves at the configured rate."""
    core = stalling_core()
    core.set_params(0, 0, 0, 0, 0, 0, 10)            # upload limit 10 KB/s
    core.set_buffer(0)                               # unbounded: nothing is refused
    per_packet = 1024 / (10 * 1024.0)                # 1024 B at 10 KB/s = 0.1 s
    releases = [judge(core, START + 0.1 * n, size=1024).releases[0] for n in range(5)]
    expected = [OUTAGE_END + per_packet * (n + 1) for n in range(5)]
    check("one packet per 100 ms, starting when the outage ends",
          all(abs(a - b) < 1e-9 for a, b in zip(releases, expected, strict=True)),
          f"({releases})")
    after = judge(core, OUTAGE_END + 0.05, size=1024)
    check("a packet arriving after the outage queues behind the burst",
          abs(after.releases[0] - (OUTAGE_END + per_packet * 6)) < 1e-9, f"({after.releases})")


def test_the_links_buffer_refuses_what_a_stalled_link_cannot_take():
    core = stalling_core()
    core.set_params(0, 0, 0, 0, 0, 0, 10)
    core.set_buffer(250)                             # room for 250 ms of queue
    outcomes = [judge(core, START + 0.1 * n, size=1024) for n in range(8)]
    kept = [d for d in outcomes if not d.drop]
    # 100 ms a packet: the first finds the link free, the second waits 100 ms and
    # ends at 200 ms, the third would end at 300 ms - past the buffer.
    check("the buffer took what fits in 250 ms", len(kept) == 2, f"({len(kept)})")
    check("the rest was refused as the speed limit's drop, not the outage's",
          {d.reason for d in outcomes if d.drop} == {"rate"})
    check("the outage held all eight (the link refused six later)", core.flap_held == 8)


def test_the_schedule_is_read_at_the_moment_the_packet_reaches_the_link():
    """A stall that ends in the schedule's next step is carried at THAT step's rate."""
    core = BeanCore()
    core.set_flap(True, PERIOD, DOWN_PCT, hold=True)
    core.set_buffer(0)
    core.set_schedule([(2.0, 0, 0), (100.0, 0, 10)])         # unlimited, then 10 KB/s up
    core.reset_buckets(START)
    held = judge(core, START + 1.0, size=1024)               # captured in step one
    check("it is charged the rate of the step the outage ends in",
          abs(held.releases[0] - (OUTAGE_END + 0.1)) < 1e-9, f"({held.releases})")


def test_a_duplicate_of_a_held_packet_is_charged_at_the_same_moment():
    """The copy rides the shaped link too. Charged from the capture time instead, it
    would see the whole stall as queue already built up and be refused by the buffer."""
    core = stalling_core()
    core.set_params(0, 0, 100, 0, 0, 0, 10)                  # duplicate everything
    core.set_buffer(1000)
    decision = judge(core, START + 0.5, size=1024)
    check("the original and its copy both leave", len(decision.releases) == 2,
          f"({decision.releases})")
    check("neither before the outage ends", min(decision.releases) >= OUTAGE_END)


def test_an_outage_of_the_whole_period_delivers_in_bursts():
    """Downtime 100% with holding: what arrives in one period leaves at the start of
    the next - a radio that wakes once per beacon."""
    core = stalling_core(period=0.1, down_pct=100)
    first = [judge(core, START + 0.01 * n).releases[0] for n in range(1, 10)]
    check("the whole first period leaves at once, when it ends",
          set(first) == {START + 0.1}, f"({sorted(set(first))})")
    later = judge(core, START + 0.25).releases[0]
    check("and the third period's packet at the end of the third",
          abs(later - (START + 0.3)) < 1e-9, f"({later})")
    check("nothing was dropped", core.flap_refused == 0)


def test_one_outage_holds_only_so_many_packets():
    core = stalling_core()
    decisions = [judge(core, START + 1.0) for _ in range(FLAP_HOLD_MAX + 25)]
    held = [d for d in decisions if not d.drop]
    refused = [d for d in decisions if d.drop]
    check("the first FLAP_HOLD_MAX were held", len(held) == FLAP_HOLD_MAX, f"({len(held)})")
    check("in arrival order: the refused are the last ones",
          all(d.drop for d in decisions[FLAP_HOLD_MAX:]))
    check("the rest were dropped as a link outage",
          len(refused) == 25 and {d.reason for d in refused} == {"flap"})
    check("and both were counted", (core.flap_held, core.flap_refused) == (FLAP_HOLD_MAX, 25),
          f"({core.flap_held}, {core.flap_refused})")
    # A new session, judged in the SAME cycle number the full outage had: the count
    # of the outage in progress must not come along.
    core.reset_buckets(START)
    check("a new session starts from zero", (core.flap_held, core.flap_refused) == (0, 0))
    check("with room from its first packet", not judge(core, START + 1.0).drop)
    for _ in range(FLAP_HOLD_MAX):
        judge(core, START + 1.0)
    check("full again", judge(core, START + 2.0).drop)
    check("the next outage starts with room again",
          not judge(core, START + PERIOD + 1.0).drop)


def test_the_limit_leaves_half_of_the_queue_to_everything_else():
    """The delay queue also carries the packets a session does not touch, and a full
    queue drops those too - on the machine the tool runs on."""
    check("FLAP_HOLD_MAX is at most half of the queue",
          0 < FLAP_HOLD_MAX <= BeanEngine().max_queue // 2,
          f"({FLAP_HOLD_MAX} of {BeanEngine().max_queue})")


def test_the_gates_before_the_outage_and_the_drops_after_it_still_apply():
    core = stalling_core()
    core.set_target(True, {1})                       # this flow is not the target
    passing = judge(core, START + 1.0)
    check("a packet out of scope is not held", passing.releases == [START + 1.0]
          and not passing.scoped and core.flap_held == 0)
    core.set_target(False, None)
    core.set_advanced(0, 500)                        # MTU 500
    big = judge(core, START + 1.0, size=1400)
    check("a held packet above the MTU is still dropped, as MTU", big.drop and big.reason == "mtu")
    core.set_advanced(0, 0)
    core.set_params(100, 0, 0, 0, 0, 0, 0)
    lost = judge(core, START + 1.0)
    check("and loss still loses it", lost.drop and lost.reason is None)


def test_holding_can_be_switched_mid_outage():
    core = stalling_core()
    check("held", judge(core, START + 1.0).releases == [OUTAGE_END])
    core.set_flap(True, PERIOD, DOWN_PCT)            # hold defaults to off
    check("the default of the setter is to drop", judge(core, START + 1.5).reason == "flap")
    core.set_flap(True, PERIOD, DOWN_PCT, hold=True)
    check("held again, to the same end", judge(core, START + 2.0).releases == [OUTAGE_END])


# -- through the engine ------------------------------------------------------- #
def _stalled_engine(packets, **settings):
    engine = BeanEngine()
    engine.set_seed(7)
    apply_settings(engine, {**DEFAULT_SETTINGS, "flap_period": 1.2, "flap_down": 50,
                            **settings})
    divert = FakeDivert(packets)
    return engine, divert


def test_through_the_engine_a_stalled_burst_arrives_whole_and_in_order():
    packets = [FakePacket(size=100 + n) for n in range(40)]
    engine, divert = _stalled_engine(packets, flap_hold=True)
    engine.start("test", divert=divert)
    try:
        check("every packet was seen",
              wait_until(lambda: engine.stats_snapshot()["seen"] >= len(packets)))
        waiting = engine.stats_snapshot()
        check("the outage holds them: nothing has been sent", not divert.sent,
              f"({len(divert.sent)} sent)")
        check("they wait in the queue", waiting["queue"] == len(packets), f"({waiting['queue']})")
        check("all of them arrive when it ends",
              wait_until(lambda: len(divert.sent) >= len(packets)))
        stats = engine.stats_snapshot()
    finally:
        engine.stop()
    check("in the order they came",
          [len(p.raw) for _t, p in divert.sent] == [100 + n for n in range(40)])
    check("counted as held", stats["flap_held"] == len(packets), f"({stats['flap_held']})")
    check("and not as dropped", stats["drop_flap"] == 0 and stats["drop_overflow"] == 0)


def test_through_the_engine_holding_off_still_drops():
    packets = [FakePacket(size=100 + n) for n in range(10)]
    engine, divert = _stalled_engine(packets)
    engine.start("test", divert=divert)
    try:
        check("every packet was seen",
              wait_until(lambda: engine.stats_snapshot()["seen"] >= len(packets)))
        stats = engine.stats_snapshot()
    finally:
        engine.stop()
    check("the outage dropped them", stats["drop_flap"] == len(packets) and not divert.sent)
    check("and held none", stats["flap_held"] == 0)


def test_stop_during_an_outage_drops_what_was_waiting_and_says_so():
    packets = [FakePacket(size=100) for _ in range(12)]
    engine, divert = _stalled_engine(packets, flap_hold=True, flap_period=60)
    engine.start("test", divert=divert)
    try:
        check("every packet was seen",
              wait_until(lambda: engine.stats_snapshot()["seen"] >= len(packets)))
    finally:
        engine.stop()
    stats = engine.stats_snapshot()
    check("nothing was sent at STOP", not divert.sent)
    check("they are counted as dropped at stop", stats["drop_shutdown"] == len(packets),
          f"({stats['drop_shutdown']})")


def test_the_engine_says_at_stop_when_an_outage_ran_out_of_room():
    lines = []
    engine = BeanEngine(log_fn=lines.append)
    engine.set_seed(7)
    apply_settings(engine, dict(DEFAULT_SETTINGS, flap_period=60, flap_down=50, flap_hold=True))
    engine.start("test", divert=FakeDivert([]))
    engine.core.flap_refused = 37                    # what _outage counts past the limit
    engine.stop()
    # the whole sentence, so the two numbers cannot trade places unnoticed
    expected = translate("log.flap_hold_full", None, n=37, cap=FLAP_HOLD_MAX)
    check("one line names both numbers, each in its place",
          "37" in expected and lines.count(expected) == 1, f"({lines})")
    quiet = []
    engine = BeanEngine(log_fn=quiet.append)
    engine.start("test", divert=FakeDivert([]))
    engine.stop()
    check("and a session that refused nothing says nothing about it",
          not [line for line in quiet if str(FLAP_HOLD_MAX) in line], f"({quiet})")


# -- settings, CLI, reproduction, summary, texts ------------------------------ #
def test_holding_is_a_parameter_of_the_outage_and_travels_with_a_profile():
    field = FIELDS["flap_hold"]
    check("it shapes the outage and arms nothing", "flap_hold" in PARAMETER_KEYS
          and field.parameter_of == "flap_period" and not field.impairs)
    check("on its own it impairs nothing",
          not unbounded_impairment(dict(DEFAULT_SETTINGS, flap_hold=True)))
    check("a profile stores it", "flap_hold" in PROFILE_FIELDS)
    check("it is off by default", DEFAULT_SETTINGS["flap_hold"] is False)
    for name, preset in PRESETS.items():
        check(f"preset {name} leaves it off", not preset_to_settings(preset)["flap_hold"])


def test_the_flag_reaches_the_core_and_comes_back_in_the_command():
    args = ["--flap-period", "8", "--flap-down", "25", "--flap-hold"]
    settings = config_from_args(build_arg_parser().parse_args(args))["settings"]
    check("the flag sets the setting", settings["flap_hold"] is True)
    engine = BeanEngine()
    apply_settings(engine, settings)
    check("and the setting reaches the core", engine.core.flap_hold is True)
    command = settings_to_cli(settings)
    check("it is in the reproduction command", "--flap-hold" in command, f"({command})")
    plain = config_from_args(build_arg_parser().parse_args(args[:-1]))["settings"]
    check("without the flag it is off, in the core and in the command",
          plain["flap_hold"] is False and "--flap-hold" not in settings_to_cli(plain))
    apply_settings(engine, plain)
    check("and an apply without it switches it off again", engine.core.flap_hold is False)


def test_the_summary_says_whether_the_outage_holds():
    base = dict(DEFAULT_SETTINGS, flap_period=8, flap_down=25)
    check("dropping reads as before", "outages every 8 s." in settings_summary(base, lang="en"))
    held = settings_summary(dict(base, flap_hold=True), lang="en")
    check("holding is said", "outages every 8 s, packets held" in held, f"({held})")
    check("the switch alone says nothing",
          "outage" not in settings_summary(dict(DEFAULT_SETTINGS, flap_hold=True), lang="en"))


def test_the_tooltip_names_the_limit_the_core_enforces():
    """The number in the text is typed, the one in the core is the truth."""
    for code in load_languages():
        text = translate("tips.flap_hold", code)
        numbers = {int(re.sub(r"\D", "", match))
                   for match in re.findall(r"\d[\d  ,.]*\d", text)}
        check(f"{code}: the tooltip says {FLAP_HOLD_MAX}", FLAP_HOLD_MAX in numbers,
              f"({sorted(numbers)} in {text!r})")
