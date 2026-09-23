"""The expression tester: does THIS value match THAT field's expression - and why.

The question it closes is the one README's "Cases that trip people up" exists
for: why does ``10.0.0.0/16, !10.0.5.0/24`` not catch ``10.0.5.7``? Until now the
only way to find out was to start a session and watch the "impaired?" column.

Everything the answer needs already exists, and nothing is parsed a second time
(convention 10): the field comes from the field registry, the expression goes
through ``matchers.parse_matcher`` with that field's own kind, label and bounds -
so an error names the right field - and the verdict with the terms behind it comes
from ``Matcher.explain``. What this module adds is the part no field needed until
a person typed a value by hand: checking the VALUE. ``matches()`` answers "no" to
a value it cannot read (it never raises, it runs per packet), and for a person
"no" would be a lie about the expression when the value was the problem - so a
value that is not an address, not a port or not a pid is reported as that.
"""
import ipaddress
import re
from typing import NamedTuple

from ..fields import EXPR, FIELDS
from ..matchers import KIND_INT, KIND_IP, KIND_PROCESS, parse_matcher

# The states a verdict can be in. Four of them are an answer about the EXPRESSION
# or the VALUE; only MATCH and NO_MATCH are an answer about the pair.
MATCH = "match"
NO_MATCH = "no_match"
NO_VALUE = "no_value"               # the expression parses; nothing to test it on yet
BAD_VALUE = "bad_value"
BAD_EXPRESSION = "bad_expression"

# The longest test value taken. The expression parser vets a regular expression by
# timing it on probes of up to 45 characters (`matchers._REGEX_PROBE_LENGTHS`), and
# runs on the UI thread, as the Control page's live validation does - so a value far
# longer than anything the vetting saw is refused rather than run through a
# pattern nobody has timed on it. 256 is far past any process name this tool has
# met; an address or a port never gets near it.
MAX_VALUE_CHARS = 256

# ASCII digits, not ``str.isdigit()``: MEASURED 2026-09-23, for "443" written in
# Arabic-Indic digits (``"٤٤٣"``) ``isdigit()`` is True and
# ``int()`` returns 443 - so the tester would have accepted a spelling of a port
# that nobody types into this field by accident and that no packet carries.
_DIGITS = re.compile(r"[0-9]+")


class Verdict(NamedTuple):
    """What the tester shows. Every field is data; the panel does the words."""
    state: str
    canonical: str = ""         # the expression as the parser read it (``describe()``)
    selected_by: tuple = ()     # positive terms the value satisfies
    excluded_by: tuple = ()     # "!" terms the value satisfies
    everything: bool = False    # the expression is empty: the field matches everything
    bounds_nothing: bool = False  # it parses, and selects nothing in particular
    problem: str = ""           # the parser's own sentence (arrives translated)
    problem_key: str = ""       # i18n key of what is wrong with the VALUE
    problem_args: tuple = ()    # ((name, value), ...) for that key's placeholders


class _BadValue(Exception):
    def __init__(self, key, **args):
        super().__init__(key)
        self.key = key
        self.args_pairs = tuple(sorted(args.items()))


# -- reading a test value, one reader per kind of expression --------------------- #
# Each returns the arguments ``Matcher.explain`` takes for that kind, or None when
# nothing was typed. A kind without a reader here is caught by a test against the
# field registry, not discovered by a person getting "does not match" for ever.

def _ip_value(_field, value, _pid):
    text = value.strip()
    if not text:
        return None
    try:
        ipaddress.ip_address(text)
    except ValueError:
        raise _BadValue("tools.exprtest.bad_ip") from None
    return (text,)


def _int_value(field, value, _pid):
    text = value.strip()
    if not text:
        return None
    if not _DIGITS.fullmatch(text):
        raise _BadValue("tools.exprtest.bad_number")
    number = int(text)
    if field.bounds is not None:
        low, high = (int(bound) for bound in field.bounds)
        if not low <= number <= high:
            raise _BadValue("tools.exprtest.out_of_range", low=low, high=high)
    return (number,)


def _process_value(_field, value, pid):
    name, pid_text = value.strip(), pid.strip()
    if not name and not pid_text:
        return None
    if pid_text and not _DIGITS.fullmatch(pid_text):
        raise _BadValue("tools.exprtest.bad_pid")
    return (int(pid_text) if pid_text else None, name)


VALUE_READERS = {
    KIND_IP: _ip_value,
    KIND_INT: _int_value,
    KIND_PROCESS: _process_value,
}


def evaluate(field_key, expression, value="", pid=""):
    """Test ``value`` (and ``pid``, for a process field) against ``expression``.

    ``field_key`` must name an expression field of the registry; anything else is
    a programming error and raises. Everything a PERSON can type comes back as a
    ``Verdict`` - it never raises for bad input.
    """
    field = FIELDS[field_key]
    if field.kind != EXPR:
        raise ValueError(f"{field_key} is not an expression field")
    reader = VALUE_READERS.get(field.expr_kind)
    if reader is None:
        return Verdict(BAD_VALUE, problem_key="tools.exprtest.kind_unknown")
    try:
        matcher = parse_matcher(expression, field.expr_kind, field.label, field.bounds)
    except ValueError as exc:
        return Verdict(BAD_EXPRESSION, problem=str(exc))
    shape = {"canonical": matcher.describe(), "everything": matcher.is_empty,
             "bounds_nothing": not matcher.is_empty and matcher.bounds_nothing}
    # A pid means something only to a process field. Left in the box after the
    # field was switched to an address, it must not turn the address's verdict
    # into "too long" or anything else.
    if field.expr_kind != KIND_PROCESS:
        pid = ""
    if max(len(value), len(pid)) > MAX_VALUE_CHARS:
        return Verdict(BAD_VALUE, problem_key="tools.exprtest.too_long",
                       problem_args=(("limit", MAX_VALUE_CHARS),), **shape)
    try:
        probe = reader(field, value, pid)
    except _BadValue as bad:
        return Verdict(BAD_VALUE, problem_key=bad.key, problem_args=bad.args_pairs,
                       **shape)
    if probe is None:
        return Verdict(NO_VALUE, **shape)
    why = matcher.explain(*probe)
    return Verdict(MATCH if why.matched else NO_MATCH, selected_by=why.selected_by,
                   excluded_by=why.excluded_by, **shape)
