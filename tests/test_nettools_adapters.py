"""The logic behind the Tools tab's adapters - no window, runs on Linux CI.

What is pinned here: the order the table opens with (the adapter the internet goes
through first), that an index of 0 never marks an adapter as the way out, the rows
of the details table and their notes, the report's text, and that every word the
logic can hand the window has a text in every language.
"""
import json
import os

from beantester import adapters as system
from beantester.adapters import AdapterRow, AddressRow, Reading
from beantester.nettools import adapters
from beantester.nettools.adapters import Words
from fakes import ROOT, check


def _row(key, index, ipv6_index=0, status=1, kind=6, name=None, addresses=(), **more):
    fields = dict(key=key, if_index=index, ipv6_index=ipv6_index, name=name or key,
                  description="", kind=kind, status=status, mac="", mtu=1500,
                  receive_bps=None, transmit_bps=None, dhcp=False, dhcp_server="",
                  addresses=tuple(addresses), gateways=(), dns_servers=(), dns_suffix="",
                  ipv4_metric=None, ipv6_metric=None)
    fields.update(more)
    return AdapterRow(**fields)


V4 = AddressRow("192.168.1.5", 4, 24, 3, 3, 4)
DOWN, VPN, WIFI, ETH = (_row("down", 21, status=2, kind=53),
                        _row("vpn", 30, ipv6_index=30, kind=131),
                        _row("wifi", 12, kind=71, addresses=(V4,)),
                        _row("eth", 9, kind=6))


def test_the_list_opens_with_the_way_out_then_what_is_up_then_the_rest():
    reading = Reading((DOWN, VPN, WIFI, ETH), {4: 12, 6: 0})
    ranked = adapters.rank(reading)
    check("internet first, then up in the system's order, then down",
          [a.key for a in ranked] == ["wifi", "vpn", "eth", "down"],
          f"({[a.key for a in ranked]})")
    check("the rank is the position", [a.rank for a in ranked] == [0, 1, 2, 3])
    check("the way out is marked for its IP version",
          ranked[0].internet == (4,) and all(a.internet == () for a in ranked[1:]),
          f"({[(a.key, a.internet) for a in ranked]})")


def test_an_index_of_zero_never_marks_an_adapter():
    """Without an IPv6 route the system leaves the index at 0 (measured), and every
    adapter without IPv6 has an IPv6 index of 0 - they must not meet."""
    reading = Reading((DOWN, ETH), {4: 0, 6: 0})
    check("no route at all: no adapter is the way out",
          all(a.internet == () for a in adapters.rank(reading)))
    both = Reading((VPN,), {4: 30, 6: 30})
    check("one adapter can be the way out for both versions",
          adapters.rank(both)[0].internet == (4, 6))


def test_a_header_click_sorts_and_the_ranking_breaks_ties():
    ranked = adapters.rank(Reading((DOWN, VPN, WIFI, ETH), {4: 12}))
    by_kind = [a.key for a in adapters.sort(ranked, "kind")]
    check("by type number", by_kind == ["eth", "down", "wifi", "vpn"], f"({by_kind})")
    by_ip = [a.key for a in adapters.sort(ranked, "ipv4")]
    check("an adapter without IPv4 sorts last", by_ip == ["wifi", "vpn", "eth", "down"],
          f"({by_ip})")
    by_ip_down = [a.key for a in adapters.sort(ranked, "ipv4", reverse=True)]
    check("in both directions", by_ip_down[0] == "wifi", f"({by_ip_down})")
    check("the default order is the ranking, and reverses",
          [a.key for a in adapters.sort(ranked)] == ["wifi", "vpn", "eth", "down"]
          and [a.key for a in adapters.sort(ranked, reverse=True)][0] == "down")
    by_status = [a.key for a in adapters.sort(ranked, "status")]
    check("up before down, the ranking within each", by_status == ["wifi", "vpn", "eth", "down"],
          f"({by_status})")


def _details(row, routes=None):
    adapter = adapters.rank(Reading((row,), routes or {}))[0]
    return {d.key: d for d in adapters.details(adapter)}


