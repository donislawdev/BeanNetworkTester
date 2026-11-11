"""The CSV exports: the appended session stats, and the connection and socket
snapshots.

Carved out of ``gui/app.py`` when it sat at the size ceiling (convention 32b says
split rather than raise the number). They still read the App - the engine snapshot,
the current view, the log - so they take it as an argument instead of pretending to
be independent, and ``App.export_csv`` / ``App.export_connections_csv`` stay as the
names every caller already uses.

The column tables live here too, and they are the source the README guard reads.
"""
import csv
import os
import tempfile
import threading
import time

from .. import crashlog
from ..i18n import T
from ..paths import CONNECTIONS_CSV_FILE, CSV_FILE, SOCKETS_CSV_FILE, hand_back
from ..views import (avg_packet_bytes, connection_proc, filter_sort_connections,
                     scoped_packets)

# Internal stat keys are engine-speak ("seen"); a CSV is read by people and
# by spreadsheets, so it gets column names that mean something.
CSV_COLUMNS = {"seen": "packets_seen", "scoped_seen": "packets_in_scope",
               "drop_loss": "dropped_loss", "loss_bursts": "loss_runs",
               "reordered": "packets_reordered",
               "drop_overflow": "dropped_overflow", "drop_syn": "dropped_syn",
               "drop_mtu": "dropped_mtu", "drop_nat": "dropped_nat",
               "drop_rst": "dropped_rst", "rst_reset": "connections_reset",
               # Next to connections_reset on purpose, and named apart from it: one
               # is a conversation cut off mid-flight, the other a connection that
               # was never allowed to start.
               "block_rejected": "connections_refused",
               "drop_lan": "dropped_lan",
               "drop_internet_only": "dropped_local_network",
               "drop_block": "dropped_block",
               "drop_flap": "dropped_link_outage", "flap_held": "held_link_outage",
               "drop_rate": "dropped_rate_limit",
               "drop_shutdown": "dropped_at_stop",
               "drop_send": "dropped_send_failed",
               "queue": "queue_len",
               "peak_queue": "queue_peak",
               # The stats CSV deliberately does NOT follow the "show only the
               # targeted traffic" preference: it is an APPEND log, and a file
               # whose columns mean one thing in some rows and another in the
               # rest is worse than useless for the spreadsheet it exists for.
               # It gains both totals instead, so the reader can do the
               # narrowing themselves and see which is which.
               "bytes_in_scoped": "delivered_in_scope_bytes_down",
               "bytes_out_scoped": "delivered_in_scope_bytes_up"}

# Columns that come from the SESSION rather than the counters: they say which
# world the counters were measured in. The comment above explains why this
# file must not follow the view preference - a column meaning one thing in
# some rows and another in the rest is useless to the spreadsheet it exists
# for. Capture narrowing is the STRONGER version of that problem and had no
# column at all: it does not pick between two totals, it changes `seen`
# itself, so a narrowed row and a wide row were indistinguishable while
# counting completely different traffic. The CLI has carried the same fact in
# its JSON summary (`capture_narrowed`) since narrowing shipped, and the repro
# report carries the whole `session_info` - only this file could not say.
# Keyed by session_info() key, like CSV_COLUMNS is keyed by counter key.
CSV_SESSION_COLUMNS = {"narrowed": "capture_narrowed"}


def session_value(key, info):
    """One session cell. Booleans as yes/no in English, like `impaired` in the
    connections export - a CSV is read by scripts and spreadsheets, so it does
    not follow the interface language."""
    value = info.get(key)
    return ("yes" if value else "no") if isinstance(value, bool) else value


