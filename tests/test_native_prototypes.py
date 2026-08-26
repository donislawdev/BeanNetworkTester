"""Every native call this package makes must declare what it actually takes.

The bug behind this guard was a hard interpreter crash on the Windows CI:

    Windows fatal exception: access violation
      driver.service_state -> installed_drivers -> cleanup_driver -> release_on_exit

Its cause was ctypes calling advapi32 with default (32-bit int) prototypes on
64-bit Windows, which truncated the pointer-sized service-control HANDLEs and
made QueryServiceStatus write through a garbage pointer. ``driver._advapi`` was
fixed then, and ``tests/test_driver_windows.py`` names its six functions one by
one - which guards THOSE SIX and nothing else. ``gui/theme.py`` was calling
user32 and dwmapi with no prototypes at all for just as long, and nothing said so.

So this file guards the RULE instead of the examples, in two directions:

1. **every function a binding factory declared carries argtypes**, read off the
   factory itself, so a function ADDED to one without a prototype goes red without
   anybody remembering that this test exists - plus, by name, the ones whose
   RESULT must be pointer-sized (see POINTER_SIZED_RESULTS for why that half
   cannot be generic, and for the vacuous assertion it replaces);
2. **no NEW direct ``ctypes.windll.lib.Func(...)`` call appears** outside the
   sites that already existed. That is what forces the next one into a factory,
   rather than repeating the history above in a third module.

What the second check is NOT: a claim that the eleven allowed sites are wrong.
They were read (2026-08-05) and every one of them passes only ints, strings or
an explicit ``byref``/``c_void_p`` - ctypes marshals those correctly without a
prototype - and returns a BOOL or a small int. They are listed rather than fixed
because a list that names its exceptions is honest, and a guard that fires on
them would simply be switched off.
"""
import ast
import os
import re

from beantester import driver, winenv
from fakes import ROOT, check

# Factories that hand out a prepared binding. `driver._advapi` is here as well as
# in test_driver_windows.py on purpose: that test asserts one specific restype is
# a HANDLE (the actual historical bug), this one asserts the general property.
FACTORIES = dict(winenv.NATIVE_FACTORIES, advapi32=driver._advapi)

# The three do NOT fail the same way off Windows, and assuming they did is what
# made the first version of this file red on the Linux runner and green here:
# `winenv.user32` / `winenv.dwmapi` check `is_windows()` and return None, while
# `driver._advapi` goes straight to `ctypes.WinDLL` and raises AttributeError.
# That is not a defect - every caller of `_advapi` is behind an `is_windows()`
# guard of its own, which `test_driver_windows.py` asserts - but it means the
# off-Windows branch here has to check the right property per factory instead of
# one property for all three.
SELF_GUARDING = tuple(winenv.NATIVE_FACTORIES)

# Direct `ctypes.windll.<lib>.<Func>` uses that predate this guard, with the
# reason each is harmless. Adding a line here is a decision, not a formality:
# the question to answer is "does this call pass a pointer or receive a handle?".
ALLOWED_DIRECT = {
    "shell32.IsUserAnAdmin",              # no arguments, BOOL result
    "shell32.ShellExecuteW",              # strings and ints; result compared with > 32
    "kernel32.QueryPerformanceFrequency",  # explicit byref: ctypes passes a real pointer
    "kernel32.QueryPerformanceCounter",   # explicit byref
    "kernel32.FreeConsole",               # no arguments, BOOL result
    "user32.SetProcessDpiAwarenessContext",  # explicit c_void_p, so pointer-sized already
    "user32.SetProcessDPIAware",          # no arguments, BOOL result
    "shcore.SetProcessDpiAwareness",      # one int argument, HRESULT result
}

# Matches `ctypes.windll.user32.Foo` AND a bare `windll.user32.Foo` (the form you
# get from `from ctypes import windll`), because the first draft matched only the
# fully qualified one and a mutation walked straight past it.
#
# What it still does NOT catch, said out loud rather than left to be discovered:
# an ALIASED import (`import ctypes as _c; _c.windll...`) escapes, and so does a
# binding built with `ctypes.WinDLL("user32")` by hand. The first is not a shape
# anybody writes by accident; the second is how `portmap.py` legitimately builds
# its iphlpapi and kernel32 bindings, WITH full prototypes, so banning it here
# would fire on correct code. Neither gap is closed by making the regex cleverer -
# closing them means a real import-graph check, and that is a different guard.
_DIRECT = re.compile(r"\bwindll\.(\w+)\.(\w+)")

