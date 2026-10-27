"""The kernel's tables of network adapters, their addresses and its routes on Linux - read only.

What ``ip link``, ``ip addr`` and ``ip route`` read, asked the way they ask it: rtnetlink,
over ``netlink``. For the Adapters tool (``adapters._Linux``), on a worker. Nothing here
changes a table, and nothing is sent: a list is a question to the kernel, and so is a
route lookup (``route_to``, what ``ip route get`` asks) - the kernel answers from its
routing table and no packet leaves.

The layouts are the kernel's (``include/uapi/linux``: ``rtnetlink.h``, ``if_link.h``,
``if_addr.h``), which never change: ``ifinfomsg``, ``ifaddrmsg`` and ``rtmsg``, each
followed by attributes. The numbers are written out, errnos included: Python's
``errno`` on Windows numbers them as Windows does (ENETUNREACH is 118 there, 101 here),
and the tests run there too.

MEASURED 2026-10-27 (``internal_tools`` probes ``2026-10-27-linux-adapters``: Ubuntu 26.04.1
with kernel 7.0.0, a network namespace holding veth, dummy, bridge, vlan, tun and
wireguard, and WSL with 6.18): every field read here matched ``ip -j`` - names, MTU,
state, MAC, kind, addresses with their prefix, lifetime and DAD state, the route out.
The three lists and two route lookups took 0.4-0.9 ms. An ordinary user gets all of
it; ``tests/test_rtnetlink.py`` holds that kernel's own answers.
"""
import ipaddress
import struct
from typing import NamedTuple

from . import netlink
from .netlink import NETLINK_ROUTE, NLM_F_ACK, NLM_F_DUMP, NLM_F_REQUEST

RTM_NEWLINK, RTM_GETLINK = 16, 18
RTM_NEWADDR, RTM_GETADDR = 20, 22
RTM_NEWROUTE, RTM_GETROUTE = 24, 26
LINUX_AF_UNSPEC, LINUX_AF_INET, LINUX_AF_INET6 = 0, 2, 10

# Linux's errnos, not this interpreter's (see above).
EAFNOSUPPORT = 97                       # the kernel has no IPv6 (booted with ipv6.disable=1)
NO_ROUTE = frozenset({100, 101, 113})   # ENETDOWN, ENETUNREACH, EHOSTUNREACH

_LINK = struct.Struct("=BxHiII")        # ifinfomsg: family, pad, type (ARPHRD), index, flags, change
_ADDRESS = struct.Struct("=BBBBI")      # ifaddrmsg: family, prefix length, flags, scope, index
_ROUTE = struct.Struct("=BBBBBBBBI")    # rtmsg: family, dst_len, src_len, tos, table, protocol,
                                        # scope, type, flags
_NEXTHOP = struct.Struct("=HBBi")       # rtnexthop: length, flags, hops, interface
_U32 = struct.Struct("=I")
_LIFETIMES = struct.Struct("=II")       # ifa_cacheinfo, its first two: preferred, valid

IFLA_ADDRESS, IFLA_IFNAME, IFLA_MTU, IFLA_OPERSTATE, IFLA_LINKINFO = 1, 3, 4, 16, 18
IFLA_INFO_KIND = 1
IFA_ADDRESS, IFA_LOCAL, IFA_CACHEINFO, IFA_FLAGS, IFA_PROTO = 1, 2, 6, 8, 11
RTA_DST, RTA_OIF, RTA_GATEWAY, RTA_PRIORITY, RTA_MULTIPATH, RTA_TABLE, RTA_VIA = (
    1, 4, 5, 6, 9, 15, 18)

FOREVER = 0xFFFFFFFF                    # a lifetime without an end
TRIES = 3                               # lists read again when one changed while it was read


class Link(NamedTuple):
    ifindex: int
    name: bytes             # as the kernel holds it: any byte but "/", ":", whitespace and NUL
    arphrd: int             # the link layer (ARPHRD_*): 1 Ethernet, 772 loopback, 65534 none
    flags: int              # IFF_*
    operstate: int          # IF_OPER_*: 0 unknown ... 6 up
    mtu: int
    address: bytes          # the hardware address; b"" when the link layer has none
    kind: str               # IFLA_INFO_KIND of a virtual device ("veth", "bridge"); "" otherwise


