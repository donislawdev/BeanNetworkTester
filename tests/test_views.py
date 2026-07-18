"""Table presentation helpers (``beantester/views.py``).

``test_summary_repro_views.py`` already covers the basic ``filter_sort_connections``
and ``sort_events`` paths. This file targets the parts that stay dark there and
that carry real risk:

* the **limit / partial-sort** branch (convention 24): when a row cap is small
  next to the input, the code switches from a full sort to a heap. The switch
  must never change the RESULT, only the cost - a silent divergence here would
  mis-order the connection table on exactly the large tables the optimisation
  exists for.
* the **derived columns** (kb / dur / idle) computed inside the sort key.
* ``SearchIndex`` - the per-keystroke search cache, whose correctness hinges on
  rebuilding when a row's stamp changes and on never mutating the rows it caches.
"""
from beantester.views import (SearchIndex, avg_packet_bytes, connection_proc,
                              filter_sort_connections, traffic_totals)
from fakes import check


def test_avg_packet_bytes_rounds_like_the_table():
    """The table cell and the CSV export must show the same mean bytes/packet.

    The table rounded (`f"{avg:.0f}"`) while the export floored (`bytes //
    packets`), so a flow at 767.5 B/pkt read 768 on screen and 767 in the file.
    Both now go through this one helper, which rounds.
    """
    check("avg: rounds to nearest (the number the table shows)",
          avg_packet_bytes({"bytes": 3070, "packets": 4}) == 768)   # 767.5 -> 768
    check("avg: exact division is unchanged",
          avg_packet_bytes({"bytes": 3072, "packets": 4}) == 768)
    check("avg: zero packets does not divide by zero",
          avg_packet_bytes({"bytes": 500, "packets": 0}) == 500)
    check("avg: missing fields count as zero", avg_packet_bytes({}) == 0)


def _conn(port, ip, proc, bin_, bout, packets=1, proto="TCP"):
    return dict(local_port=port, remote_ip=ip, remote_port=443, proto=proto,
                packets=packets, bytes=bin_ + bout, bytes_in=bin_, bytes_out=bout,
                dir="out", proc=proc)


def test_traffic_totals_sum_filtered_bytes():
    conns = [_conn(1, "1.1.1.1", "chrome.exe", 2048, 1024),
             _conn(2, "8.8.8.8", "chrome.exe", 100, 500),
             _conn(3, "9.9.9.9", "svchost.exe", 4096, 0)]
    t = traffic_totals(conns)
    check("totals: download summed", t["down"] == 2048 + 100 + 4096, f"({t})")
    check("totals: upload summed", t["up"] == 1024 + 500 + 0, f"({t})")
    check("totals: total summed", t["total"] == t["down"] + t["up"], f"({t})")
    # the footer sum honours the search, exactly like the table it sits under
    only = traffic_totals(conns, "chrome")
    check("totals: search narrows the sum", only["down"] == 2148 and only["up"] == 1524,
          f"({only})")


def test_sort_by_every_new_numeric_column():
    """down/up are DERIVED (KB), dropped/pid are plain numeric fields - every one
    must actually order the table, or a header click would silently do nothing."""
    a = _conn(1, "1.1.1.1", "x", 800, 200)     # more download
    a["dropped"], a["pid"] = 5, 100
    b = _conn(2, "2.2.2.2", "y", 100, 900)      # more upload
    b["dropped"], b["pid"] = 1, 200

    def top(col):
        return filter_sort_connections([b, a], sort_col=col, reverse=True)[0]["local_port"]

    check("sort by down: most-downloaded first", top("down") == 1, f"({top('down')})")
    check("sort by up: most-uploaded first", top("up") == 2, f"({top('up')})")
    check("sort by dropped: most-dropped first", top("dropped") == 1, f"({top('dropped')})")
    check("sort by pid: highest pid first", top("pid") == 2, f"({top('pid')})")


