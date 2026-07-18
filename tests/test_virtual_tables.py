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
from gui_harness import run_gui


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


def test_scrolling_moves_the_window_and_stays_in_range():
    run_gui("""
        table = app.pages["connections"].table
        table.sync([(f"k{i}", (str(i), "", "", "", "", "", "", "", ""))
                    for i in range(1000)])

        assert table.offset == 0
        table.scroll_by(50)
        assert table.offset == 50
        table.scroll_by(-500)
        assert table.offset == 0, "must not scroll above the first row"
        table.set_offset(10 ** 9)
        assert table.offset == table.max_offset(), "must not scroll past the last row"
        assert table.max_offset() == 1000 - table.window()

        # a model that fits entirely in the viewport cannot scroll at all
        table.sync([("only", ("1", "", "", "", "", "", "", "", ""))])
        assert table.max_offset() == 0
        assert table.offset == 0
    """)


def test_selection_is_by_model_key_and_survives_sorting():
    """Item ids are recycled slots: a selection stored as an item id is a bug."""
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

        # scrolling the selected row out of view does not deselect it
        table.set_offset(400)
        assert table.selected_keys() == ["k7"]

        # a row that leaves the model does leave the selection
        table.sync(rows[:5])
        assert table.selected_keys() == []
    """)


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
