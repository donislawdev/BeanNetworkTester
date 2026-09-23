"""The expression tester's logic (``nettools/exprtest.py``): every state it can answer with.

Pure - no tkinter. The panel on the Tools tab only draws what ``evaluate`` returns,
so the four states of the path (normal, failure, degenerate input, and the one
that matters most here: a VALUE that cannot be read is not a "no") live here.
"""
import pytest

from beantester.fields import expression_fields
from beantester.i18n import set_language
from beantester.matchers import KIND_PROCESS
from beantester.nettools import exprtest
from beantester.nettools.exprtest import (BAD_EXPRESSION, BAD_VALUE, MATCH,
                                          MAX_VALUE_CHARS, NO_MATCH, NO_VALUE,
                                          VALUE_READERS, evaluate)
from fakes import check


@pytest.fixture(autouse=True)
def _english():
    set_language("en")


def test_every_expression_field_has_a_reader_for_its_values():
    """A new expression field with a new KIND must not answer "does not match" for ever.

    ``matches()`` returns False for a value it cannot read, so a kind without a
    reader here would look like a working tester that never matches anything.
    """
    kinds = {field.expr_kind for field in expression_fields()}
    check("the registry has expression fields to test", len(kinds) >= 3, f"({kinds})")
    missing = sorted(kinds - set(VALUE_READERS))
    check("every kind of expression field has a value reader", not missing, f"({missing})")


def test_the_verdict_names_the_terms_that_decided():
    verdict = evaluate("dst_ip", "10.0.0.0/16, !10.0.5.0/24", "10.0.5.7")
    assert verdict.state == NO_MATCH, verdict
    assert verdict.selected_by == ("10.0.0.0/16",) and verdict.excluded_by == ("!10.0.5.0/24",)
    assert verdict.canonical == "10.0.0.0/16, !10.0.5.0/24"
    assert evaluate("dst_ip", "10.0.0.0/16, !10.0.5.0/24", "10.0.6.1").state == MATCH
    assert evaluate("dst_port", "443, 8000-8100", "8080").selected_by == ("8000-8100",)
    assert evaluate("block_port", "443", "80").state == NO_MATCH


def test_a_process_is_tested_by_name_and_by_pid():
    assert evaluate("target", "chrome", "chrome.exe").state == MATCH
    assert evaluate("target", "chrome, !chromedriver", "chromedriver.exe").state == NO_MATCH
    assert evaluate("target", "1000-2000", "", "1500").state == MATCH
    assert evaluate("target", "1000-2000", "anything.exe", "999").state == NO_MATCH
    # a pid term never matches a probe that carries only a name, and says so as NO_MATCH
    assert evaluate("target", "1500", "chrome.exe").state == NO_MATCH


def test_an_unreadable_value_is_reported_as_the_value_not_as_no_match():
    """``matches()`` answers False for a value it cannot read. For a person that
    False would be a statement about the EXPRESSION - and the expression is fine."""
    cases = [
        ("dst_ip", "10.0.0.0/8", "10.0.0", "", "tools.exprtest.bad_ip"),
        ("dst_ip", "10.0.0.0/8", "example.com", "", "tools.exprtest.bad_ip"),
        ("dst_port", "443", "https", "", "tools.exprtest.bad_number"),
        ("dst_port", "443", "-1", "", "tools.exprtest.bad_number"),
        ("dst_port", "443", "65536", "", "tools.exprtest.out_of_range"),
        ("target", "chrome", "chrome.exe", "12a", "tools.exprtest.bad_pid"),
    ]
    for field, expression, value, pid, key in cases:
        verdict = evaluate(field, expression, value, pid)
        check(f"{field}={value!r}/{pid!r} is a value problem",
              verdict.state == BAD_VALUE and verdict.problem_key == key,
              f"({verdict.state}, {verdict.problem_key})")
        # the expression itself still parsed, so it is still shown and still usable
        check(f"{field}={value!r}: the expression is still read",
              verdict.canonical == expression, f"({verdict.canonical!r})")
    ranged = evaluate("dst_port", "443", "70000")
    assert dict(ranged.problem_args) == {"low": 0, "high": 65535}, ranged


