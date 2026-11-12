"""Port scan: which ports of another computer answer, and how - no tkinter.

"Is my server reachable on 8443 from here?", "what does this device listen on?" - the
question Port check cannot answer, because Port check asks THIS computer. This tool
asks the computer at the address the person typed, port by port, the way any program
that connects would: a TCP connection (closed again at once, nothing sent on it) or
a UDP datagram per port, and once more for a port the second round asks again. No raw
packets and no administrator rights for the scan itself.

What is sent, and where, is the promise this tool is held to (README, "Tools"): to the
ONE address typed (a name is looked up once, at Start, by Ping's reading of a name),
on the ports typed, from Start to the end or Stop. Any address may be scanned (the
owner's decision, 2026-11-11); the help says to scan only machines you may test.

Measured 2026-11-11 on Windows, Linux, macOS and LAN devices, and the reasons the code
is the way it is:

* **Windows tries a refused connection again**: a closed port costs 2 s, not 0.2 ms.
  ``SIO_TCP_INITIAL_RTO`` with no SYN retransmissions turns that off, with no
  administrator rights, and its ``Rtt`` is when Windows gives up on a silent port -
  so it is set to this scan's wait. ``TCP_MAXRT`` is NOT a substitute: a refused port
  then reads as a time-out (10060 after 500 ms, measured 2026-11-12).
* **Pace.** A computer in a network this one is attached to (an adapter's prefix)
  answers within milliseconds: 256 at once, 1 s each. Anything behind a router goes
  through its connection table, and every silent port holds an entry there for up to
  120 s (Linux conntrack's SYN_SENT time-out): 32 at once, at most 20 new a second,
  3 s each (the owner's choice, 2026-11-11).
* **A second round** recovers ports a host was too busy to answer - macOS limits its
  RSTs to a bucket per 200 ms, and from Linux a second round recovered an OPEN port.
  When almost everything is silent (a firewall) it costs as much as the first round
  and recovers nothing, so it runs only when the silent ports are a small minority.
* **UDP** shows "open" only when a service answers, so a known service gets a real
  request (DNS, NTP, NetBIOS, mDNS, SSDP) and every other port an empty datagram.
  "Closed" is the ICMP "port unreachable" the system passes to the socket - except on
  Windows, whose firewall keeps it from every program. WinDivert sees it anyway
  (10/10, elevated): with administrator rights the scan opens a sniff-only handle for
  ICMP from the scanned address (``_Sniffer``); without them it says why no UDP port
  reads as closed.
* ``select()`` on Windows takes 512 sockets at most; the pace stays at half of that.
"""
import collections
import errno
import ipaddress
import selectors
import socket
import struct
import sys
import threading
import time
from typing import NamedTuple

from .. import crashlog, icmpsock, winenv
from ..matchers import KIND_INT, PORT_BOUNDS, parse_matcher
from . import Refused, adapters, ping, portcheck

AREA = "nettools.portscan"
WIN = sys.platform.startswith("win")

TCP, UDP = "TCP", "UDP"
PROTOCOLS = (TCP, UDP)

# What a port answered. On UDP, OPEN means a reply came back and SILENT that nothing
# did - open and quiet, closed without saying so, or blocked: UDP cannot tell those
# apart.
OPEN, CLOSED, SILENT, UNREACHABLE, DENIED, FAILED = (
    "open", "closed", "silent", "unreachable", "denied", "failed")
STATES = (OPEN, CLOSED, SILENT, UNREACHABLE, DENIED, FAILED)

REFUSALS = "tools.portscan.refused."
FIELD = "tools.portscan.ports"
ALL_PORTS = portcheck.ALL_PORTS
WELL_KNOWN = "1-1024"


class Pace(NamedTuple):
    at_once: int            # ports asked at the same time
    per_second: int         # new ports a second; 0 = as fast as answers come
    wait_s: float           # how long a port has to answer
    near: bool              # the computer is in a network this one is attached to


NEAR = Pace(256, 0, 1.0, True)
FAR = Pace(32, 20, 3.0, False)
AGAIN_AT_ONCE = 32          # the second round asks fewer at once: it is for a busy host
AGAIN_SHARE = 10            # percent: a second round only when at most this share was silent
GIVE_UP_AFTER = 64          # unreachable answers and none but silence: the computer is not there
POLL_S = 0.25               # the longest a Stop waits for the scan to notice it