class Address(NamedTuple):
    ifindex: int
    family: int             # LINUX_AF_INET / LINUX_AF_INET6
    ip: str
    prefix: int
    flags: int              # IFA_F_*, all 32 bits
    scope: int
    preferred: int          # seconds; FOREVER
    valid: int
    proto: int              # IFA_PROTO (kernel 6.3 and later): who made it; 0 when not said


class Route(NamedTuple):
    family: int
    dst_len: int            # 0: a default route
    table: int
    protocol: int           # RTPROT_*: 2 kernel, 3 boot, 4 static, 16 dhcp...
    kind: int               # RTN_*: 1 unicast; blackhole, unreachable and prohibit have no way out
    oif: int                # 0: none
    gateway: str            # "" for a route to a network the adapter is on
    priority: int | None    # the metric; None when not given


class Tables(NamedTuple):
    links: tuple
    addresses: tuple
    routes: tuple


class Changing(OSError):
    """Every try read a list the kernel said changed while it was read."""


_open = netlink.opener(NETLINK_ROUTE)


def exchange(request):
    """One request to the kernel's routing tables, through ``netlink.exchange``."""
    return netlink.exchange(request, _open)


def _ip(raw):
    return str(ipaddress.ip_address(raw)) if len(raw) in (4, 16) else ""


def _u32(raw):
    return _U32.unpack_from(raw)[0] if len(raw) >= _U32.size else 0


def _text(raw):
    return raw.split(b"\0", 1)[0].decode("ascii", errors="replace")


def _dump(kind, body, talk, what):
    """One list, its messages of the answer's own type, and whether it changed meanwhile."""
    replies = talk(netlink.message(kind, NLM_F_REQUEST | NLM_F_DUMP, body))
    code = netlink.error_of(replies)
    if code:
        raise OSError(code, f"rtnetlink: the kernel refused the list of {what}")
    answer = kind - 2               # RTM_GET* is answered with RTM_NEW*
    return [payload for k, payload in replies if k == answer], bool(
        getattr(replies, "interrupted", False))


def _link(payload):
    _family, arphrd, index, flags, _change = _LINK.unpack_from(payload)
    fields = {IFLA_IFNAME: b"", IFLA_ADDRESS: b"", IFLA_MTU: b"", IFLA_OPERSTATE: b"\0"}
    kind = ""
    for attribute in netlink.attributes(payload, _LINK.size):
        if attribute.kind == IFLA_LINKINFO:
            kind = next((_text(a.value) for a in netlink.attributes(attribute.value)
                         if a.kind == IFLA_INFO_KIND), "")
        elif attribute.kind in fields:
            fields[attribute.kind] = attribute.value
    return Link(index, fields[IFLA_IFNAME].split(b"\0", 1)[0], arphrd, flags,
                fields[IFLA_OPERSTATE][0] if fields[IFLA_OPERSTATE] else 0,
                _u32(fields[IFLA_MTU]), fields[IFLA_ADDRESS], kind)


def _address(payload):
    family, prefix, flags, scope, index = _ADDRESS.unpack_from(payload)
    found = {}
    for attribute in netlink.attributes(payload, _ADDRESS.size):
        found[attribute.kind] = attribute.value
    preferred, valid = (_LIFETIMES.unpack_from(found[IFA_CACHEINFO])
                        if len(found.get(IFA_CACHEINFO, b"")) >= _LIFETIMES.size
                        else (FOREVER, FOREVER))
    # IFA_LOCAL is this machine's address; IFA_ADDRESS is the far end's on a
    # point-to-point link, and the only one IPv6 sends - as ``ip`` reads them.
    raw = found.get(IFA_LOCAL) or found.get(IFA_ADDRESS, b"")
    # IFA_FLAGS carries all 32 bits; the byte in the header only the low eight.
    flags = _u32(found[IFA_FLAGS]) if IFA_FLAGS in found else flags
    proto = found[IFA_PROTO][0] if found.get(IFA_PROTO) else 0
    return Address(index, family, _ip(raw), prefix, flags, scope, preferred, valid, proto)


