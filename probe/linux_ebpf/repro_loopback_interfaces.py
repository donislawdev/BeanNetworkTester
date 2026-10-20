"""pydivert 4.0.0 on Linux: with `interfaces=[...]`, loopback traffic is not captured.

docs/LINUX_BACKEND.md shows `interfaces=["eth0"]` with the comment "loopback is always
included". Run as root. The same filter is opened three times, one handle at a time;
each re-injects what it receives and counts it while datagrams go over 127.0.0.1.
"""
import os
import socket
import threading
import time

import pydivert

PORT = 47050
FILTER = f"udp.DstPort == {PORT} or udp.SrcPort == {PORT}"


def run(**kw):
    seen = 0
    with pydivert.Divert(FILTER, **kw) as w:
        stop = threading.Event()

        def loop():
            nonlocal seen
            while not stop.is_set():
                try:
                    p = w.recv(timeout=0.1)
                except TimeoutError:
                    continue
                seen += 1
                w.send(p)
        t = threading.Thread(target=loop)
        t.start()
        time.sleep(0.2)
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx.bind(("127.0.0.1", PORT))
        rx.settimeout(1)
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        delivered = 0
        for _ in range(5):
            tx.sendto(b"x", ("127.0.0.1", PORT))
            try:
                rx.recvfrom(16)
                delivered += 1
            except socket.timeout:
                pass
        time.sleep(0.2)
        stop.set()
        t.join()
        rx.close()
        tx.close()
    return seen, delivered


iface = next(name for _, name in socket.if_nameindex() if name != "lo")
print(f"pydivert {pydivert.__version__}, kernel {os.uname().release}")
for kw in ({}, {"interfaces": [iface]}, {"interfaces": [iface, "lo"]}):
    seen, delivered = run(**kw)
    print(f"  {str(kw):38} captured {seen}/5, delivered {delivered}/5")
