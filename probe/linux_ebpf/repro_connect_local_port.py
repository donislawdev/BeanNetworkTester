"""SOCKET layer, CONNECT event: is LocalPort the port the new connection uses?

Runs on Windows (elevated) and on Linux (root). A sniff-only SOCKET handle watches
two TCP connections to a local listener: one from an unbound socket (the usual
client) and one from a socket bound to an ephemeral port before connect().
"""
import os
import platform
import socket
import threading
import time

import pydivert
from pydivert import Flag, Layer

PORT = 47060
CONNECT = 4


def main():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", PORT))
    srv.listen(4)
    events = []
    with pydivert.Divert("tcp", layer=Layer.SOCKET, flags=Flag.SNIFF | Flag.RECV_ONLY) as w:
        stop = threading.Event()

        def loop():
            while not stop.is_set():
                try:
                    p = w.recv(timeout=0.1)
                except TimeoutError:
                    continue
                s = p.socket
                if s is not None and int(p.event) == CONNECT and int(s.RemotePort) == PORT:
                    events.append((int(s.LocalPort), int(s.ProcessId)))
        t = threading.Thread(target=loop)
        t.start()
        time.sleep(0.3)
        unbound = socket.create_connection(("127.0.0.1", PORT))
        bound = socket.socket()
        bound.bind(("127.0.0.1", 0))
        bound.connect(("127.0.0.1", PORT))
        used = [unbound.getsockname()[1], bound.getsockname()[1]]
        time.sleep(0.5)
        stop.set()
        t.join()
    unbound.close()
    bound.close()
    srv.close()
    print(f"pydivert {pydivert.__version__}, {platform.system()} {platform.release()}, pid {os.getpid()}")
    print(f"  ports the two connections use (getsockname): unbound {used[0]}, bound first {used[1]}")
    print(f"  CONNECT events (LocalPort, ProcessId): {events}")


if __name__ == "__main__":
    main()
