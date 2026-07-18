"""``fields.FIELD_DEFS`` is the single source of truth - keep it honest.

A new setting must be impossible to half-add: if it is in the model it must have
a registry entry, a section, translated labels in every language file and a CLI
flag. These tests are what makes "one entry per field" a rule and not a wish.
"""
from beantester import fields as F
from beantester.cli import build_arg_parser
from beantester.i18n import set_language, translate
from beantester.settings import DEFAULT_SETTINGS, MATCH_FIELDS
from fakes import check


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
    for lang in ("en", "pl"):
        unresolved = [k for k in keys if translate(k, lang) == k]
        check(f"registry: all field texts resolve in {lang}", not unresolved,
              f"({sorted(set(unresolved))})")
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


def test_numeric_fields_declare_bounds():
    unbounded = [f.key for f in F.FIELD_DEFS if f.kind == F.NUMBER and not f.bounds]
    check("registry: every numeric field has bounds", not unbounded, f"({unbounded})")


def test_profile_scope_is_derived():
    check("registry: a profile stores exactly the 7 link-characteristic fields",
          set(F.PROFILE_FIELDS) == {"loss", "corrupt", "dup", "latency", "jitter",
                                    "down", "up"}, f"({F.PROFILE_FIELDS})")
    non_profile = {k for k, _ in F.NON_PROFILE_FIELDS}
    check("registry: profile and non-profile fields partition the model",
          non_profile | set(F.PROFILE_FIELDS) == set(DEFAULT_SETTINGS))


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
