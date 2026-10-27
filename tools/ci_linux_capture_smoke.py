#!/usr/bin/env python3
"""A real capture on Linux (experimental, eBPFDivert): the impairment arrives, and only where it was aimed.

Why this exists
---------------
Linux capture goes through a second driver, pydivert's eBPFDivert, chosen by
``beantester/capture_backend.py``. Everything else in the suite drives it through
stand-ins, and a stand-in cannot tell whether the kernel really held, dropped or
let past a packet. This runs the real command line, as a user would, on a real
kernel - GitHub's ubuntu runner in CI.

What it checks, and why each needs two signals
----------------------------------------------
A UDP echo far end with two ports: the TARGET the session aims at and a BYSTANDER
it must not touch. Every phase measures both, because "impaired" and "the far end
went away" look the same from one side.

* before any session: both ports answer fast (the control - without it a slow
  machine would pass the latency phase by itself);
* ``--latency 50 --narrow-filter``: the target's round trip grows by both
  directions' 50 ms, the bystander's does not, and the filter was narrowed;
* ``--loss 100``: the target goes silent, the bystander keeps answering;
* after: both are fast again - the session took nothing with it;
* Ping, the Tools tab's own ``icmp.echo``, through ``--latency 50``: first through the
  raw socket, because a new namespace refuses the ping socket even to root
  (``ping_group_range = 1 0``), then through the ping socket once the namespace
  allows it - each carries both directions' latency, and is fast before and after.
* "Reset this connection", the Connections page's own ``tcpreset.reset``, on a TCP
  connection from the namespace: with no session the program holding it hears
  ECONNABORTED and the far end a reset; during ``--loss 100`` toward the far end the
  program still hears it and the far end hears nothing - the reset is a packet like any
  other. And a connection that closed after the socket list was read: its destroy ends
  as "gone", and the listener on its port lives on (by its numbers alone, without the
  cookie, the kernel took the listener - measured 2026-10-26).
* The Tools tab's TCP health, its own ``tcpestats.watch`` and ``read``, on a TCP
  connection from the namespace: its numbers equal what ``ss -tin`` says of that socket
  at the same moment (resend timer, segment size, round trip, bytes sent, received and
  sent again); during ``--latency 50`` on its port the smoothed round trip it reports
  climbs toward both directions' 50 ms - the tool's promise, "does the stack see my
  latency"; closed, the connection reads as ended.
* The Tools tab's Adapters, its own ``adapters.read``, against ``ip -j`` of the same
  tables: in the namespace, given an address with a lease, a deprecated one and a
  duplicate (the same IPv6 address on both ends of a veth pair, so DAD finds it), each
  of which it must name; and on this machine as it is. Adapters, MTU, MAC, state, every
  address with its prefix, DAD state and lease, and the adapter the route out leaves
  through - field by field, as the probe that found no difference compared them.

What bounds the damage (convention 6)
-------------------------------------
Every packet the tool can see is inside a network namespace this script builds
(``bntci``, joined to the root namespace by a veth pair) and deletes again, also
when a phase fails. The sessions run INSIDE it, with ``--dst-ip``, ``--dst-port``
and ``--duration``, so the machine's own interfaces are never handed to the tool.
The resets act only on connections this script opened, from inside the namespace.

Not Linux, not root, or no eBPFDivert -> SKIP and exit 0, unless ``--require`` is
given, which CI passes: there a check that cannot run must fail, not pass quietly.
"""
import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NS = "bntci"
HOST, PEER = "10.233.0.1", "10.233.0.2"
TARGET_PORT, BYSTANDER_PORT = 47101, 47102
LATENCY_MS = 50
ROUNDS = 12

# Run INSIDE the namespace: one UDP echo per round, the round trip in ms or None.
CLIENT = (
    "import json, socket, sys, time\n"
    "host, port, rounds = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])\n"
    "s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
    "s.settimeout(float(sys.argv[4]))\n"
    "out = []\n"
    "for i in range(rounds):\n"
    "    t0 = time.perf_counter()\n"
    "    s.sendto(b'bnt%d' % i, (host, port))\n"
    "    try:\n"
    "        s.recvfrom(64)\n"
    "        out.append(round((time.perf_counter() - t0) * 1000, 2))\n"
    "    except OSError:\n"
    "        out.append(None)\n"
    "    time.sleep(0.05)\n"
    "print(json.dumps(out))\n")

