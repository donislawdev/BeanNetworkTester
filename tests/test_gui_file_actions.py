"""Save/Load file and Save repro - the ACTIONS, not just the modules behind them.

``settings.load/save_config_file`` and ``repro.save_repro_report`` are covered as
modules (``test_settings_config_scenario.py``, ``test_summary_repro_views.py``),
and both write formats frozen by "Kontrakty publiczne". What had no test is the
App side: which values the form hands over, what comes back into the widgets, and
what happens when the write fails. Measured 2026-08-01: ``save_repro`` (12 lines),
``load_config_file`` (10) and ``save_config_file`` (8) were the three largest
uncovered blocks in ``gui/app.py``.

The file dialogs are replaced per test, which is also the point - a cancelled
dialog returning "" must do nothing at all, and that branch is how the user backs
out of every one of these.
"""
import json
import os

from gui_harness import run_gui


def test_saving_a_config_writes_what_the_form_currently_holds():
    run_gui("""
        import json, os, tempfile
        from tkinter import filedialog

        target = os.path.join(tempfile.mkdtemp(), "cfg.json")
        filedialog.asksaveasfilename = lambda **k: target

        app.vars["loss"].set("13")
        app.vars["latency"].set("240")
        app.save_config_file()

        assert os.path.exists(target), "the config was not written"
        saved = json.load(open(target, encoding="utf-8"))
        assert float(saved["loss"]) == 13.0, saved
        assert float(saved["latency"]) == 240.0, saved
        assert any("cfg.json" in line for line in app._log_lines), app._log_lines[-3:]
    """)


def test_loading_a_config_puts_it_back_into_the_widgets():
    """Round trip through the real on-disk format, not through a dict."""
    run_gui("""
        import json, os, tempfile
        from tkinter import filedialog

        target = os.path.join(tempfile.mkdtemp(), "cfg.json")
        filedialog.asksaveasfilename = lambda **k: target
        filedialog.askopenfilename = lambda **k: target

        app.vars["loss"].set("21")
        app.vars["latency"].set("310")
        app.save_config_file()

        app.vars["loss"].set("0")
        app.vars["latency"].set("0")
        app.load_config_file()

        assert float(app.vars["loss"].get()) == 21.0, app.vars["loss"].get()
        assert float(app.vars["latency"].get()) == 310.0, app.vars["latency"].get()
    """)


def test_cancelling_the_dialog_writes_nothing_and_changes_nothing():
    """An empty path is how the user backs out; it must not reach the writer."""
    run_gui("""
        from tkinter import filedialog

        filedialog.asksaveasfilename = lambda **k: ""
        filedialog.askopenfilename = lambda **k: ""

        app.vars["loss"].set("7")
        before = len(app._log_lines)

        app.save_config_file()
        app.load_config_file()

        assert float(app.vars["loss"].get()) == 7.0, "a cancelled load must not clear the form"
        assert len(app._log_lines) == before, app._log_lines[before:]
    """)


def test_an_unwritable_path_reports_the_error_instead_of_crashing():
    """The handler is what stands between a bad path and a traceback in the UI.

    The app uses its own dark modal (``gui/dialogs.show_error``), not
    ``tkinter.messagebox`` - the native one is un-themable and takes its button
    labels from the OS locale - so that is what the spy replaces.
    """
    run_gui("""
        from tkinter import filedialog
        import beantester.gui.dialogs as dialogs

        shown = []
        dialogs.show_error = lambda parent, title, message: shown.append(message)

        # a directory that does not exist - the write must fail, not the app
        filedialog.asksaveasfilename = lambda **k: "Z:/nope/does/not/exist/cfg.json"
        app.save_config_file()

        assert shown, "a failed save must tell the user"
        assert "cfg.json" not in " ".join(app._log_lines[-2:]), (
            "and it must NOT claim the file was saved: " + str(app._log_lines[-2:]))
    """)


