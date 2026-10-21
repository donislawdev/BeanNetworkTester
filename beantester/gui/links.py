"""The page buttons: the two places in the program that open a web page.

"Donate" opens the support page, "GitHub" the project's page (source, releases,
bug reports). Both sit in the window header and in the About window, so one
button is used in four places and is built here, once. A third page is one more
``Page`` in ``PAGES``.

This is also the ONE file that calls ``webbrowser``. The program has no network
client: a page opens in the user's own browser, only when they click, and
``tests/test_no_telemetry.py`` allows exactly this file to do it.

``webbrowser`` does not raise when it fails on Windows - it returns False
(``os.startfile`` failing is caught inside it). The log used to say "Support page
opened" either way, so a click that opened nothing reported success. It now says
the browser did not open and prints the address, which the user can copy from
the log instead.

As root (Linux, where a capture needs root) no browser is started at all.
MEASURED 2026-10-20 on Ubuntu 26.04 under ``sudo``: ``webbrowser`` picked
``xdg-open``, which runs in the background, so it answered True - and nothing
opened (root has no session bus, and the display refused it). The log said
"opened". A browser that DID start would run as root on the person's desktop,
which is worse - and that holds for any way of becoming root (``su``, ``doas``, a
root login), not only for the ``sudo`` that leaves its traces in the environment.
So the window says why and prints the address, the way it does for a browser
that failed.
"""
from dataclasses import dataclass
from tkinter import ttk
import webbrowser

from .. import crashlog
from ..appinfo import REPO_URL, SUPPORT_URL
from ..i18n import T
from ..paths import running_as_root
from .theme import space
from .tooltip import add_tooltip


@dataclass(frozen=True)
class Page:
    """A web page a button opens. Every field but ``url`` names a key or a style."""

    url: str
    label: str      # i18n key of the button text
    tip: str        # i18n key of its tooltip
    opened: str     # i18n key of the log line after it opened
    style: str      # ttk style (gui/theme.py)


DONATE = Page(SUPPORT_URL, "buttons.donate", "tips.donate", "log.donate_opened",
              "Donate.TButton")
GITHUB = Page(REPO_URL, "buttons.github", "tips.github", "log.github_opened",
              "GitHub.TButton")

# In PACKING order, from the edge a row packs from: the header packs from the
# right, after the settings gear, so Donate stands next to the gear and GitHub to
# its left; the About window packs from the left edge, Donate first.
PAGES = (DONATE, GITHUB)


def open_page(page, log):
    """Open ``page`` in the user's browser and say in the log whether it opened."""
    if running_as_root():
        log(f"{T('log.page_open_yourself')}: {page.url}")
        return False
    try:
        opened = webbrowser.open_new_tab(page.url)
    except Exception as e:              # the reason goes to the crash log, the address to the user
        crashlog.note(e, "gui.links")
        log(f"{T('log.page_not_opened')}: {page.url}")
        return False
    log(f"{T(page.opened if opened else 'log.page_not_opened')}: {page.url}")
    return bool(opened)


def page_button(parent, page, log):
    """One page button, with its tooltip. The caller packs it."""
    button = ttk.Button(parent, text=T(page.label), style=page.style,
                        command=lambda: open_page(page, log))
    add_tooltip(button, page.tip)
    return button


def header_buttons(header, log):
    """The header's page buttons, packed right to left after the settings gear.

    The first one stands ``apart`` from the gear: a mis-click there opens a
    browser instead of a window. Returned in packing order, for ``App._fit_header``.
    """
    return _row(header, log, "right", space("apart"))


def footer_buttons(footer, log):
    """The About window's page buttons, packed left to right from its edge."""
    return _row(footer, log, "left", 0)


def _row(parent, log, side, edge):
    """One button per page, packed from ``side``; the first ``edge`` px off it."""
    buttons = []
    for page in PAGES:
        button = page_button(parent, page, log)
        gap = space("inline") if buttons else edge
        button.pack(side=side, padx=(0, gap) if side == "right" else (gap, 0))
        buttons.append(button)
    return tuple(buttons)


def clipped(buttons):
    """True when any of ``buttons`` is cut off - or not laid out yet.

    "Does it fit" is not arithmetic (padding, fonts and DPI all get a vote), so
    the test is the widget itself: a button whose actual width is under the width
    it ASKED for has its text cut off. A width of 1 means not laid out yet - trust
    the request, not the reality.
    """
    return any(button.winfo_width() <= 1 or button.winfo_width() < button.winfo_reqwidth()
               for button in buttons)