# Run INSIDE the namespace, from the checkout: the Tools tab's own Ping (icmp.echo),
# one request per round, the socket kind it may use and each round trip in ms or None.
PING_CLIENT = (
    "import ipaddress, json, sys\n"
    "from beantester import icmp, icmpsock\n"
    "host, rounds, wait_ms = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])\n"
    "out = []\n"
    "for i in range(rounds):\n"
    "    echo = icmp.echo(ipaddress.ip_address(host), wait_ms)\n"
    "    out.append(echo.rtt_ms if echo.status == icmp.IP_SUCCESS else None)\n"
    "print(json.dumps({'kind': icmpsock.kind(), 'rtts': out}))\n")
PING_ROUNDS = 6

RESET_PORT = 47103
ECONNABORTED = 103          # what Linux tells the program whose socket a reset destroyed

# Run INSIDE the namespace, from the checkout: one TCP connection to the far end, held
# open until a line arrives on stdin, then the Connections page's own reset of it and
# what the program holding it hears next.
RESET_CLIENT = (
    "import json, socket, sys\n"
    "from beantester import tcpreset\n"
    "host, port = sys.argv[1], int(sys.argv[2])\n"
    "s = socket.create_connection((host, port), timeout=5)\n"
    "print('ready', flush=True)\n"
    "sys.stdin.readline()\n"
    "got = tcpreset.reset(tcpreset.Target(s.getsockname()[1], host, port))\n"
    "try:\n"
    "    s.recv(1)\n"
    "    heard = None\n"
    "except OSError as exc:\n"
    "    heard = exc.errno\n"
    "print(json.dumps({'outcome': got.kind, 'client': heard}), flush=True)\n")

# Run INSIDE the namespace: a connection to a listener there, ended by a reset from its
# client, then destroyed by the socket the list showed before - what a click meets when
# the connection closes between reading the list and the destroy.
STALE_CLIENT = (
    "import json, socket, struct, time\n"
    "from beantester import tcpreset\n"
    "srv = socket.socket()\n"
    "srv.bind(('127.0.0.1', 0))\n"
    "srv.listen(4)\n"
    "port = srv.getsockname()[1]\n"
    "c = socket.create_connection(('127.0.0.1', port), timeout=5)\n"
    "a, _ = srv.accept()\n"
    "system = tcpreset._Linux()\n"
    "rows, _ = system.rows()\n"
    "served = [r for r in rows if r.local_port == port and r.remote_port == c.getsockname()[1]]\n"
    "c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))\n"
    "c.close()\n"
    "time.sleep(0.2)\n"
    "stale = system.end(served[0], None).kind if len(served) == 1 else None\n"
    "try:\n"
    "    socket.create_connection(('127.0.0.1', port), timeout=2).close()\n"
    "    listener = 'alive'\n"
    "except OSError as exc:\n"
    "    listener = type(exc).__name__\n"
    "print(json.dumps({'found': len(served), 'stale': stale, 'listener': listener}))\n")

HEALTH_PORT = 47104
HEALTH_ROUNDS = 20          # echoes of ~2 x 50 ms + 0.1 s each under the session: about 4 s
# What the far end says first: an echo alone sends as many bytes as it receives, and the
# two counters swapped would pass.
HEALTH_GREETING = b"bnt says hello\n"

# Run INSIDE the namespace, from the checkout: one TCP connection to the far end's echo,
# watched by the Tools tab's own TCP health and read by `ss -tin` at the same moment;
# then, at a line on stdin, an echo every 0.1 s (a session adds its latency meanwhile)
# and a read; then closed, and read once more.
HEALTH_CLIENT = (
    "import json, socket, subprocess, sys, time\n"
    "from beantester import tcpestats\n"
    "from beantester.tcprow import Connection\n"
    "host, port, rounds, greeting = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])\n"
    "s = socket.create_connection((host, port), timeout=5)\n"
    "s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)\n"
    "heard = b''\n"
    "while len(heard) < greeting:\n"
    "    heard += s.recv(greeting - len(heard))\n"
    "def echo(n):\n"
    "    for _ in range(n):\n"
    "        s.sendall(b'h' * 100)\n"
    "        got = 0\n"
    "        while got < 100:\n"
    "            got += len(s.recv(4096))\n"
    "        time.sleep(0.1)\n"
    "def said(r):\n"
    "    x = r.sample\n"
    "    return {'state': r.state, 'srtt': x and x.smoothed_rtt, 'rto': x and x.rto,\n"
    "            'mss': x and x.mss, 'sent': x and x.bytes_out, 'received': x and x.bytes_in,\n"
    "            'resent': x and x.resent_bytes}\n"
    "echo(5)\n"
    "time.sleep(0.3)\n"
    "c = Connection(s.getsockname()[0], s.getsockname()[1], host, port)\n"
    "r = tcpestats.watch(c)\n"
    "ss = subprocess.run(['ss', '-tinH', 'state', 'all', '( sport = :%d )' % c.local_port],\n"
    "                    capture_output=True, text=True, timeout=10).stdout\n"
    "print(json.dumps({**said(r), 'ss': ss}), flush=True)\n"
    "sys.stdin.readline()\n"
    "echo(rounds)\n"
    "during = said(tcpestats.read(c, handle=r.handle))\n"
    "s.close()\n"
    "time.sleep(0.3)\n"
    "during['closed'] = tcpestats.read(c, handle=r.handle).state\n"
    "print(json.dumps(during), flush=True)\n")


