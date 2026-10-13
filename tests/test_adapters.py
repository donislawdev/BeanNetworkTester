"""The adapter list of the Tools tab (``beantester/adapters.py``): the walk over the
linked lists ``GetAdaptersAddresses`` writes, and the route lookup.

The fake here is one level below the module: an ``iphlpapi`` that lays a real list
out in the CALLER's buffer - adapters, their addresses, gateways, DNS servers and
UTF-16 strings, linked by pointers - the way Windows does. The module's structures
are built from fixed-width integers, so this runs on the Linux runner too and the
walk is proven there; that the layout is the one Windows writes is what the live
test at the bottom proves on Windows (``Length`` against ``sizeof``).
"""
import ctypes
import ipaddress
import struct
import sys

import pytest

from beantester import adapters, crashlog
from beantester.adapters import _Adapter, _AddressNode, _Unicast
from fakes import check

ALIGN = 8


def _sockaddr(text, scope=0):
    address = ipaddress.ip_address(text)
    if address.version == 4:
        return struct.pack("<HH4s8x", adapters.AF_INET, 0, address.packed)
    return struct.pack("<HHI16sI", adapters.AF_INET6, 0, 0, address.packed, scope)


class _Writer:
    """Places records one after another in a buffer - or, with no buffer, only counts."""

    def __init__(self, buffer=None):
        self.buffer = buffer
        self.at = 0

    def take(self, size):
        offset = self.at
        self.at += (size + ALIGN - 1) // ALIGN * ALIGN
        return offset

    def address(self, offset):
        return ctypes.addressof(self.buffer) + offset

    def record(self, cls):
        offset = self.take(ctypes.sizeof(cls))
        return None if self.buffer is None else (cls.from_buffer(self.buffer, offset), offset)

    def raw(self, data):
        offset = self.take(len(data))
        if self.buffer is None:
            return 0
        ctypes.memmove(self.address(offset), data, len(data))
        return self.address(offset)

    def wide(self, text):
        return self.raw(text.encode("utf-16-le") + b"\0\0")

    def narrow(self, text):
        return self.raw(text.encode("ascii") + b"\0")


def _lay_out(writer, specs):
    """Write ``specs`` (dicts, see ADAPTER) as the system would; return the bytes used."""
    previous = None
    for spec in specs:
        placed = writer.record(_Adapter)
        if placed is None:
            record = None
        else:
            record, offset = placed
            if previous is not None:
                previous.Next = ctypes.cast(writer.address(offset), ctypes.POINTER(_Adapter))
        _fill_adapter(writer, record, spec)
        previous = record
    return writer.at


def _chain(writer, cls, items, fill):
    first, previous = None, None
    for item in items:
        placed = writer.record(cls)
        node = placed and placed[0]
        if node is not None:
            pointer = ctypes.cast(writer.address(placed[1]), ctypes.POINTER(cls))
            if previous is None:
                first = pointer
            else:
                previous.Next = pointer
        fill(writer, node, item)
        previous = node
    return first


def _fill_unicast(writer, node, item):
    ip, prefix, origin, suffix, dad = item[:5]
    scope = item[5] if len(item) > 5 else 0
    raw = _sockaddr(ip, scope)
    pointer = writer.raw(raw)
    if node is None:
        return
    node.Length = ctypes.sizeof(_Unicast)
    node.Address.lpSockaddr, node.Address.iSockaddrLength = pointer, len(raw)
    node.PrefixOrigin, node.SuffixOrigin, node.DadState = origin, suffix, dad
    node.OnLinkPrefixLength = prefix


def _fill_node(writer, node, text):
    raw = _sockaddr(text)
    pointer = writer.raw(raw)
    if node is not None:
        node.Length = ctypes.sizeof(_AddressNode)
        node.Address.lpSockaddr, node.Address.iSockaddrLength = pointer, len(raw)


