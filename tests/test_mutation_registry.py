"""The registry of mutation proofs, and the guard that keeps it honest.

Why this file exists
--------------------
This project's strongest claim about its own tests is the sentence "verified by
mutation". It appears in PROJECT_NOTES more than twenty times and in a dozen
docstrings - and until now **nothing checked a single one of them**. That is the
exact failure mode convention 5 exists to prevent, applied to the evidence for
convention 5 itself: prose nobody guards, trusted precisely because it sounds
rigorous.

So the claims move here, as data, in three lists that say three different things:

* ``MUTATIONS`` - re-runnable today. ``internal_tools/mutate.py`` breaks the named
  behaviour and proves the named test reddens. This is the only list that is proof.
* ``PROVEN_BY_HAND`` - a mutation WAS performed and dated, by a session, with no
  re-runnable entry. The claim rests on that record, not on anything a machine can
  repeat. This list should only shrink: entries move to ``MUTATIONS`` when someone
  writes the patch down.
* ``NOT_PROVEN`` - no mutation, said out loud. An empty-looking guard and an
  unproven one must not be indistinguishable, which is what happens when the third
  list is missing.

What the SUITE checks here (cheap, every run) is the bookkeeping: that every named
test exists, that no test is filed under two states, and - the one that matters -
that **every mutation's search pattern still occurs exactly once**. A pattern that
went stale would make the runner report SKIP, but only when someone runs it; the
suite catches it the day the code moves. Running the mutations themselves is not a
pytest job: each one costs a subprocess suite run.

Deliberately NOT checked here: whether a mutation is *aimed well*. A patch can
redden its test for the wrong reason - see the note in convention 5 about a test
that passed because a transposition broke a different field than the one it named.
"""
import ast
import glob
import os

from fakes import ROOT, check