# Run INSIDE the namespace (and once outside it), from the checkout: the Adapters tool's
# own read (adapters.read), and what `ip -j` says of the same tables.
ADAPTERS_CLIENT = (
    "import json, subprocess\n"
    "from beantester import adapters\n"
    "def ip(*a):\n"
    "    r = subprocess.run(['ip', '-j', *a], capture_output=True, text=True, timeout=10)\n"
    "    return json.loads(r.stdout or '[]')\n"
    "r = adapters.read()\n"
    "rows = [{'name': a.name, 'index': a.if_index, 'status': a.status, 'mtu': a.mtu,\n"
    "         'mac': a.mac, 'addresses': [[x.ip, x.prefix, x.origin, x.dad] for x in a.addresses]}\n"
    "        for a in r.adapters]\n"
    "print(json.dumps({'product': rows, 'internet': r.internet.get(4, 0), 'link': ip('link'),\n"
    "                  'addr': ip('addr'), 'route': ip('route', 'get', '8.8.8.8')}))\n")
# Addresses in the states the Adapters tool names, made in the namespace. A duplicate is
# what DAD finds when the address is on both ends of a veth pair: one end answers for it
# (nodad) while the other asks.
LEASED, DEPRECATED, DUPLICATE6 = "203.0.113.5", "203.0.113.6", "2001:db8:ac::1"
# adapters.py's numbers (AddressRow.origin, .dad), written out: this script runs with
# the checkout only on the namespace's side. tests/test_ci_linux_capture_smoke.py holds
# them equal to the module's.
ORIGIN_WELL_KNOWN, ORIGIN_DHCP, ORIGIN_ROUTER, ORIGIN_LEASE = 2, 3, 4, -1
DAD_TENTATIVE, DAD_DUPLICATE, DAD_DEPRECATED, DAD_PREFERRED = 1, 2, 3, 4
STATUS_UP = 1


# -- the judges: pure, so a test can prove they fail ------------------------------ #
def _answered(rtts):
    return [r for r in rtts if r is not None]


def _median(rtts):
    got = _answered(rtts)
    return statistics.median(got) if got else None


def judge_latency(before, during, bystander, after, latency_ms=LATENCY_MS):
    """Failures (empty = pass) for the latency phase and the controls around it."""
    fast = latency_ms / 2
    added = 2 * latency_ms                       # each direction carries the latency
    failures = []
    for name, rtts in (("before", before), ("during", during), ("bystander", bystander),
                       ("after", after)):
        if len(_answered(rtts)) < 0.8 * len(rtts) or not rtts:
            failures.append(f"{name}: only {len(_answered(rtts))} of {len(rtts)} answered")
    m = {name: _median(r) for name, r in (("before", before), ("during", during),
                                          ("bystander", bystander), ("after", after))}
    if m["before"] is not None and m["before"] >= fast:
        failures.append(f"before: {m['before']} ms - the machine is too slow to tell")
    if m["during"] is not None and not 0.9 * added <= m["during"] <= added + 100:
        failures.append(f"during: {m['during']} ms, expected about {added} ms")
    if m["bystander"] is not None and m["bystander"] >= fast:
        failures.append(f"bystander: {m['bystander']} ms - the session reached past its target")
    if m["after"] is not None and m["after"] >= fast:
        failures.append(f"after: {m['after']} ms - the session left something behind")
    return failures


def judge_loss(target, bystander):
    """Failures (empty = pass) for the --loss 100 phase."""
    failures = []
    if _answered(target):
        failures.append(f"target: {len(_answered(target))} of {len(target)} answered under --loss 100")
    if not bystander or len(_answered(bystander)) < len(bystander):
        failures.append(f"bystander: {len(_answered(bystander))} of {len(bystander)} answered")
    return failures


