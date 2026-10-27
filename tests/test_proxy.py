"""The proxy reads of the Tools tab (``beantester/proxy.py``): two WinHTTP calls, the
strings they hand over (and must have freed), and the proxy variables in the registry.

The fake sits one level below the module: a ``winhttp`` that fills the caller's
structure with pointers to real UTF-16 strings, and a ``kernel32`` whose GlobalFree
records what it was given - so the walk, the reading and the freeing run on the
Linux runner too. That the layout is Windows' own is the live test at the bottom.
"""
import ctypes
import sys

import pytest

from beantester import crashlog, proxy
from fakes import check


class FakeWinHttp:
    """Answers the two reads the way winhttp does: strings it allocated, or a failure."""

    def __init__(self, user=None, machine=None, user_rc=None, machine_rc=None, access=3):
        self.user = user            # (detect, script, server, bypass); None = NULL strings
        self.machine = machine      # (server, bypass)
        self.user_rc = user_rc      # an error code to fail with
        self.machine_rc = machine_rc
        self.access = access
        self.handed = {}            # address -> buffer, kept alive until freed
        self.error = [0]

    def _string(self, text):
        if text is None:
            return None
        buffer = ctypes.create_string_buffer(text.encode("utf-16-le") + b"\0\0")
        self.handed[ctypes.addressof(buffer)] = buffer
        return ctypes.addressof(buffer)

    def WinHttpGetIEProxyConfigForCurrentUser(self, ref):
        if self.user_rc is not None:
            self.error[0] = self.user_rc
            return 0
        config = ref._obj
        detect, script, server, bypass = self.user or (False, None, None, None)
        config.fAutoDetect = 1 if detect else 0
        config.lpszAutoConfigUrl = self._string(script)
        config.lpszProxy = self._string(server)
        config.lpszProxyBypass = self._string(bypass)
        return 1

    def WinHttpGetDefaultProxyConfiguration(self, ref):
        if self.machine_rc is not None:
            self.error[0] = self.machine_rc
            return 0
        info = ref._obj
        server, bypass = self.machine or (None, None)
        info.dwAccessType = self.access
        info.lpszProxy = self._string(server)
        info.lpszProxyBypass = self._string(bypass)
        return 1


class FakeKernel32:
    def __init__(self, winhttp):
        self.winhttp = winhttp
        self.freed = []

    def GlobalFree(self, pointer):
        assert pointer in self.winhttp.handed, f"freed something winhttp never handed out: {pointer}"
        self.freed.append(pointer)
        return None


def _native(winhttp=None, registry=None):
    winhttp = winhttp or FakeWinHttp()
    kernel32 = FakeKernel32(winhttp)
    native = proxy._Native(winhttp=winhttp, kernel32=kernel32,
                           last_error=lambda: winhttp.error[0],
                           registry=registry or (lambda root, path, names: {}))
    return native, kernel32


def test_the_account_settings_are_read_and_every_string_freed_once():
    winhttp = FakeWinHttp(user=(True, "http://192.0.2.20/proxy.pac",
                                "http=192.0.2.10:8080;https=proxy.example.com:8443",
                                "<local>;*.example.com"))
    native, kernel32 = _native(winhttp)
    got = native.user()
    check("every field, read as UTF-16", got == proxy.UserProxy(
        True, "http://192.0.2.20/proxy.pac", "http=192.0.2.10:8080;https=proxy.example.com:8443",
        "<local>;*.example.com"), f"({got})")
    check("each string freed exactly once", sorted(kernel32.freed) == sorted(winhttp.handed),
          f"({len(kernel32.freed)} of {len(winhttp.handed)})")


def test_a_null_string_is_empty_and_not_freed():
    winhttp = FakeWinHttp(user=(True, None, None, None))
    native, kernel32 = _native(winhttp)
    check("only detection on", native.user() == proxy.UserProxy(True, "", "", ""))
    check("nothing to free", kernel32.freed == [], f"({kernel32.freed})")


