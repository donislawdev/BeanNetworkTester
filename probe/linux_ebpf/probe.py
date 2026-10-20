"""eBPFDivert (pydivert 4.0.0 on Linux) measured against what BeanNetworkTester needs.

Runs as root INSIDE the network namespace ``bntp`` (run.sh puts it there), so
every TC hook it attaches lands on ``bntp-c`` and that namespace's ``lo`` - never
on the machine's real interfaces. The far end (far_end.py) lives in the root
namespace at 10.231.0.1. Every measurement prints one JSON line and carries a
control that could have failed.

    probe.py env|pass|isolation|drop|delay|modify|rst|socket|superset|filters|crash|rate
"""
import argparse
import heapq
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time

import pydivert
from pydivert import EBPFDivert, Flag, Layer

SERVER, CLIENT = "10.231.0.1", "10.231.0.2"
TCP_ECHO, UDP_ECHO, UDP_ECHO2, UDP_DISCARD, UDP_COUNT = 47001, 47002, 47004, 47005, 47006
IFACES = ["bntp-c"]
NARROW = f"ip.DstAddr == {SERVER} or ip.SrcAddr == {SERVER}"
SRC = os.environ["BNT_SRC"]          # the product source tree (run.sh requires it)


def out(name, **kv):
    print(json.dumps({"test": name, **kv}, default=str), flush=True)


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))], 3)


def divert(filt, **kw):
    kw.setdefault("interfaces", IFACES)
    return EBPFDivert(filt, **kw)


class Loop:
    """recv -> decide -> send on ONE handle, in one thread (no concurrent send).

    ``decide(pkt)`` returns None (pass now), "drop", or a delay in seconds.
    """

    def __init__(self, handle, decide=None, record=None):
        self.d, self.decide, self.record = handle, decide, record
        self.stop = threading.Event()
        self.n = self.sent = 0
        self.errors = []
        self.heap, self.seq = [], 0
        self.recv_ns = []
        self.t = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.stop.is_set():
            now = time.monotonic()
            while self.heap and self.heap[0][0] <= now:
                self._send(heapq.heappop(self.heap)[2])
            try:
                p = self.d.recv(timeout=0.001 if self.heap else 0.05)
            except TimeoutError:
                continue
            except OSError as e:
                if not self.stop.is_set():
                    self.errors.append(repr(e))
                return
            self.n += 1
            if self.record:
                self.record(p)
            verdict = self.decide(p) if self.decide else None
            if verdict == "drop":
                continue
            if verdict:
                self.seq += 1
                heapq.heappush(self.heap, (time.monotonic() + verdict, self.seq, p))
                continue
            self._send(p)
        while self.heap:
            self._send(heapq.heappop(self.heap)[2])

    def _send(self, p):
        try:
            self.d.send(p)
            self.sent += 1
        except OSError as e:
            self.errors.append(repr(e))

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.t.join(3)


def udp_rtts(n, port=UDP_ECHO, size=64, gap=0.002, timeout=0.5, payload=None):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    rtts, got = [], []
    for i in range(n):
        body = payload if payload is not None else (b"%06d" % i).ljust(size, b"A")
        t0 = time.perf_counter()
        s.sendto(body, (SERVER, port))
        try:
            data, _ = s.recvfrom(65536)
            rtts.append((time.perf_counter() - t0) * 1000)
            got.append(data)
        except socket.timeout:
            pass
        time.sleep(gap)
    s.close()
    return rtts, got


def tcp_exchange(n, size=100):
    c = socket.create_connection((SERVER, TCP_ECHO), timeout=2)
    ok = 0
    for i in range(n):
        body = (b"%06d" % i).ljust(size, b"T")
        c.sendall(body)
        buf = b""
        while len(buf) < size:
            buf += c.recv(size - len(buf))
        ok += buf == body
    c.close()
    return ok


