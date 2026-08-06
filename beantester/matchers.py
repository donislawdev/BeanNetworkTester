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
    """A single parsed term: its predicate, its SHAPE, and the text it came from.

    ``shape`` is what the parser concluded, kept instead of thrown away: a small
    immutable descriptor like ``("eq", 443)`` or ``("ip_range", 4, lo, hi)``, and
    ``None`` for the forms that have no closed description (glob, ``re:``, a
    process name). It exists so a second consumer - compiling the expression down
    into the DRIVER's own filter language, see :func:`windivert_fragment` - can
    read what was parsed instead of parsing the text a second time. A second
    parser of this mini-language is exactly what convention 10 forbids, and the
    reason is drift: two readers of the same syntax stay in step only until one
    of them is edited.

    The hot path never touches this. ``matches()`` still calls the closure.
    """
    __slots__ = ("text", "negated", "_predicate", "shape")

    def __init__(self, text, negated, predicate, shape=None):
        self.text = text
        self.negated = negated
        self._predicate = predicate
        self.shape = shape

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

    @property
    def selects_nothing_in_particular(self):
        """True when the expression names no thing to hit - only things to spare.

        ``!chrome.exe`` is not empty, so every "is a target set?" check written as
        a truth test reads it as narrow. It is the opposite: ``matches()`` skips
        the positive branch entirely, so the expression covers everything except
        the exclusions. Callers that care about BLAST RADIUS (see
        ``settings.unbounded_impairment``) must treat it as unscoped.
        """
        return not self._positives

    # Values a term is tried against to answer "does this name anything in
    # particular?". Deliberately unlike one another, so an expression that
    # matches all of them is one that would match nearly anything.
    #
    # GROUPS, not one flat list, because of address families: a rule can cover
    # the whole of IPv4 and none of IPv6, and that still bounds nothing worth
    # having. Covering any ONE group completely is enough. Kinds without such a
    # split declare a single group.
    BLAST_PROBES = ()

    @property
    def covers_everything(self):
        """True when the positive terms hit every probe - i.e. they bound nothing.

        ``selects_nothing_in_particular`` catches an expression with no positive
        term at all. This catches the other half, which reads as narrow to every
        truth test and is not: ``*`` and ``re:.*`` are positive terms that select
        the whole machine. MEASURED before this existed: ``--target *`` set
        ``targeting_is_set`` to True and silenced the start-time warning, while
        ``--loss 100`` on its own warned - so the expression that bounds nothing
        was treated as safer than no expression at all.

        A heuristic, and named as one. It answers by ASKING the compiled terms
        rather than by inspecting their text, because "matches everything" is not
        a syntactic property: ``>0`` on pids and ``0-999999`` cover every process
        without a wildcard in sight, and ``*.*`` covers only names containing a
        dot despite looking universal.

        What it cannot see, written down rather than left to be discovered:

        * an expression matching every probe by coincidence. The probes are few,
          so this is possible - and it is the SAFE direction: the caller only
          raises an advisory warning, so a false positive costs one line of text
          and a false negative costs the user's network.
        """
        if not self._positives:
            return False
        for group in self.BLAST_PROBES:
            if group and all(
                    any(t.matches(self._context(*probe)) for t in self._positives)
                    for probe in group):
                return True
        return False

    @property
    def bounds_nothing(self):
        """True when this expression does not narrow the blast radius at all.

        The two halves belong together and are exposed as one property on
        purpose: a caller reaching for either alone gets half a guard, and half a
        guard on this question is what let ``--target *`` through.
        """
        return self.selects_nothing_in_particular or self.covers_everything

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
    BLAST_PROBES = (((1,), (443,), (49152,), (65535,)),)

    @staticmethod
    def _context(value):
        return _as_int(value)


class IpMatcher(Matcher):
    """IPv4/IPv6 addresses. Rules only ever match their own address family."""
    kind = KIND_IP
    # Both families on purpose: a rule that covers one of them entirely is not
    # flagged, which is stated in Matcher.covers_everything rather than hidden.
    BLAST_PROBES = ((("127.0.0.1",), ("8.8.8.8",), ("192.168.1.1",)),
                    (("::1",), ("2001:db8::1",), ("fe80::1",)))

    @staticmethod
    def _context(value):
        return _as_ip(value)


