"""Chaos through the whole stack: engine threads, model worker and the UI tick.

``test_concurrency_chaos.py`` covers the engine's own threads, and one of its
tests now drives the model worker against a live engine. What neither reaches is
the GUI on top of both: the 700 ms ``_tick``, the start/stop transitions that run
off the UI thread, and a user doing things to the connections table while a
rebuild is in flight.

That combination is not hypothetical. The off-main-thread Tk call in the old
target refresher survived every test precisely because nothing ran the pieces
together, and the fake tkinter is single threaded, so it could not see it. The
failure it caused is the dangerous one: Tk called from a worker either hangs the
GUI - and a hung GUI keeps the WinDivert handle open, which is what FAIL-OPEN
exists to prevent - or raises ``RuntimeError: main thread is not in main loop``
into a bare ``except``, silently swallowing the thing it was told to show.

Scope, so nobody expects more than is here: this is about THREAD BOUNDARIES, not
volume. The traffic is ``SyntheticDivert``, which tops out around 1900 packets/s
over a twelve-row connection table (measured; see the note in
``test_concurrency_chaos.py``). Making the sort big enough to matter is that
file's job. Here the table just has to be alive while the UI pokes it.

The invariants:

* **no widget is touched off the main thread** - checked globally, by watching the
  fake widget base class rather than a handful of named widgets, so it also covers
  code nobody thought to spy on;
* **``_tick`` never swallows an exception** - it catches everything by design (the
  loop must survive a broken tick), and logs ``log.ui_error``. A test that only
  checked "the loop kept running" would pass while every tick failed;
* **the model worker never wedges** - ``busy()`` stuck at True is how the
  connections table stops rebuilding for the rest of the session;
* **nothing is left behind** - no leaked worker threads, no engine fault, the
  divert released.
"""
from gui_harness import run_gui


def test_the_whole_stack_survives_a_user_being_a_nuisance():
    """Start, stop, restart, switch pages, search, sort and freeze - all under
    live traffic, with the tick running throughout."""
    run_gui("""
        import threading
        import time

        import fake_tk
        from beantester.synthetic import SyntheticDivert

        # --- 1) watch for ANY widget call from a thread that is not the main one.
        # Named-widget spies only catch the widget somebody suspected; this covers
        # every widget in the app, including ones added later.
        offenders = []
        main = threading.main_thread()

        def watch(cls, name):
            original = getattr(cls, name, None)
            if original is None:
                return
            def spy(self, *a, **kw):
                if threading.current_thread() is not main:
                    offenders.append((name, threading.current_thread().name))
                return original(self, *a, **kw)
            setattr(cls, name, spy)

        # `config = configure` in the fake binds the ORIGINAL function at class
        # creation, so patching one does not patch the other. Both, explicitly.
        for _name in ("configure", "config", "pack", "pack_forget", "grid",
                      "grid_forget", "insert", "delete", "winfo_ismapped",
                      "after", "after_cancel"):
            watch(fake_tk.W, _name)

        # --- 2) a real session on synthetic traffic
        real_start = app.engine.start
        app.engine.start = (lambda filt, divert=None, duration=0:
                            real_start(filt, divert=SyntheticDivert(seed=5),
                                       duration=duration))

        def tick(times=1, pause=0.01):
            for _ in range(times):
                app._tick()
                time.sleep(pause)

        app._start(); app._settle_transition()
        assert app.running is True, "the GUI did not start"
        tick(10)
        assert app.engine.stats_snapshot()["seen"] > 0, "no traffic flowed"

        conns = app.pages["connections"]
        page_ids = list(app.pages)

        # --- 3) be a nuisance: switch pages, search, sort and freeze while the
        # worker is mid-rebuild, and restart the session underneath all of it.
        for i in range(60):
            app.select_page(page_ids[i % len(page_ids)])
            if i % 5 == 0:
                conns.search_var.set(["", "93.184", "443", "zzz"][(i // 5) % 4])
                conns._schedule_search()
            if i % 7 == 0:
                col = ["bytes", "last", "remote_ip", "local_port"][(i // 7) % 4]
                conns.table.sort["col"] = col
                conns.table.sort["reverse"] = not conns.table.sort["reverse"]
                conns.refresh(force=True)
            if i % 11 == 0:
                conns.pause_var.set(not conns.pause_var.get())
            if i == 25:
                app._stop(); app._settle_transition()
                assert app.running is False, "the GUI did not stop"
            if i == 32:
                app._start(); app._settle_transition()
                assert app.running is True, "the GUI did not restart"
            app._tick()
            time.sleep(0.005)

        conns.pause_var.set(False)
        tick(20)

        # let anything in flight land, so busy() below means something
        for _ in range(100):
            if not conns._model.busy():
                break
            app._tick()
            time.sleep(0.02)

        before_stop = {t.name for t in threading.enumerate()}
        app._stop(); app._settle_transition()
        tick(5)
        time.sleep(0.3)

        # --- 4) the invariants
        assert not offenders, f"widget touched off the main thread: {offenders[:5]}"

        # _tick catches everything on purpose - the loop has to survive a broken
        # tick - and reports it as log.ui_error. So "the loop kept running" proves
        # nothing; the log is the only place a failed tick shows up. Take the
        # literal part of the translated template, ahead of the {e} placeholder.
        marker = bnt.T("log.ui_error", e="\\x00").split("\\x00")[0].strip()
        assert marker, "log.ui_error starts with its placeholder; pick another marker"
        ui_errors = [l for l in app._log_lines if marker in l]
        assert not ui_errors, f"_tick swallowed an exception: {ui_errors[:3]}"

        assert conns._model.busy() is False, "the model worker wedged"
        assert app.engine.fault is None, f"engine faulted: {app.engine.fault}"
        assert app.engine.is_running() is False, "the engine is still running"
        assert app.engine._divert is None, "the divert was not released"

        leaked = {t.name for t in threading.enumerate()} - before_stop
        leaked -= {t.name for t in threading.enumerate() if not t.is_alive()}
        assert not leaked, f"threads outlived the session: {leaked}"
    """)