# --------------------------------------------------------------------------- #
def t_env(_):
    from pydivert import bpf
    lib = bpf.libebpfdivert
    filters = {
        "narrow": NARROW,
        "product_both": "(ip or ipv6) and (tcp or udp or icmp or icmpv6)",
        "product_narrowed": f"((ip or ipv6) and (tcp or udp or icmp or icmpv6)) and "
                            f"(ip.DstAddr == {SERVER} or ip.SrcAddr == {SERVER})",
        "rich_payload_len": f"ip.DstAddr == {SERVER} and udp.PayloadLength > 100",
        "loopback_kw": "loopback and tcp",
        "processId_at_network": "processId == 1",
        "garbage": "tcp.DstPort ==",
    }
    checks = {k: EBPFDivert.check_filter(v) for k, v in filters.items()}
    out("env", pydivert=pydivert.__version__, file=pydivert.__file__,
        lib=lib.ebpfdivert_version().decode() if lib else None,
        uname=os.uname().release, euid=os.geteuid(),
        registered=EBPFDivert.is_registered(), check_filter=checks,
        env_var=os.environ.get("PYDIVERT_EBPFDIVERT_LIB"))


def t_pass(_):
    base_rtt, _ = udp_rtts(50)
    base_tcp = tcp_exchange(50)
    meta = {"out": 0, "in": 0, "loopback": 0, "impostor": 0, "sniffed": 0,
            "ifaces": set(), "waits_us": [], "lens": []}

    def record(p):
        meta["out" if p.is_outbound else "in"] += 1
        meta["loopback"] += bool(p.is_loopback)
        meta["impostor"] += bool(p.is_impostor)
        meta["sniffed"] += bool(p.is_sniffed)
        meta["ifaces"].add(tuple(p.interface))
        meta["waits_us"].append((time.monotonic_ns() - p.timestamp) / 1000)
        meta["lens"].append(len(p.raw))

    with divert(NARROW) as d, Loop(d, record=record) as loop:
        time.sleep(0.2)
        rtt, got = udp_rtts(200)
        tcp_ok = tcp_exchange(200)
        time.sleep(0.2)
        stats = d.stats()
    udp_ok = sum(g == (b"%06d" % i).ljust(64, b"A") for i, g in enumerate(got))
    waits = meta.pop("waits_us")
    out("pass", control_udp=len(base_rtt), control_tcp=base_tcp,
        udp_echoed=len(got), udp_identical=udp_ok, tcp_identical=tcp_ok,
        captured=loop.n, reinjected=loop.sent, errors=loop.errors[:3],
        rtt_ms_base_p50=pct(base_rtt, 50), rtt_ms_p50=pct(rtt, 50), rtt_ms_p99=pct(rtt, 99),
        wait_us_p50=pct(waits, 50), wait_us_p99=pct(waits, 99), wait_us_min=pct(waits, 0),
        max_len=max(meta.pop("lens") or [0]), stats=stats, **meta)


def t_drop(_):
    with divert(NARROW) as d, Loop(d) as ctl:
        time.sleep(0.2)
        control, _ = udp_rtts(200, timeout=0.2)
    toggle = [0]

    def every_second_out(p):
        if p.is_outbound and p.udp is not None:
            toggle[0] ^= 1
            return "drop" if toggle[0] else None
        return None

    with divert(NARROW) as d, Loop(d, decide=every_second_out) as loop:
        time.sleep(0.2)
        rtts, _ = udp_rtts(200, timeout=0.2)
    out("drop", control_echoed=len(control), echoed=len(rtts), expected=100,
        captured=loop.n, errors=loop.errors[:3] + ctl.errors[:3])


def t_delay(_):
    def hold_out(p):
        return 0.050 if p.is_outbound else None

    with divert(NARROW) as d, Loop(d) as ctl:
        time.sleep(0.2)
        base, _ = udp_rtts(100, gap=0.01)
    with divert(NARROW) as d, Loop(d, decide=hold_out) as loop:
        time.sleep(0.2)
        held, _ = udp_rtts(100, gap=0.01, timeout=1.0)
    out("delay", added_ms_wanted=50, base_p50=pct(base, 50), base_p99=pct(base, 99),
        held_p50=pct(held, 50), held_p99=pct(held, 99), held_min=pct(held, 0),
        held_n=len(held), errors=loop.errors[:3] + ctl.errors[:3])


