"""The network adapters of this computer, as the system's own table lists them.

What ``ipconfig /all`` prints - each adapter's name, state, addresses, gateway, DNS
servers, MAC, MTU - read from ``iphlpapi.GetAdaptersAddresses``, plus which adapter
the route to the internet leaves through (``GetBestInterfaceEx``). For the Tools
tab: read on a click by a worker, never by the packet path
(``tests/test_hot_path.py`` watches both calls).

Nothing here sends a packet. Both calls answer from tables the system keeps - the
adapter list and the routing table - and neither is in the wire-function list of
``tests/test_no_telemetry.py`` (the ping and ARP exports of the same DLL are).

On Linux (``_Linux``) the same rows come from the kernel's own tables - what ``ip
link``, ``ip addr`` and ``ip route`` read, through ``rtnetlink`` - with the device's
driver, Wi-Fi and link speed from sysfs, and the DNS servers from the resolver's own
files. Every field matched ``ip -j`` on a real kernel (``rtnetlink``'s docstring has
the measurement); what Linux words differently is written at ``_Linux``.

Why the structures are written with fixed-width integers
-----------------------------------------------------
``wintypes.DWORD`` is 8 bytes on Linux (measured on CPython 3.14, see
``portmap._Native``) and ``c_wchar_p`` reads UTF-32 there. Built from ``c_uint32``
and ``c_void_p`` instead, the layout is the one Windows writes on BOTH: 448 bytes
for an adapter on x64 (``Length`` reported by Windows 11, measured 2026-09-24 and
2026-10-13), so a fake that writes a real list into the caller's buffer tests the
walk on the Linux runner too, and text is read as UTF-16 by hand.

The structure grew three times (Microsoft Learn, ``IP_ADAPTER_ADDRESSES_LH``:
XP SP1, Vista, Vista SP1) and ``Length`` says which one the system wrote. A field
is read only when it lies inside that length - the rule Learn gives - so an older
layout costs the newer fields, never a read past the record.

Where a record itself sits is checked too. The system writes the whole answer -
records, strings, addresses - into the caller's buffer (86 pointers of 86 inside
it, measured 2026-10-14), so a pointer is followed only when what it points at lies
inside that buffer (``_Answer``). One pointing elsewhere is a broken answer: the
list is refused as unreadable instead of read from memory nobody vouched for.
"""
import ctypes
import ipaddress
import os
import struct
import sys
from typing import NamedTuple

from . import crashlog, paths, rtnetlink
from .utils import INTERNET_PROBES   # where "the internet" is, shared with host_identity

# Address families as Windows numbers them (AF_INET6 is 23 there, not POSIX 10).
AF_UNSPEC, AF_INET, AF_INET6 = 0, 2, 23
FAMILY_OF_VERSION = {4: AF_INET, 6: AF_INET6}

# GetAdaptersAddresses flags (iptypes.h): anycast and multicast addresses are not
# shown, gateways are - they are not in the answer unless asked for.
GAA_FLAG_SKIP_ANYCAST = 0x2
GAA_FLAG_SKIP_MULTICAST = 0x4
GAA_FLAG_INCLUDE_GATEWAYS = 0x80
FLAGS = GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_INCLUDE_GATEWAYS

ERROR_BUFFER_OVERFLOW = 111
ERROR_NO_DATA = 232
ERROR_ADDRESS_NOT_ASSOCIATED = 1228

# Learn: "allocate a 15 KB buffer", and call again with the size the system asks
# for, up to three times - the list can grow between two calls. 15 KB held 7
# adapters with room on the development machine.
START_BYTES = 15000
TRIES = 3

# Bounds on what is walked. Every list here is a C linked list followed by its
# ``Next`` pointer, and a list that never ends must not hang the worker; the
# limits are far above any real machine (7 adapters, 2 addresses each, measured).
MAX_ADAPTERS = 1024
MAX_ENTRIES = 1024
MAX_TEXT = 1024          # characters in one name, description or suffix


# -- the structures, from Microsoft Learn (iptypes.h) ------------------------------ #
class _SocketAddress(ctypes.Structure):
    _fields_ = [("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", ctypes.c_int32)]


