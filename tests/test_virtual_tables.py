"""The virtualised tables: the contract that keeps them usable at scale.

Why this file exists
--------------------
``ttk.Treeview`` has no virtualisation. The old ``SortableTree.sync()`` called
``item()`` **and** ``move()`` for every row on every refresh, and ``move()`` on a
large tree is worse than quadratic. Measured on real Tk 8.6:

    400 rows -> 3 ms, 10 000 -> 353 ms, 50 000 -> 49.6 SECONDS, 100 000 -> 3 min.

The table now keeps the model in Python and renders only the rows on screen, so
the widget cost is constant. These tests pin down the three properties that make
that true - and that a well-meaning "simplification" would quietly undo:

1. the widget only ever holds a viewport's worth of items, never the model;
2. a refresh renders ONLY the visible rows (a lazy model is not an optimisation
   detail: formatting 200 000 rows a second costs more than drawing them);
3. selection, the context menu and Ctrl+C work off MODEL KEYS, because the
   widget's item ids are recycled slots and mean nothing.
"""
import ast
import os

from beantester.gui.widgets.sortable_tree import (MAX_WIDTH_FACTOR, fitted_widths,
                                                  rows_shown_in_full)
from fakes import ROOT, check
from gui_harness import run_gui

# The fake Tk has no geometry, so Tk's answer to "how many rows fit" is injected
# the way a real table receives it: the first row's box and identify_region, read
# at <Configure>. Five slots short of the window is what a real table has - a
# partial row and the buffer. The row height leaves the division two rows too
# many, so the count has to be found by asking, as on real Tk.
INJECT_FITS = """
        slots = table.window()
        fits = slots - 5
        top = 25
        row_h = (table.tree.winfo_height() - top) // (fits + 2)
        bottom = top + fits * row_h + row_h // 2        # half a row cut off below
        table.tree.bbox = lambda item, column=None: (2, top, 600, row_h)
        table.tree.identify_region = (
            lambda x, y: "cell" if 2 <= x < 602 and top <= y < bottom else "nothing")
        table._on_configure()
        assert table._fits == fits, (table._fits, fits)

        def key(sequence):
            # The fake records bindings and never fires them, so they are run here.
            # Every one has to answer "break", or ttk's class binding runs after it.
            results = [handler(None) for handler in table.tree.bindings[sequence]]
            assert "break" in results, (sequence, results)
"""


# -- hiding columns must not leave the table half empty ---------------------- #

# The Connections table's real natural widths, read off it on 2026-08-17 - so
# these tests exercise the shape the user actually meets, not a tidy invention.
NATURAL = {"proc": 134, "pid": 71, "down_seen": 118, "up_seen": 113,
           "remote_ip": 148, "proto": 83}
TREE = 1076


def test_hiding_columns_fills_the_table_instead_of_leaving_dead_space():
    """The reported fault, as arithmetic.

    MEASURED before the fix: with 2 of 17 columns shown the visible widths summed
    to 205 px in a 1076 px tree - **871 px of bare background**. The table refuses
    ``stretch`` on purpose (ttk recomputes a stretch column and a dragged width
    snaps back), so nothing was absorbing the slack.

    The four-column case is the one from the report, and it fills exactly.
    """
    visible = {"proc", "pid", "down_seen", "up_seen"}
    current = {c: NATURAL[c] for c in visible}
    out = fitted_widths(NATURAL, visible, NATURAL, current, TREE)
    total = sum(out.get(c, current[c]) for c in visible)
    check("four columns fill the tree exactly", total == TREE, f"({total} != {TREE})")
    check("every visible column grew", all(out[c] > current[c] for c in visible),
          f"({out})")
    check("a hidden column is never touched", "remote_ip" not in out, f"({out})")


