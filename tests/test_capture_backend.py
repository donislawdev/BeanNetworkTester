"""The capture backend: one place picks the platform's packet-capture driver.

``beantester/capture_backend.py`` took the WinDivert decisions out of four call
sites (the engine's handle, the socket watcher's event source, the filter
compile check, the driver-wait clock). These tests pin both halves of that:

* the Windows backend does EXACTLY what those call sites did - the same call,
  the same argument, the same order - so a Windows session is what it was;
* the call sites really ask the backend, so a second backend is a backend and
  not a fifth platform branch somewhere.

🔴 No test here may reach a real driver. The engine test goes down the REAL start
path (``divert=None``), so a stand-in ``pydivert`` that refuses to build anything
sits in ``sys.modules`` for it, and its filter is ``false`` (matches no packet):
a mutation that bypasses the backend fails on the stand-in, never on this
machine's network.
"""
import errno
import json
import os
import sys
import threading
import time
import types

import pytest

from beantester import capture_backend, crashlog, driver, filters, socketwatch, winenv
from beantester.capture_backend import EBPFDivertBackend, WinDivertBackend
from beantester.driverwait import WARN_S, DriverWait
from beantester.engine import BeanEngine
from fakes import ROOT, FakeDivert, check


def _refusing_pydivert():
    """A ``pydivert`` that fails loudly on any attempt to build a real handle."""
    module = types.ModuleType("pydivert")

    def refuse(*_a, **_k):
        raise AssertionError("a real pydivert handle was requested in a test")
    module.WinDivert = refuse
    return module


class _FakePorts:
    """The slice of portmap.PortTable a session touches (see test_socketwatch_wiring)."""

    def refresh(self, now=None, force=False):
        return True

    def refresh_if_stale(self, now=None, miss=False):
        return True

    def snapshot(self):
        return {}

    def collected(self):
        return {}, time.monotonic()

    def warm_names(self):
        pass

    def name_of(self, pid, cheap=False):
        return ""

    def ancestors(self, pid, depth=8):
        return []

    def process_for_port(self, port, now=None, allow_refresh=True):
        return ""

    def pid_for(self, port):
        return None


class _ParkedSource:
    """An event source with nothing to say: parks until closed."""

    def __init__(self):
        self._closed = threading.Event()

    def __iter__(self):
        self._closed.wait()
        return iter(())

    def close(self):
        self._closed.set()


class _FakeBackend:
    """Records what the engine asks of a backend."""

    name = "fake"
    counts_overload = False
    CLEANUP_LINE = WinDivertBackend.CLEANUP_LINE
    CLEANUP_BLOCKER = WinDivertBackend.CLEANUP_BLOCKER
    DIAGNOSTICS_HELP = WinDivertBackend.DIAGNOSTICS_HELP

    def __init__(self, source_factory=None):
        self.opened = []
        self.divert = FakeDivert([])
        self._source_factory = source_factory

    def open_network(self, filt):
        self.opened.append(filt)
        return self.divert

    def socket_source_factory(self):
        return self._source_factory

    def filter_compiles(self, text):
        return False

    @staticmethod
    def stamp_now():
        return 99

    @staticmethod
    def stamp_frequency():
        return 1234

    TEXTS = WinDivertBackend.TEXTS

    def text(self, what):
        return self.TEXTS[what]

    def overload_counters(self, divert):
        return None

    def is_permission_error(self, exc):
        return False

    def open_failure_hint(self, exc, elevated=None):
        return ""

    def doctor_rows(self):
        return None

    def platform_note(self):
        return None

    def has_capture_rights(self):
        return True

    def startup_note(self, has_rights):
        return None

    def rights_banner(self):
        return "warn.not_admin"


# -- the choice ---------------------------------------------------------------- #
def test_windows_gets_the_windivert_backend():
    check("win32 -> WinDivert", isinstance(capture_backend.select("win32"), WinDivertBackend))
    check("a platform with no capture driver keeps the WinDivert path it always had",
          isinstance(capture_backend.select("darwin"), WinDivertBackend))
    check("this process's backend is the one its platform selects",
          capture_backend.current() is capture_backend.select(sys.platform))