# The service a port usually carries, by protocol: "T" TCP, "U" UDP. Names only - the
# scan never checks what really answers. Our own table, so both systems show the same
# words (a services file differs from machine to machine), and the "Common ports"
# button types exactly these ports.
SERVICES = (
    (21, "FTP", "T"), (22, "SSH", "T"), (23, "Telnet", "T"), (25, "SMTP", "T"),
    (53, "DNS", "TU"), (67, "DHCP", "U"), (68, "DHCP", "U"), (69, "TFTP", "U"),
    (80, "HTTP", "T"), (88, "Kerberos", "TU"), (110, "POP3", "T"), (111, "Portmapper", "TU"),
    (123, "NTP", "U"), (135, "MS-RPC", "T"), (137, "NetBIOS-NS", "U"),
    (138, "NetBIOS-DGM", "U"), (139, "NetBIOS-SSN", "T"), (143, "IMAP", "T"),
    (161, "SNMP", "U"), (389, "LDAP", "TU"), (443, "HTTPS", "T"), (443, "QUIC", "U"),
    (445, "SMB", "T"), (465, "SMTPS", "T"), (500, "IKE", "U"), (514, "Syslog", "U"),
    (515, "LPD", "T"), (548, "AFP", "T"), (554, "RTSP", "TU"), (587, "SMTP", "T"),
    (631, "IPP", "TU"), (636, "LDAPS", "T"), (853, "DNS over TLS", "T"), (873, "rsync", "T"),
    (993, "IMAPS", "T"), (995, "POP3S", "T"), (1080, "SOCKS", "T"), (1194, "OpenVPN", "TU"),
    (1433, "SQL Server", "T"), (1521, "Oracle DB", "T"), (1883, "MQTT", "T"),
    (1900, "SSDP", "U"), (2049, "NFS", "TU"), (2375, "Docker", "T"), (2376, "Docker TLS", "T"),
    (3000, "Node.js, Grafana", "T"), (3306, "MySQL", "T"), (3389, "RDP", "TU"),
    (3478, "STUN, TURN", "TU"), (4500, "IPsec NAT-T", "U"), (5000, "Flask, UPnP", "T"),
    (5060, "SIP", "TU"), (5173, "Vite", "T"), (5353, "mDNS", "U"), (5355, "LLMNR", "U"),
    (5432, "PostgreSQL", "T"), (5672, "AMQP", "T"), (5900, "VNC", "T"), (5985, "WinRM", "T"),
    (5986, "WinRM TLS", "T"), (6379, "Redis", "T"), (8000, "Django, Python", "T"),
    (8080, "HTTP", "T"), (8443, "HTTPS", "T"), (8888, "Jupyter", "T"),
    (9000, "PHP-FPM, MinIO", "T"), (9090, "Prometheus", "T"), (9200, "Elasticsearch", "T"),
    (9229, "Node.js debug", "T"), (11211, "Memcached", "TU"), (27017, "MongoDB", "T"),
    (51820, "WireGuard", "U"),
)
_SERVICE = {(port, {"T": TCP, "U": UDP}[letter]): name
            for port, name, letters in SERVICES for letter in letters}
COMMON = tuple(sorted({port for port, _name, _letters in SERVICES}))
# What the "Common ports" button types into the ports box: the port language.
COMMON_TEXT = ", ".join(str(port) for port in COMMON)


def service(port, proto):
    """The service ``port`` usually carries on ``proto`` (``SERVICES``), or ""."""
    return _SERVICE.get((port, proto), "")


# -- what a UDP port is asked -------------------------------------------------- #
def _dns_name(name):
    out = b""
    for label in filter(None, name.split(".")):
        out += bytes([len(label)]) + label.encode("ascii")
    return out + b"\x00"


def _netbios_star():
    """The name "*" padded to 16 bytes, first-level encoded (RFC 1002 4.1)."""
    raw = b"*" + b"\x00" * 15
    return b"\x20" + bytes(c for b in raw for c in (0x41 + (b >> 4), 0x41 + (b & 0xF))) + b"\x00"


# A request each of these services answers; any other port gets an empty datagram, which
# only an echo service answers (measured 2026-11-11). The DNS question is "localhost",
# with recursion desired: a home router answered nothing without it, and a resolver
# answers that name itself (RFC 6761 6.3), so the question goes nowhere further.
PAYLOADS = {
    53: b"\x4b\x4e\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + _dns_name("localhost")
        + struct.pack(">HH", 1, 1),
    123: b"\x23" + b"\x00" * 47,                        # NTP v4, client mode
    137: (b"\x4b\x4e\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00" + _netbios_star()
          + struct.pack(">HH", 0x21, 1)),               # NetBIOS node status
    1900: (b"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
           b"MAN: \"ssdp:discover\"\r\nMX: 1\r\nST: ssdp:all\r\n\r\n"),
    5353: (b"\x4b\x4e\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
           + _dns_name("_services._dns-sd._udp.local") + struct.pack(">HH", 12, 1)),
}


def payload(port):
    return PAYLOADS.get(port, b"")


# -- what was typed -------------------------------------------------------------- #
def _with_zone(target):
    """A link-local IPv6 address names an adapter or it reaches nowhere: refused
    without one, the way the system would refuse every port of it."""
    address = ipaddress.ip_address(target.address)
    if address.version == 6 and address.is_link_local and address.scope_id is None:
        raise Refused(f"{REFUSALS}zone", typed=target.typed)
    return target