def t_modify(_):
    def flip(p):
        if p.is_outbound and p.udp is not None and p.payload:
            pl = bytearray(p.payload)
            pl[0] = ord("B")
            p.payload = bytes(pl)
        return None

    payload = b"A" * 64
    with divert(NARROW) as d, Loop(d) as ctl:
        time.sleep(0.2)
        _, control = udp_rtts(50, payload=payload)
    with divert(NARROW) as d, Loop(d, decide=flip) as loop:
        time.sleep(0.2)
        _, got = udp_rtts(50, payload=payload)
    out("modify", control_echoed=len(control),
        control_modified=sum(g[:1] == b"B" for g in control),
        echoed=len(got), modified=sum(g[:1] == b"B" and g[1:] == payload[1:] for g in got),
        errors=loop.errors[:3] + ctl.errors[:3])


def _product_core():
    sys.path.insert(0, SRC)
    from beantester.core import BeanCore
    return BeanCore


def _rst_case(server_addr, filt, label, **kw):
    """Open a TCP connection, catch the client's next data segment, answer it with
    the product's own RST (build_rst_fields + build_rst_packet), drop the segment."""
    BeanCore = _product_core()
    srv = None
    if server_addr[0].startswith("127."):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(server_addr)
        srv.listen(4)
        threading.Thread(target=lambda: _echo_once(srv), daemon=True).start()
    result = {}
    for inject in (False, True):
        c = socket.create_connection(server_addr, timeout=2)
        c.sendall(b"warmup")
        c.recv(64)
        done = threading.Event()
        seen = {}
        with divert(filt, **kw) as d:
            def worker():
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    try:
                        p = d.recv(timeout=0.1)
                    except TimeoutError:
                        continue
                    is_data = (p.tcp is not None and p.is_outbound and p.payload
                               and p.dst_port == server_addr[1])
                    if is_data and not seen:
                        seen.update(loopback=bool(p.is_loopback), iface=tuple(p.interface))
                        if inject:
                            fields = BeanCore.build_rst_fields(p)
                            rst = BeanCore.build_rst_packet(p, fields)
                            seen["rst_dir"] = str(rst.direction)
                            seen["rst_sent"] = d.send(rst)
                            done.set()
                            continue          # the segment itself is dropped
                        done.set()
                    d.send(p)
            th = threading.Thread(target=worker, daemon=True)
            th.start()
            time.sleep(0.2)
            t0 = time.perf_counter()
            outcome = "?"
            try:
                c.sendall(b"probe-data")
                data = c.recv(64)
                outcome = "echo" if data else "eof"
                if inject:
                    c.sendall(b"again")
                    data = c.recv(64)
                    outcome = "echo-after-rst" if data else "eof-after-rst"
            except ConnectionResetError:
                outcome = "ECONNRESET"
            except socket.timeout:
                outcome = "timeout"
            except OSError as e:
                outcome = f"OSError {e.errno}"
            ms = round((time.perf_counter() - t0) * 1000, 1)
            th.join(4)
        c.close()
        result["inject" if inject else "control"] = dict(outcome=outcome, ms=ms, **seen)
    if srv:
        srv.close()
    out("rst", case=label, **result)


def _echo_once(srv):
    while True:
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        threading.Thread(target=_tcp_conn, args=(conn,), daemon=True).start()


def _tcp_conn(conn):
    with conn:
        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    return
                conn.sendall(data)
        except OSError:
            return


def t_rst(_):
    _rst_case((SERVER, TCP_ECHO), NARROW, "veth")
    _rst_case(("127.0.0.1", 47003), "loopback and tcp and (tcp.DstPort == 47003 or tcp.SrcPort == 47003)",
              "loopback", interfaces=None)   # an interface list leaves lo out (measured)