def test_loading_a_file_that_is_not_a_config_is_refused_readably():
    """Broken JSON raises out of ``settings.load_config_file``; the form must be
    left alone rather than half-filled from a partial read."""
    run_gui("""
        import os, tempfile
        from tkinter import filedialog
        import beantester.gui.dialogs as dialogs

        shown = []
        dialogs.show_error = lambda parent, title, message: shown.append(message)

        junk = os.path.join(tempfile.mkdtemp(), "junk.json")
        open(junk, "w", encoding="utf-8").write("this is not json at all {{{")
        filedialog.askopenfilename = lambda **k: junk

        app.vars["loss"].set("33")
        app.load_config_file()

        assert shown, "a broken file must be reported, not swallowed"
        assert float(app.vars["loss"].get()) == 33.0, "the form must survive a bad load"
    """)


def test_a_config_of_the_wrong_shape_is_refused_too():
    """Valid JSON, wrong type. A settings file that is an ARRAY is what anything
    writing one entry per line produces, so it is not an exotic input."""
    run_gui("""
        import os, tempfile
        from tkinter import filedialog
        import beantester.gui.dialogs as dialogs

        shown = []
        dialogs.show_error = lambda parent, title, message: shown.append(message)

        wrong = os.path.join(tempfile.mkdtemp(), "list.json")
        open(wrong, "w", encoding="utf-8").write('[{"loss": 5}]')
        filedialog.askopenfilename = lambda **k: wrong

        app.load_config_file()
        assert shown, "a JSON array is not a config and must be refused"
    """)


def test_a_misspelled_setting_reaches_the_user_as_a_dialog():
    """The CLI is not the only reader of a config file.

    Unknown keys became an error so a typo cannot pass a pipeline's --dry-run in
    silence. The same raise travels through "Load file" here, and the GUI half of
    that change is worth its own guard: this window is where a hand-written file
    is most likely to be opened, and the form must survive the refusal with the
    values the user already had.
    """
    run_gui("""
        import json, os, tempfile
        from tkinter import filedialog
        import beantester.gui.dialogs as dialogs

        shown = []
        dialogs.show_error = lambda parent, title, message: shown.append(message)

        typo = os.path.join(tempfile.mkdtemp(), "typo.json")
        with open(typo, "w", encoding="utf-8") as f:
            json.dump({"loss": 10, "latancy": 300}, f)
        filedialog.askopenfilename = lambda **k: typo

        app.vars["loss"].set("33")
        app.load_config_file()

        assert shown, "a misspelled setting must be reported, not swallowed"
        assert "latancy" in shown[0], f"the dialog must name the key: {shown[0]!r}"
        assert float(app.vars["loss"].get()) == 33.0, "the form must survive it"
    """)


def test_a_repro_report_needs_a_session_before_it_can_be_saved():
    """Without a seed there is nothing to reproduce, so the app says so rather
    than writing a report that cannot be replayed."""
    run_gui("""
        from tkinter import filedialog

        called = []
        filedialog.asksaveasfilename = lambda **k: called.append(1) or ""

        assert app.engine.effective_seed() is None, "this test needs a stopped engine"
        app.save_repro()
        assert not called, "it must not even open the dialog without a session"
        assert app._log_lines, "and it must say why"
    """)


def test_saving_a_repro_writes_the_report_and_logs_the_command_to_replay_it():
    """The report is a frozen on-disk format AND the CLI line the user pastes
    back; the log has to carry that line or the report is half useless."""
    run_gui("""
        import json, os, tempfile
        from tkinter import filedialog
        from beantester.synthetic import SyntheticDivert

        target = os.path.join(tempfile.mkdtemp(), "repro.json")
        filedialog.asksaveasfilename = lambda **k: target

        app.engine.set_seed(4242)
        app.engine.start("test", divert=SyntheticDivert(gen_kbps=500, seed=3))
        try:
            app.save_repro()
        finally:
            app.engine.stop()

        assert os.path.exists(target), "no report was written"
        report = json.load(open(target, encoding="utf-8"))
        assert report["seed"] == 4242, report
        assert report.get("cli_command"), report
        assert any(report["cli_command"] in line for line in app._log_lines), (
            "the replay command must reach the log: " + str(app._log_lines[-3:]))
    """)