class _Unicast(ctypes.Structure):
    """``IP_ADAPTER_UNICAST_ADDRESS_LH``."""


_Unicast._fields_ = [
    ("Length", ctypes.c_uint32), ("Flags", ctypes.c_uint32),
    ("Next", ctypes.POINTER(_Unicast)), ("Address", _SocketAddress),
    ("PrefixOrigin", ctypes.c_int32), ("SuffixOrigin", ctypes.c_int32),
    ("DadState", ctypes.c_int32), ("ValidLifetime", ctypes.c_uint32),
    ("PreferredLifetime", ctypes.c_uint32), ("LeaseLifetime", ctypes.c_uint32),
    ("OnLinkPrefixLength", ctypes.c_uint8),
]


class _AddressNode(ctypes.Structure):
    """``IP_ADAPTER_DNS_SERVER_ADDRESS_XP`` and ``IP_ADAPTER_GATEWAY_ADDRESS_LH``:
    the same four fields, so one walk serves both lists."""


_AddressNode._fields_ = [
    ("Length", ctypes.c_uint32), ("Reserved", ctypes.c_uint32),
    ("Next", ctypes.POINTER(_AddressNode)), ("Address", _SocketAddress),
]


class _Adapter(ctypes.Structure):
    """``IP_ADAPTER_ADDRESSES_LH``, every field in Learn's order."""


_Adapter._fields_ = [
    ("Length", ctypes.c_uint32), ("IfIndex", ctypes.c_uint32),
    ("Next", ctypes.POINTER(_Adapter)), ("AdapterName", ctypes.c_void_p),
    ("FirstUnicastAddress", ctypes.POINTER(_Unicast)),
    ("FirstAnycastAddress", ctypes.c_void_p), ("FirstMulticastAddress", ctypes.c_void_p),
    ("FirstDnsServerAddress", ctypes.POINTER(_AddressNode)),
    ("DnsSuffix", ctypes.c_void_p), ("Description", ctypes.c_void_p),
    ("FriendlyName", ctypes.c_void_p),
    ("PhysicalAddress", ctypes.c_uint8 * 8), ("PhysicalAddressLength", ctypes.c_uint32),
    ("Flags", ctypes.c_uint32), ("Mtu", ctypes.c_uint32), ("IfType", ctypes.c_uint32),
    ("OperStatus", ctypes.c_int32), ("Ipv6IfIndex", ctypes.c_uint32),
    ("ZoneIndices", ctypes.c_uint32 * 16), ("FirstPrefix", ctypes.c_void_p),
    ("TransmitLinkSpeed", ctypes.c_uint64), ("ReceiveLinkSpeed", ctypes.c_uint64),
    ("FirstWinsServerAddress", ctypes.c_void_p),
    ("FirstGatewayAddress", ctypes.POINTER(_AddressNode)),
    ("Ipv4Metric", ctypes.c_uint32), ("Ipv6Metric", ctypes.c_uint32),
    ("Luid", ctypes.c_uint64), ("Dhcpv4Server", _SocketAddress),
    ("CompartmentId", ctypes.c_uint32), ("NetworkGuid", ctypes.c_uint8 * 16),
    ("ConnectionType", ctypes.c_int32), ("TunnelType", ctypes.c_int32),
    ("Dhcpv6Server", _SocketAddress), ("Dhcpv6ClientDuid", ctypes.c_uint8 * 130),
    ("Dhcpv6ClientDuidLength", ctypes.c_uint32), ("Dhcpv6Iaid", ctypes.c_uint32),
    ("FirstDnsSuffix", ctypes.c_void_p),
]

IP_ADAPTER_DHCP_ENABLED = 0x4       # the adapter's Flags (Learn, IP_ADAPTER_ADDRESSES)


# -- what the walk hands out: plain Python, nothing pointing into the buffer -------- #
class AddressRow(NamedTuple):
    ip: str                     # with "%zone" for a scoped IPv6 address, as portmap shows it
    version: int                # 4 / 6
    prefix: int | None          # None: not reported, or the "illegal" 255 Learn names
    origin: int                 # NL_PREFIX_ORIGIN: 1 manual, 2 well-known, 3 DHCP, 4 RA
    suffix: int                 # NL_SUFFIX_ORIGIN: 5 random
    dad: int                    # NL_DAD_STATE: 1 tentative, 2 duplicate, 3 deprecated, 4 preferred