def test_derived_avg_and_scoped():
    a = _conn(1, "1.1.1.1", "x", 900, 100, packets=4)     # 1000 bytes / 4 packets
    a["scoped"] = True
    b = _conn(2, "2.2.2.2", "y", 300, 0, packets=3)        # 300 / 3
    b["scoped"] = False
    by_avg = filter_sort_connections([a, b], sort_col="avg", reverse=True)
    check("avg: sorts by mean packet size (250 > 100)",
          by_avg[0]["local_port"] == 1, f"({[c['local_port'] for c in by_avg]})")
    by_scope = filter_sort_connections([b, a], sort_col="scoped", reverse=True)
    check("scoped: in-scope rows sort first when reversed",
          by_scope[0]["local_port"] == 1, f"({[c['local_port'] for c in by_scope]})")


def make_conns(n):
    """n connection rows with strictly increasing, distinct sortable fields."""
    return [{
        "bytes": i * 1000, "packets": i, "remote_ip": f"10.0.0.{i % 256}",
        "remote_port": 1000 + i, "local_port": 40000 + i, "proto": "TCP",
        "dir": "out", "first": float(i), "last": float(i) + 5.0, "proc": "",
    } for i in range(n)]


# --- limit / heap-vs-sort must agree with the full sort ---------------------- #
def test_small_limit_uses_the_heap_but_matches_a_full_sort_descending():
    conns = make_conns(500)                 # 500 rows
    limit = 10                              # 10 * 10 <= 500 -> heap path taken
    heaped = filter_sort_connections(conns, sort_col="bytes", reverse=True, limit=limit)
    full = filter_sort_connections(conns, sort_col="bytes", reverse=True)[:limit]
    check("heap path returns the requested count", len(heaped) == limit, f"({len(heaped)})")
    check("heap top-N equals full-sort top-N (desc)",
          [c["bytes"] for c in heaped] == [c["bytes"] for c in full])


def test_small_limit_matches_a_full_sort_ascending():
    conns = make_conns(500)
    limit = 10
    heaped = filter_sort_connections(conns, sort_col="bytes", reverse=False, limit=limit)
    full = filter_sort_connections(conns, sort_col="bytes", reverse=False)[:limit]
    check("heap bottom-N equals full-sort bottom-N (asc)",
          [c["bytes"] for c in heaped] == [c["bytes"] for c in full])


def test_large_limit_stays_on_the_full_sort_path():
    conns = make_conns(200)
    limit = 100                             # 100 * 10 > 200 -> full sort, then [:limit]
    out = filter_sort_connections(conns, sort_col="bytes", reverse=True, limit=limit)
    expected = sorted((c["bytes"] for c in conns), reverse=True)[:limit]
    check("large limit still caps the result", len(out) == limit, f"({len(out)})")
    check("large-limit result is correctly ordered",
          [c["bytes"] for c in out] == expected)


def test_limit_zero_returns_everything():
    conns = make_conns(50)
    out = filter_sort_connections(conns, sort_col="bytes", reverse=True, limit=0)
    check("limit=0 means no cap", len(out) == 50, f"({len(out)})")


# --- derived columns --------------------------------------------------------- #
def test_sort_by_derived_kb_matches_bytes_order():
    conns = make_conns(20)
    out = filter_sort_connections(conns, sort_col="kb", reverse=True, limit=0)
    check("kb sorts by bytes/1024, i.e. by bytes",
          [c["bytes"] for c in out] == sorted((c["bytes"] for c in conns), reverse=True))


def test_sort_by_derived_idle_uses_now():
    # idle = now - last; larger 'last' -> smaller idle. With now fixed, the row
    # with the largest 'last' must be the least idle.
    conns = make_conns(20)
    now = 100.0
    out = filter_sort_connections(conns, sort_col="idle", reverse=False, now=now, limit=0)
    idles = [now - c["last"] for c in out]
    check("idle ascending is actually ascending", idles == sorted(idles), f"({idles[:3]})")


