"""The speed-unit preference: a DISPLAY choice, and it may never become more.

Why this file exists separately from ``test_prefs.py``: the preference is the
small half. The load-bearing half is that KB/s stays the only unit anything
DURABLE ever sees - the CLI flags, the config file, the schedule string, the
shipped scenarios and the NDJSON ``down_kbps``/``up_kbps`` fields all carry that
number, and several of them are frozen contracts. A unit switch that leaked into
any of them would silently rewrite what a saved file means, and the file would
still load.

So the tests below come in two halves: the arithmetic (pure, and the Mbit/s
factor is the one number here people get wrong), and the boundary (what the
switch is not allowed to touch).
"""
from beantester import fields as F
from beantester.gui import rates
from beantester.gui.prefs import CHOICE, PREFS, coerce
from fakes import check
from gui_harness import run_gui


def test_a_kilobyte_here_is_1024_bytes_and_a_megabit_is_a_million_bits():
    """The conversion, with the number people expect written down as wrong.

    1024 KB/s is 8.389 Mbit/s and NOT 8.0. K is 1024 in this program (the engine
    multiplies by 1024 to get bytes per second), a byte is 8 bits, and a megabit
    is a decimal million - which is what every network interface and every ISP
    means by it. Rounding the answer to a comfortable 8 would be a 4.9% error in
    exactly the direction a reader already expects, which is the kind of number
    that never gets questioned again.
    """
    check("1024 KB/s is 1.00 MB/s", rates.rate_with_unit(1024, "mb") == "1.00 MB/s",
          f"({rates.rate_with_unit(1024, 'mb')})")
    check("1024 KB/s is 8.39 Mbit/s, not 8.00",
          rates.rate_with_unit(1024, "mbit") == "8.39 Mbit/s",
          f"({rates.rate_with_unit(1024, 'mbit')})")
    exact = 1024 * 1024 * 8 / 1_000_000
    check("and the factor is derived, not typed",
          abs(rates.in_unit(1024, "mbit") - exact) < 1e-9,
          f"({rates.in_unit(1024, 'mbit')} vs {exact})")
    check("the base unit is a no-op", rates.in_unit(937, "kb") == 937)
    check("an unknown unit reads as the base one rather than raising",
          rates.in_unit(937, "furlongs per fortnight") == 937)


def test_the_small_units_keep_the_digits_the_base_unit_does_not_need():
    """256 KB/s must not print as "0 MB/s".

    KB/s has always printed whole numbers and still does. The other two are
    smaller numbers for the same speed, so printing them the same way would round
    a real, configured limit to zero and make the readout look broken rather than
    small.
    """
    check("256 KB/s is 0.25 MB/s", rates.format_rate(256, "mb") == "0.25",
          f"({rates.format_rate(256, 'mb')})")
    check("...and the base unit is still an integer",
          rates.format_rate(256, "kb") == "256", f"({rates.format_rate(256, 'kb')})")
    check("a big number drops the decimals rather than reading like a measurement",
          rates.format_rate(1024 * 200, "mbit") == "1678",
          f"({rates.format_rate(1024 * 200, 'mbit')})")
    check("garbage in is 0, not an exception (this runs on a half-typed field)",
          rates.format_rate("12x", "mbit") == "0.00")


def test_the_rate_fields_are_a_view_over_the_registry_not_a_list_of_names():
    """A third rate field must arrive here by declaring its unit, not by editing.

    The moment this becomes a hand-written tuple it starts drifting, which is the
    failure mode this project keeps paying for. Derived means a new field with
    ``unit="KB/s"`` gets its converted readout with no second edit.
    """
    expected = tuple(f.key for f in F.FIELD_DEFS if f.unit == rates.BASE_LABEL)
    check("the rate fields come out of the field registry",
          rates.RATE_FIELD_KEYS == expected,
          f"({rates.RATE_FIELD_KEYS} vs {expected})")
    check("and today that is download and upload",
          set(rates.RATE_FIELD_KEYS) == {"down", "up"},
          f"({rates.RATE_FIELD_KEYS})")


def test_every_choice_preference_defaults_to_one_of_its_own_choices():
    """A default outside the list renders as a blank dropdown and stores nothing."""
    choices = [p for p in PREFS if p.kind == CHOICE]
    check("there is at least one CHOICE pref (else this test is vacuous)", choices)
    for pref in choices:
        values = [value for value, _ in pref.choices]
        check(f"{pref.key}: the default is one of its choices",
              pref.default in values, f"({pref.default!r} not in {values})")
        check(f"{pref.key}: an unknown stored value falls back to the default",
              coerce(pref, "something-a-later-build-removed") == pref.default)
        check(f"{pref.key}: a known one survives",
              coerce(pref, values[-1]) == values[-1])