def _hops(raw):
    """The ``(interface, gateway)`` of each way of a route with several (RTA_MULTIPATH)."""
    out, offset = [], 0
    while offset + _NEXTHOP.size <= len(raw):
        length, _flags, _hops_count, oif = _NEXTHOP.unpack_from(raw, offset)
        if length < _NEXTHOP.size:
            break
        inner = netlink.attributes(raw[offset + _NEXTHOP.size:offset + length])
        gateway = next((_via(a) for a in inner if a.kind in (RTA_GATEWAY, RTA_VIA)), "")
        out.append((oif, gateway))
        offset += (length + 3) & ~3
    return out


def _via(attribute):
    """RTA_GATEWAY is an address; RTA_VIA a family and then the address (an IPv4 route
    through an IPv6 neighbour)."""
    return _ip(attribute.value[2:] if attribute.kind == RTA_VIA else attribute.value)


def _routes(payload):
    """One route message as ``Route`` rows: one per way out."""
    family, dst_len, _src, _tos, table, protocol, _scope, kind, _flags = _ROUTE.unpack_from(payload)
    oif, gateway, priority, hops = 0, "", None, []
    for attribute in netlink.attributes(payload, _ROUTE.size):
        if attribute.kind == RTA_OIF:
            oif = _u32(attribute.value)
        elif attribute.kind in (RTA_GATEWAY, RTA_VIA):
            gateway = _via(attribute)
        elif attribute.kind == RTA_PRIORITY:
            priority = _u32(attribute.value)
        elif attribute.kind == RTA_TABLE:
            table = _u32(attribute.value)       # a table above 255 is only here
        elif attribute.kind == RTA_MULTIPATH:
            hops = _hops(attribute.value)
    return [Route(family, dst_len, table, protocol, kind, way, via, priority)
            for way, via in (hops or [(oif, gateway)])]


def _route_list(family, talk):
    try:
        payloads, interrupted = _dump(RTM_GETROUTE, _ROUTE.pack(family, 0, 0, 0, 0, 0, 0, 0, 0),
                                      talk, "routes")
    except OSError as exc:
        if family == LINUX_AF_INET6 and exc.errno == EAFNOSUPPORT:
            return [], False            # no IPv6 in this kernel: no IPv6 route
        raise
    return [route for payload in payloads for route in _routes(payload)], interrupted


def _read_once(talk):
    links, a = _dump(RTM_GETLINK, _LINK.pack(LINUX_AF_UNSPEC, 0, 0, 0, 0), talk, "adapters")
    addresses, b = _dump(RTM_GETADDR, _ADDRESS.pack(LINUX_AF_UNSPEC, 0, 0, 0, 0), talk,
                         "addresses")
    v4, c = _route_list(LINUX_AF_INET, talk)
    v6, d = _route_list(LINUX_AF_INET6, talk)
    tables = Tables(tuple(_link(p) for p in links), tuple(_address(p) for p in addresses),
                    tuple(v4 + v6))
    return tables, a or b or c or d


def read(talk=exchange):
    """The adapters, their addresses and every route, read again when the kernel said a
    list changed while it was read. Raises ``Changing`` after ``TRIES`` such reads, and
    ``OSError`` when the kernel refuses a list."""
    for _ in range(TRIES):
        tables, interrupted = _read_once(talk)
        if not interrupted:
            return tables
    raise Changing(11, "rtnetlink: the lists kept changing while they were read")


def route_to(ip, talk=exchange):
    """The interface index the kernel would send a packet to ``ip`` through - what
    ``ip route get`` asks; nothing is sent. 0 when there is no route."""
    address = ipaddress.ip_address(ip)
    family = LINUX_AF_INET if address.version == 4 else LINUX_AF_INET6
    body = (_ROUTE.pack(family, address.max_prefixlen, 0, 0, 0, 0, 0, 0, 0)
            + netlink.attribute(RTA_DST, address.packed))
    # NLM_F_ACK: without it the route comes with nothing after it (netlink's docstring).
    replies = talk(netlink.message(RTM_GETROUTE, NLM_F_REQUEST | NLM_F_ACK, body))
    code = netlink.error_of(replies)
    if code in NO_ROUTE:
        return 0
    if code:
        raise OSError(code, f"rtnetlink: the kernel refused a route lookup ({code})")
    for kind, payload in replies:
        if kind == RTM_NEWROUTE:
            return _routes(payload)[0].oif
    return 0