def test_a_fit_never_takes_a_column_past_the_width_a_drag_could_reach():
    """The cap is ``MAX_WIDTH_FACTOR`` x natural - the same ceiling ``clamp_widths``
    applies after a drag, so a fit cannot produce a width the user could not have
    dragged to by hand.

    With one narrow column against a wide tree the cap BINDS, and the leftover is
    deliberately left as dead space rather than breaking it: measured 402 px of
    column and 674 px of remainder for a single ``proc``. Bounded and honest beats
    a column stretched past anything reachable.
    """
    out = fitted_widths(NATURAL, {"proc"}, NATURAL, {"proc": 134}, TREE)
    cap = int(NATURAL["proc"] * MAX_WIDTH_FACTOR)
    check("the single column stops at its cap", out == {"proc": cap}, f"({out}, cap={cap})")
    check("and the cap really is short of the tree", cap < TREE, f"({cap})")


def test_a_fit_only_ever_widens():
    """Shrinking would take away a width the user dragged to, which is the whole
    property that refusing ``stretch`` was protecting. A column already wider than
    the tree's share keeps every pixel."""
    visible = {"proc", "pid"}
    current = {"proc": 900, "pid": 71}          # proc dragged out by hand
    out = fitted_widths(NATURAL, visible, NATURAL, current, TREE)
    check("the dragged column is not reduced", out.get("proc", 900) >= 900, f"({out})")
    for col, width in out.items():
        check(f"{col} did not shrink", width >= current[col], f"({width} < {current[col]})")


def test_a_full_or_overflowing_table_is_left_alone():
    """No slack, nothing to do - and this is the state the table is in whenever
    every column is shown, where the horizontal scrollbar is the right answer."""
    visible = set(NATURAL)
    current = dict(NATURAL)
    check("a table wider than its tree is untouched",
          fitted_widths(NATURAL, visible, NATURAL, current, 200) == {},
          "(a fit must never fire when the scrollbar has work)")
    exact = {"proc": TREE}
    check("an exact fit is untouched",
          fitted_widths(NATURAL, {"proc"}, NATURAL, exact, TREE) == {})


def test_a_table_that_has_not_been_laid_out_yet_is_not_fitted():
    """Before the first layout the widget reports width 0 or 1. Fitting against
    that would write nonsense widths that the real ``<Configure>`` then has to
    undo."""
    for width in (0, 1, None):
        check(f"width {width!r} fits nothing",
              fitted_widths(NATURAL, {"proc", "pid"}, NATURAL,
                            {"proc": 134, "pid": 71}, width) == {})
    check("no visible columns fits nothing",
          fitted_widths(NATURAL, set(), NATURAL, {}, TREE) == {})


def test_the_slack_goes_to_the_columns_that_were_born_wide():
    """Proportional to NATURAL width, so the column that was born wide stays the
    wide one. Sharing it equally would make a PID column as wide as a path."""
    visible = {"proc", "pid"}
    out = fitted_widths(NATURAL, visible, NATURAL, {"proc": 134, "pid": 71}, 500)
    check("both grew", set(out) == visible, f"({out})")
    check("the naturally wider column stays wider", out["proc"] > out["pid"], f"({out})")
    check("the slack is fully used", sum(out.values()) == 500, f"({sum(out.values())})")


def test_a_width_the_user_dragged_survives_a_fit_but_hiding_a_column_re_fits():
    """The memo, which is the rule that keeps the fit from fighting the user.

    A fit is asked for on two occasions only - the visible set changed, or the
    widget was resized. Dragging a column narrower changes neither, so the width
    the user chose stands. Without that, every fit would undo every drag.
    """
    run_gui("""
        table = app.pages["connections"].table
        table.set_visible_columns(["proc", "pid", "down_seen", "up_seen"])
        natural = table._natural["proc"]

        # the user drags "proc" narrower than anything a fit would pick
        table.tree.column("proc", width=90)
        table.fit_columns()
        assert int(table.tree.column("proc", "width")) == 90, (
            "a fit must not undo a width the user chose",
            table.tree.column("proc", "width"))

        # ...but hiding a column is a new question, and it gets a new answer
        table.set_visible_columns(["proc", "pid"])
        after = int(table.tree.column("proc", "width"))
        assert after > 90, ("hiding a column must re-fit the rest", after)
        assert after <= natural * 3, ("and still respect the cap", after, natural)
    """)


