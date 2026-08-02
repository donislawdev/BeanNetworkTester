"""Presentation helpers: sorting/filtering for the event and connection tables.

These run over the WHOLE model (which may hold hundreds of thousands of flows),
so they never copy a row and never materialise a derived column: the tables are
virtualised and format only what is on screen.
"""
import heapq

from .matchers import KIND_INT, KIND_IP, KIND_PROCESS, PORT_BOUNDS, parse_matcher

PARTIAL_SORT_RATIO = 10     # use a heap only when the limit is this much smaller

# -- field-qualified search ----------------------------------------------------- #
#
# The plain search matches one substring against a blob of process, protocol,
# direction, addresses and ports. That is 6 of the table's 17 columns: a PID is on
# screen and cannot be searched for, and neither can "only the impaired rows" or
# "only rows that dropped something" - which are the questions a tester actually
# has when the table holds a hundred thousand flows.
#
# So a term may name its column: `port:443`, `ip:10.0.0.0/8`, `pid:>4000`. The
# VALUE is parsed by `matchers.py`, i.e. the same mini-language as the form fields
# (comma lists, ranges, `!`, `>` `<`, wildcards, `re:`, CIDR). Nothing new to learn
# and, more to the point, nothing new to maintain: a second syntax for the same job
# would drift from the first one on its first edit (convention 10).
#
# Bare text keeps working exactly as before, so no existing habit breaks.
#
# `kind` is what the value is parsed as; `get` pulls the comparable value off a row.
# PROCESS is the text kind here: it is the one that understands wildcards, `re:` and
# `!` on names, which is what "search a text column" means.
SEARCH_FIELDS = {
    "proc":    (KIND_PROCESS, None),        # special: matched with (pid, name)
    "pid":     (KIND_INT, lambda c, m: c.get("pid")),
    "proto":   (KIND_PROCESS, lambda c, m: c.get("proto")),
    "dir":     (KIND_PROCESS, lambda c, m: c.get("dir")),
    "ip":      (KIND_IP, lambda c, m: c.get("remote_ip")),
    "port":    (KIND_INT, lambda c, m: c.get("remote_port")),
    "lport":   (KIND_INT, lambda c, m: c.get("local_port")),
    "packets": (KIND_INT, lambda c, m: c.get("packets")),
    "dropped": (KIND_INT, lambda c, m: c.get("dropped")),
    "down":    (KIND_INT, lambda c, m: c.get("sent_in")),
    "up":      (KIND_INT, lambda c, m: c.get("sent_out")),
    "bytes":   (KIND_INT, lambda c, m: c.get("sent")),
}

# The one genuine boolean on a row. It gets words rather than an expression because
# `scoped:yes` reads like a question and `scoped:1` reads like a bug report about the
# search box. "Has drops" needs no boolean of its own - that is `dropped:>0`.
BOOL_FIELDS = {"scoped"}
TRUE_WORDS = {"yes", "y", "true", "1", "tak"}
FALSE_WORDS = {"no", "n", "false", "0", "nie"}

_BOUNDS = {"port": PORT_BOUNDS, "lport": PORT_BOUNDS}


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
    # down/up/kb are DELIVERED - what the application actually got, the same
    # quantity the session panel and the repro report call "Downloaded". They used
    # to be the CAPTURED bytes under those headings, which is a different number
    # whenever the tool is doing its job: measured 5 122 600 B in a row whose
    # application received 409 600 B. Captured is still here, as down_seen/up_seen.
    "down": lambda c, now: c.get("sent_in", 0) / 1024.0,
    "up": lambda c, now: c.get("sent_out", 0) / 1024.0,
    "kb": lambda c, now: c.get("sent", 0) / 1024.0,
    "down_seen": lambda c, now: c.get("bytes_in", 0) / 1024.0,
    "up_seen": lambda c, now: c.get("bytes_out", 0) / 1024.0,
    "avg": lambda c, now: c.get("bytes", 0) / max(1, c.get("packets", 0)),
    "scoped": lambda c, now: 1 if c.get("scoped") else 0,
    "dur": lambda c, now: max(0.0, c.get("last", now) - c.get("first", now)),
    "idle": lambda c, now: max(0.0, now - c.get("last", now)),
    "proc": lambda c, now: str(c.get("proc") or "").lower(),
}


