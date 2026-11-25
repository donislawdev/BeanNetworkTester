"""What a session aims at, and its settings, as the program's flags.

A session always aims at something: a server, a process, or one of the program's
own aims (``target``, ``dst_ip``, ``dst_port``). Without one it would slow every
connection of the machine, the test runner's own included.
"""

from __future__ import annotations

import os
import re
import socket
from collections.abc import Mapping
from urllib.parse import urlsplit

from ._program import BadNetworkError

# Flags the helper sets itself, or that would turn the run into something else.
RESERVED = frozenset({
    "format", "stop_on_stdin_close", "duration", "simulate", "gui", "doctor", "dry_run",
    "print_config", "save_config", "license", "install_desktop", "remove_desktop",
    "cleanup_driver", "version", "help",
})
OWN_AIMS = ("target", "dst_ip", "dst_port")
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def server_address(server: object) -> tuple[str, int]:
    """``(host, port)`` from a URL, ``host:port`` or a ``(host, port)`` pair."""
    if isinstance(server, tuple) and len(server) == 2:
        host, port = server
        return str(host), int(port)
    text = str(server).strip()
    if "://" not in text:
        text = "tcp://" + text
    parts = urlsplit(text)
    host = parts.hostname
    try:
        port = parts.port or _DEFAULT_PORTS.get(parts.scheme)
    except ValueError as exc:
        raise BadNetworkError(f"server={server!r} has a port that is not a number.") from exc
    if not host or not port:
        raise BadNetworkError(
            f"server={server!r} names no host and port. Give a URL such as "
            "'http://localhost:3000', a 'host:port' pair or a (host, port) tuple.")
    return host, int(port)


def server_ips(host: str, port: int, *, resolve=socket.getaddrinfo) -> list[str]:
    """Every address the host has, IPv4 and IPv6, in the order the system gives them."""
    try:
        infos = resolve(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise BadNetworkError(f"server host {host!r} has no address: {exc}") from exc
    out: list[str] = []
    for info in infos:
        address = str(info[4][0]).split("%")[0]       # an IPv6 zone is not part of the aim
        if address not in out:
            out.append(address)
    if not out:
        raise BadNetworkError(f"server host {host!r} has no address.")
    return out


def _process(process: object) -> str:
    if process == "self":
        return str(os.getpid())
    if isinstance(process, bool) or not isinstance(process, (int, str)):
        raise BadNetworkError(f"process={process!r}: give 'self', a PID or a program name.")
    return str(process)


def _value(value: object) -> str:
    if isinstance(value, (list, tuple, set, frozenset)):
        return ",".join(str(v) for v in value)
    return str(value)


def session_flags(*, server: object = None, process: object = None, simulate: bool = False,
                  settings: Mapping[str, object], resolve=socket.getaddrinfo) -> list[str]:
    """The program's flags for one session, without the ones the session adds itself."""
    flags: list[str] = []
    for key in settings:
        if not _KEY.match(key):
            raise BadNetworkError(f"{key!r} is not a setting name. Settings are the program's "
                                  "flags with _ for -, such as latency or loss_burst.")
        if key in RESERVED:
            raise BadNetworkError(f"{key} is set by beannetworktester itself and cannot be "
                                  "passed as a setting.")
    aims = [key for key in OWN_AIMS if settings.get(key) not in (None, "", False)]
    if server is None and process is None and not aims and not simulate:
        raise BadNetworkError(
            "bad_network needs an aim: server=, process=, or one of target, dst_ip, dst_port. "
            "Without one it would slow every connection of this machine, the test runner's "
            "own included.")
    if server is not None:
        host, port = server_address(server)
        if "dst_ip" in aims or "dst_port" in aims:
            raise BadNetworkError("server= sets dst_ip and dst_port: give one or the other.")
        flags += ["--dst-ip", ",".join(server_ips(host, port, resolve=resolve)),
                  "--dst-port", str(port)]
    if process is not None:
        if "target" in aims:
            raise BadNetworkError("process= sets target: give one or the other.")
        flags += ["--target", _process(process)]
    for key, value in settings.items():
        if value is None or value is False:
            continue
        flag = "--" + key.replace("_", "-")
        flags += [flag] if value is True else [flag, _value(value)]
    return flags
