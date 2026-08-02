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
from beantester.views import (DERIVED, SearchIndex, avg_packet_bytes, connection_proc,
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


def _conn(port, ip, proc, bin_, bout, packets=1, proto="TCP",
          sent_in=None, sent_out=None):
    """One connection row.

    ``bytes_*`` are CAPTURED and ``sent_*`` are DELIVERED. They default to equal,
    i.e. an undisturbed flow - which is what every test that does not say
    otherwise means by "a connection with this much traffic".
    """
    sent_in = bin_ if sent_in is None else sent_in
    sent_out = bout if sent_out is None else sent_out
    return dict(local_port=port, remote_ip=ip, remote_port=443, proto=proto,
                packets=packets, bytes=bin_ + bout, bytes_in=bin_, bytes_out=bout,
                sent=sent_in + sent_out, sent_in=sent_in, sent_out=sent_out,
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
    check("sort by down seen: most-captured first", top("down_seen") == 1,
          f"({top('down_seen')})")
    check("sort by up seen: most-captured first", top("up_seen") == 2,
          f"({top('up_seen')})")
    check("sort by dropped: most-dropped first", top("dropped") == 1, f"({top('dropped')})")
    check("sort by pid: highest pid first", top("pid") == 2, f"({top('pid')})")


def test_delivered_and_captured_are_different_columns():
    """The whole point of the split: an impaired flow shows the two apart, and
    the delivered pair is the one the footer and the session panel agree with.

    Measured before the split: a row read bytes_in = 5 122 600 B under a heading
    the session panel used for delivered, while the application received 409 600 B.
    """
    hurt = _conn(1, "1.1.1.1", "chrome.exe", 5_122_600, 0, sent_in=409_600, sent_out=0)
    clean = _conn(2, "2.2.2.2", "svchost.exe", 1000, 500)

    down = {c["local_port"]: c for c in filter_sort_connections([hurt, clean])}
    check("split: captured is what the flow offered",
          down[1]["bytes_in"] == 5_122_600)
    check("split: delivered is what it got", down[1]["sent_in"] == 409_600)
    check("split: an undisturbed flow has them equal",
          down[2]["sent_in"] == down[2]["bytes_in"] == 1000)

    totals = traffic_totals([hurt, clean])
    check("split: the footer sums DELIVERED, like the columns above it",
          totals["down"] == 409_600 + 1000, f"({totals})")

    # the cells themselves, not just their order: sorting alone cannot tell the
    # two apart when one row happens to lead on both (it did not, and the mutant
    # that put captured back under "down" went unnoticed until this was added)
    check("split: the down column reads DELIVERED",
          DERIVED["down"](hurt, 0.0) == 409_600 / 1024.0,
          f"({DERIVED['down'](hurt, 0.0)})")
    check("split: the down seen column reads CAPTURED",
          DERIVED["down_seen"](hurt, 0.0) == 5_122_600 / 1024.0,
          f"({DERIVED['down_seen'](hurt, 0.0)})")

    # and they order the table independently: this pair leads on opposite columns
    starved = _conn(3, "3.3.3.3", "a", 9_000, 0, sent_in=10)      # huge offer, nothing through
    modest = _conn(4, "4.4.4.4", "b", 1_000, 0, sent_in=1_000)    # small offer, all through
    by_down = [c["local_port"] for c in
               filter_sort_connections([starved, modest], sort_col="down", reverse=True)]
    by_seen = [c["local_port"] for c in
               filter_sort_connections([starved, modest], sort_col="down_seen", reverse=True)]
    check("split: delivered ranks the flow that actually got its data first",
          by_down[0] == 4, f"({by_down})")
    check("split: captured ranks the flow that offered the most first",
          by_seen[0] == 3, f"({by_seen})")


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
        "bytes": i * 1000, "sent": i * 1000, "packets": i,
        "remote_ip": f"10.0.0.{i % 256}",
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
    check("kb sorts by delivered/1024, i.e. by the delivered total",
          [c["sent"] for c in out] == sorted((c["sent"] for c in conns), reverse=True))


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


# --- field-qualified search --------------------------------------------------- #
def _search_rows():
    return [
        {"proc": "chrome.exe", "pid": 100, "proto": "TCP", "dir": "out",
         "remote_ip": "8.8.8.8", "remote_port": 53, "local_port": 50001,
         "packets": 10, "dropped": 0, "scoped": True,
         "sent": 900, "sent_in": 500, "sent_out": 400},
        {"proc": "chrome.exe", "pid": 100, "proto": "UDP", "dir": "out",
         "remote_ip": "10.1.2.3", "remote_port": 443, "local_port": 50002,
         "packets": 99, "dropped": 5, "scoped": False,
         "sent": 10, "sent_in": 5, "sent_out": 5},
        {"proc": "msedge.exe", "pid": 900, "proto": "TCP", "dir": "in",
         "remote_ip": "192.168.0.9", "remote_port": 8080, "local_port": 50003,
         "packets": 1, "dropped": 0, "scoped": False,
         "sent": 1, "sent_in": 1, "sent_out": 0},
    ]


def _found(query):
    from beantester.views import _filter_connections
    return [f"{r['proc']}:{r['remote_port']}"
            for r in _filter_connections(_search_rows(), query, None)]


def test_plain_text_search_still_works_exactly_as_before():
    """The old behaviour is the default, so no existing habit breaks."""
    check("empty query returns everything", len(_found("")) == 3)
    check("a bare word still matches the blob", _found("chrome") ==
          ["chrome.exe:53", "chrome.exe:443"], f"({_found('chrome')})")
    check("a bare word that matches nothing returns nothing", _found("zzz") == [])


def test_a_term_can_name_its_column():
    """The point of the feature: 6 of 17 columns used to be searchable at all.

    A PID is on screen and could not be searched for, and neither could "only the
    rows this session impaired" - which is the question a tester has when the
    table holds a hundred thousand flows.
    """
    check("port", _found("port:443") == ["chrome.exe:443"])
    check("pid, which plain text cannot reach", _found("pid:>500") == ["msedge.exe:8080"])
    check("scoped, which plain text cannot reach", _found("scoped:yes") == ["chrome.exe:53"])
    check("dropped with a comparison", _found("dropped:>0") == ["chrome.exe:443"])
    check("a text column", _found("dir:in") == ["msedge.exe:8080"])


def test_the_values_use_the_expression_language_the_form_fields_use():
    """Comma lists, ranges, negation and CIDR - not a second syntax of our own."""
    check("a comma list", _found("port:53,8080") == ["chrome.exe:53", "msedge.exe:8080"])
    check("a range", _found("port:8000-8100") == ["msedge.exe:8080"])
    check("CIDR", _found("ip:10.0.0.0/8") == ["chrome.exe:443"])
    check("negation with a wildcard",
          _found("ip:!192.168.*") == ["chrome.exe:53", "chrome.exe:443"])
    check("a process term takes a PID too, exactly like the target field",
          _found("proc:100") == ["chrome.exe:53", "chrome.exe:443"])


def test_a_text_column_is_matched_case_insensitively():
    """`proto:tcp` must find rows holding "TCP".

    This failed in the first implementation, and silently: a process matcher
    judges (pid, name), so passing the value positionally handed it to `pid`,
    where a name cannot be evaluated - and an unevaluable term matches nothing.
    The search looked like it worked and found zero rows.
    """
    check("lowercase query, uppercase data",
          _found("proto:tcp") == ["chrome.exe:53", "msedge.exe:8080"])
    check("uppercase query, uppercase data",
          _found("proto:TCP") == ["chrome.exe:53", "msedge.exe:8080"])
    check("the field name itself is case-insensitive",
          _found("PROC:CHROME") == ["chrome.exe:53", "chrome.exe:443"])
    check("negation on a text column",
          _found("proto:!udp") == ["chrome.exe:53", "msedge.exe:8080"])


def test_several_terms_narrow_together():
    check("two columns", _found("proc:chrome port:443") == ["chrome.exe:443"])
    check("a column and plain text", _found("chrome port:53") == ["chrome.exe:53"])
    check("three terms", _found("scoped:no dropped:>0") == ["chrome.exe:443"])


def test_a_half_typed_query_finds_nothing_instead_of_throwing():
    """The box is typed into character by character.

    `port:44` on the way to `port:443` and half of `ip:10.0.` must not raise and
    must not blank the table with a traceback in the crash log. An unknown field
    is not an error either: `http://x` is a URL someone pasted, not a field.
    """
    check("an incomplete port matches nothing", _found("port:44") == [])
    check("an incomplete address matches nothing", _found("ip:10.0.") == [])
    check("an unparsable value matches nothing", _found("port:!!!") == [])
    check("an unknown field falls back to plain text", _found("nosuchfield:x") == [])
    check("a pasted URL does not explode", _found("http://8.8.8.8") == [])
    # A lone colon is plain text, so it matches every row whose blob contains one -
    # which is all of them, since the blob joins an address to its port. Keeping
    # everything visible is the right answer while someone is halfway through
    # typing `port:`: blanking the table on the way to a valid query reads as a
    # bug. Asserted as it BEHAVES rather than as first expected.
    check("a lone colon is plain text and keeps the table populated",
          len(_found(":")) == 3, f"({_found(':')})")


def test_the_query_is_compiled_once_not_per_row():
    """Parsing per row would put the expression parser on the path of every one of
    a hundred thousand rows on every keystroke."""
    from beantester.views import compile_query
    tests = compile_query("proc:chrome port:443 dropped:>0")
    check("one predicate per term", len(tests) == 3, f"({len(tests)})")
    check("an empty query compiles to nothing to do", compile_query("   ") == [])
