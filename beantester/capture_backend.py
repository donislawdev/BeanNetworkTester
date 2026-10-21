"""Which packet-capture driver this platform uses - the ONE place that knows.

Every "this is WinDivert" decision used to sit at its call site: the engine built
``pydivert.WinDivert`` itself, the socket watcher opened its own WinDivert handle,
``filters`` asked WinDivert's DLL whether a filter compiles, and ``driverwait``
read the QueryPerformanceCounter that WinDivert stamps packets with. A second
capture driver (eBPFDivert on Linux, through pydivert 4) would have meant a
platform branch in each of those places, and a branch that is missed in one of
them is a session that silently behaves like the other platform there.

So the choice is made here, once (``current()``), and the call sites ask the
backend instead. The Windows backend is the code those call sites ran before,
MOVED and not rewritten: the same calls with the same arguments in the same
order, which is what keeps a Windows session byte-for-byte what it was (pinned
by ``tests/test_capture_backend.py`` and its mutations).

None of this is on the packet path. The capture loop calls ``recv``/``send`` on
the handle it was given; the backend is asked at START and when a session's
measurements are set up, never per packet.

``pydivert`` is imported lazily, inside the methods: it is a platform-specific
dependency, and ``import beantester`` must work without it (layering contract).
"""
import errno
import os
import sys
import time
from typing import Any, Dict, Optional, Protocol, Tuple

from . import winenv


class CaptureBackend(Protocol):
    """The contract: everything a call site may ask of the platform's backend.

    A new backend implements ALL of it, and a new question goes here first, then
    into every backend - ``tests/test_capture_backend.py`` checks each backend
    against this list, so one that falls behind is red, not a session that
    behaves like another platform in one place.
    """

    name: str
    TEXTS: Dict[str, str]
    counts_overload: bool
    CLEANUP_LINE: str       # --cleanup-driver off Windows: why there is nothing to do
    CLEANUP_BLOCKER: str    # the same, as the Diagnostics button's i18n key
    # The Diagnostics "?" sheet's paragraphs on this driver's own rows, off Windows:
    # i18n keys, in order (Windows' own are nettools/diagnostics.WINDOWS_HELP).
    DIAGNOSTICS_HELP: Tuple[str, ...]

    def open_network(self, filt: str) -> Any: ...
    def socket_source_factory(self) -> Any: ...
    def filter_compiles(self, text: str) -> bool: ...
    def stamp_now(self) -> Any: ...
    def stamp_frequency(self) -> Any: ...
    def text(self, what: str) -> str: ...
    def overload_counters(self, divert: Any) -> Optional[Dict[str, int]]: ...
    def is_permission_error(self, exc: BaseException) -> bool: ...
    def open_failure_hint(self, exc: BaseException, elevated: Optional[bool] = None) -> str: ...
    def doctor_rows(self) -> Any: ...
    def platform_note(self) -> Optional[str]: ...
    def has_capture_rights(self) -> bool: ...
    def startup_note(self, has_rights: bool) -> Optional[str]: ...
    def rights_banner(self) -> str: ...


# The session lines every backend must have words for (``text``), and the ones
# only a backend whose ``overload_counters`` can answer needs.
REQUIRED_TEXTS = ("driver_queue", "driver_wait", "driver_wait_event", "send_failed")
OVERFLOW_TEXTS = ("overflow", "overflow_event", "overflow_total")

# The counters a backend whose ``counts_overload`` is True adds to the session's
# statistics (``engine.stats_snapshot``): packets the kernel let PAST this tool,
# unimpaired, and packets the driver DROPPED before this tool saw them. Neither is
# in ``seen``. One name each, read by the engine, the Statistics page, the banner
# and the repro report - and absent where the driver counts nothing (Windows), so
# that snapshot, its CSV columns and its JSON counters are what they were.
OVERLOAD_STATS = ("kernel_bypassed", "driver_dropped")


