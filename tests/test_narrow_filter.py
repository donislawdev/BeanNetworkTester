"""Narrowing the DRIVER's filter to the destination, and the traps around it.

The win: with a destination target set the tool receives every packet on the
machine and hands almost all of them straight back. Measured 2026-07-28 against a
real capture, 1944 packets diverted and 0 of them impairable. The WinDivert
filter runs in the driver, so a fragment pushed into it is traffic that never
arrives here.

Everything in this file guards the ways that can go WRONG, because the failure
mode is silent: a driver filter narrower than the matcher means traffic the user
asked to impair simply never shows up, and every counter reads healthy.
"""
from beantester import filters
from beantester.engine import BeanEngine
from beantester.matchers import KIND_INT, KIND_IP, PORT_BOUNDS, parse_matcher
from beantester.settings import DEFAULT_SETTINGS, apply_settings
from fakes import FakeDivert, check

BASE = filters.windivert_for("both")


def _m(text, kind):
    bounds = PORT_BOUNDS if kind == KIND_INT else None
    return parse_matcher(text, kind, bounds=bounds) if text else None


def test_it_narrows_only_what_it_can_prove():
    """A fragment is used only when the driver's own parser accepts it.

    ``filter_compiles`` asks ``WinDivertHelperCompileFilter`` - the driver's
    parser, not a guess at its grammar - and answers False when it cannot be
    asked at all (no pydivert, not Windows). False then means "keep the wide
    filter", which is the safe direction: over-capturing costs throughput,
    under-capturing costs correctness.
    """
    text, narrowed = filters.narrowed_filter(BASE, _m("8.8.8.8", KIND_IP),
                                             _m("53", KIND_INT))
    if filters.filter_compiles(BASE):        # i.e. pydivert is available here
        check("a plain ip+port destination narrows", narrowed, text)
        check("the base filter is still in there", BASE in text, text)
    else:
        check("without a driver to ask, nothing is narrowed", not narrowed, text)

    for ip, port in (("", ""), ("re:^8", ""), ("1.1.*", ""), ("!8.8.8.8", "")):
        text, narrowed = filters.narrowed_filter(BASE, _m(ip, KIND_IP),
                                                 _m(port, KIND_INT))
        check("%r/%r cannot narrow" % (ip, port), not narrowed, text)
        check("%r/%r leaves the base untouched" % (ip, port), text == BASE, text)


def test_a_fragment_the_driver_refuses_falls_back_instead_of_being_used():
    """The driver's grammar has a LENGTH limit, and a plausible expression hits it.

    ``windivert_fragment`` will happily emit a fragment for a hundred-port list -
    it is a perfectly valid expression - but the driver's parser rejects it.
    Measured on this machine: 50 ports (4 698 chars) compile, 100 ports (9 398)
    do not. Without the compile check the tool would hand WinDivert a filter it
    cannot parse, and opening the handle would fail at the worst moment: on START,
    after the user has set everything up.

    This is the case that makes ``filter_compiles`` load-bearing rather than
    belt-and-braces, and it was found by a mutant surviving - nothing else in this
    file produced a fragment the driver would refuse.
    """
    if not filters.filter_compiles(BASE):
        return                                # nothing to ask; see the first test
    big = ",".join(str(1000 + i) for i in range(100))
    matcher = _m(big, KIND_INT)
    from beantester.matchers import windivert_fragment
    check("the fragment itself is produced", windivert_fragment(matcher) is not None)
    check("but the driver refuses it",
          not filters.filter_compiles(windivert_fragment(matcher)))
    text, narrowed = filters.narrowed_filter(BASE, None, matcher)
    check("so nothing is narrowed", not narrowed, str(narrowed))
    check("and the base filter is handed over untouched", text == BASE, text)