def parse_target(text):
    """What was typed, as a ``ping.Target`` - or ``Refused`` saying why it is not one
    computer. UI thread: nothing is looked up and nothing is sent."""
    target = ping.parse(text, REFUSALS)
    return _with_zone(target) if target.address else target


def parse_ports(text):
    """The typed ports as a matcher, in the Control page's port language. Raises
    ``ValueError`` with a message in the window's language."""
    return parse_matcher(text, KIND_INT, FIELD, PORT_BOUNDS)


class Plan(NamedTuple):
    """What one scan asks, decided on the worker before anything is sent."""
    target: ping.Target         # with its address: looked up when a name was typed
    ports: tuple
    protocols: tuple
    pace: Pace
    own: bool                   # this computer's own address (loopback or an adapter's)
    skipped_zero: bool


def _bare(address):
    return ipaddress.ip_address(str(address).split("%", 1)[0])


def where(address, read):
    """``(own, near)``: is ``address`` this computer's, and is it in a network one of
    its adapters is attached to (an adapter's prefix). ``read`` gives the adapter list
    (None where the system has none to give); one that cannot be read answers "not
    near": the slower pace, which is safe anywhere."""
    bare = _bare(address)
    if bare.is_loopback:
        return True, True
    near = bare.version == 6 and bare.is_link_local
    if read is None:
        return False, near
    try:
        snapshot = read()
    except (adapters.Unreadable, OSError):
        return False, near
    except Exception as exc:
        crashlog.note(exc, AREA)
        return False, near
    for adapter in snapshot.adapters:
        for row in adapter.row.addresses:
            mine = _bare(row.ip)
            if mine == bare:
                return True, True
            if row.prefix is not None and mine.version == bare.version:
                near = near or bare in ipaddress.ip_network(f"{mine}/{row.prefix}", strict=False)
    return False, near


def plan(target, matcher, protocols, lookup=None, read=None):
    """The scan to run: the ports listed, the name looked up, the pace chosen. On a
    worker - the lookup can take seconds and listing 65535 ports up to 100 ms."""
    wanted, zero = portcheck.ports(matcher, REFUSALS)
    target = _with_zone(ping.resolve(target, lookup, REFUSALS))
    if read is None and adapters.supported():
        read = adapters.read
    own, near = where(target.address, read)
    return Plan(target, wanted, tuple(protocols), NEAR if near else FAR, own, zero)