# -- the three states ---------------------------------------------------------- #
# label -> what to break -> which single test must go red. Keep `old` long enough to
# be unambiguous and short enough to survive unrelated edits nearby.
MUTATIONS = [
    {
        "label": "gui: the settings form stops refreshing its field states",
        "file": "beantester/gui/panels/settings.py",
        "old": "            self.form.refresh_field_states()\n",
        "new": "",
        "test": "test_start_only_fields_are_locked_while_a_session_runs",
    },
    {
        "label": "gui: start/stop stops ticking the open windows",
        "file": "beantester/gui/app.py",
        "old": "        with crashlog.quiet(\"gui.app\"):\n            self.windows.refresh()",
        "new": "        with crashlog.quiet(\"gui.app\"):\n            pass",
        "test": "test_start_only_fields_are_locked_while_a_session_runs",
    },
    {
        "label": "gui: a row action pushes straight through to the running engine",
        "file": "beantester/gui/app.py",
        "old": ("        self.on_form_changed()\n"
                "        self.log(f\"{T('log.target_set')}: {expression}\")"),
        "new": ("        self.on_form_changed()\n"
                "        self.apply_if_running(announce=False)\n"
                "        self.log(f\"{T('log.target_set')}: {expression}\")"),
        "test": "test_a_row_action_fills_the_form_and_does_not_reach_a_running_engine",
    },
    {
        "label": "columns: hiding every column is allowed again",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "        if not wanted:\n            wanted = [next(iter(self.columns))]",
        "new": "        if not wanted:\n            pass",
        "test": "test_hiding_columns_never_leaves_the_table_with_none",
    },
    {
        "label": "columns: the saved layout stops being restored",
        "file": "beantester/gui/pages/conns.py",
        "old": "            self.table.set_visible_columns(saved)",
        "new": "            pass",
        "test": "test_the_chosen_columns_are_remembered_and_restored",
    },
    {
        "label": "search: a text column is judged in the pid position again",
        "file": "beantester/views.py",
        "old": "            tests.append(lambda c, m, x=matcher, g=getter: x.matches(None, g(c, m)))",
        "new": "            tests.append(lambda c, m, x=matcher, g=getter: x.matches(g(c, m)))",
        "test": "test_a_text_column_is_matched_case_insensitively",
    },
    {
        "label": "guards: the repository collector returns nothing",
        "file": "tests/test_repo_conventions.py",
        "old": "    out = []\n    for dirpath, dirnames, filenames in os.walk(ROOT):",
        "new": "    out = []\n    for dirpath, dirnames, filenames in []:",
        "test": "test_the_repository_scanners_actually_read_files",
    },
    {
        "label": "guards: the whole-tree walk points at a root that is not there",
        "file": "tests/test_repo_conventions.py",
        "old": "for dirpath, dirnames, filenames in os.walk(ROOT):",
        "new": "for dirpath, dirnames, filenames in os.walk(ROOT + '_nope'):",
        "test": "test_the_repository_scanners_actually_read_files",
    },
    {
        "label": "warning: an unbounded run is judged bounded",
        "file": "beantester/settings.py",
        "old": "    if not armed_global_impairments(s):\n        return False",
        "new": "    if armed_global_impairments(s) is not None:\n        return False",
        "test": "test_a_run_that_impairs_everything_forever_says_so_before_it_starts",
    },
    {
        "label": "warning: LAN mode is demoted from impairment to scenery",
        "file": "beantester/fields.py",
        "old": "          tip=\"tips.lan_mode\", span=True, cli=\"lan-mode\", impairs=IMPAIRS_ALL),",
        "new": "          tip=\"tips.lan_mode\", span=True, cli=\"lan-mode\"),",
        "test": "test_the_warning_names_lan_mode_which_reads_like_a_scope",
    },
    {
        "label": "warning: blocking counts as a bound for every other impairment",
        "file": "beantester/fields.py",
        "old": "          width=26, tip=\"tips.block\", span=True, cli=\"block-ip\",\n"
               "          impairs=IMPAIRS_MATCHED),",
        "new": "          width=26, tip=\"tips.block\", span=True, cli=\"block-ip\",\n"
               "          narrows=True),",
        "test": "test_blocking_bounds_only_its_own_damage",
    },
    {
        "label": "warning: an expression of pure exclusions passes as a target",
        "file": "beantester/matchers.py",
        "old": "        return not self._positives",
        "new": "        return False",
        "test": "test_an_exclusion_only_target_is_not_a_bound",
    },
    {
        "label": "scenario: the file is read only after the capture is open again",
        "file": "beantester/cli.py",
        "old": "    scen = None\n    if cfg[\"scenario\"]:\n        try:\n"
               "            scen = load_scenario_file(cfg[\"scenario\"])",
        "new": "    scen = None\n    if False:\n        try:\n"
               "            scen = load_scenario_file(cfg[\"scenario\"])",
        "test": "test_a_broken_scenario_never_opens_the_capture",
    },
    {
        "label": "warning: the GUI starts an unbounded run in silence",
        "file": "beantester/gui/app.py",
        "old": "        warn_if_unbounded(s, self.log)\n"
               "        # Immediate feedback",
        "new": "        pass\n"
               "        # Immediate feedback",
        "test": "test_the_gui_says_the_same_thing_before_an_unbounded_start",
    },
    {
        "label": "warning: a session that BECOMES unbounded says nothing",
        "file": "beantester/gui/app.py",
        "old": "        warn_if_unbounded(s, self.log)\n"
               "        self.engine.log_event(\"CHANGE\"",
        "new": "        pass\n"
               "        self.engine.log_event(\"CHANGE\"",
        "test": "test_the_gui_says_the_same_thing_before_an_unbounded_start",
    },
    {
        "label": "warning: --dry-run previews the values but not the shape",
        "file": "beantester/cli.py",
        "old": "            if not cfg[\"simulate\"]:\n"
               "                warn_if_unbounded(cfg[\"settings\"], log.warn)",
        "new": "            if False:\n"
               "                warn_if_unbounded(cfg[\"settings\"], log.warn)",
        "test": "test_dry_run_previews_the_shape_and_not_only_the_values",
    },
    {
        "label": "help: a semicolon creeps back into a flag's help text",
        "file": "beantester/cli.py",
        "old": "help=\"which traffic to capture at all (IPv4 and IPv6). Ports are \"",
        "new": "help=\"which traffic to capture at all (IPv4 and IPv6); ports are \"",
        "test": "test_no_semicolons_in_the_help_a_user_reads",
    },
    {
        "label": "errors: a config value is called invalid and left at that",
        "file": "beantester/settings.py",
        "old": "                                       field=key, value=repr(value),\n"
               "                                       expected=_expected_shape(key)))",
        "new": "                                       field=key, value=repr(value),\n"
               "                                       expected=\"\"))",
        "test": "test_a_config_value_says_what_the_setting_takes",
    },
    {
        "label": "errors: the scenario stops suggesting a correction",
        "file": "beantester/scenario.py",
        "old": "            if len(unknown) == 1 and close:",
        "new": "            if False:",
        "test": "test_a_misspelled_scenario_setting_gets_the_same_help_as_a_config_one",
    },
    {
        "label": "errors: a blame word creeps back into a message",
        "file": "lang/en.json",
        "old": "\"errors.bad_schedule_step\": \"Schedule step '{part}' is not in "
               "the form dur:down:up.\"",
        "new": "\"errors.bad_schedule_step\": \"bad schedule step: '{part}'.\"",
        "test": "test_no_message_blames_the_person_reading_it",
    },
    {
        "label": "errors: saving a profile throws the precise message away again",
        "file": "beantester/gui/app.py",
        "old": "            dialogs.show_error(self.root, T(\"log.error\"), str(e))\n"
               "            return\n"
               "        self._persist_profiles()",
        "new": "            dialogs.show_error(self.root, T(\"log.error\"), \"nope\")\n"
               "            return\n"
               "        self._persist_profiles()",
        "test": "test_saving_a_profile_with_a_bad_value_names_the_field",
    },
    {
        "label": "errors: a message loses its full stop",
        "file": "lang/en.json",
        "old": "\"errors.scenario_bad_json\": \"Not a valid JSON file: {error}.\"",
        "new": "\"errors.scenario_bad_json\": \"Not a valid JSON file: {error}\"",
        "test": "test_every_error_reads_like_a_sentence",
    },
    {
        "label": "keyboard: Ctrl+F is bound on the entry, not on the window",
        "file": "beantester/gui/pages/conns.py",
        "old": "            app.root.bind(\"<Control-f>\", self._focus_search)",
        "new": "            entry.bind(\"<Control-f>\", self._focus_search)",
        "test": "test_the_table_is_reachable_and_readable_without_a_mouse",
    },
    {
        "label": "public: the privacy scan reads an empty file list",
        "file": "tests/test_repo_conventions.py",
        "old": "    files = repo_text_files((\".py\", \".md\", \".json\", \".txt\", \".toml\", \".spec\", \".yml\"))\n"
               "    check(\"the privacy scan actually read the repository\"",
        "new": "    files = []\n"
               "    check(\"the privacy scan actually read the repository\"",
        "test": "test_nothing_private_to_this_machine_reaches_the_public_repository",
    },
    {
        "label": "licence: the notices name a WinDivert file that is not shipped",
        "file": "THIRD-PARTY-NOTICES.md",
        "old": "## WinDivert (`WinDivert64.dll`, `WinDivert64.sys`)",
        "new": "## WinDivert (`WinDivert.dll`, `WinDivert64.sys`)",
        "test": "test_the_notices_name_the_windivert_files_that_are_really_shipped",
    },
    {
        "label": "licence: the written offer drops below the three-year floor",
        "file": "THIRD-PARTY-NOTICES.md",
        "old": "**Written offer:** for at least three years from the date of this release, the",
        "new": "**Written offer:** for as long as this release is distributed, the",
        "test": "test_the_written_offer_lasts_as_long_as_the_licence_demands",
    },
    {
        "label": "licence: the About window drops the no-warranty notice",
        "file": "beantester/gui/panels/about.py",
        "old": "        line(text=T(\"about.no_warranty\"), style=\"Muted.TLabel\").pack(",
        "new": "        line(text=\"\", style=\"Muted.TLabel\").pack(",
        "test": "test_the_about_window_is_a_complete_legal_notice",
    },
    {
        "label": "keyboard: the search box stops advertising its shortcut",
        "file": "beantester/gui/pages/conns.py",
        "old": "        add_tooltip(entry, \"tips.conn_search\", shortcut=\"Ctrl+F\")",
        "new": "        add_tooltip(entry, \"tips.conn_search\")",
        "test": "test_shortcut_buttons_advertise_their_key",
    },
    {
        "label": "keyboard: the context menu goes back to mouse-only",
        "file": "beantester/gui/pages/conns.py",
        "old": "        for sequence in (\"<Shift-F10>\", menu_key):",
        "new": "        for sequence in ():",
        "test": "test_the_table_is_reachable_and_readable_without_a_mouse",
    },
    {
        "label": "tables: an empty table goes back to a blank rectangle",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": ("        self.repaint()\n"
                "        self._show_empty_note(not self.items)"),
        "new": "        self.repaint()",
        "test": "test_an_empty_table_says_so_instead_of_showing_a_blank_rectangle",
    },
    {
        "label": "tables: an unsearched empty table blames a search nobody made",
        "file": "beantester/gui/pages/conns.py",
        "old": ("        self.table.set_empty_text(\"tables.no_conns_match\"\n"
                "                                  if self.search_var.get().strip()\n"
                "                                  else \"tables.no_conns_yet\")"),
        "new": "        self.table.set_empty_text(\"tables.no_conns_match\")",
        "test": "test_an_empty_table_says_so_instead_of_showing_a_blank_rectangle",
    },
    {
        "label": "help: an example hardcodes the .py name the exe user lacks",
        "file": "beantester/cli.py",
        "old": "  %(prog)s --simulate --loss 20 --duration 10",
        "new": "  bean_network_tester.py --simulate --loss 20 --duration 10",
        "test": "test_the_examples_name_whatever_this_build_is_called",
    },
    {
        "label": "help: the usage wall comes back over the examples",
        "file": "beantester/cli.py",
        "old": "        usage=\"%(prog)s [options]\",",
        "new": "",
        "test": "test_help_opens_with_examples_and_not_with_a_wall_of_usage",
    },
    {
        "label": "tables: every column goes back to being left-aligned",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": ("        if col in self._numeric:\n"
                "            return \"e\""),
        "new": ("        if False:\n"
                "            return \"e\""),
        "test": "test_numeric_columns_are_right_aligned_and_the_registry_is_honest",
    },
    {
        "label": "tables: a number is left touching the text beside it",
        "file": "beantester/gui/pages/conns.py",
        "old": "CENTERED = frozenset({\"proto\", \"scoped\"})",
        "new": "CENTERED = frozenset({\"proto\"})",
        "test": "test_numeric_columns_are_right_aligned_and_the_registry_is_honest",
    },
    {
        "label": "tables: the numeric registry quietly loses a column",
        "file": "beantester/gui/pages/conns.py",
        "old": "NUMERIC = frozenset({\"pid\", \"remote_port\", \"local_port\", \"packets\", \"dropped\",",
        "new": "NUMERIC = frozenset({\"remote_port\", \"local_port\", \"packets\", \"dropped\",",
        "test": "test_numeric_columns_are_right_aligned_and_the_registry_is_honest",
    },
    {
        "label": "tables: an impaired row is marked by colour alone again",
        "file": "beantester/gui/theme.py",
        "old": "    \"impaired\": {\"foreground\": \"#ffb454\", \"font\": (FONT, 9, \"bold\")},",
        "new": "    \"impaired\": {\"foreground\": \"#ffb454\"},",
        "test": "test_an_impaired_row_is_not_marked_by_colour_alone",
    },
    {
        "label": "readme: a semicolon hides inside a nested list again",
        "file": "README.md",
        "old": "With nothing set they are equal. The moment",
        "new": "With nothing set they are equal; the moment",
        "test": "test_no_semicolons_in_readme_prose",
    },
    {
        "label": "help: the semicolon scan reads an empty parser",
        "file": "tests/test_cli_docs.py",
        "old": "    helps = [a for a in parser._actions if a.help]",
        "new": "    helps = []",
        "test": "test_no_semicolons_in_the_help_a_user_reads",
    },
    {
        "label": "guards: a HANDOFF brief falls back into the scanned set",
        "file": "tests/test_repo_conventions.py",
        "old": "SKIP_PREFIXES = (\"HANDOFF-\",)",
        "new": "SKIP_PREFIXES = ()",
        "test": "test_the_repository_scanners_stay_out_of_what_is_not_in_the_repository",
    },
    {
        "label": "guards: internal_tools falls back into the scanned set",
        "file": "tests/test_repo_conventions.py",
        "old": "\"internal_tools\", \".claude\", \"crashes\"}",
        "new": "\".claude\", \"crashes\"}",
        "test": "test_the_repository_scanners_stay_out_of_what_is_not_in_the_repository",
    },
    {
        "label": "shape: the package walk finds no files to measure",
        "file": "tests/test_code_shape.py",
        "old": "        out += [os.path.join(dirpath, n) for n in filenames if n.endswith(\".py\")]",
        "new": "        out += []",
        "test": "test_no_function_or_file_has_grown_past_the_ratchet",
    },
    {
        "label": "shape: comments start counting as logic",
        "file": "tests/test_code_shape.py",
        "old": "        if text and not text.startswith(\"#\") and number not in doc:",
        "new": "        if text:",
        "test": "test_the_ratchet_measures_logic_and_not_explanation",
    },
    {
        "label": "hot path: decide() starts keeping one object per packet",
        "file": "beantester/core.py",
        "old": "        with self._lock:\n            # 1) process targeting",
        "new": ("        with self._lock:\n"
                "            self.__dict__.setdefault(\"_leak\", []).append(size)\n"
                "            # 1) process targeting"),
        "test": "test_the_decision_path_retains_nothing_per_packet",
    },
    {
        "label": "hot path: the allocation meter stops seeing retention",
        "file": "tests/test_hot_path_allocations.py",
        "old": "        kept = [object() for _ in range(5000)]",
        "new": "        kept = [object() for _ in range(0)]",
        "test": "test_the_meter_can_actually_see_retention",
    },
    {
        "label": "driver: a start failure goes back to blaming the user's rights",
        "file": "beantester/gui/app.py",
        "old": "                hint = T(key) if key else \"\"",
        "new": "                hint = T(\"dialogs.run_as_admin\")",
        "test": "test_the_start_failure_advice_fits_the_failure_not_every_failure",
    },
    {
        "label": "driver: the console drops the advice and prints the raw error",
        "file": "beantester/cli.py",
        "old": "        _fail(exitcodes.RUNTIME, f\"cannot start the capture: {e}\"\n"
               "              + (f\"\\n{T(hint)}\" if hint else \"\"))",
        "new": "        _fail(exitcodes.RUNTIME, f\"cannot start the capture: {e}\")",
        "test": "test_the_console_also_says_what_to_do_about_a_driver_that_will_not_open",
    },
    {
        "label": "driver: the exit path stops a driver another instance is using",
        "file": "beantester/driver.py",
        "old": "        if _drop_use_marker():",
        "new": "        if _drop_use_marker() and False:",
        "test": "test_the_exit_path_stands_down_when_another_instance_is_using_the_driver",
    },
    {
        "label": "driver: --doctor calls a machine mid-unload healthy again",
        "file": "beantester/driver.py",
        "old": "                           \"warn\" if (running or blocked or stopping) else \"ok\",",
        "new": "                           \"warn\" if (running or blocked) else \"ok\",",
        "test": "test_doctor_does_not_call_a_machine_healthy_while_nothing_can_start",
    },
    {
        "label": "driver: a start no longer waits for a driver that is unloading",
        "file": "beantester/engine.py",
        "old": "                self._open_divert()",
        "new": "                self._divert.open()",
        "test": "test_a_driver_that_is_still_unloading_is_waited_for_not_reported",
    },
    {
        "label": "driver: a scheduled removal is reported as a failure again",
        "file": "beantester/driver.py",
        "old": "            if err == _ERROR_SERVICE_MARKED_FOR_DELETE:\n"
               "                return f\"{name}: stopped (removal was already scheduled)\"",
        "new": "            if False:\n"
               "                return f\"{name}: stopped (removal was already scheduled)\"",
        "test": "test_a_removal_windivert_already_scheduled_is_not_reported_as_a_failure",
    },
]