class AdapterRow(NamedTuple):
    key: str                    # AdapterName: permanent, unlike the indexes (Learn)
    if_index: int               # IfIndex: the IPv4 interface
    ipv6_index: int             # 0 when IPv6 is not available on it
    name: str                   # FriendlyName, what ipconfig and Settings show
    description: str            # the driver's own name for the device
    kind: int                   # IfType (IANA): 6 Ethernet, 71 Wi-Fi, 24 loopback...
    status: int                 # OperStatus (RFC 2863): 1 up, 2 down...
    mac: str                    # "AA-BB-CC-DD-EE-FF", "" without a link layer
    mtu: int
    receive_bps: int | None     # None: not in the record the system wrote
    transmit_bps: int | None
    dhcp: bool
    dhcp_server: str
    addresses: tuple            # of AddressRow
    gateways: tuple             # of str
    dns_servers: tuple          # of str
    dns_suffix: str
    ipv4_metric: int | None
    ipv6_metric: int | None
    # The DNS servers above that are this computer's own resolver, which asks the
    # servers on the other adapters (systemd-resolved on Linux). Windows lists none.
    stub_dns: tuple = ()


class Reading(NamedTuple):
    adapters: tuple             # of AdapterRow, in the system's order
    internet: dict              # IP version -> interface index of the route out; 0 = none


class AdaptersUnavailable(Exception):
    """The adapter list could not be read. ``reason``: "not_ready" for the one
    documented failure a person can wait out, "changing" for a Linux list that kept
    changing while it was read, "" for any other."""

    def __init__(self, reason, detail=""):
        super().__init__(detail or reason)
        self.reason = reason


# -- reading the record ------------------------------------------------------------- #
class _Answer(NamedTuple):
    """The bytes the call filled: ``[start, end)`` of the caller's buffer."""
    start: int
    end: int

    @classmethod
    def of(cls, buffer):
        start = ctypes.addressof(buffer)
        return cls(start, start + ctypes.sizeof(buffer))

    def room(self, pointer, need):
        """Bytes from ``pointer`` to the end of the answer. Raises
        ``AdaptersUnavailable`` unless ``need`` bytes from ``pointer`` lie inside it."""
        if not (self.start <= pointer and pointer + need <= self.end):
            raise AdaptersUnavailable("", "GetAdaptersAddresses: a pointer outside its answer")
        return self.end - pointer


def _has(record, cls, field):
    """``field`` lies inside the ``Length`` the system wrote for this record."""
    spec = getattr(cls, field)
    return spec.offset + spec.size <= record.Length


def _text_at(pointer, unit, encoding, answer):
    """The NUL-terminated string at ``pointer``, read ``unit`` by unit: at most
    MAX_TEXT of them, and none past the end of the answer."""
    if not pointer:
        return ""
    width = ctypes.sizeof(unit)
    room = answer.room(pointer, width) // width
    cells = ctypes.cast(pointer, ctypes.POINTER(unit))
    out = []
    for i in range(min(MAX_TEXT, room)):
        value = cells[i]
        if not value:
            break
        out.append(value)
    raw = b"".join(struct.pack("<H" if unit is ctypes.c_uint16 else "<B", v) for v in out)
    return raw.decode(encoding, errors="replace")


def _wide(pointer, answer):
    return _text_at(pointer, ctypes.c_uint16, "utf-16-le", answer)


def _narrow(pointer, answer):
    return _text_at(pointer, ctypes.c_uint8, "ascii", answer)


