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
            dict(local_port=51000, remote_ip="1.1.1.1", remote_port=443, proto="TCP",
                 packets=4, bytes=3072, bytes_in=2048, bytes_out=1024, dropped=3,
                 scoped=True, pid=1234, first=2.0, last=9.0, dir="in", proc="chrome.exe"),
            dict(local_port=51001, remote_ip="8.8.8.8", remote_port=53, proto="UDP",
                 packets=2, bytes=600, bytes_in=100, bytes_out=500, dropped=0,
                 scoped=False, pid=None, first=5.0, last=8.0, dir="out", proc="svchost.exe"),
        ]
        app.conn_query = ""
        app.conn_sort = {"col": "up", "reverse": True}     # sort by upload, desc
        app.export_connections_csv()

        rows = list(csv.reader(open(path, newline="", encoding="utf-8")))
        # the header mirrors the table's columns
        assert rows[0] == ["process", "pid", "proto", "remote_ip", "remote_port",
                           "local_port", "packets", "impaired", "dropped",
                           "download_bytes", "upload_bytes", "total_bytes",
                           "avg_bytes", "duration_s", "idle_s"], rows[0]
        # sorted by upload desc: chrome (1024) before svchost (500)
        assert rows[1][0] == "chrome.exe" and rows[2][0] == "svchost.exe", rows
        chrome, svc = rows[1], rows[2]
        assert chrome[1] == "1234", chrome            # pid
        assert chrome[7] == "yes" and chrome[8] == "3", chrome   # impaired, dropped
        assert svc[1] == "" and svc[7] == "no" and svc[8] == "0", svc
        # download / upload / total are the raw bytes_in / bytes_out / bytes
        assert chrome[9:12] == ["2048", "1024", "3072"], chrome
        assert svc[9:12] == ["100", "500", "600"], svc
        # avg_bytes = total // packets (3072 // 4 = 768), duration, idle
        assert chrome[12] == "768", chrome
        assert chrome[13] == "7.0" and chrome[14] == "1.0", chrome
        # atomic overwrite leaves no temp file behind
        assert not os.path.exists(path + ".tmp")
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
        assert rows[1][12] == "768", rows[1]                 # rounded, not floored 767
        assert rows[1][12] == str(avg_packet_bytes(row)), rows[1]
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