def judge_ping(before, raw, dgram, after, latency_ms=LATENCY_MS):
    """Failures (empty = pass) for the Ping phase. Each measurement is ``{"kind", "rtts"}``:
    the raw socket while the namespace refuses the ping socket (a new one starts at
    ``ping_group_range = 1 0``), the ping socket once it is opened."""
    fast = latency_ms / 2
    added = 2 * latency_ms
    failures = []
    for name, got, kind, slow in (("before", before, "raw", False), ("raw", raw, "raw", True),
                                  ("dgram", dgram, "dgram", True), ("after", after, "dgram", False)):
        rtts = got.get("rtts") or []
        if got.get("kind") != kind:
            failures.append(f"ping {name}: the {got.get('kind')} socket, expected the {kind} one")
        if not rtts or len(_answered(rtts)) < 0.8 * len(rtts):
            failures.append(f"ping {name}: only {len(_answered(rtts))} of {len(rtts)} answered")
            continue
        median = _median(rtts)
        if slow and not 0.9 * added <= median <= added + 100:
            failures.append(f"ping {name}: {median} ms, expected about {added} ms")
        if not slow and median >= fast:
            failures.append(f"ping {name}: {median} ms - "
                            + ("the machine is too slow to tell" if name == "before"
                               else "the session left something behind"))
    return failures


def judge_reset(plain, impaired, stale):
    """Failures (empty = pass) for the Reset phase. ``plain`` is a reset with no session,
    ``impaired`` one during ``--loss 100`` toward the far end, each ``{"outcome",
    "client", "far"}`` - ``far`` being what the far end heard, "reset" or "nothing".
    ``stale``: the destroy of a connection that closed after the list was read."""
    failures = []
    for name, got, far in (("plain reset", plain, "reset"), ("reset under loss", impaired, "nothing")):
        if got.get("outcome") != "reset":
            failures.append(f"{name}: ended {got.get('outcome')!r}, not 'reset'")
        if got.get("client") != ECONNABORTED:
            failures.append(f"{name}: the program heard errno {got.get('client')}, not ECONNABORTED")
        if got.get("far") != far:
            failures.append(f"{name}: the far end heard {got.get('far')!r}, expected {far!r}")
    if stale.get("found") != 1:
        failures.append(f"stale: {stale.get('found')} sockets listed for the connection, not 1")
    if stale.get("stale") != "gone":
        failures.append(f"stale: a closed connection's destroy ended {stale.get('stale')!r}, not 'gone'")
    if stale.get("listener") != "alive":
        failures.append(f"stale: the listener on its port: {stale.get('listener')} - the destroy took it")
    return failures


def _ip_dad(address):
    if address.get("dadfailed"):
        return DAD_DUPLICATE
    if address.get("tentative"):
        return DAD_TENTATIVE
    return DAD_DEPRECATED if address.get("deprecated") else DAD_PREFERRED


def _ip_up(link):
    """What the tool calls up: UP, or UNKNOWN switched on with its link."""
    state, flags = link.get("operstate"), set(link.get("flags", []))
    return state == "UP" or (state == "UNKNOWN" and {"UP", "LOWER_UP"} <= flags)


def _judge_links(name, mine, theirs, where, private):
    failures = []
    if mine["index"] != theirs.get("ifindex"):
        failures.append(f"adapters {where}: {name} index {mine['index']}, ip says "
                        f"{theirs.get('ifindex')}")
    if mine["mtu"] != theirs.get("mtu"):
        failures.append(f"adapters {where}: {name} MTU {mine['mtu']}, ip says {theirs.get('mtu')}")
    mac = theirs.get("address", "") if theirs.get("link_type") == "ether" else mine["mac"]
    if mine["mac"] != mac:
        said = "" if private else f" {mine['mac']!r}, ip says {mac!r}"
        failures.append(f"adapters {where}: {name} MAC differs{said}")
    if (mine["status"] == STATUS_UP) != _ip_up(theirs):
        failures.append(f"adapters {where}: {name} status {mine['status']}, ip says "
                        f"{theirs.get('operstate')} {theirs.get('flags')}")
    return failures


def _judge_address(key, mine, theirs, where, private):
    shown = f"an address on {key[0]}" if private else str(key)
    failures = []
    if mine[3] != _ip_dad(theirs):
        failures.append(f"adapters {where}: {shown} DAD state {mine[3]}, ip says {_ip_dad(theirs)}")
    leased = mine[2] in (ORIGIN_DHCP, ORIGIN_ROUTER, ORIGIN_LEASE)
    if mine[2] != ORIGIN_WELL_KNOWN and leased != bool(theirs.get("dynamic")):
        failures.append(f"adapters {where}: {shown} origin {mine[2]}, ip says dynamic "
                        f"{bool(theirs.get('dynamic'))}")
    return failures


