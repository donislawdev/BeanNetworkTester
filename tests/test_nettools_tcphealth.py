"""``beantester/nettools/tcphealth.py``: the watched connections and what they say.

Readings are made up here (``tcpestats.Reading``/``Sample``) - what Windows answers
is ``test_tcpestats.py``'s; this file is about what the list does with the answers
over time: differences from the first reading, counters that wrap, a connection
that ended or whose port was taken again, and the one socket table read a cycle
makes for the Connections rows.
"""
from beantester import portmap, tcpestats
from beantester.nettools import tcphealth
from beantester.nettools.tcphealth import Request, Watch, Watchlist
from beantester.portmap import SocketRow
from beantester.tcprow import Connection, Target
from fakes import check

C = Connection("192.0.2.10", 51000, "198.51.100.7", 443)


def sample(srtt=200, rtt=210, resent=0, timeouts=0, out=1000, received=5000, count=True,
           measured=0, low=20, dupacks=0):
    """``resent``: bytes sent again (Windows never fills the segment count)."""
    return tcpestats.Sample(srtt if count else None, rtt if count else None, low if count
                            else None, 400 if count else None, 30, 300, resent, timeouts, 0,
                            dupacks, 1460, out, received, measured)


def ok(**kw):
    return tcpestats.Reading(tcpestats.OK, sample(**kw))


def test_counters_are_differences_from_the_first_reading_and_wrap_at_32_bits():
    """Learn: counting is never turned off, so a counter may hold what happened
    before this program watched - the list says what happened since."""
    watch = Watch(C, "app.exe", 7, 0.0)
    watch.take(ok(resent=2 ** 32 - 3), 10.0)
    watch.take(ok(resent=2), 11.0)
    check("resent since watching, across the wrap", watch.since_watching("resent_bytes")
          == 5, f"({watch.since_watching('resent_bytes')})")
    check("and since the previous reading", watch.since_previous("resent_bytes") == 5)
    check("watched since the first reading with numbers", watch.since == 10.0)


def test_an_ended_connection_keeps_its_last_numbers_and_is_read_no_more():
    watch = Watch(C, "app.exe", 7, 0.0)
    watch.take(ok(resent=3), 1.0)
    watch.take(tcpestats.Reading(tcpestats.ENDED, code=1168), 2.0)
    check("ended", watch.state == tcpestats.ENDED and not watch.reading)
    check("the last numbers stay", watch.last.resent_bytes == 3)
    watch.take(ok(resent=9), 3.0)
    check("a later answer changes nothing", watch.last.resent_bytes == 3
          and watch.state == tcpestats.ENDED)


def test_a_port_taken_by_a_new_connection_stops_the_watch_instead_of_mixing_numbers():
    """The same four numbers can name a new connection: its byte counters start
    again (lower), or counting is off on it. Either way the numbers after that are
    not this connection's."""
    watch = Watch(C, "app.exe", 7, 0.0)
    watch.take(ok(out=50000), 1.0)
    watch.take(ok(out=120), 2.0)
    check("bytes went back: stopped", watch.state == tcphealth.STOPPED and not watch.reading)
    check("the numbers before it stay", watch.last.bytes_out == 50000)
    other = Watch(C, "app.exe", 7, 0.0)
    other.take(ok(), 1.0)
    other.take(tcpestats.Reading(tcpestats.NOT_COUNTING), 2.0)
    check("counting gone after it worked: stopped", other.state == tcphealth.STOPPED)
    first = Watch(C, "app.exe", 7, 0.0)
    first.take(tcpestats.Reading(tcpestats.NOT_COUNTING), 1.0)
    check("not counting at the first reading is said as it is, and read again",
          first.state == tcpestats.NOT_COUNTING and first.reading)


