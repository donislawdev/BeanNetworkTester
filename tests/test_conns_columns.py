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
                 packets=10, bytes=10240, bytes_in=8192, bytes_out=2048,
                 sent=10240, sent_in=8192, sent_out=2048, dropped=3,
                 scoped=True, pid=1234, first=90.0, last=99.0, dir="out", proc="chrome.exe"),
            dict(local_port=5001, remote_ip="192.168.0.5", remote_port=80, proto="TCP",
                 packets=4, bytes=4096, bytes_in=0, bytes_out=4096,
                 sent=4096, sent_in=0, sent_out=4096, dropped=0,
                 scoped=True, pid=None, first=95.0, last=98.0, dir="out", proc="svchost.exe"),
        ]
        app.engine.connections_snapshot = lambda limit=None: rows
        req = {"engine": app.engine, "query": "", "sort": {"col": "dropped", "reverse": True},
               "limit": app.row_limit(), "now": 100.0, "proc_map": {}}
        page._apply(page._build_model(req))

        # the render tuple must line up with the 17 columns
        assert len(page.table.columns) == 17, page.table.columns
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


def test_a_portless_row_renders_empty_port_cells_and_is_not_searchable_as_none():
    """A ping row has no ports. Passed straight through, None reaches Tk and
    renders as the literal string "None" - and the search blob would read
    "8.8.8.8:none", making every ping row a hit for the term "none"."""
    run_gui('''
        page = app.pages["connections"]
        app.engine.now_ref = lambda: 100.0
        rows = [dict(local_port=None, remote_ip="8.8.8.8", remote_port=None, proto="ICMP",
                     packets=12, bytes=1176, bytes_in=588, bytes_out=588, dropped=0,
                     scoped=True, pid=None, first=90.0, last=99.0, dir="out", proc="")]
        app.engine.connections_snapshot = lambda limit=None: rows
        req = {"engine": app.engine, "query": "", "sort": {"col": "packets", "reverse": True},
               "limit": app.row_limit(), "now": 100.0, "proc_map": {}}
        page._apply(page._build_model(req))

        _key, vals, _tags = page.table.rows[0]
        # order: proc, pid, proto, r_ip, r_port, l_port, packets, ...
        assert vals[2] == "ICMP", vals
        assert vals[4] == "" and vals[5] == "", ("port cells must be blank", vals)
        assert "None" not in [str(v) for v in vals], vals

        from beantester.views import filter_sort_connections
        assert filter_sort_connections(rows, query="none") == [], "searching 'none' matched a ping row"
        assert len(filter_sort_connections(rows, query="8.8.8.8")) == 1, "the address must still match"
    ''')


def test_two_portless_rows_to_one_address_keep_separate_identities():
    """The widget's key index is a dict, so two rows sharing a key means one of
    them cannot be selected or scrolled to. Portless rows have no ports to tell
    them apart, so the protocol has to be part of the identity - ping and, say,
    ESP to the same VPN gateway are two rows."""
    run_gui('''
        page = app.pages["connections"]
        app.engine.now_ref = lambda: 100.0
        rows = [dict(local_port=None, remote_ip="10.8.0.1", remote_port=None, proto="ICMP",
                     packets=5, bytes=490, bytes_in=245, bytes_out=245, dropped=0,
                     scoped=True, pid=None, first=90.0, last=99.0, dir="out", proc=""),
                dict(local_port=None, remote_ip="10.8.0.1", remote_port=None, proto="IP",
                     packets=9, bytes=900, bytes_in=400, bytes_out=500, dropped=0,
                     scoped=True, pid=None, first=91.0, last=99.0, dir="out", proc="")]
        app.engine.connections_snapshot = lambda limit=None: rows
        req = {"engine": app.engine, "query": "", "sort": {"col": "packets", "reverse": True},
               "limit": app.row_limit(), "now": 100.0, "proc_map": {}}
        page._apply(page._build_model(req))

        keys = [key for key, _vals, _tags in page.table.rows]
        assert len(set(keys)) == 2, ("both rows must have their own identity", keys)
        index = page.table._ensure_index()
        assert len(index) == 2, ("the key index collapsed a row", index)
    ''')


def test_numeric_columns_are_right_aligned_and_the_registry_is_honest():
    """Numbers line up by order of magnitude, which is why a column of them is
    worth reading down at all. Everything used to be anchored west, in one loop
    over the columns, so 9 and 1000000 started at the same pixel.

    Read from the page's NUMERIC registry rather than from a list retyped here:
    a test that repeats the answer cannot catch the registry drifting from the
    columns it describes, which is the failure this alignment had in the first
    place.
    """
    run_gui('''
        from beantester.gui.pages import conns

        page = app.pages["connections"]
        tree = page.table.tree

        assert conns.NUMERIC <= set(conns.COLUMNS), \
            "NUMERIC names columns that do not exist: %r" % (
                conns.NUMERIC - set(conns.COLUMNS))

        for col in conns.COLUMNS:
            want = ("e" if col in conns.NUMERIC
                    else "center" if col in conns.CENTERED else "w")
            got = tree.column(col, "anchor")
            assert got == want, "%s anchored %r, wanted %r" % (col, got, want)

        # A right-aligned cell sits on its column's right edge and a left-aligned
        # neighbour on its own left edge, so the two TOUCH - that is how the first
        # build after this change rendered "67400 TCP" and "550 tak" as one value.
        # ttk offers no per-cell padding, so nothing but alignment can fix it, and
        # nothing but this check can stop it coming back with the next column.
        cols = list(conns.COLUMNS)
        touching = [(a, b) for a, b in zip(cols, cols[1:])
                    if a in conns.NUMERIC and b not in conns.NUMERIC
                    and b not in conns.CENTERED]
        assert not touching,             "a number is left touching the text beside it: %r" % touching

        # the ones the audit named, spelled out so a shrinking registry is caught
        for col in ("pid", "packets", "dropped", "down", "up", "kb", "avg"):
            assert col in conns.NUMERIC, "%s stopped counting as a number" % col
        for col in ("proc", "proto", "remote_ip", "scoped"):
            assert col not in conns.NUMERIC, "%s is not a quantity" % col
    ''')


