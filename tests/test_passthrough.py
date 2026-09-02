"""Pass-through invariant: with no impairment configured, the tool COLLECTS
traffic but never damages it.

This is a business-critical guarantee, not a nicety. People run this tool purely
to observe: start it on the default profile ("Perfect network", all zeros), or
pick the best-network preset, and watch the connection log. If a packet were
dropped, delayed, corrupted, duplicated or reset in that mode, the tool would be
silently breaking the very traffic the user only wanted to look at - the worst
possible failure for an observe-only run.

The guarantee has three independent layers, each of which could regress on its
own:

* **the decision core** - ``decide()`` must return a clean pass-through for every
  packet shape when nothing is turned on (``DEFAULT_SETTINGS`` and the ``perfect``
  preset, applied through the real ``apply_settings`` path the GUI and CLI use);
* **the running engine** - a real session over synthetic and scripted traffic
  must forward every packet, byte for byte, while still counting it (collecting);
* **the configuration itself** - the defaults must actually BE harmless, and the
  ``perfect`` preset must stay all-zeros while every other preset keeps impairing
  something (a preset that silently does nothing is its own bug). This layer pins
  the historical regression where the form used to start on a hidden
  100 ms / +/-20 ms / 1% loss instead of a perfect link.
"""
import random
import time

from hypothesis import given, settings
from hypothesis import strategies as st

from beantester.core import BeanCore, Decision
from beantester.engine import BeanEngine
from beantester.fields import (FIELDS, IMPAIRING_KEYS, NARROWING_KEYS,
                               PARAMETER_KEYS, off_value)
from beantester.presets import PRESETS, SETTING_TO_PRESET, preset_to_settings
from beantester.settings import DEFAULT_SETTINGS, apply_settings
from beantester.synthetic import SyntheticDivert
from fakes import FakeDivert, FakePacket, check

# Every knob that can make the core do something other than "pass the packet
# straight through", paired with the value that means "off".
#
# DERIVED from the field registry, not typed out again: a field declares what it
# does to traffic (``impairs`` / ``narrows``, fields.py), and this invariant reads
# that declaration. It used to be a hand-written list, which meant a new impairment
# had to be remembered in two places - and the one that gets forgotten is always
# the test, so the damage ships looking harmless.
#
# The additions are PARAMETERS, not triggers: each of them sits behind another
# field's gate in `decide()` and arms nothing on its own, so the registry rightly
# does not call them impairments (`Field.parameter_of` names their trigger). They
# are swept anyway, because a default that shipped with any of them hot would
# still be a default nobody chose, and pass-through is the one place that should
# insist on the whole form being cold.
#
# 🔴 This dict cannot be derived outright, and saying why is cheaper than
# rediscovering it: a registry knows that `rst_cooldown` parametrises `rst_prob`,
# but not that `spike_ms` ought to ship at 0 while `rst_cooldown` ought to ship at
# 3 s. `rst_cooldown` is therefore the one parameter deliberately outside this
# sweep - 0 there means "no cooldown at all", a different setting rather than a
# cold one. What IS now derived is the bookkeeping: a parameter that ought to be
# here and is not turns
# ``test_every_cold_parameter_is_in_this_sweep`` red, so the list can no longer
# quietly fall behind the registry the way it did while it was two names typed by
# hand.
IMPAIRMENT_OFF = dict(
    {key: off_value(FIELDS[key]) for key in IMPAIRING_KEYS + NARROWING_KEYS},
    spike_ms=0, flap_down=0, loss_burst=0,
)

# The profile fields that can impair traffic, and their "no impairment" value.
# Derived from IMPAIRMENT_OFF (settings keys) so an impairment joining the
# profile scope cannot be forgotten here - the omission that would let a preset
# ship with a live flap and still count as "harmless".
#
# `buffer` is a profile field and is deliberately NOT here: it is absent from
# IMPAIRMENT_OFF because it cannot impair anything on its own - both of its
# readers sit inside `if rate > 0` (BeanCore.decide steps 11 and 12), so with no
# speed limit it touches no packet. Demanding `buffer == 0` of a harmless preset
# would demand an UNBOUNDED buffer, which is the opposite of harmless.
PRESET_OFF = {key: off for key, off in IMPAIRMENT_OFF.items()
              if key in SETTING_TO_PRESET}