def _sockaddr(address, answer):
    """``(text, version)`` of a SOCKET_ADDRESS, or ``("", 0)`` for none or an unknown family."""
    length = int(address.iSockaddrLength)
    if not address.lpSockaddr or length < 2:
        return "", 0
    length = min(length, 128)
    answer.room(address.lpSockaddr, length)
    raw = ctypes.string_at(address.lpSockaddr, length)
    family = struct.unpack_from("<H", raw)[0]
    if family == AF_INET and len(raw) >= 8:
        return str(ipaddress.IPv4Address(raw[4:8])), 4
    if family == AF_INET6 and len(raw) >= 28:
        text = str(ipaddress.IPv6Address(raw[8:24]))
        scope = struct.unpack_from("<I", raw, 24)[0]
        return (f"{text}%{scope}" if scope else text), 6
    return "", 0


def _chain(first, answer, limit=None):
    """The records of a C linked list, at most ``limit`` (MAX_ENTRIES) of them, each
    one whole inside ``answer`` before it is read.

    The bound is read at the call, not baked into a default argument when the
    module loads - a default would keep the value it had then.
    """
    node = first
    for _ in range(MAX_ENTRIES if limit is None else limit):
        if not node:
            return
        answer.room(ctypes.cast(node, ctypes.c_void_p).value, ctypes.sizeof(node._type_))
        record = node.contents
        yield record
        node = record.Next


def _address_row(unicast, answer):
    ip, version = _sockaddr(unicast.Address, answer)
    prefix = None
    if _has(unicast, _Unicast, "OnLinkPrefixLength"):
        prefix = int(unicast.OnLinkPrefixLength)
        if prefix > (32 if version == 4 else 128):
            prefix = None               # Learn: 255 "is commonly used" for illegal
    return AddressRow(ip, version, prefix, int(unicast.PrefixOrigin),
                      int(unicast.SuffixOrigin), int(unicast.DadState))


def _addresses(first, answer):
    return tuple(text for text, version in
                 (_sockaddr(node.Address, answer) for node in _chain(first, answer)) if version)


def _optional(record, field, convert=int):
    return convert(getattr(record, field)) if _has(record, _Adapter, field) else None


def _adapter_row(record, answer):
    """One ``_Adapter`` as an ``AdapterRow`` - every field copied out of the buffer."""
    mac_length = min(int(record.PhysicalAddressLength), 8)
    mac = "-".join(f"{b:02X}" for b in bytes(record.PhysicalAddress)[:mac_length])
    unicast = tuple(_address_row(u, answer) for u in _chain(record.FirstUnicastAddress, answer))
    gateways = (_addresses(record.FirstGatewayAddress, answer)
                if _has(record, _Adapter, "FirstGatewayAddress") else ())
    dhcp_server = (_sockaddr(record.Dhcpv4Server, answer)[0]
                   if _has(record, _Adapter, "Dhcpv4Server") else "")
    ipv6_index = _optional(record, "Ipv6IfIndex") or 0
    return AdapterRow(
        _narrow(record.AdapterName, answer), int(record.IfIndex), ipv6_index,
        _wide(record.FriendlyName, answer), _wide(record.Description, answer),
        int(record.IfType), int(record.OperStatus), mac, int(record.Mtu),
        _optional(record, "ReceiveLinkSpeed"), _optional(record, "TransmitLinkSpeed"),
        bool(record.Flags & IP_ADAPTER_DHCP_ENABLED), dhcp_server, unicast, gateways,
        _addresses(record.FirstDnsServerAddress, answer), _wide(record.DnsSuffix, answer),
        _optional(record, "Ipv4Metric"), _optional(record, "Ipv6Metric"))


def _sockaddr_bytes(version, text):
    """A ``sockaddr_in`` / ``sockaddr_in6`` for a route lookup (port 0, no scope)."""
    packed = ipaddress.ip_address(text).packed
    if version == 4:
        return struct.pack("<HH4s8x", AF_INET, 0, packed)
    return struct.pack("<HHI16sI", AF_INET6, 0, 0, packed, 0)


# -- the binding --------------------------------------------------------------------- #
def _iphlpapi():
    """iphlpapi with full prototypes for the two calls made here; None off Windows.

    Declared because both take pointers: without ``argtypes`` ctypes passes every
    argument as a 32-bit int (``tests/test_native_prototypes.py``, which walks this
    factory).
    """
    if not sys.platform.startswith("win"):
        return None
    return _declared(ctypes.WinDLL("iphlpapi.dll"))  # pragma: no cover - Windows only (the DLL)