class WinDivertBackend:
    """Windows: WinDivert, through ``pydivert.WinDivert``."""

    name = "windivert"
    counts_overload = False     # see overload_counters
    # Off Windows (a platform with no capture driver) there is no WinDivert service.
    CLEANUP_LINE = "Not Windows - there is no WinDivert driver to clean up."
    CLEANUP_BLOCKER = "tools.diagnostics.clean_windows_only"
    # ...and no rows of its own to explain: its --doctor rows say capture needs Windows.
    DIAGNOSTICS_HELP: Tuple[str, ...] = ()

    @staticmethod
    def open_network(filt):
        """The NETWORK-layer handle the engine diverts packets through (not opened yet)."""
        import pydivert
        from . import driver
        divert = pydivert.WinDivert(filt)
        # a REAL driver was loaded: the kernel now holds its .sys file, so it
        # has to be unloaded before the process leaves (see driver.py)
        driver.mark_driver_used()
        return divert

    @staticmethod
    def socket_source_factory():
        """What opens the SOCKET-layer event source, or ``None`` for "poll the table".

        The socket watcher's map rests on the SOCKET_CONNECT event carrying the
        local port before the connection's first packet - true of WinDivert
        (``socketwatch``'s module docstring has the measurement).
        """
        from .socketwatch import windivert_socket_source
        return windivert_socket_source

    @staticmethod
    def filter_compiles(text):
        """Would WinDivert accept this filter? ``False`` when it cannot be asked.

        ``WinDivertHelperCompileFilter`` is a DLL helper - no handle, no admin - so
        this is the driver's OWN parser, not a guess about its grammar. Without
        ``pydivert`` (or off Windows) there is nothing to ask, and ``False`` is the
        honest answer: the caller then keeps the wide filter, which is the safe
        direction.
        """
        if not text:
            return False
        try:
            import ctypes
            from pydivert import windivert_dll as wd
            err, pos = ctypes.c_char_p(), ctypes.c_uint(0)
            buf = ctypes.create_string_buffer(64 * 1024)
            return bool(wd.WinDivertHelperCompileFilter(
                text.encode(), 0, buf, len(buf), ctypes.byref(err), ctypes.byref(pos)))
        except Exception:
            # A missing dll, a missing pydivert, a driver that will not answer: all of
            # them mean "cannot prove this filter is usable", and the caller must not
            # narrow on an unproven filter.
            return False

    # The clock a packet's ``timestamp`` is written in: QueryPerformanceCounter
    # ticks, and how many of them make a second (``None``/0 where there is none).
    # Looked up in ``winenv`` at every call rather than bound here, so whatever
    # ``winenv`` holds when a session asks is what it gets. Asked 20 times a second
    # at most (``driverwait.SAMPLE_S``), never per packet.
    @staticmethod
    def stamp_now():
        return winenv.qpc_now()

    @staticmethod
    def stamp_frequency():
        return winenv.qpc_frequency()

    # The session's log lines that name the driver, by what they are about. These
    # are the keys Windows sessions have always used.
    TEXTS = {"driver_queue": "log.driver_queue", "driver_wait": "log.driver_wait",
             "driver_wait_event": "events.driver_wait", "send_failed": "log.send_failed"}

    @classmethod
    def text(cls, what):
        return cls.TEXTS[what]

    @staticmethod
    def overload_counters(divert):
        """Packets the driver let past this tool, or dropped, under load: none to read.

        WinDivert keeps no such count a program can ask for (only its queue
        parameters), so there is nothing to report and nothing is asked.
        """
        return None

    @staticmethod
    def is_permission_error(exc):
        """Is this open failure "not allowed"? Never decided here on Windows.

        The CLI refuses an unelevated run before it opens anything (exit
        PERMISSION), so a failure that reaches the open is about the driver itself
        and is answered by ``open_failure_hint``.
        """
        return False

    @staticmethod
    def open_failure_hint(exc, elevated=None):
        from . import driver
        return driver.open_failure_hint(exc, elevated=elevated)

    @staticmethod
    def doctor_rows():
        """``--doctor``'s driver rows for a platform ``driver.doctor`` has none of its own.

        ``None``: Windows has its own branch in ``driver.doctor``, and a platform
        with no capture driver keeps the rows it always had.
        """
        return None

    @staticmethod
    def platform_note():
        """What ``--doctor``'s platform row adds off Windows: ``None`` = its own words."""
        return None

    # The window's three questions about rights (``gui/app.py``): MOVED from the
    # window, where they used to be asked of Windows directly - so a Linux window
    # said "capture works only on Windows" over a session that was running.
    @staticmethod
    def has_capture_rights():
        """Does this process hold an elevated token? Yes off Windows: nothing to elevate.

        Read from shell32 itself, and a failure RAISES: the window decides what a
        token it cannot read means (it does not cry wolf). The command line keeps its
        own question, ``winenv.is_admin``, which answers that case the other way.
        """
        if not winenv.is_windows():
            return True
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())

    @staticmethod
    def startup_note(has_rights):
        """The window's first log line about capturing here, or ``None``."""
        if not winenv.is_windows():
            return "log.note_windows"
        return None if has_rights else "log.note_admin"

    @staticmethod
    def rights_banner():
        """The red line over a window that cannot capture."""
        return "warn.not_admin"