def judge_adapters(seen, where, states=False, private=False):
    """Failures (empty = pass): the Adapters tool's read of a namespace against ``ip -j``
    of the same one - adapters, index, MTU, MAC, state; every address, its prefix, its
    DAD state and whether it has a lease; the adapter the route out leaves through.
    ``states``: the namespace was made with a lease, a deprecated address and a
    duplicate, and the tool must have seen each - or the comparison proved nothing.
    ``private``: the machine's own adapters - a failure names the adapter and what
    differs, never its addresses or MAC, which a log pasted anywhere would carry."""
    product = {a["name"]: a for a in seen.get("product", [])}
    links = {link["ifname"]: link for link in seen.get("link", [])}
    if not product:
        return [f"adapters {where}: the tool listed no adapter"]
    failures = []
    if set(product) != set(links):
        failures.append(f"adapters {where}: {sorted(product)}, ip lists {sorted(links)}")
    for name in sorted(set(product) & set(links)):
        failures += _judge_links(name, product[name], links[name], where, private)
    theirs = {(link["ifname"], a["local"], a["prefixlen"]): a
              for link in seen.get("addr", []) for a in link.get("addr_info", [])}
    mine = {(name, x[0], x[1]): x for name, a in product.items() for x in a["addresses"]}
    differ = sorted(set(mine) ^ set(theirs))
    if differ:
        said = (f"{len(differ)}, on {sorted({key[0] for key in differ})}" if private
                else str(differ))
        failures.append(f"adapters {where}: addresses differ: {said}")
    for key in sorted(set(mine) & set(theirs)):
        failures += _judge_address(key, mine[key], theirs[key], where, private)
    route = seen.get("route") or []
    out = links.get(route[0].get("dev"), {}).get("ifindex", 0) if route else 0
    if seen.get("internet") != out:
        failures.append(f"adapters {where}: the route out through {seen.get('internet')}, "
                        f"ip says {out}")
    # By address AND state: the duplicate is on both ends of its pair, in use on one.
    for ip, field, value, what in ((LEASED, 2, ORIGIN_DHCP, "a lease"),
                                   (DEPRECATED, 3, DAD_DEPRECATED, "deprecated"),
                                   (DUPLICATE6, 3, DAD_DUPLICATE, "a duplicate")):
        if states and not any(x[0] == ip and x[field] == value for x in mine.values()):
            failures.append(f"adapters {where}: {ip} not seen as {what} "
                            f"({[x for x in mine.values() if x[0] == ip]})")
    return failures


SS_FIELDS = ("rto", "rtt", "mss", "bytes_sent", "bytes_received", "bytes_retrans")


def _ss_numbers(text):
    """The fields of an ``ss -tin`` line TCP health is judged by, as ``ss`` wrote them."""
    out = {}
    for token in text.split():
        key, sep, value = token.partition(":")
        if sep and key in SS_FIELDS:
            out[key] = value
    return out


def judge_health(watched, during, latency_ms=LATENCY_MS):
    """Failures (empty = pass) for the TCP health phase. ``watched`` is the reading when
    the connection was put on the list, with ``ss -tin``'s line of the same moment;
    ``during`` the reading after the echoes through ``--latency``, and ``closed`` the
    state once the connection was closed. Whole milliseconds rounded down, as the tool
    says them; ``ss`` leaves out bytes_retrans while it is 0. The far end's greeting
    makes the bytes received differ from the bytes sent."""
    if watched.get("state") != "ok":
        return [f"tcp health: watching ended {watched.get('state')!r}, not 'ok'"]
    ss = _ss_numbers(watched.get("ss") or "")
    failures = []
    try:
        want = {"rto": int(float(ss["rto"])), "srtt": int(float(ss["rtt"].split("/")[0])),
                "mss": int(ss["mss"]), "sent": int(ss["bytes_sent"]),
                "received": int(ss["bytes_received"]), "resent": int(ss.get("bytes_retrans", 0))}
    except (KeyError, ValueError):
        return [f"tcp health: ss said no numbers for the connection: {watched.get('ss')!r}"]
    for name, value in want.items():
        if watched.get(name) != value:
            failures.append(f"tcp health: {name} {watched.get(name)}, ss said {value}")
    added = 2 * latency_ms                       # each direction carries the latency
    if want["srtt"] >= latency_ms / 2:
        failures.append(f"tcp health: {want['srtt']} ms before the session - the machine is "
                        "too slow to tell")
    # A smoothed value, not one round trip: one slow sample pulls it up for seconds (232 ms
    # through this session on the VM, 2026-10-27), so the top only catches a wrong unit.
    srtt = during.get("srtt")
    if during.get("state") != "ok" or srtt is None or not 0.6 * added <= srtt <= 5 * added:
        failures.append(f"tcp health: smoothed {srtt} ms ({during.get('state')}) through the "
                        f"session, expected toward {added} ms")
    if during.get("closed") != "ended":
        failures.append(f"tcp health: closed, it read {during.get('closed')!r}, not 'ended'")
    return failures


