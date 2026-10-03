"""GUI work that need not happen (performance review 2026-09-26, chunk R-4).

Each test here pins one place where the window used to redo work whose result was
already on screen, and proves the skip is not a blind spot: the moment the input
really changes, the work happens again. Measured costs are in the docstrings of
the code under test; these tests count CALLS, which is exact on any runner -
time is the rig's business, never a test's (tracker rule 8).
"""
import textwrap

from fake_tk import W
from gui_harness import run_gui

from beantester.gui.configure import configure_changed


class _Recorder(W):
    """A fake widget that also writes down every configure() it receives."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls = []

    def configure(self, *a, **kw):
        self.calls.append(dict(kw))
        super().configure(*a, **kw)

    config = configure


# -- configure_changed -------------------------------------------------------- #
def test_configure_changed_leaves_an_unchanged_option_alone():
    """Only the options that differ reach configure(); nothing at all when none do."""
    widget = _Recorder(text="12", style="Card.TLabel")

    assert configure_changed(widget, text="12", style="Card.TLabel") is False
    assert widget.calls == [], "an option already holding its value was set again"

    assert configure_changed(widget, text="13", style="Card.TLabel") is True
    assert widget.calls == [{"text": "13"}], (
        "only the option that moved may be configured: " + repr(widget.calls))

    # A Tcl answer is compared as text: Tk hands `state` back as a Tcl object, and
    # a number written as an int reads back as its string.
    widget.calls.clear()
    widget.kw["wraplength"] = "600"
    assert configure_changed(widget, wraplength=600) is False
    assert widget.calls == []


def test_configure_changed_does_not_trust_the_state_option_alone():
    """ttk records "disabled" twice; a cleared FLAG under a "disabled" option is not
    disabled, so asking for "disabled" must configure it again."""
    ttk_like = _Recorder()
    ttk_like.configure(state="disabled")
    ttk_like.state(["!disabled"])           # the flag goes, the option stays
    ttk_like.calls.clear()
    assert ttk_like.cget("state") == "disabled"

    assert configure_changed(ttk_like, state="disabled") is True
    assert ttk_like.calls == [{"state": "disabled"}]
    assert ttk_like.instate(["disabled"]), "configuring it must set the flag again"

    # ...and with option and flag in agreement, nothing happens
    ttk_like.calls.clear()
    assert configure_changed(ttk_like, state="disabled") is False
    assert configure_changed(ttk_like, state="normal") is True
    assert configure_changed(ttk_like, state="normal") is False
    assert ttk_like.calls == [{"state": "normal"}]


def test_configure_changed_reads_the_option_alone_on_a_widget_without_flags():
    """A classic Tk widget has no state flags; its option is the whole truth."""
    class Classic:
        def __init__(self):
            self.kw = {"state": "normal"}
            self.calls = []

        def cget(self, key):
            return self.kw[key]

        def configure(self, **kw):
            self.calls.append(kw)
            self.kw.update(kw)

    widget = Classic()
    assert configure_changed(widget, state="normal") is False
    assert configure_changed(widget, state="disabled") is True
    assert widget.calls == [{"state": "disabled"}]


# -- Statistics > Live ------------------------------------------------------- #
_COUNT_CONFIGURES = """
CALLS = []

def counting(widget, name):
    real = widget.configure
    def configure(*a, **kw):
        CALLS.append((name, dict(kw)))
        return real(*a, **kw)
    widget.configure = configure
    widget.config = configure
