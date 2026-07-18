"""Reusable filter expressions for user-entered match fields.

One mini-language powers every "which packets / which processes" field in the
tool (target process, destination IP, destination port) and is meant to be the
single source of truth for any filter field added later.

Grammar - a field is a comma-separated list of terms::

    field      := term ("," term)*
    term       := ["!"] atom
    atom       := regex | comparison | range | cidr | wildcard | literal
    regex      := "re:" <python regular expression>
    comparison := (">=" | "<=" | ">" | "<") <numeric value>
    range      := <value> "-" <value>          (inclusive on BOTH ends)
    cidr       := <ip> "/" <prefix length>     (IP fields only)
    wildcard   := literal containing "*" or "?" (shell-style glob)
    literal    := a plain value

Evaluation - positives are OR-ed, negatives ("!") subtract::

    match(v) = (no positives or any(positive)) and not any(negative)

An empty field matches everything; a field with only negatives means
"everything except those". A term that cannot be evaluated for a given value
(no port on an ICMP packet, an IPv6 rule against an IPv4 address) simply does
not match - it never raises, because ``matches()`` runs in the packet hot path.

A comma inside a regular expression must be escaped (``\\,``); the escape is
removed before the pattern is compiled.

Kinds
-----
``KIND_INT``      numbers (ports): ``matches(value)``
``KIND_IP``       IPv4/IPv6 addresses: ``matches(ip_text)``
``KIND_PROCESS``  processes: ``matches(pid, name)``; numeric atoms (literal,
                  range, comparison) test the PID, text atoms (literal,
                  wildcard, regex) test the process name (substring,
                  case-insensitive - the historical behaviour). Comparison
                  operators are rejected on non-numeric operands.

Parsing raises a translated ``ValueError`` (``errors.bad_filter_*`` keys) so
the GUI can show it and the CLI can turn it into a clean error message.
"""
import fnmatch
import ipaddress
import re
import warnings

from .i18n import translate

KIND_INT = "int"
KIND_IP = "ip"
KIND_PROCESS = "process"

REGEX_PREFIX = "re:"
OPERATORS = (">=", "<=", ">", "<")       # two-character operators come first
PORT_BOUNDS = (0, 65535)                 # usable as the ``bounds`` of a port field


# -- errors ------------------------------------------------------------------ #
def _err(key, field, term, **fmt):
    """Build a translated ValueError for a bad term (``field`` is an i18n key)."""
    return ValueError(translate(key, None, field=translate(field), term=term, **fmt))


# -- value contexts (normalised once per matches() call, not per term) -------- #
class _IpValue:
    """An address normalised for comparison: canonical text, integer, family."""
    __slots__ = ("text", "num", "version")

    def __init__(self, addr):
        self.text = str(addr)
        self.num = int(addr)
        self.version = addr.version


class _ProcValue:
    """A process normalised for comparison: PID and lower-cased name."""
    __slots__ = ("pid", "name")

    def __init__(self, pid, name):
        try:
            self.pid = None if pid is None else int(pid)
        except (TypeError, ValueError):
            self.pid = None
        self.name = str(name or "").lower()


