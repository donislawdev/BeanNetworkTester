"""``beantester/netlink.py`` and ``beantester/rtnetlink.py``: the kernel's tables of
adapters, addresses and routes on Linux, and the transport under them.

The fixture is a real kernel's own answers (Ubuntu 26.04.1, kernel 7.0.0), recorded
inside a network namespace built for it - veth, dummy, bridge, vlan, tun and WireGuard;
an address with a lease, one deprecated, one another device also holds (DAD failed);
two IPv4 default routes and an IPv6 one - so it carries documentation addresses only
(``internal_tools`` probes ``2026-10-27-linux-adapters``, where every field decoded here
was compared with ``ip -j``: no difference). The requests below are the ones that
kernel answered, byte for byte.
"""
import json
import os
import shutil
import struct
import subprocess
import sys

import pytest

from beantester import netlink, rtnetlink
from fakes import check

FIXTURE = os.path.join(os.path.dirname(__file__), "data", "rtnetlink", "netns-kernel-7.0.jsonl")


def _recorded():
    with open(FIXTURE, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


RECORDED = _recorded()
BY_LABEL = {r["label"]: r for r in RECORDED}


class FakeNetlink:
    """A netlink socket that answers with the datagrams it was given, one per read."""

    def __init__(self, *datagrams, sender=(0, 0)):
        self.datagrams = list(datagrams)
        self.sender = sender
        self.sent = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.closed = True

    def sendto(self, data, address):
        self.sent.append((data, address))

    def recvmsg(self, _size):
        return self.datagrams.pop(0), [], 0, self.sender


def kernel(extra=None):
    """``talk`` answering each request the recorded kernel answered, through the real
    ``netlink.exchange``; ``extra`` maps more requests to datagrams. Keeps the requests."""
    answers = {bytes.fromhex(r["request"]): [bytes.fromhex(a) for a in r["answer"]]
               for r in RECORDED}
    answers.update(extra or {})
    sent = []

    def talk(request):
        sent.append(request)
        if request not in answers:
            raise AssertionError(f"a request the kernel was never asked: {request.hex()}")
        return netlink.exchange(request, lambda: FakeNetlink(*answers[request]))
    talk.sent = sent
    return talk


def error(code, flags=0):
    """An NLMSG_ERROR datagram carrying ``-code`` (0: an acknowledgement)."""
    return struct.pack("=IHHII", 36, netlink.NLMSG_ERROR, flags, 1, 0) + struct.pack(
        "=i", -code) + bytes(16)


def route_answer(oif, family=rtnetlink.LINUX_AF_INET):
    """A route lookup's answer: the route out through ``oif``, then the acknowledgement."""
    body = (rtnetlink._ROUTE.pack(family, 32, 0, 0, 254, 0, 0, 1, 0)
            + netlink.attribute(rtnetlink.RTA_OIF, struct.pack("=I", oif)))
    return [netlink.message(rtnetlink.RTM_NEWROUTE, 0, body), error(0)]


def by_name(tables):
    return {link.name: link for link in tables.links}


def test_the_kernels_own_tables_read_as_ip_showed_them():
    talk = kernel()
    tables = rtnetlink.read(talk)
    links = by_name(tables)
    check("every adapter of the namespace", set(links) == {
        b"lo", b"bv0", b"dm0", b"br0", b"dm1", b"dm0.7", b"tn0", b"wg0"}, f"({set(links)})")
    check("a virtual device says what it is",
          [links[n].kind for n in (b"bv0", b"dm0", b"br0", b"dm0.7", b"tn0", b"wg0")]
          == ["veth", "dummy", "bridge", "vlan", "tun", "wireguard"])
    check("lo: the loopback, UNKNOWN, up with its link",
          (links[b"lo"].arphrd, links[b"lo"].operstate, links[b"lo"].flags & 0x10001)
          == (772, 0, 0x10001))
    check("a bridge with nothing in it is down (IF_OPER_DOWN)", links[b"br0"].operstate == 2)
    check("WireGuard: no link layer, no address, its own MTU",
          (links[b"wg0"].arphrd, links[b"wg0"].address, links[b"wg0"].mtu) == (65534, b"", 1420))
    check("a MAC is six bytes", len(links[b"bv0"].address) == 6)

    addresses = {a.ip: a for a in tables.addresses}
    leased = addresses["198.51.100.3"]
    check("an address with a lease: no PERMANENT, its lifetimes",
          not leased.flags & 0x80 and 90 <= leased.preferred <= 100 and 290 <= leased.valid <= 300,
          f"({leased})")
    check("one deprecated: preferred 0", addresses["198.51.100.4"].preferred == 0)
    check("one another device holds: DADFAILED, with TENTATIVE",
          addresses["2001:db8:1::5"].flags & 0x48 == 0x48)
    check("the kernel says it made ::1 and the link-local address (IFA_PROTO)",
          (addresses["::1"].proto, addresses["fe80::fc3e:b9ff:fe84:591e"].proto) == (1, 3))
    check("an address is on its adapter", addresses["203.0.113.1"].ifindex == links[b"dm0"].ifindex)

    defaults = sorted((r.family, r.gateway, r.oif, r.priority, r.protocol)
                      for r in tables.routes if r.dst_len == 0 and r.table == 254)
    bv0, dm0 = links[b"bv0"].ifindex, links[b"dm0"].ifindex
    check("the default routes, each with its way out, metric and origin", defaults == [
        (2, "198.51.100.1", bv0, 100, 16), (2, "203.0.113.254", dm0, 200, 3),
        (10, "2001:db8:1::1", bv0, 1024, 3)], f"({defaults})")
    recorded = [bytes.fromhex(BY_LABEL[label]["request"])
                for label in ("links", "addresses", "routes2", "routes10")]
    check("asked exactly as the kernel was asked", talk.sent == recorded,
          f"({[m.hex() for m in talk.sent]})")


def test_a_route_lookup_is_what_ip_route_get_asks_and_sends_nothing():
    talk = kernel()
    check("8.8.8.8 leaves through bv0", rtnetlink.route_to("8.8.8.8", talk) == 2)
    check("so does the IPv6 probe", rtnetlink.route_to("2001:4860:4860::8888", talk) == 2)
    check("the stub resolver is the loopback", rtnetlink.route_to("127.0.0.53", talk) == 1)
    check("asked as the kernel was asked, with an acknowledgement",
          talk.sent == [bytes.fromhex(BY_LABEL[label]["request"]) for label in
                        ("get 8.8.8.8", "get 2001:4860:4860::8888", "get 127.0.0.53")])
    check("NLM_F_ACK in every lookup", all(
        struct.unpack_from("=H", m, 6)[0] == netlink.NLM_F_REQUEST | netlink.NLM_F_ACK
        for m in talk.sent))


def test_no_route_is_no_adapter_and_any_other_refusal_an_error():
    for code in (100, 101, 113):            # ENETDOWN, ENETUNREACH, EHOSTUNREACH
        talk = kernel({bytes.fromhex(BY_LABEL["get 2001:4860:4860::8888"]["request"]):
                       [error(code)]})
        check(f"errno {code}: no adapter is the way out",
              rtnetlink.route_to("2001:4860:4860::8888", talk) == 0)
    talk = kernel({bytes.fromhex(BY_LABEL["get 8.8.8.8"]["request"]): [error(1)]})
    with pytest.raises(OSError, match="refused a route lookup"):
        rtnetlink.route_to("8.8.8.8", talk)


def _interrupted(datagram):
    """The datagram with NLM_F_DUMP_INTR set on its first message."""
    flags = struct.unpack_from("=H", datagram, 6)[0] | netlink.NLM_F_DUMP_INTR
    return datagram[:6] + struct.pack("=H", flags) + datagram[8:]


def test_a_list_that_changed_while_it_was_read_is_read_again_and_then_refused():
    request = bytes.fromhex(BY_LABEL["addresses"]["request"])
    datagrams = [bytes.fromhex(a) for a in BY_LABEL["addresses"]["answer"]]
    answers = [[_interrupted(datagrams[0]), *datagrams[1:]], datagrams]

    def once_then_calm(message):
        real = kernel()
        if message == request and answers:
            return netlink.exchange(message, lambda: FakeNetlink(*answers.pop(0)))
        return real(message)
    tables = rtnetlink.read(once_then_calm)
    check("the second, calm read is the one kept", len(tables.addresses) == 13 and not answers,
          f"({len(tables.addresses)})")

    def always_changing(message):
        found = [bytes.fromhex(a) for a in BY_LABEL["links"]["answer"]]
        if message == bytes.fromhex(BY_LABEL["links"]["request"]):
            return netlink.exchange(message, lambda: FakeNetlink(_interrupted(found[0]),
                                                                 *found[1:]))
        return kernel()(message)
    with pytest.raises(rtnetlink.Changing, match="kept changing"):
        rtnetlink.read(always_changing)


def test_a_kernel_without_ipv6_still_lists_and_a_refused_list_is_an_error():
    v6 = bytes.fromhex(BY_LABEL["routes10"]["request"])
    tables = rtnetlink.read(kernel({v6: [error(97)]}))      # EAFNOSUPPORT: ipv6.disable=1
    check("no IPv6 route, the rest read", not [r for r in tables.routes if r.family == 10]
          and tables.links, f"({len(tables.routes)})")
    v4 = bytes.fromhex(BY_LABEL["routes2"]["request"])
    with pytest.raises(OSError, match="refused the list of routes"):
        rtnetlink.read(kernel({v4: [error(13)]}))
    with pytest.raises(OSError, match="refused the list of routes"):
        rtnetlink.read(kernel({v6: [error(13)]}))           # only EAFNOSUPPORT means "none"


def test_a_route_with_several_ways_out_is_one_row_per_way():
    hop = struct.Struct("=HBBi")
    ways = b""
    for oif, gateway in ((2, bytes([198, 51, 100, 1])), (3, bytes([203, 0, 113, 254]))):
        inner = netlink.attribute(rtnetlink.RTA_GATEWAY, gateway)
        ways += hop.pack(hop.size + len(inner), 0, 0, oif) + inner
    via = struct.pack("=H", 10) + bytes.fromhex("20010db8000100000000000000000001")
    multipath = (rtnetlink._ROUTE.pack(2, 0, 0, 0, 254, 3, 0, 1, 0)
                 + netlink.attribute(rtnetlink.RTA_MULTIPATH, ways))
    through_v6 = (rtnetlink._ROUTE.pack(2, 0, 0, 0, 254, 3, 0, 1, 0)
                  + netlink.attribute(rtnetlink.RTA_OIF, struct.pack("=I", 4))
                  + netlink.attribute(rtnetlink.RTA_VIA, via))
    rows = rtnetlink._routes(multipath) + rtnetlink._routes(through_v6)
    check("each way its adapter and gateway; a gateway given as RTA_VIA",
          [(r.oif, r.gateway) for r in rows]
          == [(2, "198.51.100.1"), (3, "203.0.113.254"), (4, "2001:db8:1::1")], f"({rows})")


def test_an_answer_that_does_not_add_up_is_an_error_never_a_shorter_list():
    datagram = bytes.fromhex(BY_LABEL["links"]["answer"][0])
    with pytest.raises(OSError, match="not the kernel"):
        netlink.exchange(b"r", lambda: FakeNetlink(datagram, sender=(4242, 0)))
    with pytest.raises(OSError, match="longer than its message"):
        netlink.attributes(struct.pack("=HH", 40, 3) + b"lo\0\0")
    with pytest.raises(OSError, match="longer than its datagram"):
        netlink.exchange(b"r", lambda: FakeNetlink(datagram[:100]))
    nl = FakeNetlink(_interrupted(datagram), bytes.fromhex(BY_LABEL["links"]["answer"][1]),
                     bytes.fromhex(BY_LABEL["links"]["answer"][2]))
    replies = netlink.exchange(b"r", lambda: nl)
    check("a list the kernel says changed is marked so", replies.interrupted)
    check("sent to the kernel, and closed", nl.sent == [(b"r", (0, 0))] and nl.closed)


def test_an_attribute_is_padded_to_four_bytes():
    check("4 + 3 bytes, then one of padding",
          netlink.attribute(3, b"abc") == struct.pack("=HH", 7, 3) + b"abc\0")
    check("and read back as written", netlink.attributes(netlink.attribute(3, b"abc"))
          == [netlink.Attribute(3, b"abc")])


@pytest.mark.skipif(not sys.platform.startswith("linux") or shutil.which("ip") is None,
                    reason="this runner's own kernel, against ip -j")
def test_this_machines_tables_read_as_ip_reads_them():  # pragma: no cover - Linux
    tables = rtnetlink.read()

    def ip(*args):
        return json.loads(subprocess.run(["ip", "-j", *args], capture_output=True, text=True,
                                         timeout=10, check=True).stdout or "[]")
    theirs = {link["ifindex"]: (link["ifname"], link["mtu"]) for link in ip("link")}
    mine = {link.ifindex: (link.name.decode(), link.mtu) for link in tables.links}
    check("the adapters, their names and MTU", mine == theirs, f"({mine} vs {theirs})")
    theirs = {(link["ifindex"], a["local"], a["prefixlen"]) for link in ip("addr")
              for a in link.get("addr_info", [])}
    mine = {(a.ifindex, a.ip, a.prefix) for a in tables.addresses}
    check("every address with its prefix", mine == theirs, f"({mine ^ theirs})")
    route = ip("route", "get", "8.8.8.8")
    names = {link.ifindex: link.name.decode() for link in tables.links}
    check("the way out the kernel names", names.get(rtnetlink.route_to("8.8.8.8"))
          == (route[0].get("dev") if route else None))