def perfect_settings():
    """Full settings dict for the best-network preset, via the real mapping."""
    s = dict(DEFAULT_SETTINGS)
    s.update(preset_to_settings("presets.perfect"))
    return s


def core_for(settings_dict):
    """A BeanCore configured exactly as the GUI/CLI would for these settings."""
    core = BeanCore()
    apply_settings(core, settings_dict)     # same path the app uses
    core.reset_buckets(0.0)
    return core


def is_pass_through(decision, now):
    """A packet was passed through untouched: not dropped, not corrupted,
    released immediately as a single copy, no RST, no drop reason."""
    return (isinstance(decision, Decision)
            and decision.drop is False
            and decision.corrupt is False
            and decision.reason is None
            and decision.emit_rst is False
            and decision.releases == [now])


# --------------------------------------------------------------------------- #
# Layer C (first, because it underpins the other two): the config is harmless
# --------------------------------------------------------------------------- #
def test_defaults_have_every_impairment_switched_off():
    """The program must start harmless. This is the regression guard for the old
    behaviour where the form booted on a hidden 100 ms / 1% loss link."""
    for key, off in IMPAIRMENT_OFF.items():
        check(f"default {key} is off",
              DEFAULT_SETTINGS[key] == off,
              f"(is {DEFAULT_SETTINGS[key]!r}, expected {off!r})")


def test_the_perfect_preset_is_completely_harmless():
    # through the real mapping: a preset names only the fields it means, so what
    # it DELIVERS is the completed dict, not the literal in the table
    perfect = preset_to_settings(PRESETS["presets.perfect"])
    for key, off in PRESET_OFF.items():
        check(f"perfect preset {key} is off",
              perfect[key] == off, f"(is {perfect[key]!r})")


def test_every_cold_parameter_is_in_this_sweep():
    """Bookkeeping between the registry and the hand-written half of the sweep.

    ``IMPAIRMENT_OFF`` derives its impairments and its bounds from the registry
    and then names a few PARAMETERS by hand, because no registry can know which
    of them ought to ship at zero (see the comment there). That hand half is
    exactly the shape that falls behind, so it is checked rather than trusted: a
    parameter whose neutral value IS the registry's off value has to be swept,
    and one that ships at something else is a deliberate choice this test makes
    visible instead of silent.
    """
    swept, deliberate = [], []
    for key in PARAMETER_KEYS:
        (swept if key in IMPAIRMENT_OFF else deliberate).append(key)
        if key in IMPAIRMENT_OFF:
            check(f"the sweep uses {key}'s registry off value",
                  IMPAIRMENT_OFF[key] == off_value(FIELDS[key]),
                  f"(sweeps {IMPAIRMENT_OFF[key]!r}, registry says "
                  f"{off_value(FIELDS[key])!r})")
    for key in deliberate:
        check(f"{key} is outside the sweep because it ships at a chosen value, "
              f"not because somebody forgot it",
              DEFAULT_SETTINGS[key] != off_value(FIELDS[key]),
              f"(default {DEFAULT_SETTINGS[key]!r} equals the off value, so it "
              f"belongs in IMPAIRMENT_OFF)")
    check("the registry knows about some parameters at all "
          "(an empty sweep would pass every check above)",
          len(swept) >= 2, f"(swept: {swept})")


def test_a_parameter_at_its_maximum_still_damages_nothing():
    """The property behind ``Field.parameter_of``, and it is the strong one.

    A parameter shapes an impairment, it does not arm one. Turning every one of
    them up to its registry maximum with the rest of the form at its defaults
    must therefore still pass every packet through untouched. This says far more
    than "their defaults are zero": it would catch a parameter wired so that it
    acts on its own - the mistake that would make ``impairs=""`` a lie and would
    hide a run's real blast radius from ``settings.unbounded_impairment``.
    """
    for key in PARAMETER_KEYS:
        field = FIELDS[key]
        settings = dict(DEFAULT_SETTINGS)
        settings[key] = field.bounds[1]
        core = core_for(settings)
        rng = random.Random(11)
        damaged = 0
        for i in range(2000):
            now = i * 0.001
            decision = core.decide(1200, bool(i % 2), 5000 + (i % 7), now, rng,
                                   remote_ip="1.2.3.4", remote_port=443,
                                   is_syn=(i % 50 == 0), is_tcp=bool(i % 3))
            if not is_pass_through(decision, now):
                damaged += 1
        check(f"{key} at its maximum ({field.bounds[1]}) damages nothing on its own",
              damaged == 0, f"({damaged} of 2000 packets were touched)")


