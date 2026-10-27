"""What the system's TCP stack measures for one connection - the Tools tab's TCP health.
Windows first; Linux at the end of this text.

"Does the stack see my 200 ms latency as 200 ms of round trip, and my 5% loss as
data sent again?" A second opinion on the impairments, from the side of the program
under test, and without sending anything: Windows keeps these numbers for its own
TCP (RFC 4898, "TCP Extended Statistics MIB").

How, Microsoft Learn: ``SetPerTcpConnectionEStats`` turns counting on for one
connection (``EnableCollection`` TRUE), ``GetPerTcpConnectionEStats`` reads it - the
``Tcp6`` pair for IPv6, which "Reset this connection" does not have. Two kinds are
read: ``TcpConnectionEstatsPath`` (round-trip times, resends, timeouts, segment
size) and ``TcpConnectionEstatsData`` (bytes and segments).

MEASURED 2026-10-19 on this project's machine (loopback, own processes; a control
that could fail: the bytes counted equal the bytes sent, exactly), and the reason for
each rule below:

* Counting is off by default, and a read of a connection nobody turned it on for
  answers 0 - with ``EnableCollection`` FALSE and RANDOM numbers in the statistics
  (2.6e16 bytes sent, after 12 345). Learn says to ignore them then; so a reading is
  believed only when the flag of BOTH kinds is TRUE.
* Turning counting on needs administrator rights: 5 (ACCESS_DENIED) without them.
  A connection that does not exist answers 5 too in that case, and 1168 with them -
  so the reason is taken from the process's token (``winenv.is_admin``), never from
  the number. Reading needs no rights, also for another process's connection.
* The state is kernel state shared by every program: another process sees counting
  turned on by this one. Learn: never turn it OFF - since Windows 10 1709 some
  counters do not reset, and a second program watching the same connection would
  be confused. Nothing here turns it off; a change is a difference of two readings.
* A connection that ended answers 1168 (gone, or never there) or 50 (TIME_WAIT:
  "not supported"); both are "ended".
* Right after counting is turned on, before any data, ``CountRtt`` is 0 and the
  round-trip fields read 0 (``SampleRtt`` 0xFFFFFFFF): no measurement yet, not 0 ms.
* The calls take ~10-25 us each (1000 connections); turning counting on for 1000
  left nothing measurable behind once they closed.

Windows measures a round trip when THIS computer's data is acknowledged, in whole
milliseconds: a connection that only receives has none (0 in 22 s of 28 MB received),
and loopback reads 0 ms.

🔴 MEASURED 2026-10-19 against a Linux peer (WSL) and a Windows Server 2025 peer over the
LAN, through this program's own narrow sessions, the application timing its own echo
and a packet capture on the peer as the controls:

* It does not measure every round trip. A connection that is OPEN when its round trip
  jumps past about 200 ms (plus twice what Windows measured before) is measured no
  more: with one segment in flight Windows sends it again after 200 ms (the tail loss
  probe - the peer saw every segment twice, 0.200 s apart), and the acknowledgement of
  a segment sent twice is not measured (Karn). So ``CountRtt`` stands still and the
  smoothed value keeps the old number. 90 ms each way (182 ms) was followed to the
  millisecond; a connection OPENED under 150 ms each way was measured exactly (302 ms,
  the application's own 302 ms). Hence ``rtt_samples``: the tool says when the round
  trip has not been measured for a while although data went out.
* ``PktsRetrans`` is never filled: 0 on Windows 11 and on Windows Server 2025 while 24
  to 289 segments were sent again (on the wire, and the engine's drop count).
  ``BytesRetrans`` is exact (24 x 200 B; 289 x MSS = 282 drops + 5 probes + 2 at the
  session's end), so resends are said in bytes and the segment count is not read.
* ``DataBytesOut`` / ``DataBytesIn`` count data sent again and received twice too
  (19 800 B for 15 000 B the application sent).

On Linux the kernel keeps ``struct tcp_info`` for every TCP socket, from the moment it
opened, and gives it through sock_diag (``sockdiag.lookup``) - nothing is turned on, and
no rights are needed, also for another user's connection. MEASURED 2026-10-27
(``internal_tools`` probes ``2026-10-27-linux-tcphealth``: Ubuntu 26.04.1 with kernel 7.0,
WSL with 6.18), and the reason for each rule:

* A connection is found once in the kernel's list (``sockdiag.tcp_sockets``) and read
  after that by the id the list gave, its cookie in it (``Handle``): asked by its numbers
  alone, a connection that has gone is answered by the listener on its port. No such
  socket (ENOENT), TIME_WAIT, and a socket its program has closed (answered without
  ``tcp_info``) are all "ended".
* Round trips are kept in microseconds; they are said in whole milliseconds here, as
  Windows and Ping say them. A round trip of 0 is none measured yet.
* It measured on through a round trip that jumped from 0.4 to 200 ms on an open
  connection (an echo every 100 ms, ``netem`` on a veth of a namespace of the probe's
  own), with TCP timestamps on and off: the smoothed value was at 198 ms after 6 s - no
  stall like Windows' above. It keeps no count of its measurements, so "not measured
  for N s" is never said for it.
* It keeps no newest single measurement, no highest round trip, no count of fast resends
  or duplicate ACKs (``LINUX_ABSENT``); its lowest round trip is the lowest of a window
  (``net.ipv4.tcp_min_rtt_wlen``, 300 s by default). Timeouts are counted from kernel 6.7
  on and count every expiry of the resend timer, the first one or not.
* It counts the segments sent again (``total_retrans``), which Windows never fills: 120
  segments of 1448 B for 173 760 resent bytes through 5% loss, and the resent bytes
  equal the bytes sent minus the bytes acknowledged to the byte. The bytes received do
  not count data received twice.
"""
import ctypes
import ipaddress
import sys
import types
from typing import Mapping, NamedTuple

