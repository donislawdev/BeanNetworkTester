"""``beantester/nettools/ping.py``: what Ping is asked, keeps and says - no window.

The promise this tool is held to (README, "Tools") is that it sends echo requests to
the address the person typed, and nothing anywhere else. So the first tests are about
what NEVER reaches the name lookup: a text that is not plainly an address or a host
name is refused before anything could put a DNS query for it on the wire.
"""
import socket

import pytest

from beantester import icmp
from beantester.nettools import Refused, ping
from fakes import check

REPLY = icmp.Echo(0, 201, 64, "192.0.2.10")
LOST = icmp.Echo(icmp.IP_REQ_TIMED_OUT)


@pytest.mark.parametrize("typed, address", [
    ("192.0.2.10", "192.0.2.10"), ("  192.0.2.10 ", "192.0.2.10"), ("::1", "::1"),
    ("2001:DB8::7", "2001:db8::7"), ("fe80::1%12", "fe80::1%12"), ("127.0.0.1", "127.0.0.1"),
])
def test_an_address_is_pinged_as_typed_and_looked_up_nowhere(typed, address):
    target = ping.parse(typed)
    check("no name to look up", target.name == "" and target.address == address, f"({target})")
    asked = []
    check("resolve leaves it alone", ping.resolve(target, lambda n: asked.append(n)) == target)
    check("and asks nobody", asked == [])


@pytest.mark.parametrize("typed, name", [
    ("example.com", "example.com"), ("Example.COM.", "example.com"),
    ("zażółć.pl", "xn--za-6ja4f8n1l.pl"), ("host_1.local", "host_1.local"),
    ("localhost", "localhost"),
])
def test_a_host_name_is_kept_for_the_lookup(typed, name):
    target = ping.parse(typed)
    check("a name, nothing pinged yet", target.name == name and target.address == "",
          f"({target})")


@pytest.mark.parametrize("typed, key", [
    ("", "tools.ping.refused.empty"), ("   ", "tools.ping.refused.empty"),
    ("999.1.1.1", "tools.ping.refused.bad_address"), ("127.1", "tools.ping.refused.bad_address"),
    ("0x7f.1", "tools.ping.refused.bad_address"), ("1.2.3.4.5", "tools.ping.refused.bad_address"),
    ("fe80::1%eth0", "tools.ping.refused.bad_address"), ("2001:db8::zz", "tools.ping.refused.bad_address"),
    ("0.0.0.0", "tools.ping.refused.not_one"), ("::", "tools.ping.refused.not_one"),
    ("224.0.0.1", "tools.ping.refused.not_one"), ("ff02::1", "tools.ping.refused.not_one"),
    ("255.255.255.255", "tools.ping.refused.not_one"),
    ("a..b", "tools.ping.refused.bad_name"), ("-a.com", "tools.ping.refused.bad_name"),
    ("x" * 64 + ".com", "tools.ping.refused.bad_name"), ("a b.com", "tools.ping.refused.bad_name"),
    ("a" * 250 + ".com", "tools.ping.refused.bad_name"),
])
def test_what_is_not_one_address_or_name_is_refused_before_any_lookup(typed, key):
    with pytest.raises(Refused) as refused:
        ping.parse(typed)
    check("refused with its reason", refused.value.user_key == key,
          f"({typed!r}: {refused.value.user_key})")


def test_a_name_is_looked_up_once_and_the_first_answer_in_windows_order_wins():
    asked = []

    def lookup(name):
        asked.append(name)
        return [(socket.AF_INET6, 0, 0, "", ("2001:db8::7", 0, 0, 0)),
                (socket.AF_INET, 0, 0, "", ("192.0.2.10", 0))]

    target = ping.resolve(ping.parse("Example.com"), lookup)
    check("the first answer, IPv6 here", target.address == "2001:db8::7", f"({target})")
    check("asked once, for the IDNA name", asked == ["example.com"], f"({asked})")
    zone = ping.resolve(ping.parse("router.local"),
                        lambda n: [(socket.AF_INET6, 0, 0, "", ("fe80::1", 0, 0, 12))])
    check("a link-local answer keeps its zone", zone.address == "fe80::1%12", f"({zone})")


@pytest.mark.parametrize("answer", [socket.gaierror(11001, "not found"), UnicodeError("idna"),
                                    []])
def test_a_name_windows_cannot_find_is_said_in_words(answer):
    def lookup(name):
        if isinstance(answer, Exception):
            raise answer
        return answer

    with pytest.raises(Refused) as refused:
        ping.resolve(ping.parse("nowhere.example"), lookup)
    check("not found, with the name typed", refused.value.user_key == "tools.ping.refused.not_found"
          and refused.value.user_args == {"name": "nowhere.example"}, f"({refused.value.user_args})")


def test_the_first_request_looks_the_name_up_then_sends_to_that_address(monkeypatch):
    sent = []
    monkeypatch.setattr(icmp, "echo", lambda address, timeout, system=None: (
        sent.append((str(address), timeout)), REPLY)[1])
    target, echo = ping.start_and_send(ping.parse("example.com"), 4,
                                       lookup=lambda n: [(socket.AF_INET, 0, 0, "",
                                                          ("192.0.2.10", 0))])
    check("pinged where the lookup said, waiting 4 s", sent == [("192.0.2.10", 4000)], f"({sent})")
    check("and the address is kept for the next ones", target.address == "192.0.2.10")
    check("the answer comes back", echo == REPLY)


