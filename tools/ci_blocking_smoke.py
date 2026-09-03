#!/usr/bin/env python3
"""A real-driver check that blocking BLOCKS - including by wildcard.

Why this exists
---------------
Blocking is step 2c of ``BeanCore.decide`` and it never reaches the driver
filter: ``filters.narrowed_filter`` deliberately refuses to narrow on anything it
cannot prove, so a block is decided entirely in this process. That makes it easy
to test with fakes and easy to leave untested for real - which is what had
happened. Until 2026-08-10 the coverage was:

* wildcards were tested in ``test_matchers.py``, in isolation, never as a block;
* blocking was tested in ``test_core.py`` and ``test_engine.py`` with literal
  addresses, a CIDR and a literal port - never a wildcard;
* the only real-driver blocking check, ``internal_tools/probe_blocking_truth.py``,
  is outside git, needs a LAN peer, and also used literals.

So no packet had ever been blocked by a wildcard anywhere, at any layer. This
closes that with a real WinDivert session and real sockets.

What it proves, and how the halves differ
-----------------------------------------
Each phase measures BOTH endpoints, because "blocked" and "the peer went away"
look identical from one side. A phase passes only when the named endpoint goes
silent AND the bystander keeps answering in the same run - one signal is a
result, two are a claim about the expression.

``127.5.*`` is the shape people actually type: a prefix and a star, not a CIDR.
The last phase uses the one-octet form ``127.*`` on its own, because that is how
the question was asked - and there the bystander check is reported as NOT
APPLICABLE rather than quietly skipped: a one-octet loopback prefix covers every
address a loopback bystander could have, so nothing on this machine can play that
role. Saying so is the point; pretending otherwise would be the false pass.

What bounds the damage (convention 6)
-------------------------------------
The expression under test is the SUBJECT, never the bound. The bound is the
driver filter, pinned to two UDP ports on the loopback interface, so even the
``127.*`` phase can only ever touch this script's own two sockets - nothing else
on the machine is handed to the tool at all. There is no impairment beyond the
block itself: no loss, no latency, no rate limit. Runtime is a few seconds.

Not Windows, not elevated, or no pydivert -> it prints SKIP and exits 0. A check
that cannot run must say so out loud rather than pass quietly.
"""
import os
import socket
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Two loopback addresses, so an IP expression can name one and miss the other.
# Windows binds any 127.x on the loopback adapter (verified before this was
# written - the whole shape of the check depends on it). The ADDRESSES stay
# literal because the two IP phases name them by prefix and nothing else on the
# machine competes for them. The PORTS do not: see `open_pair`.
BLOCKED_ADDR = "127.5.5.5"
BYSTANDER_ADDR = "127.9.9.9"

ROUNDS = 20                 # datagrams per endpoint per phase
SILENT_AT_MOST = 0          # a blocked endpoint must answer nothing at all
ALIVE_AT_LEAST = 18         # a bystander must stay essentially untouched
DRAWS = 20                  # attempts to land the two ports in different decades


def traffic_filter(blocked_port, bystander_port):
    """The driver filter: this script's own two UDP ports, nothing else.

    This is the BOUND on the damage (convention 6), so it is built from the ports
    actually in use rather than from a constant that might describe a socket
    nobody opened.
    """
    return ("udp and (udp.SrcPort == %d or udp.DstPort == %d or "
            "udp.SrcPort == %d or udp.DstPort == %d)"
            % (blocked_port, blocked_port, bystander_port, bystander_port))


def open_pair():
    """Two bound echo sockets, on ports the OS picked, in different decades.

    🔴 Why the ports are asked for rather than named. Windows RESERVES port
    ranges (Hyper-V, WSL, WinNAT) and a reserved port refuses `bind` with
    `WinError 10013`, a PERMISSION error rather than "in use". This script used
    to name 9091, which sits inside `9001-9100` - a range measured as reserved on
    a real machine 2026-09-03. It survived only because reservations are PER
    PROTOCOL and this echo is UDP, which is not "it works", it is "it missed".
    Its TCP twin, `ci_targeting_smoke.py`, was unrunnable for exactly that reason.

    🔴 Why they must differ in more than the last digit. The port phase turns the
    blocked port into a PREFIX GLOB (`54321` -> `5432*`), so a bystander in the
    same decade would be named by the expression under test, and the check would
    then report the expression working correctly as a bug. Windows hands out
    ephemeral ports close together, so that collision is real rather than
    theoretical - the pair is redrawn until it holds. Rejected sockets are kept
    open while drawing, or the OS would hand the same port straight back.
    """
    keep, rejects = [], []
    try:
        blocked, blocked_port = _bind(BLOCKED_ADDR)
        keep.append(blocked)
        for _ in range(DRAWS):
            other, other_port = _bind(BYSTANDER_ADDR)
            if not str(other_port).startswith(port_glob(blocked_port)[:-1]):
                keep.append(other)
                return blocked, blocked_port, other, other_port
            rejects.append(other)
        raise OSError("could not land two ports in different decades in %d draws"
                      % DRAWS)
    except BaseException:
        for sock in keep:
            sock.close()
        raise
    finally:
        for sock in rejects:
            sock.close()


