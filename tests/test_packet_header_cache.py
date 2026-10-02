"""A packet waiting in the release queue must not hold pydivert's header cache.

What this guards (performance review 2026-09-26, W-A1/W-A3)
----------------------------------------------------------
pydivert 3.1.3 caches every header it parses as a ``functools.cached_property``
in the packet's ``__dict__``, and every header points back at its packet
(``_packet``). That is a reference CYCLE: reference counting never frees it, only
the cyclic collector does. A packet that waits out a configured delay survives
the young collections, ages into the oldest generation and becomes garbage there,
so only a FULL collection frees it - and a full collection stops both worker
threads, on top of the latency this tool promises to keep precise.

MEASURED 2026-10-02 on the real driver (Win11, elevated, CPython 3.14.7, 8000 UDP
datagrams/s, ``--latency 500``, ``internal_tools/probe_latency_precision.py``):
p99.9 lateness 120-183 ms before ``_capture_loop`` dropped the cache, 16-19 ms
after - the level of the same run with the collector switched off - with full
collections of 48-123 ms gone.

Five tests, because the fix rests on more than one fact:

* the engine drops the cache of pydivert's OWN packet class before it queues one
  (a stand-in ``pydivert`` module with the same layout, so this runs on every
  runner - pydivert installs on Windows only);
* it leaves every OTHER packet type alone: the synthetic source and the test fakes
  keep their real fields in ``__dict__``, and clearing those would empty them;
* it leaves pydivert ITSELF alone when the class is laid out any other way than
  ``engine.PYDIVERT_SLOTS`` (an unpinned install, a future release);
* the real pydivert keeps what ``send()`` reads in ``__slots__`` and nothing but
  cached headers in ``__dict__`` - the condition that makes the clear safe at all;
* the real class is the one the engine finds (``sys.modules["pydivert"].Packet``).

The last two need pydivert and are skipped without it; the Windows runner has it.
"""
import functools
import struct
import sys
import time
import types

import pytest

from beantester import BeanEngine
from beantester.engine import PYDIVERT_SLOTS
from fakes import FakeDivert, FakePacket, check


class _Header:
    """What pydivert's TCPHeader keeps: a reference back to its packet."""

    def __init__(self, packet):
        self._packet = packet           # the back-reference that closes the cycle
        self.syn, self.ack = False, True


class _StandInPacket:
    """pydivert's layout in miniature: real fields in slots, caches in __dict__.

    The slot NAMES are pydivert's (``engine.PYDIVERT_SLOTS``): the engine clears
    only a class laid out that way.
    """

    __slots__ = ("raw", "_wd_addr", "_direction", "_sport", "__dict__")
    udp = icmp = icmpv6 = None

    def __init__(self, sport):
        self.raw = b"\x00" * 60
        self._wd_addr = None
        self._direction = 0             # pydivert's Direction.OUTBOUND
        self._sport = sport

    @property
    def is_outbound(self):
        return self._direction == 0

    @functools.cached_property
    def tcp(self):
        return _Header(self)

    @property
    def src_port(self):
        return self._sport if self.tcp else None      # reads through the cache

    @property
    def dst_port(self):
        return 443 if self.tcp else None

    dst_addr = "93.184.216.34"
    src_addr = "10.0.0.2"


class _ReshapedPacket:
    """A pydivert that keeps its fields in __dict__ - a layout nobody measured."""

    udp = icmp = icmpv6 = None
    is_outbound = True
    dst_addr = "93.184.216.34"
    src_addr = "10.0.0.2"

    def __init__(self, sport):
        self.raw = b"\x00" * 60
        self._sport = sport

    @functools.cached_property
    def tcp(self):
        return _Header(self)

    @property
    def src_port(self):
        return self._sport if self.tcp else None

    @property
    def dst_port(self):
        return 443 if self.tcp else None


def _stand_in_pydivert(monkeypatch, packet_class=_StandInPacket):
    module = types.ModuleType("pydivert")
    module.Packet = packet_class
    monkeypatch.setitem(sys.modules, "pydivert", module)


def _queued_after_capture(packets, timeout=15.0):
    """Run a session that queues every packet for 60 s; return what sits in the queue."""
    eng = BeanEngine()
    eng.set_params(0, 0, 0, 60000, 0, 0, 0)    # 60 s latency: nothing is released in time
    eng.start("test", divert=FakeDivert(packets))
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = eng.stats_snapshot()
            if s["seen"] >= len(packets) and s["queue"] >= len(packets):
                break
            time.sleep(0.02)
        with eng._cv:
            queued = [entry[2] for entry in eng._heap]
        rows = eng.connections_snapshot(limit=None)
    finally:
        eng.stop()
    return queued, rows


