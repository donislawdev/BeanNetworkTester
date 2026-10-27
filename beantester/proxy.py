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

On Linux (``_Linux``) there is no one place either, and two are read:

* the desktop's proxy settings (GNOME Settings > Network > Proxy), which Firefox,
  Chrome and GNOME's own programs follow, through ``gsettings`` - run as the person
  whose desktop it is: under ``sudo`` as root it reads ROOT's settings, which say
  "none" (measured 2026-10-27), so it is started as the person who typed ``sudo``
  (``setpriv``). It is the one program this tool starts, and it sends nothing:
  traced the same day, its only sockets were local ones to the system's account
  database (``internal_tools`` probes ``2026-10-27-linux-adapters``);
* the proxy variables from the files a program started from now on gets them from:
  ``/etc/environment`` and the ``environment.d`` directories for every account, the
  person's ``~/.config/environment.d`` for theirs. A shell's own startup files
  (``~/.bashrc``, ``/etc/profile.d``) are scripts and are not read. The names are
  case-sensitive there, and curl reads only the lowercase ``http_proxy``.

A machine-wide proxy for services, as WinHTTP is, Linux does not have: that part of
the reading stays empty without an error, which says "not on this system".
"""
import ctypes
import os
import re
import shutil
import struct
import subprocess
import sys
from typing import NamedTuple

from . import crashlog, paths

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
    """Each part, and why it could not be read. A part that is ``None`` with no
    error is not on this system (Linux has no WinHTTP; a server has no desktop)."""
    user: UserProxy | None
    user_error: str
    machine: MachineProxy | None
    machine_error: str
    env: tuple                  # of Variable, in ENV_NAMES order
    env_error: str
    system: str = "windows"     # whose places these are: "windows" or "linux"


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
    SYSTEM = "windows"
    HAS_MACHINE = True

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


# -- Linux ------------------------------------------------------------------------- #
GNOME_SCHEMA = "org.gnome.system.proxy"
GNOME_SCHEMES = ("http", "https", "ftp", "socks")
# gsettings prints the proxy's account and password with the rest; they are dropped
# as the lines are read and never reach a Reading.
GNOME_SECRETS = frozenset({"authentication-user", "authentication-password"})
GSETTINGS_WAIT_S = 2.0          # measured: 26 ms typical, 273 ms the first time
CHILD_PATH = "/usr/bin:/bin"
CHILD_LOCALE = "C.UTF-8"        # UTF-8 text, and gsettings' own messages in English
ENV_NAMES_LINUX = ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY",
                   "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY")
ENV_FILE = "etc/environment"    # pam_env: every account, at login
# environment.d(5), the lowest first: a file of the same name further down replaces
# one above, and the person's own directory comes last.
ENV_DIRS = ("usr/lib/environment.d", "usr/local/lib/environment.d", "run/environment.d",
            "etc/environment.d")
USER_ENV_DIR = os.path.join(".config", "environment.d")
MAX_ENV_FILES = 256
_ASSIGNMENT = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
_NUMBER = re.compile(r"-?[0-9]+")
_LOOK_UP = object()             # _Linux's person: whoever paths.invoking_user() names


def _string(text):
    """A quoted GVariant string at the start of ``text``, and what follows it."""
    quote, out, i = text[0], [], 1
    while i < len(text):
        char = text[i]
        if char == quote:
            return "".join(out), text[i + 1:]
        if char == "\\" and i + 1 < len(text):
            code = text[i + 1]
            width = {"u": 4, "U": 8}.get(code)
            if width:
                out.append(chr(int(text[i + 2:i + 2 + width], 16)))
                i += 2 + width
            else:
                out.append(_ESCAPES.get(code, code))
                i += 2
            continue
        out.append(char)
        i += 1
    raise ValueError("gsettings: a string without its closing quote")


def _array(text):
    items, rest = [], text[1:].lstrip()
    while not rest.startswith("]"):
        value, rest = _value(rest)
        items.append(value)
        rest = rest.lstrip()
        if rest.startswith(","):
            rest = rest[1:].lstrip()
        elif not rest.startswith("]"):
            raise ValueError("gsettings: an array that does not close")
    return items, rest[1:]


def _value(text):
    """One value as ``g_variant_print`` writes it - a string, a number, true or false,
    an array of them - and what follows it."""
    text = text.lstrip()
    if text.startswith("@"):                # a type written before an empty value: @as []
        text = text.split(None, 1)[1] if " " in text else ""
    if text[:1] in ("'", '"'):
        return _string(text)
    if text.startswith("["):
        return _array(text)
    for word, value in (("true", True), ("false", False)):
        if text.startswith(word):
            return value, text[len(word):]
    number = _NUMBER.match(text)
    if number:
        return int(number.group()), text[number.end():]
    raise ValueError(f"gsettings: a value this program does not read: {text[:40]!r}")


def gnome_values(text):
    """``{(schema, key): value}`` from ``gsettings list-recursively``, without the
    proxy's account and password."""
    values = {}
    for line in text.splitlines():
        parts = line.split(" ", 2)
        if len(parts) != 3 or parts[1] in GNOME_SECRETS:
            continue
        value, rest = _value(parts[2])
        if rest.strip():
            raise ValueError(f"gsettings: more after a value: {rest[:40]!r}")
        values[(parts[0], parts[1])] = value
    return values