def test_the_details_say_what_ipconfig_says_and_what_each_address_is():
    row = _row("eth", 9, ipv6_index=9, name="Ethernet", description="Intel",
               addresses=(V4, AddressRow("fe80::1%9", 6, 64, 2, 4, 1),
                          AddressRow("10.0.0.7", 4, 8, 1, 1, 2)),
               gateways=("192.168.1.1", "fe80::1%9"),
               dns_servers=("1.1.1.1", "fec0:0:0:ffff::1%1"), dhcp=True,
               dhcp_server="192.168.1.1", mac="AA-BB", receive_bps=10 ** 9,
               transmit_bps=10 ** 8, ipv4_metric=35)
    rows = _details(row, {4: 9})
    check("the address with its prefix, its origin as a word",
          rows["address|0"].value == "192.168.1.5/24"
          and rows["address|0"].note == (Words("tools.adapters.origin.dhcp"),), f"({rows})")
    check("a state other than preferred is said next to it",
          rows["address|1"].note == (Words("tools.adapters.origin.well_known"),
                                     Words("tools.adapters.dad.tentative")))
    check("a duplicate address is coloured and named",
          rows["address|2"].tag == "duplicate"
          and Words("tools.adapters.dad.duplicate") in rows["address|2"].note)
    check("a gateway can be limited to - without its IPv6 zone",
          (rows["gateway|0"].address, rows["gateway|1"].address) == ("192.168.1.1", "fe80::1"))
    check("a real DNS server can be limited to",
          rows["dns|0"].address == "1.1.1.1" and not rows["dns|0"].note)
    check("Windows' placeholder DNS is named for what it is and not offered",
          rows["dns|1"].address == "" and rows["dns|1"].note
          == (Words("tools.adapters.dns_placeholder"),), f"({rows['dns|1']})")
    check("the way out", rows["internet"].value == "IPv4", f"({rows['internet']})")
    check("speeds that differ are both shown", rows["speed"].value == "1 Gbit/s / 100 Mbit/s",
          f"({rows['speed'].value!r})")
    check("an IPv6 metric the record did not carry is left out",
          "metric_v6" not in rows and rows["metric_v4"].value == "35")
    check("the index pair", rows["index"].value == "9 / 9")


def test_an_adapter_with_nothing_set_says_so_instead_of_showing_blanks():
    rows = _details(_row("bare", 4))
    check("no address: one row that says none",
          rows["address"].value == Words("tools.adapters.value.none"))
    check("empty values are left out, not shown blank",
          not {"mac", "dns_suffix", "dhcp_server", "speed", "metric_v4"} & set(rows),
          f"({sorted(rows)})")
    check("no way out", rows["internet"].value == Words("tools.adapters.value.no"))
    check("no IPv6 index", rows["index"].value == "4 / -")


def test_speeds_read_in_the_unit_that_fits():
    cases = {10 ** 9: "1 Gbit/s", 1073741824: "1.07 Gbit/s", 10 ** 8: "100 Mbit/s",
             54 * 10 ** 6: "54 Mbit/s", 9600: "9.6 kbit/s", 300: "300 bit/s",
             0: "", 2 ** 64 - 1: "", None: ""}
    got = {bps: adapters.speed_text(bps) for bps in cases}
    check("each speed", got == cases, f"({got})")


def test_a_number_the_tables_do_not_name_is_shown_as_a_number():
    check("an unknown status", adapters.status_words(42) == Words("tools.adapters.status.code", 42))
    check("an unknown type", adapters.kind_words(209) == Words("tools.adapters.kind.code", 209))
    check("a known one", adapters.kind_words(71) == Words("tools.adapters.kind.wifi"))