class EBPFDivertBackend:
    """Linux (experimental): eBPFDivert, through ``pydivert.EBPFDivert`` (pydivert 4).

    eBPFDivert runs WinDivert's filter language and packet semantics on eBPF: TC
    hooks for the NETWORK layer, cgroup programs for the event layers. Both it
    (0.0.5) and pydivert's Linux backend are marked experimental upstream.
    MEASURED 2026-10-20 in WSL2 (6.18) and on GitHub's ubuntu-24.04 (7.0) and
    ubuntu-22.04 (6.8) runners, always inside a network namespace of its own:
    pass-through byte for byte, drop, delay, payload edits, this program's own RST
    in both directions and on loopback, and every filter shape this program builds
    is matched exactly in the kernel. What differs from WinDivert shaped the
    methods below, each where it applies.
    """

    name = "ebpfdivert"
    counts_overload = True      # see overload_counters
    # Nothing to clean up, MEASURED 2026-10-20 (Ubuntu 26.04): a SIGKILLed session's
    # programs stopped holding traffic after 2.6 s, and EBPFDivert.unregister() right
    # after the kill made it 2.6 s too - so a cleanup button would do nothing. (It
    # did leave a LIVE handle of another process alone.) The kernel does it.
    CLEANUP_LINE = ("Linux - nothing to clean up: the kernel removes a stopped or killed "
                    "session's eBPF programs by itself, within about 3 seconds.")
    CLEANUP_BLOCKER = "tools.diagnostics.clean_linux"
    # What doctor_rows' four rows need, then why "Clean up the driver" stays greyed
    # out - the same sentence as the note under the button, not a second copy of it.
    DIAGNOSTICS_HELP: Tuple[str, ...] = ("tools.diagnostics.help_linux", CLEANUP_BLOCKER)

    @staticmethod
    def open_network(filt):
        import pydivert
        # Never ``interfaces=``: with an interface list eBPFDivert leaves loopback
        # traffic out (measured; pydivert's docs say it is always included), and the
        # default is every interface plus loopback. Never the ``Divert`` facade
        # either: it forwards every attribute through __getattr__, on the packet path.
        return pydivert.EBPFDivert(filt)

    @staticmethod
    def socket_source_factory():
        """``None``: poll the socket table instead (owner's decision, 2026-10-20).

        eBPFDivert's SOCKET_CONNECT carries LocalPort 0 for a socket that was not
        bound first - the usual client (measured) - and the socket watcher's map
        rests on that port arriving before the connection's first packet. MEASURED
        on this program with ``--target``: with the events on, a new connection of
        the target went through unimpaired for 0.3-0.5 s (its port reached the map
        only through the poller); polling alone, for its first exchange only.
        """
        return None

    @staticmethod
    def filter_compiles(text):
        """Would eBPFDivert accept this filter? ``False`` when it cannot be asked.

        ``EBPFDivert.check_filter`` is WinDivert's own filter compiler, built into
        libebpfdivert - no handle and no root needed.
        """
        if not text:
            return False
        try:
            from pydivert import EBPFDivert
            return bool(EBPFDivert.check_filter(text)[0])
        except Exception:
            # The same rule as WinDivert's check: "cannot be asked" keeps the wide
            # filter, the safe direction.
            return False

    # The clock a packet's ``timestamp`` is written in: CLOCK_MONOTONIC
    # nanoseconds (eBPFDivert's API reference; measured: a packet received at once
    # reads 20-52 us old on this clock).
    @staticmethod
    def stamp_now():
        return time.clock_gettime_ns(time.CLOCK_MONOTONIC)

    @staticmethod
    def stamp_frequency():
        return 1_000_000_000

    TEXTS = {"driver_queue": "log.ebpf_driver_queue", "driver_wait": "log.ebpf_driver_wait",
             "driver_wait_event": "events.ebpf_driver_wait", "send_failed": "log.ebpf_send_failed",
             "overflow": "log.ebpf_overflow", "overflow_event": "events.ebpf_overflow",
             "overflow_total": "log.ebpf_overflow_total"}

    @classmethod
    def text(cls, what):
        return cls.TEXTS[what]

    @staticmethod
    def overload_counters(divert):
        """``{"bypassed", "dropped"}`` since the handle opened, or ``None``.

        An overloaded eBPFDivert does two different things, both MEASURED: a packet
        that does not fit the kernel's ring buffer is let PAST this tool, unimpaired
        (``ringbuf_full``), and one that does not fit the library's queue is DROPPED
        (``queue_full``). Without the first number a session told to drop
        everything reports 100% loss while a third of the traffic arrives. A bigger
        ring does not help: it turned bypassed packets into dropped ones (64 MB: 188
        000 dropped), with the same throughput. ``None`` for a divert that keeps no
        such count (the simulate path, test doubles).
        """
        stats = getattr(divert, "stats", None)
        if stats is None:
            return None
        counts = stats()
        return {"bypassed": int(counts.get("ringbuf_full", 0)),
                "dropped": int(counts.get("queue_full", 0))}

    @staticmethod
    def is_permission_error(exc):
        """eBPFDivert refuses an unprivileged open with EPERM/EACCES (it needs root, or
        CAP_BPF + CAP_NET_ADMIN + CAP_NET_RAW). Asked of the open itself rather than
        guessed beforehand: the open is the authority, and nothing is captured yet.

        Not when the process IS root: the kernel can refuse root too (lockdown, an
        LSM policy such as SELinux or AppArmor), and "run it with sudo" would then
        be wrong advice next to ``--doctor``'s "privileges ok". That failure stays
        a RUNTIME one, with the driver's own words and ``open_failure_hint``'s.
        """
        if getattr(exc, "errno", None) not in _REFUSED:
            return False
        return _euid() != 0

    OPEN_ERROR_HINTS = {errno.EPERM: "dialogs.ebpf_needs_root",
                        errno.EACCES: "dialogs.ebpf_needs_root",
                        errno.EOPNOTSUPP: "dialogs.ebpf_kernel",
                        errno.EINVAL: "dialogs.ebpf_filter_refused"}
    ROOT_REFUSED_HINT = "dialogs.ebpf_refused_as_root"

    @classmethod
    def open_failure_hint(cls, exc, elevated=None):
        code = getattr(exc, "errno", None)
        if code in _REFUSED and _euid() == 0:
            return cls.ROOT_REFUSED_HINT
        return cls.OPEN_ERROR_HINTS.get(code, "")

    PLATFORM_NOTE = " - capture is experimental (eBPFDivert), and --simulate needs none of the rows below"

    @staticmethod
    def doctor_rows(release=None, root="/", euid=None, status=None):
        """``--doctor``'s rows for eBPFDivert. Reads files, opens no handle.

        A row without which a capture cannot start is a ``fail``, as Windows'
        administrator and pydivert rows are (the owner's decision, 2026-10-20). It
        used to be a ``warn``, and the Diagnostics tab printed "Nothing here stops a
        session from starting" under "a capture needs sudo" (measured on Ubuntu
        26.04): the verdict is about a real session, and without these one does not
        start. ``--doctor`` then ends with exit 1 there, as it does on Windows
        unelevated. The arguments are seams for the tests (kernel release,
        filesystem root, euid, the text of /proc/self/status).
        """
        release = os.uname().release if release is None else release
        rows = []
        try:
            major, minor = (int(part) for part in release.split(".")[:2])
            new_enough = (major, minor) >= (5, 10)
        except ValueError:
            new_enough = False
        rows.append(("kernel", "ok" if new_enough else "fail",
                     release + ("" if new_enough else " - eBPFDivert needs Linux 5.10 or newer, "
                                                      "so a capture session cannot start")))
        btf = os.path.exists(os.path.join(root, "sys", "kernel", "btf", "vmlinux"))
        rows.append(("btf", "ok" if btf else "fail",
                     "present" if btf else "missing - the kernel was built without BTF, which "
                                           "eBPFDivert needs, so a capture session cannot start"))
        rows.append(_privileges_row(_euid() if euid is None else euid, root, status))
        rows.append(_pydivert_row())
        return rows

    @classmethod
    def platform_note(cls):
        return cls.PLATFORM_NOTE

    @staticmethod
    def has_capture_rights():
        """Root, or CAP_BPF + CAP_NET_ADMIN + CAP_NET_RAW - the ``--doctor`` row's answer.

        A hint, not the authority: the open itself decides (``is_permission_error``),
        and the kernel can refuse root too. Asked by the window for its red line.
        """
        return _rights(_euid(), "/", None) is not None

    @staticmethod
    def startup_note(has_rights):
        return "log.ebpf_note_experimental" if has_rights else "log.ebpf_note_root"

    @staticmethod
    def rights_banner():
        return "warn.ebpf_not_root"