def estimate_s(scan_plan):
    """The longest the first round can take: every port silent, at this pace. A
    computer that answers is quicker; a second round adds to it."""
    pace = scan_plan.pace
    count = len(scan_plan.ports) * len(scan_plan.protocols)
    by_rate = count / pace.per_second if pace.per_second else 0.0
    by_waiting = -(-count // pace.at_once) * pace.wait_s
    return max(by_rate, by_waiting)


# -- how far a scan is ----------------------------------------------------------- #
class Progress(portcheck.Progress):
    """Port check's progress with what a scan adds: the open ports found so far, the
    ports asked a second time, and when it started (for the time left). ``at`` is
    ``(proto, port)``."""

    def __init__(self):
        super().__init__()
        self.opened = 0
        self.again = 0          # ports in the second round now; 0 in the first
        self.started = None     # the scan's clock at the start

    def left_s(self, now):
        """Seconds left at the pace so far, or None while there is too little to tell."""
        if self.started is None or self.made < 10 or self.made >= self.planned:
            return None
        spent = now - self.started
        return spent / self.made * (self.planned - self.made) if spent > 0 else None


# -- what the system answered ------------------------------------------------------ #
_REFUSED = frozenset({errno.ECONNREFUSED, 10061})
_RESET = frozenset({errno.ECONNRESET, 10054})
_UNREACHABLE = frozenset({errno.EHOSTUNREACH, errno.ENETUNREACH, 10065, 10051})
_TIMED_OUT = frozenset({errno.ETIMEDOUT, 10060})
_DENIED = frozenset({errno.EACCES, errno.EPERM, 10013})
_IN_PROGRESS = frozenset({errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY,
                          10035, 10036, 10037})


class Answer(NamedTuple):
    state: str
    code: int = 0           # the system's error number; 0 for an answer or silence
    reply: int = 0          # UDP: the bytes of the reply


def classify(code):
    """The state an error number means for a port (0: connected, or a reply)."""
    if not code:
        return Answer(OPEN)
    if code in _REFUSED or code in _RESET:
        return Answer(CLOSED, code)
    if code in _UNREACHABLE:
        return Answer(UNREACHABLE, code)
    if code in _TIMED_OUT:
        # No code: on Windows the system ends a silent try at the scan's own wait
        # (SIO_TCP_INITIAL_RTO's Rtt), so which of the two came first is chance - and
        # a code would split next ports that read the same into rows (measured 2026-11-12).
        return Answer(SILENT)
    if code in _DENIED:
        return Answer(DENIED, code)
    return Answer(FAILED, code)


def _code(exc):
    return getattr(exc, "winerror", None) or exc.errno or 0


# -- the real sockets ------------------------------------------------------------ #
_WS2 = [None]
SIO_TCP_INITIAL_RTO = 0x98000011
NO_SYN_RETRANSMISSIONS = 0xFE   # TCP_INITIAL_RTO_NO_SYN_RETRANSMISSIONS


def _ws2_32():
    """ws2_32's WSAIoctl with its full prototype, or None off Windows. Cached.

    The one call this program makes into Winsock directly: Python's ``socket.ioctl``
    knows three control codes and SIO_TCP_INITIAL_RTO is not one of them. It sets how
    a connection attempt is retried and sends nothing itself.
    """
    if _WS2[0] is not None:
        return _WS2[0] or None
    _WS2[0] = False
    if not WIN:
        return None
    with crashlog.quiet(AREA):  # pragma: no cover - Windows only (ctypes.wintypes)
        import ctypes
        from ctypes import wintypes

        lib = ctypes.WinDLL("ws2_32", use_last_error=True)
        # int WSAIoctl(SOCKET, DWORD, LPVOID, DWORD, LPVOID, DWORD, LPDWORD,
        #              LPWSAOVERLAPPED, LPWSAOVERLAPPED_COMPLETION_ROUTINE)
        lib.WSAIoctl.argtypes = [ctypes.c_size_t, wintypes.DWORD, ctypes.c_void_p,
                                 wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
                                 ctypes.c_void_p]
        lib.WSAIoctl.restype = ctypes.c_int
        _WS2[0] = lib
    return _WS2[0] or None


def _answer_refusals_at_once(sock, wait_s):  # pragma: no cover - Windows only
    """A refused connection answers now instead of being tried again, and a silent
    one ends after ``wait_s`` (``Rtt``, measured to be when Windows gives up)."""
    lib = _ws2_32()
    if lib is None:
        return
    import ctypes
    from ctypes import wintypes

    class InitialRto(ctypes.Structure):
        _fields_ = [("Rtt", ctypes.c_ushort), ("MaxSynRetransmissions", ctypes.c_ubyte)]

    params = InitialRto(min(0xFFFE, int(wait_s * 1000)), NO_SYN_RETRANSMISSIONS)
    returned = wintypes.DWORD(0)
    if lib.WSAIoctl(sock.fileno(), SIO_TCP_INITIAL_RTO, ctypes.byref(params),
                    ctypes.sizeof(params), None, 0, ctypes.byref(returned), None, None):
        # Windows 8 and later know it; without it a closed port reads as silent.
        crashlog.once(AREA, OSError(ctypes.get_last_error(), "SIO_TCP_INITIAL_RTO"))


def _linger_zero(sock):
    """Close with a RST: the connection the scan made ends at once on both sides."""
    with crashlog.quiet(AREA):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                        struct.pack("HH", 1, 0) if WIN else struct.pack("ii", 1, 0))


def sockaddr(address, port):
    """Where a socket connects for ``address`` and ``port``: an IPv6 zone as its number."""
    bare = _bare(address)
    if bare.version == 4:
        return str(bare), port
    zone = str(address).partition("%")[2]
    scope = int(zone) if zone.isdigit() else (icmpsock.zone_index(zone) or 0) if zone else 0
    return str(bare), port, 0, scope


