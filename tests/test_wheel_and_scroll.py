"""The wheel dispatcher and the scrollable container - the behaviour, not the wiring.

``gui/scrollable.py`` carries three fixes for bugs a user hit, each written up in
its docstring, and the suite guarded NONE of them (measured 2026-08-01, 44.5%
line coverage):

* the wheel used to work only over the bare pixels between panels, because the
  old code tore its binding down on ``<Leave>``. The fix is ``_resolve``: hit-test
  by pointer and walk UP the master chain to whatever owns that spot.
* scrolling the page while the pointer passed over a combobox silently changed
  the selected traffic filter or profile. The fix is ``_disarm_combobox_wheel``.
* expanding a section pinned to the bottom edge revealed its content BELOW the
  viewport. The fix is ``ensure_visible``.

The one test that touched any of this replaced ``_resolve`` with a lambda, and
the one that touched ``ensure_visible`` replaced it with a spy - both legitimate
wiring tests, but between them the behaviour above never executed. See the note's
rule about a test that stubs the very function the fault was in.
"""
from gui_harness import run_gui


# -- _resolve: what is under the pointer ------------------------------------- #


def test_the_wheel_finds_the_scrollable_that_owns_the_spot_under_the_pointer():
    """The whole point of the rewrite: a control deep inside the page still
    scrolls the PAGE, because _resolve walks up to the owning ScrollableFrame."""
    run_gui("""
        from tkinter import ttk
        scroll = app.pages["control"].scroll

        # the container itself, and anything nested inside it
        kind, target = app._wheel._resolve(scroll.body)
        assert (kind, target) == ("canvas", scroll), (kind, target)

        deep = ttk.Entry(ttk.Frame(ttk.Frame(scroll.body)))
        kind, target = app._wheel._resolve(deep)
        assert (kind, target) == ("canvas", scroll), (kind, target)
        assert target is scroll, "a nested control must scroll the page it sits on"
    """)


def test_a_widget_that_scrolls_itself_keeps_its_own_wheel():
    """A Treeview with more rows than fit is 'native': the dispatcher must hand
    the wheel to it, not scroll the page out from under it."""
    run_gui("""
        table = app.pages["connections"].table
        table.tree._yview = (0.0, 0.4)          # 60% of the rows are off-screen
        kind, target = app._wheel._resolve(table.tree)
        assert kind == "native" and target is table.tree, (kind, target)

        # ...but only while it actually has something to scroll
        table.tree._yview = (0.0, 1.0)
        kind, _ = app._wheel._resolve(table.tree)
        assert kind != "native", "a fully visible table must not swallow the wheel"
    """)


def test_the_wheel_over_nothing_scrollable_does_nothing():
    run_gui("""
        from tkinter import ttk
        loose = ttk.Frame(root)                  # not inside any ScrollableFrame
        assert app._wheel._resolve(loose) == (None, None)
        assert app._wheel._resolve(None) == (None, None)
    """)


def test_the_walk_up_the_master_chain_is_bounded():
    """``_resolve`` follows ``master`` links; a cycle must not hang the UI thread."""
    run_gui("""
        class Loop:
            pass
        a, b = Loop(), Loop()
        a.master, b.master = b, a               # a cycle, which Tk itself cannot make
        assert app._wheel._resolve(a) == (None, None), "the walk must give up"
    """)


def test_the_wheel_scrolls_the_page_under_the_pointer():
    """End to end through _on_wheel: a real delta moves the real container."""
    run_gui("""
        scroll = app.pages["control"].scroll
        scroll.canvas._yview = (0.0, 0.5)       # there IS something to scroll
        scroll.canvas.scrolled.clear()

        event = type("E", (), {"delta": -120, "num": None, "widget": scroll.body,
                               "x_root": 10, "y_root": 10})()
        assert app._wheel._on_wheel(event) == "break", "a handled wheel must stop here"
        assert any(s[0] == "scroll" for s in scroll.canvas.scrolled), scroll.canvas.scrolled
    """)


