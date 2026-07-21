"""Presentation helpers: sorting/filtering for the event and connection tables.

These run over the WHOLE model (which may hold hundreds of thousands of flows),
so they never copy a row and never materialise a derived column: the tables are
virtualised and format only what is on screen.
"""
import heapq

PARTIAL_SORT_RATIO = 10     # use a heap only when the limit is this much smaller


class SearchIndex:
    """Cached lowercase search text, one entry per row.

    Searching a table means matching the query against every column of every row.
    That is fine for the four columns the connection log has today. It is not fine
    for the tables this tool is heading towards: measured over **30 columns**, a
    plain scan costs 307 ms at 100 000 rows, **1.6 s at 500 000** and 3.5 s at a
    million - per keystroke, on the UI thread.

    Nearly all of that is rebuilding the same strings over and over: the fields a
    search looks at (process, protocol, addresses, ports) do not change over a
    flow's life. So join and lowercase them ONCE, keep the result, and a search
    becomes a substring test - which is ~25x cheaper and, more importantly, flat in
    the number of columns.

    The cache is owned by the PAGE, not written into the engine's rows. The capture
    thread writes to those dicts continuously; adding a key to one from the UI
    thread can resize it under a reader's feet ("dictionary changed size during
    iteration"), and a caching layer that corrupts the thing it is caching is not a
    good trade.
    """

    def __init__(self, blob_of, key_of, limit=250_000):
        self._blob_of = blob_of         # item -> the text to search (uncached)
        self._key_of = key_of           # item -> stable identity
        self._limit = int(limit)
        self._cache = {}                # key -> (stamp, blob)

    def blob(self, item, stamp=None):
        """The search text for ``item``, built at most once per ``stamp``.

        ``stamp`` is whatever makes the text stale - for a connection that is the
        process name, which starts out unknown and is filled in later.
        """
        key = self._key_of(item)
        hit = self._cache.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        blob = self._blob_of(item).lower()
        if len(self._cache) >= self._limit:
            self._cache.clear()         # bounded: a table this size churns anyway
        self._cache[key] = (stamp, blob)
        return blob

    def filter(self, items, query, stamp_of=None):
        q = (query or "").strip().lower()
        if not q:
            return list(items)
        if stamp_of is None:
            return [it for it in items if q in self.blob(it)]
        return [it for it in items if q in self.blob(it, stamp_of(it))]

    def clear(self):
        self._cache.clear()


def sort_events(events, sort_col="t", reverse=False):
    """Sort events (tuples: t, iso, type, description) by the chosen column."""
    idx = {"t": 0, "time": 1, "type": 2, "desc": 3}.get(sort_col, 0)
    numeric = sort_col == "t"

    def key(e):
        v = e[idx] if len(e) > idx else ""
        if numeric:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
        return str(v).lower()

    return sorted(events, key=key, reverse=reverse)


def connection_proc(c, proc_map=None):
    """Process name for a connection row ("" when it could not be resolved)."""
    name = c.get("proc") or ""
    if not name and proc_map:
        name = proc_map.get(c.get("local_port"), "")
    return name


def avg_packet_bytes(c):
    """Mean bytes per packet for a connection row, as a rounded integer.

    Shared by the on-screen table cell and the CSV export so the two can never
    disagree: the table used to round (``f"{avg:.0f}"``) while the export floored
    (``bytes // packets``), so a flow at 767.5 B/pkt showed 768 on screen and 767
    in the file. One helper, one number.
    """
    packets = c.get("packets") or 0
    return round(c.get("bytes", 0) / max(1, packets))