# The runner's own check: a patch that cannot compile must be reported as BROKEN, not
# as "caught". Without it, a tree that fails to build looks exactly like a mutation
# the suite detected, and every other line of the report becomes worthless.
CANARY = {
    "label": "CANARY: deliberately unparsable, must report BROKEN",
    "file": "beantester/utils.py",
    "old": "def clamp01(",
    "new": "def ((( clamp01(",
    "test": "test_no_old_name_references",
}

# A mutation was run and dated by a session, but nobody wrote the patch down, so no
# machine can repeat it. This is weaker than MUTATIONS and stronger than nothing -
# and it is the honest state of most "verified by mutation" lines in the notes.
PROVEN_BY_HAND = {
    # No re-runnable patch is possible here: in a healthy tree EVERY workflow
    # script is tracked, so disabling the check has nothing left to fail on - the
    # mutant survives for the same reason the guard is quiet, which is not a fault
    # in either. Proven the only way it can be: by committing the mistake. Moving
    # tools/check_public_text.py into internal_tools/ (2026-08-04) turned the test
    # red at once, and moving it back turned it green.
    "test_every_script_the_workflows_run_is_actually_in_the_repository":
        "2026-08-04, moved a workflow script into internal_tools/ and back",
    # test_shortcut_buttons_advertise_their_key moved to MUTATIONS on 2026-08-03,
    # when Ctrl+F gave it a patch worth writing down. This list is meant to shrink.
    "test_an_overridden_field_is_visibly_disabled": "2026-07-21, removing the disabled style maps",
    "test_no_stale_pending_markers": "2026-07-25, both directions",
    "test_every_remote_endpoint_gate_fires_in_both_directions": "2026-07, the inbound branch",
    "test_a_worker_thread_exception_is_recorded": "2026-08-01, the excepthook body",
    "test_pid_for_takes_no_lock_because_the_capture_thread_calls_it": "2026-07-29, taking the lock",
}

