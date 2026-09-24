"""The logic behind the Tools tab - one module per tool, and no tkinter anywhere.

Why it is its own package rather than code inside each panel
------------------------------------------------------------
* **One reader of each fact.** A tool's answer is computed here and only DRAWN in
  ``gui/toolbox/``. If a command-line form ever comes (a ``--tool`` flag was costed
  in the analysis of this tab), it calls the same functions - the way ``--doctor``
  and a future GUI diagnostics tool both read ``driver.doctor()``.
* **Tests without a window.** Everything here returns plain data (``NamedTuple``),
  so it is tested on Linux CI without the fake tkinter.

The contract every module here keeps
------------------------------------
* No ``tkinter``, no ``gui``, no ``engine``, no ``cli`` - enforced by
  ``tests/test_layering.py``.
* Returns DATA and i18n KEYS, never a sentence it translated itself (the shape of
  ``driver.OPEN_ERROR_HINTS``). The one named exception is a message that arrives
  already translated from a lower layer - the expression parser raises its errors
  as sentences (``matchers._err``) - which is passed through as data.
* A platform API sits behind an object the tests can replace, like
  ``portmap._Native``.
"""


class Refused(Exception):
    """What was asked cannot be run as asked: an answer for the person, not a fault.

    ``user_key`` and ``user_args`` say why in the window's language
    (``gui/toolbox/base.py`` shows them). Raised on the worker when only the worker
    can tell - listing the ports an expression names takes up to 100 ms, too long
    for the UI thread. Kept out of the crash log: that file is for the program's
    faults, and "1001 ports, 1000 at most" is not one.
    """

    def __init__(self, user_key, **user_args):
        super().__init__(user_key)
        self.user_key = user_key
        self.user_args = user_args
