"""What a session aims at, and its settings, as the program's flags.

A session always aims at something. ``server=`` (one or more servers) and ``process=``
(this test, or a process it started) are exact, and they are what the helper promises: a
scenario may not change what they set while it runs, or it could widen the aim to the
whole machine. The program's own aim flags (``target``, ``dst_ip``, ``dst_port``) are an
aim too, in the program's own syntax, for what those two cannot say: an API on a port, a
range of addresses, a process by name. They reach as far as they match, which the package
READMEs spell out (``dst_port=443`` is every HTTPS connection of the machine).
"""

from __future__ import annotations

import json
import os
import re
import socket
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit

from ._program import BadNetworkError

# Flags the helper sets itself, or that would turn the run into something else.
RESERVED = frozenset({
    "format", "stop_on_stdin_close", "duration", "simulate", "gui", "doctor", "dry_run",
    "print_config", "save_config", "license", "install_desktop", "remove_desktop",
    "cleanup_driver", "version", "help",
})
# The program's aim flags: an aim of their own, or a narrowing of server= / process=,
# which set some of them.
AIM_KEYS = ("target", "dst_ip", "dst_port")
SERVER_KEYS = frozenset({"dst_ip", "dst_port"})
PROCESS_KEYS = frozenset({"target"})
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}
# The two shapes the program accepts for a scenario it ships (paths.shipped_scenario).
_SHIPPED_FOLDERS = (("scenarios",), ("_internal", "scenarios"))
_SCENARIO_ADVICE = {
    SERVER_KEYS: "Aim with process= instead, and the scenario then narrows that process's "
                 "traffic.",
    PROCESS_KEYS: "Aim with server= instead, or take target out of the scenario.",
}


def server_address(server: object) -> tuple[str, int]:
    """``(host, port)`` from a URL, ``host:port`` or a ``(host, port)`` pair."""
    if isinstance(server, tuple) and len(server) == 2:
        host, port = server
        try:
            return str(host), int(port)
        except (TypeError, ValueError) as exc:
            raise BadNetworkError(f"server={server!r} has a port that is not a number.") from exc
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


def servers(server: object) -> list[tuple[str, int]]:
    """Every ``(host, port)`` that ``server=`` names: one, or a list of them."""
    if isinstance(server, list):
        if not server:
            raise BadNetworkError("server=[] names no server.")
        return [server_address(one) for one in server]
    return [server_address(server)]


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


def _running_child(process: object) -> int | None:
    """The PID of a process object this test started, while it runs; None for anything else.

    An object and not a number: a number may name any process of the machine (PID 1 on
    Linux, whose tree is every process), or one that took over the number of a process
    that ended.
    """
    import asyncio.subprocess
    import subprocess
    if isinstance(process, subprocess.Popen):
        running = process.poll() is None
    elif isinstance(process, asyncio.subprocess.Process):
        running = process.returncode is None
    else:
        return None
    if not running:
        raise BadNetworkError(f"process={process!r} has already ended, so there is nothing of "
                              "it to slow, and its number may belong to another process now.")
    return int(process.pid)


def _process(process: object) -> str:
    if isinstance(process, str) and process == "self":
        return str(os.getpid())
    pid = _running_child(process)
    if pid is None:
        raise BadNetworkError(
            f"process={process!r}: give 'self' (this test and everything it started), or the "
            "process object your test started, such as a subprocess.Popen (process=proc, not "
            "proc.pid). For a process ID or a program name, use target=, the program's own "
            "aim: a name there matches every program whose name contains it, and a process ID "
            "covers every process it started.")
    return str(pid)


def _value(value: object) -> str:
    if isinstance(value, (list, tuple, set, frozenset)):
        return ",".join(str(v) for v in value)
    return str(value)


def _given(value: object) -> bool:
    return value is not None and value is not False and value != ""


