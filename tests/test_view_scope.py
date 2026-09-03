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


def test_both_scope_switches_are_rendered_in_one_card():
    """The two switches must be READ TOGETHER, so they must be SEEN together.

    They differ by one verb - "Capture only the targeted traffic" against "Show
    only the targeted traffic" - and only the first changes what the tool takes
    in. Rendered in two separate panels a few rows apart, they read as two
    spellings of one setting. They come from different registries (an engine
    field with a CLI flag against a ui.json preference), so nothing but the card
    can hold them together, and nothing but a built window can prove it did.
    """
    run_gui("""
        panel = app.open_window("settings")

        # the field half: the checkbox ControlForm built for this section
        assert "narrow_filter" in panel.form.entries, sorted(panel.form.entries)
        card = panel.form.entries["narrow_filter"].master

        # the preference half: same card, not a preference group elsewhere
        assert "scope_view_to_target" in panel._pref_vars, sorted(panel._pref_vars)

        def descends_from(widget, ancestor):
            while widget is not None:
                if widget is ancestor:
                    return True
                widget = getattr(widget, "master", None)
            return False

        holder = panel._scope_status
        assert holder is not None, "the scope card has no status line"
        assert descends_from(holder, card) or descends_from(card, holder.master), \\
            "the verdict line is not in the same card as the capture switch"
    """)


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


def test_a_narrowed_capture_re_words_both_notes():
    """The bug, from the user's side: tick the box, start, read the two tabs.

    Both notes used to keep saying "ALL captured traffic" / "All captured
    connections ... targeting decides what gets impaired, not what gets listed"
    over figures the DRIVER had already cut down to the destination - while the
    checkbox's own tooltip promised the opposite, one window away.
    """
    run_gui("""
        app.set_pref("scope_view_to_target", False)
        for page_id in ("statistics", "connections"):
            app.select_page(page_id)
            app.pages[page_id].refresh()

        stats, conns = app.pages["statistics"], app.pages["connections"]
        assert stats._scope_note.kw.get("text") == bnt.T("stats.scope_note")
        assert conns._scope_note.kw.get("text") == bnt.T("conns.scope_note")

        app.engine._narrowed = True          # what a narrowed start writes
        stats.refresh(); conns.refresh()
        assert stats._scope_note.kw.get("text") == bnt.T("stats.scope_note_capture"), \\
            stats._scope_note.kw.get("text")
        assert conns._scope_note.kw.get("text") == bnt.T("conns.scope_note_capture"), \\
            conns._scope_note.kw.get("text")

        # ...and with a process target as well, the counters cover MORE than the
        # impairment does, which is a different sentence again.
        app.engine.set_target(True, {50001})
        stats.refresh(); conns.refresh()
        assert stats._scope_note.kw.get("text") == \\
            bnt.T("stats.scope_note_capture_process"), stats._scope_note.kw.get("text")
        assert conns._scope_note.kw.get("text") == \\
            bnt.T("conns.scope_note_capture_process"), conns._scope_note.kw.get("text")
    """)


def test_the_note_and_its_bubble_never_describe_different_states():
    """The tooltip is the longer version of the sentence it hangs under.

    It was bound once at build time and never touched again, so every re-wording
    left the bubble explaining the state the note had just stopped being in.
    """
    run_gui("""
        app.set_pref("scope_view_to_target", False)
        app.select_page("statistics")
        page = app.pages["statistics"]
        page.refresh()
        note = page._scope_note
        assert note._bnt_tooltip.text == bnt.T("tips.scope_note"), note._bnt_tooltip.text

        app.engine._narrowed = True
        page.refresh()
        assert note.kw.get("text") == bnt.T("stats.scope_note_capture")
        assert note._bnt_tooltip.text == bnt.T("tips.scope_note_capture"), \\
            note._bnt_tooltip.text

        app.set_pref("scope_view_to_target", True)
        page.refresh()
        assert note.kw.get("text") == bnt.T("stats.scope_note_scoped")
        assert note._bnt_tooltip.text == bnt.T("tips.scope_note_scoped"), \\
            note._bnt_tooltip.text
    """)


def test_the_chart_caption_names_the_traffic_it_is_drawing():
    """The chart is what gets screenshotted and sent on, so the picture has to
    carry its own scope - a tooltip nobody hovered cannot."""
    run_gui("""
        app.set_pref("scope_view_to_target", False)
        app.select_page("statistics")
        page = app.pages["statistics"]
        page.refresh()
        secs = "%.0f" % app.pref("chart_seconds")
        assert page._chart_frame.kw.get("text") == bnt.T("frames.throughput", s=secs)

        app.engine._narrowed = True
        page.refresh()
        assert page._chart_frame.kw.get("text") == \\
            bnt.T("frames.throughput_capture", s=secs), page._chart_frame.kw.get("text")
    """)


