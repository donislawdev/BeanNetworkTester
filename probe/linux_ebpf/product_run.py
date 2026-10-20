"""The REAL CLI of the source tree in BNT_SRC on Linux, with ONE probe-only change: the class.

Inside bntp (run.sh mounts cgroup2 for it). The child is the product; this parent
measures what it does to the traffic: a UDP RTT to the far end before, during and
after a ``--dst-ip 10.231.0.1 --latency 50 --duration 8`` session, plus a decoy on
the namespace's own loopback that the session's --dst-ip does NOT cover.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time

SRC = os.environ["BNT_SRC"]          # the product source tree (run.sh requires it)
SERVER = "10.231.0.1"
LAUNCH = (
    "import sys\n"
    f"sys.path.insert(0, {SRC!r})\n"
    "import pydivert\n"
    "pydivert.WinDivert = pydivert.EBPFDivert   # probe only: the product names WinDivert\n"
    "from beantester.cli import main\n"
    "sys.exit(main(sys.argv[1:]))\n")


def rtts(n, port=47002, gap=0.02):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(1.0)
    out = []
    for i in range(n):
        t0 = time.perf_counter()
        s.sendto(b"p%05d" % i, (SERVER, port))
        try:
            s.recvfrom(64)
            out.append(round((time.perf_counter() - t0) * 1000, 2))
        except socket.timeout:
            pass
        time.sleep(gap)
    s.close()
    return out


def lo_rtts(n):
    """A decoy the session's --dst-ip does not cover: this namespace's own loopback."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 47030))

    def echo():
        while True:
            try:
                d, a = srv.recvfrom(64)
            except OSError:
                return
            srv.sendto(d, a)
    threading.Thread(target=echo, daemon=True).start()
    c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    c.settimeout(1.0)
    out = []
    for i in range(n):
        t0 = time.perf_counter()
        c.sendto(b"l", ("127.0.0.1", 47030))
        try:
            c.recvfrom(64)
            out.append(round((time.perf_counter() - t0) * 1000, 2))
        except socket.timeout:
            pass
        time.sleep(0.02)
    c.close()
    srv.close()
    return out


def med(xs):
    return sorted(xs)[len(xs) // 2] if xs else None


def main():
    before = rtts(20)
    child = subprocess.Popen(
        [sys.executable, "-c", LAUNCH, "--dst-ip", SERVER, "--latency", "50", "--duration", "8",
         "--log-level", "debug"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    threading.Thread(target=lambda: lines.extend(child.stdout), daemon=True).start()
    time.sleep(3.0)
    during = rtts(50)
    decoy = lo_rtts(20)
    rc = child.wait(30)
    time.sleep(0.5)
    after = rtts(20)
    print(json.dumps({"test": "product", "exit_code": rc,
                      "rtt_before_med": med(before), "rtt_during_med": med(during),
                      "during_n": len(during), "rtt_after_med": med(after),
                      "decoy_lo_med": med(decoy), "decoy_n": len(decoy)}), flush=True)
    print("---- product output (last 60 lines)")
    for line in lines[-60:]:
        print("  " + line.rstrip())


if __name__ == "__main__":
    main()
