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
        # A page can REFUSE: the Control page's box can be switched off in the
        # Settings window, and a shortcut that focuses a widget nobody can see is
        # worse than one that does nothing. Refusing sends the user to the table,
        # which is what Ctrl+F did before that page had a box at all.
        if page.focus_search() is not False:
            return "break"
    app.select_page(SEARCH_FALLBACK)
    fallback = app.pages.get(SEARCH_FALLBACK)
    if fallback is not None:
        fallback.focus_search()
    return "break"


def pref_changed(app, key):
    """A GUI preference was written: let the pages that react to one react NOW.

    Preferences are stored and then simply READ - the chart asks for its history
    length on the next tick, ``scoped_stat`` asks for the view scope on every
    figure it prints. That is enough for anything the tick redraws anyway, and it
    is NOT enough for a switch whose whole visible effect is a widget appearing or
    disappearing: up to one tick (0.7 s) of a ticked box doing nothing reads as a
    broken checkbox, not as a slow one.

    A broadcast rather than a name in the registry, and the reason is the shape of
    the alternative: ``Pref`` would have to carry the name of an ``App`` method,
    and ``gui/app.py`` sits ON the size ratchet with zero headroom
    (``tests/test_code_shape.py``), so that method would have to live somewhere
    else and be reached through App anyway. This is the same dispatcher shape as
    ``focus_search`` above, in the same place, for the same reason: how a page is
    ADDRESSED belongs to the page registry.

    A page that raises must not take the Settings window down with it - the user
    would be left with a checkbox they cannot untick.
    """
    from ... import crashlog
    for page in app.pages.values():
        handler = getattr(page, "on_pref_changed", None)
        if handler is None:
            continue
        with crashlog.quiet("gui.pages"):
            handler(key)


__all__ = ["PAGES", "Page", "ControlPage", "StatsPage", "ConnsPage",
           "focus_search", "pref_changed"]