class _Net:
    """The sockets of one scan: started, answered, given up on. ``_round`` asks this
    and nothing else, so the tests stand in for it with an answer per port."""

    FLOWS_KEPT = 32         # the session line looks at the latest few flows

    def __init__(self, address, sniffer=None):
        self.address = address
        self.family = socket.AF_INET6 if _bare(address).version == 6 else socket.AF_INET
        self.sniffer = sniffer
        self.selector = selectors.DefaultSelector()
        self.waiting = {}       # port -> socket
        self.flows = collections.deque(maxlen=self.FLOWS_KEPT)
        self._remote = str(_bare(address))

    def start(self, proto, port, wait_s):
        """Ask ``port``: None while the answer is awaited, else the Answer."""
        kind = socket.SOCK_STREAM if proto == TCP else socket.SOCK_DGRAM
        sock = socket.socket(self.family, kind)
        try:
            sock.setblocking(False)
            if proto == TCP:
                if WIN:
                    _answer_refusals_at_once(sock, wait_s)
                code = sock.connect_ex(sockaddr(self.address, port))
                if code and code not in _IN_PROGRESS:
                    return self._end(sock, proto, classify(code))
                self._keep(sock, port, selectors.EVENT_WRITE)
            else:
                sock.connect(sockaddr(self.address, port))
                sock.send(payload(port))
                self._keep(sock, port, selectors.EVENT_READ)
        except OSError as exc:
            return self._end(sock, proto, classify(_code(exc)))
        return None

    def _keep(self, sock, port, event):
        with crashlog.quiet(AREA):
            self.flows.append((sock.getsockname()[1], self._remote, port))
        self.selector.register(sock, event, port)
        self.waiting[port] = sock

    def answers(self, proto, timeout):
        """The answers that arrive within ``timeout`` seconds."""
        out = []
        if self.waiting:
            for key, _mask in self.selector.select(timeout):
                out.append((key.data, self._read(proto, key.fileobj)))
        elif timeout > 0:
            time.sleep(timeout)
        if proto == UDP and self.sniffer is not None:
            for port in self.sniffer.closed_among(self.waiting):
                out.append((port, Answer(CLOSED)))
        for port, answer in out:
            self._drop(port, reset=proto == TCP and answer.state == OPEN)
        return out

    def _read(self, proto, sock):
        if proto == TCP:
            return classify(sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR))
        try:
            return Answer(OPEN, 0, len(sock.recv(65535)))
        except OSError as exc:
            return classify(_code(exc))

    def give_up(self, proto, port):
        """The wait for ``port`` is over: silent, unless the sniffer saw it refused."""
        self._drop(port)
        if proto == UDP and self.sniffer is not None and self.sniffer.closed_among((port,)):
            return Answer(CLOSED)
        return Answer(SILENT)

    def _drop(self, port, reset=False):
        """Close ``port``'s socket; ``reset``: with a RST (an open TCP connection, or one
        still connecting), so neither side keeps it in TIME_WAIT for minutes."""
        sock = self.waiting.pop(port, None)
        if sock is None:
            return
        with crashlog.quiet(AREA):
            self.selector.unregister(sock)
        if reset:
            _linger_zero(sock)
        sock.close()

    def _end(self, sock, proto, answer):
        if proto == TCP and answer.state == OPEN:
            _linger_zero(sock)
        sock.close()
        return answer

    def close(self):
        for port in list(self.waiting):
            self._drop(port, reset=self.waiting[port].type == socket.SOCK_STREAM)
        self.selector.close()


def _closed_port(raw, target, v6):
    """The UDP port an ICMP "port unreachable" from ``target`` (packed) is about, or
    None. ``raw`` is the whole IP packet that carried it: the message quotes the
    datagram it refuses - its IP header, then the first 8 bytes of its UDP header."""
    try:
        outer = 40 if v6 else (raw[0] & 0x0F) * 4
        inner = raw[outer + 8:]
        if v6:
            if inner[6] != socket.IPPROTO_UDP or inner[24:40] != target:
                return None
            udp = inner[40:]
        else:
            if inner[9] != socket.IPPROTO_UDP or inner[16:20] != target:
                return None
            udp = inner[(inner[0] & 0x0F) * 4:]
        return struct.unpack(">H", udp[2:4])[0]
    except (IndexError, struct.error):
        return None


class _Seen:
    """The ports the sniffer's thread saw refused, asked by the scan's thread. Added
    to in place under a lock: a set copied whole for every message would copy up to
    65 535 ports 65 535 times in a UDP scan of a computer that refuses every port."""

    def __init__(self):
        self._lock = threading.Lock()
        self._ports = set()

    def add(self, port):
        with self._lock:
            self._ports.add(port)

    def among(self, ports):
        """The ones of ``ports`` seen refused."""
        with self._lock:
            return {port for port in ports if port in self._ports}


class _Sniffer:  # pragma: no cover - Windows only (pydivert, a real driver, elevated)
    """Copies of the ICMP "port unreachable" messages the scanned computer sends back,
    which the Windows firewall keeps from the socket.

    SNIFF | RECV_ONLY: the handle cannot drop, change or send anything, so it changes
    nothing about the traffic - the shape of ``socketwatch``'s handle. Its filter is
    only that ICMP message, from that one address. Read on a thread of its own, the
    way socketwatch reads: a blocking receive, ended by closing the handle.
    """

    def __init__(self, address):
        import pydivert
        from pydivert.consts import Flag, Layer
        bare = _bare(address)
        self._v6 = bare.version == 6
        self._target = bare.packed
        if self._v6:
            filt = f"inbound and icmpv6.Type == 1 and icmpv6.Code == 4 and ipv6.SrcAddr == {bare}"
        else:
            filt = f"inbound and icmp.Type == 3 and icmp.Code == 3 and ip.SrcAddr == {bare}"
        self.closed = _Seen()
        self._closing = False
        self._handle = pydivert.WinDivert(filt, layer=Layer.NETWORK,
                                          flags=Flag.SNIFF | Flag.RECV_ONLY)
        self._handle.open()
        try:
            self._thread = threading.Thread(target=self._read, name="portscan-sniff",
                                            daemon=True)
            self._thread.start()
        except BaseException:
            # no reader, so nobody would ever close the handle the driver holds
            self._handle.close()
            raise

    def closed_among(self, ports):
        return self.closed.among(ports)

    def _read(self):
        try:
            for packet in self._handle:
                port = _closed_port(bytes(packet.raw), self._target, self._v6)
                if port:
                    self.closed.add(port)
        except Exception as exc:
            if not self._closing:
                crashlog.note(exc, AREA)

    def close(self):
        self._closing = True
        with crashlog.quiet(AREA):
            self._handle.close()
        self._thread.join(1.0)


