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
# written - the whole shape of the check depends on it).
BLOCKED_ADDR, BLOCKED_PORT = "127.5.5.5", 9091
BYSTANDER_ADDR, BYSTANDER_PORT = "127.9.9.9", 9200

ROUNDS = 20                 # datagrams per endpoint per phase
SILENT_AT_MOST = 0          # a blocked endpoint must answer nothing at all
ALIVE_AT_LEAST = 18         # a bystander must stay essentially untouched

FILTER = ("udp and (udp.SrcPort == %d or udp.DstPort == %d or "
          "udp.SrcPort == %d or udp.DstPort == %d)"
          % (BLOCKED_PORT, BLOCKED_PORT, BYSTANDER_PORT, BYSTANDER_PORT))


def echo(addr, port, stop):
    """A UDP echo server. UDP so the count is exact - no retransmission to hide
    a partial block, and no connect timeout to wait through."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((addr, port))
    sock.settimeout(0.2)
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

    stop = threading.Event()
    for addr, port in ((BLOCKED_ADDR, BLOCKED_PORT), (BYSTANDER_ADDR, BYSTANDER_PORT)):
        threading.Thread(target=echo, args=(addr, port, stop), daemon=True).start()
    time.sleep(0.4)

    # (label, block ip, block port, bystander is meaningful here)
    phases = [
        ("control - nothing blocked", "", "", True),
        ("block ip by prefix wildcard '127.5.*'", "127.5.*", "", True),
        ("block port by wildcard '909*'", "", "909*", True),
        ("block ip by ONE-OCTET wildcard '127.*'", "127.*", "", False),
    ]

    engine = BeanEngine()
    engine.start(FILTER)
    results = []
    try:
        for label, ip, port, bystander_counts in phases:
            engine.set_block(bool(ip or port), ip, port)
            time.sleep(0.2)
            named = answered(BLOCKED_ADDR, BLOCKED_PORT)
            other = answered(BYSTANDER_ADDR, BYSTANDER_PORT)
            results.append((label, ip, port, named, other, bystander_counts))
    finally:
        engine.stop()
        stop.set()
        from beantester import driver
        driver.mark_driver_used()
        driver.release_on_exit()

    problems = []
    for label, ip, port, named, other, bystander_counts in results:
        blocking = bool(ip or port)
        if not blocking:
            if named < ALIVE_AT_LEAST or other < ALIVE_AT_LEAST:
                problems.append("%s: the control phase did not pass traffic "
                                "(%d/%d and %d/%d) - every later verdict would be "
                                "meaningless" % (label, named, ROUNDS, other, ROUNDS))
            continue
        if named > SILENT_AT_MOST:
            problems.append("%s: the NAMED endpoint still answered %d of %d"
                            % (label, named, ROUNDS))
        if bystander_counts and other < ALIVE_AT_LEAST:
            problems.append("%s: the bystander was hit too (%d of %d) - the block "
                            "took more than it named" % (label, other, ROUNDS))

    print("phase                                     named  bystander")
    for label, ip, port, named, other, bystander_counts in results:
        note = "" if bystander_counts else "   (bystander N/A: a one-octet " \
                                           "loopback prefix covers every 127.x)"
        print("  %-38s %2d/%-2d  %2d/%-2d%s"
              % (label, named, ROUNDS, other, ROUNDS, note))

    for line in problems:
        print("FAIL: %s" % line)
    if problems:
        return 1
    print("ok: every blocking expression cut exactly what it named, wildcards "
          "included, and the bystander survived each one that could have a bystander")
    return 0


if __name__ == "__main__":
    sys.exit(main())
