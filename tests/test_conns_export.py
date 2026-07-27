"""The two CSV exports: the connection snapshot (App.export_connections_csv) and
the appended session stats (App.export_csv).

Nothing exercised either export before this. The connection export is guarded so its
contract - the columns mirroring the table, the raw byte split, and honouring the
current search and sort - cannot silently drift. The stats export is guarded for its
append-and-rotate behaviour: a changed column set must roll the old file aside instead
of misaligning rows against a stale header.
"""
from gui_harness import run_gui


def test_export_connections_csv_writes_the_current_view():
    run_gui('''
        import os, tempfile, csv
        import beantester.gui.app as m
        path = os.path.join(tempfile.mkdtemp(), "conns.csv")
        m.CONNECTIONS_CSV_FILE = path

        app.engine.now_ref = lambda: 10.0
        app.engine.connections_snapshot = lambda limit=None: [
            # chrome was impaired: it offered 2048 down and only 1024 arrived
            dict(local_port=51000, remote_ip="1.1.1.1", remote_port=443, proto="TCP",
                 packets=4, bytes=3072, bytes_in=2048, bytes_out=1024,
                 sent=2048, sent_in=1024, sent_out=1024, dropped=3,
                 scoped=True, pid=1234, first=2.0, last=9.0, dir="in", proc="chrome.exe"),
            # svchost was untouched: delivered == captured
            dict(local_port=51001, remote_ip="8.8.8.8", remote_port=53, proto="UDP",
                 packets=2, bytes=600, bytes_in=100, bytes_out=500,
                 sent=600, sent_in=100, sent_out=500, dropped=0,
                 scoped=False, pid=None, first=5.0, last=8.0, dir="out", proc="svchost.exe"),
        ]
        app.conn_query = ""
        app.conn_sort = {"col": "up", "reverse": True}     # sort by upload, desc
        app.export_connections_csv()

        rows = list(csv.reader(open(path, newline="", encoding="utf-8")))
        # the header mirrors the table's columns
        assert rows[0] == ["process", "pid", "proto", "remote_ip", "remote_port",
                           "local_port", "packets", "impaired", "dropped",
                           "delivered_down_bytes", "delivered_up_bytes",
                           "delivered_total_bytes",
                           "captured_down_bytes", "captured_up_bytes",
                           "captured_total_bytes",
                           "avg_bytes", "duration_s", "idle_s"], rows[0]
        # sorted by delivered upload desc: chrome (1024) before svchost (500)
        assert rows[1][0] == "chrome.exe" and rows[2][0] == "svchost.exe", rows
        chrome, svc = rows[1], rows[2]
        assert chrome[1] == "1234", chrome            # pid
        assert chrome[7] == "yes" and chrome[8] == "3", chrome   # impaired, dropped
        assert svc[1] == "" and svc[7] == "no" and svc[8] == "0", svc
        # delivered first, then captured - and for chrome they DIFFER, which is
        # the whole point: 2048 B were offered downstream, 1024 B arrived
        assert chrome[9:12] == ["1024", "1024", "2048"], chrome
        assert chrome[12:15] == ["2048", "1024", "3072"], chrome
        # an untouched flow has the two pairs equal
        assert svc[9:12] == ["100", "500", "600"], svc
        assert svc[12:15] == ["100", "500", "600"], svc
        # avg_bytes is CAPTURED bytes per captured packet (3072 / 4 = 768)
        assert chrome[15] == "768", chrome
        assert chrome[16] == "7.0" and chrome[17] == "1.0", chrome
        # atomic overwrite leaves no temp file behind
        assert not os.path.exists(path + ".tmp")
    ''')


def test_a_failed_connections_export_leaves_no_tmp_file_behind():
    """The export writes `<file>.tmp` and renames it. When the write blew up, the
    temp file stayed on disk next to the real one for the user to find and wonder
    about - and the next export silently overwrote it, so the litter was not even
    stable. `jsonfile.write_json` has cleaned up after itself for a while; this is
    the same guarantee for the same reason.

    The failure is forced from inside the row loop (a row whose timestamps cannot
    be subtracted), so the temp file definitely exists by the time it happens.
    """
    run_gui('''
        import os, tempfile
        import beantester.gui.app as m
        path = os.path.join(tempfile.mkdtemp(), "conns.csv")
        m.CONNECTIONS_CSV_FILE = path

        app.engine.now_ref = lambda: 10.0
        app.engine.connections_snapshot = lambda limit=None: [
            dict(local_port=51000, remote_ip="1.1.1.1", remote_port=443, proto="TCP",
                 packets=4, bytes=3072, bytes_in=2048, bytes_out=1024, dropped=0,
                 scoped=False, pid=None, first="not a number", last="boom",
                 dir="in", proc="chrome.exe"),
        ]
        app.conn_query = ""
        app.conn_sort = {"col": "packets", "reverse": True}
        app.export_connections_csv()

        assert not os.path.exists(path + ".tmp"), "a half-written .tmp was left behind"
        assert not os.path.exists(path), "a failed export must not create the real file"
        assert any("csv" in line.lower() or "błąd" in line.lower()
                   for line in app._log_lines), app._log_lines[-3:]
    ''')


