"""The proxy this account and this machine are set to use - read, never used.

Three places a program on Windows takes a proxy from, each read on its own so one
that fails costs only its own part:

* the account's proxy settings (Settings > Network > Proxy), for the connection in
  use, through ``WinHttpGetIEProxyConfigForCurrentUser`` - Microsoft Learn: the
  settings "for the current active network connection (for example, LAN, dial-up,
  or VPN connection)", read "without calling into WinInet.dll";
* the machine's WinHTTP proxy (``netsh winhttp set proxy``), which services and some
  programs use, through ``WinHttpGetDefaultProxyConfiguration`` - Learn: it
  "retrieves the configuration specified in the registry";
* the ``HTTP_PROXY`` family of environment variables, which curl, git, Python, Node
  and Go read - from the registry, where a program started from now on gets them,
  not from this process's own environment (inherited when it started).

Nothing here sends anything. Measured 2026-10-14 on a Windows Server 2025 VM with
Windows Filtering Platform auditing: 1000 reads of both calls, with automatic
detection, a setup script and a manual proxy all set, raised no event from the
reading program and none towards the script's host, while one UDP datagram from the
same program did. The calls that DO
send - discovery, script download, requests - are watched by name in
``tests/test_no_telemetry.py`` (``WIRE_FUNCTIONS``) and none is called here.

Why the structures are written with fixed-width integers: the same as
``adapters.py`` - ``wintypes`` and ``c_wchar_p`` change size and encoding on Linux,
where the walk is tested against a fake, so text is read as UTF-16 by hand.
"""
import ctypes
import struct
import sys
from typing import NamedTuple

from . import crashlog

ERROR_FILE_NOT_FOUND = 2        # Learn: "No Internet Explorer proxy settings can be found."
WINHTTP_ACCESS_TYPE_NAMED_PROXY = 3

# A string the system hands over is read up to its NUL or this many characters. A
# company's bypass list can run to thousands of characters; this is far above that.
MAX_TEXT = 32768

# The variables, and where the registry keeps them for programs started from now on.
# A user's value replaces the machine's for the same name, as Windows builds a new
# program's environment.
ENV_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
ENV_PLACES = (("user", "HKEY_CURRENT_USER", "Environment"),
              ("machine", "HKEY_LOCAL_MACHINE",
               "SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment"))


class _IEConfig(ctypes.Structure):
    """``WINHTTP_CURRENT_USER_IE_PROXY_CONFIG`` (Learn): BOOL and three LPWSTR."""
    _fields_ = [("fAutoDetect", ctypes.c_int32), ("lpszAutoConfigUrl", ctypes.c_void_p),
                ("lpszProxy", ctypes.c_void_p), ("lpszProxyBypass", ctypes.c_void_p)]


class _ProxyInfo(ctypes.Structure):
    """``WINHTTP_PROXY_INFO`` (Learn): DWORD and two LPWSTR."""
    _fields_ = [("dwAccessType", ctypes.c_uint32), ("lpszProxy", ctypes.c_void_p),
                ("lpszProxyBypass", ctypes.c_void_p)]


class UserProxy(NamedTuple):
    """What the account's settings turn on. Learn's structure carries a string only
    for what is switched on (measured: a proxy turned off keeps its address in the
    registry and the call does not return it)."""
    detect: bool                # "Automatically detect settings"
    script: str                 # "Use setup script": its address
    server: str                 # "Use a proxy server": the list, as the system holds it
    bypass: str


class MachineProxy(NamedTuple):
    server: str                 # "" = direct access
    bypass: str


class Variable(NamedTuple):
    name: str
    value: str
    scope: str                  # "user" or "machine"
    replaces: bool = False      # a user value over a machine value of the same name


class Reading(NamedTuple):
    user: UserProxy | None
    user_error: str
    machine: MachineProxy | None
    machine_error: str
    env: tuple                  # of Variable, in ENV_NAMES order
    env_error: str


NOTHING = UserProxy(False, "", "", "")


def _wide(pointer, limit=None):
    """The NUL-terminated UTF-16 string at ``pointer``, at most ``limit`` characters.

    The bound is read at the call (``MAX_TEXT`` when None): a default argument would
    keep the value the constant had when the module loaded.
    """
    if not pointer:
        return ""
    cells = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint16))
    out = []
    for i in range(MAX_TEXT if limit is None else limit):
        value = cells[i]
        if not value:
            break
        out.append(value)
    return struct.pack(f"<{len(out)}H", *out).decode("utf-16-le", errors="replace")


# -- the binding --------------------------------------------------------------------- #
def _winhttp():
    """winhttp with the prototypes of the two calls made here; None off Windows."""
    if not sys.platform.startswith("win"):
        return None
    return _declared(ctypes.WinDLL("winhttp.dll", use_last_error=True))  # pragma: no cover - Windows only (the DLL)


