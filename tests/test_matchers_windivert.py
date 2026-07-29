"""Compiling a destination expression into the DRIVER's filter language.

Why this exists: with a destination target set, the tool captures EVERYTHING and
re-injects almost all of it untouched. Measured 2026-07-28 against a real
capture: 1944 packets diverted and 0 of them impairable; another run, 1632
diverted and 8 impairable. Every one of those cost a recv plus a send for
nothing. The WinDivert filter runs IN THE DRIVER, so an expression that can be
pushed into it is traffic that never reaches this process at all.

The ONE invariant: the fragment must match AT LEAST everything the matcher
matches. Over-capturing is free - ``decide()`` still filters. Under-capturing is
the silent regression this project keeps hunting: traffic the user asked to
impair would never arrive, and every counter would read healthy.

Two layers of guard, deliberately:

* the tests here run EVERYWHERE and pin the structure - which forms narrow, which
  refuse to, and that both directions are covered;
* the last test runs only where ``pydivert`` is importable (win32) and checks the
  invariant against **the driver's own evaluator**, so it is not my reading of the
  filter language checked against my reading of the matcher. It is skipped on the
  Linux half of the CI matrix, which is worth knowing when reading a green run.
"""
import struct

import pytest

from beantester.matchers import (KIND_INT, KIND_IP, KIND_PROCESS, PORT_BOUNDS,
                                 parse_matcher, windivert_fragment)
from fakes import check


def _fragment(text, kind):
    bounds = PORT_BOUNDS if kind == KIND_INT else None
    return windivert_fragment(parse_matcher(text, kind, bounds=bounds))


def test_only_the_provable_forms_narrow_anything():
    """Anything that cannot be proven a superset must return None, not a guess.

    The forms that DO compile were checked against the real parser
    (``WinDivertHelperCompileFilter``) on 2026-07-28; the forms that do not are
    rejected by it - a wildcard and a ``re:`` pattern are "bad token", and
    ``processId`` is "bad token for layer", which is why a process expression can
    never be pushed into a NETWORK-layer filter no matter how simple it looks.
    """
    for text, kind in (("53", KIND_INT), ("80,443", KIND_INT),
                       ("8000-8100", KIND_INT), (">1024", KIND_INT),
                       ("8.8.8.8", KIND_IP), ("10.0.0.0/8", KIND_IP),
                       ("2001:4860:4860::8888", KIND_IP)):
        check("%r narrows" % text, _fragment(text, kind) is not None)

    for text, kind in (("", KIND_INT), ("44*", KIND_INT), ("re:^44", KIND_INT),
                       ("!53", KIND_INT), ("1.1.*", KIND_IP),
                       ("re:^8\\.8", KIND_IP), ("!8.8.8.8", KIND_IP),
                       ("chrome.exe", KIND_PROCESS), ("1234", KIND_PROCESS)):
        check("%r must NOT narrow" % text, _fragment(text, kind) is None,
              repr(_fragment(text, kind)))


def test_both_directions_are_covered_because_the_remote_end_swaps():
    """The trap that nearly shipped, and the reason this test is first-class.

    ``engine._capture_loop`` reads the remote endpoint as the packet's
    DESTINATION when it is outbound and as its SOURCE when it is inbound. A
    fragment testing only ``DstAddr``/``DstPort`` would therefore have kept every
    inbound packet out of the driver's hand - the tool would have impaired one
    direction and silently stopped impairing the other, with all counters healthy.
    """
    port = _fragment("443", KIND_INT)
    for field in ("tcp.DstPort", "tcp.SrcPort", "udp.DstPort", "udp.SrcPort"):
        check("port fragment covers %s" % field, field in port, port)

    ip = _fragment("8.8.8.8", KIND_IP)
    for field in ("ip.DstAddr", "ip.SrcAddr"):
        check("ip fragment covers %s" % field, field in ip, ip)

    v6 = _fragment("2001:4860:4860::8888", KIND_IP)
    for field in ("ipv6.DstAddr", "ipv6.SrcAddr"):
        check("ipv6 fragment covers %s" % field, field in v6, v6)