def _host_port(host, port):
    host = f"[{host}]" if ":" in host else host
    return f"{host}:{port}" if port else host


def gnome_proxy(values):
    """The desktop's settings as the account part, the way Windows' read: automatic
    detection, a setup script, or the servers in Learn's list grammar
    (``http=host:port;socks=host:port``), so the rows, the report and the masking
    read them unchanged."""
    def get(schema, key, default):
        value = values.get((GNOME_SCHEMA + schema, key))
        return default if value is None else value
    mode = get("", "mode", "none")
    if mode == "none":
        return NOTHING
    if mode == "auto":                      # no address: the network is asked (WPAD)
        script = get("", "autoconfig-url", "")
        return UserProxy(not script, script, "", "")
    if mode == "manual":
        servers = [f"{scheme}={_host_port(get('.' + scheme, 'host', ''), get('.' + scheme, 'port', 0))}"
                   for scheme in GNOME_SCHEMES if get("." + scheme, "host", "")]
        return UserProxy(False, "", ";".join(servers), ";".join(get("", "ignore-hosts", [])))
    raise ValueError(f"gsettings: a proxy mode this program does not know: {mode!r}")


def assignments(text):
    """``(name, value)`` of each ``NAME=value`` line, outer quotes taken off; comments
    and anything else skipped. ``${OTHER}`` is shown as written."""
    out = []
    for line in (text or "").splitlines():
        if line.lstrip().startswith("#"):
            continue
        found = _ASSIGNMENT.fullmatch(line.rstrip())
        if not found:
            continue
        value = found.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out.append((found.group(1), value))
    return out


def _run(argv, env):
    """The one program this tool starts: gsettings (the docstring at the top says why,
    and what it was measured to send - nothing). Nothing of this process reaches it -
    not its terminal, its files or its environment - and it may take ``GSETTINGS_WAIT_S``."""
    return subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                          timeout=GSETTINGS_WAIT_S, env=env, check=False)


