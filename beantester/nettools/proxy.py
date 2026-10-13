"""Tools tab: the proxy row of the Adapters tool, its details and its report lines.

"Why does the impairment not reach my target?" - one answer is a proxy: a program
that uses one connects to the PROXY, not to the address the tester limited the
impairments to. This shows what the system holds (``beantester/proxy.py`` reads it)
and offers the proxy's address to the Control page the way a gateway's is offered.

The proxy list grammar is Microsoft Learn's (WINHTTP_PROXY_INFO, Remarks): entries
``([<scheme>=][<scheme>"://"]<server>[":"<port>])`` separated by semicolons or
whitespace; the bypass list holds names, and ``<local>`` stands for every name
without a dot. A server given as a NAME is shown, never looked up: a name lookup
is a DNS query, and nothing on this tab sends anything.

Passwords in a URL (``http://user:secret@proxy:8080``, common in ``HTTP_PROXY``) are
hidden everywhere, the window included - screenshots end up in public bug reports.
The report also drops a setup script address's query (``?token=...``).
"""
import ipaddress
import re

from .. import proxy as system
from .adapters import Detail, Words

# The variables that send a program to a proxy; NO_PROXY lists what goes around it.
PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
_USERINFO = re.compile(r"(?<=//)[^/@\s]*@")
_SEPARATORS = re.compile(r"[;\s]+")


def supported():
    return system.supported()


def read(native=None):
    """The system's proxy settings (``proxy.Reading``). On a worker; never raises."""
    return system.read(native)


# -- reading a value ---------------------------------------------------------------- #
def masked(value):
    """``value`` with every URL's user and password replaced: ``http://***@host``."""
    return _USERINFO.sub("***@", value)


def for_report(value):
    """``masked``, and an address's query and fragment left out - a setup script's
    address may carry a token there."""
    return re.sub(r"[?#][^\s;]*", "", masked(value))


def entries(text):
    """The entries of a proxy or bypass list, each as written."""
    return [part for part in _SEPARATORS.split(text or "") if part]


def host_of(entry):
    """One entry's server, without the scheme, a user and the port."""
    server = entry.split("=", 1)[-1].split("://", 1)[-1].rsplit("@", 1)[-1]
    if server.startswith("["):
        end = server.find("]")
        return server[1:end] if end > 0 else ""
    if server.count(":") == 1:                  # host:port; more colons is a bare IPv6
        return server.split(":", 1)[0]
    return server.split("/", 1)[0]


def address_of(entry):
    """The entry's server as an IP address the Control page takes; "" for a name."""
    try:
        return str(ipaddress.ip_address(host_of(entry)))
    except ValueError:
        return ""


def in_use(reading):
    """Some program on this machine would be sent to a proxy."""
    user, machine = reading.user, reading.machine
    return bool((user and (user.detect or user.script or user.server))
                or (machine and machine.server)
                or any(v.name in PROXY_VARIABLES for v in reading.env))


def unreadable(reading):
    return reading.user is None or reading.machine is None or bool(reading.env_error)


# -- the row on the adapter list ---------------------------------------------------- #
def state_words(reading):
    if in_use(reading):
        return Words("tools.adapters.proxy.state.in_use")
    if unreadable(reading):
        return Words("tools.adapters.proxy.state.unreadable")
    return Words("tools.adapters.proxy.state.not_set")


def first_server(reading):
    """The first proxy server a program would be sent to, for the list's address column."""
    for text in ((reading.user.server if reading.user else ""),
                 (reading.machine.server if reading.machine else "")):
        for entry in entries(text):
            return host_of(entry)
    return ""


# -- the details --------------------------------------------------------------------- #
def _servers(key, item, text, note):
    out = []
    for n, entry in enumerate(entries(text)):
        address = address_of(entry)
        words = [Words("tools.adapters.proxy.note.goes_here"), *note]
        if not address:
            words.append(Words("tools.adapters.proxy.note.name"))
        out.append(Detail(f"{key}|{n}", Words(item), masked(entry), tuple(words),
                          address=address))
    return out


def _bypass(key, item, text):
    if not text:
        return []
    note = (Words("tools.adapters.proxy.note.local"),) if "<local>" in text.lower() else ()
    return [Detail(key, Words(item), ", ".join(entries(text)), note)]


