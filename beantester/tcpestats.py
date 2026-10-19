"""What Windows' TCP stack measures for one connection - the Tools tab's TCP health.

"Does the stack see my 200 ms latency as 200 ms of round trip, and my 5% loss as
resent segments?" A second opinion on the impairments, from the side of the program
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
milliseconds: a connection that only receives has few measurements, and loopback
reads 0 ms.

🔴 And it does not measure every round trip - MEASURED 2026-10-19 against a WSL peer
through this program's own sessions (`sondy/2026-10-19-t5-estats/probe_t5_m5b.py`, the
application timing its own echo as the control): latency of 50 and 60 ms each way
(round trips of 102 and 122 ms) was followed to the millisecond; at 100, 120, 160 and
200 ms each way (202 to 402 ms) ``CountRtt`` STOOD STILL for the whole session, so the
smoothed value stayed where it was. A session that impairs nothing changes nothing,
and the engine delays every packet the same way - this is Windows, the reason unknown
(it is not the resend timer: 242 ms < 300 stood still too). With 20% loss the
timeouts were counted and ``PktsRetrans`` stayed 0. Hence ``rtt_samples``: the tool
says when the round trip has not been measured for a while although data went out.
"""
import ctypes
import sys
from typing import NamedTuple

from . import crashlog, tcprow, winenv

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


class Sample(NamedTuple):
    """One reading's numbers. Round trips in ms, None while Windows has none."""
    smoothed_rtt: int | None
    sample_rtt: int | None
    min_rtt: int | None
    max_rtt: int | None
    rtt_var: int | None
    rto: int                    # the resend timer, ms
    resent_segments: int        # counters: since counting was turned on, 32-bit
    resent_bytes: int
    timeouts: int
    fast_resends: int
    duplicate_acks: int
    mss: int
    bytes_out: int              # 64-bit counters
    bytes_in: int
    rtt_samples: int = 0        # CountRtt: how many round trips Windows has measured


class Reading(NamedTuple):
    state: str
    sample: Sample | None = None
    code: int = 0               # what Windows answered, when it said no
    detail: str = ""            # FAILED: the exception, program text


def _sample(path, data):
    measured = path.CountRtt > 0

    def rtt(value):
        return value if measured and value != UNSET else None

    return Sample(rtt(path.SmoothedRtt), rtt(path.SampleRtt), rtt(path.MinRtt),
                  rtt(path.MaxRtt), rtt(path.RttVar), path.CurRto, path.PktsRetrans,
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
    return sys.platform.startswith("win")


class _System:
    """What a reading asks of Windows. Injectable, so it all runs in tests anywhere."""

    def __init__(self, iphlpapi=None, is_admin=None):
        self.iphlpapi = iphlpapi if iphlpapi is not None else _iphlpapi()
        self.is_admin = is_admin or winenv.is_admin

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


def _guard(work, connection, system):
    try:
        return work(tcprow.row_for(connection), system or _System())
    except Exception as exc:
        crashlog.note(exc, "tcpestats")
        return Reading(FAILED, detail=f"{type(exc).__name__}: {exc}")


def watch(connection, system=None):
    """Turn counting on for ``connection`` and read it. On a worker; never raises."""
    return _guard(_watch, connection, system)


def read(connection, system=None):
    """Read ``connection``; counting must have been turned on. Never raises."""
    return _guard(_read, connection, system)