def test_the_session_panel_says_which_traffic_the_driver_handed_over():
    """Two sessions with the same `packets` figure can describe two different
    worlds. The CLI and the repro report always said which; the GUI said nothing
    anywhere, so a screenshot of this panel was unreadable on the point.

    It follows the session fact, not the coverage state: a VIEW preference cannot
    change what was captured, and showing it here would say it had.
    """
    run_gui("""
        app.set_pref("scope_view_to_target", False)
        app.select_page("statistics")
        page = app.pages["statistics"]
        page.select("session")
        row = lambda: page.sess_labels["capture"].kw.get("text")
        page.refresh()
        assert row() == bnt.T("session.capture_all"), row()

        # The discriminating case: the VIEW is narrowed while the CAPTURE is not.
        # Deriving this row from the coverage state instead of the session fact
        # passes every other assertion here and lies about exactly this one.
        app.set_pref("scope_view_to_target", True)
        page.refresh()
        assert row() == bnt.T("session.capture_all"), row()

        app.engine._narrowed = True
        page.refresh()
        assert row() == bnt.T("session.capture_narrowed"), row()

        app.set_pref("scope_view_to_target", False)    # ...and back: still narrowed
        page.refresh()
        assert row() == bnt.T("session.capture_narrowed"), row()
    """)


def test_an_incomplete_wording_table_is_refused_when_the_page_is_imported():
    """``keys_for_states`` is the mechanism that stops a state from having no
    words of its own, so it needs its own test rather than only complete callers.

    A table missing a state would fall back to whatever the lookup returned,
    which is how "ALL captured traffic" came to sit over narrowed figures in the
    first place - the state existed, the sentence did not.
    """
    complete = {s: f"key.{s}" for s in scope.STATES}
    check("a complete table passes through",
          scope.keys_for_states(complete) == complete)

    short = {s: f"key.{s}" for s in scope.STATES if s != scope.CAPTURE_PROCESS}
    try:
        scope.keys_for_states(short)
    except ValueError as exc:
        check("the refusal names the missing state", scope.CAPTURE_PROCESS in str(exc),
              str(exc))
    else:
        raise AssertionError("an incomplete wording table was accepted")

    stale = dict(complete, no_such_state="key.gone")
    try:
        scope.keys_for_states(stale)
    except ValueError as exc:
        check("and an obsolete entry is named too", "no_such_state" in str(exc), str(exc))
    else:
        raise AssertionError("a table with an unknown state was accepted")


def test_nothing_is_wedged_between_the_two_scope_checkboxes():
    """They are a pair, so nothing may sit in the gap between them.

    What did: ``narrow_filter`` is ``start_only``, and ControlForm reserves an
    EMPTY, permanently-mapped note line for such a section (so the panel does not
    jump when the field locks mid-session). The extra builder ran after it, so the
    blank line landed between the two checkboxes and pushed them visibly apart -
    which is how a pair reads as two unrelated settings. Content now comes before
    the commentary.
    """
    run_gui("""
        panel = app.open_window("settings")
        card = panel.form.sections["scope"].body
        kids = list(card.winfo_children())

        def index_of(predicate):
            for i, w in enumerate(kids):
                if predicate(w):
                    return i
                for sub in w.winfo_children():
                    if predicate(sub):
                        return i
            return -1

        capture = index_of(lambda w: w is panel.form.entries["narrow_filter"])
        view = index_of(lambda w: w.kw.get("text") == bnt.T("prefs.scope_view"))
        assert capture >= 0 and view >= 0, (capture, view, len(kids))
        assert view == capture + 1, (
            "something sits between the two scope checkboxes: "
            + repr([getattr(w, "kw", {}).get("text") for w in kids[capture:view + 1]]))

        # ...and the reserved note is still there, just below both of them
        note = panel.form.notes.get("scope")
        assert note is not None, "the start-only note went missing"
        assert kids.index(note) > view, (kids.index(note), view)
    """)