def test_perfect_is_the_only_harmless_preset():
    """Every OTHER preset must impair something. A 'bad network' preset that
    silently does nothing would pass every damage test while being useless."""
    harmless = [key for key, spec in PRESETS.items()
                if all(preset_to_settings(spec)[k] == off
                       for k, off in PRESET_OFF.items())]
    check("exactly one all-zero preset exists", harmless == ["presets.perfect"],
          f"(harmless presets: {harmless})")


# --------------------------------------------------------------------------- #
# Layer A: the decision core passes every packet through
# --------------------------------------------------------------------------- #
packet_shapes = st.fixed_dictionaries({
    "size": st.integers(min_value=1, max_value=65535),
    "is_outbound": st.booleans(),
    "local_port": st.one_of(st.none(), st.integers(min_value=0, max_value=65535)),
    "remote_port": st.one_of(st.none(), st.integers(min_value=0, max_value=65535)),
    "remote_ip": st.one_of(st.none(), st.ip_addresses().map(str)),
    "is_syn": st.booleans(),
    "is_tcp": st.booleans(),
    "now": st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
})

SLOW = settings(max_examples=400, deadline=None)


@SLOW
@given(pkt=packet_shapes)
def test_default_core_passes_every_packet_through(pkt):
    core = core_for(DEFAULT_SETTINGS)
    rng = random.Random(0)
    d = core.decide(pkt["size"], pkt["is_outbound"], pkt["local_port"], pkt["now"], rng,
                    remote_ip=pkt["remote_ip"], remote_port=pkt["remote_port"],
                    is_syn=pkt["is_syn"], is_tcp=pkt["is_tcp"])
    check("default: packet passed through untouched", is_pass_through(d, pkt["now"]),
          f"(decision={d}, pkt={pkt})")


@SLOW
@given(pkt=packet_shapes)
def test_perfect_preset_core_passes_every_packet_through(pkt):
    core = core_for(perfect_settings())
    rng = random.Random(0)
    d = core.decide(pkt["size"], pkt["is_outbound"], pkt["local_port"], pkt["now"], rng,
                    remote_ip=pkt["remote_ip"], remote_port=pkt["remote_port"],
                    is_syn=pkt["is_syn"], is_tcp=pkt["is_tcp"])
    check("perfect: packet passed through untouched", is_pass_through(d, pkt["now"]),
          f"(decision={d}, pkt={pkt})")


def test_default_core_is_pass_through_across_a_deterministic_sweep():
    """Belt-and-suspenders for the property tests: a fixed, exhaustive-ish sweep
    that pins the invariant even if Hypothesis is disabled or reconfigured."""
    core = core_for(DEFAULT_SETTINGS)
    rng = random.Random(1)
    sizes = [1, 40, 100, 576, 1400, 1500, 9000, 65535]
    ips = ["8.8.8.8", "1.2.3.4", "192.168.0.5", "10.0.0.9",
           "127.0.0.1", "::1", "2001:4860:4860::8888", None]
    ports = [None, 0, 53, 80, 443, 1234, 65535]
    violations = 0
    for size in sizes:
        for ip in ips:
            for port in ports:
                for is_out in (True, False):
                    for is_tcp in (True, False):
                        for is_syn in (True, False):
                            now = rng.uniform(0.0, 3600.0)
                            d = core.decide(size, is_out, port, now, rng,
                                            remote_ip=ip, remote_port=port,
                                            is_syn=is_syn, is_tcp=is_tcp)
                            if not is_pass_through(d, now):
                                violations += 1
    check("no pass-through violation across the whole sweep", violations == 0,
          f"({violations} packets were modified)")