def open_sniffer(scan_plan):
    """A ``_Sniffer`` when the scan asks UDP on Windows with administrator rights, of
    another computer; else None. A failure to open it is said by the scan's result
    (no UDP port reads as closed) and kept in the crash log."""
    if UDP not in scan_plan.protocols or not WIN or scan_plan.own or not winenv.is_admin():
        return None
    try:
        return _Sniffer(scan_plan.target.address)
    except Exception as exc:
        crashlog.note(exc, AREA)
        return None


# -- the scan -------------------------------------------------------------------- #
class Row(NamedTuple):
    """One port - or ports next to each other that answered the same - on one protocol."""
    key: str
    port: int               # the first port
    last: int               # the last port: ``port`` when the row is one port
    proto: str
    state: str
    code: int
    service: str
    reply: int              # UDP: the bytes of the reply; 0 otherwise

    def size(self):
        return self.last - self.port + 1


class Again(NamedTuple):
    """A second round: how many silent ports it asked, and how many answered then."""
    proto: str
    asked: int
    answered: int


class Scan(NamedTuple):
    rows: tuple
    plan: Plan
    made: int                   # ports asked, per protocol, both rounds
    planned: int
    # (proto, port) asked last before Stop - () when Stop came before the first port;
    # None when the scan ran to its end.
    stopped_at: tuple | None
    gave_up: tuple              # protocols on which the computer could not be reached
    again: tuple                # of Again
    udp_closed_seen: bool       # a closed UDP port can read as closed here
    started: float              # time.time()
    elapsed_s: float
    flows: tuple                # (local port, address, port) of the latest few
    # Protocols not asked: the computer could not be reached on one asked before them,
    # and every protocol goes to the same computer.
    skipped: tuple = ()

    @property
    def stopped(self):
        return self.stopped_at is not None


class _Pacer:
    """When the next port may start, at ``per_second`` at most (0: no limit).

    Counted from a base - start ``n`` at ``base + n / per_second`` - rather than by
    adding a gap to the last start: twenty added gaps of 0.05 s fall short of a second
    by a rounding error, and a test counted 21 starts in one second that way
    (2026-11-12). A pause longer than the pace starts a new base, so a burst never
    borrows the time it spent waiting.
    """

    def __init__(self, per_second, now):
        self.per_second = per_second
        self.base = now
        self.count = 0

    def next_at(self):
        return self.base + self.count / self.per_second if self.per_second else self.base

    def ready(self, now):
        return not self.per_second or now >= self.next_at()

    def started(self, now):
        if not self.per_second:
            return
        if now > self.next_at():
            self.base, self.count = now, 0
        self.count += 1


def _round(net, proto, ports, pace, progress, clock):
    """``(answers, how)``: an Answer per port asked, and "done", "stopped" or
    "gave_up". A port Stop caught waiting has no answer: it was not checked."""
    queue = collections.deque(ports)
    waiting = {}                # port -> when it was asked
    heard = _Heard()
    pacer = _Pacer(pace.per_second, clock())
    while queue or waiting:
        if progress.stopped:
            return heard.by_port, "stopped"
        _start_some(net, (proto, queue, waiting, heard), pace, progress, (clock, pacer))
        if _not_there(heard):
            # Closed now, unanswered: a socket left waiting would answer in the next
            # protocol's round, under its port number.
            for port in waiting:
                net.give_up(proto, port)
            return heard.by_port, "gave_up"
        timeout = _timeout(waiting, queue, pace, pacer, clock)
        for port, answer in net.answers(proto, timeout):
            if waiting.pop(port, None) is not None:
                _got(heard, progress, port, answer)
        now = clock()
        for port, asked in list(waiting.items()):
            if now - asked >= pace.wait_s:
                del waiting[port]
                _got(heard, progress, port, net.give_up(proto, port))
    return heard.by_port, "done"


def _start_some(net, state, pace, progress, timing):
    """Ask as many ports as the pace allows now - and none once the computer is not
    there: a try the system refuses at once (its neighbour already failed) leaves no
    socket waiting, so nothing else would stop this loop before the queue is empty."""
    proto, queue, waiting, heard = state
    clock, pacer = timing
    now = clock()
    while (queue and len(waiting) < pace.at_once and pacer.ready(now) and not progress.stopped
           and not _not_there(heard)):
        port = queue.popleft()
        progress.at = (proto, port)
        pacer.started(now)
        answer = net.start(proto, port, pace.wait_s)
        if answer is None:
            waiting[port] = now
        else:
            _got(heard, progress, port, answer)
        now = clock()


def _timeout(waiting, queue, pace, pacer, clock):
    """How long to wait for answers: until the oldest wait ends or the next port may
    start, and never longer than ``POLL_S`` (Stop)."""
    now = clock()
    soonest = now + POLL_S
    if waiting:
        soonest = min(soonest, min(waiting.values()) + pace.wait_s)
    if queue and len(waiting) < pace.at_once:
        soonest = min(soonest, pacer.next_at())
    return max(0.0, soonest - now)