def t_socket(_):
    events = []
    with EBPFDivert("tcp or udp", layer=Layer.SOCKET, flags=Flag.SNIFF | Flag.RECV_ONLY) as d:
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    p = d.recv(timeout=0.1)
                except TimeoutError:
                    continue
                except OSError:
                    return
                s = p.socket
                if s is None:
                    continue
                events.append(dict(event=str(p.event), pid=int(s.ProcessId),
                                   lport=int(s.LocalPort), rport=int(s.RemotePort),
                                   ep=int(s.EndpointId), parent=int(s.ParentEndpointId),
                                   proto=int(s.Protocol)))
        th = threading.Thread(target=reader, daemon=True)
        th.start()
        time.sleep(0.3)
        child = subprocess.Popen([sys.executable, "-c", (
            "import socket,time\n"
            f"c=socket.create_connection(('{SERVER}',{TCP_ECHO}));c.sendall(b'x');c.recv(8)\n"
            "u=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);u.bind(('0.0.0.0',47010))\n"
            "l=socket.socket();l.bind(('127.0.0.1',47011));l.listen(1)\n"
            "time.sleep(0.3);c.close();u.close();l.close()\n")])
        child.wait(5)
        time.sleep(0.5)
        stop.set()
        th.join(2)
    mine = [e for e in events if e["pid"] == child.pid]
    ports = {TCP_ECHO, 47010, 47011}
    by_port = [e for e in events if e["lport"] in ports or e["rport"] in ports]
    with open("/proc/self/status") as f:
        nspid = [line.strip() for line in f if line.startswith("NSpid")]
    out("socket", total_events=len(events), child_pid=child.pid, child_events=mine[:20],
        events_on_child_ports=by_port[:20], own_pid=os.getpid(), own_nspid=nspid,
        pid_ns=os.readlink("/proc/self/ns/pid"), pid1_ns=os.readlink("/proc/1/ns/pid"))


def t_superset(_):
    """Does traffic OUTSIDE a filter depend on this process reading?"""
    res = {}
    for label, filt in (("simple", f"ip.DstAddr == {SERVER} and udp.DstPort == {UDP_ECHO2}"),
                        ("rich", f"ip.DstAddr == {SERVER} and udp.PayloadLength > 100")):
        with divert(filt) as d:
            time.sleep(0.2)
            # nobody calls recv: a packet the KERNEL handed up is stuck until we do
            stalled, _ = udp_rtts(20, port=UDP_ECHO, size=40, gap=0.02, timeout=0.2)
            seen = []
            with Loop(d, record=lambda p: seen.append(len(p.payload or b""))) as loop:
                time.sleep(0.1)
                small_rtt, _ = udp_rtts(50, port=UDP_ECHO, size=40)
                big_rtt, _ = udp_rtts(50, port=UDP_ECHO, size=200)
                time.sleep(0.2)
            stats = d.stats()
        res[label] = dict(small_echoed_while_not_reading=len(stalled), small_echoed=len(small_rtt),
                          small_p50=pct(small_rtt, 50), big_echoed=len(big_rtt), big_p50=pct(big_rtt, 50),
                          handed_up=loop.n, handed_up_small=sum(n <= 100 for n in seen),
                          diverted=stats.get("diverted"))
    out("superset", **res)


def t_crash(_):
    code = ("import sys,time\nfrom pydivert import EBPFDivert\n"
            f"d=EBPFDivert({NARROW!r}, interfaces={IFACES!r});d.open()\n"
            "print('OPEN',flush=True)\ntime.sleep(60)\n")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.05)

    def ping():
        s.sendto(b"crash-probe", (SERVER, UDP_ECHO))
        try:
            s.recvfrom(64)
            return True
        except socket.timeout:
            return False
    before = sum(ping() for _ in range(10))
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "OPEN"
    time.sleep(0.2)
    while_held = sum(ping() for _ in range(10))
    os.kill(child.pid, signal.SIGKILL)
    child.wait()
    t0 = time.monotonic()
    back = None
    while time.monotonic() - t0 < 10:
        if ping():
            back = round(time.monotonic() - t0, 3)
            break
    reopen = None
    try:
        with divert(NARROW) as d, Loop(d) as loop:
            time.sleep(0.2)
            r, _ = udp_rtts(10)
        reopen = dict(echoed=len(r), captured=loop.n)
    except Exception as e:
        reopen = repr(e)
    out("crash", echoed_before=before, echoed_while_child_holds=while_held,
        traffic_back_after_s=back, reopen=reopen)