def _declared(lib):
    """``lib`` with the prototypes of the two calls made here (Microsoft Learn)."""
    lib.GetAdaptersAddresses.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                         ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    lib.GetAdaptersAddresses.restype = ctypes.c_uint32
    lib.GetBestInterfaceEx.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    lib.GetBestInterfaceEx.restype = ctypes.c_uint32
    return lib


class _Native:
    """The two calls. ``iphlpapi`` is injectable, so the walk runs in tests anywhere."""

    def __init__(self, iphlpapi=None):
        self.iphlpapi = iphlpapi if iphlpapi is not None else _iphlpapi()

    def adapters(self):
        """Every adapter as ``AdapterRow``, in the system's order. Raises
        ``AdaptersUnavailable`` when the list cannot be read."""
        size = ctypes.c_uint32(START_BYTES)
        rc = ERROR_BUFFER_OVERFLOW
        for _ in range(TRIES):
            buffer = ctypes.create_string_buffer(size.value)
            rc = self.iphlpapi.GetAdaptersAddresses(AF_UNSPEC, FLAGS, None, buffer,
                                                    ctypes.byref(size))
            if rc != ERROR_BUFFER_OVERFLOW:
                break
        if rc == ERROR_NO_DATA:
            return ()                   # "no addresses were found": none to list
        if rc == ERROR_ADDRESS_NOT_ASSOCIATED:
            raise AdaptersUnavailable("not_ready", f"GetAdaptersAddresses answered {rc}")
        if rc:
            raise AdaptersUnavailable("", f"GetAdaptersAddresses answered {rc}")
        # Every record is copied out before `buffer` goes: the list, its addresses
        # and its strings all live inside it (see portmap._Native._fetch), and each
        # pointer is checked against it before it is followed (`_Answer`).
        answer = _Answer.of(buffer)
        first = ctypes.cast(buffer, ctypes.POINTER(_Adapter))
        return tuple(_adapter_row(record, answer)
                     for record in _chain(first, answer, MAX_ADAPTERS))

    def best_interface(self, version):
        """The interface index the route to the internet leaves through; 0 for none.

        0 is never a real index, and is what the call leaves behind when it fails -
        measured 2026-10-13 on a machine without an IPv6 route: error 1231
        (ERROR_NETWORK_UNREACHABLE) and index 0. So a failure reads as "no adapter
        is the way out", never as the adapter whose IPv6 index is 0 (IPv6 off).
        """
        raw = _sockaddr_bytes(version, INTERNET_PROBES[version])
        destination = ctypes.create_string_buffer(raw, len(raw))
        index = ctypes.c_uint32(0)
        rc = self.iphlpapi.GetBestInterfaceEx(destination, ctypes.byref(index))
        return int(index.value) if rc == 0 else 0


# -- Linux: the kernel's tables, in the rows above -------------------------------- #
# The link layer (ARPHRD_*, include/uapi/linux/if_arp.h) as the IANA ifType Windows
# reports, so one table of words serves both systems.
ARPHRD_ETHER, ARPHRD_PPP, ARPHRD_LOOPBACK, ARPHRD_NONE = 1, 512, 772, 65534
ARPHRD_TUNNELS = frozenset({768, 769, 776, 778, 823})   # ipip, ip6tnl, sit, gre, ip6gre
IF_OTHER, IF_ETHERNET, IF_PPP, IF_LOOPBACK, IF_VIRTUAL, IF_WIFI, IF_TUNNEL = (
    1, 6, 23, 24, 53, 71, 131)