def test_the_widget_never_holds_more_than_a_viewport():
    """100 000 model rows must not become 100 000 Tcl items."""
    run_gui("""
        page = app.pages["connections"]
        table = page.table
        rows = [(f"k{i}", (f"p{i}.exe", "TCP", "1.2.3.4", "443",
                           str(i), "1", "0.1", "0.2", "0.3"))
                for i in range(100_000)]
        table.sync(rows)

        assert len(table.items) == 100_000, "the model must hold every row"
        widget_rows = len(table.tree.get_children())
        assert widget_rows == table.window(), (widget_rows, table.window())
        assert widget_rows < 200, f"the widget holds {widget_rows} items - not virtualised"
    """)


def test_a_refresh_renders_only_the_visible_rows():
    """The lazy model is the point: 200k rows must not be formatted per tick."""
    run_gui("""
        page = app.pages["connections"]
        table = page.table

        rendered = []
        def render(item):
            rendered.append(item[0])
            return item[1]

        items = [(f"k{i}", (f"p{i}", "TCP", "1.2.3.4", "443",
                            str(i), "1", "0.1", "0.2", "0.3"))
                 for i in range(50_000)]
        table.set_model(items, render=render, key_of=lambda it: it[0])

        assert len(rendered) <= table.window(), (
            f"{len(rendered)} rows rendered for a {table.window()}-row viewport")
        assert rendered[0] == "k0", rendered[:3]

        # scrolling renders the new window, and nothing else
        rendered.clear()
        table.set_offset(10_000)
        assert len(rendered) <= table.window()
        assert rendered[0] == "k10000", rendered[:3]
    """)


def _tk_layout(left=2, top=25, columns=408, width=408, height=136, below=2):
    """``rows_shown_in_full``'s arguments for a table, answered the way Tk answers.

    ``identify_region`` names a row only inside the row area: under the header,
    above the ``below`` pixels of border, over the columns and inside the side
    borders. The row height is 22. Returns the arguments and the questions asked.
    """
    asked = []

    def region_at(x, y):
        asked.append((x, y))
        over_rows = max(left, 2) <= x < min(left + columns, width - 2)
        return "cell" if over_rows and top <= y < height - below else "nothing"

    return ((left, top, columns, 22), width, height, region_at), asked


def test_the_rows_in_full_are_asked_of_tks_own_layout():
    """The border under the rows is FOUND by asking Tk, never assumed.

    ``height // rowheight`` counted the header and the border as rows (external
    review, P1-4). ``yview`` then held on Tk 9 only: Tk 8.6 counts the row cut off
    at the bottom as shown, and the render check caught the count one too high on
    the Linux runner. A bottom border taken to be as wide as the side one counts
    rows that are not there once a table is scrolled sideways, because the first
    row's box then starts left of the widget. The stand-in answers like Tk, so each
    of those shortcuts fails one of the cases below.
    """
    cases = (
        ("a half row at the bottom is not counted", {}, 4),
        ("rows that fit exactly are all counted", {"height": 25 + 10 * 22 + 2}, 10),
        ("a border thicker than a row is found too",
         {"height": 25 + 5 * 22 + 30, "below": 30}, 5),
        ("a table scrolled sideways is asked where it is on screen",
         {"left": -406, "columns": 816}, 4),
        ("columns narrower than the widget are asked over a column",
         {"columns": 150}, 4),
        ("a widget shorter than a row still shows one", {"height": 30}, 1),
    )
    for name, layout, expected in cases:
        args, asked = _tk_layout(**layout)
        found = rows_shown_in_full(*args)
        check(name, found == expected, f"({found}, expected {expected}; asked {asked})")
    args, asked = _tk_layout()
    rows_shown_in_full(*args)
    check("a border thinner than a row takes two questions at most", len(asked) <= 2,
          f"({asked})")
    _, width, height, region_at = args
    for box in ("", None, (2, 25, 408, 0)):
        check(f"no row to measure ({box!r}): nothing to read",
              rows_shown_in_full(box, width, height, region_at) is None, "")