def test_the_settings_window_can_reach_every_group_at_any_height():
    """The Behaviour group used to render as a bare header with nothing under it.

    The footer is packed first on purpose, so the CONTENT is what runs out of
    room - which meant a card too many pushed the last group off the bottom edge,
    with no scrollbar and no sign that anything was missing. The window grows with
    every preference, in two languages, at every DPI, so its height can only be
    right by accident.
    """
    run_gui("""
        panel = app.open_window("settings")
        assert getattr(panel, "scroll", None) is not None, "the body does not scroll"

        # every group is built inside the scrolled body, not the raw window body
        def descends_from(widget, ancestor):
            while widget is not None:
                if widget is ancestor:
                    return True
                widget = getattr(widget, "master", None)
            return False

        for section in panel.form.sections.values():
            assert descends_from(section.body, panel.scroll.body), section

        def find_text(widget, text):
            if widget.kw.get("text") == text:
                return widget
            for sub in widget.winfo_children():
                found = find_text(sub, text)
                if found is not None:
                    return found
            return None

        # The LAST group is the one that fell off the bottom edge. Checked by its
        # ROWS rather than its header: a CollapsibleSection carries its title
        # itself, so there is no `text` widget to find for the group name.
        for key in ("prefs.confirm_close", "prefs.restore_profile", "prefs.reset_layout"):
            found = find_text(panel.body, bnt.T(key))
            assert found is not None, key
            assert descends_from(found, panel.scroll.body), f"{key} is outside the scroller"

        # ...but Close stays OUT of it. It is the way to shut the window, so it
        # must never be the thing that scrolled away.
        def find_close(widget):
            if widget.kw.get("text") == bnt.T("buttons.close"):
                return widget
            for sub in widget.winfo_children():
                found = find_close(sub)
                if found is not None:
                    return found
            return None

        close = find_close(panel.body)
        assert close is not None, "the Close button is gone"
        assert not descends_from(close, panel.scroll.body), "Close can scroll out of view"
    """)


def test_the_scope_card_answers_before_the_session_starts():
    """Ticking the box is a REQUEST, and the answer used to arrive only after a
    start - as a log line, in a window you may not be looking at.

    ``narrowed_filter`` is patched here rather than trusted: it asks the DRIVER's
    own parser, which is absent on the Linux half of the CI matrix, where the
    honest answer for every destination is "cannot prove it". Patching keeps the
    test about the LINE, not about whether pydivert happens to be installed.
    """
    run_gui("""
        from beantester.gui.panels import settings as settings_panel

        answer = [True]
        settings_panel.narrowed_filter = lambda base, ip, port: (base, answer[0])

        panel = app.open_window("settings")
        status = panel._scope_status

        # not asked for: the line says nothing and takes up no room
        app.vars["narrow_filter"].set(False)
        panel.refresh()
        assert status.kw.get("text") == "", status.kw.get("text")
        assert status.pack_info is None

        # asked for, and this destination can be pushed into the driver
        app.vars["narrow_filter"].set(True)
        app.vars["dst_ip"].set("8.8.8.8")
        panel.refresh()
        assert status.kw.get("text") == bnt.T("scope.narrow_works"), status.kw.get("text")
        assert status.pack_info is not None

        # asked for, and it cannot - the case that used to pass in silence
        answer[0] = False
        app.vars["dst_ip"].set("192.*")
        panel.refresh()
        assert status.kw.get("text") == bnt.T("scope.narrow_has_no_effect"), \\
            status.kw.get("text")
        assert status.kw.get("style") == "Bad.TLabel", status.kw.get("style")
    """)


def test_the_verdict_is_right_the_moment_the_window_opens():
    """Not one tick later. Somebody who ticks the box, opens Settings and reads a
    blank line has been told nothing - and 700 ms is long enough to look away.

    Deliberately never calls ``refresh()``: this asserts the BUILD path, which
    every other test in here skips straight past.
    """
    run_gui("""
        from beantester.gui.panels import settings as settings_panel
        settings_panel.narrowed_filter = lambda base, ip, port: (base, False)

        app.vars["narrow_filter"].set(True)
        app.vars["dst_ip"].set("192.*")
        panel = app.open_window("settings")

        assert panel._scope_status.kw.get("text") == bnt.T("scope.narrow_has_no_effect"), \\
            panel._scope_status.kw.get("text")
        assert panel._scope_status.pack_info is not None
    """)


def test_a_running_session_outranks_the_preview_in_the_scope_card():
    """Mid-session the handle's filter is already fixed, so the fields on screen
    can describe a session that does not exist. The line must report what this
    session DID, not what a restart would do - that is the whole reason the
    destination is start-only while narrowing is on."""
    run_gui("""
        from beantester.gui.panels import settings as settings_panel
        settings_panel.narrowed_filter = lambda base, ip, port: (base, True)

        panel = app.open_window("settings")
        app.vars["narrow_filter"].set(True)
        app.vars["dst_ip"].set("8.8.8.8")
        panel.refresh()
        assert panel._scope_status.kw.get("text") == bnt.T("scope.narrow_works")

        # the session narrowed nothing, whatever the preview would say now
        app.running = True
        app.engine._narrowed = False
        panel.refresh()
        assert panel._scope_status.kw.get("text") == bnt.T("scope.narrow_has_no_effect"), \\
            panel._scope_status.kw.get("text")
    """)


