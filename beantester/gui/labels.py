"""Labels that wrap to the width they actually get.

A ttk.Label does not wrap unless it is told a ``wraplength`` **in pixels**, and
a pixel number decided at build time is wrong the moment the window is resized
(or the DPI differs, or the translation is longer than the English original).
A long note then does not wrap - it is simply CUT at the frame edge, which is
exactly what happened to the "these are all captured connections" note.

``wrapping_label`` binds the wraplength to the real width of its container.
"""
from tkinter import ttk

from .scaling import scaled
from .tooltip import retip
from ..i18n import T
from .. import crashlog


def bind_wraplength(label, container=None, pad=16):
    """Keep ``label``'s wraplength equal to the width of ``container``."""
    holder = container if container is not None else label.master

    def _resize(event=None):
        try:
            # The binding lives on the CONTAINER, and the container routinely
            # outlives the label: App._build_ui() destroys the labels on every
            # rebuild while the root window they hang off stays. Nothing unbinds
            # this (it is added with add="+", and unbinding by funcid still clears
            # the whole sequence on the oldest Python in the CI matrix), so a dead
            # label is not an edge case here - it is the steady state after the
            # first language switch. Without this check every resize afterwards
            # raised TclError("invalid command name") into the crash log, once per
            # dead label, forever.
            if not label.winfo_exists():
                return
            width = int(getattr(event, "width", 0) or holder.winfo_width() or 0)
            if width > scaled(80):
                label.config(wraplength=max(scaled(80), width - scaled(pad)))
        except Exception as _exc:
            crashlog.note(_exc, "gui.labels")

    try:
        holder.bind("<Configure>", _resize, add="+")
    except Exception as _exc:
        crashlog.note(_exc, "gui.labels")
    _resize()
    return label


def wrapping_label(parent, text="", style="Muted.TLabel", pad=16, **kw):
    """A label that wraps instead of being clipped."""
    label = ttk.Label(parent, text=text, style=style, justify="left",
                      anchor="w", wraplength=scaled(600), **kw)
    bind_wraplength(label, parent, pad)
    return label


def sync_note(owner, notes, tips, state, subsystem, attr="_scope_note"):
    """Re-word a note built by ``wrapping_label`` - and its bubble - on a new state.

    Both scope notes on the Statistics and Connections pages were this, written
    twice: the same nine lines, differing only in which i18n maps they read and
    which subsystem they record under. Structurally identical code in two files is
    code that gets FIXED in one of them, and this pair has the scar - the tooltip
    used to be bound once and never touched again, so re-wording the note left the
    bubble underneath still explaining the other state, and that was repaired on
    each page separately.

    The state comparison is what makes it cheap enough to call from a refresh that
    runs several times a second: a state that has not moved does no widget work at
    all. ``crashlog.quiet`` rather than a bare guard because the note may already
    be destroyed - a language switch rebuilds the page under a refresh that is
    already in flight, which is the ordinary case here and not an edge one.
    """
    note = getattr(owner, attr, None)
    if note is None:
        return
    seen = attr + "_state"
    if state == getattr(owner, seen, None):
        return
    setattr(owner, seen, state)
    with crashlog.quiet(subsystem):
        note.config(text=T(notes[state]))
        retip(note, tips[state])
