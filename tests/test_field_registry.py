"""``fields.FIELD_DEFS`` is the single source of truth - keep it honest.

A new setting must be impossible to half-add: if it is in the model it must have
a registry entry, a section, translated labels in every language file and a CLI
flag. These tests are what makes "one entry per field" a rule and not a wish.
"""
from beantester import fields as F
from beantester.cli import build_arg_parser
from beantester.i18n import set_language, translate
from beantester.settings import DEFAULT_SETTINGS, MATCH_FIELDS
from fakes import LANGS, check


def test_registry_covers_every_setting():
    missing = [k for k in DEFAULT_SETTINGS if k not in F.FIELDS]
    check("registry: every DEFAULT_SETTINGS key has a Field", not missing, f"({missing})")
    extra = [f.key for f in F.FIELD_DEFS if f.key not in DEFAULT_SETTINGS]
    check("registry: no Field without a default", not extra, f"({extra})")


def test_every_field_belongs_to_a_section():
    section_ids = {s.id for s in F.SECTIONS}
    orphans = [f.key for f in F.FIELD_DEFS if f.section not in section_ids]
    check("registry: every field lives in a known section", not orphans, f"({orphans})")
    placed = {k for s in F.SECTIONS for k in s.fields}
    unplaced = [f.key for f in F.FIELD_DEFS if f.key not in placed]
    check("registry: every field is placed on the form", not unplaced, f"({unplaced})")


def test_sections_split_cleanly_by_surface():
    """A section renders on exactly one surface, and the two views partition the
    registry (the Control page and the Settings window are both renderers of the
    same SECTIONS - see gui/form.py::ControlForm(sections=...))."""
    surfaces = {s.surface for s in F.SECTIONS}
    check("registry: only known surfaces are used",
          surfaces <= {"control", "settings"}, f"({surfaces})")
    control = {s.id for s in F.CONTROL_SECTIONS}
    settings = {s.id for s in F.SETTINGS_SECTIONS}
    allids = {s.id for s in F.SECTIONS}
    check("registry: surfaces do not overlap", not (control & settings))
    check("registry: surfaces cover every section", control | settings == allids)


def test_ui_only_fields_live_on_the_settings_surface():
    """Convention 37: the Settings window takes the ``ui_only`` fields. A view
    setting applied live must not sit on the Control page, where the dirty-state
    machinery would promise to 'apply' something already applied."""
    settings_ids = {s.id for s in F.SETTINGS_SECTIONS}
    stray = [f.key for f in F.FIELD_DEFS
             if f.ui_only and f.section not in settings_ids]
    check("registry: every ui_only field is on the Settings surface", not stray,
          f"({stray})")


def test_labels_and_tips_exist_in_every_language():
    keys = []
    for f in F.FIELD_DEFS:
        keys += [f.label] + [k for k in (f.tip, f.hint, f.unit_key) if k]
    keys += [s.label for s in F.SECTIONS] + [s.toggle for s in F.SECTIONS if s.toggle]
    for lang in LANGS:
        unresolved = [k for k in keys if translate(k, lang) == k]
        check(f"registry: all field texts resolve in {lang}", not unresolved,
              f"({sorted(set(unresolved))})")
    set_language("pl")


def test_a_label_ends_with_a_colon_exactly_when_it_precedes_a_box():
    """The form's punctuation rule, in both languages.

    `form.py::_place_one` draws a BOOL as a Checkbutton whose caption IS the label,
    and a CHOICE as a bare Combobox with no label widget at all. Everything else
    gets a `ttk.Label` immediately to the left of an Entry - and that is the only
    shape a trailing colon belongs to.

    Measured before this test existed: 16 fields followed the rule and 10 did not
    (`Loss`, `Corruption`, `Duplication` sat beside `Latency:` and `Jitter:`), and
    the flapping section contradicted itself in adjacent cells - `Period:` next to
    `Downtime percent`. Nothing enforced either half, in either direction.
    """
    for lang in LANGS:
        for field in F.FIELD_DEFS:
            takes_a_box = field.kind not in (F.BOOL, F.CHOICE)
            text = translate(field.label, lang)
            check(f"label {lang}/{field.key}: colon iff it precedes a box",
                  text.rstrip().endswith(":") == takes_a_box,
                  f"({text!r}, kind={field.kind})")
    set_language("pl")