# Capability bits (linux/capability.h) a capture needs without root.
_CAP_NET_ADMIN, _CAP_NET_RAW, _CAP_BPF = 12, 13, 39

# What eBPFDivert's open answers when it is not allowed.
_REFUSED = (errno.EPERM, errno.EACCES)


def _euid():
    """The effective user id, or ``None`` where the platform has none (Windows).

    One place, so a test can say "root" or "not root" on any machine.
    """
    geteuid = getattr(os, "geteuid", None)
    return geteuid() if geteuid is not None else None


def _rights(euid, root, status):
    """What lets this process capture - ``"root"`` or the three capabilities - or ``None``.

    ONE answer for ``--doctor``'s row and the window's red line, so the two cannot
    disagree about the same process.
    """
    if euid == 0:
        return "root"
    if status is None:
        try:
            with open(os.path.join(root, "proc", "self", "status"), encoding="ascii") as f:
                status = f.read()
        except OSError:
            status = ""
    caps = 0
    for line in status.splitlines():
        if line.startswith("CapEff:"):
            caps = int(line.split(":", 1)[1].strip() or "0", 16)
    needed = (1 << _CAP_NET_ADMIN) | (1 << _CAP_NET_RAW) | (1 << _CAP_BPF)
    if caps & needed == needed:
        return "CAP_BPF, CAP_NET_ADMIN and CAP_NET_RAW"
    return None


