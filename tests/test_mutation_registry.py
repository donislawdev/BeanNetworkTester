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
    "test_shortcut_buttons_advertise_their_key": "2026-07-21, dropping shortcut= from Save/Load",
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
        text = open(path, encoding="utf-8").read()
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