def skip_reason(platform, euid, library_loaded):
    """Why this machine cannot run the check, or None."""
    if not platform.startswith("linux"):
        return "not Linux"
    if euid != 0:
        return "not root (the capture needs it)"
    if not library_loaded:
        return "pydivert's libebpfdivert is not loaded"
    return None


# -- the machine ---------------------------------------------------------------- #
def _ip(*args):
    subprocess.run(["ip", *args], check=True, capture_output=True, text=True)


def build_namespace():
    teardown_namespace()
    _ip("netns", "add", NS)
    _ip("link", "add", f"{NS}-h", "type", "veth", "peer", "name", f"{NS}-c")
    _ip("link", "set", f"{NS}-c", "netns", NS)
    _ip("addr", "add", f"{HOST}/30", "dev", f"{NS}-h")
    _ip("link", "set", f"{NS}-h", "up")
    _ip("-n", NS, "addr", "add", f"{PEER}/30", "dev", f"{NS}-c")
    _ip("-n", NS, "link", "set", f"{NS}-c", "up")
    _ip("-n", NS, "link", "set", "lo", "up")


def teardown_namespace():
    subprocess.run(["ip", "netns", "del", NS], capture_output=True)
    subprocess.run(["ip", "link", "del", f"{NS}-h"], capture_output=True)


def start_far_end():
    """UDP echo on both ports, in THIS process, in the root namespace."""
    for port in (TARGET_PORT, BYSTANDER_PORT):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((HOST, port))

        def echo(s=sock):
            while True:
                data, addr = s.recvfrom(64)
                s.sendto(data, addr)
        threading.Thread(target=echo, daemon=True).start()


def in_namespace(*argv):
    return ["ip", "netns", "exec", NS, *argv]


def measure(port, rounds=ROUNDS, timeout=1.0):
    """Round trips from inside the namespace: ``rounds * (timeout + 0.05)`` s at worst."""
    r = subprocess.run(in_namespace(sys.executable, "-c", CLIENT, HOST, str(port), str(rounds),
                                    str(timeout)),
                       capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout.strip() or "[]")


def ping(rounds=PING_ROUNDS, wait_ms=1000):
    """Ping's own echo from inside the namespace: ``rounds * wait`` s at worst."""
    r = subprocess.run(in_namespace(sys.executable, "-c", PING_CLIENT, HOST, str(rounds),
                                    str(wait_ms)),
                       cwd=ROOT, capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout.strip() or "{}")


def open_ping_sockets():
    """Let every group open the ping socket - in the namespace only. The setting is the
    namespace's own (each one has its ``ping_group_range``) and goes with it:
    ``teardown_namespace`` deletes the namespace in ``main``'s ``finally``, so there is
    nothing to put back."""
    subprocess.run(in_namespace("sysctl", "-q", "-w", "net.ipv4.ping_group_range=0 2147483647"),
                   check=True, capture_output=True, text=True)


def run_session(args, during):
    """The real CLI inside the namespace; ``during()`` runs once the session is up."""
    p = subprocess.Popen(in_namespace(sys.executable, "-m", "beantester", *args), cwd=ROOT,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env={**os.environ, "LANG": "C.UTF-8"})
    lines, up = [], threading.Event()

    def read():
        for line in p.stdout:
            lines.append(line.rstrip())
            if "Running" in line:
                up.set()
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    if not up.wait(20):
        p.kill()
        p.wait(10)
        return None, lines, None
    try:
        result = during()
        code = p.wait(60)
    except BaseException:
        # A measurement that raised, or a session that outlived its --duration: the
        # CLI still holds its eBPF programs, and the namespace is about to go -
        # never leave it running behind this check.
        p.kill()
        p.wait(10)
        raise
    reader.join(5)
    return result, lines, code


def _session_failures(name, result, lines, code):
    if result is None:
        return [f"{name} session never said it was running: {lines[-5:]}"]
    return [f"{name} session: exit {code}"] if code != 0 else []


def _latency_phase():
    before = measure(TARGET_PORT)
    # 12 rounds of ~100 ms + 12 of a few ms: about 2.5 s of an 8 s session.
    result, lines, code = run_session(
        ["--dst-ip", HOST, "--dst-port", str(TARGET_PORT), "--latency", str(LATENCY_MS),
         "--narrow-filter", "--duration", "8"],
        lambda: (measure(TARGET_PORT), measure(BYSTANDER_PORT)))
    failures = _session_failures("latency", result, lines, code)
    if result is None:
        return failures
    during, bystander = result
    after = measure(TARGET_PORT)
    failures += judge_latency(before, during, bystander, after)
    if not any("narrowed" in line for line in lines):
        failures.append("latency session: the driver filter was not narrowed")
    print("latency:", json.dumps({"before": _median(before), "during": _median(during),
                                  "bystander": _median(bystander), "after": _median(after)}))
    return failures