def test_no_message_repeats_the_label_colon():
    """A label goes into running text WITHOUT the colon it wears on the form.

    `Field 'Latency:' must be between 0 and 600000.` is what the CLI printed, and
    the quotes make the stray colon look like part of the field's name. One helper
    strips it (`i18n.field_name`) and all three readers go through it - the range
    error, the expression error and the profile-scope warning - so adding a colon
    to a label can never leak into a sentence again.
    """
    from beantester.i18n import field_name
    from beantester.matchers import KIND_INT, parse_matcher
    from beantester.validators import parse_number

    for lang in LANGS:
        # Both widths: a CJK label ends in U+FF1A, and a strip that only knows
        # the ASCII one would leave it sitting inside the sentence.
        check(f"field_name strips the colon ({lang})",
              not field_name("fields.latency", lang).endswith((":", chr(0xFF1A))),
              f"({field_name('fields.latency', lang)!r})")

        try:
            parse_number("999999", "fields.latency", (0, 600000), lang)
        except ValueError as exc:
            check(f"range error names the field cleanly ({lang})",
                  "':'" not in str(exc) and ":'" not in str(exc), f"({exc})")
        else:
            check(f"range error was raised at all ({lang})", False)

    try:
        parse_matcher("abc", KIND_INT, "fields.port")
    except ValueError as exc:
        check("expression error names the field cleanly",
              ":'" not in str(exc).split("'")[0] + "'", f"({exc})")
    else:
        check("expression error was raised at all", False)
    set_language("pl")


def test_every_field_has_a_cli_flag():
    parser = build_arg_parser()
    known = set()
    for action in parser._actions:
        known.update(action.option_strings)
    missing = [f.key for f in F.FIELD_DEFS if f.cli and f"--{f.cli}" not in known]
    check("registry: every field's CLI flag exists in the parser", not missing,
          f"({missing})")
    no_flag = [f.key for f in F.FIELD_DEFS if not f.cli]
    check("registry: every field declares a CLI flag", not no_flag, f"({no_flag})")


def test_match_fields_is_a_view_over_the_registry():
    expected = tuple((f.key, f.expr_kind, f.label, f.bounds) for f in F.expression_fields())
    check("registry: MATCH_FIELDS is derived, not a second list",
          MATCH_FIELDS == expected, f"({MATCH_FIELDS})")
    check("registry: the expression fields are still there",
          [k for k, _, _, _ in MATCH_FIELDS]
          == ["target", "dst_ip", "dst_port", "block_ip", "block_port"])


def test_only_fields_that_can_show_a_hint_declare_one():
    """A hint on a checkbox is text nobody will ever read.

    ``gui/form.py::_place_one`` handles BOOL and CHOICE and **returns** before
    the line that renders ``field.hint``, so a hint on either kind is written,
    translated into every language, reviewed and then shown to no one. That is
    not hypothetical: ``narrow_filter`` carried a 300-character hint that never
    appeared on screen, which is exactly why its TOOLTIP had swollen into a wall
    trying to carry the same explanation.

    Nothing raises when it happens - the text simply is not drawn - so this is
    the only thing that can notice.
    """
    hintless = {F.BOOL, F.CHOICE}
    stray = [(f.key, f.kind) for f in F.FIELD_DEFS if f.hint and f.kind in hintless]
    check("registry: no field declares a hint its widget cannot show", not stray,
          f"({stray})")


def test_numeric_fields_declare_bounds():
    unbounded = [f.key for f in F.FIELD_DEFS if f.kind == F.NUMBER and not f.bounds]
    check("registry: every numeric field has bounds", not unbounded, f"({unbounded})")


def test_profile_scope_is_derived():
    check("registry: a profile stores the link-characteristic fields",
          set(F.PROFILE_FIELDS) == {"loss", "loss_burst", "corrupt", "dup",
                                    "latency", "jitter",
                                    "down", "up", "buffer", "spike_prob",
                                    "spike_ms", "flap_period", "flap_down",
                                    # asymmetry: the switch and the seven values
                                    # it governs. A profile that stored "200 ms"
                                    # without saying it was download-only would
                                    # store a link nobody has.
                                    "asym", "latency_up", "jitter_up",
                                    "spike_prob_up", "spike_ms_up",
                                    "loss_up", "corrupt_up", "dup_up"},
          f"({F.PROFILE_FIELDS})")
    non_profile = {k for k, _ in F.NON_PROFILE_FIELDS}
    check("registry: profile and non-profile fields partition the model",
          non_profile | set(F.PROFILE_FIELDS) == set(DEFAULT_SETTINGS))


def test_the_stored_profile_shape_follows_the_registry():
    """``in_profile`` is the ONLY switch that puts a field into a profile.

    The short-key map used to be a second hand-written table in ``presets.py``,
    so ``in_profile=True`` could declare a field in scope while the save path
    ignored it - and the failure was silent in both directions: the warning
    dialog (built from ``NON_PROFILE_FIELDS``) would stop listing the field as
    "not saved", and it still would not be saved.
    """
    from beantester.presets import PRESET_DEFAULTS, PRESET_TO_SETTING
    stored = set(PRESET_TO_SETTING.values())
    check("registry: the stored shape covers exactly the profile fields",
          stored == set(F.PROFILE_FIELDS),
          f"({sorted(stored ^ set(F.PROFILE_FIELDS))})")
    # the on-disk format is frozen: these two have been short since v1
    check("registry: the historical short keys are unchanged",
          {"lat", "jit"} <= set(PRESET_TO_SETTING), f"({sorted(PRESET_TO_SETTING)})")
    check("registry: every stored field has a default to fall back to",
          set(PRESET_DEFAULTS) == set(PRESET_TO_SETTING))