"""


def _counting(body):
    """``body`` with ``counting(widget, name)`` and its ``CALLS`` list defined."""
    return _COUNT_CONFIGURES + textwrap.dedent(body)


def test_the_live_counters_are_not_rewritten_when_nothing_moved():
    """Writing the same 22 texts back every tick was 3.7-4.0 ms of re-layout on
    real Tk. Now an unchanged counter is left alone - and a changed one is not."""
    run_gui(_counting("""
        app.select_page("statistics")
        page = app.current_page()
        app.last_snapshot = {"seen": 7, "drop_loss": 2}
        page.refresh_counters()                  # the first pass writes them

        for key, label in page.stat_labels.items():
            counting(label, key)
        counting(page._chart_frame, "chart frame")
        page.refresh_counters()
        assert CALLS == [], "nothing moved, yet these were rewritten: %r" % CALLS

        app.last_snapshot = {"seen": 8, "drop_loss": 2}
        page.refresh_counters()
        assert [name for name, _ in CALLS] == ["seen"], CALLS
        assert page.stat_labels["seen"].cget("text") == "8"
    """))


def test_the_chart_is_not_redrawn_from_the_same_data():
    """A stopped session showed the same picture, redrawn from scratch every tick
    (1.7 ms). Same data, same size, same unit: no redraw. New data: a redraw."""
    run_gui("""
        from beantester.gui.pages import stats as stats_mod
        DRAWN = []
        real = stats_mod.draw_throughput_chart
        def counting(*a, **k):
            DRAWN.append(1)
            return real(*a, **k)
        stats_mod.draw_throughput_chart = counting

        app.select_page("statistics")
        page = app.current_page()
        page.draw_chart()
        page.draw_chart()
        assert len(DRAWN) == 1, "the same data was drawn %d times" % len(DRAWN)

        app.down_hist.append(42.0)
        page.draw_chart()
        assert len(DRAWN) == 2, "new data must reach the chart"
    """)


# -- the running icon -------------------------------------------------------- #
def test_the_running_dot_is_the_same_picture_in_far_fewer_tk_calls():
    """The dot was one PhotoImage.put per pixel over the whole image - ~8 000 Tk
    calls and 265-311 ms of the window's start for the shipped 256 px icon. It is
    one put per stretch of a row now, and the pixels must be exactly the ones the
    per-pixel version painted (the rule is restated here, not imported, so a change
    to the drawing cannot quietly agree with itself)."""
    run_gui("""
        from beantester.gui import icon

        class Recording:
            def __init__(self):
                self.pixels, self.puts = {}, 0
            def put(self, data, to):
                self.puts += 1
                if data.startswith("{"):            # one row: "{#c #c ...}"
                    colours = data.strip("{}").split()
                else:                               # one pixel: "#c"
                    colours = [data]
                x0, y = to
                for i, colour in enumerate(colours):
                    assert (x0 + i, y) not in self.pixels, "painted twice"
                    self.pixels[(x0 + i, y)] = colour

        def reference(size):
            dcx = dcy = size * 0.76
            dr = max(2.0, size * 0.20)
            out = {}
            for y in range(size):
                for x in range(size):
                    d = ((x - dcx) / dr) ** 2 + ((y - dcy) / dr) ** 2
                    if d <= 1.0:
                        out[(x, y)] = "#8a1010" if d > 0.62 else "#e53935"
            return out

        for size in (2, 3, 7, 16, 64, 256):
            img = Recording()
            icon._put_dot(img, size)
            want = reference(size)
            assert img.pixels == want, "size %d: %d pixels differ" % (
                size, len(set(img.pixels.items()) ^ set(want.items())))
            rows = len({y for _, y in want})
            assert img.puts == rows, (
                "size %d: %d puts for %d rows - one per row is the point"
                % (size, img.puts, rows))
    """)


# -- one tick ------------------------------------------------------------------ #
def test_one_tick_takes_one_stats_snapshot_and_the_banner_reads_it():
    """The banner took a second snapshot of its own - the stats lock and the
    injector's heap lock, twice a tick, for the same numbers. One snapshot now, and
    the banner must still speak about THIS tick, not the one before."""
    run_gui("""
        TAKEN = []
        real = app.engine.stats_snapshot
        def counting(*a, **k):
            TAKEN.append(1)
            return real(*a, **k)
        app.engine.stats_snapshot = counting

        app.engine.st["drop_overflow"] = 3
        app._tick()
        assert len(TAKEN) == 1, "one tick took %d stats snapshots" % len(TAKEN)
        assert app.engine_warning.kw.get("text") == bnt.T("warn.queue_overflow"), (
            "the banner did not see the snapshot of the tick it ran in")
    """)


def test_a_resize_inside_the_window_does_not_rewrap_the_root_labels():
    """Bound on the root, the handler heard every widget's <Configure> (394 while
    the window was built). Only the root's and the summary holder's own events can
    change what it computes, so only those reach it."""
    run_gui(_counting("""
        class Event:
            def __init__(self, widget):
                self.widget = widget

        for name in ("summary", "admin_warning", "engine_warning"):
            if getattr(app, name) is not None:
                counting(getattr(app, name), name)

        app._on_root_configure(Event(next(iter(app.form.entries.values()))))
        app._on_root_configure(Event(".a.widget.tkinter.never.named"))
        assert CALLS == [], "a child's resize rewrapped the root labels: %r" % CALLS

        app._on_root_configure(Event(app.root))
        assert {"summary", "engine_warning"} <= {name for name, _ in CALLS}, CALLS
        CALLS.clear()
        app._on_root_configure(Event(app.summary_holder))
        assert "summary" in {name for name, _ in CALLS}, CALLS
        CALLS.clear()
        app._on_root_configure()                 # called directly: as before
        assert "summary" in {name for name, _ in CALLS}, CALLS
    """))


# -- the log box --------------------------------------------------------------- #
def test_queued_log_lines_reach_the_box_in_one_write():
    """Fifty queued lines were fifty inserts, scrolls and state changes (13 ms on
    real Tk); they are one write now, in the same order."""
    run_gui("""
        import threading
        app._logview.drain()
        box = app.log_box
        WRITES = []
        real_insert = box.insert
        def counting(where, text):
            WRITES.append(text)
            return real_insert(where, text)
        box.insert = counting

        lines = ["line %d" % i for i in range(50)]
        worker = threading.Thread(target=lambda: [app.log(x) for x in lines])
        worker.start()
        worker.join()                            # a worker queues, it never drains
        assert WRITES == [], "a worker thread wrote into the widget"

        app._logview.drain()
        assert len(WRITES) == 1, "%d writes for one drain" % len(WRITES)
        stamped = app._log_lines[-50:]
        assert [line.split("] ", 1)[1] for line in stamped] == lines
        assert WRITES[0] == "\\n".join(stamped) + "\\n"
    """)


# -- Statistics > Session ------------------------------------------------------ #
def test_the_session_page_asks_for_the_host_once_per_half_minute():
    """Every tick opened two UDP sockets to find this machine's addresses - on
    Windows each one a SOCKET-layer event for the engine's watcher to parse."""
    run_gui("""
        import beantester.utils as utils
        ASKED = []
        def counting():
            ASKED.append(1)
            return ("host", "10.0.0.2", "-")
        utils.host_identity = counting

        app.select_page("statistics")
        page = app.current_page()
        page.refresh_session()
        page.refresh_session()
        assert len(ASKED) == 1, ASKED
        assert page.sess_labels["private_ipv4"].cget("text") == "10.0.0.2"

        page._host_at -= page.HOST_IDENTITY_S    # half a minute later
        page.refresh_session()
        assert len(ASKED) == 2, ASKED

        page._on_subpage()                       # coming back asks afresh
        page.refresh_session()
        assert len(ASKED) == 3, ASKED
    """)


