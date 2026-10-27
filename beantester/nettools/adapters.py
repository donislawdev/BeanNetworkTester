"""Network adapters: what ``ipconfig /all`` shows, as rows a table can draw.

The system is read in ``beantester/adapters.py`` - the one module that asks it -
and turned here into what the Tools tab shows: one row per adapter, ranked so the
one that matters is on top, and the details of one adapter as "item | value |
note" rows. Nothing here draws or translates: words a person reads are i18n KEYS
(``Words``), addresses and numbers are the program's own text.

The report a person copies is the program's own text too, in English, like the
diagnostics report it can be added to (``nettools/diagnostics.py``, as an option:
it carries addresses and the MAC, and that report is pasted into public bug
reports).
"""
import ipaddress
import itertools
import time
from typing import NamedTuple

from .. import adapters as system

UP = 1

# The words, by the numbers the system gives. A number not listed is shown as
# itself through the ``code`` key - never as a wrong word.
# OperStatus (IF_OPER_STATUS, RFC 2863 - Microsoft Learn, IP_ADAPTER_ADDRESSES_LH).
STATUS = {1: "up", 2: "down", 3: "testing", 4: "unknown", 5: "dormant",
          6: "not_present", 7: "lower_layer_down"}
# IfType (IANA ifType): Learn's table of common values, plus 53 "propVirtual" -
# two of the seven adapters on the development machine were one (measured).
KINDS = {1: "other", 6: "ethernet", 9: "token_ring", 23: "ppp", 24: "loopback",
         37: "atm", 53: "virtual", 71: "wifi", 131: "tunnel", 144: "firewire"}
# NL_PREFIX_ORIGIN: where an address's network part came from - and one of the
# program's own, for a Linux address with a lifetime and no word on who gave it.
ORIGINS = {0: "other", 1: "manual", 2: "well_known", 3: "dhcp", 4: "router",
           system.LEASE: "lease"}
# NL_DAD_STATE. "preferred" is the normal state and gets no note; "duplicate" is the
# one worth a tester's eye - Learn: "a duplicate IP address has been detected".
# "tentative" is normal on an adapter that is down (all of them there, measured).
DAD = {0: "invalid", 1: "tentative", 2: "duplicate", 3: "deprecated", 4: "preferred"}
PREFERRED, DUPLICATE = 4, 2

# The three DNS servers Windows lists for an adapter that has none of its own -
# old site-local addresses, measured 2026-10-13 on five of seven adapters (with
# zone 1). `ipconfig /all` does NOT print them (measured the same day), so a
# tester comparing the two would think one of them wrong: the note says what they
# are, and the row menu does not offer to limit the impairments to one.
PLACEHOLDER_DNS = frozenset({"fec0:0:0:ffff::1", "fec0:0:0:ffff::2", "fec0:0:0:ffff::3"})


class Words(NamedTuple):
    """Something said in the window's language: an i18n key, and the number a
    ``code`` key shows (a state or type the table above does not name) - or the
    name Linux gave an answer of Ping's (``EPERM``)."""
    key: str
    code: int | str | None = None


def _word(table, prefix, number):
    slug = table.get(number)
    return Words(prefix + slug) if slug else Words(prefix + "code", number)


def status_words(number):
    return _word(STATUS, "tools.adapters.status.", number)


def kind_words(number):
    return _word(KINDS, "tools.adapters.kind.", number)


class Adapter(NamedTuple):
    row: system.AdapterRow
    rank: int                   # the default order: see rank()
    internet: tuple             # the IP versions whose route out leaves here: (4,), (4, 6)...

    @property
    def key(self):
        return self.row.key

    @property
    def up(self):
        return self.row.status == UP

    def first_ipv4(self):
        """The first IPv4 address with its prefix, as the table's column shows it."""
        for address in self.row.addresses:
            if address.version == 4:
                return address_text(address)
        return ""


class Snapshot(NamedTuple):
    adapters: tuple             # of Adapter, ranked
    read_at: float              # time.time() when the read finished
    elapsed_ms: int
    made: int                   # a count, not a clock: the newest snapshot is shown


_MADE = itertools.count(1)


class Unreadable(Exception):
    """The adapter list could not be read, for a reason the person can act on.

    ``user_key`` names it in the window's language (``gui/toolbox/base.py`` shows
    it); the message stays the program's own words, for the crash log.
    """

    def __init__(self, user_key, detail):
        super().__init__(detail)
        self.user_key = user_key


# ``adapters.AdaptersUnavailable.reason`` -> what the person is told.
UNREADABLE_KEYS = {"not_ready": "tools.adapters.error_not_ready",
                   "changing": "tools.adapters.error_changing"}


def supported():
    return system.supported()


