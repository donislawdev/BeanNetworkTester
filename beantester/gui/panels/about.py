"""The "About" window: who wrote this, what version it is, and what it is built on.

This is not decoration. Two of the things it shows are obligations, not niceties:

* **The third-party notice.** WinDivert and PyDivert are used under the LGPLv3,
  which requires the user of the BINARY to be told that those libraries are in
  there, under which licence, and where their source lives. A file in a repository
  the user never sees does not discharge that; a window in the program they are
  actually holding does. (``BeanNetworkTester.exe --license`` prints the same thing
  for people who prefer a shell, and for licence audits, which are usually scripts.)
* **"Sends no data anywhere".** The tool captures the user's network traffic. The
  first question a security-minded tester or an IT department asks is where that
  goes. The answer is "nowhere", and the answer belongs where they are looking.

The donate button is here as well as in the header - deliberately. Being in two
places is not clutter for a voluntary ask that funds the work; being nowhere near
the "who made this" screen would be strange.
"""
from functools import partial
import tkinter as tk
from tkinter import ttk
import webbrowser

from ... import crashlog, legal
from ...appinfo import (APP_NAME, AUTHOR, COPYRIGHT, LICENSE_NAME, SUPPORT_URL,
                        __version__)
from ...i18n import T
from ..labels import wrapping_label
from ..scaling import scaled
from ..theme import FIELD, FG, MONO_FONT, MUT
from ..tooltip import add_tooltip
from ..windows import PanelWindow, register_window


@register_window
class AboutWindow(PanelWindow):
    """Version, author, licence and the components we ship."""

    ID = "about"
    TITLE = "windows.about"
    SIZE = (640, 520)

    def build(self, body):
        pad = scaled(12)

        head = ttk.Frame(body)
        head.pack(side="top", fill="x", padx=pad, pady=(pad, scaled(4)))
        ttk.Label(head, text=APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(head, text=T("about.version", version=__version__),
                  style="Muted.TLabel").pack(side="left", padx=(scaled(10), 0),
                                             anchor="s", pady=(0, scaled(3)))

        # Every line here is PROSE, and prose in a translation is longer than the
        # English it was written from - the licence sentence and the privacy line
        # both ran off the right edge and were simply cut. A plain ttk.Label never
        # wraps; wrapping_label ties its wraplength to the window (see gui/labels.py).
        # The pad allows for the padx below on BOTH sides, plus the few pixels a
        # wrapped ttk.Label asks for on top of its wraplength (measured, not
        # guessed: at pad=30 the widest wrapped line still overhung by 12 px).
        line = partial(wrapping_label, body, pad=2 * 12 + 16)
        line(text=T("about.author", author=AUTHOR), style="TLabel").pack(
            side="top", fill="x", anchor="w", padx=pad)
        line(text=COPYRIGHT, style="Muted.TLabel").pack(
            side="top", fill="x", anchor="w", padx=pad, pady=(0, scaled(8)))

        line(text=T("about.license", license=LICENSE_NAME), style="TLabel").pack(
            side="top", fill="x", anchor="w", padx=pad)
        line(text=T("about.license_terms"), style="Muted.TLabel").pack(
            side="top", fill="x", anchor="w", padx=pad, pady=(0, scaled(8)))

        # The privacy line is the one people came here to read.
        line(text=T("about.no_telemetry"), style="Good.TLabel").pack(
            side="top", fill="x", anchor="w", padx=pad, pady=(0, scaled(10)))

        line(text=T("about.third_party"), style="TLabel").pack(
            side="top", fill="x", anchor="w", padx=pad)

        # A read-only text box, not a table: this is prose plus links, and it has
        # to be selectable so someone can copy a URL into a browser or a ticket.
        wrap = ttk.Frame(body)
        wrap.pack(side="top", fill="both", expand=True, padx=pad, pady=(scaled(4), 0))
        bar = ttk.Scrollbar(wrap, orient="vertical")
        bar.pack(side="right", fill="y")
        text = tk.Text(wrap, height=8, font=(MONO_FONT, 9), bg=FIELD, fg=MUT,
                       insertbackground=FG, relief="flat", borderwidth=0,
                       highlightthickness=0, wrap="none", yscrollcommand=bar.set)
        text.pack(side="left", fill="both", expand=True)
        bar.config(command=text.yview)
        for name, version, licence, url in legal.component_rows():
            text.insert("end", "%-26s %-10s %s\n%-26s %-10s %s\n"
                        % (name, version, licence, "", "", url))
        text.insert("end", "\n" + T("about.licenses_dir", path=legal.licenses_dir()) + "\n")
        text.config(state="disabled")

        foot = ttk.Frame(body)
        foot.pack(side="bottom", fill="x", padx=pad, pady=pad)
        donate = ttk.Button(foot, text=T("buttons.donate"), style="Donate.TButton",
                            command=self._donate)
        donate.pack(side="left")
        add_tooltip(donate, "tips.donate")
        ttk.Button(foot, text=T("buttons.close"), command=self.close).pack(side="right")

    def _donate(self):
        """Open the support page in the user's browser - the app opens no sockets."""
        with crashlog.quiet("gui.about"):
            webbrowser.open_new_tab(SUPPORT_URL)
            self.app.log(f"{T('log.donate_opened')}: {SUPPORT_URL}")
