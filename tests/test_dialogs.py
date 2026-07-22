"""The in-app dark dialogs (``gui/dialogs.py``), driven on the fake tkinter.

They replace ``tkinter.messagebox`` / ``simpledialog``, which draw un-themable
native windows and take their button labels from the OS locale (an English UI
asking "Tak / Nie" on a Polish Windows). Being real modals, they block in
``wait_window`` until a button sets the result - which on the fake tkinter is a
no-op, so calling one runs its whole construction path and comes back with the
DEFAULT a dismissed dialog yields. The click path (``_close`` records the value
and tears the window down) is driven directly, since there is no modal loop to
click into.
"""
from gui_harness import run_gui


def test_every_dialog_builds_and_returns_its_dismissal_default():
    run_gui('''
        import beantester.gui.dialogs as d

        # Dismissed without a click, each modal yields its documented default.
        assert d.show_info(root, "Title", "all good") is True
        assert d.show_warning(root, "Title", "be careful") is True
        assert d.show_error(root, "Title", "it broke") is True
        assert d.ask_yes_no(root, "Title", "proceed?") is False       # default is NO
        assert d.show_help(root, "Filters", "a, b, 1-9, !x, re:^y$") is True
        assert d.ask_string(root, "Name", "profile name?") is None    # cancelled
        print("defaults-ok")
    ''')


def test_clicking_a_dialog_button_records_the_result_and_closes_it():
    run_gui('''
        import beantester.gui.dialogs as d

        # _close is what every button command calls: it records the chosen value
        # under the window key and destroys the dialog. Drive it directly, because
        # the modal loop that would normally reach it is a no-op on the fake tk.
        win, body = d._shell(root, "Title")
        d._close(win, "chosen")
        assert d._result.get(str(win)) == "chosen", d._result
        print("close-ok")
    ''')
