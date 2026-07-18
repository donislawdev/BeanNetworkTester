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

from beantester import i18n  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_i18n_state():
    i18n.load_languages()      # real lang/ files
    i18n.set_language("pl")
    yield
    i18n.load_languages()      # undo any temp-dir language loads
    i18n.set_language("pl")