def test_no_settings_at_all_are_nothing_and_another_failure_is_one():
    """Learn: ERROR_FILE_NOT_FOUND = "No Internet Explorer proxy settings can be found"."""
    native, _ = _native(FakeWinHttp(user_rc=proxy.ERROR_FILE_NOT_FOUND))
    check("2: nothing set, not a failure", native.user() == proxy.NOTHING)
    native, _ = _native(FakeWinHttp(user_rc=12004))
    with pytest.raises(OSError) as caught:
        native.user()
    check("anything else fails, with its code", "12004" in str(caught.value), f"({caught.value})")


def test_a_string_that_cannot_be_read_is_still_freed(monkeypatch):
    winhttp = FakeWinHttp(user=(False, "http://192.0.2.20/x.pac", "192.0.2.10:8080", "<local>"))
    native, kernel32 = _native(winhttp)
    real = proxy._wide
    seen = []

    def breaks_on_the_second(pointer, limit=None):
        seen.append(pointer)
        if len(seen) == 2:
            raise ValueError("the second string broke on purpose")
        return real(pointer, limit)
    monkeypatch.setattr(proxy, "_wide", breaks_on_the_second)
    with pytest.raises(ValueError):
        native.user()
    check("all three freed anyway", sorted(kernel32.freed) == sorted(winhttp.handed),
          f"({len(kernel32.freed)} of {len(winhttp.handed)})")


def test_the_machine_proxy_is_named_or_direct():
    native, kernel32 = _native(FakeWinHttp(machine=("192.0.2.30:3128", "<local>")))
    check("a named proxy", native.machine() == proxy.MachineProxy("192.0.2.30:3128", "<local>"))
    winhttp = FakeWinHttp(machine=("stale:1", "stale"), access=1)
    native, kernel32 = _native(winhttp)
    check("NO_PROXY reads as direct, whatever strings came with it",
          native.machine() == proxy.MachineProxy("", ""))
    check("and those strings are freed", sorted(kernel32.freed) == sorted(winhttp.handed))
    native, _ = _native(FakeWinHttp(machine_rc=8))
    with pytest.raises(OSError):
        native.machine()


def test_the_variables_come_from_the_registry_a_users_over_the_machines():
    places = {"HKEY_CURRENT_USER": {"http_proxy": "http://user:secret@192.0.2.40:8080",
                                    "NO_PROXY": "localhost"},
              "HKEY_LOCAL_MACHINE": {"HTTP_PROXY": "http://192.0.2.41:8080",
                                     "HTTPS_PROXY": "http://192.0.2.42:8443"}}
    asked = []

    def registry(root, path, names):
        asked.append((root, path, tuple(names)))
        return places[root]
    native, _ = _native(registry=registry)
    got = native.env()
    check("in a fixed order, the user's value over the machine's, names in any case",
          got == (proxy.Variable("HTTP_PROXY", "http://user:secret@192.0.2.40:8080", "user",
                                 replaces=True),
                  proxy.Variable("HTTPS_PROXY", "http://192.0.2.42:8443", "machine"),
                  proxy.Variable("NO_PROXY", "localhost", "user")), f"({got})")
    check("where Windows keeps them for programs started from now on",
          [a[:2] for a in asked] == [(root, path) for _scope, root, path in proxy.ENV_PLACES],
          f"({asked})")


def test_one_part_that_fails_costs_only_itself(monkeypatch):
    notes = []
    monkeypatch.setattr(crashlog, "note", lambda exc, area, *a: notes.append(area))

    def broken(root, path, names):
        raise PermissionError("the registry refused on purpose")
    native, _ = _native(FakeWinHttp(user=(True, None, None, None), machine=(None, None),
                                    access=1), registry=broken)
    reading = proxy.read(native)
    check("the account's settings are there", reading.user == proxy.UserProxy(True, "", "", ""))
    check("so is the machine's", reading.machine == proxy.MachineProxy("", ""))
    check("the variables say why they are not",
          reading.env == () and "refused on purpose" in reading.env_error, f"({reading})")
    check("and the failure is recorded", notes == ["proxy.env"], f"({notes})")