class _Heard:
    """One round's answers by port, and how many of each state - counted as they come,
    because ``_not_there`` asks after every wait and a round can hold 65 535 ports."""

    def __init__(self):
        self.by_port = {}
        self.states = collections.Counter()

    def add(self, port, answer):
        self.by_port[port] = answer
        self.states[answer.state] += 1


def _got(heard, progress, port, answer):
    heard.add(port, answer)
    progress.made += 1
    if answer.state == OPEN:
        progress.opened += 1


def _not_there(heard):
    """The system said "unreachable" for ``GIVE_UP_AFTER`` ports and no port answered
    otherwise: the computer is not there, and asking the rest says it again.

    Silence does not count against it. On Linux the system gives up on the neighbour
    of an address nobody holds after about 3 s, and the near pace waits 1 s a port, so
    the first ports of such a scan read "no answer" before the first "unreachable" -
    with silence counted, the scan never stopped early (measured 2026-11-12: 3000
    ports in 12.6 s, every port of a computer that is not there in over four minutes).
    """
    states = heard.states
    return (states[UNREACHABLE] >= GIVE_UP_AFTER
            and states[UNREACHABLE] + states[SILENT] == sum(states.values()))


def _ask_again(answers):
    """The silent ports worth asking a second time: when they are a small minority
    and the computer answered on other ports (it is there, and was busy)."""
    silent = [port for port, answer in answers.items() if answer.state == SILENT]
    answered = len(answers) - len(silent)
    if not silent or not answered or len(silent) * 100 > AGAIN_SHARE * len(answers):
        return []
    return silent


def _one_protocol(net, proto, scan_plan, progress, clock):
    """``(answers, how, again)`` for one protocol, both rounds."""
    answers, how = _round(net, proto, scan_plan.ports, scan_plan.pace, progress, clock)
    again = None
    silent = _ask_again(answers) if how == "done" else []
    if silent:
        progress.planned += len(silent)
        progress.again = len(silent)
        pace = scan_plan.pace._replace(at_once=min(AGAIN_AT_ONCE, scan_plan.pace.at_once))
        second, how = _round(net, proto, silent, pace, progress, clock)
        progress.again = 0
        changed = {port: answer for port, answer in second.items() if answer.state != SILENT}
        answers.update(changed)
        again = Again(proto, len(silent), len(changed))
    return answers, how, again


def _open_net(scan_plan):
    """``(net, sniffer)``: the real sockets, and the sniffer they read closed UDP ports
    from (or None). A sniffer whose sockets could not be made is closed again."""
    sniffer = open_sniffer(scan_plan)
    try:
        return _Net(scan_plan.target.address, sniffer), sniffer
    except BaseException:
        if sniffer is not None:
            sniffer.close()
        raise


def scan(scan_plan, progress=None, net=None, clock=time.monotonic):
    """Ask every port of the plan, protocol by protocol, and fold what came back into
    rows. On a worker. ``progress`` carries Stop and how far it is."""
    progress = progress if progress is not None else Progress()
    progress.planned = len(scan_plan.ports) * len(scan_plan.protocols)
    progress.started = clock()
    started = time.time()
    sniffer = None
    if net is None:
        net, sniffer = _open_net(scan_plan)
    rows, gave_up, again = [], [], []
    asked = []
    try:
        for proto in scan_plan.protocols:
            asked.append(proto)
            answers, how, second = _one_protocol(net, proto, scan_plan, progress, clock)
            rows.extend(_rows(proto, answers))
            if second is not None:
                again.append(second)
            if how == "gave_up":
                # "Unreachable" is about the computer, not a port: the next protocol
                # would only wait for it. On Linux it cannot even hear it - the system
                # gives up on a missing neighbour ~3 s after a datagram and a UDP port
                # waits 1 s, so a whole UDP range read "no answer" (measured 2026-11-12).
                gave_up.append(proto)
                break
            if progress.stopped:
                break
    finally:
        net.close()
        if sniffer is not None:
            sniffer.close()
    closed_seen = not WIN or scan_plan.own or getattr(net, "sniffer", None) is not None
    skipped = tuple(p for p in scan_plan.protocols if p not in asked) if gave_up else ()
    return Scan(tuple(rows), scan_plan, progress.made, progress.planned,
                (progress.at or ()) if progress.stopped else None, tuple(gave_up),
                tuple(again),
                bool(closed_seen), started, clock() - progress.started,
                tuple(getattr(net, "flows", ())), skipped)


def _rows(proto, answers):
    """One row per run of ports next to each other with the same answer and service."""
    rows = []
    for port in sorted(answers):
        answer = answers[port]
        row = Row(f"{port}|{proto}", port, port, proto, answer.state, answer.code,
                  service(port, proto), answer.reply)
        last = rows[-1] if rows else None
        if (last is not None and port == last.last + 1
                and (row.state, row.code, row.service, row.reply)
                == (last.state, last.code, last.service, last.reply)):
            rows[-1] = last._replace(last=port)
        else:
            rows.append(row)
    return rows