def _fill_adapter(writer, record, spec):
    # None stands for a NULL pointer, which the system may leave in a text field.
    texts = {name: 0 if spec.get(name, "") is None else writer.wide(spec.get(name, ""))
             for name in ("name", "description", "suffix")}
    key = writer.narrow(spec.get("key", "{0}"))
    unicast = _chain(writer, _Unicast, spec.get("addresses", ()), _fill_unicast)
    gateways = _chain(writer, _AddressNode, spec.get("gateways", ()), _fill_node)
    dns = _chain(writer, _AddressNode, spec.get("dns", ()), _fill_node)
    dhcp = _sockaddr(spec["dhcp_server"]) if spec.get("dhcp_server") else b""
    dhcp_pointer = writer.raw(dhcp) if dhcp else 0
    if record is None:
        return
    record.Length = spec.get("length", ctypes.sizeof(_Adapter))
    record.IfIndex = spec.get("index", 1)
    record.Ipv6IfIndex = spec.get("ipv6_index", 0)
    record.AdapterName = key
    record.FriendlyName, record.Description = texts["name"], texts["description"]
    record.DnsSuffix = texts["suffix"]
    mac = spec.get("mac", b"")
    for i, byte in enumerate(mac):
        record.PhysicalAddress[i] = byte
    record.PhysicalAddressLength = len(mac)
    record.Flags = spec.get("flags", 0)
    record.Mtu = spec.get("mtu", 1500)
    record.IfType = spec.get("kind", 6)
    record.OperStatus = spec.get("status", 1)
    record.ReceiveLinkSpeed = spec.get("rx", 0)
    record.TransmitLinkSpeed = spec.get("tx", 0)
    record.Ipv4Metric, record.Ipv6Metric = spec.get("metrics", (0, 0))
    if unicast is not None:
        record.FirstUnicastAddress = unicast
    if gateways is not None:
        record.FirstGatewayAddress = gateways
    if dns is not None:
        record.FirstDnsServerAddress = dns
    if dhcp:
        record.Dhcpv4Server.lpSockaddr, record.Dhcpv4Server.iSockaddrLength = \
            dhcp_pointer, len(dhcp)


class FakeIphlpapi:
    """Writes the list into the caller's buffer the way iphlpapi does."""

    def __init__(self, specs=(), rc=0, grow_forever=False, routes=None):
        self.specs = list(specs)
        self.rc = rc
        self.grow_forever = grow_forever
        self.routes = routes or {}      # IP version -> (rc, index)
        self.sizes = []                 # the buffer size offered on each call
        self.asked = []                 # the destinations of the route lookups

    def GetAdaptersAddresses(self, family, flags, _reserved, buffer, size_ref):
        size = size_ref._obj
        self.sizes.append(size.value)
        assert (family, flags) == (adapters.AF_UNSPEC, adapters.FLAGS), (family, flags)
        if self.rc:
            return self.rc
        if not self.specs:
            return adapters.ERROR_NO_DATA   # what Windows answers with nothing to list
        need = _lay_out(_Writer(), self.specs)
        if self.grow_forever or size.value < need:
            size.value = max(need, size.value + 4096)
            return adapters.ERROR_BUFFER_OVERFLOW
        _lay_out(_Writer(buffer), self.specs)
        return 0

    def GetBestInterfaceEx(self, destination, index_ref):
        raw = bytes(destination)
        family = struct.unpack_from("<H", raw)[0]
        version = 4 if family == adapters.AF_INET else 6
        packed = raw[4:8] if version == 4 else raw[8:24]
        self.asked.append(str(ipaddress.ip_address(packed)))
        rc, index = self.routes.get(version, (1231, 0))
        if rc == 0:
            index_ref._obj.value = index
        return rc


ETHERNET = {"key": "{E1}", "index": 9, "ipv6_index": 9, "name": "Ethernet",
            "description": "Intel(R) Ethernet", "kind": 6, "status": 1,
            "mac": bytes([0xAA, 0xBB, 0xCC, 0x01, 0x02, 0x03]), "mtu": 1500,
            "rx": 10 ** 9, "tx": 10 ** 8, "flags": 0x4 | 0x80, "dhcp_server": "192.168.1.1",
            "addresses": [("192.168.1.5", 24, 3, 3, 4), ("fe80::1", 64, 2, 4, 1, 9)],
            "gateways": ["192.168.1.1"], "dns": ["192.168.1.1", "fec0:0:0:ffff::1"],
            "suffix": "home", "metrics": (35, 40)}
