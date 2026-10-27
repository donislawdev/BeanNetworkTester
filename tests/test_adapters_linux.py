"""``adapters._Linux``: the Adapters tool's rows from a Linux kernel's own tables.

The kernel's answers are a real kernel's (``tests/data/rtnetlink``, see
``test_rtnetlink.py``); sysfs and the resolver's files are written into a temporary
root, so every row is made here on any runner. ``paths.read_small_file``, which reads
those files, is tested at the end.
"""
import os
import struct
import sys

import pytest

from beantester import adapters, paths, rtnetlink
from beantester.nettools import adapters as logic
from fakes import check
from test_rtnetlink import BY_LABEL, kernel, route_answer


def _write(root, relative, text):
    path = os.path.join(root, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _lookup(ip, oif):
    """The request ``route_to(ip)`` sends, and the kernel's answer through ``oif``."""
    sent = []
    rtnetlink.route_to(ip, lambda m: sent.append(m) or [(2, struct.pack("=i", -101))])
    return {sent[0]: route_answer(oif, rtnetlink.LINUX_AF_INET6 if ":" in ip else
                                  rtnetlink.LINUX_AF_INET)}


def rows(tmp_path, extra=None):
    reading = adapters.read(adapters._Linux(kernel(extra), root=str(tmp_path)))
    return {row.name: row for row in reading.adapters}, reading


def test_linux_rows_read_as_the_kernel_holds_them(tmp_path):
    _write(str(tmp_path), "sys/class/net/bv0/speed", "10000\n")
    _write(str(tmp_path), "sys/class/net/br0/speed", "10000\n")     # down: not shown
    found, reading = rows(tmp_path)
    check("every adapter, in the kernel's order", list(found) ==
          ["lo", "bv0", "dm0", "br0", "dm1", "dm0.7", "tn0", "wg0"], f"({list(found)})")
    lo, bv0, dm0, br0, wg0 = (found[n] for n in ("lo", "bv0", "dm0", "br0", "wg0"))
    check("the loopback: up, its kind, no MAC (six zeros)",
          (lo.status, lo.kind, lo.mac) == (1, 24, ""))
    check("UNKNOWN with its link is up (dummy, WireGuard); a bridge with nothing is down",
          (dm0.status, wg0.status, br0.status) == (1, 1, 2))
    check("a veth: virtual, its MAC as ip writes it, 10 Gbit/s",
          (bv0.kind, bv0.description, bv0.receive_bps, bv0.transmit_bps)
          == (53, "veth", 10 ** 10, 10 ** 10) and bv0.mac.count(":") == 5
          and bv0.mac == bv0.mac.lower(), f"({bv0})")
    check("no speed for an adapter that is down", br0.receive_bps is None)
    check("tun and WireGuard are tunnels without a MAC",
          (found["tn0"].kind, wg0.kind, wg0.mac) == (131, 131, ""))
    check("the key is the name, never the proxy row's",
          [r.key for r in found.values()][:2] == ["if:lo", "if:bv0"])
    check("each adapter's default gateways, IPv4 before IPv6",
          (bv0.gateways, dm0.gateways) == (("198.51.100.1", "2001:db8:1::1"), ("203.0.113.254",)))
    check("the metric is the default route's",
          (bv0.ipv4_metric, bv0.ipv6_metric, dm0.ipv4_metric, dm0.ipv6_metric)
          == (100, 1024, 200, None))
    check("DHCP: a lease or a route from DHCP; neither on dm0", (bv0.dhcp, dm0.dhcp) == (True, False))
    check("one index for both versions, 0 without an IPv6 address",
          (bv0.if_index, bv0.ipv6_index, br0.ipv6_index) == (2, 2, 0))
    check("what Linux keeps for NetworkManager is not shown",
          (bv0.dhcp_server, bv0.dns_suffix) == ("", ""))
    check("the route out, for both versions", reading.internet == {4: 2, 6: 2})


def test_linux_says_where_each_address_came_from_and_its_dad_state(tmp_path):
    found, _ = rows(tmp_path)
    by_ip = {a.ip: a for row in found.values() for a in row.addresses}
    check("set by hand (permanent)", by_ip["198.51.100.2"].origin == adapters.ORIGIN_MANUAL)
    check("a lease on IPv4 is DHCP's", by_ip["198.51.100.3"].origin == adapters.ORIGIN_DHCP)
    check("the loopback and link-local are the system's",
          {by_ip[ip].origin for ip in ("127.0.0.1", "::1", "fe80::fc3e:b9ff:fe84:591e")}
          == {adapters.ORIGIN_WELL_KNOWN})
    check("deprecated (preferred 0)", by_ip["198.51.100.4"].dad == adapters.DAD_DEPRECATED)
    check("DAD failed: a duplicate, not 'tentative'",
          by_ip["2001:db8:1::5"].dad == adapters.DAD_DUPLICATE)
    check("the rest are in normal use", by_ip["2001:db8:1::2"].dad == adapters.DAD_PREFERRED)
    lease = rtnetlink.Address(2, 10, "2001:db8:9::1", 64, 0, 0, 3600, 7200, 0)
    check("an IPv6 lease the kernel cannot place: the program's own word",
          adapters._linux_origin(lease, adapters.ipaddress.ip_address(lease.ip)) == adapters.LEASE)
    ra = lease._replace(proto=adapters.IFA_PROTO_KERNEL_RA)
    temporary = lease._replace(flags=adapters.IFA_F_TEMPORARY)
    check("the kernel's own SLAAC and a temporary address are the router's",
          {adapters._linux_origin(a, adapters.ipaddress.ip_address(a.ip)) for a in (ra, temporary)}
          == {adapters.ORIGIN_ROUTER})
    check("a temporary address has a random suffix", adapters._linux_address(temporary).suffix == 5)
    secondary = rtnetlink.Address(2, 2, "198.51.100.9", 24, adapters.IFA_F_TEMPORARY | 0x80,
                                  0, adapters.rtnetlink.FOREVER, adapters.rtnetlink.FOREVER, 0)
    check("0x01 on IPv4 is SECONDARY, not temporary",
          adapters._linux_address(secondary).suffix == 0)


def test_linux_kinds_and_states_from_the_link_layer():
    link = rtnetlink.Link(5, b"x", 1, 0x1 | 0x10000, 0, 1500, b"\x02" * 6, "")
    check("Ethernet with Wi-Fi in sysfs is Wi-Fi", adapters._linux_kind(link, True) == 71)
    check("plain Ethernet", adapters._linux_kind(link, False) == 6)
    check("PPP, a sit tunnel, something else",
          [adapters._linux_kind(link._replace(arphrd=a), False) for a in (512, 776, 280)]
          == [23, 131, 1])
    check("UNKNOWN switched on without a link: unknown",
          adapters._linux_status(link._replace(flags=0x1)) == 4)
    check("UNKNOWN with its link but switched off: unknown",
          adapters._linux_status(link._replace(flags=0x10000)) == 4)
    check("the kernel's states in OperStatus' numbers",
          [adapters._linux_status(link._replace(operstate=s, flags=0)) for s in range(7)]
          == [4, 6, 2, 7, 3, 5, 1])


def test_linux_lists_each_dns_server_at_the_adapter_it_is_asked_through(tmp_path):
    root = str(tmp_path)
    _write(root, "etc/resolv.conf", "# by systemd-resolved\nnameserver 127.0.0.53\nsearch .\n")
    _write(root, "run/systemd/resolve/resolv.conf",
           "nameserver 198.51.100.1\nnameserver 2001:db8:1::1\nnameserver fe80::1%dm0\n")
    extra = {**_lookup("198.51.100.1", 2), **_lookup("2001:db8:1::1", 2)}
    found, _ = rows(tmp_path, extra)
    check("the stub at the loopback, said to be one",
          (found["lo"].dns_servers, found["lo"].stub_dns) == (("127.0.0.53",), ("127.0.0.53",)))
    check("the servers it asks, at the adapter their route leaves through",
          found["bv0"].dns_servers == ("198.51.100.1", "2001:db8:1::1"), f"({found['bv0']})")
    check("a zone names its adapter, no lookup asked", found["dm0"].dns_servers == ("fe80::1",))
    details = {d.key: d for d in logic.details(logic.Adapter(found["lo"], 0, ()))}
    stub = details["dns|0"]
    check("the stub's note, and it is not offered to the Control page",
          stub.note == (logic.Words("tools.adapters.dns_stub"),) and stub.address == "")
    check("a server it asks is offered", {d.key: d for d in logic.details(
        logic.Adapter(found["bv0"], 0, ()))}["dns|0"].address == "198.51.100.1")
    check("the report says what the stub is", "  DNS: 127.0.0.53 (systemd-resolved, on this "
          "computer)" in logic.adapter_lines(logic.Adapter(found["lo"], 0, ())))


def test_linux_reads_resolveds_servers_only_when_programs_ask_its_stub(tmp_path):
    root = str(tmp_path)
    _write(root, "etc/resolv.conf", "nameserver 198.51.100.1\nnameserver 198.51.100.7\n"
                                    "nameserver 198.51.100.8\nnameserver 198.51.100.9\n")
    _write(root, "run/systemd/resolve/resolv.conf", "nameserver 2001:db8:1::1\n")
    extra = {**_lookup("198.51.100.1", 2), **_lookup("198.51.100.7", 2),
             **_lookup("198.51.100.8", 2)}
    found, _ = rows(tmp_path, extra)
    check("glibc's three, and not resolved's list", found["bv0"].dns_servers
          == ("198.51.100.1", "198.51.100.7", "198.51.100.8"), f"({found['bv0'].dns_servers})")
    os.remove(os.path.join(root, "etc", "resolv.conf"))
    found, _ = rows(tmp_path)
    check("no resolv.conf: no DNS, and the list still reads",
          not any(row.dns_servers for row in found.values()))


def test_linux_failures_say_which_one(tmp_path):
    def changing(message):
        raise rtnetlink.Changing(11, "rtnetlink: the lists kept changing while they were read")
    with pytest.raises(logic.Unreadable) as raised:
        logic.read(adapters._Linux(changing, root=str(tmp_path)))
    check("a list that kept changing: Refresh in a moment",
          raised.value.user_key == "tools.adapters.error_changing")

    def refused(message):
        raise OSError(13, "rtnetlink: the kernel refused the list of adapters")
    with pytest.raises(logic.Unreadable) as raised:
        logic.read(adapters._Linux(refused, root=str(tmp_path)))
    check("any other refusal: the program's own words, no key", raised.value.user_key == ""
          and "refused" in str(raised.value))


def test_a_linux_name_that_is_not_utf8_is_shown_and_keyed_apart(tmp_path):
    native = adapters._Linux(kernel(), root=str(tmp_path))
    tables = rtnetlink.Tables((rtnetlink.Link(9, b"eth\xff", 1, 0, 2, 1500, b"", ""),
                               rtnetlink.Link(10, b"eth\xfe", 1, 0, 2, 1500, b"", ""),
                               rtnetlink.Link(11, b"proxy", 1, 0, 2, 1500, b"", "")), (), ())
    made = [native._row(link, tables, (), frozenset()) for link in tables.links]
    check("shown with the byte replaced", made[0].name == "eth�")
    check("two such names keep two keys", made[0].key != made[1].key, f"({made[0].key})")
    check("an adapter called proxy is not the proxy row", made[2].key == "if:proxy")


def test_the_linux_words_have_a_text_in_every_language():
    import json
    keys = {"tools.adapters.origin.lease", "tools.adapters.dns_stub",
            "tools.adapters.error_changing", "tools.adapters.help_linux",
            "tips.tools_adapters_col_name_linux"}
    check("the lease word is the one the logic gives", logic.ORIGINS[adapters.LEASE] == "lease")
    for lang in ("en", "pl", "zh"):
        with open(os.path.join(os.path.dirname(__file__), "..", "lang", f"{lang}.json"),
                  encoding="utf-8") as f:
            texts = json.load(f)
        missing = sorted(k for k in keys if not texts.get(k))
        check(f"{lang}: every Linux word has a text", not missing, f"({missing})")


def test_only_the_sheet_and_two_tips_are_linuxs_own_and_windows_keeps_its_keys():
    from beantester.gui.toolbox import adapters as panel
    from beantester.gui.toolbox import diagnostics as diag
    check("Windows: today's sheet and tips", (panel.help_key("win32"), panel.tips("win32"))
          == ("tools.adapters.help_body", panel.TIPS))
    check("Linux: its own sheet", panel.help_key("linux") == "tools.adapters.help_linux")
    linux_tips = panel.tips("linux")
    check("Linux: only the name's tip differs",
          {k for k in panel.TIPS if panel.TIPS[k] != linux_tips[k]} == {"name"}
          and linux_tips["name"] == "tips.tools_adapters_col_name_linux")
    proxy_box = next(b for b in diag.OPTIONAL_BOXES if b.section == "proxy")
    adapters_box = next(b for b in diag.OPTIONAL_BOXES if b.section == "adapters")
    check("the proxy box: Windows' tip on Windows, Linux's on Linux",
          (diag.box_tip(proxy_box, "win32"), diag.box_tip(proxy_box, "linux"))
          == ("tips.tools_diagnostics_proxy", "tips.tools_diagnostics_proxy_linux"))
    check("the adapters box says the same on both",
          diag.box_tip(adapters_box, "linux") == adapters_box.tip)


# -- paths.read_small_file -------------------------------------------------------- #
def test_a_small_file_is_read_whole_up_to_its_bound(tmp_path):
    path = os.path.join(str(tmp_path), "f")
    with open(path, "wb") as f:
        f.write("nameserver 198.51.100.1\nż\n".encode() + b"\xff")
    check("read as UTF-8, what does not decode replaced",
          paths.read_small_file(path) == "nameserver 198.51.100.1\nż\n�")
    check("at most the bound", paths.read_small_file(path, limit=10) == "nameserver")
    check("no file: None", paths.read_small_file(os.path.join(str(tmp_path), "none")) is None)
    check("a file under a file: None",
          paths.read_small_file(os.path.join(path, "under")) is None)
    owner = os.stat(path).st_uid
    check("its owner's file is read", paths.read_small_file(path, owner=owner) is not None)
    check("anyone else's is not", paths.read_small_file(path, owner=owner + 1) is None)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="FIFOs and links of Linux")
def test_a_fifo_or_a_dangling_link_in_a_files_place_reads_as_none(tmp_path):  # pragma: no cover - Linux
    fifo = os.path.join(str(tmp_path), "resolv.conf")
    os.mkfifo(fifo)
    check("a FIFO is refused without waiting for a writer", paths.read_small_file(fifo) is None)
    link = os.path.join(str(tmp_path), "dangling")
    os.symlink(os.path.join(str(tmp_path), "gone"), link)
    check("a dangling link is no file", paths.read_small_file(link) is None)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="this runner's own kernel")
def test_this_machines_adapters_read_whole():  # pragma: no cover - Linux
    reading = adapters.read()
    check("at least the loopback", any(row.kind == 24 for row in reading.adapters),
          f"({[row.name for row in reading.adapters]})")
    check("every key once", len({row.key for row in reading.adapters}) == len(reading.adapters))
    check("labels the logic can rank", logic.rank(reading) is not None)
    check("the recorded fixture is the one the module docstring names", "links" in BY_LABEL)