def test_a_resize_is_measured_on_the_new_layout_not_the_old_one():
    """A treeview is laid out when Tk is next idle, after <Configure> has run.

    On Tk 8.6.14, the Linux runner's, bbox and identify_region read the layout as
    it was - the OLD size - and a table grown from 4 rows to 10 went on counting 4.
    ``yview`` lays a pending layout out first, so the table calls it before it
    measures. The stand-in answers like 8.6.14: from the old layout until yview.
    """
    run_gui("""
        table = app.pages["connections"].table
        tree = table.tree
        top, row_h = 25, 20
        height = [top + 10 * row_h + 2]
        laid_out = [top + 4 * row_h + 2]                # the size before the resize

        def yview(*args):
            laid_out[0] = height[0]
            return (0.0, 1.0)

        tree.yview = yview
        tree.winfo_height = lambda: height[0]
        tree.bbox = lambda item, column=None: (2, top, 600, row_h)
        tree.identify_region = (
            lambda x, y: "cell" if top <= y < laid_out[0] - 2 else "nothing")
        table._on_configure()
        assert table._fits == 10, ("measured on the layout before the resize", table._fits)
    """)


def test_scrolling_moves_the_window_and_stays_in_range():
    """The bottom is measured in rows Tk shows IN FULL, not in slots.

    Until 2026-09-29 this test PINNED ``max_offset() == len - window()``. The window
    holds a partial row and a buffer below the rows on screen, so at the bottom the
    last rows sat in slots nobody could see: on real Tk the last five of every
    table, and a table of 20 rows could not scroll at all (external review, P1-4).
    """
    run_gui("""
        table = app.pages["connections"].table
        table.sync([(f"k{i}", (str(i), "", "", "", "", "", "", "", ""))
                    for i in range(1000)])
    """ + INJECT_FITS + """
        assert table.offset == 0
        table.scroll_by(50)
        assert table.offset == 50
        table.scroll_by(-500)
        assert table.offset == 0, "must not scroll above the first row"
        table.set_offset(10 ** 9)
        assert table.offset == table.max_offset(), "must not scroll past the last row"
        assert table.max_offset() == 1000 - fits, (table.max_offset(), fits)

        # the scrollbar: the thumb spans the rows in full and ends at the end
        spans = []
        table.vsb.set = lambda first, last: spans.append((first, last))
        table.repaint()
        assert spans[-1] == ((1000 - fits) / 1000, 1.0), spans[-1]
        table._on_scrollbar("moveto", "0.0")
        assert spans[-1] == (0.0, fits / 1000), spans[-1]
        table._on_scrollbar("scroll", "1", "pages")
        assert table.offset == fits, "a page is the rows shown in full"
        # The thumb at the end stands on (total - fits) / total, and for about one
        # model size in a hundred that float lands a hair under the last offset.
        # A size where it does is picked, so truncating would stop one row short.
        total = next(t for t in range(fits + 1, 5000)
                     if int(((t - fits) / t) * t) != t - fits)
        table.sync([(f"k{i}", (str(i), "", "", "", "", "", "", "", ""))
                    for i in range(total)])
        table._on_scrollbar("moveto", repr((total - fits) / total))
        assert table.offset == total - fits, ("the end of the thumb is the end",
                                              total, table.offset)

        # a model a few rows longer than the view scrolls exactly that far
        table.sync([(f"k{i}", (str(i), "", "", "", "", "", "", "", "")) for i in range(20)])
        table.set_offset(10 ** 9)
        assert table.offset == 20 - fits, (table.offset, fits)
        # a model that fits entirely in the viewport cannot scroll at all
        table.sync([("only", ("1", "", "", "", "", "", "", "", ""))])
        assert table.max_offset() == 0
        assert table.offset == 0
    """)