def test_the_chart_keeps_a_minute_of_measured_round_trips_and_says_its_span():
    watch = Watch(C, "app.exe", 7, 0.0)
    watch.take(ok(count=False), 0.0)
    check("nothing measured yet: nothing to draw", tcphealth.chart(watch, 1.0) == ([], [], 0))
    for second in range(1, 70):
        watch.take(ok(srtt=second, rtt=second + 1), float(second))
    smoothed, raw, span = tcphealth.chart(watch, 70.0)
    check("sixty points, the newest last", len(smoothed) == 60 and smoothed[-1] == 69
          and raw[-1] == 70, f"({len(smoothed)}, {smoothed[-1]})")
    check("the span is the time the points cover, not their count", span == 60, f"({span})")
    check("no watch: nothing", tcphealth.chart(None, 1.0) == ([], [], 0))


def test_the_list_takes_a_connection_once_and_at_most_twenty():
    watchlist = Watchlist()
    check("asked", watchlist.ask(Request("a", 1, connection=C)) == tcphealth.WATCHING)
    result = tcphealth.Result(((watchlist.pending[0], C, tcphealth.WATCHING, ok()),), {})
    watchlist.pending.clear()
    watchlist.apply(result, 1.0)
    check("on the list", list(watchlist.watches) == [tcphealth.key_of(C)])
    check("asked again: it already is, nothing queued",
          watchlist.ask(Request("a", 1, connection=C)) == tcphealth.WATCHING
          and watchlist.pending == [])
    for port in range(1, tcphealth.MAX_WATCHED):
        watchlist.ask(Request("b", 2, connection=C._replace(local_port=port)))
    check("the twenty-first is refused",
          watchlist.ask(Request("c", 3, connection=C._replace(local_port=99))) == tcphealth.FULL)


def test_a_reading_for_a_connection_taken_off_the_list_meanwhile_is_dropped():
    watchlist = Watchlist()
    watchlist.apply(tcphealth.Result(((Request("a", 1, connection=C), C, tcphealth.WATCHING,
                                       ok()),), {}), 1.0)
    key = tcphealth.key_of(C)
    watchlist.remove(key)
    watchlist.apply(tcphealth.Result((), {key: ok(resent=4)}), 2.0)
    check("not back on the list", key not in watchlist.watches)


def test_a_cycle_reads_the_socket_table_once_and_only_for_connections_rows():
    calls = []

    def rows():
        calls.append(1)
        return ([SocketRow("TCP", 4, "192.0.2.10", 51000, "198.51.100.7", 443, "ESTABLISHED",
                           7)], [])
    watched = []
    result = tcphealth.cycle(
        [Request("x", 1, target=Target(51000, "198.51.100.7", 443)),
         Request("y", 2, target=Target(51001, "198.51.100.7", 443)),
         Request("z", 3, connection=C._replace(local_port=60000))],
        [(C, None)], watch=lambda c: watched.append(c) or ok(),
        read=lambda c, handle=None: ok(resent=1), rows=rows)
    check("one socket table read for two Connections rows", calls == [1], f"({calls})")
    kinds = [(r.process, kind) for r, _c, kind, _reading in result.added]
    check("found, gone, and a known connection that needed no lookup",
          kinds == [("x", tcphealth.WATCHING), ("y", tcphealth.GONE),
                    ("z", tcphealth.WATCHING)], f"({kinds})")
    check("the found one with the table's local address",
          result.added[0][1] == C and watched == [C, C._replace(local_port=60000)])
    check("and what was on the list is read", list(result.readings) == [tcphealth.key_of(C)])
    none = tcphealth.cycle([Request("z", 3, connection=C)], [], watch=lambda c: ok(),
                           read=lambda c, handle=None: ok(), rows=lambda: calls.append(2))
    check("no Connections row: no table read", calls == [1] and len(none.added) == 1)