def test_linux_gets_the_ebpfdivert_backend():
    check("linux -> eBPFDivert", isinstance(capture_backend.select("linux"), EBPFDivertBackend))


# -- the Windows backend is the code it was moved from -------------------------- #
def test_the_windows_backend_builds_windivert_with_the_filter_then_marks_the_driver(monkeypatch):
    calls = []

    class _WinDivert:
        def __init__(self, *args, **kwargs):
            calls.append(("WinDivert", args, kwargs))

    module = types.ModuleType("pydivert")
    module.WinDivert = _WinDivert
    monkeypatch.setitem(sys.modules, "pydivert", module)
    monkeypatch.setattr(driver, "mark_driver_used", lambda: calls.append(("marked",)))

    handle = WinDivertBackend.open_network("tcp.DstPort == 9")
    check("pydivert.WinDivert gets the filter and nothing else",
          calls[0] == ("WinDivert", ("tcp.DstPort == 9",), {}), f"({calls})")
    check("the driver is marked used AFTER the handle object exists",
          calls[1:] == [("marked",)], f"({calls})")
    check("and the handle comes back unopened, for the engine to open",
          isinstance(handle, _WinDivert))

    calls.clear()

    def refused(*_a, **_k):
        raise OSError("refused")
    module.WinDivert = refused
    try:
        WinDivertBackend.open_network("false")
        raised = False
    except OSError:
        raised = True
    check("a handle that cannot be built raises, and marks nothing", raised and calls == [], f"({calls})")


def test_the_windows_event_source_is_the_windivert_socket_layer():
    check("the SOCKET-layer source the socket watcher has always opened",
          WinDivertBackend.socket_source_factory() is socketwatch.windivert_socket_source)


def test_the_windows_filter_check_asks_windivert_and_never_guesses(monkeypatch):
    asked = []
    answer = [1]

    def compile_filter(text, layer, buf, size, err, pos):
        asked.append((text, layer))
        return answer[0]

    module = types.ModuleType("pydivert")
    module.windivert_dll = types.SimpleNamespace(WinDivertHelperCompileFilter=compile_filter)
    monkeypatch.setitem(sys.modules, "pydivert", module)

    check("WinDivert's parser accepts -> True", WinDivertBackend.filter_compiles("tcp") is True)
    check("asked with the text and the NETWORK layer", asked == [(b"tcp", 0)], f"({asked})")
    answer[0] = 0
    check("WinDivert's parser refuses -> False", WinDivertBackend.filter_compiles("tcp ==") is False)
    asked.clear()
    check("an empty filter is False without asking", WinDivertBackend.filter_compiles("") is False and not asked)

    def broken(*_a):
        raise OSError("no dll")
    module.windivert_dll = types.SimpleNamespace(WinDivertHelperCompileFilter=broken)
    check("a parser that cannot be asked -> False", WinDivertBackend.filter_compiles("tcp") is False)
    monkeypatch.setitem(sys.modules, "pydivert", None)
    check("no pydivert at all -> False", WinDivertBackend.filter_compiles("tcp") is False)


def test_the_windows_clock_is_the_qpc_winenv_reads(monkeypatch):
    monkeypatch.setattr(winenv, "qpc_now", lambda: 7)
    monkeypatch.setattr(winenv, "qpc_frequency", lambda: 10_000_000)
    check("stamp_now is QueryPerformanceCounter, read when asked", WinDivertBackend.stamp_now() == 7)
    check("stamp_frequency is its frequency", WinDivertBackend.stamp_frequency() == 10_000_000)


# -- the call sites ask the backend ---------------------------------------------- #
def test_the_filter_check_is_the_backends(monkeypatch):
    seen = []

    class _Answering(_FakeBackend):
        def filter_compiles(self, text):
            seen.append(text)
            return "the backend's answer"
    monkeypatch.setattr(capture_backend, "current", lambda: _Answering())
    check("filters.filter_compiles returns what the backend says",
          filters.filter_compiles("udp") == "the backend's answer" and seen == ["udp"], f"({seen})")