def read(native=None):
    """Read the adapters and rank them. Runs on a worker; may raise ``Unreadable``."""
    started = time.perf_counter()
    try:
        reading = system.read(native)
    except system.AdaptersUnavailable as exc:
        raise Unreadable(UNREADABLE_KEYS.get(exc.reason, ""), str(exc)) from exc
    adapters = rank(reading)
    return Snapshot(adapters, time.time(), round((time.perf_counter() - started) * 1000),
                    next(_MADE))


def _internet(row, routes):
    """The versions whose route out leaves through ``row``. An index of 0 is no
    route at all (``adapters._Native.best_interface``), never "the adapter whose
    IPv6 index is 0" - which every adapter without IPv6 has."""
    out = []
    if routes.get(4) and row.if_index == routes[4]:
        out.append(4)
    if routes.get(6) and row.ipv6_index == routes[6]:
        out.append(6)
    return tuple(out)


def rank(reading):
    """The adapters in the order the table opens with: the one the internet goes
    through, then the others that are up, then the rest - each group in the
    system's own order, which follows the route metric on Windows 10 and later
    (Learn, GetAdaptersAddresses). The owner's decision, 2026-09-24."""
    found = [Adapter(row, 0, _internet(row, reading.internet)) for row in reading.adapters]
    order = sorted(range(len(found)),
                   key=lambda i: (not found[i].internet, not found[i].up, i))
    return tuple(found[i]._replace(rank=n) for n, i in enumerate(order))


# -- sorting the table ------------------------------------------------------------ #
def _ip_key(text):
    if not text:
        return None
    return int(ipaddress.ip_address(text.split("/")[0].split("%")[0]))


# Per column, the value to sort by; None sorts last both ways. Ties keep the rank.
SORT_KEYS = {
    "name": lambda a: a.row.name.casefold() or None,
    "status": lambda a: (not a.up, a.row.status),
    "kind": lambda a: a.row.kind,
    "ipv4": lambda a: _ip_key(a.first_ipv4()),
    "internet": lambda a: (not a.internet, a.internet),
}
RANKED = ""     # the sort "column" of the default order: no header carries an arrow


def sort(adapters, column=RANKED, reverse=False):
    """``adapters`` by one column, empty cells last; the default order for ``RANKED``."""
    ranked = sorted(adapters, key=lambda a: a.rank)
    key = SORT_KEYS.get(column)
    if key is None:
        return list(reversed(ranked)) if reverse else ranked
    present = [a for a in ranked if key(a) is not None]
    present.sort(key=key, reverse=reverse)
    return present + [a for a in ranked if key(a) is None]


# -- one adapter's details ------------------------------------------------------- #
class Detail(NamedTuple):
    """One row of the details table. ``item`` and ``value`` are text or ``Words``;
    ``note`` is a tuple of ``Words`` joined on screen."""
    key: str                    # unique within one adapter's rows
    item: object
    value: object
    note: tuple = ()
    address: str = ""           # an address the row menu may put into the Control page
    tag: str = ""               # "duplicate": an address another device also claims


def address_text(address):
    """``192.168.1.5/24`` - the address and its prefix, the way the Control fields
    and ``ipconfig`` write a network."""
    return f"{address.ip}/{address.prefix}" if address.prefix is not None else address.ip


def _address_note(address):
    note = [Words(f"tools.adapters.origin.{ORIGINS.get(address.origin, 'other')}")]
    if address.dad != PREFERRED:
        note.append(Words(f"tools.adapters.dad.{DAD.get(address.dad, 'invalid')}"))
    return tuple(note)


def _bare(ip):
    """An address as a Control field takes it: without an IPv6 zone."""
    return ip.split("%")[0]


def speed_text(bps):
    """Bits per second in the unit that reads best; "" for an unknown speed (0, or
    the all-ones value a driver may report)."""
    if not bps or bps >= 2 ** 64 - 1:
        return ""
    for unit, name in ((10 ** 9, "Gbit/s"), (10 ** 6, "Mbit/s"), (10 ** 3, "kbit/s")):
        if bps >= unit:
            return f"{bps / unit:.3g} {name}"
    return f"{bps} bit/s"


def _speed(row):
    receive, transmit = speed_text(row.receive_bps), speed_text(row.transmit_bps)
    if receive == transmit:
        return receive
    return f"{receive or '-'} / {transmit or '-'}"


def _internet_value(adapter):
    if not adapter.internet:
        return Words("tools.adapters.value.no")
    return ", ".join(f"IPv{v}" for v in adapter.internet)


