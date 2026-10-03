"""The message log at the bottom of the window: its queue, its cap, its widget.

Everything the App used to do to that Text box, minus the box's construction,
which stays in ``_build_ui`` because it is layout and a layout test asserts where
it hangs. What moved is the BEHAVIOUR: the thread-safe hand-off, the two caps
(the list in memory and the widget itself), and the guard that decides whether
there is anything to write to at all.

It lives here for the reason ``gui/crash.py`` gives at the top of its own
docstring: ``gui/app.py`` sits ON the size ratchet in ``tests/test_code_shape.py``,
and that guard's answer is to put code where it belongs rather than to raise the
number. This is not App logic - it is one widget's own bookkeeping.

``App.log`` / ``App.clear_log`` / ``App.log_box`` / ``App._log_lines`` all still
work and mean what they meant. Two of those are read by things outside this
package's control (``gui/crash.py`` takes the tail into every crash report, and
the GUI tests read both), so they are kept as names rather than renamed away.
"""
import queue
import threading
import time

from .. import crashlog

# Trim only past ``keep + HYSTERESIS``, so a busy session does not reslice the
# whole list on every single line once the cap is reached.
HYSTERESIS = 100


class LogView:
    """The log box, and the state that outlives it.

    ``lines`` outlives the widget on purpose: a language change destroys every
    child of the root and builds new ones, and the log is expected to still be
    there afterwards. The widget is therefore something this object is HANDED
    (``attach``), not something it owns.
    """

    def __init__(self, app):
        self.app = app
        self.box = None             # the Text widget, once _build_ui has made one
        self.lines = []             # survives a rebuild; the widget does not
        self._queue = queue.Queue()

    def attach(self, box):
        """Take the widget ``_build_ui`` just made, and restore the log into it."""
        self.box = box
        if self.lines:
            keep = self.app.pref("log_lines")
            box.config(state="normal")
            box.insert("end", "\n".join(self.lines[-keep:]) + "\n")
            box.config(state="disabled")
            box.see("end")
        # Anything logged while there was no usable widget is still in the queue,
        # and a rebuild is exactly such a window. `App.log` drains synchronously on
        # the main thread, so without this those lines wait for the next tick to
        # appear - which reads as the log having missed them.
        self.drain()

    def forget(self):
        """Start the log empty (a language change does not keep mixed languages)."""
        self.lines = []

    # -- writing ------------------------------------------------------------- #
    def log(self, msg):
        """Thread-safe entry point. Worker threads never touch widgets."""
        stamp = time.strftime("%H:%M:%S")
        self._queue.put(f"[{stamp}] {msg}")
        if threading.current_thread() is threading.main_thread():
            self.drain()

    def clear(self):
        self.lines = []
        if not self._usable():
            return
        try:
            self.box.config(state="normal")
            self.box.delete("1.0", "end")
            self.box.config(state="disabled")
        except Exception as _exc:
            crashlog.note(_exc, "gui.logview")

    def drain(self):
        """Apply queued lines to the widget, all of them in ONE write. Main thread only.

        Line by line, each one cost two state changes, an insert, an index, a
        scroll and a preference read: 13.0-13.1 ms for 50 queued lines on real
        Tk, against 1.1-1.3 ms for the same 50 written at once (2026-10-03,
        performance review W-C3). Bursts come from worker threads - a session
        starting or stopping says several things at once.
        """
        if not self._usable():
            return                  # UI not built yet; lines stay queued
        batch = []
        while True:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if batch:
            self._write_lines(batch)

    def _usable(self):
        """Is there a widget, and does it still exist?

        🔴 The second half is not paranoia. A DESTROYED Tk widget is not ``None``:
        it is the same Python object, and only its Tcl path is gone, so a guard
        written as ``if self.box is None`` passes and every call after it raises
        ``TclError``. ``_build_ui`` destroys every child of the root and the
        attribute keeps pointing at the corpse until a new widget is attached, so
        anything logged inside that window - and ``App.log`` drains synchronously
        on the main thread - went through exactly that hole.
        """
        box = self.box
        if box is None:
            return False
        try:
            return bool(box.winfo_exists())
        except Exception as _exc:       # a half-torn-down interpreter, at shutdown
            crashlog.note(_exc, "gui.logview")
            return False

    def _write_lines(self, batch):
        """A LIST of lines, in one insert, one trim, one scroll (see ``drain``).

        It was ``_append(line)``, one line, until it started taking a batch - and
        it was renamed for that, not just retyped. A ``str`` is iterable, so an old
        one-line caller handed to a list-taking method does not fail: it writes
        the line one CHARACTER per line, which is what a test calling the old name
        did on the first push of performance review R-4. Under a new name such a
        caller stops at an AttributeError instead.
        """
        keep = self.app.pref("log_lines")
        self.lines.extend(batch)
        if len(self.lines) > keep + HYSTERESIS:
            self.lines = self.lines[-keep:]
        self.box.config(state="normal")
        self.box.insert("end", "\n".join(batch) + "\n")
        try:            # keep the widget bounded too, not just the in-memory list
            count = int(self.box.index("end-1c").split(".")[0])
            if count > keep + HYSTERESIS:
                self.box.delete("1.0", f"{count - keep}.0")
        except Exception as _exc:
            crashlog.note(_exc, "gui.logview")
        self.box.see("end")
        self.box.config(state="disabled")