def test_the_driver_wait_reads_the_backends_clock(monkeypatch):
    monkeypatch.setattr(capture_backend, "current", lambda: _FakeBackend())
    wait = DriverWait(lambda *_a: None, lambda *_a: None)
    wait.begin()
    check("the frequency comes from the backend", wait.freq == 1234, f"({wait.freq})")
    check("and so does the clock it compares stamps with", wait.qpc() == 99)


def test_the_engine_opens_its_capture_through_the_backend(monkeypatch):
    monkeypatch.setitem(sys.modules, "pydivert", _refusing_pydivert())
    monkeypatch.setattr(crashlog, "arm_for_capture", lambda: None)
    backend = _FakeBackend(source_factory=None)
    monkeypatch.setattr(capture_backend, "current", lambda: backend)
    eng = BeanEngine()
    eng._ports = _FakePorts()
    eng.start("false")                               # divert=None: the REAL start path
    try:
        check("the handle came from the backend, with the session's filter",
              backend.opened == ["false"] and eng._divert is backend.divert, f"({backend.opened})")
        check("no event source from the backend -> the session polls the table",
              eng._socketwatch is None and eng.is_running())
    finally:
        eng.stop()


def test_the_engine_takes_its_event_source_from_the_backend(monkeypatch):
    monkeypatch.setitem(sys.modules, "pydivert", _refusing_pydivert())
    monkeypatch.setattr(crashlog, "arm_for_capture", lambda: None)
    made = []

    def factory():
        made.append(_ParkedSource())
        return made[-1]
    backend = _FakeBackend(source_factory=factory)
    monkeypatch.setattr(capture_backend, "current", lambda: backend)
    eng = BeanEngine()
    eng._ports = _FakePorts()
    eng.start("false")
    try:
        check("the socket watcher runs on the source the backend made",
              len(made) == 1 and eng._socketwatch is not None, f"({made}, {eng._socketwatch})")
    finally:
        eng.stop()


# -- the contract ------------------------------------------------------------------ #
def test_every_backend_answers_the_whole_contract():
    """A question added to one backend only is a session that behaves like another
    platform in that one place - so every backend is held to the Protocol's list."""
    contract = capture_backend.CaptureBackend
    members = sorted({n for n in vars(contract) if not n.startswith("_")}
                     | set(contract.__annotations__))
    check("the contract names what the call sites ask",
          {"open_network", "socket_source_factory", "filter_compiles", "stamp_now",
           "stamp_frequency", "text", "overload_counters", "is_permission_error",
           "open_failure_hint", "doctor_rows", "platform_note", "name", "TEXTS",
           "has_capture_rights", "startup_note", "rights_banner", "counts_overload",
           "CLEANUP_LINE", "CLEANUP_BLOCKER", "DIAGNOSTICS_HELP"} <= set(members),
          f"({members})")
    for backend in (WinDivertBackend, EBPFDivertBackend, _FakeBackend):
        missing = [n for n in members if not hasattr(backend, n)]
        check(f"{backend.name}: answers all of it", not missing, f"({missing})")
        texts = [n for n in capture_backend.REQUIRED_TEXTS if n not in backend.TEXTS]
        check(f"{backend.name}: has words for every session line", not texts, f"({texts})")
    check("the backend that counts overload has words for it",
          all(n in EBPFDivertBackend.TEXTS for n in capture_backend.OVERFLOW_TEXTS))


# -- the Linux backend (eBPFDivert) ---------------------------------------------- #
# Every test here drives EBPFDivertBackend on ANY platform through a stand-in
# pydivert, so the Windows runner checks the Linux rules too.

def _ebpf_pydivert(check_filter=None, version=b"0.0.5", lib=True):
    """A stand-in ``pydivert`` with what the Linux backend asks of the real one."""
    made = []

    class _EBPFDivert:
        def __init__(self, *args, **kwargs):
            made.append((args, kwargs))

        @staticmethod
        def check_filter(text, layer=0):
            return check_filter(text) if check_filter else (True, 0, "")

    module = types.ModuleType("pydivert")
    module.EBPFDivert = _EBPFDivert
    library = types.SimpleNamespace(ebpfdivert_version=lambda: version) if lib else None
    module.bpf = types.SimpleNamespace(libebpfdivert=library)
    return module, made


