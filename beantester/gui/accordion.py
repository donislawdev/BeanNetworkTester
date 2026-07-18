"""Collapsible section (accordion panel) used by the Control page.

The panel body is a *card* (a lighter surface than the page) so the sections
read as separate groups again - a bare header over a bare frame lost the visual
grouping the old LabelFrames gave.
"""
from tkinter import ttk

from .scaling import scaled

OPEN_GLYPH = "\u25be"       # down triangle
CLOSED_GLYPH = "\u25b8"     # right triangle


class CollapsibleSection:
    """A titled panel that folds away. Put content into ``.body``."""

    def __init__(self, parent, title, is_open=True, on_toggle=None):
        self.title = title
        self.on_toggle = on_toggle
        self._open = bool(is_open)

        self.frame = ttk.Frame(parent)
        self.header = ttk.Button(self.frame, style="Section.TButton",
                                 command=self.toggle)
        self.header.pack(fill="x")
        self.body = ttk.Frame(self.frame, style="Card.TFrame",
                              padding=(scaled(10), scaled(7)))
        self._render_header()
        if self._open:
            self._show_body()

    def _show_body(self):
        self.body.pack(fill="x", padx=scaled(2), pady=(0, scaled(1)))

    def _render_header(self):
        glyph = OPEN_GLYPH if self._open else CLOSED_GLYPH
        self.header.config(text=f"{glyph}  {self.title}")

    @property
    def is_open(self):
        return self._open

    def set_open(self, value):
        value = bool(value)
        self._open = value
        self._render_header()
        if value:
            self._show_body()
        else:
            self.body.pack_forget()

    def toggle(self):
        self.set_open(not self._open)
        if self.on_toggle:
            self.on_toggle(self)

    def pack(self, **kw):
        kw.setdefault("fill", "x")
        kw.setdefault("pady", (scaled(1), scaled(3)))
        self.frame.pack(**kw)
        return self.frame