# --------------------------------------------------------------------------- #
# Layer B: a real engine session forwards everything while still collecting
# --------------------------------------------------------------------------- #
DAMAGE_COUNTERS = ["drop_loss", "drop_flap", "drop_lan", "drop_internet_only",
                   "drop_block", "drop_mtu",
                   "drop_nat", "drop_rst", "drop_syn", "drop_overflow", "drop_rate",
                   "corrupted", "duplicated", "rst_sent", "loss_bursts"]


def _run_until(engine, predicate, timeout=6.0):
    deadline = time.time() + timeout
    while time.time() < deadline and not predicate(engine.stats_snapshot()):
        time.sleep(0.02)
    time.sleep(0.1)     # let the inject queue drain


def test_default_engine_collects_traffic_without_damaging_it():
    engine = BeanEngine()
    apply_settings(engine, DEFAULT_SETTINGS)        # default = observe only
    engine.start("true", divert=SyntheticDivert(seed=7))
    _run_until(engine, lambda s: s.get("seen", 0) >= 500)
    st_snap = engine.stats_snapshot()
    engine.stop()

    check("engine actually collected traffic", st_snap.get("seen", 0) > 0,
          f"(seen={st_snap.get('seen')})")
    check("engine recorded the bytes it saw",
          st_snap.get("bytes_in_total", 0) + st_snap.get("bytes_out_total", 0) > 0,
          f"(in={st_snap.get('bytes_in_total')}, out={st_snap.get('bytes_out_total')})")
    for counter in DAMAGE_COUNTERS:
        check(f"nothing damaged: {counter} == 0", st_snap.get(counter, 0) == 0,
              f"({counter}={st_snap.get(counter)})")


def test_perfect_preset_engine_collects_traffic_without_damaging_it():
    engine = BeanEngine()
    apply_settings(engine, perfect_settings())
    engine.start("true", divert=SyntheticDivert(seed=11))
    _run_until(engine, lambda s: s.get("seen", 0) >= 500)
    st_snap = engine.stats_snapshot()
    engine.stop()

    check("engine collected traffic on the perfect preset", st_snap.get("seen", 0) > 0,
          f"(seen={st_snap.get('seen')})")
    for counter in DAMAGE_COUNTERS:
        check(f"perfect preset damages nothing: {counter} == 0",
              st_snap.get(counter, 0) == 0, f"({counter}={st_snap.get(counter)})")


def test_default_engine_forwards_every_packet_byte_for_byte():
    """The strongest form of 'does not damage': feed known packets and prove each
    one is forwarded exactly once with its payload untouched."""
    count = 2000
    packets = [FakePacket(size=100 + (i % 7), is_outbound=(i % 2 == 0),
                          port=1000 + i, payload=f"payload-{i}".encode())
               for i in range(count)]
    # Snapshot identity -> original bytes BEFORE the engine can touch anything.
    original = {id(p): (p.raw, p.payload) for p in packets}
    fake = FakeDivert(packets)

    engine = BeanEngine()
    apply_settings(engine, DEFAULT_SETTINGS)
    engine.start("test", divert=fake)
    _run_until(engine, lambda s: s.get("seen", 0) >= count and s.get("queue", 0) == 0)
    st_snap = engine.stats_snapshot()
    engine.stop()

    sent_packets = [p for _, p in fake.sent]
    check("every packet was read", st_snap.get("seen", 0) == count,
          f"(seen={st_snap.get('seen')})")
    check("every packet was forwarded (none dropped)", len(sent_packets) == count,
          f"(sent={len(sent_packets)})")
    check("no packet was duplicated", st_snap.get("duplicated", 0) == 0,
          f"(duplicated={st_snap.get('duplicated')})")

    mutated = [p for p in sent_packets
               if (p.raw, p.payload) != original.get(id(p))]
    check("no forwarded packet had its bytes changed", not mutated,
          f"({len(mutated)} packets were mutated in flight)")

    forwarded_ids = {id(p) for p in sent_packets}
    check("the exact packets read are the packets sent",
          forwarded_ids == {id(p) for p in packets},
          f"(missing={len(set(map(id, packets)) - forwarded_ids)})")
