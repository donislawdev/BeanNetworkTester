"""Connections page columns added on top of the traffic split: pid, "impaired?",
dropped, avg, the impaired-row highlight tag, and the traffic-totals footer.

Driven through the real ConnsPage on the fake tkinter so the render tuple, the
column set, the tag callback and the footer label are exercised end to end - the
render tuple must stay the same length as COLUMNS or the table silently misaligns.
"""
from gui_harness import run_gui


def test_connection_columns_tag_and_footer():
    run_gui('''
        page = app.pages["connections"]
        app.engine.now_ref = lambda: 100.0
        # Target chrome's port only. svchost carries scoped=True from EARLIER in the
        # session (impaired before the target was narrowed) and its port is NOT in the
        # current target. The column and the row highlight are now ONE signal - the
        # stored scoped record - so they must AGREE: svchost reads "yes" AND is
        # highlighted. (Before, the column read the record while the highlight asked
        # the LIVE target, so svchost was "yes" with no colour - the exact mismatch
        # that read as "something is wrong with the connections table".)
        app.engine.core.set_target(True, {5000})
        rows = [
            dict(local_port=5000, remote_ip="1.1.1.1", remote_port=443, proto="TCP",
                 packets=10, bytes=10240, bytes_in=8192, bytes_out=2048, dropped=3,
                 scoped=True, pid=1234, first=90.0, last=99.0, dir="out", proc="chrome.exe"),
            dict(local_port=5001, remote_ip="192.168.0.5", remote_port=80, proto="TCP",
                 packets=4, bytes=4096, bytes_in=0, bytes_out=4096, dropped=0,
                 scoped=True, pid=None, first=95.0, last=98.0, dir="out", proc="svchost.exe"),
        ]
        app.engine.connections_snapshot = lambda limit=None: rows
        req = {"engine": app.engine, "query": "", "sort": {"col": "dropped", "reverse": True},
               "limit": app.row_limit(), "now": 100.0, "proc_map": {}}
        page._apply(page._build_model(req))

        # the render tuple must line up with the 15 columns
        assert len(page.table.columns) == 15, page.table.columns
        model = {vals[0]: (vals, tags) for _key, vals, tags in page.table.rows}

        chrome_vals, chrome_tags = model["chrome.exe"]
        svc_vals, svc_tags = model["svchost.exe"]

        # order: proc, pid, proto, r_ip, r_port, l_port, packets, scoped, dropped, ...
        assert str(chrome_vals[1]) == "1234", chrome_vals            # pid
        assert chrome_vals[7] == bnt.T("conns.yes"), chrome_vals     # impaired?
        assert str(chrome_vals[8]) == "3", chrome_vals               # dropped
        assert svc_vals[1] == "", svc_vals                           # pid None -> blank

        # column and highlight AGREE for every row - one stored signal:
        assert chrome_vals[7] == bnt.T("conns.yes") and "impaired" in chrome_tags, \
            (chrome_vals, chrome_tags)
        # svchost: stored "yes" AND highlighted, even though its port is out of the
        # current target (this is the fix - it used to be "yes" with an empty tag).
        assert svc_vals[7] == bnt.T("conns.yes") and "impaired" in svc_tags, \
            (svc_vals, svc_tags)

        # footer sums every filtered flow (down 8192 + 0 B = 8.0 KB, up 2048 + 4096 = 6.0 KB)
        footer = page.totals.kw["text"]
        assert "8.0" in footer and "6.0" in footer, footer
    ''')
