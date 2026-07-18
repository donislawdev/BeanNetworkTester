"""Pure input validators shared by the GUI, the CLI and the config loader.

The rule mirrors ``matchers.py``: parsing/validation lives in exactly one
place, raises a *translated* ``ValueError`` (keys ``errors.*``) and never
depends on tkinter. The GUI shows the message under the field, the CLI turns
it into ``error: ...`` and the config loader into ``errors.bad_config_value``.
"""
from .i18n import translate
from .utils import number_string


def parse_number(value, field_key=None, bounds=None, lang=None):
    """Parse a user-entered number and check it against ``bounds``.

    ``field_key`` is an i18n key used to name the field in the error message;
    ``bounds`` is an inclusive ``(min, max)`` pair (either side may be None).
    Returns a ``float``. Raises a translated ``ValueError``.
    """
    name = translate(field_key, lang) if field_key else ""
    text = str("" if value is None else value).strip().replace(",", ".")
    try:
        number = float(text)
    except (TypeError, ValueError):
        raise ValueError(translate("errors.field_number", lang, name=name))
    if number != number or number in (float("inf"), float("-inf")):   # NaN / inf
        raise ValueError(translate("errors.field_number", lang, name=name))
    if bounds:
        low, high = bounds
        if (low is not None and number < low) or (high is not None and number > high):
            raise ValueError(translate(
                "errors.field_range", lang, name=name,
                min=number_string(low) if low is not None else "-",
                max=number_string(high) if high is not None else "-"))
    return number


def parse_seed(value, lang=None):
    """Parse the reproducibility seed: empty means ``-1`` ("random")."""
    text = str("" if value is None else value).strip()
    if not text or text == "-1":
        return -1
    try:
        return int(text)
    except (TypeError, ValueError):
        raise ValueError(translate("errors.seed_integer", lang))
