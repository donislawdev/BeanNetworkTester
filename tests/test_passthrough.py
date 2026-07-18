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

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from beantester.core import BeanCore, Decision
from beantester.engine import BeanEngine
from beantester.presets import PRESETS, preset_to_settings
from beantester.settings import DEFAULT_SETTINGS, apply_settings
from beantester.synthetic import SyntheticDivert
from fakes import FakeDivert, FakePacket, check

# Every knob that can make the core do something other than "pass the packet
# straight through", paired with the value that means "off". If a new impairment
# is added to the model, add it here too - an omission is exactly how a default
# could start damaging traffic without a test noticing.
IMPAIRMENT_OFF = {
    "loss": 0, "corrupt": 0, "dup": 0, "latency": 0, "jitter": 0,
    "down": 0, "up": 0, "syn_drop": 0, "max_size": 0, "spike_prob": 0,
    "spike_ms": 0, "nat_timeout": 0, "rst_prob": 0, "flap_period": 0,
    "flap_down": 0, "target": "", "dst_ip": "", "dst_port": "",
    "block_ip": "", "block_port": "",
    "rate_schedule": "", "lan_mode": False,
}

# The seven fields a preset carries (short keys), and their "no impairment" value.
PRESET_OFF = {"loss": 0, "corrupt": 0, "dup": 0, "lat": 0, "jit": 0, "down": 0, "up": 0}


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
    perfect = PRESETS["presets.perfect"]
    for key, off in PRESET_OFF.items():
        check(f"perfect preset {key} is off",
              perfect[key] == off, f"(is {perfect[key]!r})")


def test_perfect_is_the_only_harmless_preset():
    """Every OTHER preset must impair something. A 'bad network' preset that
    silently does nothing would pass every damage test while being useless."""
    harmless = [key for key, spec in PRESETS.items()
                if all(spec[k] == off for k, off in PRESET_OFF.items())]
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
DAMAGE_COUNTERS = ["drop_loss", "drop_flap", "drop_lan", "drop_block", "drop_mtu",
                   "drop_nat", "drop_rst", "drop_syn", "drop_overflow", "drop_rate",
                   "corrupted", "duplicated", "rst_sent"]


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