# Columns the table shows but the engine does not store: they are DERIVED from
# the raw row. They used to be materialised into a copy of every connection
# before sorting - which is fine for 400 rows and hundreds of milliseconds of
# pointless work at 200 000. Now they are computed inside the sort key, i.e.
# once per row per sort, and rendered only for the rows actually on screen.
DERIVED = {
    "down": lambda c, now: c.get("bytes_in", 0) / 1024.0,
    "up": lambda c, now: c.get("bytes_out", 0) / 1024.0,
    "kb": lambda c, now: c.get("bytes", 0) / 1024.0,
    "avg": lambda c, now: c.get("bytes", 0) / max(1, c.get("packets", 0)),
    "scoped": lambda c, now: 1 if c.get("scoped") else 0,
    "dur": lambda c, now: max(0.0, c.get("last", now) - c.get("first", now)),
    "idle": lambda c, now: max(0.0, now - c.get("last", now)),
    "proc": lambda c, now: str(c.get("proc") or "").lower(),
}


def _connection_blob(c, proc_map=None):
    """The lowercase text a search matches against - one place, so the table filter
    and the footer totals agree on what "matches" means."""
    return (f"{connection_proc(c, proc_map)} {c.get('proto', '')} {c.get('dir', '')} "
            f"{c.get('remote_ip', '')}:{c.get('remote_port', '')} "
            f"{c.get('local_port', '')}").lower()


def _filter_connections(conns, query, proc_map):
    q = (query or "").strip().lower()
    if not q:
        return list(conns)
    return [c for c in conns if q in _connection_blob(c, proc_map)]


def traffic_totals(conns, query="", proc_map=None):
    """Summed download / upload / total BYTES over the FILTERED rows.

    Feeds the connection table's footer. It sums every matching flow, not only the
    rows that fit under the display limit, so the footer is a true total of what the
    search selects - which is exactly the number the display cap hides."""
    down = up = total = 0
    for c in _filter_connections(conns, query, proc_map):
        down += c.get("bytes_in", 0)
        up += c.get("bytes_out", 0)
        total += c.get("bytes", 0)
    return {"down": down, "up": up, "total": total}


def filter_sort_connections(conns, query="", sort_col="bytes", reverse=True,
                            now=None, proc_map=None, limit=0):
    """Filter connections by text (process/IP/port/proto) and sort by a column.

    Returns the SAME row objects, filtered and ordered - no copies, so this stays
    cheap on a table that may hold hundreds of thousands of flows.

    ``limit`` (0 = none) caps the result AND is used to pick the cheaper strategy:
    a partial selection (``heapq``) beats a full sort only when the limit is small
    next to the input. Hence the ratio test rather than "always use the heap".

    Re-measured 2026-07-21 (Win11 AMD64, CPython 3.14.6, 200 000 synthetic rows with
    well-spread keys, median of 7):

    ======  ==========  ==============
    top N   nlargest    sort + slice
    ======  ==========  ==============
       400  12.6 ms     27.7 ms
     5 000  23.4 ms     26.7 ms
    50 000  130.6 ms    28.0 ms
    ======  ==========  ==============

    The crossover is what this function encodes; the absolute figures move with the
    machine and the Python build, so compare the two COLUMNS, never a number here
    against a number you measured. (A previous revision quoted 28/107 and 371/123 ms
    with no conditions attached - same shape, roughly 2-4x slower hardware. Beware
    also of benchmarking this with keys drawn from a tiny range: Timsort exploits
    the resulting runs and the sort column comes out artificially fast.)
    """
    out = _filter_connections(conns, query, proc_map)
    numeric = sort_col in ("remote_port", "local_port", "packets", "bytes",
                           "bytes_in", "bytes_out", "down", "up", "kb", "avg",
                           "dropped", "pid", "dur", "idle", "first", "last")
    derived = DERIVED.get(sort_col)
    clock = now if now is not None else 0.0

    def key(c):
        if derived is not None:
            return derived(c, clock)
        v = c.get(sort_col, "")
        if numeric:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
        return str(v).lower()

    if limit and limit * PARTIAL_SORT_RATIO <= len(out):
        picker = heapq.nlargest if reverse else heapq.nsmallest
        return picker(limit, out, key=key)
    out.sort(key=key, reverse=reverse)
    return out[:limit] if limit else out
