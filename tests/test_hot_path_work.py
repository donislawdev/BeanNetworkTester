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
import random

from fakes import check

from beantester import matchers, utils
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