VIRTUAL = {"key": "{V2}", "index": 21, "name": "Połączenie lokalne* 1",
           "description": None, "kind": 53, "status": 2, "mtu": 1500,
           "addresses": [("169.254.19.100", 16, 2, 4, 1)]}


def _native(fake):
    return adapters._Native(iphlpapi=fake)


def test_a_list_the_system_writes_is_read_whole_on_any_platform():
    rows = _native(FakeIphlpapi([ETHERNET, VIRTUAL])).adapters()
    check("both adapters, in the system's order", [r.key for r in rows] == ["{E1}", "{V2}"],
          f"({rows})")
    first, second = rows
    want = adapters.AdapterRow(
        "{E1}", 9, 9, "Ethernet", "Intel(R) Ethernet", 6, 1, "AA-BB-CC-01-02-03", 1500,
        10 ** 9, 10 ** 8, True, "192.168.1.1",
        (adapters.AddressRow("192.168.1.5", 4, 24, 3, 3, 4),
         adapters.AddressRow("fe80::1%9", 6, 64, 2, 4, 1)),
        ("192.168.1.1",), ("192.168.1.1", "fec0:0:0:ffff::1"), "home", 35, 40)
    check("every field of the first, copied out of the buffer", first == want,
          f"\n got {first}\nwant {want}")
    check("a name outside ASCII comes back whole (UTF-16 read by hand)",
          second.name == "Połączenie lokalne* 1", f"({second.name!r})")
    check("no MAC, no gateway, no DNS: empty, not garbage",
          (second.mac, second.gateways, second.dns_servers, second.dhcp) == ("", (), (), False),
          f"({second})")
    check("a text the system left NULL reads as empty", second.description == "",
          f"({second.description!r})")


def test_an_address_of_a_family_this_does_not_know_is_left_out():
    """A SOCKET_ADDRESS that is not IPv4 or IPv6 (or is too short for its family)
    gives no address - never bytes read as one."""
    cases = {"unknown family": struct.pack("<H14x", 17),
             "IPv6, cut short": struct.pack("<H10x", adapters.AF_INET6),
             "nothing at all": b""}
    for name, raw in cases.items():
        data = ctypes.create_string_buffer(raw, max(len(raw), 1))
        address = adapters._SocketAddress(ctypes.addressof(data) if raw else 0, len(raw))
        check(name, adapters._sockaddr(address) == ("", 0), f"({adapters._sockaddr(address)})")


def test_both_calls_are_declared_with_their_prototypes():
    """``_declared`` runs on every platform against a stand-in; that the real DLL gets
    the same is ``test_native_prototypes.py``'s walk on Windows."""
    import types
    lib = types.SimpleNamespace(GetAdaptersAddresses=types.SimpleNamespace(),
                                GetBestInterfaceEx=types.SimpleNamespace())
    adapters._declared(lib)
    check("the list call takes five, the last a pointer to its size",
          len(lib.GetAdaptersAddresses.argtypes) == 5
          and lib.GetAdaptersAddresses.argtypes[4] == ctypes.POINTER(ctypes.c_uint32))
    check("the route lookup takes the address and a pointer to the index",
          lib.GetBestInterfaceEx.argtypes == [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)])
    check("both answer a 32-bit code",
          lib.GetAdaptersAddresses.restype is lib.GetBestInterfaceEx.restype is ctypes.c_uint32)


