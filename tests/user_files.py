"""Point every file the app writes for the USER at a throwaway directory.

One place, two callers: ``gui_harness.run_gui`` (which builds an App per test in a
subprocess) and ``smoke_gui.py``. It used to live only in the harness, so the smoke
script - run by ``tests/test_gui_smoke.py`` and by CI - wrote the developer's real
``bean_network_tester_ui.json`` and a ``crashes/`` folder into the repository root
on every test run. Both are git-ignored, so nothing ever showed it: running the
suite quietly reset the remembered window geometry, language and sort order.

Call it BEFORE the App is built - the stores read their path at construction.
"""
import os
import tempfile


def redirect_to_temp(directory=None):
    """Send UI state, profiles and the crash log to ``directory`` (a temp dir).

    Returns the directory, so a caller can assert against it.
    """
    directory = directory or tempfile.mkdtemp(prefix="bnt-test-")

    import beantester.gui.ui_state as ui_state
    import beantester.gui.profiles as profiles
    from beantester import crashlog

    # The stores take their path as a default argument, which is what the App
    # relies on; rebinding the default is what makes an already-imported module
    # follow us without touching production code.
    ui_state.UiStateStore.__init__.__defaults__ = (
        os.path.join(directory, "ui.json"),)
    profiles.ProfileStore.__init__.__defaults__ = (
        os.path.join(directory, "profiles.json"),)
    crashlog.app_dir = lambda: directory
    return directory