def test_a_socket_table_that_does_not_answer_is_said_and_not_taken_for_closed(monkeypatch):
    noted = []
    monkeypatch.setattr(tcphealth.crashlog, "note", lambda exc, area: noted.append(area))

    def unavailable():
        raise portmap.SocketTableUnavailable("denied")
    target = Request("x", 1, target=Target(51000, "198.51.100.7", 443))
    for rows in (unavailable, lambda: ([], ["tcp/v6"]), lambda: (_ for _ in ()).throw(
            RuntimeError("a fault in the table read on purpose"))):
        result = tcphealth.cycle([target], [(C, None)], watch=lambda c: ok(),
                                 read=lambda c, handle=None: ok(), rows=rows)
        check(f"{rows}: unreadable", result.added[0][2] == tcphealth.UNREADABLE,
              f"({result.added})")
        check("and what was watched is still read", list(result.readings) ==
              [tcphealth.key_of(C)])
    check("the fault, and only it, is noted", noted == ["nettools.tcphealth"], f"({noted})")


def test_only_a_tcp_row_with_a_far_end_and_a_connection_behind_it_is_offered():
    cases = {("TCP", "198.51.100.7", "ESTABLISHED"): True, ("TCP", "2001:db8::7", ""): True,
             ("TCP", "fe80::7%12", "CLOSE_WAIT"): True, ("UDP", "198.51.100.7", ""): False,
             ("TCP", "", "LISTEN"): False, ("TCP", "0.0.0.0", "LISTEN"): False,
             ("TCP", "198.51.100.7", "TIME_WAIT"): False, ("TCP", "::", ""): False,
             ("TCP", None, ""): False, ("ICMP", "198.51.100.7", ""): False}
    for (proto, ip, state), wanted in cases.items():
        check(f"{proto} {ip!r} {state}", tcphealth.watchable(proto, ip, state) is wanted)


def test_the_details_and_the_report_say_the_numbers_since_watching():
    watch = Watch(Connection("2001:db8::20", 52188, "2001:db8::7", 443), "app.exe", 7, 0.0)
    watch.take(ok(resent=1460, timeouts=1, out=1000, received=5000, dupacks=4), 1.0)
    watch.take(ok(resent=4380, timeouts=1, out=3000, received=9000, dupacks=7), 2.0)
    rows = {d.key: d for d in tcphealth.details(watch)}
    check("the remote address offered to the Control page, without brackets",
          rows["remote"].value == "[2001:db8::7]:443" and rows["remote"].address == "2001:db8::7")
    check("resent in BYTES since watching, and the growth since the last read in brackets",
          rows["resent_bytes"].value == "2920 B (+2920)", f"({rows['resent_bytes']})")
    check("no row for the segment count Windows never fills",
          "resent" not in rows and "resent_segments" not in rows, f"({list(rows)})")
    check("nor Linux's lowest-alone row: Windows has the range",
          "lowest" not in rows and "range" in rows)
    check("a counter that did not grow: no brackets", rows["timeouts"].value == "0"
          and rows["dupacks"].value == "3 (+3)", f"({rows['timeouts']}, {rows['dupacks']})")
    check("bytes sent and received since watching", rows["data"].value == "2000 / 4000 B")
    check("the Note column says nothing but the marker (every other note was cut)",
          all(d.note == () for d in rows.values()), [d for d in rows.values() if d.note])
    lines = tcphealth.report_lines(Watchlist())
    check("an empty report still says what and when", lines[0].startswith(
        "TCP health: 0 connections, read "), f"({lines})")
    watchlist = Watchlist()
    watchlist.watches[watch.key] = watch
    text = tcphealth.report(watchlist)
    check("the report: the endpoints, the state, the round trips and the counters",
          "app.exe [2001:db8::20]:52188 -> [2001:db8::7]:443: ok" in text
          and "smoothed 200 ms" in text and "resent 2920 B, timeouts 0" in text
          and "segments" not in text
          and "sent 2000 B, received 4000 B" in text, "\n" + text)