# A cell a spreadsheet would run instead of showing. Excel and LibreOffice treat a
# cell starting with one of these as a FORMULA, and this program writes strings it
# did not choose: a process name comes from the filesystem, and `=cmd.exe` or
# `=HYPERLINK("http://...")` are legal Windows file names. The CSV is written to be
# shared - it goes into bug reports and measurements - so the person who opens it is
# usually not the person whose machine produced it. CWE-1236.
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def formula_safe(value):
    """One data cell, with a leading apostrophe when a spreadsheet would run it.

    Only strings are touched, which is what keeps the numeric columns numeric: the
    writers below pass ints and floats as ints and floats, so a negative NUMBER
    never reaches this and never turns into text. Header rows are deliberately not
    passed through here either - the stats file compares the header it finds on
    disk against the one it would write, and quoting one side of that comparison
    would rotate the file on every append.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_LEAD):
        return "'" + value
    return value


def export_stats(app):
    snap = app.engine.stats_snapshot()
    info = app.engine.session_info()
    session_cells = [session_value(k, info)
                     for k in CSV_SESSION_COLUMNS]
    header = ["time", *CSV_SESSION_COLUMNS.values(),
              *(CSV_COLUMNS.get(k, k) for k in snap)]
    try:
        write_header = not os.path.exists(CSV_FILE)
        if not write_header:
            with open(CSV_FILE, newline="", encoding="utf-8") as f:
                existing = next(csv.reader(f), [])
            if existing != header:
                # the stat columns changed between versions: appending would
                # silently misalign rows against the old header
                backup = CSV_FILE[:-4] + time.strftime(".%Y%m%d-%H%M%S.csv")
                os.replace(CSV_FILE, backup)
                app.log(f"{T('log.csv_rotated')} {os.path.basename(backup)}")
                write_header = True
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(header)
            writer.writerow([formula_safe(v) for v in
                             (time.strftime("%Y-%m-%d %H:%M:%S"),
                              *session_cells, *snap.values())])
        hand_back(CSV_FILE)             # a window run with sudo: the file stays theirs
        # The WHOLE path, not just the file name: these files no longer sit next to
        # the executable, so the name alone would leave the user hunting for them.
        app.log(f"{T('log.stats_saved_to')} {CSV_FILE}")
    except Exception as e:
        app.log(f"{T('log.csv_error')}: {e}")

# Mirrors the table's columns so the export is the table, on disk. Raw bytes,
# not KB: a CSV is read by a spreadsheet or a script, where exact, summable
# integers beat the one-decimal KB the table shows for people. `impaired` is
# "yes"/"no" in English, like the headers - the CSV is language-independent.
# delivered_* is what reached the application; captured_* is what the tool
# saw offered. The old download_bytes/upload_bytes/total_bytes held CAPTURED
# under names every other surface uses for delivered, so they are renamed
# rather than reused - a column that quietly changes meaning is worse than one
# that disappears.
CONN_CSV_HEADER = ["process", "pid", "proto", "remote_ip", "remote_port",
                   "local_port", "packets", "impaired", "dropped",
                   "delivered_down_bytes", "delivered_up_bytes",
                   "delivered_total_bytes",
                   "captured_down_bytes", "captured_up_bytes",
                   "captured_total_bytes",
                   "avg_bytes", "duration_s", "idle_s",
                   # LAST, not beside "proto" where the table shows it: a reader that
                   # takes the columns by position keeps working (owner, 2026-11-04)
                   "ice",
                   # after it for the same reason. "impaired" keeps its yes/no (any
                   # packet in scope): a third value there would change what an
                   # existing reader of that column gets
                   "packets_in_scope"]


# One export at a time, and the thing being protected is the FILE, not the window:
# `CONNECTIONS_CSV_FILE` is one fixed path, so two windows would collide on it as
# surely as two clicks. Module scope is therefore right rather than lazy.
_EXPORT_LOCK = threading.Lock()


def export_connections(app):
    """Write the CURRENT connection view (search + sort) to a CSV snapshot.

    The display row-limit is a rendering cap, not part of what the user asked
    to see, so the export carries every filtered row - sorted the same way the
    table is. The file is overwritten atomically each time (tmp + os.replace):
    it is a snapshot of "the connections as they are now", not an append log
    like the stats CSV.

    OFF THE UI THREAD, because everything after the snapshot is unbounded work on
    a table that may hold 200 000 flows: a full filter and sort with no row cap,
    then a row-by-row CSV write. This is the one path that stayed on the UI thread
    after `gui/model_worker.py` moved the table's own rebuild off it, and its
    docstring says why that matters - a frozen window is a STOP button the user
    cannot press, on a machine whose networking they have deliberately broken.

    What is read from the App is read HERE, on the UI thread, and handed over as
    plain data - the same shape `ConnsPage.refresh` uses. The worker touches no
    widget. It calls `app.log`, which is thread-safe by contract.

    Returns the worker thread so a caller that needs the file on disk before it
    goes on can join it. The GUI does not. ``None`` back means an export was
    already running and this click was refused.
    """
    if not _EXPORT_LOCK.acquire(blocking=False):
        # Two clicks, one file. Refusing out loud beats two workers racing to
        # `os.replace` the same path, where the winner is whichever finishes last.
        app.log(T("log.conns_export_busy"))
        return None
    try:
        payload = _connections_payload(app)
    except BaseException:
        _EXPORT_LOCK.release()
        raise
    worker = threading.Thread(target=_write_connections, args=(app, payload),
                              name="conns-csv", daemon=True)
    worker.start()
    return worker


def _connections_payload(app):
    """UI thread: everything the writer needs, as plain data."""
    now = app.engine.now_ref()
    snapshot = app.engine.connections_snapshot(limit=None)
    # The export follows the view: what you exported and what you were looking
    # at have to be the same set, or the file quietly disagrees with the screen
    # that produced it.
    if app.scoped_view():
        snapshot = [c for c in snapshot if c.get("scoped")]
    return {"now": now, "snapshot": snapshot, "query": app.conn_query,
            "sort": dict(app.conn_sort), "proc_map": app.proc_map}


def _write_connections(app, payload):
    """Worker thread: filter, sort and write. Touches no widget."""
    try:
        _write_connections_now(app, payload)
    finally:
        _EXPORT_LOCK.release()


def _write_connections_now(app, payload):
    now, proc_map = payload["now"], payload["proc_map"]
    rows = filter_sort_connections(
        payload["snapshot"], payload["query"],
        payload["sort"]["col"], payload["sort"]["reverse"],
        now=now, proc_map=proc_map, limit=0)
    path = CONNECTIONS_CSV_FILE
    try:
        _replace_csv(path, CONN_CSV_HEADER, (_connection_cells(c, now, proc_map) for c in rows))
    except Exception as e:
        crashlog.note(e, "gui.csv_export")
        app.log(f"{T('log.csv_error')}: {e}")
        return
    app.log(f"{T('log.conns_saved_to')} {path} ({len(rows)})")


def _connection_cells(c, now, proc_map):
    """One connection's cells, in ``CONN_CSV_HEADER`` order."""
    last = c.get("last", now)
    packets = c.get("packets", 0) or 0
    return [formula_safe(v) for v in (
        connection_proc(c, proc_map) or "?",
        c.get("pid") or "",
        c.get("proto", "IP"), c.get("remote_ip", ""),
        c.get("remote_port", ""), c.get("local_port", ""),
        packets, "yes" if c.get("scoped") else "no",
        c.get("dropped", 0),
        c.get("sent_in", 0), c.get("sent_out", 0), c.get("sent", 0),
        c.get("bytes_in", 0), c.get("bytes_out", 0), c.get("bytes", 0),
        avg_packet_bytes(c),
        f"{max(0.0, last - c.get('first', now)):.1f}",
        f"{max(0.0, now - last):.1f}",
        c.get("ice") or "", scoped_packets(c))]