def _bind(addr):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((addr, 0))
    sock.settimeout(0.2)
    return sock, sock.getsockname()[1]


def port_glob(port):
    """The wildcard the port phase blocks with: the port, last digit starred."""
    return str(port)[:-1] + "*"


def echo(sock, stop):
    """A UDP echo server on an already-bound socket. UDP so the count is exact -
    no retransmission to hide a partial block, and no connect timeout to wait
    through."""
    while not stop.is_set():
        try:
            data, peer = sock.recvfrom(2048)
            sock.sendto(data, peer)
        except socket.timeout:
            continue
        except OSError:
            break
    sock.close()


def answered(addr, port, rounds=ROUNDS):
    """How many of `rounds` datagrams came back."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.25)
    got = 0
    try:
        for index in range(rounds):
            try:
                sock.sendto(b"block-probe-%03d" % index, (addr, port))
                sock.recv(2048)
                got += 1
            except socket.timeout:
                continue
            except OSError:
                continue
    finally:
        sock.close()
    return got


def skip(reason):
    print("SKIP: %s" % reason)
    return 0


def main():
    from beantester import winenv
    if not winenv.is_windows():
        return skip("not Windows - there is no WinDivert here")
    if not winenv.is_admin():
        return skip("not elevated - a capture session cannot start")
    try:
        import pydivert                                  # noqa: F401
    except Exception as exc:
        return skip("pydivert is not importable (%s)" % exc)

    from beantester.engine import BeanEngine

    try:
        blocked, blocked_port, other, bystander_port = open_pair()
    except OSError as exc:
        # Not a SKIP: the three checks above are the known reasons this cannot
        # run, and "the machine would not give me two loopback ports" is not one
        # of them. A check that cannot run says so, and this one says why.
        print("FAIL: could not open the two echo sockets (%s)" % exc)
        return 1

    stop = threading.Event()
    for sock in (blocked, other):
        threading.Thread(target=echo, args=(sock, stop), daemon=True).start()

    glob = port_glob(blocked_port)
    # (label, block ip, block port, bystander is meaningful here)
    phases = [
        ("control - nothing blocked", "", "", True),
        ("block ip by prefix wildcard '127.5.*'", "127.5.*", "", True),
        ("block port by wildcard '%s'" % glob, "", glob, True),
        ("block ip by ONE-OCTET wildcard '127.*'", "127.*", "", False),
    ]

    print("ports this run: blocked %d (glob %s), bystander %d\n"
          % (blocked_port, glob, bystander_port))
    engine = BeanEngine()
    engine.start(traffic_filter(blocked_port, bystander_port))
    results = []
    try:
        for label, ip, port, bystander_counts in phases:
            engine.set_block(bool(ip or port), ip, port)
            time.sleep(0.2)
            named = answered(BLOCKED_ADDR, blocked_port)
            seen = answered(BYSTANDER_ADDR, bystander_port)
            results.append((label, ip, port, named, seen, bystander_counts))
    finally:
        engine.stop()
        stop.set()
        from beantester import driver
        driver.mark_driver_used()
        driver.release_on_exit()

    problems = []
    for label, ip, port, named, seen, bystander_counts in results:
        blocking = bool(ip or port)
        if not blocking:
            if named < ALIVE_AT_LEAST or seen < ALIVE_AT_LEAST:
                problems.append("%s: the control phase did not pass traffic "
                                "(%d/%d and %d/%d) - every later verdict would be "
                                "meaningless" % (label, named, ROUNDS, seen, ROUNDS))
            continue
        if named > SILENT_AT_MOST:
            problems.append("%s: the NAMED endpoint still answered %d of %d"
                            % (label, named, ROUNDS))
        if bystander_counts and seen < ALIVE_AT_LEAST:
            problems.append("%s: the bystander was hit too (%d of %d) - the block "
                            "took more than it named" % (label, seen, ROUNDS))

    print("phase                                     named  bystander")
    for label, _ip, _port, named, seen, bystander_counts in results:
        note = "" if bystander_counts else "   (bystander N/A: a one-octet " \
                                           "loopback prefix covers every 127.x)"
        print("  %-38s %2d/%-2d  %2d/%-2d%s"
              % (label, named, ROUNDS, seen, ROUNDS, note))

    for line in problems:
        print("FAIL: %s" % line)
    if problems:
        return 1
    print("ok: every blocking expression cut exactly what it named, wildcards "
          "included, and the bystander survived each one that could have a bystander")
    return 0


if __name__ == "__main__":
    sys.exit(main())