def test_a_round_trip_windows_stopped_measuring_while_data_went_out_is_said_to_be_old():
    """MEASURED 2026-10-19: an open connection whose round trip jumped by 200 ms or more
    was measured no more for a whole session (Windows resent each segment before its
    ACK could come), and the smoothed value only looked current. Measured on THIS
    computer's data, so a connection that only receives is not old."""
    watch = Watch(C, "app.exe", 7, 0.0)
    for second in range(6):
        watch.take(ok(out=1000 + 200 * second, measured=5), float(second))
        if second == tcphealth.STALE_S - 1:
            check("two quiet seconds are ordinary", watch.unmeasured_for() == 0)
    check("five seconds without a measurement while 1000 B went out",
          watch.unmeasured_for() == 5, f"({watch.unmeasured_for()})")
    rows = {d.key: d for d in tcphealth.details(watch)}
    check("said on the smoothed round trip, in the caution colour",
          rows["srtt"].note == (tcphealth.Words("tools.tcphealth.note.not_measured", 5),)
          and rows["srtt"].tag == "stale", f"({rows['srtt']})")
    check("and its row on the list in the same colour", tcphealth.tag_of(watch) == "stale")
    lines = tcphealth.report_lines(_one(watch))
    check("and in the report", any("none for 5 s while data went out" in line for line in lines),
          "\n" + "\n".join(lines))
    watch.take(ok(out=3000, measured=6), 6.0)
    check("a new measurement: current again", watch.unmeasured_for() == 0
          and {d.key: d for d in tcphealth.details(watch)}["srtt"].tag == ""
          and tcphealth.tag_of(watch) == "")
    quiet = Watch(C, "app.exe", 7, 0.0)
    for second in range(6):
        quiet.take(ok(out=1000, received=5000 + 500 * second, measured=5), float(second))
    check("only receiving: not old", quiet.unmeasured_for() == 0)
    ended = Watch(C, "app.exe", 7, 0.0)
    for second in range(6):
        ended.take(ok(out=1000 + 200 * second, measured=5), float(second))
    check("old while open", ended.unmeasured_for() == 5)
    ended.take(tcpestats.Reading(tcpestats.ENDED, code=1168), 6.0)
    check("ended: its last numbers are final, not old - no marker, no colour",
          ended.unmeasured_for() == 0 and tcphealth.tag_of(ended) == ""
          and {d.key: d for d in tcphealth.details(ended)}["srtt"].tag == "")


def _one(watch):
    watchlist = Watchlist()
    watchlist.watches[watch.key] = watch
    return watchlist


def test_the_list_sorts_round_trips_and_counts_as_numbers():
    slow, fast, new = (Watch(C._replace(local_port=p), "a", 1, 0.0) for p in (1, 2, 3))
    slow.take(ok(srtt=1000), 1.0)
    fast.take(ok(srtt=90), 1.0)
    order = sorted((slow, fast, new), key=lambda w: tcphealth.sort_key(w, 4))
    check("unmeasured first, then 90 before 1000",
          [w.connection.local_port for w in order] == [3, 2, 1])
    slow.take(ok(srtt=1000, resent=9000), 2.0)
    fast.take(ok(srtt=90, resent=10000), 2.0)
    order = sorted((slow, fast, new), key=lambda w: tcphealth.sort_key(w, 5))
    check("resent bytes as numbers: 9000 before 10000",
          [w.connection.local_port for w in order] == [3, 1, 2])


def test_a_round_trip_under_a_millisecond_is_said_so_not_as_none():
    """Windows counts whole milliseconds: its 0 is 0.4 ms to a WSL peer (measured
    2026-10-19), and "0 ms" read as no round trip at all."""
    watch = Watch(C, "app.exe", 7, 0.0)
    watch.take(ok(srtt=0, rtt=0, low=0, measured=3), 1.0)
    rows = {d.key: d for d in tcphealth.details(watch)}
    check("the list", tcphealth.cells(watch)[4] == "< 1 ms", f"({tcphealth.cells(watch)})")
    check("the details", rows["srtt"].value == "< 1 ms" and rows["sample"].value == "< 1 ms"
          and rows["range"].value == "< 1 / 400 ms", f"({rows['range']})")
    check("the report", "smoothed < 1 ms" in tcphealth.report(_one(watch)))
    check("the chart's readout number", tcphealth.rtt_number(0) == "< 1"
          and tcphealth.rtt_number(214) == "214")
    check("not measured stays not measured", tcphealth.ms(None) == tcphealth.Words(
        "tools.tcphealth.value.no_rtt"))