def test_an_impaired_row_is_not_marked_by_colour_alone():
    """WCAG 1.4.1 level A: colour may not be the only visual carrier.

    The text column "impaired?" used to be the other one - then the column
    chooser shipped (2026-08-02) and the user could hide it, which put the row
    back on colour alone. The second signal therefore has to be something no
    column setting can remove, which rules out a marker inside a cell: every
    cell belongs to a column and every column can be hidden.
    """
    run_gui('''
        from beantester.gui import theme

        style = theme.CONN_COLORS["impaired"]
        assert "foreground" in style, "the colour itself went missing"
        non_colour = set(style) - {"foreground", "background"}
        assert non_colour, \
            "impaired rows carry colour and nothing else: %r" % style

        page = app.pages["connections"]
        applied = page.table.tree.tag_styles.get("impaired", {})
        assert set(applied) - {"foreground", "background"}, \
            "the table did not apply the non-colour signal: %r" % applied
    ''')


def test_the_table_is_reachable_and_readable_without_a_mouse():
    """WCAG 2.1.1, and the way testers actually work.

    Two tables carry a search box and neither had Ctrl+F; the context menu hung
    on <Button-3> alone, so there was no keyboard path to it at all - while
    services.msc and the console have had Shift+F10 since forever.

    Ctrl+F is bound on the ROOT rather than on the entry: a shortcut that only
    works once the caret is already in the box is not a shortcut. It brings the
    page forward first, so "find" answers the same wherever the user was.
    """
    run_gui('''
        page = app.pages["connections"]
        app.select_page("control")

        root_binds = set(root.bindings)
        assert "<Control-f>" in root_binds, \
            "no Ctrl+F on the main window: %r" % sorted(root_binds)

        page.focus_search()
        assert app.current_page() is page, \
            "Ctrl+F did not bring the Connections page forward"
        assert root.focus_get() is page._search_entry, \
            "the caret did not land in the search box"

        # The menu key is spelled per platform and Tk RAISES on a spelling it
        # does not know, so the test has to ask for the same one the code binds -
        # asserting "<App>" everywhere is the Windows-only assumption that broke
        # the Linux render check in the first place.
        import sys as _sys
        tree_binds = set(page.table.tree.bindings)
        menu_key = "<App>" if _sys.platform == "win32" else "<Menu>"
        for seq in ("<Shift-F10>", menu_key):
            assert seq in tree_binds, "no keyboard route to the menu: %s" % seq

        # ...and it refuses when there is no row to act on, exactly as the mouse
        # route refuses on an empty table
        page.table.select_keys([])
        assert page._popup_from_keyboard() == "break"
    ''')


def test_an_empty_table_says_so_instead_of_showing_a_blank_rectangle():
    """The count underneath read "0 of N"; the table itself said nothing.

    A blank table is equally consistent with "nothing matched" and "something
    broke". Since the search box learned column qualifiers, the empty view is
    common rather than rare - a half-typed `port:44` on the way to `port:443`
    correctly matches nothing.
    """
    run_gui('''
        page = app.pages["connections"]
        table = page.table
        note = table._empty_note
        assert note is not None, "the Connections table declares no empty note"

        # nothing typed: an empty table means no traffic YET, and saying
        # "nothing matches your search" to someone who never searched is a lie
        page.search_var.set("")
        page._apply({"rows": [], "total": 0, "limit": 0,
                     "totals": {"down": 0, "up": 0, "total": 0}, "scope_active": False})
        assert "place" in note.kw, "nothing was shown on an empty table"
        assert note.kw.get("text") == bnt.T("tables.no_conns_yet"),             "wrong reason with no search typed: %r" % note.kw.get("text")

        # ...and with a query typed, the other reason
        page.search_var.set("port:44")
        page._apply({"rows": [], "total": 9, "limit": 0,
                     "totals": {"down": 0, "up": 0, "total": 0}, "scope_active": False})
        assert note.kw.get("text") == bnt.T("tables.no_conns_match"),             "wrong reason with a search typed: %r" % note.kw.get("text")

        table.set_model([("k", ("a",) * 17)], render=lambda i: i[1],
                        key_of=lambda i: i[0])
        assert "place" not in note.kw, \
            "the note stayed over a table that has rows again"
    ''')
