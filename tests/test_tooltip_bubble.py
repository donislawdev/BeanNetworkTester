"""The tooltip bubble: ONE reused window, and it keeps out of the way.

``gui/tooltip.py`` exists for a single reason, stated in its own docstring:
Windows flashes an application's taskbar button whenever a new top-level window
appears while the app is not in the foreground, so a fresh ``Toplevel`` per hover
made an idle, STOPPED app light up its own icon at the user for no reason. The
module's answer is one hidden bubble per toplevel, shown and moved and hidden
again.

Nothing guarded that (measured 2026-08-01: 39.9% line coverage, the whole
show/hide lifecycle untouched). Rewriting ``_bubble_for`` to build a Toplevel per
hover would have brought the taskbar flashing back with the suite fully green.
"""
from gui_harness import run_gui


def test_one_bubble_is_reused_for_every_widget_in_a_window():
    """The reason the module exists. A second Toplevel per hover is the bug."""
    run_gui("""
        from beantester.gui import tooltip
        from tkinter import ttk

        tooltip._BUBBLES.clear()
        first, second = ttk.Label(root, text="a"), ttk.Label(root, text="b")

        w1 = tooltip._show_bubble(first, "explanation one", 10, 10, 20)
        w2 = tooltip._show_bubble(second, "explanation two", 40, 60, 20)
        assert w1 is not None and w2 is not None, (w1, w2)
        assert w1 is w2, "a second hover must reuse the bubble, not build one"
        assert len(tooltip._BUBBLES) == 1, tooltip._BUBBLES
    """)


def test_a_bubble_whose_window_died_is_rebuilt_not_reused():
    """The cache is keyed by toplevel; a stale entry must not be handed out."""
    run_gui("""
        from beantester.gui import tooltip
        from tkinter import ttk

        tooltip._BUBBLES.clear()
        label = ttk.Label(root, text="a")
        window, _ = tooltip._bubble_for(label)
        window.destroy()

        again, _ = tooltip._bubble_for(label)
        assert again is not window, "a destroyed bubble must be replaced"
        assert again.winfo_exists(), "and the replacement must be alive"
    """)


def test_no_bubble_is_shown_while_a_dropdown_holds_the_grab():
    """The bubble would cover the very list the user just opened - its popdown
    sits directly under the field the tooltip describes."""
    run_gui("""
        import fake_tk
        from beantester.gui import tooltip
        from tkinter import ttk

        tooltip._BUBBLES.clear()
        label = ttk.Label(root, text="a")

        fake_tk.GRAB[0] = root                      # a popdown is open
        assert tooltip._show_bubble(label, "text", 10, 10) is None
        assert tooltip.make_bubble(label, "text", 10, 10) is None

        fake_tk.GRAB[0] = None
        assert tooltip._show_bubble(label, "text", 10, 10) is not None
    """)


def test_an_empty_tooltip_shows_nothing_at_all():
    run_gui("""
        from beantester.gui import tooltip
        from tkinter import ttk

        tooltip._BUBBLES.clear()
        label = ttk.Label(root, text="a")
        assert tooltip._show_bubble(label, "", 10, 10) is None
        assert not tooltip._BUBBLES, "an empty text must not even build the window"
    """)


def test_hovering_shows_the_bubble_and_leaving_hides_it():
    """The Tooltip state machine: schedule on Enter, show, hide on Leave. The
    fake fires `after` callbacks only when asked, so `_show` is called directly."""
    run_gui("""
        import fake_tk
        from beantester.gui import tooltip
        from tkinter import ttk

        tooltip._BUBBLES.clear()
        fake_tk.GRAB[0] = None
        label = ttk.Label(root, text="a")
        tip = tooltip.Tooltip(label, "the explanation")

        assert tip.shown is False
        tip._show()
        assert tip.shown is True, "hovering long enough must show the bubble"

        tip._hide()
        assert tip.shown is False, "leaving must hide it again"
    """)


def test_a_retipped_label_shows_the_new_wording_not_the_old_one():
    """Toggling "show only the targeted traffic" re-words the scope note; the
    bubble under it is the LONGER version of that same sentence, so a stale
    tooltip contradicts the line it is attached to."""
    run_gui("""
        from beantester.gui import tooltip
        from tkinter import ttk

        label = ttk.Label(root, text="a")
        tooltip.add_tooltip(label, "app.tabs.connections")
        before = label._bnt_tooltip.text

        tooltip.retip(label, "app.tabs.statistics")
        after = label._bnt_tooltip.text
        assert after != before, (before, after)
        assert label._bnt_tooltip is not None

        # retip on a label that never had one attaches instead of failing
        plain = ttk.Label(root, text="b")
        tooltip.retip(plain, "app.tabs.control")
        assert getattr(plain, "_bnt_tooltip", None) is not None
    """)


def test_a_shortcut_is_advertised_on_its_own_line():
    run_gui("""
        from beantester.gui import tooltip
        text = tooltip.tooltip_text("app.tabs.control", shortcut="F5")
        assert text.endswith("\\n[F5]"), repr(text)
        assert tooltip.tooltip_text("", shortcut="F5") == "[F5]"
        assert tooltip.tooltip_text("") == ""
    """)