def _as_int(value):
    """Lenient int, or ``None`` when the value is not a whole number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_ip(value):
    """``_IpValue`` for a valid address, else ``None``."""
    if value is None:
        return None
    if isinstance(value, _IpValue):
        return value
    try:
        return _IpValue(ipaddress.ip_address(str(value).strip()))
    except (ValueError, TypeError):
        return None


# -- terms -------------------------------------------------------------------- #
class _Term:
    """A single parsed term: its predicate plus the text it came from."""
    __slots__ = ("text", "negated", "_predicate")

    def __init__(self, text, negated, predicate):
        self.text = text
        self.negated = negated
        self._predicate = predicate

    def matches(self, ctx):
        # The predicate runs for every captured packet; a surprise here must
        # never take down the capture thread, so failures mean "no match".
        try:
            return bool(self._predicate(ctx))
        except Exception:
            return False

    def __repr__(self):                                   # pragma: no cover
        return f"<_Term {self.text!r}>"


# -- matchers ----------------------------------------------------------------- #
class Matcher:
    """A compiled field expression. Compile once, call ``matches()`` per packet."""
    kind = None

    def __init__(self, raw, terms):
        self.raw = str(raw or "").strip()
        self.terms = list(terms)
        self._positives = [t for t in self.terms if not t.negated]
        self._negatives = [t for t in self.terms if t.negated]

    @property
    def is_empty(self):
        """True for an empty field - "match everything"."""
        return not self.terms

    def __bool__(self):
        """A matcher is falsy when empty, so callers can write ``if matcher:``."""
        return not self.is_empty

    def _context(self, *value):
        raise NotImplementedError

    def matches(self, *value):
        if not self.terms:
            return True
        ctx = self._context(*value)
        if self._positives and not any(t.matches(ctx) for t in self._positives):
            return False
        return not any(t.matches(ctx) for t in self._negatives)

    def excluded(self, *value):
        """True when a value is knocked out by an explicit ``!`` term.

        ``matches()`` alone cannot answer "was this *rejected*, or did it merely
        fail to be selected?" - and process targeting needs the difference: a
        socket may be pulled in by its parent process (see ``targeting.py``), but
        never one the user excluded by hand (``chrome, !chromedriver``).
        """
        if not self._negatives:
            return False
        ctx = self._context(*value)
        return any(t.matches(ctx) for t in self._negatives)

    def describe(self):
        """Canonical text of the expression - and it PARSES BACK to this matcher.

        The comma escape has to be put back. ``split_terms`` turns ``\\,`` into a
        literal comma inside the term, so a term that contains one (only possible
        in a ``re:`` pattern) would otherwise be emitted as a bare comma - i.e. as
        a TERM SEPARATOR, silently splitting one regex into two nonsense terms.
        Found by a property test (``test_describe_reparses_to_the_same_matcher``).
        """
        return ", ".join(t.text.replace(",", "\\,") for t in self.terms)

    def __str__(self):
        return self.raw

    def __repr__(self):                                   # pragma: no cover
        return f"<{type(self).__name__} {self.raw!r}>"


class IntMatcher(Matcher):
    """Numbers - ports today, any numeric field tomorrow."""
    kind = KIND_INT

    @staticmethod
    def _context(value):
        return _as_int(value)


class IpMatcher(Matcher):
    """IPv4/IPv6 addresses. Rules only ever match their own address family."""
    kind = KIND_IP

    @staticmethod
    def _context(value):
        return _as_ip(value)


class ProcessMatcher(Matcher):
    """Processes, matched on ``(pid, name)``."""
    kind = KIND_PROCESS

    @staticmethod
    def _context(pid, name=""):
        return _ProcValue(pid, name)


_MATCHER_CLASSES = {KIND_INT: IntMatcher, KIND_IP: IpMatcher,
                    KIND_PROCESS: ProcessMatcher}


# -- splitting ----------------------------------------------------------------- #
def split_terms(text):
    """Split a field on commas, honouring the ``\\,`` escape (for regexes).

    ``\\,`` becomes a literal comma inside the term; every other backslash is
    kept as-is so regular expressions such as ``re:^\\d+$`` survive intact.
    """
    parts, buf, escaped = [], [], False
    for ch in str(text or ""):
        if escaped:
            if ch != ",":
                buf.append("\\")
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if escaped:
        buf.append("\\")
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


# -- atom parsers --------------------------------------------------------------- #
def _check_bounds(number, bounds, field, term):
    if bounds and not (bounds[0] <= number <= bounds[1]):
        raise _err("errors.bad_filter_bounds", field, term,
                   min=bounds[0], max=bounds[1])
    return number


def _parse_int_atom(body, term, field, bounds):
    """Predicate over an ``int`` context, or ``None`` when the atom is not numeric.

    ``None`` lets the caller fall back to the text atoms (the process field
    accepts both PIDs and names in the same expression).
    """
    # comparison
    for op in OPERATORS:
        if body.startswith(op):
            operand = body[len(op):].strip()
            if not operand.isdigit():
                # ">chrome" is meaningless: comparisons need a number (a PID)
                raise _err("errors.bad_filter_compare", field, term)
            number = _check_bounds(int(operand), bounds, field, term)
            return _compare_predicate(op, number)
    # range  a-b  (inclusive)
    if "-" in body:
        lo_text, _, hi_text = body.partition("-")
        lo_text, hi_text = lo_text.strip(), hi_text.strip()
        if lo_text.isdigit() and hi_text.isdigit():
            lo = _check_bounds(int(lo_text), bounds, field, term)
            hi = _check_bounds(int(hi_text), bounds, field, term)
            if lo > hi:
                raise _err("errors.bad_filter_range", field, term)
            return lambda c: c is not None and lo <= c <= hi
    # literal number
    if body.isdigit():
        number = _check_bounds(int(body), bounds, field, term)
        return lambda c: c == number
    return None


def _compare_predicate(op, number):
    if op == ">":
        return lambda c: c is not None and c > number
    if op == "<":
        return lambda c: c is not None and c < number
    if op == ">=":
        return lambda c: c is not None and c >= number
    return lambda c: c is not None and c <= number


def _compile_regex(pattern, field, term):
    pattern = pattern.strip()
    if not pattern:
        raise _err("errors.bad_filter_regex", field, term)
    try:
        # A user pattern like "[a-z[0-9]]" makes `re` emit a FutureWarning ("possible
        # nested set"). It is not an error and the pattern still compiles - but the
        # warning goes to stderr, which in a windowed build DOES NOT EXIST, and in the
        # CLI lands in the middle of the log channel. Either way it is noise the user
        # can do nothing about, so it is swallowed here; a pattern that is genuinely
        # broken still raises re.error below.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            warnings.simplefilter("ignore", DeprecationWarning)
            return re.compile(pattern, re.IGNORECASE)
    except re.error:
        raise _err("errors.bad_filter_regex", field, term)


def _is_glob(body):
    return "*" in body or "?" in body


def _parse_int_term(body, term, field, bounds):
    if body.lower().startswith(REGEX_PREFIX):
        rx = _compile_regex(body[len(REGEX_PREFIX):], field, term)
        return lambda c: c is not None and rx.search(str(c)) is not None
    predicate = _parse_int_atom(body, term, field, bounds)
    if predicate is not None:
        return predicate
    if _is_glob(body):
        # glob over the decimal text: "8*" matches 8, 80, 8080 (see the docs -
        # a range is almost always what you actually want)
        pattern = body
        return lambda c: c is not None and fnmatch.fnmatchcase(str(c), pattern)
    raise _err("errors.bad_filter_number", field, term)


def _parse_ip_term(body, term, field):
    if body.lower().startswith(REGEX_PREFIX):
        rx = _compile_regex(body[len(REGEX_PREFIX):], field, term)
        return lambda c: c is not None and rx.search(c.text) is not None
    # comparison
    for op in OPERATORS:
        if body.startswith(op):
            operand = _as_ip(body[len(op):].strip())
            if operand is None:
                raise _err("errors.bad_filter_ip", field, term)
            version, num = operand.version, operand.num
            base = _compare_predicate(op, num)
            return lambda c: c is not None and c.version == version and base(c.num)
    # CIDR
    if "/" in body:
        try:
            net = ipaddress.ip_network(body, strict=False)
        except (ValueError, TypeError):
            raise _err("errors.bad_filter_ip", field, term)
        lo = int(net.network_address)
        hi = int(net.broadcast_address)
        version = net.version
        return lambda c: c is not None and c.version == version and lo <= c.num <= hi
    # range a-b (IPv6 text never contains "-", so this is unambiguous)
    if "-" in body:
        lo_text, _, hi_text = body.partition("-")
        lo_ip, hi_ip = _as_ip(lo_text), _as_ip(hi_text)
        if lo_ip is None or hi_ip is None:
            raise _err("errors.bad_filter_ip", field, term)
        if lo_ip.version != hi_ip.version:
            raise _err("errors.bad_filter_ip_family", field, term)
        if lo_ip.num > hi_ip.num:
            raise _err("errors.bad_filter_range", field, term)
        lo, hi, version = lo_ip.num, hi_ip.num, lo_ip.version
        return lambda c: c is not None and c.version == version and lo <= c.num <= hi
    # wildcard over the canonical text (IPv6 canonical form is lower-case)
    if _is_glob(body):
        pattern = body.lower()
        return lambda c: c is not None and fnmatch.fnmatchcase(c.text.lower(), pattern)
    # plain address
    literal = _as_ip(body)
    if literal is None:
        raise _err("errors.bad_filter_ip", field, term)
    num, version = literal.num, literal.version
    return lambda c: c is not None and c.version == version and c.num == num


def _parse_process_term(body, term, field):
    if body.lower().startswith(REGEX_PREFIX):
        rx = _compile_regex(body[len(REGEX_PREFIX):], field, term)
        return lambda c: rx.search(c.name) is not None
    # comparison operators only make sense on a PID; on a name they are an error
    for op in OPERATORS:
        if body.startswith(op):
            operand = body[len(op):].strip()
            if not operand.isdigit():
                raise _err("errors.bad_filter_compare_name", field, term)
            base = _compare_predicate(op, int(operand))
            return lambda c: c.pid is not None and base(c.pid)
    # numeric atoms (literal PID / PID range) reuse the int parser
    numeric = _parse_int_atom(body, term, field, None)
    if numeric is not None:
        return lambda c: numeric(c.pid)
    # wildcard over the process name
    if _is_glob(body):
        pattern = body.lower()
        return lambda c: fnmatch.fnmatchcase(c.name, pattern)
    # plain name: case-insensitive substring (historical behaviour - "chrome"
    # still finds "chrome.exe"); use a wildcard or re: when you need precision
    needle = body.lower()
    return lambda c: needle in c.name


# -- public API ------------------------------------------------------------------ #
def parse_matcher(text, kind, field="fields.filter", bounds=None):
    """Compile a field expression into a :class:`Matcher`.

    ``kind``   one of ``KIND_INT`` / ``KIND_IP`` / ``KIND_PROCESS``
    ``field``  i18n key of the field label, used in error messages
    ``bounds`` optional ``(min, max)`` for numeric fields (ports: ``PORT_BOUNDS``)

    Raises a translated ``ValueError`` on a malformed expression.
    """
    if isinstance(text, Matcher):
        return text
    try:
        cls = _MATCHER_CLASSES[kind]
    except KeyError:
        raise ValueError(f"unknown matcher kind: {kind!r}")

    terms = []
    for raw_term in split_terms(text):
        negated = raw_term.startswith("!")
        body = raw_term[1:].strip() if negated else raw_term
        if not body:
            raise _err("errors.bad_filter_term", field, raw_term)
        if kind == KIND_INT:
            predicate = _parse_int_term(body, raw_term, field, bounds)
        elif kind == KIND_IP:
            predicate = _parse_ip_term(body, raw_term, field)
        else:
            predicate = _parse_process_term(body, raw_term, field)
        terms.append(_Term(raw_term, negated, predicate))
    return cls(text, terms)


def validate_matcher(text, kind, field="fields.filter", bounds=None):
    """Parse and discard - raises the translated ``ValueError`` on bad input."""
    parse_matcher(text, kind, field, bounds)
    return True


def port_expression(value):
    """Normalise a port field that may still hold a legacy number.

    The port used to be an ``int`` (with ``0`` meaning "no port"); config files,
    profiles and scenarios written by older versions still carry that shape.
    Numbers become their decimal text, ``0`` (the old "unset" sentinel) and
    ``None`` become an empty expression, and text passes through untouched.
    """
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        if float(value) == 0.0:
            return ""
        return str(int(value)) if float(value).is_integer() else str(value)
    return str(value).strip()
