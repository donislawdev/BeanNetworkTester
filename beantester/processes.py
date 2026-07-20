"""Process <-> port lookups.

The target expression is compiled by :mod:`beantester.matchers`, so a single
field accepts names, PIDs, lists, ranges, comparisons, wildcards, ``re:``
patterns and ``!`` exclusions.

The actual resolution lives in :mod:`beantester.targeting` (a *live* port set
that refreshes itself and follows process trees) on top of
:mod:`beantester.portmap` (the fast socket table). This module keeps the small,
stable API the GUI, the CLI and the settings layer have always used.
"""
from . import crashlog, portmap
from .matchers import KIND_PROCESS, Matcher, parse_matcher
from .targeting import NO_PROCESS, ProcessTargeting, resolve_ports

TARGET_FIELD = "fields.target_process"


def parse_target(expr):
    """Compile a target-process expression (translated ``ValueError`` if bad)."""
    return parse_matcher(expr, KIND_PROCESS, TARGET_FIELD)


def compile_target(expr):
    """Expression (or an already compiled matcher) -> ``Matcher``."""
    return expr if isinstance(expr, Matcher) else parse_target(expr)


def make_targeting(expr, table=None):
    """Build the live :class:`~beantester.targeting.ProcessTargeting` for ``expr``.

    Returns ``None`` for an empty expression ("no targeting" = every packet is
    a candidate).
    """
    matcher = compile_target(expr)
    if matcher.is_empty:
        return None
    targeting = ProcessTargeting(matcher, table=table)
    targeting.refresh()
    return targeting


def find_process_ports(target):
    """Return ``(port_set, description)`` for every process matching ``target``.

    A snapshot, for reporting - the engine gets the live object instead
    (``make_targeting``). Matching follows the process TREE: a socket counts
    when its owner or any of its ancestors matches, unless the owner itself is
    explicitly excluded.
    """
    matcher = compile_target(target)
    if matcher.is_empty:
        return set(), NO_PROCESS
    return resolve_ports(matcher)


def port_process_map():
    """Best-effort map of local port -> process name (empty when unavailable)."""
    table = portmap.default_table()
    # Best-effort stays best-effort for the CALLER (an empty map just means the
    # process column shows "?"), but the failure itself is recorded: a lookup that
    # silently stops working looked identical to a machine with nothing to report.
    with crashlog.quiet("processes.port_map"):
        table.refresh_if_stale()
        return {port: (table.name_of(pid) or str(pid))
                for port, pid in table.snapshot().items()}
    return {}