def test_one_unprovable_half_still_lets_the_other_half_narrow():
    """A wildcard IP with a plain port must still narrow on the port.

    Dropping a conjunct makes the filter WIDER, and wider is always safe. Giving
    up on both because one could not be expressed would throw away the win for no
    reason.
    """
    if not filters.filter_compiles(BASE):
        return                                # no driver to ask; covered above
    text, narrowed = filters.narrowed_filter(BASE, _m("1.1.*", KIND_IP),
                                             _m("443", KIND_INT))
    check("the port half still narrows", narrowed, text)
    check("and the wildcard IP contributed nothing", "1.1." not in text, text)


def test_an_injected_divert_is_never_narrowed():
    """--simulate and the tests hand in their own divert, which ignores the filter.

    Narrowing there would move a number in the report (``session.narrowed``)
    without changing a single packet - a cosmetic lie, and this project has spent
    an audit removing those.
    """
    engine = BeanEngine()
    engine.set_dest(True, "8.8.8.8", "53")
    engine.start(BASE, divert=FakeDivert([]), duration=0, narrow=True)
    try:
        info = engine.session_info()
        check("no narrowing on an injected divert", info["narrowed"] is False,
              str(info["narrowed"]))
        check("and the filter is reported unchanged", info["filter"] == BASE,
              info["filter"])
    finally:
        engine.stop()


def test_a_destination_change_is_refused_while_the_filter_is_narrowed():
    """The trap this whole design has to survive.

    A handle's filter is fixed when it opens. Accepting a new destination
    mid-session would leave the DRIVER holding the old, narrower filter while
    ``decide()`` judged by the new one - traffic the user just asked to impair
    would never arrive, and every counter would read healthy. Refusing out loud
    is the only honest option.
    """
    class _Core:
        dst_ip, dst_port = "8.8.8.8", "53"

    class _NarrowedEngine:
        core = _Core()
        applied = []

        def is_running(self):
            return True

        def session_info(self):
            return {"narrowed": True}

        def set_dest(self, *a):
            self.applied.append(a)

        def __getattr__(self, _name):        # every other set_* is a no-op
            return lambda *a, **k: None

    lines = []
    engine = _NarrowedEngine()

    same = dict(DEFAULT_SETTINGS, dst_ip="8.8.8.8", dst_port="53")
    apply_settings(engine, same, lines.append)
    check("re-applying the SAME destination is not refused",
          engine.applied and engine.applied[-1][0] is True, str(engine.applied))
    check("...and says nothing about freezing",
          not any("fixed for the session" in ln or "ustalony" in ln for ln in lines),
          str(lines))

    engine.applied.clear()
    lines.clear()
    changed = dict(DEFAULT_SETTINGS, dst_ip="1.1.1.1", dst_port="53")
    apply_settings(engine, changed, lines.append)
    check("a CHANGED destination is not pushed to the engine",
          not engine.applied, str(engine.applied))
    check("and the refusal is said out loud", any(ln for ln in lines), str(lines))


def test_a_destination_change_is_allowed_when_nothing_was_narrowed():
    """The refusal must not leak into ordinary sessions.

    Without narrowing the destination is live-appliable and always has been
    (``apply_settings`` -> ``set_dest``); freezing it there would be a regression
    dressed up as a safety feature.
    """
    class _Core:
        dst_ip, dst_port = "8.8.8.8", "53"

    class _PlainEngine:
        core = _Core()
        applied = []

        def is_running(self):
            return True

        def session_info(self):
            return {"narrowed": False}

        def set_dest(self, *a):
            self.applied.append(a)

        def __getattr__(self, _name):
            return lambda *a, **k: None

    engine = _PlainEngine()
    apply_settings(engine, dict(DEFAULT_SETTINGS, dst_ip="1.1.1.1"), lambda *_: None)
    # `.raw` if it arrived compiled: since the apply became a single batch, the
    # expressions are compiled BEFORE the lock is taken and handed to `set_dest`
    # as matchers (see core.compile_endpoint). What this test is about is that the
    # new destination reaches the engine at all, not which of the two shapes
    # `set_dest` accepts it in.
    applied = engine.applied[-1][1] if engine.applied else None
    check("an ordinary session still applies a new destination",
          getattr(applied, "raw", applied) == "1.1.1.1", str(engine.applied))
