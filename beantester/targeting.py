"""Process targeting: which LOCAL ports belong to the targeted processes.

Why this is not just "a set of ports"
-------------------------------------
The old implementation resolved the target expression into a plain ``set`` of
local ports every 2 seconds. Two things escaped it, and both were reported from
the field ("I target chrome and the browser keeps working"):

1. **New sockets.** A browser opens connections continuously; each one gets a
   fresh ephemeral port that is not in the set yet, so every packet of it was
   passed through untouched until the next scan - up to 2 seconds of perfectly
   healthy traffic.
2. **Child processes.** ``chrome.exe`` (the browser process) owns no sockets at
   all - its *network service* child does. Targeting the browser's PID resolved
   to zero ports, i.e. to nothing at all.

So targeting is a live object instead:

* it rebuilds its port set every ``interval`` (300 ms by default, cheap thanks
  to :mod:`beantester.portmap`),
* an **unknown port forces an early rebuild** (rate limited to ``miss_interval``),
  which shrinks the "new socket slips through" window from seconds to tens of
  milliseconds,
* a socket belongs to the target when its owning process **or any of its
  ancestors** matches the expression - so a PID (or a name) covers the whole
  process tree. An explicitly EXCLUDED process (``!chromedriver``) is never
  pulled back in by its parent.

``BeanCore.decide()`` keeps its ``local_port not in target_ports`` test: this
class simply *is* the container it tests against (``__contains__``).

Hard limit, documented on purpose: WinDivert hands us a packet, not a PID, so
the port -> process mapping is inherently a race. It cannot be closed, only made
small; the very first packet of a brand-new connection may still slip through.
"""
import threading
import time

from . import portmap


class ProcessTargeting:
    """The set of local ports owned by the processes matching an expression."""

    def __init__(self, matcher, table=None, interval=portmap.REFRESH_S,
                 miss_interval=portmap.MISS_REFRESH_S, clock=time.monotonic):
        self.matcher = matcher
        self.expression = getattr(matcher, "raw", str(matcher))
        self.table = table if table is not None else portmap.default_table()
        self.interval = float(interval)
        self.miss_interval = float(miss_interval)
        self.clock = clock
        self._lock = threading.RLock()
        self._ports = frozenset()
        self._names = ()
        self._pids = frozenset()
        self._last = 0.0
        self._refreshes = 0

    # -- resolution ----------------------------------------------------------- #
    def _matches(self, pid, name):
        return bool(self.matcher.matches(pid, name))

    def _excluded(self, pid, name):
        excluded = getattr(self.matcher, "excluded", None)
        return bool(excluded(pid, name)) if excluded else False

    def refresh(self, now=None, force=True):
        """Rebuild the port set from the current socket table."""
        now = self.clock() if now is None else now
        with self._lock:
            self.table.refresh(force=force)
            port_pid = self.table.snapshot()
            pids, names = set(), set()
            for pid in set(port_pid.values()):
                name = self.table.name_of(pid)
                if self._matches(pid, name):
                    pids.add(pid)
                    names.add(name or str(pid))
                    continue
                if self._excluded(pid, name):
                    continue      # an explicit "!" wins over an inherited match
                for ancestor_pid, ancestor_name in self.table.ancestors(pid):
                    if self._matches(ancestor_pid, ancestor_name):
                        pids.add(pid)
                        names.add(name or str(pid))
                        break
            self._pids = frozenset(pids)
            self._ports = frozenset(port for port, pid in port_pid.items()
                                    if pid in pids)
            self._names = tuple(sorted(n for n in names if n))
            self._last = now
            self._refreshes += 1
            return self._ports

    # -- the container BeanCore tests against ---------------------------------- #
    def __contains__(self, port):
        if port is None:
            return False
        now = self.clock()
        if (now - self._last) >= self.interval:
            self.refresh(now)
        if port in self._ports:
            return True
        # An unknown port is the interesting case: it is either traffic we do not
        # care about, or a connection the target opened microseconds ago. Only a
        # fresh look can tell - rate limited, so a busy link cannot turn this into
        # a rebuild per packet.
        if (now - self._last) >= self.miss_interval:
            self.refresh(now)
            return port in self._ports
        return False

    def __iter__(self):
        return iter(self._ports)

    def __len__(self):
        return len(self._ports)

    def __eq__(self, other):
        if isinstance(other, (set, frozenset)):
            return set(self._ports) == set(other)
        return NotImplemented

    def __hash__(self):                                   # pragma: no cover
        return hash(self._ports)

    def __repr__(self):                                   # pragma: no cover
        return f"<ProcessTargeting {self.expression!r} {len(self._ports)} ports>"

    # -- reporting -------------------------------------------------------------- #
    def ports(self):
        return set(self._ports)

    def pids(self):
        return set(self._pids)

    def names(self):
        return list(self._names)

    def describe(self):
        return ", ".join(self._names) if self._names else NO_PROCESS

    @property
    def matched(self):
        """True when at least one process (with a socket) matched."""
        return bool(self._pids)

    @property
    def refreshes(self):
        return self._refreshes


NO_PROCESS = "(none)"


def resolve_ports(matcher, table=None):
    """One-shot resolution: ``(ports, description)`` for a compiled matcher.

    Used by the CLI/GUI when they only want to *report* what an expression
    resolves to right now (``find_process_ports``).
    """
    targeting = ProcessTargeting(matcher, table=table)
    targeting.refresh()
    return targeting.ports(), targeting.describe()
