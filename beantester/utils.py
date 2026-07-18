"""Small dependency-free helpers shared across the engine, GUI and CLI."""
import math


def clamp01(x):
    """Clamp a number into the ``[0.0, 1.0]`` range."""
    return max(0.0, min(1.0, x))


def to_number(value):
    """Lenient float conversion: ``None`` / garbage -> ``0.0``."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def number_string(value):
    """Compact string for a number: ``5.0`` -> ``'5'``, ``2.5`` -> ``'2.5'``."""
    f = to_number(value)
    return str(int(f)) if f == int(f) else str(f)


def bytes_to_mb(n):
    """Bytes -> megabytes (MB = 1024*1024 B), rounded to 2 decimals."""
    return round(to_number(n) / (1024.0 * 1024.0), 2)


def nice_ceiling(v):
    """Round up to a 'nice' axis value (1/2/2.5/5 x 10^k)."""
    v = to_number(v)
    if v <= 0:
        return 1.0
    exp = math.floor(math.log10(v))
    base = 10 ** exp
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * base:
            return round(m * base, 6)
    return 10 * base


def canonical_ip(ip):
    """Canonical text form of an IPv4/IPv6 address, or ``None`` if invalid.

    Used to validate user-entered destination IPs and to compare them against
    packet addresses regardless of formatting (IPv6 shorthand, leading zeros).
    """
    try:
        import ipaddress
        return str(ipaddress.ip_address(str(ip).strip()))
    except (ValueError, TypeError):
        return None


def is_local_ip(ip):
    """True for local addresses (RFC1918, loopback, link-local, CGNAT...).

    Public (internet) addresses return False. Missing/error = treated as local.
    """
    if not ip:
        return True
    try:
        import ipaddress
        return not ipaddress.ip_address(str(ip)).is_global
    except Exception:
        return True


def _route_source_ip(family, probe):
    """The local address the OS would use to reach ``probe`` - no packet is sent.

    A connected UDP socket only records a default peer, so this asks the routing
    table which interface would be picked without putting anything on the wire
    (it does not disturb capture). ``"-"`` when that family has no route (e.g. a
    box with no IPv6 connectivity).
    """
    import socket
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.connect((probe, 80))
            return sock.getsockname()[0] or "-"
    except OSError:
        return "-"


def host_identity():
    """Hostname and this machine's private IPv4 / IPv6 addresses.

    The addresses belong to the adapter that would route to the internet, found
    via ``_route_source_ip`` (no traffic, so it never disturbs capture) - which
    also avoids ``gethostbyname(gethostname())`` handing back ``127.0.0.1`` or
    the wrong interface. Returns ``(hostname, ipv4, ipv6)``; anything
    unavailable degrades to ``"-"``.
    """
    import socket
    try:
        host = socket.gethostname() or "-"
    except OSError:
        host = "-"
    ipv4 = _route_source_ip(socket.AF_INET, "8.8.8.8")
    if ipv4 == "-":
        try:
            ipv4 = socket.gethostbyname(socket.gethostname()) or "-"
        except OSError:
            ipv4 = "-"
    ipv6 = _route_source_ip(socket.AF_INET6, "2001:4860:4860::8888")
    return host, ipv4, ipv6


# Backward-compatible alias kept for the original monolith's private name.
_num = to_number


def human_duration(seconds):
    """A session length a human can read, at any length.

    It used to be ``f"{minutes}m {seconds}s"``, which is fine for the ten-minute
    runs everybody tested with and turns into ``4320m 0s`` after a long weekend -
    and long weekends are exactly what this tool gets left running over.
    """
    seconds = max(0, int(seconds or 0))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    return f"{minutes}m {secs}s"