def test_the_unit_preference_never_reaches_the_engine_or_a_file():
    """The boundary, and the reason the switch is a Pref rather than a field.

    A registry field would get a CLI flag and ride inside a saved traffic config
    (convention 42), so a config written with Mbit/s selected would carry a
    display choice into a file that describes TRAFFIC - and the schedule string
    beside it would still be in KB/s. This asserts the separation mechanically
    instead of trusting that nobody moves it later.
    """
    check("the unit is not a settings field",
          "rate_unit" not in {f.key for f in F.FIELD_DEFS})
    from beantester.settings import DEFAULT_SETTINGS
    check("...and not a settings key", "rate_unit" not in DEFAULT_SETTINGS)
    from beantester.cli import build_arg_parser
    flags = {a for action in build_arg_parser()._actions
             for a in action.option_strings}
    check("...and has no CLI flag", "--rate-unit" not in flags, f"({sorted(flags)[:3]}...)")
    check("the rate FIELDS still declare the base unit, whatever is on screen",
          all(F.FIELDS[k].unit == rates.BASE_LABEL for k in rates.RATE_FIELD_KEYS))


def test_the_dropdown_stores_the_value_and_never_the_label():
    """The bug this kind invites: writing "Mbit/s" into ui.json instead of "mbit".

    The combobox shows labels and the store keeps values, so the two are one
    mapping apart - and a label written to disk would survive a restart, fail to
    match any known unit and silently fall back to KB/s, which reads as "the
    preference does not stick" rather than as a bug in the write.
    """
    run_gui("""
        panel = app.open_window("settings")
        var = panel._pref_vars["rate_unit"]

        # Find the combobox this pref rendered and fire ITS binding, so the
        # label -> value mapping under test is the production one rather than a
        # copy of it written here.
        from fake_tk import walk
        boxes = [w for w in walk(panel.win)
                 if getattr(w, "kw", {}).get("textvariable") is var]
        assert boxes, "the choice pref rendered no widget bound to its variable"
        box = boxes[0]
        assert list(box.kw.get("values")) == ["KB/s", "Mbit/s", "MB/s"], box.kw.get("values")
        assert box.kw.get("state") == "readonly", box.kw.get("state")

        var.set("Mbit/s")
        for handler in box.bindings.get("<<ComboboxSelected>>", []):
            handler(None)

        assert app.pref("rate_unit") == "mbit", app.pref("rate_unit")
        assert app.ui.get("pref.rate_unit") == "mbit", app.ui.get("pref.rate_unit")
    """)


def test_the_converted_readout_appears_only_when_there_is_something_to_convert():
    """Beside the speed limits: empty in KB/s, filled otherwise, quiet on garbage.

    Repeating "1024 KB/s" next to a box that says 1024 is noise, so the base unit
    shows nothing. A half-typed value shows nothing either: this readout is a
    comment on the box, not a validator, and colouring the field or logging from
    here would make it one.
    """
    run_gui("""
        from beantester.gui.pages import pref_changed

        app.select_page("control")
        form = app.form
        assert set(form.rate_hints) == {"down", "up"}, sorted(form.rate_hints)

        def pick(unit):
            # The production path: the Settings window persists and then TELLS the
            # pages (SettingsWindow._store -> pages.pref_changed). Calling
            # form.sync_rate_hints() directly here would test the label and leave
            # the WIRING unguarded - which is the half that broke when the reaction
            # moved out of App.set_pref.
            app.set_pref("rate_unit", unit)
            pref_changed(app, "rate_unit")

        app.vars["down"].set("1024")
        pick("kb")
        assert form.rate_hints["down"].kw.get("text") == "", \\
            form.rate_hints["down"].kw.get("text")

        pick("mbit")
        shown = form.rate_hints["down"].kw.get("text")
        assert "8.39" in shown and "Mbit/s" in shown, shown

        pick("mb")
        shown = form.rate_hints["down"].kw.get("text")
        assert "1.00" in shown and "MB/s" in shown, shown

        # a value in the middle of being typed says nothing rather than erroring
        app.vars["down"].set("12x")
        form.sync_rate_hints()
        assert form.rate_hints["down"].kw.get("text") == "", \\
            form.rate_hints["down"].kw.get("text")
    """)