class _Linux:
    """The desktop's settings and the variables' files. Who is asked - ``person``,
    ``(uid, gid)`` of whoever typed ``sudo`` - how a program is run and found, and
    where the files are are injectable, so this runs in tests anywhere."""
    SYSTEM = "linux"
    HAS_MACHINE = False

    def __init__(self, run=None, which=None, root="/", person=_LOOK_UP, own_uid=None,
                 home=None):
        self.run = run or _run
        self.which = which or shutil.which
        self.root = root
        self.person = paths.invoking_user() if person is _LOOK_UP else person
        # geteuid exists off Windows only; there a test brings its own.
        self.own_uid = own_uid if own_uid is not None else getattr(os, "geteuid", lambda: 0)()
        self.uid = self.person[0] if self.person else self.own_uid
        self.home = home or paths.home_of(self.uid)

    # -- the desktop's settings ---------------------------------------------- #
    def user(self):
        """GNOME's proxy settings; None where there is no GNOME to ask."""
        text = self._gsettings()
        return None if text is None else gnome_proxy(gnome_values(text))

    def _gsettings(self):
        program = self.which("gsettings")
        if not program:
            return None
        if not self.home:
            raise OSError(f"no home directory for the account {self.uid}")
        argv = [program, "list-recursively", GNOME_SCHEMA]
        if self.uid != self.own_uid:
            setpriv = self.which("setpriv")
            if not setpriv:
                raise OSError("setpriv was not found, so the desktop of the person who "
                              "typed sudo cannot be asked")
            argv = [setpriv, f"--reuid={self.person[0]}", f"--regid={self.person[1]}",
                    "--init-groups", *argv]
        done = self.run(argv, {"HOME": self.home, "PATH": CHILD_PATH, "LC_ALL": CHILD_LOCALE})
        said = done.stderr.decode("utf-8", errors="replace")
        # No schema: not a GNOME system. The "memory" backend: GLib has nowhere the
        # desktop keeps its settings, and answers with the defaults.
        if "No such schema" in said or "'memory' GSettings backend" in said:
            return None
        if done.returncode:
            first = said.strip().splitlines()[0] if said.strip() else ""
            raise OSError(f"gsettings answered {done.returncode}: {first}")
        return done.stdout.decode("utf-8", errors="replace")

    # -- the variables ------------------------------------------------------- #
    def env(self):
        values, machine = {}, set()
        sources = [(os.path.join(self.root, ENV_FILE), "machine", None), *self._env_files()]
        for path, scope, owner in sources:
            for name, value in assignments(paths.read_small_file(path, owner=owner)):
                if name not in ENV_NAMES_LINUX:
                    continue
                if scope == "machine":
                    machine.add(name)
                values[name] = Variable(name, value, scope,
                                        replaces=scope == "user" and name in machine)
        return tuple(values[name] for name in ENV_NAMES_LINUX if name in values)

    def _env_files(self):
        chosen = {}
        for directory in ENV_DIRS:
            for name in _conf_names(os.path.join(self.root, directory)):
                chosen[name] = (os.path.join(self.root, directory, name), "machine", None)
        if self.home:
            own = os.path.join(self.home, USER_ENV_DIR)
            for name in _conf_names(own, owner=self.uid):
                chosen[name] = (os.path.join(own, name), "user", self.uid)
        return [chosen[name] for name in sorted(chosen)][:MAX_ENV_FILES]


def _conf_names(directory, owner=None):
    """The ``*.conf`` names in ``directory``; none when it is missing, or - for a
    person's own directory read by root - when it is not theirs."""
    try:
        if owner is not None and os.stat(directory).st_uid != owner:
            return []
        return sorted(n for n in os.listdir(directory) if n.endswith(".conf"))[:MAX_ENV_FILES]
    except (FileNotFoundError, NotADirectoryError):
        return []


def supported():
    """Proxy settings are read on Windows and on Linux, like the adapters they sit beside."""
    return sys.platform.startswith(("win", "linux"))


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
        linux = sys.platform.startswith("linux")
        native, why = _part(_Linux if linux else _Native, "proxy")
        if native is None:
            return Reading(None, why, None, "" if linux else why, (), why,
                           "linux" if linux else "windows")
    # A reader that does not say otherwise has Windows' three places.
    has_machine = getattr(native, "HAS_MACHINE", True)
    user, user_error = _part(native.user, "proxy.user")
    machine, machine_error = (_part(native.machine, "proxy.machine") if has_machine
                              else (None, ""))
    env, env_error = _part(native.env, "proxy.env")
    return Reading(user, user_error, machine, machine_error, env or (), env_error,
                   getattr(native, "SYSTEM", "windows"))
