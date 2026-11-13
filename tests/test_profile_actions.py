"""The profile picker's actions (gui/profile_actions.py), on the fake tkinter.

A profile is the user's own work: replacing or deleting one cannot be undone, so
both ask first. And the picker must not name a profile the form has left.
"""
import textwrap

from gui_harness import run_gui

# Answers the dialogs give, and what they were asked; set before every action.
ANSWERING = '''
import beantester.gui.dialogs as _dlg
asked = []

def answer(name=None, yes=None):
    _dlg.ask_string = lambda *a, **k: name
    def yes_no(root, title, message, careful=False):
        asked.append((message, careful))
        return yes
    _dlg.ask_yes_no = yes_no
'''


def run_answering(body):
    """Each part dedented on its own, and the body proven to reach its end: glued
    and dedented together, the body sat INSIDE ``answer`` and never ran (the trap
    tests/test_dialogs.py::run_pressing describes)."""
    out = run_gui(ANSWERING + textwrap.dedent(body) + '\nprint("body-done")\n')
    assert "body-done" in out, f"the test body never reached its end:\n{out}"


def test_saving_under_an_existing_name_asks_before_replacing_it():
    """It replaced the profile after one Enter, with nothing to bring it back."""
    run_answering("""
        app.profiles.persist = lambda: None
        app.vars["latency"].set("150")
        answer(name="Moj test")
        app.save_profile()
        assert asked == [], "a NEW name must not ask anything: %r" % asked
        assert app.profiles.get("Moj test")["lat"] == 150.0

        app.vars["latency"].set("999")
        answer(name="Moj test", yes=False)
        app.save_profile()
        assert len(asked) == 1 and "Moj test" in asked[0][0], asked
        assert asked[0][1] is True, "the keyboard must start on No: %r" % asked
        assert app.profiles.get("Moj test")["lat"] == 150.0, "No must keep the old values"

        answer(name="Moj test", yes=True)
        app.save_profile()
        assert app.profiles.get("Moj test")["lat"] == 999.0, "Yes replaces it"
    """)


def test_deleting_a_profile_asks_first_and_no_keeps_it():
    run_answering("""
        app.profiles.persist = lambda: None
        app.profiles.set("Moje VPN", app._settings_from_widgets())
        app.select_profile("Moje VPN")

        answer(yes=False)
        app.delete_profile()
        assert "Moje VPN" in app.profiles, "No must keep the profile"
        assert app._profile_key == "Moje VPN", app._profile_key
        assert len(asked) == 1 and "Moje VPN" in asked[0][0] and asked[0][1] is True, asked

        answer(yes=True)
        app.delete_profile()
        assert "Moje VPN" not in app.profiles
    """)


def test_the_picker_marks_a_profile_the_form_has_left():
    """It kept saying "Perfect network" over +100 ms of ping."""
    run_answering("""
        name = bnt.T("presets.roaming")
        app.select_profile("presets.roaming")
        assert app.profile_var.get() == name, app.profile_var.get()

        before = app.vars["latency"].get()
        app.vars["latency"].set(str(float(before) + 1))
        app.on_form_changed()
        marked = bnt.T("app.profile_modified", name=name)
        assert app.profile_var.get() == marked, app.profile_var.get()

        # the same number written another way is not a change
        app.vars["latency"].set(str(float(before)).replace(".", ","))
        app.on_form_changed()
        assert app.profile_var.get() == name, app.profile_var.get()

        # a field no profile stores does not mark it either
        app.target_var.set("chrome.exe")
        app.on_form_changed()
        assert app.profile_var.get() == name, app.profile_var.get()

        # the marked text still names the profile: loading it refills the form
        app.vars["latency"].set("12345")
        app.on_form_changed()
        assert app.profile_var.get() == marked
        app.load_selected_profile()
        assert app._profile_key == "presets.roaming", app._profile_key
        assert app.vars["latency"].get() == before, app.vars["latency"].get()
        assert app.profile_var.get() == name, app.profile_var.get()
    """)


def test_a_profile_named_like_the_marked_one_loads_itself():
    """Picking the row of a profile named "Office (changed)" while "Office" was the
    marked current one loaded "Office" again: the text matched the mark first."""
    run_answering("""
        app.profiles.persist = lambda: None
        app.vars["latency"].set("150")
        answer(name="Office")
        app.save_profile()
        marked = bnt.T("app.profile_modified", name="Office")
        app.vars["latency"].set("300")
        answer(name=marked)
        app.save_profile()

        app.select_profile("Office")
        app.vars["latency"].set("151")
        app.on_form_changed()
        assert app.profile_var.get() == marked, app.profile_var.get()

        app.profile_var.set(marked)           # the row of the profile with that name
        app.load_selected_profile()
        assert app._profile_key == marked, app._profile_key
        assert float(app.vars["latency"].get()) == 300.0, app.vars["latency"].get()
    """)