def test_linux_opens_ebpfdivert_with_the_filter_and_nothing_else(monkeypatch):
    module, made = _ebpf_pydivert()
    monkeypatch.setitem(sys.modules, "pydivert", module)
    marked = []
    monkeypatch.setattr(driver, "mark_driver_used", lambda: marked.append(1))
    handle = EBPFDivertBackend.open_network("udp.DstPort == 9")
    check("EBPFDivert gets the filter, and no interface list (one would drop loopback)",
          made == [(("udp.DstPort == 9",), {})], f"({made})")
    check("no WinDivert service marker: there is no service on Linux", not marked)
    check("and the handle comes back unopened", isinstance(handle, module.EBPFDivert))


def test_linux_polls_the_socket_table_instead_of_the_socket_events():
    check("no event source: SOCKET_CONNECT carries no local port here (owner's decision: poll)",
          EBPFDivertBackend.socket_source_factory() is None)


def test_the_linux_filter_check_asks_ebpfdivert_and_never_guesses(monkeypatch):
    asked = []
    verdict = [(True, 0, "")]

    def check_filter(text):
        asked.append(text)
        return verdict[0]
    module, _ = _ebpf_pydivert(check_filter=check_filter)
    monkeypatch.setitem(sys.modules, "pydivert", module)
    check("eBPFDivert's compiler accepts -> True", EBPFDivertBackend.filter_compiles("tcp") is True)
    verdict[0] = (False, 3, "parse error")
    check("it refuses -> False", EBPFDivertBackend.filter_compiles("tcp ==") is False)
    asked.clear()
    check("an empty filter is False without asking",
          EBPFDivertBackend.filter_compiles("") is False and not asked)

    def broken(text, layer=0):
        raise ImportError("libebpfdivert not found")
    module.EBPFDivert.check_filter = staticmethod(broken)
    check("a compiler that cannot be asked -> False", EBPFDivertBackend.filter_compiles("tcp") is False)
    monkeypatch.setitem(sys.modules, "pydivert", None)
    check("no pydivert -> False", EBPFDivertBackend.filter_compiles("tcp") is False)


def test_the_linux_clock_is_clock_monotonic_in_nanoseconds():
    check("a second is 1e9 of its ticks", EBPFDivertBackend.stamp_frequency() == 1_000_000_000)
    if not hasattr(time, "clock_gettime_ns"):
        pytest.skip("CLOCK_MONOTONIC is read only where the platform has clock_gettime")
    before = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    now = EBPFDivertBackend.stamp_now()
    after = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    check("stamp_now reads CLOCK_MONOTONIC", before <= now <= after, f"({before} {now} {after})")


def test_the_session_texts_name_the_platforms_own_driver():
    check("Windows keeps the keys its sessions have always said",
          WinDivertBackend.TEXTS == {"driver_queue": "log.driver_queue",
                                     "driver_wait": "log.driver_wait",
                                     "driver_wait_event": "events.driver_wait",
                                     "send_failed": "log.send_failed"}, f"({WinDivertBackend.TEXTS})")
    for code in ("en", "pl", "zh"):
        with open(os.path.join(ROOT, "lang", f"{code}.json"), encoding="utf-8") as f:
            texts = json.load(f)
        for backend in (WinDivertBackend, EBPFDivertBackend):
            missing = sorted(k for k in backend.TEXTS.values() if k not in texts)
            check(f"{code}: every {backend.name} text exists", not missing, f"({missing})")
        hints = sorted((set(EBPFDivertBackend.OPEN_ERROR_HINTS.values())
                        | {EBPFDivertBackend.ROOT_REFUSED_HINT}) - set(texts))
        check(f"{code}: every Linux open-failure hint exists", not hints, f"({hints})")
        if code == "en":
            named = sorted(k for k in EBPFDivertBackend.TEXTS.values() if "WinDivert" in texts[k])
            check("no Linux line names WinDivert", not named, f"({named})")


