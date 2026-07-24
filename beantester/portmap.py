"""Local port -> owning process, fast enough for the packet hot path.

WinDivert gives us a packet, never a PID: everything the tool knows about
"which process does this packet belong to" comes from mapping the packet's
LOCAL port onto the socket table. That mapping is a moving target - a browser
opens and closes sockets continuously - so it has to be rebuilt often, which
means it has to be *cheap*.

Two implementations, picked at runtime:

* **Windows (default)** - ``iphlpapi.GetExtendedTcpTable`` /
  ``GetExtendedUdpTable`` through ctypes, for IPv4 **and** IPv6. One syscall per
  table, a few hundred microseconds, no per-process work at all.
* **fallback** - ``psutil.net_connections()``; correct everywhere, but it
  enumerates every socket in the system and is an order of magnitude slower.
  Used off Windows, in the tests, and whenever the native call fails.

Process names (and parent PIDs, needed to follow a process TREE - see
``targeting.py``) are resolved lazily and only for the PIDs that actually own a
socket, then cached: that is a few dozen processes instead of the several
hundred ``psutil.process_iter()`` would walk on every refresh.

Nothing here raises: a lookup that cannot be answered returns ``None`` /
``""``, because the callers sit in the capture loop.
"""
import sys
import threading
import time

from . import crashlog

REFRESH_S = 0.30          # a routine rebuild of the port table
MISS_REFRESH_S = 0.05     # a rebuild forced by an unknown port (rate limited)
INFO_TTL_S = 30.0         # how long a pid -> (name, ppid) entry survives unused

_AF_INET = 2
_AF_INET6 = 23            # AF_INET6 on Windows (NOT the POSIX 10)
_TCP_TABLE_OWNER_PID_ALL = 5
_UDP_TABLE_OWNER_PID = 1
_ERROR_INSUFFICIENT_BUFFER = 122


def _swap16(value):
    """The socket tables store ports in network byte order inside a DWORD."""
    return ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)


