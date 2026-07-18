"""Bounded-buffer rate limiter: recovery after a rate rise (P1), bounded
queueing delay (P2), the drop_rate counter, and legacy unbounded behaviour.

These lock in the fix for two bugs in the old token bucket:

* a rate INCREASE was swallowed - the virtual-finish-time bucket had run seconds
  ahead at the low rate and kept gating every later high-rate step (a schedule
  never recovered, and "Apply changes" raising the cap did nothing for a while);
* the bucket ran arbitrarily far ahead, injecting 100 s+ of latency and an
  ever-growing queue.

The old ``test_rate_schedule`` only checked ``_current_rates`` (the rate LOOKUP),
never the delivered throughput, so the pinning slipped straight through.
"""
import random

from beantester.core import BeanCore

SIZE = 1500
OFFERED_BPS = 4_000_000            # ~16x a 256 KB/s cap: the bucket wants to run ahead


def _saturate(core, rate_kbps, seconds, start_i=0, start_t=0.0):
    """Feed inbound packets far above ``rate_kbps`` for ``seconds`` of offered time."""
    rng = random.Random(1)
    interval = SIZE / OFFERED_BPS
    i = start_i
    now = start_t
    while now < start_t + seconds:
        now = i * interval
        core.decide(SIZE, False, 1000, now, rng, remote_ip="8.8.8.8", remote_port=443)
        i += 1
    return i, now


def test_bounded_buffer_caps_queueing_delay():
    # P2: with a 2 s buffer no delivered packet is scheduled more than ~2 s out,
    # and the delivered rate still equals the cap (the excess is tail-dropped).
    core = BeanCore()
    core.set_params(0, 0, 0, 0, 0, 256, 0)
    core.set_buffer(2000)
    core.reset_buckets(0.0)
    rng = random.Random(1)
    interval = SIZE / OFFERED_BPS
    max_delay = 0.0
    delivered = last_rel = 0
    dropped = 0
    now = 0.0
    for i in range(40000):
        now = i * interval
        d = core.decide(SIZE, False, 1000, now, rng, remote_ip="8.8.8.8", remote_port=443)
        if d.drop and d.reason == "rate":
            dropped += 1
        else:
            delivered += 1
            last_rel = d.releases[0]
            max_delay = max(max_delay, d.releases[0] - now)
    assert max_delay <= 2.0 + SIZE / (256 * 1024) + 0.01, max_delay
    assert dropped > 0, "an over-offered capped link must drop from a full buffer"
    eff_kbps = delivered * SIZE / last_rel / 1024
    assert abs(eff_kbps - 256) < 8, eff_kbps          # delivered rate stays at the cap


def test_rate_increase_recovers_within_the_buffer():
    # P1 (constant limits): saturate at 64 KB/s so the bucket runs ~2 s ahead, then
    # raise the cap. A packet arriving after the buffer has drained gets ~no delay.
    core = BeanCore()
    core.set_params(0, 0, 0, 0, 0, 64, 0)
    core.set_buffer(2000)
    core.reset_buckets(0.0)
    i, t = _saturate(core, 64, 3.0)

    core.set_params(0, 0, 0, 0, 0, 100000, 0)         # raise to ~100 MB/s
    rng = random.Random(2)
    # right after the raise the backlog is still bounded by the buffer...
    d_now = core.decide(SIZE, False, 1000, t, rng, remote_ip="8.8.8.8", remote_port=443)
    assert d_now.releases[0] - t <= 2.0 + 0.01, d_now.releases[0] - t
    # ...and once real time passes the buffer window, throughput is fully back
    d_later = core.decide(SIZE, False, 1000, t + 2.5, rng,
                          remote_ip="8.8.8.8", remote_port=443)
    assert d_later.releases[0] - (t + 2.5) < 0.01, d_later.releases[0] - (t + 2.5)


def test_schedule_recovers_to_the_high_rate():
    # P1 (schedule): 1 s @ 64 then 5 s @ 1024, looping, 2 s buffer. Saturate the
    # low window; well into the high window (buffer long drained) a packet gets
    # ~no delay. Before the fix the bucket stayed ~60 s ahead and never recovered.
    core = BeanCore()
    core.set_schedule([(1.0, 64, 0), (5.0, 1024, 0)])
    core.set_buffer(2000)
    core.reset_buckets(0.0)
    _saturate(core, 64, 0.99)                          # heavy offer during the 64 window

    rng = random.Random(3)
    probe = core.decide(SIZE, False, 1000, 4.0, rng,   # deep in the 1024 window
                        remote_ip="8.8.8.8", remote_port=443)
    assert probe.releases[0] - 4.0 < 0.05, probe.releases[0] - 4.0