def test_a_binding_that_will_not_load_costs_the_proxy_and_raises_nothing(monkeypatch):
    """The adapter list is read in the same job: the proxy must never cost it. Windows'
    reader on any runner (the platform stood in: on Linux ``read`` takes ``_Linux``)."""
    monkeypatch.setattr(crashlog, "note", lambda *a: None)

    def will_not_load(*_a, **_k):
        raise OSError("winhttp.dll did not load, on purpose")
    monkeypatch.setattr(proxy, "_Native", will_not_load)
    monkeypatch.setattr(proxy.sys, "platform", "win32")
    reading = proxy.read()
    check("three parts, each saying why", reading.user is None and reading.machine is None
          and all("on purpose" in e for e in (reading.user_error, reading.machine_error,
                                               reading.env_error)), f"({reading})")
    # Linux's reader the same way: its two parts say why, the part it has not is not a failure.
    monkeypatch.setattr(proxy, "_Linux", will_not_load)
    monkeypatch.setattr(proxy.sys, "platform", "linux")
    reading = proxy.read()
    check("Linux: the desktop and the variables say why, no WinHTTP part",
          (reading.system, reading.machine, reading.machine_error) == ("linux", None, "")
          and "on purpose" in reading.user_error and "on purpose" in reading.env_error,
          f"({reading})")


def test_a_text_is_read_up_to_its_bound(monkeypatch):
    winhttp = FakeWinHttp(user=(False, None, "Połączenie:8080", None))
    native, _ = _native(winhttp)
    check("UTF-16 outside ASCII comes back whole", native.user().server == "Połączenie:8080")
    monkeypatch.setattr(proxy, "MAX_TEXT", 4)
    native, _ = _native(FakeWinHttp(user=(False, None, "192.0.2.10:8080", None)))
    check("cut at the bound, never read past it", native.user().server == "192.",
          f"({native.user().server!r})")


def test_both_reads_are_declared_with_their_prototypes():
    import types
    lib = types.SimpleNamespace(WinHttpGetIEProxyConfigForCurrentUser=types.SimpleNamespace(),
                                WinHttpGetDefaultProxyConfiguration=types.SimpleNamespace())
    proxy._declared(lib)
    check("each takes a pointer to its structure", (
        lib.WinHttpGetIEProxyConfigForCurrentUser.argtypes == [ctypes.POINTER(proxy._IEConfig)]
        and lib.WinHttpGetDefaultProxyConfiguration.argtypes
        == [ctypes.POINTER(proxy._ProxyInfo)]))
    check("and answers a 32-bit BOOL", lib.WinHttpGetIEProxyConfigForCurrentUser.restype
          is lib.WinHttpGetDefaultProxyConfiguration.restype is ctypes.c_int32)


def test_the_layout_is_the_one_windows_writes():
    """Learn's two structures on a 64-bit process: a BOOL or DWORD, padding, pointers."""
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        pytest.skip("the sizes are for a 64-bit process")
    sizes = (ctypes.sizeof(proxy._IEConfig), ctypes.sizeof(proxy._ProxyInfo))
    check("32 and 24 bytes", sizes == (32, 24), f"({sizes})")
    check("the pointers start after the padding",
          (proxy._IEConfig.lpszAutoConfigUrl.offset, proxy._ProxyInfo.lpszProxy.offset) == (8, 8))


def test_off_windows_nothing_is_loaded():
    if sys.platform.startswith("win"):
        pytest.skip("the Windows branch is the live test below")
    check("no library and no registry",
          (proxy._winhttp(), proxy._kernel32(), proxy._registry_reader()) == (None, None, None))
    check("supported on Linux only, of the rest", proxy.supported() == sys.platform.startswith("linux"))


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="the proxy settings are Windows'")
def test_the_real_reads_answer_on_this_machine():  # pragma: no cover - Windows only
    """Every part reads on a real Windows, whatever this machine's settings are."""
    reading = proxy.read()
    check("the account's settings", reading.user is not None, f"({reading.user_error})")
    check("the machine's WinHTTP proxy", reading.machine is not None,
          f"({reading.machine_error})")
    check("the variables", reading.env_error == "", f"({reading.env_error})")
