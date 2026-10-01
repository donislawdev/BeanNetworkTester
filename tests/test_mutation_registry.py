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

* ``MUTATIONS`` - re-runnable today. ``tools/mutate.py`` breaks the named
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
        # "I could not check" printing as a clean bill of health - the same lie the
        # WinDivert row was fixed for, one check further down.
        "label": "doctor: an unchecked program folder reports as a pass",
        "file": "beantester/driver.py",
        "old": '    if is_admin():\n        return ("program folder", "warn",',
        "new": '    if is_admin():\n        return ("program folder", "ok",',
        "test": "test_doctor_says_when_anything_running_as_you_could_replace_the_driver",
    },
    {
        # The hand-rolled quoting, restored exactly as it shipped: an argument
        # ending in a backslash escapes its own closing quote.
        "label": "winenv: relaunch quoting goes back to wrapping each argument",
        "file": "beantester/winenv.py",
        "old": "    import subprocess\n"
               "    return subprocess.list2cmdline([str(a) for a in args])",
        "new": "    return ' '.join('\"%s\"' % str(a).replace('\"', chr(92) + '\"')\n"
               "                    for a in args)",
        "test": "test_the_relaunch_quoting_survives_the_arguments_windows_reparses",
    },
    {
        # Back to str.format, which walks attributes into whatever it was given.
        "label": "i18n: a translation file gets str.format back",
        "file": "beantester/i18n.py",
        "old": "            return _FORMATTER.vformat(text, (), fmt)",
        "new": "            return text.format(**fmt)",
        "test": "test_a_translation_file_cannot_reach_inside_the_values_it_formats",
    },
    {
        # The half that was missing for years: the step's setting NAMES were
        # checked, its VALUES went to the engine untouched.
        "label": "scenario: a step's settings values stop being validated",
        "file": "beantester/scenario.py",
        "old": "            settings = validated_patch(settings)",
        "new": "            settings = dict(settings)",
        "test": "test_a_scenario_value_is_checked_when_the_file_is_opened",
    },
    {
        "label": "scenario: at goes back to float(), which accepts Infinity",
        "file": "beantester/scenario.py",
        "old": '        at = parse_number(step["at"], bounds=(0, None))',
        "new": '        at = float(step["at"])',
        "test": "test_a_scenario_step_cannot_be_scheduled_at_infinity",
    },
    {
        # The timeline dies, the session keeps impairing traffic, nobody is told.
        "label": "scenario: a broken timeline stops telling the engine",
        "file": "beantester/scenario_runner.py",
        "old": "                self.engine.worker_failed(exc)",
        "new": "                pass",
        "test": "test_a_timeline_that_breaks_takes_the_session_down_with_it",
    },
    {
        # Back to saying it first: a held console keeps the session impairing
        # traffic for as long as it is held.
        "label": "scenario: a broken timeline says so before the engine is told",
        "file": "beantester/scenario_runner.py",
        "old": "                self.engine.worker_failed(exc)\n"
               "                log(T(\"log.scenario_failed\", e=f\"{type(exc).__name__}: {exc}\"))",
        "new": "                log(T(\"log.scenario_failed\", e=f\"{type(exc).__name__}: {exc}\"))\n"
               "                self.engine.worker_failed(exc)",
        "test": "test_a_broken_timeline_stops_the_session_before_it_says_so",
    },
    {
        # The shipped stop(): a flag and a return. The thread is still between two
        # steps and applies one more set of settings after the caller moved on.
        "label": "scenario: stop() goes back to setting a flag and returning",
        "file": "beantester/scenario_runner.py",
        "old": "        thread = self._thread\n"
               "        if (thread is not None and thread.is_alive()\n"
               "                and thread is not threading.current_thread()):\n"
               "            thread.join(timeout=timeout)",
        "new": "        return",
        "test": "test_stop_returns_with_the_thread_already_gone",
    },
    {
        # Joining the calling thread raises - and raises INSIDE the net that
        # handles the timeline's own failure, because worker_failed comes back here
        # on the runner thread.
        "label": "scenario: stop() joins whichever thread called it",
        "file": "beantester/scenario_runner.py",
        "old": "                and thread is not threading.current_thread()):",
        "new": "                and True):",
        "test": "test_stopping_from_inside_the_runner_thread_does_not_raise",
    },
    {
        # start() back to clearing the stop flag over a thread it never stopped:
        # the orphan keeps applying its own timeline to the same engine.
        "label": "scenario: start() abandons the thread it already owns",
        "file": "beantester/scenario_runner.py",
        "old": "        self.stop()\n        self._wake.clear()",
        "new": "        self._wake.clear()",
        "test": "test_starting_again_leaves_no_orphan_applying_the_old_timeline",
    },
    {
        # The exact shape that walked past all four JSON loaders: RecursionError is
        # neither OSError nor ValueError, so re-raising it is the bug restored.
        "label": "jsonfile: deep nesting escapes the reader again",
        "file": "beantester/jsonfile.py",
        "old": '            raise ValueError("nesting is too deep to read") from exc',
        "new": "            raise",
        "test": "test_no_loader_can_be_taken_down_by_a_hostile_file",
    },
    {
        # `parse_constant` back to the permissive default: float("NaN") and
        # float("Infinity") are exactly what json would have produced on its own.
        "label": "jsonfile: the NaN and Infinity literals are accepted again",
        "file": "beantester/jsonfile.py",
        "old": '    raise ValueError(f"{name} is not a value a JSON file may carry")',
        "new": "    return float(name)",
        "test": "test_no_loader_can_be_taken_down_by_a_hostile_file",
    },
    {
        "label": "jsonfile: the size limit stops being checked",
        "file": "beantester/jsonfile.py",
        "old": "    size = os.path.getsize(path)                     "
               "# OSError if it is not there",
        "new": "    size = 0",
        "test": "test_no_loader_can_be_taken_down_by_a_hostile_file",
    },
    {
        # The name that shipped: derived from the target, so two writers of one
        # file are two writers of one temp file. This is not an invented break.
        "label": "jsonfile: the temp file gets a predictable name again",
        "file": "beantester/jsonfile.py",
        "old": "        tmp = temp_beside(path)",
        "new": '        tmp = f"{path}.tmp"',
        "test": "test_two_writers_do_not_share_one_temp_file",
    },
    {
        # TypeError back out of the tuple: a value json has no rule for escapes
        # the writer again, past its own temp-file cleanup.
        "label": "jsonfile: a value json cannot write escapes the writer",
        "file": "beantester/jsonfile.py",
        "old": "    except (OSError, TypeError, ValueError) as e:",
        "new": "    except (OSError, ValueError) as e:",
        "test": "test_a_value_json_cannot_write_is_an_error_not_a_crash",
    },
    {
        "label": "paths: two copies migrate through one temp file again",
        "file": "beantester/paths.py",
        "old": "            tmp = temp_beside(dst)",
        "new": '            tmp = dst + ".tmp"',
        "test": "test_two_copies_migrating_at_once_do_not_share_one_temp_file",
    },
    {
        # The 2026-08-26 report in one line. "The screen" is SM_CXSCREEN on
        # Windows, which is the PRIMARY monitor whatever the window is on, so this
        # patch is not an invented break: it is the code that shipped.
        "label": "gui: the tooltip bubble is clamped to the primary monitor again",
        "file": "beantester/gui/tooltip.py",
        "old": "                                  _bounds_for(widget, x_root, y_root))",
        "new": "                                  (0, 0, widget.winfo_screenwidth() or 1920,\n"
               "                                   widget.winfo_screenheight() or 1080))",
        "test": "test_the_bubble_opens_on_the_monitor_the_widget_is_on",
    },
    {
        # The caller half of the same fix: `geometry_fits` grew an argument, and
        # the quiet way to lose the fix is to stop passing it - the default is the
        # old primary-screen answer, so nothing looks broken.
        "label": "gui: the main window validates its geometry against the primary screen",
        "file": "beantester/gui/app.py",
        "old": "        if saved and geometry_fits(saved, screen_w, screen_h,"
               " winenv.monitor_work_area):",
        "new": "        if saved and geometry_fits(saved, screen_w, screen_h):",
        "test": "test_the_main_window_goes_back_to_the_second_monitor_it_was_left_on",
    },
    {
        "label": "gui: a panel centres on the primary monitor, not on the app's",
        "file": "beantester/gui/windows.py",
        "old": "            x, y = centred_in(self._app_monitor(screen_w, screen_h), width, height)",
        "new": "            x, y = centred_in((0, 0, screen_w, screen_h), width, height)",
        "test": "test_a_window_opens_on_the_monitor_the_application_is_on",
    },
    {
        "label": "gui: a panel forgets a position that is not on the primary screen",
        "file": "beantester/gui/windows.py",
        "old": "        if saved and screen_w and geometry_fits(saved, screen_w, screen_h,\n"
               "                                                winenv.monitor_work_area):",
        "new": "        if saved and screen_w and geometry_fits(saved, screen_w, screen_h):",
        "test": "test_a_window_opens_on_the_monitor_the_application_is_on",
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
        # The line moved into driver.format_doctor (2026-09-23), which --doctor and
        # the Tools tab's report both print through; the CLI test still reads it.
        "label": "doctor: stops printing where the user's files are",
        "file": "beantester/driver.py",
        "old": '    lines.append(f"user files: {data_dir}")\n',
        "new": "",
        "test": "test_doctor_says_where_the_users_own_files_are",
    },
    {
        # Back onto the UI thread: a full filter and sort with no row cap, then a
        # row-by-row CSV write, on a table that may hold 200 000 flows.
        "label": "gui: the connection export is run inline instead of started",
        "file": "beantester/gui/csv_export.py",
        "old": "    worker.start()\n    return worker",
        "new": "    worker.run()\n    return worker",
        "test": "test_the_connection_export_does_not_run_on_the_ui_thread",
    },
    {
        # One fixed path, two workers: whichever finishes last publishes, and the
        # other one's file is gone. Easier to hit now that the window stays
        # responsive during the write.
        "label": "gui: two clicks can start two exports onto the same file",
        "file": "beantester/gui/csv_export.py",
        "old": ("    if not _EXPORT_LOCK.acquire(blocking=False):\n"
                "        # Two clicks, one file. Refusing out loud beats two workers"
                " racing to\n"
                "        # `os.replace` the same path, where the winner is whichever"
                " finishes last.\n"
                '        app.log(T("log.conns_export_busy"))\n'
                "        return None\n"),
        "new": "    _EXPORT_LOCK.acquire(blocking=False)\n",
        "test": "test_a_second_export_is_refused_while_the_first_is_still_writing",
    },
    {
        # The split that lets one filtering pass answer both the sorted view and
        # the footer's total. A half that stops filtering makes them disagree.
        "label": "views: the filtering half of the split stops filtering",
        "file": "beantester/views.py",
        "old": "    return _filter_connections(conns, query, proc_map)\n\n\ndef sum_traffic",
        "new": "    return list(conns)\n\n\ndef sum_traffic",
        "test": "test_the_split_halves_agree_with_the_pair_they_replace",
    },
    {
        # `_pending` is cleared here or by poll() reading a result, so a build that
        # ends any other way wedges the table for the rest of the session.
        "label": "gui: a model build that fails oddly wedges the table for good",
        "file": "beantester/gui/model_worker.py",
        "old": "        except BaseException as exc:",
        "new": "        except Exception as exc:",
        "test": "test_a_build_that_fails_outside_Exception_does_not_wedge_the_table",
    },
    {
        # Back to a rebuild that destroys every widget without telling the pages,
        # leaving their after() timers armed against commands Tk has deleted.
        "label": "gui: a language switch stops telling the pages to put their timers away",
        "file": "beantester/gui/app.py",
        "old": "        if getattr(self, \"pages\", None):\n            teardown_pages(self)\n",
        "new": "",
        "test": "test_a_language_switch_cancels_what_the_pages_had_scheduled",
    },
    {
        # The guard that reads as thorough and is not: a DESTROYED Tk widget is not
        # None, so `box is None` passes and every call after it raises TclError.
        "label": "gui: the log box guard trusts the attribute instead of the widget",
        "file": "beantester/gui/logview.py",
        "old": "        try:\n            return bool(box.winfo_exists())",
        "new": "        try:\n            return True",
        "test": "test_logging_into_a_destroyed_box_is_not_an_error",
    },
    {
        # `crashlog.record` deduplicates and counts. The dialog deduplicated
        # nothing, so a binding firing in a series stacked modal windows.
        "label": "gui: every occurrence of one fault opens its own modal window again",
        "file": "beantester/gui/app.py",
        "old": "        if key in self._ui_errors_shown:\n            return\n",
        "new": "",
        "test": "test_one_window_per_fault_not_one_per_occurrence",
    },
    {
        # The shipped P0: every tick pushed the RAW target field to the engine, so
        # an emptied or half-typed field switched targeting off without Apply.
        "label": "gui: the tick pushes the target field to the engine again",
        "file": "beantester/gui/app.py",
        "old": "                self._refresh_target_verdict()\n            else:",
        "new": "                self._refresh_target_verdict()\n"
               "                __import__(\"beantester.settings\", fromlist=[\"x\"])"
               ".apply_targeting(self.engine, "
               "str(self.vars[\"target\"].get()).strip(), announce=False)\n"
               "            else:",
        "test": "test_a_row_action_fills_the_form_and_does_not_reach_a_running_engine",
    },
    {
        # Back to the banner that said the opposite of the truth: a target that
        # could not be used leaves EVERY connection impaired, not none.
        "label": "gui: an unusable target is reported as impairing nothing",
        "file": "beantester/gui/app.py",
        "old": 'T("fields.target_all_traffic") if self._applied_target else "")',
        "new": 'T("fields.target_no_match") if self._applied_target else "")',
        "test": "test_a_target_that_cannot_be_used_says_everything_is_impaired",
    },
    {
        "label": "gui: START forgets which target it applied",
        "file": "beantester/gui/app.py",
        "old": "        self._applied_target = str(s.get(\"target\", \"\")).strip()\n"
               "        self._sync_running_ui()",
        "new": "        self._applied_target = \"\"\n"
               "        self._sync_running_ui()",
        "test": "test_a_target_that_cannot_be_used_says_everything_is_impaired",
    },
    {
        "label": "gui: Apply changes forgets which target it applied",
        "file": "beantester/gui/app.py",
        "old": "        session_repro.apply(self, s)\n"
               "        self._applied_target = str(s.get(\"target\", \"\")).strip()",
        "new": "        session_repro.apply(self, s)",
        "test": "test_a_target_that_cannot_be_used_says_everything_is_impaired",
    },
    {
        # "Every connection is being impaired" must not outlive the session.
        "label": "gui: the target banner stays up after STOP",
        "file": "beantester/gui/app.py",
        "old": "                self._pending_target_warning = \"\"   "
               "# nothing is impaired when stopped",
        "new": "                pass",
        "test": "test_a_target_that_cannot_be_used_says_everything_is_impaired",
    },
    {
        # The exact shape before 2026-09-02: the put outside the try, and a catch
        # narrow enough for anything else to escape past it - which leaves
        # `_transition` set forever and START/STOP dead for the life of the window.
        "label": "gui: a transition worker can end without ever feeding the queue",
        "file": "beantester/gui/app.py",
        "old": ("            err = None\n"
                "            try:\n"
                "                work()\n"
                "            except BaseException as e:  # carried to the main thread,"
                " never swallowed\n"
                "                err = e\n"
                "            finally:\n"
                "                self._ui_queue.put((kind, err))"),
        "new": ("            try:\n"
                "                work()\n"
                "                err = None\n"
                "            except Exception as e:\n"
                "                err = e\n"
                "            self._ui_queue.put((kind, err))"),
        "test": "test_a_start_that_fails_outside_Exception_still_gives_the_button_back",
    },
    {
        # Back to the watchdog as it stood before 2026-09-02, which asked
        # `is_alive()` and nothing else - so a thread spinning in a regular
        # expression or blocked on a driver that stopped answering was healthy.
        "label": "engine: the watchdog stops noticing a capture thread that stalled",
        "file": "beantester/engine.py",
        "old": "            if self._capture_has_stalled():",
        "new": "            if False:",
        "test": "test_a_capture_thread_that_is_alive_but_no_longer_moving_fails_open",
    },
    {
        # The shipped order before 2026-09-28: say it, then stop. A console held by
        # a text selection kept the session running past its --duration.
        "label": "engine: the deadline is said before the session is stopped",
        "file": "beantester/engine.py",
        "old": "                self._worker_stop(\n"
               "                    \"duration\", (T(\"log.duration_reached\", "
               "v=f\"{self._duration:g}\"),), session)",
        "new": "                self.log(T(\"log.duration_reached\", v=f\"{self._duration:g}\"))\n"
               "                self._worker_stop(\"duration\", session=session)",
        "test": "test_a_stop_closes_the_divert_while_the_log_is_still_blocked",
    },
    {
        # The fault line said by the worker before it asks for the stop: every
        # watchdog fault and the foreign-worker door hold the divert open again.
        "label": "engine: a fault is said before the session is stopped",
        "file": "beantester/engine.py",
        "old": "        say = (*lead, T(\"log.engine_fault\", e=str(error)))",
        "new": "        self._say((*lead, T(\"log.engine_fault\", e=str(error))))\n"
               "        say = ()",
        "test": "test_a_stop_closes_the_divert_while_the_log_is_still_blocked",
    },
    {
        # The stop itself says why before it closes - the callers hand the lines
        # over correctly and it still waits for the log.
        "label": "engine: a stop says why before it closes the divert",
        "file": "beantester/engine.py",
        "old": "        if self._divert is not None:\n"
               "            try:\n"
               "                self._divert.close()",
        "new": "        self._say(say)\n"
               "        say = ()\n"
               "        if self._divert is not None:\n"
               "            try:\n"
               "                self._divert.close()",
        "test": "test_a_stop_closes_the_divert_while_the_log_is_still_blocked",
    },
    {
        # The first version of this fix: said at the divert close, before the rest
        # of the teardown - a held log kept the timer request, the switch interval
        # and the atexit entry until it moved.
        "label": "engine: a stop says why before the rest of its teardown",
        "file": "beantester/engine.py",
        "old": "        self.log_event(\"STOP\", self.EVENT_BY_REASON.get(reason, "
               "\"events.stopped\"))",
        "new": "        self._say(say)\n"
               "        say = ()\n"
               "        self.log_event(\"STOP\", self.EVENT_BY_REASON.get(reason, "
               "\"events.stopped\"))",
        "test": "test_a_stop_closes_the_divert_while_the_log_is_still_blocked",
    },
    {
        # START's failure handler said its fault first, then stopped.
        "label": "engine: a failed start says its fault before stopping",
        "file": "beantester/engine.py",
        "old": "            self._stop_locked(\"fault\", say=(T(\"log.engine_fault\", e=str(exc)),))",
        "new": "            self.log(T(\"log.engine_fault\", e=str(exc)))\n"
               "            self._stop_locked(\"fault\")",
        "test": "test_a_stop_closes_the_divert_while_the_log_is_still_blocked",
    },
    {
        # The capture thread said the recv error itself before asking for the stop.
        "label": "engine: a recv error is said before the stop",
        "file": "beantester/engine.py",
        "old": "                    self._fail_stop(e, lead=(f\"{T('log.recv_error')}: {e}\",), "
               "session=session)",
        "new": "                    self.log(f\"{T('log.recv_error')}: {e}\")\n"
               "                    self._fail_stop(e, session=session)",
        "test": "test_a_stop_closes_the_divert_while_the_log_is_still_blocked",
    },
    {
        # The sink's exception reaches the watchdog again: it dies on the deadline
        # line and the session never stops.
        "label": "engine: a log that raises escapes into the caller again",
        "file": "beantester/engine.py",
        "old": "        try:\n"
               "            self._log_fn(msg)\n"
               "        except Exception as _exc:\n"
               "            crashlog.note(_exc, \"engine.log\")",
        "new": "        self._log_fn(msg)",
        "test": "test_a_log_that_raises_cannot_cancel_a_stop",
    },
    {
        # The other direction, and the more expensive one to get wrong: without the
        # phase, a thread parked in recv() on a link with no traffic looks exactly
        # like a stalled one, and the watchdog would kill a healthy session.
        "label": "engine: the stall check forgets which side of recv the thread is on",
        "file": "beantester/engine.py",
        "old": "        if self._cap_beat_at is None or self._cap_waiting:",
        "new": "        if self._cap_beat_at is None:",
        "test": "test_a_quiet_link_is_never_mistaken_for_a_stalled_capture_thread",
    },
    {
        # Back to the state before 2026-09-02: `re.compile` succeeding was the
        # whole check, so a pattern that parses but never finishes went straight
        # onto the capture thread.
        "label": "matchers: a pattern that cannot finish is no longer refused",
        "file": "beantester/matchers.py",
        "old": "    if _blows_the_budget(rx) and _blows_the_budget(rx):",
        "new": "    if False:",
        "test": "test_a_pattern_that_cannot_finish_is_refused_at_parse_time",
    },
    {
        # The other way to make the guard useless without touching its call: stop
        # the ladder before it reaches a length where backtracking shows. The
        # budget cannot be loosened instead - a mutant with no ceiling would run
        # the explosive pattern at 45 characters and hang the suite rather than
        # fail it.
        "label": "matchers: the probe ladder stops before backtracking shows",
        "file": "beantester/matchers.py",
        "old": "_REGEX_PROBE_LENGTHS = (6, 8, 10, 12, 14, 16, 20, 24, 32, 45)",
        "new": "_REGEX_PROBE_LENGTHS = (6,)",
        "test": ("test_a_pattern_that_cannot_finish_leaves_the_table_search"
                 "_answering_normally"),
    },
    {
        # Back to a ladder of bare runs, which the pattern matches: every repeat
        # inside a repeat that fails only at its end walks through again.
        "label": "matchers: the probe forgets the character after the run",
        "file": "beantester/matchers.py",
        "old": "_REGEX_PROBE_TAILS = (\"\", \"!\")",
        "new": "_REGEX_PROBE_TAILS = (\"\",)",
        "test": "test_a_pattern_that_fails_only_at_its_end_is_refused_too",
    },
    {
        # OverflowError and RecursionError escape `parse_matcher` again.
        "label": "matchers: only re.error becomes a ValueError again",
        "file": "beantester/matchers.py",
        "old": "    except (re.error, OverflowError, RecursionError) as exc:",
        "new": "    except re.error as exc:",
        "test": "test_a_pattern_the_parser_cannot_build_is_a_value_error_on_every_kind",
    },
    {
        # Every compile judges again: the form's "yes" and Apply's answer can differ.
        "label": "matchers: an accepted pattern is judged again at every compile",
        "file": "beantester/matchers.py",
        "old": "@functools.lru_cache(maxsize=256)\ndef _accepted_regex(pattern):",
        "new": "def _accepted_regex(pattern):",
        "test": "test_an_accepted_pattern_is_not_judged_again",
    },
    {
        # The shipped tolerance: a destination that could not be read is switched
        # OFF, which impairs everything.
        "label": "settings: a bad destination at apply switches it off again",
        "file": "beantester/settings.py",
        "old": "            log(f\"{T('log.filter_skipped')}: {e}\")\n"
               "            dest = None",
        "new": "            log(f\"{T('log.filter_skipped')}: {e}\")\n"
               "            dest = (False, *compile_endpoint(None, None))",
        "test": "test_a_bad_destination_at_apply_leaves_the_previous_one_in_place",
    },
    {
        "label": "settings: a bad block at apply switches blocking off again",
        "file": "beantester/settings.py",
        "old": "        if block is not None:\n"
               "            engine.set_block(*block)",
        "new": "        engine.set_block(*(block or (False, *compile_endpoint(None, None),"
               " False)))",
        "test": "test_a_bad_block_at_apply_leaves_the_previous_one_in_place",
    },
    {
        # Targeting switched off by an expression that could not be read: every
        # connection in the filter impaired.
        "label": "settings: a bad target at apply switches targeting off again",
        "file": "beantester/settings.py",
        "old": "            return engine.targeting()",
        "new": "            engine.set_target(False)\n"
               "            return None",
        "test": "test_apply_targeting_logs_and_keeps_the_target_on_a_bad_expression",
    },
    {
        # Back to the check as it stood before 2026-09-02, which is the exact
        # shape that let NaN through: `float('nan') <= 0` is False.
        "label": "cli: the report interval is only checked for being above zero",
        "file": "beantester/cli.py",
        "old": "if not (0 < interval <= MAX_INTERVAL_S):",
        "new": "if interval <= 0:",
        "test": ("test_the_report_interval_is_refused_while_it_is_still_a_number"
                 "_on_a_command_line"),
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
        # The same knob on the complexity axis, which had no crowd count at all
        # until 2026-08-21: `max-complexity` watches the single most branching
        # function and cannot see the runners-up climbing together underneath it.
        "label": "ratchet: the complexity crowd count is frozen looser than the measurement",
        "file": "tests/test_code_shape.py",
        # Re-anchored 2026-08-31 (3 -> 5) and again 2026-09-06 (5 -> 4, when
        # `_run_session` was split into three phases and left the band). The
        # mutation still proves the same thing - a count frozen looser than
        # today's measurement is caught by the equality half of that test, not by
        # the "at most" half. Re-anchoring is the routine cost of a pattern that
        # pins exact source text; a stale one reports SKIP, which reads like a
        # result and is not one.
        "old": "COMPLEX_NEAR_CEILING = 4    # decide, settings_summary, _capture_loop,",
        "new": "COMPLEX_NEAR_CEILING = 7    # decide, settings_summary, _capture_loop,",
        "test": "test_nothing_else_is_creeping_up_on_the_complexity_ceiling",
    },
    {
        # A rule deleted from `select` to turn a red build green is a check that
        # vanished - and a check that has vanished cannot fail to announce itself.
        "label": "ruff: a selected rule quietly leaves the configuration",
        "file": "pyproject.toml",
        "old": 'select = ["F", "B", "S", "ASYNC", "C90", "PLR0913"]',
        "new": 'select = ["F", "B", "S", "ASYNC", "C90"]',
        "test": "test_the_selected_rules_only_ever_grow",
    },
    {
        # The notice exists because a cron is easy to miss. Pointed at pull
        # requests it becomes an issue factory instead - one per pull request -
        # and the fastest way to teach everyone that these issues are noise.
        "label": "cron notice: the weekly notice starts firing on pull requests",
        "file": ".github/workflows/ci.yml",
        "old": "      && (github.event_name == 'schedule' || github.event_name == 'workflow_dispatch')",
        "new": "      && (github.event_name == 'schedule' || github.event_name == 'pull_request')",
        "test": "test_the_cron_notice_watches_every_job_in_the_workflow",
    },
    {
        # A job outside `needs` fails every Monday in silence - the same defect
        # the notice itself exists to cure, one level up.
        "label": "cron notice: a job drops out of what the weekly notice watches",
        "file": ".github/workflows/ci.yml",
        "old": "    needs: [public-text, lint, types, semgrep, audit, mutations, tests, build]",
        "new": "    needs: [public-text, lint, types, semgrep, audit, mutations, tests]",
        "test": "test_the_cron_notice_watches_every_job_in_the_workflow",
    },
    {
        # A tag can be cut days before the next cron, so the pinned set has to be
        # asked about when it CHANGES, not only when the calendar turns.
        "label": "audit: the pinned set stops being checked when a pull request moves it",
        "file": ".github/workflows/ci.yml",
        "old": "      || github.event_name == 'pull_request'",
        "new": "      || false",
        "test": "test_the_audit_job_answers_to_a_pull_request_that_moves_the_pins",
    },
    {
        # File mode covers 7 of the 9 packages and silently skips `packaging` and
        # `setuptools` - measured 2026-08-11. A release audited that way reads
        # clean for a reason that has nothing to do with being clean.
        "label": "release: the pre-release audit reads the requirement files instead of the install",
        "file": ".github/workflows/release.yml",
        "old": "          pip-audit --path audit-env/Lib/site-packages -f json -o release-audit.json",
        "new": "          pip-audit -r requirements.txt -f json -o release-audit.json",
        "test": "test_the_release_audits_its_pins_before_it_builds",
    },
    {
        # The gap the pairing exists for: `--select` on the command line REPLACES
        # the list in pyproject.toml, so a rule can stay configured, stay visible
        # to `ruff check` on a developer machine, and stop blocking anything.
        "label": "ci: a blocking ruff rule drops out of the workflow command",
        "file": ".github/workflows/ci.yml",
        "old": "        run: ruff check --select F,B,C90,PLR0913 --output-format github",
        "new": "        run: ruff check --select F,B,C90 --output-format github",
        "test": "test_every_blocking_rule_is_named_in_the_workflow_that_blocks",
    },
    {
        # A ceiling standing above the truth grants headroom nobody decided to
        # grant - the same defect the file and function ceilings are guarded for.
        "label": "ratchet: the argument ceiling is raised above the widest signature",
        "file": "pyproject.toml",
        "old": "max-args = 14",
        "new": "max-args = 20",
        "test": "test_the_argument_ceiling_is_the_measurement_not_a_number_above_it",
    },
    {
        # The third axis, added the same day. Aimed at the COUNT rather than at
        # `_nesting_depth` itself for the reason written next to the depth metric
        # tests in PROVEN_BY_HAND: any patch to the metric reddens three tests at
        # once, and an entry that fells a crowd proves nothing about any one of them.
        "label": "ratchet: the nesting crowd count is frozen looser than the measurement",
        "file": "tests/test_code_shape.py",
        "old": "DEPTHS_NEAR_CEILING = 8         # make_gear_icon at 5, seven more at 4",
        "new": "DEPTHS_NEAR_CEILING = 20        # make_gear_icon at 5, eleven more at 4",
        "test": "test_the_depth_ceiling_and_its_count_are_not_set_so_loosely_they_never_fire",
    },
    {
        # The step the notes' "how to add an impairment" recipe does not mention:
        # a new core setter needs a forwarder, and forgetting one used to surface
        # much later as an AttributeError out of apply_settings, in whatever ran
        # first. Aimed at the ADDITION rather than at a deleted forwarder, because
        # that is the direction a session actually takes.
        "label": "engine: a new core setter arrives without its forwarder",
        "file": "beantester/core.py",
        "old": "    def set_nat(self, timeout_s):",
        "new": "    def set_brand_new_thing(self, x):\n"
               "        return x\n\n"
               "    def set_nat(self, timeout_s):",
        "test": "test_every_core_setter_has_a_forwarder_that_matches_it",
    },
    {
        # The other half, and the one no other check in the repository can reach:
        # a loop built entirely out of lazy imports. It runs, it passes every
        # direction check, and it becomes an ImportError the day somebody hoists
        # the import to the top of the file for tidiness. `cli` imports `views`,
        # so one deferred import pointing back closes the ring.
        "label": "layering: a new lazy import cycle appears with no reason declared",
        "file": "beantester/views.py",
        "old": "def filter_sort_connections(",
        "new": "def _probe():\n"
               "    from . import cli\n"
               "    return cli\n\n\n"
               "def filter_sort_connections(",
        "test": "test_every_lazy_import_cycle_is_one_this_file_knows_about",
    },
    {
        # The loop the four DIRECTION checks in that file cannot see. `utils` is
        # the bottom layer and `core` imports it, so one line pointing back is a
        # genuine cycle and reaches nothing else: no other test in the repository
        # asserts anything about what utils.py imports.
        "label": "layering: an import cycle appears at module load",
        "file": "beantester/utils.py",
        "old": "import math\n",
        "new": "import math\n\nfrom . import core\n",
        "test": "test_the_package_has_no_import_cycle_at_module_load",
    },
    {
        # The FOURTH axis, added 2026-09-06. Aimed at the class GROWING rather
        # than at a loosened constant, because that is the direction this axis
        # exists for: three carves out of `app.py` moved the file ratchet every
        # time and left `App` at the same 96 methods, so the object a reader has
        # to hold in their head was never once measured.
        "label": "ratchet: a class quietly grows another method",
        "file": "beantester/gui/app.py",
        "old": "    def _reveal(self):\n",
        "new": "    def _ratchet_probe(self):\n"
               "        return None\n\n"
               "    def _reveal(self):\n",
        "test": "test_no_class_has_grown_past_the_ratchet",
    },
    {
        # The same axis from the other side: a ceiling parked above the truth.
        # Kept separate from the entry above because they fail for different
        # reasons, and an entry that reddens both proves neither.
        "label": "ratchet: the class attribute ceiling is raised above the truth",
        "file": "tests/test_code_shape.py",
        "old": "CLASS_ATTR_CEILING = 77         # gui/app.py::App",
        "new": "CLASS_ATTR_CEILING = 86         # gui/app.py::App",
        "test": "test_the_class_numbers_are_the_measurement_not_a_number_above_them",
    },
    {
        # The bucket is a virtual FINISH TIME, not a token count, so a link that
        # has been quiet leaves it in the past. Charging from a stale one banks
        # the idleness as burst credit: the shaper adds no delay until the bucket
        # catches up, and `queued` goes negative so the bounded buffer cannot
        # tail-drop either. Found UNGUARDED on 2026-09-06 - deleting this clamp
        # survived all 1405 tests - while giving the token bucket its own
        # function, and the test was written from this mutation rather than from
        # the code.
        "label": "rate: an idle shaped link banks its silence as burst credit",
        "file": "beantester/core.py",
        "old": "        b = self._bucket[is_outbound]\n        if b < now:\n            b = now\n",
        "new": "        b = self._bucket[is_outbound]\n",
        "test": "test_an_idle_shaped_link_does_not_bank_burst_credit",
    },
    {
        # The other half of what the shared helper now owns: the duplicate is a
        # second copy on the wire and has to be charged for, or a shaped link
        # quietly carries (1 + dup%) of its limit. This one WAS guarded before the
        # extraction and the entry records that it still is afterwards.
        "label": "rate: a duplicate rides the shaped link for free",
        "file": "beantester/core.py",
        "old": "                if rate <= 0 or self._charge(is_outbound, size, now, rate) is not None:",
        "new": "                if True:",
        "test": "test_a_duplicate_is_charged_to_the_speed_limit",
    },
    {
        # The suite's own axes, added 2026-09-06. Aimed at a test GROWING, which
        # is the direction they exist for: 23 359 logic lines of tests guarded the
        # package while nothing measured their shape, and one test at a hundred
        # lines is not "more tests" - it is one test nobody can follow, which will
        # not say what broke when it fails. The ceiling is pinned to this exact
        # function, so one statement is enough to cross it.
        "label": "ratchet: a test function grows past the suite ceiling",
        "file": "tests/test_concurrency_chaos.py",
        "old": "def test_the_model_worker_survives_a_live_connection_table():",
        "new": "def test_the_model_worker_survives_a_live_connection_table():\n"
               "    _ratchet_probe = 1",
        "test": "test_no_test_function_has_grown_past_the_ratchet",
    },
    {
        # The rule itself: a definition nothing names must be caught.
        #
        # 🔴 RE-AIMED 2026-09-06, after this entry SURVIVED on CI. It used to drop
        # `tests` from `USAGE_TREES`, on the reasoning that half the package is
        # only ever named from the suite, so a scan that stops reading tests/
        # would call a live helper dead. That reasoning stopped being true on
        # 2026-09-02, when a mention from the test tree stopped counting as LIFE
        # (backlog B-16): the twelve definitions that would go dead are now all in
        # KNOWN_UNUSED already, so removing the tree changes the `unexpected` list
        # from empty to empty.
        #
        # MEASURED while re-aiming, and it is worth writing down because it is
        # larger than this one entry: dropping ANY of the five trees - `tests`,
        # `tools`, `lang` or `scenarios` - leaves the guard green. `USAGE_TREES`
        # is a knob no mutation can reach any more, and its real job (an allow
        # list, so that a tree existing only on the maintainer's machine cannot
        # make a name look alive locally and dead on CI) is a property about
        # ABSENT directories, which nothing present can demonstrate. Aiming at the
        # rule is honest; aiming at a knob that no longer moves the answer is the
        # SKIP-shaped non-result this registry exists to avoid.
        #
        # Verified by hand before being written down: an unreferenced helper added
        # to `summary.py` reddens this test by name.
        "label": "dead code: a definition nothing names is left in the package",
        "file": "beantester/summary.py",
        "old": "def settings_summary(",
        "new": "def _orphan_helper(value):\n"
               "    return value\n\n\n"
               "def settings_summary(",
        "test": "test_no_definition_in_the_package_is_unreferenced",
    },
    {
        # The quiet direction, and the reason the exception list is a ratchet
        # rather than a note: a scan blinded here finds NOTHING and reads exactly
        # like a clean package. What catches it is the list of names that are
        # supposed to still be unreferenced - they stop being reported, and the
        # second test says so.
        "label": "dead code: the scan stops recognising an unreferenced definition",
        "file": "tests/test_code_hygiene.py",
        "old": "            if not living:\n                dead.add(key)",
        "new": "            if False:\n                dead.add(key)",
        "test": "test_the_known_unused_list_only_ever_shrinks",
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
        # P3-17: without the group of real socket owners, `*.exe` - every program
        # but System - passes as a narrow target again.
        "label": "blast radius: no probe stands for the programs that own sockets",
        "file": "beantester/matchers.py",
        "old": ('                     (2, "svchost.exe"), (65000, "a")),\n'
                '                    ((1234, "chrome.exe"), (2, "svchost.exe"), (65000, "a.exe")))\n'),
        "new": '                     (2, "svchost.exe"), (65000, "a")),)\n',
        "test": "test_a_target_that_names_every_exe_is_not_a_bound",
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
        "old": "    scen = _read_scenario(cfg[\"scenario\"], log) if cfg[\"scenario\"] else None",
        "new": "    scen = None",
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
        "old": "                                   field=key, value=repr(value),\n"
               "                                   expected=_expected_shape(key)))",
        "new": "                                   field=key, value=repr(value),\n"
               "                                   expected=\"\"))",
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
        # A title bound counted in characters lets a Chinese title through at twice the
        # width a result shows, and cuts a Thai one that is perfectly short.
        "label": "site: a wide character is counted as one column again",
        "file": "tools/build_site.py",
        "old": '        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1',
        "new": "        width += 1",
        "test": "test_the_width_of_a_text_counts_columns_not_characters",
    },
    {
        "label": "site: a combining mark is counted as a column again",
        "file": "tools/build_site.py",
        "old": '        if unicodedata.category(ch) in ("Mn", "Me", "Cf"):\n            continue\n',
        "new": "        if False:\n            continue\n",
        "test": "test_the_width_of_a_text_counts_columns_not_characters",
    },
    {
        # The pages would quote words the reader's window does not contain, in a
        # language the program has no file for yet.
        "label": "site: a language the program lacks quotes its own missing words",
        "file": "tools/build_site.py",
        "old": '    default = registry["default_language"]\n'
               '    return _language(registry, default).get("app_language") or default',
        "new": "    return code",
        "test": "test_the_pages_quote_the_program_in_the_language_the_program_would_show",
    },
    {
        "label": "site: a declared program file that is missing is quietly replaced",
        "file": "tools/build_site.py",
        "old": "        if not os.path.isfile(_program_file(root, declared)):\n"
               "            raise SiteError(",
        "new": "        if False:\n            raise SiteError(",
        "test": "test_the_pages_quote_the_program_in_the_language_the_program_would_show",
    },
    {
        # The page said seven for as long as nobody counted.
        "label": "site: the scenario count on the page is typed in again",
        "file": "tools/build_site.py",
        "old": '        "page.scenario_count": len(scenario_files(root)),',
        "new": '        "page.scenario_count": 7,',
        "test": "test_the_scenario_count_is_the_number_of_files_that_ship",
    },
    {
        "label": "site: the scenario count in a description is typed in again",
        "file": "tools/build_site.py",
        "old": "                description = description.replace(SCENARIO_COUNT_TOKEN,\n"
               "                                                  str(len(scenario_files(root))))",
        "new": '                description = description.replace(SCENARIO_COUNT_TOKEN, "7")',
        "test": "test_the_scenario_count_is_the_number_of_files_that_ship",
    },
    {
        # Arabic rendered left to right reads as noise with full stops in the wrong place.
        "label": "site: every page is written left to right",
        "file": "tools/build_site.py",
        "old": '        "page.direction": _language(registry, code).get("direction", "ltr"),',
        "new": '        "page.direction": "ltr",',
        "test": "test_a_language_says_which_way_it_is_written",
    },
    {
        "label": "site: a direction that is neither ltr nor rtl is accepted",
        "file": "tools/build_site.py",
        "old": '        if lang.get("direction", "ltr") not in ("ltr", "rtl"):',
        "new": "        if False:",
        "test": "test_a_language_says_which_way_it_is_written",
    },
    {
        "label": "site: the language menu stops being a menu",
        "file": "tools/build_site.py",
        "old": """    return Raw('<details class="langmenu"><summary>%s: <span lang="%s">%s</span></summary>'""",
        "new": """    return Raw('<div class="langmenu"><summary>%s: <span lang="%s">%s</span></summary>'""",
        "test": "test_the_language_menu_holds_every_language_and_marks_the_current_one",
    },
    {
        "label": "site: the error page offers no language to a reader who is lost",
        "file": "tools/build_site.py",
        "old": "        if code == skip:\n            continue\n        dir_path = home",
        "new": "        if True:\n            continue\n        dir_path = home",
        "test": "test_the_error_page_points_to_the_home_page_of_every_language",
    },
    {
        # A translation merged into lang/ would change the pages and never redeploy.
        "label": "site: the workflow stops watching the program's language files",
        "file": ".github/workflows/pages.yml",
        "old": '      - "lang/**"\n      - "beantester/appinfo.py"',
        "new": '      - "beantester/appinfo.py"',
        "test": "test_the_workflow_rebuilds_when_any_source_of_the_page_changes",
    },
    {
        # The wrong side of a list in Arabic, and a skip link that makes the page scroll.
        "label": "site: a list indents from the left again",
        "file": "site/assets/style.css",
        "old": "  padding-inline-start: 1.4rem;\n  max-width: 70ch;",
        "new": "  padding-left: 1.4rem;\n  max-width: 70ch;",
        "test": "test_the_stylesheet_pins_nothing_to_the_left_or_the_right",
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
        "file": "beantester/gui/widgets/sortable_tree.py",
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
        "old": "    \"impaired\": {\"foreground\": CAUTION, \"font\": (FONT, 9, \"bold\")},",
        "new": "    \"impaired\": {\"foreground\": CAUTION},",
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
        # Since 2026-09-06 this one line is the walk for BOTH trees (the package
        # and the suite), so emptying it proves both canaries at once. It briefly
        # existed twice, when the suite axes arrived with their own copy, and the
        # runner said "occurs 2 times, not 1" instead of running - which is how a
        # duplicated helper turns a proven guard into a non-result.
        "label": "shape: the tree walk finds no files to measure",
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
        "old": "                self._open_with_retry(self._divert.open)",
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
        "old": "                if self._pid_matches(pid, name, table):\n"
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
               "                crashlog.note(exc, \"targeting.adopt\")"
               "   # note, not once: see below",
        "new": "            targeting.adopt_new_pids()",
        "test": "test_a_failing_adoption_does_not_kill_the_resolver",
    },
    {
        # `once` keys on the subsystem NAME, so the first failure silences every
        # later one - including a different fault, which is the one worth reading.
        "label": "targeting: only the resolver's FIRST kind of failure is recorded",
        "file": "beantester/target_resolver.py",
        "old": "                crashlog.note(exc, \"targeting.resolver\")",
        "new": "                crashlog.once(\"targeting.resolver\", exc)",
        "test": "test_a_second_kind_of_resolver_failure_is_recorded_too",
    },
    {
        # The shipped shape: an unguarded check-then-act, in five copies. Two
        # readers both find the catalogue empty and both scan lang/.
        "label": "i18n: the lazy load goes back to being unguarded",
        "file": "beantester/i18n.py",
        "old": "    if _translations:\n"
               "        return\n"
               "    with _load_lock:\n"
               "        if not _translations:       "
               "# somebody else may have loaded it while we\n"
               "            load_languages()        "
               "# waited - checked again inside the lock",
        "new": "    if not _translations:\n        load_languages()",
        "test": "test_a_cold_catalogue_is_loaded_once_however_many_threads_ask",
    },
    {
        # Cleared only on success, as shipped: a socket table that keeps hiccupping
        # leaves the dict growing, and growing STALE - the rescue then puts a port
        # back in scope whose socket closed long ago.
        "label": "targeting: late owners survive a walk that failed",
        "file": "beantester/targeting.py",
        "old": "            with self._ports_lock:\n"
               "                self._late_owners = {}\n"
               "            table.refresh(force=force)",
        "new": "            table.refresh(force=force)",
        "test": "test_a_failing_refresh_does_not_leave_late_owners_behind",
    },
    {
        # The shipped shape: fourteen setters, fourteen separate holds of the lock
        # a packet is judged under, so a packet in the middle sees a mixture.
        #
        # 🔴 There is deliberately NO companion entry turning `core._lock` back
        # into a plain `Lock`. That mutation does not FAIL, it DEADLOCKS - the
        # batch holds the lock and the first setter inside it waits forever - and
        # this runner has no timeout, so the "proof" would be a hung suite rather
        # than a red one. The reentrancy is REQUIRED by the entry below; it is not
        # separately provable this way, and pretending otherwise would be the kind
        # of claim this whole registry exists to refuse.
        "label": "settings: an apply goes back to separate lock holds per setter",
        "file": "beantester/settings.py",
        "old": "    with _batch(engine):",
        "new": "    with nullcontext():",
        "test": "test_a_packet_decided_during_an_apply_never_sees_half_of_it",
    },
    {
        # A compiled matcher stringified back into text is a matcher compiled
        # AGAIN - and inside the batch, which is the one place compilation may not
        # happen. Not invented: it is what the first version of this batch did,
        # and the guard is what found it.
        "label": "settings: a batched apply recompiles its port expressions",
        "file": "beantester/core.py",
        "old": "            parse_matcher(port if isinstance(port, Matcher) "
               "else port_expression(port),",
        "new": "            parse_matcher(port_expression(port),",
        "test": "test_an_apply_holds_the_core_lock_over_assignments_only",
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
        "old": "                resolved |= late\n",
        "new": "",
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
        "old": ("        self._socketwatch = watcher\n        try:\n"
                "            self._open_with_retry(watcher.start)"),
        "new": "        try:\n            self._open_with_retry(watcher.start)",
        "test": "test_the_socket_watcher_survives_start_stop_cycles",
    },
    {
        "label": "targeting: the bootstrap snapshot is taken before subscribing",
        "file": "beantester/engine.py",
        "old": "        try:\n"
               "            self._open_with_retry(watcher.start)\n"
               "        except Exception as exc:\n",
        "new": "        ports, collected_at = self._ports.collected()\n"
               "        try:\n"
               "            self._open_with_retry(watcher.start)\n"
               "        except Exception as exc:\n",
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
        # 🔴 RE-ANCHORED 2026-08-21, and the reason is the trap itself: this used to
        # aim at the bare `pip install --require-hashes -r requirements-lint.txt`
        # line, which was unique only while ONE job installed the linter. The
        # moment the mutation job needed ruff too, the pattern matched twice and
        # the entry stopped proving anything - the suite said so the same day.
        # The anchor now names two requirement files in one command, which is
        # unique for a reason that has nothing to do with the property guarded
        # here, so extending the linter install again cannot break it.
        "label": "supply chain: a workflow upgrades pip from the index again",
        "file": ".github/workflows/ci.yml",
        "old": "          pip install --require-hashes -r requirements.txt -r requirements-build.txt",
        "new": "          python -m pip install --upgrade pip\n"
               "          pip install --require-hashes -r requirements.txt -r requirements-build.txt",
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
        #
        # 🔴 Anchored on `.sigstore.json` rather than on the flag alone. The flag now
        # appears three times in README.md - it was added to the two ONLINE forms on
        # 2026-08-21, after the one without it shipped in 0.5.0 answering HTTP 404 -
        # and a pattern that matches three places proves nothing about any of them.
        # This anchor is version-independent: the file name carries the version, the
        # extension does not.
        "label": "release: the documented OFFLINE verify command loses its predicate type",
        "file": "README.md",
        "old": ".sigstore.json --repo donislawdev/BeanNetworkTester"
               " --predicate-type https://spdx.dev/Document/v2.3",
        "new": ".sigstore.json --repo donislawdev/BeanNetworkTester",
        "test": "test_the_documented_verify_command_matches_what_we_actually_attest",
    },
    {
        # The other half, and the one that actually broke. `-R` is the online form's
        # short flag and appears nowhere else in the file, so this anchor stays unique
        # for the same reason the one above does.
        "label": "release: the documented ONLINE verify command loses its predicate type",
        "file": "README.md",
        "old": "-R donislawdev/BeanNetworkTester"
               " --predicate-type https://spdx.dev/Document/v2.3",
        "new": "-R donislawdev/BeanNetworkTester",
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
        # Anchored on the line ABOVE as well, and that is not decoration: the
        # installer is signed by the same ritual and carries the same check one
        # indent deeper, so the bare `if actual != ...` line became a SUBSTRING of
        # its own copy and the count went to two. `certificate_of(exe)` is the half
        # that stays unique.
        "label": "release: the signing script stops checking WHICH certificate signed",
        "file": "tools/sign_release.py",
        "old": "        actual = certificate_of(exe)\n        if actual != CODESIGN_SHA256:",
        "new": "        actual = certificate_of(exe)\n        if actual == CODESIGN_SHA256:",
        "test": "test_the_signing_certificate_is_pinned_by_its_bytes",
    },
    {
        # The installer is the SECOND thing this ritual signs, and it needed its own
        # entry the moment it existed: the guard above was written when there was one
        # comparison in the file, and a bare substring search cannot tell which copy
        # it found. It reported SURVIVED on the day the installer landed.
        "label": "release: the signing script stops checking who signed the INSTALLER",
        "file": "tools/sign_release.py",
        "old": "            actual = certificate_of(msi)\n            if actual != CODESIGN_SHA256:",
        "new": "            actual = certificate_of(msi)\n            if actual == CODESIGN_SHA256:",
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
        # Written from the GUI tick, so the shared name is 1.4 chances a second
        # for as long as two windows are open.
        "label": "crashlog: the breadcrumb temp file gets a predictable name again",
        "file": "beantester/crashlog.py",
        "old": "        tmp = temp_beside(path)",
        "new": '        tmp = path + ".tmp"',
        "test": "test_two_breadcrumb_writers_do_not_share_one_temp_file",
    },
    {
        # Back to removing one known name. With a unique temp file that sweeps
        # nothing, and one orphan keeps `crashes/` alive for ever after.
        "label": "crashlog: the sweep for orphaned temp breadcrumbs stops sweeping",
        "file": "beantester/crashlog.py",
        "old": "    for name in [BREADCRUMB_NAME, *stale]:",
        "new": "    for name in [BREADCRUMB_NAME]:",
        "test": "test_a_temp_breadcrumb_left_by_a_kill_is_swept_on_the_next_clean_exit",
    },
    {
        # atexit is LIFO, so without this call the diverts are closed by engine.py's
        # own handler AFTER faulthandler is off - which is what shipped.
        "label": "crashlog: the diverts are closed after the native handler is off",
        "file": "beantester/crashlog.py",
        "old": "            live._stop_live_engines()       "
               "# idempotent: stop() forgets the engine",
        "new": "            pass",
        "test": "test_the_diverts_are_closed_while_the_native_handler_is_still_armed",
    },
    {
        # The shipped cliff: full table -> new fingerprints refused -> every
        # occurrence of a fault that arrived late is a fresh record and a write.
        "label": "crashlog: the crash table refuses new faults instead of making room",
        "file": "beantester/crashlog.py",
        "old": "        _seen[fingerprint] = entry\n"
               "        if len(_seen) > MAX_RECORDS:\n"
               "            _seen.popitem(last=False)       "
               "# the least recently seen fault",
        "new": "        if len(_seen) < MAX_RECORDS:\n"
               "            _seen[fingerprint] = entry",
        "test": "test_a_repeating_fault_is_still_deduplicated_when_the_table_is_full",
    },
    {
        # Bounded, but evicting by ARRIVAL: the fault firing right now is thrown
        # out to make room for faults seen once each.
        "label": "crashlog: the crash table evicts by arrival instead of by recency",
        "file": "beantester/crashlog.py",
        "old": "    _seen.move_to_end(fingerprint)",
        "new": "    pass",
        "test": "test_the_table_makes_room_by_dropping_the_coldest_fault_not_the_busiest",
    },
    {
        # The provider recorded its own fault and was asked again from inside
        # itself: the same failing code, another record, another ask.
        "label": "crashlog: a provider's own fault asks the provider again",
        "file": "beantester/crashlog.py",
        "old": '    if getattr(_local, "in_provider", False):',
        "new": "    if False:",
        "test": "test_a_provider_that_records_a_fault_of_its_own_does_not_wedge_the_logger",
    },
    {
        # The shipped deadlock: the App's provider runs while the logger's only
        # lock is held, so a slow or re-entering provider wedges every thread.
        "label": "crashlog: the context provider runs under the lock again",
        "file": "beantester/crashlog.py",
        "old": "        extra = _context_provider() or {}",
        "new": "        with _lock:\n"
               "            extra = _context_provider() or {}",
        "test": "test_two_threads_can_build_their_context_at_the_same_time",
    },
    {
        # Two threads built a context for the same NEW fault; without the second
        # look the loser overwrites the record and writes it to disk again.
        "label": "crashlog: a fault recorded twice at once is written twice",
        "file": "beantester/crashlog.py",
        "old": "disk write. The context built here is simply dropped.\n"
               "            return _count_again(existing, fingerprint)",
        "new": "disk write. The context built here is simply dropped.\n"
               "            pass",
        "test": "test_the_same_new_fault_from_two_threads_at_once_is_one_record",
    },
    {
        # Back to reading the Tk variables on whichever thread failed: a Tcl call
        # from a worker waits for a main loop that may be waiting on the logger.
        "label": "crash: the GUI's crash report reads the form through Tk again",
        "file": "beantester/gui/crash.py",
        "old": "    raw = _FORMS.get(app)",
        "new": "    raw = app._raw_settings()",
        "test": "test_a_gui_crash_report_never_reads_tk_off_the_main_thread",
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
        "old": 'module = ["beantester.utils", "beantester.gui.rates", "beantester.gui.scope",',
        "new": 'module = ["beantester.gui.rates", "beantester.gui.scope",',
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
        # pack hands out space in CALL order, so a bar packed with nothing to sit
        # before goes in last and lands UNDER the whole page body. The fake cannot
        # render that - it can see the order and that the call stopped saying it.
        "label": "gui: the search bar comes back without saying where to sit",
        "file": "beantester/gui/pages/control.py",
        "old": "                       pady=(scaled(12), scaled(3)), before=self.scroll.canvas)",
        "new": "                       pady=(scaled(12), scaled(3)))",
        "test": "test_the_control_search_bar_can_be_switched_off_and_back_on",
    },
    {
        # The SAME call, broken the other way, and it is a different defect with a
        # different guard: named before the SCROLLBAR the bar takes the full width
        # first, so the scrollbar covers only what sits below this row. Measured on
        # real Tk: 269 px of a 300 px frame instead of 299.
        "label": "gui: the scrollbar stops short of the search row",
        "file": "beantester/gui/pages/control.py",
        "old": "before=self.scroll.canvas)",
        "new": "before=self.scroll.vsb)",
        "test": "test_the_scrollbar_covers_the_page_not_only_what_sits_below_the_search_bar",
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
        # Moved with DROP_BY_REASON when damage.py was carved out of engine.py
        # (2026-09-04). The registry reported it the same day: a pattern that no
        # longer matches is a SKIP, and a skip reads like a pass.
        "label": "engine: the Internet-only drop loses its own counter",
        "file": "beantester/damage.py",
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
        # The seven switches became a table when the complexity ratchet fired on
        # the seventh, so the mutation drops one ROW instead of one branch. Same
        # statement, and the same test still has to redden.
        "old": '("internet_only", "--internet-only"),\n',
        "new": "",
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
        # The measured reason there are two chains: one shared chain splits every
        # run across both directions, so each side sees about half the length the
        # user typed - and the error follows the traffic mix, so there is not even
        # a constant anyone could correct for.
        "label": "burst loss: the two run chains collapse into one shared flag",
        "file": "beantester/core.py",
        "old": "        self._loss_bad[is_outbound] = bad\n        return bad",
        "new": "        self._loss_bad[True] = bad\n        return bad",
        "test": "test_each_direction_gets_a_run_of_the_length_that_was_asked_for",
    },
    {
        # The bug the second analysis caught before it shipped: `p` depends on the
        # loss as much as on the run length, so leaving this to `set_loss_burst`
        # alone would let the ORDER of two setter calls decide correctness.
        "label": "burst loss: changing only the loss leaves the chain stale",
        "file": "beantester/core.py",
        # `_recompute_burst` became `_recompute` when the value sets went per
        # direction (it now re-derives both of them, not only the chain), so the
        # pattern follows the rename. Same statement: drop the re-derivation from
        # the setter that can change the loss.
        "old": "            # for the burst chain, from the run length too), so it has to be\n"
               "            # re-derived here - see _recompute.\n"
               "            self._recompute()",
        "new": "            pass",
        "test": "test_changing_only_the_loss_re_derives_the_chain",
    },
    {
        # A clamp that reports the number it was ASKED for is the silent lie this
        # whole feature was built to avoid: the session would deliver 83% while
        # every surface said 90%.
        "label": "burst loss: an impossible pair claims to deliver what was asked",
        "file": "beantester/core.py",
        "old": "        return (1.0, r, 1.0 / (1.0 + r))",
        "new": "        return (1.0, r, loss)",
        "test": "test_a_pair_that_cannot_exist_is_clamped_and_says_so",
    },
    {
        # Restarting a session inside a run means the first packets of the next
        # one vanish for a reason belonging to the previous session.
        "label": "burst loss: a new session starts inside the previous run",
        "file": "beantester/core.py",
        "old": "            self._loss_bad[True] = self._loss_bad[False] = False\n"
               "            self.loss_bursts = 0",
        "new": "            self.loss_bursts = 0",
        "test": "test_a_session_never_starts_inside_a_run",
    },
    {
        # The counter exists to tell "too short a session" from "this is not
        # working", so a counter stuck at zero is worse than none at all.
        "label": "burst loss: the run counter never counts",
        "file": "beantester/core.py",
        "old": "            bad = True\n            self.loss_bursts += 1",
        "new": "            bad = True",
        "test": "test_the_run_counter_answers_did_this_fire_at_all",
    },
    {
        # The shape the external review found (P1-1): a chain told to "stay bad"
        # at 100% still leaves the bad state at r and lets that packet through.
        "label": "burst loss: total loss walks the chain and lets packets through",
        "file": "beantester/core.py",
        "old": "        # way. This branch is also what keeps the division below from raising.\n"
               "        return None",
        "new": "        # way. This branch is also what keeps the division below from raising.\n"
               "        return (1.0, r, 1.0)",
        "test": "test_total_loss_loses_every_packet_whatever_the_run_length",
    },
    {
        # The shipped scenario walked step by step on one engine: the steps around
        # its outage must deliver their own loss, so a chain derived wrongly shows
        # up there even though the outage itself still drops everything.
        "label": "burst loss: the steps around a scenario's outage deliver the wrong loss",
        "file": "beantester/core.py",
        "old": "    p = loss * r / room",
        "new": "    p = r",
        "test": "test_the_shipped_lte_to_3g_outage_loses_everything",
    },
    {
        # The upload walks its own chain from its own loss, so it clamps on its
        # own - and until P3-4 the apply log never asked about it.
        "label": "burst loss: the upload's clamp and gap go unsaid",
        "file": "beantester/settings.py",
        "old": "    if g(\"asym\"):\n"
               "        _say_burst_loss_for(g(\"loss_up\"), g(\"loss_burst\"), _BURST_LINES_UP, log)",
        "new": "    pass",
        "test": "test_an_upload_the_runs_cannot_carry_is_said_out_loud",
    },
    {
        # The other half of the same helper: with the switch off the upload values
        # are not read, so a line about them describes a link nobody is producing.
        "label": "burst loss: leftover upload values are said with asymmetry off",
        "file": "beantester/settings.py",
        "old": "    if g(\"asym\"):\n"
               "        _say_burst_loss_for(g(\"loss_up\")",
        "new": "    if True:\n"
               "        _say_burst_loss_for(g(\"loss_up\")",
        "test": "test_upload_values_the_session_does_not_read_are_not_said",
    },
    {
        # The upload half of the strip said its loss without its run length, so an
        # upload losing in runs read exactly like one losing evenly (P3-4).
        "label": "summary: the upload loss is described without its run length",
        "file": "beantester/summary.py",
        "old": "             + _loss_parts(g, tr, num, \"loss_up\")",
        "new": "             + _plain_parts(g, tr, num, ((\"loss_up\", \"summary.loss\"),))",
        "test": "test_the_summary_strip_names_the_runs_each_direction_really_gets",
    },
    {
        # A threshold instead of asking the function that DECIDES: the strip then
        # claims runs the engine is not producing - at 100% loss, for one.
        "label": "summary: the upload's run length is compared instead of asked",
        "file": "beantester/summary.py",
        "old": "    if burst_loss_params(number_or_zero(g(key)) / 100.0,\n"
               "                         number_or_zero(g(\"loss_burst\"))) is not None:",
        "new": "    if number_or_zero(g(\"loss_burst\")) > 1.0:",
        "test": "test_the_summary_strip_names_the_runs_each_direction_really_gets",
    },
    {
        # The same shortcut in the download half, which asks inline (it says there
        # why): at 100% loss the strip would promise runs the engine never makes.
        "label": "summary: the download's run length is compared instead of asked",
        "file": "beantester/summary.py",
        "old": "        if burst_loss_params(number_or_zero(g(\"loss\")) / 100.0,\n"
               "                             number_or_zero(g(\"loss_burst\"))) is not None:",
        "new": "        if number_or_zero(g(\"loss_burst\")) > 1.0:",
        "test": "test_the_summary_strip_names_the_runs_each_direction_really_gets",
    },
    {
        # The plainest way to break convention 36, and the one a session in a
        # hurry would reach for: an update check, a crash reporter, a "quick
        # ping home". The static layer answers this one.
        "label": "telemetry: a network client is imported into the shipped package",
        "file": "beantester/summary.py",
        "old": "def settings_summary",
        "new": "import urllib.request\n\n\ndef settings_summary",
        "test": "test_the_shipped_package_imports_no_network_client",
    },
    {
        # The bypass a module-name scan cannot see: `windll.wininet` needs no
        # import statement, so nothing about its spelling looks like networking.
        # This is the entry that justifies the ctypes half existing at all.
        "label": "telemetry: a network library reached through ctypes",
        "file": "beantester/winenv.py",
        "old": "        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))",
        "new": "        ctypes.windll.wininet.InternetOpenW(0, 0, 0, 0, 0)",
        "test": "test_ctypes_opens_only_local_windows_libraries",
    },
    {
        # The bypass the entry above cannot see: the library is ALLOWED. iphlpapi
        # reads the socket table for portmap.py and exports IcmpSendEcho2 for
        # anybody, and the check by library name passed this line on 2026-09-21
        # without a word. The function-level half is what reddens it.
        "label": "telemetry: a ping through the allowed iphlpapi",
        "file": "beantester/winenv.py",
        "old": "        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))",
        "new": "        ctypes.windll.iphlpapi.IcmpSendEcho2(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)",
        "test": "test_no_allowed_library_is_used_to_send_a_packet",
    },
    {
        # The bypass an outside review found, and the measurement confirmed: the
        # scan read `socket.x(...)` and nothing else, so `import socket as s`
        # walked straight through - as did the from-import form. Registering the
        # IMPORT is what closes it, because a statement names its module whatever
        # the local name becomes.
        "label": "telemetry: a module reaches for socket under an alias",
        "file": "beantester/views.py",
        "old": "def sort_events(",
        "new": "import socket as _s\n\n\ndef sort_events(",
        "test": "test_only_named_files_may_import_a_module_that_reaches_outside",
    },
    {
        # The RUNTIME half, and the only one of the three that no AST can answer:
        # the module name is assembled from two strings. Measured: the audit hook
        # reported urllib, http, http.client and ssl the moment the line ran.
        "label": "telemetry: a client imported under a computed name at runtime",
        "file": "beantester/cli.py",
        "old": '    """Run the CLI. Returns the process exit code (see ``exitcodes``)."""',
        "new": '    """Run the CLI. Returns the process exit code (see ``exitcodes``)."""\n'
               "    __import__('url' + 'lib.request')",
        "test": "test_a_real_run_raises_no_network_audit_event",
    },
    {
        # The counter simply not counting. Its own tile would read 0 for ever,
        # which is indistinguishable from a session where nothing overtook
        # anything - the exact confusion the counter exists to end.
        "label": "reordering: an overtaken packet is not counted",
        "file": "beantester/engine.py",
        "old": '            self._bump("reordered")',
        "new": "            pass",
        "test": "test_a_packet_that_is_overtaken_is_counted_as_reordered",
    },
    {
        # The other direction, and the one a bare "does it count?" test misses:
        # a counter that increments per delivered packet passes the test above
        # and means nothing.
        "label": "reordering: every packet counts as reordered",
        "file": "beantester/engine.py",
        "old": "        if arrived < self._last_sent[is_out]:",
        "new": "        if True:",
        "test": "test_packets_that_keep_their_order_are_not_counted",
    },
    {
        # One shared high-water mark instead of one per direction. Ordinary
        # two-way traffic then ticks the counter for inbound and outbound
        # packets overtaking each other, which no receiver can observe.
        "label": "reordering: one high-water mark shared by both directions",
        "file": "beantester/engine.py",
        "old": "        if arrived < self._last_sent[is_out]:\n"
               '            self._bump("reordered")\n'
               "        else:\n"
               "            self._last_sent[is_out] = arrived",
        "new": "        if arrived < self._last_sent[True]:\n"
               '            self._bump("reordered")\n'
               "        else:\n"
               "            self._last_sent[True] = arrived",
        "test": "test_the_two_directions_are_judged_separately",
    },
    {
        # Marking a packet as sent on the FAILURE path. The packet behind it is
        # then judged against one that never reached the stack and reported as
        # overtaken by it. Surgical on purpose: it touches only the except
        # branch, so the other four tests here stay green and this one is shown
        # to be load-bearing on its own.
        "label": "reordering: a refused send still moves the mark",
        "file": "beantester/engine.py",
        "old": '                self._bump("drop_send")\n'
               '                self._conns_log.charge(key, "dropped")\n',
        "new": '                self._bump("drop_send")\n'
               '                self._conns_log.charge(key, "dropped")\n'
               "                self._note_order(arrived,\n"
               '                                 bool(getattr(packet, "is_outbound", True)))\n',
        "test": "test_a_packet_the_driver_refused_does_not_make_the_next_one_look_overtaken",
    },
    {
        # The mark surviving a restart while the counter is zeroed. The next
        # session then reports reordering it never did, on its very first
        # packets, and the numbers look plausible.
        "label": "reordering: a restart keeps the previous high-water mark",
        "file": "beantester/engine.py",
        "old": "        self._last_sent = {True: -1, False: -1}",
        "new": '        self._last_sent = getattr(self, "_last_sent", {True: -1, False: -1})',
        "test": "test_a_restarted_session_does_not_inherit_the_previous_high_water_mark",
    },
    {
        # The comfortable answer: a megabit as 1024*1024 bits makes 1024 KB/s come
        # out as exactly 8.00, which is the number a reader expects and is 4.9%
        # wrong. Nothing but an assertion on the digits can catch it, because the
        # wrong version looks MORE right than the correct one.
        "label": "units: a megabit becomes binary, so 1024 KB/s reads 8.00",
        "file": "beantester/gui/rates.py",
        "old": '    ("mbit", "Mbit/s", 1024.0 * 8.0 / 1_000_000.0),',
        "new": '    ("mbit", "Mbit/s", 1024.0 * 8.0 / 1_048_576.0),',
        "test": "test_a_kilobyte_here_is_1024_bytes_and_a_megabit_is_a_million_bits",
    },
    {
        # Writing the LABEL into ui.json instead of the value. It survives the
        # restart, matches no known unit, falls back to KB/s - and reads as "the
        # preference does not stick" rather than as a bug in the write.
        "label": "units: the dropdown stores its label instead of its value",
        "file": "beantester/gui/panels/settings.py",
        "old": "                     self._store(k, m.get(v.get())), add=\"+\")",
        "new": "                     self._store(k, v.get()), add=\"+\")",
        "test": "test_the_dropdown_stores_the_value_and_never_the_label",
    },
    {
        # The view over the registry replaced by a list of names - the drift this
        # project keeps paying for, and invisible until a third rate field exists.
        "label": "units: the rate fields become a hand-written list",
        "file": "beantester/gui/rates.py",
        "old": "RATE_FIELD_KEYS = tuple(f.key for f in FIELD_DEFS if f.unit == BASE_LABEL)",
        "new": 'RATE_FIELD_KEYS = ("down",)',
        "test": "test_the_rate_fields_are_a_view_over_the_registry_not_a_list_of_names",
    },
    {
        # "1024 KB/s" printed beside a box that says 1024. Harmless-looking, and
        # the reason the readout exists at all is that it says something the box
        # does not.
        "label": "units: the converted readout repeats the value in the base unit",
        "file": "beantester/gui/form.py",
        "old": "            if unit == DEFAULT_UNIT or var is None:",
        "new": "            if var is None:",
        "test": "test_the_converted_readout_appears_only_when_there_is_something_to_convert",
    },
    {
        # The WIRING rather than the label: the page stops reacting to the
        # preference, so the readout keeps naming the unit you just changed away
        # from until something else rebuilds the form. Worth its own entry because
        # this reaction has already moved once (out of App.set_pref, which sits on
        # the size ratchet) and the test had to be pointed at the real path before
        # it could see the difference.
        "label": "units: the Control page stops reacting to the unit preference",
        "file": "beantester/gui/pages/control.py",
        "old": "            self.form.sync_rate_hints()",
        "new": "            pass",
        "test": "test_the_converted_readout_appears_only_when_there_is_something_to_convert",
    },
    {
        # The reset that answers a SYN loses its ACK - which is the shape the
        # project measured being IGNORED in SYN_SENT twice, a year and a month
        # apart. It looks like it works: the reset goes out and rst_sent counts it.
        "label": "block: the reset answering a SYN goes back to having no ACK",
        "file": "beantester/core.py",
        "old": "                seq, ack = 0, (getattr(tcp, \"seq_num\", 0) + 1) & 0xFFFFFFFF",
        "new": "                seq, ack = getattr(tcp, \"ack_num\", 0), None",
        "test": "test_the_reset_that_answers_a_syn_acknowledges_it",
    },
    {
        # A refusal counted as a connection torn down. Both numbers reach the user
        # (connections_reset in the CSV and the repro report), and neither would
        # mean anything afterwards.
        "label": "block: a refusal is counted as a connection torn down",
        "file": "beantester/engine.py",
        "old": "                    self._bump(RST_BY_REASON.get(dec.reason, \"rst_reset\"))",
        "new": "                    self._bump(\"rst_reset\")",
        "test": "test_every_forged_reset_is_counted_under_its_own_cause",
    },
    {
        # The mode stops being a mode: every block answers, which changes what
        # every existing block does to the traffic it was already blocking.
        "label": "block: the refuse mode is ignored and every block answers",
        "file": "beantester/core.py",
        "old": "                                self.block_reject and is_tcp and is_outbound)",
        "new": "                                is_tcp and is_outbound)",
        "test": "test_a_blocked_connection_is_refused_only_when_the_mode_is_on",
    },
    {
        # The rate limit goes back to a log line per failed injection. The RST
        # feature could only fail slowly (a cooldown per flow); a refusal fires on
        # every SYN retransmit, and the GUI applies every line on the UI thread.
        "label": "block: a failed refusal is logged per packet again",
        "file": "beantester/engine.py",
        "old": "            self._warn_rst_failed(e)",
        "new": "            self.log(f\"{T('log.rst_inject_failed')} ({e})\")",
        "test": "test_a_reset_that_cannot_be_injected_is_reported_once_not_per_packet",
    },
    {
        # The two limits that would forge a reset nobody receives. UDP first: a
        # blocked datagram would get a TCP reset built from a packet with no TCP
        # header at all.
        "label": "block: the refusal stops checking that this is outbound TCP",
        "file": "beantester/core.py",
        "old": "                                self.block_reject and is_tcp and is_outbound)",
        "new": "                                self.block_reject)",
        "test": "test_what_the_refusal_deliberately_does_not_answer",
    },
    {
        # The exact line Chocolatey's moderation refused, and the branch pin that
        # came with it. One line carries both faults, so one mutation restores both.
        "label": "packaging: the Chocolatey icon goes back to a branch on github.com",
        "file": "packaging/chocolatey/bean-network-tester.nuspec.in",
        "old": "    <iconUrl>{{ICON_URL}}</iconUrl>",
        "new": "    <iconUrl>{{REPO_URL}}/raw/master/bean.png</iconUrl>",
        "test": "test_the_chocolatey_icon_is_a_pinned_cdn_url",
    },
    {
        # Two directions losing different amounts need two chains, because p is
        # derived from the loss. Sharing one pair meant re-deriving it reset BOTH
        # runs, so a change to the upload ended the download's run in flight.
        "label": "core: the burst chains share one reset again",
        "file": "beantester/core.py",
        "old": "                self._loss_bad[outbound] = False",
        "new": "                self._loss_bad[True] = self._loss_bad[False] = False",
        "test": "test_raising_the_upload_loss_does_not_cut_a_download_run_in_flight",
    },
    {
        # ...and the other half of the same fix: both chains derived from the
        # DOWNLOAD loss, so the upload walks a chain built for the wrong number.
        "label": "core: both burst chains come from the download loss",
        "file": "beantester/core.py",
        "old": "        params = burst_loss_params(loss, self.loss_burst)",
        "new": "        params = burst_loss_params(self.loss, self.loss_burst)",
        "test": "test_raising_the_upload_loss_does_not_cut_a_download_run_in_flight",
    },
    {
        # The rejected design, where an absent upload value simply means zero. A
        # profile written before asymmetry then silently becomes "7% down, 0% up"
        # - it still LOADS, which is why loading was never the question.
        "label": "core: upload values are read whether or not the switch is on",
        "file": "beantester/core.py",
        "old": "        if self.asymmetric:",
        "new": "        if True:",
        "test": "test_a_profile_written_before_asymmetry_still_means_what_it_meant",
    },
    {
        # Without impairs, `--asym --loss-up 50` cuts half of everything this
        # machine sends, with no target and no deadline, and starts in silence.
        "label": "fields: an upload impairment stops declaring its blast radius",
        "file": "beantester/fields.py",
        "old": '          cli="loss-up", impairs=IMPAIRS_ALL, live_when="asym",',
        "new": '          cli="loss-up", live_when="asym",',
        "test": "test_an_upload_impairment_earns_the_blast_radius_warning",
    },
    {
        # ...and without live_when it cries wolf on the ordinary path of trying
        # the feature and unticking the box again.
        "label": "fields: an upload impairment forgets which switch reads it",
        "file": "beantester/fields.py",
        "old": '          cli="loss-up", impairs=IMPAIRS_ALL, live_when="asym",',
        "new": '          cli="loss-up", impairs=IMPAIRS_ALL,',
        "test": "test_an_upload_value_left_behind_by_the_switch_warns_about_nothing",
    },
    {
        # The switch is the first BOOL in the profile scope. Dropped from it,
        # every saved asymmetric profile comes back symmetric with all seven
        # values present - the wrong link, described in full.
        "label": "fields: the asymmetry switch leaves the profile scope",
        "file": "beantester/fields.py",
        "old": '          tip="tips.asym", span=True, cli="asym", in_profile=True,',
        "new": '          tip="tips.asym", span=True, cli="asym", in_profile=False,',
        "test": "test_the_switch_survives_a_profile_round_trip",
    },
    {
        # The uniform number_string both form loaders used before a profile field
        # could be a checkbox: the switch arrives as the string "0", which real
        # tkinter coerces back to False by luck.
        "label": "fields: a profile switch reaches the form as text",
        "file": "beantester/fields.py",
        "old": "    return bool(value) if FIELDS[key].kind == BOOL else number_string(value)",
        "new": "    return number_string(value)",
        "test": "test_a_profile_switch_reaches_the_form_as_a_switch_not_as_text",
    },
    # -- the Tools tab (2026-09-23) -------------------------------------------- #
    {
        # A hand-written list here is what hid two Statistics tabs from the render
        # check for months; derived, a new tool is measured the day it lands.
        "label": "toolbox: the sub-tab list stops following the registry",
        "file": "beantester/gui/pages/toolbox.py",
        "old": "    SUBPAGES = tuple((tool.id, tool.label) for tool in TOOLS)",
        "new": "    SUBPAGES = ()",
        "test": "test_the_tools_page_is_the_renderer_of_its_registry",
    },
    {
        # The render check selects a sub-tab and measures at once; a panel built
        # only from <<NotebookTabChanged>> would be an empty tab when measured.
        "label": "toolbox: select no longer builds the panel it shows",
        "file": "beantester/gui/pages/toolbox.py",
        "old": "            self.nb.select(index)\n        self._ensure(tool_id)",
        "new": "            self.nb.select(index)",
        "test": "test_a_panel_is_built_on_first_view_and_the_open_tab_is_remembered",
    },
    {
        "label": "toolbox: a tool that is gone from the registry breaks the page",
        "file": "beantester/gui/pages/toolbox.py",
        "old": "        if tool_id not in TOOL_BY_ID:\n            tool_id = TOOLS[0].id",
        "new": "        if False:\n            tool_id = TOOLS[0].id",
        "test": "test_a_panel_is_built_on_first_view_and_the_open_tab_is_remembered",
    },
    {
        # App._tick refreshes the page in one try with the summary bar and the
        # secondary windows: an unguarded panel would stop them every 700 ms.
        "label": "toolbox: a panel's refresh reaches the tick unguarded",
        "file": "beantester/gui/pages/toolbox.py",
        "old": '            self._each("refresh", panels=(panel,))',
        "new": "            panel.refresh()",
        "test": "test_a_tool_that_fails_does_not_take_the_tab_or_the_tick_down",
    },
    {
        "label": "toolbox: a rebuild no longer tears the panels down",
        "file": "beantester/gui/pages/toolbox.py",
        "old": '    def teardown(self):\n        self._each("teardown")',
        "new": "    def teardown(self):\n        pass",
        "test": "test_a_rebuild_puts_the_typing_timer_away_first",
    },
    {
        # Saved only when the pause runs out, a language change inside it loses
        # the last word typed.
        "label": "toolbox: the tester remembers what was typed only after the pause",
        "file": "beantester/gui/toolbox/exprtest.py",
        "old": "        self.memory[name] = self.vars[name].get()\n        self.debounce()",
        "new": "        self.debounce()",
        "test": "test_the_tester_answers_and_names_the_term_that_decided",
    },
    {
        # Empty in the Process field means ALL traffic once applied.
        "label": "toolbox: Use sends an empty expression into the Control field",
        "file": "beantester/gui/toolbox/exprtest.py",
        "old": '        return verdict.state in USABLE and bool(self.vars["expression"].get().strip())',
        "new": "        return verdict.state in USABLE",
        "test": "test_use_replaces_the_field_and_refuses_an_empty_or_unreadable_expression",
    },
    {
        # matches() says False for a value it cannot read; shown to a person that
        # is a statement about the expression, which is fine.
        "label": "exprtest: an address that is not one answers 'does not match'",
        "file": "beantester/nettools/exprtest.py",
        "old": '        raise _BadValue("tools.exprtest.bad_ip") from None',
        "new": "        return (text,)",
        "test": "test_an_unreadable_value_is_reported_as_the_value_not_as_no_match",
    },
    {
        "label": "exprtest: a number is anything isdigit() accepts",
        "file": "beantester/nettools/exprtest.py",
        "old": "    if not _DIGITS.fullmatch(text):",
        "new": "    if not text.isdigit():",
        "test": "test_only_ascii_digits_are_a_number",
    },
    {
        "label": "exprtest: a pid left in the box is held against an address",
        "file": "beantester/nettools/exprtest.py",
        "old": "    if field.expr_kind != KIND_PROCESS:\n        pid = \"\"",
        "new": "    if False:\n        pid = \"\"",
        "test": "test_a_pid_left_behind_does_not_touch_a_field_that_has_none",
    },
    {
        # The logic package calls the window: the day a --tool form of it could no
        # longer exist without a display.
        "label": "exprtest: the logic imports the window",
        "file": "beantester/nettools/exprtest.py",
        "old": "from ..fields import EXPR, FIELDS",
        "new": "from ..fields import EXPR, FIELDS\nfrom ..gui import theme  # noqa: F401",
        "test": "test_nettools_never_reaches_up_into_the_window",
    },
    {
        # The README promise edited on its own: without the exact-sentence check the
        # guard below it would go quiet while the reworded promise stood unchecked.
        "label": "toolbox promise: the README sentence is reworded behind the check",
        "file": "README.md",
        "old": "  Nothing on this tab sends anything over the network. Today:",
        "new": "  Nothing on this tab sends anything anywhere. Today:",
        "test": "test_the_tools_tab_says_it_sends_nothing_only_while_nothing_on_it_can",
    },
    {
        # One allowlist entry and a reason would let a sending tool past the
        # package-wide guard; the tab's own promise must still go red.
        "label": "toolbox promise: a tool reaches for a socket",
        "file": "beantester/nettools/exprtest.py",
        "old": "import ipaddress\nimport re\n",
        "new": "import ipaddress\nimport re\nimport socket  # noqa: F401\n",
        "test": "test_the_tools_tab_says_it_sends_nothing_only_while_nothing_on_it_can",
    },
    {
        # Only exclusions ("!chromedriver") must still match everything else - the
        # rule matches() has always had, and the one the tester explains.
        "label": "matchers: explain forgets that no positive term means everything",
        "file": "beantester/matchers.py",
        "old": "        matched = (not self._positives or bool(selected)) and not excluded",
        "new": "        matched = bool(selected) and not excluded",
        "test": "test_explain_names_the_terms_that_decided",
    },
    {
        # The import extractor resolving nothing: the page's tkinter import alone
        # used to keep the canary green, so only the gui/ half can prove this.
        "label": "layering canary: the import extractor resolves nothing",
        "file": "tests/test_layering.py",
        "old": "    eager, lazy = _internal_imports(path)\n    upward = sorted(",
        "new": "    eager, lazy = set(), set()\n    upward = sorted(",
        "test": "test_nettools_never_reaches_up_into_the_window",
    },
    {
        # The raw-key pattern back to one dot: `tools.exprtest.tab` on screen went
        # unseen that way, with every translation check green.
        "label": "smoke: the raw-key pattern stops seeing nested keys",
        "file": "smoke_gui.py",
        "old": 'RAW_KEY = re.compile(r"^(%s)(\\.[a-z0-9_]+)+$"',
        "new": 'RAW_KEY = re.compile(r"^(%s)\\.[a-z0-9_]+$"',
        "test": "test_gui_smoke_script",
    },
    {
        # The shared "?" with its sheet's two keys swapped: the right window, the
        # wrong words, on every "?" at once.
        "label": "help button: the sheet opens with title and body swapped",
        "file": "beantester/gui/dialogs.py",
        "old": "command=lambda: show_help(root, T(title_key), T(body_key)))",
        "new": "command=lambda: show_help(root, T(body_key), T(title_key)))",
        "test": "test_every_question_mark_opens_its_own_sheet",
    },
    {
        # One caller handing over another place's sheet - the connection search
        # opening the expression cheat sheet it used to be copied from.
        "label": "help button: the connection search opens the expression sheet",
        "file": "beantester/gui/pages/conns.py",
        "old": '"dialogs.conn_search_help_title",\n                            '
               '"dialogs.conn_search_help",',
        "new": '"dialogs.match_help_title",\n                            '
               '"dialogs.match_help",',
        "test": "test_every_question_mark_opens_its_own_sheet",
    },
    {
        # The runner's own refusal gone: a typo'd filter falls through to an empty
        # run again, which crashed - or, with --changed, reported "nothing touched".
        "label": "mutate: a label filter that matches nothing is run anyway",
        "file": "tools/mutate.py",
        "old": "    if needle and not entries:\n",
        "new": "    if False:\n",
        "test": "test_a_label_filter_that_matches_nothing_is_a_usage_error",
    },
    {
        # Usage printed, exit 0 - and a run behind it: only counting the runs sees it.
        "label": "mutate: --help prints the usage and runs mutations anyway",
        "file": "tools/mutate.py",
        "old": "        print(__doc__[__doc__.index(\"Usage\"):].rstrip())\n        return 0\n",
        "new": "        print(__doc__[__doc__.index(\"Usage\"):].rstrip())\n        argv = [\"mutate:\"]\n",
        "test": "test_help_prints_the_usage_instead_of_running",
    },
    # -- the Tools tab: diagnostics (T-1) -------------------------------------- #
    {
        # The driver unloaded under the window's own session.
        "label": "diagnostics: the cleanup forgets a running session",
        "file": "beantester/gui/toolbox/diagnostics.py",
        "old": "return not self.blocker and not self._session_busy() and not self.job.busy()",
        "new": "return not self.blocker and not self.job.busy()",
        "test": "test_cleaning_up_waits_for_the_session_and_for_a_yes",
    },
    {
        # A session starting or stopping holds the handle while `running` says no.
        "label": "diagnostics: a start or stop in flight is not a session",
        "file": "beantester/gui/toolbox/diagnostics.py",
        "old": 'return bool(self.app.running) or getattr(self.app, "_transition", None) is not None',
        "new": "return bool(self.app.running)",
        "test": "test_cleaning_up_waits_for_the_session_and_for_a_yes",
    },
    {
        # Unloaded before anyone read what it interrupts.
        "label": "diagnostics: the cleanup runs without a yes",
        "file": "beantester/gui/toolbox/diagnostics.py",
        "old": "        if not dialogs.ask_yes_no(self.app.root,",
        "new": "        if False and dialogs.ask_yes_no(self.app.root,",
        "test": "test_cleaning_up_waits_for_the_session_and_for_a_yes",
    },
    {
        # The window keeps its marker, so "another instance" can never be seen.
        "label": "driver: the window's cleanup keeps its own use marker",
        "file": "beantester/driver.py",
        "old": "someone_else = (_drop_use_marker() if release_own",
        "new": "someone_else = (_drop_use_marker() if False",
        "test": "test_a_window_lets_its_own_marker_go_before_asking_about_others",
    },
    {
        # The other half of the same promise: the tab asking the read-only way.
        "label": "diagnostics: the tab cleans up without letting its marker go",
        "file": "beantester/nettools/diagnostics.py",
        "old": "return tuple(driver.cleanup_driver(release_own=True, opens_seen=opens_seen))",
        "new": "return tuple(driver.cleanup_driver(opens_seen=opens_seen))",
        "test": "test_the_window_cleans_up_with_its_own_marker_let_go_first",
    },
    {
        # A START pressed during the cleanup opens its handle while the driver stops.
        "label": "driver: a window's cleanup runs outside the claim",
        "file": "beantester/driver.py",
        "old": "    with _CLAIM:\n        return _cleanup_claimed(release_own, opens_seen)",
        "new": "    if True:\n        return _cleanup_claimed(release_own, opens_seen)",
        "test": "test_a_window_cleanup_and_a_start_hold_one_claim",
    },
    {
        # ...and the other side: a start that does not wait for a cleanup running.
        "label": "driver: a start marks the driver without waiting for a cleanup",
        "file": "beantester/driver.py",
        "old": "    with _CLAIM:\n        _DRIVER_USED[0] = True",
        "new": "    if True:\n        _DRIVER_USED[0] = True",
        "test": "test_a_window_cleanup_and_a_start_hold_one_claim",
    },
    {
        "label": "driver: taking the use marker is two steps again",
        "file": "beantester/driver.py",
        "old": "    with _CLAIM:        # \"none yet\" and \"now ours\" must be one step",
        "new": "    if True:        # \"none yet\" and \"now ours\" must be one step",
        "test": "test_each_marker_step_is_one_step",
    },
    {
        # Two threads read the same handle and both close it.
        "label": "driver: dropping the use marker is two steps again",
        "file": "beantester/driver.py",
        "old": "    with _CLAIM:\n        marker, _USE_MARKER[0] = _USE_MARKER[0], None",
        "new": "    if True:\n        marker, _USE_MARKER[0] = _USE_MARKER[0], None",
        "test": "test_each_marker_step_is_one_step",
    },
    {
        # The START won the claim first; the cleanup stops the driver under it.
        "label": "driver: a cleanup asked for before a start unloads it anyway",
        "file": "beantester/driver.py",
        "old": "    if opens_seen is not None and _OPENS[0] != opens_seen:",
        "new": "    if False:",
        "test": "test_a_cleanup_asked_for_before_a_start_stands_down_for_it",
    },
    {
        # Read by the worker, the count already includes the START it must catch.
        "label": "diagnostics: the open count is read by the worker, not at the yes",
        "file": "beantester/gui/toolbox/diagnostics.py",
        "old": "        self._run(CLEAN, lambda: diagnostics.clean_up(seen))",
        "new": "        self._run(CLEAN, lambda: diagnostics.clean_up(diagnostics.opens_so_far()))",
        "test": "test_the_cleanup_is_held_to_what_was_open_at_the_yes",
    },
    {
        # One test's starts reach the next test's count (conftest's teardown).
        "label": "tests: the open count survives into the next test",
        "file": "tests/fakes.py",
        "old": "    driver._OPENS[0] = 0",
        "new": "    driver._OPENS[0] += 0",
        "test": "test_no_test_hands_its_driver_state_to_the_next",
    },
    {
        # ...and its flag, so the next test's exit path unloads a driver it never used.
        "label": "tests: the driver-used flag survives into the next test",
        "file": "tests/fakes.py",
        "old": "    driver._DRIVER_USED[0] = False",
        "new": "    driver._DRIVER_USED[0] = driver._DRIVER_USED[0]",
        "test": "test_no_test_hands_its_driver_state_to_the_next",
    },
    {
        # A report whose crash-log block failed still starts with "crash log: ".
        "label": "diagnostics: the crash-log block of the report cannot be read",
        "file": "beantester/nettools/diagnostics.py",
        "old": "    counts = crashlog.summary()",
        "new": "    counts = crashlog.summary_that_is_not_there()",
        "test": "test_the_report_is_the_version_line_and_the_doctor_output",
    },
    {
        # doctor() grows or renames a check and the window shows it unnamed.
        "label": "diagnostics: a check doctor gives has no name in the language files",
        "file": "beantester/driver.py",
        "old": 'checks.append(("driver queue", "ok",',
        "new": 'checks.append(("driver queues", "ok",',
        "test": "test_every_check_doctor_can_give_has_a_name_in_every_language",
    },
    {
        "label": "diagnostics: one broken report section takes the report down",
        "file": "beantester/nettools/diagnostics.py",
        "old": '        except Exception as exc:\n            crashlog.note(exc, "nettools.diagnostics")',
        "new": '        except ZeroDivisionError as exc:\n            crashlog.note(exc, "nettools.diagnostics")',
        "test": "test_a_section_that_fails_costs_its_own_block_and_nothing_else",
    },
    {
        # The template asks for --doctor's output; the copy drifts from it.
        "label": "diagnostics: the report stops being the --doctor output",
        "file": "beantester/nettools/diagnostics.py",
        "old": "return driver.format_doctor(diagnosis.checks, diagnosis.data_dir)",
        "new": "return driver.format_doctor(diagnosis.checks[:1], diagnosis.data_dir)",
        "test": "test_the_report_is_the_version_line_and_the_doctor_output",
    },
    {
        # A tool whose work raises: the status line would say "working" for ever.
        "label": "toolbox: a failed run never reaches the status line",
        "file": "beantester/gui/toolbox/base.py",
        "old": "    except BaseException as exc:",
        "new": "    except ZeroDivisionError as exc:",
        "test": "test_a_check_that_fails_says_why_and_keeps_the_rows_it_had",
    },
    {
        # The worker kept on the panel: a language change loses the running answer.
        "label": "toolbox: a rebuild starts a new worker and loses the running answer",
        "file": "beantester/gui/toolbox/base.py",
        "old": "    if tool_id not in jobs:",
        "new": "    if True:",
        "test": "test_a_rebuild_mid_check_hands_the_answer_to_the_new_panel",
    },
    {
        # `pending()` looks while a timer is armed: the forgotten one keeps a chain.
        "label": "toolbox: looking now leaves the armed timer behind",
        "file": "beantester/gui/toolbox/base.py",
        "old": "        self.cancel()\n        outcome = self._job.collect()",
        "new": "        self._timer = None\n        outcome = self._job.collect()",
        "test": "test_looking_now_puts_the_armed_timer_away_first",
    },
    {
        # Refilling the old container: its resize handlers pile up per check.
        "label": "diagnostics: re-checking keeps the old rows container alive",
        "file": "beantester/gui/toolbox/diagnostics.py",
        "old": "        if self.rows is not None:\n            self.rows.destroy()",
        "new": "        if self.rows is not None:\n            self.rows.pack_forget()",
        "test": "test_diagnostics_shows_every_check_with_its_verdict_and_checks_once_by_itself",
    },
    {
        "label": "diagnostics: the first view does not check by itself",
        "file": "beantester/gui/toolbox/diagnostics.py",
        "old": ("        if CHECK not in self.job.last and not self.job.busy():\n"
                "            self.check()"),
        "new": "        if False:\n            self.check()",
        "test": "test_diagnostics_shows_every_check_with_its_verdict_and_checks_once_by_itself",
    },
    {
        # The tool the window reopens on is built with it: a check there runs at
        # every start of the program (B-21).
        "label": "diagnostics: the check runs when the window opens",
        "file": "beantester/gui/toolbox/diagnostics.py",
        "old": "        self.poller = Poller(self.frame, self.job, self._on_outcome)",
        "new": ("        self.poller = Poller(self.frame, self.job, self._on_outcome)\n"
                "        self._check_if_never()"),
        "test": "test_diagnostics_checks_when_first_looked_at_and_not_at_start_up",
    },
    {
        # A check that failed is asked again on every tick, forever.
        "label": "diagnostics: a failed first check is retried on every tick",
        "file": "beantester/gui/toolbox/diagnostics.py",
        "old": "        if CHECK not in self.job.last and not self.job.busy():",
        "new": "        if not self.job.value and not self.job.busy():",
        "test": "test_a_first_check_that_fails_says_so_and_is_not_retried_by_itself",
    },
    {
        # Real Tk runs the constructor's own tab change once the window is built,
        # with another page in front: the tool on that tab goes to work at start-up.
        "label": "toolbox: a tab change off screen puts the tool to work",
        "file": "beantester/gui/pages/toolbox.py",
        "old": "        if self.app.current_page() is self:\n            self.refresh()",
        "new": "        if True:\n            self.refresh()",
        "test": "test_the_socket_table_reads_when_first_looked_at_and_not_at_start_up",
    },
    {
        # The shared copy, moved out of the Statistics page: a cheerful lie again.
        "label": "clipboard: a copy is confirmed without reading it back",
        "file": "beantester/gui/clipboard.py",
        "old": "        if app.root.clipboard_get() == text:",
        "new": "        if True:",
        "test": "test_a_copy_is_confirmed_only_when_the_clipboard_really_has_it",
    },
    {
        # A tab filled by a worker measured empty, every label outside the check.
        "label": "render check: a surface is measured before its worker answered",
        "file": "tools/ci_gui_render.py",
        "old": "    while pending():",
        "new": "    while False:",
        "test": "test_the_render_check_walks_every_page_and_every_sub_tab",
    },
    {
        # The promise read off the tab's own files only, blind to driver.py.
        "label": "toolbox promise: the modules the tab reaches into go unread",
        "file": "tests/test_no_telemetry.py",
        "old": "        names |= eager | lazy\n",
        "new": "        names |= set()\n",
        "test": "test_the_tools_tab_says_it_sends_nothing_only_while_nothing_on_it_can",
    },
    {
        # The staged mid-tick stop detaches a watcher nobody stops: its thread parks
        # for the rest of the process and reddens later thread counts elsewhere.
        "label": "tests: the mid-tick stop test leaves its watcher thread running",
        "file": "tests/test_socketwatch_wiring.py",
        "old": "        if ports.detached is not None:\n            ports.detached.stop()",
        "new": "        if False:\n            ports.detached.stop()",
        "test": "test_a_stop_landing_mid_tick_does_not_fault_the_watchdog",
    },
    {
        # An __init__ read as a module of its parent: its own edges lost or misfiled.
        "label": "layering: a package's __init__ resolves its imports one level too high",
        "file": "tests/source_imports.py",
        "old": "    if not is_package:\n        parts = parts[:-1]\n",
        "new": "    parts = parts[:-1]\n",
        "test": "test_a_package_init_resolves_its_relative_imports_inside_itself",
    },
    {
        # The walk the capture-side port map and the Tools tab share: a table that
        # outgrew the first buffer is dropped instead of asked again.
        "label": "portmap: the socket table stops growing its buffer",
        "file": "beantester/portmap.py",
        "old": "            if rc != _ERROR_INSUFFICIENT_BUFFER:\n                return None",
        "new": "            if True:\n                return None",
        "test": "test_the_walk_grows_its_buffer_and_remembers_the_size",
    },
    {
        # The capture side's map starts installing TIME_WAIT rows as PID 0's ports.
        "label": "portmap: the port map keeps the socket no process owns",
        "file": "beantester/portmap.py",
        "old": "            if port and pid:\n                # LAST ROW WINS",
        "new": "            if port:\n                # LAST ROW WINS",
        "test": "test_the_socket_table_keeps_every_row_the_port_map_drops",
    },
    {
        # A listener shows the 1.2.3.4:99 its row happens to hold.
        "label": "portmap: a listener shows the remote half it does not have",
        "file": "beantester/portmap.py",
        "old": "                     \"\" if idle else _ipv4(row.dwRemoteAddr),",
        "new": "                     _ipv4(row.dwRemoteAddr),",
        "test": "test_the_socket_table_keeps_every_row_the_port_map_drops",
    },
    {
        # Learn's "network byte order", which the measurement contradicts.
        "label": "portmap: the IPv6 scope is byte-swapped the way the docs say",
        "file": "beantester/portmap.py",
        "old": "    return f\"{text}%{int(scope)}\" if scope else text",
        "new": ("    return (f\"{text}%{int.from_bytes(int(scope).to_bytes(4, 'little'), 'big')}\"\n"
                "            if scope else text)"),
        "test": "test_the_socket_table_keeps_every_row_the_port_map_drops",
    },
    {
        # The two paths stop speaking the same words: state:syn_received misses psutil's.
        "label": "portmap: psutil's state names are shown as psutil spells them",
        "file": "beantester/portmap.py",
        "old": "    state = _PSUTIL_STATES.get(conn.status, conn.status) if proto == \"TCP\" else \"\"",
        "new": "    state = conn.status if proto == \"TCP\" else \"\"",
        "test": "test_psutil_rows_speak_the_same_words_as_the_native_ones",
    },
    {
        # One refusing table throws away the three that answered.
        "label": "portmap: one broken table sends the whole socket table to psutil",
        "file": "beantester/portmap.py",
        "old": "        if len(failed) < len(_ROW_CONVERTERS):",
        "new": "        if not failed:",
        "test": "test_an_empty_table_is_an_answer_and_an_error_code_is_not",
    },
    {
        # "Nobody may read it" becomes an empty table: a claim about the machine.
        "label": "portmap: a refused socket table reads as an empty one",
        "file": "beantester/portmap.py",
        "old": "        raise SocketTableUnavailable(\n            \"denied\",",
        "new": "        return []\n        raise SocketTableUnavailable(\n            \"denied\",",
        "test": "test_a_table_nobody_may_read_is_said_to_be_one",
    },
    {
        # The panel checks each answer against the box; without it a search typed
        # during a read is never run.
        "label": "sockets: a search typed during a read is never answered",
        "file": "beantester/gui/toolbox/sockets.py",
        "old": ("        if latest is not None and not self._answers_the_inputs(latest):\n"
                "            self._asked_again()"),
        "new": "        if False:\n            self._asked_again()",
        "test": "test_a_search_typed_during_a_read_is_answered_on_that_read",
    },
    {
        # The first tool is built with the window: a read there runs at every start.
        "label": "sockets: the table is read when the window opens",
        "file": "beantester/gui/toolbox/sockets.py",
        "old": "        self.poller = Poller(self.frame, self.job, self._on_outcome)",
        "new": ("        self.poller = Poller(self.frame, self.job, self._on_outcome)\n"
                "        self._read_if_never()"),
        "test": "test_the_socket_table_reads_when_first_looked_at_and_not_at_start_up",
    },
    {
        # A read that failed is asked again on every tick, forever.
        "label": "sockets: a failed first read is retried on every tick",
        "file": "beantester/gui/toolbox/sockets.py",
        "old": "        if READ not in self.job.last and not self.job.busy():",
        "new": "        if not self.job.value and not self.job.busy():",
        "test": "test_a_first_read_that_fails_is_not_an_empty_machine_and_is_not_retried_by_itself",
    },
    {
        # The PID shows under "process" and the name under "PID".
        "label": "sockets: a cell sits under another column's header",
        "file": "beantester/gui/toolbox/sockets.py",
        "old": "    return (s.proc, \"\" if s.pid is None else s.pid, s.proto,",
        "new": "    return (\"\" if s.pid is None else s.pid, s.proc, s.proto,",
        "test": "test_the_socket_table_reads_when_first_looked_at_and_not_at_start_up",
    },
    {
        # fe80::5%12 goes into dst_ip / block_ip: an interface, not an address.
        "label": "sockets: the IPv6 zone goes into the Control field",
        "file": "beantester/gui/toolbox/sockets.py",
        "old": "    return s.remote_ip.split(\"%\")[0]",
        "new": "    return s.remote_ip",
        "test": "test_the_row_menu_offers_what_the_row_can_do_and_fills_the_control_fields",
    },
    {
        # "Target this process" offered on a TIME_WAIT row, "Block" on a listener.
        "label": "sockets: the row menu offers what the row cannot do",
        "file": "beantester/gui/toolbox/sockets.py",
        "old": "set_menu_entry_available(self.menu, index, allowed)",
        "new": "set_menu_entry_available(self.menu, index, True)",
        "test": "test_the_row_menu_offers_what_the_row_can_do_and_fills_the_control_fields",
    },
    {
        # A free port has no program: "Target this process" offered for nobody.
        "label": "portcheck: the row menu offers a process for a free port",
        "file": "beantester/gui/toolbox/portcheck.py",
        "old": "set_menu_entry_available(self.menu, index, named)",
        "new": "set_menu_entry_available(self.menu, index, True)",
        "test": "test_the_port_check_row_menu_acts_on_the_program_that_holds_the_port",
    },
    {
        "label": "conns: the row menu offers to target a process it could not name",
        "file": "beantester/gui/pages/conns.py",
        "old": "self.TARGET_INDEX, bool(name and name != \"?\"))",
        "new": "self.TARGET_INDEX, True)",
        "test": "test_connection_menu_needs_a_row_to_act_on",
    },
    {
        # Back to Tk's own disabled state: blurred on Windows, and invisible to
        # the fake tkinter, which records options and never draws them.
        "label": "theme: an unavailable menu entry goes back to Tk's disabled state",
        "file": "beantester/gui/theme.py",
        "old": "menu.entryconfigure(index, **(MENU_ENTRY_LIVE if available else MENU_ENTRY_INERT))",
        "new": "menu.entryconfigure(index, state=\"normal\" if available else \"disabled\")",
        "test": "test_an_entry_a_row_cannot_use_is_coloured_inert_not_disabled",
    },
    {
        # The fourth table copies the pattern it finds: a call site greys out on its own.
        "label": "sockets: a row menu greys an entry out with Tk's state again",
        "file": "beantester/gui/toolbox/sockets.py",
        "old": "set_menu_entry_available(self.menu, index, allowed)",
        "new": "self.menu.entryconfigure(index, state=\"normal\" if allowed else \"disabled\")",
        "test": "test_no_menu_entry_is_greyed_out_with_tk_disabled_state",
    },
    {
        # Two identical sockets, one key: a click on one selects the other.
        "label": "sockets: two identical sockets share one key",
        "file": "beantester/nettools/sockets.py",
        "old": "        yield Socket(f\"{base}|{repeat}\",",
        "new": "        yield Socket(f\"{base}\",",
        "test": "test_two_identical_sockets_are_two_rows_with_two_keys",
    },
    {
        # A TIME_WAIT row is named "[System Process]", the snapshot's PID 0.
        "label": "sockets: a socket no process owns is named after PID 0",
        "file": "beantester/nettools/sockets.py",
        "old": "        name = names.get(row.pid, \"\") if row.pid else \"\"",
        "new": "        name = names.get(row.pid, \"\")",
        "test": "test_a_read_names_each_row_after_the_table_and_keeps_what_failed",
    },
    {
        # 127.0.0.1 before 93.184.216.34, and IPv6 among IPv4.
        "label": "sockets: addresses sort as text",
        "file": "beantester/nettools/sockets.py",
        "old": "        key = cache[text] = (address.version, int(address))",
        "new": "        key = cache[text] = (0, text)",
        "test": "test_a_column_sorts_by_value_with_empty_cells_last_both_ways",
    },
    {
        # An empty cell is sorted as the smallest value instead of no value.
        "label": "sockets: empty cells sort first",
        "file": "beantester/nettools/sockets.py",
        "old": "    return [s for _k, s in present] + [s for k, s in keyed if k is None]",
        "new": "    return [s for k, s in keyed if k is None] + [s for _k, s in present]",
        "test": "test_a_column_sorts_by_value_with_empty_cells_last_both_ways",
    },
    {
        # A search after a failed Refresh shows the old rows as if they were fresh.
        "label": "sockets: a search after a failed read drops the rows' age",
        "file": "beantester/gui/toolbox/sockets.py",
        "old": "stale=self._read_failed()",
        "new": "stale=False",
        "test": "test_a_read_that_fails_says_why_and_keeps_the_rows_it_had",
    },
    {
        # The reason is lost on the way: portmap's exception reaches the window as is.
        "label": "sockets: a refused table reaches the window without its reason",
        "file": "beantester/nettools/sockets.py",
        "old": "        raise Unreadable(UNREADABLE_KEYS.get(exc.reason, \"\"), str(exc)) from exc",
        "new": "        raise",
        "test": "test_a_table_nobody_may_read_becomes_a_reason_the_window_can_say",
    },
    {
        # The reason stays, the way out goes: "install it" with no command to type.
        "label": "sockets: a missing psutil no longer says how to get it",
        "file": "lang/en.json",
        "old": "Install it with pip install psutil, then start the program again.",
        "new": "Install it, then start the program again.",
        "test": "test_a_missing_psutil_says_how_to_get_it_in_every_language",
    },
    {
        # A failure the tool can name is shown as an English exception anyway.
        "label": "toolbox: a known failure is shown as program text",
        "file": "beantester/gui/toolbox/base.py",
        "old": ("            error = (T(outcome.error_key, **dict(outcome.error_args)) if outcome.error_key\n"
                "                     else outcome.error)"),
        "new": "            error = outcome.error",
        "test": "test_a_socket_table_the_system_refuses_is_said_in_the_windows_language",
    },
    {
        # The middle button opens the row menu on Windows and X11 again.
        "label": "tables: the row menu opens on a middle click",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "        self.tree.bind(\"<<ContextMenu>>\", self.row_menu_at_pointer)",
        "new": ("        self.tree.bind(\"<<ContextMenu>>\", self.row_menu_at_pointer)\n"
                "        self.tree.bind(\"<Button-2>\", self.row_menu_at_pointer)"),
        "test": "test_the_table_is_reachable_and_readable_without_a_mouse",
    },
    {
        # The right click binds nothing: the handler exists, the table never calls it.
        "label": "tables: the right click opens no menu",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "        self.tree.bind(\"<<ContextMenu>>\", self.row_menu_at_pointer)",
        "new": "        self.tree.bind(\"<<ContextMenu>>\", lambda _event: \"break\")",
        "test": "test_the_table_is_reachable_and_readable_without_a_mouse",
    },
    {
        # External review P1-4: the window holds a partial row and a buffer below
        # the rows on screen, so a bottom measured in slots hid the last rows.
        "label": "tables: the bottom is measured in slots again",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "        return max(0, len(self.items) - self._fits)",
        "new": "        return max(0, len(self.items) - self.window())",
        "test": "test_scrolling_moves_the_window_and_stays_in_range",
    },
    {
        "label": "tables: the scrollbar thumb is measured in slots again",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "        last = min(1.0, (self.offset + self._fits) / total)",
        "new": "        last = min(1.0, (self.offset + self.window()) / total)",
        "test": "test_scrolling_moves_the_window_and_stays_in_range",
    },
    {
        # The thumb dragged to the end asks for 1 - fits/total, a float a hair
        # under the last offset: truncating it stops one row short.
        "label": "tables: dragging the thumb to the end stops a row short",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "            self.set_offset(round(float(value) * total))",
        "new": "            self.set_offset(int(float(value) * total))",
        "test": "test_scrolling_moves_the_window_and_stays_in_range",
    },
    {
        # P2-18: Tk answers every selection the table writes with a QUEUED
        # <<TreeviewSelect>>, and rebuilding from it kept only the rows on screen.
        "label": "tables: the echo of our own selection wipes it again",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "        if chosen == self._written:",
        "new": "        if False:",
        "test": "test_selection_is_by_model_key_and_survives_sorting",
    },
    {
        # Without "break" ttk's class binding runs after ours and `see`s a slot,
        # which scrolls the widget's own view under the window.
        "label": "tables: a key lets ttk's own handler run after it",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "            self._choose(max(0, min(count - 1, target)), extend=extend)\n"
               "        return \"break\"",
        "new": "            self._choose(max(0, min(count - 1, target)), extend=extend)\n"
               "        return None",
        "test": "test_the_keyboard_moves_a_cursor_through_the_model",
    },
    {
        "label": "tables: PageDown skips the rows past the ones in full",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "                                 \"page_down\": self._fits}[step]",
        "new": "                                 \"page_down\": self.window()}[step]",
        "test": "test_the_keyboard_moves_a_cursor_through_the_model",
    },
    {
        "label": "tables: Shift ranges forget their anchor",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "        anchor = self._position_of(self._anchor) if self._multi and extend else None",
        "new": "        anchor = None",
        "test": "test_shift_selects_a_range_across_pages_and_scrolling_keeps_it",
    },
    {
        "label": "tables: a chosen row is left where it is, half cut off",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "        self._cursor = key\n        self._reveal(position)",
        "new": "        self._cursor = key",
        "test": "test_a_click_chooses_by_model_row_and_brings_the_half_row_into_view",
    },
    {
        "label": "tables: a click lets ttk's own press run after it",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "            self._restore_selection()\n        return \"break\"\n\n"
               "    def _on_extend_press",
        "new": "            self._restore_selection()\n        return None\n\n"
               "    def _on_extend_press",
        "test": "test_a_click_chooses_by_model_row_and_brings_the_half_row_into_view",
    },
    {
        # The count starts from the height as if nothing sat under the rows; the
        # border is found by asking Tk. Without the step back it is a row too many.
        "label": "tables: the border under the rows is counted as a row",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": ("    while rows > 1 and region_at(x, top + rows * row_height - 1) not in (\"cell\", \"tree\"):\n"
                "        rows -= 1\n"),
        "new": "",
        "test": "test_the_rows_in_full_are_asked_of_tks_own_layout",
    },
    {
        # Scrolled sideways, the first row's box starts left of the widget: asked
        # at its left edge, Tk finds no row anywhere and the count collapses to one.
        "label": "tables: the rows are asked about left of the widget",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "    x = (max(left, 0) + min(left + span, int(width))) // 2",
        "new": "    x = left + 1",
        "test": "test_the_rows_in_full_are_asked_of_tks_own_layout",
    },
    {
        # Columns narrower than the widget leave blank space right of them, and
        # the middle of the widget is then no row at all.
        "label": "tables: the rows are asked about right of the columns",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "    x = (max(left, 0) + min(left + span, int(width))) // 2",
        "new": "    x = int(width) // 2",
        "test": "test_the_rows_in_full_are_asked_of_tks_own_layout",
    },
    {
        # Tk 8.6.14 lays a treeview out when idle: without yview first, bbox and
        # identify inside <Configure> read the layout of the size before.
        "label": "tables: a resize is measured on the layout before it",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "            self.tree.yview()\n",
        "new": "",
        "test": "test_a_resize_is_measured_on_the_new_layout_not_the_old_one",
    },
    {
        # A set rebuilt from the selection on every repaint: a scroll paid for
        # every selected row (200 000 selected: 0.07 -> 9.9 ms per row scrolled).
        "label": "tables: every repaint copies the whole selection",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "        selected = self._selected\n",
        "new": "        selected = set(self._selected)\n",
        "test": "test_a_huge_selection_does_not_make_every_scroll_pay_for_it",
    },
    {
        # An emptied selection kept its anchor, and Shift ranged from a row that
        # had been cleared away.
        "label": "tables: select_keys([]) keeps the old anchor",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "        self._cursor = self._anchor = next(iter(self._selected), None)",
        "new": ("        if self._selected:\n"
                "            self._cursor = self._anchor = next(iter(self._selected))"),
        "test": "test_a_cleared_selection_leaves_no_anchor_behind",
    },
    {
        "label": "tables: a click on a blank slot keeps the old anchor",
        "file": "beantester/gui/widgets/sortable_tree.py",
        "old": "            self._selected = {}\n            self._cursor = self._anchor = None\n",
        "new": "            self._selected = {}\n",
        "test": "test_a_cleared_selection_leaves_no_anchor_behind",
    },
    {
        # The pixel half of the table tests lives in the render check under Xvfb;
        # dropping its pass from main would leave every fake-Tk test green.
        "label": "render: CI stops measuring the table viewport",
        "file": "tools/ci_gui_render.py",
        "old": "    rc = subprocess.run(\n"
               "        [sys.executable, os.path.abspath(__file__), \"--tables\"]).returncode\n"
               "    ok = (rc == 0) and ok\n",
        "new": "",
        "test": "test_the_render_check_measures_the_table_viewport_on_real_tk",
    },
    {
        # proc: on another table stops reading the PID: `proc:1234` finds nothing.
        "label": "search: another table's proc: judges the name alone",
        "file": "beantester/views.py",
        "old": "            tests.append(lambda c, m, x=matcher, g=getter: x.matches(*g(c, m)))",
        "new": "            tests.append(lambda c, m, x=matcher, g=getter: x.matches(None, g(c, m)[1]))",
        "test": "test_the_search_is_the_connection_tables_language_on_these_columns",
    },
    {
        # A dual-stack server on [::]: every bind succeeds beside it (measured), so a
        # verdict that asks the bind first calls a held port free.
        "label": "portcheck: a holder only a table can see counts for nothing",
        "file": "beantester/nettools/portcheck.py",
        "old": "    if owners:\n        return IN_USE",
        "new": "    if owners and code:\n        return IN_USE",
        "test": "test_a_holder_no_bind_can_see_still_holds_the_port",
    },
    {
        "label": "portcheck: TIME_WAIT is counted as a holder",
        "file": "beantester/nettools/portcheck.py",
        "old": "        if s.state == \"TIME_WAIT\":",
        "new": "        if False:",
        "test": "test_time_wait_holds_nothing_and_a_refusal_beside_it_is_closing",
    },
    {
        # Off Windows, EACCES is a port the account may not use, not a reservation.
        "label": "portcheck: access denied reads as a reservation everywhere",
        "file": "beantester/nettools/portcheck.py",
        "old": "        return RESERVED if WINDOWS else DENIED",
        "new": "        return RESERVED",
        "test": "test_access_denied_is_a_reservation_on_windows_only",
    },
    {
        "label": "portcheck: any number of ports is checked",
        "file": "beantester/nettools/portcheck.py",
        "old": "    if len(wanted) > MAX_PORTS:",
        "new": "    if False:",
        "test": "test_the_ports_an_expression_names",
    },
    {
        # bind(0) is "any free port" - checking it answers a question nobody asked.
        "label": "portcheck: port 0 is checked like a port",
        "file": "beantester/nettools/portcheck.py",
        "old": "    wanted = tuple(port for port in range(1, 65536) if matcher.matches(port))",
        "new": "    wanted = tuple(port for port in range(0, 65536) if matcher.matches(port))",
        "test": "test_the_ports_an_expression_names",
    },
    {
        # The wildcard address: still silent without a listen, but it is not what
        # the Tools tab's quiet exception says the probe does.
        "label": "portcheck: the probe binds every address instead of loopback",
        "file": "beantester/nettools/portcheck.py",
        "old": "_LOOPBACK = {4: (socket.AF_INET, \"127.0.0.1\"), 6: (socket.AF_INET6, \"::1\")}",
        "new": "_LOOPBACK = {4: (socket.AF_INET, \"0.0.0.0\"), 6: (socket.AF_INET6, \"::\")}",
        "test": "test_a_port_check_only_creates_and_binds_sockets_on_loopback",
    },
    {
        "label": "portcheck: a missing IP version is asked about port by port",
        "file": "beantester/nettools/portcheck.py",
        "old": "            if code in NO_FAMILY_CODES:\n                return None",
        "new": "            if code in NO_FAMILY_CODES:\n                continue",
        "test": "test_a_machine_without_an_ip_version_is_said_once_not_per_port",
    },
    {
        # The table read BEFORE the binds: a holder starting in between is missed
        # and its port called free.
        "label": "portcheck: the table is read before the system is asked",
        "file": "beantester/nettools/portcheck.py",
        "old": ("    codes, unavailable = {}, []\n"
                "    for family in families:\n"
                "        answers = _ask_family(bind, family, protocols, wanted)\n"
                "        if answers is None:\n"
                "            unavailable.append(family)\n"
                "        else:\n"
                "            codes.update(answers)\n"
                "    live, closing = _holders(read())\n"),
        "new": ("    live, closing = _holders(read())\n"
                "    codes, unavailable = {}, []\n"
                "    for family in families:\n"
                "        answers = _ask_family(bind, family, protocols, wanted)\n"
                "        if answers is None:\n"
                "            unavailable.append(family)\n"
                "        else:\n"
                "            codes.update(answers)\n"),
        "test": "test_the_system_is_asked_first_and_the_table_read_after",
    },
    {
        "label": "portcheck: the probe leaves its socket open",
        "file": "beantester/nettools/portcheck.py",
        "old": "    with sock:\n        try:",
        "new": "    if sock:\n        try:",
        "test": "test_the_probe_closes_every_socket_it_makes",
    },
    {
        # "1001 ports, 1000 at most" written into the crash log as a fault.
        "label": "toolbox: a refusal of the input is recorded as a fault",
        "file": "beantester/gui/toolbox/base.py",
        "old": "        if not isinstance(exc, Refused):",
        "new": "        if True:",
        "test": "test_too_many_ports_are_refused_with_their_numbers_in_the_windows_language",
    },
    {
        "label": "toolbox: a known failure loses its numbers on the worker",
        "file": "beantester/gui/toolbox/base.py",
        "old": "        error_args = tuple(sorted((getattr(exc, \"user_args\", None) or {}).items()))",
        "new": "        error_args = ()",
        "test": "test_too_many_ports_are_refused_with_their_numbers_in_the_windows_language",
    },
    {
        "label": "toolbox: a known failure is said without its numbers",
        "file": "beantester/gui/toolbox/base.py",
        "old": "            error = (T(outcome.error_key, **dict(outcome.error_args)) if outcome.error_key",
        "new": "            error = (T(outcome.error_key) if outcome.error_key",
        "test": "test_too_many_ports_are_refused_with_their_numbers_in_the_windows_language",
    },
    {
        # A second check queued behind a running one would land on stale inputs.
        "label": "portcheck panel: Check stays on while a check runs",
        "file": "beantester/gui/toolbox/portcheck.py",
        "old": "        return (not self.job.busy() and bool(self.ports.get().strip())",
        "new": "        return (bool(self.ports.get().strip())",
        "test": "test_one_check_at_a_time_and_a_rebuild_mid_check_gets_the_answer",
    },
    {
        "label": "portcheck panel: the parser's sentence is not shown",
        "file": "beantester/gui/toolbox/portcheck.py",
        "old": "            self.status.refused(str(exc))",
        "new": "            self.status.refused(\"\")",
        "test": "test_ports_the_parser_refuses_never_reach_the_worker",
    },
    {
        "label": "portcheck panel: a held port is not coloured",
        "file": "beantester/gui/toolbox/portcheck.py",
        "old": "ROW_TAGS = {portcheck.IN_USE: \"blocked\",",
        "new": "ROW_TAGS = {portcheck.IN_USE: \"\",",
        "test": "test_the_port_check_waits_to_be_asked_and_answers_per_protocol_and_ip_version",
    },
    {
        "label": "portcheck panel: the IP-version boxes are ignored",
        "file": "beantester/gui/toolbox/portcheck.py",
        "old": "        families = tuple(f for f, var in self.families.items() if var.get())",
        "new": "        families = tuple(self.families)",
        "test": "test_the_boxes_choose_what_is_checked_and_are_kept_across_a_rebuild",
    },
    {
        # Name and PID apart again: two holders of one port lose which PID is whose.
        "label": "portcheck panel: the holder loses its PID",
        "file": "beantester/gui/toolbox/portcheck.py",
        "old": "        return T(\"tools.portcheck.holder\", name=name, pid=pid)",
        "new": "        return name",
        "test": "test_the_port_check_waits_to_be_asked_and_answers_per_protocol_and_ip_version",
    },
    {
        # T() never raises on a missing argument: the whole line comes back raw.
        "label": "engine: the driver queue line stops passing the warning threshold",
        "file": "beantester/engine.py",
        "old": "kb=q[\"queue_size\"] // 1024, warn=f\"{driverwait.WARN_MS:g}\"))",
        "new": "kb=q[\"queue_size\"] // 1024))",
        "test": "test_the_start_line_about_the_driver_queue_is_filled_in_to_the_last_number",
    },
    {
        # Bytes printed as KB: 4194304 KB. The queue LENGTH is 4096 as well, so a
        # test that only looks for "4096" cannot see this.
        "label": "engine: the driver queue line prints the size in bytes",
        "file": "beantester/engine.py",
        "old": "kb=q[\"queue_size\"] // 1024,",
        "new": "kb=q[\"queue_size\"],",
        "test": "test_the_start_line_about_the_driver_queue_is_filled_in_to_the_last_number",
    },
    {
        # External review P1-3: the report's command was built from the settings
        # alone, so it lost --simulate (and never had the scenario).
        "label": "repro: the report's command forgets what only the engine knows",
        "file": "beantester/repro.py",
        "old": "        cli_command=session_command(engine, settings),",
        "new": "        cli_command=settings_to_cli_string(settings, seed=seed),",
        "test": "test_the_session_command_takes_the_scenario_and_the_stand_in_from_the_engine",
    },
    {
        "label": "repro: the command drops the scenario",
        "file": "beantester/repro.py",
        "old": "    if scenario:\n        args += [\"--scenario\", str(scenario)]\n",
        "new": "    if False:\n        args += [\"--scenario\", str(scenario)]\n",
        "test": "test_the_reproduction_command_parses_back_into_the_same_run",
    },
    {
        # P3-15: the field holds 1400.5, the flag is type=int - exit 2.
        "label": "repro: --max-size keeps its fraction and argparse refuses it",
        "file": "beantester/repro.py",
        "old": "        if key in WHOLE_NUMBER_FLAGS and math.isfinite(to_number(value)):",
        "new": "        if False:",
        "test": "test_the_reproduction_command_parses_back_into_the_same_run",
    },
    {
        # P3-14: the old trigger list, which had no ^ - cmd.exe eats a bare one.
        "label": "repro: a bare ^ is left for cmd.exe to eat",
        "file": "beantester/repro.py",
        "old": "    if arg and all(ch in _BARE for ch in arg):",
        "new": "    if not any(ch in arg for ch in ' ,!<>*?|&$()\"'):",
        "test": "test_the_command_survives_the_shell_it_is_pasted_into",
    },
    {
        # A quote written \" ends cmd's quoting, and a | after it becomes a pipe.
        "label": "repro: a quote in a pattern is escaped the way only argv reads",
        "file": "beantester/repro.py",
        "old": "    if \"re:\" in arg.lower():",
        "new": "    if False:",
        "test": "test_the_command_survives_the_shell_it_is_pasted_into",
    },
    {
        "label": "engine: a stand-in driver is not reported as one",
        "file": "beantester/engine.py",
        "old": "            self._simulated = not real_windivert",
        "new": "            self._simulated = False",
        "test": "test_the_session_command_takes_the_scenario_and_the_stand_in_from_the_engine",
    },
    {
        "label": "engine: the scenario a session ran is not recorded",
        "file": "beantester/engine.py",
        "old": "        self._scenario_file = getattr(scenario, \"source\", None)",
        "new": "        self._scenario_file = None",
        "test": "test_the_session_command_takes_the_scenario_and_the_stand_in_from_the_engine",
    },
    {
        "label": "engine: a new session keeps the last one's scenario",
        "file": "beantester/engine.py",
        "old": "            self._scenario_file, self._scenario_loop = None, False    # start_scenario sets\n",
        "new": "",
        "test": "test_the_session_command_takes_the_scenario_and_the_stand_in_from_the_engine",
    },
    {
        # Cleared before the handle opened: a start that then FAILED erased the
        # facts of the session whose seed and counters are still on screen.
        "label": "engine: a failed start erases the last session's scenario",
        "file": "beantester/engine.py",
        "old": "        self._divert = divert\n",
        "new": "        self._divert = divert\n        self._scenario_file = None\n",
        "test": "test_the_session_command_takes_the_scenario_and_the_stand_in_from_the_engine",
    },
    {
        # External review P2-15: the command came from the form, unapplied edits
        # and all.
        "label": "gui: Copy CLI reads the form again",
        "file": "beantester/gui/session_repro.py",
        "old": "        recorded = settings_of(app)\n        if recorded is None:",
        "new": "        recorded = None\n        if recorded is None:",
        "test": "test_the_repro_describes_the_session_the_engine_ran_not_the_form",
    },
    {
        "label": "gui: a START that failed is recorded as the session",
        "file": "beantester/gui/app.py",
        "old": "            dialogs.show_start_failure(self.root, err, self._is_admin)\n",
        "new": ("            session_repro.started(self, self._pending_start_settings)\n"
                "            dialogs.show_start_failure(self.root, err, self._is_admin)\n"),
        "test": "test_the_repro_describes_the_session_the_engine_ran_not_the_form",
    },
    {
        # Owner decision D-28: an Apply during a scenario is its new base, so it
        # is what repeats the session. Recorded only without a scenario - the
        # behaviour before the runner took a new base - it is dropped again.
        "label": "gui: an Apply during a running scenario is not recorded",
        "file": "beantester/gui/session_repro.py",
        "old": ("        apply_settings(engine, settings, app.log)\n"
                "    if engine.is_running():\n"
                "        _SESSIONS[app] = dict(settings)"),
        "new": ("        apply_settings(engine, settings, app.log)\n"
                "        if engine.is_running():\n"
                "            _SESSIONS[app] = dict(settings)"),
        "test": "test_apply_during_a_running_scenario_is_what_repeats_the_session",
    },
    {
        # The window says "running" until the stop worker finishes; the engine
        # has ended the session before that.
        "label": "gui: an Apply while STOP is under way rewrites the session",
        "file": "beantester/gui/session_repro.py",
        "old": "    if engine.is_running():\n        _SESSIONS[app] = dict(settings)",
        "new": "    if True:\n        _SESSIONS[app] = dict(settings)",
        "test": "test_an_apply_while_stop_is_under_way_does_not_rewrite_the_session",
    },
    {
        # Every install puts the exe on PATH: the copied command runs from any
        # folder, where the program-relative name found nothing (exit 4).
        "label": "scenario: a shipped name opens only from the program's folder",
        "file": "beantester/scenario.py",
        "old": "    found = path if os.path.exists(path) else (shipped_scenario(path) or path)",
        "new": "    found = path",
        "test": "test_the_names_a_repro_command_writes_open_from_any_folder",
    },
    {
        "label": "scenario: a shipped file wins over the working folder's",
        "file": "beantester/scenario.py",
        "old": "    found = path if os.path.exists(path) else (shipped_scenario(path) or path)",
        "new": "    found = shipped_scenario(path) or path",
        "test": "test_a_file_in_the_working_folder_still_wins",
    },
    {
        "label": "paths: any missing relative path opens a shipped scenario",
        "file": "beantester/paths.py",
        "old": "    if folders not in _SHIPPED_SCENARIO_FOLDERS:\n        return None",
        "new": "    if False:\n        return None",
        "test": "test_only_the_names_the_command_writes_fall_back",
    },
    {
        "label": "paths: the exe's _internal name is not read back",
        "file": "beantester/paths.py",
        "old": '_SHIPPED_SCENARIO_FOLDERS = (("scenarios",), ("_internal", "scenarios"))',
        "new": '_SHIPPED_SCENARIO_FOLDERS = (("scenarios",),)',
        "test": "test_the_command_path_and_its_reading_are_one_round_trip",
    },
    {
        # The dialog's absolute path carries the Windows account name into every
        # shared report (owner decision 2026-09-29).
        "label": "gui: a shipped scenario is named by the dialog's absolute path",
        "file": "beantester/gui/session_repro.py",
        "old": "        return os.path.relpath(here, home)",
        "new": "        return path",
        "test": "test_apply_during_a_running_scenario_is_what_repeats_the_session",
    },
    {
        "label": "crash: the report's command is the form's again",
        "file": "beantester/gui/crash.py",
        "old": "        state[\"repro_command\"] = session_command(app.engine, session)",
        "new": "        pass",
        "test": "test_a_gui_crash_report_repeats_the_session_not_the_form",
    },
    {
        # External review P1-2: bool("false") is True - "lan_mode": "false"
        # switched on the mode that cuts all public traffic.
        "label": "validators: a switch takes the truth of any value again",
        "file": "beantester/validators.py",
        "old": "    if isinstance(value, bool):\n        return value\n"
               "    if isinstance(value, (int, float)) and value in (0, 1):",
        "new": "    if not isinstance(value, (list, dict)):\n        return bool(value)\n"
               "    if isinstance(value, (int, float)) and value in (0, 1):",
        "test": "test_a_switch_in_a_file_is_true_or_false_and_nothing_else",
    },
    {
        # P2-4: "tcpp" reached the driver, "outbound" became a raw filter.
        "label": "validators: the traffic filter takes any text again",
        "file": "beantester/validators.py",
        "old": "    if text in choices:\n        return text",
        "new": "    if text is not None:\n        return text",
        "test": "test_the_filter_in_a_file_is_one_the_program_knows",
    },
    {
        # P2-5: 1.9 became 1 in silence.
        "label": "validators: a fractional seed is taken again",
        "file": "beantester/validators.py",
        "old": "        if not value.is_integer() or abs(value) > _EXACT_FLOAT_INT:",
        "new": "        if False:",
        "test": "test_a_seed_in_a_file_is_a_whole_number",
    },
    {
        # P2-5: 42 came back as 42.0, which the seed field refuses - START blocked.
        "label": "validators: a seed written 42.0 stays a float",
        "file": "beantester/validators.py",
        "old": "        return int(value)\n    if isinstance(value, int):",
        "new": "        return value\n    if isinstance(value, int):",
        "test": "test_a_file_seed_written_42_0_no_longer_blocks_start",
    },
    {
        "label": "settings: the form and scenario steps skip the type layer",
        "file": "beantester/settings.py",
        "old": "            s[f.key] = coerce_field(f, raw[f.key], lang, bounded=True)",
        "new": "            s[f.key] = raw[f.key]",
        "test": "test_a_switch_in_a_file_is_true_or_false_and_nothing_else",
    },
    {
        # NOWE-3-1: {"target": 1e400} became the process name "inf".
        "label": "settings: an infinite number becomes an expression's text again",
        "file": "beantester/settings.py",
        "old": "        if isinstance(value, float) and not math.isfinite(value):",
        "new": "        if False:",
        "test": "test_a_number_too_large_for_a_float_is_refused_not_a_crash",
    },
    {
        # P2-2: a time of 0 or less became a 10 ms step.
        "label": "schedule: any step time is taken again",
        "file": "beantester/settings.py",
        "old": "        if not (0 < dur <= F.SECONDS[1]\n",
        "new": "        if not (True\n",
        "test": "test_a_schedule_step_is_a_real_time_and_real_speeds",
    },
    {
        # P2-2: a negative speed meant NO limit, NaN crashed the run.
        "label": "schedule: any step speed is taken again",
        "file": "beantester/settings.py",
        "old": "                and all(F.RATE[0] <= rate <= F.RATE[1] for rate in (dn, up))):",
        "new": "                and True):",
        "test": "test_a_schedule_step_is_a_real_time_and_real_speeds",
    },
    {
        # P1-2: "loop": "false" looped, and a CI run without --duration never ended.
        "label": "scenario: loop takes the truth of any value again",
        "file": "beantester/scenario.py",
        "old": "            loop = parse_bool(data.get(\"loop\", False))",
        "new": "            loop = bool(data.get(\"loop\", False))",
        "test": "test_a_switch_in_a_file_is_true_or_false_and_nothing_else",
    },
    {
        # NOWE-3-5: a run that never began was reported as "finishing".
        "label": "cli: a failure before the session is called finishing the run",
        "file": "beantester/cli.py",
        "old": "        log.error(f\"unexpected failure outside the session: \"",
        "new": "        log.error(f\"unexpected failure while finishing the run: \"",
        "test": "test_a_failure_before_the_session_is_not_called_finishing_the_run",
    },
    {
        # External review P2-19: Tab to "No", Enter answered "Yes" - on closing
        # the window during a session and on unloading the driver.
        "label": "dialogs: Enter presses the default whatever has the focus",
        "file": "beantester/gui/dialogs.py",
        "old": "        (focused if focused in buttons else default).invoke()",
        "new": "        default.invoke()",
        "test": "test_enter_presses_the_button_the_keyboard_is_on",
    },
    {
        "label": "dialogs: the keypad Enter does nothing",
        "file": "beantester/gui/dialogs.py",
        "old": 'ENTER_KEYS = ("<Return>", "<KP_Enter>")',
        "new": 'ENTER_KEYS = ("<Return>",)',
        "test": "test_enter_presses_the_button_the_keyboard_is_on",
    },
    {
        "label": "dialogs: Enter on Cancel saves the typed name",
        "file": "beantester/gui/dialogs.py",
        "old": "    _enter_presses(win, [cancel, ok], ok)",
        "new": "    _enter_presses(win, [ok], ok)",
        "test": "test_enter_presses_the_button_the_keyboard_is_on",
    },
    {
        # Owner decision D-2: the keyboard starts on the default button.
        "label": "dialogs: a yes/no opens with the keyboard on no button",
        "file": "beantester/gui/dialogs.py",
        "old": "    _center(win, parent, focus=first)",
        "new": "    _center(win, parent)",
        "test": "test_a_dialog_opens_with_the_keyboard_on_its_default_button",
    },
    {
        "label": "dialogs: the help sheet opens with the keyboard on no button",
        "file": "beantester/gui/dialogs.py",
        "old": "    _center(win, parent, focus=ok)",
        "new": "    _center(win, parent)",
        "test": "test_a_dialog_opens_with_the_keyboard_on_its_default_button",
    },
    {
        "label": "dialogs: the warning paints a raw colour again",
        "file": "beantester/gui/dialogs.py",
        "old": "    return _message(parent, title, message, CAUTION,",
        "new": "    return _message(parent, title, message, \"#ffb454\",",
        "test": "test_no_gui_module_but_the_theme_names_a_colour",
    },
    {
        "label": "render check: main no longer runs the dialogs' keyboard pass",
        "file": "tools/ci_gui_render.py",
        "old": "        [sys.executable, os.path.abspath(__file__), \"--dialogs\"]).returncode",
        "new": "        [sys.executable, os.path.abspath(__file__), \"--lang\"]).returncode",
        "test": "test_the_render_check_presses_the_dialogs_keys_on_real_tk",
    },
    {
        # Review of #218: with Tab excused, the check passed on Escape alone.
        "label": "render check: a Tk that cannot deliver Tab passes the dialogs",
        "file": "tools/ci_gui_render.py",
        "old": 'DIALOG_OPTIONAL_KEYS = ("<KP_Enter>",)',
        "new": 'DIALOG_OPTIONAL_KEYS = ("<KP_Enter>", "<Tab>", "<Return>")',
        "test": "test_the_render_check_presses_the_dialogs_keys_on_real_tk",
    },
    {
        # External review P2-6: a BOM (Notepad) or UTF-16 (PowerShell 5.1 `>`)
        # file was refused, and profiles.json quarantined with every profile.
        "label": "jsonfile: user files are read as UTF-8 text again",
        "file": "beantester/jsonfile.py",
        "old": '    with open(path, "rb") as f:',
        "new": '    with open(path, encoding="utf-8") as f:',
        "test": "test_a_file_saved_by_notepad_or_powershell_loads_through_every_door",
    },
    {
        # External review P3-16: the first save after a failed quarantine wrote
        # over the file the quarantine was protecting.
        "label": "jsonfile: a save writes over a file it could not move aside",
        "file": "beantester/jsonfile.py",
        "old": "    if unread and os.path.isfile(path) and quarantine(path) is None:\n"
               "        return \"the file could not be read or moved aside, so it was not overwritten\"\n",
        "new": "",
        "test": "test_a_broken_file_that_cannot_be_moved_aside_is_never_saved_over",
    },
    {
        "label": "jsonfile: a file left in place is reported like a quarantined one",
        "file": "beantester/jsonfile.py",
        "old": "    if os.path.isfile(path):\n"
               "        return f\"{detail} (could not be moved aside, so it is left as it is)\"\n",
        "new": "",
        "test": "test_a_broken_file_that_cannot_be_moved_aside_is_never_saved_over",
    },
    {
        "label": "profiles: the store forgets its file could not be moved aside",
        "file": "beantester/gui/profiles.py",
        "old": "        error = write_json(self.path, self.profiles, unread=self._unread)",
        "new": "        error = write_json(self.path, self.profiles)",
        "test": "test_a_broken_file_that_cannot_be_moved_aside_is_never_saved_over",
    },
    {
        "label": "ui state: the store forgets its file could not be moved aside",
        "file": "beantester/gui/ui_state.py",
        "old": "        error = write_json(self.path, self.data, unread=self._unread)",
        "new": "        error = write_json(self.path, self.data)",
        "test": "test_a_broken_file_that_cannot_be_moved_aside_is_never_saved_over",
    },
    {
        # External review P3-28: `{"col": "kb"}` is a dict, and the app did not start.
        "label": "ui state: a dict value is checked as a dict and no further",
        "file": "beantester/gui/ui_state.py",
        "old": "        return all(k in value and isinstance(value[k], type(v)) for k, v in default.items())",
        "new": "        return True",
        "test": "test_a_sort_order_must_be_whole_and_the_extra_keys_stay",
    },
    {
        "label": "ui state: a dict value needs its keys but not their types",
        "file": "beantester/gui/ui_state.py",
        "old": "        return all(k in value and isinstance(value[k], type(v)) for k, v in default.items())",
        "new": "        return all(k in value for k in default)",
        "test": "test_a_sort_order_must_be_whole_and_the_extra_keys_stay",
    },
    {
        # The floor under the strictness: keys a newer version adds cost nothing.
        "label": "ui state: a sort order with an extra key is thrown away",
        "file": "beantester/gui/ui_state.py",
        "old": "        return all(k in value and isinstance(value[k], type(v)) for k, v in default.items())",
        "new": "        return value.keys() == default.keys() and all(\n"
               "            isinstance(value[k], type(v)) for k, v in default.items())",
        "test": "test_a_sort_order_must_be_whole_and_the_extra_keys_stay",
    },
    {
        # External review P1-7: the strip read the form through float(), so a
        # "2,5" the engine takes as 2.5% was described as a perfect link.
        "label": "summary: the strip reads typed numbers through float() again",
        "file": "beantester/summary.py",
        "old": "from .validators import number_or_zero",
        "new": "from .utils import to_number as number_or_zero",
        "test": "test_the_summary_reads_a_typed_number_the_way_the_engine_does",
    },
    {
        # The half a fix of the tests alone leaves behind: "2,5" is described,
        # as "0% loss".
        "label": "summary: the described value is read apart from the test for it",
        "file": "beantester/summary.py",
        "old": "    num = lambda k: number_string(number_or_zero(g(k)))",
        "new": "    num = lambda k: number_string(g(k))",
        "test": "test_the_summary_reads_a_typed_number_the_way_the_engine_does",
    },
    {
        "label": "form: text handed back to the form is formatted as a number again",
        "file": "beantester/gui/form.py",
        "old": "                var.set(value if isinstance(value, str) else number_string(value))",
        "new": "                var.set(number_string(value))",
        "test": "test_a_row_action_and_a_rebuild_keep_a_number_as_it_was_typed",
    },
    {
        # The other direction: a number from a file is still shown as a number,
        # "100" and not "100.0".
        "label": "form: a number from a file is shown as Python prints it",
        "file": "beantester/gui/form.py",
        "old": "                var.set(value if isinstance(value, str) else number_string(value))",
        "new": "                var.set(str(value))",
        "test": "test_a_row_action_and_a_rebuild_keep_a_number_as_it_was_typed",
    },
    {
        "label": "utils: number_string raises on infinity and NaN again",
        "file": "beantester/utils.py",
        "old": "    if not math.isfinite(f):\n        return str(f)\n",
        "new": "",
        "test": "test_a_number_that_cannot_be_written_as_digits_is_displayed_not_raised",
    },
    {
        # Owner decision D-3: the comma is a decimal separator, in ONE place.
        "label": "validators: the decimal comma is no longer read",
        "file": "beantester/validators.py",
        "old": "    text = str(\"\" if value is None else value).strip().replace(\",\", \".\")",
        "new": "    text = str(\"\" if value is None else value).strip()",
        "test": "test_number_or_zero_reads_what_parse_number_reads_and_zero_where_it_refuses",
    },
    {
        "label": "validators: infinity and NaN pass as numbers",
        "file": "beantester/validators.py",
        "old": "    return number if math.isfinite(number) else None",
        "new": "    return number",
        "test": "test_number_or_zero_reads_what_parse_number_reads_and_zero_where_it_refuses",
    },
    {
        # External review P1-6: `--format json` on a redirected Windows stdout
        # lost the whole record (0 bytes, exit 0) over one non-ASCII character.
        "label": "clilog: a JSON record carries non-ASCII text as it is",
        "file": "beantester/clilog.py",
        "old": "        _write(self._out, json.dumps(record, ensure_ascii=True)",
        "new": "        _write(self._out, json.dumps(record, ensure_ascii=False)",
        "test": "test_a_json_record_is_ascii_so_no_code_page_can_drop_it",
    },
    {
        # ...and a text line vanished the same way: with the branch that never
        # matches, the encoding error falls to the ValueError of a closed stream
        # and is swallowed - the old code exactly.
        "label": "clilog: a line the code page cannot hold is swallowed again",
        "file": "beantester/clilog.py",
        "old": "    except UnicodeEncodeError:",
        "new": "    except ZeroDivisionError:",
        "test": "test_a_line_the_code_page_cannot_hold_arrives_escaped_not_lost",
    },
    {
        # External review P2-3 / owner decision D-5: the loop wrapped before the
        # last step's settings and action were due, so they never ran.
        "label": "scenario runner: a loop wraps without playing its last step",
        "file": "beantester/scenario_runner.py",
        "old": "                self._play(scenario, prev_t, scenario.duration, last, log)\n",
        "new": "",
        "test": "test_a_loop_plays_its_last_step_before_it_starts_over",
    },
    {
        "label": "scenario runner: each cycle restarts from now and drifts",
        "file": "beantester/scenario_runner.py",
        "old": "                start += (t // scenario.duration) * scenario.duration",
        "new": "                start = self._clock()",
        "test": "test_a_loop_does_not_drift",
    },
    {
        # External review P2-1: every Apply and every scenario step restarted the
        # schedule's cycle.
        "label": "core: the same schedule applied again restarts its cycle",
        "file": "beantester/core.py",
        "old": "            if schedule != self.schedule:",
        "new": "            if True:",
        "test": "test_the_same_schedule_applied_again_keeps_its_cycle",
    },
    {
        # The other half: a changed schedule restarts the clock AND replaces the
        # steps. With the first one kept, only the step lengths tell them apart.
        "label": "core: a changed schedule restarts its cycle but keeps the old steps",
        "file": "beantester/core.py",
        "old": "                self.schedule = schedule\n",
        "new": "                self.schedule = self.schedule or schedule\n",
        "test": "test_the_same_schedule_applied_again_keeps_its_cycle",
    },
    {
        "label": "core: a reset still running carries into the next session",
        "file": "beantester/core.py",
        "old": "            self._reset_now_deadline = 0.0\n",
        "new": "",
        "test": "test_a_reset_still_running_does_not_carry_into_the_next_session",
    },
    {
        # External review NOWE-2-3 / owner decision D-26.
        "label": "scenario: a reset that lasts no time loads",
        "file": "beantester/scenario.py",
        "old": "        if duration <= 0:",
        "new": "        if duration < 0:",
        "test": "test_a_reset_that_lasts_no_time_or_an_hour_and_more_is_refused",
    },
    {
        "label": "scenario: a reset has no upper bound again",
        "file": "beantester/scenario.py",
        "old": "        duration = parse_number(value, bounds=(0, MAX_ACTION_S))",
        "new": "        duration = parse_number(value, bounds=(0, None))",
        "test": "test_a_reset_that_lasts_no_time_or_an_hour_and_more_is_refused",
    },
    {
        # External review P3-12: a step setting a START-only key loaded in silence.
        "label": "scenario: the keys a step cannot change are not looked for",
        "file": "beantester/scenario.py",
        "old": "        ignored = [k for k in settings if k in NOT_APPLIED_LIVE]",
        "new": "        ignored = []",
        "test": "test_a_step_setting_what_a_step_cannot_change_loads_and_says_so",
    },
    {
        # Owner decision D-30: the seed is START-only in the registry, which is
        # also what puts it among the keys a step cannot change.
        "label": "settings: the seed is taken for a setting a step can change",
        "file": "beantester/fields.py",
        "old": "hint=\"fields.seed_hint\", cli=\"seed\", start_only=True),",
        "new": "hint=\"fields.seed_hint\", cli=\"seed\"),",
        "test": "test_a_step_setting_what_a_step_cannot_change_loads_and_says_so",
    },
    {
        "label": "cli: the scenario's load warnings are not said",
        "file": "beantester/cli.py",
        "old": "    for warning in scen.warnings:\n        log.warn(warning)\n",
        "new": "",
        "test": "test_a_scenario_step_setting_what_it_cannot_change_is_said_by_the_dry_run_and_the_run",
    },
    {
        "label": "gui: the scenario's load warnings are not said",
        "file": "beantester/gui/session_repro.py",
        "old": "    for warning in scenario.warnings:\n        log(warning)\n",
        "new": "",
        "test": "test_loading_a_scenario_says_what_its_steps_cannot_change",
    },
    {
        # D-27: our own DNS scenario set the traffic filter in a step, where it
        # does nothing.
        "label": "shipped scenario: failing-dns sets the filter in a step again",
        "file": "scenarios/failing-dns.json",
        "old": "\"settings\": { \"dst_port\": \"53\",",
        "new": "\"settings\": { \"filter\": \"udp\", \"dst_port\": \"53\",",
        "test": "test_every_shipped_scenario_parses",
    },
    {
        # External review P2-17 / owner decision D-6: the step after an Apply put
        # the START settings back, and an unchanged step was re-applied over it.
        "label": "scenario runner: an Apply is undone at the next tick",
        "file": "beantester/scenario_runner.py",
        "old": "                if last is not None and not moved:",
        "new": "                if False:",
        "test": "test_an_apply_stands_until_the_timeline_moves_and_the_next_step_builds_on_it",
    },
    {
        "label": "scenario runner: the step after an Apply puts the START base back",
        "file": "beantester/scenario_runner.py",
        "old": "            self._base = dict(base)\n            return True",
        "new": "            return True",
        "test": "test_an_apply_stands_until_the_timeline_moves_and_the_next_step_builds_on_it",
    },
    {
        "label": "scenario runner: an Apply in the tick a step begins swallows the step",
        "file": "beantester/scenario_runner.py",
        "old": "                moved = scenario.settings_at(t, self._rebased_from) != last",
        "new": "                moved = False",
        "test": "test_an_apply_in_the_tick_a_step_begins_does_not_swallow_the_step",
    },
    {
        # A fresh lock each time excludes nobody: the step and the Apply race.
        "label": "scenario runner: a step is applied outside the lock an Apply takes",
        "file": "beantester/scenario_runner.py",
        "old": "        with self._lock:\n            s = scenario.settings_at(t, self._base)",
        "new": "        with threading.Lock():\n            s = scenario.settings_at(t, self._base)",
        "test": "test_an_apply_waits_for_a_step_being_applied",
    },
    {
        "label": "gui: Apply during a scenario goes around the runner",
        "file": "beantester/gui/session_repro.py",
        "old": "    if not engine.rebase_scenario(settings, app.log):",
        "new": "    if True:",
        "test": "test_the_step_after_an_apply_builds_on_what_apply_set",
    },
    {
        # Owner decisions D-6 and D-29: Load, Clear and Loop act at START only.
        "label": "gui: the scenario controls stay live during a session",
        "file": "beantester/gui/pages/control.py",
        "old": "        return loop, clear, load\n",
        "new": "",
        "test": "test_the_scenario_controls_lock_while_a_session_runs",
    },
    {
        # A key renamed in the code and not in lang/: every other i18n test stays
        # green, and the user reads the key instead of the sentence.
        "label": "i18n: a key the code names is missing from the language files",
        "file": "beantester/gui/app.py",
        "old": '        self.log(T("log.scenario_cleared"))',
        "new": '        self.log(T("log.scenario_was_cleared"))',
        "test": "test_every_key_the_code_names_is_in_the_language_files",
    },
    {
        # A whole namespace gone from the English file while the window titles
        # still name it. With the namespaces read from that same file, the scan
        # stopped looking for them and passed. The comma goes too, so the file
        # stays valid JSON and the scan is what fails.
        "label": "i18n: a namespace the code uses is gone from the language files",
        "file": "lang/en.json",
        "old": (',\n  "windows.about": "About Bean Network Tester",\n'
                '  "windows.event_log": "Event log",\n'
                '  "windows.settings": "Settings"\n'),
        "new": "\n",
        "test": "test_every_key_the_code_names_is_in_the_language_files",
    },
    {
        # External review P3-26: one window for both views mixed the targeted
        # bytes with all bytes after a switch (348 000 KB/s).
        "label": "rates: the two views share one peak window",
        "file": "beantester/gui/rates.py",
        "old": "        self._windows = {view: PeakWindow(window_s, warmup_s) for view in (False, True)}",
        "new": "        self._windows = dict.fromkeys((False, True), PeakWindow(window_s, warmup_s))",
        "test": "test_each_view_keeps_its_own_peak_and_they_never_mix",
    },
    {
        # Owner decision D-7: Apply does not send what a session takes at START.
        "label": "applied: Apply marks the form's start-only keys as applied",
        "file": "beantester/gui/applied.py",
        "old": "    kept = {k: v for k, v in (applied or ()) if k in START_ONLY_KEYS}",
        "new": "    kept = {}",
        "test": "test_after_apply_keeps_the_start_only_keys_start_gave",
    },
    {
        # External review P3-24: the fingerprint read when the start FINISHED.
        "label": "gui: the applied fingerprint is read when the start finishes",
        "file": "beantester/gui/app.py",
        "old": "        self.peaks.reset()\n",
        "new": ("        self._applied_sig = self._signature(self._raw_settings())\n"
                "        self.peaks.reset()\n"),
        "test": "test_an_edit_made_while_start_is_under_way_is_not_marked_applied",
    },
    {
        # External review P2-16a: the pick was never the filter a rebuild restored.
        "label": "form: picking a filter leaves the remembered one behind",
        "file": "beantester/gui/form.py",
        "old": "        self.app.set_filter_cli_key(self.app._filter_cli_key())\n",
        "new": "",
        "test": "test_a_column_switch_keeps_the_filter_the_lock_and_the_labels",
    },
    {
        # External review P2-16b, d: the column switch rebuilt the App's widgets
        # and left them as new - unlocked, "no scenario", Delete live.
        "label": "control page: a column switch leaves the App's widgets as new",
        "file": "beantester/gui/pages/control.py",
        "old": ("        app = self.app\n        app._sync_profile_widgets()\n"
                "        app._update_scenario_label()\n        app._sync_running_ui()\n"),
        "new": "",
        "test": "test_a_column_switch_keeps_the_filter_the_lock_and_the_labels",
    },
    {
        # External review P3-32: closed AFTER the reset, the open windows wrote
        # back the geometry it had just cleared.
        "label": "gui: Reset layout closes the windows after forgetting them",
        "file": "beantester/gui/app.py",
        "old": ("        self.windows.close_all()\n"
                "        for key in (\"geometry\", \"page\", \"stats_page\", \"tools_page\", \"collapsed\",\n"
                "                    \"log_height\", \"conn_sort\", \"event_sort\"):\n"
                "            self.ui.set(key, UI_DEFAULTS[key])\n"
                "        for wid in list(self.ui.data):\n"
                "            if wid.startswith(\"window.\"):        # secondary-window geometries\n"
                "                self.ui.set(wid, \"\")\n"),
        "new": ("        for key in (\"geometry\", \"page\", \"stats_page\", \"tools_page\", \"collapsed\",\n"
                "                    \"log_height\", \"conn_sort\", \"event_sort\"):\n"
                "            self.ui.set(key, UI_DEFAULTS[key])\n"
                "        for wid in list(self.ui.data):\n"
                "            if wid.startswith(\"window.\"):        # secondary-window geometries\n"
                "                self.ui.set(wid, \"\")\n"
                "        self.windows.close_all()\n"),
        "test": "test_reset_layout_forgets_open_windows_and_live_sorts_and_keeps_the_filter",
    },
    {
        # External review NOWE-1-1: the tables are rebuilt from the live sorts.
        "label": "gui: Reset layout keeps the live table sorts",
        "file": "beantester/gui/app.py",
        "old": ("        self.conn_sort, self.event_sort = dict(UI_DEFAULTS[\"conn_sort\"]), "
                "dict(UI_DEFAULTS[\"event_sort\"])\n"),
        "new": "",
        "test": "test_reset_layout_forgets_open_windows_and_live_sorts_and_keeps_the_filter",
    },
    {
        # External review P2-14: a START still resolving its target when the
        # window closes goes on to open the driver after the window is gone.
        "label": "gui: a start still resolving when the window closes opens the driver",
        "file": "beantester/gui/app.py",
        "old": ("            self.engine.start(filt, duration=duration, "
                "narrow=bool(s.get(\"narrow_filter\")),\n"
                "                              admit=lambda: not self._closing)"),
        "new": ("            self.engine.start(filt, duration=duration, "
                "narrow=bool(s.get(\"narrow_filter\")))"),
        "test": "test_closing_the_window_while_start_resolves_opens_no_driver_afterwards",
    },
    {
        # External review P2-14: the driver release runs before the stop, while a
        # start is still loading the driver, so it finds nothing to unload.
        "label": "gui: closing unloads the driver before stopping a start loading it",
        "file": "beantester/gui/app.py",
        "old": ("            self.engine.stop()\n"
                "            self.running = False\n"),
        "new": ("            driver.release_on_exit(lambda line: "
                "self.log(f\"{T('log.driver')}: {line}\"))\n"
                "            self.engine.stop()\n"
                "            self.running = False\n"),
        "test": "test_closing_the_window_waits_for_a_start_already_opening_the_driver",
    },
    {
        # CodeRabbit on PR #230: "still wanted?" asked BEFORE the stop lock - a
        # close landing between the answer and the start stops nothing and
        # releases nothing, and the start then loads a driver nobody unloads.
        "label": "engine: a start's admit is asked before the stop lock, not under it",
        "file": "beantester/engine.py",
        "old": ("        with self._stop_lock:\n"
                "            if admit is not None and not admit():\n"
                "                return False\n"),
        "new": ("        if admit is not None and not admit():\n"
                "            return False\n"
                "        with self._stop_lock:\n"),
        "test": "test_a_window_that_closes_right_after_admit_stops_after_the_start",
    },
    {
        # The start ignores admit's "no" and opens the driver anyway.
        "label": "engine: a start that admit turned down opens anyway",
        "file": "beantester/engine.py",
        "old": ("            if admit is not None and not admit():\n"
                "                return False\n"),
        "new": "",
        "test": "test_a_start_asks_admit_under_the_lock_its_stop_takes",
    },
    {
        # External review P3-30: the scenario's failure escapes _finish_start and
        # leaves a running session behind a START button.
        "label": "gui: a scenario that cannot start leaves the session running",
        "file": "beantester/gui/app.py",
        "old": "            self.engine.worker_failed(e)\n",
        "new": "            raise\n",
        "test": "test_a_scenario_that_cannot_start_ends_the_session",
    },
    {
        # CodeRabbit on PR #230: the crash record (a file write, a context
        # request) stands between the failed scenario and the stop that gives
        # the network back.
        "label": "gui: a failed scenario is recorded before its session is stopped",
        "file": "beantester/gui/app.py",
        "old": ("            self.engine.worker_failed(e)\n"
                "            crashlog.note(e, \"gui.app\")\n"),
        "new": ("            crashlog.note(e, \"gui.app\")\n"
                "            self.engine.worker_failed(e)\n"),
        "test": "test_a_scenario_that_cannot_start_ends_the_session",
    },
    {
        # The start-failed dialog moved to dialogs: a missing pydivert is an
        # install, and gets its own dialog.
        "label": "dialogs: a missing pydivert gets the generic start-failed dialog",
        "file": "beantester/gui/dialogs.py",
        "old": ("    if isinstance(err, ImportError):\n"
                "        return show_error(parent, T(\"dialogs.missing_library\"), "
                "T(\"dialogs.install_pydivert\"))\n"),
        "new": "",
        "test": "test_a_start_that_fails_shows_the_dialog_that_fits_the_failure",
    },
    {
        # External review P2-12: the capture thread reads the engine's flag and
        # handle live again, so one that outlived its join is revived by the next
        # START and reads the new session's traffic.
        "label": "engine: the capture thread reads the engine's live state again",
        "file": "beantester/engine.py",
        "old": ("        divert = session.divert         # this session's handle, never the next one's\n"
                "        while session.live:\n"
                "            # Three stores per packet and not one allocation: `True`/`False` are\n"
                "            # singletons and `now` below is a float this loop already reads. That\n"
                "            # matters because this is the hot path - see the module's \"What this\n"
                "            # actually sustains\" section.\n"
                "            self._cap_waiting = True\n"
                "            try:\n"
                "                packet = divert.recv()"),
        "new": ("        while self._running:\n"
                "            self._cap_waiting = True\n"
                "            try:\n"
                "                packet = self._divert.recv()"),
        "test": "test_a_capture_thread_that_outlives_its_session_never_reads_the_next_one",
    },
    {
        # P2-12: the same for the injector - one hung in send() past its join
        # comes back into the next session's queue.
        "label": "engine: the inject thread loops on the engine's flag again",
        "file": "beantester/engine.py",
        "old": ("        while session.live:\n"
                "            with self._cv:\n"
                "                while session.live and not self._heap:\n"
                "                    self._cv.wait()\n"
                "                if not session.live:\n"
                "                    break"),
        "new": ("        while self._running:\n"
                "            with self._cv:\n"
                "                while self._running and not self._heap:\n"
                "                    self._cv.wait()\n"
                "                if not self._running:\n"
                "                    break"),
        "test": "test_an_inject_thread_that_outlives_its_session_ends_with_it",
    },
    {
        # P2-12: a finished session's watchdog records its fault on the next one.
        "label": "engine: a fault from a finished session is recorded again",
        "file": "beantester/engine.py",
        "old": ("        if session is not None and session is not self._session:\n"
                "            return\n"
                "        if not self._running:\n"
                "            self._say(lead)"),
        "new": ("        if not self._running:\n"
                "            self._say(lead)"),
        "test": "test_a_watchdog_that_outlives_its_session_never_faults_the_next_one",
    },
    {
        # P2-12: a finished session's worker, bowing out of a stop it finds taken,
        # says its lines into the running session's log.
        "label": "engine: a finished session's worker speaks when it bows out",
        "file": "beantester/engine.py",
        "old": ("        if session is not None and session is not self._session:\n"
                "            return                      # a worker of a session that is over: _Session\n"),
        "new": "",
        "test": "test_a_stop_or_a_fault_from_a_finished_session_leaves_the_running_one_alone",
    },
    {
        # P2-12: the check under the lock - a worker that waited for it across a
        # STOP and a START stops the new session.
        "label": "engine: a finished session's worker can stop the running one",
        "file": "beantester/engine.py",
        "old": ("        if session is not None and session is not self._session:\n"
                "            return\n"
                "        if not self._running:\n"
                "            self._say(say)"),
        "new": ("        if not self._running:\n"
                "            self._say(say)"),
        "test": "test_a_stop_or_a_fault_from_a_finished_session_leaves_the_running_one_alone",
    },
    {
        # P2-12: the resolver's shared stop signal, which start() cleared - any
        # thread keeps looping while the resolver owns SOME thread.
        "label": "target_resolver: a thread that outlived its stop is revived by start()",
        "file": "beantester/target_resolver.py",
        "old": "        while self._thread is me:",
        "new": "        while self._thread is not None:",
        "test": "test_a_thread_that_outlived_its_stop_is_not_revived_by_the_next_start",
    },
    {
        # P2-12: the runner's flag alone, which start() clears for the new thread.
        "label": "scenario_runner: the live timeline is the flag, not the thread",
        "file": "beantester/scenario_runner.py",
        "old": "        return not self._stop and self._thread is threading.current_thread()",
        "new": "        return not self._stop",
        "test": "test_a_thread_still_in_a_step_when_started_again_is_not_the_timeline_any_more",
    },
    {
        # P2-12: a step that fails after STOP is reported as a dead worker of
        # whatever session runs now.
        "label": "scenario_runner: a stopped timeline's failure stops the session again",
        "file": "beantester/scenario_runner.py",
        "old": ("                if not self._owns():\n"
                "                    # A step that failed after STOP: whatever session is running\n"
                "                    # now is not this timeline's, and must not be stopped for it.\n"
                "                    return\n"),
        "new": "",
        "test": "test_a_thread_still_in_a_step_when_started_again_is_not_the_timeline_any_more",
    },
    {
        # P2-12: a step that outlasted STOP logs its SCENARIO event in the next
        # session.
        "label": "scenario_runner: a step applied after STOP is still recorded",
        "file": "beantester/scenario_runner.py",
        "old": ("                if not self._owns():\n"
                "                    return last         # stopped while it applied: nothing more of it\n"),
        "new": "",
        "test": "test_a_scenario_step_still_resolving_at_stop_never_reaches_the_next_session",
    },
    {
        # P2-12: the step no longer tells apply_settings when it stopped being
        # the timeline, so the old target lands in the next session.
        "label": "scenario_runner: a step's target is installed after STOP again",
        "file": "beantester/scenario_runner.py",
        "old": "                apply_settings(eng, s, log, live=self._owns)",
        "new": "                apply_settings(eng, s, log)",
        "test": "test_a_scenario_step_still_resolving_at_stop_never_reaches_the_next_session",
    },
    {
        # P2-12: the question is asked but nothing waits for the answer.
        "label": "settings: a target resolved after its session ended is installed",
        "file": "beantester/settings.py",
        "old": ("            targeting.refresh()\n"
                "    if live is not None and not live():\n"
                "        return None\n"),
        "new": "            targeting.refresh()\n",
        "test": "test_a_scenario_step_still_resolving_at_stop_never_reaches_the_next_session",
    },
    {
        # P2-12, after review: a step that lost its session before its target was
        # even looked up still publishes it through target_for - or, with no
        # target, switches the running session's target off.
        "label": "settings: a stale step still reaches the target",
        "file": "beantester/settings.py",
        "old": ("    if live is not None and not live():\n"
                "        return None\n"
                "    matcher = target if hasattr(target, \"matches\") else None"),
        "new": "    matcher = target if hasattr(target, \"matches\") else None",
        "test": "test_an_apply_that_is_no_longer_live_changes_nothing",
    },
    {
        # P2-12, after review: a stale step's impairment values land in the
        # session that runs now.
        "label": "settings: a stale step still applies its values",
        "file": "beantester/settings.py",
        "old": ("    if live is not None and not live():\n"
                "        return\n"
                "    with _batch(engine):"),
        "new": "    with _batch(engine):",
        "test": "test_an_apply_that_is_no_longer_live_changes_nothing",
    },
    {
        # P3-9: the injector never says it is on a packet, so a hung send()
        # leaves the session running with nothing delivered.
        "label": "engine: the inject thread's busy marker is never set",
        "file": "beantester/engine.py",
        "old": ("                heapq.heappop(self._heap)\n"
                "                # Busy from HERE, not from the wait above: a packet waiting out its\n"
                "                # delay is the job, and seconds of it are normal. Until the line\n"
                "                # after the except, so a warning held by the log counts as well.\n"
                "                session.busy = now\n"),
        "new": "                heapq.heappop(self._heap)\n",
        "test": "test_an_inject_thread_that_is_alive_but_no_longer_moving_fails_open",
    },
    {
        # P3-9: the marker outlives its packet - a quiet link after one packet
        # reads as a stalled injector and stops a healthy session.
        "label": "engine: the inject thread's busy marker is never cleared",
        "file": "beantester/engine.py",
        "old": ("                    self._warn_send_failed(e)\n"
                "            session.busy = None"),
        "new": "                    self._warn_send_failed(e)",
        "test": "test_a_packet_waiting_out_its_delay_is_not_a_stalled_injector",
    },
    {
        # P3-9: waiting out a packet's delay counts as being stuck on it.
        "label": "engine: a packet waiting out its delay counts as a busy injector",
        "file": "beantester/engine.py",
        "old": ("                now = time.monotonic()\n"
                "                if release > now:"),
        "new": ("                now = session.busy = time.monotonic()\n"
                "                if release > now:"),
        "test": "test_a_packet_waiting_out_its_delay_is_not_a_stalled_injector",
    },
    {
        # P3-9: the marker is kept, and nobody reads it.
        "label": "engine: the watchdog stops noticing an inject thread that stalled",
        "file": "beantester/engine.py",
        "old": "            if busy is not None and time.monotonic() - busy > self.CAPTURE_STALL_S:",
        "new": "            if False:",
        "test": "test_an_inject_thread_that_is_alive_but_no_longer_moving_fails_open",
    },
    {
        # NOWE-5a-2: each stuck worker gets a whole join of its own again.
        "label": "engine: STOP gives each stuck worker its own join timeout",
        "file": "beantester/engine.py",
        "old": "            t.join(timeout=max(0.0, deadline - time.monotonic()))",
        "new": "            t.join(timeout=self.JOIN_S)",
        "test": "test_stop_gives_its_stuck_workers_one_budget_between_them",
    },
    {
        # D-32: the watchdog is left to sleep out its tick, and STOP's join waits
        # for it.
        "label": "engine: STOP no longer wakes the watchdog",
        "file": "beantester/engine.py",
        "old": "        self._session.woken.set()\n",
        "new": "",
        "test": "test_an_ordinary_stop_does_not_wait_for_the_watchdog_tick",
    },
    {
        # D-33: the stuck worker is known, and START keeps quiet about it.
        "label": "engine: START no longer says the previous session is still stuck",
        "file": "beantester/engine.py",
        "old": ("        if stuck:\n"
                "            self.log(T(\"log.previous_session_stuck\"))\n"),
        "new": "",
        "test": "test_a_start_says_when_part_of_the_previous_session_is_still_stuck",
    },
    {
        # D-33: STOP no longer records the workers it gave up on.
        "label": "engine: STOP forgets the workers it could not join",
        "file": "beantester/engine.py",
        "old": "        self._session.stuck += tuple(t for t in workers if t.is_alive())\n",
        "new": "",
        "test": "test_a_start_says_when_part_of_the_previous_session_is_still_stuck",
    },
    {
        # D-33: only the session right before is asked, so a worker stuck two
        # sessions ago is forgotten after one clean session.
        "label": "engine: a stuck worker is not carried into the next session",
        "file": "beantester/engine.py",
        "old": "        session = self._session = _Session(divert, stuck)",
        "new": "        session = self._session = _Session(divert)",
        "test": "test_a_start_says_when_part_of_the_previous_session_is_still_stuck",
    },
    {
        # D-33: a worker that has since ended is still reported at every START.
        "label": "engine: a stuck worker that has ended is still reported",
        "file": "beantester/engine.py",
        "old": "        stuck = tuple(t for t in previous.stuck if t.is_alive()) if previous else ()",
        "new": "        stuck = tuple(previous.stuck) if previous else ()",
        "test": "test_a_start_says_when_part_of_the_previous_session_is_still_stuck",
    },
    # -- the driver-wait measurement, carved out of engine.py (driverwait.py) ----- #
    {
        # A later, healthier packet erases the worst moment.
        "label": "driverwait: a healthier sample lowers the recorded peak",
        "file": "beantester/driverwait.py",
        "old": ("        if waited_ms > self.peak_ms:\n"
                "            self.peak_ms = round(waited_ms, 3)\n"),
        "new": "        self.peak_ms = round(waited_ms, 3)\n",
        "test": "test_a_shorter_wait_never_lowers_the_recorded_peak",
    },
    {
        # One line per sample: the log fills with the same complaint.
        "label": "driverwait: the warning is said on every sample",
        "file": "beantester/driverwait.py",
        "old": ("        if now - self._warned < WARN_S:\n"
                "            return\n"),
        "new": "",
        "test": "test_a_long_driver_wait_warns_once_not_per_packet",
    },
    {
        # A test's QPC frequency overwritten by the machine's: on Windows a known
        # 200 ms wait reads 20 ms, on Linux there is no frequency at all.
        "label": "driverwait: a session start overwrites a supplied QPC frequency",
        "file": "beantester/driverwait.py",
        "old": ("        if self.freq is None:\n"
                "            self.freq = winenv.qpc_frequency()\n"),
        "new": "        self.freq = winenv.qpc_frequency()\n",
        "test": "test_the_capture_loop_actually_takes_the_sample",
    },
    {
        # The measurement exists and the packet path never reaches it.
        "label": "engine: the capture loop never samples the driver wait",
        "file": "beantester/engine.py",
        "old": "                wait.sample(packet, now)\n",
        "new": "                pass\n",
        "test": "test_the_capture_loop_actually_takes_the_sample",
    },
    {
        # The peak is measured and never reaches the stats, the CSV or the report.
        "label": "engine: the stats leave out the driver-wait peak",
        "file": "beantester/engine.py",
        "old": "        s[\"driver_wait_peak_ms\"] = self._driver_wait.peak_ms\n",
        "new": "",
        "test": "test_the_wait_inside_the_driver_is_measured_and_kept",
    },
    {
        # The first session's worst moment handed to every later one.
        "label": "engine: a stats reset keeps the driver-wait peak",
        "file": "beantester/engine.py",
        "old": "        self._driver_wait.reset()\n",
        "new": "",
        "test": "test_a_stats_reset_starts_a_new_driver_wait_window",
    },
    # -- the start order (external review P1-5) ------------------------------------ #
    {
        # The socket watcher and the target resolve back in the gap between the
        # open and the capture thread, holding every matching packet.
        "label": "engine: the slow start work runs after the handle opens again",
        "file": "beantester/engine.py",
        "old": ("            socket_error = self._start_socketwatch(real_windivert, socket_source)\n"
                "            self._bind_targeting()\n"
                "            if hasattr(self._divert, \"open\"):\n"
                "                self._open_with_retry(self._divert.open)\n"),
        "new": ("            if hasattr(self._divert, \"open\"):\n"
                "                self._open_with_retry(self._divert.open)\n"
                "            socket_error = self._start_socketwatch(real_windivert, socket_source)\n"
                "            self._bind_targeting()\n"),
        "test": "test_the_slow_part_of_a_start_runs_before_the_handle_opens",
    },
    {
        # The NETWORK handle refuses and the socket watcher opened before it sniffs on.
        "label": "engine: a handle that will not open leaves the socket watcher running",
        "file": "beantester/engine.py",
        "old": ("            self._divert = None\n"
                "            self._stop_socketwatch()\n"
                "            raise\n"),
        "new": ("            self._divert = None\n"
                "            raise\n"),
        "test": "test_a_handle_that_will_not_open_leaves_no_socket_watcher_behind",
    },
    {
        # D-35: the SOCKET half of a start that fails anyway is a crash record.
        "label": "engine: a socket handle failure is recorded before the start opens",
        "file": "beantester/engine.py",
        "old": ("            self._socketwatch = None\n"
                "            return exc\n"),
        "new": ("            self._socketwatch = None\n"
                "            crashlog.note(exc, \"engine.socketwatch.start\")\n"
                "            return None\n"),
        "test": "test_a_socket_handle_failure_is_recorded_only_for_a_start_that_opened",
    },
    {
        # D-35: a SOCKET handle that failed alone is no longer recorded at all.
        "label": "engine: a socket handle that failed alone is not recorded",
        "file": "beantester/engine.py",
        "old": "                crashlog.note(socket_error, \"engine.socketwatch.start\")\n",
        "new": "                pass\n",
        "test": "test_a_socket_handle_failure_is_recorded_only_for_a_start_that_opened",
    },
    {
        # P1-5 after review: the SOCKET record written again before the capture
        # thread reads - a file write and the GUI's context while nothing drains.
        "label": "engine: a socket handle failure is recorded before the capture reads",
        "file": "beantester/engine.py",
        "old": ("            self._driver_wait.begin()\n"
                "            self._t_cap.start()\n"
                "            self._t_inj.start()\n"
                "            if socket_error is not None:\n"),
        "new": ("            if socket_error is not None:\n"
                "                crashlog.note(socket_error, \"engine.socketwatch.start\")\n"
                "            self._driver_wait.begin()\n"
                "            self._t_cap.start()\n"
                "            self._t_inj.start()\n"
                "            if False:\n"),
        "test": "test_a_socket_handle_failure_is_recorded_only_for_a_start_that_opened",
    },
    {
        # A watcher whose thread would not start is dropped with its handle open.
        "label": "engine: a socket watcher that cannot start keeps its handle open",
        "file": "beantester/engine.py",
        "old": ("            watcher.stop()\n"
                "            self._socketwatch = None\n"
                "            return exc\n"),
        "new": ("            self._socketwatch = None\n"
                "            return exc\n"),
        "test": "test_a_socket_watcher_that_cannot_start_its_thread_closes_its_handle",
    },
    {
        # The SOCKET handle, now first, meets an unloading driver without waiting.
        "label": "engine: the socket handle does not wait for an unloading driver",
        "file": "beantester/engine.py",
        "old": "            self._open_with_retry(watcher.start)\n",
        "new": "            watcher.start()\n",
        "test": "test_a_socket_handle_waits_for_an_unloading_driver_too",
    },
    {
        # A step between the open and the try again: its exception escapes with
        # the session "running" and the handle open.
        "label": "engine: a step right after the open escapes the try that stops a start",
        "file": "beantester/engine.py",
        "old": "        session = self._session = _Session(divert, stuck)\n",
        "new": ("        session = self._session = _Session(divert, stuck)\n"
                "        self._fine_timers = winenv.request_fine_timers()\n"),
        "test": "test_a_failure_right_after_the_handle_opens_still_closes_it",
    },
    {
        # The start line said again before the capture thread exists: a log that
        # blocks on it holds all the filtered traffic.
        "label": "engine: the start line is said before the capture thread reads",
        "file": "beantester/engine.py",
        "old": ("            self._driver_wait.begin()\n"
                "            self._t_cap.start()\n"),
        "new": ("            self.log(f\"{T('log.start_filter')}: {filt}  "
                "(seed={self._effective_seed})\")\n"
                "            self._driver_wait.begin()\n"
                "            self._t_cap.start()\n"),
        "test": "test_a_start_line_held_by_the_log_does_not_hold_the_traffic",
    },
    {
        # The packet queued while the start still resolved its target is sampled,
        # and the start's wait becomes the peak and a false warning.
        "label": "driverwait: the start's own wait counts as a driver wait",
        "file": "beantester/driverwait.py",
        "old": "        if not stamp or not freq or stamp < self.floor:\n",
        "new": "        if not stamp or not freq:\n",
        "test": "test_a_packet_queued_before_the_capture_thread_started_is_not_a_driver_wait",
    },
    {
        # P2-10(a): the owner of a late port the walk never saw is dropped unjudged,
        # and its connection waits for the next rebuild.
        "label": "targeting: a pid the walk never saw is dropped unjudged",
        "file": "beantester/targeting.py",
        "old": ("                unseen = frozenset(owner for owner in self._late_owners.values()\n"
                "                                   if owner not in seen)\n"),
        "new": "                unseen = frozenset()\n",
        "test": "test_a_target_with_no_socket_at_the_walk_is_judged_again_when_it_opens_one",
    },
    {
        # P2-10(a): a late owner the walk saw and ruled out is queued to be judged again.
        "label": "targeting: a pid the walk ruled out is queued again",
        "file": "beantester/targeting.py",
        "old": "                                   if owner not in seen)\n",
        "new": "                                   if owner not in pids)\n",
        "test": "test_a_target_with_no_socket_at_the_walk_is_judged_again_when_it_opens_one",
    },
    {
        # P2-10(a): what the walk queued waits for a bell that some packet rings.
        "label": "targeting: the resolver is not rung for what the walk queued",
        "file": "beantester/targeting.py",
        "old": ("            if pending and wake is not None:\n"
                "                wake()\n"),
        "new": "",
        "test": "test_a_target_with_no_socket_at_the_walk_is_judged_again_when_it_opens_one",
    },
    {
        # P2-10(b): the walk empties the whole queue, judged or not.
        "label": "targeting: the walk empties a queue it did not judge",
        "file": "beantester/targeting.py",
        "old": "                pending = (self._pending_pids - seen) | unseen\n",
        "new": "                pending = unseen\n",
        "test": "test_a_new_process_announced_while_a_walk_runs_is_still_judged",
    },
    {
        # P2-10: what a walk queues grows the queue past its ceiling.
        "label": "targeting: a walk pushes the queue past its ceiling",
        "file": "beantester/targeting.py",
        "old": "                    pending = frozenset(keep + rest)\n",
        "new": "                    pending = pending\n",
        "test": "test_the_pending_queue_cannot_grow_without_a_bound",
    },
    {
        # P2-10 after review: the cap cuts in set order and drops the owners the
        # walk queued - the ones P2-10 exists to rescue.
        "label": "targeting: a full queue drops the owners the walk queued",
        "file": "beantester/targeting.py",
        "old": "                    pending = frozenset(keep + rest)\n",
        "new": "                    pending = frozenset(list(pending)[:self.MAX_PENDING_PIDS])\n",
        "test": "test_the_pending_queue_cannot_grow_without_a_bound",
    },
    {
        # P2-10(b): a pid the walk judged stays queued and is judged twice.
        "label": "targeting: a pid the walk judged stays queued",
        "file": "beantester/targeting.py",
        "old": "                pending = (self._pending_pids - seen) | unseen\n",
        "new": "                pending = self._pending_pids | unseen\n",
        "test": "test_a_new_process_announced_while_a_walk_runs_is_still_judged",
    },
    {
        # P3-20: a walk that reads self.table at every step mixes two tables.
        "label": "targeting: a walk reads names from a table swapped under it",
        "file": "beantester/targeting.py",
        "old": ("                name = table.name_of(pid)\n"
                "                if self._pid_matches(pid, name, table):\n"
                "                    pids.add(pid)"),
        "new": ("                name = self.table.name_of(pid)\n"
                "                if self._pid_matches(pid, name, table):\n"
                "                    pids.add(pid)"),
        "test": "test_a_table_swap_does_not_wait_for_a_walk_nor_change_the_one_under_way",
    },
    {
        # P3-20: the swap under the walk's lock - STOP waits for a walk in flight.
        "label": "targeting: a table swap waits for the walk under way",
        "file": "beantester/targeting.py",
        "old": ("        on the table it started with.\n"
                "        \"\"\"\n"
                "        self.table = table if table is not None else portmap.default_table()\n"),
        "new": ("        on the table it started with.\n"
                "        \"\"\"\n"
                "        with self._lock:\n"
                "            self.table = table if table is not None else portmap.default_table()\n"),
        "test": "test_a_table_swap_does_not_wait_for_a_walk_nor_change_the_one_under_way",
    },
    {
        # P3-20: targeting stays on the session's stopped socket map after STOP.
        "label": "engine: targeting stays on the stopped socket watcher",
        "file": "beantester/engine.py",
        "old": ("            with self._target_lock:\n"
                "                if self._targeting is not None:\n"
                "                    self._targeting.set_table(self._ports)\n"
                "            watcher.stop()\n"),
        "new": "            watcher.stop()\n",
        "test": "test_between_sessions_the_target_resolves_against_the_poller",
    },
    {
        # P3-19: a failed refresh dates the OLD map as freshly collected.
        "label": "portmap: a failed refresh dates the old map as new",
        "file": "beantester/portmap.py",
        "old": "                self._tried = now                    # do not hammer a broken lookup\n",
        "new": "                self._last = self._tried = now\n",
        "test": "test_a_refresh_that_failed_does_not_make_the_old_map_look_new",
    },
    {
        # P3-19: a failed refresh no longer paces the next attempt.
        "label": "portmap: a failed refresh does not pace the next one",
        "file": "beantester/portmap.py",
        "old": "                self._tried = now                    # do not hammer a broken lookup\n",
        "new": "                pass\n",
        "test": "test_a_refresh_that_failed_does_not_make_the_old_map_look_new",
    },
    {
        # P3-19: refresh() paces by the last success again - a broken lookup is hammered.
        "label": "portmap: refresh paces by the last success",
        "file": "beantester/portmap.py",
        "old": "            if not force and (now - self._tried) < self.interval and self._ports:\n",
        "new": "            if not force and (now - self._last) < self.interval and self._ports:\n",
        "test": "test_a_refresh_that_failed_does_not_make_the_old_map_look_new",
    },
    {
        # P3-19: refresh_if_stale judges by the last success again.
        "label": "portmap: staleness is judged by the last success",
        "file": "beantester/portmap.py",
        "old": "        if (now - self._tried) >= limit or not self._ports:\n",
        "new": "        if (now - self._last) >= limit or not self._ports:\n",
        "test": "test_a_refresh_that_failed_does_not_make_the_old_map_look_new",
    },
    {
        # P2-9: a pid typed as a number follows the NUMBER to its next holder.
        "label": "targeting: a pid typed as a number matches whoever holds it now",
        "file": "beantester/targeting.py",
        "old": "        if created is None or created <= self._set_at + self.LITERAL_PID_SLACK_S:\n",
        "new": "        if True:\n",
        "test": "test_a_pid_typed_as_a_number_is_not_handed_to_its_next_holder",
    },
    {
        # P2-9, D-38 (T) kept after review: the moment is refreshed whenever the same
        # text is applied again - every Apply and every scenario step does that.
        "label": "engine: applying the same target again resets the moment it was set",
        "file": "beantester/engine.py",
        "old": "        # Pointing the RESOLVER at it is set_target's job (one place, one\n",
        "new": ("        current._set_at = time.time()\n"
                "        # Pointing the RESOLVER at it is set_target's job (one place, one\n"),
        "test": "test_applying_the_same_pid_again_does_not_hand_it_to_its_next_holder",
    },
    {
        # P2-9: "cannot tell" read as "somebody else" - the literal pid stops matching.
        "label": "targeting: an unknown start time makes a literal pid a stranger",
        "file": "beantester/targeting.py",
        "old": "        if created is None or created <= self._set_at + self.LITERAL_PID_SLACK_S:\n",
        "new": "        if created is not None and created <= self._set_at + self.LITERAL_PID_SLACK_S:\n",
        "test": "test_what_the_identity_check_leaves_as_it_was",
    },
    {
        # P2-9: judged against "now" - every running process is older than that.
        "label": "targeting: a literal pid is judged against now, not the moment it was set",
        "file": "beantester/targeting.py",
        "old": "        if created is None or created <= self._set_at + self.LITERAL_PID_SLACK_S:\n",
        "new": "        if created is None or created <= time.time() + self.LITERAL_PID_SLACK_S:\n",
        "test": "test_the_moment_a_target_was_set_is_read_once",
    },
    {
        # P2-9: no slack - two clocks read a moment apart disown the real target.
        "label": "targeting: a process started a moment after the target was set is a stranger",
        "file": "beantester/targeting.py",
        "old": "        if created is None or created <= self._set_at + self.LITERAL_PID_SLACK_S:\n",
        "new": "        if created is None or created <= self._set_at:\n",
        "test": "test_the_moment_a_target_was_set_is_read_once",
    },
    {
        # P2-9: `!1234` excludes the NUMBER, so the app's next process under it too.
        "label": "targeting: an exclusion by pid follows the number",
        "file": "beantester/targeting.py",
        "old": "        if self._excluded(own, name):\n",
        "new": "        if self._excluded(pid, name):\n",
        "test": "test_a_pid_excluded_by_number_stays_with_the_process_it_named",
    },
    {
        # P2-9: the next holder's CHILD is matched through its parent's number.
        "label": "targeting: an ancestor typed as a number is matched by the number",
        "file": "beantester/targeting.py",
        "old": "            if self._matches(self._as_named(ancestor_pid, table), ancestor_name):\n",
        "new": "            if self._matches(ancestor_pid, ancestor_name):\n",
        "test": "test_a_pid_typed_as_a_number_is_not_handed_to_its_next_holder",
    },
    {
        # P2-9: a range or a comparison is checked as if it named one process.
        "label": "targeting: every pid is checked as if typed as a number",
        "file": "beantester/targeting.py",
        "old": "        if pid not in self._literal_pids:\n",
        "new": "        if False:\n",
        "test": "test_what_the_identity_check_leaves_as_it_was",
    },
    {
        # P2-9: `!1234` is not known as a literal pid - its "!" hides the number.
        "label": "matchers: an excluded pid is not a literal pid",
        "file": "beantester/matchers.py",
        "old": "        bodies = (_split_negation(term.text)[1] for term in self.terms)\n",
        "new": "        bodies = (term.text for term in self.terms)\n",
        "test": "test_a_pid_written_as_a_bare_number_names_a_process",
    },
    {
        # P2-9: a new process under a dead parent's number is walked as its parent.
        "label": "portmap: the ancestor walk goes on past a younger parent",
        "file": "beantester/portmap.py",
        "old": "                    and parent_born - born >= _SAME_START_S):\n",
        "new": "                    and parent_born - born >= 1e18):\n",
        "test": "test_a_parent_younger_than_its_child_is_not_its_parent",
    },
    {
        # P2-9: "cannot tell" cuts the chain - Chrome's hardened children fall off.
        "label": "portmap: an unknown start time breaks the ancestor walk",
        "file": "beantester/portmap.py",
        "old": ("            if (parent_born is not None and born is not None\n"
                "                    and parent_born - born >= _SAME_START_S):\n"),
        "new": ("            if (parent_born is None or born is None\n"
                "                    or parent_born - born >= _SAME_START_S):\n"),
        "test": "test_a_parent_younger_than_its_child_is_not_its_parent",
    },
    {
        # P2-9: a stamp asked of the OS per ancestor (~5.7 ms a pid where denied).
        "label": "portmap: the ancestor walk asks the OS for every start time",
        "file": "beantester/portmap.py",
        "old": "            parent_born = self._stamp(current)\n",
        "new": "            parent_born = self.created_of(current)\n",
        "test": "test_a_parent_younger_than_its_child_is_not_its_parent",
    },
    {
        # P2-9: the cache's stamp for "no pid" raises - `ancestors(None)` with it.
        "label": "portmap: the cached stamp of no pid raises",
        "file": "beantester/portmap.py",
        "old": ("        \"\"\"The start time the cache holds for ``pid``. Never asks the OS.\"\"\"\n"
                "        if pid is None:\n"
                "            return None\n"),
        "new": "        \"\"\"The start time the cache holds for ``pid``. Never asks the OS.\"\"\"\n",
        "test": "test_a_parent_younger_than_its_child_is_not_its_parent",
    },
    {
        # P2-9: the snapshot writes over a verified entry and strips its stamp again.
        "label": "portmap: a snapshot overwrites a verified entry",
        "file": "beantester/portmap.py",
        "old": ("        if (old is None or old[2] is None or old[0].lower() != name.lower()\n"
                "                or _looks_recycled(created, old[2])):\n"),
        "new": "        if True:\n",
        "test": "test_a_snapshot_does_not_strip_a_verified_start_time",
    },
    {
        # P2-9: a verified entry survives a snapshot naming ANOTHER process.
        "label": "portmap: a snapshot keeps an entry under another name",
        "file": "beantester/portmap.py",
        "old": "        if (old is None or old[2] is None or old[0].lower() != name.lower()\n",
        "new": "        if (old is None or old[2] is None or False\n",
        "test": "test_a_snapshot_still_replaces_an_entry_about_another_process",
    },
    {
        # P2-9: a verified entry survives a start time that proves another process.
        "label": "portmap: a snapshot keeps an entry another start time disproves",
        "file": "beantester/portmap.py",
        "old": "                or _looks_recycled(created, old[2])):\n",
        "new": "                or False):\n",
        "test": "test_a_snapshot_still_replaces_an_entry_about_another_process",
    },
    {
        # P2-9: an entry nobody verified is no longer refreshed by a snapshot.
        "label": "portmap: a snapshot stops refreshing an unverified entry",
        "file": "beantester/portmap.py",
        "old": "        if (old is None or old[2] is None or old[0].lower() != name.lower()\n",
        "new": "        if (old is None or old[0].lower() != name.lower()\n",
        "test": "test_a_snapshot_still_replaces_an_entry_about_another_process",
    },
    {
        # P2-9: "Chrome.exe" and "chrome.exe" taken for two processes.
        "label": "portmap: a snapshot compares process names case by case",
        "file": "beantester/portmap.py",
        "old": "        if (old is None or old[2] is None or old[0].lower() != name.lower()\n",
        "new": "        if (old is None or old[2] is None or old[0] != name\n",
        "test": "test_a_snapshot_does_not_strip_a_verified_start_time",
    },
    {
        # P2-9: the cache is read without verifying - the previous holder's stamp.
        "label": "portmap: created_of answers without verifying the entry",
        "file": "beantester/portmap.py",
        "old": ("        self.info(pid)\n"
                "        created = self._stamp(pid)\n"),
        "new": "        created = self._stamp(pid)\n",
        "test": "test_created_of_answers_for_the_process_holding_the_number_now",
    },
    {
        # P2-9: an entry the snapshot wrote has no stamp, and nobody asks psutil.
        "label": "portmap: created_of gives up on an entry without a stamp",
        "file": "beantester/portmap.py",
        "old": "        return created if created is not None else _psutil_created(pid)\n",
        "new": "        return created\n",
        "test": "test_created_of_answers_for_the_process_holding_the_number_now",
    },
    {
        # P2-9: a real session resolves against the watcher, which keeps it back.
        "label": "socketwatch: the live map keeps start times to itself",
        "file": "beantester/socketwatch.py",
        "old": "        return created_of(pid) if created_of is not None else None\n",
        "new": "        return None\n",
        "test": "test_a_pid_typed_as_a_number_is_checked_through_the_live_map_too",
    },
    {
        # P2-8: one endpoint's CLOSE frees the port of a server still listening.
        "label": "socketwatch: every CLOSE frees the port again",
        "file": "beantester/socketwatch.py",
        "old": "                if self._ports.get(port) == pid and self._closed(port, pid, ev):\n",
        "new": "                if self._ports.get(port) == pid:\n",
        "test": "test_a_port_stays_its_owners_until_the_last_of_its_endpoints_closes",
    },
    {
        # P2-8: a listener opened before the watcher is never learnt from its ACCEPT.
        "label": "socketwatch: an event's parent endpoint is not counted",
        "file": "beantester/socketwatch.py",
        "old": ("        if ev.parent:\n"
                "            endpoints.add(ev.parent)\n"),
        "new": "        pass\n",
        "test": "test_a_port_stays_its_owners_until_the_last_of_its_endpoints_closes",
    },
    {
        # P2-8: a CLOSE ends ANY endpoint, as a count would - UDP's comes twice.
        "label": "socketwatch: endpoints are counted instead of named",
        "file": "beantester/socketwatch.py",
        "old": "        endpoints.discard(ev.endpoint)\n",
        "new": "        endpoints.pop()\n",
        "test": "test_a_port_stays_its_owners_until_the_last_of_its_endpoints_closes",
    },
    {
        # P2-8: the next owner's endpoints go on top of the previous owner's.
        "label": "socketwatch: the next owner inherits the previous owner's endpoints",
        "file": "beantester/socketwatch.py",
        "old": ("        if owner != pid:\n"
                "            endpoints = set()\n"),
        "new": ("        if owner is None:\n"
                "            endpoints = set()\n"),
        "test": "test_endpoints_of_the_previous_owner_do_not_hold_the_port_for_the_next",
    },
    {
        # P2-8: a port known from a snapshot only outlives every CLOSE.
        "label": "socketwatch: a port with no endpoint known outlives its CLOSE",
        "file": "beantester/socketwatch.py",
        "old": ("        if owner != pid:\n"
                "            return True\n"),
        "new": ("        if owner != pid:\n"
                "            return False\n"),
        "test": "test_a_port_with_no_endpoint_known_is_freed_by_any_close_as_before",
    },
    {
        # P2-8: the endpoints of a port the snapshots pruned stay for ever.
        "label": "socketwatch: a pruned port keeps its endpoints",
        "file": "beantester/socketwatch.py",
        "old": "                     if merged.get(port) != entry[0]]\n",
        "new": "                     if False]\n",
        "test": "test_a_port_the_snapshots_prune_forgets_its_endpoints",
    },
    {
        # P2-8 after review: a snapshot's new owner inherits the old owner's endpoints.
        "label": "socketwatch: a port a snapshot hands on keeps the old endpoints",
        "file": "beantester/socketwatch.py",
        "old": "                     if merged.get(port) != entry[0]]\n",
        "new": "                     if port not in merged]\n",
        "test": "test_a_port_a_snapshot_hands_to_another_pid_drops_the_old_endpoints",
    },
    {
        # P2-8 after review: ids whose CLOSE was missed pile up for a whole session.
        "label": "socketwatch: a port's endpoints grow without a bound",
        "file": "beantester/socketwatch.py",
        "old": ("        if len(endpoints) > self.MAX_ENDPOINTS_PER_PORT:\n"
                "            del self._endpoints[port]\n"),
        "new": "        pass\n",
        "test": "test_the_endpoints_kept_for_one_port_are_bounded",
    },
    {
        # P2-8: the empty endpoint set of a freed port stays behind.
        "label": "socketwatch: a freed port leaves its endpoint set behind",
        "file": "beantester/socketwatch.py",
        "old": ("        del self._endpoints[port]\n"
                "        return True\n"),
        "new": "        return True\n",
        "test": "test_a_port_stays_its_owners_until_the_last_of_its_endpoints_closes",
    },
    {
        # P3-21: a reader that dies mid-session does not say so.
        "label": "socketwatch: a reader that dies does not say so",
        "file": "beantester/socketwatch.py",
        "old": "                self._died = True\n",
        "new": "",
        "test": "test_a_dead_socket_reader_hands_targeting_back_to_the_poller",
    },
    {
        # P3-21, D-44: a reader's death is recorded once per PROCESS again.
        "label": "socketwatch: a reader's death is recorded once per process",
        "file": "beantester/socketwatch.py",
        "old": "                crashlog.note(exc, \"socketwatch.loop\")\n",
        "new": "                crashlog.once(\"socketwatch.loop\", exc)\n",
        "test": "test_stop_does_not_record_the_close_induced_error_as_a_crash",
    },
    {
        # P3-21: a dead socket map stays the session's - targeting waits for snapshots.
        "label": "engine: a dead socket watcher stays in the session",
        "file": "beantester/engine.py",
        "old": "                if watcher is not None and watcher.died:\n",
        "new": "                if False:\n",
        "test": "test_a_dead_socket_reader_hands_targeting_back_to_the_poller",
    },
    {
        # P3-21: a watchdog kept past its session retires the next session's watcher.
        "label": "engine: another session's watchdog retires the socket watcher",
        "file": "beantester/engine.py",
        "old": "        if session is not self._session or not self._stop_lock.acquire(blocking=False):\n",
        "new": "        if not self._stop_lock.acquire(blocking=False):\n",
        "test": "test_only_its_own_session_retires_a_dead_watcher_and_never_waits_for_a_stop",
    },
    {
        # P3-21: retiring waits for a STOP that holds the lock while joining this thread.
        "label": "engine: retiring a dead socket watcher waits for STOP",
        "file": "beantester/engine.py",
        "old": "        if session is not self._session or not self._stop_lock.acquire(blocking=False):\n",
        "new": "        if session is not self._session or not self._stop_lock.acquire():\n",
        "test": "test_only_its_own_session_retires_a_dead_watcher_and_never_waits_for_a_stop",
    },
    {
        # P3-21: a watcher that is not the session's any more is stopped anyway.
        "label": "engine: a socket watcher the session replaced is retired",
        "file": "beantester/engine.py",
        "old": "            if self._socketwatch is watcher:\n",
        "new": "            if True:\n",
        "test": "test_only_its_own_session_retires_a_dead_watcher_and_never_waits_for_a_stop",
    },
    {
        # P3-21, D-44: a SOCKET handle that failed alone is recorded once per PROCESS.
        "label": "engine: a socket handle failure is recorded once per process",
        "file": "beantester/engine.py",
        "old": "                crashlog.note(socket_error, \"engine.socketwatch.start\")\n",
        "new": "                crashlog.once(\"engine.socketwatch.start\", socket_error)\n",
        "test": "test_a_socket_handle_failure_is_recorded_in_every_session",
    },
    {
        # P3-22: the old copy of the whole port set per new socket of the target.
        "label": "targeting: every new socket of the target copies the whole port set",
        "file": "beantester/targeting.py",
        "old": "                self._ports.add(port)          # in place: see _ports in __init__\n",
        "new": "                self._ports = self._ports | {port}\n",
        "test": "test_a_new_socket_of_the_target_joins_the_port_set_without_copying_it",
    },
    {
        # P3-22: adoption copies the whole port set.
        "label": "targeting: adoption copies the whole port set",
        "file": "beantester/targeting.py",
        "old": "                self._ports.update(ports)\n",
        "new": "                self._ports = self._ports | ports\n",
        "test": "test_a_new_socket_of_the_target_joins_the_port_set_without_copying_it",
    },
    {
        # P3-22: iterating the target walks the set the watcher adds to.
        "label": "targeting: iterating the target walks the live port set",
        "file": "beantester/targeting.py",
        "old": "        return iter(self.ports())\n",
        "new": "        return iter(self._ports)\n",
        "test": "test_iterating_the_target_survives_a_socket_announced_meanwhile",
    },
    {
        # P3-22: a rebuild empties and refills the set a packet may be holding.
        "label": "targeting: a rebuild refills the port set in place",
        "file": "beantester/targeting.py",
        "old": "                self._ports = resolved\n",
        "new": "                self._ports.clear()\n                self._ports.update(resolved)\n",
        "test": "test_a_rebuild_never_changes_the_set_a_packet_may_be_holding",
    },
    {
        # D-46, kept after review: the old return value, but now the LIVE set.
        "label": "targeting: a rebuild hands out the live port set",
        "file": "beantester/targeting.py",
        "old": "            if pending and wake is not None:\n                wake()\n",
        "new": ("            if pending and wake is not None:\n                wake()\n"
                "            return self._ports\n"),
        "test": "test_what_a_rebuild_returns_cannot_change_the_target",
    },
    {
        # P2-11: a retry asks for exactly the size the table reported.
        "label": "portmap: a retry asks for exactly the size the table reported",
        "file": "beantester/portmap.py",
        "old": "            size.value = self._roomy(size.value, row_type)\n",
        "new": "",
        "test": "test_a_table_that_grows_while_it_is_read_is_still_read_in_one_walk",
    },
    {
        # P2-11: the first attempt asks for exactly the size remembered.
        "label": "portmap: the first attempt asks for exactly the size remembered",
        "file": "beantester/portmap.py",
        "old": "        size = wintypes.DWORD(self._roomy(need, row_type) if need else 8192)\n",
        "new": "        size = wintypes.DWORD(need or 8192)\n",
        "test": "test_a_table_that_grows_while_it_is_read_is_still_read_in_one_walk",
    },
    {
        # P2-11: the buffer's size is remembered, so the room compounds.
        "label": "portmap: the buffer's size is remembered, room included",
        "file": "beantester/portmap.py",
        "old": "        self._sizes[(proto, family)] = header + count * ctypes.sizeof(row_type)\n",
        "new": "        self._sizes[(proto, family)] = size.value\n",
        "test": "test_the_size_remembered_is_what_the_table_needed_not_the_buffer",
    },
    {
        # P2-11, D-48: a failing socket table is recorded once per PROCESS.
        "label": "portmap: a failing socket table is recorded once per process",
        "file": "beantester/portmap.py",
        "old": "            crashlog.note(error, \"portmap.native.\" + \".\".join(failed))\n",
        "new": "            crashlog.once(\"portmap.native.\" + \".\".join(failed), error)\n",
        "test": "test_a_table_that_fails_is_recorded_every_time_and_so_is_none_answering",
    },
    {
        # P2-11, D-48: no table answering at all is not recorded.
        "label": "portmap: no socket table answering is not recorded",
        "file": "beantester/portmap.py",
        "old": "        if failed:\n            error = RuntimeError(\n",
        "new": "        if 0 < len(failed) < 4:\n            error = RuntimeError(\n",
        "test": "test_a_table_that_fails_is_recorded_every_time_and_so_is_none_answering",
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
    # 🔴 These three cannot become MUTATIONS entries, and the reason is a property
    # of what they guard rather than laziness. Every patch to `_nesting_depth`
    # moves the measurement of the whole package, so it reddens the two ratchet
    # tests pinned to that measurement as well as the metric test being aimed at -
    # measured on 2026-08-21: making an `elif` count as a level again turned three
    # tests red at once, and rule 3 of this registry is that an entry names ONE.
    # An entry that fells a crowd proves nothing about any single guard in it.
    #
    # All three were red for real during the session that wrote them, which is
    # better evidence than usual for this list: the metric was WRONG when the tests
    # went in - it walked an `if` body without adding the level that body sits at -
    # and `test_the_depth_metric_still_counts_real_nesting` is what found it, before
    # any constant had been filled in.
    "test_an_elif_chain_is_one_level_not_one_per_branch":
        "2026-08-21, made elif count per branch again, saw red, restored, saw green",
    "test_an_except_handler_is_not_a_level_of_its_own":
        "2026-08-21, same patch run: the handler counted as its own level",
    "test_the_depth_metric_still_counts_real_nesting":
        "2026-08-21, it failed on the first draft of the metric (four nested blocks "
        "measured three) and passed once the missing level was added",
}

# No mutation at all. Naming them is the point: an unproven guard and a guard nobody
# looked at must not read the same. This list is allowed to grow only when a guard
# is added without its proof - and every entry is a debt.
# 🔴 These three lists are keyed by TEST NAME, so a property with no test of its
# own has no slot here and must not be given one by borrowing a neighbour's name -
# that is what "filed under exactly one state" catches. One such property exists as
# of 2026-09-03: `i18n.load_languages` publishes `_language_names` before
# `_translations` because the second is what every "loaded yet?" check reads, and
# the window is two adjacent stores, so a guard would need a reader racing a loader
# in a loop - slow, flaky, and green most of the time for the wrong reason. It is
# recorded where it can be read next to the code, in a comment at the assignment.
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
