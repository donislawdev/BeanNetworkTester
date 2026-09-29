"""Pure input validators shared by the GUI, the CLI and the config loader.

The rule mirrors ``matchers.py``: parsing/validation lives in exactly one
place, raises a *translated* ``ValueError`` (keys ``errors.*``) and never
depends on tkinter. The GUI shows the message under the field, the CLI turns
it into ``error: ...`` and the config loader into ``errors.bad_config_value``.
"""
import math

from .i18n import field_name, translate
from .utils import number_string


def _decimal(value):
    """A finite number read from user text, decimal comma included - or None.

    The one place the comma rule lives (owner decision D-3): ``"2,5"`` is 2.5 and
    ``"10,000"`` is ten, because the comma is a decimal separator and thousands
    are never grouped. ``parse_number`` refuses on None, ``number_or_zero`` reads
    it as zero; two copies of the rule is how the preview strip came to read a
    value the engine accepted as no value at all (external review P1-7).
    """
    text = str("" if value is None else value).strip().replace(",", ".")
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def number_or_zero(value):
    """``value`` read exactly as ``parse_number`` reads it, or 0.0 where it refuses.

    For text that DESCRIBES the form instead of validating it - the preview
    strip - which has to say what the engine will get. A field it refuses is 0
    here, and the field itself is the one that says why.
    """
    number = _decimal(value)
    return 0.0 if number is None else number


def parse_number(value, field_key=None, bounds=None, lang=None):
    """Parse a user-entered number and check it against ``bounds``.

    ``field_key`` is an i18n key used to name the field in the error message;
    ``bounds`` is an inclusive ``(min, max)`` pair (either side may be None).
    Returns a ``float``. Raises a translated ``ValueError``.
    """
    # The label carries a colon for the form ("Latency:"); a sentence naming the
    # field must not (`Field 'Latency:' must be...`). One place strips it.
    name = field_name(field_key, lang) if field_key else ""
    number = _decimal(value)
    if number is None:                  # not a number, or NaN / infinity
        raise ValueError(translate("errors.field_number", lang, name=name))
    if bounds:
        low, high = bounds
        if (low is not None and number < low) or (high is not None and number > high):
            raise ValueError(translate(
                "errors.field_range", lang, name=name,
                min=number_string(low) if low is not None else "-",
                max=number_string(high) if high is not None else "-"))
    return number


# Past this a float no longer holds every whole number exactly, so a seed written
# as one would not repeat the run it came from.
_EXACT_FLOAT_INT = 2 ** 53


def parse_seed(value, lang=None):
    """Parse the reproducibility seed as an int: empty, None and -1 mean "random" (-1).

    A whole number written as a float - ``42.0``, which ``--save-config`` used to
    write - is that number (owner decision D-22). A fraction, a bool, or a float
    too large to be exact is refused: ``1.9`` used to become 1 in silence, and a
    config file's ``42`` came back as ``42.0``, which this very function then
    refused in the form, so START stayed blocked (external review P2-5).
    """
    error = ValueError(translate("errors.seed_integer", lang))
    if isinstance(value, bool):
        raise error
    if isinstance(value, float):
        if not value.is_integer() or abs(value) > _EXACT_FLOAT_INT:   # also NaN, inf
            raise error
        return int(value)
    if isinstance(value, int):
        return value
    text = str("" if value is None else value).strip()
    if not text or text == "-1":
        return -1
    try:
        return int(text)
    except (TypeError, ValueError) as exc:
        raise error from exc


def parse_bool(value, field_key=None, lang=None):
    """A switch: ``true`` / ``false``, or the numbers 0 and 1 (owner decision D-21).

    A string is refused, ``"false"`` included. ``bool("false")`` is True, which is
    how ``"lan_mode": "false"`` in a config file TURNED ON the mode that cuts all
    public traffic while ``--dry-run`` called the file valid (external review P1-2).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    name = field_name(field_key, lang) if field_key else ""
    raise ValueError(translate("errors.field_bool", lang, name=name))


def parse_choice(value, choices, field_key=None, lang=None):
    """One of ``choices``, exactly (surrounding spaces aside) - anything else refused.

    The traffic filter took any text: ``"tcpp"`` passed ``--dry-run`` and failed at
    the driver, ``null`` became the text ``"None"``, and ``"outbound"`` went to
    WinDivert as a raw filter nobody documented (external review P2-4).
    """
    text = value.strip() if isinstance(value, str) else None
    if text in choices:
        return text
    name = field_name(field_key, lang) if field_key else ""
    raise ValueError(translate("errors.field_choice", lang, name=name,
                               choices=", ".join(choices)))
