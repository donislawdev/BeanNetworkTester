"""Who is allowed to answer "which process owns this local port", and from where.

Two sides of the tool ask that question and they do NOT ask it the same way:

* the impairment **GATE** resolves against ONE table - the live SOCKET-event map
  in a real session (``engine._targeting_table``). ``ProcessTargeting.refresh``
  builds its port set from that table's snapshot and ``owner_targeted`` reads that
  table's ``pid_for``. Nothing else is consulted;
* the **DISPLAY** (the process and PID columns, the CSV export, the repro report,
  and the row actions that write a process NAME back into the target field) goes
  through ``engine._live_pid``, which asks the live map first and the POLLER
  second - and then the GUI has a third source of its own (``views.connection_proc``
  falling back to ``App.proc_map``).

So the display can name an owner the gate never saw. That is a real asymmetry and
it is the reason this file exists. What it is NOT is a guess about how much it
matters: MEASURED 2026-08-05 over five 20 s sessions with real traffic
(``internal_tools/probe_owner_source.py``), the live map answered 97.7-99.3% of
lookups, the poller answered alone for 0-3 ports per run, and in **every** one of
those the port had been closed or predated the watcher - a `CLOSE` event with no
`ADD`. The two sources never disagreed about a port the live map went on to learn
(`poller_agreed` and `poller_wrong` were 0 in all five runs).

The fallback is therefore kept: it names the LAST KNOWN owner of a port whose
socket has ended, which the live map deletes on purpose, and it was never
observed contradicting it. What is added is the guard, because the measurement is
a snapshot of today and the drift it would hide is silent - a row naming a
process the gate never impaired reads exactly like a tool that is not working.

The third test is the one that has to survive future sessions: a NEW caller of
``_live_pid`` that nobody thought about reddens it, which is the difference
between guarding the rule and guarding two examples (PROJECT_NOTES rule 2.6).
"""
import ast
import os

import bean_network_tester as bnt
from beantester.engine import BeanEngine
from beantester.targeting import ProcessTargeting
from fakes import ROOT, check

LIVE_PID, POLLER_PID, PORT = 100, 200, 51000

# Every consumer of "who owns this port", and which SOURCE it is allowed to use.
# The scan at the bottom checks this list against the code, so a consumer added
# without a decision about its source cannot slip in silently.
GATE_CONSUMERS = ("owner_targeted", "__contains__")
DISPLAY_CONSUMERS = ("_process_for", "_pid_for")


class _Names:
    def name_of(self, pid, cheap=False):
        return {LIVE_PID: "chrome.exe", POLLER_PID: "svchost.exe"}.get(pid, "")

    def ancestors(self, pid, depth=8):
        return []


class _Table(_Names):
    """The read surface both a SocketWatcher and a PortTable expose."""

    def __init__(self, ports):
        self._ports = dict(ports)

    def snapshot(self):
        return dict(self._ports)

    def pid_for(self, port):
        return self._ports.get(port)

    def refresh(self, now=None, force=False):
        return False


def _engine(live, poller):
    engine = BeanEngine(log_fn=lambda _line: None)
    engine._socketwatch = _Table(live)
    engine._ports = _Table(poller)
    return engine


def _gate(table):
    targeting = ProcessTargeting(bnt.parse_target("chrome"), table=table)
    targeting.refresh()
    return targeting


def test_the_gate_and_the_display_agree_whenever_the_live_map_knows_the_port():
    """The ordinary case, and the one that must never drift.

    The live map names chrome; the poller names something else for the SAME port
    (which is what a stale snapshot looks like). Every consumer must come back
    with the live map's answer - the display included, or a row would name the
    process the gate did NOT impair while the map was saying otherwise.
    """
    live, poller = {PORT: LIVE_PID}, {PORT: POLLER_PID}
    engine = _engine(live, poller)
    targeting = _gate(_Table(live))

    check("gate: owner_targeted follows the live map", targeting.owner_targeted(PORT))
    check("gate: the resolved port set contains it", PORT in targeting)
    check("display: the pid column is the live map's",
          engine._pid_for(PORT) == LIVE_PID, f"({engine._pid_for(PORT)})")
    check("display: the process column is the live map's",
          engine._process_for(PORT) == "chrome.exe", f"({engine._process_for(PORT)!r})")