def test_only_the_linux_driver_counts_what_it_let_past_or_dropped():
    class _Counting:
        def stats(self):
            return {"ringbuf_full": 7, "queue_full": 2, "diverted": 99}
    check("eBPFDivert: let past = ringbuf_full, dropped = queue_full",
          EBPFDivertBackend.overload_counters(_Counting()) == {"bypassed": 7, "dropped": 2})
    check("a divert that keeps no count (simulate, doubles) -> None",
          EBPFDivertBackend.overload_counters(FakeDivert([])) is None)
    check("WinDivert asks nothing, whatever the handle has",
          WinDivertBackend.overload_counters(_Counting()) is None)


def test_only_linux_reads_an_open_failure_as_missing_rights(monkeypatch):
    monkeypatch.setattr(capture_backend, "_euid", lambda: 1000)       # not root, on any machine
    for code in (errno.EPERM, errno.EACCES):
        check(f"Linux: errno {code} at the open means 'not allowed'",
              EBPFDivertBackend.is_permission_error(OSError(code, "no")))
    check("Linux: a bad filter is not a rights problem",
          not EBPFDivertBackend.is_permission_error(OSError(errno.EINVAL, "bad filter")))
    check("Windows never decides it at the open (its check runs before)",
          not WinDivertBackend.is_permission_error(OSError(errno.EPERM, "no")))
    check("Linux hints: rights, kernel, filter, and nothing for the rest",
          [EBPFDivertBackend.open_failure_hint(OSError(c, "x"))
           for c in (errno.EPERM, errno.EOPNOTSUPP, errno.EINVAL, errno.ENOENT)]
          == ["dialogs.ebpf_needs_root", "dialogs.ebpf_kernel", "dialogs.ebpf_filter_refused", ""])
    monkeypatch.setattr(capture_backend, "_euid", lambda: 0)
    refused = OSError(errno.EPERM, "Operation not permitted")
    check("root refused by the kernel (lockdown, an LSM) is not 'missing rights'",
          not EBPFDivertBackend.is_permission_error(refused))
    check("and is told so, not to use sudo",
          EBPFDivertBackend.open_failure_hint(refused) == "dialogs.ebpf_refused_as_root")
    check("root's other failures keep their own hints",
          EBPFDivertBackend.open_failure_hint(OSError(errno.EINVAL, "x")) == "dialogs.ebpf_filter_refused")
    seen = []
    monkeypatch.setattr(driver, "open_failure_hint",
                        lambda exc, elevated=None: seen.append((exc, elevated)) or "key")
    err = OSError(5, "denied")
    check("Windows: the hint is driver.open_failure_hint's, asked the same way",
          WinDivertBackend.open_failure_hint(err, elevated=True) == "key" and seen == [(err, True)])


def test_the_windows_backend_asks_the_window_s_rights_questions_as_the_window_did(monkeypatch):
    """MOVED from ``App._detect_admin``/``_check_environment``/the banner: shell32's
    token on Windows (a failure raises - the window does not cry wolf), "nothing to
    elevate" off it, and the same two notes and banner as before."""
    import ctypes
    monkeypatch.setattr(winenv, "is_windows", lambda: True)
    shell32 = types.SimpleNamespace(IsUserAnAdmin=lambda: 1)
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(shell32=shell32), raising=False)
    check("an elevated token", WinDivertBackend.has_capture_rights() is True)
    shell32.IsUserAnAdmin = lambda: 0
    check("and one that is not", WinDivertBackend.has_capture_rights() is False)

    def unreadable():
        raise OSError("no token")
    shell32.IsUserAnAdmin = unreadable
    with pytest.raises(OSError):
        WinDivertBackend.has_capture_rights()
    check("no note for an elevated window", WinDivertBackend.startup_note(True) is None)
    check("'run as administrator' for one that is not",
          WinDivertBackend.startup_note(False) == "log.note_admin")
    check("the banner it always had", WinDivertBackend.rights_banner() == "warn.not_admin")
    monkeypatch.setattr(winenv, "is_windows", lambda: False)
    check("off Windows: nothing to elevate for", WinDivertBackend.has_capture_rights() is True)
    check("and the note says where capture works",
          WinDivertBackend.startup_note(True) == "log.note_windows")