def test_every_word_the_logic_can_give_has_a_text_in_every_language():
    """The keys are built from tables at run time, so the scan of literal keys in
    ``test_i18n.py`` sees only their prefixes - this walks the tables."""
    keys = {adapters.status_words(n).key for n in list(adapters.STATUS) + [99]}
    keys |= {adapters.kind_words(n).key for n in list(adapters.KINDS) + [999]}
    keys |= {f"tools.adapters.origin.{slug}" for slug in adapters.ORIGINS.values()}
    keys |= {f"tools.adapters.dad.{slug}" for slug in adapters.DAD.values()
             if slug != "preferred"}
    row = _row("all", 1, 1, addresses=(V4,), gateways=("1.2.3.4",), dns_servers=("5.6.7.8",),
               dhcp_server="1.2.3.4", dns_suffix="x", mac="AA", receive_bps=1,
               ipv4_metric=1, ipv6_metric=1)
    for detail in adapters.details(adapters.rank(Reading((row,), {}))[0]):
        keys |= {part.key for part in (detail.item, detail.value, *detail.note)
                 if isinstance(part, Words)}
    check("the walk found the words", len(keys) >= 40, f"({len(keys)})")
    for lang in ("en", "pl", "zh"):
        with open(os.path.join(ROOT, "lang", f"{lang}.json"), encoding="utf-8") as handle:
            texts = json.load(handle)
        missing = sorted(k for k in keys if k not in texts)
        check(f"{lang}: every word has a text", not missing, f"({missing})")


def test_the_report_is_one_block_per_adapter_in_plain_english():
    row = _row("eth", 9, ipv6_index=9, name="Ethernet", description="Intel",
               addresses=(V4, AddressRow("fe80::1%9", 6, 64, 2, 4, 2)),
               gateways=("192.168.1.1",), dns_servers=("fec0:0:0:ffff::1%1",), dhcp=True,
               dhcp_server="192.168.1.1", mac="AA-BB", receive_bps=10 ** 9,
               transmit_bps=10 ** 9, ipv4_metric=35, dns_suffix="home")
    snapshot = adapters.Snapshot(adapters.rank(Reading((row, DOWN), {4: 9})), 0.0, 3, 1)
    lines = adapters.report_lines(snapshot)
    check("a head line with the count", lines[0].startswith("network adapters: 2, read "),
          f"({lines[0]!r})")
    want = ["Ethernet (Intel)",
            "  status: up, type: ethernet (6), internet: IPv4",
            "  IPv4: 192.168.1.5/24 (dhcp)",
            "  IPv6: fe80::1%9/64 (well known, duplicate)",
            "  gateway: 192.168.1.1",
            "  DNS: fec0:0:0:ffff::1%1 (Windows placeholder)",
            "  DHCP: on, server 192.168.1.1",
            "  DNS suffix: home",
            "  MAC: AA-BB",
            "  MTU: 1500, speed: 1 Gbit/s",
            "  metric: 35 / -, index: 9 / 9"]
    check("the first adapter, line by line", lines[1:12] == want,
          "\n" + "\n".join(lines[1:12]))
    check("then the second: its name alone without a description, its type by name and number",
          lines[12] == "down" and lines[13].startswith("  status: down, type: virtual (53)"),
          f"({lines[12:14]})")
    check("the text is the lines joined", adapters.report(snapshot) == "\n".join(lines))


def test_a_list_the_system_cannot_give_is_said_in_the_windows_language(monkeypatch):
    def refused(native=None):
        raise system.AdaptersUnavailable("not_ready", "GetAdaptersAddresses answered 1228")
    monkeypatch.setattr(system, "read", refused)
    try:
        adapters.read()
    except adapters.Unreadable as exc:
        check("the person's reason", exc.user_key == "tools.adapters.error_not_ready")
        check("the program's words kept", "1228" in str(exc))
    else:
        raise AssertionError("a refused list must not read as an empty one")


def test_a_read_is_ranked_and_counted(monkeypatch):
    monkeypatch.setattr(system, "read", lambda native=None: Reading((DOWN, ETH), {4: 9}))
    first, second = adapters.read(), adapters.read()
    check("ranked", [a.key for a in first.adapters] == ["eth", "down"])
    check("the newer snapshot is counted, not timed", second.made > first.made)
