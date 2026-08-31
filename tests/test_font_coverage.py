"""The render check's honesty valve: "no font" must not be able to mean "fine".

``tools/ci_gui_render.py`` measures real font metrics, so a language whose glyphs
are missing is measured as the missing-glyph box - and a box has a width, which
sails through every clipping test. The day Chinese landed, a Linux runner with no
CJK font would have reported a green nobody earned.

The rule guarded here is the half that is easy to "simplify" away: a NO is only
believed after the mechanism has been shown to say YES. Without the control query
an fc-list that answers nothing at all reads as "this machine has no fonts", every
language is reported unmeasured, and the check quietly stops checking - the same
silence in the opposite direction.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import font_coverage                                       # noqa: E402
from fakes import check                                    # noqa: E402


class _Result:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def _fake_fc(answers, calls=None):
    """An fc-list that answers ``answers[lang]``; anything unlisted is empty."""
    def run(argv, **kwargs):
        lang = argv[1].split("=", 1)[1]
        if calls is not None:
            calls.append(lang)
        value = answers.get(lang)
        if isinstance(value, Exception):
            raise value
        return _Result(stdout="".join(f"{name}\n" for name in value or ()))
    return run


def test_a_language_with_no_font_is_reported_as_such():
    run = _fake_fc({"en": ["DejaVu Sans"], "zh": []})
    check("a covered language answers yes",
          font_coverage.system_can_draw("en", run) is True)
    check("an uncovered language answers no",
          font_coverage.system_can_draw("zh", run) is False)


def test_a_control_that_finds_nothing_means_no_opinion_not_no_fonts():
    """fc-list answering nothing for ENGLISH is fontconfig failing, not a bare
    machine. Believing it would mark every language unmeasured and turn the whole
    render check into a formality that always passes."""
    run = _fake_fc({"en": [], "zh": []})
    check("the control decides: nothing is claimed",
          font_coverage.system_can_draw("zh", run) is None)


def test_no_fontconfig_at_all_is_no_opinion():
    """Windows has no fc-list. The check must behave exactly as it did before
    this file existed there, rather than declaring the machine glyph-less."""
    run = _fake_fc({"en": OSError("no fc-list"), "zh": OSError("no fc-list")})
    check("a missing fc-list claims nothing",
          font_coverage.system_can_draw("zh", run) is None)
    check("and families() says so too", font_coverage.families("zh", run) is None)


def test_a_failing_fc_list_is_not_read_as_an_answer():
    def run(argv, **kwargs):
        return _Result(stdout="whatever", returncode=2)
    check("a non-zero exit claims nothing",
          font_coverage.system_can_draw("zh", run) is None)


def test_the_control_is_asked_second_so_a_yes_costs_one_call():
    """The common case on a healthy runner is a covered language, and that must
    not pay for the diagnosis of a broken one."""
    calls = []
    run = _fake_fc({"en": ["DejaVu Sans"], "pl": ["DejaVu Sans"]}, calls)
    font_coverage.system_can_draw("pl", run)
    check("a covered language asks once", calls == ["pl"], f"({calls})")
