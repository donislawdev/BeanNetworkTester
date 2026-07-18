"""tkinter GUI for BeanNetworkTester.

Imports are lazy (PEP 562): pulling in ``beantester.gui.scaling`` or
``beantester.gui.wheel`` - both tkinter-free - must not drag tkinter into the
process, otherwise the pure GUI helpers could not be unit-tested headlessly.
"""
__all__ = ["App", "Tooltip", "add_tooltip", "make_bean_icon"]


def __getattr__(name):
    if name == "App":
        from .app import App
        return App
    if name in ("Tooltip", "add_tooltip"):
        from . import tooltip
        return getattr(tooltip, name)
    if name == "make_bean_icon":
        from .icon import make_bean_icon
        return make_bean_icon
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