def details(adapter):
    """The rows of the details table, in the order a person reads a property sheet."""
    row = adapter.row
    out = [Detail("name", Words("tools.adapters.item.name"), row.name),
           Detail("description", Words("tools.adapters.item.description"), row.description),
           Detail("status", Words("tools.adapters.item.status"), status_words(row.status)),
           Detail("kind", Words("tools.adapters.item.kind"), kind_words(row.kind)),
           Detail("internet", Words("tools.adapters.item.internet"), _internet_value(adapter))]
    for n, address in enumerate(row.addresses):
        item = "tools.adapters.item.ipv4" if address.version == 4 else "tools.adapters.item.ipv6"
        out.append(Detail(f"address|{n}", Words(item), address_text(address),
                          _address_note(address),
                          tag="duplicate" if address.dad == DUPLICATE else ""))
    if not row.addresses:
        out.append(Detail("address", Words("tools.adapters.item.addresses"),
                          Words("tools.adapters.value.none")))
    for n, gateway in enumerate(row.gateways):
        out.append(Detail(f"gateway|{n}", Words("tools.adapters.item.gateway"), gateway,
                          address=_bare(gateway)))
    for n, server in enumerate(row.dns_servers):
        if _bare(server) in PLACEHOLDER_DNS:
            out.append(Detail(f"dns|{n}", Words("tools.adapters.item.dns"), server,
                              (Words("tools.adapters.dns_placeholder"),)))
        elif server in row.stub_dns:
            # Not offered to the Control page either: impairing it would slow only
            # the step to this computer's own resolver, not its questions out.
            out.append(Detail(f"dns|{n}", Words("tools.adapters.item.dns"), server,
                              (Words("tools.adapters.dns_stub"),)))
        else:
            out.append(Detail(f"dns|{n}", Words("tools.adapters.item.dns"), server,
                              address=_bare(server)))
    out.append(Detail("dhcp", Words("tools.adapters.item.dhcp"),
                      Words("tools.adapters.value.yes" if row.dhcp else "tools.adapters.value.no")))
    optional = (("dhcp_server", row.dhcp_server), ("dns_suffix", row.dns_suffix),
                ("mac", row.mac), ("mtu", str(row.mtu)), ("speed", _speed(row)),
                ("metric_v4", "" if row.ipv4_metric is None else str(row.ipv4_metric)),
                ("metric_v6", "" if row.ipv6_metric is None else str(row.ipv6_metric)))
    out += [Detail(name, Words(f"tools.adapters.item.{name}"), value)
            for name, value in optional if value]
    out.append(Detail("index", Words("tools.adapters.item.index"),
                      f"{row.if_index} / {row.ipv6_index or '-'}"))
    return out


# -- the report ---------------------------------------------------------------------- #
def _slug(table, number):
    return table.get(number, str(number)).replace("_", " ")


def adapter_lines(adapter):
    """One adapter as the report writes it - program text, English."""
    row = adapter.row
    lines = [f"{row.name} ({row.description})" if row.description else row.name,
             f"  status: {_slug(STATUS, row.status)}, type: {_slug(KINDS, row.kind)} "
             f"({row.kind}), internet: "
             + (", ".join(f"IPv{v}" for v in adapter.internet) or "no")]
    for address in row.addresses:
        note = _slug(ORIGINS, address.origin)
        if address.dad != PREFERRED:
            note += ", " + _slug(DAD, address.dad)
        lines.append(f"  IPv{address.version}: {address_text(address)} ({note})")
    lines += [f"  gateway: {gateway}" for gateway in row.gateways]
    lines += [f"  DNS: {server}" + _dns_note(row, server) for server in row.dns_servers]
    dhcp = "on" + (f", server {row.dhcp_server}" if row.dhcp_server else "") if row.dhcp else "off"
    lines.append(f"  DHCP: {dhcp}")
    if row.dns_suffix:
        lines.append(f"  DNS suffix: {row.dns_suffix}")
    if row.mac:
        lines.append(f"  MAC: {row.mac}")
    lines.append(f"  MTU: {row.mtu}" + (f", speed: {_speed(row)}" if _speed(row) else ""))
    metric = " / ".join("-" if m is None else str(m) for m in (row.ipv4_metric, row.ipv6_metric))
    lines.append(f"  metric: {metric}, index: {row.if_index} / {row.ipv6_index or '-'}")
    return lines


def _dns_note(row, server):
    if _bare(server) in PLACEHOLDER_DNS:
        return " (Windows placeholder)"
    if server in row.stub_dns:
        return " (systemd-resolved, on this computer)"
    return ""


def _read_at(read_at):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(read_at))


def report_lines(snapshot):
    """Every adapter, as the Copy button and the optional diagnostics section write it."""
    lines = [f"network adapters: {len(snapshot.adapters)}, read {_read_at(snapshot.read_at)}"]
    for adapter in snapshot.adapters:
        lines += adapter_lines(adapter)
    return lines


def report(snapshot):
    return "\n".join(report_lines(snapshot))


def adapter_report(adapter, read_at):
    """ONE adapter, as its row menu copies it: the report's own lines for it, under
    the time they were read - the same words as the whole report, so a pasted part
    reads like the whole."""
    return "\n".join([f"network adapter, read {_read_at(read_at)}", *adapter_lines(adapter)])