class ProcessMatcher(Matcher):
    """Processes, matched on ``(pid, name)``."""
    kind = KIND_PROCESS
    # Unlike each other in both halves a term can look at: the pid and the name.
    BLAST_PROBES = (((4, "System"), (1234, "chrome.exe"),
                     (2, "svchost.exe"), (65000, "a")),)

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


def add_term(text, term):
    """Return ``text`` with ``term`` appended, or unchanged if it is already there.

    The Connections context menu builds expressions one row at a time: block this
    address, then that one, then leave this process alone. Appending is the only
    behaviour that makes sense there - replacing would silently drop the two
    addresses the user blocked a moment ago.

    It lives HERE rather than in the GUI because splitting on commas is a question
    about the FILTER SYNTAX, and this module owns that (convention 10). Naive
    string concatenation gets three things wrong that ``split_terms`` already
    knows: an escaped ``\\,`` inside a regex is not a separator, terms carry
    surrounding whitespace that must not become part of the value, and a trailing
    comma from an earlier edit would produce an empty term.

    Duplicates are dropped rather than repeated. ``80,80`` means the same as
    ``80``, so the only thing a repeat changes is that the field looks broken.

    🔴 **The comma escape has to be put back on the way out**, exactly as in
    ``Matcher.describe``. ``split_terms`` turns ``\\,`` into a literal comma inside
    the term, so re-joining without escaping emits it as a SEPARATOR and silently
    splits one regex into two nonsense terms. This function reintroduced that bug
    when it was first written, on the same day its twin was cited as a solved one -
    which is why the round trip is now a test, not a promise.
    """
    term = str(term or "").strip()
    if not term:
        return str(text or "")
    existing = split_terms(text)
    terms = existing if term in existing else existing + [term]
    return ",".join(t.replace(",", "\\,") for t in terms)


# -- atom parsers --------------------------------------------------------------- #
def _check_bounds(number, bounds, field, term):
    if bounds and not (bounds[0] <= number <= bounds[1]):
        raise _err("errors.bad_filter_bounds", field, term,
                   min=bounds[0], max=bounds[1])
    return number


def _parse_int_atom(body, term, field, bounds):
    """``(predicate, shape)`` over an ``int`` context, or ``None`` when not numeric.

    ``None`` lets the caller fall back to the text atoms (the process field
    accepts both PIDs and names in the same expression). ``shape`` is the parsed
    description kept for :func:`windivert_fragment` - see ``_Term``.
    """
    # comparison
    for op in OPERATORS:
        if body.startswith(op):
            operand = body[len(op):].strip()
            if not operand.isdigit():
                # ">chrome" is meaningless: comparisons need a number (a PID)
                raise _err("errors.bad_filter_compare", field, term)
            number = _check_bounds(int(operand), bounds, field, term)
            return _compare_predicate(op, number), ("cmp", op, number)
    # range  a-b  (inclusive)
    if "-" in body:
        lo_text, _, hi_text = body.partition("-")
        lo_text, hi_text = lo_text.strip(), hi_text.strip()
        if lo_text.isdigit() and hi_text.isdigit():
            lo = _check_bounds(int(lo_text), bounds, field, term)
            hi = _check_bounds(int(hi_text), bounds, field, term)
            if lo > hi:
                raise _err("errors.bad_filter_range", field, term)
            return (lambda c: c is not None and lo <= c <= hi), ("range", lo, hi)
    # literal number
    if body.isdigit():
        number = _check_bounds(int(body), bounds, field, term)
        return (lambda c: c == number), ("eq", number)
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
    """``(predicate, shape)``; ``shape`` is ``None`` for the undescribable forms."""
    if body.lower().startswith(REGEX_PREFIX):
        rx = _compile_regex(body[len(REGEX_PREFIX):], field, term)
        return (lambda c: c is not None and rx.search(str(c)) is not None), None
    atom = _parse_int_atom(body, term, field, bounds)
    if atom is not None:
        return atom
    if _is_glob(body):
        # glob over the decimal text: "8*" matches 8, 80, 8080 (see the docs -
        # a range is almost always what you actually want)
        pattern = body
        return (lambda c: c is not None and fnmatch.fnmatchcase(str(c), pattern)), None
    raise _err("errors.bad_filter_number", field, term)


