"""Mouse-wheel delta normalisation (pure, no tkinter - so it is unit-tested).

Windows reports multiples of 120 (but precision touchpads send less), macOS
reports small integers, X11 uses Button-4/5 instead of a delta. The old code did
``int(-1 * (delta / 120))``, which is exactly 0 for every delta below 120 - one
of the reasons the wheel appeared dead.
"""
MAX_NOTCHES = 5           # clamp absurd deltas (kinetic scrolling, some drivers)
UNITS_PER_NOTCH = 3       # 3 * yscrollincrement ~= the Windows "3 lines" default


def wheel_units(delta=0, platform="win32", num=None):
    """Normalise a wheel event into scroll units (negative = up, 0 = nothing)."""
    if num in (4, 5):
        return -UNITS_PER_NOTCH if num == 4 else UNITS_PER_NOTCH
    try:
        delta = int(delta or 0)
    except (TypeError, ValueError):
        return 0
    if delta == 0:
        return 0
    if str(platform).startswith("darwin"):
        notches = abs(delta)                       # Tk already reports notches
    else:
        notches = int(round(abs(delta) / 120.0))   # Windows: WHEEL_DELTA = 120
    notches = max(1, min(MAX_NOTCHES, notches))    # sub-120 deltas still scroll once
    units = notches * UNITS_PER_NOTCH
    return -units if delta > 0 else units