def test_selection_is_by_model_key_and_survives_sorting():
    """Item ids are recycled slots: a selection stored as an item id is a bug.

    Until 2026-09-29 the scroll step below was green only because the fake never
    fires <<TreeviewSelect>>. Real Tk answers every selection the table writes with
    a QUEUED one, and the table rebuilt its selection from it - from the rows on
    screen, which after the scroll were none (external review, P2-18). The echo is
    now delivered by hand, as Tk delivers it.
    """
    run_gui("""
        table = app.pages["connections"].table
        rows = [(f"k{i}", (f"p{i}", "TCP", "1.2.3.4", "443",
                           str(i), "1", "0.1", "0.2", "0.3"))
                for i in range(500)]
        table.sync(rows)

        table.select_keys(["k7"])
        assert table.selected_keys() == ["k7"]
        assert table.selection_values()[0] == "p7"

        # re-sorting reshuffles every row into a different slot; the SELECTION
        # follows the row, not the slot it happened to be sitting in
        table.sync(list(reversed(rows)))
        assert table.selected_keys() == ["k7"], "selection lost when the order changed"
        assert table.selection_values()[0] == "p7"

        # scrolling the selected row out of view does not deselect it - not even
        # once Tk's queued echo of that write arrives, naming no row at all
        table.set_offset(400)
        table._on_select()
        assert table.selected_keys() == ["k7"], table.selected_keys()
        assert table.copy_text(), "Ctrl+C still has the row to copy"

        # a row that leaves the model does leave the selection
        table.sync(rows[:5])
        assert table.selected_keys() == []
    """)


def test_the_keyboard_moves_a_cursor_through_the_model():
    """Up/Down, PageUp/PageDown and Home/End choose rows by MODEL position.

    ttk's own handlers chose a SLOT and ``see``-d it, which scrolled the widget's
    own view under the window: after 40 presses of Down, rows 0-4 could not be
    scrolled back to (external review, P2-18). Home and End did nothing at all.
    """
    run_gui("""
        table = app.pages["connections"].table
        table.sync([(f"k{i}", (str(i), "", "", "", "", "", "", "", ""))
                    for i in range(100)])
    """ + INJECT_FITS + """
        key("<Down>")                   # nothing chosen yet: the top row on screen
        assert table.selected_keys() == ["k0"], table.selected_keys()
        for _ in range(fits):
            key("<Down>")
        assert table.selected_keys() == [f"k{fits}"], table.selected_keys()
        assert table.offset == 1, ("one row past the bottom moves the window one", table.offset)
        key("<Next>")
        assert table.selected_keys() == [f"k{2 * fits}"], "a page is the rows in full"
        key("<End>")
        assert table.selected_keys() == ["k99"] and table.offset == 100 - fits
        key("<Home>")
        assert table.selected_keys() == ["k0"] and table.offset == 0
        key("<Up>")
        assert table.selected_keys() == ["k0"], "Up on the first row stays on it"
        key("<Left>")                   # swallowed: ttk's Right re-selects its slot
        key("<Right>")
        assert table.selected_keys() == ["k0"]
    """)


def test_shift_selects_a_range_across_pages_and_scrolling_keeps_it():
    """A range is built from model positions, so it can run past a page.

    Shift+click used to measure from ttk's focus item, which is a slot: after a
    scroll the range started at whatever row that slot held by then.
    """
    run_gui("""
        table = app.pages["connections"].table
        table.sync([(f"k{i}", (str(i), "", "", "", "", "", "", "", ""))
                    for i in range(100)])
    """ + INJECT_FITS + """
        key("<Home>")
        for _ in range(30):
            key("<Shift-Down>")
        assert table.selected_keys() == [f"k{i}" for i in range(31)], table.selected_keys()
        table.set_offset(60)            # the whole range leaves the window
        table._on_select()              # and Tk's queued echo of that write arrives
        assert len(table.selected_keys()) == 31, len(table.selected_keys())
        assert len(table.copy_text().splitlines()) == 31, "Ctrl+C copies all of it"
        key("<Shift-Up>")
        assert table.selected_keys() == [f"k{i}" for i in range(30)]
        assert table.offset <= 29 < table.offset + fits, "the cursor is brought back"
    """)