def test_a_field_past_the_records_length_is_not_read():
    """Learn: the structure grew three times, and ``Length`` says which one was
    written. The XP SP1 record ends before the link speeds; the XP unicast record
    before the prefix length."""
    xp = dict(ETHERNET, length=_Adapter.TransmitLinkSpeed.offset)
    rows = _native(FakeIphlpapi([xp])).adapters()
    row = rows[0]
    check("the fields the old record has are read", row.mtu == 1500 and row.ipv6_index == 9,
          f"({row})")
    check("the newer ones are not", (row.receive_bps, row.transmit_bps, row.gateways,
                                     row.dhcp_server, row.ipv4_metric, row.ipv6_metric)
          == (None, None, (), "", None, None), f"({row})")

    class OldUnicast(FakeIphlpapi):
        def GetAdaptersAddresses(self, *args):
            rc = super().GetAdaptersAddresses(*args)
            if rc == 0:
                first = ctypes.cast(args[3], ctypes.POINTER(_Adapter)).contents
                first.FirstUnicastAddress.contents.Length = _Unicast.OnLinkPrefixLength.offset
            return rc

    row = _native(OldUnicast([ETHERNET])).adapters()[0]
    check("an address without the prefix field has no prefix",
          row.addresses[0].prefix is None and row.addresses[1].prefix == 64, f"({row.addresses})")


def test_a_prefix_the_system_calls_illegal_is_not_shown():
    spec = dict(ETHERNET, addresses=[("10.0.0.2", 255, 1, 1, 4), ("fe80::2", 129, 2, 4, 4)])
    row = _native(FakeIphlpapi([spec])).adapters()[0]
    check("255 (Learn's illegal value) and anything past the address width: no prefix",
          [a.prefix for a in row.addresses] == [None, None], f"({row.addresses})")


def test_the_buffer_grows_to_what_the_system_asks_for():
    many = [dict(ETHERNET, key="{%d}" % i, index=i) for i in range(60)]
    fake = FakeIphlpapi(many)
    rows = _native(fake).adapters()
    check("all of them read", len(rows) == 60, f"({len(rows)})")
    check("15 KB first, then the size the system asked for",
          fake.sizes[0] == adapters.START_BYTES and len(fake.sizes) == 2
          and fake.sizes[1] > adapters.START_BYTES, f"({fake.sizes})")


def test_a_list_that_outgrows_every_buffer_is_refused_not_chased():
    fake = FakeIphlpapi([ETHERNET], grow_forever=True)
    with pytest.raises(adapters.AdaptersUnavailable) as caught:
        _native(fake).adapters()
    check("asked as often as Learn says, then gave up", len(fake.sizes) == adapters.TRIES,
          f"({fake.sizes})")
    check("a failure without a reason a person can act on", caught.value.reason == "")


def test_the_documented_answers_of_the_call():
    check("ERROR_NO_DATA: no adapters to list, not a failure",
          _native(FakeIphlpapi(rc=adapters.ERROR_NO_DATA)).adapters() == ())
    for rc, reason in ((adapters.ERROR_ADDRESS_NOT_ASSOCIATED, "not_ready"), (87, "")):
        with pytest.raises(adapters.AdaptersUnavailable) as caught:
            _native(FakeIphlpapi(rc=rc)).adapters()
        check(f"{rc}: reason {reason!r}", caught.value.reason == reason
              and str(rc) in str(caught.value), f"({caught.value.reason!r}, {caught.value})")


def test_a_list_that_never_ends_stops_at_its_bound(monkeypatch):
    """A ``Next`` that points back must not hang the worker."""
    monkeypatch.setattr(adapters, "MAX_ADAPTERS", 5)
    monkeypatch.setattr(adapters, "MAX_ENTRIES", 3)

    class Looped(FakeIphlpapi):
        def GetAdaptersAddresses(self, *args):
            rc = super().GetAdaptersAddresses(*args)
            if rc == 0:
                first = ctypes.cast(args[3], ctypes.POINTER(_Adapter))
                first.contents.Next = first
                unicast = first.contents.FirstUnicastAddress
                unicast.contents.Next = unicast
            return rc

    rows = _native(Looped([ETHERNET])).adapters()
    check("the adapter list stops at its bound", len(rows) == 5, f"({len(rows)})")
    check("and so does an address list", len(rows[0].addresses) == 3, f"({rows[0].addresses})")


def test_a_name_is_read_up_to_its_bound(monkeypatch):
    monkeypatch.setattr(adapters, "MAX_TEXT", 3)
    row = _native(FakeIphlpapi([ETHERNET])).adapters()[0]
    check("cut at the bound, never read past it", row.name == "Eth", f"({row.name!r})")