def _replace_csv(path, header, rows):
    """Put a CSV of ``header`` and ``rows`` at ``path`` whole, or leave the one
    there as it was. Raises what went wrong, with nothing left behind.

    The connections and sockets exports' one write. A file beside the real one,
    renamed over it once written - under a name nobody else picks (``mkstemp``:
    made by this call, never a link someone put there) and written through the
    descriptor that made it, never opened again by name. The old ``<file>.tmp``
    was a name known in advance: a link put there by anyone who may write in that
    folder sent the write - root's, under sudo - wherever it pointed. Handed back
    under sudo before it takes the place of the person's file (``hand_back``,
    which changes the entry, never what a link there points at). The previous
    export is untouched by a failure: a half-written file left beside it was the
    connections export's litter for a while, overwritten by the next export.
    """
    directory, name = os.path.split(path)
    handle, tmp = tempfile.mkstemp(dir=directory or ".", prefix=name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
        hand_back(tmp)
        os.replace(tmp, path)
    except BaseException:
        with crashlog.quiet("gui.csv_export"):
            os.remove(tmp)
        raise


# The socket table (Tools > Sockets), its columns in the table's own words where
# a spreadsheet can take them: times as "YYYY-MM-DD HH:MM:SS" in this computer's
# time zone, `change` as the program's own "new" / "closed" (English, like the
# connections export's yes/no). `opened` is when the socket was bound, as the
# system says it - empty on Linux, which does not say.
SOCKETS_CSV_HEADER = ["process", "service", "pid", "proto", "local_ip", "local_port",
                      "remote_ip", "remote_port", "state", "opened", "change", "changed_at"]

# One export of the socket table at a time - its own file, so its own lock.
_SOCKETS_LOCK = threading.Lock()


def export_sockets(app, rows):
    """Write the socket table's rows - as the window shows them: its search, its
    "Show" and its order - to their CSV, overwritten each time like the connections
    snapshot, and on a worker for its reason. ``rows`` are the window's own
    ``nettools.sockets.Socket`` values, which nothing changes once made, so they
    are handed over as they are. Returns the worker, or None when an export was
    already running."""
    if not _SOCKETS_LOCK.acquire(blocking=False):
        app.log(T("log.conns_export_busy"))
        return None
    try:
        worker = threading.Thread(target=_write_sockets, args=(app, list(rows)),
                                  name="sockets-csv", daemon=True)
        worker.start()
    except BaseException:
        _SOCKETS_LOCK.release()
        raise
    return worker


def _stamp(at):
    return "" if at is None else time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at))


def _socket_cells(s):
    """One socket's cells, in ``SOCKETS_CSV_HEADER`` order."""
    return [formula_safe(v) for v in (
        s.proc, s.service, "" if s.pid is None else s.pid, s.proto,
        s.local_ip, s.local_port, s.remote_ip,
        "" if s.remote_port is None else s.remote_port, s.state,
        _stamp(s.created), s.change, _stamp(s.at))]


def _write_sockets(app, rows):
    """Worker thread: the connections snapshot's write (``_replace_csv``), so a
    failure leaves the previous export whole."""
    path = SOCKETS_CSV_FILE
    try:
        _replace_csv(path, SOCKETS_CSV_HEADER, (_socket_cells(s) for s in rows))
        app.log(f"{T('log.sockets_saved_to')} {path} ({len(rows)})")
    except Exception as e:
        crashlog.note(e, "gui.csv_export")
        app.log(f"{T('log.csv_error')}: {e}")
    finally:
        _SOCKETS_LOCK.release()