from . import crashlog, portmap, sockdiag, tcprow, winenv

# TCP_ESTATS_TYPE (Learn, tcpestats.h).
DATA, PATH = 1, 3
ERROR_NOT_FOUND, ERROR_NOT_SUPPORTED = 1168, 50
# A 32-bit counter's field that holds no measurement yet.
UNSET = 0xFFFFFFFF

# How a reading ended. OK is the one that holds numbers.
OK = "ok"
ENDED = "ended"                 # the connection is gone or closing (1168, 50)
NOT_COUNTING = "not_counting"   # read, but counting is off: the numbers mean nothing
NEEDS_ADMIN = "needs_admin"     # counting could not be turned on: no administrator rights
REFUSED = "refused"             # Windows said no although the process is elevated
FAILED = "failed"               # anything else; ``detail`` is the program's own words


class _Rw(ctypes.Structure):
    """``TCP_ESTATS_PATH_RW_v0`` and ``TCP_ESTATS_DATA_RW_v0``: one BOOLEAN."""
    _fields_ = [("EnableCollection", ctypes.c_ubyte)]


_PATH_FIELDS = (
    "FastRetran Timeouts SubsequentTimeouts CurTimeoutCount AbruptTimeouts PktsRetrans "
    "BytesRetrans DupAcksIn SacksRcvd SackBlocksRcvd CongSignals PreCongSumCwnd "
    "PreCongSumRtt PostCongSumRtt PostCongCountRtt EcnSignals EceRcvd SendStall QuenchRcvd "
    "RetranThresh SndDupAckEpisodes SumBytesReordered NonRecovDa NonRecovDaEpisodes "
    "AckAfterFr DsackDups SampleRtt SmoothedRtt RttVar MaxRtt MinRtt SumRtt CountRtt CurRto "
    "MaxRto MinRto CurMss MaxMss MinMss SpuriousRtoDetections").split()


class _PathRod(ctypes.Structure):
    """``TCP_ESTATS_PATH_ROD_v0`` (Learn): forty ULONGs, in this order."""
    _fields_ = [(name, ctypes.c_uint32) for name in _PATH_FIELDS]


class _DataRod(ctypes.Structure):
    """``TCP_ESTATS_DATA_ROD_v0`` (Learn). ctypes aligns the ULONG64s as the C
    compiler does, on Windows and on the Linux runner alike."""
    _fields_ = [("DataBytesOut", ctypes.c_uint64), ("DataSegsOut", ctypes.c_uint64),
                ("DataBytesIn", ctypes.c_uint64), ("DataSegsIn", ctypes.c_uint64),
                ("SegsOut", ctypes.c_uint64), ("SegsIn", ctypes.c_uint64),
                ("SoftErrors", ctypes.c_uint32), ("SoftErrorReason", ctypes.c_uint32),
                ("SndUna", ctypes.c_uint32), ("SndNxt", ctypes.c_uint32),
                ("SndMax", ctypes.c_uint32), ("ThruBytesAcked", ctypes.c_uint64),
                ("RcvNxt", ctypes.c_uint32), ("ThruBytesReceived", ctypes.c_uint64)]