def _parse_ip_term(body, term, field):
    """``(predicate, shape)``; ``shape`` is ``None`` for the undescribable forms."""
    if body.lower().startswith(REGEX_PREFIX):
        rx = _compile_regex(body[len(REGEX_PREFIX):], field, term)
        return (lambda c: c is not None and rx.search(c.text) is not None), None
    # comparison
    for op in OPERATORS:
        if body.startswith(op):
            operand = _as_ip(body[len(op):].strip())
            if operand is None:
                raise _err("errors.bad_filter_ip", field, term)
            version, num = operand.version, operand.num
            base = _compare_predicate(op, num)
            return ((lambda c: c is not None and c.version == version and base(c.num)),
                    ("ip_cmp", version, op, num))
    # CIDR
    if "/" in body:
        try:
            net = ipaddress.ip_network(body, strict=False)
        except (ValueError, TypeError):
            raise _err("errors.bad_filter_ip", field, term)
        lo = int(net.network_address)
        hi = int(net.broadcast_address)
        version = net.version
        return ((lambda c: c is not None and c.version == version and lo <= c.num <= hi),
                ("ip_range", version, lo, hi))
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
        return ((lambda c: c is not None and c.version == version and lo <= c.num <= hi),
                ("ip_range", version, lo, hi))
    # wildcard over the canonical text (IPv6 canonical form is lower-case)
    if _is_glob(body):
        pattern = body.lower()
        return ((lambda c: c is not None
                 and fnmatch.fnmatchcase(c.text.lower(), pattern)), None)
    # plain address
    literal = _as_ip(body)
    if literal is None:
        raise _err("errors.bad_filter_ip", field, term)
    num, version = literal.num, literal.version
    return ((lambda c: c is not None and c.version == version and c.num == num),
            ("ip_eq", version, num))


def _parse_process_term(body, term, field):
    """``(predicate, None)`` - a process term NEVER carries a shape.

    Not an oversight and not laziness: the shape exists only to compile a term
    into the driver's filter, and the NETWORK layer has no notion of a process.
    ``processId == 1234`` is rejected by ``WinDivertHelperCompileFilter`` with
    "bad token for layer" (checked 2026-07-28), so there is nothing a shape could
    ever be turned into here.
    """
    if body.lower().startswith(REGEX_PREFIX):
        rx = _compile_regex(body[len(REGEX_PREFIX):], field, term)
        return (lambda c: rx.search(c.name) is not None), None
    # comparison operators only make sense on a PID; on a name they are an error
    for op in OPERATORS:
        if body.startswith(op):
            operand = body[len(op):].strip()
            if not operand.isdigit():
                raise _err("errors.bad_filter_compare_name", field, term)
            base = _compare_predicate(op, int(operand))
            return (lambda c: c.pid is not None and base(c.pid)), None
    # numeric atoms (literal PID / PID range) reuse the int parser
    numeric = _parse_int_atom(body, term, field, None)
    if numeric is not None:
        predicate = numeric[0]
        return (lambda c: predicate(c.pid)), None
    # wildcard over the process name
    if _is_glob(body):
        pattern = body.lower()
        return (lambda c: fnmatch.fnmatchcase(c.name, pattern)), None
    # plain name: case-insensitive substring (historical behaviour - "chrome"
    # still finds "chrome.exe"); use a wildcard or re: when you need precision
    needle = body.lower()
    return (lambda c: needle in c.name), None


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
            predicate, shape = _parse_int_term(body, raw_term, field, bounds)
        elif kind == KIND_IP:
            predicate, shape = _parse_ip_term(body, raw_term, field)
        else:
            predicate, shape = _parse_process_term(body, raw_term, field)
        terms.append(_Term(raw_term, negated, predicate, shape))
    return cls(text, terms)


def validate_matcher(text, kind, field="fields.filter", bounds=None):
    """Parse and discard - raises the translated ``ValueError`` on bad input."""
    parse_matcher(text, kind, field, bounds)
    return True