def test_the_route_out_is_an_index_and_a_failure_is_none():
    """Measured 2026-10-13: without an IPv6 route the call fails with 1231 and leaves
    the index 0. That 0 must never be read as an index."""
    fake = FakeIphlpapi(routes={4: (0, 9), 6: (1231, 0)})
    native = _native(fake)
    check("IPv4: the index of the route out", native.best_interface(4) == 9)
    check("IPv6: no route reads as none", native.best_interface(6) == 0)
    check("the routing table was asked about the probes, nothing else",
          fake.asked == [adapters.INTERNET_PROBES[4], adapters.INTERNET_PROBES[6]],
          f"({fake.asked})")
    reading = adapters.read(native)
    check("read() hands the routes over with the list",
          reading.internet == {4: 9, 6: 0} and len(reading.adapters) == 0, f"({reading})")


def test_a_route_lookup_that_raises_costs_the_mark_and_nothing_else(monkeypatch):
    notes = []
    monkeypatch.setattr(crashlog, "note", lambda exc, area, *a: notes.append(area))

    class Broken(adapters._Native):
        def best_interface(self, version):
            raise OSError("the routing table refused on purpose")

    reading = adapters.read(Broken(iphlpapi=FakeIphlpapi([ETHERNET])))
    check("the list is still read", [r.key for r in reading.adapters] == ["{E1}"])
    check("no route marked", reading.internet == {4: 0, 6: 0}, f"({reading.internet})")
    check("and the failure is recorded", notes == ["adapters.route", "adapters.route"],
          f"({notes})")


def test_the_layout_is_the_one_windows_writes():
    """The sizes Windows 11 x64 reports in ``Length`` (measured 2026-09-24 and
    2026-10-13): 448, 64 and 32 bytes. Pointer-sized fields make the numbers hold
    for a 64-bit interpreter on any platform - the Linux runner included."""
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        pytest.skip("the measured sizes are for a 64-bit process")
    sizes = (ctypes.sizeof(_Adapter), ctypes.sizeof(_Unicast), ctypes.sizeof(_AddressNode))
    check("adapter, unicast address, address node", sizes == (448, 64, 32), f"({sizes})")
    check("the last field of the Vista SP1 record ends inside it",
          _Adapter.FirstDnsSuffix.offset + _Adapter.FirstDnsSuffix.size <= 448)


def _records():                         # pragma: no cover - Windows only (the real call)
    """The raw records of this machine, walked with the module's own structures."""
    lib = adapters._iphlpapi()
    size = ctypes.c_uint32(adapters.START_BYTES)
    for _ in range(adapters.TRIES):
        buffer = ctypes.create_string_buffer(size.value)
        rc = lib.GetAdaptersAddresses(adapters.AF_UNSPEC, adapters.FLAGS, None, buffer,
                                      ctypes.byref(size))
        if rc != adapters.ERROR_BUFFER_OVERFLOW:
            break
    assert rc == 0, rc
    out = []
    for record in adapters._chain(ctypes.cast(buffer, ctypes.POINTER(_Adapter))):
        out.append((record.Length, [u.Length for u in adapters._chain(record.FirstUnicastAddress)]))
    return out


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="the adapter list is Windows'")
def test_windows_writes_the_records_these_structures_describe():  # pragma: no cover - Windows only
    """Every record this machine's system writes is exactly as long as the structure
    the module reads it with - the check that the layout above is Windows' own."""
    records = _records()
    check("the machine has adapters to compare", records, f"({records})")
    for length, unicast in records:
        check("an adapter record is the structure's size", length == ctypes.sizeof(_Adapter),
              f"({length} != {ctypes.sizeof(_Adapter)})")
        check("so is each address record",
              all(n == ctypes.sizeof(_Unicast) for n in unicast), f"({unicast})")
    reading = adapters.read()
    check("and the module reads the same adapters", len(reading.adapters) == len(records),
          f"({len(reading.adapters)} != {len(records)})")