def _kernel32():
    """kernel32 for ``GlobalFree`` (Learn: how both calls' strings are freed)."""
    if not sys.platform.startswith("win"):
        return None
    lib = ctypes.WinDLL("kernel32.dll")  # pragma: no cover - Windows only (the DLL)
    lib.GlobalFree.argtypes = [ctypes.c_void_p]  # pragma: no cover - Windows only
    lib.GlobalFree.restype = ctypes.c_void_p  # pragma: no cover - Windows only
    return lib  # pragma: no cover - Windows only


def _declared(lib):
    """``lib`` with the prototypes of the two reads (Microsoft Learn)."""
    lib.WinHttpGetIEProxyConfigForCurrentUser.argtypes = [ctypes.POINTER(_IEConfig)]
    lib.WinHttpGetIEProxyConfigForCurrentUser.restype = ctypes.c_int32
    lib.WinHttpGetDefaultProxyConfiguration.argtypes = [ctypes.POINTER(_ProxyInfo)]
    lib.WinHttpGetDefaultProxyConfiguration.restype = ctypes.c_int32
    return lib


def _registry_reader():  # pragma: no cover - Windows only (winreg)
    """``(root_name, path, names) -> {name: value}`` over winreg; None off Windows."""
    if not sys.platform.startswith("win"):
        return None
    import winreg

    def read(root_name, path, names):
        found = {}
        try:
            key = winreg.OpenKey(getattr(winreg, root_name), path)
        except FileNotFoundError:
            return found
        with key:
            for name in names:
                try:
                    value, kind = winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    continue
                if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and value:
                    found[name] = value
        return found
    return read


class _Native:
    """The three reads. Everything is injectable, so they run in tests anywhere."""

    def __init__(self, winhttp=None, kernel32=None, last_error=None, registry=None):
        self.winhttp = winhttp if winhttp is not None else _winhttp()
        self.kernel32 = kernel32 if kernel32 is not None else _kernel32()
        # get_last_error exists on Windows only; elsewhere a fake brings its own.
        self.last_error = last_error or getattr(ctypes, "get_last_error", lambda: 0)
        self.registry = registry if registry is not None else _registry_reader()

    def _take(self, pointers):
        """Each string read, then EVERY non-NULL one freed exactly once - also when
        reading one of them fails."""
        try:
            return [_wide(p) for p in pointers]
        finally:
            for pointer in pointers:
                if pointer:
                    self.kernel32.GlobalFree(pointer)

    def user(self):
        config = _IEConfig()
        if not self.winhttp.WinHttpGetIEProxyConfigForCurrentUser(ctypes.byref(config)):
            code = self.last_error()
            if code == ERROR_FILE_NOT_FOUND:
                return NOTHING
            raise OSError(code, f"WinHttpGetIEProxyConfigForCurrentUser failed: {code}")
        script, server, bypass = self._take(
            [config.lpszAutoConfigUrl, config.lpszProxy, config.lpszProxyBypass])
        return UserProxy(bool(config.fAutoDetect), script, server, bypass)

    def machine(self):
        info = _ProxyInfo()
        if not self.winhttp.WinHttpGetDefaultProxyConfiguration(ctypes.byref(info)):
            code = self.last_error()
            raise OSError(code, f"WinHttpGetDefaultProxyConfiguration failed: {code}")
        server, bypass = self._take([info.lpszProxy, info.lpszProxyBypass])
        if info.dwAccessType != WINHTTP_ACCESS_TYPE_NAMED_PROXY:
            return MachineProxy("", "")
        return MachineProxy(server, bypass)

    def env(self):
        found = {scope: self.registry(root, path, ENV_NAMES) for scope, root, path in ENV_PLACES}
        out = []
        for name in ENV_NAMES:
            # Value names in the registry ignore case, as the variables do.
            user, machine = (_lookup(found[scope], name) for scope in ("user", "machine"))
            if user is not None:
                out.append(Variable(name, user, "user", replaces=machine is not None))
            elif machine is not None:
                out.append(Variable(name, machine, "machine"))
        return tuple(out)


def _lookup(values, name):
    for key, value in values.items():
        if key.upper() == name:
            return value
    return None


def supported():
    """Proxy settings are read on Windows only, like the adapters they sit beside."""
    return sys.platform.startswith("win")


def _part(read, area):
    """``(value, "")`` or ``(None, why)``: one part that fails costs only itself."""
    try:
        return read(), ""
    except Exception as exc:
        crashlog.note(exc, area)
        return None, f"{type(exc).__name__}: {exc}"


def read(native=None):
    """The three parts, each with its own error. Runs on a worker; never raises - the
    adapter list is read in the same job, and a proxy that cannot be read must not
    cost it (a library that will not load included)."""
    if native is None:
        native, why = _part(_Native, "proxy")
        if native is None:
            return Reading(None, why, None, why, (), why)
    user, user_error = _part(native.user, "proxy.user")
    machine, machine_error = _part(native.machine, "proxy.machine")
    env, env_error = _part(native.env, "proxy.env")
    return Reading(user, user_error, machine, machine_error, env or (), env_error)