def test_a_click_chooses_by_model_row_and_brings_the_half_row_into_view():
    """The row half cut off at the bottom is the one ttk's press used to ``see``.

    That scrolled ttk's own view by a row (measured on Tk 9.0.4: yview 0 -> 0.045).
    Now the click is answered by model position and the WINDOW scrolls, so the row
    ends up in full; a heading or a separator is still ttk's, for sorting and
    resizing.
    """
    run_gui("""
        import types
        table = app.pages["connections"].table
        table.sync([(f"k{i}", (str(i), "", "", "", "", "", "", "", ""))
                    for i in range(100)])
    """ + INJECT_FITS + """
        table.tree.identify_region = lambda x, y: "cell"

        def click(slot, sequence="<Button-1>"):
            table.tree.row_at = table._slots[slot]
            event = types.SimpleNamespace(x=10, y=5)
            return [handler(event) for handler in table.tree.bindings[sequence]]

        assert "break" in click(fits), "ttk's own press must not run after it"
        assert table.selected_keys() == [f"k{fits}"], table.selected_keys()
        assert table.offset == 1, ("the half row is scrolled into full view", table.offset)
        click(0, "<Shift-Button-1>")    # slot 0 holds k1 now
        assert table.selected_keys() == [f"k{i}" for i in range(1, fits + 1)]
        click(2, "<Control-Button-1>")  # k3 out of the range, the rest kept
        assert "k3" not in table.selected_keys()
        assert len(table.selected_keys()) == fits - 1, table.selected_keys()

        table.tree.identify_region = lambda x, y: "heading"
        assert "break" not in click(0), "a heading click is ttk's: it sorts"

        table.tree.identify_region = lambda x, y: "cell"
        table.sync([(f"k{i}", (str(i), "", "", "", "", "", "", "", "")) for i in range(3)])
        click(5)                        # a blank slot below the three rows
        assert table.selected_keys() == [], table.selected_keys()
    """)


def test_a_cleared_selection_leaves_no_anchor_behind():
    """After the selection is cleared, Shift starts afresh from the top row on screen.

    ``select_keys([])`` and a click on a blank slot emptied the selection but kept
    the cursor and the anchor, so the next Shift+Down selected a range from a row
    that had been cleared away - rows nobody chose, and nothing on screen said
    where the range came from.
    """
    run_gui("""
        import types
        table = app.pages["connections"].table
        table.sync([(f"k{i}", (str(i), "", "", "", "", "", "", "", ""))
                    for i in range(100)])
    """ + INJECT_FITS + """
        key("<Home>")
        for _ in range(3):
            key("<Shift-Down>")
        assert len(table.selected_keys()) == 4, table.selected_keys()
        table.select_keys([])
        key("<Shift-Down>")
        assert table.selected_keys() == ["k0"], ("select_keys([])", table.selected_keys())

        table.sync([(f"k{i}", (str(i), "", "", "", "", "", "", "", "")) for i in range(3)])
        key("<Home>")
        key("<Shift-Down>")
        key("<Shift-Down>")
        assert len(table.selected_keys()) == 3, table.selected_keys()
        table.tree.identify_region = lambda x, y: "cell"
        table.tree.row_at = table._slots[5]         # a blank slot below the rows
        for handler in table.tree.bindings["<Button-1>"]:
            handler(types.SimpleNamespace(x=10, y=5))
        assert table.selected_keys() == []
        key("<Shift-Down>")
        assert table.selected_keys() == ["k0"], ("blank click", table.selected_keys())
    """)


def test_a_huge_selection_does_not_make_every_scroll_pay_for_it():
    """A scroll costs the rows on screen, however many rows are selected.

    A Shift range can hold every row of the model, and each repaint rebuilt a set
    of the selected keys: with 200 000 rows selected a one-row scroll went from
    0.07 to 9.9 ms (measured 2026-09-29 on Tk 9.0.4), and every live refresh paid
    the same. Time is a noisy witness on a shared runner; memory is not - a set of
    100 000 keys is megabytes, the rows on screen are kilobytes.
    """
    run_gui("""
        import tracemalloc
        table = app.pages["connections"].table
        table.sync([(f"k{i}", (str(i), "", "", "", "", "", "", "", ""))
                    for i in range(100_000)])
    """ + INJECT_FITS + """
        key("<Home>")
        key("<Shift-End>")
        assert len(table.selected_keys()) == 100_000, len(table.selected_keys())
        table.set_offset(0)                         # End left it at the bottom
        tracemalloc.start()
        for _ in range(3):
            table.scroll_by(1)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        assert table.offset == 3, table.offset
        assert peak < 512 * 1024, f"three one-row scrolls allocated {peak} bytes"
    """)