_SORT_KEYS = {
    "port": lambda r: r.port,
    "proto": lambda r: r.proto,
    "state": lambda r: STATES.index(r.state),
    # A port with no usual service after every named one.
    "service": lambda r: r.service.lower() if r.service else None,
    "detail": lambda r: (r.reply, r.code) if (r.reply or r.code) else None,
}
COLUMNS = tuple(_SORT_KEYS)
# Open ports first: they are what a scan is read for.
DEFAULT_SORT = ("state", False)


def sort(rows, column=DEFAULT_SORT[0], reverse=False):
    """``rows`` in the order of one column, ties by port and protocol - Port check's
    ``sort``, with this tool's columns. On the UI thread when a header is clicked:
    every port of a computer folds to a few hundred rows (116 for a Mac, 2026-11-12)."""
    key = _SORT_KEYS.get(column, _SORT_KEYS[DEFAULT_SORT[0]])
    base = sorted(rows, key=lambda r: (r.port, r.proto))
    present = [r for r in base if key(r) is not None]
    present.sort(key=key, reverse=reverse)      # stable: ties keep the port order
    return present + [r for r in base if key(r) is None]


def counts(result):
    """``{(proto, state): ports}`` - ports, not rows."""
    out = collections.Counter()
    for row in result.rows:
        out[(row.proto, row.state)] += row.size()
    return out


# -- what it says ------------------------------------------------------------------ #
def conclusions(result):
    """``(key, args)`` pairs: what the scan means, in the order a person reads it."""
    said = []
    total = counts(result)
    asked = {proto: sum(n for (p, _s), n in total.items() if p == proto)
             for proto in result.plan.protocols}
    if result.plan.own:
        said.append(("tools.portscan.say.own", {}))
    for proto in result.gave_up:
        said.append(("tools.portscan.say.unreachable", {"proto": proto, "count": GIVE_UP_AFTER}))
    for proto in result.skipped:
        said.append(("tools.portscan.say.skipped", {"proto": proto, "by": result.gave_up[0]}))
    if asked.get(TCP) and total[(TCP, SILENT)] == asked[TCP] and TCP not in result.gave_up:
        said.append(("tools.portscan.say.all_silent", {}))
    elif total[(TCP, SILENT)]:
        said.append(("tools.portscan.say.tcp_silent", {"s": seconds_text(result.plan.pace.wait_s)}))
    for again in result.again:
        said.append(("tools.portscan.say.again", {"proto": again.proto, "asked": again.asked,
                                                  "answered": again.answered}))
    if asked.get(UDP):
        said.append(("tools.portscan.say.udp", {}))
        if not result.udp_closed_seen:
            said.append(("tools.portscan.say.udp_no_closed", {}))
        elif total[(UDP, SILENT)] > 100:
            said.append(("tools.portscan.say.udp_rate", {}))
    return said


def seconds_text(value):
    return f"{value:g}"


REPORT_STATES = {OPEN: "open", CLOSED: "closed", SILENT: "no answer",
                 UNREACHABLE: "unreachable", DENIED: "not allowed", FAILED: "error"}


def port_text(row):
    return str(row.port) if row.last == row.port else f"{row.port}-{row.last}"


def report(result):
    """The copied results, in English like every report of the tab."""
    plan_ = result.plan
    target = plan_.target
    named = f" ({target.typed})" if target.name else ""
    started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(result.started))
    pace = plan_.pace
    lines = [f"Port scan of {target.address}{named}",
             f"Started {started}, took {result.elapsed_s:.1f} s, "
             f"{result.made} of {result.planned} port checks"
             + (" (stopped)" if result.stopped else ""),
             f"Pace: {pace.at_once} at once"
             + (f", {pace.per_second} new a second" if pace.per_second else "")
             + f", {seconds_text(pace.wait_s)} s to answer"
             + (" (same network)" if pace.near else " (behind a router)")]
    for again in result.again:
        lines.append(f"{again.proto}: second round for the ports with no answer: "
                     f"{again.asked} asked, {again.answered} answered")
    for proto in result.gave_up:
        lines.append(f"{proto}: unreachable, the scan stopped asking")
    for proto in result.skipped:
        lines.append(f"{proto}: not asked, the computer could not be reached")
    lines.append("")
    for row in result.rows:
        state = REPORT_STATES[row.state]
        extra = [row.service] if row.service else []
        if row.code and row.state in (DENIED, FAILED, UNREACHABLE):
            extra.append(f"code {row.code}")
        if row.reply:
            extra.append(f"replied {row.reply} bytes")
        lines.append(f"{row.proto} {port_text(row)} {state}"
                     + (f" ({', '.join(extra)})" if extra else ""))
    return "\n".join(lines)
