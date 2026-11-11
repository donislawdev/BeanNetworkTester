"""Filling a Control-page field from somewhere else in the window.

Three places do this today - the right-click menus of the connection table and
of the socket table on the Tools tab (block this address, leave this process
alone) and the expression tester - and all must travel the SAME road into the
form, or one of them will eventually skip a step the others take: the tk
variable, the form's own copy of the values, the dirty-state and summary refresh
(``on_form_changed``), the log line, and - during a session - the reminder that
nothing reaches the engine until the user presses Apply (convention 15).

It lives outside ``gui/app.py`` for the reason written in several places there:
that file sits on the size ratchet in ``tests/test_code_shape.py``. And outside
``gui/pages/conns.py``, where it was born, because a tool panel importing a PAGE
to reach a helper would be a sideways dependency between two things that should
not know about each other. The row actions themselves (what "block this address"
MEANS) live here for the same reason: two tables offer them. So does "Reset this
connection", born on the Connections page and offered by the socket table too: one
rule for which rows it acts on, one worker, one sentence for each way it ends.
"""
import sys
import threading

from .. import capabilities, tcpreset
from ..i18n import T
from ..matchers import add_term


def fill_field(app, key, value, log_key, **fmt):
    """Put ``value`` into the Control field ``key``, replacing what was there."""
    app.vars[key].set(value)
    app.form.set_values(app._settings_for_form())
    app.on_form_changed()
    app.log(f"{T(log_key, **fmt)}: {value}")
    if app.running:
        app.log(T("log.apply_needed"))


def append_to_field(app, key, term, log_key):
    """Add one term to an expression field, keeping what is already there.

    The row actions build a field up click by click - block this address, then
    that one - so they append. Replacing would throw away what the previous click
    put there, which is the opposite of what the second click means.
    ``matchers.add_term`` owns the syntax (convention 10): it drops repeats, keeps
    the comma escape of a regex intact and never leaves an empty term behind.
    """
    fill_field(app, key, add_term(app.vars[key].get(), term), log_key)


def block_ip_address(app, ip):
    """Add an address to the blocking field (decision pipeline step 2c)."""
    if str(ip or "").strip():
        append_to_field(app, "block_ip", str(ip).strip(), "log.block_ip_added")


def leave_process_alone(app, name):
    """Exclude a process from impairment by adding ``!name`` to the target.

    With a target already set this narrows it. With the target EMPTY it turns
    "impair everything" into "impair everything except this one", because a bare
    negative means exactly that in this expression language - and that is the case
    the menu entry is really for.
    """
    name = str(name or "").strip()
    if not name or name == "?":
        app.log(T("log.no_process_for_row"))
        return
    append_to_field(app, "target", f"!{name}", "log.process_excluded")


# What the log says for each way "Reset this connection" can end (tcpreset.Outcome).
RESET_LOG = {tcpreset.RESET: "log.conn_reset_done", tcpreset.GONE: "log.conn_reset_gone",
             tcpreset.AMBIGUOUS: "log.conn_reset_ambiguous",
             tcpreset.REFUSED: "log.conn_reset_refused",
             tcpreset.NEEDS_ADMIN: "log.conn_reset_needs_admin",
             tcpreset.UNREADABLE: "log.conn_reset_unreadable",
             tcpreset.NOT_IPV4: "log.conn_reset_not_ipv4",
             tcpreset.FAILED: "log.conn_reset_failed"}
# Where Linux's words differ: its rights are root's, the rule on states is this
# program's own (tcpreset.RESETS), and a socket missing from the kernel's list may
# belong to a container or another network namespace, not only to the past.
RESET_LOG_LINUX = {**RESET_LOG, tcpreset.GONE: "log.conn_reset_gone_linux",
                   tcpreset.REFUSED: "log.conn_reset_refused_linux",
                   tcpreset.NEEDS_ADMIN: "log.conn_reset_needs_root"}


def reset_log(platform=None):
    """The sentence for each way a reset can end, on this system or ``platform``."""
    return RESET_LOG_LINUX if (platform or sys.platform).startswith("linux") else RESET_LOG


def can_reset(row):
    """Whether "Reset this connection" acts on ``row``: TCP over the families this
    system resets - IPv4 on Windows, which has no IPv6 form of the call, IPv4 and IPv6
    on Linux (tcpreset) - and nothing at all on a system without it (capabilities).
    The menu greys the entry out by it, and the entry's command refuses by it, so the
    two cannot answer differently."""
    return capabilities.available("tcp_reset") and tcpreset.resettable(
        row.get("proto"), row.get("remote_ip"))


def reset_connection(app, row):
    """Reset the connection a row names: the row is read HERE, as plain data, and
    the reset runs on a worker - it reads the socket table - which says how it ended
    in one log line (``app.log`` is thread-safe; the same shape as
    ``csv_export.export_connections``). Returns the worker, or None for a row with
    no ports to reset."""
    try:
        target = tcpreset.Target(int(row["local_port"]), str(row["remote_ip"]),
                                 int(row["remote_port"]))
    except (KeyError, TypeError, ValueError):
        return None
    worker = threading.Thread(target=_reset_and_say, args=(app, target),
                              name="conn-reset", daemon=True)
    worker.start()
    return worker


def _reset_and_say(app, target):
    outcome = tcpreset.reset(target)
    app.log(T(reset_log().get(outcome.kind, "log.conn_reset_failed"),
              address=f"{target.remote_ip}:{target.remote_port}", state=outcome.state or "?",
              code=outcome.code, detail=outcome.detail))