def test_the_linux_backend_reads_rights_the_way_the_doctor_row_does(monkeypatch):
    """One answer (``_rights``) for the window's red line and ``--doctor``'s row."""
    none, caps = "CapEff:\t0000000000000000\n", "CapEff:\t0000008000003000\n"   # bits 12, 13, 39
    check("root", capture_backend._rights(0, "/", none) == "root")
    check("the three capabilities", capture_backend._rights(1000, "/", caps).startswith("CAP_BPF"))
    check("neither", capture_backend._rights(1000, "/", none) is None)
    check("two of three is not enough",
          capture_backend._rights(1000, "/", "CapEff:\t0000000000003000\n") is None)
    real = capture_backend._rights
    for status, euid, expected in ((none, 0, True), (none, 1000, False), (caps, 1000, True)):
        monkeypatch.setattr(capture_backend, "_euid", lambda e=euid: e)
        monkeypatch.setattr(capture_backend, "_rights", lambda e, r, s, st=status: real(e, r, st))
        check(f"euid {euid}, {status.strip()}: has_capture_rights is {expected}",
              EBPFDivertBackend.has_capture_rights() is expected)
        row = capture_backend._privileges_row(euid, "/", status)
        check("and the doctor row agrees", (row[1] == "ok") is expected, f"({row})")
    check("the note for a window that can capture",
          EBPFDivertBackend.startup_note(True) == "log.ebpf_note_experimental")
    check("and for one that cannot", EBPFDivertBackend.startup_note(False) == "log.ebpf_note_root")
    check("its own banner", EBPFDivertBackend.rights_banner() == "warn.ebpf_not_root")


def _rows(**kw):
    return {row[0]: row for row in EBPFDivertBackend.doctor_rows(**kw)}


def test_the_linux_doctor_rows_say_what_is_missing_and_fail_what_stops_a_capture(monkeypatch,
                                                                                 tmp_path):
    """Each row without which a capture cannot start is a ``fail``, as on Windows
    (owner, 2026-10-20). It was a ``warn``, and the Diagnostics tab said "Nothing here
    stops a session from starting" under "a capture needs sudo"."""
    monkeypatch.setitem(sys.modules, "pydivert", _ebpf_pydivert()[0])
    (tmp_path / "sys" / "kernel" / "btf").mkdir(parents=True)
    (tmp_path / "sys" / "kernel" / "btf" / "vmlinux").write_bytes(b"")
    ready = _rows(release="6.8.0-1064-azure", root=str(tmp_path), euid=0)
    check("a ready machine: kernel, BTF, root and pydivert all ok",
          [ready[n][1] for n in ("kernel", "btf", "privileges", "pydivert")] == ["ok"] * 4,
          f"({ready})")
    check("and it names the eBPFDivert version", "0.0.5" in ready["pydivert"][2])

    caps = (1 << 12) | (1 << 13) | (1 << 39)
    by_caps = _rows(release="6.8.0", root=str(tmp_path), euid=1000,
                    status="CapEff:\t%016x\n" % caps)
    check("not root, but CAP_BPF + CAP_NET_ADMIN + CAP_NET_RAW: ok", by_caps["privileges"][1] == "ok")

    monkeypatch.setitem(sys.modules, "pydivert", _ebpf_pydivert(lib=False)[0])
    bare = _rows(release="5.4.0-42-generic", root=str(tmp_path / "nothing"), euid=1000,
                 status="CapEff:\t0000000000000000\n")
    check("an old kernel, no BTF, no rights, no library: each one fails",
          [bare[n][1] for n in ("kernel", "btf", "privileges", "pydivert")] == ["fail"] * 4,
          f"({bare})")
    check("and says what to do", "5.10" in bare["kernel"][2] and "sudo" in bare["privileges"][2]
          and "reinstall" in bare["pydivert"][2], f"({bare})")
    check("each in the words Windows uses for it",
          all("cannot start" in bare[n][2] for n in ("kernel", "btf", "privileges")), f"({bare})")
    monkeypatch.setitem(sys.modules, "pydivert", None)
    gone = _rows(release="6.8.0", root=str(tmp_path), euid=0)
    check("no pydivert: a failure with the install command", gone["pydivert"][1] == "fail"
          and "pip install pydivert" in gone["pydivert"][2], f"({gone['pydivert']})")
    check("a ready machine fails nothing, root or the three capabilities",
          all(row[1] == "ok" for rows in (ready, by_caps) for row in rows.values()))