# -- Linux: what its kernel keeps (tcpestats._linux_sample) ----------------------------- #
def linux(**kernel):
    """A Linux reading from ``tcp_info``'s fields, in the kernel's units (microseconds).
    A field given as None is one an older kernel's shorter struct does not have."""
    info = {"rto": 201000, "snd_mss": 1448, "rtt": 210500, "rttvar": 3200, "total_retrans": 0,
            "bytes_received": 5000, "min_rtt": 180250, "bytes_sent": 1000, "bytes_retrans": 0,
            "total_rto": 0, **kernel}
    return tcpestats.Reading(tcpestats.OK, tcpestats._linux_sample(
        {name: value for name, value in info.items() if value is not None}), handle="id")


def test_a_linux_reading_says_only_what_its_kernel_keeps():
    """No newest single round trip, no highest one, no fast resends or duplicate ACKs, no
    count of measurements - so none of those is said, not even as "not measured yet". It
    does count the segments sent again, which Windows never fills."""
    watch = Watch(C, "app", 7, 0.0)
    watch.take(linux(total_retrans=3, bytes_retrans=4344), 1.0)
    for second in range(2, 9):
        watch.take(linux(total_retrans=5, bytes_retrans=7240, bytes_sent=1000 + 500 * second),
                   float(second))
    rows = {d.key: d for d in tcphealth.details(watch)}
    check("what Linux keeps, in its order",
          list(rows) == ["process", "local", "remote", "state", "srtt", "lowest", "rttvar", "rto",
                         "resent_bytes", "resent_segments", "timeouts", "mss", "data", "since"],
          f"({list(rows)})")
    check("whole milliseconds, rounded down", rows["srtt"].value == "210 ms"
          and rows["lowest"].value == "180 ms" and rows["rttvar"].value == "3 ms"
          and rows["rto"].value == "201 ms", f"({rows['srtt']}, {rows['lowest']})")
    check("the segments sent again since watching, as a counter",
          rows["resent_segments"].value == "2" and rows["resent_bytes"].value == "2896 B",
          f"({rows['resent_segments']}, {rows['resent_bytes']})")
    check("never said to be unmeasured: Linux keeps no count of its measurements",
          watch.unmeasured_for() == 0 and tcphealth.tag_of(watch) == ""
          and rows["srtt"].note == ())
    text = tcphealth.report(_one(watch))
    check("the report says the same and no more",
          "smoothed 210 ms, lowest 180 ms, variation 3 ms, resend timer 201 ms, segment size "
          "1448 B" in text and "resent 2896 B (2 segments), timeouts 0, sent 4000 B, received 0 B"
          in text and not any(word in text for word in ("last", "highest", "measured",
                                                        "fast resends", "duplicate ACKs")),
          "\n" + text)
    smoothed, sample, _span = tcphealth.chart(watch, 9.0)
    check("the chart: the smoothed line alone", len(smoothed) == 8 and sample == [],
          f"({smoothed}, {sample})")


def test_linux_counters_wrap_at_their_own_widths():
    """The kernel's timeout count is 16 bits, its resent bytes 64: a difference taken at
    Windows' 32 would be a huge jump in one and a wrap that never was in the other."""
    watch = Watch(C, "app", 7, 0.0)
    watch.take(linux(total_rto=65534, bytes_retrans=1), 1.0)
    watch.take(linux(total_rto=2, bytes_retrans=2 ** 32 + 5), 2.0)
    check("timeouts across the 16-bit wrap", watch.since_watching("timeouts") == 4
          and watch.since_previous("timeouts") == 4, f"({watch.since_watching('timeouts')})")
    check("resent bytes past 4 GiB", watch.since_watching("resent_bytes") == 2 ** 32 + 4,
          f"({watch.since_watching('resent_bytes')})")