def test_the_render_check_measures_the_table_viewport_on_real_tk():
    """The pixel half of the tests above runs in CI, not here.

    Which rows Tk draws in full and whether ttk's own view moved are pixel facts
    the fake cannot show, so ``tools/ci_gui_render.py --tables`` measures them on
    real Tk under Xvfb. This pins that CI still runs it: ``main`` sends
    ``--tables`` to ``check_table_viewport`` and runs that pass on its own. Losing
    the step would leave every test here green.
    """
    path = os.path.join(ROOT, "tools", "ci_gui_render.py")
    with open(path, encoding="utf-8") as handle:
        module = ast.parse(handle.read())
    main = next(node for node in ast.walk(module)
                if isinstance(node, ast.FunctionDef) and node.name == "main")
    calls = [node for node in ast.walk(main) if isinstance(node, ast.Call)]
    named = {call.func.id for call in calls if isinstance(call.func, ast.Name)}
    check("--tables reaches check_table_viewport", "check_table_viewport" in named,
          f"({sorted(named)})")
    runs = [call for call in calls
            if isinstance(call.func, ast.Attribute) and call.func.attr == "run"
            and any(isinstance(leaf, ast.Constant) and leaf.value == "--tables"
                    for arg in call.args for leaf in ast.walk(arg))]
    check("main runs the table pass as a process of its own", len(runs) == 1,
          f"({len(runs)} subprocess run(s) with --tables)")


def test_clicking_a_blank_slot_selects_nothing():
    """Below the last real row the slots are empty; clicking one used to leave it
    highlighted. The widget selection must drop any blank slot."""
    run_gui("""
        table = app.pages["connections"].table
        rows = [(f"k{i}", (f"p{i}", "TCP", "1.2.3.4", "443",
                           str(i), "1", "0.1", "0.2", "0.3")) for i in range(3)]
        table.sync(rows)

        # a slot past the 3 real rows carries no model key
        blank = next(iid for iid, key in zip(table._slots, table._slot_keys)
                     if key is None)
        real = table._slots[0]

        # click a blank row: nothing is selected, and the widget clears it
        table.tree.selection_set(blank)
        table._on_select()
        assert table.selected_keys() == [], table.selected_keys()
        assert table.tree.selection() == (), table.tree.selection()

        # click a real row AND a blank one: only the real key survives
        table.tree.selection_set(real, blank)
        table._on_select()
        assert table.selected_keys() == ["k0"], table.selected_keys()
        assert table.tree.selection() == (real,), table.tree.selection()
    """)


def test_repaint_is_free_when_nothing_changed():
    """A table nobody is touching must not talk to Tcl at all."""
    run_gui("""
        table = app.pages["connections"].table
        table.sync([(f"k{i}", (str(i), "", "", "", "", "", "", "", ""))
                    for i in range(1000)])

        calls = []
        original = table.tree.item
        table.tree.item = lambda *a, **kw: (calls.append(1), original(*a, **kw))[1]

        table.repaint()
        assert not calls, f"{len(calls)} Tcl writes for an unchanged table"

        # but a real change IS written through
        table.set_offset(10)
        assert calls, "a scrolled table must repaint"
    """)


def test_row_limit_comes_from_the_registry_not_a_constant():
    """The 400-row cap used to be hard-coded, so "your connections" meant "400 of them"."""
    run_gui("""
        from beantester.fields import FIELDS
        from beantester.settings import DEFAULT_SETTINGS

        assert "row_limit" in FIELDS, "row_limit must be a registry field"
        assert "row_limit" in DEFAULT_SETTINGS
        assert app.row_limit() == DEFAULT_SETTINGS["row_limit"]

        app.vars["row_limit"].set(25)
        assert app.row_limit() == 25

        app.vars["row_limit"].set(0)
        assert app.row_limit() == 0, "0 means no limit"

        app.vars["row_limit"].set("nonsense")
        assert app.row_limit() == DEFAULT_SETTINGS["row_limit"], "bad input falls back"
    """)


def test_event_table_is_virtualised_too():
    run_gui("""
        stats = app.pages["statistics"]
        stats.select("events")
        for i in range(2000):
            app.engine.log_event("CHANGE", f"e{i}")
        stats.refresh_events()

        table = stats.events
        assert len(table.tree.get_children()) == table.window()
        assert len(table.tree.get_children()) < 100, "event table is not virtualised"
    """)