# IF_OPER_* are RFC 2863's states numbered the kernel's way; OperStatus numbers them
# the RFC's way.
IF_OPER_UNKNOWN = 0
OPER_STATUS = {0: 4, 1: 6, 2: 2, 3: 7, 4: 3, 5: 5, 6: 1}
STATUS_UP, STATUS_UNKNOWN = 1, 4
IFF_UP, IFF_LOWER_UP = 0x1, 0x10000
# IFA_F_* (include/uapi/linux/if_addr.h). 0x01 is TEMPORARY for IPv6 and SECONDARY
# for IPv4 - one bit, two meanings (measured).
IFA_F_TEMPORARY, IFA_F_OPTIMISTIC, IFA_F_DADFAILED = 0x01, 0x04, 0x08
IFA_F_DEPRECATED, IFA_F_TENTATIVE, IFA_F_PERMANENT = 0x20, 0x40, 0x80
IFA_F_MANAGETEMPADDR = 0x100
IFA_PROTO_KERNEL_RA = 2
RTPROT_DHCP = 16
RT_TABLE_LOCAL = 255
RTN_UNICAST = 1
# NL_PREFIX_ORIGIN and NL_DAD_STATE, as AddressRow carries them, and one origin of
# the program's own: an address with a lifetime the kernel cannot say the source of.
ORIGIN_MANUAL, ORIGIN_WELL_KNOWN, ORIGIN_DHCP, ORIGIN_ROUTER = 1, 2, 3, 4
LEASE = -1
SUFFIX_RANDOM = 5
DAD_TENTATIVE, DAD_DUPLICATE, DAD_DEPRECATED, DAD_PREFERRED = 1, 2, 3, 4
_SCOPED = (ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("169.254.0.0/16"),
           ipaddress.ip_network("::1/128"), ipaddress.ip_network("fe80::/10"))

# The resolver's own files. glibc asks the first three servers (MAXNS) and nothing
# after them; systemd-resolved, when /etc/resolv.conf sends programs to its stub,
# asks the servers in its own file.
RESOLV_CONF = "etc/resolv.conf"
RESOLVED_CONF = "run/systemd/resolve/resolv.conf"
RESOLVER_STUBS = frozenset({"127.0.0.53", "127.0.0.54"})
MAX_NAMESERVERS = 3


def _linux_status(link):
    """OperStatus. The kernel says UNKNOWN for a driver that keeps no state - the
    loopback, a dummy, WireGuard (measured) - and its documentation
    (networking/operstates.rst) says such an adapter "must be considered for user
    data": up, when it is switched on and has its link."""
    if (link.operstate == IF_OPER_UNKNOWN
            and link.flags & IFF_UP and link.flags & IFF_LOWER_UP):
        return STATUS_UP
    return OPER_STATUS.get(link.operstate, STATUS_UNKNOWN)


def _linux_kind(link, wireless):
    if link.arphrd == ARPHRD_LOOPBACK:
        return IF_LOOPBACK
    if link.arphrd == ARPHRD_ETHER:
        if wireless:
            return IF_WIFI
        return IF_VIRTUAL if link.kind else IF_ETHERNET
    if link.arphrd == ARPHRD_NONE or link.arphrd in ARPHRD_TUNNELS:
        return IF_TUNNEL                    # tun, WireGuard, the IP-in-IP family
    return IF_PPP if link.arphrd == ARPHRD_PPP else IF_OTHER


def _linux_mac(raw):
    """As ``ip link`` writes it; "" for none, and for the loopback's six zeros."""
    return ":".join(f"{b:02x}" for b in raw) if any(raw) else ""


def _linux_origin(address, ip):
    if any(ip in network for network in _SCOPED if network.version == ip.version):
        return ORIGIN_WELL_KNOWN
    if address.flags & IFA_F_PERMANENT:
        return ORIGIN_MANUAL
    if (address.proto == IFA_PROTO_KERNEL_RA
            or (ip.version == 6 and address.flags & (IFA_F_TEMPORARY | IFA_F_MANAGETEMPADDR))):
        return ORIGIN_ROUTER
    # A lifetime and no word from the kernel on who gave it: on IPv4 only DHCP does
    # that; on IPv6 DHCPv6 and a router's advertisement both do, and NetworkManager
    # makes the second kind itself, so the kernel cannot tell them apart.
    return ORIGIN_DHCP if ip.version == 4 else LEASE


