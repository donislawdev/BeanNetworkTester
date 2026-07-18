"""Page registry.

The notebook is a *renderer* of this table. When the tool outgrows a tab bar
(more than ~6 pages), swapping the Notebook for a sidebar means writing one new
adapter, not rewriting the GUI.
"""
from typing import NamedTuple

from .conns import ConnsPage
from .control import ControlPage
from .stats import StatsPage


class Page(NamedTuple):
    id: str
    label: str          # i18n key
    factory: type


PAGES = (
    Page(ControlPage.ID, ControlPage.LABEL, ControlPage),
    Page(StatsPage.ID, StatsPage.LABEL, StatsPage),
    Page(ConnsPage.ID, ConnsPage.LABEL, ConnsPage),
)

__all__ = ["PAGES", "Page", "ControlPage", "StatsPage", "ConnsPage"]