def test_sort_by_derived_dur():
    conns = make_conns(10)
    conns[3]["last"] = conns[3]["first"] + 999.0      # one very long-lived flow
    out = filter_sort_connections(conns, sort_col="dur", reverse=True, limit=0)
    check("longest-lived flow sorts first by duration",
          out[0]["last"] - out[0]["first"] == 999.0)


# --- text filter + proc_map fallback ---------------------------------------- #
def test_filter_matches_across_columns():
    conns = make_conns(30)
    out = filter_sort_connections(conns, query="10.0.0.5", limit=0)
    check("query matches the remote ip column",
          all("10.0.0.5" in c["remote_ip"] for c in out) and out)


def test_connection_proc_falls_back_to_proc_map():
    row = {"local_port": 40001, "proc": ""}
    check("proc resolved from the port map when the row has none",
          connection_proc(row, {40001: "chrome.exe"}) == "chrome.exe")
    check("an explicit proc on the row wins",
          connection_proc({"local_port": 40001, "proc": "firefox.exe"},
                          {40001: "chrome.exe"}) == "firefox.exe")


# --- SearchIndex ------------------------------------------------------------- #
def test_search_index_builds_the_blob_once_per_stamp():
    calls = {"n": 0}

    def blob_of(item):
        calls["n"] += 1
        return item["text"]

    idx = SearchIndex(blob_of, key_of=lambda it: it["id"])
    item = {"id": 1, "text": "Chrome HTTPS 443", "proc": None}

    idx.blob(item, stamp=item["proc"])
    idx.blob(item, stamp=item["proc"])          # same stamp -> cache hit
    check("blob is built once while the stamp is unchanged", calls["n"] == 1,
          f"(built {calls['n']} times)")

    item["proc"] = "chrome.exe"                  # the process name arrived later
    idx.blob(item, stamp=item["proc"])          # stamp changed -> rebuild
    check("blob is rebuilt when the stamp changes", calls["n"] == 2,
          f"(built {calls['n']} times)")


def test_search_index_filter_is_case_insensitive_and_empty_query_returns_all():
    items = [{"id": i, "text": t} for i, t in enumerate(
        ["Chrome 443", "firefox 80", "curl 53"])]
    idx = SearchIndex(lambda it: it["text"], key_of=lambda it: it["id"])
    hits = idx.filter(items, "CHROME")
    check("filter is case-insensitive", [h["id"] for h in hits] == [0], f"({hits})")
    check("empty query returns every item", len(idx.filter(items, "")) == 3)


def test_search_index_filter_uses_the_stamp_when_given():
    items = [{"id": 1, "text": "port 443", "proc": None}]
    idx = SearchIndex(lambda it: f"{it['text']} {it['proc'] or ''}",
                      key_of=lambda it: it["id"])
    # First pass with no proc: the process name is not searchable yet.
    check("not found before the proc name is known",
          idx.filter(items, "chrome", stamp_of=lambda it: it["proc"]) == [])
    items[0]["proc"] = "chrome.exe"
    check("found once the stamp (proc) updates and the blob is rebuilt",
          len(idx.filter(items, "chrome", stamp_of=lambda it: it["proc"])) == 1)


def test_search_index_clears_when_it_exceeds_its_limit():
    idx = SearchIndex(lambda it: it["t"], key_of=lambda it: it["id"], limit=2)
    for i in range(2):
        idx.blob({"id": i, "t": f"row{i}"})
    check("cache filled to the limit", len(idx._cache) == 2, f"({len(idx._cache)})")
    idx.blob({"id": 99, "t": "overflow"})       # exceeding the limit clears first
    check("cache is bounded: it clears instead of growing past the limit",
          len(idx._cache) == 1, f"({len(idx._cache)})")


def test_search_index_clear_empties_the_cache():
    idx = SearchIndex(lambda it: it["t"], key_of=lambda it: it["id"])
    idx.blob({"id": 1, "t": "x"})
    idx.clear()
    check("clear() empties the cache", idx._cache == {})
