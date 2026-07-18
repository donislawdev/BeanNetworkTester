"""Secondary windows (Toplevels), one module each.

Importing this package REGISTERS every window in it: a window is one entry, and
``App.open_window(id)`` is the only way one is ever constructed. See
``gui/windows.py`` for what a window gets for free, and ``event_log.py`` for a
worked example meant to be copied.
"""
from . import about                # noqa: F401  (imported for its @register_window)
from . import event_log            # noqa: F401  (imported for its @register_window)
from . import settings             # noqa: F401  (imported for its @register_window)

__all__ = ["about", "event_log", "settings"]
