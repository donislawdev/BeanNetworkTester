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
import textwrap

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


def run_pressing(body, done):
    """Run ``body`` after the helpers below, and prove it ran to its last line.

    Each part is dedented on its own. Glued first and dedented together, the test's
    lines sat at the depth of ``press``'s body - after its ``return``, where they
    never ran: five mutations survived a test that looked green.
    """
    out = run_gui(textwrap.dedent(OPEN_AND_PRESS) + textwrap.dedent(body))
    assert done in out, f"the test body never reached its end:\n{out}"


# Opens a dialog and keeps it open (the fake's modal loop is replaced), so a test
# can put the keyboard somewhere and press a key through the dialog's own binding.
OPEN_AND_PRESS = '''
    import beantester.gui.dialogs as d
    from beantester.i18n import T

    kept = []
    d._run = lambda win, default=None: kept.append(win) or default

    def opened(show):
        show()
        win, found, stack = kept[-1], {}, [kept[-1]]
        while stack:
            widget = stack.pop()
            stack.extend(widget.children)
            if "command" in widget.kw:
                found[widget.kw.get("text")] = widget
            elif "textvariable" in widget.kw:
                found["entry"] = widget
        return win, found

    def press(show, on=None, key="<Return>", typed=None):
        """Open, move the keyboard to ``on`` (a button's text, "entry", or the
        window itself), press ``key``; return (answer, where the keyboard started)."""
        win, found = opened(show)
        started = root.focus_get()
        if typed is not None:
            found["entry"].kw["textvariable"].set(typed)
        (win if on is None else found[on]).focus_set()
        d._result.pop(str(win), None)
        win.bindings[key][-1](None)
        return d._result.pop(str(win), "still open"), started, found
'''


def test_enter_presses_the_button_the_keyboard_is_on():
    """Tab to "No", Enter: the dialog answered "Yes" (external review, P2-19).

    ``<Return>`` was bound to the first button whatever held the focus - on
    closing the window during a session and on unloading the driver - while Space
    pressed the focused one. Enter now presses the button the keyboard is on, and
    the default from anywhere else; the keypad's Enter does the same.
    """
    run_pressing('''
        yes_no = lambda: d.ask_yes_no(root, "Title", "proceed?")
        yes, no = T("buttons.yes"), T("buttons.no")
        for key in ("<Return>", "<KP_Enter>"):
            assert press(yes_no, on=no, key=key)[0] is False, key
            assert press(yes_no, on=yes, key=key)[0] is True, key
            assert press(yes_no, on=None, key=key)[0] is True, key   # no button: default

        ok, cancel = T("buttons.ok"), T("buttons.cancel")
        name = lambda: d.ask_string(root, "Name", "profile name?")
        assert press(name, on="entry", typed="abc")[0] == "abc"
        assert press(name, on=ok, typed="abc")[0] == "abc"
        assert press(name, on=cancel, typed="abc")[0] is None     # used to save it
        assert press(name, on=cancel, typed="abc", key="<KP_Enter>")[0] is None

        for show in (lambda: d.show_info(root, "T", "m"), lambda: d.show_warning(root, "T", "m"),
                     lambda: d.show_error(root, "T", "m"), lambda: d.show_help(root, "T", "m")):
            for key in ("<Return>", "<KP_Enter>"):
                assert press(show, on=None, key=key)[0] is True, key
        print("enter-ok")
    ''', "enter-ok")


def test_a_dialog_opens_with_the_keyboard_on_its_default_button():
    """The keyboard starts where Enter will land, so its ring shows it first
    (owner decision D-2): "Yes" stays the default and gets the focus; a dialog
    that asks for a name starts in the field instead."""
    run_pressing('''
        yes, ok = T("buttons.yes"), T("buttons.ok")
        _, started, found = press(lambda: d.ask_yes_no(root, "T", "proceed?"))
        assert started is found[yes], started
        for show in (lambda: d.show_warning(root, "T", "m"), lambda: d.show_help(root, "T", "m")):
            _, started, found = press(show)
            assert started is found[ok], started
        _, started, found = press(lambda: d.ask_string(root, "N", "name?"))
        assert started is found["entry"], started
        print("focus-ok")
    ''', "focus-ok")


def test_the_render_check_presses_the_dialogs_keys_on_real_tk():
    """The key half of the tests above runs in CI, not here.

    Where the focus lands when a dialog opens and which binding a key reaches are
    facts the fake has no model of, so ``tools/ci_gui_render.py --dialogs`` opens
    the real dialogs and presses the keys. This pins that ``main`` still runs that
    pass in a process of its own, and that the cases still include the one the
    review found and the keypad's Enter.
    """
    import ast
    import os

    from fakes import ROOT, check

    path = os.path.join(ROOT, "tools", "ci_gui_render.py")
    with open(path, encoding="utf-8") as handle:
        module = ast.parse(handle.read())
    main = next(node for node in ast.walk(module)
                if isinstance(node, ast.FunctionDef) and node.name == "main")
    calls = [node for node in ast.walk(main) if isinstance(node, ast.Call)]
    named = {call.func.id for call in calls if isinstance(call.func, ast.Name)}
    check("--dialogs reaches check_dialogs", "check_dialogs" in named, f"({sorted(named)})")
    runs = [call for call in calls
            if isinstance(call.func, ast.Attribute) and call.func.attr == "run"
            and any(isinstance(leaf, ast.Constant) and leaf.value == "--dialogs"
                    for arg in call.args for leaf in ast.walk(arg))]
    check("main runs the dialog pass as a process of its own", len(runs) == 1,
          f"({len(runs)} subprocess run(s) with --dialogs)")
    cases = next(ast.literal_eval(node.value) for node in module.body
                 if isinstance(node, ast.Assign)
                 and any(getattr(t, "id", None) == "DIALOG_CASES" for t in node.targets))
    keys_and_answers = {(tuple(keys), expected) for _l, _o, keys, expected, _f in cases}
    check("the review's case is measured: Tab to No, then Enter, answers No",
          (("<Tab>", "<Return>"), False) in keys_and_answers, f"({keys_and_answers})")
    check("and the keypad's Enter", any("<KP_Enter>" in keys for keys, _a in keys_and_answers))
    # Only the keypad's Enter may go unmeasured: a Tk that cannot deliver Tab or
    # Return measures nothing that matters, and has to fail rather than pass on
    # the Escape case alone (review of #218).
    optional = next(ast.literal_eval(node.value) for node in module.body
                    if isinstance(node, ast.Assign)
                    and any(getattr(t, "id", None) == "DIALOG_OPTIONAL_KEYS"
                            for t in node.targets))
    check("only the keypad's Enter may be skipped", optional == ("<KP_Enter>",),
          f"({optional})")