def test_exclusions_are_dropped_because_dropping_them_only_widens():
    """``80,443,!8080`` compiles as though the exclusion were not there.

    Keeping it would make the fragment NARROWER than the matcher in the one case
    that matters - a packet the exclusion knocks out is still a packet the driver
    must hand us, because ``decide()`` is where that decision belongs. Dropping a
    negative can only widen, and widening is the safe direction.
    """
    check("an exclusion does not change the fragment",
          _fragment("80,443,!8080", KIND_INT) == _fragment("80,443", KIND_INT))
    check("an expression made only of exclusions cannot narrow at all",
          _fragment("!8080", KIND_INT) is None)


def test_no_address_dependent_terms_leak_into_the_fragment():
    """``outbound`` / ``loopback`` live in WINDIVERT_ADDRESS, not in the packet.

    Keeping them out is what lets the oracle test below evaluate a fragment
    against a SYNTHETIC packet and still mean something: with a blank address
    struct those terms would be judged against zeros. Verified 2026-07-28 that the
    evaluator reads them from the address (40 real packets, 9 filters, no
    disagreement), which is precisely why they must not appear here.
    """
    for text, kind in (("53", KIND_INT), ("8000-8100", KIND_INT),
                       ("8.8.8.8", KIND_IP), ("10.0.0.0/8", KIND_IP)):
        frag = _fragment(text, kind)
        for banned in ("outbound", "inbound", "loopback", "impostor", "ifIdx"):
            check("%r stays free of %s" % (text, banned), banned not in frag, frag)


# -- the oracle: the driver's own evaluator, win32 only ------------------------- #
def _udp(src_ip, dst_ip, src_port, dst_port):
    payload = b"x" * 16
    udp = struct.pack(">HHHH", src_port, dst_port, 8 + len(payload), 0) + payload
    total = 20 + len(udp)
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, total, 1, 0, 64, 17, 0,
                     bytes(int(x) for x in src_ip.split(".")),
                     bytes(int(x) for x in dst_ip.split(".")))
    return ip + udp


def test_the_fragment_never_excludes_what_the_matcher_accepts():
    """The invariant, checked against WinDivert's OWN evaluator.

    ``WinDivertHelperEvalFilter`` is the same code the driver runs, so this is not
    two readings of the filter language agreeing with each other. Skipped without
    ``pydivert`` (win32-only), which is half the CI matrix - so a green run on
    Linux has NOT checked this.

    Run in full outside the suite over 27 648 packet views on 16 expressions with
    zero violations (2026-07-28); the sweep here is trimmed to keep the suite fast.
    """
    pydivert = pytest.importorskip("pydivert")
    import ctypes
    from pydivert import windivert_dll as w
    from pydivert.windivert_dll import WinDivertAddress

    addr = WinDivertAddress()

    def evaluates(text, raw):
        buf = ctypes.create_string_buffer(raw, len(raw))
        return bool(w.WinDivertHelperEvalFilter(text.encode(), buf, len(raw),
                                                ctypes.byref(addr)))

    ips = ["8.8.8.8", "8.8.4.4", "10.1.2.3", "192.168.1.25"]
    ports = [53, 80, 443, 1024, 8080, 8100]
    cases = [("53", KIND_INT), ("80,443", KIND_INT), ("8000-8100", KIND_INT),
             (">1024", KIND_INT), ("8.8.8.8", KIND_IP), ("10.0.0.0/8", KIND_IP)]

    violations, checked = [], 0
    for text, kind in cases:
        bounds = PORT_BOUNDS if kind == KIND_INT else None
        matcher = parse_matcher(text, kind, bounds=bounds)
        frag = windivert_fragment(matcher)
        check("%r produced a fragment" % text, frag is not None)
        for dst_ip in ips:
            for src_ip in ips[:2]:
                for dport in ports:
                    for sport in ports[:2]:
                        raw = _udp(src_ip, dst_ip, sport, dport)
                        # outbound reads the remote end as dst, inbound as src
                        for remote_ip, remote_port in ((dst_ip, dport),
                                                       (src_ip, sport)):
                            want = (matcher.matches(remote_port) if kind == KIND_INT
                                    else matcher.matches(remote_ip))
                            checked += 1
                            if want and not evaluates(frag, raw):
                                violations.append((text, remote_ip, remote_port))
    check("the sweep actually ran", checked > 500, str(checked))
    check("the matcher never accepts what the fragment excludes",
          not violations, str(violations[:3]))