def test_buffer_zero_is_unbounded_legacy():
    # buffer 0 == the old behaviour: the bucket runs far ahead and nothing is
    # dropped by the rate limiter. This is what a bare BeanCore()/set_params keeps.
    core = BeanCore()
    core.set_params(0, 0, 0, 0, 0, 256, 0)
    core.set_buffer(0)                                 # explicit, though 0 is the core default
    core.reset_buckets(0.0)
    rng = random.Random(1)
    interval = SIZE / OFFERED_BPS
    rate_drops = 0
    last_rel = now = 0.0
    for i in range(20000):
        now = i * interval
        d = core.decide(SIZE, False, 1000, now, rng, remote_ip="8.8.8.8", remote_port=443)
        if d.drop and d.reason == "rate":
            rate_drops += 1
        else:
            last_rel = d.releases[0]
    assert rate_drops == 0, rate_drops
    assert last_rel - now > 10.0, "unbounded buffer should run far ahead of now"


def test_empty_buffer_never_blacks_out_the_link():
    # A buffer smaller than one packet's serialisation must still pass a packet
    # into an EMPTY buffer (queued == 0), so a tiny buffer throttles hard but never
    # drops everything.
    core = BeanCore()
    core.set_params(0, 0, 0, 0, 0, 50, 0)              # 50 KB/s: 1500 B takes ~29 ms
    core.set_buffer(1)                                 # 1 ms buffer, < one packet time
    core.reset_buckets(0.0)
    rng = random.Random(4)
    passed = 0
    for i in range(200):
        d = core.decide(SIZE, False, 1000, i * 0.05, rng,   # 50 ms apart: buffer empties
                        remote_ip="8.8.8.8", remote_port=443)
        if not d.drop:
            passed += 1
    assert passed == 200, passed                        # empty buffer always accepts


def test_drop_rate_counter_via_apply_settings():
    # Engine level, through the production path (apply_settings sets the buffer from
    # DEFAULT_SETTINGS). A burst well over the cap fills the bounded buffer, so the
    # excess is counted as drop_rate - NOT drop_overflow (that stays the tool's own
    # failsafe) and NOT drop_loss.
    import time
    from beantester import BeanEngine
    from beantester.settings import DEFAULT_SETTINGS, apply_settings
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from fakes import FakeDivert, FakePacket

    pkts = [FakePacket(size=1024, is_outbound=False, port=2000) for _ in range(600)]
    fake = FakeDivert(pkts)
    eng = BeanEngine()
    apply_settings(eng, {**DEFAULT_SETTINGS, "down": 50, "buffer": 500})   # 50 KB/s, 0.5 s buffer
    eng.start("test", divert=fake)
    deadline = time.time() + 10
    while time.time() < deadline:
        s = eng.stats_snapshot()
        if s["seen"] >= 600 and s["queue"] == 0:
            break
        time.sleep(0.02)
    time.sleep(0.1)
    eng.stop()
    s = eng.stats_snapshot()

    assert s["seen"] == 600, s["seen"]
    assert s["drop_rate"] > 0, "a full rate-limit buffer must report drop_rate"
    assert s["drop_loss"] == 0, s["drop_loss"]          # not misreported as loss
    # every packet either got through or was a rate drop (nothing vanished)
    assert s["drop_rate"] + len(fake.sent) == 600, (s["drop_rate"], len(fake.sent))


def test_tiny_positive_rate_is_not_silently_unlimited():
    # A positive but sub-byte/s cap floors at 1 B/s instead of rounding to 0
    # (== unlimited). --down 0.0005 must throttle hard, not do nothing.
    core = BeanCore()
    core.set_params(0, 0, 0, 0, 0, 0.0005, 0.0005)
    assert core.rate_down == 1, core.rate_down
    assert core.rate_up == 1, core.rate_up
    core.set_params(0, 0, 0, 0, 0, 0, 0)               # a real 0 stays unlimited
    assert core.rate_down == 0 and core.rate_up == 0
    core.set_schedule([(1.0, 0.0004, 0)])              # same rule inside a schedule
    assert core.schedule[0][1] == 1, core.schedule