def _linux_dad(address):
    if address.flags & IFA_F_DADFAILED:     # it comes with TENTATIVE (measured)
        return DAD_DUPLICATE
    if address.flags & (IFA_F_TENTATIVE | IFA_F_OPTIMISTIC):
        return DAD_TENTATIVE
    if address.flags & IFA_F_DEPRECATED or address.preferred == 0:
        return DAD_DEPRECATED
    return DAD_PREFERRED


def _linux_address(address):
    ip = ipaddress.ip_address(address.ip)
    suffix = SUFFIX_RANDOM if ip.version == 6 and address.flags & IFA_F_TEMPORARY else 0
    return AddressRow(address.ip, ip.version, address.prefix, _linux_origin(address, ip),
                      suffix, _linux_dad(address))


def _nameservers(text, limit):
    """The ``nameserver`` addresses of a resolv.conf, first ``limit`` of them."""
    found = []
    for line in (text or "").splitlines():
        words = line.split()
        if len(words) >= 2 and words[0] == "nameserver":
            found.append(words[1])
    return found[:limit]


class _Device(NamedTuple):
    driver: str
    wireless: bool
    speed_bps: int | None


class _Linux:
    """The kernel's tables as ``AdapterRow``s. ``talk`` (one rtnetlink request) and
    ``root`` (where /sys, /etc and /run are) are injectable, so the rows are made in
    tests anywhere from a real kernel's bytes.

    Where Linux says it differently: the key is ``if:`` and the adapter's name - the
    name stays when the adapter is made again, its index does not, and a name cannot
    hold ":" (the kernel refuses it), so no key is ever the proxy row's. One index
    serves IPv4 and IPv6. The MAC is written as ``ip link`` writes it. DHCP is "yes"
    when an IPv4 address has a lease or a default route came from DHCP; who served
    it, and the DNS suffix, sit only in files NetworkManager keeps for itself, so
    they are not shown. The metric is the default route's. Each DNS server is shown
    at the adapter the kernel would send to it through.
    """

    def __init__(self, talk=None, root="/"):
        self.talk = talk or rtnetlink.exchange
        self.root = root

    def adapters(self):
        try:
            tables = rtnetlink.read(self.talk)
        except rtnetlink.Changing as exc:
            raise AdaptersUnavailable("changing", str(exc)) from exc
        except OSError as exc:
            raise AdaptersUnavailable("", f"rtnetlink: {exc}") from exc
        links = tables.links[:MAX_ADAPTERS]
        try:
            dns, stubs = self._dns(links)
        except OSError as exc:      # a resolver file it may not read costs the DNS servers only
            crashlog.note(exc, "adapters.dns")
            dns, stubs = {}, frozenset()
        mine = _by_link(tables)
        return tuple(self._row(link, mine.get(link.ifindex, ([], [])), dns.get(link.ifindex, ()),
                               stubs) for link in links)

    def best_interface(self, version):
        return rtnetlink.route_to(INTERNET_PROBES[version], self.talk)

    # -- one adapter -------------------------------------------------------- #
    def _row(self, link, mine, dns, stubs):
        """``mine``: the link's addresses and default routes (``_by_link``)."""
        addresses, defaults = mine
        name = link.name.decode("utf-8", errors="replace")
        status = _linux_status(link)
        device = self._device(link, status == STATUS_UP)
        rows = tuple(_linux_address(a) for a in addresses[:MAX_ENTRIES])
        gateways = tuple(dict.fromkeys(r.gateway for r in defaults if r.gateway))[:MAX_ENTRIES]
        dhcp = (any(a.version == 4 and a.origin == ORIGIN_DHCP for a in rows)
                or any(r.protocol == RTPROT_DHCP for r in defaults))
        speed = device.speed_bps
        return AdapterRow(
            "if:" + link.name.decode("utf-8", errors="backslashreplace"), link.ifindex,
            link.ifindex if any(a.version == 6 for a in rows) else 0, name,
            device.driver or link.kind, _linux_kind(link, device.wireless), status,
            _linux_mac(link.address), link.mtu, speed, speed, dhcp, "", rows, gateways,
            tuple(dns[:MAX_ENTRIES]), "", _metric(defaults, rtnetlink.LINUX_AF_INET),
            _metric(defaults, rtnetlink.LINUX_AF_INET6),
            tuple(server for server in dns if server in stubs))

    def _device(self, link, up):
        """The driver, Wi-Fi and speed sysfs gives for ``link``; nothing of it for an
        adapter gone since the list was read. The speed only for one that is up: down,
        the kernel answers EINVAL, and some drivers ask the hardware first."""
        try:
            # sysfs names the adapter by its bytes (a Windows runner's path cannot
            # hold them all: a ValueError there, never on Linux).
            base = os.path.join(os.fsencode(self.root), b"sys", b"class", b"net", link.name)
        except ValueError:
            return _Device("", False, None)
        try:
            driver = os.path.basename(os.readlink(os.path.join(base, b"device", b"driver")))
        except OSError:
            driver = b""
        wireless = (os.path.isdir(os.path.join(base, b"wireless"))
                    or os.path.exists(os.path.join(base, b"phy80211")))
        return _Device(driver.decode("utf-8", errors="replace"), wireless,
                       _speed(os.path.join(base, b"speed")) if up else None)

    # -- the DNS servers ---------------------------------------------------- #
    def _dns(self, links):
        """``{index: [server, ...]}`` and the servers that are a local stub."""
        listed = _nameservers(paths.read_small_file(self._path(RESOLV_CONF)), MAX_NAMESERVERS)
        stubs = RESOLVER_STUBS & set(listed)
        servers = list(listed)
        if stubs:
            servers += _nameservers(paths.read_small_file(self._path(RESOLVED_CONF)),
                                    MAX_ENTRIES)
        by_name = {link.name.decode("utf-8", errors="replace"): link.ifindex for link in links}
        out: dict = {}
        for server in dict.fromkeys(servers):
            index = self._dns_index(server, by_name)
            if index:
                out.setdefault(index, []).append(server.split("%")[0])
        return out, stubs

    def _dns_index(self, server, by_name):
        """The adapter a query to ``server`` leaves through: the one its zone names,
        else the kernel's route to it. 0 when there is none."""
        ip, _, zone = server.partition("%")
        if zone:
            return by_name.get(zone, 0)
        try:
            return rtnetlink.route_to(ip, self.talk)
        except (OSError, ValueError) as exc:
            crashlog.note(exc, "adapters.dns_route")
            return 0

    def _path(self, relative):
        return os.path.join(self.root, relative)