def test_hiding_a_bubble_never_builds_a_window():
    """``_hide`` is bound to <Destroy>, so this path runs during Tk's teardown.

    It used to go through ``_bubble_for``, which BUILDS a Toplevel when the cached
    one is gone. REPRODUCED on real Tk before the fix: destroying a window with the
    bubble still alive creates nothing, but destroying the BUBBLE first and then the
    window built a fresh Toplevel inside the destroy cascade, every time.
    """
    run_gui("""
        from beantester.gui import tooltip
        from tkinter import ttk
        import tkinter as tk

        tooltip._BUBBLES.clear()
        label = ttk.Label(root, text="a")
        window, _ = tooltip._bubble_for(label)
        window.destroy()                      # the bubble dies before its widget

        built = []
        real = tk.Toplevel
        tk.Toplevel = lambda *a, **kw: (built.append(1), real(*a, **kw))[1]
        tooltip.tk.Toplevel = tk.Toplevel
        try:
            tooltip._hide_bubble(label)        # what <Destroy> reaches
        finally:
            tk.Toplevel = real
            tooltip.tk.Toplevel = real
        assert not built, "hiding a dead bubble built a window during teardown"
    """)


def test_hiding_still_withdraws_a_live_bubble():
    """The other half: the fix must not turn hiding into a no-op.

    Asserted on the CALL rather than on ``state()`` - the fake tkinter answers
    "normal" unconditionally, so a state assertion here would pass whatever the
    code did, which is the kind of green that hides a broken fix.
    """
    run_gui("""
        from beantester.gui import tooltip
        from tkinter import ttk

        tooltip._BUBBLES.clear()
        label = ttk.Label(root, text="a")
        window = tooltip._show_bubble(label, "text", 10, 10, 20)
        assert window is not None
        hidden = []
        window.withdraw = lambda *a, **kw: hidden.append(1)
        tooltip._hide_bubble(label)
        assert hidden, "a live bubble was not withdrawn"
    """)


def test_the_bubble_opens_on_the_monitor_the_widget_is_on():
    """The 2026-08-26 report, end to end: window on the second monitor, bubble on
    the first one.

    ``_show_bubble`` asked Tk how big "the screen" is, and on Windows that is the
    PRIMARY monitor however many are attached - so the bubble was clamped onto a
    monitor the user was not looking at. This drives the whole show path (the
    monitor lookup is the only thing stubbed) and reads back the geometry the
    bubble was actually given.

    The second half is the half that would have shipped broken: on Linux CI, and
    on any machine where the system will not answer, ``monitor_work_area``
    returns None and the bubble must fall back to the old screen box rather than
    to nothing.
    """
    run_gui("""
        from beantester import winenv
        from beantester.gui import tooltip
        from tkinter import ttk

        def where(window):
            spec = window.kw.get("geometry")
            assert spec, "the bubble never positioned itself"
            x, _, y = spec.lstrip("+").partition("+")
            return int(x), int(y)

        # A portrait monitor to the right of the primary one - the reporter's setup.
        # The fake Tk still answers 1920x1080 for "the screen", which is exactly
        # the lie the old code believed.
        tooltip._BUBBLES.clear()
        winenv.monitor_work_area = lambda x, y: (1920, 0, 3000, 1920)
        label = ttk.Label(root, text="?")
        window = tooltip._show_bubble(label, "filter expression syntax", 2400, 300, 20)
        assert window is not None
        x, y = where(window)
        assert 1920 <= x < 3000, "the bubble jumped back to the primary monitor: %d" % x
        assert 0 <= y < 1920, y

        # No answer from the system: the old behaviour, not no behaviour.
        winenv.monitor_work_area = lambda x, y: None
        window = tooltip._show_bubble(label, "filter expression syntax", 100, 100, 20)
        assert window is not None
        x, y = where(window)
        assert 0 <= x <= 1920 and 0 <= y <= 1080, (x, y)
    """)


def test_dead_bubbles_do_not_pile_up_across_windows():
    """The cache is keyed by toplevel NAME and Tk does not reuse names, so without
    pruning every window ever opened leaves an entry holding a dead Toplevel and
    Label. MEASURED on real Tk: 25 open/close cycles left 25 entries, all dead."""
    run_gui("""
        from beantester.gui import tooltip
        from tkinter import ttk
        import tkinter as tk

        tooltip._BUBBLES.clear()
        for _ in range(12):
            win = tk.Toplevel(root)
            label = ttk.Label(win, text="x")
            tooltip._show_bubble(label, "text", 10, 10, 20)
            win.destroy()

        alive = [k for k, e in tooltip._BUBBLES.items() if tooltip._alive(e)]
        assert len(tooltip._BUBBLES) <= 1, (
            "dead bubble entries accumulate: %d left after 12 windows"
            % len(tooltip._BUBBLES))
        assert not alive or len(alive) == 1, alive
    """)