def test_clicking_a_column_header_sorts_by_it_and_clicking_again_reverses():
    """The table's primary interaction, and it had ZERO test coverage (measured
    2026-08-01: `_clicked` was never called by anything in the suite).

    The header command is what `refresh_headers` installs on every column, so the
    test goes through the heading exactly the way a click does, rather than
    calling the private method directly.
    """
    run_gui("""
        table = app.pages["connections"].table
        columns = list(table.columns)
        first, second = columns[0], columns[1]
        seen = []
        table.on_sort = lambda state: seen.append(dict(state))

        def click(col):
            table.refresh_headers()
            table.tree.headings[col]["command"]()

        click(first)
        assert table.sort["col"] == first, table.sort
        assert seen and seen[-1]["col"] == first, seen

        # the SAME column flips direction
        was = table.sort["reverse"]
        click(first)
        assert table.sort["col"] == first and table.sort["reverse"] is not was, table.sort

        # a DIFFERENT column starts from that column's default direction, it does
        # not inherit the direction the previous one happened to be left in
        table.sort["reverse"] = True
        default = table.sort.get("default_reverse", False)
        click(second)
        assert table.sort["col"] == second, table.sort
        assert table.sort["reverse"] == default, table.sort

        assert len(seen) == 3, "every click must reach the on_sort callback"
    """)


def test_sorting_returns_the_viewport_to_the_top():
    """A new order means the rows under the pointer are different anyway, and the
    top is what the user looks at after sorting."""
    run_gui("""
        table = app.pages["connections"].table
        table.sync([(str(i), ("p%d" % i, "TCP", "1.2.3.4", "443", "5000",
                              "7", "0.5", "1.0", "0.1")) for i in range(400)])
        table.set_offset(120)
        assert table.offset > 0, table.offset

        table.refresh_headers()
        table.tree.headings[list(table.columns)[0]]["command"]()
        assert table.offset == 0, "sorting must scroll back to the top"
    """)


def test_copying_with_headers_puts_the_column_names_on_the_first_line():
    run_gui("""
        table = app.pages["connections"].table
        table.sync([("a", ("chrome.exe", "TCP", "1.2.3.4", "443", "5000",
                           "7", "0.5", "1.0", "0.1"))])
        table.select_keys(["a"])

        plain = table.copy_text()
        with_head = table.copy_text(header=True)
        assert len(with_head.splitlines()) == len(plain.splitlines()) + 1, (
            plain, with_head)
        assert with_head.splitlines()[1] == plain, "the rows must be unchanged"
        assert "chrome.exe" in with_head

        # nothing selected copies nothing at all, rather than a lone header row
        table.select_keys([])
        assert table.copy_text() == "" and table.copy_text(header=True) == ""
    """)


def test_hiding_columns_never_leaves_the_table_with_none():
    """`set_visible_columns` is how a table hides a column, and it has a floor.

    Hiding is done with ttk's `displaycolumns` rather than by rebuilding the tree
    with fewer columns, which is what keeps it cheap: the model, the render
    callback and the recycled slots still deal in the full row, so nothing about
    virtualisation changes and no data is reformatted.

    The floor matters more than it looks. A table showing no columns is not a
    narrow view, it is a dead end - the header the user would right-click to get
    the columns back is gone with them.
    """
    run_gui("""
        table = app.pages["connections"].table
        everything = table.visible_columns()
        assert len(everything) > 10, everything

        table.set_visible_columns(["proc", "remote_ip", "packets"])
        assert table.visible_columns() == ["proc", "remote_ip", "packets"]
        assert table.tree.kw.get("displaycolumns") == ("proc", "remote_ip", "packets")

        # the order is the TABLE's, not the caller's
        table.set_visible_columns(["packets", "proc"])
        assert table.visible_columns() == ["proc", "packets"]

        table.set_visible_columns([])
        assert len(table.visible_columns()) == 1, "an empty table is a dead end"

        # a layout saved by an older build may name a column that no longer exists
        table.set_visible_columns(["nosuchcolumn", "pid"])
        assert table.visible_columns() == ["pid"]

        table.set_visible_columns(everything)
        assert table.visible_columns() == everything
    """)