# -- native (Windows) --------------------------------------------------------- #
class _Native:
    """ctypes bindings for the two extended socket tables. Windows only."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.iphlpapi = ctypes.WinDLL("iphlpapi.dll")

        class MIB_TCPROW_OWNER_PID(ctypes.Structure):
            _fields_ = [("dwState", wintypes.DWORD),
                        ("dwLocalAddr", wintypes.DWORD),
                        ("dwLocalPort", wintypes.DWORD),
                        ("dwRemoteAddr", wintypes.DWORD),
                        ("dwRemotePort", wintypes.DWORD),
                        ("dwOwningPid", wintypes.DWORD)]

        class MIB_TCP6ROW_OWNER_PID(ctypes.Structure):
            _fields_ = [("ucLocalAddr", ctypes.c_ubyte * 16),
                        ("dwLocalScopeId", wintypes.DWORD),
                        ("dwLocalPort", wintypes.DWORD),
                        ("ucRemoteAddr", ctypes.c_ubyte * 16),
                        ("dwRemoteScopeId", wintypes.DWORD),
                        ("dwRemotePort", wintypes.DWORD),
                        ("dwState", wintypes.DWORD),
                        ("dwOwningPid", wintypes.DWORD)]

        class MIB_UDPROW_OWNER_PID(ctypes.Structure):
            _fields_ = [("dwLocalAddr", wintypes.DWORD),
                        ("dwLocalPort", wintypes.DWORD),
                        ("dwOwningPid", wintypes.DWORD)]

        class MIB_UDP6ROW_OWNER_PID(ctypes.Structure):
            _fields_ = [("ucLocalAddr", ctypes.c_ubyte * 16),
                        ("dwLocalScopeId", wintypes.DWORD),
                        ("dwLocalPort", wintypes.DWORD),
                        ("dwOwningPid", wintypes.DWORD)]

        self.rows = {
            ("tcp", _AF_INET): MIB_TCPROW_OWNER_PID,
            ("tcp", _AF_INET6): MIB_TCP6ROW_OWNER_PID,
            ("udp", _AF_INET): MIB_UDPROW_OWNER_PID,
            ("udp", _AF_INET6): MIB_UDP6ROW_OWNER_PID,
        }
        self._sizes = {}            # (proto, family) -> bytes the table needed last time

    def _table(self, proto, family, out):
        """Append ``(port, pid)`` pairs of one table to ``out``."""
        import ctypes
        from ctypes import wintypes

        row_type = self.rows[(proto, family)]
        call = (self.iphlpapi.GetExtendedTcpTable if proto == "tcp"
                else self.iphlpapi.GetExtendedUdpTable)
        table_class = (_TCP_TABLE_OWNER_PID_ALL if proto == "tcp"
                       else _UDP_TABLE_OWNER_PID)

        # Start from the size this table needed last time. The socket table is
        # queried several times per second and its size barely moves, so the first
        # attempt normally fits and we skip the grow-and-retry round trip.
        #
        # The BUFFER is deliberately not reused. A previous version stored it and
        # claimed to reuse it, but allocated a fresh one on every call anyway and
        # never read the stored one back - so the cache only pinned memory. Real
        # reuse was considered and rejected: it saves four allocations a few times
        # a second and buys aliasing between calls in ctypes code, which is a poor
        # trade in the module the packet path leans on.
        size = wintypes.DWORD(self._sizes.get((proto, family)) or 8192)
        for _ in range(6):                       # the table can grow between calls
            buffer = ctypes.create_string_buffer(size.value)
            rc = call(buffer, ctypes.byref(size), False, family, table_class, 0)
            if rc == 0:
                self._sizes[(proto, family)] = size.value
                break
            if rc != _ERROR_INSUFFICIENT_BUFFER:
                return False
        else:
            return False

        count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD))[0]
        if not count:
            return True
        rows = ctypes.cast(
            ctypes.byref(buffer, ctypes.sizeof(wintypes.DWORD)),
            ctypes.POINTER(row_type * count)).contents
        for row in rows:
            port = _swap16(row.dwLocalPort & 0xFFFF)
            pid = int(row.dwOwningPid)
            if port and pid:
                out[port] = pid
        return True

    FAMILY_NAMES = {_AF_INET: "v4", _AF_INET6: "v6"}

    def port_pid_map(self):
        """``{local port: pid}`` from all four socket tables, or ``None``.

        A PARTIAL result is still returned. Dropping to psutil because one table
        of four stopped answering would trade a possible gap for a certain
        slowdown, and the native path is what makes live targeting affordable at
        all - so the gap is the better risk.

        What it must not be is SILENT. A table that stops answering means sockets
        this tool can no longer see, and a socket it cannot see is traffic the user
        asked to impair sailing through untouched - which looks exactly like "the
        application coped". ``once()`` keeps that free in the hot path, and the key
        carries WHICH tables failed, so a different failure still gets recorded.
        """
        out = {}
        failed = []
        for proto in ("tcp", "udp"):
            for family in (_AF_INET, _AF_INET6):
                if not self._table(proto, family, out):
                    failed.append(f"{proto}/{self.FAMILY_NAMES[family]}")
        if len(failed) == 4:
            return None                  # nothing answered at all: let psutil try
        if failed:
            crashlog.once("portmap.native." + ".".join(failed), RuntimeError(
                "socket table(s) unavailable, the port map may be incomplete: "
                + ", ".join(failed)))
        return out


def _make_native():
    if not sys.platform.startswith("win"):
        return None
    try:
        return _Native()
    except Exception:                                    # pragma: no cover
        return None


# -- fallback (psutil) --------------------------------------------------------- #
def _psutil_port_pid_map():
    try:
        import psutil
    except Exception:
        return None
    try:
        out = {}
        for conn in psutil.net_connections(kind="inet"):
            laddr, pid = conn.laddr, conn.pid
            if not laddr or not pid:
                continue
            port = laddr.port if hasattr(laddr, "port") else laddr[1]
            if port:
                out[int(port)] = int(pid)
        return out
    except Exception:
        return None


def _psutil_process_table():
    """``{pid: (name, ppid, created)}`` for every process (the slow, portable path)."""
    try:
        import psutil
    except Exception:
        return {}
    try:
        table = {}
        for proc in psutil.process_iter(["pid", "name", "ppid", "create_time"]):
            info = getattr(proc, "info", None) or {}
            pid = info.get("pid")
            if pid is None:
                continue
            table[int(pid)] = (str(info.get("name") or ""), info.get("ppid"),
                               info.get("create_time"))
        return table
    except Exception:
        return {}


# Off on non-Windows and in tests (which fake psutil); the fixtures flip it.
_ALLOW_NATIVE_PROCESSES = sys.platform.startswith("win")


def _toolhelp_process_table():
    """``{pid: (name, ppid, None)}`` from a CreateToolhelp32Snapshot, or ``None``.

    This reads the name and parent PID of EVERY process in one call WITHOUT opening
    any of them. That is the whole point: it is fast (~6 ms for 350 processes,
    measured, against ~2.6 s for ``psutil.process_iter``) AND it names HARDENED
    processes - Chrome's network service, some services - that refuse the OpenProcess
    a per-PID ``psutil.Process(pid)`` needs, and so had NO name at all before. That
    gap is why targeting ``chrome`` by NAME resolved to nothing while targeting its
    PID worked: PID matching needs no name, name matching does. It gives no start
    time (the recycle check then falls back to the TTL, the unverifiable-env path).
    """
    if not _ALLOW_NATIVE_PROCESSES:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_char * 260)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # restype/argtypes MATTER: the snapshot is a HANDLE (pointer-sized), and the
        # default c_int return truncates it on 64-bit.
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
        k32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        snap = k32.CreateToolhelp32Snapshot(0x2, 0)            # TH32CS_SNAPPROCESS
        if not snap or snap == wintypes.HANDLE(-1).value:
            return None
        try:
            out = {}
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            ok = k32.Process32First(snap, ctypes.byref(entry))
            while ok:
                out[int(entry.th32ProcessID)] = (
                    entry.szExeFile.decode("mbcs", "replace"),
                    int(entry.th32ParentProcessID), None)
                ok = k32.Process32Next(snap, ctypes.byref(entry))
            return out or None
        finally:
            k32.CloseHandle(snap)
    except Exception:
        return None


def _process_table():
    """Every process as ``{pid: (name, ppid, created)}``: the fast native snapshot
    when available, the psutil scan otherwise (and in tests, which disable native)."""
    native = _toolhelp_process_table()
    return native if native is not None else _psutil_process_table()


def _looks_recycled(current, cached):
    """True only when we can PROVE the PID now belongs to a different process.

    "Cannot tell" is not "recycled". If either start time is missing - psutil has
    no ``Process`` here, the platform will not say, a bulk scan wrote the entry
    without one - the honest answer is that the entry is unverifiable, and the
    cache falls back to its TTL exactly as it did before. Treating unverifiable as
    recycled looked tempting ("fail safe") and was in fact a way to destroy the
    cache wholesale on every fallback path: every lookup would evict, re-resolve,
    fail to stamp, and evict again, so process names came back empty. Hardening
    must not degrade the environments it cannot harden.

    The tolerance absorbs the last-bit difference between ``process_iter`` and
    ``Process.create_time`` for the same process.
    """
    if current is None or cached is None:
        return False
    return abs(current - cached) >= 0.001


def _psutil_created(pid):
    """Start time of ``pid`` right now - the identity stamp. ``None`` if unknown.

    This is what tells a recycled PID from the process that used to own it, and it
    is the reason the cache can be trusted at all. Deliberately its OWN call rather
    than part of the full lookup: it is the cheapest identity probe there is. Its
    cost is decided by one thing - whether ``OpenProcess`` succeeds. MEASURED
    2026-07-24 (Win11, CPython 3.14): ~0.005 ms per PID when the handle opens,
    ~5.7 ms when it is DENIED, because psutil then falls back to a full-system scan
    for that single PID. Whether it opens is an ELEVATION question, not a "hardened
    process" one - see ``PortTable.info`` for what that means per refresh, and why
    it is cheap in every real session.
    """
    try:
        import psutil
        return psutil.Process(int(pid)).create_time()
    except Exception:
        return None


def _psutil_process_info(pid):
    """``(name, ppid, created)`` for one pid, or ``None`` when it cannot be resolved."""
    try:
        import psutil
        process = psutil.Process(int(pid))
        return str(process.name() or ""), process.ppid(), process.create_time()
    except Exception:
        return None


# -- the table ----------------------------------------------------------------- #
class PortTable:
    """Cached ``local port -> pid`` map plus a lazy ``pid -> (name, ppid)`` cache.

    ``refresh`` is rate limited by ``interval``; a caller that misses a port may
    ask for an earlier rebuild (``miss_interval``), which is what closes the gap
    between "the app just opened a socket" and "the tool impairs it".
    """

    def __init__(self, interval=REFRESH_S, miss_interval=MISS_REFRESH_S,
                 clock=time.monotonic):
        self.interval = float(interval)
        self.miss_interval = float(miss_interval)
        self.clock = clock
        self._lock = threading.RLock()
        self._ports = {}                 # port -> pid
        self._info = {}                  # pid -> (name, ppid, created, written_at)
        self._bulk_at = 0.0              # last full process_iter (fallback path)
        self._last = 0.0                 # last successful refresh
        self._native = _make_native()
        self.native = self._native is not None

    # -- port table ------------------------------------------------------------ #
    def refresh(self, now=None, force=False):
        """Rebuild the port map. Returns True when it actually ran."""
        now = self.clock() if now is None else now
        with self._lock:
            if not force and (now - self._last) < self.interval and self._ports:
                return False
            ports = None
            if self._native is not None:
                try:
                    ports = self._native.port_pid_map()
                except Exception:                        # pragma: no cover
                    ports = None
                if ports is None:                        # native path broke: stop using it
                    self._native = None
                    self.native = False
            if ports is None:
                ports = _psutil_port_pid_map()
            if ports is None:
                self._last = now                         # do not hammer a broken lookup
                return False
            # A PID that has just lost every socket is a PID whose process is
            # probably gone - and a PID can only be handed to somebody else AFTER
            # its owner exits. So this is the moment to forget its name, before the
            # OS can hand the number to a process with a different one. It closes
            # the dangerous window (impairing a process the user never targeted)
            # from "the rest of the session" down to one refresh interval.
            #
            # Costs 2.5 us (measured): two set builds and a difference. The TTL
            # above still backstops PIDs that never owned a socket - ancestors,
            # and whatever a bulk scan swept in - which cannot be caught this way.
            departed = set(self._ports.values()) - set(ports.values())
            self._ports = ports
            self._last = now
            for pid in departed:
                self._info.pop(pid, None)
            self._expire_info(now)
            return True

    def refresh_if_stale(self, now=None, miss=False):
        """Refresh when the map is older than the (miss) interval."""
        now = self.clock() if now is None else now
        limit = self.miss_interval if miss else self.interval
        if (now - self._last) >= limit or not self._ports:
            return self.refresh(now, force=True)
        return False

    def snapshot(self):
        with self._lock:
            return dict(self._ports)

    def pid_for(self, port):
        if port is None:
            return None
        return self._ports.get(int(port))

    def age(self, now=None):
        return (self.clock() if now is None else now) - self._last

    # -- process info ----------------------------------------------------------- #
    def _expire_info(self, now):
        """Drop entries older than ``INFO_TTL_S``, counted from when they were WRITTEN.

        There used to be a ``len(self._info) < 512`` early return, and on a normal
        machine the cache holds 26-343 entries - so this never ran at all. Combined
        with ``info()`` bumping the timestamp on every cache HIT, an entry that was
        being read constantly could not expire by any route. A PID whose process had
        died therefore kept the dead process's name for the life of the session.

        That is not a cosmetic problem. Windows reuses PIDs, and the name is what
        targeting matches on, so a stale entry means either the target restarting
        onto a recycled PID is NOT impaired, or an innocent process that inherits
        the target's old PID IS. Both were reproduced against the real table.

        Measured cost of sweeping unconditionally: 2.2 us. There was never anything
        to buy with that threshold.
        """
        cutoff = now - INFO_TTL_S
        self._info = {pid: entry for pid, entry in self._info.items()
                      if entry[3] > cutoff}

    def info(self, pid, cheap=False):
        """``(name, ppid)`` for a pid - cached, verified, never raises.

        ``cheap=True`` means **never touch the OS from here**: answer from the cache
        or not at all. That is the mode the CAPTURE THREAD uses, and it is not an
        optimisation - it is the boundary the previous chunk established. Both the
        identity check and the fall-back resolve are psutil calls, so leaving either
        reachable from the packet path puts back exactly what was taken out of it.
        The cost of being cheap is a connection-log row that may show a stale or
        empty process name; ``_log_conn`` retries while packets keep coming, and the
        name is display, not a decision. Targeting - which IS a decision - always
        runs on the resolver thread and always verifies.

        Every cache hit is checked against the process's START TIME. A PID is only
        a number the OS hands out; the same number can belong to a different
        process a second later, and targeting matches on the NAME, so trusting a
        cached name means either the target restarting onto a recycled PID is not
        impaired, or an innocent process that inherits the old PID is. Both were
        reproduced against the real table before this check existed.

        Verifying is cheaper than a full resolve, but its cost turns entirely on
        whether ``OpenProcess`` succeeds - and that is an ELEVATION question, not the
        "hardened process" one an earlier version of this note assumed. MEASURED
        2026-07-24 (Win11, CPython 3.14, Chrome open): ``create_time()`` is ~0.005 ms
        per PID when the handle opens and ~5.7 ms when it is DENIED (psutil then
        scans the whole system for that one PID). An ADMIN opens every socket-owning
        PID - 0 of 27 denied here - so a warm refresh's recycle check is ~0.16 ms; a
        NON-admin is denied on system / other-user PIDs (16 of 27) and it climbs to
        ~90-180 ms, with the cold resolve at ~380 ms against ~36 ms elevated. Real
        impairment ALWAYS runs elevated (WinDivert will not open without admin), so
        this is cheap in every real session; the slow figure appears only on the one
        non-elevated path that runs the resolver at all, ``--simulate`` (synthetic
        packets, and the cost sits on the RESOLVER thread, never the capture one).
        Batching the denied PIDs in one ``NtQuerySystemInformation`` was measured and
        REJECTED (2026-07-24): it speeds only the non-elevated warm check - a demo
        mode - and does nothing for the elevated hot path or for the cold resolve,
        which NAME resolution dominates.
        """
        if pid is None:
            return ("", None)
        pid = int(pid)
        now = self.clock()
        with self._lock:
            entry = self._info.get(pid)
        if entry is not None:
            if cheap or not _looks_recycled(_psutil_created(pid), entry[2]):
                # The timestamp is NOT bumped here. It marks when the entry was
                # written, so the TTL means "this answer is at most N seconds old"
                # rather than "nobody has asked lately". Bumping it made the entry
                # of a busily-read PID immortal - which is exactly the entry most
                # worth re-checking, because it is the one decisions rest on.
                return (entry[0], entry[1])
            # Same number, PROVABLY a different process: the cached name is about
            # somebody else. Drop it and resolve afresh.
            with self._lock:
                if self._info.get(pid) is entry:
                    del self._info[pid]
        if cheap:
            # Nothing cached (or what was cached is provably wrong) and we may not
            # ask the OS. "" is the honest answer; the resolver will have filled the
            # cache by the time this row is looked at again.
            return ("", None)
        resolved = _psutil_process_info(pid)
        if resolved is None:
            # psutil.Process could not open the process (it is HARDENED - Chrome's
            # network service, some services - or denied, or already gone). Fall back
            # to a whole-system snapshot, which names it WITHOUT opening it. This used
            # to be ``psutil.process_iter`` at ~2.6 s; it is now a native toolhelp
            # snapshot at ~6 ms (see _process_table), so it is affordable on the
            # SYNCHRONOUS start/apply resolve too - which is what makes targeting a
            # hardened app like chrome BY NAME work fast. Throttled so a burst of
            # misses shares one snapshot.
            with self._lock:
                stale = (now - self._bulk_at) > 1.0
            if stale:
                table = _process_table()
                with self._lock:
                    self._bulk_at = now
                    for other, (name, ppid, created) in table.items():
                        self._info[other] = (name, ppid, created, now)
                    entry = self._info.get(pid)
                return (entry[0], entry[1]) if entry else ("", None)
            with self._lock:
                entry = self._info.get(pid)
            return (entry[0], entry[1]) if entry else ("", None)
        with self._lock:
            self._info[pid] = (resolved[0], resolved[1], resolved[2], now)
        return (resolved[0], resolved[1])

    def name_of(self, pid, cheap=False):
        return self.info(pid, cheap=cheap)[0]

    def warm_names(self):
        """Resolve (and verify) the name of every PID that currently owns a socket.

        Somebody on a background thread has to do this, because the capture thread
        reads names CHEAPLY - cache or nothing - and would otherwise show an empty
        process column. The resolver fills the cache for the PIDs it matches, but
        only while a target is set; most sessions have none, and the connection
        log's process column exists precisely so a tester can see who the traffic
        belongs to before deciding what to target.

        Cheap in the steady state: the names are already cached, so this is one
        identity check per PID (~0.13 ms for the 25-odd PIDs a desktop has). The
        first pass pays the real resolve (~124 ms) once.
        """
        for pid in set(self.snapshot().values()):
            self.info(pid)

    def ancestors(self, pid, depth=8):
        """``[(pid, name), ...]`` from the parent upwards (bounded, cycle-safe)."""
        chain, seen = [], {int(pid)} if pid is not None else set()
        current = self.info(pid)[1] if pid is not None else None
        while current and len(chain) < depth:
            current = int(current)
            if current in seen or current <= 0:
                break
            seen.add(current)
            name, parent = self.info(current)
            chain.append((current, name))
            current = parent
        return chain

    def process_for_port(self, port, now=None, allow_refresh=True):
        """Best-effort process name for a local port (``""`` when unknown)."""
        pid = self.pid_for(port)
        if pid is None and allow_refresh:
            self.refresh_if_stale(now, miss=True)
            pid = self.pid_for(port)
        # allow_refresh=False means "do not touch the OS", and that has to cover the
        # NAME lookup too - not just the socket-table rebuild. Resolving a name and
        # verifying an identity are both psutil calls; gating only one of them left
        # the packet path making the other.
        return self.name_of(pid, cheap=not allow_refresh) if pid else ""


_DEFAULT = None
_DEFAULT_LOCK = threading.Lock()


def default_table():
    """The process-wide port table (engine, GUI and targeting share one cache)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = PortTable()
        return _DEFAULT


def reset_default_table():
    """Drop the shared table (tests)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = None