# No mutation at all. Naming them is the point: an unproven guard and a guard nobody
# looked at must not read the same. This list is allowed to grow only when a guard
# is added without its proof - and every entry is a debt.
NOT_PROVEN = {
    "test_a_resize_after_the_label_is_gone_is_not_a_crash": "never mutated",
    "test_the_ui_rebuild_does_not_pile_up_configure_handlers_on_the_root": "never mutated",
    "test_an_injected_rst_is_always_recomputed": "never mutated",
    "test_evicting_the_connection_log_can_never_empty_it": "never mutated",
}


def _known_test_names():
    names = set()
    for path in glob.glob(os.path.join(ROOT, "tests", "test_*.py")):
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    names.add(node.name)
    return names


def test_every_mutation_still_points_at_code_that_exists():
    """The registry rots the moment the code it patches moves.

    A stale pattern makes the runner print SKIP - but only for whoever runs it, and
    the entry keeps LOOKING like a proof in the meantime. Checking the occurrence
    count here means the suite says it the day the code changes, which is the whole
    difference between a registry and a list of good intentions.
    """
    for entry in MUTATIONS + [CANARY]:
        path = os.path.join(ROOT, entry["file"])
        check(f"{entry['label']}: {entry['file']} exists", os.path.exists(path))
        # Read the way the RUNNER reads - bytes, then normalise - not in text mode.
        # Text mode applies universal newlines, so a pattern written with `\n` matches
        # a CRLF file here and does NOT match in a runner that works on raw bytes.
        # That happened: entries aiming at `sortable_tree.py` (600 CRLF) reported SKIP
        # while this test called them healthy. Two checks of the same fact must not
        # read it two different ways.
        with open(path, "rb") as handle:
            text = handle.read().decode("utf-8").replace("\r\n", "\n")
        found = text.count(entry["old"])
        check(f"{entry['label']}: its search pattern occurs exactly once "
              f"(a stale pattern proves nothing and reports SKIP)",
              found == 1, f"(found {found} times)")