def test_an_older_kernel_without_a_field_has_no_row_for_it():
    """Fields are added at the end of ``tcp_info``: Linux before 6.7 has no timeout count
    (Ubuntu 22.04). The row goes, never a 0 that was not counted."""
    watch = Watch(C, "app", 7, 0.0)
    watch.take(linux(total_rto=None), 1.0)
    rows = {d.key: d for d in tcphealth.details(watch)}
    check("no timeouts row", "timeouts" not in rows and "resent_segments" in rows, f"({list(rows)})")
    check("nor in the report", "timeouts" not in tcphealth.report(_one(watch)))


def test_a_round_trip_linux_has_not_measured_yet_is_said_so():
    """A round trip of 0 us is none yet (a connection still opening, measured 2026-10-27);
    its variation is then the kernel's starting value, not a measurement."""
    watch = Watch(C, "app", 7, 0.0)
    watch.take(linux(rtt=0, rttvar=250000, min_rtt=0xFFFFFFFF), 1.0)
    rows = {d.key: d for d in tcphealth.details(watch)}
    none = tcphealth.Words("tools.tcphealth.value.no_rtt")
    check("not measured yet", rows["srtt"].value == none and rows["rttvar"].value == none
          and rows["lowest"].value == none, f"({rows['srtt']}, {rows['rttvar']})")
    under = Watch(C, "app", 7, 0.0)
    under.take(linux(rtt=999, min_rtt=14), 1.0)
    check("measured, 0.999 ms: rounded down, < 1 ms - under one, as it was",
          tcphealth.cells(under)[4] == "< 1 ms", f"({tcphealth.cells(under)})")


def test_a_connections_row_is_looked_up_in_the_systems_own_table(monkeypatch):
    """The system's table (``tcpestats.socket_rows``): on Linux the kernel's list, which
    writes a dual-stack socket's address as the row does, where psutil does not."""
    asked = []

    def system_rows():
        asked.append(1)
        return ([SocketRow("TCP", 4, "192.0.2.10", 51000, "198.51.100.7", 443, "ESTABLISHED",
                           7)], [])
    monkeypatch.setattr(tcpestats, "socket_rows", system_rows)
    result = tcphealth.cycle([Request("x", 1, target=Target(51000, "198.51.100.7", 443))], [],
                             watch=lambda c: ok())
    check("the system's table, read once", asked == [1]
          and result.added[0][2] == tcphealth.WATCHING, f"({asked}, {result.added})")


def test_the_handle_a_watch_gave_is_what_its_connection_is_read_by():
    """Linux reads a connection by the kernel's id of its socket, cookie in it - the one
    the watch found. A reading without one (Windows) keeps none."""
    watchlist = Watchlist()
    watchlist.apply(tcphealth.Result(((Request("a", 1, connection=C), C, tcphealth.WATCHING,
                                       linux()),), {}), 1.0)
    check("kept", watchlist.to_read() == [(C, "id")], f"({watchlist.to_read()})")
    watchlist.apply(tcphealth.Result((), {tcphealth.key_of(C): ok()}), 2.0)
    check("a reading without one does not lose it", watchlist.to_read() == [(C, "id")])
    asked = []
    result = tcphealth.cycle([], watchlist.to_read(), watch=lambda c: ok(),
                             read=lambda c, handle=None: asked.append((c, handle)) or ok())
    check("and the cycle reads by it", asked == [(C, "id")]
          and list(result.readings) == [tcphealth.key_of(C)], f"({asked})")


def test_no_note_about_rights_where_watching_needs_none(monkeypatch):
    monkeypatch.setattr(tcphealth.driver, "is_admin", lambda: False)
    monkeypatch.setattr(tcpestats, "needs_rights", lambda: True)
    check("Windows without rights: said", tcphealth.blocker() == "tools.tcphealth.needs_admin")
    monkeypatch.setattr(tcpestats, "needs_rights", lambda: False)
    check("Linux: nothing to say", tcphealth.blocker() == "")
    monkeypatch.setattr(tcpestats.sys, "platform", "linux")
    check("Linux needs none", tcpestats.needs_rights() is False)