def test_a_request_no_longer_wanted_before_or_after_the_lookup_sends_nothing(monkeypatch):
    """Stop pressed while the request waited for the worker: no lookup, no echo. Stop
    pressed during the lookup: the lookup was already asked, the echo is not."""
    sent, looked = [], []
    monkeypatch.setattr(icmp, "echo", lambda address, timeout, system=None: (
        sent.append(str(address)), REPLY)[1])

    def lookup(name):
        looked.append(name)
        return [(socket.AF_INET, 0, 0, "", ("192.0.2.10", 0))]
    target, echo = ping.start_and_send(ping.parse("example.com"), 4, lookup=lookup,
                                       wanted=lambda: False)
    check("stopped before it began: nothing asked of anyone",
          looked == [] and sent == [] and echo is None and not target.address,
          f"({looked}, {sent}, {echo})")
    answers = iter((True, False))
    target, echo = ping.start_and_send(ping.parse("example.com"), 4, lookup=lookup,
                                       wanted=lambda: next(answers))
    check("stopped during the lookup: looked up, nothing sent",
          looked == ["example.com"] and sent == [] and echo is None, f"({looked}, {sent})")
    check("and the address it found is kept", target.address == "192.0.2.10")


def test_a_run_counts_every_ping_and_keeps_the_last_ones():
    run = ping.Run(ping.parse("192.0.2.10"), every_s=1, wait_s=4, started=1000.0)
    for i in range(10):
        run.add(1000.0 + i, LOST if i in (3, 7) else icmp.Echo(0, 200 + i, 64, "192.0.2.10"))
    check("sent, replies, lost", (run.sent, run.replies, run.lost) == (10, 8, 2))
    check("lost share", run.lost_pct() == 20.0)
    # 200..209 without the two lost (203, 207): 1635 / 8 = 204.4
    check("lowest, average, highest over the replies", run.round_trips() == (200, 204, 209),
          f"({run.round_trips()})")
    chart = run.chart()
    check("charted with a gap where nothing came back", chart[3] is None and chart[7] is None
          and chart[0] == 200 and len(chart) == 10, f"({chart})")
    check("numbered from 1", [r.seq for r in run.results][:3] == [1, 2, 3])
    long = ping.Run(ping.parse("192.0.2.10"))
    for i in range(ping.KEPT + 5):
        long.add(float(i), REPLY)
    check("rows kept up to KEPT, totals count all", len(long.results) == ping.KEPT
          and long.sent == ping.KEPT + 5 and long.results[0].seq == 6)
    check("charted: the last CHARTED", len(long.chart()) == ping.CHARTED)
    check("no replies yet: no round trips", ping.Run(ping.parse("::1")).round_trips() is None)


def test_the_next_request_waits_for_the_pace_and_for_the_answer():
    run = ping.Run(ping.parse("192.0.2.10"), every_s=1)
    check("a quick answer: a pace after the last request", run.next_at(100.0, 100.2) == 101.0)
    check("a slow answer: right after it, never two out at once",
          run.next_at(100.0, 103.5) == 103.5)


def test_what_came_back_is_said_in_words():
    words = {icmp.Echo(0, 5, 64, "x"): "tools.ping.result.reply",
             icmp.Echo(0, 5, 64, "x", True): "tools.ping.result.changed",
             LOST: "tools.ping.result.lost",
             icmp.Echo(icmp.IP_TTL_EXPIRED_TRANSIT, reply_from="198.51.100.1"):
                 "tools.ping.result.ttl_expired",
             icmp.Echo(icmp.ERROR_NETWORK_UNREACHABLE): "tools.ping.result.net_unreachable",
             icmp.Echo(icmp.IP_DEST_HOST_UNREACHABLE): "tools.ping.result.host_unreachable"}
    for echo, key in words.items():
        check(f"{echo.status} -> {key}", ping.result_words(echo).key == key)
    unknown = ping.result_words(icmp.Echo(11042))
    check("an unnamed status keeps its number",
          (unknown.key, unknown.code) == ("tools.ping.result.code", 11042), f"({unknown})")
    target = ping.Target("192.0.2.10", "", "192.0.2.10")
    check("a router's answer is someone else's",
          ping.answered_by_other(icmp.Echo(11013, reply_from="198.51.100.1"), target))
    check("the address itself is not", not ping.answered_by_other(REPLY, target))
    check("nor is a reply without an address", not ping.answered_by_other(LOST, target))
    zoned = ping.Target("fe80::1%12", "", "fe80::1%12")
    check("a zone is not a different address",
          not ping.answered_by_other(icmp.Echo(0, 0, None, "fe80::1"), zoned))
    check("whole milliseconds, 0 is under one", (ping.rtt_number(0), ping.rtt_number(7))
          == ("< 1", "7"))


def test_the_copied_report_says_what_was_asked_and_what_came_back():
    run = ping.Run(ping.Target("example.com", "example.com", "192.0.2.10"), every_s=0.5,
                   wait_s=4, started=0.0)
    run.add(1.0, icmp.Echo(0, 0, 64, "192.0.2.10"))
    run.add(2.0, LOST)
    run.add(3.0, icmp.Echo(icmp.IP_TTL_EXPIRED_TRANSIT, reply_from="198.51.100.1"))
    run.add(4.0, icmp.Echo(0, 201, 64, "192.0.2.10", True))
    text = ping.report(run)
    lines = text.splitlines()
    check("what and where", lines[0].startswith("Ping example.com (192.0.2.10): every 0.5 s, "
                                                "waiting up to 4 s"), f"({lines[0]})")
    check("a row per ping", len([line for line in lines if line.lstrip()[:1].isdigit()]) == 4,
          text)
    check("in English, with who answered", "< 1 ms" in text and "no reply" in text
          and "TTL expired in transit  from 198.51.100.1" in text
          and "reply came back changed" in text, text)
    check("the totals", "sent 4, replies 2, lost 2 (50.0%), 1 came back changed" in text, text)
    check("the round trips", "round trip: lowest < 1, average 100, highest 201 ms" in text, text)