def test_only_ascii_digits_are_a_number():
    """MEASURED 2026-09-23: ``isdigit()`` is True and ``int()`` returns 443 for
    "443" written in Arabic-Indic digits - so ``isdigit`` would accept it."""
    arabic_443 = "٤٤٣"
    assert arabic_443.isdigit() and int(arabic_443) == 443      # the trap itself
    assert evaluate("dst_port", "443", arabic_443).problem_key == "tools.exprtest.bad_number"
    assert evaluate("target", "443", "", arabic_443).problem_key == "tools.exprtest.bad_pid"


def test_an_expression_that_cannot_be_read_carries_the_parsers_own_sentence():
    verdict = evaluate("dst_port", "443, !", "443")
    assert verdict.state == BAD_EXPRESSION, verdict
    # the parser names the field it was told about - the tester passes the field's
    # own label, so the sentence points at the right one
    assert verdict.problem.endswith(".") and "Port" in verdict.problem, verdict.problem
    assert verdict.canonical == "" and not verdict.selected_by


def test_nothing_typed_is_its_own_state():
    for field, expression in (("dst_ip", "10.0.0.0/8"), ("dst_port", "443"),
                              ("target", "chrome")):
        verdict = evaluate(field, expression, "   ", "  ")
        check(f"{field}: blank value is NO_VALUE, not a verdict",
              verdict.state == NO_VALUE, f"({verdict.state})")


def test_empty_and_exclusion_only_expressions_are_flagged():
    empty = evaluate("dst_ip", "   ", "8.8.8.8")
    assert empty.state == MATCH and empty.everything and not empty.bounds_nothing, empty
    spare = evaluate("dst_ip", "!10.0.0.0/8", "8.8.8.8")
    assert spare.state == MATCH and spare.bounds_nothing and not spare.everything, spare
    everything = evaluate("target", "*", "chrome.exe")
    assert everything.state == MATCH and everything.bounds_nothing, everything
    narrow = evaluate("dst_ip", "10.0.0.0/8", "10.1.1.1")
    assert not narrow.bounds_nothing and not narrow.everything, narrow


def test_address_families_never_cross_and_never_raise():
    assert evaluate("dst_ip", "10.0.0.0/8", "::1").state == NO_MATCH
    assert evaluate("dst_ip", "fe80::/10", "fe80::1%12").state == MATCH


def test_a_pid_left_behind_does_not_touch_a_field_that_has_none():
    """Typed for the Process field, then the field switched to an address: the pid
    box still holds text, and it must not change the address's verdict."""
    long_pid = "9" * (MAX_VALUE_CHARS + 5)
    assert evaluate("dst_ip", "10.0.0.0/8", "10.1.1.1", long_pid).state == MATCH
    assert evaluate("dst_ip", "10.0.0.0/8", "10.1.1.1", "not a pid").state == MATCH


def test_the_length_limit_is_a_value_problem_and_sits_exactly_at_the_limit():
    at_limit = "a" * MAX_VALUE_CHARS
    assert evaluate("target", "re:^a+$", at_limit).state == MATCH
    over = evaluate("target", "re:^a+$", at_limit + "a")
    assert over.state == BAD_VALUE and over.problem_key == "tools.exprtest.too_long", over
    assert dict(over.problem_args) == {"limit": MAX_VALUE_CHARS}
    over_pid = evaluate("target", "1", "", "1" * (MAX_VALUE_CHARS + 1))
    assert over_pid.problem_key == "tools.exprtest.too_long", over_pid


def test_a_field_that_is_not_an_expression_is_a_programming_error():
    with pytest.raises(ValueError):
        evaluate("loss", "1", "1")
    with pytest.raises(KeyError):
        evaluate("no_such_field", "1", "1")


def test_a_kind_without_a_reader_says_so_instead_of_guessing(monkeypatch):
    monkeypatch.delitem(exprtest.VALUE_READERS, KIND_PROCESS)
    verdict = evaluate("target", "chrome", "chrome.exe")
    assert verdict.state == BAD_VALUE and verdict.problem_key == "tools.exprtest.kind_unknown"
