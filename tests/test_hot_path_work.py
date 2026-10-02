"""The packet path does each piece of work once - COUNTED, never timed.

What this guards
----------------
The performance review of 2026-09-26 (chunk R-2 of its tracker) found work the
packet path repeated for every packet although the answer could not change: an
address parsed again for every packet of a flow, a schedule walked step by step, a
lookup that can never succeed. Each fix here is a COST, and a cost comes back
without failing a single correctness test - the program only gets slower, on
somebody else's weaker machine.

So these tests count calls, exactly, in the manner of ``test_hot_path.py`` (trips
to the operating system) and ``test_hot_path_allocations.py`` (bytes retained).
Time is measured by the rigs, never here: a timing assertion on a CI runner is a
flake with a threshold.
"""
import ipaddress
import itertools
import random

from fakes import check

from beantester import core as core_mod
from beantester import matchers, utils
from beantester.core import BeanCore
from beantester.matchers import KIND_INT, KIND_IP, parse_matcher


# -- W-A2: an address or port is judged once, not once per packet -------------- #
def _counting(monkeypatch, module, name):
    calls = [0]
    real = getattr(module, name)

    def counted(*args, **kwargs):
        calls[0] += 1
        return real(*args, **kwargs)
    monkeypatch.setattr(module, name, counted)
    return calls


def test_an_address_is_parsed_once_however_many_packets_carry_it(monkeypatch):
    """A flow sends thousands of packets from one address; its verdict is one."""
    parsed = _counting(monkeypatch, matchers, "_as_ip")
    ip = parse_matcher("93.184.216.0/24, 2001:db8::/32", KIND_IP)
    verdicts = {ip.matches("93.184.216.34") for _ in range(1000)}
    verdicts |= {ip.matches("2001:db8::7") for _ in range(1000)}
    check("2000 packets from two addresses parse two addresses",
          parsed[0] == 2, f"(parsed {parsed[0]} times)")
    check("and the remembered verdict is the one the terms give", verdicts == {True})

    counted = _counting(monkeypatch, matchers, "_as_int")
    port = parse_matcher("443, 8000-8100", KIND_INT)
    for _ in range(1000):
        port.matches(443)
    check("1000 packets to one port read the port once",
          counted[0] == 1, f"(read {counted[0]} times)")


def test_the_verdict_memory_has_a_ceiling():
    """A port scan sends every packet from a new value; the memory stays bounded."""
    ip = parse_matcher("10.0.0.0/8", KIND_IP)
    ceiling = type(ip).VERDICTS_MAX
    rng = random.Random(5)
    largest = 0
    for _ in range(3 * ceiling):
        ip.matches(str(ipaddress.IPv4Address(rng.getrandbits(32))))
        largest = max(largest, len(ip._verdicts))
    check(f"3 x {ceiling} new addresses never hold more than {ceiling} verdicts",
          largest <= ceiling, f"(held {largest})")
    check("and the memory was really used up to its ceiling", largest == ceiling)


def test_a_remembered_verdict_never_answers_for_a_value_of_another_type():
    """``True == 1 == 1.0`` as dict keys; to this language they are not the same.

    ``_as_int(True)`` is "no value", so ``!1`` lets ``True`` through and refuses
    ``1``. One instance asked in this order must answer as a fresh one would.
    """
    for text, kind, values in (
            ("!1", KIND_INT, [1, True, 1.0, "1", 1, True, None, 1.5]),
            ("1", KIND_INT, [True, 1, 1.0, False, 0]),
            ("10.0.0.1", KIND_IP, ["10.0.0.1", " 10.0.0.1", None, 167772161,
                                   ipaddress.IPv4Address("10.0.0.1"), "10.0.0.1"])):
        shared = parse_matcher(text, kind)
        got = [shared.matches(v) for v in values]
        fresh = [parse_matcher(text, kind).matches(v) for v in values]
        check(f"{text!r} answers {values!r} like fresh matchers do",
              got == fresh, f"(shared {got}, fresh {fresh})")


def test_every_remembered_verdict_is_the_one_the_terms_give():
    """Through hits, misses and whole clears: never a stale or borrowed answer.

    The reference is the same instance asked through ``Matcher.matches`` - the
    terms themselves, with no memory in between.
    """
    terms = matchers.Matcher.matches
    rng = random.Random(9)
    ip = parse_matcher("10.0.0.0/8, !10.9.0.0/16, 2001:db8::/32, 192.168.*.1", KIND_IP)
    port = parse_matcher("1-1023, !22, >=60000", KIND_INT)
    pool = ([f"10.{rng.randrange(12)}.{rng.randrange(256)}.1" for _ in range(3000)]
            + [f"192.168.{rng.randrange(256)}.1" for _ in range(3000)]
            + [str(ipaddress.IPv6Address(rng.getrandbits(128))) for _ in range(2000)])
    wrong = 0
    for _ in range(30000):
        a = rng.choice(pool)
        p = rng.randrange(65536)
        wrong += ip.matches(a) != terms(ip, a)
        wrong += port.matches(p) != terms(port, p)
    check("30 000 lookups through the memory, clears included, agree with the terms",
          wrong == 0, f"({wrong} disagreed)")