def test_every_named_test_exists_and_has_exactly_one_state():
    """A guard is proven, hand-proven or unproven - never two of those, never none.

    The state being VISIBLE is the point. Two rows of another project's regression
    table said "verified by mutation" with no entry behind them, and the only reason
    anyone found out was a test exactly like this one.
    """
    known = _known_test_names()
    states = {}
    for entry in MUTATIONS:
        states.setdefault(entry["test"], set()).add("MUTATIONS")
    for name in PROVEN_BY_HAND:
        states.setdefault(name, set()).add("PROVEN_BY_HAND")
    for name in NOT_PROVEN:
        states.setdefault(name, set()).add("NOT_PROVEN")

    for name, where in sorted(states.items()):
        check(f"{name} is a real test (a registry naming a ghost is worse than "
              f"an empty registry)", name in known, f"(listed in {sorted(where)})")
        check(f"{name} is filed under exactly one state", len(where) == 1,
              f"(in {sorted(where)})")


def test_the_canary_is_not_quietly_disarmed():
    """The canary must name a real test and a real file, or the runner cannot fail.

    A runner whose canary silently stops firing reports "everything caught" for a
    run that proved nothing - which is worse than not running it, because it is
    quotable.
    """
    check("the canary names a test that exists",
          CANARY["test"] in _known_test_names(), f"({CANARY['test']})")
    check("the canary would really break the parse", "(((" in CANARY["new"])