# -- compiling an expression down into the DRIVER's own filter language ---------- #
#
# Why this is worth doing at all: with a destination target set, the tool still
# captures EVERYTHING and re-injects almost all of it untouched. Measured
# 2026-07-28: 1944 packets diverted, 0 of them impairable, and 1632 diverted with
# 8 impairable. Every one of those cost a recv plus a send for nothing. The
# WinDivert filter runs IN THE DRIVER, so an expression that can be compiled into
# it is traffic that never reaches this process in the first place.
#
# THE ONLY invariant that matters: the fragment must match AT LEAST everything the
# matcher matches. Over-capturing is free (decide() still filters); under-capturing
# is a silent regression - traffic the user asked to impair would never arrive, and
# every counter would read healthy. So anything that cannot be proven a superset
# returns None, and the caller keeps the wide filter.
#
# Three things make that provable rather than hopeful:
#   * only POSITIVE terms are compiled. Negatives are dropped, which only widens.
#   * a term with no ``shape`` (glob, ``re:``) makes the whole expression give up:
#     one unbounded member of an OR makes the OR unbounded.
#   * BOTH directions are emitted. This is the trap that nearly got through:
#     ``engine._capture_loop`` reads the remote endpoint as the DESTINATION on an
#     outbound packet and as the SOURCE on an inbound one, so a fragment testing
#     only ``DstAddr`` would have quietly stopped impairing everything coming back.

_WD_PORT_FIELDS = ("tcp.DstPort", "tcp.SrcPort", "udp.DstPort", "udp.SrcPort")
_WD_ADDR_FIELDS = {4: ("ip.DstAddr", "ip.SrcAddr"),
                   6: ("ipv6.DstAddr", "ipv6.SrcAddr")}


def _wd_address(version, num):
    return str(ipaddress.IPv4Address(num) if version == 4
               else ipaddress.IPv6Address(num))


def _wd_int_term(shape):
    kind = shape[0]
    if kind == "eq":
        return " or ".join("%s == %d" % (f, shape[1]) for f in _WD_PORT_FIELDS)
    if kind == "range":
        return " or ".join("(%s >= %d and %s <= %d)" % (f, shape[1], f, shape[2])
                           for f in _WD_PORT_FIELDS)
    if kind == "cmp":
        return " or ".join("%s %s %d" % (f, shape[1], shape[2])
                           for f in _WD_PORT_FIELDS)
    return None


def _wd_ip_term(shape):
    kind = shape[0]
    version = shape[1]
    fields = _WD_ADDR_FIELDS.get(version)
    if fields is None:                                   # pragma: no cover
        return None
    if kind == "ip_eq":
        value = _wd_address(version, shape[2])
        return " or ".join("%s == %s" % (f, value) for f in fields)
    if kind == "ip_range":
        lo, hi = _wd_address(version, shape[2]), _wd_address(version, shape[3])
        return " or ".join("(%s >= %s and %s <= %s)" % (f, lo, f, hi) for f in fields)
    if kind == "ip_cmp":
        value = _wd_address(version, shape[3])
        return " or ".join("%s %s %s" % (f, shape[2], value) for f in fields)
    return None


def windivert_fragment(matcher):
    """A driver-filter fragment matching AT LEAST everything ``matcher`` does.

    ``None`` when no narrowing can be proven - an empty expression, one made only
    of exclusions ("everything except X" is not a narrowing), or one containing a
    wildcard or ``re:`` pattern, which the driver's language cannot express.

    The result is deliberately free of address-dependent terms (``outbound``,
    ``loopback``): those live in ``WINDIVERT_ADDRESS`` rather than in the packet,
    so keeping them out is what lets the guard test evaluate this against
    synthetic packets and still mean something.

    The caller must still COMPILE the result before trusting it - the driver's
    parser has a length limit (200 ORed terms compile, 1000 do not, checked
    2026-07-28), and a fragment that will not compile has to fall back the same
    way an unprovable one does.
    """
    if matcher is None or getattr(matcher, "is_empty", True):
        return None
    positives = [t for t in matcher.terms if not t.negated]
    if not positives:
        return None
    emit = _wd_int_term if matcher.kind == KIND_INT else (
        _wd_ip_term if matcher.kind == KIND_IP else None)
    if emit is None:
        return None                     # process expressions: see _parse_process_term
    parts = []
    for term in positives:
        if term.shape is None:
            return None
        piece = emit(term.shape)
        if piece is None:               # pragma: no cover - shape kinds are closed
            return None
        parts.append("(%s)" % piece)
    return "(%s)" % " or ".join(parts)


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