def _by_link(tables):
    """``{ifindex: ([address, ...], [default route, ...])}`` - each table walked once, not
    once per adapter: a host with hundreds of container adapters has thousands of rows."""
    out: dict = {}
    for address in tables.addresses:
        if address.ip:
            out.setdefault(address.ifindex, ([], []))[0].append(address)
    for route in tables.routes:
        if route.dst_len == 0 and route.kind == RTN_UNICAST and route.table != RT_TABLE_LOCAL:
            out.setdefault(route.oif, ([], []))[1].append(route)
    return out


def _speed(path):
    """Bits per second from sysfs' ``speed`` (Mbit/s); None where it says none: no
    file, EINVAL (no link speed to give) or -1 (the driver does not know)."""
    try:
        with open(path, "rb") as f:
            mbps = int(f.read().strip() or b"0")
    except (OSError, ValueError):
        return None
    return mbps * 10 ** 6 if mbps > 0 else None


def _metric(defaults, family):
    metrics = [r.priority for r in defaults if r.family == family and r.priority is not None]
    return min(metrics) if metrics else None


def supported():
    """The adapter list is read on Windows (since 2026-09-24) and on Linux (2026-10-27)."""
    return sys.platform.startswith(("win", "linux"))


def _system_class():
    return _Linux if sys.platform.startswith("linux") else _Native


def read(native=None):
    """The adapters and the route out, for IPv4 and IPv6. Runs on a worker; may raise.

    A route lookup that fails costs the "internet" mark and nothing else: the list
    is still true without it.
    """
    native = native or _system_class()()
    rows = native.adapters()
    internet = {}
    for version in (4, 6):
        try:
            internet[version] = native.best_interface(version)
        except Exception as exc:
            crashlog.note(exc, "adapters.route")
            internet[version] = 0
    return Reading(rows, internet)