def _loss_phase():
    # 6 rounds at 0.3 s each, at worst 2.1 s, inside a 6 s session: a round that
    # outlived the session would be answered by an unimpaired path and read as a leak.
    result, lines, code = run_session(
        ["--dst-ip", HOST, "--dst-port", str(TARGET_PORT), "--loss", "100", "--duration", "6"],
        lambda: (measure(TARGET_PORT, rounds=6, timeout=0.3),
                 measure(BYSTANDER_PORT, rounds=6, timeout=0.3)))
    failures = _session_failures("loss", result, lines, code)
    if result is None:
        return failures
    target, bystander = result
    failures += judge_loss(target, bystander)
    print("loss:", json.dumps({"target_answered": len(_answered(target)),
                               "bystander_answered": len(_answered(bystander))}))
    return failures


def _ping_phase():
    # 6 rounds of ~100 ms for each socket, about 2 s of an 8 s session; the namespace
    # opens the ping socket between them, so one session measures both.
    before = ping()

    def during():
        raw = ping()
        open_ping_sockets()
        return raw, ping()
    result, lines, code = run_session(
        ["--dst-ip", HOST, "--latency", str(LATENCY_MS), "--duration", "8"], during)
    failures = _session_failures("ping", result, lines, code)
    if result is None:
        return failures
    raw, dgram = result
    after = ping()
    failures += judge_ping(before, raw, dgram, after)
    print("ping:", json.dumps({name: [got.get("kind"), _median(got.get("rtts") or [])]
                               for name, got in (("before", before), ("raw", raw),
                                                 ("dgram", dgram), ("after", after))}))
    return failures


def start_tcp_far_end():
    """A TCP listener in the root namespace, in THIS process: the far end a reset reaches."""
    far = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    far.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    far.bind((HOST, RESET_PORT))
    far.listen(4)
    far.settimeout(10)
    return far


def heard(conn, wait):
    """What the far end of a connection hears within ``wait`` s - "reset" or "nothing"
    ("closed" or "data" no reset should bring) - and the far end's socket closed."""
    conn.settimeout(wait)
    try:
        data = conn.recv(16)
    except ConnectionResetError:
        return "reset"
    except TimeoutError:
        return "nothing"
    finally:
        conn.close()
    return "data" if data else "closed"


def held_connection(far, clients, ends):
    """The reset client, connected from the namespace and waiting; and the far end's
    socket of it, or None when it never connected. The client goes on ``clients`` and the
    far end's socket on ``ends`` before anything can fail, so the caller stops and
    closes them on every path."""
    p = subprocess.Popen(in_namespace(sys.executable, "-c", RESET_CLIENT, HOST, str(RESET_PORT)),
                         cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True)
    clients.append(p)
    if p.stdout.readline().strip() != "ready":
        return p, None
    try:
        conn = far.accept()[0]
    except OSError:                 # the far end's 10 s wait ran out
        return p, None
    ends.append(conn)
    return p, conn


def fire(client, conn, wait):
    """Reset the held connection: the client's report, and what the far end heard."""
    client.stdin.write("go\n")
    client.stdin.flush()
    got = json.loads(client.stdout.readline() or "{}")
    got["far"] = heard(conn, wait)
    return got


def _reset_phase():
    far = start_tcp_far_end()
    clients, ends = [], []
    try:
        client, conn = held_connection(far, clients, ends)
        plain = fire(client, conn, 2.0) if conn else {"outcome": "never connected"}
        # Connected BEFORE the session: --loss 100 would keep a new connection out. The
        # far end listens 1.5 s of a 6 s session.
        client, conn = held_connection(far, clients, ends)
        if conn is None:
            return ["reset under loss: the client never connected"]
        result, lines, code = run_session(
            ["--dst-ip", HOST, "--dst-port", str(RESET_PORT), "--loss", "100", "--duration", "6"],
            lambda: fire(client, conn, 1.5))
        failures = _session_failures("reset", result, lines, code)
        r = subprocess.run(in_namespace(sys.executable, "-c", STALE_CLIENT), cwd=ROOT,
                           capture_output=True, text=True, timeout=30)
        stale = json.loads(r.stdout.strip() or "{}")
        failures += judge_reset(plain, result or {}, stale)
        print("reset:", json.dumps({"plain": plain, "under loss": result, "stale": stale}))
        return failures
    finally:
        for client in clients:
            if client.poll() is None:
                client.kill()
            client.wait(10)
        for conn in ends:           # closed already by heard(), unless a step failed first
            conn.close()
        far.close()