def test_doctor_off_windows_takes_the_linux_backends_rows(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pydivert", _ebpf_pydivert()[0])
    # A ready machine has BTF. Without the file this test's "healthy" verdict rested
    # on a missing-BTF row being only a warning - which is what it no longer is.
    (tmp_path / "sys" / "kernel" / "btf").mkdir(parents=True)
    (tmp_path / "sys" / "kernel" / "btf" / "vmlinux").write_bytes(b"")

    class _Linux(EBPFDivertBackend):
        @staticmethod
        def doctor_rows():
            return EBPFDivertBackend.doctor_rows(release="6.8.0", root=str(tmp_path), euid=0)
    monkeypatch.setattr(capture_backend, "current", lambda: _Linux())
    monkeypatch.setattr(driver, "is_windows", lambda: False)
    ok, checks = driver.doctor()
    names = [c[0] for c in checks]
    platform_row = next(c for c in checks if c[0] == "platform")
    check("the platform row says Linux capture is experimental",
          "experimental" in platform_row[2] and platform_row[1] == "warn", f"({platform_row})")
    check("and does not tell root to use sudo", "sudo" not in platform_row[2], f"({platform_row})")
    check("the Linux rows follow", {"kernel", "btf", "privileges", "pydivert"} <= set(names),
          f"({names})")
    check("and nothing on the Windows path is asked", "windivert driver" not in names)
    check("a ready machine as root: the verdict is healthy (the platform warns only)", ok)

    class _NotRoot(EBPFDivertBackend):
        @staticmethod
        def doctor_rows():
            return EBPFDivertBackend.doctor_rows(release="6.8.0", root=str(tmp_path), euid=1000,
                                                 status="CapEff:\t0000000000000000\n")
    monkeypatch.setattr(capture_backend, "current", lambda: _NotRoot())
    ok, checks = driver.doctor()
    check("without root the verdict says a capture cannot start, as unelevated Windows", not ok)


# -- the session's overload counters (driverwait.watch_overflow) ------------------ #
class _CountingBackend(_FakeBackend):
    """A backend whose driver counts what it let past and dropped, as eBPFDivert does."""

    TEXTS = EBPFDivertBackend.TEXTS
    counts_overload = True

    def __init__(self, readings):
        super().__init__()
        self.readings = list(readings)

    def text(self, what):
        return self.TEXTS[what]

    def overload_counters(self, divert):
        return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]


def _counts(bypassed, dropped):
    return {"bypassed": bypassed, "dropped": dropped}


def test_an_overloaded_driver_is_said_once_per_window_and_totalled_at_stop(monkeypatch):
    backend = _CountingBackend([_counts(0, 0), _counts(5, 1), _counts(9, 1), _counts(9, 1)])
    monkeypatch.setattr(capture_backend, "current", lambda: backend)
    lines, events = [], []
    wait = DriverWait(lines.append, lambda *a: events.append(a))
    wait.begin()
    wait.watch_overflow(object(), 100.0)                  # the base: nothing yet
    check("nothing let past, nothing said", not lines and not events)
    wait.watch_overflow(object(), 101.0)
    check("the first growth is said, with both numbers",
          len(lines) == 1 and "5" in lines[0] and "1" in lines[0], f"({lines})")
    check("and reaches the event log once", events == [("WARN", "events.ebpf_overflow")], f"({events})")
    wait.watch_overflow(object(), 101.0 + WARN_S / 2)
    check("growth inside the window is not said again", len(lines) == 1, f"({lines})")
    wait.watch_overflow(object(), 102.0 + WARN_S)
    check("no growth, no line, window or not", len(lines) == 1, f"({lines})")
    check("the totals follow the driver", (wait.bypassed, wait.dropped) == (9, 1))
    wait.say_overflow_total()
    check("STOP says the session's totals", len(lines) == 2 and "9" in lines[1], f"({lines})")


