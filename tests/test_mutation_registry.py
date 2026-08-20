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
        "label": "upgrade: a config file stops getting defaults for keys it omits",
        "file": "beantester/settings.py",
        "old": "    s = dict(DEFAULT_SETTINGS)\n"
               "    s.update({k: _coerce_setting(k, v) for k, v in data.items()})\n"
               "    return s",
        "new": "    return {k: _coerce_setting(k, v) for k, v in data.items()}",
        "test": "test_a_config_file_from_every_release_still_loads",
    },
    {
        # The historical bug in miniature: absence collapsing into zero, where
        # zero on `buffer` means an UNBOUNDED queue.
        "label": "upgrade: an absent profile field zero-fills instead of "
                 "taking its own default",
        "file": "beantester/gui/profiles.py",
        "old": "                raw = PRESET_DEFAULTS[key]",
        "new": "                raw = 0",
        "test": "test_a_profile_from_every_release_still_loads_with_its_own_defaults",
    },
    {
        # Names a field instead of reading the registry - the exact shape the
        # guard used to have, and the one that let narrow_filter through.
        "label": "gui: is_locked names a field instead of reading start_only",
        "file": "beantester/gui/form.py",
        "old": '        return bool(FIELDS[key].start_only and getattr(self.app, "running", False))',
        "new": '        return bool(key == "duration" and getattr(self.app, "running", False))',
        "test": "test_start_only_fields_are_locked_while_a_session_runs",
    },
    {
        # The SBOM could not name the tool that froze the binary, whose bootloader
        # ships inside it under its own licence.
        "label": "sbom: the registry stops asking for the PyInstaller version",
        "file": "beantester/legal.py",
        "old": '        elif name.startswith("PyInstaller"):\n'
               "            version = _pyinstaller_version()\n",
        "new": "",
        "test": "test_the_sbom_names_the_pyinstaller_that_froze_the_build",
    },
    {
        # The other direction, which matters more: inside the shipped exe there is
        # no PyInstaller to ask, and the answer there must stay "no assertion".
        "label": "sbom: an absent build tool gets an invented version",
        "file": "beantester/legal.py",
        "old": '        return "bundled"\n\n\ndef component_rows():',
        "new": '        return "0.0.0"\n\n\ndef component_rows():',
        "test": "test_a_build_tool_that_is_not_installed_is_not_invented",
    },
    {
        # The one defect in this work that CI found and this machine could not:
        # relpath raises across drives, and the Windows runner keeps the repo and
        # the temp directory on different ones.
        "label": "packaging: the renderer raises when its output is on another drive",
        "file": "tools/build_packages.py",
        "old": "    try:\n        return os.path.relpath(path, ROOT)\n"
               "    except ValueError:\n        return path\n",
        "new": "    return os.path.relpath(path, ROOT)\n",
        "test": "test_rendering_onto_another_drive_is_not_a_crash",
    },
    {
        # The only place the interface answers "where are my profiles". This guard
        # was VACUOUS at first: it asserted the path alone, and from sources the
        # data directory is the project root, which is a prefix of the licence-texts
        # path shown two lines below - so another line satisfied it. It now asserts
        # the whole rendered sentence.
        "label": "about: the window stops naming the user's data directory",
        "file": "beantester/gui/panels/about.py",
        "old": '        text.insert("end", "\\n" + T("about.data_dir", '
               'path=user_data_dir()) + "\\n")\n',
        "new": "",
        "test": "test_the_about_window_says_where_the_users_files_are",
    },
    {
        "label": "doctor: stops printing where the user's files are",
        "file": "beantester/cli.py",
        "old": '        log.data(dict(), f"user files: {where}")\n',
        "new": "",
        "test": "test_doctor_says_where_the_users_own_files_are",
    },
    {
        "label": "doctor: the JSON report loses the data_dir field",
        "file": "beantester/cli.py",
        "old": 'log.data(dict(event="doctor", ok=ok, data_dir=where,',
        "new": 'log.data(dict(event="doctor", ok=ok,',
        "test": "test_doctor_says_where_the_users_own_files_are",
    },
    {
        # Without this field WinGet reaches the exe through a symlink, which severs
        # it from the _internal directory it cannot run without. The package would
        # install cleanly and then fail to start.
        "label": "packaging: the winget manifest drops ArchiveBinariesDependOnPath",
        "file": "packaging/winget/installer.yaml.in",
        "old": "ArchiveBinariesDependOnPath: true\n",
        "new": "",
        "test": "test_the_winget_manifest_keeps_the_exe_with_its_siblings",
    },
    {
        # Convention 34 in the place it is easiest to break: a manifest with a
        # hand-typed version still parses, and still points at the wrong build.
        "label": "packaging: a version number is typed into a manifest",
        "file": "packaging/winget/version.yaml.in",
        "old": "PackageVersion: {{VERSION}}",
        "new": "PackageVersion: 0.4.0",
        "test": "test_no_package_source_carries_a_version_number",
    },
    {
        # This one SURVIVED at first: the guard searched the whole file, so the
        # comment explaining the call satisfied it after the call itself was gone.
        # The fix was to the test, which now reads only lines that invoke the exe.
        "label": "packaging: the chocolatey hook stops releasing the driver",
        "file": "packaging/chocolatey/tools/chocolateybeforemodify.ps1.in",
        "old": "& $exe --cleanup-driver | Write-Host",
        "new": "& $exe --version | Write-Host",
        "test": "test_the_chocolatey_scripts_release_the_driver_before_a_change",
    },
    {
        # The message that answers "where is my file". It was the basename while the
        # file sat next to the exe, and nothing else on screen names the directory.
        "label": "csv: the export log names the file but not where it went",
        "file": "beantester/gui/csv_export.py",
        "old": "app.log(f\"{T('log.conns_saved_to')} {path} ({len(rows)})\")",
        "new": "app.log(f\"{T('log.conns_saved_to')} {os.path.basename(path)} ({len(rows)})\")",
        "test": "test_both_exports_tell_the_user_the_whole_path",
    },
    {
        # The whole point of moving the user files: a package manager owns the
        # install directory and wipes it on upgrade. This is the old behaviour
        # put back, which is also what any writability probe would degrade into.
        "label": "paths: a frozen build writes user files next to the executable again",
        "file": "beantester/paths.py",
        "old": "    return os.path.join(_local_app_data(), TOOL_ID)",
        "new": "    return executable_dir()",
        "test": "test_a_frozen_build_keeps_no_user_file_next_to_the_executable",
    },
    {
        # The display's source order. Reversed, a connection row names whatever a
        # snapshot taken a few times a second last saw, while the gate is judging
        # by the live map - the exact reported shape, from the other direction.
        "label": "attribution: the display asks the poller before the live map",
        "file": "beantester/engine.py",
        "old": "        watcher = self._socketwatch      # read ONCE: stop() clears it concurrently\n"
               "        if watcher is not None:\n"
               "            pid = watcher.pid_for(local_port)\n"
               "            if pid is not None:\n"
               "                return pid\n"
               "        return self._ports.pid_for(local_port)\n",
        "new": "        pid = self._ports.pid_for(local_port)\n"
               "        if pid is not None:\n"
               "            return pid\n"
               "        watcher = self._socketwatch\n"
               "        return watcher.pid_for(local_port) if watcher is not None else None\n",
        "test": "test_the_gate_and_the_display_agree_whenever_the_live_map_knows_the_port",
    },
    {
        # A fifth consumer inherits the fallback silently. This is the entry that
        # makes the guard a RULE rather than a check on two functions.
        "label": "attribution: a new consumer of the owner lookup appears",
        "file": "beantester/engine.py",
        "old": "    def stats_snapshot(self):\n",
        "new": "    def owner_hint(self, port):\n"
               "        return self._live_pid(port)\n\n"
               "    def stats_snapshot(self):\n",
        "test": "test_every_consumer_of_the_owner_lookup_is_one_this_file_knows_about",
    },
    {
        # The gate's side of the same rule. It SURVIVED at first: the real
        # process-wide poller answers None for an unused port, so the fallback was
        # invisible until the test made that poller answer.
        "label": "attribution: the gate grows a second source underneath",
        "file": "beantester/targeting.py",
        "old": "        pid = pid_for(port)\n        return pid is not None and pid in self._pids\n",
        "new": "        pid = pid_for(port)\n"
               "        if pid is None:\n"
               "            from . import portmap\n"
               "            pid = portmap.default_table().pid_for(port)\n"
               "        return pid is not None and pid in self._pids\n",
        "test": "test_the_gate_resolves_against_exactly_one_table",
    },
    {
        # Widget creation during Tk's destroy cascade, on a path bound to
        # <Destroy>. Reproduced on real Tk before the fix (see _hide_bubble).
        "label": "gui: hiding a bubble goes back to the path that CREATES one",
        "file": "beantester/gui/tooltip.py",
        "old": "        entry = _BUBBLES.get(str(widget.winfo_toplevel()))",
        "new": "        entry = _bubble_for(widget)",
        "test": "test_hiding_a_bubble_never_builds_a_window",
    },
    {
        # The cache is keyed by toplevel NAME and Tk does not reuse names.
        "label": "gui: dead bubble windows stop being pruned",
        "file": "beantester/gui/tooltip.py",
        "old": "    for dead in [k for k, e in _BUBBLES.items() if not _alive(e)]:\n"
               "        del _BUBBLES[dead]\n",
        "new": "",
        "test": "test_dead_bubbles_do_not_pile_up_across_windows",
    },
    {
        # A ratchet frozen one above the truth allows the next arrival in
        # silence - which is the drift it exists to catch, wearing its badge.
        "label": "ratchet: the crowd count is frozen looser than the measurement",
        "file": "tests/test_code_shape.py",
        "old": "FILES_NEAR_CEILING = 1          # beantester/gui/app.py",
        "new": "FILES_NEAR_CEILING = 3          # beantester/gui/app.py",
        "test": "test_the_crowd_counts_are_not_set_so_loosely_that_they_never_fire",
    },
    {
        # The leak guard's newest half. It runs in CI and had never been shown
        # able to fail - the canary that finally did found it blind to exactly
        # the class the convention names first.
        "label": "leak: the private-literal check drops out of the scanner",
        "file": "tools/check_public_text.py",
        "old": "        low = line.lower()\n"
               "        if any(value in low for value in literals):",
        "new": "        low = line.lower()\n"
               "        if False and any(value in low for value in literals):",
        "test": "test_a_literal_from_the_private_list_is_caught_without_being_printed",
    },
    {
        # Half the predicate is what shipped, and half a guard on this question
        # let `--target *` silence the warning about damaging every connection
        # on the machine.
        "label": "blast radius: the narrowing check reads only half the question",
        "file": "beantester/settings.py",
        "old": "        if not matcher.bounds_nothing:",
        "new": "        if not matcher.selects_nothing_in_particular:",
        "test": "test_a_target_that_matches_everything_is_not_a_bound_either",
    },
    {
        # The class that already crashed this project once (driver._advapi). The
        # generic half of the guard: argtypes is the only part of a prototype that
        # ctypes leaves as None, so it is the only part a walk can check.
        "label": "native: a declared binding loses its argtypes",
        "file": "beantester/winenv.py",
        "old": "        lib.SetWindowPos.argtypes = [H, H, ctypes.c_int, ctypes.c_int,\n"
               "                                     ctypes.c_int, ctypes.c_int, wintypes.UINT]\n",
        "new": "",
        "test": "test_every_declared_native_function_has_a_full_prototype",
    },
    {
        # The specific half: a result that must be pointer-sized. Checked by name
        # because `restype` defaults to c_long and `c_long is c_int is BOOL` on
        # Windows, so "a restype was declared" is not a checkable statement.
        "label": "native: a handle-returning call is truncated to 32 bits",
        "file": "beantester/winenv.py",
        "old": "        lib.GetParent.restype = H\n",
        "new": "        lib.GetParent.restype = ctypes.c_int\n",
        "test": "test_every_declared_native_function_has_a_full_prototype",
    },
    {
        # What forces the NEXT native call into a factory instead of repeating
        # the history in a third module.
        "label": "native: a direct ctypes.windll call comes back into the theme",
        "file": "beantester/gui/theme.py",
        # Anchored on the line after it: the GetParent call itself appears in BOTH
        # theme functions, and the registry rightly refuses an ambiguous pattern.
        "old": "        hwnd = user32.GetParent(window.winfo_id())\n"
               "        get_long = ",
        "new": "        import ctypes\n"
               "        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())\n"
               "        get_long = ",
        "test": "test_no_new_native_call_bypasses_a_prototype",
    },
    {
        # The GUI half of native-crash capture. Without it a hard crash in a
        # process that never started a session is recorded NOWHERE - which is how
        # the 2026-08-04 access violation in `tkinter mainloop` came within one
        # earlier session of leaving nothing at all behind.
        "label": "crash: the GUI entry point stops arming native capture",
        "file": "beantester/cli.py",
        "old": "    crashlog.arm_native()\n    try:\n        import tkinter as tk",
        "new": "    try:\n        import tkinter as tk",
        "test": "test_the_gui_arms_native_capture_without_ever_starting_a_capture",
    },
    {
        # The mechanism can be perfect and still record nothing if the one caller
        # stops calling. This is the half that rots silently.
        "label": "crash: the GUI tick stops leaving a breadcrumb",
        "file": "beantester/gui/app.py",
        "old": "            gui_crash.leave_breadcrumb(self)   # state a NATIVE crash cannot write\n",
        "new": "",
        "test": "test_the_running_gui_actually_leaves_one",
    },
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
        "old": "          tip=\"tips.lan_mode\", span=False, cli=\"lan-mode\", impairs=IMPAIRS_ALL),",
        "new": "          tip=\"tips.lan_mode\", span=False, cli=\"lan-mode\"),",
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
        # Replaced 2026-08-18, and the reason is worth more than the entry was.
        # This used to break the Connections page's Ctrl+F by moving its binding
        # from the root onto the entry. Since the Control page grew a search box
        # of its own, BOTH pages bind the same dispatcher on the root - so losing
        # one of the two bindings changes nothing a user can see, and the old
        # mutation SURVIVED without anything being wrong. What is worth guarding
        # now is the dispatcher's decision: the shortcut must reach the box on the
        # page you are looking at, not always the table.
        "label": "keyboard: Ctrl+F ignores which page is in front",
        "file": "beantester/gui/pages/__init__.py",
        "old": "    page = app.current_page()",
        "new": "    page = None",
        "test": "test_one_ctrl_f_reaches_whichever_search_box_is_in_front",
    },
    {
        "label": "public: the privacy scan reads an empty file list",
        "file": "tests/test_repo_conventions.py",
        "old": "    files = repo_text_files((\".py\", \".md\", \".json\", \".txt\", \".toml\", \".spec\", \".yml\")\n"
               "                            + WEB_EXTS)\n"
               "    check(\"the privacy scan actually read the repository\"",
        "new": "    files = []\n"
               "    check(\"the privacy scan actually read the repository\"",
        "test": "test_nothing_private_to_this_machine_reaches_the_public_repository",
    },
    {
        # The site exists to produce this one click. A generator that points it a
        # level up still builds, still renders and still looks right.
        "label": "site: the download button stops at the releases list",
        "file": "tools/build_site.py",
        "old": "        \"site.download_url\": \"%s/releases/latest\" % repo,",
        "new": "        \"site.download_url\": \"%s/releases\" % repo,",
        "test": "test_the_download_button_points_at_the_release_page",
    },
    {
        # Two dark themes drifting apart is the failure nobody reports: each page
        # looks fine on its own, and only a side-by-side would show it.
        "label": "site: the palette stops coming from theme.py",
        "file": "tools/build_site.py",
        "old": "    colours = palette(root, registry[\"palette\"])",
        "new": "    colours = {var: \"#010203\" for var in registry[\"palette\"]}",
        "test": "test_the_palette_is_read_out_of_the_theme_module",
    },
    {
        # The regression this feature could most easily cause: a search that
        # unfolds the page FOR GOOD. `toggle` runs the accordion's callback, which
        # persists the fold state through App.on_sections_changed; `set_open` does
        # not, which is the whole reason the reveal path uses it.
        "label": "search: revealing a hit writes the fold state to ui.json",
        "file": "beantester/gui/pages/control.py",
        "old": "        if not panel.is_open:\n            panel.set_open(True)",
        "new": "        if not panel.is_open:\n            panel.toggle()",
        "test": "test_a_hit_in_a_folded_section_is_opened_but_never_remembered",
    },
    {
        # Reported from the running program: with a column hidden, every header
        # to its right explained the wrong one - including columns that were not
        # on screen at all. Forcing the fallback path puts that back.
        "label": "tables: a header tooltip counts hidden columns again",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "            identifier = self.tree.column(spec, \"id\")",
        "new": "            identifier = None",
        "test": "test_a_header_tooltip_still_names_its_own_column_after_others_are_hidden",
    },
    {
        # A second hand-written list of rows is how the copy comes to show
        # yesterday's panel: the text has to be built from the registry the panel
        # itself renders.
        "label": "stats: the session copy stops following the row registry",
        "file": "beantester/gui/pages/stats.py",
        "old": "            for key, cap, _tip in SESSION_ROWS if key in self.sess_labels)",
        "new": "            for key, cap, _tip in SESSION_ROWS[:4] if key in self.sess_labels)",
        "test": "test_the_session_panel_copies_exactly_what_it_shows",
    },
    {
        # The owner's report: with several matches, nothing said which one Enter
        # had taken you to. If every hit is painted the same the count is a
        # promise the page does not keep.
        "label": "search: every match is painted as the current one",
        "file": "beantester/gui/pages/control.py",
        "old": "                widget.configure(style=current if index == self._at else other)",
        "new": "                widget.configure(style=current)",
        "test": "test_the_hit_you_are_on_looks_different_from_the_rest",
    },
    {
        # Measured on real Tk: a dropdown marks its section header, and that
        # header is often a hit itself - the second claim repainted the first and
        # the current hit vanished.
        "label": "search: two hits may claim the same widget again",
        "file": "beantester/gui/pages/control.py",
        "old": "            if mark is None or any(mark[0] is widget for widget in seen):",
        "new": "            if mark is None:",
        "test": "test_two_hits_never_fight_over_one_widget",
    },
    {
        # Half a feature, and the half nobody can diagnose from outside: Polish
        # labels carry diacritics and people type without them.
        "label": "search: matching stops ignoring Polish diacritics",
        "file": "beantester/gui/form_search.py",
        "old": "    decomposed = unicodedata.normalize(\"NFKD\", str(text or \"\"))",
        "new": "    decomposed = str(text or \"\")",
        "test": "test_an_accented_label_is_reachable_without_its_accents",
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
        "file": "beantester/gui/dialogs.py",
        "old": "    key = open_failure_hint(err, elevated)",
        "new": "    key = \"dialogs.run_as_admin\"",
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
        "label": "targeting: a new socket of a targeted process waits for a rebuild",
        "file": "beantester/targeting.py",
        "old": "        if pid in self._pids:\n            with self._ports_lock:",
        "new": "        if False:\n            with self._ports_lock:",
        "test": "test_a_new_socket_of_a_targeted_process_is_in_scope_from_its_event",
    },
    {
        "label": "targeting: a brand-new process is never adopted from its event",
        "file": "beantester/targeting.py",
        "old": "                if self._pid_matches(pid, name):\n"
               "                    matched.add(pid)",
        "new": "                if False:\n"
               "                    matched.add(pid)",
        "test": "test_a_brand_new_process_is_adopted_from_its_first_socket_event",
    },
    {
        "label": "targeting: the resolver stops draining pending pids",
        "file": "beantester/target_resolver.py",
        "old": "                targeting.adopt_new_pids()",
        "new": "                pass",
        "test": "test_the_resolver_adopts_a_new_pid_without_waiting_for_its_floor",
    },
    {
        "label": "targeting: a failed adoption is left to kill the resolver thread",
        "file": "beantester/target_resolver.py",
        "old": "            try:\n"
               "                targeting.adopt_new_pids()\n"
               "            except Exception as exc:\n"
               "                crashlog.once(\"targeting.adopt\", exc)",
        "new": "            targeting.adopt_new_pids()",
        "test": "test_a_failing_adoption_does_not_kill_the_resolver",
    },
    {
        "label": "targeting: a pid whose name will not resolve is written off",
        "file": "beantester/targeting.py",
        "old": "                elif name:\n                    judged.add(pid)",
        "new": "                else:\n                    judged.add(pid)",
        "test": "test_a_pid_whose_name_will_not_resolve_yet_is_asked_again_not_written_off",
    },
    {
        "label": "targeting: a rebuild in flight loses a socket the event added",
        "file": "beantester/targeting.py",
        "old": "                self._ports = resolved | late",
        "new": "                self._ports = resolved",
        "test": "test_a_rebuild_in_flight_does_not_lose_a_socket_the_event_added",
    },
    {
        "label": "targeting: a rescued port stops being checked against its owner",
        "file": "beantester/targeting.py",
        "old": "                late = frozenset(port for port, owner in self._late_owners.items()\n"
               "                                 if owner in pids)",
        "new": "                late = frozenset(self._late_owners)",
        "test": "test_a_recycled_pid_reaches_further_through_the_push_path_but_not_further_in_time",
    },
    {
        "label": "targeting: an adopted pid is kept for ever instead of re-judged",
        "file": "beantester/targeting.py",
        "old": "                self._pids = frozenset(pids)",
        "new": "                self._pids = self._pids | frozenset(pids)",
        "test": "test_an_adopted_pid_still_falls_out_at_the_next_rebuild",
    },
    {
        "label": "targeting: a ruled-out pid is looked up again on every socket",
        "file": "beantester/targeting.py",
        "old": "                with self._ports_lock:\n"
               "                    self._not_ours = self._not_ours | judged\n"
               "                return False",
        "new": "                return False",
        "test": "test_a_pid_that_does_not_match_is_judged_once_not_once_per_socket",
    },
    {
        "label": "targeting: the System process takes a port off a user process again",
        "file": "beantester/socketwatch.py",
        "old": "                if pid == _SYSTEM_PID and self._ports.get(port, _SYSTEM_PID) != _SYSTEM_PID:",
        "new": "                if False:",
        "test": "test_the_system_process_does_not_take_a_port_off_a_user_process",
    },
    {
        "label": "targeting: refusing a System event freezes the entry against the snapshot",
        "file": "beantester/socketwatch.py",
        "old": "                    self._events += 1\n                    return\n                self._ports[port] = pid",
        "new": "                    self._evidence[port] = self.clock()\n                    self._events += 1\n                    return\n                self._ports[port] = pid",
        "test": "test_refusing_the_system_event_leaves_the_snapshot_able_to_heal",
    },
    {
        "label": "targeting: the live map stops telling anybody about a new socket",
        "file": "beantester/socketwatch.py",
        "old": "                with crashlog.quiet(\"socketwatch.listener\"):\n"
               "                    listener(port, pid)",
        "new": "                pass",
        "test": "test_a_listener_is_told_about_each_socket_the_map_gains",
    },
    {
        "label": "targeting: clearing the target leaves the map calling an orphan",
        "file": "beantester/engine.py",
        "old": "        self._bind_socket_listener()\n"
               "        self.core.set_target(active, ports)",
        "new": "        self.core.set_target(active, ports)",
        "test": "test_the_engine_wires_the_live_map_to_targeting_and_unwires_it",
    },
    {
        "label": "targeting: a running watcher is not published for stop() to find",
        "file": "beantester/engine.py",
        "old": "        self._socketwatch = watcher\n        try:\n            watcher.start()",
        "new": "        try:\n            watcher.start()",
        "test": "test_the_socket_watcher_survives_start_stop_cycles",
    },
    {
        "label": "targeting: the bootstrap snapshot is taken before subscribing",
        "file": "beantester/engine.py",
        "old": "        try:\n"
               "            watcher.start()\n"
               "        except Exception as exc:\n"
               "            crashlog.once(\"engine.socketwatch.start\", exc)",
        "new": "        ports, collected_at = self._ports.collected()\n"
               "        try:\n"
               "            watcher.start()\n"
               "        except Exception as exc:\n"
               "            crashlog.once(\"engine.socketwatch.start\", exc)",
        "test": "test_the_event_source_is_open_before_the_bootstrap_snapshot_is_taken",
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
    {
        # The cap is what makes the fit safe: without it a single narrow column
        # would be stretched to the whole tree, far past anything a drag can reach.
        "label": "gui: the column fit stops respecting the drag cap",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "        take = min(caps[col] - out[col], int(slack * base[col] / total))",
        "new": "        take = int(slack * base[col] / total)",
        "test": "test_a_fit_never_takes_a_column_past_the_width_a_drag_could_reach",
    },
    {
        # With every column shown the table is WIDER than the tree and the
        # horizontal scrollbar is the right answer; fitting there would shrink
        # columns, which is the one thing this function must never do.
        "label": "gui: the column fit runs even when there is no slack",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "    if slack <= 0:\n        return {}",
        "new": "    if slack < -(10 ** 9):\n        return {}",
        "test": "test_a_full_or_overflowing_table_is_left_alone",
    },
    {
        # The memo is the rule that keeps a fit from undoing a drag. Removing it
        # makes every resize event overwrite the width the user chose.
        "label": "gui: a column fit forgets what it was last computed for",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "            if not force and token == self._fitted_for:",
        "new": "            if False:",
        "test": "test_a_width_the_user_dragged_survives_a_fit_but_hiding_a_column_re_fits",
    },
    {
        # The reported fault: a scroll region shorter than its viewport lets Tk
        # move the canvas origin above the content, so the Settings window showed
        # a blank band and the scrollbar swore there was nothing to scroll.
        "label": "gui: the scroll region stops being clamped to the viewport",
        "file": "beantester/gui/scrollable.py",
        "old": "    return (x0, y0, x1, max(y1, y0 + height))",
        "new": "    return (x0, y0, x1, y1)",
        "test": "test_a_scroller_whose_content_fits_is_still_confined_to_it",
    },
    {
        # The second way into the same fault, found while fixing the first:
        # configure(scrollregion=None) clears the region, and an unconfined canvas
        # is exactly what the clamp exists to prevent.
        "label": "gui: an empty canvas passes None through as its scroll region",
        "file": "beantester/gui/scrollable.py",
        "old": "    if not bbox:\n        x0 = y0 = x1 = y1 = 0",
        "new": "    if bbox is None:\n        return None",
        "test": "test_an_empty_canvas_still_gets_a_region_instead_of_none",
    },
    {
        # The 2026-08-17 failure in one line: an unpinned builder in a workflow.
        # CI resolved PyInstaller 6.22.1, this machine had 6.21.0, and only the
        # older one mis-handles Python 3.14's DLL-embedded Tcl/Tk 9 archive - so
        # the same commit built a working exe there and a crashing one here.
        "label": "release: a workflow installs the freezer unpinned again",
        "file": ".github/workflows/ci.yml",
        "old": "          pip install --require-hashes -r requirements.txt -r requirements-build.txt",
        "new": "          pip install -r requirements.txt pyinstaller",
        "test": "test_both_workflows_install_the_same_pinned_builder",
    },
    {
        # The other half: the file is wired in, but stops actually pinning. Kept
        # version-agnostic on purpose - `pyinstaller==` survives every bump, while
        # spelling the number here would make this entry go stale on each one.
        "label": "release: the builder pin loosens into a range",
        "file": "requirements-build.txt",
        "old": "pyinstaller==",
        "new": "pyinstaller>=",
        "test": "test_both_workflows_install_the_same_pinned_builder",
    },
    {
        # The one unverified link in a hash-checked chain: an unpinned pip, fetched
        # from the index a line before it is asked to verify our hashes. Additive on
        # purpose - it puts the line back without taking anything away, so exactly
        # one test answers.
        "label": "supply chain: a workflow upgrades pip from the index again",
        "file": ".github/workflows/ci.yml",
        "old": "          pip install --require-hashes -r requirements-lint.txt",
        "new": "          python -m pip install --upgrade pip\n"
               "          pip install --require-hashes -r requirements-lint.txt",
        "test": "test_no_workflow_bootstraps_pip_from_the_index",
    },
    {
        # The flag, not the file. Without --require-hashes the hashes still get
        # checked today and stop being checked the day a line loses its block -
        # a downgrade with no error anywhere.
        "label": "supply chain: an analysis job stops asking pip to check hashes",
        "file": ".github/workflows/ci.yml",
        "old": "      - name: Install the linter\n"
               "        run: pip install --require-hashes -r requirements-lint.txt",
        "new": "      - name: Install the linter\n"
               "        run: pip install -r requirements-lint.txt",
        "test": "test_every_install_of_a_hashed_file_asks_pip_to_check_the_hashes",
    },
    {
        # Version-agnostic like the pyinstaller entry above, and for the same
        # reason: spelling the number here would make the entry go stale on the
        # next bump. A closure line that stops being a pin breaks hash-checking
        # for the whole install, not just for itself.
        "label": "supply chain: a line in the lint closure loosens into a range",
        "file": "requirements-lint.txt",
        "old": "pluggy==",
        "new": "pluggy>=",
        "test": "test_the_analysis_tools_carry_their_artefact_hashes_too",
    },
    {
        # The permission that outlives the job it was written for: back at the top
        # of release.yml, where every job added later inherits it.
        # The filter a user reads stops being the filter that runs: a term ending
        # in a backslash escapes the separator `describe()` writes after it, and
        # two terms silently become one.
        "label": "matchers: a term keeps a trailing escape that eats the separator",
        "file": "beantester/matchers.py",
        "old": "        term = _without_a_dangling_escape(part.strip())",
        "new": "        term = part.strip()",
        "test": "test_a_term_may_not_end_in_an_escape_that_swallows_the_separator",
    },
    {
        # The OVER-correction, which is the likelier future mistake: stripping the
        # whole tail looks tidier and breaks `a\\`, which already round-tripped.
        "label": "matchers: the escape fix widens into stripping every trailing backslash",
        "file": "beantester/matchers.py",
        "old": "    return term[:-1] if trailing % 2 else term",
        "new": r'    return term.rstrip("\\")',
        "test": "test_a_term_may_not_end_in_an_escape_that_swallows_the_separator",
    },
    {
        # The command in the README stops matching what we attest, and every user who
        # follows it gets an error. Nothing here runs `gh`, so only this pairing can
        # notice.
        "label": "release: the documented verify command loses its predicate type",
        "file": "README.md",
        "old": " --predicate-type https://spdx.dev/Document/v2.3",
        "new": "",
        "test": "test_the_documented_verify_command_matches_what_we_actually_attest",
    },
    {
        # The escaping removed as "noise" - and the tool that writes our supply-chain
        # hashes can again be pointed at a different PyPI endpoint by a `?` in a
        # version string, silently answering about something else.
        "label": "supply chain: the hash generator stops escaping what it asks about",
        "file": "tools/pin_hashes.py",
        "old": 'return API % (quote(name, safe=""), quote(version, safe=""))',
        "new": "return API % (name, version)",
        "test": "test_no_version_can_truncate_the_path_into_a_query",
    },
    {
        # The simplification that puts an UNSIGNED executable on a public release
        # page for as long as the signing ritual takes. It looks like tidying: the
        # archive is right there, why not attach it.
        "label": "release: the draft ships the unsigned archive after all",
        "file": ".github/workflows/release.yml",
        "old": 'gh release create "$GITHUB_REF_NAME" "$SBOM" "${flags[@]}"',
        "new": 'gh release create "$GITHUB_REF_NAME" "$ASSET" "$SBOM" "${flags[@]}"',
        "test": "test_the_release_never_publishes_an_unsigned_archive",
    },
    {
        # "Signed" going back to being a claim instead of a measurement. A second
        # code-signing certificate on the same machine would then sign a release
        # under this project's name and nothing would say so.
        "label": "release: the signing script stops checking WHICH certificate signed",
        "file": "tools/sign_release.py",
        "old": "        if actual != CODESIGN_SHA256:",
        "new": "        if actual == CODESIGN_SHA256:",
        "test": "test_the_signing_certificate_is_pinned_by_its_bytes",
    },
    {
        # The tempting shortcut in the attestation half: it was HANDED a digest, so
        # why download the file. Because then it attests something nobody checked -
        # a rumour with a signature on it.
        "label": "attestation: the signed release is attested from a digest, not the file",
        "file": ".github/workflows/attest-release.yml",
        "old": "          subject-path: ${{ env.ARCHIVE }}",
        "new": "          subject-digest: sha256:${{ inputs.digest }}",
        "test": "test_the_signed_archive_is_attested_over_bytes_the_job_holds",
    },
    {
        # The one job here that costs money per run, and the line that decides whether
        # it runs at all. Measured at $2.92 a run before it was made optional, so an
        # automatic trigger put back "while tidying" is a standing bill nobody chose.
        "label": "review: the optional review goes back to running by itself",
        "file": ".github/workflows/claude-review.yml",
        "old": "  issue_comment:",
        "new": "  pull_request:\n    types: [opened]\n  issue_comment:",
        "test": "test_the_optional_review_never_runs_by_itself",
    },
    {
        "label": "supply chain: release.yml grants write at the file level again",
        "file": ".github/workflows/release.yml",
        "old": "permissions:\n  contents: read",
        "new": "permissions:\n  contents: write",
        "test": "test_the_release_workflow_grants_write_on_the_job_not_the_whole_file",
    },
    {
        # The correction that stops a rounded figure being printed in a unit
        # that cannot hold it: 1023.7 B rounds to 1024 B, and the byte band
        # ends at 1023. Leaving it out is the mistake every hand-rolled size
        # formatter makes, and it shows only on two values in a thousand.
        "label": "units: a rounded byte figure prints in a unit too small for it",
        "file": "beantester/utils.py",
        "old": "    if (index < len(BYTE_UNITS) - 1",
        "new": "    if False and (index < len(BYTE_UNITS) - 1",
        "test": "test_human_bytes_reads_at_every_size",
    },
    {
        # The change itself, in one cell: back to a fixed KB, where a 5 GB flow
        # reads "5242880.0" and a ninety-byte one reads "0.0".
        "label": "gui: a connection traffic cell goes back to a fixed unit",
        "file": "beantester/gui/pages/conns.py",
        "old": '                human_bytes(c.get(\"sent_in\", 0)),',
        "new": '                str(round(c.get(\"sent_in\", 0) / 1024.0, 1)),',
        "test": "test_connection_columns_tag_and_footer",
    },
    {
        # The footer carries the largest numbers on the page and is summed
        # separately from the cells, which is exactly how one of the two gets
        # left behind on a change like this.
        "label": "gui: the connections footer keeps a fixed unit",
        "file": "beantester/gui/pages/conns.py",
        "old": '                                  total=human_bytes(t[\"total\"])))',
        "new": '                                  total=str(round(t[\"total\"] / 1024.0, 1))))',
        "test": "test_connection_columns_tag_and_footer",
    },
    {
        # The exact line Semgrep found, put back: a `${{ }}` expanded into a
        # script is source code, not an argument. The guard has to see it
        # wherever in the block it sits, so this mutates only one of the two
        # variables and leaves the other in its safe form.
        "label": "ci: a workflow interpolates a GitHub expression into a script",
        "file": ".github/workflows/ci.yml",
        "old": 'python tools/check_public_text.py --commits \"origin/$BASE_REF..$HEAD_SHA\"',
        "new": 'python tools/check_public_text.py --commits origin/${{ github.base_ref }}..$HEAD_SHA',
        "test": "test_no_workflow_puts_a_github_expression_inside_a_shell_script",
    },
    {
        # One action slides back onto a floating tag - the state the whole
        # repository was in, and the one a hand-written `uses:` falls into.
        "label": "ci: an action goes back to a movable tag",
        "file": ".github/workflows/dependency-review.yml",
        "old": "actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294  # v5.0.0",
        "new": "actions/dependency-review-action@v5",
        "test": "test_every_action_a_workflow_uses_is_pinned_to_a_commit",
    },
    {
        # The other half of the same rule: a digest with nothing saying which
        # version it is. Legal YAML, unreadable diff, and Dependabot has
        # nothing to rewrite when it bumps the pin.
        "label": "ci: a pinned action stops saying which version it is",
        "file": ".github/workflows/dependency-review.yml",
        "old": "actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294  # v5.0.0",
        "new": "actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294",
        "test": "test_every_action_a_workflow_uses_is_pinned_to_a_commit",
    },
    {
        # The check that keeps `--repo` inside its own meaning. Without it the
        # value still lands in the PATH of an api.github.com URL, so
        # `../../gists` asks a different endpoint and prints the answer as if
        # those were releases.
        "label": "tools: the downloads repository argument stops being checked",
        "file": "tools/downloads.py",
        "old": "    if not REPO.match(str(repo or \"\")):",
        "new": "    if False and not REPO.match(str(repo or \"\")):",
        "test": "test_the_downloads_tool_refuses_anything_that_is_not_owner_slash_name",
    },
    {
        # The crash id is printed in a record a user may paste into a report,
        # so its shape is the contract - not the hash behind it.
        "label": "crashlog: the crash id stops being twelve characters",
        "file": "beantester/crashlog.py",
        "old": ".hexdigest()[:12]",
        "new": ".hexdigest()",
        "test": "test_different_faults_get_different_fingerprints",
    },
    {
        # One byte of the recorded driver hash. The version resource still reads
        # 2.2 - which is exactly what a swapped kernel driver looks like.
        "label": "legal: the recorded WinDivert driver hash stops matching",
        "file": "beantester/legal.py",
        "old": "8da085332782708d8767bcace5327a6ec7283c17cfb85e40b03cd2323a90ddc2",
        "new": "0da085332782708d8767bcace5327a6ec7283c17cfb85e40b03cd2323a90ddc2",
        "test": "test_the_shipped_driver_is_byte_for_byte_the_one_we_recorded",
    },
    {
        # The line that makes an undetectable licence block. Without it this gate
        # agrees with the official action: informs, and passes.
        "label": "deps: an undetectable licence stops blocking",
        "file": "tools/dependency_gate.py",
        "old": "    if licence is None or not str(licence).strip():",
        "new": "    if False and (licence is None or not str(licence).strip()):",
        "test": "test_an_unknown_licence_blocks",
    },
    {
        # A module quietly dropping out of the strict list. The check that
        # vanishes cannot fail, which is why the list is recorded twice.
        "label": "types: a module loses its strict typing quietly",
        "file": "pyproject.toml",
        "old": 'module = ["beantester.utils", "beantester.gui.rates", "beantester.gui.scope"]',
        "new": 'module = ["beantester.gui.rates", "beantester.gui.scope"]',
        "test": "test_the_strictly_typed_modules_only_ever_grow",
    },
    {
        # How the white menu got in: one of the two menus in the program was
        # built bare. The rule guard reads the source, so this is the patch it
        # has to see.
        "label": "gui: a context menu is built without the dark theme",
        "file": "beantester/gui/pages/stats.py",
        "old": "menu = style_menu(tk.Menu(self.frame, tearoff=0))",
        "new": "menu = tk.Menu(self.frame, tearoff=0)",
        "test": "test_every_context_menu_is_handed_to_the_dark_theme",
    },
    {
        # The other half, and the reason both exist: "style_menu was called" and
        # "the menu is dark" are two claims. This one breaks the wrapper while
        # leaving every call site intact, so only the behavioural test can see it.
        "label": "gui: the menu theme stops setting a background",
        "file": "beantester/gui/theme.py",
        "old": "        menu.configure(background=BG2, foreground=FG,",
        "new": "        menu.configure(foreground=FG,",
        "test": "test_the_statistics_copy_menu_is_dark_like_every_other_context_menu",
    },
    {
        # pack hands out space in CALL order, so the bar comes back UNDER the
        # whole page body. The fake cannot render it - it can only see that the
        # call no longer says where to sit.
        "label": "gui: the search bar comes back without saying where to sit",
        "file": "beantester/gui/pages/control.py",
        "old": "            self._pack_bar(before=self.scroll.vsb)",
        "new": "            self._pack_bar()",
        "test": "test_the_control_search_bar_can_be_switched_off_and_back_on",
    },
    {
        # The marks live on the FORM, so hiding the bar without clearing leaves
        # fields highlighted with nothing left to clear them from.
        "label": "gui: hiding the search leaves its marks on the form",
        "file": "beantester/gui/pages/control.py",
        "old": '        self.query_var.set("")\n'
               "        self._apply()               # unmarks, refolds, forgets the query",
        "new": "        pass",
        "test": "test_hiding_the_search_takes_its_marks_and_its_folds_with_it",
    },
    {
        # Focusing a widget that is not on screen swallows whatever the user
        # types next - the shortcut has to decline instead.
        "label": "gui: Ctrl+F still claims a hidden search box",
        "file": "beantester/gui/pages/control.py",
        "old": "        if not self._search_shown:\n            return False",
        "new": "        pass",
        "test": "test_one_ctrl_f_reaches_whichever_search_box_is_in_front",
    },
    {
        # Text written, translated and reviewed, then drawn by nobody: the BOOL
        # row returns before the hint. The field registry has had this guard for
        # a while; the pref registry did not, and lost a paragraph to it.
        "label": "prefs: a checkbox declares a hint its row cannot draw",
        "file": "beantester/gui/prefs.py",
        "old": '         default=False, section="scope"),',
        "new": '         default=False, hint="prefs.scope_view", section="scope"),',
        "test": "test_only_prefs_that_can_show_a_hint_declare_one",
    },
    {
        "label": "core: the Internet-only gate stops cutting the local network",
        "file": "beantester/core.py",
        "old": "        if self.internet_only and is_lan_ip(remote_ip):\n"
               '            return "internet_only"',
        "new": "        pass",
        "test": "test_internet_only_gate",
    },
    {
        # The carve-out the owner asked for. Without it the switch takes down the
        # local development server on the machine running the tool.
        "label": "utils: loopback stops being carved out of the local network",
        "file": "beantester/utils.py",
        "old": "        return not address.is_global and not address.is_loopback",
        "new": "        return not address.is_global",
        "test": "test_is_lan_ip_carves_out_loopback",
    },
    {
        # Without its own row the drop falls through to the unnamed default and
        # is reported as packet LOSS - the exact confusion drop_flap was split
        # out to end.
        "label": "engine: the Internet-only drop loses its own counter",
        "file": "beantester/engine.py",
        "old": '                  "internet_only": "drop_internet_only", "block": "drop_block",',
        "new": '                  "block": "drop_block",',
        "test": "test_every_drop_counter_and_drop_reason_is_classified",
    },
    {
        # Both switches on cuts everything but loopback. Silence there looks like
        # a broken tool rather than a tool doing as it was told.
        "label": "settings: both LAN switches on stops saying so",
        "file": "beantester/settings.py",
        "old": '        log(T("log.lan_and_internet_only"))',
        "new": "        pass",
        "test": "test_both_lan_switches_at_once_are_allowed_and_said_out_loud",
    },
    {
        # The hand-written list falling behind the registry: the command then
        # reproduces a DIFFERENT run, with nothing red to say so. That is how
        # --narrow-filter went missing for weeks.
        "label": "repro: a flag drops out of the reproduction command",
        "file": "beantester/repro.py",
        "old": '    if g("internet_only"):\n        args += ["--internet-only"]',
        "new": "    pass",
        "test": "test_every_setting_with_a_flag_reaches_the_reproduction_command",
    },
    {
        # The harness itself. It claimed pack order for months while answering in
        # creation order, so every ordering question had to go to a live render.
        "label": "harness: the fake stops honouring before= when packing",
        "file": "tests/fake_tk.py",
        "old": "        if before is not None and before in order:\n"
               "            index = order.index(before)",
        "new": "        if False:\n            index = 0",
        "test": "test_the_harness_models_pack_order_so_layout_tests_can_ask_about_it",
    },
    {
        # A checkbox takes a whole row BY KIND, so the pair goes back to a column
        # the moment the registry's override stops being read.
        "label": "gui: the form ignores a field's span override",
        "file": "beantester/gui/form.py",
        "old": "    return field.kind in SPAN_KINDS if field.span is None else field.span",
        "new": "    return field.kind in SPAN_KINDS",
        "test": "test_the_two_lan_switches_share_one_row",
    },
    {
        # How they shipped touching: the checkbox branch packed with no padding
        # while every other kind went through a cell that had some, so the pair
        # only looked wrong once two of them ended up in one row.
        "label": "gui: paired checkboxes lose the gap between them",
        "file": "beantester/gui/form.py",
        "old": '            widget.pack(side="left", anchor="w", padx=(0, _gap_after(field)))',
        "new": '            widget.pack(side="left", anchor="w")',
        "test": "test_the_two_lan_switches_share_one_row",
    },
    {
        # Without the idle hint the row is one cluster in a band of nothing -
        # the shape that has now been reported twice.
        "label": "gui: the search bar loses its idle right-hand anchor",
        "file": "beantester/gui/pages/control.py",
        "old": '        return "" if self.query_var.get().strip() else "Ctrl+F"',
        "new": '        return ""',
        "test": "test_clearing_the_search_puts_every_style_back",
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
    # Not in MUTATIONS because the patch would be the two enormous `log.driver_*`
    # lines pasted twice over, which is a registry entry nobody will ever read. The
    # swap was done for real, both ways, on both files.
    "test_the_language_files_stay_sorted":
        "2026-08-17, swapped two adjacent keys back out of order in both lang "
        "files (byte-level, so LF survived), saw it go red, restored it, saw green",
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