_ROOT_NS_CANARY = (
    "import socket,time\n"
    "s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(0.3);ok=0\n"
    "for i in range(10):\n"
    f"    s.sendto(b'canary',('{SERVER}',{UDP_ECHO}))\n"
    "    try: s.recvfrom(64); ok+=1\n"
    "    except OSError: pass\n"
    "t=time.perf_counter()\n"
    "try: socket.getaddrinfo('pypi.org',443); dns='ok'\n"
    "except OSError as e: dns=repr(e)\n"
    "print(ok, dns, round((time.perf_counter()-t)*1000,1))\n")


def _root_ns_canary():
    r = subprocess.run(["nsenter", "-t", "1", "-n", sys.executable, "-c", _ROOT_NS_CANARY],
                       capture_output=True, text=True, timeout=20)
    return (r.stdout.strip() or r.stderr.strip()[-200:])


def t_isolation(_):
    """A handle that takes EVERYTHING in this namespace and never reads it: the
    namespace goes dark (the control), the root namespace does not (the claim)."""
    before = _root_ns_canary()
    with EBPFDivert("true") as d:              # no interface list: all of THIS namespace
        time.sleep(0.2)
        inside, _ = udp_rtts(10, timeout=0.2)
        during = _root_ns_canary()
        inside_lo = _ns_lo_echo()
    out("isolation", root_ns_before=before, root_ns_during=during,
        ns_echoed_while_held=len(inside), ns_loopback_while_held=inside_lo,
        expect="root ns '10 ok', namespace 0")


def _ns_lo_echo():
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 47012))
    c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    c.settimeout(0.2)
    c.sendto(b"lo", ("127.0.0.1", 47012))
    srv.settimeout(0.2)
    try:
        srv.recvfrom(16)
        got = True
    except OSError:
        got = False
    srv.close()
    c.close()
    return got


# --------------------------------------------------------------------------- #
# filters: which of the PRODUCT's filter shapes does the kernel take EXACTLY?
#
# A shape the kernel can only widen makes traffic the filter does NOT match wait on
# this process (measured in `superset`). Each case opens the product's own filter
# text, never reads, and sends one flow the filter does not match (must still flow)
# and one it does (must stall - the control that proves the handle is attached).

def _echo_count(addr, port, n=10, size=40, family=socket.AF_INET, timeout=0.2):
    s = socket.socket(family, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    got = 0
    for i in range(n):
        s.sendto(b"f" * size, (addr, port))
        try:
            s.recvfrom(65536)
            got += 1
        except OSError:
            pass
    s.close()
    return got


def _tcp_ok(addr, port):
    try:
        c = socket.create_connection((addr, port), timeout=0.5)
        c.settimeout(0.5)
        c.sendall(b"t")
        ok = c.recv(8) == b"t"
        c.close()
        return int(ok)
    except OSError:
        return 0


def _ping_count(addr):
    r = subprocess.run(["ping", "-c", "3", "-i", "0.2", "-W", "1", addr], capture_output=True, text=True)
    return sum("bytes from" in line for line in r.stdout.splitlines())


def _lo_count(n=10):
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 47013))
    srv.settimeout(0.2)
    c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    got = 0
    for _ in range(n):
        c.sendto(b"lo", ("127.0.0.1", 47013))
        try:
            srv.recvfrom(16)
            got += 1
        except OSError:
            pass
    srv.close()
    c.close()
    return got


