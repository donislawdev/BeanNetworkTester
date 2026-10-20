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
import sys
import threading
import time
import types

from beantester import capture_backend, crashlog, driver, filters, socketwatch, winenv
from beantester.capture_backend import WinDivertBackend
from beantester.driverwait import DriverWait
from beantester.engine import BeanEngine
from fakes import FakeDivert, check


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


# -- the choice ---------------------------------------------------------------- #
def test_windows_gets_the_windivert_backend():
    check("win32 -> WinDivert", isinstance(capture_backend.select("win32"), WinDivertBackend))
    check("a platform with no capture driver keeps the WinDivert path it always had",
          isinstance(capture_backend.select("darwin"), WinDivertBackend))
    check("this process's backend is the one its platform selects",
          capture_backend.current() is capture_backend.select(sys.platform))


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
