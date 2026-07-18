"""BeanNetworkTester - launcher and backward-compatible facade.

The implementation lives in the ``beantester`` package; this module keeps the
historical entry point (``python bean_network_tester.py``) and re-exports the
public API so existing imports, docs and PyInstaller commands keep working.

    GUI (as administrator):  python bean_network_tester.py
    CLI example:             python bean_network_tester.py --simulate --loss 10
"""
import sys

from beantester import *          # noqa: F401,F403  (engine/CLI public API)
from beantester import main


# The GUI (tkinter) is resolved LAZILY, mirroring beantester.gui.__init__: merely
# importing this launcher must NOT drag in tkinter or the whole gui/ package. The
# GUI-launch path pays a UAC double-process (asInvoker + elevate_self, convention
# 19) and the doomed pre-elevation process used to import all of gui/ - and Tk -
# for nothing, only to relaunch and import it again. Backward compatibility is
# kept (docs/scripts doing ``from bean_network_tester import App``): the names
# still resolve, they are just imported on first access, not at module load.
def __getattr__(name):
    if name in ("App", "Tooltip", "add_tooltip", "make_bean_icon"):
        from beantester import gui
        return getattr(gui, name)
    if name == "_HAS_TK":
        try:
            from beantester import gui
            gui.App                    # force the tkinter-backed import to run
            return True
        except Exception:
            return False
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    sys.exit(main())