def _discard_then_count(n=10):
    """Outbound only: n datagrams to the discard port; the count is asked AFTER the
    handle closes (its answer is inbound and would be held)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for _ in range(n):
        s.sendto(b"d", (SERVER, UDP_DISCARD))
    s.close()

    def later():
        q = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        q.settimeout(1)
        q.sendto(b"?", (SERVER, UDP_COUNT))
        try:
            return int(q.recvfrom(64)[0])
        finally:
            q.close()
    return later


_INBOUND_SENDER = (
    "import socket\n"
    "s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)\n"
    f"[s.sendto(b'i',('{CLIENT}',47040)) for _ in range(10)]\n")


def _inbound_only_count():
    """Inbound only: the ROOT namespace sends 10 datagrams in; nothing goes back."""
    r = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    r.bind((CLIENT, 47040))
    r.settimeout(0.3)
    subprocess.run(["nsenter", "-t", "1", "-n", sys.executable, "-c", _INBOUND_SENDER], timeout=10)
    got = 0
    for _ in range(10):
        try:
            r.recvfrom(16)
            got += 1
        except OSError:
            break
    r.close()
    return got


def t_filters(_):
    sys.path.insert(0, SRC)
    from beantester import filters as F
    from beantester.matchers import KIND_INT, KIND_IP, parse_matcher
    from beantester.core import port_expression
    # Probe only: the product asks WinDivert's DLL whether a filter compiles, which is
    # always False off Windows - so --narrow-filter never narrows there.
    F.filter_compiles = lambda text: bool(text) and EBPFDivert.check_filter(text)[0]

    def narrowed(ip="", port=""):
        text, ok = F.narrowed_filter(F.CLI_FILTERS["both"], parse_matcher(ip, KIND_IP, "fields.ip"),
                                     parse_matcher(port_expression(port), KIND_INT, "fields.port"))
        return text if ok else None

    v6 = socket.AF_INET6
    B = F.CLI_FILTERS
    cases = [
        ("tcp", B["tcp"], lambda: _echo_count(SERVER, UDP_ECHO), lambda: _tcp_ok(SERVER, TCP_ECHO), 10),
        ("udp", B["udp"], lambda: _tcp_ok(SERVER, TCP_ECHO), lambda: _echo_count(SERVER, UDP_ECHO), 1),
        ("ping", B["ping"], lambda: _echo_count(SERVER, UDP_ECHO), lambda: _ping_count(SERVER), 10),
        ("loopback", B["loopback"], lambda: _echo_count(SERVER, UDP_ECHO), _lo_count, 10),
        ("in", B["in"], _discard_then_count, lambda: _echo_count(SERVER, UDP_ECHO), 10),
        ("out", B["out"], _inbound_only_count, lambda: _echo_count(SERVER, UDP_ECHO), 10),
        ("ip 10.231.0.1", narrowed(ip=SERVER), lambda: _echo_count("10.231.0.3", UDP_ECHO),
         lambda: _echo_count(SERVER, UDP_ECHO), 10),
        ("ip 10.231.0.0/31", narrowed(ip="10.231.0.0/31"), lambda: _echo_count("10.231.0.3", UDP_ECHO),
         lambda: _echo_count(SERVER, UDP_ECHO), 10),
        ("ip list", narrowed(ip="10.231.0.1, 10.231.0.5"), lambda: _echo_count("10.231.0.3", UDP_ECHO),
         lambda: _echo_count(SERVER, UDP_ECHO), 10),
        ("ipv6 fd00:231::1", narrowed(ip="fd00:231::1"),
         lambda: _echo_count("fd00:231::3", UDP_ECHO, family=v6),
         lambda: _echo_count("fd00:231::1", UDP_ECHO, family=v6), 10),
        ("port 47002", narrowed(port="47002"), lambda: _echo_count(SERVER, UDP_ECHO2),
         lambda: _echo_count(SERVER, UDP_ECHO), 10),
        ("port range", narrowed(port="47001-47002"), lambda: _echo_count(SERVER, UDP_ECHO2),
         lambda: _echo_count(SERVER, UDP_ECHO), 10),
        ("port list", narrowed(port="47002, 47009"), lambda: _echo_count(SERVER, UDP_ECHO2),
         lambda: _echo_count(SERVER, UDP_ECHO), 10),
        ("ip+port", narrowed(ip=SERVER, port="47002"), lambda: _echo_count("10.231.0.3", UDP_ECHO),
         lambda: _echo_count(SERVER, UDP_ECHO), 10),
        ("ip+port, other port", narrowed(ip=SERVER, port="47002"), lambda: _echo_count(SERVER, UDP_ECHO2),
         lambda: _echo_count(SERVER, UDP_ECHO), 10),
        ("FRAGMENTS, port 47002", narrowed(port="47002"),
         lambda: _echo_count(SERVER, UDP_ECHO2, n=5, size=3000, timeout=0.3),
         lambda: _echo_count(SERVER, UDP_ECHO), 5),
        ("FRAGMENTS, ip 10.231.0.1", narrowed(ip=SERVER),
         lambda: _echo_count("10.231.0.3", UDP_ECHO, n=5, size=3000, timeout=0.3),
         lambda: _echo_count(SERVER, UDP_ECHO), 5),
    ]
    for name, filt, nonmatch, match, total in cases:
        if filt is None:
            out("filters", case=name, filter=None, note="the product did not narrow")
            continue
        ok = EBPFDivert.check_filter(filt)
        before = nonmatch()
        before = before() if callable(before) else before
        with EBPFDivert(filt) as d:            # no interface list: lo included
            time.sleep(0.2)
            nm = nonmatch()
            m = match()
            stats = d.stats()
        nm = nm() if callable(nm) else nm
        out("filters", case=name, compiles=ok[0], nonmatching_flowed=f"{nm}/{total}",
            control_before=f"{before}/{total}", matching_flowed=m, diverted=stats.get("diverted"),
            verdict="EXACT" if nm == total and not m else
                    ("SUPERSET" if nm < total and before == total and not m else "UNCLEAR"),
            filter=filt)


_SENDER = (
    "import socket,sys,time\n"
    "secs,pps=float(sys.argv[1]),int(sys.argv[2])\n"
    "s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);body=b'R'*64;n=0\n"
    "end=time.monotonic()+secs;gap=1.0/pps if pps else 0;nxt=time.monotonic()\n"
    "while time.monotonic()<end:\n"
    f"    try: s.sendto(body,('{SERVER}',{UDP_DISCARD})); n+=1\n"
    "    except OSError: pass\n"
    "    if gap:\n"
    "        nxt+=gap\n"
    "        while time.monotonic()<nxt: pass\n"
    "print(n)\n")


def t_rate(a):
    def count():
        q = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        q.settimeout(1)
        q.sendto(b"?", (SERVER, UDP_COUNT))
        n = int(q.recvfrom(64)[0])
        q.close()
        return n
    res = {}
    for label in ("no_divert", "passthrough", "passthrough_norecalc"):
        count()
        handle = divert(f"ip.DstAddr == {SERVER} and udp.DstPort == {UDP_DISCARD}") if label != "no_divert" else None
        cost = []
        if handle:
            handle.open()

        def loop_fn():
            while not stop.is_set():
                try:
                    p = handle.recv(timeout=0.05)
                except TimeoutError:
                    continue
                t0 = time.perf_counter_ns()
                handle.send(p, recalculate_checksum=label == "passthrough")
                cost.append(time.perf_counter_ns() - t0)
                proc[0] += 1
        stop, proc = threading.Event(), [0]
        th = threading.Thread(target=loop_fn, daemon=True) if handle else None
        if th:
            th.start()
        time.sleep(0.2)
        # The sender is its OWN process: in this one it spun on the GIL and starved
        # the divert thread (first run: 5.5k processed at a 10k target, 9.7k unpaced).
        r = subprocess.run([sys.executable, "-c", _SENDER, str(a.seconds), str(a.pps)],
                           capture_output=True, text=True, timeout=a.seconds + 10)
        sent = int(r.stdout.strip() or 0)
        time.sleep(0.5)
        stop.set()
        if th:
            th.join(2)
        st = handle.stats() if handle else {}
        if handle:
            handle.close()
        got = count()
        res[label] = dict(sent=sent, received=got, processed=proc[0],
                          send_pps=round(sent / a.seconds), recv_pps=round(got / a.seconds),
                          send_us_p50=pct([c / 1000 for c in cost], 50),
                          stats={k: st.get(k) for k in ("diverted", "dropped", "ringbuf_full", "queue_full")})
    out("rate", seconds=a.seconds, target_pps=a.pps, **res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("test")
    ap.add_argument("--seconds", type=float, default=3)
    ap.add_argument("--pps", type=int, default=0)
    a = ap.parse_args()
    globals()["t_" + a.test](a)


if __name__ == "__main__":
    main()