# -- the Control form, one keystroke ----------------------------------------- #
def test_a_keystroke_reconfigures_nothing_that_did_not_change():
    """A keystroke re-ran every override, mark and note in the form and configured
    each of them regardless (1.63 ms a keystroke on real Tk). The ones that did not
    change are left alone; the one that did is still painted."""
    run_gui(_counting("""
        from beantester.gui.form import SECTION_BY_ID
        form = app.form
        sid = "latency"
        keys = [k for k in SECTION_BY_ID[sid].fields if k in form.entries]
        assert keys, "the latency section must have text fields"
        form._on_edit(sid)                       # settle: first marks are written

        watched = dict(form.entries)
        watched.update({"label " + k: w for k, w in form.labels.items()})
        watched.update({"note " + k: w for k, w in form.notes.items()})
        watched.update({"error " + k: w for k, w in form.errors.items()})
        watched["START"] = app.btn_start
        for name, widget in watched.items():
            counting(widget, name)

        form._on_edit(sid)
        assert CALLS == [], "an unchanged form was reconfigured: %r" % CALLS

        # a value the field rejects: THAT field turns red and the reason appears
        key = keys[0]
        app.vars[key].set("not a number")
        form._on_edit(sid)
        touched = sorted({name for name, _ in CALLS})
        assert key in touched and ("error " + sid) in touched, touched
        assert form.entries[key].cget("style") == "Bad.TEntry"
    """))
