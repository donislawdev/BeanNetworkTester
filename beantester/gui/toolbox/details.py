"""The details table under a tool's list: what its cells say, and its row menu.

The adapters tool brought it (T-4: item / value / note, ``nettools.adapters.Detail``),
its proxy row reused it, and TCP health has the same table under its own list - so
the words and the menu live here once, and a tool says only what is its own: the
log line "Limit to this IP address" writes.
"""
import tkinter as tk

from ... import crashlog
from ...i18n import T
from ...nettools.adapters import Words
from ..clipboard import copy_confirmed
from ..field_actions import fill_field
from ..theme import set_menu_entry_available, style_menu


def say(part):
    """A cell's text: ``Words`` in the window's language, anything else as it is."""
    if isinstance(part, Words):
        return T(part.key, code=part.code)
    return "" if part is None else str(part)


def render_detail(detail):
    return (say(detail.item), say(detail.value), ", ".join(say(w) for w in detail.note))


def popup(menu, allowed, x_root, y_root, area):
    """Open ``menu`` at the pointer, each entry in ``allowed`` (index -> bool) live
    or greyed out, and let the pointer go again however it ends."""
    for index, available in allowed.items():
        with crashlog.quiet(area):
            set_menu_entry_available(menu, index, available)
    try:
        menu.tk_popup(x_root, y_root)
    finally:
        with crashlog.quiet(area):
            menu.grab_release()


class DetailsMenu:
    """"Copy value" and "Limit to this IP address" on a details table's row."""

    COPY_VALUE, LIMIT = 0, 1

    def __init__(self, app, parent, table, limited_key, area):
        self.app, self.table, self.limited_key, self.area = app, table, limited_key, area
        self.menu = style_menu(tk.Menu(parent, tearoff=0))
        self.menu.add_command(label=T("menu.copy_value"), command=self.copy_value)
        self.menu.add_command(label=T("tools.adapters.limit"), command=self.limit)
        table.bind_row_menu(self.show)

    def selected(self):
        keys = self.table.selected_keys()
        return self.table.item_for_key(keys[0]) if keys else None

    def show(self, x_root, y_root):
        detail = self.selected()
        popup(self.menu, {self.COPY_VALUE: bool(detail and say(detail.value)),
                          self.LIMIT: bool(detail and detail.address)},
              x_root, y_root, self.area)

    def copy_value(self):
        detail = self.selected()
        text = say(detail.value) if detail else ""
        if text:
            copy_confirmed(self.app, text, text, self.area)

    def limit(self):
        """The row's address into the Control page's destination field - the address
        only: the port the person set there stays (the owner's decision, 2026-10-13;
        ``set_destination`` would have emptied it)."""
        detail = self.selected()
        if detail and detail.address:
            fill_field(self.app, "dst_ip", detail.address, self.limited_key)