def start_tcp_echo(port):
    """A TCP echo in the root namespace, in THIS process: the far end TCP health watches."""
    far = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    far.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    far.bind((HOST, port))
    far.listen(4)

    def serve():
        try:
            conn = far.accept()[0]
        except OSError:             # closed before anyone connected
            return
        with conn:
            conn.sendall(HEALTH_GREETING)
            while data := conn.recv(4096):
                conn.sendall(data)
    threading.Thread(target=serve, daemon=True).start()
    return far


def _health_phase():
    far = start_tcp_echo(HEALTH_PORT)
    client = subprocess.Popen(
        in_namespace(sys.executable, "-c", HEALTH_CLIENT, HOST, str(HEALTH_PORT),
                     str(HEALTH_ROUNDS), str(len(HEALTH_GREETING))),
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True)
    try:
        watched = json.loads(client.stdout.readline() or "{}")

        def during():
            client.stdin.write("go\n")
            client.stdin.flush()
            return json.loads(client.stdout.readline() or "{}")
        result, lines, code = run_session(
            ["--dst-ip", HOST, "--dst-port", str(HEALTH_PORT), "--latency", str(LATENCY_MS),
             "--duration", "10"], during)
        failures = _session_failures("tcp health", result, lines, code)
        failures += judge_health(watched, result or {})
        print("tcp health:", json.dumps({"watched": {k: watched.get(k) for k in
                                                     ("state", "srtt", "rto", "mss")},
                                         "during": result}))
        return failures
    finally:
        if client.poll() is None:
            client.kill()
        client.wait(10)
        far.close()


def _read_adapters(argv):
    r = subprocess.run([*argv, sys.executable, "-c", ADAPTERS_CLIENT], cwd=ROOT,
                       capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout.strip() or "{}")


def _adapters_phase():
    """The Adapters tool in the namespace, with an address in each state it names, and on
    this machine as it is - each against ``ip -j``. Everything made here is the
    namespace's and goes with it."""
    dummy, pair = f"{NS}-d", (f"{NS}-a", f"{NS}-b")
    _ip("-n", NS, "link", "add", dummy, "type", "dummy")
    _ip("-n", NS, "link", "set", dummy, "up")
    _ip("-n", NS, "addr", "add", f"{LEASED}/24", "dev", dummy, "valid_lft", "300",
        "preferred_lft", "100")
    _ip("-n", NS, "addr", "add", f"{DEPRECATED}/24", "dev", dummy, "valid_lft", "300",
        "preferred_lft", "0")
    _ip("-n", NS, "link", "add", pair[0], "type", "veth", "peer", "name", pair[1])
    for end in pair:
        _ip("-n", NS, "link", "set", end, "up")
    _ip("-n", NS, "addr", "add", f"{DUPLICATE6}/64", "dev", pair[0], "nodad")
    _ip("-n", NS, "addr", "add", f"{DUPLICATE6}/64", "dev", pair[1])
    _ip("-n", NS, "route", "add", "default", "via", HOST)
    for _ in range(50):                     # DAD takes about a second
        shown = subprocess.run(["ip", "-n", NS, "-j", "addr", "show", "dev", pair[1]],
                               capture_output=True, text=True, timeout=10).stdout
        if '"dadfailed"' in shown:
            break
        time.sleep(0.1)
    inside = _read_adapters(in_namespace())
    outside = _read_adapters([])
    # The namespace is this script's own, documentation addresses; of the machine itself
    # only how many adapters it has - its addresses and names stay out of the log.
    print("adapters:", json.dumps({"namespace": inside.get("product"),
                                   "this machine": len(outside.get("product", []))}))
    return judge_adapters(inside, "in the namespace", states=True) + judge_adapters(
        outside, "on this machine", private=True)


def main(argv=None, environment=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--require", action="store_true",
                        help="fail instead of skipping when this machine cannot run the check")
    args = parser.parse_args(argv)
    if environment is None:
        try:
            from pydivert import bpf
            loaded = bpf.libebpfdivert is not None
        except ImportError:
            loaded = False
        environment = (sys.platform, os.geteuid() if hasattr(os, "geteuid") else -1, loaded)
    reason = skip_reason(*environment)
    if reason:
        print(("FAIL" if args.require else "SKIP") + f": {reason}")
        return 1 if args.require else 0

    failures = []
    build_namespace()
    try:
        start_far_end()
        failures += _latency_phase()
        failures += _loss_phase()
        failures += _ping_phase()
        failures += _reset_phase()
        failures += _health_phase()
        failures += _adapters_phase()       # last: it gives the namespace a default route
    except Exception as exc:                      # a phase that could not run is a failure
        failures.append(f"{type(exc).__name__}: {exc}")
    finally:
        teardown_namespace()
    for failure in failures:
        print("FAIL:", failure)
    print("OK" if not failures else f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