# Functions whose RESULT is pointer-sized. This has to be stated rather than
# derived, and the reason is the trap this file nearly shipped: ``restype``
# cannot be checked generically at all.
#
# ctypes defaults ``restype`` to ``c_long``, never to None, and on Windows
# ``c_long is c_int is wintypes.BOOL``. So "declares a restype" is a sentence that
# can never be false, and a function returning a truncated HANDLE is
# indistinguishable from one correctly declared to return a BOOL. (That exact
# vacuous assertion sat in ``test_driver_windows.py`` from the day the access
# violation was fixed - the one line beside it that could fail is the one naming
# OpenSCManagerW's restype.) ``argtypes`` DOES default to None, so that half is
# checked generically below; the width of a result is checked here, by name.
POINTER_SIZED_RESULTS = {
    "user32": ("GetParent", "GetWindowLongPtrW", "SetWindowLongPtrW",
               "MonitorFromPoint"),
    "advapi32": ("OpenSCManagerW", "OpenServiceW"),
}


def _package_sources():
    for base, dirs, files in os.walk(os.path.join(ROOT, "beantester")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if name.endswith(".py"):
                path = os.path.join(base, name)
                rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                with open(path, encoding="utf-8") as handle:
                    yield rel, handle.read()


def test_every_declared_native_function_has_a_full_prototype():
    """Read the FACTORY, not a list of names somebody wrote down.

    ``ctypes`` caches each function it hands out on the library object, so walking
    the object is walking exactly what the factory prepared - and also anything
    else that has been fetched off the same binding without declaring itself.
    """
    import ctypes

    if not hasattr(ctypes, "windll"):
        # Not Windows. See SELF_GUARDING for why this is two checks and not one.
        for name in SELF_GUARDING:
            check(f"{name} degrades to None off Windows", FACTORIES[name]() is None)
        check("the advapi32 binding is guarded by its CALLERS instead",
              driver.service_state("WinDivert") is None)
        return

    pointer = ctypes.sizeof(ctypes.c_void_p)
    checked = 0
    for name, factory in FACTORIES.items():           # pragma: no cover - Windows only
        lib = factory()
        check(f"{name} could be loaded", lib is not None)
        for attribute, value in vars(lib).items():
            if not isinstance(value, ctypes._CFuncPtr):
                continue
            checked += 1
            # The only half that can fail: argtypes really does default to None.
            check(f"{name}.{attribute} declares argtypes", value.argtypes is not None,
                  "without it ctypes passes every argument as a 32-bit int")
            if attribute in POINTER_SIZED_RESULTS.get(name, ()):
                check(f"{name}.{attribute} returns a pointer-sized result",
                      ctypes.sizeof(value.restype) >= pointer,
                      f"({value.restype}) - a truncated handle is the historical crash")
    # The canary this project puts on every scan: a walk that finds nothing
    # satisfies every assertion above perfectly.
    check("the walk actually found native functions", checked >= 10, f"({checked})")


def test_the_monitor_lookup_answers_a_usable_rectangle():
    """The prototypes above are only half of it - this CALLS through them.

    ``monitor_work_area`` is what stops the GUI from clamping windows and tooltip
    bubbles onto the primary monitor (see its docstring). A prototype guard cannot
    tell whether the struct is laid out correctly, because a wrong layout returns
    numbers rather than raising: it just returns the WRONG numbers, and the only
    cheap way to notice is to insist the answer is a usable rectangle of plain
    Python ints.

    On a single-monitor machine this cannot prove the multi-monitor case. What it
    does prove is the part that would break for everyone: the call works, the
    fields land where we said they do, and a point that is on NO monitor still
    gets an answer instead of None - the case a window dragged past the edge of
    the desktop produces.
    """
    area = winenv.monitor_work_area(10, 10)
    if not winenv.is_windows():
        check("monitor_work_area degrades to None off Windows", area is None, f"({area})")
        return
    check("the monitor lookup answers at all", area is not None)     # pragma: no cover
    check("it is four plain ints",                                   # pragma: no cover
          isinstance(area, tuple) and len(area) == 4
          and all(isinstance(edge, int) for edge in area), f"({area})")
    left, top, right, bottom = area                                  # pragma: no cover
    check("the work area is a real rectangle, not an empty one",     # pragma: no cover
          right - left >= 640 and bottom - top >= 480,
          f"({area}) - a mislaid struct field reads as garbage, not as an error")
    far = winenv.monitor_work_area(1 << 20, 1 << 20)                 # pragma: no cover
    check("a point on no monitor still gets the nearest one",        # pragma: no cover
          far is not None and far[2] > far[0], f"({far})")


def test_the_pointer_sized_table_still_matches_the_factories():
    """A name in POINTER_SIZED_RESULTS that no factory declares checks nothing.

    Exactly the stale-mutation-pattern problem one layer down: the entry costs
    nothing, reads as coverage, and the day the function is renamed it silently
    stops being a guard rather than going red.
    """
    import ctypes

    if not hasattr(ctypes, "windll"):
        check("nothing to match off Windows", True)
        return
    for name, wanted in POINTER_SIZED_RESULTS.items():   # pragma: no cover - Windows
        lib = FACTORIES[name]()
        missing = [fn for fn in wanted if not isinstance(
            vars(lib).get(fn), ctypes._CFuncPtr)]
        check(f"{name}: every pointer-sized name is really declared", not missing,
              f"{missing}")


def test_a_style_reading_call_is_not_left_to_ctypes_defaults():
    """The one prototype whose absence was MEASURED to change a value.

    2026-08-05, on this machine: ``GetWindowLongPtrW(GWL_STYLE)`` read a WS_POPUP
    window's style as NEGATIVE under ctypes' default signed 32-bit restype
    (0x94cc0008 for a transient dialog, 0x96000008 for the tooltip bubble), while
    the root window and a withdrawn Toplevel - the only two shapes
    ``theme.disable_maximize`` is called on today - came back identical either way.
    Reachable, not currently reached; one transient non-resizable window would end
    that, so the size of the result is pinned here rather than left to luck.
    """
    import ctypes

    lib = winenv.user32()
    if lib is None:
        check("user32 is None off Windows", True)
        return
    getter = getattr(lib, "GetWindowLongPtrW", None) or lib.GetWindowLongW
    setter = getattr(lib, "SetWindowLongPtrW", None) or lib.SetWindowLongW
    check("a window style is read at pointer width, not as a 32-bit int",
          ctypes.sizeof(getter.restype) >= ctypes.sizeof(ctypes.c_void_p),
          f"({getter.restype})")
    check("and written back at the same width",
          ctypes.sizeof(setter.argtypes[-1]) >= ctypes.sizeof(ctypes.c_void_p),
          f"({setter.argtypes})")


def test_no_new_native_call_bypasses_a_prototype():
    """A call written inline gets ctypes' defaults, which is how this started.

    The check is on the SHAPE (`ctypes.windll.lib.Func`), so it does not care where
    in the package the next one appears - which is the difference between guarding
    a rule and guarding the two modules somebody happened to look at.
    """
    found = {}
    for rel, source in _package_sources():
        for match in _DIRECT.finditer(source):
            symbol = f"{match.group(1)}.{match.group(2)}"
            if symbol not in ALLOWED_DIRECT:
                line = source[:match.start()].count("\n") + 1
                found.setdefault(symbol, []).append(f"{rel}:{line}")
    check("no native call is made without a declared prototype "
          "(put it in a winenv factory instead)", not found, f"{found}")


def test_the_allowlist_does_not_outlive_its_call_sites():
    """A name left here after its call site is gone reads as a live exception.

    Same failure mode as a stale mutation pattern: the entry costs nothing, says
    something false about the code, and nothing else would ever notice.
    """
    present = set()
    for _rel, source in _package_sources():
        present.update(f"{m.group(1)}.{m.group(2)}" for m in _DIRECT.finditer(source))
    stale = sorted(ALLOWED_DIRECT - present)
    check("every allowlisted direct call still exists", not stale, f"{stale}")


def test_the_scan_would_actually_see_a_violation():
    """The canary. A regex that matches nothing passes both checks above."""
    for sample in ("x = ctypes.windll.user32.SomethingNobodyDeclared(handle)\n",
                   "from ctypes import windll\ny = windll.user32.SomethingNobodyDeclared(h)\n"):
        matches = [f"{m.group(1)}.{m.group(2)}" for m in _DIRECT.finditer(sample)]
        check("the scan recognises a direct call",
              matches == ["user32.SomethingNobodyDeclared"], f"{matches} in {sample!r}")
    check("the package really was read",
          sum(1 for _rel, _src in _package_sources()) >= 30)


def test_the_theme_no_longer_calls_windows_without_a_prototype():
    """The module this chunk was about, named so the fix cannot quietly come back.

    ``gui/theme.py`` used ``ctypes.windll`` directly in two of its three native
    functions while the third declared its prototypes properly - which is what a
    rule enforced by nothing looks like after a while.
    """
    source = dict(_package_sources())["beantester/gui/theme.py"]
    check("gui/theme.py makes no direct ctypes.windll call",
          not _DIRECT.search(source))
    tree = ast.parse(source)
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    check("it goes through the winenv factories instead",
          {"user32", "dwmapi"} <= names, f"({sorted(names & {'user32', 'dwmapi'})})")
