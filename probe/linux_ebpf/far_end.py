"""The far end for the eBPFDivert probe: runs in the ROOT network namespace, outside the divert.

TCP echo 47001, UDP echo 47002 and 47004 (IPv4 and IPv6), UDP discard counter
47005 (a datagram to 47006 answers the count since the last question and resets
it). Each UDP echo is bound to ONE address (10.231.0.1, 10.231.0.3, fd00:231::1,
fd00:231::3): a socket bound to 0.0.0.0 answers a datagram sent to .3 FROM .1, the
primary address, and that reply matches a filter on .1 - which once read as the
kernel widening an IPv4 address filter. Dies on its own after --life seconds.
"""
import argparse
import socket
import threading
import time

HOST = "0.0.0.0"


def tcp_echo(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, port))
    srv.listen(64)
    while True:
        conn, _ = srv.accept()
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


def udp_echo(port, addr):
    s = socket.socket(socket.AF_INET6 if ":" in addr else socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((addr, port))
    while True:
        data, addr = s.recvfrom(65536)
        s.sendto(data, addr)


COUNT = [0]
LOCK = threading.Lock()


def udp_discard(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
    s.bind((HOST, port))
    while True:
        s.recv(65536)
        with LOCK:
            COUNT[0] += 1


def udp_count(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((HOST, port))
    while True:
        _, addr = s.recvfrom(64)
        with LOCK:
            n, COUNT[0] = COUNT[0], 0
        s.sendto(str(n).encode(), addr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--life", type=float, default=900)
    a = ap.parse_args()
    jobs = [(tcp_echo, (47001,)), (udp_discard, (47005,)), (udp_count, (47006,))]
    jobs += [(udp_echo, (port, addr)) for port in (47002, 47004)
             for addr in ("10.231.0.1", "10.231.0.3", "fd00:231::1", "fd00:231::3")]
    for fn, args in jobs:
        threading.Thread(target=fn, args=args, daemon=True).start()
    print("FAR_END_UP", flush=True)
    time.sleep(a.life)


if __name__ == "__main__":
    main()
