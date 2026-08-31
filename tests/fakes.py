"""Shared test doubles and helpers (no Windows / WinDivert required)."""
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG_DIR = os.path.join(ROOT, "lang")

# Every language the repository ships, DISCOVERED rather than listed. Nine guards
# looped over a hardcoded ("en", "pl") and went on reporting green the day a third
# file landed: label coverage, layout, presets, prefs and scope notes all stopped
# at two languages while the program shipped three. A pair written into a test is
# a claim that ages the moment somebody adds a file, and nobody re-reads a green
# loop. The separate question - whether we ship exactly the set we think we do -
# is asserted once, in smoke_gui.py, where an appearing or vanishing file is
# meant to be noticed rather than absorbed.
LANGS = tuple(sorted(os.path.splitext(name)[0] for name in os.listdir(LANG_DIR)
                     if name.lower().endswith(".json")))


def check(name, cond, detail=""):
    """Assertion helper keeping the original suite's readable messages.

    ``__tracebackhide__`` keeps the failure pointing at the CALLING test rather
    than at the ``assert`` inside this helper. Without it pytest's last frame is
    always this file, which is the one place the failure is never interesting.

    Pass ``detail`` whenever the values are not obvious from the name: pytest can
    only rewrite an ``assert`` it can see, so ``check("ports match", a == b)``
    reports the label and nothing else, while a plain ``assert a == b`` would show
    both sides.
    """
    __tracebackhide__ = True
    assert cond, f"{name} {detail}".strip()


def wait_until(predicate, timeout=5.0, interval=0.005):
    """Block until ``predicate()`` is true; returns whether it became true.

    Use this instead of ``time.sleep(0.05)`` before an assertion about worker
    state. A fixed wait is wrong in both directions: it is a race on a loaded CI
    box, and on a fast one it is dead time paid by every run. Polling to a
    deadline returns as soon as the thread has done its work and only spends the
    full timeout when the test is genuinely about to fail.

    It cannot express "this never happens" - for that, a fixed wait is still the
    honest tool, so those stay, with a comment saying so.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


class FakeTCP:
    def __init__(self, syn=False, ack=False):
        self.syn = syn
        self.ack = ack


class FakePacket:
    """A stand-in packet.

    ``src_port``/``dst_port`` default to ``port`` - the shape every existing test
    was written against - but can be set apart, and sometimes they MUST be. The
    engine reads the remote endpoint as the DESTINATION on an outbound packet and
    as the SOURCE on an inbound one; with both ports equal, a test cannot tell the
    two apart, so an assertion about direction is vacuous while looking sound.
    Found by a mutant surviving: swapping the inbound branch's two ports changed
    nothing anywhere in the suite (2026-07-29).
    """

    def __init__(self, size=100, is_outbound=True, port=1000, payload=b"hello world",
                 dst_addr="8.8.8.8", src_addr="10.0.0.2", syn=False,
                 src_port=None, dst_port=None):
        self.raw = b"\x00" * size
        self.is_outbound = is_outbound
        self.src_port = port if src_port is None else src_port
        self.dst_port = port if dst_port is None else dst_port
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
        # What the engine asked for on each send: True only when it edited the
        # packet. Recorded separately from `sent` so the existing readers of that
        # list keep their (time, packet) shape.
        self.recalc = []
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

    def send(self, p, recalculate_checksum=True):
        self.sent.append((time.monotonic(), p))
        self.recalc.append(recalculate_checksum)

    def close(self):
        self.closed = True
