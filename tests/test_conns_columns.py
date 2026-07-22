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
        # target the chrome flow's local port only. svchost carries scoped=True as
        # a session record: it WAS in impairment scope earlier, before the target
        # was narrowed to chrome. The two signals now differ on purpose:
        #   * the COLUMN is that stored record  -> svchost still reads "yes"
        #   * the ROW HIGHLIGHT is the live target -> svchost is NOT highlighted
        # (before, a live column flipped every closed flow to "no", so a run that
        #  impaired all of chrome looked like it had caught nothing.)
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
        # svchost was impaired earlier this session: the COLUMN keeps the record
        # even though it is out of the CURRENT target.
        assert svc_vals[7] == bnt.T("conns.yes"), svc_vals

        # the HIGHLIGHT is live: only the row in the current target is tagged, so the
        # out-of-scope svchost row keeps its record but loses the highlight.
        assert "impaired" in chrome_tags, chrome_tags
        assert svc_tags == (), svc_tags

        # footer sums every filtered flow (down 8192 + 0 B = 8.0 KB, up 2048 + 4096 = 6.0 KB)
        footer = page.totals.kw["text"]
        assert "8.0" in footer and "6.0" in footer, footer
    ''')
