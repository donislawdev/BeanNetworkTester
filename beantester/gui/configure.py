"""Configure a widget with only the options that would actually change it.

A Tk ``configure`` is not free when it changes nothing: a ttk widget lays itself
out again and schedules a redraw on every call, whatever the value. MEASURED
2026-10-03 on real Tk (Win11, CPython 3.14.7, performance review W-C2 / W-C4):
writing the same text again into the 22 counters of Statistics > Live cost
3.7-4.0 ms a tick, and one keystroke in the Control form 1.63 ms (averaged over
its 12 sections) - nearly all of it options set to the value they already held.
Read back first and skipped when equal: 0.016-0.019 ms for the counters, 0.08 ms
for the keystroke.

The comparison asks the WIDGET (``cget``), not a memory of what was last written.
A language switch or a layout change builds new widgets, and a cache would have
to be told about every one of those paths; the widget simply knows.

``state`` on a ttk widget is checked twice, because ttk records "disabled" twice:
in the ``-state`` option and in the widget's state flags. ``widget.state(
["!disabled"])`` clears the flag and leaves the option saying "disabled", so the
option alone can name a state the widget no longer shows - and skipping on it
would leave the widget enabled. ``configure(state=...)`` sets both, so asking
both before skipping it is what keeps this exactly as good as configuring.
"""


def configure_changed(widget, **options):
    """``widget.configure(**options)`` with the options that already hold left out.

    True when something was configured. Raises whatever ``cget``/``configure``
    raise (a destroyed widget is a ``TclError``), so callers keep the handling
    they had around ``configure``.
    """
    changed = {name: value for name, value in options.items()
               if not _holds(widget, name, value)}
    if changed:
        widget.configure(**changed)
    return bool(changed)


def _holds(widget, name, value):
    """Does ``widget`` already show ``name=value``? (see the module docstring)"""
    # str() on both sides: Tk answers `state` and `wraplength` with a Tcl object,
    # whose str() is the value, and the callers pass plain strings and numbers.
    if str(widget.cget(name)) != str(value):
        return False
    if name != "state" or not hasattr(widget, "instate"):
        return True
    return bool(widget.instate(["disabled"])) == (str(value) == "disabled")