# What a system's stack does not keep, by ``Sample`` field. Such a field is never shown:
# a round trip of None is otherwise "not measured yet", a counter of 0 "nothing happened".
WINDOWS_ABSENT = frozenset({"resent_segments"})          # PktsRetrans: never filled (above)
LINUX_ABSENT = frozenset({"sample_rtt", "max_rtt", "fast_resends", "duplicate_acks",
                          "rtt_samples"})
# Each counter's width in bits: a difference of two readings is taken modulo it.
WINDOWS_WIDTHS = types.MappingProxyType({
    "resent_bytes": 32, "timeouts": 32, "fast_resends": 32, "duplicate_acks": 32,
    "resent_segments": 32, "bytes_out": 64, "bytes_in": 64})
LINUX_WIDTHS = types.MappingProxyType({
    "resent_bytes": 64, "timeouts": 16, "fast_resends": 32, "duplicate_acks": 32,
    "resent_segments": 32, "bytes_out": 64, "bytes_in": 64})


class Sample(NamedTuple):
    """One reading's numbers. Round trips in ms, None while the system has none."""
    smoothed_rtt: int | None
    sample_rtt: int | None
    min_rtt: int | None
    max_rtt: int | None
    rtt_var: int | None
    rto: int                    # the resend timer, ms
    resent_bytes: int           # counters: since counting was turned on (``widths``)
    timeouts: int
    fast_resends: int
    duplicate_acks: int
    mss: int
    bytes_out: int
    bytes_in: int
    rtt_samples: int = 0        # CountRtt: how many round trips Windows has measured
    resent_segments: int = 0    # Linux's total_retrans
    absent: frozenset = WINDOWS_ABSENT
    widths: Mapping = WINDOWS_WIDTHS


class Reading(NamedTuple):
    state: str
    sample: Sample | None = None
    code: int = 0               # what the system answered, when it said no
    detail: str = ""            # FAILED: the exception, program text
    handle: object = None       # how the system finds this connection again (Linux)


def _sample(path, data):
    measured = path.CountRtt > 0

    def rtt(value):
        return value if measured and value != UNSET else None

    return Sample(rtt(path.SmoothedRtt), rtt(path.SampleRtt), rtt(path.MinRtt),
                  rtt(path.MaxRtt), rtt(path.RttVar), path.CurRto,
                  path.BytesRetrans, path.Timeouts, path.FastRetran, path.DupAcksIn,
                  path.CurMss, data.DataBytesOut, data.DataBytesIn, path.CountRtt)


# -- the binding --------------------------------------------------------------------- #
def _iphlpapi():
    """iphlpapi with the four prototypes; None off Windows."""
    if not sys.platform.startswith("win"):
        return None
    return _declared(ctypes.WinDLL("iphlpapi.dll"))  # pragma: no cover - Windows only (the DLL)


