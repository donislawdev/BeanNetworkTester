"""Pytest configuration: import paths and deterministic i18n state.

The original suite ran top-to-bottom and relied on earlier tests leaving the
language set to Polish; here every test starts from a clean, known state
(real language files loaded, UI language = "pl") so tests are order-independent.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest  # noqa: E402

from beantester import crashlog, i18n  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _crash_log_outside_the_repo(tmp_path_factory):
    """No test run may leave a ``crashes/`` folder in the working tree.

    Tests that inject faults on purpose still record them - they just record them
    somewhere disposable. Without this the suite dropped a real crash log next to
    the sources on every run: git-ignored, so nothing ever showed it, and
    indistinguishable at a glance from a crash the developer actually hit.

    ``tests/test_crashlog.py`` points ``app_dir`` at its own per-test directory on
    top of this; a function-scoped monkeypatch wins over a session fixture, so the
    two do not fight.
    """
    crashlog.app_dir = lambda: str(tmp_path_factory.mktemp("crashlog"))
    yield


@pytest.fixture(autouse=True)
def _clean_i18n_state():
    i18n.load_languages()      # real lang/ files
    i18n.set_language("pl")
    yield
    i18n.load_languages()      # undo any temp-dir language loads
    i18n.set_language("pl")


@pytest.fixture(autouse=True)
def _release_the_machine_wide_driver_marker():
    r"""No test may leave ``Global\BeanNetworkTester.WinDivertInUse`` held.

    ``driver.mark_driver_used()`` takes a REAL, machine-wide named mutex - that is
    the whole point of it, and two tests call it because the behaviour they cover
    is about that marker. One of them then monkeypatches ``_drop_use_marker`` so
    the release path never runs, so the handle survived for the rest of the pytest
    process.

    The damage was order-dependent and looked like flakiness in unrelated places:
    ``test_release_on_exit_swallows_a_cleanup_fault`` took the stand-down path and
    never reached the fault it exists to exercise, and
    ``test_cleanup_driver_stops_every_installed_service`` collected an extra
    warning line. Both were failing on this machine before this fixture existed,
    and a full run left the marker held for MINUTES afterwards - measured by
    watching the mutex through two suite runs - so it also stood in the way of any
    real session started right after the tests.

    Cleaning up here rather than in the two tests is deliberate: the next test to
    call ``mark_driver_used`` inherits the guarantee instead of having to know
    about it.
    """
    yield
    from beantester import driver
    marker, driver._USE_MARKER[0] = driver._USE_MARKER[0], None
    driver._DRIVER_USED[0] = False
    if marker is not None:
        try:
            driver._kernel32().CloseHandle(marker[0])
        except Exception:
            pass