def _connection_blob(c, proc_map=None):
    """The lowercase text a search matches against - one place, so the table filter
    and the footer totals agree on what "matches" means."""
    # `or ''` rather than a dict default: a portless row (ICMP) HAS the port keys,
    # they just hold None, so the default never fires and the blob would read
    # "8.8.8.8:none" - making every ping row a hit for the search term "none".
    return (f"{connection_proc(c, proc_map)} {c.get('proto') or ''} {c.get('dir') or ''} "
            f"{c.get('remote_ip') or ''}:{c.get('remote_port') or ''} "
            f"{c.get('local_port') or ''}").lower()


def compile_query(query):
    """Turn a search string into a list of predicates, ONCE per query.

    Compiling per row would put the expression parser on the path of every one of
    a hundred thousand rows on every keystroke, which is the shape of the problem
    ``SearchIndex`` exists to solve, reintroduced one layer up. So parse here and
    return closures; the row loop then only calls them.

    A term is either ``field:value`` or bare text. Terms are ANDed, because that is
    what narrowing means and what every search box a tester has used does.

    An unparsable value is NOT an error: the box is typed into character by
    character, so `port:44` is a valid search on the way to `port:443` and half of
    `ip:10.0.` must not throw or blank the table. Such a term simply matches
    nothing until it becomes valid, and a term naming an unknown field falls back
    to plain text - `http://x` is a URL someone pasted, not a field called `http`.
    """
    tests = []
    for raw in str(query or "").split():
        field, sep, value = raw.partition(":")
        field = field.lower()
        if not sep or (field not in SEARCH_FIELDS and field not in BOOL_FIELDS):
            text = raw.lower()
            tests.append(lambda c, m, t=text: t in _connection_blob(c, m))
            continue
        if field in BOOL_FIELDS:
            want = value.strip().lower()
            if want in TRUE_WORDS:
                tests.append(lambda c, m, k=field: bool(c.get(k)))
            elif want in FALSE_WORDS:
                tests.append(lambda c, m, k=field: not c.get(k))
            else:                                   # half-typed: match nothing yet
                tests.append(lambda c, m: False)
            continue
        kind, getter = SEARCH_FIELDS[field]
        try:
            matcher = parse_matcher(value, kind, f"fields.{field}",
                                    bounds=_BOUNDS.get(field))
        except ValueError:
            tests.append(lambda c, m: False)
            continue
        if not matcher:                             # `port:` with nothing after it
            continue
        if field == "proc":
            # The process kind judges (pid, name) together, exactly as the target
            # field does - so `proc:1234` and `proc:chrome` both work here for the
            # same reason they both work there.
            tests.append(lambda c, m, x=matcher: x.matches(c.get("pid"),
                                                           connection_proc(c, m)))
        elif kind == KIND_PROCESS:
            # A text column is a process matcher with no pid: the value goes in the
            # NAME position. Passing it positionally instead gives it to `pid`,
            # where a name cannot be evaluated - and an unevaluable term quietly
            # matches nothing, so `proto:tcp` found zero rows while looking correct.
            tests.append(lambda c, m, x=matcher, g=getter: x.matches(None, g(c, m)))
        else:
            tests.append(lambda c, m, x=matcher, g=getter: x.matches(g(c, m)))
    return tests


def _filter_connections(conns, query, proc_map):
    tests = compile_query(query)
    if not tests:
        return list(conns)
    return [c for c in conns if all(t(c, proc_map) for t in tests)]


def traffic_totals(conns, query="", proc_map=None):
    """Summed download / upload / total BYTES over the FILTERED rows.

    Feeds the connection table's footer. It sums every matching flow, not only the
    rows that fit under the display limit, so the footer is a true total of what the
    search selects - which is exactly the number the display cap hides."""
    down = up = total = 0
    for c in _filter_connections(conns, query, proc_map):
        # DELIVERED, because the footer uses the same three words as the columns
        # above it ("down / up / total") and those are delivered now. A footer
        # summing captured under headings that mean delivered is the same mismatch
        # this split exists to remove, one row lower down.
        down += c.get("sent_in", 0)
        up += c.get("sent_out", 0)
        total += c.get("sent", 0)
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
                           "bytes_in", "bytes_out", "sent", "sent_in", "sent_out",
                           "down", "up", "kb", "down_seen", "up_seen", "avg",
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
