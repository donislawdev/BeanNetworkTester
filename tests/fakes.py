"""Shared test doubles and helpers (no Windows / WinDivert required)."""
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG_DIR = os.path.join(ROOT, "lang")


def check(name, cond, detail=""):
    """Assertion helper keeping the original suite's readable messages."""
    assert cond, f"{name} {detail}".strip()


class FakeTCP:
    def __init__(self, syn=False, ack=False):
        self.syn = syn
        self.ack = ack


class FakePacket:
    def __init__(self, size=100, is_outbound=True, port=1000, payload=b"hello world",
                 dst_addr="8.8.8.8", src_addr="10.0.0.2", syn=False):
        self.raw = b"\x00" * size
        self.is_outbound = is_outbound
        self.src_port = port
        self.dst_port = port
        self.dst_addr = dst_addr
        self.src_addr = src_addr
        self.tcp = FakeTCP(syn=syn) if syn else None
        self._payload = payload

    @property
    def payload(self):
        return self._payload

    @payload.setter
    def payload(self, v):
        self._payload = v


class FakeDivert:
    """Feeds a fixed list of packets and records everything sent back."""

    def __init__(self, packets):
        self.inbox = list(packets)
        self.i = 0
        self.sent = []
        self.closed = False

    def open(self):
        pass

    def recv(self):
        if self.i < len(self.inbox):
            p = self.inbox[self.i]
            self.i += 1
            return p
        while not self.closed:
            time.sleep(0.003)
        raise OSError("closed")

    def send(self, p):
        self.sent.append((time.monotonic(), p))

    def close(self):
        self.closed = True