def test_a_queued_pydivert_packet_holds_no_header_cache(monkeypatch):
    _stand_in_pydivert(monkeypatch)
    n = 40
    queued, rows = _queued_after_capture([_StandInPacket(40000 + i) for i in range(n)])
    check("every packet reached the queue", len(queued) == n, f"(queued={len(queued)})")
    check("the engine read the header (otherwise the cache was never built)",
          rows and all(r["proto"] == "TCP" and r["remote_port"] == 443 for r in rows),
          f"(rows={rows[:2]})")
    holding = [p for p in queued if p.__dict__]
    check("no queued packet keeps the header cache that makes it a cycle", not holding,
          f"({len(holding)} of {len(queued)} still hold {sorted(holding[0].__dict__) if holding else ''})")
    check("what the injector reads is still there",
          all(p.raw and p.is_outbound for p in queued))


def test_only_pydivert_s_own_packets_lose_their_cache(monkeypatch):
    """The synthetic source and the fakes keep their FIELDS in __dict__."""
    _stand_in_pydivert(monkeypatch)
    fakes = [FakePacket(size=80, port=41000 + i, dst_port=443) for i in range(20)]
    queued, _rows = _queued_after_capture(fakes + [_StandInPacket(42000 + i) for i in range(20)])
    kept = [p for p in queued if isinstance(p, FakePacket)]
    check("every fake reached the queue", len(kept) == len(fakes), f"(kept={len(kept)})")
    emptied = [p for p in kept if "raw" not in p.__dict__]
    check("a packet that is not pydivert's keeps its fields", not emptied,
          f"({len(emptied)} of {len(kept)} fakes were emptied)")


def test_a_pydivert_laid_out_another_way_is_left_alone(monkeypatch):
    """The clear is safe only for the layout it was measured on.

    A pydivert that kept ``raw`` in ``__dict__`` - an unpinned install from source,
    a future release - would lose the bytes ``send()`` needs. Such a class is left
    alone: the old cost, never a broken packet.
    """
    _stand_in_pydivert(monkeypatch, _ReshapedPacket)
    queued, _rows = _queued_after_capture([_ReshapedPacket(44000 + i) for i in range(20)])
    check("every packet reached the queue", len(queued) == 20, f"(queued={len(queued)})")
    emptied = [p for p in queued if "raw" not in p.__dict__]
    check("a packet laid out another way keeps its fields", not emptied,
          f"({len(emptied)} of {len(queued)} lost them)")


def _raw_ipv4_tcp(sport, dport=443):
    tcp = struct.pack(">HHIIBBHHH", sport, dport, 1, 2, 0x50, 0x10, 8192, 0, 0)
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 1, 0, 64, 6, 0,
                     bytes([10, 0, 0, 2]), bytes([93, 184, 216, 34]))
    return bytearray(ip + tcp)


def test_pydivert_keeps_what_send_reads_out_of_the_dict_the_engine_clears():
    pydivert = pytest.importorskip("pydivert")
    slots = set(getattr(pydivert.Packet, "__slots__", ()))
    needed = set(PYDIVERT_SLOTS) | {"_interface"}
    check("pydivert keeps the packet's real fields in __slots__ - the layout the "
          "engine checks before it clears anything", needed <= slots,
          f"(missing {sorted(needed - slots)})")
    p = pydivert.Packet(_raw_ipv4_tcp(50001), (1, 0), pydivert.Direction.OUTBOUND)
    before = (p.src_port, p.dst_port, p.dst_addr, p.tcp.syn, p.udp)
    cached = set(p.__dict__)
    caches = {name for name, value in vars(pydivert.Packet).items()
              if isinstance(value, functools.cached_property)}
    check("reading the header filled the cache (or this proves nothing)", cached)
    check("nothing but cached headers lives in __dict__", cached <= caches,
          f"(not a cache: {sorted(cached - caches)})")
    check("the cache really is a cycle", p.tcp._packet is p)
    p.__dict__.clear()
    check("the bytes and the direction survive the clear",
          len(p.raw) == 40 and p.is_outbound)
    check("every header reads back the same", (p.src_port, p.dst_port, p.dst_addr,
                                               p.tcp.syn, p.udp) == before)


def test_real_pydivert_packets_reach_the_queue_without_their_cache():
    pydivert = pytest.importorskip("pydivert")
    n = 20
    packets = [pydivert.Packet(_raw_ipv4_tcp(43000 + i), (1, 0), pydivert.Direction.OUTBOUND)
               for i in range(n)]
    queued, _rows = _queued_after_capture(packets)
    check("every packet reached the queue", len(queued) == n, f"(queued={len(queued)})")
    holding = [p for p in queued if p.__dict__]
    check("the engine found pydivert's own class and cleared it", not holding,
          f"({len(holding)} of {len(queued)} still hold {sorted(holding[0].__dict__) if holding else ''})")