def test_export_connections_csv_writes_a_portless_row_with_empty_port_cells():
    """A ping row reaches the export with both ports None. The columns must come
    out EMPTY, not "None" and not shifted - a misaligned row here is silent."""
    run_gui('''
        import os, tempfile, csv
        import beantester.gui.app as m
        path = os.path.join(tempfile.mkdtemp(), "conns.csv")
        m.CONNECTIONS_CSV_FILE = path

        app.engine.now_ref = lambda: 10.0
        app.engine.connections_snapshot = lambda limit=None: [
            dict(local_port=None, remote_ip="8.8.8.8", remote_port=None, proto="ICMP",
                 packets=6, bytes=588, bytes_in=294, bytes_out=294, dropped=0,
                 scoped=True, pid=None, first=2.0, last=9.0, dir="out", proc=""),
        ]
        app.conn_query = ""
        app.conn_sort = {"col": "packets", "reverse": True}
        app.export_connections_csv()

        rows = list(csv.reader(open(path, newline="", encoding="utf-8")))
        assert len(rows) == 2, rows
        row = rows[1]
        assert len(row) == len(rows[0]), ("row is misaligned against the header", row)
        assert row[2] == "ICMP", row
        assert row[4] == "" and row[5] == "", ("port cells must be empty", row)
        assert "None" not in row, row
        assert row[6] == "6", row                    # packets still line up after them
    ''')


def test_export_connections_csv_honours_the_search():
    run_gui('''
        import os, tempfile, csv
        import beantester.gui.app as m
        path = os.path.join(tempfile.mkdtemp(), "conns.csv")
        m.CONNECTIONS_CSV_FILE = path

        app.engine.now_ref = lambda: 10.0
        app.engine.connections_snapshot = lambda limit=None: [
            dict(local_port=1, remote_ip="1.1.1.1", remote_port=443, proto="TCP",
                 packets=1, bytes=10, bytes_in=10, bytes_out=0,
                 first=0.0, last=1.0, dir="in", proc="chrome.exe"),
            dict(local_port=2, remote_ip="8.8.8.8", remote_port=53, proto="UDP",
                 packets=1, bytes=10, bytes_in=0, bytes_out=10,
                 first=0.0, last=1.0, dir="out", proc="svchost.exe"),
        ]
        app.conn_query = "chrome"                          # only one row matches
        app.conn_sort = {"col": "up", "reverse": True}
        app.export_connections_csv()

        rows = list(csv.reader(open(path, newline="", encoding="utf-8")))
        assert len(rows) == 2, rows            # header + the single matching row
        assert rows[1][0] == "chrome.exe", rows
    ''')


def test_export_connections_csv_avg_matches_the_table_rounding():
    """Regression: the avg column floored in the CSV but rounded in the table.

    A flow at 3070 B over 4 packets is 767.5 B/pkt: the table showed 768, the
    export wrote 767. Both now round through ``views.avg_packet_bytes``.
    """
    run_gui('''
        import os, tempfile, csv
        import beantester.gui.app as m
        from beantester.views import avg_packet_bytes
        path = os.path.join(tempfile.mkdtemp(), "conns.csv")
        m.CONNECTIONS_CSV_FILE = path

        app.engine.now_ref = lambda: 10.0
        row = dict(local_port=1, remote_ip="1.1.1.1", remote_port=443, proto="TCP",
                   packets=4, bytes=3070, bytes_in=3070, bytes_out=0,
                   first=0.0, last=1.0, dir="in", proc="chrome.exe")
        app.engine.connections_snapshot = lambda limit=None: [row]
        app.conn_query = ""
        app.conn_sort = {"col": "bytes", "reverse": True}
        app.export_connections_csv()

        rows = list(csv.reader(open(path, newline="", encoding="utf-8")))
        avg = rows[0].index("avg_bytes")
        assert rows[1][avg] == "768", rows[1]                 # rounded, not floored 767
        assert rows[1][avg] == str(avg_packet_bytes(row)), rows[1]
    ''')


def test_export_csv_stats_appends_then_rotates_on_a_column_change():
    run_gui('''
        import os, tempfile, csv
        import beantester.gui.app as m
        path = os.path.join(tempfile.mkdtemp(), "stats.csv")
        m.CSV_FILE = path

        # first two exports share a column set: header once, then two data rows
        app.engine.stats_snapshot = lambda: {"seen": 100, "drop_loss": 5, "queue": 2}
        app.export_csv()
        app.export_csv()
        rows = list(csv.reader(open(path, newline="", encoding="utf-8")))
        assert rows[0] == ["time", "packets_seen", "dropped_loss", "queue_len"], rows[0]
        assert len(rows) == 3, rows                      # header + two rows
        assert rows[1][1:] == ["100", "5", "2"], rows[1]

        # a changed column set must NOT append into the old header - it rolls the
        # old file aside and starts a fresh one
        app.engine.stats_snapshot = lambda: {"seen": 7, "corrupted": 3}
        app.export_csv()
        rows = list(csv.reader(open(path, newline="", encoding="utf-8")))
        assert rows[0] == ["time", "packets_seen", "corrupted"], rows[0]
        assert len(rows) == 2, rows                      # fresh header + one row
        backups = [n for n in os.listdir(os.path.dirname(path))
                   if n != "stats.csv" and n.endswith(".csv")]
        assert len(backups) == 1, backups                # the old file was kept aside
    ''')