def _shipped(path: str, folders: Sequence[str]) -> str | None:
    """The file a scenario name the program ships stands for, as the program finds it."""
    if os.path.isabs(path):
        return None
    parts = os.path.normpath(path).replace("\\", "/").split("/")
    if tuple(os.path.normcase(part) for part in parts[:-1]) not in _SHIPPED_FOLDERS:
        return None
    for folder in folders:
        candidate = os.path.join(folder, parts[-1])
        if os.path.isfile(candidate):
            return candidate
    return None


def checked_scenario(path: object, aim_keys: frozenset[str], shipped: Sequence[str]) -> str:
    """The scenario's file as an absolute path, once no step of it changes ``aim_keys``.

    The program is handed this path, so it reads the file that was checked. A file this
    cannot read is refused here: the program could not read it either.
    """
    given = os.fspath(path) if isinstance(path, os.PathLike) else str(path)
    found = given if os.path.isfile(given) else _shipped(given, shipped)
    if found is None:
        raise BadNetworkError(f"scenario={given!r}: there is no such file. A scenario the "
                              "program ships is named 'scenarios/<file>.json'.")
    try:
        with open(found, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise BadNetworkError(f"scenario={given!r} could not be read as JSON: {exc}") from exc
    steps = data.get("steps") if isinstance(data, dict) else data
    if not isinstance(steps, list):
        raise BadNetworkError(f"scenario={given!r} is not a scenario: it has no list of steps.")
    for number, step in enumerate(steps, 1):
        settings = step.get("settings") if isinstance(step, dict) else None
        if not isinstance(settings, dict):
            continue
        changed = sorted(key for key in settings if key in aim_keys)
        if changed:
            raise BadNetworkError(
                f"scenario={given!r}: step {number} changes {', '.join(changed)}, which is "
                "what this session aims at. A scenario may change how the network behaves, "
                "not what the session aims at, or it could widen it to the whole machine. "
                + _SCENARIO_ADVICE.get(aim_keys, "Take those settings out of the scenario."))
    return os.path.abspath(found)


def session_flags(*, server: object = None, process: object = None, simulate: bool = False,
                  settings: Mapping[str, object], resolve=socket.getaddrinfo,
                  shipped_scenarios: Sequence[str] = ()) -> list[str]:
    """The program's flags for one session, without the ones the session adds itself."""
    for key in settings:
        if not _KEY.match(key):
            raise BadNetworkError(f"{key!r} is not a setting name. Settings are the program's "
                                  "flags with _ for -, such as latency or loss_burst.")
        if key in RESERVED:
            raise BadNetworkError(f"{key} is set by beannetworktester itself and cannot be "
                                  "passed as a setting.")
    aims = [key for key in AIM_KEYS if _given(settings.get(key))]
    if server is None and process is None and not aims and not simulate:
        raise BadNetworkError(
            "bad_network needs an aim: server= (a URL, 'host:port', or a list of them), "
            "process= ('self', or a process your test started), or one of the program's own "
            "target=, dst_ip=, dst_port=. Without one it would slow every connection of this "
            "machine, the test runner's own included.")
    flags: list[str] = []
    aim_keys: frozenset[str] = frozenset()
    if server is not None:
        if SERVER_KEYS & set(aims):
            raise BadNetworkError("server= sets dst_ip and dst_port: give one or the other.")
        # Several servers are every address of them with every port of them: the
        # program's two aim flags are matched apart, not as pairs.
        ips: list[str] = []
        ports: list[str] = []
        for host, port in servers(server):
            ips += [ip for ip in server_ips(host, port, resolve=resolve) if ip not in ips]
            if str(port) not in ports:
                ports.append(str(port))
        flags += ["--dst-ip", ",".join(ips), "--dst-port", ",".join(ports)]
        aim_keys |= SERVER_KEYS
    if process is not None:
        if "target" in aims:
            raise BadNetworkError("process= sets target: give one or the other.")
        flags += ["--target", _process(process)]
        aim_keys |= PROCESS_KEYS
    for key, value in settings.items():
        if value is None or value is False:
            continue
        if key == "scenario":
            value = checked_scenario(value, aim_keys, shipped_scenarios)
        flag = "--" + key.replace("_", "-")
        flags += [flag] if value is True else [flag, _value(value)]
    return flags
