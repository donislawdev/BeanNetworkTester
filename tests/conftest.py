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
from fakes import forget_the_driver_state  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _crash_log_outside_the_repo(tmp_path_factory):
    """No test run may leave a ``crashes/`` folder in the working tree.

    Tests that inject faults on purpose still record them - they just record them
    somewhere disposable. Without this the suite dropped a real crash log next to
    the sources on every run: git-ignored, so nothing ever showed it, and
    indistinguishable at a glance from a crash the developer actually hit.

    ``tests/test_crashlog.py`` points ``user_data_dir`` at its own per-test
    directory on top of this; a function-scoped monkeypatch wins over a session
    fixture, so the two do not fight.
    """
    crashlog.user_data_dir = lambda: str(tmp_path_factory.mktemp("crashlog"))
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
    the whole point of it, and tests call it because the behaviour they cover is
    about that marker. One of them monkeypatches ``_drop_use_marker`` so the
    release path never runs, so the handle survived for the rest of the pytest
    process.

    The damage was order-dependent and looked like flakiness in unrelated places:
    ``test_release_on_exit_swallows_a_cleanup_fault`` took the stand-down path and
    never reached the fault it exists to exercise, and
    ``test_cleanup_driver_stops_every_installed_service`` collected an extra
    warning line. Both were failing on this machine before this fixture existed,
    and a full run left the marker held for MINUTES afterwards - measured by
    watching the mutex through two suite runs - so it also stood in the way of any
    real session started right after the tests.

    The open count ``_OPENS`` goes back to zero for the same reason. Every
    ``mark_driver_used`` adds one for the rest of the process - measured at the
    start of successive tests in two files: 0, 1, 2, 3, 4. Nothing went red,
    because every reader compared a before and an after; the first test to expect
    a count of its own would have been green alone and red after a neighbour.

    Cleaning up here rather than in each test is deliberate: the next test to call
    ``mark_driver_used`` inherits the guarantee instead of having to know about it.
    The body is ``fakes.forget_the_driver_state``, so a test can prove it.
    """
    yield
    forget_the_driver_state()
