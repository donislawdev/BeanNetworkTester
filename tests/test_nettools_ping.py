"""``beantester/nettools/ping.py``: what Ping is asked, keeps and says - no window.

The promise this tool is held to (README, "Tools") is that it sends echo requests to
the address the person typed, and nothing anywhere else. So the first tests are about
what NEVER reaches the name lookup: a text that is not plainly an address or a host
name is refused before anything could put a DNS query for it on the wire.
"""
import json
import os
import socket
import sys

import pytest

from beantester import icmp, icmpsock
from beantester.nettools import Refused, ping
from beantester.nettools.adapters import Words
from fakes import LANGS, ROOT, check

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
    ("fe80::1%nosuch0", "tools.ping.refused.bad_address"),
    ("2001:db8::zz", "tools.ping.refused.bad_address"),
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


def test_a_named_zone_is_an_interface_on_linux_and_nowhere_on_windows(monkeypatch):
    """Windows numbers its zones (fe80::1%12); on Linux the person types the
    interface's name (fe80::1%eth0) - taken when this machine has it."""
    monkeypatch.setattr(icmpsock, "zone_index", lambda name: {"eth0": 2}.get(name))
    monkeypatch.setattr(sys, "platform", "linux")
    target = ping.parse("fe80::1%eth0")
    check("Linux: kept as typed", target == ping.Target("fe80::1%eth0", "", "fe80::1%eth0"),
          f"({target})")
    with pytest.raises(Refused):
        ping.parse("fe80::1%wlan9")
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(Refused) as refused:
        ping.parse("fe80::1%eth0")
    check("Windows: no such zone", refused.value.user_key == "tools.ping.refused.bad_address")


def test_what_linux_said_is_shown_and_reported_in_its_own_name():
    echo = icmp.Echo(icmp.IP_GENERAL_FAILURE, reply_from="192.0.2.1", said="EPERM")
    check("the Result column", ping.result_words(echo) == Words("tools.ping.result.linux",
                                                                 "EPERM"))
    check("Windows' number keeps its own", ping.result_words(icmp.Echo(11042))
          == Words("tools.ping.result.code", 11042))
    run = ping.Run(ping.Target("192.0.2.10", "", "192.0.2.10"), started=0.0)
    run.add(1.0, echo)
    run.add(2.0, icmp.Echo(11042))
    text = ping.report(run)
    check("the report says who answered", "Linux answered EPERM" in text
          and "Windows answered 11042" in text, text)


@pytest.mark.parametrize("platform, keys", [
    ("win32", ping.WINDOWS_HELP), ("linux", ping.LINUX_HELP), ("darwin", ())])
def test_the_sheet_has_a_paragraph_about_the_system_it_runs_on(monkeypatch, platform, keys):
    monkeypatch.setattr(sys, "platform", platform)
    check(f"{platform}", ping.platform_help() == keys, f"({ping.platform_help()})")


def test_no_ping_text_linux_shows_names_windows():
    """Every Ping text on screen on Linux, in every language: only the paragraph about
    Windows' wait and the words for a number Windows answered are Windows' own, and
    Linux never shows them. The Linux paragraph says how to get the right to send."""
    windows_only = {"tools.ping.help_windows", "tools.ping.result.code"}
    for code in LANGS:
        with open(os.path.join(ROOT, "lang", f"{code}.json"), encoding="utf-8") as f:
            texts = json.load(f)
        shown = {k: v for k, v in texts.items() if (k.startswith(("tools.ping.", "tips.tools_ping_"))
                                                    and k not in windows_only)}
        check(f"{code}: Ping's texts were found", len(shown) > 40, f"({len(shown)})")
        named = [k for k, v in shown.items() if "Windows" in v]
        check(f"{code}: none names Windows", not named, f"({named})")
        linux = texts["tools.ping.help_linux"]
        check(f"{code}: the Linux paragraph says how", "sudo" in linux
              and "net.ipv4.ping_group_range" in linux, f"({linux})")
        # sudo is not enough without CAP_NET_RAW, and a refused ping shows Linux's word
        check(f"{code}: and what sudo needs, and what EPERM and ICMP 3/13 mean",
              "CAP_NET_RAW" in linux and "EPERM" in linux and "ICMP 3/13" in linux, f"({linux})")


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
    monkeypatch.setattr(icmp, "echo", lambda address, timeout, system=None, size=32: (
        sent.append((str(address), timeout, size)), REPLY)[1])
    target, echo = ping.start_and_send(ping.parse("example.com"), 4,
                                       lookup=lambda n: [(socket.AF_INET, 0, 0, "",
                                                          ("192.0.2.10", 0))], size=1372)
    check("pinged where the lookup said, waiting 4 s, with the size asked for",
          sent == [("192.0.2.10", 4000, 1372)], f"({sent})")
    check("and the address is kept for the next ones", target.address == "192.0.2.10")
    check("the answer comes back", echo == REPLY)
    ping.send(target, 1)
    check("ping.exe's 32 bytes unless asked", sent[-1] == ("192.0.2.10", 1000, 32), f"({sent})")