def test_the_display_still_names_a_port_the_live_map_has_forgotten():
    """The asymmetry, asserted rather than left implicit.

    A socket that closed - or that was open before the watcher started - is gone
    from the live map by design, and the poller still has it. The gate says "not
    mine", because it cannot say anything else; the display says who it was.
    MEASURED: this is the ONLY shape the fallback was ever seen answering for.
    """
    live, poller = {}, {PORT: POLLER_PID}
    engine = _engine(live, poller)
    targeting = _gate(_Table(live))

    check("gate: an unknown port is not targeted", not targeting.owner_targeted(PORT))
    check("gate: and it is not in the resolved set", PORT not in targeting)
    check("display: falls back to the poller's answer",
          engine._pid_for(PORT) == POLLER_PID, f"({engine._pid_for(PORT)})")
    check("display: and names it", engine._process_for(PORT) == "svchost.exe",
          f"({engine._process_for(PORT)!r})")


def test_the_fallback_is_never_preferred_over_the_live_map():
    """Order, not merely presence.

    ``_live_pid`` asking the poller FIRST would pass the test above and reverse
    the tool's whole attribution story - the poller is a snapshot taken a few
    times a second, and the live map is what the gate uses.
    """
    engine = _engine({PORT: LIVE_PID}, {PORT: POLLER_PID})
    check("the live map wins when both answer", engine._live_pid(PORT) == LIVE_PID,
          f"({engine._live_pid(PORT)})")

    engine_without_watcher = _engine({}, {PORT: POLLER_PID})
    engine_without_watcher._socketwatch = None
    check("with no watcher at all the poller still answers "
          "(--simulate and the no-WinDivert path)",
          engine_without_watcher._live_pid(PORT) == POLLER_PID)


def test_every_consumer_of_the_owner_lookup_is_one_this_file_knows_about():
    """The guard that has to outlive this session.

    A fifth consumer of ``_live_pid`` - a new column, an export, a decision - would
    inherit the fallback silently, and the failure it can produce (a row naming a
    process nothing impaired) is exactly the report this work started from. Read
    off the SOURCE, so adding one without a line here goes red.
    """
    path = os.path.join(ROOT, "beantester", "engine.py")
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    callers = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "_live_pid"):
                callers.add(node.name)
    check("the scan found the lookup at all (an empty scan passes everything)",
          callers, f"{callers}")
    check("every caller of _live_pid has a declared source",
          callers == set(DISPLAY_CONSUMERS),
          f"(found {sorted(callers)}, declared {sorted(DISPLAY_CONSUMERS)}) - "
          "a new consumer inherits the poller fallback; decide about it here")


def test_the_gate_resolves_against_exactly_one_table():
    """The other half of the same rule, from the gate's side.

    ``ProcessTargeting`` must keep asking ONE table. If it ever grew a fallback of
    its own the two sides would converge by accident, and the day one of them was
    changed back nothing would notice.
    """
    live = {PORT: LIVE_PID}
    targeting = _gate(_Table(live))
    check("the gate reads the table it was given", targeting.owner_targeted(PORT))

    # The process-wide poller is made to ANSWER for this port, so a fallback would
    # be visible. Without this the check was vacuous and a mutation proved it: the
    # real default table returns None for an unused port, so a gate that had
    # quietly grown a fallback looked identical to one that had not.
    from beantester import portmap
    real_default = portmap.default_table
    portmap.default_table = lambda: _Table({PORT: LIVE_PID})
    try:
        targeting.set_table(_Table({}))
        check("swap the table and the gate loses the port "
              "(no second source underneath, not even the process-wide poller)",
              not targeting.owner_targeted(PORT))
    finally:
        portmap.default_table = real_default

    for name in GATE_CONSUMERS:
        check(f"the gate still exposes {name}", hasattr(ProcessTargeting, name))