# -- the combobox fix -------------------------------------------------------- #


def test_scrolling_over_a_combobox_cannot_change_its_value():
    """ttk::combobox ships a CLASS binding that steps through its values, and
    bindtags run it long before our dispatcher - so scrolling the Control page
    with the pointer crossing a combobox silently changed the traffic filter."""
    run_gui("""
        disarmed = root.class_bindings
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            for widget_class in ("TCombobox", "TSpinbox"):
                key = (widget_class, sequence)
                assert key in disarmed, "not disarmed: " + str(key)
                # replaced with a no-op that returns None, NOT "break": the event
                # must keep travelling to the `all` bindtag where we scroll the page
                assert disarmed[key](None) is None, str(key)
    """)


# -- ensure_visible ---------------------------------------------------------- #


def test_expanding_a_section_at_the_bottom_edge_scrolls_it_into_view():
    """The maths, not the call. Four cases on a viewport smaller than the body."""
    run_gui("""
        scroll = app.pages["control"].scroll
        canvas, body = scroll.canvas, scroll.body

        def geometry(total, view, widget_top, widget_height, at=0.0):
            body.winfo_height = lambda: total
            canvas.winfo_height = lambda: view
            body.winfo_rooty = lambda: 0
            canvas.canvasy = lambda _y: at
            w = type("W", (), {"winfo_rooty": lambda self: widget_top,
                               "winfo_height": lambda self: widget_height})()
            canvas.scrolled.clear()
            return w

        # 1) below the viewport -> scrolls down far enough to show its bottom
        w = geometry(total=1000, view=200, widget_top=500, widget_height=80)
        scroll.ensure_visible(w, margin=10)
        moves = [s for s in canvas.scrolled if s[0] == "moveto"]
        assert moves, "a widget below the fold must be scrolled to"
        assert 0.0 < moves[-1][1] <= 1.0, moves

        # 2) already visible -> nothing happens
        w = geometry(total=1000, view=600, widget_top=100, widget_height=50)
        scroll.ensure_visible(w, margin=10)
        assert not canvas.scrolled, "a visible widget must not move the page"

        # 3) above the current position -> scrolls back up
        w = geometry(total=1000, view=200, widget_top=50, widget_height=40, at=400)
        scroll.ensure_visible(w, margin=10)
        moves = [s for s in canvas.scrolled if s[0] == "moveto"]
        assert moves and moves[-1][1] < 400 / 1000.0, moves

        # 4) taller than the viewport -> show its START, not its end
        w = geometry(total=2000, view=200, widget_top=800, widget_height=900)
        scroll.ensure_visible(w, margin=10)
        moves = [s for s in canvas.scrolled if s[0] == "moveto"]
        assert moves, "a tall widget must still be scrolled to"
        assert abs(moves[-1][1] - (800 - 10) / 2000.0) < 0.01, (
            "a widget taller than the viewport must be shown from its TOP: " + str(moves))
    """)


def test_everything_already_fitting_is_never_scrolled():
    """Guards the early return: with no overflow there is nothing to reveal, and
    moving the page anyway is the jump the user notices."""
    run_gui("""
        scroll = app.pages["control"].scroll
        scroll.body.winfo_height = lambda: 300
        scroll.canvas.winfo_height = lambda: 600      # viewport bigger than content
        scroll.canvas.scrolled.clear()
        widget = type("W", (), {"winfo_rooty": lambda self: 280,
                                "winfo_height": lambda self: 40})()
        scroll.ensure_visible(widget)
        assert not scroll.canvas.scrolled, scroll.canvas.scrolled
    """)


def test_a_container_with_nothing_to_scroll_ignores_the_wheel():
    run_gui("""
        scroll = app.pages["control"].scroll
        scroll.canvas._yview = (0.0, 1.0)             # everything fits
        scroll.canvas.scrolled.clear()
        scroll.scroll(-3)
        assert not scroll.canvas.scrolled, scroll.canvas.scrolled
    """)