def _failed(key, item, error):
    return [Detail(key, Words(item), Words("tools.adapters.proxy.state.unreadable"), (error,))]


def _user_rows(reading):
    user = reading.user
    if user is None:
        return _failed("user", "tools.adapters.proxy.item.account", reading.user_error)
    yes, no = Words("tools.adapters.value.yes"), Words("tools.adapters.value.no")
    out = [Detail("detect", Words("tools.adapters.proxy.item.detect"), yes if user.detect else no,
                  (Words("tools.adapters.proxy.note.detect"),) if user.detect else ()),
           Detail("script", Words("tools.adapters.proxy.item.script"),
                  masked(user.script) or Words("tools.adapters.value.none"))]
    servers = _servers("server", "tools.adapters.proxy.item.server", user.server, ())
    out += servers or [Detail("server", Words("tools.adapters.proxy.item.server"),
                              Words("tools.adapters.value.none"))]
    return out + _bypass("bypass", "tools.adapters.proxy.item.bypass", user.bypass)


def _machine_rows(reading):
    machine = reading.machine
    if machine is None:
        return _failed("winhttp", "tools.adapters.proxy.item.winhttp", reading.machine_error)
    note = (Words("tools.adapters.proxy.note.services"),)
    servers = _servers("winhttp", "tools.adapters.proxy.item.winhttp", machine.server, note)
    if not servers:
        return [Detail("winhttp", Words("tools.adapters.proxy.item.winhttp"),
                       Words("tools.adapters.value.none"), note)]
    return servers + _bypass("winhttp_bypass", "tools.adapters.proxy.item.winhttp_bypass",
                             machine.bypass)


def _variable_rows(reading):
    if reading.env_error:
        return _failed("env", "tools.adapters.proxy.item.variables", reading.env_error)
    out = []
    for variable in reading.env:
        shown = masked(variable.value)
        note = [Words("tools.adapters.proxy.note.this_account" if variable.scope == "user"
                      else "tools.adapters.proxy.note.all_accounts")]
        if variable.replaces:
            note.append(Words("tools.adapters.proxy.note.replaces"))
        note.append(Words("tools.adapters.proxy.note.readers" if variable.name in PROXY_VARIABLES
                          else "tools.adapters.proxy.note.no_proxy"))
        if shown != variable.value:
            note.append(Words("tools.adapters.proxy.note.masked"))
        address = (address_of(variable.value) if variable.name in PROXY_VARIABLES else "")
        out.append(Detail(f"env|{variable.name}", variable.name, shown, tuple(note),
                          address=address))
    return out or [Detail("env", Words("tools.adapters.proxy.item.variables"),
                          Words("tools.adapters.value.none"))]


def details(reading):
    """The rows of the details table, in reading order: the account's settings, the
    machine's WinHTTP proxy, the variables."""
    return _user_rows(reading) + _machine_rows(reading) + _variable_rows(reading)


# -- the report (English, like the adapters') -------------------------------------- #
def _or_none(text):
    return for_report(text) if text else "none"


def report_lines(reading):
    """The proxy in the copied report: passwords hidden, setup script queries dropped."""
    user, machine = reading.user, reading.machine
    if user is None:
        lines = [f"proxy, this account: could not be read ({reading.user_error})"]
    else:
        lines = [f"proxy, this account: detect automatically {'yes' if user.detect else 'no'}, "
                 f"setup script {_or_none(user.script)}, server {_or_none(user.server)}, "
                 f"bypass {_or_none(user.bypass)}"]
    if machine is None:
        lines.append(f"proxy for services (WinHTTP): could not be read ({reading.machine_error})")
    else:
        lines.append(f"proxy for services (WinHTTP): {_or_none(machine.server)}"
                     + (f", bypass {for_report(machine.bypass)}" if machine.bypass else ""))
    if reading.env_error:
        lines.append(f"proxy variables: could not be read ({reading.env_error})")
    else:
        variables = ", ".join(f"{v.name}={for_report(v.value)} ({v.scope})" for v in reading.env)
        lines.append(f"proxy variables: {variables or 'none'}")
    return lines


def report(reading):
    return "\n".join(report_lines(reading))
