"""The "show only the targeted traffic" preference, and what it must NOT touch.

It narrows what you SEE. It never narrows what is captured, what is impaired, or
what the machine-readable outputs carry - the reproduction report and the NDJSON
always hold both totals, so a pipeline never has to guess which world a file came
from.

Two things in here are load-bearing omissions rather than gaps, and both have a
test because "we decided not to" is exactly the kind of intent that gets tidied
away by somebody making things consistent:

* ``drop_overflow`` / ``drop_shutdown`` / ``drop_send`` always cover the FULL
  captured traffic. They count packets THIS TOOL lost, including traffic the user
  never targeted, and narrowing them would hide the tool's own damage - the thing
  convention 20 exists for.
* the stats CSV does not follow the preference either. It is an APPEND log, and a
  file whose columns mean one thing in some rows and another in the rest is worse
  than useless for the spreadsheet it exists for. It carries both totals instead.
"""
import time

from beantester.engine import BeanEngine
from beantester.gui import prefs
from fakes import FakeDivert, FakePacket, check
from gui_harness import run_gui

PEER = "8.8.8.8"
OTHER = "1.1.1.1"


def _session_with_mixed_traffic():
    """A session where exactly one flow is in scope and one is not."""
    engine = BeanEngine()
    engine.set_dest(True, PEER, "")
    packets = [
        FakePacket(size=200, is_outbound=True, src_port=50001, dst_port=53,
                   dst_addr=PEER),
        FakePacket(size=300, is_outbound=False, src_port=53, dst_port=50001,
                   src_addr=PEER),
        FakePacket(size=100, is_outbound=True, src_port=50002, dst_port=80,
                   dst_addr=OTHER),
    ]
    engine.start("test", divert=FakeDivert(packets))
    deadline = time.time() + 5
    while time.time() < deadline and engine.stats_snapshot()["seen"] < len(packets):
        time.sleep(0.02)
    time.sleep(0.2)
    stats = engine.stats_snapshot()
    conns = engine.connections_snapshot(limit=None)
    engine.stop()
    return stats, conns


def test_the_engine_keeps_both_totals_so_a_view_can_choose():
    """Scoped delivered bytes exist next to the full ones - neither replaces the other.

    They are counted on the INJECT thread from the row's own sticky ``scoped``
    flag, without taking the stats lock: that thread is their only writer, which is
    the same argument already justified for ``sent``/``sent_in``/``sent_out``.
    """
    stats, _ = _session_with_mixed_traffic()
    check("everything was seen", stats["seen"] == 3, str(stats["seen"]))
    check("two packets were in scope", stats["scoped_seen"] == 2,
          str(stats["scoped_seen"]))
    check("full delivered bytes count all three",
          (stats["bytes_in"], stats["bytes_out"]) == (300, 300),
          "%s/%s" % (stats["bytes_in"], stats["bytes_out"]))
    check("scoped delivered bytes leave the untargeted flow out",
          (stats["bytes_in_scoped"], stats["bytes_out_scoped"]) == (300, 200),
          "%s/%s" % (stats["bytes_in_scoped"], stats["bytes_out_scoped"]))


def test_the_preference_exists_and_defaults_to_showing_everything():
    """Default OFF: the tool behaves exactly as it always has until asked otherwise."""
    pref = prefs.PREFS_BY_KEY.get("scope_view_to_target")
    check("the preference is registered", pref is not None)
    check("it is a checkbox", pref.kind == prefs.BOOL, pref.kind)
    check("and it defaults to showing everything", pref.default is False,
          repr(pref.default))
    check("it is rendered in the Settings window",
          any("scope_view_to_target" in keys for _, keys in prefs.PREF_GROUPS))


def test_the_scoped_twins_cover_exactly_the_three_counters_that_have_one():
    """The map is the whole contract, so pin it.

    Adding a twin for a tool-loss counter would silently start hiding the tool's
    own damage; adding one for an impairment counter would be a no-op that reads
    as meaningful (they are already scoped by construction).
    """
    run_gui("""
        twins = app.SCOPED_TWIN
        assert set(twins) == {"seen", "bytes_in", "bytes_out"}, twins
        for hidden in ("drop_overflow", "drop_shutdown", "drop_send"):
            assert hidden not in twins, hidden

        snap = {"seen": 100, "scoped_seen": 7,
                "bytes_in": 5000, "bytes_in_scoped": 500,
                "bytes_out": 4000, "bytes_out_scoped": 400,
                "drop_overflow": 9, "drop_shutdown": 3, "drop_send": 2}

        app.set_pref("scope_view_to_target", False)
        assert app.scoped_view() is False
        assert app.scoped_stat(snap, "seen") == 100
        assert app.scoped_stat(snap, "bytes_in") == 5000

        app.set_pref("scope_view_to_target", True)
        assert app.scoped_view() is True
        assert app.scoped_stat(snap, "seen") == 7
        assert app.scoped_stat(snap, "bytes_in") == 500
        assert app.scoped_stat(snap, "bytes_out") == 400
        # the three that must never narrow, whatever the preference says
        assert app.scoped_stat(snap, "drop_overflow") == 9
        assert app.scoped_stat(snap, "drop_shutdown") == 3
        assert app.scoped_stat(snap, "drop_send") == 2
    """)


def test_the_note_follows_the_view_instead_of_describing_the_other_one():
    """A note reading "ALL captured traffic" over narrowed numbers is the lie.

    The preference can be toggled while the page is already built, so the note is
    re-worded on the tick rather than only at build time.
    """
    run_gui("""
        app.set_pref("scope_view_to_target", False)
        app.select_page("statistics")
        page = app.pages["statistics"]
        page.refresh()
        wide = page._scope_note.kw.get("text")
        assert wide == bnt.T("stats.scope_note"), wide

        app.set_pref("scope_view_to_target", True)
        page.refresh()
        narrow = page._scope_note.kw.get("text")
        assert narrow == bnt.T("stats.scope_note_scoped"), narrow
        assert narrow != wide, "the note did not change with the preference"
    """)


def test_the_stats_csv_carries_both_totals_and_never_narrows():
    """It is an append log: rows written under different preferences must compare."""
    run_gui("""
        cols = app.CSV_COLUMNS
        assert "bytes_in_scoped" in cols and "bytes_out_scoped" in cols, cols
        assert cols["seen"] == "packets_seen", cols["seen"]
        assert cols["scoped_seen"] == "packets_in_scope", cols["scoped_seen"]
    """)