def test_an_address_is_classified_once_for_lan_mode_and_internet_only(monkeypatch):
    """LAN mode and Internet only ask about the same address for every packet."""
    utils._address_class.cache_clear()
    parsed = _counting(monkeypatch, ipaddress, "ip_address")
    for _ in range(1000):
        utils.is_lan_ip("192.168.1.10")
        utils.is_local_ip("192.168.1.10")
    check("2000 questions about one address parse it once",
          parsed[0] == 1, f"(parsed {parsed[0]} times)")
    check("the address memory has a ceiling (an unbounded one is a slow leak)",
          utils._address_class.cache_info().maxsize is not None)


def _is_local_before(ip):
    """``is_local_ip`` as written before it was remembered - the reference."""
    if not ip:
        return True
    try:
        return not ipaddress.ip_address(str(ip)).is_global
    except Exception:
        return True


def _is_lan_before(ip):
    if not ip:
        return False
    try:
        address = ipaddress.ip_address(str(ip))
        return not address.is_global and not address.is_loopback
    except Exception:
        return False


def test_the_remembered_address_class_answers_as_the_old_code_did():
    """Every input the public pair can meet, before and after it was remembered."""
    utils._address_class.cache_clear()
    values = ["", None, 0, "127.0.0.1", "127.8.9.1", "::1", "10.0.0.1", "172.20.1.1",
              "192.168.1.10", "100.64.0.1", "169.254.1.1", "192.0.2.1", "8.8.8.8",
              "224.0.0.251", "0.0.0.0", "::", "fe80::1", "fd00::5", "2001:db8::1",
              "2001:4860:4860::8888", "::ffff:10.0.0.1", "::ffff:8.8.8.8", " 10.0.0.1",
              "not an address", "10.0.0.256", 167772161, ipaddress.IPv4Address("8.8.8.8"),
              ipaddress.IPv6Address("fe80::1"), ["10.0.0.1"], b"10.0.0.1", True, 1.5]
    for _ in range(2):                      # the second pass answers from memory
        for v in values:
            check(f"is_local_ip({v!r}) as before",
                  utils.is_local_ip(v) == _is_local_before(v))
            check(f"is_lan_ip({v!r}) as before", utils.is_lan_ip(v) == _is_lan_before(v))


# -- W-A5: the schedule step is found, not walked to ----------------------------- #
class _CountingList(list):
    """A schedule that counts how often somebody walks it from the start."""

    def __init__(self, items):
        super().__init__(items)
        self.walks = 0

    def __iter__(self):
        self.walks += 1
        return super().__iter__()


def _walked_rates(core, now):
    """The step lookup as it was written before - the reference."""
    pos = (now - core._sched_start) % core._sched_total
    acc = 0.0
    for dur, dn, up in core.schedule:
        acc += dur
        if pos < acc:
            return dn, up
    return core.schedule[-1][1], core.schedule[-1][2]


def test_the_schedule_step_is_found_not_walked():
    """A 1000-step schedule replayed from a trace walked 1000 steps per packet."""
    core = BeanCore()
    core.set_schedule([(0.01, 100 + i, 200 + i) for i in range(1000)])
    core.reset_buckets(0.0)
    core.schedule = _CountingList(core.schedule)
    rng = random.Random(1)
    for i in range(200):
        core._current_rates(rng.uniform(0, 30))
        core.decide(100, i % 2 == 0, 5000, rng.uniform(0, 30), rng,
                    remote_ip="1.2.3.4", remote_port=443, is_tcp=True)
    check("200 rate lookups never walk the schedule from its first step",
          core.schedule.walks == 0, f"(walked {core.schedule.walks} times)")


def test_the_found_step_is_the_step_the_walk_stopped_at():
    """Same step at every boundary, and after the schedule is replaced."""
    rng = random.Random(11)
    wrong = 0
    core = BeanCore()
    for _ in range(40):
        steps = [(rng.choice([0.01, 0.1, 1 / 3, 0.7, 2.5, rng.uniform(0.01, 5)]), i, -i)
                 for i in range(rng.randint(1, 300))]
        core.set_schedule(steps)            # the SAME core: a changed schedule replaces
        core.reset_buckets(0.0)
        ends = list(itertools.accumulate(s[0] for s in core.schedule))
        probes = [rng.uniform(0, 3 * core._sched_total) for _ in range(300)]
        probes += ends + [core._sched_total * k for k in (0, 1, 2)]
        wrong += sum(core._current_rates(p) != _walked_rates(core, p) for p in probes)
    check("40 schedules, boundaries included: the found step is the walked step",
          wrong == 0, f"({wrong} positions disagreed)")


