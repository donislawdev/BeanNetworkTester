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
import sys

from . import winenv


class WinDivertBackend:
    """Windows: WinDivert, through ``pydivert.WinDivert``."""

    name = "windivert"

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


_WINDIVERT = WinDivertBackend()


def select(platform):
    """The backend for ``platform`` (a ``sys.platform`` value).

    WinDivert for every platform: it is the only capture driver this program
    drives, and off Windows its path fails exactly where it always has (no
    pydivert to import, no DLL to load).
    """
    return _WINDIVERT


_CURRENT = select(sys.platform)


def current():
    """This process's backend, chosen once at import."""
    return _CURRENT