def test_a_stats_reset_counts_from_the_drivers_last_reading_not_from_zero(monkeypatch):
    backend = _CountingBackend([_counts(10, 2), _counts(15, 2)])
    monkeypatch.setattr(capture_backend, "current", lambda: backend)
    wait = DriverWait(lambda *_a: None, lambda *_a: None)
    wait.begin()
    wait.watch_overflow(object(), 1.0)
    wait.reset()
    wait.watch_overflow(object(), 2.0)
    check("after a reset, only what came after it", (wait.bypassed, wait.dropped) == (5, 0),
          f"({wait.bypassed}, {wait.dropped})")


def test_a_driver_that_counts_nothing_says_nothing(monkeypatch):
    lines = []
    monkeypatch.setattr(capture_backend, "current", lambda: WinDivertBackend())
    wait = DriverWait(lines.append, lambda *_a: None)
    wait.begin()
    wait.watch_overflow(object(), 1.0)
    wait.say_overflow_total()
    check("Windows: no counters asked, no line",
          not lines and (wait.bypassed, wait.dropped) == (0, 0))


class _QueueDivert(FakeDivert):
    """A divert that answers the driver-queue parameters, as a real handle does."""

    def get_param(self, number):
        return (4096, 2000, 4 << 20)[number]


def test_the_engine_watches_the_drivers_counters_and_says_its_own_words(monkeypatch):
    from beantester.i18n import T
    monkeypatch.setitem(sys.modules, "pydivert", _refusing_pydivert())
    monkeypatch.setattr(crashlog, "arm_for_capture", lambda: None)
    backend = _CountingBackend([_counts(0, 0), _counts(4, 0)])
    backend.divert = _QueueDivert([])
    monkeypatch.setattr(capture_backend, "current", lambda: backend)
    lines = []
    overflow = T("log.ebpf_overflow", bypassed=4, dropped=0)
    eng = BeanEngine(log_fn=lines.append)
    eng._ports = _FakePorts()
    eng.start("false")
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and overflow not in lines:
            time.sleep(0.02)
    finally:
        eng.stop()
    queue_line = T("log.ebpf_driver_queue", n=4096, t=2000, kb=4096, warn="50")
    check("the START line is the Linux backend's text", queue_line in lines, f"({lines[:6]})")
    check("the watchdog asked the counters and said so", overflow in lines, f"({lines})")
    total = T("log.ebpf_overflow_total", bypassed=4, dropped=0)
    check("and STOP said the total", total in lines, f"({lines[-4:]})")


def test_the_drivers_counters_reach_the_statistics_only_where_it_counts(monkeypatch):
    """The snapshot behind the Statistics page, the CSV and the JSON counters carries
    the driver's two numbers on a backend that counts them, and nothing new on one
    that does not (Windows: its snapshot is what it was). The repro report follows."""
    from beantester.repro import build_repro_report
    from beantester.settings import DEFAULT_SETTINGS
    keys = capture_backend.OVERLOAD_STATS
    counting = _CountingBackend([_counts(0, 0)])
    monkeypatch.setattr(capture_backend, "current", lambda: counting)
    eng = BeanEngine(log_fn=lambda *_: None)
    eng._driver_wait.bypassed, eng._driver_wait.dropped = 7, 3
    snap = eng.stats_snapshot()
    check("the driver's counters, under their names", [snap.get(k) for k in keys] == [7, 3],
          f"({ {k: snap.get(k) for k in keys} })")
    metrics = build_repro_report(eng, dict(DEFAULT_SETTINGS))["metrics"]
    check("and in the repro report", [metrics.get(k) for k in keys] == [7, 3], f"({metrics})")
    monkeypatch.setattr(capture_backend, "current", lambda: _FakeBackend())
    snap = eng.stats_snapshot()
    check("a driver that counts nothing adds nothing", not set(keys) & set(snap), f"({sorted(snap)})")
    metrics = build_repro_report(eng, dict(DEFAULT_SETTINGS))["metrics"]
    check("nor to the report", not set(keys) & set(metrics))
    check("Windows counts nothing of the kind", WinDivertBackend.counts_overload is False
          and EBPFDivertBackend.counts_overload is True)
