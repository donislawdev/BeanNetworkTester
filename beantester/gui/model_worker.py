"""Rebuild a table's model on a worker thread, so the UI thread never blocks.

The tables are virtualised, so DRAWING them is free: a repaint is ~0.1 ms whether
the model holds 400 rows or a million. What is not free is deciding WHICH rows,
in WHAT order - the pure-Python filter and sort - and that still ran on the UI
thread, where it becomes a freeze:

===========  =====================  =========================
rows         filter + sort          search across 30 columns
===========  =====================  =========================
100 000      37 ms                  307 ms
500 000      162-361 ms             1 595 ms
1 000 000    332-744 ms             3 530 ms
2 000 000    1.2-1.5 s              -
===========  =====================  =========================

Every one of those numbers is a frozen window: no scrolling, no typing, no STOP
button. And STOP is the one control a network tester must never take away - the
user has impaired their own machine's networking and this is how they undo it.

So the rebuild moves off the UI thread:

* the worker gets a SNAPSHOT of the rows and does the filtering and sorting;
* the UI thread keeps the previous model on screen in the meantime - a table that
  is one second stale is not a problem; a table that will not scroll is;
* the result is picked up on the next tick and swapped in whole;
* requests coalesce - a user typing does not start six sorts of a million rows,
  the last request wins;
* a result that no longer matches what was asked for is DISCARDED, so a slow sort
  finishing after the user changed column cannot resurrect the old order.

Thread safety: the worker reads the engine's connection dicts while the capture
thread is still writing to them. That is safe here, and deliberately so - it reads
individual keys (atomic under the GIL) and never iterates a dict that the capture
thread might resize. ``sorted(key=...)`` extracts every key BEFORE it compares
anything, so the ordering it produces is consistent even if a counter moves under
it. The alternative - deep-copying 200 000 rows per refresh - costs more than the
sort it protects.
"""
import itertools
import queue
import threading

from .. import crashlog


class AsyncModel:
    """A model rebuilt off-thread, delivered to the UI thread whole.

    ``build(payload) -> rows`` runs on the WORKER. It must not touch a widget, and
    it must not raise (if it does, the failure is recorded and the old model stays
    on screen, which is the right thing to show a user mid-session).
    """

    def __init__(self, build, name="model-worker"):
        self._build = build
        self._name = name
        self._results = queue.Queue()
        self._tokens = itertools.count(1)
        self._pending = None            # token of the request in flight
        self._latest = None             # newest request, if one arrived while busy
        self._lock = threading.Lock()

    # -- UI thread ------------------------------------------------------------ #
    def request(self, payload):
        """Ask for a rebuild. Coalesces: while one is running, only the LAST wins."""
        with self._lock:
            if self._pending is not None:
                self._latest = payload      # somebody is already working; queue it
                return
            token = next(self._tokens)
            self._pending = token
        self._spawn(token, payload)

    def poll(self):
        """Main thread: the finished model, or None. Never blocks."""
        rows = None
        while True:
            try:
                token, result = self._results.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                current = self._pending
            if token == current:
                rows = result               # a newer request supersedes an older result
        if rows is None:
            return None

        with self._lock:
            self._pending = None
            queued = self._latest
            self._latest = None
        if queued is not None:
            self.request(queued)           # somebody asked again while we worked
        return rows

    def busy(self):
        with self._lock:
            return self._pending is not None

    # -- worker --------------------------------------------------------------- #
    def _spawn(self, token, payload):
        thread = threading.Thread(target=self._run, args=(token, payload),
                                  name=self._name, daemon=True)
        thread.start()

    def _run(self, token, payload):
        try:
            rows = self._build(payload)
        except Exception as exc:
            # the old model stays on screen: a stale table beats a broken one
            crashlog.note(exc, "gui.model_worker")
            with self._lock:
                if self._pending == token:
                    self._pending = None
            return
        self._results.put((token, rows))