def test_every_registry_field_reaches_the_settings_through_its_cli_flag():
    """One entry in FIELD_DEFS must be enough (convention 11).

    A field's ``--flag`` used to be wired in THREE places: the registry, the
    argparse parser, and a hand-written ``flag_map`` in ``config_from_args``. The
    tests only guarded the first two, so a field could have a widget, a label and
    a flag, and still be quietly dropped on its way to the engine. The map is now
    derived from the registry - this test is what keeps it that way.
    """
    from beantester.cli import build_arg_parser, config_from_args
    from beantester.fields import BOOL, CHOICE, EXPR, FIELD_DEFS, NUMBER, SCHEDULE, SEED
    from beantester.matchers import KIND_INT, KIND_IP, KIND_PROCESS

    parser = build_arg_parser()
    flags = {action.option_strings[0] for action in parser._actions
             if action.option_strings}

    # a value each KIND actually accepts (an IP field will not take a port number)
    by_expr_kind = {KIND_IP: "10.0.0.1", KIND_INT: "80", KIND_PROCESS: "chrome"}
    samples = {SEED: "123", SCHEDULE: "1:100:50", CHOICE: "tcp"}

    for field in FIELD_DEFS:
        check(f"{field.key}: declares a CLI flag", bool(field.cli))
        flag = f"--{field.cli}"
        check(f"{field.key}: {flag} exists in the parser", flag in flags, f"({flags})")

        if field.kind == BOOL:
            cfg = config_from_args(parser.parse_args([flag]))
            check(f"{field.key}: {flag} sets the setting", cfg["settings"][field.key] is True)
            # and an ABSENT flag must not overwrite a config file (precedence!)
            cfg = config_from_args(parser.parse_args([]))
            check(f"{field.key}: absent {flag} leaves the default alone",
                  cfg["settings"][field.key] is False)
            continue

        if field.kind == NUMBER:
            low, high = field.bounds or (0.0, 100.0)
            raw = str(int(max(low, min(high, 7))))
        elif field.kind == EXPR:
            raw = by_expr_kind[field.expr_kind]
        else:
            raw = samples[field.kind]

        cfg = config_from_args(parser.parse_args([flag, raw]))
        got = cfg["settings"][field.key]
        if field.kind == NUMBER:
            check(f"{field.key}: {flag} {raw} reaches settings[{field.key!r}]",
                  float(got) == float(raw), f"(got {got!r})")
        elif field.kind == SEED:
            check(f"{field.key}: {flag} {raw} reaches settings[{field.key!r}]",
                  int(got) == int(raw), f"(got {got!r})")
        else:
            check(f"{field.key}: {flag} {raw} reaches settings[{field.key!r}]",
                  str(got) == str(raw), f"(got {got!r})")


def test_a_field_that_waits_on_a_switch_names_a_real_one_and_what_it_mirrors():
    """The accounting for ``live_when`` / ``mirror_of``, which three places read.

    ``settings.armed_global_impairments`` asks whether the switch is on before it
    calls an upload value armed, the form greys the field while it is off, and
    the form copies the mirror across when it goes on. A typo in either key would
    not raise anywhere: the warning would silently stop covering a field, and the
    copy would silently skip one - leaving exactly the blank box the switch
    exists to avoid.
    """
    for field in F.FIELD_DEFS:
        if not field.live_when:
            continue
        switch = F.FIELDS.get(field.live_when)
        check(f"{field.key}: live_when names a field that exists",
              switch is not None, f"({field.live_when!r})")
        if switch is not None:
            check(f"{field.key}: and that field is a switch",
                  switch.kind == F.BOOL, f"({switch.key} is {switch.kind})")
            check(f"{field.key}: which is not itself waiting on one",
                  not switch.live_when, f"({switch.key} waits on {switch.live_when!r})")
        check(f"{field.key}: names the field it mirrors",
              bool(field.mirror_of), "(nothing to copy across when the switch goes on)")
        mirror = F.FIELDS.get(field.mirror_of)
        check(f"{field.key}: and that field exists", mirror is not None,
              f"({field.mirror_of!r})")
        if mirror is not None:
            check(f"{field.key}: with the same kind, bounds and unit as its mirror",
                  (mirror.kind, mirror.bounds, mirror.unit)
                  == (field.kind, field.bounds, field.unit),
                  f"({mirror.key}: {mirror.kind}/{mirror.bounds}/{mirror.unit!r} vs "
                  f"{field.kind}/{field.bounds}/{field.unit!r})")
            check(f"{field.key}: and its mirror is not itself gated",
                  not mirror.live_when, f"({mirror.key} waits on {mirror.live_when!r})")
    # The canary: an empty scan satisfies every check above.
    check("some field waits on a switch at all",
          len(F.CONDITIONAL_IMPAIRING_KEYS) >= 1,
          f"({F.CONDITIONAL_IMPAIRING_KEYS})")
