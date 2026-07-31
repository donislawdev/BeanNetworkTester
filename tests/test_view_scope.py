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
from beantester.gui import prefs, scope
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


# -- the coverage verdict (gui/scope.py) ----------------------------------- #
# What the numbers on screen cover depends on THREE facts, not one, and the
# notes used to read only the third. These pin the derivation itself, so a
# surface can be checked against the verdict instead of against a re-derivation.
def test_the_verdict_names_a_state_for_every_combination_of_the_three_facts():
    """All eight inputs, spelled out - no combination may fall through to "all".

    The dangerous fall-through is (capture narrowed, view wide): that is the
    state the notes got wrong, and the one a table missing an entry lands on.
    """
    cases = {
        # (capture_narrowed, view_scoped, process_target): state
        (False, False, False): scope.ALL,
        (False, False, True): scope.ALL,
        (True, False, False): scope.CAPTURE,
        (True, False, True): scope.CAPTURE_PROCESS,
        (False, True, False): scope.VIEW,
        (False, True, True): scope.VIEW,
        (True, True, False): scope.VIEW,
        (True, True, True): scope.VIEW,
    }
    for (narrowed, viewed, proc), expected in cases.items():
        got = scope.coverage(narrowed, viewed, proc)
        check(f"coverage{(narrowed, viewed, proc)}", got.state == expected,
              f"= {got.state}, expected {expected}")
        check("the raw facts travel with the verdict",
              (got.capture_narrowed, got.view_scoped, got.process_target)
              == (narrowed, viewed, proc), str(got))
    check("every state is reachable",
          set(cases.values()) == set(scope.STATES), str(scope.STATES))


def test_the_view_preference_outranks_a_narrowed_capture():
    """With the view scoped, the figures ARE the scoped twins - whatever was captured.

    Ordering these the other way round would put a sentence about the capture
    over numbers that had already been narrowed further, which is the same class
    of lie this module exists to remove.
    """
    verdict = scope.coverage(True, True, False)
    check("the view wins", verdict.state == scope.VIEW, verdict.state)
    check("but the capture fact is still readable for the surfaces that need it",
          verdict.capture_narrowed is True, str(verdict))


def test_a_missing_fact_cannot_invent_a_fifth_state():
    """The callers read a preference store, an engine flag and a core flag; before
    the first session one of them can answer None, and that must be "no"."""
    verdict = scope.coverage(None, None, None)
    check("None reads as off", verdict.state == scope.ALL, verdict.state)
    check("and is stored as a real bool",
          verdict.capture_narrowed is False and verdict.view_scoped is False,
          str(verdict))


def test_the_narrowing_fact_has_one_source_and_two_readers_that_agree():
    """``capture_narrowed()`` and ``session_info()["narrowed"]`` are one fact.

    They are read by different worlds - the GUI's per-tick surfaces and the
    reproduction report / NDJSON summary - so a session that narrowed must not be
    able to look narrowed in a saved report and wide on screen.
    """
    engine = BeanEngine()
    engine.start("test", divert=FakeDivert([]))
    try:
        check("a session with an injected divert is not narrowed",
              engine.capture_narrowed() is False, str(engine.capture_narrowed()))
        check("and both readers say so",
              engine.session_info()["narrowed"] == engine.capture_narrowed())
        # The one line a REAL narrowed start would have written (engine.py:
        # _start_locked). It cannot happen on an injected divert by design -
        # see test_narrow_filter.py::test_an_injected_divert_is_never_narrowed.
        engine._narrowed = True
        check("both readers follow the fact",
              engine.capture_narrowed() is True
              and engine.session_info()["narrowed"] is True)
    finally:
        engine.stop()
    check("STOP does not clear it: the counters it describes are still on screen",
          engine.capture_narrowed() is True, str(engine.capture_narrowed()))
    engine.start("test", divert=FakeDivert([]))
    try:
        check("but the next session starts from its own truth",
              engine.capture_narrowed() is False, str(engine.capture_narrowed()))
    finally:
        engine.stop()


def test_the_process_half_of_targeting_is_readable_on_its_own():
    """A narrowed capture can express the DESTINATION and never the process.

    So "capture narrowed" and "a process target is still filtering inside it" are
    two different questions, and the second needs its own reader - with a
    destination target set, ``process_target_active`` must stay False even though
    ``targeting_active`` is True.
    """
    engine = BeanEngine()
    check("nothing targeted", engine.process_target_active() is False)
    engine.set_dest(True, "8.8.8.8", "53")
    check("a destination target is not a process target",
          engine.process_target_active() is False)
    check("though targeting IS active", engine.targeting_active() is True)
    engine.set_target(True, {50001})
    check("a process target reads True", engine.process_target_active() is True)
    engine.set_target(False, set())
    check("and clears again", engine.process_target_active() is False)


def test_the_app_verdict_reads_the_engine_and_the_preference_together():
    """One decider on the App, so no surface re-derives this from its own inputs."""
    run_gui("""
        from beantester.gui import scope

        app.set_pref("scope_view_to_target", False)
        assert app.coverage().state == scope.ALL, app.coverage()

        app.engine._narrowed = True          # what a narrowed start writes
        assert app.coverage().state == scope.CAPTURE, app.coverage()

        app.engine.set_target(True, {50001})
        assert app.coverage().state == scope.CAPTURE_PROCESS, app.coverage()

        app.set_pref("scope_view_to_target", True)
        assert app.coverage().state == scope.VIEW, app.coverage()
    """)


def test_the_stats_csv_carries_both_totals_and_never_narrows():
    """It is an append log: rows written under different preferences must compare."""
    run_gui("""
        cols = app.CSV_COLUMNS
        assert "bytes_in_scoped" in cols and "bytes_out_scoped" in cols, cols
        assert cols["seen"] == "packets_seen", cols["seen"]
        assert cols["scoped_seen"] == "packets_in_scope", cols["scoped_seen"]
    """)