def test_a_request_no_longer_wanted_before_or_after_the_lookup_sends_nothing(monkeypatch):
    """Stop pressed while the request waited for the worker: no lookup, no echo. Stop
    pressed during the lookup: the lookup was already asked, the echo is not."""
    sent, looked = [], []
    monkeypatch.setattr(icmp, "echo", lambda address, timeout, system=None, size=32: (
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
    check("what and where", lines[0].startswith(
        "Ping example.com (192.0.2.10): 32 bytes every 0.5 s, waiting up to 4 s, started"),
          f"({lines[0]})")
    check("the one part it was", lines[1].startswith("--- from ")
          and lines[1].endswith(", no session"), f"({lines[1]})")
    check("a row per ping", len([line for line in lines if line.lstrip()[:1].isdigit()]) == 4,
          text)
    check("in English, with who answered", "< 1 ms" in text and "no reply" in text
          and "TTL expired in transit  from 198.51.100.1" in text
          and "reply came back changed" in text, text)
    check("the totals", "sent 4, replies 2, lost 2 (50.0%), at most 2 lost in a row, "
                        "1 came back changed" in text, text)
    check("the round trips", "round trip: lowest < 1, average 100, highest 201 ms, "
                             "jitter 201 ms, 95% within 201 ms" in text, text)
    check("one part: no part's numbers apart from the run's", "the whole run" not in text, text)
    asked = ping.Run(ping.parse("192.0.2.10"), every_s=1, wait_s=2, size=1372, count=100)
    check("the size and the number asked for", ping.report(asked).startswith(
        "Ping 192.0.2.10: 1372 bytes every 1 s, waiting up to 2 s, 100 pings, started"),
          ping.report(asked))


START = (1, "START", "filter=both, seed=7")
CHANGE = (2, "CHANGE", "latency 100 ms")
STOP = (3, "STOP", "events.stopped")


def test_a_run_is_cut_into_parts_where_the_session_changed():
    """Start, a session started, its settings applied, it stopped: four parts, each
    with its own numbers - and the ping that was out while the session started is a
    row and a ping of the run, but in no part."""
    run = ping.Run(ping.parse("192.0.2.10"), started=0.0)
    for i in range(3):
        run.add(float(i), icmp.Echo(0, 1, 64, "192.0.2.10"))
    run.add(3.0, icmp.Echo(0, 150, 64, "192.0.2.10"), None, START)       # out across it
    for i in range(4, 7):
        run.add(float(i), icmp.Echo(0, 201, 64, "192.0.2.10"), START, START)
    run.add(7.0, LOST, START, START)
    run.add(8.0, icmp.Echo(0, 401, 64, "192.0.2.10"), CHANGE, CHANGE)
    run.add(9.0, icmp.Echo(0, 2, 64, "192.0.2.10"), STOP, STOP)
    check("four parts, by what the session did",
          [p.kind for p in run.parts] == ["none", "start", "change", "stop"],
          f"({[p.kind for p in run.parts]})")
    check("each counts its own", [p.stats.sent for p in run.parts] == [3, 4, 1, 1]
          and run.parts[1].stats.round_trips() == (201, 201, 201)
          and run.parts[1].stats.lost == 1, f"({[p.stats.sent for p in run.parts]})")
    check("the ping across the change: a row of the run, in no part",
          run.sent == 10 and not run.results[3].counted and run.results[3].part == 0
          and all(r.counted for i, r in enumerate(run.results) if i != 3))
    check("a part begins where its first ping went", run.parts[1].started == 4.0)
    check("the chart marks the first ping of each part after the first",
          run.chart_changes() == [4, 8, 9], f"({run.chart_changes()})")
    check("the engine's words for the settings - never a STOP's reason name",
          [p.settings for p in run.parts] == ["", "filter=both, seed=7", "latency 100 ms", ""])
    text = ping.report(run)
    check("the report heads each part and says its settings",
          "session running: filter=both, seed=7" in text and "changes applied: latency 100 ms"
          in text and ", session stopped" in text and "events.stopped" not in text, text)
    check("and marks the ping that was out across the change",
          "(the session changed while it was out: in no part)" in text, text)
    check("then each part's numbers and the run's", text.count("part from ") == 4
          and "the whole run:" in text and "sent 10, replies 9, lost 1 (10.0%)" in text, text)


def test_jitter_the_95th_percentile_and_the_longest_run_of_losses():
    stats = ping.Stats()
    check("nothing yet: none of them", (stats.jitter(), stats.p95(), stats.round_trips(),
                                        stats.longest_loss) == (None, None, None, 0))
    stats.add(icmp.Echo(0, 100, 64, "x"))
    check("one reply: a percentile, no jitter", (stats.jitter(), stats.p95()) == (None, 100))
    for rtt in (110, 100, 130):         # moves of 10, 10 and 30: 50 / 3
        stats.add(icmp.Echo(0, rtt, 64, "x"))
    check("jitter: the mean move from one reply to the next", stats.jitter() == 17,
          f"({stats.jitter()})")
    for echo in (LOST, LOST, icmp.Echo(0, 120, 64, "x"), LOST):
        stats.add(echo)
    check("a lost ping between two replies does not part them (moves 10, 10, 30, 10)",
          stats.jitter() == 15, f"({stats.jitter()})")
    check("the longest run of losses, not the last", stats.longest_loss == 2)
    spread = ping.Stats()
    for rtt in range(1, 101):
        spread.add(icmp.Echo(0, rtt, 64, "x"))
    check("95 of 100 replies took 95 ms or less", spread.p95() == 95, f"({spread.p95()})")
    spread.add(icmp.Echo(0, 5000, 64, "x"))
    check("one slow reply moves the highest, not the 95th", spread.p95() == 96
          and spread.round_trips()[2] == 5000, f"({spread.p95()})")


@pytest.mark.parametrize("typed, size", [("32", 32), (" 0 ", 0), ("65500", 65500),
                                         ("01372", 1372)])
def test_a_size_is_whole_bytes_up_to_ping_exes_largest(typed, size):
    check(f"{typed!r} -> {size}", ping.parse_size(typed) == size)


@pytest.mark.parametrize("typed", ["", "-1", "1.5", "65501", "100000", "²", "abc", "1e3",
                                   "+5"])
def test_a_size_that_is_not_whole_bytes_up_to_the_largest_is_refused(typed):
    with pytest.raises(Refused) as refused:
        ping.parse_size(typed)
    check("said with what was typed and the largest",
          refused.value.user_key == "tools.ping.refused.size"
          and refused.value.user_args == {"typed": typed.strip(), "most": ping.MAX_SIZE},
          f"({refused.value.user_args})")


def test_a_run_asked_for_a_number_of_pings_is_done_after_the_last():
    run = ping.Run(ping.parse("192.0.2.10"), count=3)
    for _ in range(2):
        run.add(0.0, REPLY)
    check("not before", not run.done())
    run.add(0.0, LOST)
    check("done on the third, lost or not", run.done())
    endless = ping.Run(ping.parse("192.0.2.10"))
    for _ in range(1001):
        endless.add(0.0, REPLY)
    check("until Stop: never done", not endless.done())
