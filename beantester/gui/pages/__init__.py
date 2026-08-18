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

SEARCH_FALLBACK = ConnsPage.ID


def focus_search(app):
    """Ctrl+F: put the caret in the search box of the page the user is looking at.

    🔴 There are TWO search boxes now (the connection table and the Control
    page's field search) and only one Ctrl+F. Both pages used to bind it on the
    ROOT - and a root binding without ``add="+"`` REPLACES the one before it, so
    whichever page happened to be built second would have silently taken the
    shortcut away from the other. One dispatcher, bound by both, cannot do that.

    From a page with no search box the shortcut still does what it has always
    done: bring the connection table forward and start typing there. That is the
    older behaviour and the one people already have in their fingers.
    """
    page = app.current_page()
    if page is not None and hasattr(page, "focus_search"):
        page.focus_search()
        return "break"
    app.select_page(SEARCH_FALLBACK)
    fallback = app.pages.get(SEARCH_FALLBACK)
    if fallback is not None:
        fallback.focus_search()
    return "break"


__all__ = ["PAGES", "Page", "ControlPage", "StatsPage", "ConnsPage", "focus_search"]