def _privileges_row(euid, root, status):
    how = _rights(euid, root, status)
    if how is not None:
        return ("privileges", "ok", how)
    return ("privileges", "fail", "not root, and without CAP_BPF, CAP_NET_ADMIN and CAP_NET_RAW - "
                                  "a capture session cannot start. Run it with sudo")


def _pydivert_row():
    try:
        from pydivert import bpf
    except ImportError:
        return ("pydivert", "fail", "missing - pip install pydivert")
    lib = bpf.libebpfdivert
    if lib is None:
        return ("pydivert", "fail", "installed, but its libebpfdivert did not load - "
                                    "reinstalling pydivert puts it back")
    return ("pydivert", "ok", "importable, eBPFDivert " + lib.ebpfdivert_version().decode())


_WINDIVERT = WinDivertBackend()
_EBPFDIVERT = EBPFDivertBackend()


def select(platform: str) -> CaptureBackend:
    """The backend for ``platform`` (a ``sys.platform`` value).

    eBPFDivert on Linux, WinDivert everywhere else: off Windows and Linux the
    WinDivert path fails exactly where it always has (no pydivert to import, no
    DLL to load).
    """
    return _EBPFDIVERT if platform.startswith("linux") else _WINDIVERT


_CURRENT: CaptureBackend = select(sys.platform)


def current() -> CaptureBackend:
    """This process's backend, chosen once at import."""
    return _CURRENT
