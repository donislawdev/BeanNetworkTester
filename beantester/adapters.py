"""The network adapters of this computer, as the system's own table lists them.

What ``ipconfig /all`` prints - each adapter's name, state, addresses, gateway, DNS
servers, MAC, MTU - read from ``iphlpapi.GetAdaptersAddresses``, plus which adapter
the route to the internet leaves through (``GetBestInterfaceEx``). For the Tools
tab: read on a click by a worker, never by the packet path
(``tests/test_hot_path.py`` watches both calls).

Nothing here sends a packet. Both calls answer from tables the system keeps - the
adapter list and the routing table - and neither is in the wire-function list of
``tests/test_no_telemetry.py`` (the ping and ARP exports of the same DLL are).

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
"""
import ctypes
import ipaddress
import struct
import sys
from typing import NamedTuple

from . import crashlog

# Where "the internet" is, for the route lookup. The Session panel's own-address
# lookup routes to the same two (``utils.host_identity``), read from here so the
# two can never disagree about which adapter that is. Public DNS resolvers, never
# contacted: only the routing table is asked.
INTERNET_PROBES = {4: "8.8.8.8", 6: "2001:4860:4860::8888"}

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


class Reading(NamedTuple):
    adapters: tuple             # of AdapterRow, in the system's order
    internet: dict              # IP version -> interface index of the route out; 0 = none


class AdaptersUnavailable(Exception):
    """The adapter list could not be read. ``reason``: "not_ready" for the one
    documented failure a person can wait out, "" for any other."""

    def __init__(self, reason, detail=""):
        super().__init__(detail or reason)
        self.reason = reason


# -- reading the record ------------------------------------------------------------- #
def _has(record, cls, field):
    """``field`` lies inside the ``Length`` the system wrote for this record."""
    spec = getattr(cls, field)
    return spec.offset + spec.size <= record.Length


def _text_at(pointer, unit, encoding):
    """The NUL-terminated string at ``pointer``, read ``unit`` by unit, at most MAX_TEXT."""
    if not pointer:
        return ""
    cells = ctypes.cast(pointer, ctypes.POINTER(unit))
    out = []
    for i in range(MAX_TEXT):
        value = cells[i]
        if not value:
            break
        out.append(value)
    raw = b"".join(struct.pack("<H" if unit is ctypes.c_uint16 else "<B", v) for v in out)
    return raw.decode(encoding, errors="replace")


def _wide(pointer):
    return _text_at(pointer, ctypes.c_uint16, "utf-16-le")


def _narrow(pointer):
    return _text_at(pointer, ctypes.c_uint8, "ascii")


def _sockaddr(address):
    """``(text, version)`` of a SOCKET_ADDRESS, or ``("", 0)`` for none or an unknown family."""
    length = int(address.iSockaddrLength)
    if not address.lpSockaddr or length < 2:
        return "", 0
    raw = ctypes.string_at(address.lpSockaddr, min(length, 128))
    family = struct.unpack_from("<H", raw)[0]
    if family == AF_INET and len(raw) >= 8:
        return str(ipaddress.IPv4Address(raw[4:8])), 4
    if family == AF_INET6 and len(raw) >= 28:
        text = str(ipaddress.IPv6Address(raw[8:24]))
        scope = struct.unpack_from("<I", raw, 24)[0]
        return (f"{text}%{scope}" if scope else text), 6
    return "", 0


def _chain(first, limit=None):
    """The records of a C linked list, at most ``limit`` (MAX_ENTRIES) of them.

    The bound is read at the call, not baked into a default argument when the
    module loads - a default would keep the value it had then.
    """
    node = first
    for _ in range(MAX_ENTRIES if limit is None else limit):
        if not node:
            return
        record = node.contents
        yield record
        node = record.Next


def _address_row(unicast):
    ip, version = _sockaddr(unicast.Address)
    prefix = None
    if _has(unicast, _Unicast, "OnLinkPrefixLength"):
        prefix = int(unicast.OnLinkPrefixLength)
        if prefix > (32 if version == 4 else 128):
            prefix = None               # Learn: 255 "is commonly used" for illegal
    return AddressRow(ip, version, prefix, int(unicast.PrefixOrigin),
                      int(unicast.SuffixOrigin), int(unicast.DadState))


def _addresses(first):
    return tuple(text for text, version in (_sockaddr(node.Address) for node in _chain(first))
                 if version)


def _optional(record, field, convert=int):
    return convert(getattr(record, field)) if _has(record, _Adapter, field) else None


def _adapter_row(record):
    """One ``_Adapter`` as an ``AdapterRow`` - every field copied out of the buffer."""
    mac_length = min(int(record.PhysicalAddressLength), 8)
    mac = "-".join(f"{b:02X}" for b in bytes(record.PhysicalAddress)[:mac_length])
    unicast = tuple(_address_row(u) for u in _chain(record.FirstUnicastAddress))
    gateways = (_addresses(record.FirstGatewayAddress)
                if _has(record, _Adapter, "FirstGatewayAddress") else ())
    dhcp_server = (_sockaddr(record.Dhcpv4Server)[0]
                   if _has(record, _Adapter, "Dhcpv4Server") else "")
    ipv6_index = _optional(record, "Ipv6IfIndex") or 0
    return AdapterRow(
        _narrow(record.AdapterName), int(record.IfIndex), ipv6_index,
        _wide(record.FriendlyName), _wide(record.Description), int(record.IfType),
        int(record.OperStatus), mac, int(record.Mtu),
        _optional(record, "ReceiveLinkSpeed"), _optional(record, "TransmitLinkSpeed"),
        bool(record.Flags & IP_ADAPTER_DHCP_ENABLED), dhcp_server, unicast, gateways,
        _addresses(record.FirstDnsServerAddress), _wide(record.DnsSuffix),
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
        # and its strings all live inside it (see portmap._Native._fetch).
        first = ctypes.cast(buffer, ctypes.POINTER(_Adapter))
        return tuple(_adapter_row(record) for record in _chain(first, MAX_ADAPTERS))

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


def supported():
    """The adapter list is read on Windows only (the owner's decision, 2026-09-24)."""
    return sys.platform.startswith("win")


def read(native=None):
    """The adapters and the route out, for IPv4 and IPv6. Runs on a worker; may raise.

    A route lookup that fails costs the "internet" mark and nothing else: the list
    is still true without it.
    """
    native = native or _Native()
    rows = native.adapters()
    internet = {}
    for version in (4, 6):
        try:
            internet[version] = native.best_interface(version)
        except Exception as exc:
            crashlog.note(exc, "adapters.route")
            internet[version] = 0
    return Reading(rows, internet)