def _declared(lib):
    """``lib`` with the prototypes of the calls made here (Microsoft Learn)."""
    for name, row in (("GetPerTcpConnectionEStats", tcprow.TcpRow),
                      ("GetPerTcp6ConnectionEStats", tcprow.Tcp6Row)):
        call = getattr(lib, name)
        call.argtypes = [ctypes.POINTER(row), ctypes.c_int,
                         ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                         ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                         ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        call.restype = ctypes.c_uint32
    for name, row in (("SetPerTcpConnectionEStats", tcprow.TcpRow),
                      ("SetPerTcp6ConnectionEStats", tcprow.Tcp6Row)):
        call = getattr(lib, name)
        call.argtypes = [ctypes.POINTER(row), ctypes.c_int, ctypes.c_void_p,
                         ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
        call.restype = ctypes.c_uint32
    return lib


def supported():
    """Windows has the EStats calls; Linux has ``tcp_info`` when its kernel lists TCP
    sockets through sock_diag (``_Linux.can_list``). Asked through ``capabilities``."""
    if sys.platform.startswith("win"):
        return True
    return sys.platform.startswith("linux") and _Linux().can_list()


NOT_HERE_LINUX = "tools.tcphealth.not_here_linux"


def why_not():
    """What a system without TCP health says instead (``capabilities.why_not``): on
    Linux, that its kernel lists no TCP sockets - the shared words name Linux as a
    system the tool works on. Elsewhere nothing of its own."""
    return NOT_HERE_LINUX if sys.platform.startswith("linux") else None


def needs_rights():
    """Whether watching needs administrator rights here: on Windows turning counting on
    does (above); Linux counts for every socket and lets any user read it."""
    return sys.platform.startswith("win")


def socket_rows():
    """The socket table a Connections row is looked up in, as ``portmap.socket_rows``
    answers. On Linux the kernel's own list: it writes a socket opened as IPv6 for an
    IPv4 address with the IPv4 one, as the row does, where psutil writes ``::ffff:``."""
    if sys.platform.startswith("linux"):
        return _Linux().rows()
    return portmap.socket_rows()


class _System:
    """What a reading asks of Windows. Injectable, so it all runs in tests anywhere."""

    def __init__(self, iphlpapi=None, is_admin=None):
        self.iphlpapi = iphlpapi if iphlpapi is not None else _iphlpapi()
        self.is_admin = is_admin or winenv.is_admin

    def watch(self, connection):
        return _watch(tcprow.row_for(connection), self)

    def read(self, connection, _handle=None):
        return _read(tcprow.row_for(connection), self)

    def enable(self, row, kind):
        """Turn counting ON (never off - Learn). Version 0 and offset 0, as Learn says."""
        call = (self.iphlpapi.SetPerTcpConnectionEStats if isinstance(row, tcprow.TcpRow)
                else self.iphlpapi.SetPerTcp6ConnectionEStats)
        rw = _Rw(1)
        return int(call(ctypes.byref(row), kind, ctypes.byref(rw), 0, ctypes.sizeof(rw), 0))

    def read_stats(self, row, kind, rod):
        """Read one kind into ``rod``: (answer, EnableCollection)."""
        call = (self.iphlpapi.GetPerTcpConnectionEStats if isinstance(row, tcprow.TcpRow)
                else self.iphlpapi.GetPerTcp6ConnectionEStats)
        rw = _Rw(0)
        code = call(ctypes.byref(row), kind, ctypes.byref(rw), 0, ctypes.sizeof(rw),
                    None, 0, 0, ctypes.byref(rod), 0, ctypes.sizeof(rod))
        return int(code), int(rw.EnableCollection)


def _ended(code):
    return code in (ERROR_NOT_FOUND, ERROR_NOT_SUPPORTED)


def _read(row, system):
    path, data = _PathRod(), _DataRod()
    for kind, rod in ((PATH, path), (DATA, data)):
        code, counting = system.read_stats(row, kind, rod)
        if _ended(code):
            return Reading(ENDED, code=code)
        if code:
            return Reading(FAILED, code=code, detail=f"answered {code}")
        if counting != 1:
            return Reading(NOT_COUNTING)
    return Reading(OK, _sample(path, data))


def _watch(row, system):
    for kind in (PATH, DATA):
        code = system.enable(row, kind)
        if _ended(code):
            return Reading(ENDED, code=code)
        if code:
            return Reading(REFUSED if system.is_admin() else NEEDS_ADMIN, code=code)
    return _read(row, system)


# -- Linux --------------------------------------------------------------------------- #
US_PER_MS = 1000
ENOENT = 2
# Answers that hold no connection to read: TIME_WAIT and CLOSED keep no tcp_info, and a
# LISTEN answer is the listener on the port, never the connection (the cookie prevents
# it; this is the second lock).
_NOT_OPEN = frozenset({"TIME_WAIT", "CLOSED", "LISTEN"})
# Sample field -> the tcp_info field it is read from: one an older kernel's shorter struct
# lacks goes to ``absent`` for that reading.
_FROM_KERNEL = {"smoothed_rtt": "rtt", "min_rtt": "min_rtt", "rtt_var": "rttvar", "rto": "rto",
                "resent_bytes": "bytes_retrans", "timeouts": "total_rto", "mss": "snd_mss",
                "bytes_out": "bytes_sent", "bytes_in": "bytes_received",
                "resent_segments": "total_retrans"}


class Handle(NamedTuple):
    """A socket's id in the kernel's words: the list it is in and ``inet_diag_sockid``
    with the cookie."""
    kernel_family: int
    sockid: bytes


def _bare(ip):
    """An address as one value: without its zone, an IPv4 address mapped into IPv6 as
    the IPv4 one (psutil writes a dual-stack socket that way, the kernel's list not)."""
    address = ipaddress.ip_address(str(ip).split("%")[0])
    return getattr(address, "ipv4_mapped", None) or address


def _same(socket, connection):
    try:
        return (socket.local_port == connection.local_port
                and socket.remote_port == connection.remote_port
                and _bare(socket.local_ip) == _bare(connection.local_ip)
                and _bare(socket.remote_ip) == _bare(connection.remote_ip))
    except ValueError:
        return False


def _ms(value):
    return value // US_PER_MS


def _linux_sample(info):
    """A ``Sample`` from ``sockdiag.tcp_info``'s fields. Whole milliseconds, rounded down,
    so "< 1" means under one; a round trip of 0 is none measured yet, and then neither
    is its variation (the kernel starts it at 250 ms before any measurement)."""
    measured = bool(info.get("rtt"))

    def rtt(name):
        value = info.get(name)
        return _ms(value) if measured and value is not None and value != UNSET else None
    absent = LINUX_ABSENT | {field for field, name in _FROM_KERNEL.items() if name not in info}
    return Sample(rtt("rtt"), None, rtt("min_rtt"), None, rtt("rttvar"),
                  _ms(info.get("rto", 0)), info.get("bytes_retrans", 0),
                  info.get("total_rto", 0), 0, 0, info.get("snd_mss", 0),
                  info.get("bytes_sent", 0), info.get("bytes_received", 0),
                  resent_segments=info.get("total_retrans", 0), absent=frozenset(absent),
                  widths=LINUX_WIDTHS)


class _Linux:
    """What a reading asks of Linux: the kernel's list (``sockdiag``) to find a
    connection once, then that one socket's ``tcp_info`` by its id. ``talk`` sends one
    request as ``sockdiag.exchange`` does - a test brings its own."""

    def __init__(self, talk=None):
        self.talk = talk or sockdiag.exchange

    def rows(self):
        try:
            return sockdiag.tcp_sockets(self.talk), []
        except OSError as exc:
            raise portmap.SocketTableUnavailable("missing", str(exc)) from exc

    def lookup(self, handle):
        return sockdiag.lookup(handle.kernel_family, handle.sockid, self.talk)

    def can_list(self):
        try:
            return sockdiag.lists(self.talk)
        except OSError:
            return False        # no sock_diag at all, or netlink refused to this process

    def watch(self, connection):
        """Find ``connection`` in the kernel's list by its four numbers, then read it.
        Two sockets with them (a link-local address on two links) are not guessed at. A
        list the kernel would not give is said in its words - not a fault of the program."""
        try:
            rows, _failed = self.rows()
        except portmap.SocketTableUnavailable as exc:
            return Reading(FAILED, detail=str(exc))
        found = [s for s in rows if _same(s, connection)]
        if not found:
            return Reading(ENDED, code=ENOENT)
        if len(found) > 1:
            return Reading(FAILED, detail=f"{len(found)} sockets have these addresses and ports")
        return self.read(connection, Handle(found[0].kernel_family, found[0].sockid))

    def read(self, connection, handle):
        """Read the socket ``handle`` names. A watch that found none to read (a list the
        kernel would not give, two sockets with its numbers) carried no handle: it is
        looked for again, as Windows asks again after a failure."""
        if handle is None:
            return self.watch(connection)
        code, found = self.lookup(handle)
        if code == ENOENT or (code == 0 and (found.info is None or found.state in _NOT_OPEN)):
            return Reading(ENDED, code=code, handle=handle)
        if code:
            return Reading(FAILED, code=code, detail=f"sock_diag answered errno {code}",
                           handle=handle)
        return Reading(OK, _linux_sample(sockdiag.tcp_info(found.info)), handle=handle)


def _system_class():
    """The system a reading asks here. Off Windows and Linux it is never reached:
    ``supported`` says no first."""
    return _Linux if sys.platform.startswith("linux") else _System


def _guard(work):
    try:
        return work()
    except Exception as exc:
        crashlog.note(exc, "tcpestats")
        return Reading(FAILED, detail=f"{type(exc).__name__}: {exc}")


def watch(connection, system=None):
    """Turn counting on for ``connection`` (Windows; Linux always counts) and read it.
    On a worker; never raises."""
    return _guard(lambda: (system or _system_class()()).watch(connection))


def read(connection, system=None, handle=None):
    """Read ``connection``: counting turned on (Windows), or the socket ``handle`` names -
    the one its watch reading carried (Linux). Never raises."""
    return _guard(lambda: (system or _system_class()()).read(connection, handle))