def test_the_window_says_whether_the_narrowing_actually_happened():
    """Both outcomes, because only one of them is easy to notice.

    The option silently does nothing when the destination cannot be expressed as
    a driver filter, and the fallback is the safe direction - so a run that did
    NOT narrow looks exactly like one that did. The CLI has said so since the
    option shipped; the window, the one place the checkbox is visible, said
    nothing either way.
    """
    run_gui("""
        def start_with(narrow, narrowed):
            # cleared in place, not rebound: `_log_lines` is a read-only property
            # over LogView's list (the log's state moved to gui/logview.py), and
            # assigning to it raises. The list itself is the live one.
            app._log_lines.clear()
            app.engine._narrowed = narrowed
            app._pending_start_settings = dict(app._settings_from_widgets(),
                                               narrow_filter=narrow)
            app._finish_start(None)
            app._logview.drain()        # was App._drain_log before gui/logview.py
            return "\\n".join(app._log_lines)

        # not asked for: the log must not gain a line about it either way
        quiet = start_with(False, False)
        assert bnt.T("log.narrow_applied") not in quiet
        assert bnt.T("log.narrow_no_effect") not in quiet

        got_it = start_with(True, True)
        assert bnt.T("log.narrow_applied") in got_it, got_it

        # asked for and did NOT get it - the case that used to pass in silence
        missed = start_with(True, False)
        assert bnt.T("log.narrow_no_effect") in missed, missed
        assert bnt.T("log.narrow_applied") not in missed
    """)


def test_every_wording_table_is_complete_and_every_key_has_text():
    """The tables are keyed by all four states (gui/scope.py refuses less), but a
    complete table of MISSPELLED keys renders the key itself on screen - which is
    what a missing translation looks like to a user."""
    run_gui("""
        from beantester.gui import scope
        from beantester.gui.pages import conns as conns_page, stats as stats_page

        tables = {
            "stats.SCOPE_NOTES": stats_page.SCOPE_NOTES,
            "stats.SCOPE_TIPS": stats_page.SCOPE_TIPS,
            "stats.THROUGHPUT_TITLES": stats_page.THROUGHPUT_TITLES,
            "conns.SCOPE_NOTES": conns_page.SCOPE_NOTES,
            "conns.SCOPE_TIPS": conns_page.SCOPE_TIPS,
        }
        for lang in LANGS:
            bnt.set_language(lang)
            for name, table in tables.items():
                assert set(table) == set(scope.STATES), (name, sorted(table))
                for state, key in table.items():
                    text = bnt.T(key)
                    assert text and text != key, (lang, name, state, key)
    """)


def test_the_stats_csv_carries_both_totals_and_never_narrows():
    """It is an append log: rows written under different preferences must compare."""
    run_gui("""
        from beantester.gui.csv_export import CSV_COLUMNS as cols
        assert "bytes_in_scoped" in cols and "bytes_out_scoped" in cols, cols
        assert cols["seen"] == "packets_seen", cols["seen"]
        assert cols["scoped_seen"] == "packets_in_scope", cols["scoped_seen"]
    """)


def test_the_stats_csv_records_which_world_each_row_was_measured_in():
    """An append log needs the capture scope ON THE ROW.

    The view preference picks between two columns that are both present, so a
    reader can undo it. Capture narrowing cannot be undone that way - it changes
    what `packets_seen` counted - so without this column two rows under one
    header could describe completely different traffic with no way to tell.
    """

    out = run_gui("""
        import csv, os, tempfile
        from beantester.gui import csv_export as csv_mod

        path = os.path.join(tempfile.mkdtemp(), "stats.csv")
        csv_mod.CSV_FILE = path

        app.engine._narrowed = False
        app.export_csv()
        app.engine._narrowed = True
        app.export_csv()

        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        print(repr(rows[0].index("capture_narrowed")))
        print(repr([r[rows[0].index("capture_narrowed")] for r in rows[1:]]))
        # one header, two rows: a changed column set would have rotated the file
        assert len(rows) == 3, rows
    """)
    index, values = [eval(line) for line in out.strip().splitlines()[-2:]]
    check("the scope column sits right after the timestamp", index == 1, str(index))
    check("and records each row's own world", values == ["no", "yes"], str(values))