# -- W-A7: the default path does no flow-table or schedule work ------------------ #
def _count_methods(monkeypatch, cls, names):
    counts = dict.fromkeys(names, 0)
    for name in names:
        real = getattr(cls, name)

        def counted(*args, _real=real, _name=name, **kwargs):
            counts[_name] += 1
            return _real(*args, **kwargs)
        monkeypatch.setattr(cls, name, counted)
    return counts


def _tcp_packets(core, count, start=100.0, rng=None):
    rng = rng or random.Random(4)
    for i in range(count):
        core.decide(1200, i % 2 == 0, 5000 + i % 40, start + i * 0.001, rng,
                    remote_ip="93.184.216.34", remote_port=443,
                    is_syn=(i % 50 == 0), is_tcp=True)


def test_the_default_path_does_no_flow_table_or_schedule_work(monkeypatch):
    """Nothing armed: no table to ask, no reset to look up, no schedule to read.

    Each of the three was paid on every packet (W-A7): two ``len()`` calls on empty
    flow tables, a lookup in an empty RST table, and a call for the constant rates.
    The second half arms each one and proves the counters can see the work.
    """
    tables = _count_methods(monkeypatch, core_mod._FlowTable, ("__len__", "get"))
    core_calls = _count_methods(monkeypatch, BeanCore, ("_current_rates", "_prune"))
    _tcp_packets(BeanCore(), 1000)
    check("1000 default decisions ask no flow table how long it is",
          tables["__len__"] == 0, f"({tables['__len__']} calls)")
    check("1000 default decisions look nothing up in the RST table",
          tables["get"] == 0, f"({tables['get']} calls)")
    check("1000 default decisions read no schedule",
          core_calls["_current_rates"] == 0, f"({core_calls['_current_rates']} calls)")
    check("1000 default decisions prune no table", core_calls["_prune"] == 0,
          f"({core_calls['_prune']} calls)")

    armed = BeanCore()
    armed.set_rst(30, 1.0)
    armed.set_schedule([(1.0, 100, 100)])
    armed.set_nat(30)
    _tcp_packets(armed, 200)
    check("armed, the same counters see the work (RST lookups, rates, pruning)",
          tables["get"] > 0 and core_calls["_current_rates"] > 0
          and core_calls["_prune"] > 0, f"({tables}, {core_calls})")


def test_a_reset_still_holds_down_after_the_reset_switch_goes_off():
    """The RST step is skipped only when NOTHING can hold a flow down.

    A cooldown recorded while RST was on still has to drop its flow after RST is
    switched off, and a manual reset has to fire with RST off. Both reach step 4
    only through the clauses of the new gate.
    """
    core = BeanCore()
    core.set_rst(100, 5.0)
    rng = random.Random(2)
    fired = core.decide(1200, True, 5000, 100.0, rng, remote_ip="93.184.216.34",
                        remote_port=443, is_tcp=True)
    core.set_rst(0, 5.0)
    held = core.decide(1200, True, 5000, 101.0, rng, remote_ip="93.184.216.34",
                       remote_port=443, is_tcp=True)
    check("a reset fires with RST at 100%", fired.reason == "rst" and fired.emit_rst)
    check("its cooldown still holds the flow down after RST is switched off",
          held.reason == "rst" and not held.emit_rst, f"({held})")

    manual = BeanCore()
    manual.reset_now(2.0, now=100.0)
    cut = manual.decide(1200, True, 5000, 100.5, rng, remote_ip="93.184.216.34",
                        remote_port=443, is_tcp=True)
    check("a manual reset fires with RST off", cut.reason == "rst" and cut.emit_rst)


def test_rst_cooldowns_are_still_retired_without_nat():
    """The prune gate asks about BOTH tables: RST alone must keep its table bounded."""
    core = BeanCore()
    core.set_rst(100, 0.1)
    rng = random.Random(3)
    for flow in range(10):
        for t in (100.0, 100.01):                       # the second packet prunes
            core.decide(1200, True, 6000 + flow, t, rng, remote_ip="93.184.216.34",
                        remote_port=443, is_tcp=True)
    check("ten flows were reset", len(core._reset_until) == 10,
          f"({len(core._reset_until)} recorded)")
    core.set_rst(0, 0.1)
    for second in range(101, 200):
        core.decide(1200, True, 7000, float(second), rng, remote_ip="93.184.216.34",
                    remote_port=443, is_tcp=True)
    check("with NAT off the RST table still ages out", len(core._reset_until) == 0,
          f"({len(core._reset_until)} left)")
